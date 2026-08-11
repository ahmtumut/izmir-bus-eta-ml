"""
ingestion_log.csv deki zaman damgalarini inceleyip GERCEK kesintisiz
veri toplama segmentlerini otomatik tespit eder.
"""
import csv
from pathlib import Path
from datetime import datetime, timedelta

RAW_DIR = Path("data/raw")
GAP_THRESHOLD_MINUTES = 5


def load_timestamps():
    path = RAW_DIR / "ingestion_log.csv"
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        times = sorted(
            datetime.fromisoformat(r["started_at"])
            for r in reader if r["started_at"]
        )
    return times


def find_segments(times):
    if not times:
        return []

    segments = []
    seg_start = times[0]
    prev = times[0]

    for t in times[1:]:
        gap = (t - prev).total_seconds() / 60
        if gap > GAP_THRESHOLD_MINUTES:
            segments.append((seg_start, prev))
            seg_start = t
        prev = t

    segments.append((seg_start, prev))
    return segments


def main():
    times = load_timestamps()
    print(f"Toplam kayit sayisi: {len(times)}")

    segments = find_segments(times)
    print(f"\nTespit edilen kesintisiz segment sayisi: {len(segments)}\n")

    total_duration = timedelta()
    for i, (start, end) in enumerate(segments, 1):
        duration = end - start
        total_duration += duration
        print(f"Segment {i}: {start.isoformat()}  ->  {end.isoformat()}")
        print(f"  Sure: {duration}")

    print(f"\nToplam GERCEK (kesintisiz parcalarin toplami) veri toplama suresi: {total_duration}")

    if len(segments) > 1:
        print("\n--- Segmentler arasi bosluklar (kesinti suresi) ---")
        for i in range(1, len(segments)):
            gap_start = segments[i - 1][1]
            gap_end = segments[i][0]
            gap_duration = gap_end - gap_start
            print(f"  Kesinti {i}: {gap_start.isoformat()} -> {gap_end.isoformat()}  ({gap_duration})")


if __name__ == "__main__":
    main()
