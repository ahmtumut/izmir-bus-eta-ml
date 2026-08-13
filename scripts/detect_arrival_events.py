"""
Faz 2 madde 6 (v3 - performans duzeltmesi): "Durağa ulasti" olayinin V1 tanimi.

v2'DEKI PERFORMANS HATASI DUZELTILDI: v2, her durak adayi icin aracin TUM
gozlem dizisine (120-240 nokta) tek tek ST_Distance sorgusu atiyordu - bu,
arac basina onbinlerce DB round-trip'e yol aciyordu (pratikte "donmus"
gorunuyordu). v3'te:

1. ONCE ucuz (Python-ici, DB'ye gitmeyen) route-progress farkiyla
   yaklasma/en-yakin/gecis adaylarini tespit et (v1'deki gibi hizli).
2. SADECE gercekten aday olan (yakinlik esigini gecen) durak-arac
   eslesmeleri icin, SADECE kucuk trend penceresindeki birkac nokta icin
   TEK BIR toplu sorguyla gercek ST_Distance hesapla.

Kullanim:
    python scripts/detect_arrival_events.py --run-id 3
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

PROXIMITY_M = 50
COLLECTOR_INTERVAL_SECONDS = 60
MIN_TREND_POINTS = 3
COARSE_APPROACH_WINDOW_M = PROXIMITY_M * 4


def fetch_target_stops(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rss.route_id, rss.stop_id, s.stop_id AS stop_business_id,
                   s.stop_name, rss.distance_along_route_m
            FROM route_stop_sequence rss
            JOIN stops s ON s.id = rss.stop_id
            """
        )
        return cur.fetchall()


