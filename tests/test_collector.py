"""
app/collectors/bus_location_collector.py icin testler.
Gorev madde 14: gercek API'ye cagri yapilmaz, mock response kullanilir.
"""
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.storage.raw_storage as raw_storage
from app.collectors.bus_location_collector import collect_line


@pytest.fixture(autouse=True)
def redirect_storage_dirs(tmp_path, monkeypatch):
    """Testler gercek data/ klasorune yazmasin, gecici klasore yazsin."""
    monkeypatch.setattr(raw_storage, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(raw_storage, "PROCESSED_DIR", tmp_path / "processed")
    yield


def make_mock_response(status_code=200, json_text=None, raise_timeout=False, raise_connection_error=False):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = json_text if json_text is not None else ""
    mock_resp.elapsed.total_seconds.return_value = 0.5
    return mock_resp


def test_basarili_response_isleniyor():
    payload = json.dumps({
        "HataMesaj": "",
        "HatOtobusKonumlari": [
            {"OtobusId": 1, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"},
        ],
        "HataVarMi": False,
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line("515")
    assert result == "OK"


def test_bos_arac_listesi_kontrollu_karsilaniyor():
    payload = json.dumps({"HataMesaj": "", "HatOtobusKonumlari": [], "HataVarMi": False})
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line("515")
    assert result == "OK"


def test_http_500_collectoru_durdurmuyor():
    mock_resp = make_mock_response(500, "Internal Server Error")
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line("515")
    assert result == "HTTP_ERROR"


def test_http_429_rate_limit_isaretleniyor():
    mock_resp = make_mock_response(429, '{"message":"API rate limit exceeded"}')
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line("515")
    assert result == "RATE_LIMITED"


def test_timeout_yonetiliyor():
    with patch("app.collectors.bus_location_collector.requests.get", side_effect=requests.Timeout):
        result = collect_line("515")
    assert result == "TIMEOUT"


def test_baglanti_hatasi_yonetiliyor():
    with patch("app.collectors.bus_location_collector.requests.get", side_effect=requests.ConnectionError):
        result = collect_line("515")
    assert result == "CONNECTION_ERROR"


def test_bozuk_json_yakalaniyor():
    mock_resp = make_mock_response(200, "{bu gecerli json degil")
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line("515")
    assert result == "JSON_PARSE_ERROR"


def test_bos_response_yakalaniyor():
    mock_resp = make_mock_response(200, "")
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line("515")
    assert result == "EMPTY_RESPONSE"


def test_bilinmeyen_sema_uygulamayi_bozmuyor():
    # HatOtobusKonumlari alani olmayan, tamamen farkli bir sema
    payload = json.dumps({"BeklenmedikAlan": "deger"})
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line("515")
    assert result == "UNKNOWN_SCHEMA"


def test_eksik_arac_id_isaretleniyor():
    payload = json.dumps({
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [{"OtobusId": None, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"}],
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        collect_line("515")

    csv_path = raw_storage.PROCESSED_DIR / "normalized_positions.csv"
    content = csv_path.read_text(encoding="utf-8")
    assert "MISSING_VEHICLE_ID" in content


def test_hatali_koordinat_isaretleniyor():
    payload = json.dumps({
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [{"OtobusId": 1, "Yon": 0, "KoorX": "0", "KoorY": "0"}],
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        collect_line("515")

    csv_path = raw_storage.PROCESSED_DIR / "normalized_positions.csv"
    content = csv_path.read_text(encoding="utf-8")
    assert "ZERO_COORDINATE" in content


def test_duplicate_observation_algilaniyor():
    payload = json.dumps({
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [
            {"OtobusId": 1, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"},
            {"OtobusId": 1, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"},  # tam ayni tekrar
        ],
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        collect_line("515")

    csv_path = raw_storage.PROCESSED_DIR / "normalized_positions.csv"
    content = csv_path.read_text(encoding="utf-8")
    assert "EXACT_DUPLICATE_IN_RESPONSE" in content


def test_payload_hash_dogru_hesaplaniyor():
    import hashlib
    payload = json.dumps({
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [{"OtobusId": 1, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"}],
    })
    expected_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        collect_line("515")

    log_path = raw_storage.RAW_DIR / "ingestion_log.csv"
    content = log_path.read_text(encoding="utf-8")
    assert expected_hash in content
