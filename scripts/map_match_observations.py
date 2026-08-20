"""
Faz 2 madde 4 (v2 - Supervisor duzeltmesi): Arac GPS konumlarini ilgili
hat+yon LineString'ine map-matching yapar.

DEGISIKLIK (Faz 2 kapanis duzeltmesi): Onceki versiyon her iki yonu de
deneyip en yakinini SESSIZCE seciyordu. Artik:
1. Kaynak API'den gelen source_direction VARSA, ONCELIKLE o yonun
   route'una map-match yapilir.
2. Geometri, source_direction'in route'undan ONEMLI OLCUDE uzaksa VE
   diger yonun route'u gercekten daha yakinsa, bu durum SESSIZCE
   diger yone cevrilmez - route_id yine de gercekte en yakin olan
   geometriye atanir (cunku fiziksel gercek budur) AMA
   DIRECTION_ROUTE_MISMATCH flag'i quality_flags'e eklenir ve
   data_quality_events'e loglanir.
3. source_direction yoksa (normalize edilemedi), eski davranisa
   (iki yonu de dene, en yakinini sec) donulur, SOURCE_DIRECTION_UNKNOWN
   flag'i eklenir.

Kullanim:
    python scripts/map_match_observations.py --run-id 3
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

GOOD_THRESHOLD_M = 30
DEGRADED_THRESHOLD_M = 100

MISMATCH_MARGIN_M = 20


def quality_from_distance(distance_m: float) -> str:
    if distance_m <= GOOD_THRESHOLD_M:
        return "GOOD"
    if distance_m <= DEGRADED_THRESHOLD_M:
        return "DEGRADED"
    return "REJECTED"


def fetch_observations(conn, run_id, only_unmatched=False):
    """only_unmatched=True: sadece map_match_quality IS NULL olan satirlar -
    collector'in kendi dongusune gomulu periyodik cagrilar icin (Faz 4 canli
    mod), her seferinde TUM run'i yeniden islemek yerine sadece o cycle'in
    yeni satirlarini isler. CLI kullanimindaki varsayilan (False, tam
    reprocessing) davranisi degismedi."""
    query = """
        SELECT vo.id, vo.line_no, vo.geom, vo.raw_lat, vo.raw_lon, vo.source_direction
        FROM vehicle_observations vo
        JOIN raw_snapshots rs ON vo.raw_snapshot_id = rs.id
        WHERE rs.ingestion_run_id = %s
    """
    if only_unmatched:
        query += " AND vo.map_match_quality IS NULL"
    query += " ORDER BY vo.id"

    with conn.cursor() as cur:
        cur.execute(query, (run_id,))
        return cur.fetchall()


def fetch_routes_for_line(conn, line_no):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, direction, total_length_m FROM routes WHERE line_no = %s",
            (line_no,),
        )
        return cur.fetchall()


def project_onto_route(conn, route_id, geom_wkb, total_length_m):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ST_Distance(shape_geom, %s::geography) AS dist_m,
                ST_LineLocatePoint(shape_geom::geometry, %s::geometry) AS fraction
            FROM routes WHERE id = %s
            """,
            (geom_wkb, geom_wkb, route_id),
        )
        dist_m, fraction = cur.fetchone()
    distance_along_m = fraction * total_length_m if total_length_m else None
    return dist_m, fraction, distance_along_m


def map_match_one(conn, geom_wkb, candidate_routes, source_direction):
    """candidate_routes: [(route_id, direction, total_length_m), ...]
    Doner: (route_id, dist_m, fraction, distance_along_m, extra_flags: list)"""
    flags = []

    results = {}
    for route_id, direction, total_length_m in candidate_routes:
        dist_m, fraction, distance_along_m = project_onto_route(
            conn, route_id, geom_wkb, total_length_m
        )
        results[direction] = (route_id, dist_m, fraction, distance_along_m)

    best_direction = min(results, key=lambda d: results[d][1])
    best = results[best_direction]

    if source_direction is None:
        flags.append("SOURCE_DIRECTION_UNKNOWN")
        return (*best, flags)

    if source_direction not in results:
        flags.append("SOURCE_DIRECTION_ROUTE_MISSING")
        return (*best, flags)

    source_result = results[source_direction]

    if best_direction != source_direction and \
            (source_result[1] - best[1]) > MISMATCH_MARGIN_M:
        flags.append("DIRECTION_ROUTE_MISMATCH")
        return (*best, flags)

    return (*source_result, flags)


