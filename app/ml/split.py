"""
Faz 3: Train/Validation/Test split.

KRITIK KURALLAR (data leakage koruması):
1. Split satir bazinda DEGIL, arrival_event_id bazinda yapilir. Bir arrival
   event'ten birden fazla T0 training sample uretilebildigi icin (bkz.
   generate_eta_training_samples.py), ayni event'in bir T0'i train'e digeri
   test'e duserse model kendi gordugu bir yolculugun baska bir anini "test"
   ediyormus gibi yapay sekilde iyi sonuc verir. Bu yuzden butun satirlar
   arrival_event_id'ye gore GRUPLANIP birlikte tek bir split'e atanir.
2. Split ZAMANSAL siralidir (random degil): erken donem -> train, sonraki
   -> validation, en son -> test. Sira, arrival_events.arrival_observed_at
   (event'in gerctek dunya zamani) baz alinarak kurulur - bu, gercek
   deployment senaryosunu taklit eder (gecmis veriyle egit, gelecegi tahmin
   et) ve zamansal olarak "gelecegi gorerek" model secimi yapmayi engeller.
3. label_quality='REJECTED' satirlar split disi tutulur (dataset_split=NULL)
   - bunlar zaten training/evaluation icin kullanilmiyor (bkz. migration 008
   ve docs/faz3-veri-toplama-ve-gold-bulgulari.md'deki vehicle_id reuse
   bulgusu).
4. Oranlar (~%70/15/15) EVENT SAYISINA gore hedeflenir, ama bir event asla
   bolunmez - oran ugruna event parcalanmaz (gorev talimati).

HAT BAZINDA SPLIT (--per-line): Ilk (global) zamansal split'te 761 hattinin
verisinin %97'si tek bir gunden (16 Agustos, 10 saatlik oturum) geldigi icin
test seti hat dagilimi acisindan ciddi carpitildi (bkz.
docs/faz3-veri-toplama-ve-gold-bulgulari.md, Bulgu 3). --per-line modu,
split'i TUM veri uzerinde degil HER HATTIN KENDI event zaman ekseni
icinde ayri ayri yapar (515 kendi icinde erken/orta/gec, 121 kendi icinde,
761 kendi icinde), sonra hepsini ayni dataset_split kolonuna birlestirir.
Bu, her split'te uc hattin da orantili temsil edilmesini saglar - AMA
761'in kendi ic zaman araligi hala buyuk olcude tek gune sikismis oldugu
icin bu hat ozelinde split "gun-arasi" degil kismen "gun-ici" genelleme
test eder (bilinen ve dokumante edilmis bir sinirlama, veri toplamadan
tam cozulemez).

Kullanim:
    python -m app.ml.split --per-line
    python -m app.ml.split --per-line --train-ratio 0.7 --val-ratio 0.15
"""
import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.storage import db_storage

DEFAULT_TRAIN_RATIO = 0.70
DEFAULT_VAL_RATIO = 0.15
# test_ratio = 1 - train_ratio - val_ratio


def fetch_valid_events(conn):
    """label_quality != REJECTED olan satirlarin arkasindaki benzersiz
    arrival_event'leri, event'in kendi arrival_observed_at zamaniyla birlikte
    getirir. Zaman kaynagi arrival_events tablosu (T0'larin observed_at'i
    DEGIL) - cunku bir event'i zaman ekseninde TEK bir noktaya yerlestirmek
    istiyoruz (o yolculugun ne zaman gerceklestigi), T0 coklugu degil."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ets.arrival_event_id, ae.arrival_observed_at
            FROM eta_training_samples ets
            JOIN arrival_events ae ON ae.id = ets.arrival_event_id
            WHERE ets.label_quality != 'REJECTED'
            ORDER BY ae.arrival_observed_at ASC
            """
        )
        return cur.fetchall()


def fetch_valid_events_by_line(conn):
    """fetch_valid_events ile ayni, ama ets.line_no'ya gore ayri ayri
    gruplanmis dondurur: {line_no: [(event_id, arrival_observed_at), ...]}
    (her liste kendi icinde zamansal sirali)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ets.line_no, ets.arrival_event_id, ae.arrival_observed_at
            FROM eta_training_samples ets
            JOIN arrival_events ae ON ae.id = ets.arrival_event_id
            WHERE ets.label_quality != 'REJECTED'
            ORDER BY ets.line_no, ae.arrival_observed_at ASC
            """
        )
        rows = cur.fetchall()

    by_line = {}
    for line_no, event_id, arrival_observed_at in rows:
        by_line.setdefault(line_no, []).append((event_id, arrival_observed_at))
    return by_line


def assign_splits(events, train_ratio, val_ratio):
    """events: [(event_id, arrival_observed_at), ...] zaten zamansal sirali.
    Doner: {event_id: 'train'|'validation'|'test'}"""
    n = len(events)
    train_cut = int(n * train_ratio)
    val_cut = int(n * (train_ratio + val_ratio))

    assignment = {}
    for i, (event_id, _) in enumerate(events):
        if i < train_cut:
            assignment[event_id] = "train"
        elif i < val_cut:
            assignment[event_id] = "validation"
        else:
            assignment[event_id] = "test"
    return assignment


