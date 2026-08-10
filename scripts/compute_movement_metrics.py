"""
normalized_positions.csv icindeki gecerli gozlemleri arac+hat bazinda
gruplar, zaman sirasina koyar, hareket metriklerini hesaplar.
"""
import csv
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.trajectory.movement_metrics import compute_movement_metrics

INPUT_FILE = Path("data/processed/normalized_positions.csv")
OUTPUT_FILE = Path("data/processed/movement_metrics.csv")

OUTPUT_FIELDS = [
    "line_no", "vehicle_id", "prev_observed_at", "curr_observed_at",
    "distance_meters", "elapsed_seconds", "calculated_speed_kmh",
    "bearing_degrees", "is_unrealistic_speed",
]


def load_valid_positions():
    with open(INPUT_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r["is_valid"] == "True"]
    return rows

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

def main():
    rows = load_valid_positions()
    print(f"Toplam gecerli gozlem: {len(rows)}")
    rows = dedupe_trail_points(rows)
    print(f"Trail-nokta ayiklama sonrasi: {len(rows)}")

    groups = defaultdict(list)
    for r in rows:
        key = (r["line_no"], r["vehicle_id"])
        groups[key].append(r)

    output_rows = []
    for (line_no, vehicle_id), positions in groups.items():
        positions.sort(key=lambda r: r["observed_at"])

        for i in range(1, len(positions)):
            prev, curr = positions[i - 1], positions[i]
            try:
                prev_time = datetime.fromisoformat(prev["observed_at"])
                curr_time = datetime.fromisoformat(curr["observed_at"])
                metrics = compute_movement_metrics(
                    float(prev["latitude"]), float(prev["longitude"]), prev_time,
                    float(curr["latitude"]), float(curr["longitude"]), curr_time,
                )
            except (ValueError, TypeError):
                continue

            output_rows.append({
                "line_no": line_no,
                "vehicle_id": vehicle_id,
                "prev_observed_at": prev["observed_at"],
                "curr_observed_at": curr["observed_at"],
                **metrics,
            })

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    unrealistic_count = sum(1 for r in output_rows if r["is_unrealistic_speed"])
    print(f"Uretilen hareket metrigi satiri: {len(output_rows)}")
    print(f"Gercekci olmayan hiz isaretlenen: {unrealistic_count}")
    print(f"Cikti: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
