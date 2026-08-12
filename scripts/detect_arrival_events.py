"""
Faz 2 madde 6: "Durağa ulasti" olayinin V1 tanimi.

Sadece "50m icine girdi" YETERLI DEGIL. Su dorduncun birlikte
saglanmasi gerekiyor:
  1. Arac dogru hat/yonde (map_match_quality GOOD/DEGRADED, ayni route_id)
  2. Duraga YAKLASIYOR (distance_along_route_m, durak'in
     distance_along_route_m'ine dogru artiyor)
  3. Belirlenen YAKINLIK ALANINA giriyor (fiziksel mesafe <= PROXIMITY_M)
  4. Yakinliktan SONRA durak sonrasina ilerliyor (distance_along_route_m,
     durak degerini gecti)

API'de source timestamp olmadigi icin arrival_observed_at bizim
gozlem zamanimizdir; bu da +-collector_interval kadar belirsizlik
getirir (60 saniyelik cycle -> +-60sn hata payi olarak dokumante
ediliyor).

Kullanim:
    python scripts/detect_arrival_events.py --run-id 3
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

PROXIMITY_M = 50  # yakinlik alani esigi
COLLECTOR_INTERVAL_SECONDS = 60  # arrival_observed_at belirsizligi (+-)


def fetch_target_stops(conn):
    """route_stop_sequence'teki (route_id, stop_pk, distance_along_route_m) uclulerini doner."""
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
    """map-match edilmis (route_id dolu) gozlemleri arac+route bazinda zaman sirali doner."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vo.id, vo.vehicle_id, vo.line_no, vo.route_id, r.direction,
                   vo.observed_at, vo.distance_along_route_m, vo.map_match_quality
            FROM vehicle_observations vo
            JOIN raw_snapshots rs ON vo.raw_snapshot_id = rs.id
            JOIN routes r ON r.id = vo.route_id
            WHERE rs.ingestion_run_id = %s
              AND vo.route_id IS NOT NULL
              AND vo.map_match_quality IN ('GOOD', 'DEGRADED')
            ORDER BY vo.vehicle_id, vo.route_id, vo.observed_at
            """,
            (run_id,),
        )
        rows = cur.fetchall()

    series = defaultdict(list)
    for obs_id, vehicle_id, line_no, route_id, direction, observed_at, dist_along, quality in rows:
        series[(vehicle_id, route_id)].append({
            "id": obs_id, "line_no": line_no, "direction": direction,
            "observed_at": observed_at, "dist_along": dist_along, "quality": quality,
        })
    return series


def detect_arrivals_for_vehicle(obs_list, target_stops_for_route):
    """
    obs_list: tek bir (vehicle_id, route_id) icin zaman sirali gozlemler.
    target_stops_for_route: [(stop_pk, stop_business_id, stop_name, stop_dist_along), ...]
    """
    events = []

    for stop_pk, stop_business_id, stop_name, stop_dist_along in target_stops_for_route:
        # Bu durak icin yaklasma/yakinlik/gecis dongusunu ara.
        approach_idx = None
        closest_idx = None
        closest_dist = None
        passed_idx = None

        for i, obs in enumerate(obs_list):
            if obs["dist_along"] is None:
                continue
            physical_gap = abs(obs["dist_along"] - stop_dist_along)

            if approach_idx is None and physical_gap <= PROXIMITY_M * 4:
                # yaklasma basladi (durakdan 200m'e kadar bir yerde takip baslat)
                approach_idx = i

            if approach_idx is not None and passed_idx is None:
                if closest_dist is None or physical_gap < closest_dist:
                    closest_dist = physical_gap
                    closest_idx = i

                # durak sonrasina gecti mi? (guzergah ilerlemesi durak degerini asti)
                if obs["dist_along"] > stop_dist_along + 5:  # 5m tolerans
                    passed_idx = i

            if passed_idx is not None:
                break

        if approach_idx is not None and closest_idx is not None and passed_idx is not None \
                and closest_dist is not None and closest_dist <= PROXIMITY_M:
            events.append({
                "stop_pk": stop_pk,
                "stop_business_id": stop_business_id,
                "stop_name": stop_name,
                "line_no": obs_list[0]["line_no"],
                "direction": obs_list[0]["direction"],
                "approach_started_at": obs_list[approach_idx]["observed_at"],
                "arrival_observed_at": obs_list[closest_idx]["observed_at"],
                "passed_at": obs_list[passed_idx]["observed_at"],
                "minimum_distance_m": closest_dist,
                "triggering_observation_id": obs_list[closest_idx]["id"],
            })

    return events


def run_detection(conn, run_id):
    target_stops_raw = fetch_target_stops(conn)
    stops_by_route = defaultdict(list)
    for route_id, stop_pk, stop_business_id, stop_name, dist_along in target_stops_raw:
        stops_by_route[route_id].append((stop_pk, stop_business_id, stop_name, dist_along))

    obs_series = fetch_matched_observations(conn, run_id)

    total_events = 0
    with conn.cursor() as cur:
        for (vehicle_id, route_id), obs_list in obs_series.items():
            target_stops = stops_by_route.get(route_id, [])
            if not target_stops:
                continue

            events = detect_arrivals_for_vehicle(obs_list, target_stops)

            for ev in events:
                # Support API ile capraz dogrulama: SADECE ayni hedef durak
                # (target_stop_id) icin, ayni arac, zaman araliginda
                # KalanDurakSayisi azaliyor mu? (Onceki surumde stop_id
                # kontrolu eksikti - farkli bir duraga yaklasirkenki
                # veri yanlislikla kanit olarak kullanilabiliyordu.)
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

                quality_flags = []
                if len(support_rows) >= 2 and support_rows[0][0] > support_rows[-1][0]:
                    confidence = "HIGH"
                    validation_source = "gps_plus_support_api"
                elif len(support_rows) >= 1:
                    confidence = "MEDIUM"
                    validation_source = "gps_only"
                    quality_flags.append("SUPPORT_API_INCONCLUSIVE")
                else:
                    confidence = "MEDIUM"
                    validation_source = "gps_only"
                    quality_flags.append("NO_SUPPORT_API_DATA")

                cur.execute(
                    """
                    INSERT INTO arrival_events
                        (vehicle_id, line_no, direction, stop_id, approach_started_at,
                         arrival_observed_at, passed_at, minimum_distance_m,
                         arrival_confidence, validation_source, quality_flags,
                         triggering_observation_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        vehicle_id, ev["line_no"], ev["direction"], ev["stop_pk"],
                        ev["approach_started_at"], ev["arrival_observed_at"], ev["passed_at"],
                        ev["minimum_distance_m"], confidence, validation_source,
                        quality_flags, ev["triggering_observation_id"],
                    ),
                )
                event_id = cur.fetchone()[0]
                total_events += 1

                print(f"  Arrival event #{event_id}: arac {vehicle_id}, hat {ev['line_no']}, "
                      f"durak '{ev['stop_name']}', min_dist={ev['minimum_distance_m']:.1f}m, "
                      f"confidence={confidence} ({validation_source})")

    print(f"\nToplam {total_events} arrival event uretildi.")
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
