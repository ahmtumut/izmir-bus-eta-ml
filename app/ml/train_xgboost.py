"""
Faz 3: XGBoost Regressor egitimi (CPU, tree_method=hist).

- GPU KULLANILMIYOR (device=cpu, gorev talimati).
- Hiperparametre aramasi: kucuk, kontrollu bir RANDOMIZED search - k-fold CV
  DEGIL (zamansal split'te k-fold, train/val arasinda zamansal siziniti
  yaratir). Her aday, TRAIN'de fit edilir, VALIDATION'da early-stopping +
  skorlanir (gorev talimati: "Model secimi ve hiperparametre ayari yalniz
  train + validation uzerinde yapilmali"). TEST SETINE bu asamada HIC
  dokunulmuyor.
- Thread: n_jobs=12 (gorev talimati: 12-16 thread, 20'nin tamamini verme).

Kullanim:
    python -m app.ml.train_xgboost --features data/processed/eta_features_20260817.csv
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from sklearn.model_selection import ParameterSampler
from xgboost import XGBRegressor

from app.ml.dataset import load_features, split_dataframe, get_X_y, MODEL_FEATURE_COLUMNS
from app.ml.evaluate import compute_metrics, metrics_by_group, eta_range_bucket, format_metrics_table

N_JOBS = 12
N_SEARCH_ITER = 20
EARLY_STOPPING_ROUNDS = 30
RANDOM_STATE = 42

PARAM_DISTRIBUTIONS = {
    "max_depth": [3, 4, 5, 6],
    "learning_rate": [0.01, 0.03, 0.05, 0.08, 0.1],
    "subsample": [0.7, 0.8, 0.9, 1.0],
    "colsample_bytree": [0.6, 0.7, 0.8, 1.0],
    "min_child_weight": [1, 3, 5],
    "reg_lambda": [1, 2, 5, 10],
}


def get_git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent
        ).decode().strip()
    except Exception:
        return "unknown"


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def random_search(X_train, y_train, X_val, y_val):
    sampler = list(ParameterSampler(PARAM_DISTRIBUTIONS, n_iter=N_SEARCH_ITER, random_state=RANDOM_STATE))
    results = []

    for i, params in enumerate(sampler):
        model = XGBRegressor(
            tree_method="hist", device="cpu", n_jobs=N_JOBS,
            n_estimators=1000, early_stopping_rounds=EARLY_STOPPING_ROUNDS,
            enable_categorical=True, random_state=RANDOM_STATE,
            eval_metric="mae",
            **params,
        )
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        val_pred = model.predict(X_val)
        val_metrics = compute_metrics(y_val, val_pred)
        results.append({
            "params": params,
            "best_iteration": int(model.best_iteration) if model.best_iteration is not None else model.n_estimators,
            "val_mae_min": val_metrics["mae_min"],
        })
        print(f"  [{i+1}/{len(sampler)}] val_mae={val_metrics['mae_min']:.3f}dk "
              f"iter={results[-1]['best_iteration']} params={params}")

    results.sort(key=lambda r: r["val_mae_min"])
    return results


def main():
    parser = argparse.ArgumentParser(description="Faz 3 XGBoost egitimi")
    parser.add_argument("--features", type=str, required=True)
    parser.add_argument("--search-iter", type=int, default=N_SEARCH_ITER)
    args = parser.parse_args()

    df = load_features(args.features)
    train_df, val_df, test_df = split_dataframe(df)
    print(f"train={len(train_df)}, validation={len(val_df)}, test={len(test_df)}")

    X_train, y_train = get_X_y(train_df)
    X_val, y_val = get_X_y(val_df)
    X_test, y_test = get_X_y(test_df)

    print(f"\nRandomized search basliyor ({args.search_iter} aday, sadece train+validation)...")
    t_search_start = datetime.now()
    results = random_search(X_train, y_train, X_val, y_val)
    search_seconds = (datetime.now() - t_search_start).total_seconds()

    best = results[0]
    print(f"\nEn iyi aday: val_mae={best['val_mae_min']:.3f}dk, params={best['params']}, "
          f"n_estimators(best_iteration)={best['best_iteration']}")

    # Final model: en iyi hiperparametrelerle, ayni early-stopping mantigiyla
    # train'de fit edilir (best_iteration'i validation belirledi, modelin
    # kendisi hala sadece train'i gormus olur - test'e hic dokunulmadi).
    final_model = XGBRegressor(
        tree_method="hist", device="cpu", n_jobs=N_JOBS,
        n_estimators=1000, early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        enable_categorical=True, random_state=RANDOM_STATE,
        eval_metric="mae",
        **best["params"],
    )
    t_train_start = datetime.now()
    final_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    train_seconds = (datetime.now() - t_train_start).total_seconds()

    # --- Degerlendirme (train/val/test, hepsi ayni metriklerle) ---
    t_infer_start = datetime.now()
    test_pred = final_model.predict(X_test)
    infer_seconds_per_row = (datetime.now() - t_infer_start).total_seconds() / max(len(X_test), 1)

    train_metrics = compute_metrics(y_train, final_model.predict(X_train))
    val_metrics = compute_metrics(y_val, final_model.predict(X_val))
    test_metrics = compute_metrics(y_test, test_pred)

    print("\n" + "=" * 70)
    print("XGBOOST SONUCLARI")
    print("=" * 70)
    print(format_metrics_table({"train": train_metrics, "validation": val_metrics, "test": test_metrics}))

    # Test seti kirilimlari
    test_df = test_df.copy()
    test_df["y_pred_sec"] = test_pred
    test_df["eta_range"] = eta_range_bucket(test_df["actual_eta_seconds"])

    breakdowns = {}
    for group_col in ["line_no", "direction", "eta_range", "label_quality"]:
        bdf = metrics_by_group(test_df, "actual_eta_seconds", "y_pred_sec", group_col)
        breakdowns[group_col] = bdf
        print(f"\n--- Test seti - {group_col} bazinda ---")
        print(bdf.to_string())

    # --- Feature importance ---
    importance = dict(zip(MODEL_FEATURE_COLUMNS, final_model.feature_importances_.tolist()))
    importance_sorted = dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))
    print("\n--- Feature importance ---")
    for feat, imp in importance_sorted.items():
        print(f"  {feat}: {imp:.4f}")

    # --- Artifact'leri kaydet ---
    models_dir = Path(__file__).resolve().parent.parent.parent / "models"
    reports_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    models_dir.mkdir(exist_ok=True)
    reports_dir.mkdir(exist_ok=True)

    model_path = models_dir / "xgboost_eta_model.json"
    final_model.save_model(str(model_path))

    metadata = {
        "model_type": "XGBRegressor",
        "training_date_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_sha": get_git_sha(),
        "dataset_path": str(args.features),
        "dataset_sha256": file_sha256(args.features),
        "feature_columns": MODEL_FEATURE_COLUMNS,
        "target_column": "actual_eta_seconds",
        "best_hyperparameters": best["params"],
        "best_iteration": best["best_iteration"],
        "search_candidates_evaluated": len(results),
        "search_seconds": search_seconds,
        "final_train_seconds": train_seconds,
        "inference_seconds_per_row": infer_seconds_per_row,
        "n_jobs": N_JOBS,
        "device": "cpu",
        "tree_method": "hist",
        "split_sizes": {"train": len(train_df), "validation": len(val_df), "test": len(test_df)},
        "split_date_ranges": {
            split_name: {
                "min": str(d["observed_at"].min()), "max": str(d["observed_at"].max()),
            }
            for split_name, d in [("train", train_df), ("validation", val_df), ("test", test_df)]
        },
        "metrics": {"train": train_metrics, "validation": val_metrics, "test": test_metrics},
        "test_breakdowns": {k: v.to_dict(orient="index") for k, v in breakdowns.items()},
        "feature_importance": importance_sorted,
    }

    metrics_path = reports_dir / "xgboost-metrics.json"
    metrics_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")

    print(f"\nModel kaydedildi: {model_path}")
    print(f"Metadata/metrics kaydedildi: {metrics_path}")


if __name__ == "__main__":
    main()
