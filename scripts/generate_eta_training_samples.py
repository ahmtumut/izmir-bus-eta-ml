"""
Faz 2 madde 7 (v2 - Supervisor duzeltmesi): ETA ground-truth training
orneklerini uretir.

DEGISIKLIKLER (Faz 2 kapanis duzeltmesi):
1. T0 adaylari artik SADECE ayni vehicle_id + line_no + direction + route_id
   uzerinde araniyor (once sadece vehicle_id+line_no+zaman penceresi
   kullaniliyordu - bu, farkli yon/route'taki gozlemlerin karismasina
   izin verebiliyordu).
2. Sadece map_match_quality GOOD/DEGRADED olan gozlemler T0 adayi olabilir;
   REJECTED kesinlikle training'e girmiyor.
3. position_quality = STALE_POSITION olan gozlemler T0 adayi olamaz.
4. recent_speed_mps hesabinda da AYNI filtreler uygulaniyor (route_id,
   direction, GOOD/DEGRADED, stale olmayan) - baska route/yon/REJECTED
   bir nokta hiz hesabina karismiyor.
5. Script idempotent: ayni (source_observation_id, arrival_event_id)
   ikilisi icin ikinci kez calistirildiginda yeni satir uretmiyor.

Kullanim:
    python scripts/generate_eta_training_samples.py --run-id 3
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

CONFIDENCE_TO_LABEL_QUALITY = {
    "HIGH": "GOLD",
    "MEDIUM": "SILVER",
    "LOW": "REJECTED",
}

VALID_MATCH_QUALITIES = ("GOOD", "DEGRADED")


def fetch_arrival_events_for_run(conn, run_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ae.id, ae.vehicle_id, ae.line_no, ae.direction,
                   ae.stop_id, ae.approach_started_at, ae.arrival_observed_at,
                   ae.arrival_confidence, vo.route_id
            FROM arrival_events ae
            JOIN vehicle_observations vo ON vo.id = ae.triggering_observation_id
            JOIN raw_snapshots rs ON rs.id = vo.raw_snapshot_id
            WHERE rs.ingestion_run_id = %s
            """,
            (run_id,),
        )
        return cur.fetchall()


def fetch_t0_candidates(conn, vehicle_id, line_no, direction, route_id,
                         approach_started_at, arrival_observed_at):
    """T0 adaylari: AYNI vehicle_id + line_no + direction + route_id,
    SADECE GOOD/DEGRADED map-match kalitesi, STALE_POSITION HARIC,
    T1'den (arrival_observed_at) ONCE."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vo.id, vo.observed_at, vo.distance_along_route_m,
                   vo.progress_along_route
            FROM vehicle_observations vo
            WHERE vo.vehicle_id = %s
              AND vo.line_no = %s
              AND vo.route_id = %s
              AND vo.observed_at >= %s
              AND vo.observed_at < %s
              AND vo.distance_along_route_m IS NOT NULL
              AND vo.map_match_quality = ANY(%s)
              AND vo.position_quality != 'STALE_POSITION'
            ORDER BY vo.observed_at
            """,
            (vehicle_id, line_no, route_id, approach_started_at, arrival_observed_at,
             list(VALID_MATCH_QUALITIES)),
        )
        return cur.fetchall()


def compute_recent_speed(conn, vehicle_id, line_no, route_id, before_time, lookback_seconds=180):
    """before_time'dan hemen once, AYNI route_id (dolayisiyla ayni yon) ve
    SADECE GOOD/DEGRADED, stale olmayan gozlemler arasindaki hiz (m/s)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT observed_at, distance_along_route_m
            FROM vehicle_observations
            WHERE vehicle_id = %s AND line_no = %s AND route_id = %s
              AND observed_at <= %s
              AND observed_at >= %s - (%s * INTERVAL '1 second')
              AND distance_along_route_m IS NOT NULL
              AND map_match_quality = ANY(%s)
              AND position_quality != 'STALE_POSITION'
            ORDER BY observed_at
            """,
            (vehicle_id, line_no, route_id, before_time, before_time, lookback_seconds,
             list(VALID_MATCH_QUALITIES)),
        )
        rows = cur.fetchall()
        if len(rows) < 2:
            return None
        (t_first, d_first), (t_last, d_last) = rows[0], rows[-1]
        dt = (t_last - t_first).total_seconds()
        if dt <= 0:
            return None
        return (d_last - d_first) / dt


def get_stop_distance_along(conn, route_id, stop_pk):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT distance_along_route_m FROM route_stop_sequence "
            "WHERE route_id = %s AND stop_id = %s",
            (route_id, stop_pk),
        )
        row = cur.fetchone()
        return row[0] if row else None


def upsert_training_sample(cur, values):
    cur.execute(
        """
        INSERT INTO eta_training_samples
            (vehicle_id, line_no, direction, target_stop_id, arrival_event_id,
             source_observation_id, observed_at, actual_arrival_at,
             actual_eta_seconds, distance_remaining_m, progress_along_route,
             recent_speed_mps, hour_of_day, day_of_week, label_quality)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_observation_id, arrival_event_id) DO NOTHING
        RETURNING id
        """,
        values,
    )
    row = cur.fetchone()
    return (row[0], True) if row else (None, False)


def generate_samples(conn, run_id):
    events = fetch_arrival_events_for_run(conn, run_id)
    print(f"{len(events)} arrival_event bulundu (run_id={run_id}).")

    total_new = 0
    total_reused = 0
    skipped_leakage = 0
    skipped_no_sequence = 0

    with conn.cursor() as cur:
        for (event_id, vehicle_id, line_no, direction, stop_pk,
             approach_started_at, arrival_observed_at, confidence, route_id) in events:

            stop_dist_along = get_stop_distance_along(conn, route_id, stop_pk)
            if stop_dist_along is None:
                skipped_no_sequence += 1
                continue

            t0_candidates = fetch_t0_candidates(
                conn, vehicle_id, line_no, direction, route_id,
                approach_started_at, arrival_observed_at,
            )

            label_quality = CONFIDENCE_TO_LABEL_QUALITY[confidence]

            for obs_id, observed_at, dist_along, progress in t0_candidates:
                actual_eta_seconds = (arrival_observed_at - observed_at).total_seconds()

                if actual_eta_seconds <= 0:
                    skipped_leakage += 1
                    continue

                distance_remaining_m = stop_dist_along - dist_along
                if distance_remaining_m < 0:
                    continue

                recent_speed = compute_recent_speed(conn, vehicle_id, line_no, route_id, observed_at)

                values = (
                    vehicle_id, line_no, direction, stop_pk, event_id, obs_id,
                    observed_at, arrival_observed_at, actual_eta_seconds,
                    distance_remaining_m, progress, recent_speed,
                    observed_at.hour, observed_at.weekday(), label_quality,
                )
                sample_id, is_new = upsert_training_sample(cur, values)
                if is_new:
                    total_new += 1
                else:
                    total_reused += 1

    print(f"\n{total_new} YENI eta_training_samples uretildi, {total_reused} zaten vardi (idempotent).")
    print(f"{skipped_leakage} aday future-leakage riski nedeniyle atlandi.")
    print(f"{skipped_no_sequence} event, route_stop_sequence eksikligi nedeniyle atlandi.")
    return total_new


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    conn = db_storage.get_connection()
    generate_samples(conn, args.run_id)
    conn.close()
