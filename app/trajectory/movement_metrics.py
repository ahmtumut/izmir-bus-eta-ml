"""
Ardisik iki gecerli GPS gozleminden hareket metrikleri turetir.
"""
import math
from datetime import datetime
from typing import Optional

EARTH_RADIUS_M = 6371000
MAX_REALISTIC_SPEED_KMH = 90.0
MIN_ELAPSED_SECONDS_FOR_SPEED = 1.0


def haversine_distance_m(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


def bearing_degrees(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    theta = math.atan2(x, y)
    return (math.degrees(theta) + 360) % 360


def compute_movement_metrics(prev_lat, prev_lon, prev_time, curr_lat, curr_lon, curr_time):
    elapsed_seconds = (curr_time - prev_time).total_seconds()
    distance_m = haversine_distance_m(prev_lat, prev_lon, curr_lat, curr_lon)
    bearing = bearing_degrees(prev_lat, prev_lon, curr_lat, curr_lon)

    speed_kmh = None
    is_unrealistic = False

    if elapsed_seconds >= MIN_ELAPSED_SECONDS_FOR_SPEED:
        speed_kmh = (distance_m / elapsed_seconds) * 3.6
        if speed_kmh > MAX_REALISTIC_SPEED_KMH:
            is_unrealistic = True

    return {
        "distance_meters": round(distance_m, 2),
        "elapsed_seconds": round(elapsed_seconds, 1),
        "calculated_speed_kmh": round(speed_kmh, 2) if speed_kmh is not None else None,
        "bearing_degrees": round(bearing, 1),
        "is_unrealistic_speed": is_unrealistic,
    }
