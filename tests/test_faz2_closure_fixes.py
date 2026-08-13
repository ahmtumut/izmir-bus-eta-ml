"""
Faz 2 kapanis duzeltmeleri (Supervisor geri bildirimi) icin testler:
- source_direction normalizasyonu
- DIRECTION_ROUTE_MISMATCH tespiti
- arrival_events / eta_training_samples idempotency (unique constraint'ler)
- Baseline 2 leave-one-out mantigi
- ETA training T0 filtrelerinin siki tutulmasi (GOOD/DEGRADED + stale haric)

Kullanim:
    pytest tests/test_faz2_closure_fixes.py -v
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from map_match_observations import map_match_one  # noqa: E402
from compute_baseline_eta import baseline_segment_median_leave_one_out  # noqa: E402
from generate_eta_training_samples import fetch_t0_candidates  # noqa: E402


@pytest.fixture(scope="module")
def conn():
    connection = db_storage.get_connection()
    yield connection
    connection.close()


# ---------------------------------------------------------------------------
# source_direction normalizasyonu
# ---------------------------------------------------------------------------

def test_normalize_source_direction_mapping():
    assert db_storage.normalize_source_direction(1) == 0
    assert db_storage.normalize_source_direction(2) == 1
    assert db_storage.normalize_source_direction("1") == 0
    assert db_storage.normalize_source_direction("2") == 1


def test_normalize_source_direction_unknown_values_return_none():
    assert db_storage.normalize_source_direction(0) is None
    assert db_storage.normalize_source_direction(3) is None
    assert db_storage.normalize_source_direction(None) is None
    assert db_storage.normalize_source_direction("gidis") is None


# ---------------------------------------------------------------------------
# DIRECTION_ROUTE_MISMATCH tespiti (DB'ye karsi, gercek PostGIS ile)
# ---------------------------------------------------------------------------

@pytest.fixture()
def two_direction_routes(conn):
    """Biri dogu-bati, biri kuzey-guney iki route olusturur - net ayirt
    edilebilir bir mismatch senaryosu icin."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO routes (line_no, direction, shape_geom)
            VALUES ('PYTEST_MISMATCH', 0,
                    ST_GeogFromText('SRID=4326;LINESTRING(27.10 38.40, 27.20 38.40)'))
            RETURNING id
            """
        )
        route0_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO routes (line_no, direction, shape_geom)
            VALUES ('PYTEST_MISMATCH', 1,
                    ST_GeogFromText('SRID=4326;LINESTRING(27.10 38.50, 27.10 38.60)'))
            RETURNING id
            """
        )
        route1_id = cur.fetchone()[0]

    yield [(route0_id, 0, 11119.5), (route1_id, 1, 11119.5)]

    with conn.cursor() as cur:
        cur.execute("DELETE FROM routes WHERE line_no = 'PYTEST_MISMATCH'")


def test_direction_mismatch_flagged_when_geometry_disagrees(conn, two_direction_routes):
    """Kaynak API source_direction=0 diyor (dogu-bati hat), ama arac aslinda
    kuzey-guney hattin (direction=1) UZERINDE. Sessizce direction=1'e
    cevrilmemeli - DIRECTION_ROUTE_MISMATCH ile flaglenmeli, route_id yine
    de gercek en yakin (direction=1) route'a atanmali."""
    # Bu nokta tam olarak direction=1 route'unun uzerinde (27.10, 38.55)
    point_wkb = "POINT(27.10 38.55)"

    with conn.cursor() as cur:
        cur.execute(f"SELECT ST_GeogFromText('SRID=4326;{point_wkb}')")
        geom = cur.fetchone()[0]

    route_id, dist_m, fraction, distance_along_m, flags = map_match_one(
        conn, geom, two_direction_routes, source_direction=0
    )

    assert "DIRECTION_ROUTE_MISMATCH" in flags
    matched_direction = next(d for rid, d, _ in two_direction_routes if rid == route_id)
    assert matched_direction == 1, "En yakin gercek geometri kullanilmali, kaynak yon degil"


def test_no_mismatch_flag_when_direction_agrees(conn, two_direction_routes):
    """Kaynak yon dogruysa flag olmamali."""
    point_wkb = "POINT(27.15 38.40)"  # direction=0 route'unun tam ortasi

    with conn.cursor() as cur:
        cur.execute(f"SELECT ST_GeogFromText('SRID=4326;{point_wkb}')")
        geom = cur.fetchone()[0]

    route_id, dist_m, fraction, distance_along_m, flags = map_match_one(
        conn, geom, two_direction_routes, source_direction=0
    )

    assert "DIRECTION_ROUTE_MISMATCH" not in flags


