"""
Adim 1c: Freshness sonuc analizi
Amac: freshness_log.csv ve data/raw altindaki ham JSON dosyalarini okuyup
gorev metninin istedigi formatta CANLI / SUPHELI / SABIT raporu uretmek.
"""
import csv
import json
from pathlib import Path
from collections import defaultdict

LOG_FILE = Path("data/raw/freshness_log.csv")
RAW_DIR = Path("data/raw")

MOVEMENT_THRESHOLD_DEGREES = 0.0001  # ~11 metre - bunun altindaki fark "hareketsiz" sayilir


def parse_koor(value: str) -> float:
    return float(value.replace(",", "."))


def load_log():
    rows = []
    with open(LOG_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_raw_jsons_for_line(hat_no: str):
    files = sorted(RAW_DIR.glob(f"*/line-{hat_no}/*.json"))
    results = []
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            vehicles = data.get("HatOtobusKonumlari", [])
            results.append((fp.name, vehicles))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def analyze_line(hat_no: str, log_rows: list):
    line_rows = [r for r in log_rows if r["hat_no"] == hat_no]
    ok_rows = [r for r in line_rows if r["result"] == "OK"]

    sorgu_sayisi = len(line_rows)
    farkli_payload = len(set(r["payload_hash"] for r in ok_rows if r["payload_hash"]))

    raw_snapshots = load_raw_jsons_for_line(hat_no)

    vehicle_positions = defaultdict(list)
    all_vehicle_ids = set()

    for fname, vehicles in raw_snapshots:
        for v in vehicles:
            vid = v.get("OtobusId")
            if vid is None:
                continue
            all_vehicle_ids.add(vid)
            try:
                lat = parse_koor(v["KoorX"])
                lon = parse_koor(v["KoorY"])
            except (KeyError, ValueError):
                continue
            vehicle_positions[vid].append((fname, lat, lon))

    hareket_eden = 0
    stale_vehicles = []

    for vid, positions in vehicle_positions.items():
        if len(positions) < 2:
            continue
        moved = False
        current_run = 1
        longest_run = 1
        for i in range(1, len(positions)):
            _, lat1, lon1 = positions[i - 1]
            _, lat2, lon2 = positions[i]
            diff = abs(lat1 - lat2) + abs(lon1 - lon2)
            if diff > MOVEMENT_THRESHOLD_DEGREES:
                moved = True
                current_run = 1
            else:
                current_run += 1
                longest_run = max(longest_run, current_run)
        if moved:
            hareket_eden += 1
        if longest_run >= 3:
            stale_vehicles.append((vid, longest_run))

    goruldu_arac = len(all_vehicle_ids)

    snapshot_sets = [
        set(v.get("OtobusId") for v in vehicles if v.get("OtobusId") is not None)
        for _, vehicles in raw_snapshots
    ]
    giris_sayisi = 0
    cikis_sayisi = 0
    for i in range(1, len(snapshot_sets)):
        giris_sayisi += len(snapshot_sets[i] - snapshot_sets[i - 1])
        cikis_sayisi += len(snapshot_sets[i - 1] - snapshot_sets[i])

    ok_hashes = [r["payload_hash"] for r in ok_rows if r["payload_hash"]]
    degisim_sayisi = sum(1 for i in range(1, len(ok_hashes)) if ok_hashes[i] != ok_hashes[i - 1])
    karsilastirma_sayisi = max(1, len(ok_hashes) - 1)
    degisim_orani = degisim_sayisi / karsilastirma_sayisi
    tahmini_guncelleme_sn = round(60 / degisim_orani, 1) if degisim_orani > 0 else None

    if sorgu_sayisi == 0:
        sonuc = "VERI YOK"
    elif farkli_payload <= 1:
        sonuc = "SABIT"
    elif goruldu_arac > 0 and hareket_eden == 0:
        sonuc = "SUPHELI"
    elif hareket_eden > 0:
        sonuc = "CANLI"
    else:
        sonuc = "SUPHELI"

    return {
        "hat_no": hat_no,
        "sorgu_sayisi": sorgu_sayisi,
        "basarili_sorgu": len(ok_rows),
        "goruldu_arac": goruldu_arac,
        "farkli_payload": farkli_payload,
        "hareket_eden_arac": hareket_eden,
        "stale_vehicles": stale_vehicles,
        "giris_sayisi": giris_sayisi,
        "cikis_sayisi": cikis_sayisi,
        "tahmini_guncelleme_sn": tahmini_guncelleme_sn,
        "sonuc": sonuc,
    }


def main():
    log_rows = load_log()
    hat_numaralari = sorted(set(r["hat_no"] for r in log_rows))

    print("=" * 60)
    print("FRESHNESS TEST SONUC RAPORU")
    print("=" * 60)

    for hat_no in hat_numaralari:
        result = analyze_line(hat_no, log_rows)
        print(f"\nHat: {result['hat_no']}")
        print(f"Sorgu sayisi: {result['sorgu_sayisi']} (basarili: {result['basarili_sorgu']})")
        print(f"Gorulen arac: {result['goruldu_arac']}")
        print(f"Farkli payload: {result['farkli_payload']}")
        print(f"Hareket ettigi gozlenen arac: {result['hareket_eden_arac']}")
        if result["stale_vehicles"]:
            stale_str = ", ".join(f"arac {vid} ({run} ardisik ayni konum)" for vid, run in result["stale_vehicles"])
            print(f"Uzun sure ayni konumda kalan arac(lar): {stale_str}")
        else:
            print("Uzun sure ayni konumda kalan arac: yok (3+ ardisik gozlemde)")
        print(f"Listeye giren arac (toplam, ardisik snapshotlar arasi): {result['giris_sayisi']}")
        print(f"Listeden cikan arac (toplam, ardisik snapshotlar arasi): {result['cikis_sayisi']}")
        if result["tahmini_guncelleme_sn"] is not None:
            print(f"Tahmini API guncelleme periyodu: ~{result['tahmini_guncelleme_sn']} saniye")
        else:
            print("Tahmini API guncelleme periyodu: hesaplanamadi (yetersiz veri)")
        print(f"Sonuc: {result['sonuc']}")

    error_rows = [r for r in log_rows if r["result"] not in ("OK",)]
    print(f"\n{'=' * 60}")
    print(f"Toplam hatali/rate-limit sonuc: {len(error_rows)} / {len(log_rows)}")


if __name__ == "__main__":
    main()
