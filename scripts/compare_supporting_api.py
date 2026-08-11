"""
Gorev madde 10: Ana hat-konum API'si ile destekleyici "duraga
yaklasan otobusler" API'sini karsilastirir.
"""
import requests
import json
import time

DELAY = 3
REQUEST_TIMEOUT = 10

PILOT_LINE_STOPS = {
    "515": {"durak_id": "10454", "durak_adi": "Halkapinar Metro"},
    "121": {"durak_id": "10019", "durak_adi": "Bahribaba"},
    "761": {"durak_id": "50576", "durak_adi": "Yesil Yol"},
}


def get_json(url):
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"  BAGLANTI HATASI: {e}")
        return None
    if resp.status_code != 200:
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    try:
        return resp.json()
    except json.JSONDecodeError:
        print(f"  JSON PARSE HATASI: {resp.text[:200]}")
        return None


def compare_line(line_no, durak_id, durak_adi):
    print(f"\n{'=' * 70}")
    print(f"Hat {line_no} - Durak: {durak_adi} (ID: {durak_id})")
    print("=" * 70)

    main_url = f"https://openapi.izmir.bel.tr/api/iztek/hatotobuskonumlari/{line_no}"
    main_data = get_json(main_url)
    time.sleep(DELAY)

    support_url = f"https://openapi.izmir.bel.tr/api/iztek/hattinyaklasanotobusleri/{line_no}/{durak_id}"
    support_data = get_json(support_url)
    time.sleep(DELAY)

    if main_data is None or support_data is None:
        print("  Karsilastirma yapilamadi (API hatasi)")
        return

    main_vehicles = main_data.get("HatOtobusKonumlari", [])
    main_ids = set(v.get("OtobusId") for v in main_vehicles if v.get("OtobusId") is not None)

    support_ids = set(v.get("OtobusId") for v in support_data if v.get("OtobusId") is not None)

    print(f"Ana API - toplam arac: {len(main_vehicles)}, benzersiz ID: {len(main_ids)}")
    print(f"Destek API - bu duraga yaklasan arac: {len(support_data)}, benzersiz ID: {len(support_ids)}")

    overlap = main_ids & support_ids
    only_main = main_ids - support_ids
    only_support = support_ids - main_ids

    print(f"\nEslesen ID (her iki API'de de gorulen): {len(overlap)} -> {overlap}")
    print(f"Sadece ana API'de: {len(only_main)}")
    print(f"Sadece destek API'de: {len(only_support)} -> {only_support}")

    if support_data:
        print("\nDestek API'deki araclarin detayi (KalanDurakSayisi ile):")
        for v in support_data:
            print(f"  OtobusId={v.get('OtobusId')}, KalanDurakSayisi={v.get('KalanDurakSayisi')}, "
                  f"HatNumarasi={v.get('HatNumarasi')}, HatAdi={v.get('HatAdi')}")


if __name__ == "__main__":
    for line_no, stop in PILOT_LINE_STOPS.items():
        compare_line(line_no, stop["durak_id"], stop["durak_adi"])
        time.sleep(DELAY)