def test_unknown_source_direction_flagged(conn, two_direction_routes):
    point_wkb = "POINT(27.15 38.40)"
    with conn.cursor() as cur:
        cur.execute(f"SELECT ST_GeogFromText('SRID=4326;{point_wkb}')")
        geom = cur.fetchone()[0]

    route_id, dist_m, fraction, distance_along_m, flags = map_match_one(
        conn, geom, two_direction_routes, source_direction=None
    )
    assert "SOURCE_DIRECTION_UNKNOWN" in flags


# ---------------------------------------------------------------------------
# Idempotency: arrival_events
# ---------------------------------------------------------------------------

def test_arrival_events_insert_is_idempotent(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stops (stop_id, stop_name, geom)
            VALUES ('PYTEST_IDEMP_STOP', 'Test Idempotent Durak',
                    ST_SetSRID(ST_MakePoint(27.15, 38.40), 4326)::geography)
            RETURNING id
            """
        )
        stop_pk = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO raw_snapshots (ingestion_run_id, source_api, line_no,
                requested_at, http_status, raw_response, response_hash)
            SELECT id, 'main_api', 'PYTEST', now(), 200, '{}'::jsonb, 'pytest_idemp_hash'
            FROM ingestion_runs LIMIT 1
            RETURNING id
            """
        )
        # Eger hic ingestion_run yoksa once bir tane olustur.
        row = cur.fetchone()
        if row is None:
            run_id = db_storage.start_ingestion_run(conn, ["PYTEST"], "pytest")
            cur.execute(
                """
                INSERT INTO raw_snapshots (ingestion_run_id, source_api, line_no,
                    requested_at, http_status, raw_response, response_hash)
                VALUES (%s, 'main_api', 'PYTEST', now(), 200, '{}'::jsonb, 'pytest_idemp_hash2')
                RETURNING id
                """,
                (run_id,),
            )
            row = cur.fetchone()
        snapshot_id = row[0]

        cur.execute(
            """
            INSERT INTO vehicle_observations
                (raw_snapshot_id, response_index, vehicle_id, line_no, observed_at, geom, raw_lat, raw_lon)
            VALUES (%s, 999, 'PYTEST_VEH_IDEMP', 'PYTEST', now(),
                    ST_SetSRID(ST_MakePoint(27.15, 38.40), 4326)::geography, 38.40, 27.15)
            RETURNING id
            """,
            (snapshot_id,),
        )
        obs_id = cur.fetchone()[0]

        insert_sql = """
            INSERT INTO arrival_events
                (vehicle_id, line_no, direction, stop_id, approach_started_at,
                 arrival_observed_at, minimum_distance_m, arrival_confidence,
                 validation_source, triggering_observation_id)
            VALUES ('PYTEST_VEH_IDEMP', 'PYTEST', 0, %s, now() - interval '30 seconds',
                    now(), 10.0, 'MEDIUM', 'gps_only', %s)
            ON CONFLICT (triggering_observation_id, stop_id) DO NOTHING
            RETURNING id
        """
        cur.execute(insert_sql, (stop_pk, obs_id))
        first_id = cur.fetchone()[0]

        cur.execute(insert_sql, (stop_pk, obs_id))
        second_result = cur.fetchone()

        assert second_result is None, "Ikinci INSERT DO NOTHING ile hicbir satir donmemeli"

        cur.execute(
            "SELECT COUNT(*) FROM arrival_events WHERE triggering_observation_id = %s",
            (obs_id,),
        )
        count = cur.fetchone()[0]
        assert count == 1, "Ayni triggering_observation_id+stop_id icin sadece 1 satir olmali"

    with conn.cursor() as cur:
        cur.execute("DELETE FROM arrival_events WHERE triggering_observation_id = %s", (obs_id,))
        cur.execute("DELETE FROM vehicle_observations WHERE id = %s", (obs_id,))
        cur.execute("DELETE FROM raw_snapshots WHERE id = %s", (snapshot_id,))
        cur.execute("DELETE FROM stops WHERE stop_id = 'PYTEST_IDEMP_STOP'")


# ---------------------------------------------------------------------------
# Baseline 2 leave-one-out
# ---------------------------------------------------------------------------

def test_leave_one_out_excludes_own_sample():
    segment_actuals = {
        ("515", 0, 1): [(101, 300.0), (102, 320.0), (103, 280.0)],
    }
    # sample 101'in tahmini SADECE 102 ve 103'un medyanindan hesaplanmali.
    pred = baseline_segment_median_leave_one_out(101, ("515", 0, 1), segment_actuals)
    assert pred == 300.0  # median(320, 280) = 300.0


def test_leave_one_out_returns_none_when_segment_has_single_sample():
    segment_actuals = {
        ("761", 1, 5): [(201, 500.0)],
    }
    pred = baseline_segment_median_leave_one_out(201, ("761", 1, 5), segment_actuals)
    assert pred is None, "n=1 segmentte leave-one-out sonrasi tahmin uretilmemeli"


