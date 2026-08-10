"""
GPS verisi uzerinde temel kalite kontrolleri.
Supheli kayitlar silinmez, is_valid=False ve quality_flags ile isaretlenir.
"""
from typing import Optional

IZMIR_LAT_MIN, IZMIR_LAT_MAX = 38.0, 38.9
IZMIR_LON_MIN, IZMIR_LON_MAX = 26.5, 27.5


def parse_koor(value: Optional[str]):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def validate_vehicle(raw_vehicle: dict) -> dict:
    flags = []

    vehicle_id = raw_vehicle.get("OtobusId")
    if vehicle_id is None:
        flags.append("MISSING_VEHICLE_ID")

    direction = raw_vehicle.get("Yon")

    lat = parse_koor(raw_vehicle.get("KoorX"))
    lon = parse_koor(raw_vehicle.get("KoorY"))

    if lat is None or lon is None:
        flags.append("COORDINATE_PARSE_ERROR")
    else:
        if lat == 0 and lon == 0:
            flags.append("ZERO_COORDINATE")
        elif not (IZMIR_LAT_MIN <= lat <= IZMIR_LAT_MAX):
            flags.append("LATITUDE_OUT_OF_RANGE")
        elif not (IZMIR_LON_MIN <= lon <= IZMIR_LON_MAX):
            flags.append("LONGITUDE_OUT_OF_RANGE")

    is_valid = len(flags) == 0

    return {
        "vehicle_id": vehicle_id,
        "latitude": lat,
        "longitude": lon,
        "direction": direction,
        "is_valid": is_valid,
        "quality_flags": flags,
    }


def detect_duplicate_ids(raw_vehicles):
    seen = set()
    duplicates = set()
    for v in raw_vehicles:
        vid = v.get("OtobusId")
        if vid is None:
            continue
        key = (vid, v.get("KoorX"), v.get("KoorY"))
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return duplicates
