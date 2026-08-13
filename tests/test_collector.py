"""
app/collectors/bus_location_collector.py icin testler.
Gorev madde 14: gercek API'ye cagri yapilmaz, mock response kullanilir.

FAZ 2 GUNCELLEMESI: collect_line artik (conn, run_id, line_no) aliyor ve
CSV/dosya yerine app.storage.db_storage uzerinden DB'ye yaziyor. Bu testler
artik gercek bir DB baglantisina ihtiyac duymuyor - db_storage fonksiyonlari
tamamen mock'lanıyor, boylece hem hizli hem izole kalıyor (Docker gerekmez).
"""
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collectors.bus_location_collector import collect_line


@pytest.fixture()
def conn():
    """Gercek DB baglantisi yerine sahte bir connection - cursor() context
    manager'ini destekleyen minimal bir mock."""
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = MagicMock()
    fake_conn.cursor.return_value.__exit__.return_value = False
    return fake_conn


@pytest.fixture(autouse=True)
def mock_db_storage():
    """db_storage'in yazma fonksiyonlarini mock'lar; collect_line'in DB'ye
    GERCEKTEN gitmesine gerek kalmaz. save_vehicle_observations'a gecen
    records listesini yakalamak icin call_args uzerinden erisiyoruz."""
    with patch("app.collectors.bus_location_collector.db_storage.save_raw_snapshot",
               return_value=1) as mock_save_snapshot, \
         patch("app.collectors.bus_location_collector.db_storage.save_vehicle_observations",
               return_value=0) as mock_save_obs, \
         patch("app.collectors.bus_location_collector.db_storage.log_quality_event") as mock_log_event:
        yield {
            "save_raw_snapshot": mock_save_snapshot,
            "save_vehicle_observations": mock_save_obs,
            "log_quality_event": mock_log_event,
        }


def make_mock_response(status_code=200, json_text=None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = json_text if json_text is not None else ""
    mock_resp.elapsed.total_seconds.return_value = 0.5
    return mock_resp


def get_saved_records(mock_db_storage):
    """save_vehicle_observations'a gecen 'records' kwarg/positional'ini doner."""
    call = mock_db_storage["save_vehicle_observations"].call_args
    if call is None:
        return []
    # collect_line, save_vehicle_observations'i named argumanlarla cagiriyor:
    # db_storage.save_vehicle_observations(conn, raw_snapshot_id=..., line_no=...,
    #                                       observed_at=..., records=...)
    if "records" in call.kwargs:
        return call.kwargs["records"]
    return call.args[-1]  # pozisyonel cagrilmissa son argumandir


# ---------------------------------------------------------------------------
# Temel HTTP/parse senaryolari
# ---------------------------------------------------------------------------

def test_basarili_response_isleniyor(conn, mock_db_storage):
    payload = json.dumps({
        "HataMesaj": "",
        "HatOtobusKonumlari": [
            {"OtobusId": 1, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"},
        ],
        "HataVarMi": False,
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line(conn, 1, "515")
    assert result == "OK"
    mock_db_storage["save_raw_snapshot"].assert_called_once()
    mock_db_storage["save_vehicle_observations"].assert_called_once()


def test_bos_arac_listesi_kontrollu_karsilaniyor(conn, mock_db_storage):
    payload = json.dumps({"HataMesaj": "", "HatOtobusKonumlari": [], "HataVarMi": False})
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line(conn, 1, "515")
    assert result == "OK"


def test_http_500_collectoru_durdurmuyor(conn, mock_db_storage):
    mock_resp = make_mock_response(500, "Internal Server Error")
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line(conn, 1, "515")
    assert result == "HTTP_ERROR"
    mock_db_storage["save_raw_snapshot"].assert_not_called()


def test_http_429_rate_limit_isaretleniyor(conn, mock_db_storage):
    mock_resp = make_mock_response(429, '{"message":"API rate limit exceeded"}')
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line(conn, 1, "515")
    assert result == "RATE_LIMITED"


def test_timeout_yonetiliyor(conn, mock_db_storage):
    with patch("app.collectors.bus_location_collector.requests.get", side_effect=requests.Timeout):
        result = collect_line(conn, 1, "515")
    assert result == "TIMEOUT"


def test_baglanti_hatasi_yonetiliyor(conn, mock_db_storage):
    with patch("app.collectors.bus_location_collector.requests.get", side_effect=requests.ConnectionError):
        result = collect_line(conn, 1, "515")
    assert result == "CONNECTION_ERROR"


def test_bozuk_json_yakalaniyor(conn, mock_db_storage):
    mock_resp = make_mock_response(200, "{bu gecerli json degil")
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line(conn, 1, "515")
    assert result == "JSON_PARSE_ERROR"


def test_bos_response_yakalaniyor(conn, mock_db_storage):
    mock_resp = make_mock_response(200, "")
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line(conn, 1, "515")
    assert result == "EMPTY_RESPONSE"


def test_bilinmeyen_sema_uygulamayi_bozmuyor(conn, mock_db_storage):
    payload = json.dumps({"BeklenmedikAlan": "deger"})
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        result = collect_line(conn, 1, "515")
    assert result == "UNKNOWN_SCHEMA"


# ---------------------------------------------------------------------------
# Kalite bayraklari - artik CSV yerine save_vehicle_observations'a
# gecen 'records' listesindeki quality_flags alaninda kontrol ediliyor.
# ---------------------------------------------------------------------------

def test_eksik_arac_id_isaretleniyor(conn, mock_db_storage):
    payload = json.dumps({
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [{"OtobusId": None, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"}],
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        collect_line(conn, 1, "515")

    records = get_saved_records(mock_db_storage)
    assert len(records) == 1
    assert "MISSING_VEHICLE_ID" in records[0]["quality_flags"]


def test_hatali_koordinat_isaretleniyor(conn, mock_db_storage):
    payload = json.dumps({
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [{"OtobusId": 1, "Yon": 0, "KoorX": "0", "KoorY": "0"}],
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        collect_line(conn, 1, "515")

    records = get_saved_records(mock_db_storage)
    assert "ZERO_COORDINATE" in records[0]["quality_flags"]


def test_duplicate_observation_algilaniyor(conn, mock_db_storage):
    payload = json.dumps({
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [
            {"OtobusId": 1, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"},
            {"OtobusId": 1, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"},  # tam ayni tekrar
        ],
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        collect_line(conn, 1, "515")

    records = get_saved_records(mock_db_storage)
    assert any("EXACT_DUPLICATE_IN_RESPONSE" in r["quality_flags"] for r in records)


def test_payload_hash_save_raw_snapshot_a_gonderiliyor(conn, mock_db_storage):
    """Hash hesaplamasi artik db_storage.save_raw_snapshot icinde yapiliyor
    (raw_text'ten); burada sadece dogru raw_text'in gonderildigini dogruluyoruz."""
    payload = json.dumps({
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [{"OtobusId": 1, "Yon": 0, "KoorX": "38,46", "KoorY": "27,22"}],
    })
    mock_resp = make_mock_response(200, payload)
    with patch("app.collectors.bus_location_collector.requests.get", return_value=mock_resp):
        collect_line(conn, 1, "515")

    call = mock_db_storage["save_raw_snapshot"].call_args
    sent_raw_text = call.kwargs.get("raw_text") if "raw_text" in call.kwargs else call.args[-1]
    assert sent_raw_text == payload
