"""
Faz 2 madde 1: GPS belirsizligi arastirmasi icin ana API ve support API'yi
AYNI ingestion_run altinda, ayni cycle'larda birlikte calistirir.

Bu, "ayni aracin zaman icinde GPS koordinati ile KalanDurakSayisi
degisimini karsilastir" gereksinimini karsilar - iki API'nin gozlemleri
ayni zaman ekseninde (ayni run_id, yakin observed_at) DB'ye yazilir.

Kullanim:
    python scripts/run_dual_collector.py --minutes 90
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Proje kokunu sys.path'e ekle (scripts/ altindan calistirilinca "app" modulu
# bulunamiyor, cunku Python sadece scripts/ klasorunu path'e ekliyor).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import db_storage
from app.collectors.bus_location_collector import collect_line, COLLECTOR_VERSION
from app.collectors.supporting_api_collector import run_support_collector, PILOT_LINE_STOPS

CYCLE_INTERVAL_SECONDS = 60
DELAY_BETWEEN_CALLS = 3


def main(duration_minutes: int):
    lines = list(PILOT_LINE_STOPS.keys())
    conn = db_storage.get_connection()
    run_id = db_storage.start_ingestion_run(
        conn, target_lines=lines,
        collector_version=f"{COLLECTOR_VERSION}-dual-madde1",
    )
    print(f"Dual collector basladi. ingestion_run_id={run_id}, "
          f"hedef sure={duration_minutes} dk, hatlar={lines}")
    print("Erken durdurmak icin Ctrl+C\n")

    end_time = time.monotonic() + duration_minutes * 60
    cycle_num = 0

    try:
        while time.monotonic() < end_time:
            cycle_num += 1
            cycle_start = time.monotonic()
            print(f"--- Cycle {cycle_num} ({datetime.now().strftime('%H:%M:%S')}) ---")

            # 1) Ana API - tum pilot hatlar
            for i, line_no in enumerate(lines):
                result = collect_line(conn, run_id, line_no)
                print(f"  [main] Hat {line_no}: {result}")
                time.sleep(DELAY_BETWEEN_CALLS)

            # 2) Support API - tum pilot hat+durak ciftleri
            run_support_collector(conn, run_id, delay_between_lines=DELAY_BETWEEN_CALLS)

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, CYCLE_INTERVAL_SECONDS - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\nErken durduruldu. Toplam {cycle_num} cycle tamamlandi.")
    finally:
        db_storage.end_ingestion_run(conn, run_id)
        conn.close()
        print(f"\nTamamlandi. ingestion_run_id={run_id}, toplam cycle={cycle_num}")
        print("Analiz icin: SELECT * FROM vehicle_observations WHERE raw_snapshot_id IN "
              f"(SELECT id FROM raw_snapshots WHERE ingestion_run_id={run_id});")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Madde 1: GPS belirsizligi arastirmasi icin dual collector")
    parser.add_argument("--minutes", type=int, default=90,
                         help="Toplam calisma suresi (dk). Gorev: 60-120 dk arasi.")
    args = parser.parse_args()
    main(args.minutes)
