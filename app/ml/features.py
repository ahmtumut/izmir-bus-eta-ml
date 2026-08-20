"""
Faz 3: Feature engineering.

TEMEL feature'lar (Faz 2'de generate_eta_training_samples.py tarafindan
zaten uretildi, burada eta_training_samples'tan sadece okunuyor):
    distance_remaining_m, progress_along_route, recent_speed_mps (180sn
    penceresi), hour_of_day, day_of_week, line_no, direction,
    target_stop_id

EK feature'lar (bu script tarafindan, T0 ve GECMIS gozlemlerden uretilir):
    distance_to_route_m           - T0 gozleminin map-match mesafesi
                                     (dogrudan vehicle_observations kolonu,
                                     GPS/map-match belirsizligini yansitir)
    time_since_previous_obs_s     - T0'dan hemen once en yakin gozlemle
                                     arasindaki sure (gozlem sikligi sinyali)
    speed_avg_last3_mps           - son 3 gozlem arasindaki hiz orneklerinin
                                     ortalamasi (en fazla 2 ornek, 3 nokta ->
                                     2 ardisik interval)
    speed_std_last3_mps           - ayni orneklerin standart sapmasi
                                     (hiz degiskenligi - trafik/duraklama sinyali)
    speed_avg_5min_mps            - T0'dan geriye 5 dakikalik penceredeki
                                     baslangic-bitis noktalarindan hesaplanan
                                     ortalama hiz (recent_speed_mps'in 180sn
                                     yerine 300sn'lik versiyonu)

KRITIK - future leakage korumasi: Tum feature sorgulari "observed_at <= T0"
filtresi kullanir (bkz. fetch_last_n_observations / fetch_window_observations).
actual_arrival_at / actual_eta_seconds bu script tarafindan HICBIR feature
hesabinda okunmaz - onlar sadece label'dir (chk_no_future_leakage constraint'i
DB seviyesinde bunu zaten garanti ediyor, feature sorgulari ayrica kendi
observed_at <= T0 filtresini uyguluyor).

vehicle_id ciktiya dahil edilir (iz surulebilirlik/gelecekteki ablation testi
icin) ama modele feature olarak VERILMEMELIDIR (gorev talimati - modelin
arac kimligini ezberlemesi istenmiyor). Bu ayrim burada degil, train
script'lerinde (feature listesinden vehicle_id haric tutularak) yapilacak.

Sadece dataset_split IS NOT NULL olan (yani label_quality != REJECTED VE
app/ml/split.py tarafindan train/validation/test'e atanmis) satirlar islenir.

Kullanim:
    python -m app.ml.features
    python -m app.ml.features --save data/processed/eta_features_20260817.csv
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from app.storage import db_storage

VALID_MATCH_QUALITIES = ("GOOD", "DEGRADED")
FIVE_MIN_SECONDS = 300


def fetch_base_rows(conn):
    """dataset_split atanmis (REJECTED disi) tum satirlari, T0 gozleminin
    route_id ve distance_to_route_m'i ile birlikte getirir."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ets.id, ets.arrival_event_id, ets.vehicle_id, ets.line_no,
                   ets.direction, ets.target_stop_id, ets.source_observation_id,
                   ets.observed_at, ets.actual_eta_seconds,
                   ets.distance_remaining_m, ets.progress_along_route,
                   ets.recent_speed_mps, ets.hour_of_day, ets.day_of_week,
                   ets.label_quality, ets.dataset_split,
                   vo.route_id, vo.distance_to_route_m
            FROM eta_training_samples ets
            JOIN vehicle_observations vo ON vo.id = ets.source_observation_id
            WHERE ets.dataset_split IS NOT NULL
            ORDER BY ets.id
            """
        )
        cols = [d.name for d in cur.description]
        return cols, cur.fetchall()


def fetch_out_of_sample_rows(conn, limit: int = 3000):
    """fetch_base_rows'un ayna fonksiyonu: dataset_split HENUZ ATANMAMIS
    (train/val/test split'i DONDURULDUKTEN SONRA toplanan, modelin egitim/
    dogrulama/test asamalarinda HIC GORMEDIGI) satirlari getirir. Gercek
    zamanlı model performans izleme icin (bkz. app/api/model_metrics.py:
    /api/model/live-performance) - modelin production'da, gercekten hic
    gormedigi taze veride ne kadar iyi calistigini gosterir.

    limit: build_*_feature_dataframe satir basina 2 ek DB sorgusu yapiyor
    (compute_row_features) - binlerce satirda bu HTTP istegini yavaslatir,
    bu yuzden EN YENI `limit` satirla sinirlandirilir (yine de "canli"
    performansi temsil eder, hatta daha guncel oldugu icin daha iyi)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ets.id, ets.arrival_event_id, ets.vehicle_id, ets.line_no,
                   ets.direction, ets.target_stop_id, ets.source_observation_id,
                   ets.observed_at, ets.actual_eta_seconds,
                   ets.distance_remaining_m, ets.progress_along_route,
                   ets.recent_speed_mps, ets.hour_of_day, ets.day_of_week,
                   ets.label_quality, ets.dataset_split,
                   vo.route_id, vo.distance_to_route_m
            FROM eta_training_samples ets
            JOIN vehicle_observations vo ON vo.id = ets.source_observation_id
            WHERE ets.dataset_split IS NULL AND ets.label_quality != 'REJECTED'
            ORDER BY ets.id DESC
            LIMIT %s
            """,
            (limit,),
        )
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
        rows.reverse()  # kronolojik siraya geri cevir
        return cols, rows


def build_out_of_sample_feature_dataframe(conn) -> pd.DataFrame:
    cols, rows = fetch_out_of_sample_rows(conn)
    records = []
    for row in rows:
        base = dict(zip(cols, row))
        engineered = compute_row_features(
            conn, base["vehicle_id"], base["route_id"], base["observed_at"]
        )
        record = {**base, **engineered}
        records.append(record)
    return pd.DataFrame.from_records(records)


def fetch_last_n_observations(conn, vehicle_id, route_id, t0, n=3):
    """T0'dan (dahil) geriye dogru, AYNI route_id + GOOD/DEGRADED + stale
    olmayan son n gozlemi zaman ARTAN sirayla dondurur. T0'in kendisi de
    (source_observation_id'nin karsiligi) bu listenin icindedir - "en son
    gozlem" T0'in kendisidir, gelecege bakilmiyor."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT observed_at, distance_along_route_m
            FROM vehicle_observations
            WHERE vehicle_id = %s AND route_id = %s
              AND observed_at <= %s
              AND distance_along_route_m IS NOT NULL
              AND map_match_quality = ANY(%s)
              AND position_quality != 'STALE_POSITION'
            ORDER BY observed_at DESC
            LIMIT %s
            """,
            (vehicle_id, route_id, t0, list(VALID_MATCH_QUALITIES), n),
        )
        rows = cur.fetchall()
    return list(reversed(rows))  # zaman artan sira


def fetch_window_observations(conn, vehicle_id, route_id, t0, lookback_seconds=FIVE_MIN_SECONDS):
    """T0'dan geriye lookback_seconds'lik pencerede, ayni filtrelerle tum
    gozlemleri zaman artan sirayla dondurur (5dk ortalama hiz icin)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT observed_at, distance_along_route_m
            FROM vehicle_observations
            WHERE vehicle_id = %s AND route_id = %s
              AND observed_at <= %s
              AND observed_at >= %s - (%s * INTERVAL '1 second')
              AND distance_along_route_m IS NOT NULL
              AND map_match_quality = ANY(%s)
              AND position_quality != 'STALE_POSITION'
            ORDER BY observed_at ASC
            """,
            (vehicle_id, route_id, t0, t0, lookback_seconds, list(VALID_MATCH_QUALITIES)),
        )
        return cur.fetchall()


def compute_speed_samples(points):
    """points: [(observed_at, distance_along_route_m), ...] zaman artan sirali.
    Ardisik ciftler arasindaki hiz orneklerini (m/s) dondurur; sifir/negatif
    zaman farki olan ciftler atlanir (ayni observed_at ile iki farkli gozlem
    - Bulgu 2'deki gibi response-ici cakisma ihtimaline karsi guvenlik)."""
    samples = []
    for i in range(len(points) - 1):
        t1, d1 = points[i]
        t2, d2 = points[i + 1]
        dt = (t2 - t1).total_seconds()
        if dt > 0:
            samples.append((d2 - d1) / dt)
    return samples


def compute_row_features(conn, vehicle_id, route_id, t0):
    last3 = fetch_last_n_observations(conn, vehicle_id, route_id, t0, n=3)
    window5min = fetch_window_observations(conn, vehicle_id, route_id, t0)

    time_since_previous_obs_s = None
    if len(last3) >= 2:
        time_since_previous_obs_s = (last3[-1][0] - last3[-2][0]).total_seconds()

    speed_samples_last3 = compute_speed_samples(last3)
    speed_avg_last3_mps = statistics.mean(speed_samples_last3) if speed_samples_last3 else None
    speed_std_last3_mps = (
        statistics.stdev(speed_samples_last3) if len(speed_samples_last3) >= 2 else None
    )

    speed_avg_5min_mps = None
    if len(window5min) >= 2:
        t_first, d_first = window5min[0]
        t_last, d_last = window5min[-1]
        dt = (t_last - t_first).total_seconds()
        if dt > 0:
            speed_avg_5min_mps = (d_last - d_first) / dt

    return {
        "time_since_previous_obs_s": time_since_previous_obs_s,
        "speed_avg_last3_mps": speed_avg_last3_mps,
        "speed_std_last3_mps": speed_std_last3_mps,
        "speed_avg_5min_mps": speed_avg_5min_mps,
    }


def build_feature_dataframe(conn) -> pd.DataFrame:
    cols, rows = fetch_base_rows(conn)
    records = []
    for row in rows:
        base = dict(zip(cols, row))
        engineered = compute_row_features(
            conn, base["vehicle_id"], base["route_id"], base["observed_at"]
        )
        record = {**base, **engineered}
        records.append(record)

    df = pd.DataFrame.from_records(records)
    return df


def print_missing_report(df: pd.DataFrame):
    engineered_cols = [
        "distance_to_route_m", "time_since_previous_obs_s",
        "speed_avg_last3_mps", "speed_std_last3_mps", "speed_avg_5min_mps",
    ]
    print("\n--- Eksik (NULL) feature orani ---")
    for col in engineered_cols:
        n_missing = df[col].isna().sum()
        pct = n_missing / len(df) * 100 if len(df) else 0
        print(f"  {col}: {n_missing}/{len(df)} eksik ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Faz 3 feature engineering")
    parser.add_argument("--save", type=str, default=None,
                         help="Feature dataframe'ini CSV olarak kaydet "
                              "(ör. data/processed/eta_features_20260817.csv)")
    args = parser.parse_args()

    conn = db_storage.get_connection()
    df = build_feature_dataframe(conn)
    conn.close()

    print(f"Toplam satir: {len(df)}")
    print(f"Split bazinda: {df['dataset_split'].value_counts().to_dict()}")
    print(f"Hat bazinda: {df['line_no'].value_counts().to_dict()}")
    print_missing_report(df)

    if args.save:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"\nFeature dataframe kaydedildi: {out_path} ({len(df)} satir, {len(df.columns)} kolon)")


if __name__ == "__main__":
    main()
