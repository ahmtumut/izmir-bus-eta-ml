"""
Faz 2 madde 1: GPS belirsizligi arastirmasi (v2 - nokta bazli).

v1'deki arac-geneli siniflandirma cok gevsekti: bir arac gozlem penceresinde
TEK BIR KEZ farkli koordinat aldiysa bile tum arac CURRENT_POSITION
sayiliyordu, bu da uzun donuk bloklari maskeliyordu.

v2, her gozlemi kendinden onceki/sonraki gozlemle kiyaslayarak, ardisik
AYNI koordinat calisan bloklarini (run) tespit eder ve HER NOKTAYI ayri
degerlendirir:

- Bir nokta, bir onceki noktayla AYNI koordinattaysa VE bu tekrar blogu
  >= STALE_RUN_THRESHOLD uzunluguysa -> STALE adayi.
  - Bu blok suresince support API'de KalanDurakSayisi azaliyorsa ->
    STALE_POSITION (kanitli).
  - Support API verisi yoksa veya o da sabit ise -> UNKNOWN_POSITION
    (kesin hukum verilemiyor, acikca boyle raporlaniyor).
- Kisa tekrarlar (1-2 nokta, orn. kirmizi isikta bekleme) icin kesin bir
  kural cikarilamiyor -> UNKNOWN_POSITION, STALE degil.
- Bir onceki noktadan FARKLI koordinattaki nokta -> CURRENT_POSITION.
- Serinin ilk noktasi icin "once/sonra" karsilastirmasi eksik oldugundan,
  ilk nokta tek basina asla CURRENT_POSITION varsayilmaz; sonraki nokta
  ile ayni ise o run'in parcasi olarak degerlendirilir, farkliysa da
  "ilk nokta gunceldir" degil, "sonraki noktadan once farkliydi" mantigi
  ile CURRENT olarak kaydedilir (cunku degisim gozlemlendi).

Kullanim:
    python scripts/analyze_gps_uncertainty.py --run-id 3
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

STALE_RUN_THRESHOLD = 3  # ardisik ayni koordinat sayisi bu esigi gecerse stale adayi


def fetch_vehicle_series(conn, run_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vo.id, vo.vehicle_id, vo.line_no, vo.observed_at, vo.raw_lat, vo.raw_lon
            FROM vehicle_observations vo
            JOIN raw_snapshots rs ON vo.raw_snapshot_id = rs.id
            WHERE rs.ingestion_run_id = %s
            ORDER BY vo.vehicle_id, vo.observed_at
            """,
            (run_id,),
        )
        rows = cur.fetchall()

    series = defaultdict(list)
    for obs_id, vehicle_id, line_no, observed_at, lat, lon in rows:
        series[(vehicle_id, line_no)].append(
            {"id": obs_id, "observed_at": observed_at, "lat": lat, "lon": lon}
        )
    return series


