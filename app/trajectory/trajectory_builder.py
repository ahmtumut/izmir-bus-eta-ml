"""
Gorev madde 7: Ayni araca ait ardisik GPS noktalarini zaman sirasina
gore iliskilendirip, hat+arac+zaman uzerinden sorgulanabilir bicimde
saklar.
"""
import csv
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

NORMALIZED_FILE = Path("data/processed/normalized_positions.csv")
TRAJECTORY_DIR = Path("data/processed/trajectories")
INDEX_FILE = TRAJECTORY_DIR / "trajectory_index.csv"

INDEX_FIELDS = [
    "line_no", "vehicle_id", "point_count", "start_observed_at",
    "end_observed_at", "file_path",
]


def load_valid_positions():
    with open(NORMALIZED_FILE, encoding="utf-8") as f:
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


def build_trajectories():
    rows = load_valid_positions()
    rows = dedupe_trail_points(rows)

    groups = defaultdict(list)
    for r in rows:
        key = (r["line_no"], r["vehicle_id"])
        groups[key].append(r)

    TRAJECTORY_DIR.mkdir(parents=True, exist_ok=True)
    index_rows = []

    for (line_no, vehicle_id), positions in groups.items():
        positions.sort(key=lambda r: r["observed_at"])

        trajectory_points = [
            {
                "observed_at": p["observed_at"],
                "latitude": float(p["latitude"]),
                "longitude": float(p["longitude"]),
                "direction": p["direction"],
            }
            for p in positions
        ]

        line_dir = TRAJECTORY_DIR / line_no
        line_dir.mkdir(parents=True, exist_ok=True)
        file_path = line_dir / f"{vehicle_id}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({
                "line_no": line_no,
                "vehicle_id": vehicle_id,
                "point_count": len(trajectory_points),
                "points": trajectory_points,
            }, f, ensure_ascii=False, indent=2)

        index_rows.append({
            "line_no": line_no,
            "vehicle_id": vehicle_id,
            "point_count": len(trajectory_points),
            "start_observed_at": trajectory_points[0]["observed_at"],
            "end_observed_at": trajectory_points[-1]["observed_at"],
            "file_path": str(file_path),
        })

    with open(INDEX_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(index_rows)

    return index_rows


def query_trajectory(line_no, vehicle_id):
    file_path = TRAJECTORY_DIR / line_no / f"{vehicle_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def query_trajectories_for_line(line_no):
    if not INDEX_FILE.exists():
        return []
    with open(INDEX_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r["line_no"] == line_no]


if __name__ == "__main__":
    index_rows = build_trajectories()
    print(f"Toplam {len(index_rows)} trajectory olusturuldu.")
    for r in index_rows:
        print(f"  Hat {r['line_no']}, Arac {r['vehicle_id']}: "
              f"{r['point_count']} nokta ({r['start_observed_at']} -> {r['end_observed_at']})")
    print(f"\nIndex: {INDEX_FILE}")