def apply_split(conn, assignment: dict):
    by_split = {"train": [], "validation": [], "test": []}
    for event_id, split in assignment.items():
        by_split[split].append(event_id)

    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        for split, event_ids in by_split.items():
            if not event_ids:
                continue
            cur.execute(
                """
                UPDATE eta_training_samples
                SET dataset_split = %s, split_assigned_at = %s
                WHERE arrival_event_id = ANY(%s) AND label_quality != 'REJECTED'
                """,
                (split, now, event_ids),
            )
    return by_split


def get_git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent
        ).decode().strip()
    except Exception:
        return "unknown"


def build_report(conn, events, by_split_event_ids, per_line: bool = False) -> list[str]:
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 70)
    out("FAZ 3 TRAIN/VALIDATION/TEST SPLIT RAPORU")
    out("=" * 70)
    out(f"\nOlusturulma zamani (UTC): {datetime.now(timezone.utc).isoformat()}")
    out(f"Git commit SHA: {get_git_sha()}")
    out(f"\nToplam gecerli (REJECTED disi) benzersiz arrival_event: {len(events)}")

    event_time_by_id = dict(events)

    with conn.cursor() as cur:
        for split in ("train", "validation", "test"):
            event_ids = by_split_event_ids.get(split, [])
            if not event_ids:
                out(f"\n--- {split.upper()}: 0 event ---")
                continue

            times = [event_time_by_id[eid] for eid in event_ids]
            out(f"\n--- {split.upper()} ---")
            out(f"  Event sayisi: {len(event_ids)}")
            out(f"  Zaman araligi: {min(times)}  ->  {max(times)}")

            cur.execute(
                """
                SELECT count(*), count(DISTINCT arrival_event_id)
                FROM eta_training_samples
                WHERE dataset_split = %s
                """,
                (split,),
            )
            row_count, event_count_check = cur.fetchone()
            out(f"  Satir sayisi (eta_training_samples): {row_count}")

            cur.execute(
                """
                SELECT line_no, count(*) FROM eta_training_samples
                WHERE dataset_split = %s GROUP BY 1 ORDER BY 1
                """,
                (split,),
            )
            out(f"  Hat bazinda satir: {cur.fetchall()}")

            cur.execute(
                """
                SELECT label_quality, count(*) FROM eta_training_samples
                WHERE dataset_split = %s GROUP BY 1 ORDER BY 1
                """,
                (split,),
            )
            out(f"  Label quality bazinda satir: {cur.fetchall()}")

    out("\n" + "=" * 70)
    mode_desc = ("HAT BAZINDA (--per-line): her hat kendi zaman ekseninde ayri "
                 "ayri split edildi, sonra birlestirildi." if per_line else
                 "GLOBAL: tum hatlar birlikte tek bir zaman ekseninde split edildi.")
    out(f"Split modu: {mode_desc}")
    out("Not: Split arrival_event_id bazinda ve zamansal siralidir (erken -> "
        "train, gec -> test). Oranlar event sayisina gore hedeflendi, hicbir "
        "event bolunmedi. label_quality=REJECTED satirlar split disi "
        "birakildi (dataset_split=NULL).")
    out("=" * 70)

    return lines


def main():
    parser = argparse.ArgumentParser(description="Faz 3 train/validation/test split")
    parser.add_argument("--train-ratio", type=float, default=DEFAULT_TRAIN_RATIO)
    parser.add_argument("--val-ratio", type=float, default=DEFAULT_VAL_RATIO)
    parser.add_argument("--per-line", action="store_true",
                         help="Split'i her hat icin kendi zaman ekseninde ayri ayri yap "
                              "(bkz. modul docstring'i - hat dagilimi carpitilmasini onler)")
    parser.add_argument("--save", type=str, default=None,
                         help="Raporu bu dosyaya da yaz (ör. reports/split-report-20260817.md)")
    args = parser.parse_args()

    if args.train_ratio + args.val_ratio >= 1.0:
        parser.error("train-ratio + val-ratio < 1.0 olmali (test_ratio icin pay kalmali)")

    conn = db_storage.get_connection()

    if args.per_line:
        events_by_line = fetch_valid_events_by_line(conn)
        if not events_by_line:
            print("Split edilecek gecerli (REJECTED disi) event bulunamadi.")
            conn.close()
            return

        assignment = {}
        for line_no, line_events in events_by_line.items():
            line_assignment = assign_splits(line_events, args.train_ratio, args.val_ratio)
            assignment.update(line_assignment)
            print(f"Hat {line_no}: {len(line_events)} event split edildi "
                  f"(train={sum(1 for v in line_assignment.values() if v=='train')}, "
                  f"validation={sum(1 for v in line_assignment.values() if v=='validation')}, "
                  f"test={sum(1 for v in line_assignment.values() if v=='test')})")
        events = [e for line_events in events_by_line.values() for e in line_events]
    else:
        events = fetch_valid_events(conn)
        if not events:
            print("Split edilecek gecerli (REJECTED disi) event bulunamadi.")
            conn.close()
            return
        assignment = assign_splits(events, args.train_ratio, args.val_ratio)

    by_split = apply_split(conn, assignment)

    lines = build_report(conn, events, by_split, per_line=args.per_line)
    conn.close()

    if args.save:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nRapor kaydedildi: {out_path}")


if __name__ == "__main__":
    main()
