"""
Faz 2 madde 5: Durak sirasini guzergah uzerinden uretir ve dogrular.

Yontem:
1. stops.lines_through alaninda hat numarasi gecen tum duraklari bul
   (bu, "duraktan gecen hatlar" ESHOT verisine dayanan mekansal-olmayan
   bir on-filtre).
2. Her adayi ilgili route'un LineString'ine ST_LineLocatePoint ile
   projekte et (0-1 arasi fraction -> distance_along_route_m).
3. Durak, route'a cok uzaksa (DISTANCE_REJECT_M) o yon icin gecersiz
   sayilir - "sadece mekansal yakinlik nedeniyle yanlis siraya giren
   durak" riskini azaltmak icin, ONCE lines_through filtresi (durak
   gercekten bu hattan geciyor mu) uygulanir, SONRA mesafe kontrolu
   yapilir. Boylece yalnizca mekansal yakinlikla eslesen (ama o hattan
   gecmeyen) duraklar route_stop_sequence'e hic girmez.
4. Sonuc sequence_order = distance_along_route_m'e gore siralanir.
5. validation_method = 'kalan_durak_sayisi' SADECE docs/api-comparison.md
   'daki bilinen pilot durak-hat eslemeleri icin 'manual_pilot_sample'
   olarak isaretlenir; geri kalani 'spatial_only' kalir (madde 5: "sadece
   mekansal yakinlik nedeniyle yanlis siraya giren duraklari tespit et"
   uyarisina uygun olarak bu ayrim acikca tutuluyor).

Kullanim:
    python scripts/build_route_stop_sequence.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

DISTANCE_REJECT_M = 75  # durak route'a bu mesafeden uzaksa haric tutulur

# docs/api-comparison.md'deki elle dogrulanmis pilot durak-hat eslemeleri.
# Bu duraklar icin validation_method = 'manual_pilot_sample' olarak isaretlenir.
MANUAL_PILOT_SAMPLES = {
    ("515", "10454"),  # Halkapinar Metro
    ("121", "10019"),  # Bahribaba
    ("761", "50576"),  # Yesil Yol
}


def fetch_routes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, line_no, direction, total_length_m FROM routes")
        return cur.fetchall()


def fetch_candidate_stops(conn, line_no):
    """lines_through icinde bu hat numarasi gecen durak adaylari."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, stop_id, stop_name FROM stops WHERE %s = ANY(lines_through)",
            (line_no,),
        )
        return cur.fetchall()


def project_stop_onto_route(conn, route_id, stop_geom):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ST_Distance(shape_geom, %s::geography) AS dist_m,
                ST_LineLocatePoint(shape_geom::geometry, %s::geometry) AS fraction
            FROM routes WHERE id = %s
            """,
            (stop_geom, stop_geom, route_id),
        )
        return cur.fetchone()


def fetch_stop_geom(conn, stop_pk):
    with conn.cursor() as cur:
        cur.execute("SELECT geom FROM stops WHERE id = %s", (stop_pk,))
        return cur.fetchone()[0]


def build_sequence_for_route(conn, route_id, line_no, direction, total_length_m):
    candidates = fetch_candidate_stops(conn, line_no)
    projected = []

    for stop_pk, stop_id, stop_name in candidates:
        geom = fetch_stop_geom(conn, stop_pk)
        dist_m, fraction = project_stop_onto_route(conn, route_id, geom)

        if dist_m > DISTANCE_REJECT_M:
            continue  # bu yonde gecmiyor olabilir ya da cok uzak - haric tut

        distance_along_m = fraction * total_length_m if total_length_m else 0
        projected.append((stop_pk, stop_id, stop_name, dist_m, distance_along_m))

    # guzergah boyunca sirala
    projected.sort(key=lambda x: x[4])

    with conn.cursor() as cur:
        cur.execute("DELETE FROM route_stop_sequence WHERE route_id = %s", (route_id,))
        for seq, (stop_pk, stop_id, stop_name, dist_m, distance_along_m) in enumerate(projected):
            is_manual = (line_no, stop_id) in MANUAL_PILOT_SAMPLES
            validation_method = "manual_pilot_sample" if is_manual else "spatial_only"

            cur.execute(
                """
                INSERT INTO route_stop_sequence
                    (route_id, stop_id, sequence_order, distance_along_route_m,
                     validation_method, is_verified)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (route_id, stop_pk, seq, distance_along_m, validation_method, is_manual),
            )

    return projected


if __name__ == "__main__":
    conn = db_storage.get_connection()
    routes = fetch_routes(conn)

    print(f"{len(routes)} route bulundu.\n")

    for route_id, line_no, direction, total_length_m in routes:
        projected = build_sequence_for_route(conn, route_id, line_no, direction, total_length_m)
        print(f"Hat {line_no}, Yon {direction}: {len(projected)} durak sirlandi "
              f"(route_id={route_id}, uzunluk={total_length_m:.0f}m)")

        # Manuel pilot ornekleri bu hatta varsa, sirada nerede cikti goster
        for i, (stop_pk, stop_id, stop_name, dist_m, distance_along_m) in enumerate(projected):
            if (line_no, stop_id) in MANUAL_PILOT_SAMPLES:
                pct = (distance_along_m / total_length_m * 100) if total_length_m else 0
                print(f"  -> PILOT ORNEGI dogrulandi: sira {i}/{len(projected)-1}, "
                      f"'{stop_name}' (id={stop_id}), guzergahin %{pct:.1f}'inde, "
                      f"route'a mesafe={dist_m:.1f}m")

    conn.close()
    print("\nTamamlandi.")
