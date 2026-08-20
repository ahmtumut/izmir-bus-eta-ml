"""Faz 4: model performans dashboard'u icin endpoint'ler.

Faz 3'te uretilen metrikleri statik bir JSON/rapor dosyasindan okumak yerine,
DB'den (eta_training_samples + vehicle_observations) CANLI olarak feature
dataframe'i kurup (app.ml.features.build_feature_dataframe - egitimdeki
BIREBIR ayni sorgu mantigi) baseline'lari ve iki modeli o dataframe uzerinde
yeniden degerlendirir. Feature dataframe kurulumu N=~15k satir icin agirlikli
bir islem (satir basina 2 ek DB sorgusu) - o yuzden process icinde bir kez
hesaplanip bellekte cache'lenir, sonraki istekler cache'ten hizlica doner.
"""
import time

import numpy as np
from catboost import CatBoostRegressor
from fastapi import APIRouter
from xgboost import XGBRegressor

from app.ml.baselines import baseline_distance_speed_predict, baseline_historical_median_predict, FALLBACK_MIN_SPEED_MPS
from app.ml.dataset import MODEL_FEATURE_COLUMNS, CATEGORICAL_FEATURES, split_dataframe
from app.ml.evaluate import compute_metrics, metrics_by_group, eta_range_bucket
from app.ml.features import build_feature_dataframe, build_out_of_sample_feature_dataframe
from app.storage import db_storage

router = APIRouter(prefix="/api/model", tags=["model"])

MODELS_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "models"

_cache: dict = {}


def _load_feature_df():
    """DB'den TEXT gelen line_no/target_stop_id, egitim zamanindaki CSV'de
    (dataset.py -> load_features) int64 idi - XGBoost'un native categorical
    kodlamasi egitim/tahmin arasinda AYNI kategori dtype'ini bekliyor, yoksa
    hata veriyor (kategori indeksleri eslesmiyor). Bu yuzden once int'e,
    sonra category'ye cevriliyor - CSV'deki ile birebir ayni temsil."""
    if "df" not in _cache:
        conn = db_storage.get_connection()
        try:
            df = build_feature_dataframe(conn)
        finally:
            conn.close()
        df["line_no"] = df["line_no"].astype(int)
        df["target_stop_id"] = df["target_stop_id"].astype(int)
        df["direction"] = df["direction"].astype(int)
        for col in CATEGORICAL_FEATURES:
            df[col] = df[col].astype("category")
        _cache["df"] = df
    return _cache["df"]


def _predict_xgboost(model, X):
    """XGBoost enable_categorical=True ile egitildi - pandas 'category' dtype bekliyor."""
    X = X.copy()
    for col in CATEGORICAL_FEATURES:
        X[col] = X[col].astype("category")
    return model.predict(X)


def _predict_catboost(model, X):
    """CatBoost kategorik kolonlari string olarak bekliyor (train_catboost.py ile tutarli)."""
    X = X.copy()
    for col in CATEGORICAL_FEATURES:
        X[col] = X[col].astype(str)
    return model.predict(X)


def _load_models():
    if "xgb" not in _cache:
        xgb = XGBRegressor()
        xgb.load_model(str(MODELS_DIR / "xgboost_eta_model.json"))
        _cache["xgb"] = xgb
    if "cat" not in _cache:
        cat = CatBoostRegressor()
        cat.load_model(str(MODELS_DIR / "catboost_eta_model.cbm"))
        _cache["cat"] = cat
    return _cache["xgb"], _cache["cat"]


def _clean_metrics(m: dict) -> dict:
    """NaN/Inf -> None (JSON'da temsil edilemiyor)."""
    out = {}
    for k, v in m.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            out[k] = None
        else:
            out[k] = v
    return out


def _breakdown(df, y_true_col, pred_col, group_col) -> dict:
    grouped = metrics_by_group(df, y_true_col, pred_col, group_col)
    return {str(idx): _clean_metrics(row.to_dict()) for idx, row in grouped.iterrows()}


@router.get("/metrics")
def get_model_metrics():
    df = _load_feature_df()
    train_df, val_df, test_df = split_dataframe(df)
    xgb, cat = _load_models()

    fallback_speed = train_df["recent_speed_mps"].dropna()
    fallback_speed = fallback_speed[fallback_speed > 0].mean()
    if not np.isfinite(fallback_speed):
        fallback_speed = 3.0  # ~10.8 km/h, sehir ici otobus icin makul bir alt sinir

    pred_b1 = baseline_distance_speed_predict(test_df, fallback_speed)
    pred_b2 = baseline_historical_median_predict(train_df, test_df)

    X_test = test_df[MODEL_FEATURE_COLUMNS]
    pred_xgb = _predict_xgboost(xgb, X_test)
    pred_cat = _predict_catboost(cat, X_test)

    y_true = test_df["actual_eta_seconds"]
    comparison = {
        "distance_speed_baseline": _clean_metrics(compute_metrics(y_true, pred_b1)),
        "historical_median_baseline": _clean_metrics(compute_metrics(y_true, pred_b2)),
        "xgboost": _clean_metrics(compute_metrics(y_true, pred_xgb)),
        "catboost": _clean_metrics(compute_metrics(y_true, pred_cat)),
    }

    test_df = test_df.copy()
    test_df["pred_catboost"] = pred_cat
    test_df["eta_range"] = eta_range_bucket(test_df["actual_eta_seconds"])

    breakdowns = {
        "by_line_no": _breakdown(test_df, "actual_eta_seconds", "pred_catboost", "line_no"),
        "by_direction": _breakdown(test_df, "actual_eta_seconds", "pred_catboost", "direction"),
        "by_eta_range": _breakdown(test_df, "actual_eta_seconds", "pred_catboost", "eta_range"),
        "by_label_quality": _breakdown(test_df, "actual_eta_seconds", "pred_catboost", "label_quality"),
    }

    # Tahmin hata gorsellestirmesi (dashboard scatter) icin: test setinden
    # (gercek dk, tahmin dk) ciftlerinin bir orneklemi - tum test setini
    # (binlerce nokta) gondermek yerine, gorsel olarak yeterli ama makul
    # boyutta bir orneklem (sabit seed - her istekte AYNI nokta kumesi
    # donsun, grafik "titremesin").
    sample_n = min(600, len(test_df))
    sample_df = test_df.sample(n=sample_n, random_state=42) if sample_n > 0 else test_df
    scatter_sample = [
        {"actual_min": round(a / 60, 2), "predicted_min": round(p / 60, 2)}
        for a, p in zip(sample_df["actual_eta_seconds"], sample_df["pred_catboost"])
    ]

    return {
        "test_n": len(test_df),
        "train_n": len(train_df),
        "validation_n": len(val_df),
        "comparison": comparison,
        "breakdowns_catboost": breakdowns,
        "selected_model": "catboost",
        "scatter_sample_catboost": scatter_sample,
    }


