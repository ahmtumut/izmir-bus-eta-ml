"""
Gorev teslimlerindeki "En az 24 saatlik veri toplama ozeti" bolumu icin
gerekli tum istatistikleri hesaplar.
"""
import csv
from pathlib import Path
from collections import defaultdict, Counter

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")


def load_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    ingestion_log = load_csv(RAW_DIR / "ingestion_log.csv")
    positions = load_csv(PROCESSED_DIR / "normalized_positions.csv")
    stale = load_csv(PROCESSED_DIR / "stale_report.csv")

    print("=" * 70)
    print("VERI TOPLAMA OZETI")
    print("=" * 70)

    if ingestion_log:
        times = [r["started_at"] for r in ingestion_log if r["started_at"]]
        print(f"\nKapsanan zaman araligi: {min(times)}  ->  {max(times)}")

    print(f"\nToplam ingestion kaydi (tum hatlar, tum sonuclar): {len(ingestion_log)}")

    print("\n--- Hat bazinda sorgu sayisi ---")
    query_counts = Counter(r["line_no"] for r in ingestion_log)
    for line_no, count in sorted(query_counts.items()):
        print(f"  Hat {line_no}: {count} sorgu")

    print("\n--- Hat bazinda sonuc dagilimi ---")
    for line_no in sorted(query_counts.keys()):
        results = Counter(r["result"] for r in ingestion_log if r["line_no"] == line_no)
        print(f"  Hat {line_no}: {dict(results)}")

    error_results = {"TIMEOUT", "CONNECTION_ERROR", "HTTP_ERROR", "RATE_LIMITED",
                      "JSON_PARSE_ERROR", "EMPTY_RESPONSE", "UNKNOWN_SCHEMA"}
    total_errors = sum(1 for r in ingestion_log if r["result"] in error_results)
    if ingestion_log:
        print(f"\nToplam API hata/timeout sayisi: {total_errors} / {len(ingestion_log)} "
              f"({total_errors / len(ingestion_log):.1%})")

    print("\n--- Hat bazinda benzersiz arac sayisi ---")
    vehicles_by_line = defaultdict(set)
    for r in positions:
        if r["is_valid"] == "True":
            vehicles_by_line[r["line_no"]].add(r["vehicle_id"])
    for line_no, vehicles in sorted(vehicles_by_line.items()):
        print(f"  Hat {line_no}: {len(vehicles)} benzersiz arac")

    print(f"\nToplam GPS gozlem sayisi (normalize edilmis, tum): {len(positions)}")
    valid_count = sum(1 for r in positions if r["is_valid"] == "True")
    invalid_count = len(positions) - valid_count
    print(f"  Gecerli: {valid_count}")
    print(f"  Gecersiz: {invalid_count}")

    print("\n--- Gecersiz kayit flag dagilimi ---")
    flag_counts = Counter()
    for r in positions:
        if r["is_valid"] == "False" and r["quality_flags"]:
            for flag in r["quality_flags"].split(";"):
                flag_counts[flag] += 1
    for flag, count in flag_counts.most_common():
        print(f"  {flag}: {count}")

    if ingestion_log:
        total_vehicles_seen = sum(int(r["vehicle_count"]) for r in ingestion_log if r["vehicle_count"])
        total_duplicates = sum(int(r["duplicate_count"]) for r in ingestion_log if r["duplicate_count"])
        dup_rate = total_duplicates / total_vehicles_seen if total_vehicles_seen else 0
        print(f"\nDuplicate orani: {total_duplicates} / {total_vehicles_seen} ({dup_rate:.2%})")

    print(f"\nTespit edilen stale (hareketsiz) seri sayisi: {len(stale)}")
    if stale:
        for r in stale:
            print(f"  Hat {r['line_no']}, Arac {r['vehicle_id']}: {r['run_length']} ardisik gozlem")


if __name__ == "__main__":
    main()