def test_leave_one_out_uses_others_not_self_with_distinct_values():
    segment_actuals = {
        ("121", 0, 2): [(301, 100.0), (302, 500.0), (303, 500.0)],
    }
    pred = baseline_segment_median_leave_one_out(301, ("121", 0, 2), segment_actuals)
    assert pred == 500.0  # median(500, 500), 100.0 (kendi degeri) haric tutuldu


# ---------------------------------------------------------------------------
# ETA training T0 filtreleri (GOOD/DEGRADED + stale haric)
# ---------------------------------------------------------------------------

def test_fetch_t0_candidates_excludes_rejected_and_stale(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO routes (line_no, direction, shape_geom)
            VALUES ('PYTEST_T0FILTER', 0,
                    ST_GeogFromText('SRID=4326;LINESTRING(27.10 38.40, 27.20 38.40)'))
            RETURNING id
            """
        )
        route_id = cur.fetchone()[0]

        run_id = db_storage.start_ingestion_run(conn, ["PYTEST_T0"], "pytest")
        cur.execute(
            """
            INSERT INTO raw_snapshots (ingestion_run_id, source_api, line_no,
                requested_at, http_status, raw_response, response_hash)
            VALUES (%s, 'main_api', 'PYTEST_T0FILTER', now(), 200, '{}'::jsonb, 'pytest_t0_hash')
            RETURNING id
            """,
            (run_id,),
        )
        snapshot_id = cur.fetchone()[0]

        base_time = datetime.now(timezone.utc)

        # GOOD kalite, stale degil -> ADAY OLMALI
        cur.execute(
            """
            INSERT INTO vehicle_observations
                (raw_snapshot_id, response_index, vehicle_id, line_no, observed_at,
                 geom, raw_lat, raw_lon, route_id, distance_along_route_m,
                 progress_along_route, map_match_quality, position_quality)
            VALUES (%s, 0, 'PYTEST_T0_VEH', 'PYTEST_T0FILTER', %s,
                    ST_SetSRID(ST_MakePoint(27.12, 38.40), 4326)::geography, 38.40, 27.12,
                    %s, 500.0, 0.1, 'GOOD', 'CURRENT_POSITION')
            """,
            (snapshot_id, base_time, route_id),
        )

        # REJECTED kalite -> ADAY OLMAMALI
        cur.execute(
            """
            INSERT INTO vehicle_observations
                (raw_snapshot_id, response_index, vehicle_id, line_no, observed_at,
                 geom, raw_lat, raw_lon, route_id, distance_along_route_m,
                 progress_along_route, map_match_quality, position_quality)
            VALUES (%s, 1, 'PYTEST_T0_VEH', 'PYTEST_T0FILTER', %s,
                    ST_SetSRID(ST_MakePoint(27.13, 38.40), 4326)::geography, 38.40, 27.13,
                    %s, 600.0, 0.15, 'REJECTED', 'CURRENT_POSITION')
            """,
            (snapshot_id, base_time + timedelta(seconds=60), route_id),
        )

        # STALE_POSITION -> ADAY OLMAMALI
        cur.execute(
            """
            INSERT INTO vehicle_observations
                (raw_snapshot_id, response_index, vehicle_id, line_no, observed_at,
                 geom, raw_lat, raw_lon, route_id, distance_along_route_m,
                 progress_along_route, map_match_quality, position_quality)
            VALUES (%s, 2, 'PYTEST_T0_VEH', 'PYTEST_T0FILTER', %s,
                    ST_SetSRID(ST_MakePoint(27.14, 38.40), 4326)::geography, 38.40, 27.14,
                    %s, 700.0, 0.2, 'GOOD', 'STALE_POSITION')
            """,
            (snapshot_id, base_time + timedelta(seconds=120), route_id),
        )

        candidates = fetch_t0_candidates(
            conn, "PYTEST_T0_VEH", "PYTEST_T0FILTER", 0, route_id,
            base_time - timedelta(seconds=10), base_time + timedelta(seconds=300),
        )

        assert len(candidates) == 1, f"Sadece 1 gecerli aday olmali, {len(candidates)} bulundu"
        assert candidates[0][2] == 500.0  # distance_along_route_m dogru gozlem

    with conn.cursor() as cur:
        cur.execute("DELETE FROM vehicle_observations WHERE line_no = 'PYTEST_T0FILTER'")
        cur.execute("DELETE FROM raw_snapshots WHERE id = %s", (snapshot_id,))
        cur.execute("DELETE FROM ingestion_runs WHERE id = %s", (run_id,))
        cur.execute("DELETE FROM routes WHERE line_no = 'PYTEST_T0FILTER'")
