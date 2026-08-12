"""
Faz 2 madde 10: Otomatik testler.

Kapsam:
- PostgreSQL migration / tablo varligi
- Duplicate ingestion (raw_snapshots response_hash unique constraint)
- PostGIS point/LineString islemleri (ST_MakePoint, ST_Distance, ST_LineLocatePoint)
- GPS map matching (quality_from_distance esik mantigi)
- Direction ayrimi (routes tablosu line_no+direction unique)
- Ayni response icindeki coklu arac noktalari (response_index)
- Stale GPS run tespiti (find_runs)
- KalanDurakSayisi zaman serisi (remaining_trend_during)
- Durak siralama (route_stop_sequence unique constraint)
- Arrival event (temel insert/select akisi)
- Future leakage yoklugu (eta_training_samples CHECK constraint)
- Collector restart senaryolari (is_resumed_run, get_last_run_id)

Bu testler GERCEK DB'ye karsi calisir (ayni docker-compose DB'si).
Her test kendi ingestion_run'ini olusturur ve sonunda temizler, boylece
mevcut/gercek toplama verisiyle CAKISMAZ.

Calistirmadan once Docker container'in ayakta oldugundan emin olun:
    docker compose up -d postgis

Kullanim:
    pytest tests/test_faz2_integration.py -v
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

# map_match_observations.py, analyze_gps_uncertainty.py, detect_arrival_events.py
# birer script oldugu icin fonksiyonlarini dogrudan scripts/ klasorunden import
# ediyoruz (asagida sys.path'e ekleniyor).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from map_match_observations import quality_from_distance  # noqa: E402
from analyze_gps_uncertainty import find_runs, remaining_trend_during  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def conn():
    connection = db_storage.get_connection()
    yield connection
    connection.close()


@pytest.fixture()
def test_run(conn):
    """Her test icin izole bir ingestion_run olusturur, sonunda temizler."""
    run_id = db_storage.start_ingestion_run(
        conn, target_lines=["TEST"], collector_version="pytest"
    )
    yield run_id
    with conn.cursor() as cur:
        # cascade ile raw_snapshots / vehicle_observations / supporting_api_observations
        # da silinir (FK ON DELETE CASCADE tanimliydi).
        cur.execute("DELETE FROM ingestion_runs WHERE id = %s", (run_id,))


# ---------------------------------------------------------------------------
# 1. Migration / tablo varligi
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "ingestion_runs", "raw_snapshots", "data_sources", "stops", "routes",
    "route_shape_points", "route_stop_sequence", "vehicle_observations",
    "supporting_api_observations", "arrival_events", "eta_training_samples",
    "data_quality_events",
}


def test_all_expected_tables_exist(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        )
        existing = {row[0] for row in cur.fetchall()}
    missing = EXPECTED_TABLES - existing
    assert not missing, f"Eksik tablolar: {missing}"


def test_postgis_extension_installed(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'postgis'")
        assert cur.fetchone() is not None, "PostGIS extension kurulu degil"


# ---------------------------------------------------------------------------
# 2. Duplicate ingestion
# ---------------------------------------------------------------------------

def test_duplicate_raw_snapshot_does_not_create_new_row(conn, test_run):
    requested_at = datetime.now(timezone.utc)
    raw_text = '{"HatOtobusKonumlari": []}'

    id1 = db_storage.save_raw_snapshot(
        conn, test_run, "main_api", "TESTLINE", requested_at, 200, raw_text
    )
    id2 = db_storage.save_raw_snapshot(
        conn, test_run, "main_api", "TESTLINE", requested_at, 200, raw_text
    )
    assert id1 == id2, "Ayni (run, source, line, zaman, hash) icin farkli id uretilmemeli"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM raw_snapshots WHERE ingestion_run_id = %s", (test_run,)
        )
        count = cur.fetchone()[0]
    assert count == 1, "Duplicate ingestion yeni satir olusturmamali"


# ---------------------------------------------------------------------------
# 3. PostGIS point / LineString islemleri
# ---------------------------------------------------------------------------

def test_postgis_point_creation_and_distance(conn):
    with conn.cursor() as cur:
        # Izmir merkez ile ~1km dogu arasi mesafe kabaca dogrulanabilir.
        cur.execute(
            """
            SELECT ST_Distance(
                ST_SetSRID(ST_MakePoint(27.1428, 38.4237), 4326)::geography,
                ST_SetSRID(ST_MakePoint(27.1548, 38.4237), 4326)::geography
            )
            """
        )
        dist_m = cur.fetchone()[0]
    # 0.012 derece boylam farki ekvatora yakin ~1.06km'ye denk gelir (38 derece enlemde biraz daha az)
    assert 800 < dist_m < 1200, f"Beklenmeyen mesafe: {dist_m}m"


def test_postgis_linestring_locate_point(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ST_LineLocatePoint(
                ST_GeomFromText('LINESTRING(27.10 38.40, 27.20 38.40)', 4326),
                ST_GeomFromText('POINT(27.15 38.40)', 4326)
            )
            """
        )
        fraction = cur.fetchone()[0]
    assert abs(fraction - 0.5) < 0.01, "Ortadaki nokta fraction=0.5 vermeli"


