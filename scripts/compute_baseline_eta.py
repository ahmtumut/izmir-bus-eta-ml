"""
Faz 2 madde 9 (v2 - Supervisor duzeltmesi): Baseline ETA modelleri.

DEGISIKLIK: Baseline 2 (segment medyani) artik GERCEK leave-one-out
uyguluyor - bir ornegin tahmini hesaplanirken, o ornegin actual_eta
degeri KENDI segment medyanina KATILMIYOR. Bir segmentte sadece 1 ornek
varsa (leave-one-out sonrasi 0 tarihsel veri kalir), o ornek icin
Baseline 2 tahmini URETILEMEZ - atlanir, uydurma bir deger verilmez.

Not: Faz 3'te asil degerlendirme train/test ayrimiyla yapilacak; bu
script Faz 2 kapsaminda "en azindan leave-one-out" seviyesindeki
minimum duzeltmeyi saglar.

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
        return None
    return distance_remaining_m / recent_speed_mps


def baseline_segment_median_leave_one_out(sample_id, key, segment_actuals):
    """Bu ornegin actual_eta'sini HARIC tutarak segment medyanini hesaplar."""
    others = [(sid, val) for sid, val in segment_actuals[key] if sid != sample_id]
    if len(others) == 0:
        return None  # leave-one-out sonrasi tarihsel veri kalmadi
    return median(val for _, val in others)


def compute_metrics(errors):
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

    b1_errors = []
    b1_skipped_no_speed = 0

    segment_actuals = defaultdict(list)
    for (sid, vehicle_id, line_no, direction, stop_pk, actual_eta,
         dist_remaining, recent_speed, label_quality) in samples:
        segment_actuals[(line_no, direction, stop_pk)].append((sid, actual_eta))

    b2_errors = []
    b2_skipped_no_history = 0
    segment_sample_counts = {key: len(vals) for key, vals in segment_actuals.items()}

    for (sid, vehicle_id, line_no, direction, stop_pk, actual_eta,
         dist_remaining, recent_speed, label_quality) in samples:

        pred1 = baseline_speed_based(dist_remaining, recent_speed)
        if pred1 is None:
            b1_skipped_no_speed += 1
        else:
            b1_errors.append(pred1 - actual_eta)

        key = (line_no, direction, stop_pk)
        pred2 = baseline_segment_median_leave_one_out(sid, key, segment_actuals)
        if pred2 is None:
            b2_skipped_no_history += 1
        else:
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
    print("BASELINE 2: Hat-yon-durak bazli MEDIAN actual_eta (LEAVE-ONE-OUT)")
    print("=" * 60)
    m2 = compute_metrics(b2_errors)
    if m2:
        print(f"  n={m2['n']} (leave-one-out sonrasi tarihsel veri kalmadigi icin "
              f"{b2_skipped_no_history} ornek atlandi)")
        print(f"  MAE  = {m2['mae_sec']:.1f} sn ({m2['mae_sec']/60:.2f} dk)")
        print(f"  RMSE = {m2['rmse_sec']:.1f} sn ({m2['rmse_sec']/60:.2f} dk)")
        print(f"  +-2 dakika icinde dogru: %{m2['within_2min_pct']:.1f}")
    else:
        print(f"  Hicbir segmentte leave-one-out sonrasi tarihsel veri kalmadi "
              f"({b2_skipped_no_history} ornegin tumu atlandi) - baseline uretilemedi. "
              f"Bu, veri setinin kucuklugunun (cogu segmentte n=1) dogrudan bir sonucu.")

    print("\nSegment basina ornek sayisi (kucuk n = leave-one-out'ta veri kalmayabilir):")
    for key, count in sorted(segment_sample_counts.items()):
        flag = "  <-- n=1: leave-one-out'ta bu segment icin HICBIR tahmin uretilemez" if count < 2 else ""
        print(f"  Hat {key[0]}, Yon {key[1]}, Durak_pk {key[2]}: n={count}{flag}")

    print("\n" + "=" * 60)
    print("SINIRLAMALAR")
    print("=" * 60)
    print("- Veri seti kucuk - bu sonuclar istatistiksel olarak guvenilir degil,")
    print("  pipeline'in uctan uca calistigini gostermek icin bir ilk deneme.")
    print("- Baseline 2 artik leave-one-out uyguluyor: bir ornegin kendi degeri")
    print("  kendi tahminine KATILMIYOR. n=1 olan segmentlerde tahmin uretilemiyor")
    print("  (uydurma deger verilmiyor, ornek atlanip acikca raporlaniyor).")
    print("- Faz 3'te asil degerlendirme train/test ayrimiyla yapilacak; bu script")
    print("  sadece Faz 2 kapsaminda 'ayni ornegi kendi tahmininde kullanmama'")
    print("  minimum kuralini saglar.")

    return m1, m2


if __name__ == "__main__":
    conn = db_storage.get_connection()
    run_baselines(conn)
    conn.close()
