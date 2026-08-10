"""
Adim 2 - on calisma: Destekleyici API'lerin gercek response semasini dogrulama.
Dokumandaki ornek ID'ler kullanilir (hatId=446, durakId=21056 / durakId=21050).
"""
import requests
import json
import time

DELAY = 3

def test_endpoint(name, url):
    print(f"\n{'=' * 60}")
    print(f"{name}")
    print(f"URL: {url}")
    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException as e:
        print(f"BAGLANTI HATASI: {e}")
        return
    print(f"http_status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:300]}")
        return
    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"JSON PARSE HATASI. Raw: {resp.text[:300]}")
        return
    print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    test_endpoint(
        "Duraga Yaklasan Otobusler (durakId=21050, dokuman ornegi)",
        "https://openapi.izmir.bel.tr/api/iztek/duragayaklasanotobusler/21050"
    )
    time.sleep(DELAY)

    test_endpoint(
        "Hattin Duraga Yaklasan Otobusleri (hatId=446, durakId=21056, dokuman ornegi)",
        "https://openapi.izmir.bel.tr/api/iztek/hattinyaklasanotobusleri/446/21056"
    )
    time.sleep(DELAY)

    test_endpoint(
        "Ana API karsilastirma icin (hatId=446, dokuman ornegi)",
        "https://openapi.izmir.bel.tr/api/iztek/hatotobuskonumlari/446"
    )
