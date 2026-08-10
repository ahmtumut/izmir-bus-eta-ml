"""
Collector'i calistirmak icin giris noktasi.
Kullanim: python scripts/run_collector.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collectors.bus_location_collector import run_collector

PILOT_LINES = ["515", "121", "761"]

if __name__ == "__main__":
    run_collector(PILOT_LINES, cycle_interval_seconds=60, delay_between_lines=3)
