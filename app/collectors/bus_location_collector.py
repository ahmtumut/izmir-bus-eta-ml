"""
Ana collector. Pilot hatlari periyodik olarak sorgular, ham veriyi
saklar, normalize edip dogrular, ingestion log'u tutar.
"""
import hashlib
import json
import time
from datetime import datetime, timezone

import requests

from app.storage.raw_storage import (
    save_raw_response,
    append_normalized_records,
    append_ingestion_log,
)
from app.validation.quality import validate_vehicle, detect_duplicate_ids
from app.schemas.vehicle import NormalizedVehiclePosition

BASE_URL = "https://openapi.izmir.bel.tr/api/iztek/hatotobuskonumlari/{hat_id}"
REQUEST_TIMEOUT = 10


def collect_line(line_no: str) -> str:
    started_at = datetime.now(timezone.utc)
    url = BASE_URL.format(hat_id=line_no)

    log_row = {
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "line_no": line_no,
        "http_status": None,
        "response_time_ms": None,
        "vehicle_count": 0,
        "valid_vehicle_count": 0,
        "invalid_vehicle_count": 0,
        "duplicate_count": 0,
        "payload_hash": None,
        "result": None,
    }

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        log_row["result"] = "TIMEOUT"
        log_row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_ingestion_log(log_row)
        return "TIMEOUT"
    except requests.RequestException:
        log_row["result"] = "CONNECTION_ERROR"
        log_row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_ingestion_log(log_row)
        return "CONNECTION_ERROR"

    log_row["http_status"] = resp.status_code
    log_row["response_time_ms"] = round(resp.elapsed.total_seconds() * 1000, 1)

    if resp.status_code == 429:
        log_row["result"] = "RATE_LIMITED"
        log_row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_ingestion_log(log_row)
        return "RATE_LIMITED"

    if resp.status_code != 200:
        log_row["result"] = "HTTP_ERROR"
        log_row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_ingestion_log(log_row)
        return "HTTP_ERROR"

    raw_text = resp.text
    if not raw_text.strip():
        log_row["result"] = "EMPTY_RESPONSE"
        log_row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_ingestion_log(log_row)
        return "EMPTY_RESPONSE"

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        log_row["result"] = "JSON_PARSE_ERROR"
        log_row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_ingestion_log(log_row)
        return "JSON_PARSE_ERROR"

    vehicles = data.get("HatOtobusKonumlari")
    if vehicles is None:
        log_row["result"] = "UNKNOWN_SCHEMA"
        log_row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_ingestion_log(log_row)
        return "UNKNOWN_SCHEMA"

    payload_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
    duplicate_ids = detect_duplicate_ids(vehicles)

    normalized_records = []
    valid_count = 0
    invalid_count = 0

    for v in vehicles:
        result = validate_vehicle(v)
        vid = result["vehicle_id"]

        flags = list(result["quality_flags"])
        key = (vid, v.get("KoorX"), v.get("KoorY"))
        if key in duplicate_ids:
            flags.append("EXACT_DUPLICATE_IN_RESPONSE")

        is_valid = result["is_valid"] and "EXACT_DUPLICATE_IN_RESPONSE" not in flags

        record = NormalizedVehiclePosition(
            line_no=line_no,
            vehicle_id=vid,
            observed_at=started_at.isoformat(),
            source_timestamp=None,
            latitude=result["latitude"],
            longitude=result["longitude"],
            direction=result["direction"],
            raw_payload_hash=payload_hash,
            is_valid=is_valid,
            quality_flags=flags,
        )
        normalized_records.append(record.to_dict())

        if is_valid:
            valid_count += 1
        else:
            invalid_count += 1

    save_raw_response(line_no, started_at, raw_text)
    append_normalized_records(normalized_records)

    log_row["vehicle_count"] = len(vehicles)
    log_row["valid_vehicle_count"] = valid_count
    log_row["invalid_vehicle_count"] = invalid_count
    log_row["duplicate_count"] = len(duplicate_ids)
    log_row["payload_hash"] = payload_hash
    log_row["result"] = "OK"
    log_row["finished_at"] = datetime.now(timezone.utc).isoformat()
    append_ingestion_log(log_row)

    return "OK"


def run_collector(lines: list, cycle_interval_seconds: int = 60, delay_between_lines: int = 3):
    print(f"Collector basladi. Hatlar: {lines}")
    print("Durdurmak icin Ctrl+C\n")

    cycle_num = 0
    try:
        while True:
            cycle_num += 1
            cycle_start = time.monotonic()
            print(f"--- Cycle {cycle_num} ---")

            for i, line_no in enumerate(lines):
                result = collect_line(line_no)
                print(f"  Hat {line_no}: {result}")
                if i < len(lines) - 1:
                    time.sleep(delay_between_lines)

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, cycle_interval_seconds - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\nCollector durduruldu. Toplam {cycle_num} cycle tamamlandi.")
