"""
Adim 1b: Freshness test collector
Amac: 3 pilot hatti 60 saniye araliklarla sorgulayip verinin
gercekten degistigini (freshness) kanitlamak icin ham veri biriktirmek.

Calistirma: python scripts/freshness_test.py
Durdurma: Ctrl+C (o ana kadarki veri korunur)
"""
import requests
import json
import hashlib
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://openapi.izmir.bel.tr/api/iztek/hatotobuskonumlari/{hat_id}"

PILOT_LINES = ["515", "121", "761"]

CYCLE_INTERVAL_SECONDS = 60
DELAY_BETWEEN_LINES = 3
REQUEST_TIMEOUT = 10

RAW_DIR = Path("data/raw")
LOG_FILE = Path("data/raw/freshness_log.csv")

LOG_FIELDS = [
    "hat_no", "request_time", "http_status", "response_time_ms",
    "vehicle_count", "payload_hash", "result", "error_message"
]


def ensure_log_file():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            writer.writeheader()


def append_log(row: dict):
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writerow(row)


def save_raw_response(hat_no: str, request_time_dt: datetime, raw_text: str):
    day_folder = RAW_DIR / request_time_dt.strftime("%Y-%m-%d") / f"line-{hat_no}"
    day_folder.mkdir(parents=True, exist_ok=True)
    filename = request_time_dt.strftime("%H-%M-%S") + ".json"
    filepath = day_folder / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(raw_text)


def query_line(hat_no: str):
    url = BASE_URL.format(hat_id=hat_no)
    request_time_dt = datetime.now(timezone.utc)
    request_time = request_time_dt.isoformat()

    row = {
        "hat_no": hat_no,
        "request_time": request_time,
        "http_status": None,
        "response_time_ms": None,
        "vehicle_count": None,
        "payload_hash": None,
        "result": None,
        "error_message": "",
    }

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        row["result"] = "CONNECTION_ERROR"
        row["error_message"] = str(e)[:200]
        print(f"[{request_time}] HAT {hat_no}: BAGLANTI HATASI - {e}")
        append_log(row)
        return

    row["http_status"] = resp.status_code
    row["response_time_ms"] = round(resp.elapsed.total_seconds() * 1000, 1)

    if resp.status_code == 429:
        row["result"] = "RATE_LIMITED"
        row["error_message"] = resp.text[:200]
        print(f"[{request_time}] HAT {hat_no}: RATE LIMIT (429)")
        append_log(row)
        return

    if resp.status_code != 200:
        row["result"] = "HTTP_ERROR"
        row["error_message"] = resp.text[:200]
        print(f"[{request_time}] HAT {hat_no}: HTTP {resp.status_code}")
        append_log(row)
        return

    raw_text = resp.text
    payload_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]

    try:
        data = resp.json()
        vehicles = data.get("HatOtobusKonumlari", [])
        vehicle_count = len(vehicles)
    except json.JSONDecodeError:
        row["result"] = "JSON_PARSE_ERROR"
        row["error_message"] = raw_text[:200]
        print(f"[{request_time}] HAT {hat_no}: JSON PARSE HATASI")
        append_log(row)
        return

    row["vehicle_count"] = vehicle_count
    row["payload_hash"] = payload_hash
    row["result"] = "OK"

    save_raw_response(hat_no, request_time_dt, raw_text)
    append_log(row)

    print(f"[{request_time}] HAT {hat_no}: OK - {vehicle_count} arac - hash {payload_hash}")


def run():
    ensure_log_file()
    print(f"Freshness test basladi. Log dosyasi: {LOG_FILE}")
    print(f"Pilot hatlar: {PILOT_LINES}")
    print("Durdurmak icin Ctrl+C\n")

    cycle_num = 0
    try:
        while True:
            cycle_num += 1
            cycle_start = time.monotonic()
            print(f"\n--- Cycle {cycle_num} basladi ---")

            for i, hat_no in enumerate(PILOT_LINES):
                query_line(hat_no)
                if i < len(PILOT_LINES) - 1:
                    time.sleep(DELAY_BETWEEN_LINES)

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, CYCLE_INTERVAL_SECONDS - elapsed)
            print(f"--- Cycle {cycle_num} bitti ({elapsed:.1f}s surdu), {sleep_time:.1f}s bekleniyor ---")
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\n\nDurduruldu. Toplam {cycle_num} cycle tamamlandi.")
        print(f"Sonuclari incelemek icin: {LOG_FILE}")


if __name__ == "__main__":
    run()
