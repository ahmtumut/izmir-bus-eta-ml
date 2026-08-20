"""
Faz 3: Inference - secilen final model (CatBoost) ile canli tahmin.

Egitimdeki feature uretim mantigiyla (app/ml/features.py) BIREBIR AYNI
sorgu/pencere tanimlarini kullanir - T0, verilen aracin EN SON bilinen
GOOD/DEGRADED gozlemidir (gercek deployment senaryosu: "su an" icin
tahmin uret). Gelecekteki hicbir veriye bakilmaz (T0'dan sonraki
gozlemler sorgularda hic kullanilmaz).

Kullanim:
    python -m app.ml.inference --vehicle-id 2283 --line-no 761 --target-stop-id 50605
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
from catboost import CatBoostRegressor

from app.storage import db_storage
from app.ml.dataset import MODEL_FEATURE_COLUMNS, CATEGORICAL_FEATURES
from app.ml.features import (
    fetch_last_n_observations, fetch_window_observations, compute_speed_samples,
)

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "catboost_eta_model.cbm"

# detect_arrival_events.py'deki COARSE_APPROACH_WINDOW_M=3000 nedeniyle train
# setinde distance_remaining_m HICBIR ZAMAN ~3200m'yi gecmiyor (gozlemlenen
# max: 3191m). Model bu aralikta hic ornek gormedi - cok daha uzak bir durak
# icin tahmin istenirse SESSIZCE ekstrapolasyon yapip fiziksel olarak anlamsiz
# sonuclar uretebilir (test edildi: 26km icin 5.8dk gibi imkansiz bir deger
# dondu). Bu yuzden bu esigin uzerinde acik bir uyari basiliyor.
TRAINING_MAX_DISTANCE_REMAINING_M = 3200


def fetch_latest_observation(conn, vehicle_id: str, line_no: str):
    """Aracin EN SON GOOD/DEGRADED, stale olmayan gozlemi - inference'da
    "T0 = su an" varsayimi budur."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT observed_at, route_id, distance_along_route_m,
                   progress_along_route, distance_to_route_m
            FROM vehicle_observations
            WHERE vehicle_id = %s AND line_no = %s
              AND map_match_quality IN ('GOOD', 'DEGRADED')
              AND position_quality != 'STALE_POSITION'
              AND distance_along_route_m IS NOT NULL
            ORDER BY observed_at DESC
            LIMIT 1
            """,
            (vehicle_id, line_no),
        )
        return cur.fetchone()


def fetch_observation_at(conn, vehicle_id: str, line_no: str, at_time):
    """Faz 4 replay: 'T0 = su an' yerine 'T0 = at_time'deki (veya ondan hemen
    once) en son GOOD/DEGRADED, stale olmayan gozlem. Ayni future-leakage
    korumasi (observed_at <= at_time) - gecmis bir ana "o an model ne
    tahmin ederdi" sorusu icin, gelecekteki hicbir gozleme bakilmaz."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT observed_at, route_id, distance_along_route_m,
                   progress_along_route, distance_to_route_m
            FROM vehicle_observations
            WHERE vehicle_id = %s AND line_no = %s
              AND observed_at <= %s
              AND map_match_quality IN ('GOOD', 'DEGRADED')
              AND position_quality != 'STALE_POSITION'
              AND distance_along_route_m IS NOT NULL
            ORDER BY observed_at DESC
            LIMIT 1
            """,
            (vehicle_id, line_no, at_time),
        )
        return cur.fetchone()


def fetch_next_stop(conn, route_id: int, distance_along_route_m: float):
    """Aracin su anki route-ilerlemesinin hemen onundeki ilk durak (replay'de
    'hangi durak icin ETA gosterelim' sorusuna otomatik cevap)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.stop_id, s.stop_name, rss.distance_along_route_m
            FROM route_stop_sequence rss
            JOIN stops s ON s.id = rss.stop_id
            WHERE rss.route_id = %s AND rss.distance_along_route_m > %s
            ORDER BY rss.distance_along_route_m ASC
            LIMIT 1
            """,
            (route_id, distance_along_route_m),
        )
        return cur.fetchone()


def fetch_route_direction(conn, route_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT direction, total_length_m FROM routes WHERE id = %s", (route_id,))
        return cur.fetchone()


def fetch_stop_distance_along(conn, route_id: int, target_stop_id: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rss.distance_along_route_m
            FROM route_stop_sequence rss
            JOIN stops s ON s.id = rss.stop_id
            WHERE rss.route_id = %s AND s.stop_id = %s
            """,
            (route_id, target_stop_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def build_feature_row(conn, vehicle_id: str, line_no: str, target_stop_id: str, at_time=None) -> dict:
    """at_time=None: canli kullanim, T0 = aracin en son gozlemi (mevcut davranis,
    degismedi). at_time verilirse (Faz 4 replay): T0 = o zamandaki (veya hemen
    onceki) en son gozlem - 'gecmiste o an model ne tahmin ederdi' sorusu icin,
    gelecekteki hicbir gozleme bakilmaz (fetch_observation_at ayni observed_at
    <= at_time filtresini uygular)."""
    obs = (
        fetch_latest_observation(conn, vehicle_id, line_no)
        if at_time is None
        else fetch_observation_at(conn, vehicle_id, line_no, at_time)
    )
    if obs is None:
        raise ValueError(f"Arac {vehicle_id} (hat {line_no}) icin uygun (GOOD/DEGRADED, "
                          f"stale olmayan) guncel bir gozlem bulunamadi.")
    t0, route_id, dist_along, progress, dist_to_route = obs

    direction_row = fetch_route_direction(conn, route_id)
    if direction_row is None:
        raise ValueError(f"route_id={route_id} icin routes kaydi bulunamadi.")
    direction, _ = direction_row

    stop_dist_along = fetch_stop_distance_along(conn, route_id, target_stop_id)
    if stop_dist_along is None:
        raise ValueError(f"Durak {target_stop_id}, route_id={route_id} icin "
                          f"route_stop_sequence'ta bulunamadi (hat/yon uyumsuz olabilir).")

    distance_remaining_m = stop_dist_along - dist_along
    if distance_remaining_m < 0:
        raise ValueError(f"Arac zaten durağı geçmiş görünüyor "
                          f"(distance_remaining_m={distance_remaining_m:.1f}m < 0) - "
                          f"tahmin anlamlı değil.")

    last3 = fetch_last_n_observations(conn, vehicle_id, route_id, t0, n=3)
    window5min = fetch_window_observations(conn, vehicle_id, route_id, t0)

    time_since_previous_obs_s = None
    if len(last3) >= 2:
        time_since_previous_obs_s = (last3[-1][0] - last3[-2][0]).total_seconds()

    speed_samples = compute_speed_samples(last3)
    speed_avg_last3_mps = sum(speed_samples) / len(speed_samples) if speed_samples else None
    speed_std_last3_mps = None
    if len(speed_samples) >= 2:
        mean = sum(speed_samples) / len(speed_samples)
        speed_std_last3_mps = (sum((s - mean) ** 2 for s in speed_samples) / (len(speed_samples) - 1)) ** 0.5

    speed_avg_5min_mps = None
    recent_speed_mps = None
    if len(window5min) >= 2:
        t_first, d_first = window5min[0]
        t_last, d_last = window5min[-1]
        dt = (t_last - t_first).total_seconds()
        if dt > 0:
            speed_avg_5min_mps = (d_last - d_first) / dt
    # recent_speed_mps: 180sn'lik alt-pencere (generate_eta_training_samples.py ile tutarli)
    window180 = [(t, d) for t, d in window5min if (t0 - t).total_seconds() <= 180]
    if len(window180) >= 2:
        t_first, d_first = window180[0]
        t_last, d_last = window180[-1]
        dt = (t_last - t_first).total_seconds()
        if dt > 0:
            recent_speed_mps = (d_last - d_first) / dt

    return {
        "line_no": line_no,
        "direction": direction,
        "target_stop_id": target_stop_id,
        "distance_remaining_m": distance_remaining_m,
        "progress_along_route": progress,
        "recent_speed_mps": recent_speed_mps,
        "hour_of_day": t0.hour,
        "day_of_week": t0.weekday(),
        "distance_to_route_m": dist_to_route,
        "time_since_previous_obs_s": time_since_previous_obs_s,
        "speed_avg_last3_mps": speed_avg_last3_mps,
        "speed_std_last3_mps": speed_std_last3_mps,
        "speed_avg_5min_mps": speed_avg_5min_mps,
    }, t0


def predict_eta(conn, vehicle_id: str, line_no: str, target_stop_id: str,
                 model: CatBoostRegressor = None, at_time=None):
    """Doner: (predicted_eta_seconds, t0_observed_at, feature_row_dict).
    at_time: bkz. build_feature_row - None ise canli davranis (degismedi)."""
    if model is None:
        model = CatBoostRegressor()
        model.load_model(str(MODEL_PATH))

    feature_row, t0 = build_feature_row(conn, vehicle_id, line_no, target_stop_id, at_time=at_time)

    X = pd.DataFrame([feature_row])[MODEL_FEATURE_COLUMNS]
    for col in CATEGORICAL_FEATURES:
        X[col] = X[col].astype(str)

    predicted_eta_seconds = float(model.predict(X)[0])
    return predicted_eta_seconds, t0, feature_row


def main():
    parser = argparse.ArgumentParser(description="Faz 3 inference - tek arac/durak icin ETA tahmini")
    parser.add_argument("--vehicle-id", type=str, required=True)
    parser.add_argument("--line-no", type=str, required=True)
    parser.add_argument("--target-stop-id", type=str, required=True)
    args = parser.parse_args()

    conn = db_storage.get_connection()
    try:
        predicted_eta_seconds, t0, feature_row = predict_eta(
            conn, args.vehicle_id, args.line_no, args.target_stop_id
        )
    except ValueError as e:
        print(f"Tahmin üretilemedi: {e}")
        conn.close()
        sys.exit(1)
    conn.close()

    now = datetime.now(timezone.utc)
    t0_age_s = (now - t0).total_seconds()
    predicted_arrival = t0 + pd.Timedelta(seconds=predicted_eta_seconds)

    print(f"Arac {args.vehicle_id} (hat {args.line_no}) -> durak {args.target_stop_id}")
    print(f"T0 (son bilinen gozlem): {t0.isoformat()} ({t0_age_s:.0f}sn once)")
    print(f"Kalan mesafe: {feature_row['distance_remaining_m']:.0f}m")
    print(f"Tahmini ETA: {predicted_eta_seconds:.0f}sn ({predicted_eta_seconds/60:.1f}dk)")
    print(f"Tahmini varis zamani (T0 baz alinarak): {predicted_arrival.isoformat()}")
    if t0_age_s > 120:
        print(f"UYARI: T0 gozlemi {t0_age_s:.0f}sn once - guncel olmayabilir "
              f"(collector aktif calismiyor olabilir).")
    if feature_row["distance_remaining_m"] > TRAINING_MAX_DISTANCE_REMAINING_M:
        print(f"UYARI: kalan mesafe ({feature_row['distance_remaining_m']:.0f}m) "
              f"modelin egitim verisinde gordugu maksimumun (~{TRAINING_MAX_DISTANCE_REMAINING_M}m) "
              f"cok uzerinde - bu tahmin GUVENILMEZ (ekstrapolasyon). Model, "
              f"COARSE_APPROACH_WINDOW_M=3000 nedeniyle sadece durağa ~3km'den "
              f"yakin T0'lardan egitildi.")


if __name__ == "__main__":
    main()
