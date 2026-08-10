"""
Ham API response'larini ve normalize edilmis arac konumlarini diske yazar.
"""
import csv
from datetime import datetime
from pathlib import Path

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")

NORMALIZED_FIELDS = [
    "line_no", "vehicle_id", "observed_at", "source_timestamp",
    "latitude", "longitude", "direction", "raw_payload_hash",
    "is_valid", "quality_flags",
]

INGESTION_LOG_FIELDS = [
    "started_at", "finished_at", "line_no", "http_status",
    "response_time_ms", "vehicle_count", "valid_vehicle_count",
    "invalid_vehicle_count", "duplicate_count", "payload_hash", "result",
]


def save_raw_response(line_no: str, request_time_dt: datetime, raw_text: str):
    day_folder = RAW_DIR / request_time_dt.strftime("%Y-%m-%d") / f"line-{line_no}"
    day_folder.mkdir(parents=True, exist_ok=True)
    filepath = day_folder / (request_time_dt.strftime("%H-%M-%S") + ".json")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(raw_text)
    return filepath


def _ensure_csv(filepath: Path, fieldnames: list):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if not filepath.exists():
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()


def append_normalized_records(records: list):
    filepath = PROCESSED_DIR / "normalized_positions.csv"
    _ensure_csv(filepath, NORMALIZED_FIELDS)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NORMALIZED_FIELDS)
        for r in records:
            writer.writerow(r)


def append_ingestion_log(row: dict):
    filepath = RAW_DIR / "ingestion_log.csv"
    _ensure_csv(filepath, INGESTION_LOG_FIELDS)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INGESTION_LOG_FIELDS)
        writer.writerow(row)
