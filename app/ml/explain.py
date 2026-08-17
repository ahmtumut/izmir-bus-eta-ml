"""
Faz 3: Model aciklanabilirligi - SHAP analizi.

Gorev talimati: "XGBoost tarafinda mumkunse SHAP analizi yap" - bu script
HEM XGBoost HEM CatBoost (secilen final model) icin SHAP degerleri
hesaplar (shap.TreeExplainer ikisini de native destekler).

Sorulan sorular:
    - Hangi feature'lar ETA'yi en cok etkiliyor?
    - distance_remaining beklendigi kadar guclu mu?
    - recent_speed ne kadar etkili?
    - Saat etkisi olusuyor mu?
    - Hat ve durak bilgisi ne kadar onemli?

SHAP degerleri TEST seti uzerinde hesaplanir (train'de degil - train
uzerinde hesaplamak overfit edilmis iliskileri yansitir, test held-out
verideki gercek etkiyi gosterir).

Kullanim:
    python -m app.ml.explain --features data/processed/eta_features_20260817_v2.csv
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import shap
from catboost import CatBoostRegressor
from xgboost import XGBRegressor

from app.ml.dataset import load_features, split_dataframe, get_X_y, MODEL_FEATURE_COLUMNS, CATEGORICAL_FEATURES


def compute_shap_summary(model, X, model_name: str) -> dict:
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    mean_abs_shap = np.abs(shap_values).mean(axis=0)
    importance = dict(zip(MODEL_FEATURE_COLUMNS, mean_abs_shap.tolist()))
    importance_sorted = dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))

    print(f"\n--- {model_name}: SHAP ortalama |etki| (dakika cinsinden hedefte, saniye/60) ---")
    for feat, val in importance_sorted.items():
        print(f"  {feat}: {val/60:.4f} dk")

    return {
        "mean_abs_shap": importance_sorted,
        "shap_values": shap_values,
    }


def answer_questions(xgb_importance: dict, cat_importance: dict):
    print("\n" + "=" * 70)
    print("SORULARA CEVAPLAR (CatBoost - secilen final model - baz alinarak)")
    print("=" * 70)

    ranked = list(cat_importance.keys())

    print(f"\n1) Hangi feature'lar ETA'yi en cok etkiliyor?")
    print(f"   Ilk 5: {ranked[:5]}")

    dist_rank = ranked.index("distance_remaining_m") + 1
    print(f"\n2) distance_remaining_m beklendigi kadar guclu mu?")
    print(f"   Sira: {dist_rank}/{len(ranked)}. "
          f"{'Evet, en guclu/ust siralarda feature - sezgiyle tutarli.' if dist_rank <= 2 else 'Beklenenden zayif - dikkat cekici.'}")

    speed_rank = ranked.index("recent_speed_mps") + 1
    speed5min_rank = ranked.index("speed_avg_5min_mps") + 1
    print(f"\n3) recent_speed ne kadar etkili?")
    print(f"   recent_speed_mps (180sn): sira {speed_rank}/{len(ranked)}")
    print(f"   speed_avg_5min_mps (300sn): sira {speed5min_rank}/{len(ranked)}")

    hour_rank = ranked.index("hour_of_day") + 1
    dow_rank = ranked.index("day_of_week") + 1
    print(f"\n4) Saat etkisi olusuyor mu?")
    print(f"   hour_of_day: sira {hour_rank}/{len(ranked)}, day_of_week: sira {dow_rank}/{len(ranked)}")
    print(f"   {'Zayif etki - alt siralarda.' if hour_rank > len(ranked)-4 else 'Belirgin bir etki var.'}")

    line_rank = ranked.index("line_no") + 1
    stop_rank = ranked.index("target_stop_id") + 1
    print(f"\n5) Hat ve durak bilgisi ne kadar onemli?")
    print(f"   line_no: sira {line_rank}/{len(ranked)}, target_stop_id: sira {stop_rank}/{len(ranked)}")


def main():
    parser = argparse.ArgumentParser(description="Faz 3 SHAP analizi")
    parser.add_argument("--features", type=str, required=True)
    args = parser.parse_args()

    df = load_features(args.features)
    _, _, test_df = split_dataframe(df)
    X_test, y_test = get_X_y(test_df)

    print(f"SHAP test seti: {len(X_test)} satir")

    xgb = XGBRegressor()
    xgb.load_model(str(Path(__file__).resolve().parent.parent.parent / "models" / "xgboost_eta_model.json"))
    xgb_result = compute_shap_summary(xgb, X_test, "XGBoost")

    cat = CatBoostRegressor()
    cat.load_model(str(Path(__file__).resolve().parent.parent.parent / "models" / "catboost_eta_model.cbm"))
    X_test_cat = X_test.copy()
    for c in CATEGORICAL_FEATURES:
        X_test_cat[c] = X_test_cat[c].astype(str)
    cat_result = compute_shap_summary(cat, X_test_cat, "CatBoost (final model)")

    answer_questions(xgb_result["mean_abs_shap"], cat_result["mean_abs_shap"])

    reports_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    out = {
        "xgboost_mean_abs_shap_sec": xgb_result["mean_abs_shap"],
        "catboost_mean_abs_shap_sec": cat_result["mean_abs_shap"],
        "test_n": len(X_test),
    }
    out_path = reports_dir / "shap-analysis.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nSHAP ozet kaydedildi: {out_path}")

    # Basit ozet bar grafik (matplotlib zaten requirements'ta)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        for ax, (name, importance) in zip(axes, [("XGBoost", xgb_result["mean_abs_shap"]),
                                                    ("CatBoost (final)", cat_result["mean_abs_shap"])]):
            feats = list(importance.keys())
            vals = [v / 60 for v in importance.values()]
            ax.barh(feats[::-1], vals[::-1])
            ax.set_xlabel("Ortalama |SHAP| (dakika)")
            ax.set_title(name)
        plt.tight_layout()
        fig_path = reports_dir / "shap-feature-importance.png"
        plt.savefig(fig_path, dpi=120)
        print(f"Grafik kaydedildi: {fig_path}")
    except Exception as e:
        print(f"Grafik kaydedilemedi (kritik degil): {e}")


if __name__ == "__main__":
    main()
