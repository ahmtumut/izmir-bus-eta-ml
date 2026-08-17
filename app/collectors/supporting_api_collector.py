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

# Faz 3 GOLD validation (v2 - supervisor duzeltmesi): ilk denemede 9 ek durak
# (3/hat) eklenmisti, ama bunlar normal 60sn cycle'la sorgulaninca genislik
# artti, DERINLIK artmadi - varis penceresi (~60-120sn) icine nadiren 2. bir
# support-API ornegi dusebildi (0 HIGH confidence sonucu). Supervisor talebi:
# "butun duraklari surekli sorgulamak yerine SECILMIS BIRKAC durakta KONTROLLU
# validation penceresi" - yani genislik yerine derinlik. Bu yuzden:
#   - Her hatta durak sayisi 3'ten 1'e indirildi (pilot durak + en cok arrival
#     event ureten 1 ek durak, ilk denemenin verisine gore secildi).
#   - Bu az sayidaki durak, GOLD burst penceresinde run_dual_collector.py
#     tarafindan cok daha sik (varsayilan 30sn) sorgulanir (bkz. run_gold_burst).
GOLD_VALIDATION_STOPS = {
    "515": [
        {"durak_id": "10454", "durak_adi": "Halkapinar Metro"},  # pilot durak
        {"durak_id": "30300", "durak_adi": "Adalet Mahallesi"},  # ilk denemede en cok arrival event (14)
    ],
    "121": [
        {"durak_id": "10019", "durak_adi": "Bahribaba"},  # pilot durak
        {"durak_id": "20135", "durak_adi": "Bayrakli Ust Gecit"},  # ilk denemede en cok arrival event (8)
    ],
    "761": [
        {"durak_id": "50576", "durak_adi": "Yesil Yol"},  # pilot durak
        {"durak_id": "51615", "durak_adi": "Mordogan Gunbatimi"},  # ilk denemede tek arrival event yakalayan validation duragi
    ],
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


def run_support_collector(conn, run_id: int, delay_between_lines: int = 3, lines: list = None):
    """Tek bir cycle icin pilot hat+durak ciftlerini sorgular.
    Ana collector'in run_collector'i ile ayni run_id altinda cagrilmasi,
    zaman ekseninin ana API ile hizali olmasini saglar (madde 8).
    lines verilirse (ör. ['761']) sadece o hatlar sorgulanir - hat bazinda
    hedefli veri toplama oturumlari icin (bkz. run_dual_collector.py --lines)."""
    stops = {k: v for k, v in PILOT_LINE_STOPS.items() if lines is None or k in lines}
    for i, (line_no, stop) in enumerate(stops.items()):
        result = collect_support_line(conn, run_id, line_no, stop["durak_id"])
        print(f"  [support] Hat {line_no} / Durak {stop['durak_adi']}: {result}")
        if i < len(stops) - 1:
            time.sleep(delay_between_lines)


def run_gold_validation_collector(conn, run_id: int, delay_between_calls: int = 2, lines: list = None):
    """GOLD_VALIDATION_STOPS'taki hat+durak ciftlerini bir kez sorgular.
    run_dual_collector.py'deki run_gold_burst() bunu GOLD validation
    penceresinde sik araliklarla (varsayilan 30sn) cagirir - amac az sayida
    durakta yuksek zamansal cozunurluk elde etmek (bkz. GOLD_VALIDATION_STOPS
    yorumu). lines verilirse sadece o hatlarin duraklari sorgulanir."""
    pairs = [
        (line_no, stop)
        for line_no, stops in GOLD_VALIDATION_STOPS.items()
        if lines is None or line_no in lines
        for stop in stops
    ]
    for i, (line_no, stop) in enumerate(pairs):
        result = collect_support_line(conn, run_id, line_no, stop["durak_id"])
        print(f"    [gold] Hat {line_no} / Durak {stop['durak_adi']}: {result}")
        if i < len(pairs) - 1:
            time.sleep(delay_between_calls)
