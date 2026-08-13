"""
PostgreSQL/PostGIS depolama katmani (Faz 2).

Faz 1'deki "her API cagrisi icin ayri JSON dosyasi" yapisinin yerini alir:
- raw_snapshots  : her API cagrisinin tam ham cevabi (JSONB)
- vehicle_observations : response icindeki her arac konumu, response_index ile
  ayri satir (madde 1: cok koordinatli response'larda veri kaybi olmaz)

"Ilk nokta gunceldir" varsayimi burada YAPILMAZ; position_quality varsayilan
olarak UNKNOWN_POSITION yazilir. Siniflandirma mantigi ayri bir analiz
adiminda (Faz 2 madde 1 arastirmasi) doldurulacak.
"""
import hashlib
import json
import os
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "izmir_bus_eta"),
    "user": os.getenv("DB_USER", "eta_user"),
    "password": os.getenv("DB_PASSWORD", "eta_password_dev_only"),
}


def get_connection():
    """Yeni bir DB baglantisi acar. autocommit=True: collector kesintiye
    ugrarsa (restart senaryosu) yarim kalmis transaction riski olmasin diye."""
    return psycopg.connect(**DB_CONFIG, autocommit=True)


# ---------------------------------------------------------------------------
# ingestion_runs
# ---------------------------------------------------------------------------

