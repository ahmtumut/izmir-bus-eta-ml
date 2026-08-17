"""
Faz 3: CatBoost Regressor egitimi (CPU, task_type=CPU).

line_no, direction, target_stop_id CatBoost'a native kategorik feature
olarak verilir (cat_features) - one-hot/label encoding YAPILMAZ, CatBoost
bunu kendi ordered target-statistics yontemiyle isler. XGBoost'la anlamli
bir karsilastirma saglamasi beklenen budur (gorev talimati).

Hiperparametre aramasi ve degerlendirme mantigi train_xgboost.py ile
BIREBIR AYNI prensiplere uyar: randomized search sadece train+validation'da,
test'e hic dokunulmaz.

Kullanim:
    python -m app.ml.train_catboost --features data/processed/eta_features_20260817.csv
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from catboost import CatBoostRegressor, Pool
from sklearn.model_selection import ParameterSampler

from app.ml.dataset import load_features, split_dataframe, get_X_y, MODEL_FEATURE_COLUMNS, CATEGORICAL_FEATURES
from app.ml.evaluate import compute_metrics, metrics_by_group, eta_range_bucket, format_metrics_table

N_JOBS = 12
N_SEARCH_ITER = 20
EARLY_STOPPING_ROUNDS = 30
RANDOM_STATE = 42

PARAM_DISTRIBUTIONS = {
    "depth": [4, 5, 6, 7, 8],
    "learning_rate": [0.01, 0.03, 0.05, 0.08, 0.1],
    "l2_leaf_reg": [1, 3, 5, 10],
    "subsample": [0.7, 0.8, 0.9, 1.0],
    "random_strength": [0.5, 1, 2],
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


def make_pool(X, y):
    X = X.copy()
    for col in CATEGORICAL_FEATURES:
        X[col] = X[col].astype(str)
    return Pool(X, y, cat_features=CATEGORICAL_FEATURES)


def random_search(X_train, y_train, X_val, y_val):
    sampler = list(ParameterSampler(PARAM_DISTRIBUTIONS, n_iter=N_SEARCH_ITER, random_state=RANDOM_STATE))
    train_pool = make_pool(X_train, y_train)
    val_pool = make_pool(X_val, y_val)
    results = []

    for i, params in enumerate(sampler):
        model = CatBoostRegressor(
            task_type="CPU", thread_count=N_JOBS, iterations=1000,
            early_stopping_rounds=EARLY_STOPPING_ROUNDS,
            random_state=RANDOM_STATE, loss_function="MAE",
            verbose=False,
            **params,
        )
        model.fit(train_pool, eval_set=val_pool, use_best_model=True)
        val_pred = model.predict(val_pool)
        val_metrics = compute_metrics(y_val, val_pred)
        results.append({
            "params": params,
            "best_iteration": int(model.get_best_iteration()) if model.get_best_iteration() is not None else model.tree_count_,
            "val_mae_min": val_metrics["mae_min"],
        })
        print(f"  [{i+1}/{len(sampler)}] val_mae={val_metrics['mae_min']:.3f}dk "
              f"iter={results[-1]['best_iteration']} params={params}")

    results.sort(key=lambda r: r["val_mae_min"])
    return results


def main():
    parser = argparse.ArgumentParser(description="Faz 3 CatBoost egitimi")
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
          f"iterations(best)={best['best_iteration']}")

    final_model = CatBoostRegressor(
        task_type="CPU", thread_count=N_JOBS, iterations=1000,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        random_state=RANDOM_STATE, loss_function="MAE",
        verbose=False,
        **best["params"],
    )
    train_pool = make_pool(X_train, y_train)
    val_pool = make_pool(X_val, y_val)
    test_pool = make_pool(X_test, y_test)

    t_train_start = datetime.now()
    final_model.fit(train_pool, eval_set=val_pool, use_best_model=True)
    train_seconds = (datetime.now() - t_train_start).total_seconds()

    t_infer_start = datetime.now()
    test_pred = final_model.predict(test_pool)
    infer_seconds_per_row = (datetime.now() - t_infer_start).total_seconds() / max(len(X_test), 1)

    train_metrics = compute_metrics(y_train, final_model.predict(train_pool))
    val_metrics = compute_metrics(y_val, final_model.predict(val_pool))
    test_metrics = compute_metrics(y_test, test_pred)

    print("\n" + "=" * 70)
    print("CATBOOST SONUCLARI")
    print("=" * 70)
    print(format_metrics_table({"train": train_metrics, "validation": val_metrics, "test": test_metrics}))

    test_df = test_df.copy()
    test_df["y_pred_sec"] = test_pred
    test_df["eta_range"] = eta_range_bucket(test_df["actual_eta_seconds"])

    breakdowns = {}
    for group_col in ["line_no", "direction", "eta_range", "label_quality"]:
        bdf = metrics_by_group(test_df, "actual_eta_seconds", "y_pred_sec", group_col)
        breakdowns[group_col] = bdf
        print(f"\n--- Test seti - {group_col} bazinda ---")
        print(bdf.to_string())

    importance = dict(zip(MODEL_FEATURE_COLUMNS, final_model.get_feature_importance(train_pool).tolist()))
    importance_sorted = dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))
    print("\n--- Feature importance ---")
    for feat, imp in importance_sorted.items():
        print(f"  {feat}: {imp:.4f}")

    models_dir = Path(__file__).resolve().parent.parent.parent / "models"
    reports_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    models_dir.mkdir(exist_ok=True)
    reports_dir.mkdir(exist_ok=True)

    model_path = models_dir / "catboost_eta_model.cbm"
    final_model.save_model(str(model_path))

    metadata = {
        "model_type": "CatBoostRegressor",
        "training_date_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_sha": get_git_sha(),
        "dataset_path": str(args.features),
        "dataset_sha256": file_sha256(args.features),
        "feature_columns": MODEL_FEATURE_COLUMNS,
        "categorical_features": CATEGORICAL_FEATURES,
        "target_column": "actual_eta_seconds",
        "best_hyperparameters": best["params"],
        "best_iteration": best["best_iteration"],
        "search_candidates_evaluated": len(results),
        "search_seconds": search_seconds,
        "final_train_seconds": train_seconds,
        "inference_seconds_per_row": infer_seconds_per_row,
        "n_jobs": N_JOBS,
        "device": "cpu",
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

    metrics_path = reports_dir / "catboost-metrics.json"
    metrics_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")

    print(f"\nModel kaydedildi: {model_path}")
    print(f"Metadata/metrics kaydedildi: {metrics_path}")


if __name__ == "__main__":
    main()
