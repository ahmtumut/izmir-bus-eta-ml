"""Faz 4: canli veri modu - collector'in su an aktif olup olmadigini ve en
son arac konumlarini sunar. Dis API'ye (Izmir Belediyesi) HICBIR yeni cagri
eklemez - sadece ic Postgres DB'yi sorgular (collector ayri bir terminalde
kullanici tarafindan manuel calistirilir, bkz. scripts/run_dual_collector.py).
"""
import math
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.api.db import get_read_connection

router = APIRouter(prefix="/api/live", tags=["live"])

# Ayni (vehicle_id, observed_at) icin birden fazla satirin ham konumlari
# bu mesafeden fazla ayrisiyorsa, bu vehicle_id'nin gercekten farkli
# fiziksel araclar arasinda "collision" yasadigi kabul edilir (bkz.
# get_live_observations docstring) - GERCEK bir 1-2 metrelik GPS gurultusu
# degil, ayni ID altinda birbirinden km'lerce uzak iki farkli konum.
DUPLICATE_ID_CONFLICT_THRESHOLD_M = 300


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    to_rad = math.pi / 180
    d_lat = (lat2 - lat1) * to_rad
    d_lon = (lon2 - lon1) * to_rad
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1 * to_rad) * math.cos(lat2 * to_rad) * math.sin(d_lon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))

# scripts/run_dual_collector.py: CYCLE_INTERVAL_SECONDS=60 - normal dongude
# her hat ~60sn'de bir guncelleniyor. 90sn esigi (60sn + tampon) collector
# canli ama tam bu anda bir cagri arasindaysa yanlislikla "pasif" denmesini
# onler.
ACTIVE_STALENESS_SECONDS = 90
PILOT_LINES = ["515", "121", "761"]


@router.get("/status")
def get_live_status():
    with get_read_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at, ended_at
            FROM ingestion_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
        run = cur.fetchone()

        cur.execute("SELECT MAX(observed_at) AS latest FROM vehicle_observations")
        latest_row = cur.fetchone()

    latest_observation_at = latest_row["latest"] if latest_row else None
    seconds_since_last_observation = None
    if latest_observation_at is not None:
        seconds_since_last_observation = (
            datetime.now(timezone.utc) - latest_observation_at
        ).total_seconds()

    # Cokmus bir collector ended_at'i hic set etmez - tek basina
    # "ended_at IS NULL" guvenilir degil, gozlem tazeligiyle birlikte
    # degerlendiriliyor.
    run_open = bool(run and run["ended_at"] is None)
    is_fresh = (
        seconds_since_last_observation is not None
        and seconds_since_last_observation <= ACTIVE_STALENESS_SECONDS
    )
    collector_active = run_open and is_fresh

    return {
        "collector_active": collector_active,
        "latest_run_id": run["id"] if run else None,
        "run_open": run_open,
        "latest_observation_at": latest_observation_at.isoformat() if latest_observation_at else None,
        "seconds_since_last_observation": seconds_since_last_observation,
    }


