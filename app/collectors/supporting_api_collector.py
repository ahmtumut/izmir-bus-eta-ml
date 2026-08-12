"""
Destekleyici API collector (Faz 2, madde 8).
hattinyaklasanotobusleri/{hat_no}/{durak_id} endpoint'ini pilot hat+durak
eslemesiyle sorgular, ham response'u ve KalanDurakSayisi gozlemlerini
DB'ye yazar.

Pilot hat -> durak eslemesi docs/api-comparison.md'deki arastirmadan alindi.
"""
import hashlib
import json
import time
from datetime import datetime, timezone

import requests

from app.storage import db_storage

SUPPORT_BASE_URL = "https://openapi.izmir.bel.tr/api/iztek/hattinyaklasanotobusleri/{hat_no}/{durak_id}"
REQUEST_TIMEOUT = 10

# docs/api-comparison.md'deki PILOT_LINE_STOPS ile birebir ayni
PILOT_LINE_STOPS = {
    "515": {"durak_id": "10454", "durak_adi": "Halkapinar Metro"},
    "121": {"durak_id": "10019", "durak_adi": "Bahribaba"},
    "761": {"durak_id": "50576", "durak_adi": "Yesil Yol"},
}


def collect_support_line(conn, run_id: int, line_no: str, durak_id: str) -> str:
    started_at = datetime.now(timezone.utc)
    url = SUPPORT_BASE_URL.format(hat_no=line_no, durak_id=durak_id)

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="ERROR",
            description=f"[support] Hat {line_no}/Durak {durak_id}: baglanti hatasi - {e}",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "CONNECTION_ERROR"

    if resp.status_code != 200:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="ERROR",
            description=f"[support] Hat {line_no}/Durak {durak_id}: HTTP {resp.status_code}",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "HTTP_ERROR"

    raw_text = resp.text
    if not raw_text.strip():
        # Bos response, hata degil (api-comparison.md'deki Hat 761 durumu).
        raw_text = "[]"

    try:
        vehicles = json.loads(raw_text)
    except json.JSONDecodeError:
        db_storage.log_quality_event(
            conn, stage="ingestion", severity="ERROR",
            description=f"[support] Hat {line_no}/Durak {durak_id}: JSON parse hatasi",
            ingestion_run_id=run_id, line_no=line_no,
        )
        return "JSON_PARSE_ERROR"

    snapshot_id = db_storage.save_raw_snapshot(
        conn, ingestion_run_id=run_id, source_api="hattinyaklasanotobusleri",
        line_no=line_no, requested_at=started_at, http_status=resp.status_code,
        raw_text=raw_text,
    )
    inserted = db_storage.save_supporting_observations(
        conn, raw_snapshot_id=snapshot_id, line_no=line_no,
        target_stop_id=durak_id, observed_at=started_at, vehicles=vehicles,
    )

    print(f"    -> [support] snapshot_id={snapshot_id}, {inserted} gozlem "
          f"(durak={durak_id}, bos_liste={len(vehicles) == 0})")

    return "OK"


def run_support_collector(conn, run_id: int, delay_between_lines: int = 3):
    """Tek bir cycle icin tum pilot hat+durak ciftlerini sorgular.
    Ana collector'in run_collector'i ile ayni run_id altinda cagrilmasi,
    zaman ekseninin ana API ile hizali olmasini saglar (madde 8)."""
    for i, (line_no, stop) in enumerate(PILOT_LINE_STOPS.items()):
        result = collect_support_line(conn, run_id, line_no, stop["durak_id"])
        print(f"  [support] Hat {line_no} / Durak {stop['durak_adi']}: {result}")
        if i < len(PILOT_LINE_STOPS) - 1:
            time.sleep(delay_between_lines)
