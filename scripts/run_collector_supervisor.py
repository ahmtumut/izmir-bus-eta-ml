"""
Faz 4: collector'i KALICI (uzun sureli, kesintisiz) calistirmak icin
supervisor/watchdog script'i.

run_dual_collector.py --minutes N ile calistirilinca sure dolunca ya da
beklenmedik bir hatada (ag kesintisi, DB baglanti sorunu, ESHOT API'sinin
gecici 5xx/429 donmesi vb.) surec tamamen duruyor - kullanicinin elle fark
edip yeniden baslatmasi gerekiyordu (bu proje boyunca birden fazla kez
oldu). Bu script bunun yerine: run_dual_collector.main()'i COK UZUN bir
sure (varsayilan 24 saat) ile cagirir, CIKTIGINDA (sure doldu ya da
beklenmeyen bir exception) KISA bir bekleme sonrasi YENI bir
ingestion_run ile OTOMATIK olarak yeniden baslatir - sonsuz bir dongude.

Ctrl+C ile supervisor'in KENDISI durdurulabilir (o an devam eden run
duzgunce sonlandirilir, run_dual_collector.main()'in kendi
KeyboardInterrupt/finally mantigi calisir).

Loglar hem konsola hem de logs/collector_supervisor.log dosyasina yazilir
(dosya, restart/hata gecmisini kalici olarak saklamak icin - "collector
neden durdu/kac kere yeniden basladi" sorusuna sonradan cevap verebilmek
icin).

Kullanim:
    python scripts/run_collector_supervisor.py --lines 515,121,761 --cycle-seconds 30
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_dual_collector import main as run_collector_once, DEFAULT_CYCLE_INTERVAL_SECONDS

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

RESTART_BACKOFF_SECONDS = 15
# Tek bir ingestion_run'in ust siniri - bu sureyi normal sekilde
# doldurursa (hata degil) supervisor otomatik olarak YENI bir run baslatir,
# boylece tek bir run tablo/log acisindan sonsuza kadar buyumez.
RUN_DURATION_MINUTES = 24 * 60

logger = logging.getLogger("collector_supervisor")
logger.setLevel(logging.INFO)
_console = logging.StreamHandler(sys.stdout)
_file = logging.FileHandler(LOG_DIR / "collector_supervisor.log", encoding="utf-8")
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_console.setFormatter(_fmt)
_file.setFormatter(_fmt)
logger.addHandler(_console)
logger.addHandler(_file)


def supervise(lines_filter: str | None, cycle_seconds: int,
              validation_every_minutes: int, validation_burst_minutes: int):
    attempt = 0
    logger.info(
        "Supervisor baslatildi. hatlar=%s cycle=%ssn run-suresi=%sdk",
        lines_filter or "tum pilot hatlar", cycle_seconds, RUN_DURATION_MINUTES,
    )
    while True:
        attempt += 1
        logger.info("Collector run #%d baslatiliyor...", attempt)
        try:
            run_collector_once(
                duration_minutes=RUN_DURATION_MINUTES,
                session_label="supervised",
                validation_every_minutes=validation_every_minutes,
                validation_burst_minutes=validation_burst_minutes,
                lines_filter=lines_filter,
                cycle_seconds=cycle_seconds,
            )
            logger.info("Run #%d normal sekilde sona erdi (sure doldu).", attempt)
        except KeyboardInterrupt:
            logger.info("Supervisor kullanici tarafindan durduruldu (Ctrl+C).")
            return
        except Exception:
            logger.exception("Run #%d beklenmeyen bir hatayla sonlandi.", attempt)

        logger.info("%d saniye sonra yeni bir run baslatilacak...", RESTART_BACKOFF_SECONDS)
        try:
            time.sleep(RESTART_BACKOFF_SECONDS)
        except KeyboardInterrupt:
            logger.info("Supervisor kullanici tarafindan durduruldu (Ctrl+C).")
            return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collector'i kalici/kesintisiz calistiran supervisor - "
                     "her run bittiginde (sure dolmasi ya da hata) otomatik yeniden baslatir."
    )
    parser.add_argument("--lines", type=str, default=None,
                         help="Sadece bu hatlari topla (virgulle ayir). Belirtilmezse tum pilot hatlar.")
    parser.add_argument("--cycle-seconds", type=int, default=DEFAULT_CYCLE_INTERVAL_SECONDS,
                         help=f"Normal cycle araligi (sn). Varsayilan {DEFAULT_CYCLE_INTERVAL_SECONDS}sn.")
    parser.add_argument("--validation-every-minutes", type=int, default=30)
    parser.add_argument("--validation-burst-minutes", type=int, default=10)
    args = parser.parse_args()

    supervise(args.lines, args.cycle_seconds, args.validation_every_minutes, args.validation_burst_minutes)