@router.get("/observations")
def get_live_observations(
    line_no: str | None = Query(None, description="virgulle ayrilmis hat listesi"),
    max_age_seconds: int = Query(ACTIVE_STALENESS_SECONDS, ge=1, le=3600),
):
    """Her vehicle_id icin EN SON gozlem (max_age_seconds'tan daha eski
    olanlar bayat kabul edilip elenir). Replay modundaki felsefeyle tutarli:
    REJECTED gozlemler de donuyor (gorsel amacli, gri gosterilir), sadece
    frontend katmanlari (vehicleLayer/etaLayer) bunlari nasil isleyecegine
    karar veriyor - burada filtrelenmiyor.

    KRITIK: Izmir Belediyesi API'si TEK BIR pollde AYNI vehicle_id'yi
    BIRDEN FAZLA kez, FARKLI konumlarla dondurebiliyor (muhtemelen farkli
    fiziksel araclarin ayni ID'yi paylasmasi/collision - dokumante
    edilmemis bir API kusuru). Ayni (vehicle_id, observed_at) icin birden
    fazla satir oldugunda eski sorgu (sadece "ORDER BY vehicle_id,
    observed_at DESC") TIE-BREAK icin DETERMINISTIK DEGILDI - Postgres
    hangi satiri once dondurecegini garanti etmiyor, bu da ayni aracin
    pollden polle FARKLI FIZIKSEL KONUMLAR arasinda "zipliyormus" gibi
    gorunmesine yol aciyordu (frontend'deki interpolasyon/hiz kontrolleri
    bunu cozemez, cunku her polldeki tek deger kendi icinde tutarli
    gorunur). Duzeltme: esitlikte ONCE ehli GOOD/DEGRADED (REJECTED'a
    tercih edilir), SONRA da satirin kendi `id`'si (deterministik, kararli
    bir tie-break) kullanilir - boylece ayni poll'da tekrar calistirilsa
    bile HEP AYNI satir secilir.

    Ama tie-break tek basina yeterli degil: eger vehicle_id GERCEKTEN iki
    farkli fiziksel araca aitse (collision), ardisik poll'larda HANGI
    "yaris"in secilecegi ESHOT'un kendi cevap sirasina bagli kalmaya devam
    eder ve arac pollden polle iki uzak konum arasinda "zipliyormus" gibi
    gorunmeye devam edebilir.

    ILK DENEME (TAMAMEN DISLAMA) BASARISIZ OLDU: ayni en-iyi-kalite
    katmaninda birden fazla, birbirinden uzak konum varsa o vehicle_id'yi
    o poll'un sonucundan tamamen cikarmak once denendi - ama bu belirsizlik
    NADIR degil, bircok arac icin NEREDEYSE HER POLLDE ortaya cikan yaygin
    bir durum oldugu ortaya cikti (ESHOT API'sinde vehicle_id collision'i
    dusunulenden daha genis capli). Sonuc: dislanan araclar pollarin
    yarisinda hic guncellenmeyip freezeAtEnd sayesinde "donup kaliyor" -
    yakininda durak olmamasina ragmen rotanin ortasinda hareketsiz duran
    otobus seklinde gozlemleniyordu (kullanicinin bildirdigi sorun).

    DUZELTME (UZAMSAL SUREKLILIK): artik belirsizlik oldugunda arac hic
    dislanmiyor - bunun yerine, adaylardan HANGISI bu aracin BIR ONCEKI
    bilinen konumuna daha yakinsa O secilir (gercek fiziksel bir aracin
    konumu pollar arasinda buyuk sicramalar yapmaz, bu yuzden "onceki
    konuma yakinlik" guvenilir bir ayirt edici). Onceki konum yoksa (aracin
    ilk gorulme ani) deterministik tie-break'in zaten sectigi satir
    KORUNUR - hicbir zaman veri tamamen atilmiyor.

    HENUZ MAP-MATCH EDILMEMIS (map_match_quality IS NULL) SATIRLAR HARIC
    TUTULUR: collector once GPS'i toplar (satir NULL kaliteyle eklenir),
    map-matching AYRI bir adimda (dongu sonunda) bu satiri GUNCELLER. Bu
    ikisi arasindaki kisa pencerede bir poll tam bu ANA denk gelirse, arac
    HENUZ ROTAYA PROJEKTE EDILMEMIS HAM konumuyla (kalite bilgisi olmadan)
    gosterilir - yol/rota disinda (orn. bir kanal kenarinda) suzuluyormus
    gibi gorunur (kullanicinin ekran goruntusunde yakaladigi sorun).
    Duzeltme: bu satirlar en bastan HARIC TUTULUR, DISTINCT ON dogal olarak
    bir onceki (zaten eslesmis) gozleme duser - birkac saniyelik gecikme
    pahasina, hatali/yarim veri asla gosterilmez."""
    lines = [v.strip() for v in line_no.split(",")] if line_no else PILOT_LINES

    with get_read_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (vehicle_id)
                   vehicle_id, line_no, observed_at, raw_lat, raw_lon,
                   route_id, position_quality, map_match_quality,
                   distance_along_route_m, progress_along_route, distance_to_route_m
            FROM vehicle_observations
            WHERE line_no = ANY(%s)
              AND observed_at >= now() - (%s * INTERVAL '1 second')
              AND map_match_quality IS NOT NULL
            ORDER BY vehicle_id, observed_at DESC,
                     CASE map_match_quality
                       WHEN 'GOOD' THEN 0
                       WHEN 'DEGRADED' THEN 1
                       WHEN 'REJECTED' THEN 2
                       ELSE 3
                     END,
                     id DESC
            """,
            (lines, max_age_seconds),
        )
        rows = cur.fetchall()

        if rows:
            cur.execute(
                """
                SELECT vehicle_id, line_no, observed_at, raw_lat, raw_lon,
                       route_id, position_quality, map_match_quality,
                       distance_along_route_m, progress_along_route, distance_to_route_m
                FROM vehicle_observations
                WHERE (vehicle_id, observed_at) IN (
                    SELECT UNNEST(%s::text[]), UNNEST(%s::timestamptz[])
                )
                """,
                ([r["vehicle_id"] for r in rows], [r["observed_at"] for r in rows]),
            )
            dup_rows = cur.fetchall()
        else:
            dup_rows = []

        # Sadece EN IYI kalite katmanindaki ("GOOD" varsa sadece GOOD'lar,
        # yoksa sadece DEGRADED'lar, o da yoksa REJECTED'lar) kopyalar
        # birbiriyle KARSILASTIRILIR - dusuk kaliteli/hayalet bir "phantom"
        # kopyanin (genelde sabit/park halindeki baska bir arac) varligi TEK
        # BASINA belirsizlik sayilmaz. Sadece AYNI EN IYI katmanda BIRDEN
        # FAZLA, birbirinden uzak konum varsa gercekten hangisinin dogru
        # oldugu belirsizdir.
        quality_rank = {"GOOD": 0, "DEGRADED": 1, "REJECTED": 2}
        best_rank_by_vehicle: dict[str, int] = {}
        for d in dup_rows:
            rank = quality_rank.get(d["map_match_quality"], 3)
            vid = d["vehicle_id"]
            if vid not in best_rank_by_vehicle or rank < best_rank_by_vehicle[vid]:
                best_rank_by_vehicle[vid] = rank

        # TAM satirlar saklanir (sadece lat/lon degil) - aksi halde secilen
        # adayin ham konumunu baska bir adayin route_id/distance_along_route_m
        # gibi alanlariyla karistirip (iki FARKLI fiziksel aracin verisini
        # birlestirip) tutarsiz/yanlis bir rota-izdusumu uretebilirdik.
        candidates_by_vehicle: dict[str, list[dict]] = {}
        for d in dup_rows:
            vid = d["vehicle_id"]
            if quality_rank.get(d["map_match_quality"], 3) == best_rank_by_vehicle[vid]:
                candidates_by_vehicle.setdefault(vid, []).append(d)

        ambiguous_vehicle_ids = [
            vid for vid, cands in candidates_by_vehicle.items()
            if len(cands) > 1
            and any(
                _haversine_m(cands[i]["raw_lat"], cands[i]["raw_lon"], cands[j]["raw_lat"], cands[j]["raw_lon"]) > DUPLICATE_ID_CONFLICT_THRESHOLD_M
                for i in range(len(cands)) for j in range(i + 1, len(cands))
            )
        ]

        rows_by_vehicle = {r["vehicle_id"]: r for r in rows}
        for vid in ambiguous_vehicle_ids:
            cur.execute(
                """
                SELECT raw_lat, raw_lon FROM vehicle_observations
                WHERE vehicle_id = %s AND observed_at < %s
                ORDER BY observed_at DESC
                LIMIT 1
                """,
                (vid, rows_by_vehicle[vid]["observed_at"]),
            )
            prev = cur.fetchone()
            if prev is None:
                continue  # ilk gorulme - deterministik tie-break'in secimi korunur
            best_candidate = min(
                candidates_by_vehicle[vid],
                key=lambda c: _haversine_m(c["raw_lat"], c["raw_lon"], prev["raw_lat"], prev["raw_lon"]),
            )
            rows_by_vehicle[vid].update(best_candidate)

    return {"count": len(rows), "observations": rows}
