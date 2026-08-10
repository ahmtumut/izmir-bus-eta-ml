"""
Gorev madde 8: "ayni koordinat uzun sure tekrar ediyor mu?" kontrolu.
"""
import csv
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INPUT_FILE = Path("data/processed/normalized_positions.csv")
OUTPUT_FILE = Path("data/processed/stale_report.csv")

STALE_THRESHOLD_DEGREES = 0.0001
MIN_CONSECUTIVE_FOR_STALE = 3

OUTPUT_FIELDS = [
    "line_no", "vehicle_id", "run_length", "start_observed_at",
    "end_observed_at", "latitude", "longitude",
]


def load_valid_positions():
    with open(INPUT_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r["is_valid"] == "True"]


def dedupe_trail_points(rows):
    seen = set()
    result = []
    for r in rows:
        key = (r["line_no"], r["vehicle_id"], r["observed_at"])
        if key in seen:
            continue
        seen.add(key)
        result.append(r)
    return result


def find_stale_runs(positions):
    runs = []
    if len(positions) < 2:
        return runs

    run_start_idx = 0
    for i in range(1, len(positions)):
        prev, curr = positions[i - 1], positions[i]
        diff = abs(float(prev["latitude"]) - float(curr["latitude"])) + \
               abs(float(prev["longitude"]) - float(curr["longitude"]))

        if diff > STALE_THRESHOLD_DEGREES:
            run_length = i - run_start_idx
            if run_length >= MIN_CONSECUTIVE_FOR_STALE:
                runs.append((run_start_idx, i - 1, run_length))
            run_start_idx = i

    run_length = len(positions) - run_start_idx
    if run_length >= MIN_CONSECUTIVE_FOR_STALE:
        runs.append((run_start_idx, len(positions) - 1, run_length))

    return runs


def main():
    rows = load_valid_positions()
    rows = dedupe_trail_points(rows)

    groups = defaultdict(list)
    for r in rows:
        key = (r["line_no"], r["vehicle_id"])
        groups[key].append(r)

    output_rows = []
    for (line_no, vehicle_id), positions in groups.items():
        positions.sort(key=lambda r: r["observed_at"])
        runs = find_stale_runs(positions)

        for start_idx, end_idx, run_length in runs:
            output_rows.append({
                "line_no": line_no,
                "vehicle_id": vehicle_id,
                "run_length": run_length,
                "start_observed_at": positions[start_idx]["observed_at"],
                "end_observed_at": positions[end_idx]["observed_at"],
                "latitude": positions[start_idx]["latitude"],
                "longitude": positions[start_idx]["longitude"],
            })

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Tespit edilen stale (hareketsiz) seri sayisi: {len(output_rows)}")
    for r in output_rows:
        print(f"  Hat {r['line_no']}, Arac {r['vehicle_id']}: {r['run_length']} ardisik gozlem "
              f"({r['start_observed_at']} -> {r['end_observed_at']})")
    print(f"Cikti: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
