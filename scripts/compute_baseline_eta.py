"""
Faz 2 madde 9: Baseline ETA modelleri.

Iki basit baseline:
1. distance_remaining_m / son gecerli ortalama hiz (recent_speed_mps)
2. Hat-yon-durak bazli MEDIAN actual_eta_seconds (o segment icin daha once
   gorulen ornekler - "tarihsel veri" burada ayni run icindeki diger
   orneklerdir, kucuk bir veri setiyle calisildigi acikca belirtiliyor)

Ikisi de gercek actual_eta_seconds ile karsilastirilir: MAE, RMSE,
+-2 dakika dogruluk orani raporlanir. Sonuclar kotu olsa bile
SAKLANMAZ/DEGISTIRILMEZ - oldugu gibi raporlanir (madde 9 geregi).

Kullanim:
    python scripts/compute_baseline_eta.py
"""
import sys
import math
from collections import defaultdict
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage


def fetch_samples(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, vehicle_id, line_no, direction, target_stop_id,
                   actual_eta_seconds, distance_remaining_m, recent_speed_mps,
                   label_quality
            FROM eta_training_samples
            ORDER BY line_no, direction, target_stop_id, observed_at
            """
        )
        return cur.fetchall()


def baseline_speed_based(distance_remaining_m, recent_speed_mps):
    if recent_speed_mps is None or recent_speed_mps <= 0.5:
        return None  # anlamli bir hiz tahmini yok - baseline uretilemiyor
    return distance_remaining_m / recent_speed_mps


def compute_metrics(errors):
    """errors: (predicted - actual) listesi (saniye)."""
    n = len(errors)
    if n == 0:
        return None
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e ** 2 for e in errors) / n)
    within_2min = sum(1 for e in errors if abs(e) <= 120) / n * 100
    return {"n": n, "mae_sec": mae, "rmse_sec": rmse, "within_2min_pct": within_2min}


def run_baselines(conn):
    samples = fetch_samples(conn)
    print(f"{len(samples)} eta_training_samples bulundu.\n")

    # --- Baseline 1: mesafe / son hiz ---
    b1_errors = []
    b1_skipped_no_speed = 0

    # --- Baseline 2: segment medyani (line_no, direction, target_stop_id) ---
    segment_actuals = defaultdict(list)
    for (sid, vehicle_id, line_no, direction, stop_pk, actual_eta,
         dist_remaining, recent_speed, label_quality) in samples:
        segment_actuals[(line_no, direction, stop_pk)].append(actual_eta)

    segment_medians = {
        key: median(vals) for key, vals in segment_actuals.items()
    }

    b2_errors = []
    segment_sample_counts = {key: len(vals) for key, vals in segment_actuals.items()}

    for (sid, vehicle_id, line_no, direction, stop_pk, actual_eta,
         dist_remaining, recent_speed, label_quality) in samples:

        pred1 = baseline_speed_based(dist_remaining, recent_speed)
        if pred1 is None:
            b1_skipped_no_speed += 1
        else:
            b1_errors.append(pred1 - actual_eta)

        # Segment medyanini "kendi ornegini haric tutarak" hesaplamak daha
        # dogru olurdu (leave-one-out), ama kucuk veri setinde bu asiri
        # karmasiklastirir - burada TUM segment medyani kullaniliyor ve
        # bu acikca iyimser bir tahmin olabilir, sinirlama olarak belirtiliyor.
        key = (line_no, direction, stop_pk)
        pred2 = segment_medians[key]
        b2_errors.append(pred2 - actual_eta)

    print("=" * 60)
    print("BASELINE 1: distance_remaining_m / recent_speed_mps")
    print("=" * 60)
    m1 = compute_metrics(b1_errors)
    if m1:
        print(f"  n={m1['n']} (hiz verisi olmadigi icin {b1_skipped_no_speed} ornek atlandi)")
        print(f"  MAE  = {m1['mae_sec']:.1f} sn ({m1['mae_sec']/60:.2f} dk)")
        print(f"  RMSE = {m1['rmse_sec']:.1f} sn ({m1['rmse_sec']/60:.2f} dk)")
        print(f"  +-2 dakika icinde dogru: %{m1['within_2min_pct']:.1f}")
    else:
        print("  Hicbir ornek icin hiz verisi yoktu - baseline uretilemedi.")

    print()
    print("=" * 60)
    print("BASELINE 2: Hat-yon-durak bazli MEDIAN actual_eta")
    print("=" * 60)
    m2 = compute_metrics(b2_errors)
    if m2:
        print(f"  n={m2['n']}")
        print(f"  MAE  = {m2['mae_sec']:.1f} sn ({m2['mae_sec']/60:.2f} dk)")
        print(f"  RMSE = {m2['rmse_sec']:.1f} sn ({m2['rmse_sec']/60:.2f} dk)")
        print(f"  +-2 dakika icinde dogru: %{m2['within_2min_pct']:.1f}")

    print("\nSegment basina ornek sayisi (kucuk n = guvenilmez medyan):")
    for key, count in sorted(segment_sample_counts.items()):
        flag = "  <-- DUSUK ORNEK SAYISI" if count < 5 else ""
        print(f"  Hat {key[0]}, Yon {key[1]}, Durak_pk {key[2]}: n={count}{flag}")

    print("\n" + "=" * 60)
    print("SINIRLAMALAR (acikca raporlaniyor, sonuclar degistirilmedi)")
    print("=" * 60)
    print("- Veri seti kucuk (60 dk / 12 arac / 94 ornek) - bu sonuclar")
    print("  ISTATISTIKSEL OLARAK GUVENILIR DEGIL, sadece pipeline'in uctan")
    print("  uca calistigini gostermek icin bir ilk deneme.")
    print("- Baseline 2, segment medyanini hesaplarken kendi test ornegini")
    print("  disarida birakmiyor (leave-one-out degil) - bu, gercek")
    print("  performansi OLDUGUNDAN IYI gosteriyor olabilir.")
    print("- label_quality dagilimi kontrol edilmeli; SILVER/REJECTED")
    print("  agirlikli bir set GOLD orneklerden daha az guvenilir sonuc verir.")

    return m1, m2


if __name__ == "__main__":
    conn = db_storage.get_connection()
    run_baselines(conn)
    conn.close()