def start_ingestion_run(conn, target_lines: list, collector_version: str,
                         is_resumed_run: bool = False,
                         resumed_from_run_id: int = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_runs
                (target_lines, collector_version, is_resumed_run, resumed_from_run_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (target_lines, collector_version, is_resumed_run, resumed_from_run_id),
        )
        return cur.fetchone()[0]


def end_ingestion_run(conn, run_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_runs SET ended_at = now() WHERE id = %s",
            (run_id,),
        )


def get_last_run_id(conn):
    """Collector restart senaryosunda en son run'i bulmak icin kullanilabilir."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM ingestion_runs ORDER BY started_at DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# raw_snapshots
# ---------------------------------------------------------------------------

def save_raw_snapshot(conn, ingestion_run_id: int, source_api: str, line_no: str,
                       requested_at: datetime, http_status: int, raw_text: str) -> int:
    """Ham response'u JSONB olarak kaydeder. Duplicate ingestion durumunda
    (ayni run+source+line+zaman+hash) yeni satir eklemez, mevcut id'yi doner."""
    response_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    raw_json = json.loads(raw_text)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_snapshots
                (ingestion_run_id, source_api, line_no, requested_at,
                 http_status, raw_response, response_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ingestion_run_id, source_api, line_no, requested_at, response_hash)
            DO NOTHING
            RETURNING id
            """,
            (ingestion_run_id, source_api, line_no, requested_at,
             http_status, Jsonb(raw_json), response_hash),
        )
        row = cur.fetchone()
        if row:
            return row[0]

        cur.execute(
            """
            SELECT id FROM raw_snapshots
            WHERE ingestion_run_id = %s AND source_api = %s AND line_no = %s
              AND requested_at = %s AND response_hash = %s
            """,
            (ingestion_run_id, source_api, line_no, requested_at, response_hash),
        )
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# vehicle_observations
# ---------------------------------------------------------------------------

def normalize_source_direction(raw_direction):
    """
    Kaynak API'nin 'Yon' alanini routes.direction konvansiyonuna (0/1) cevirir.

    VARSAYIM: Ana API'nin 'Yon' alani, ESHOT guzergah CSV'sindeki YON alaniyla
    (1=gidis, 2=donus) AYNI konvansiyonu kullaniyor - iki veri kaynagi da
    ayni belediye sisteminden geldigi icin bu makul bir varsayim, ama
    DOGRULANMADI. 1 -> 0 (gidis), 2 -> 1 (donus). Baska bir deger (0, 3,
    None, vb.) gelirse None doner - cagiran taraf bunu SOURCE_DIRECTION_UNKNOWN
    olarak isaretlemeli, sessizce 0 ya da 1 varsayilmamali.

    Gercek veri toplaninca bu varsayim kontrol edilmeli (bkz.
    data_quality_events'teki SOURCE_DIRECTION_UNKNOWN loglari).
    """
    if raw_direction is None:
        return None
    try:
        val = int(raw_direction)
    except (ValueError, TypeError):
        return None

    if val == 1:
        return 0
    if val == 2:
        return 1
    return None


def save_vehicle_observations(conn, raw_snapshot_id: int, line_no: str,
                               observed_at: datetime, records: list):
    """
    records: bus_location_collector.py'daki normalized_records listesi -
    her biri en az {vehicle_id, latitude, longitude} icermeli, varsa
    {direction} (ham API 'Yon' degeri) de kullanilir.

    Madde 1: ayni response icindeki her nokta response_index ile ayri satir
    olarak saklanir; "ilk nokta gunceldir" varsayimi yapilmaz.
    """
def save_vehicle_observations(conn, raw_snapshot_id: int, line_no: str,
                               observed_at: datetime, records: list):
    """
    records: bus_location_collector.py'daki normalized_records listesi -
    her biri en az {vehicle_id, latitude, longitude} icermeli, varsa
    {direction} (ham API 'Yon' degeri) ve {quality_flags} (';' ile
    birlestirilmis string) de kullanilir.

    Madde 1: ayni response icindeki her nokta response_index ile ayri satir
    olarak saklanir; "ilk nokta gunceldir" varsayimi yapilmaz.
    """
    inserted = 0
    skipped_missing_id = 0
    with conn.cursor() as cur:
        for idx, r in enumerate(records):
            if r.get("vehicle_id") is None:
                # vehicle_observations.vehicle_id NOT NULL - MISSING_VEHICLE_ID
                # kayitlari eklenmiyor (NOT NULL ihlali yerine sessizce atlaniyor,
                # ama izlenebilirlik icin quality event olarak loglaniyor).
                skipped_missing_id += 1
                log_quality_event(
                    conn, stage="ingestion", severity="WARNING",
                    description=f"response_index={idx}: vehicle_id eksik (MISSING_VEHICLE_ID), "
                                  "vehicle_observations'a yazilamadi.",
                    line_no=line_no, context={"raw_snapshot_id": raw_snapshot_id, "response_index": idx},
                )
                continue

            lat, lon = r.get("latitude"), r.get("longitude")
            if lat is None or lon is None:
                continue  # gecersiz koordinat - ayri quality event olarak loglanabilir

            source_direction = normalize_source_direction(r.get("direction"))

            raw_flags_str = r.get("quality_flags", "")
            record_flags = [f for f in raw_flags_str.split(";") if f] if raw_flags_str else []

            if lat == 0 and lon == 0:
                position_quality = "UNKNOWN_POSITION"
                reason = ("Koordinat (0,0) - null island sentinel degeri, "
                           "gercek bir GPS okumasi degil. Map-matching'den haric tutulmali.")
            else:
                position_quality = "UNKNOWN_POSITION"
                reason = "Faz2 madde1 siniflandirmasi henuz yapilmadi; ham gozlem."

            cur.execute(
                """
                INSERT INTO vehicle_observations
                    (raw_snapshot_id, response_index, vehicle_id, line_no, observed_at,
                     geom, raw_lat, raw_lon, position_quality, position_quality_reason,
                     source_direction, quality_flags)
                VALUES
                    (%s, %s, %s, %s, %s,
                     ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                     %s, %s, %s, %s, %s, %s)
                ON CONFLICT (raw_snapshot_id, response_index) DO NOTHING
                """,
                (
                    raw_snapshot_id, idx, r["vehicle_id"], line_no, observed_at,
                    lon, lat,               # ST_MakePoint(lon, lat) - PostGIS sirasi
                    lat, lon,               # raw_lat, raw_lon
                    position_quality,
                    reason,
                    source_direction,
                    record_flags,
                ),
            )
            inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# data_quality_events
# ---------------------------------------------------------------------------

def log_quality_event(conn, stage: str, severity: str, description: str,
                       ingestion_run_id: int = None, vehicle_id: str = None,
                       line_no: str = None, context: dict = None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_quality_events
                (stage, severity, ingestion_run_id, vehicle_id, line_no, description, context)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (stage, severity, ingestion_run_id, vehicle_id, line_no, description,
             Jsonb(context) if context is not None else None),
        )


# ---------------------------------------------------------------------------
# supporting_api_observations
# ---------------------------------------------------------------------------

def save_supporting_observations(conn, raw_snapshot_id: int, line_no: str,
                                  target_stop_id: str, observed_at: datetime,
                                  vehicles: list):
    """
    vehicles: hattinyaklasanotobusleri API'sinin dondurdugu ham liste
    (her eleman OtobusId, KalanDurakSayisi, HatNumarasi, HatAdi icerir).

    Madde 8: Bu fonksiyon sadece HAM kaydi yazar. "Zaman serisi kanit"
    degerlendirmesi (ayni vehicle_id'nin zaman icinde azalan
    remaining_stop_count degerleri) uygulama/analiz katmaninda,
    bu tablo uzerinden vehicle_id + observed_at ile sorgulanarak yapilir.
    Tek response'daki farkli araclarin degerleri zaman serisi kaniti
    olarak KULLANILMAZ.
    """
    inserted = 0
    with conn.cursor() as cur:
        for idx, v in enumerate(vehicles):
            vehicle_id = v.get("OtobusId")
            remaining = v.get("KalanDurakSayisi")
            if vehicle_id is None or remaining is None:
                continue

            cur.execute(
                """
                INSERT INTO supporting_api_observations
                    (raw_snapshot_id, response_index, vehicle_id, line_no,
                     target_stop_id, remaining_stop_count, observed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (raw_snapshot_id, response_index) DO NOTHING
                """,
                (raw_snapshot_id, idx, str(vehicle_id), line_no,
                 target_stop_id, remaining, observed_at),
            )
            inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# vehicle_observations - madde 1 siniflandirma guncellemesi
# ---------------------------------------------------------------------------

def update_position_quality(conn, observation_id: int, quality: str, reason: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE vehicle_observations
            SET position_quality = %s, position_quality_reason = %s
            WHERE id = %s
            """,
            (quality, reason, observation_id),
        )


def add_observation_quality_flag(conn, observation_id: int, flag: str):
    """vehicle_observations.quality_flags dizisine tekrarsiz sekilde flag ekler."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE vehicle_observations
            SET quality_flags = ARRAY(SELECT DISTINCT unnest(quality_flags || ARRAY[%s]))
            WHERE id = %s
            """,
            (flag, observation_id),
        )