def fetch_support_series(conn, run_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sao.vehicle_id, sao.line_no, sao.observed_at, sao.remaining_stop_count
            FROM supporting_api_observations sao
            JOIN raw_snapshots rs ON sao.raw_snapshot_id = rs.id
            WHERE rs.ingestion_run_id = %s
            ORDER BY sao.vehicle_id, sao.observed_at
            """,
            (run_id,),
        )
        rows = cur.fetchall()

    series = defaultdict(list)
    for vehicle_id, line_no, observed_at, remaining in rows:
        series[(vehicle_id, line_no)].append(
            {"observed_at": observed_at, "remaining": remaining}
        )
    return series


def remaining_trend_during(support_obs, start_time, end_time):
    """start_time-end_time araligina denk dusen KalanDurakSayisi gozlemlerini
    bulur, azalma varsa True doner. Yeterli veri yoksa None doner."""
    if not support_obs:
        return None
    window = [s for s in support_obs if start_time <= s["observed_at"] <= end_time]
    if len(window) < 2:
        return None
    return window[0]["remaining"] > window[-1]["remaining"]


def find_runs(obs_list):
    """Ardisik ayni koordinatli bloklari bulur. Her run: (start_idx, end_idx, length)."""
    runs = []
    i = 0
    n = len(obs_list)
    while i < n:
        j = i
        while j + 1 < n and (obs_list[j + 1]["lat"], obs_list[j + 1]["lon"]) == \
                             (obs_list[i]["lat"], obs_list[i]["lon"]):
            j += 1
        runs.append((i, j, j - i + 1))
        i = j + 1
    return runs


def classify(conn, run_id):
    gps_series = fetch_vehicle_series(conn, run_id)
    support_series = fetch_support_series(conn, run_id)

    lines = [f"# GPS Belirsizligi Analiz Raporu (v2 - nokta/run bazli)\n",
             f"ingestion_run_id = {run_id}, STALE_RUN_THRESHOLD = {STALE_RUN_THRESHOLD}\n"]
    lines.append(f"\nToplam arac/hat kombinasyonu: {len(gps_series)}\n")
    lines.append("\n## Arac Bazli Sonuclar\n")

    totals = {"CURRENT_POSITION": 0, "STALE_POSITION": 0, "UNKNOWN_POSITION": 0}

    for (vehicle_id, line_no), obs_list in gps_series.items():
        support_obs = support_series.get((vehicle_id, line_no))
        runs = find_runs(obs_list)

        vehicle_counts = {"CURRENT_POSITION": 0, "STALE_POSITION": 0, "UNKNOWN_POSITION": 0}
        long_runs_detail = []

        for start_idx, end_idx, length in runs:
            if length == 1:
                quality = "CURRENT_POSITION"
                reason = "Komsu gozlemlerden farkli koordinat - hareket gozlemlendi."
            elif length < STALE_RUN_THRESHOLD:
                quality = "UNKNOWN_POSITION"
                reason = (f"{length} ardisik gozlemde ayni koordinat - kisa bir tekrar "
                           "(orn. trafik isigi olabilir), kesin hukum verilemiyor.")
            else:
                start_t = obs_list[start_idx]["observed_at"]
                end_t = obs_list[end_idx]["observed_at"]
                trend = remaining_trend_during(support_obs, start_t, end_t)
                if trend is True:
                    quality = "STALE_POSITION"
                    reason = (f"{length} ardisik gozlemde ({start_t}-{end_t}) koordinat hic "
                               "degismedi, ancak support API'de KalanDurakSayisi bu aralikta "
                               "azaldi - GPS donmus, arac gercekte ilerliyor.")
                    long_runs_detail.append((start_t, end_t, length, "STALE (support ile dogrulandi)"))
                else:
                    quality = "UNKNOWN_POSITION"
                    reason = (f"{length} ardisik gozlemde ({start_t}-{end_t}) koordinat hic "
                               "degismedi. Support API bu aralikta ya yok ya da ilerleme "
                               "gostermiyor - aracin gercekten durup durmadigi belirsiz.")
                    long_runs_detail.append((start_t, end_t, length, "UNKNOWN (dogrulanamadi)"))

            for idx in range(start_idx, end_idx + 1):
                obs = obs_list[idx]
                db_storage.update_position_quality(conn, obs["id"], quality, reason)
                vehicle_counts[quality] += 1
                totals[quality] += 1

        lines.append(
            f"- Arac **{vehicle_id}** (Hat {line_no}): {len(obs_list)} gozlem -> "
            f"CURRENT={vehicle_counts['CURRENT_POSITION']}, "
            f"STALE={vehicle_counts['STALE_POSITION']}, "
            f"UNKNOWN={vehicle_counts['UNKNOWN_POSITION']}"
        )
        for start_t, end_t, length, verdict in long_runs_detail:
            lines.append(f"  - Uzun donuk blok: {length} gozlem, {start_t} -> {end_t} : {verdict}")

    lines.append("\n## Genel Ozet (nokta bazli)\n")
    for k, v in totals.items():
        lines.append(f"- {k}: {v}")

    lines.append("\n## Bilinen Sinirlamalar\n")
    lines.append(
        f"- STALE_RUN_THRESHOLD={STALE_RUN_THRESHOLD} keyfi bir esik; 1-2 gozlemlik "
        "tekrarlar (trafik isigi vb. ile karistirilabilecegi icin) her zaman UNKNOWN "
        "olarak birakildi, STALE denmedi.\n"
        "- Support API capraz dogrulamasi yalnizca 3 pilot durakta yaklasan araclar "
        "icin mumkun; bu disinda kalan uzun donuk bloklar STALE degil UNKNOWN kaliyor "
        "- bu, gercek stale orani muhtemelen raporlanandan yuksek demektir.\n"
        "- 'Ilk nokta gunceldir' varsayimi yapilmadi; ilk run'in siniflandirmasi da "
        "diger run'larla ayni kurala tabi tutuldu."
    )

    return "\n".join(lines), totals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Madde 1: GPS belirsizligi analizi (v2)")
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    conn = db_storage.get_connection()
    report, totals = classify(conn, args.run_id)
    conn.close()

    print(report)
    print(f"\n\nOZET: {totals}")

    out_dir = Path(__file__).resolve().parent.parent / "docs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"gps-uncertainty-report-run{args.run_id}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nRapor kaydedildi: {out_path}")
