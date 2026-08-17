"""
Faz 3: Duzeltilmis baseline modeller - XGBoost/CatBoost'un gecmesi gereken
alt siniri belirler.

Baseline 1 (distance/speed): predicted_eta = distance_remaining_m / speed.
    speed kaynagi: recent_speed_mps (180sn), yoksa speed_avg_5min_mps,
    o da yoksa TRAIN setinin ortalama hizi (fallback - test setine
    bakilmadan hesaplanir, leakage yok).

Baseline 2 (historical segment median): predicted_eta = TRAIN setinde ayni
    (line_no, direction, target_stop_id) segmentinin medyan actual_eta_seconds
    degeri. Faz 2'deki "leave-one-out yapilmadi, guvenilmez" sorunu burada
    DOGAL OLARAK COZULUYOR: medyan SADECE train'den hesaplanip val/test'e
    uygulaniyor (split'ler zaten ayrik) - bu, gercek bir leave-out.
    Segment train'de hic gorulmemisse, train'in genel medyanina dusulur.

Kullanim:
    python -m app.ml.baselines --features data/processed/eta_features_20260817.csv
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np

from app.ml.dataset import load_features, split_dataframe
from app.ml.evaluate import compute_metrics, format_metrics_table

FALLBACK_MIN_SPEED_MPS = 0.5  # sifira bolme / durma durumunda alt sinir


def baseline_distance_speed_predict(df, fallback_speed_mps):
    speed = df["recent_speed_mps"].copy()
    speed = speed.where(speed.notna() & (speed > 0), df["speed_avg_5min_mps"])
    speed = speed.where(speed.notna() & (speed > 0), fallback_speed_mps)
    speed = speed.clip(lower=FALLBACK_MIN_SPEED_MPS)
    return df["distance_remaining_m"] / speed


def baseline_historical_median_predict(train_df, target_df):
    seg_median = (
        train_df.groupby(["line_no", "direction", "target_stop_id"], observed=True)["actual_eta_seconds"]
        .median()
    )
    overall_median = train_df["actual_eta_seconds"].median()

    keys = list(zip(target_df["line_no"], target_df["direction"], target_df["target_stop_id"]))
    preds = [seg_median.get(k, overall_median) for k in keys]
    return np.array(preds)


def main():
    parser = argparse.ArgumentParser(description="Faz 3 baseline modeller")
    parser.add_argument("--features", type=str, required=True)
    args = parser.parse_args()

    df = load_features(args.features)
    train_df, val_df, test_df = split_dataframe(df)

    fallback_speed = train_df["recent_speed_mps"].dropna()
    fallback_speed = fallback_speed[fallback_speed > 0].mean()
    print(f"Baseline 1 fallback hiz (train ortalamasi): {fallback_speed:.2f} m/s")

    results = {}
    for split_name, split_df in [("train", train_df), ("validation", val_df), ("test", test_df)]:
        pred1 = baseline_distance_speed_predict(split_df, fallback_speed)
        m1 = compute_metrics(split_df["actual_eta_seconds"], pred1)
        results[f"baseline1_{split_name}"] = m1

        pred2 = baseline_historical_median_predict(train_df, split_df)
        m2 = compute_metrics(split_df["actual_eta_seconds"], pred2)
        results[f"baseline2_{split_name}"] = m2

    print("\n" + "=" * 70)
    print("BASELINE SONUCLARI (Baseline 1: distance/speed, Baseline 2: historical median)")
    print("=" * 70)
    print(format_metrics_table(results))

    print("\nOnemli: Baseline 2 artik LEAVE-OUT - medyanlar sadece TRAIN'den "
          "hesaplandi, val/test'e uygulandi (Faz 2'deki guvenilmezlik sorunu "
          "duzeltildi).")


if __name__ == "__main__":
    main()
