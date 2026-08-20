"""Faz 4: statik geometri endpoint'leri (route hatlari, durak listesi)."""
from fastapi import APIRouter

from app.api.db import get_read_connection

router = APIRouter(prefix="/api", tags=["static"])


@router.get("/routes")
def get_routes():
    """515/121/761 icin hat+yon bazli route geometrisi (GeoJSON LineString)."""
    with get_read_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id AS route_id, r.line_no, r.direction, r.total_length_m,
                   rsp.seq, ST_X(rsp.geom::geometry) AS lon, ST_Y(rsp.geom::geometry) AS lat
            FROM routes r
            JOIN route_shape_points rsp ON rsp.route_id = r.id
            ORDER BY r.line_no, r.direction, rsp.seq
            """
        )
        rows = cur.fetchall()

    routes: dict[tuple, dict] = {}
    for row in rows:
        key = (row["line_no"], row["direction"])
        if key not in routes:
            routes[key] = {
                "route_id": row["route_id"],
                "line_no": row["line_no"],
                "direction": row["direction"],
                "total_length_m": row["total_length_m"],
                "coordinates": [],
            }
        routes[key]["coordinates"].append([row["lon"], row["lat"]])

    return {"routes": list(routes.values())}


@router.get("/stops")
def get_stops(line_no: str | None = None):
    """Durak konumlari, verilirse belirli bir hatla sinirli (route_stop_sequence uzerinden)."""
    with get_read_connection() as conn, conn.cursor() as cur:
        if line_no:
            cur.execute(
                """
                SELECT DISTINCT s.id, s.stop_id, s.stop_name, s.lines_through,
                       ST_X(s.geom::geometry) AS lon, ST_Y(s.geom::geometry) AS lat,
                       rss.route_id, rss.sequence_order, rss.distance_along_route_m,
                       r.line_no, r.direction
                FROM stops s
                JOIN route_stop_sequence rss ON rss.stop_id = s.id
                JOIN routes r ON r.id = rss.route_id
                WHERE r.line_no = %s
                ORDER BY r.direction, rss.sequence_order
                """,
                (line_no,),
            )
        else:
            cur.execute(
                """
                SELECT id, stop_id, stop_name, lines_through,
                       ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat,
                       NULL AS route_id, NULL AS sequence_order, NULL AS distance_along_route_m,
                       NULL AS line_no, NULL AS direction
                FROM stops
                """
            )
        rows = cur.fetchall()

    return {"stops": rows}