def fetch_matched_observations(conn, run_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vo.id, vo.vehicle_id, vo.line_no, vo.route_id, r.direction,
                   vo.observed_at, vo.distance_along_route_m, vo.map_match_quality,
                   vo.geom
            FROM vehicle_observations vo
            JOIN raw_snapshots rs ON vo.raw_snapshot_id = rs.id
            JOIN routes r ON r.id = vo.route_id
            WHERE rs.ingestion_run_id = %s
              AND vo.route_id IS NOT NULL
              AND vo.map_match_quality IN ('GOOD', 'DEGRADED')
              AND vo.position_quality != 'STALE_POSITION'
            ORDER BY vo.vehicle_id, vo.route_id, vo.observed_at
            """,
            (run_id,),
        )
        rows = cur.fetchall()

    series = defaultdict(list)
    for (obs_id, vehicle_id, line_no, route_id, direction, observed_at,
         dist_along, quality, geom) in rows:
        series[(vehicle_id, route_id)].append({
            "id": obs_id, "line_no": line_no, "direction": direction,
            "observed_at": observed_at, "dist_along": dist_along,
            "quality": quality, "geom": geom,
        })
    return series


def fetch_real_distances_batch(conn, obs_geoms, stop_pk):
    """Verilen gozlem geometrileri icin TEK bir sorguda (UNION ALL ile,
    sira korunarak) gercek ST_Distance hesaplar. Not: PostGIS geography
    degerlerini bir Python listesi olarak ::geography[] array parametresine
    gecirmek psycopg'de serialization sorunu cikarabiliyor (array icindeki
    hex/WKB temsili virgul iceriyor, adapter bunu yanlis parcaliyor) - bu
    yuzden array yerine UNION ALL ile ayri ayri baglanan parametreler
    kullaniliyor. Pencere kucuk oldugu icin (genelde <20 nokta) performans
    sorunu yaratmiyor."""
    if not obs_geoms:
        return []

    parts = []
    params = []
    for i, g in enumerate(obs_geoms):
        parts.append(f"SELECT {i} AS ord, ST_Distance(%s::geography, s.geom) AS dist "
                      f"FROM stops s WHERE s.id = %s")
        params.extend([g, stop_pk])

    query = " UNION ALL ".join(parts) + " ORDER BY ord"
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [row[1] for row in rows]


def find_candidate_window(obs_list, stop_dist_along):
    approach_idx = None
    closest_idx = None
    closest_progress_gap = None
    passed_idx = None

    for i, obs in enumerate(obs_list):
        if obs["dist_along"] is None:
            continue
        progress_gap = abs(obs["dist_along"] - stop_dist_along)

        if approach_idx is None and progress_gap <= COARSE_APPROACH_WINDOW_M:
            approach_idx = i

        if approach_idx is not None and passed_idx is None:
            if closest_progress_gap is None or progress_gap < closest_progress_gap:
                closest_progress_gap = progress_gap
                closest_idx = i

            if obs["dist_along"] > stop_dist_along + 5:
                passed_idx = i

        if passed_idx is not None:
            break

    return approach_idx, closest_idx, passed_idx


def detect_arrivals_for_vehicle(conn, obs_list, target_stops_for_route):
    events = []

    for stop_pk, stop_business_id, stop_name, stop_dist_along in target_stops_for_route:
        approach_idx, closest_idx, passed_idx = find_candidate_window(obs_list, stop_dist_along)

        if not (approach_idx is not None and closest_idx is not None and passed_idx is not None):
            continue

        window_obs = obs_list[approach_idx:passed_idx + 1]
        window_geoms = [o["geom"] for o in window_obs]
        real_distances = fetch_real_distances_batch(conn, window_geoms, stop_pk)

        local_closest_pos = min(range(len(real_distances)), key=lambda i: real_distances[i])
        closest_dist = real_distances[local_closest_pos]
        closest_idx_real = approach_idx + local_closest_pos

        if closest_dist > PROXIMITY_M:
            continue

        trend_window = real_distances[:local_closest_pos + 1]
        quality_flags = []

        if len(trend_window) >= MIN_TREND_POINTS:
            diffs = [trend_window[i + 1] - trend_window[i] for i in range(len(trend_window) - 1)]
            increasing_steps = sum(1 for d in diffs if d > 5)
            if increasing_steps > len(diffs) // 2:
                quality_flags.append("APPROACH_TREND_NOT_CONFIRMED")
        else:
            quality_flags.append("INSUFFICIENT_TREND_POINTS")

        events.append({
            "stop_pk": stop_pk,
            "stop_business_id": stop_business_id,
            "stop_name": stop_name,
            "line_no": obs_list[0]["line_no"],
            "direction": obs_list[0]["direction"],
            "approach_started_at": obs_list[approach_idx]["observed_at"],
            "arrival_observed_at": obs_list[closest_idx_real]["observed_at"],
            "passed_at": obs_list[passed_idx]["observed_at"],
            "minimum_distance_m": closest_dist,
            "triggering_observation_id": obs_list[closest_idx_real]["id"],
            "quality_flags": quality_flags,
        })

    return events


def upsert_arrival_event(cur, vehicle_id, ev, confidence, validation_source):
    cur.execute(
        """
        INSERT INTO arrival_events
            (vehicle_id, line_no, direction, stop_id, approach_started_at,
             arrival_observed_at, passed_at, minimum_distance_m,
             arrival_confidence, validation_source, quality_flags,
             triggering_observation_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (triggering_observation_id, stop_id) DO NOTHING
        RETURNING id
        """,
        (
            vehicle_id, ev["line_no"], ev["direction"], ev["stop_pk"],
            ev["approach_started_at"], ev["arrival_observed_at"], ev["passed_at"],
            ev["minimum_distance_m"], confidence, validation_source,
            ev["quality_flags"], ev["triggering_observation_id"],
        ),
    )
    row = cur.fetchone()
    if row:
        return row[0], True

    cur.execute(
        "SELECT id FROM arrival_events WHERE triggering_observation_id = %s AND stop_id = %s",
        (ev["triggering_observation_id"], ev["stop_pk"]),
    )
    return cur.fetchone()[0], False


def run_detection(conn, run_id):
    target_stops_raw = fetch_target_stops(conn)
    stops_by_route = defaultdict(list)
    for route_id, stop_pk, stop_business_id, stop_name, dist_along in target_stops_raw:
        stops_by_route[route_id].append((stop_pk, stop_business_id, stop_name, dist_along))

    obs_series = fetch_matched_observations(conn, run_id)
    print(f"{len(obs_series)} arac/route kombinasyonu bulundu.")

    total_events = 0
    total_reused = 0
    with conn.cursor() as cur:
        for (vehicle_id, route_id), obs_list in obs_series.items():
            target_stops = stops_by_route.get(route_id, [])
            if not target_stops:
                continue

            events = detect_arrivals_for_vehicle(conn, obs_list, target_stops)

            for ev in events:
                cur.execute(
                    """
                    SELECT remaining_stop_count, observed_at
                    FROM supporting_api_observations
                    WHERE vehicle_id = %s AND line_no = %s AND target_stop_id = %s
                      AND observed_at BETWEEN %s AND %s
                    ORDER BY observed_at
                    """,
                    (vehicle_id, ev["line_no"], ev["stop_business_id"],
                     ev["approach_started_at"], ev["passed_at"]),
                )
                support_rows = cur.fetchall()

                if len(support_rows) >= 2 and support_rows[0][0] > support_rows[-1][0]:
                    confidence = "HIGH"
                    validation_source = "gps_plus_support_api"
                elif len(support_rows) >= 1:
                    confidence = "MEDIUM"
                    validation_source = "gps_only"
                    ev["quality_flags"].append("SUPPORT_API_INCONCLUSIVE")
                else:
                    confidence = "MEDIUM"
                    validation_source = "gps_only"
                    ev["quality_flags"].append("NO_SUPPORT_API_DATA")

                if "APPROACH_TREND_NOT_CONFIRMED" in ev["quality_flags"] and confidence == "HIGH":
                    confidence = "MEDIUM"

                event_id, is_new = upsert_arrival_event(cur, vehicle_id, ev, confidence, validation_source)

                if is_new:
                    total_events += 1
                    print(f"  Arrival event #{event_id}: arac {vehicle_id}, hat {ev['line_no']}, "
                          f"durak '{ev['stop_name']}', min_dist={ev['minimum_distance_m']:.1f}m, "
                          f"confidence={confidence} ({validation_source}), flags={ev['quality_flags']}")
                else:
                    total_reused += 1

    print(f"\nToplam {total_events} YENI arrival event uretildi, {total_reused} zaten vardi (idempotent).")
    print(f"Not: arrival_observed_at, collector'in kendi gozlem zamanidir; "
          f"API'de source timestamp olmadigi icin +-{COLLECTOR_INTERVAL_SECONDS}sn "
          f"belirsizlik payi vardir.")
    return total_events


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    conn = db_storage.get_connection()
    run_detection(conn, args.run_id)
    conn.close()
