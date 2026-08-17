"""
Faz 3: Model egitimine baslamadan once dataset kalite/kapsam ozeti.

CLAUDE.md'de listelenen tum kirilimlari raporlar. Ozellikle satir sayisi
(eta_training_samples) ile benzersiz arrival_event sayisi AYRI raporlanir -
tek bir arrival_event birden fazla T0 training sample uretebildigi icin
(bkz. scripts/generate_eta_training_samples.py) satir sayisi tek basina
bagimsiz yolculuk/gozlem sayisini yansitmaz.

Kullanim:
    python scripts/generate_dataset_summary.py
    python scripts/generate_dataset_summary.py --save reports/dataset-summary-YYYYMMDD.md
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage


def fetch_all(conn, query, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def section(title):
    print(f"\n--- {title} ---")


def build_report(conn) -> list[str]:
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 70)
    out("FAZ 3 DATASET OZETI")
    out("=" * 70)

    # --- Ingestion runs / zaman kapsami ---
    runs = fetch_all(conn, """
        SELECT id, started_at, ended_at, target_lines, collector_version
        FROM ingestion_runs ORDER BY id
    """)
    out(f"\nToplam ingestion_run: {len(runs)}")
    for r in runs:
        dur_min = None
        if r["started_at"] and r["ended_at"]:
            dur_min = (r["ended_at"] - r["started_at"]).total_seconds() / 60
        out(f"  run_id={r['id']} version={r['collector_version']} "
            f"basladi={r['started_at']} sure={dur_min:.1f}dk" if dur_min is not None
            else f"  run_id={r['id']} version={r['collector_version']} basladi={r['started_at']} (bitmemis)")

    # --- GPS gozlemleri ---
    total_obs = fetch_all(conn, "SELECT count(*) AS n FROM vehicle_observations")[0]["n"]
    out(f"\nToplam GPS observation (vehicle_observations): {total_obs}")

    section("Map-match kalite dagilimi")
    mm = fetch_all(conn, """
        SELECT coalesce(map_match_quality::text, 'NULL') AS quality, count(*) AS n
        FROM vehicle_observations GROUP BY 1 ORDER BY 1
    """)
    for row in mm:
        pct = row["n"] / total_obs * 100 if total_obs else 0
        out(f"  {row['quality']}: {row['n']} ({pct:.1f}%)")

    unique_vehicles = fetch_all(conn, "SELECT count(DISTINCT vehicle_id) AS n FROM vehicle_observations")[0]["n"]
    out(f"\nBenzersiz arac (vehicle_observations): {unique_vehicles}")

    # --- Arrival events ---
    total_events = fetch_all(conn, "SELECT count(*) AS n FROM arrival_events")[0]["n"]
    out(f"\nToplam arrival_event: {total_events}")

    section("Arrival confidence dagilimi (HIGH/MEDIUM/LOW)")
    conf = fetch_all(conn, """
        SELECT arrival_confidence, count(*) AS n FROM arrival_events
        GROUP BY 1 ORDER BY 1
    """)
    for row in conf:
        pct = row["n"] / total_events * 100 if total_events else 0
        out(f"  {row['arrival_confidence']}: {row['n']} ({pct:.1f}%)")

    section("Hat basina arrival_event")
    for row in fetch_all(conn, "SELECT line_no, count(*) AS n FROM arrival_events GROUP BY 1 ORDER BY 1"):
        out(f"  Hat {row['line_no']}: {row['n']}")

    # --- Training samples ---
    total_samples = fetch_all(conn, "SELECT count(*) AS n FROM eta_training_samples")[0]["n"]
    unique_events_in_samples = fetch_all(
        conn, "SELECT count(DISTINCT arrival_event_id) AS n FROM eta_training_samples"
    )[0]["n"]
    out(f"\nToplam eta_training_samples SATIRI: {total_samples}")
    out(f"Bu satirlarin ARKASINDAKI BENZERSIZ arrival_event sayisi: {unique_events_in_samples}")
    if unique_events_in_samples:
        out(f"  (ortalama {total_samples / unique_events_in_samples:.1f} T0 sample / event)")
    out("  >> UYARI: Satir sayisi bagimsiz yolculuk sayisi DEGILDIR - split/degerlendirme "
        "arrival_event_id bazinda yapilmali (asagida ayrica hatirlatilir).")

    section("Label quality dagilimi (GOLD/SILVER/REJECTED)")
    lq = fetch_all(conn, "SELECT label_quality, count(*) AS n FROM eta_training_samples GROUP BY 1 ORDER BY 1")
    for row in lq:
        pct = row["n"] / total_samples * 100 if total_samples else 0
        out(f"  {row['label_quality']}: {row['n']} ({pct:.1f}%)")

    section("Hat basina training sample")
    for row in fetch_all(conn, "SELECT line_no, count(*) AS n FROM eta_training_samples GROUP BY 1 ORDER BY 1"):
        out(f"  Hat {row['line_no']}: {row['n']}")

    section("Yon basina training sample")
    for row in fetch_all(conn, "SELECT direction, count(*) AS n FROM eta_training_samples GROUP BY 1 ORDER BY 1"):
        out(f"  Yon {row['direction']}: {row['n']}")

    section("Durak basina training sample (target_stop_id)")
    for row in fetch_all(conn, """
        SELECT target_stop_id, count(*) AS n FROM eta_training_samples
        GROUP BY 1 ORDER BY n DESC
    """):
        out(f"  Durak {row['target_stop_id']}: {row['n']}")

    section("Saat dilimi basina training sample (hour_of_day)")
    for row in fetch_all(conn, """
        SELECT hour_of_day, count(*) AS n FROM eta_training_samples
        GROUP BY 1 ORDER BY 1
    """):
        out(f"  {row['hour_of_day']:02d}:00: {row['n']}")

    section("Gun basina training sample (day_of_week, 0=Pazartesi)")
    for row in fetch_all(conn, """
        SELECT day_of_week, count(*) AS n FROM eta_training_samples
        GROUP BY 1 ORDER BY 1
    """):
        out(f"  gun={row['day_of_week']}: {row['n']}")

    out("\n" + "=" * 70)
    out("Not: Bu ozet, model egitimine gecmeden once CLAUDE.md Faz 3 kabul "
        "kriterinin bir parcasidir. Saat dilimi / gun cesitliligi dusukse "
        "(tek gun/tek saat dilimi hakimse) model egitimine gecilmemelidir.")
    out("=" * 70)

    return lines


def main():
    parser = argparse.ArgumentParser(description="Faz 3 dataset ozet raporu")
    parser.add_argument("--save", type=str, default=None,
                         help="Raporu bu dosyaya da yaz (ör. reports/dataset-summary-20260813.md)")
    args = parser.parse_args()

    conn = db_storage.get_connection()
    lines = build_report(conn)
    conn.close()

    if args.save:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nRapor kaydedildi: {out_path}")


if __name__ == "__main__":
    main()
