"""
app/trajectory/movement_metrics.py icin testler.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.trajectory.movement_metrics import (
    haversine_distance_m,
    compute_movement_metrics,
)


def test_mesafe_hesabi_dogru():
    lat1, lon1 = 38.4192, 27.1287
    lat2, lon2 = 38.4380, 27.1428
    distance = haversine_distance_m(lat1, lon1, lat2, lon2)
    assert 2000 < distance < 3500


def test_ayni_koordinat_sifir_mesafe():
    distance = haversine_distance_m(38.46, 27.22, 38.46, 27.22)
    assert distance == 0


def test_elapsed_time_dogru():
    t0 = datetime(2026, 8, 10, 12, 0, 0)
    t1 = datetime(2026, 8, 10, 12, 1, 0)
    result = compute_movement_metrics(38.46, 27.22, t0, 38.461, 27.221, t1)
    assert result["elapsed_seconds"] == 60.0


def test_hiz_hesabi_dogru():
    t0 = datetime(2026, 8, 10, 12, 0, 0)
    t1 = t0 + timedelta(seconds=60)
    result = compute_movement_metrics(38.460, 27.220, t0, 38.4645, 27.220, t1)
    assert result["calculated_speed_kmh"] is not None
    assert result["calculated_speed_kmh"] > 0


def test_gercekci_olmayan_hiz_isaretleniyor():
    t0 = datetime(2026, 8, 10, 12, 0, 0)
    t1 = t0 + timedelta(seconds=1)
    result = compute_movement_metrics(38.40, 27.10, t0, 38.50, 27.30, t1)
    assert result["is_unrealistic_speed"] is True


def test_cok_kisa_sure_hiz_hesaplamiyor():
    t0 = datetime(2026, 8, 10, 12, 0, 0, 0)
    t1 = t0 + timedelta(milliseconds=500)
    result = compute_movement_metrics(38.46, 27.22, t0, 38.461, 27.221, t1)
    assert result["calculated_speed_kmh"] is None
