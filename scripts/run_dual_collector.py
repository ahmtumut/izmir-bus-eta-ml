"""
Faz 2 madde 1: GPS belirsizligi arastirmasi icin ana API ve support API'yi
AYNI ingestion_run altinda, ayni cycle'larda birlikte calistirir.

Bu, "ayni aracin zaman icinde GPS koordinati ile KalanDurakSayisi
degisimini karsilastir" gereksinimini karsilar - iki API'nin gozlemleri
ayni zaman ekseninde (ayni run_id, yakin observed_at) DB'ye yazilir.

Faz 3 GOLD validation (v3 - supervisor duzeltmesi #2): v2'de (6 durak, 30sn
cadence, ana GPS + support birlikte) HALA 0 HIGH cikti. Sebep bulundu: ana GPS'i
de 30sn'de bir sorgulayinca yaklasma/gecis penceresi COK DAHA HASSAS olcduldu
(onceki 60-120sn'lik pencereler aslinda seyrek GPS orneklemesinin bir yapay
urunuymus) - gercek fiziksel varis penceresi ~0-30sn'ye dustu. Bu da support
API'nin 30sn cadence'iyle ayni buyuklukte - 2 ornek yakalamak yine sansa kaldi.

v3 duzeltmesi: support API (sadece GOLD_VALIDATION_STOPS, 6 durak) ana GPS'ten
BAGIMSIZ, cok daha sik (varsayilan 12sn) sorgulanir; ana GPS ise daha seyrek
(3 support tick'te bir, ~36sn) sorgulanir - cunku darbogaz artik ana GPS
cozunurlugu degil, support API cozunurlugu. Amac: ~0-30sn'lik gercek varis
penceresi icine en az 2 support-API ornegi dusurmek.

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
from app.collectors.supporting_api_collector import (
    run_support_collector, run_gold_validation_collector, PILOT_LINE_STOPS,
)

CYCLE_INTERVAL_SECONDS = 60
DELAY_BETWEEN_CALLS = 3

# GOLD burst v3: support API (6 durak) ana GPS'ten bagimsiz, cok sik sorgulanir.
# 6 durak x ~0.7sn gecikme ~5-6sn suruyor; 12sn cadence rahat bosluk birakiyor.
GOLD_SUPPORT_TICK_SECONDS = 12
GOLD_BURST_CALL_DELAY_SECONDS = 0.7
# Ana GPS her N support tick'inde bir sorgulanir (~N*12sn'de bir) - darbogaz
# artik ana GPS cozunurlugu olmadigi icin bunu seyrek tutmak yeterli ve
# ana API'yi de gereksiz yere yormaz.
GOLD_MAIN_EVERY_N_TICKS = 3


def run_gold_burst(conn, run_id: int, lines: list, burst_minutes: float):
    """Burst penceresi boyunca GOLD_VALIDATION_STOPS'u siki cadence'le
    (GOLD_SUPPORT_TICK_SECONDS) sorgular; ana GPS'i daha seyrek
    (GOLD_MAIN_EVERY_N_TICKS tick'te bir) sorgular. Bu fonksiyon blocking'dir;
    disaridaki normal CYCLE_INTERVAL_SECONDS dongusu ile cakismaz."""
    print(f"  >> GOLD validation burst basladi ({burst_minutes:.1f} dk, "
          f"support {GOLD_SUPPORT_TICK_SECONDS}sn / ana GPS ~{GOLD_SUPPORT_TICK_SECONDS * GOLD_MAIN_EVERY_N_TICKS}sn cadence)")
    burst_end = time.monotonic() + burst_minutes * 60
    tick_num = 0

    while time.monotonic() < burst_end:
        tick_num += 1
        tick_start = time.monotonic()

        if tick_num % GOLD_MAIN_EVERY_N_TICKS == 1:
            for line_no in lines:
                result = collect_line(conn, run_id, line_no)
                print(f"    [gold-main] Hat {line_no}: {result}")
                time.sleep(GOLD_BURST_CALL_DELAY_SECONDS)

        run_gold_validation_collector(conn, run_id, delay_between_calls=GOLD_BURST_CALL_DELAY_SECONDS, lines=lines)

        tick_elapsed = time.monotonic() - tick_start
        time.sleep(max(0, GOLD_SUPPORT_TICK_SECONDS - tick_elapsed))

    print(f"  >> GOLD validation burst bitti ({tick_num} support tick tamamlandi)")


def main(duration_minutes: int, session_label: str,
         validation_every_minutes: int, validation_burst_minutes: int,
         lines_filter: str = None):
    all_lines = list(PILOT_LINE_STOPS.keys())
    if lines_filter:
        requested = [l.strip() for l in lines_filter.split(",")]
        unknown = [l for l in requested if l not in all_lines]
        if unknown:
            raise ValueError(f"Bilinmeyen hat(lar): {unknown}. Gecerli hatlar: {all_lines}")
        lines = requested
    else:
        lines = all_lines
    conn = db_storage.get_connection()
    version_suffix = f"-dual-madde1-{session_label}" if session_label else "-dual-madde1"
    run_id = db_storage.start_ingestion_run(
        conn, target_lines=lines,
        collector_version=f"{COLLECTOR_VERSION}{version_suffix}",
    )
    print(f"Dual collector basladi. ingestion_run_id={run_id}, "
          f"hedef sure={duration_minutes} dk, hatlar={lines}, session={session_label or '(belirtilmedi)'}")
    print(f"GOLD validation burst: her {validation_every_minutes} dk'da bir, "
          f"{validation_burst_minutes} dk boyunca support {GOLD_SUPPORT_TICK_SECONDS}sn cadence")
    print("Erken durdurmak icin Ctrl+C\n")

    start_time = time.monotonic()
    end_time = start_time + duration_minutes * 60
    cycle_num = 0

    try:
        while time.monotonic() < end_time:
            cycle_num += 1
            cycle_start = time.monotonic()
            elapsed_minutes = (cycle_start - start_time) / 60
            print(f"--- Cycle {cycle_num} ({datetime.now().strftime('%H:%M:%S')}) ---")

            in_burst_window = (
                validation_every_minutes > 0
                and (elapsed_minutes % validation_every_minutes) < validation_burst_minutes
            )

            if in_burst_window:
                # Bu pencere penceresinin sonuna kadar kalan sure kadar blocking calisir,
                # icinde hem ana GPS hem GOLD duraklari siki cadence'le sorgular.
                remaining_burst = validation_burst_minutes - (elapsed_minutes % validation_every_minutes)
                run_gold_burst(conn, run_id, lines, remaining_burst)
                continue

            # Normal (burst disi) cycle: ana API + sadece pilot duraklar (seyrek izleme)
            for i, line_no in enumerate(lines):
                result = collect_line(conn, run_id, line_no)
                print(f"  [main] Hat {line_no}: {result}")
                time.sleep(DELAY_BETWEEN_CALLS)

            run_support_collector(conn, run_id, delay_between_lines=DELAY_BETWEEN_CALLS, lines=lines)

            elapsed = time.monotonic() - cycle_start
            remaining = max(0, CYCLE_INTERVAL_SECONDS - elapsed)
            time.sleep(remaining)

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
    parser.add_argument("--session-label", type=str, default="",
                         help="Faz 3: zaman dilimi etiketi (sabah/ogle/aksam), collector_version'a eklenir")
    parser.add_argument("--validation-every-minutes", type=int, default=30,
                         help="Faz 3: kac dakikada bir GOLD validation burst baslatilsin (0 = devre disi)")
    parser.add_argument("--validation-burst-minutes", type=int, default=10,
                         help="Faz 3: her validation burst kac dakika sursun")
    parser.add_argument("--lines", type=str, default=None,
                         help="Faz 3: sadece bu hatlari topla (virgulle ayir, ör. '761'). "
                              "Belirtilmezse tum pilot hatlar (515,121,761) toplanir.")
    args = parser.parse_args()
    main(args.minutes, args.session_label, args.validation_every_minutes,
         args.validation_burst_minutes, args.lines)