# ---------------------------------------------------------------------------
# 4. Map-matching kalite esikleri
# ---------------------------------------------------------------------------

def test_quality_from_distance_thresholds():
    assert quality_from_distance(0) == "GOOD"
    assert quality_from_distance(30) == "GOOD"
    assert quality_from_distance(31) == "DEGRADED"
    assert quality_from_distance(100) == "DEGRADED"
    assert quality_from_distance(101) == "REJECTED"
    assert quality_from_distance(9999) == "REJECTED"


# ---------------------------------------------------------------------------
# 5. Direction ayrimi
# ---------------------------------------------------------------------------

def test_routes_direction_unique_constraint(conn):
    """Ayni (line_no, direction) ikilisi icin ikinci INSERT hata vermeli."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO routes (line_no, direction, shape_geom)
            VALUES ('PYTEST_LINE', 0, ST_GeogFromText('SRID=4326;LINESTRING(27.1 38.4, 27.2 38.4)'))
            """
        )

    with pytest.raises(Exception):
        with conn.cursor() as cur2:
            cur2.execute(
                """
                INSERT INTO routes (line_no, direction, shape_geom)
                VALUES ('PYTEST_LINE', 0, ST_GeogFromText('SRID=4326;LINESTRING(27.1 38.4, 27.3 38.4)'))
                """
            )

    # temizlik (autocommit modunda oldugumuz icin ayri bir cursor ile)
    with conn.cursor() as cur3:
        cur3.execute("DELETE FROM routes WHERE line_no = 'PYTEST_LINE'")


# ---------------------------------------------------------------------------
# 6. Ayni response icindeki coklu arac noktalari
# ---------------------------------------------------------------------------

def test_multiple_vehicle_points_in_same_response_are_preserved(conn, test_run):
    requested_at = datetime.now(timezone.utc)
    snapshot_id = db_storage.save_raw_snapshot(
        conn, test_run, "main_api", "TESTLINE", requested_at, 200, '{"HatOtobusKonumlari": []}'
    )
    # Ayni vehicle_id, FARKLI koordinatlarla iki kez - response_index ile ayri saklanmali.
    records = [
        {"vehicle_id": "V1", "latitude": 38.40, "longitude": 27.10},
        {"vehicle_id": "V1", "latitude": 38.41, "longitude": 27.11},
    ]
    inserted = db_storage.save_vehicle_observations(
        conn, snapshot_id, "TESTLINE", requested_at, records
    )
    assert inserted == 2, "Ayni vehicle_id'nin farkli koordinatlari kaybolmamali"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT response_index, raw_lat, raw_lon FROM vehicle_observations "
            "WHERE raw_snapshot_id = %s ORDER BY response_index",
            (snapshot_id,),
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0][0] == 0 and rows[1][0] == 1


# ---------------------------------------------------------------------------
# 7. Stale GPS run tespiti (saf fonksiyon, DB gerekmiyor)
# ---------------------------------------------------------------------------

def test_find_runs_detects_repeated_coordinates():
    obs = [
        {"lat": 1.0, "lon": 1.0},
        {"lat": 1.0, "lon": 1.0},
        {"lat": 1.0, "lon": 1.0},
        {"lat": 2.0, "lon": 2.0},
        {"lat": 2.0, "lon": 2.0},
    ]
    runs = find_runs(obs)
    assert runs == [(0, 2, 3), (3, 4, 2)]


