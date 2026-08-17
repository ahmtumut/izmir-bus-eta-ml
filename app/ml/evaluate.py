"""
Faz 3: Ortak degerlendirme metrikleri. Baseline'lar ve XGBoost/CatBoost
sonuclari AYNI fonksiyonlarla degerlendirilir ki karsilastirma adil olsun.

Ana karar metrigi MAE (dakika) - kullanici perspektifinden en anlasilir.
MAPE kullanilmiyor (gorev talimati: ETA sifira yaklastikca yaniltici olur).
"""
import numpy as np
import pandas as pd

ETA_RANGE_BINS = [0, 5, 10, 20, np.inf]
ETA_RANGE_LABELS = ["0-5dk", "5-10dk", "10-20dk", "20+dk"]


def compute_metrics(y_true_sec, y_pred_sec) -> dict:
    """y_true_sec, y_pred_sec: saniye cinsinden. Metrikler DAKIKA cinsinden
    raporlanir (kullanici perspektifi icin)."""
    y_true = np.asarray(y_true_sec, dtype=float) / 60.0
    y_pred = np.asarray(y_pred_sec, dtype=float) / 60.0
    err = y_pred - y_true
    abs_err = np.abs(err)

    n = len(y_true)
    if n == 0:
        return {"n": 0}

    return {
        "n": n,
        "mae_min": float(np.mean(abs_err)),
        "rmse_min": float(np.sqrt(np.mean(err ** 2))),
        "median_ae_min": float(np.median(abs_err)),
        "within_1min_pct": float(np.mean(abs_err <= 1.0) * 100),
        "within_2min_pct": float(np.mean(abs_err <= 2.0) * 100),
        "within_3min_pct": float(np.mean(abs_err <= 3.0) * 100),
    }


def eta_range_bucket(y_true_sec) -> pd.Series:
    y_true_min = pd.Series(np.asarray(y_true_sec, dtype=float) / 60.0)
    return pd.cut(y_true_min, bins=ETA_RANGE_BINS, labels=ETA_RANGE_LABELS, right=False)


def metrics_by_group(df: pd.DataFrame, y_true_col: str, y_pred_col: str, group_col: str) -> pd.DataFrame:
    """df icinde y_true_col, y_pred_col ve group_col bulunmali. Her grup icin
    compute_metrics uygulanir, tek bir DataFrame olarak doner."""
    rows = []
    for group_value, sub in df.groupby(group_col, observed=True):
        m = compute_metrics(sub[y_true_col], sub[y_pred_col])
        m[group_col] = group_value
        rows.append(m)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).set_index(group_col)
    return out.sort_index()


def format_metrics_table(metrics_by_model: dict) -> str:
    """metrics_by_model: {model_adi: metrics_dict}. Karsilastirma tablosu
    (Model / MAE / RMSE / ±2dk) - gorev talimatindaki final tablo formati."""
    lines = []
    lines.append(f"{'Model':<22} {'MAE(dk)':>8} {'RMSE(dk)':>9} {'MedAE(dk)':>10} "
                  f"{'±1dk%':>7} {'±2dk%':>7} {'±3dk%':>7} {'n':>6}")
    lines.append("-" * 90)
    for name, m in metrics_by_model.items():
        if m.get("n", 0) == 0:
            lines.append(f"{name:<22} {'(veri yok)':>8}")
            continue
        lines.append(
            f"{name:<22} {m['mae_min']:>8.2f} {m['rmse_min']:>9.2f} {m['median_ae_min']:>10.2f} "
            f"{m['within_1min_pct']:>6.1f}% {m['within_2min_pct']:>6.1f}% {m['within_3min_pct']:>6.1f}% "
            f"{m['n']:>6}"
        )
    return "\n".join(lines)