def run_map_matching(conn, run_id, only_unmatched=False):
    observations = fetch_observations(conn, run_id, only_unmatched=only_unmatched)
    print(f"{len(observations)} gozlem bulundu (run_id={run_id}).")

    route_cache = {}
    counts = {"GOOD": 0, "DEGRADED": 0, "REJECTED": 0}
    mismatch_count = 0
    unknown_direction_count = 0
    skipped_null_island = 0
    updated = 0

    with conn.cursor() as cur:
        for obs_id, line_no, geom, raw_lat, raw_lon, source_direction in observations:
            if raw_lat == 0 and raw_lon == 0:
                skipped_null_island += 1
                db_storage.log_quality_event(
                    conn, stage="map_matching", severity="WARNING",
                    description=f"Gozlem {obs_id} (hat {line_no}): (0,0) null island "
                                  "koordinati, map-matching'den haric tutuldu.",
                    ingestion_run_id=run_id, line_no=line_no,
                    context={"observation_id": obs_id},
                )
                continue

            if line_no not in route_cache:
                route_cache[line_no] = fetch_routes_for_line(conn, line_no)
            candidates = route_cache[line_no]

            if not candidates:
                continue

            route_id, dist_m, fraction, distance_along_m, extra_flags = map_match_one(
                conn, geom, candidates, source_direction
            )
            quality = quality_from_distance(dist_m)
            counts[quality] += 1

            cur.execute(
                """
                UPDATE vehicle_observations
                SET route_id = %s, distance_to_route_m = %s,
                    progress_along_route = %s, distance_along_route_m = %s,
                    map_match_quality = %s
                WHERE id = %s
                """,
                (route_id, dist_m, fraction, distance_along_m, quality, obs_id),
            )
            updated += 1

            for flag in extra_flags:
                db_storage.add_observation_quality_flag(conn, obs_id, flag)
                if flag == "DIRECTION_ROUTE_MISMATCH":
                    mismatch_count += 1
                    db_storage.log_quality_event(
                        conn, stage="map_matching", severity="WARNING",
                        description=(f"Gozlem {obs_id} (hat {line_no}): kaynak yon "
                                      f"(source_direction={source_direction}) ile en yakin "
                                      f"geometri celisiyor. dist={dist_m:.1f}m"),
                        ingestion_run_id=run_id, line_no=line_no,
                        context={"observation_id": obs_id, "source_direction": source_direction,
                                 "matched_distance_m": dist_m},
                    )
                elif flag == "SOURCE_DIRECTION_UNKNOWN":
                    unknown_direction_count += 1

            if quality == "REJECTED":
                db_storage.log_quality_event(
                    conn, stage="map_matching", severity="WARNING",
                    description=(f"Gozlem {obs_id} (hat {line_no}): en yakin route'a "
                                  f"{dist_m:.1f}m mesafede - REJECTED, sessizce duzeltilmedi."),
                    ingestion_run_id=run_id, line_no=line_no,
                    context={"observation_id": obs_id, "distance_m": dist_m},
                )

    print(f"\n{updated} gozlem map-match edildi. {skipped_null_island} null-island gozlem atlandi.")
    print(f"GOOD: {counts['GOOD']}, DEGRADED: {counts['DEGRADED']}, REJECTED: {counts['REJECTED']}")
    print(f"DIRECTION_ROUTE_MISMATCH: {mismatch_count}, SOURCE_DIRECTION_UNKNOWN: {unknown_direction_count}")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    conn = db_storage.get_connection()
    run_map_matching(conn, args.run_id)
    conn.close()
