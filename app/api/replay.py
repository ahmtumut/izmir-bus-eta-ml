"""Faz 4: gecmis veri replay endpoint'leri (toplama oturumlari, GPS gozlemleri, arrival event'leri)."""
from datetime import datetime

import pandas as pd
import psycopg
from catboost import CatBoostRegressor
from fastapi import APIRouter, HTTPException, Query

from app.api.db import get_read_connection
from app.ml.dataset import MODEL_FEATURE_COLUMNS, CATEGORICAL_FEATURES
from app.ml.inference import (
    MODEL_PATH, TRAINING_MAX_DISTANCE_REMAINING_M,
    build_feature_row, fetch_next_stop, fetch_observation_at,
)
from app.storage.db_storage import DB_CONFIG

router = APIRouter(prefix="/api/replay", tags=["replay"])

PILOT_LINES = ["515", "121", "761"]

_model = None


def _get_model() -> CatBoostRegressor:
    """Model dosyasini bir kere yukleyip process boyunca yeniden kullanir
    (her istekte diskten okumak yerine)."""
    global _model
    if _model is None:
        _model = CatBoostRegressor()
        _model.load_model(str(MODEL_PATH))
    return _model


@router.get("/sessions")
def get_sessions():
    """Mevcut toplama oturumlarinin listesi - kullanici bir zaman araligi secsin diye."""
    with get_read_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ir.id AS run_id, ir.started_at, ir.ended_at, ir.target_lines,
                   COUNT(vo.id) AS observation_count
            FROM ingestion_runs ir
            LEFT JOIN raw_snapshots rs ON rs.ingestion_run_id = ir.id
            LEFT JOIN vehicle_observations vo ON vo.raw_snapshot_id = rs.id
            GROUP BY ir.id, ir.started_at, ir.ended_at, ir.target_lines
            HAVING COUNT(vo.id) > 0
            ORDER BY ir.started_at
            """
        )
        rows = cur.fetchall()
    return {"sessions": rows}


def _parse_line_nos(line_no: str | None) -> list[str]:
    if not line_no:
        return PILOT_LINES
    return [v.strip() for v in line_no.split(",") if v.strip()]


@router.get("/observations")
def get_observations(
    start: datetime = Query(..., description="ISO8601 baslangic zamani"),
    end: datetime = Query(..., description="ISO8601 bitis zamani"),
    line_no: str | None = Query(None, description="virgulle ayrilmis hat listesi, orn. 515,121"),
):
    if end <= start:
        raise HTTPException(status_code=400, detail="end, start'tan sonra olmali")

    lines = _parse_line_nos(line_no)
    with get_read_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT vehicle_id, line_no, observed_at, raw_lat, raw_lon,
                   route_id, position_quality, map_match_quality,
                   distance_along_route_m, progress_along_route, distance_to_route_m
            FROM vehicle_observations
            WHERE line_no = ANY(%s) AND observed_at BETWEEN %s AND %s
            ORDER BY vehicle_id, observed_at
            """,
            (lines, start, end),
        )
        rows = cur.fetchall()
    return {"count": len(rows), "observations": rows}