def test_find_runs_all_different():
    obs = [{"lat": i, "lon": i} for i in range(5)]
    runs = find_runs(obs)
    assert len(runs) == 5
    assert all(length == 1 for _, _, length in runs)


# ---------------------------------------------------------------------------
# 8. KalanDurakSayisi zaman serisi trend tespiti (saf fonksiyon)
# ---------------------------------------------------------------------------

def test_remaining_trend_during_decreasing():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    support_obs = [
        {"observed_at": t0, "remaining": 10},
        {"observed_at": t0 + timedelta(minutes=1), "remaining": 5},
    ]
    trend = remaining_trend_during(support_obs, t0, t0 + timedelta(minutes=2))
    assert trend is True


def test_remaining_trend_during_insufficient_data():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    support_obs = [{"observed_at": t0, "remaining": 10}]  # tek gozlem - trend cikarilamaz
    trend = remaining_trend_during(support_obs, t0, t0 + timedelta(minutes=2))
    assert trend is None, "Tek gozlemle trend UNKNOWN olmali, True/False degil"


def test_remaining_trend_different_vehicles_not_mixed():
    """Farkli araclarin degerleri asla tek bir zaman serisi gibi degerlendirilmemeli -
    bu fonksiyon zaten tek bir arac icin cagrilir, ama bos/None girdilerde de
    guvenli davranmali."""
    trend = remaining_trend_during(None, datetime.now(timezone.utc), datetime.now(timezone.utc))
    assert trend is None


# ---------------------------------------------------------------------------
# 9. Durak siralama unique constraint
# ---------------------------------------------------------------------------

def test_route_stop_sequence_unique_constraints(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO routes (line_no, direction, shape_geom)
            VALUES ('PYTEST_SEQ', 0, ST_GeogFromText('SRID=4326;LINESTRING(27.1 38.4, 27.2 38.4)'))
            RETURNING id
            """
        )
        route_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO stops (stop_id, stop_name, geom)
            VALUES ('PYTEST_STOP_1', 'Test Durak 1',
                    ST_SetSRID(ST_MakePoint(27.15, 38.40), 4326)::geography)
            RETURNING id
            """
        )
        stop1_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO stops (stop_id, stop_name, geom)
            VALUES ('PYTEST_STOP_2', 'Test Durak 2',
                    ST_SetSRID(ST_MakePoint(27.16, 38.40), 4326)::geography)
            RETURNING id
            """
        )
        stop2_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO route_stop_sequence
                (route_id, stop_id, sequence_order, distance_along_route_m, validation_method)
            VALUES (%s, %s, 0, 100.0, 'spatial_only')
            """,
            (route_id, stop1_id),
        )

    # Ayni sequence_order ile ikinci durak eklemek hata vermeli.
    with pytest.raises(Exception):
        with conn.cursor() as cur2:
            cur2.execute(
                """
                INSERT INTO route_stop_sequence
                    (route_id, stop_id, sequence_order, distance_along_route_m, validation_method)
                VALUES (%s, %s, 0, 200.0, 'spatial_only')
                """,
                (route_id, stop2_id),
            )

    # temizlik
    with conn.cursor() as cur:
        cur.execute("DELETE FROM route_stop_sequence WHERE route_id = %s", (route_id,))
        cur.execute("DELETE FROM routes WHERE id = %s", (route_id,))
        cur.execute("DELETE FROM stops WHERE stop_id IN ('PYTEST_STOP_1', 'PYTEST_STOP_2')")


# ---------------------------------------------------------------------------
# 10. Arrival event temel akis
# ---------------------------------------------------------------------------

