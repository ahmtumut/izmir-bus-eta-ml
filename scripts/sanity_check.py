"""
Adim 1a: API sanity check (v2 - rate limit tespiti ile)
Amac: 3 pilot hattin API'den gercekten arac dondugunu dogrulamak
ve rate limit esigini tespit etmek.
"""
import requests
import json
import time
from datetime import datetime, timezone

BASE_URL = "https://openapi.izmir.bel.tr/api/iztek/hatotobuskonumlari/{hat_id}"

PILOT_LINES = {
    "515": "kisa/yogun sehir ici",
    "121": "orta mesafe",
    "761": "uzun guzergah",
}

DELAY_BETWEEN_REQUESTS = 3


def parse_koor(value: str) -> float:
    return float(value.replace(",", "."))


def check_line(hat_id: str, description: str):
    url = BASE_URL.format(hat_id=hat_id)
    request_time = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException as e:
        print(f"[HAT {hat_id}] BAGLANTI HATASI: {e}")
        return

    print(f"\n{'=' * 60}")
    print(f"HAT: {hat_id} ({description})")
    print(f"request_time: {request_time}")
    print(f"http_status: {resp.status_code}")
    print(f"response_time_ms: {resp.elapsed.total_seconds() * 1000:.1f}")

    if resp.status_code != 200:
        print(f"BEKLENMEYEN STATUS. Body: {resp.text[:300]}")
        return

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"JSON PARSE HATASI. Raw body: {resp.text[:300]}")
        return

    hata_mesaj = data.get("HataMesaj")
    vehicles = data.get("HatOtobusKonumlari", [])

    print(f"HataMesaj: {hata_mesaj}")
    print(f"vehicle_count: {len(vehicles)}")

    if vehicles:
        v = vehicles[0]
        print("Ilk aracin ham hali:", json.dumps(v, ensure_ascii=False))
        lat = parse_koor(v["KoorX"])
        lon = parse_koor(v["KoorY"])
        print(f"Parse edilmis koordinat -> lat: {lat}, lon: {lon}")
    else:
        print("UYARI: Bu hatta su an hic arac donmedi (bos liste).")


if __name__ == "__main__":
    lines = list(PILOT_LINES.items())
    for i, (hat_id, desc) in enumerate(lines):
        check_line(hat_id, desc)
        if i < len(lines) - 1:
            print(f"\n[{DELAY_BETWEEN_REQUESTS} saniye bekleniyor...]")
            time.sleep(DELAY_BETWEEN_REQUESTS)
