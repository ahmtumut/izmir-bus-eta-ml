"""
Faz 2 madde 7: ETA ground-truth training orneklerini uretir.

Her arrival_event icin, o olaydan ONCEKI arac gozlemlerinden (T0) training
satirlari uretir:
    T0 = arac gozlemi (arrival_event'in approach_started_at .. arrival_observed_at
         arasindaki HERHANGI bir map-matched gozlem, sadece en yakini degil -
         boylece farkli "durağa ne kadar kaldi" senaryolari icin cesitli
         training ornekleri elde edilir)
    T1 = arrival_event.arrival_observed_at (dogrulanmis varis)

    actual_eta_seconds = T1 - T0

GELECEK SIZINTISI KORUMASI: T0'da bilinen hicbir feature, T1'den sonraki
bilgiyi icermez. actual_eta SADECE label uretiminde kullanilir, feature
olarak hicbir sekilde training satirina yazilmaz (zaten schema'da boyle
bir kolon yok, sadece actual_eta_seconds var - bu acikca LABEL'dir).

label_quality:
    GOLD   <- arrival_event.arrival_confidence = HIGH
    SILVER <- arrival_event.arrival_confidence = MEDIUM
    REJECTED <- arrival_event.arrival_confidence = LOW (yine de saklanir,
                seffaflik icin, ama training'de kullanilmamali)

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


def fetch_arrival_events_for_run(conn, run_id):
    """Bu run'daki gozlemlere denk dusen arrival_events'i bulur
    (triggering_observation_id uzerinden ingestion_run'a baglaniyor)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ae.id, ae.vehicle_id, ae.line_no, ae.direction,
                   ae.stop_id, ae.approach_started_at, ae.arrival_observed_at,
                   ae.arrival_confidence
            FROM arrival_events ae
            JOIN vehicle_observations vo ON vo.id = ae.triggering_observation_id
            JOIN raw_snapshots rs ON rs.id = vo.raw_snapshot_id
            WHERE rs.ingestion_run_id = %s
            """,
            (run_id,),
        )
        return cur.fetchall()


def fetch_t0_candidates(conn, vehicle_id, route_id_line_no, approach_started_at, arrival_observed_at):
    """approach_started_at ile arrival_observed_at arasindaki (T1'den ONCEKI)
    map-matched gozlemleri T0 adayi olarak doner."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vo.id, vo.observed_at, vo.distance_along_route_m,
                   vo.progress_along_route, vo.line_no
            FROM vehicle_observations vo
            WHERE vo.vehicle_id = %s
              AND vo.line_no = %s
              AND vo.observed_at >= %s
              AND vo.observed_at < %s
              AND vo.distance_along_route_m IS NOT NULL
            ORDER BY vo.observed_at
            """,
            (vehicle_id, route_id_line_no, approach_started_at, arrival_observed_at),
        )
        return cur.fetchall()


def compute_recent_speed(conn, vehicle_id, line_no, before_time, lookback_seconds=180):
    """before_time'dan hemen once iki gozlem arasindaki hiz (m/s) tahmini."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT observed_at, distance_along_route_m
            FROM vehicle_observations
            WHERE vehicle_id = %s AND line_no = %s
              AND observed_at <= %s
              AND observed_at >= %s - (%s * INTERVAL '1 second')
              AND distance_along_route_m IS NOT NULL
            ORDER BY observed_at
            """,
            (vehicle_id, line_no, before_time, before_time, lookback_seconds),
        )
        rows = cur.fetchall()
        if len(rows) < 2:
            return None
        (t_first, d_first), (t_last, d_last) = rows[0], rows[-1]
        dt = (t_last - t_first).total_seconds()
        if dt <= 0:
            return None
        return (d_last - d_first) / dt  # m/s, negatifse geri gitme/gurultu


def get_stop_distance_along(conn, route_id, stop_pk):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT distance_along_route_m FROM route_stop_sequence "
            "WHERE route_id = %s AND stop_id = %s",
            (route_id, stop_pk),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_route_id_for_line_direction(conn, line_no, direction):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, total_length_m FROM routes WHERE line_no = %s AND direction = %s",
            (line_no, direction),
        )
        return cur.fetchone()


def generate_samples(conn, run_id):
    events = fetch_arrival_events_for_run(conn, run_id)
    print(f"{len(events)} arrival_event bulundu (run_id={run_id}).")

    total_samples = 0
    skipped_leakage = 0

    with conn.cursor() as cur:
        for (event_id, vehicle_id, line_no, direction, stop_pk,
             approach_started_at, arrival_observed_at, confidence) in events:

            route_info = get_route_id_for_line_direction(conn, line_no, direction)
            if not route_info:
                continue
            route_id, total_length_m = route_info

            stop_dist_along = get_stop_distance_along(conn, route_id, stop_pk)
            if stop_dist_along is None:
                continue  # bu durak icin sequence yok, atla

            t0_candidates = fetch_t0_candidates(
                conn, vehicle_id, line_no, approach_started_at, arrival_observed_at
            )

            label_quality = CONFIDENCE_TO_LABEL_QUALITY[confidence]

            for obs_id, observed_at, dist_along, progress, obs_line_no in t0_candidates:
                actual_eta_seconds = (arrival_observed_at - observed_at).total_seconds()

                if actual_eta_seconds <= 0:
                    # future leakage koruma: T0 mutlaka T1'den once olmali
                    skipped_leakage += 1
                    continue

                distance_remaining_m = stop_dist_along - dist_along
                if distance_remaining_m < 0:
                    # arac zaten duragi gecmis - bu T0 adayi gecersiz
                    continue

                recent_speed = compute_recent_speed(conn, vehicle_id, line_no, observed_at)

                cur.execute(
                    """
                    INSERT INTO eta_training_samples
                        (vehicle_id, line_no, direction, target_stop_id, arrival_event_id,
                         source_observation_id, observed_at, actual_arrival_at,
                         actual_eta_seconds, distance_remaining_m, progress_along_route,
                         recent_speed_mps, hour_of_day, day_of_week, label_quality)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        vehicle_id, line_no, direction, stop_pk, event_id, obs_id,
                        observed_at, arrival_observed_at, actual_eta_seconds,
                        distance_remaining_m, progress, recent_speed,
                        observed_at.hour, observed_at.weekday(), label_quality,
                    ),
                )
                total_samples += 1

    print(f"\n{total_samples} eta_training_samples uretildi.")
    print(f"{skipped_leakage} aday, future-leakage riski nedeniyle atlandi "
          f"(T0 >= T1 durumu - beklenmiyordu ama kontrol edildi).")
    return total_samples


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    conn = db_storage.get_connection()
    generate_samples(conn, args.run_id)
    conn.close()