def test_arrival_event_basic_insert_and_select(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stops (stop_id, stop_name, geom)
            VALUES ('PYTEST_STOP_AE', 'Test Durak AE',
                    ST_SetSRID(ST_MakePoint(27.15, 38.40), 4326)::geography)
            RETURNING id
            """
        )
        stop_pk = cur.fetchone()[0]

        t0 = datetime.now(timezone.utc)
        cur.execute(
            """
            INSERT INTO arrival_events
                (vehicle_id, line_no, direction, stop_id, approach_started_at,
                 arrival_observed_at, minimum_distance_m, arrival_confidence,
                 validation_source)
            VALUES ('PYTEST_VEHICLE', 'PYTEST_LINE', 0, %s, %s, %s, 12.5, 'MEDIUM', 'gps_only')
            RETURNING id
            """,
            (stop_pk, t0 - timedelta(seconds=30), t0),
        )
        event_id = cur.fetchone()[0]

        cur.execute("SELECT vehicle_id, minimum_distance_m FROM arrival_events WHERE id = %s",
                    (event_id,))
        row = cur.fetchone()
        assert row[0] == "PYTEST_VEHICLE"
        assert float(row[1]) == 12.5

    with conn.cursor() as cur:
        cur.execute("DELETE FROM arrival_events WHERE id = %s", (event_id,))
        cur.execute("DELETE FROM stops WHERE stop_id = 'PYTEST_STOP_AE'")


# ---------------------------------------------------------------------------
# 11. Future leakage koruma (CHECK constraint)
# ---------------------------------------------------------------------------

def test_eta_training_sample_rejects_future_leakage(conn):
    """observed_at (T0) >= actual_arrival_at (T1) olan bir satir DB
    seviyesinde REDDEDILMELI (CHECK constraint)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stops (stop_id, stop_name, geom)
            VALUES ('PYTEST_STOP_LEAK', 'Test Durak Leak',
                    ST_SetSRID(ST_MakePoint(27.15, 38.40), 4326)::geography)
            RETURNING id
            """
        )
        stop_pk = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO arrival_events
                (vehicle_id, line_no, direction, stop_id, approach_started_at,
                 arrival_observed_at, minimum_distance_m, arrival_confidence, validation_source)
            VALUES ('PYTEST_VEHICLE_LEAK', 'PYTEST_LINE', 0, %s, now() - interval '1 minute',
                    now(), 10.0, 'MEDIUM', 'gps_only')
            RETURNING id
            """,
            (stop_pk,),
        )
        event_id = cur.fetchone()[0]

    t1 = datetime.now(timezone.utc)
    t0_invalid = t1 + timedelta(seconds=10)  # T0, T1'DEN SONRA -> gecersiz olmali

    with pytest.raises(Exception):
        with conn.cursor() as cur2:
            cur2.execute(
                """
                INSERT INTO eta_training_samples
                    (vehicle_id, line_no, direction, target_stop_id, arrival_event_id,
                     source_observation_id, observed_at, actual_arrival_at,
                     actual_eta_seconds, distance_remaining_m, progress_along_route,
                     hour_of_day, day_of_week, label_quality)
                VALUES ('PYTEST_VEHICLE_LEAK', 'PYTEST_LINE', 0, %s, %s, NULL, %s, %s,
                        -10, 50.0, 0.5, 10, 1, 'SILVER')
                """,
                (stop_pk, event_id, t0_invalid, t1),
            )

    with conn.cursor() as cur:
        cur.execute("DELETE FROM arrival_events WHERE id = %s", (event_id,))
        cur.execute("DELETE FROM stops WHERE stop_id = 'PYTEST_STOP_LEAK'")


# ---------------------------------------------------------------------------
# 12. Collector restart senaryolari
# ---------------------------------------------------------------------------

def test_get_last_run_id_returns_most_recent(conn, test_run):
    last_id = db_storage.get_last_run_id(conn)
    assert last_id is not None
    assert last_id >= test_run


def test_resumed_run_links_to_original(conn, test_run):
    resumed_id = db_storage.start_ingestion_run(
        conn, target_lines=["TEST"], collector_version="pytest",
        is_resumed_run=True, resumed_from_run_id=test_run,
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT is_resumed_run, resumed_from_run_id FROM ingestion_runs WHERE id = %s",
            (resumed_id,),
        )
        is_resumed, resumed_from = cur.fetchone()
    assert is_resumed is True
    assert resumed_from == test_run

    with conn.cursor() as cur:
        cur.execute("DELETE FROM ingestion_runs WHERE id = %s", (resumed_id,))


def test_end_ingestion_run_sets_ended_at(conn, test_run):
    db_storage.end_ingestion_run(conn, test_run)
    with conn.cursor() as cur:
        cur.execute("SELECT ended_at FROM ingestion_runs WHERE id = %s", (test_run,))
        ended_at = cur.fetchone()[0]
    assert ended_at is not None
