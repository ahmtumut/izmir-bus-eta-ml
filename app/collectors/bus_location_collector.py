"""
Ana collector (Faz 2). Pilot hatlari periyodik olarak sorgular, ham veriyi
ve normalize edilmis arac konumlarini PostgreSQL/PostGIS'e yazar.

Faz 1'e gore degisiklik: JSON dosyasi / CSV yazan raw_storage yerine
db_storage kullanilir. Kucuk JSON dosyalari problemi ortadan kalkar
(Faz 2 madde 2 kabul kriteri).
"""
import hashlib
import json
import time
from datetime import datetime, timezone

import requests

from app.storage import db_storage
from app.validation.quality import validate_vehicle, detect_duplicate_ids
from app.schemas.vehicle import NormalizedVehiclePosition

BASE_URL = "https://openapi.izmir.bel.tr/api/iztek/hatotobuskonumlari/{hat_id}"
REQUEST_TIMEOUT = 10
COLLECTOR_VERSION = "faz2-db-v1"  # ileride git commit SHA ile degistirilebilir


def collect_line(conn, run_id: int, line_no: str) -> str:
    started_at = datetime.now(timezone.utc)
    url = BASE_URL.format(hat_id=line_no)

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="WARNING",
            description=f"Hat {line_no}: request timeout",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "TIMEOUT"
    except requests.RequestException as e:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="ERROR",
            description=f"Hat {line_no}: connection error - {e}",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "CONNECTION_ERROR"

    if resp.status_code == 429:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="WARNING",
            description=f"Hat {line_no}: rate limited (429)",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "RATE_LIMITED"

    if resp.status_code != 200:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="ERROR",
            description=f"Hat {line_no}: HTTP {resp.status_code}",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "HTTP_ERROR"

    raw_text = resp.text
    if not raw_text.strip():
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="WARNING",
            description=f"Hat {line_no}: empty response",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "EMPTY_RESPONSE"

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="ERROR",
            description=f"Hat {line_no}: JSON parse error",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "JSON_PARSE_ERROR"

    vehicles = data.get("HatOtobusKonumlari")
    if vehicles is None:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="ERROR",
            description=f"Hat {line_no}: beklenmeyen schema (HatOtobusKonumlari yok)",
            ingestion_run_id=run_id, line_no=line_no,
        )
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

    # --- DB'ye yaz ---
    snapshot_id = db_storage.save_raw_snapshot(
        conn, ingestion_run_id=run_id, source_api="main_api", line_no=line_no,
        requested_at=started_at, http_status=resp.status_code, raw_text=raw_text,
    )
    inserted = db_storage.save_vehicle_observations(
        conn, raw_snapshot_id=snapshot_id, line_no=line_no,
        observed_at=started_at, records=normalized_records,
    )

    if duplicate_ids:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="INFO",
            description=f"Hat {line_no}: response icinde {len(duplicate_ids)} exact duplicate",
            ingestion_run_id=run_id, line_no=line_no,
            context={"duplicate_count": len(duplicate_ids)},
        )

    print(f"    -> snapshot_id={snapshot_id}, {inserted} arac gozlemi yazildi "
          f"(valid={valid_count}, invalid={invalid_count})")

    return "OK"


def run_collector(lines: list, cycle_interval_seconds: int = 60, delay_between_lines: int = 3):
    conn = db_storage.get_connection()
    run_id = db_storage.start_ingestion_run(conn, target_lines=lines,
                                             collector_version=COLLECTOR_VERSION)
    print(f"Collector basladi. ingestion_run_id={run_id}, Hatlar: {lines}")
    print("Durdurmak icin Ctrl+C\n")

    cycle_num = 0
    try:
        while True:
            cycle_num += 1
            cycle_start = time.monotonic()
            print(f"--- Cycle {cycle_num} ---")

            for i, line_no in enumerate(lines):
                result = collect_line(conn, run_id, line_no)
                print(f"  Hat {line_no}: {result}")
                if i < len(lines) - 1:
                    time.sleep(delay_between_lines)

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, cycle_interval_seconds - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\nCollector durduruldu. Toplam {cycle_num} cycle tamamlandi.")
    finally:
        db_storage.end_ingestion_run(conn, run_id)
        conn.close()
