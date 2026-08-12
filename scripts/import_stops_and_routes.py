"""
Faz 2 madde 3 + 4: ESHOT durak ve hat guzergah verilerini PostgreSQL/PostGIS'e
aktarir.

- Tum duraklar data/reference/eshot-otobus-duraklari.csv'den `stops` tablosuna.
- Sadece PILOT_LINES icin guzergah noktalari
  data/reference/eshot-otobus-hat-guzergahlari.csv'den `routes` +
  `route_shape_points` tablolarina. Dosyadaki satir sirasi, guzergah
  boyunca doğru nokta sirasi olarak kabul edilir (ayni hat+yon icin
  ardisik satirlar halinde geldigi dogrulandi).

Kaynagin URL'si, indirilme zamani ve SHA-256 hash'i data_sources
tablosunda tutulur (madde 3 gereksinimi).

Kullanim:
    python scripts/import_stops_and_routes.py \
        --stops-csv data/reference/eshot-otobus-duraklari.csv \
        --routes-csv data/reference/eshot-otobus-hat-guzergahlari.csv
"""
import argparse
import csv
import hashlib
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

PILOT_LINES = {"515", "121", "761"}

# Kaynak URL'leri bilinmiyor/elde yoksa acikca boyle isaretleniyor -
# gercek indirme kaynagi biliniyorsa bu degerleri guncelle.
STOPS_SOURCE_NAME = "ESHOT_Otobus_Duraklari"
STOPS_SOURCE_URL = "acikveri.bizizmir.com (yerel CSV, tam kaynak URL dogrulanmadi)"
ROUTES_SOURCE_NAME = "ESHOT_Otobus_Hat_Guzergahlari"
ROUTES_SOURCE_URL = "acikveri.bizizmir.com (yerel CSV, tam kaynak URL dogrulanmadi)"


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def register_data_source(conn, source_name, source_url, file_path: Path) -> int:
    content_hash = sha256_of_file(file_path)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_sources (source_name, source_url, downloaded_at, content_sha256)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_name, content_sha256) DO NOTHING
            RETURNING id
            """,
            (source_name, source_url, datetime.now(timezone.utc), content_hash),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "SELECT id FROM data_sources WHERE source_name = %s AND content_sha256 = %s",
            (source_name, content_hash),
        )
        return cur.fetchone()[0]


def import_stops(conn, csv_path: Path, data_source_id: int) -> int:
    inserted = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        with conn.cursor() as cur:
            for row in reader:
                stop_id = row["DURAK_ID"].strip()
                stop_name = row["DURAK_ADI"].strip()
                lat = float(row["ENLEM"])
                lon = float(row["BOYLAM"])
                lines_raw = row.get("DURAKTAN_GECEN_HATLAR", "").strip()
                lines_through = [x for x in lines_raw.split("-") if x] if lines_raw else []

                cur.execute(
                    """
                    INSERT INTO stops (stop_id, stop_name, geom, lines_through, data_source_id)
                    VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s)
                    ON CONFLICT (stop_id) DO UPDATE SET
                        stop_name = EXCLUDED.stop_name,
                        geom = EXCLUDED.geom,
                        lines_through = EXCLUDED.lines_through,
                        data_source_id = EXCLUDED.data_source_id
                    """,
                    (stop_id, stop_name, lon, lat, lines_through, data_source_id),
                )
                inserted += 1
    return inserted


def import_routes(conn, csv_path: Path, data_source_id: int) -> dict:
    """Sadece PILOT_LINES icin route + route_shape_points olusturur.
    Sonuc: {(hat, yon): nokta_sayisi}"""
    # Once tum ilgili satirlari, dosyadaki sirayla, hat+yon'a gore grupla.
    groups = defaultdict(list)  # (hat_no, yon) -> [(lon, lat), ...]
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            hat_no = row["HAT_NO"].strip()
            if hat_no not in PILOT_LINES:
                continue
            yon_raw = row["YON"].strip()
            lat = float(row["ENLEM"])
            lon = float(row["BOYLAM"])
            groups[(hat_no, yon_raw)].append((lon, lat))

    results = {}
    with conn.cursor() as cur:
        for (hat_no, yon_raw), points in groups.items():
            # YON: 1 -> direction 0 (gidis), 2 -> direction 1 (donus)
            direction = 0 if yon_raw == "1" else 1

            wkt_points = ", ".join(f"{lon} {lat}" for lon, lat in points)
            linestring_wkt = f"LINESTRING({wkt_points})"

            cur.execute(
                """
                INSERT INTO routes (line_no, direction, shape_geom, data_source_id)
                VALUES (%s, %s, ST_GeogFromText('SRID=4326;' || %s), %s)
                ON CONFLICT (line_no, direction) DO UPDATE SET
                    shape_geom = EXCLUDED.shape_geom,
                    data_source_id = EXCLUDED.data_source_id
                RETURNING id
                """,
                (hat_no, direction, linestring_wkt, data_source_id),
            )
            route_id = cur.fetchone()[0]

            cur.execute(
                "UPDATE routes SET total_length_m = ST_Length(shape_geom) WHERE id = %s",
                (route_id,),
            )

            # Eski shape point'leri temizle (tekrar calistirmada duplicate olmasin)
            cur.execute("DELETE FROM route_shape_points WHERE route_id = %s", (route_id,))
            for seq, (lon, lat) in enumerate(points):
                cur.execute(
                    """
                    INSERT INTO route_shape_points (route_id, seq, geom)
                    VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                    """,
                    (route_id, seq, lon, lat),
                )

            results[(hat_no, yon_raw)] = len(points)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stops-csv", required=True)
    parser.add_argument("--routes-csv", required=True)
    args = parser.parse_args()

    stops_path = Path(args.stops_csv)
    routes_path = Path(args.routes_csv)

    conn = db_storage.get_connection()

    print(f"Durak kaynagi kaydediliyor: {stops_path}")
    stops_source_id = register_data_source(conn, STOPS_SOURCE_NAME, STOPS_SOURCE_URL, stops_path)
    print(f"  data_source_id={stops_source_id}")

    print("Duraklar iceri aktariliyor...")
    n_stops = import_stops(conn, stops_path, stops_source_id)
    print(f"  {n_stops} durak islendi (insert/update).")

    print(f"\nGuzergah kaynagi kaydediliyor: {routes_path}")
    routes_source_id = register_data_source(conn, ROUTES_SOURCE_NAME, ROUTES_SOURCE_URL, routes_path)
    print(f"  data_source_id={routes_source_id}")

    print(f"Pilot hatlar icin guzergah aktariliyor: {sorted(PILOT_LINES)}")
    results = import_routes(conn, routes_path, routes_source_id)
    for (hat_no, yon_raw), n_points in sorted(results.items()):
        print(f"  Hat {hat_no}, Yon {yon_raw}: {n_points} nokta")

    conn.close()
    print("\nTamamlandi.")