@router.get("/arrivals")
def get_arrivals(
    start: datetime = Query(...),
    end: datetime = Query(...),
    line_no: str | None = Query(None),
):
    if end <= start:
        raise HTTPException(status_code=400, detail="end, start'tan sonra olmali")

    lines = _parse_line_nos(line_no)
    with get_read_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ae.id, ae.vehicle_id, ae.line_no, ae.direction, ae.stop_id,
                   s.stop_id AS stop_code, s.stop_name,
                   ST_X(s.geom::geometry) AS lon, ST_Y(s.geom::geometry) AS lat,
                   ae.approach_started_at, ae.arrival_observed_at, ae.passed_at,
                   ae.minimum_distance_m, ae.arrival_confidence
            FROM arrival_events ae
            JOIN stops s ON s.id = ae.stop_id
            WHERE ae.line_no = ANY(%s)
              AND ae.arrival_observed_at BETWEEN %s AND %s
            ORDER BY ae.arrival_observed_at
            """,
            (lines, start, end),
        )
        rows = cur.fetchall()
    return {"count": len(rows), "arrivals": rows}


@router.get("/eta")
def get_eta(
    vehicle_id: str = Query(...),
    line_no: str = Query(...),
    at: datetime = Query(..., description="Replay'in o anki sanal zamani (ISO8601)"),
):
    """Faz 4: verilen replay anindaki T0 gozlemine gore CatBoost modelinin
    ETA tahmini - 'o an model ne tahmin ederdi'. Hedef durak otomatik olarak
    aracin route uzerindeki mevcut ilerlemesinin hemen onundeki ilk durak
    olarak secilir. build_feature_row/fetch_observation_at ayni future-leakage
    korumasini uygular (at'tan sonraki hicbir gozleme bakilmaz)."""
    with psycopg.connect(**DB_CONFIG) as conn:
        obs = fetch_observation_at(conn, vehicle_id, line_no, at)
        if obs is None:
            raise HTTPException(
                status_code=404,
                detail=f"Arac {vehicle_id} (hat {line_no}) icin {at} oncesinde uygun gozlem yok.",
            )
        t0, route_id, dist_along, _progress, _dist_to_route = obs

        next_stop = fetch_next_stop(conn, route_id, dist_along)
        if next_stop is None:
            raise HTTPException(status_code=404, detail="Aracin onunde durak kalmamis (rota sonu).")
        target_stop_id, stop_name, _stop_dist_along = next_stop

        try:
            feature_row, t0 = build_feature_row(conn, vehicle_id, line_no, target_stop_id, at_time=at)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        model = _get_model()
        X = pd.DataFrame([feature_row])[MODEL_FEATURE_COLUMNS]
        for col in CATEGORICAL_FEATURES:
            X[col] = X[col].astype(str)
        predicted_eta_seconds = float(model.predict(X)[0])

    return {
        "vehicle_id": vehicle_id,
        "line_no": line_no,
        "target_stop_id": target_stop_id,
        "stop_name": stop_name,
        "t0": t0.isoformat(),
        "distance_remaining_m": feature_row["distance_remaining_m"],
        "predicted_eta_seconds": predicted_eta_seconds,
        "extrapolation_warning": feature_row["distance_remaining_m"] > TRAINING_MAX_DISTANCE_REMAINING_M,
    }


STOP_ETA_STALENESS_SECONDS = 180  # ~3x collector cycle - daha eski gozlemler "yaklasiyor" sayilmaz


@router.get("/stop-eta")
def get_stop_eta(
    target_stop_id: str = Query(...),
    at: datetime = Query(..., description="Replay/canli o anki zaman (ISO8601)"),
    line_no: str | None = Query(None, description="virgulle ayrilmis hat filtresi (bos ise durak'tan gecen tum hatlar)"),
):
    """Bir duraga tiklaninca 'buraya en yakin zamanda hangi otobusler
    varacak' sorusuna cevap - o durak+yon icin rotada halen YAKLASMAKTA
    olan (distance_along_route_m < durak mesafesi) her aracin ETA'sini
    hesaplar, en yakindan (en kucuk ETA) en uzaga siralar."""
    wanted_lines = set(_parse_line_nos(line_no)) if line_no else None

    with psycopg.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT rss.route_id, r.line_no, r.direction, rss.distance_along_route_m
                FROM route_stop_sequence rss
                JOIN routes r ON r.id = rss.route_id
                JOIN stops s ON s.id = rss.stop_id
                WHERE s.stop_id = %s
                """,
                (target_stop_id,),
            )
            stop_routes = cur.fetchall()

        if wanted_lines:
            stop_routes = [r for r in stop_routes if r[1] in wanted_lines]
        if not stop_routes:
            raise HTTPException(status_code=404, detail=f"Durak {target_stop_id} icin route_stop_sequence kaydi yok.")

        model = _get_model()
        candidates = []
        for route_id, rline_no, direction, stop_dist_along in stop_routes:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (vehicle_id) vehicle_id, observed_at
                    FROM vehicle_observations
                    WHERE route_id = %s AND observed_at <= %s
                      AND map_match_quality IN ('GOOD', 'DEGRADED')
                      AND position_quality != 'STALE_POSITION'
                      AND distance_along_route_m IS NOT NULL
                      AND distance_along_route_m < %s
                    ORDER BY vehicle_id, observed_at DESC
                    """,
                    (route_id, at, stop_dist_along),
                )
                approaching = cur.fetchall()

            for vehicle_id, observed_at in approaching:
                if (at - observed_at).total_seconds() > STOP_ETA_STALENESS_SECONDS:
                    continue  # bayat gozlem - "su an yaklasiyor" sayilamaz
                try:
                    feature_row, t0 = build_feature_row(conn, vehicle_id, rline_no, target_stop_id, at_time=at)
                except ValueError:
                    continue

                X = pd.DataFrame([feature_row])[MODEL_FEATURE_COLUMNS]
                for col in CATEGORICAL_FEATURES:
                    X[col] = X[col].astype(str)
                predicted_eta_seconds = float(model.predict(X)[0])

                candidates.append({
                    "vehicle_id": vehicle_id,
                    "line_no": rline_no,
                    "direction": direction,
                    "t0": t0.isoformat(),
                    "distance_remaining_m": feature_row["distance_remaining_m"],
                    "predicted_eta_seconds": predicted_eta_seconds,
                    "extrapolation_warning": feature_row["distance_remaining_m"] > TRAINING_MAX_DISTANCE_REMAINING_M,
                })

        candidates.sort(key=lambda c: c["predicted_eta_seconds"])

    return {"target_stop_id": target_stop_id, "count": len(candidates), "candidates": candidates}