@router.get("/live-performance")
def get_live_model_performance():
    """Faz 4: train/validation/test split'i DONDURULDUKTEN SONRA toplanan
    (modelin hicbir egitim/degerlendirme asamasinda GORMEDIGI) taze veride
    CatBoost'un GERCEK performansini olcer - "model production'da ne kadar
    iyi calisiyor" sorusuna somut, surekli guncellenen bir cevap. /metrics
    endpoint'indeki sabit test seti SONUCLARINDAN FARKLI: o, model secimi
    icin BIR KEZ dondurulmus bir test seti; bu ise zaman icinde BUYUYEN,
    gercekten hic goruumemis bir veri akisi."""
    now = time.time()
    cached = _cache.get("live_perf")
    if cached and cached["_fresh_until"] > now:
        return cached["data"]

    conn = db_storage.get_connection()
    try:
        df = build_out_of_sample_feature_dataframe(conn)
    finally:
        conn.close()

    if df.empty:
        result = {
            "n": 0,
            "message": "Henuz train/validation/test split'inden sonra toplanmis "
                       "yeterli veri yok (arrival_events + eta_training_samples "
                       "uretilmemis olabilir).",
        }
        _cache["live_perf"] = {"data": result, "_fresh_until": now + 60}
        return result

    df["line_no"] = df["line_no"].astype(int)
    df["target_stop_id"] = df["target_stop_id"].astype(int)
    df["direction"] = df["direction"].astype(int)
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("category")

    _, cat = _load_models()
    X = df[MODEL_FEATURE_COLUMNS]
    pred = _predict_catboost(cat, X)
    y_true = df["actual_eta_seconds"]

    metrics = _clean_metrics(compute_metrics(y_true, pred))

    df = df.copy()
    df["pred_catboost"] = pred
    df["eta_range"] = eta_range_bucket(df["actual_eta_seconds"])
    breakdowns = {
        "by_line_no": _breakdown(df, "actual_eta_seconds", "pred_catboost", "line_no"),
        "by_eta_range": _breakdown(df, "actual_eta_seconds", "pred_catboost", "eta_range"),
        "by_label_quality": _breakdown(df, "actual_eta_seconds", "pred_catboost", "label_quality"),
    }

    result = {
        "n": len(df),
        "date_range": {
            "from": df["observed_at"].min().isoformat(),
            "to": df["observed_at"].max().isoformat(),
        },
        "metrics": metrics,
        "breakdowns": breakdowns,
        "note": "Bu metrikler, train/validation/test split'i dondurulduktan SONRA "
                "toplanan ve modelin hicbir asamada gormedigi veriler uzerinde "
                "hesaplandi - gercek (out-of-sample) canli performans.",
    }
    # 5 dakika cache - her dashboard yenilemesinde 3000 satirlik feature
    # dataframe'i (satir basina 2 ek DB sorgusu) yeniden kurmamak icin.
    _cache["live_perf"] = {"data": result, "_fresh_until": now + 300}
    return result


@router.get("/feature-importance")
def get_feature_importance():
    if "shap" in _cache:
        return _cache["shap"]

    import shap

    df = _load_feature_df()
    _, _, test_df = split_dataframe(df)
    xgb, cat = _load_models()

    X_test = test_df[MODEL_FEATURE_COLUMNS]

    xgb_explainer = shap.TreeExplainer(xgb)
    xgb_shap = xgb_explainer.shap_values(X_test)
    xgb_importance = dict(zip(MODEL_FEATURE_COLUMNS, (np.abs(xgb_shap).mean(axis=0) / 60).tolist()))

    X_test_cat = X_test.copy()
    for c in CATEGORICAL_FEATURES:
        X_test_cat[c] = X_test_cat[c].astype(str)
    cat_explainer = shap.TreeExplainer(cat)
    cat_shap = cat_explainer.shap_values(X_test_cat)
    cat_importance = dict(zip(MODEL_FEATURE_COLUMNS, (np.abs(cat_shap).mean(axis=0) / 60).tolist()))

    xgb_importance = dict(sorted(xgb_importance.items(), key=lambda kv: kv[1], reverse=True))
    cat_importance = dict(sorted(cat_importance.items(), key=lambda kv: kv[1], reverse=True))

    result = {
        "test_n": len(X_test),
        "xgboost_mean_abs_shap_min": xgb_importance,
        "catboost_mean_abs_shap_min": cat_importance,
        "unit": "dakika (ortalama |SHAP degeri|, hedef degiskendeki etki buyuklugu)",
    }
    _cache["shap"] = result
    return result
