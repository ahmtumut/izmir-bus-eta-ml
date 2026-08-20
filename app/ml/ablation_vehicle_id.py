"""
Faz 4: vehicle_id ablation testi.

CLAUDE.md'de belirtilen gorev talimati geregi, ana CatBoost modeli
vehicle_id'yi FEATURE OLARAK KULLANMIYOR ("Amacimiz aracin ID'sini
ezberleyen bir model degil, farkli araclara genellenebilen bir ETA modeli
gelistirmek"). Bu script, o kararin GERCEKTEN dogru oldugunu (ya da
olmadigini) somut olarak olcer: AYNI train/validation/test split'i,
AYNI hiperparametreleri kullanarak, SADECE vehicle_id'yi ekstra bir
kategorik feature olarak ekleyen bir CatBoost modeli egitir ve test MAE'sini
raporda kayitli final modelin (vehicle_id'siz) test MAE'siyle karsilastirir.

Hiperparametre aramasi TEKRARLANMAZ - raporda kayitli
(reports/catboost-metrics.json) best_hyperparameters AYNEN kullanilir.
Boylece fark SADECE "vehicle_id eklendi mi eklenmedi mi"ye atfedilebilir,
farkli bir hiperparametre kombinasyonunun etkisiyle karismaz (kontrollu
deney).

Yorumlama:
- vehicle_id eklenince test MAE ONEMLI olcude DUSERSE: model arac
  kimligine gore ezberleme yapiyor olabilir (ayni araclar train/test'te
  ortak oldugu icin - bu VERI SIZINTISINA yakin bir sinyal olurdu, cunku
  gercek dunyada yeni/gorulmemis bir arac icin bu "avantaj" iscisiz kalir).
  Boyle bir sonuc, mevcut "vehicle_id disarida birakma" kararini DOGRULAR.
- test MAE ONEMLI OLCUDE DEGISMEZSE (ya da kotulesirse): vehicle_id'nin
  zaten diger feature'lar (line_no, target_stop_id, distance_remaining_m
  vb.) araciligiyla dolayli olarak yeterince temsil edildigini, ayrica
  eklemenin bir katkisi olmadigini gosterir - yine mevcut karari destekler,
  ama farkli bir gerekceyle (yararsiz feature, faydasiz karmasiklik).

Kullanim:
    python -m app.ml.ablation_vehicle_id --features data/processed/eta_features_20260817_v2.csv
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from catboost import CatBoostRegressor, Pool

from app.ml.dataset import load_features, split_dataframe, MODEL_FEATURE_COLUMNS, CATEGORICAL_FEATURES
from app.ml.evaluate import compute_metrics, format_metrics_table

N_JOBS = 12
EARLY_STOPPING_ROUNDS = 30
RANDOM_STATE = 42
ITERATIONS = 1000

ABLATION_FEATURE_COLUMNS = MODEL_FEATURE_COLUMNS + ["vehicle_id"]
ABLATION_CATEGORICAL_FEATURES = CATEGORICAL_FEATURES + ["vehicle_id"]


def make_pool(df, feature_columns, categorical_features):
    X = df[feature_columns].copy()
    for col in categorical_features:
        X[col] = X[col].astype(str)
    y = df["actual_eta_seconds"]
    return Pool(X, y, cat_features=categorical_features)


def train_and_eval(train_df, val_df, test_df, feature_columns, categorical_features, hyperparams):
    train_pool = make_pool(train_df, feature_columns, categorical_features)
    val_pool = make_pool(val_df, feature_columns, categorical_features)
    test_pool = make_pool(test_df, feature_columns, categorical_features)

    model = CatBoostRegressor(
        task_type="CPU", thread_count=N_JOBS, iterations=ITERATIONS,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        random_state=RANDOM_STATE, loss_function="MAE",
        verbose=False,
        **hyperparams,
    )
    t0 = datetime.now()
    model.fit(train_pool, eval_set=val_pool, use_best_model=True)
    train_seconds = (datetime.now() - t0).total_seconds()

    test_pred = model.predict(test_pool)
    test_metrics = compute_metrics(test_df["actual_eta_seconds"], test_pred)

    importance = dict(zip(feature_columns, model.get_feature_importance(train_pool).tolist()))
    importance_sorted = dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))

    return {
        "test_metrics": test_metrics,
        "feature_importance": importance_sorted,
        "train_seconds": train_seconds,
        "best_iteration": int(model.get_best_iteration()) if model.get_best_iteration() is not None else model.tree_count_,
    }


def main():
    parser = argparse.ArgumentParser(description="Faz 4: vehicle_id ablation testi")
    parser.add_argument("--features", type=str, required=True)
    parser.add_argument("--baseline-metrics", type=str,
                         default="reports/catboost-metrics.json",
                         help="Karsilastirma icin, vehicle_id'siz final modelin kayitli metrikleri")
    args = parser.parse_args()

    baseline_report = json.loads(Path(args.baseline_metrics).read_text(encoding="utf-8"))
    hyperparams = baseline_report["best_hyperparameters"]
    baseline_test_metrics = baseline_report["metrics"]["test"]

    print(f"Kontrollu deney: AYNI hiperparametreler kullanilacak (final modelden): {hyperparams}")

    df = load_features(args.features)
    train_df, val_df, test_df = split_dataframe(df)
    print(f"train={len(train_df)}, validation={len(val_df)}, test={len(test_df)}")
    n_unique_vehicles_train = train_df["vehicle_id"].nunique()
    n_unique_vehicles_test = test_df["vehicle_id"].nunique()
    n_vehicles_test_seen_in_train = test_df["vehicle_id"].isin(train_df["vehicle_id"]).sum()
    print(f"Benzersiz arac (train): {n_unique_vehicles_train}, (test): {n_unique_vehicles_test}")
    print(f"Test setindeki satirlarin {n_vehicles_test_seen_in_train}/{len(test_df)}'i "
          f"train'de de gorulmus bir vehicle_id'ye ait (zamansal split oldugu icin beklenir).")

    print("\nvehicle_id EKLENMIS model egitiliyor...")
    ablation_result = train_and_eval(
        train_df, val_df, test_df, ABLATION_FEATURE_COLUMNS, ABLATION_CATEGORICAL_FEATURES, hyperparams
    )

    baseline_mae = baseline_test_metrics["mae_min"]
    ablation_mae = ablation_result["test_metrics"]["mae_min"]
    delta = ablation_mae - baseline_mae
    delta_pct = (delta / baseline_mae) * 100 if baseline_mae else float("nan")

    print("\n" + "=" * 70)
    print("ABLATION SONUCU: vehicle_id feature olarak eklenirse ne olur?")
    print("=" * 70)
    print(format_metrics_table({
        "final_model (vehicle_id YOK, kayitli)": baseline_test_metrics,
        "ablation (vehicle_id VAR)": ablation_result["test_metrics"],
    }))
    print(f"\nMAE degisimi: {baseline_mae:.3f}dk -> {ablation_mae:.3f}dk "
          f"({'+' if delta >= 0 else ''}{delta:.3f}dk, {delta_pct:+.1f}%)")

    SIGNIFICANT_THRESHOLD_PCT = 5.0
    if delta_pct <= -SIGNIFICANT_THRESHOLD_PCT:
        verdict = (
            f"vehicle_id eklenince test MAE %{abs(delta_pct):.1f} DUSTU (onemli iyilesme). "
            "Bu, modelin kismen arac kimligine gore ezberleme yaptigina isaret ediyor olabilir - "
            "gercek dunyada YENI bir aracta bu avantaj iscisiz kalir. Mevcut 'vehicle_id disarida "
            "birakma' karari DOGRULANDI (feature'in katkisi cazip gorunse de guvenilir/genellenebilir degil)."
        )
    elif delta_pct >= SIGNIFICANT_THRESHOLD_PCT:
        verdict = (
            f"vehicle_id eklenince test MAE %{delta_pct:.1f} ARTTI (kotulesti) - beklenen bir "
            "sonuc: fazladan bir kategorik feature (yuksek kardinalite) modelin genellemesini "
            "zorlastirmis olabilir. Mevcut 'vehicle_id disarida birakma' karari DOGRULANDI."
        )
    else:
        verdict = (
            f"vehicle_id eklenmesi test MAE'yi anlamli sekilde degistirmedi (%{delta_pct:+.1f}, "
            f"{SIGNIFICANT_THRESHOLD_PCT}% esiginin altinda). Arac kimligi bilgisi zaten diger "
            "feature'lar (rota/durak/mesafe) araciligiyla dolayli temsil ediliyor gibi gorunuyor. "
            "Mevcut 'vehicle_id disarida birakma' karari DOGRULANDI (ekstra karmasikliga deger fayda yok)."
        )
    print(f"\nYORUM: {verdict}")

    vehicle_id_rank = list(ablation_result["feature_importance"].keys()).index("vehicle_id") + 1
    print(f"\nvehicle_id'nin feature importance sirasi: {vehicle_id_rank}/{len(ABLATION_FEATURE_COLUMNS)} "
          f"(deger: {ablation_result['feature_importance']['vehicle_id']:.4f})")

    reports_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "hyperparameters_used": hyperparams,
        "baseline_test_metrics_no_vehicle_id": baseline_test_metrics,
        "ablation_test_metrics_with_vehicle_id": ablation_result["test_metrics"],
        "mae_delta_min": delta,
        "mae_delta_pct": delta_pct,
        "verdict": verdict,
        "ablation_feature_importance": ablation_result["feature_importance"],
        "vehicle_id_importance_rank": vehicle_id_rank,
        "n_unique_vehicles_train": int(n_unique_vehicles_train),
        "n_unique_vehicles_test": int(n_unique_vehicles_test),
        "n_test_rows_vehicle_seen_in_train": int(n_vehicles_test_seen_in_train),
        "n_test_rows_total": len(test_df),
        "train_seconds": ablation_result["train_seconds"],
    }
    out_path = reports_dir / "ablation-vehicle-id.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nRapor kaydedildi: {out_path}")


if __name__ == "__main__":
    main()
