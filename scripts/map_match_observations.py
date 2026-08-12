"""
Faz 2 madde 4: Arac GPS konumlarini ilgili hat+yon LineString'ine
map-matching yapar.

vehicle_observations.route_id NULL olan (henuz eslesmemis) satirlari,
hem yon 0 hem yon 1 route'una projekte eder, hangisi daha yakinsa onu
secer. Sonuclari distance_to_route_m, progress_along_route,
distance_along_route_m, map_match_quality alanlarina yazar.

Guzergahtan anormal uzak kayitlar SESSIZCE duzeltilmez; REJECTED olarak
isaretlenir (route_id yine de en yakin route'a set edilir, ama quality
REJECTED oldugu icin downstream kullanimda filtrelenmelidir).

Esikler (deneysel, ihtiyaca gore ayarlanabilir):
    GOOD     : distance_to_route_m <= 30
    DEGRADED : 30 < distance_to_route_m <= 100
    REJECTED : distance_to_route_m > 100

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


def quality_from_distance(distance_m: float) -> str:
    if distance_m <= GOOD_THRESHOLD_M:
        return "GOOD"
    if distance_m <= DEGRADED_THRESHOLD_M:
        return "DEGRADED"
    return "REJECTED"


def fetch_observations(conn, run_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vo.id, vo.line_no, vo.geom, vo.raw_lat, vo.raw_lon
            FROM vehicle_observations vo
            JOIN raw_snapshots rs ON vo.raw_snapshot_id = rs.id
            WHERE rs.ingestion_run_id = %s
            ORDER BY vo.id
            """,
            (run_id,),
        )
        return cur.fetchall()


def fetch_routes_for_line(conn, line_no):
    """line_no icin (route_id, direction, total_length_m) listesini doner."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, direction, total_length_m FROM routes WHERE line_no = %s",
            (line_no,),
        )
        return cur.fetchall()


def map_match_one(conn, obs_id, geom_wkb, candidate_routes):
    """candidate_routes: [(route_id, direction, total_length_m), ...]
    Her ikisine de (yon 0 ve yon 1) projekte eder, en yakinini secer."""
    best = None  # (route_id, distance_m, fraction, distance_along_m)

    with conn.cursor() as cur:
        for route_id, direction, total_length_m in candidate_routes:
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

            if best is None or dist_m < best[1]:
                best = (route_id, dist_m, fraction, distance_along_m)

    return best


def run_map_matching(conn, run_id):
    observations = fetch_observations(conn, run_id)
    print(f"{len(observations)} gozlem bulundu (run_id={run_id}).")

    route_cache = {}
    counts = {"GOOD": 0, "DEGRADED": 0, "REJECTED": 0}
    skipped_null_island = 0
    updated = 0

    with conn.cursor() as cur:
        for obs_id, line_no, geom, raw_lat, raw_lon in observations:
            if raw_lat == 0 and raw_lon == 0:
                # Null island sentinel degeri - map-matching anlamsiz, atla.
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
                # Bu hat icin routes tablosunda kayit yok (pilot disi hat vb.)
                continue

            route_id, dist_m, fraction, distance_along_m = map_match_one(
                conn, obs_id, geom, candidates
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
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    conn = db_storage.get_connection()
    run_map_matching(conn, args.run_id)
    conn.close()
