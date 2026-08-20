"""
Pilot hat guzergahlarini resmi ESHOT GTFS `shapes.txt` dosyasindan
`routes`/`route_shape_points` tablolarina aktarir (mevcut ESHOT CSV
kaynaklarindan turetilen, ~11m'ye yuvarlanmis dusuk cozunurluklu geometrinin
yerini alir - GTFS shape noktalari sub-metre hassasiyette ve gercek yol
agina zaten oturmus durumda).

BILINCLI SINIRLAMA: Sadece `routes.shape_geom` + `route_shape_points`
guncellenir. `stops`/`route_stop_sequence` (durak noktalari ve durak->rota
mesafeleri) BU SCRIPT TARAFINDAN DOKUNULMAZ - kullanici acikca durak
noktalarinin sabit kalmasini istedi. Bunun sonucu: route_stop_sequence
tablosundaki distance_along_route_m degerleri ESKI geometriye gore
hesaplanmis kaldi; yeni geometriyle hafif tutarsiz olabilir (rota
uzunlugu/sekli degisti). Bu script'i calistirdiktan sonra durak sirasini
da guncellemek istenirse ayrica `scripts/build_route_stop_sequence.py`
calistirilmali - ama bu, kullanicinin bu turdaki talebinin disinda.

GTFS dosyalarinda route_id, ESHOT'un hat numarasiyla (511, 121, 761 vb.)
birebir ayni degerde geldigi routes.txt uzerinden dogrulandi. trips.txt'te
her pilot hat icin YALNIZCA iki shape_id var (direction_id 0 ve 1) - "1<hat>"
sekli gidis (direction 0), "2<hat>" sekli donus (direction 1) icin
kullaniliyor; bu, DB'deki mevcut baslangic/bitis noktalariyla karsilastirilarak
dogrulandi (bkz. gorev notlari).

Kullanim:
    python scripts/import_gtfs_route_shapes.py \
        --shapes-txt "C:\\Users\\ahmet\\Downloads\\bus-eshot-gtfs\\shapes.txt"
"""
import argparse
import hashlib
import sys
from collections import defaultdict
from csv import DictReader
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

PILOT_LINES = ["515", "121", "761"]

SOURCE_NAME = "ESHOT_GTFS_Shapes"
SOURCE_URL = "ESHOT GTFS feed (yerel dosya, tam indirme URL'si dogrulanmadi)"


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def register_data_source(conn, file_path: Path) -> int:
    content_hash = sha256_of_file(file_path)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_sources (source_name, source_url, downloaded_at, content_sha256)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_name, content_sha256) DO NOTHING
            RETURNING id
            """,
            (SOURCE_NAME, SOURCE_URL, datetime.now(timezone.utc), content_hash),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "SELECT id FROM data_sources WHERE source_name = %s AND content_sha256 = %s",
            (SOURCE_NAME, content_hash),
        )
        return cur.fetchone()[0]


def load_shapes(shapes_path: Path, wanted_shape_ids: set[str]) -> dict[str, list[tuple[float, float]]]:
    """shape_id -> [(lon, lat), ...] sirali (shape_pt_sequence'e gore)."""
    points_by_shape: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    with open(shapes_path, encoding="utf-8-sig", newline="") as f:
        reader = DictReader(f)
        for row in reader:
            shape_id = row["shape_id"].strip()
            if shape_id not in wanted_shape_ids:
                continue
            seq = int(row["shape_pt_sequence"])
            lat = float(row["shape_pt_lat"])
            lon = float(row["shape_pt_lon"])
            points_by_shape[shape_id].append((seq, lon, lat))

    result = {}
    for shape_id, pts in points_by_shape.items():
        pts.sort(key=lambda p: p[0])
        result[shape_id] = [(lon, lat) for _, lon, lat in pts]
    return result


def upsert_route(conn, line_no: str, direction: int, points: list[tuple[float, float]], data_source_id: int) -> int:
    wkt_points = ", ".join(f"{lon} {lat}" for lon, lat in points)
    linestring_wkt = f"LINESTRING({wkt_points})"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO routes (line_no, direction, shape_geom, data_source_id)
            VALUES (%s, %s, ST_GeogFromText('SRID=4326;' || %s), %s)
            ON CONFLICT (line_no, direction) DO UPDATE SET
                shape_geom = EXCLUDED.shape_geom,
                data_source_id = EXCLUDED.data_source_id
            RETURNING id
            """,
            (line_no, direction, linestring_wkt, data_source_id),
        )
        route_id = cur.fetchone()[0]

        cur.execute(
            "UPDATE routes SET total_length_m = ST_Length(shape_geom) WHERE id = %s",
            (route_id,),
        )

        cur.execute("DELETE FROM route_shape_points WHERE route_id = %s", (route_id,))
        for seq, (lon, lat) in enumerate(points):
            cur.execute(
                """
                INSERT INTO route_shape_points (route_id, seq, geom)
                VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                """,
                (route_id, seq, lon, lat),
            )

    return route_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shapes-txt", required=True)
    args = parser.parse_args()

    shapes_path = Path(args.shapes_txt)

    # direction 0 -> "1<hat>" shape'i, direction 1 -> "2<hat>" shape'i
    # (routes.txt/trips.txt uzerinden dogrulandi - bkz. modul docstring'i).
    shape_id_map = {}
    for line_no in PILOT_LINES:
        shape_id_map[(line_no, 0)] = f"1{line_no}"
        shape_id_map[(line_no, 1)] = f"2{line_no}"
    wanted_shape_ids = set(shape_id_map.values())

    conn = db_storage.get_connection()

    print(f"GTFS shapes kaynagi kaydediliyor: {shapes_path}")
    data_source_id = register_data_source(conn, shapes_path)
    print(f"  data_source_id={data_source_id}")

    print(f"Shape noktalari okunuyor (hedef shape_id'ler: {sorted(wanted_shape_ids)})...")
    shapes = load_shapes(shapes_path, wanted_shape_ids)
    for shape_id in sorted(wanted_shape_ids):
        n = len(shapes.get(shape_id, []))
        print(f"  {shape_id}: {n} nokta")
        if n == 0:
            print(f"  UYARI: {shape_id} icin nokta bulunamadi, atlaniyor.")

    print("\nroutes / route_shape_points guncelleniyor (stops/route_stop_sequence DOKUNULMUYOR)...")
    for (line_no, direction), shape_id in sorted(shape_id_map.items()):
        points = shapes.get(shape_id)
        if not points:
            continue
        route_id = upsert_route(conn, line_no, direction, points, data_source_id)
        print(f"  Hat {line_no}, direction {direction} (shape {shape_id}): {len(points)} nokta -> route_id={route_id}")

    conn.commit()
    conn.close()
    print("\nTamamlandi.")
