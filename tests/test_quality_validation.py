"""
app/validation/quality.py icin testler.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.validation.quality import parse_koor, validate_vehicle, detect_duplicate_ids


def test_parse_koor_virgullu_ondalik():
    assert parse_koor("38,46577667") == 38.46577667


def test_parse_koor_gecersiz_deger():
    assert parse_koor("abc") is None


def test_parse_koor_none_deger():
    assert parse_koor(None) is None


def test_validate_vehicle_gecerli_kayit():
    v = {"OtobusId": 2126, "Yon": 0, "KoorX": "38,465", "KoorY": "27,228"}
    result = validate_vehicle(v)
    assert result["is_valid"] is True
    assert result["quality_flags"] == []
    assert result["vehicle_id"] == 2126


def test_validate_vehicle_eksik_id():
    v = {"OtobusId": None, "Yon": 0, "KoorX": "38,465", "KoorY": "27,228"}
    result = validate_vehicle(v)
    assert result["is_valid"] is False
    assert "MISSING_VEHICLE_ID" in result["quality_flags"]


def test_validate_vehicle_sifir_koordinat():
    v = {"OtobusId": 1, "Yon": 0, "KoorX": "0", "KoorY": "0"}
    result = validate_vehicle(v)
    assert result["is_valid"] is False
    assert "ZERO_COORDINATE" in result["quality_flags"]


def test_validate_vehicle_izmir_disi_koordinat():
    v = {"OtobusId": 1, "Yon": 0, "KoorX": "39,92", "KoorY": "32,85"}
    result = validate_vehicle(v)
    assert result["is_valid"] is False
    assert any("OUT_OF_RANGE" in f for f in result["quality_flags"])


def test_validate_vehicle_parse_edilemeyen_koordinat():
    v = {"OtobusId": 1, "Yon": 0, "KoorX": "gecersiz", "KoorY": "27,2"}
    result = validate_vehicle(v)
    assert result["is_valid"] is False
    assert "COORDINATE_PARSE_ERROR" in result["quality_flags"]


def test_detect_duplicate_ids_gercek_duplicate():
    vehicles = [
        {"OtobusId": 1, "KoorX": "38,4", "KoorY": "27,1"},
        {"OtobusId": 1, "KoorX": "38,4", "KoorY": "27,1"},
    ]
    duplicates = detect_duplicate_ids(vehicles)
    assert len(duplicates) == 1


def test_detect_duplicate_ids_trail_noktasi_duplicate_sayilmaz():
    vehicles = [
        {"OtobusId": 1, "KoorX": "38,4", "KoorY": "27,1"},
        {"OtobusId": 1, "KoorX": "38,5", "KoorY": "27,2"},
    ]
    duplicates = detect_duplicate_ids(vehicles)
    assert len(duplicates) == 0
