======================================================================
FAZ 3 TRAIN/VALIDATION/TEST SPLIT RAPORU
======================================================================

Olusturulma zamani (UTC): 2026-08-17T07:39:35.779045+00:00
Git commit SHA: cd7e8df399ec5d4b0b1c505c4584dc0d8867e4d5

Toplam gecerli (REJECTED disi) benzersiz arrival_event: 600

--- TRAIN ---
  Event sayisi: 418
  Zaman araligi: 2026-08-12 09:01:01.050421+00:00  ->  2026-08-16 13:52:39.942962+00:00
  Satir sayisi (eta_training_samples): 1109
  Hat bazinda satir: [('121', 287), ('515', 380), ('761', 442)]
  Label quality bazinda satir: [('SILVER', 1109)]

--- VALIDATION ---
  Event sayisi: 91
  Zaman araligi: 2026-08-14 12:45:37.680320+00:00  ->  2026-08-17 06:36:39.090627+00:00
  Satir sayisi (eta_training_samples): 1224
  Hat bazinda satir: [('121', 81), ('515', 65), ('761', 1078)]
  Label quality bazinda satir: [('SILVER', 1224)]

--- TEST ---
  Event sayisi: 91
  Zaman araligi: 2026-08-16 12:49:09.998901+00:00  ->  2026-08-17 07:15:27.139582+00:00
  Satir sayisi (eta_training_samples): 831
  Hat bazinda satir: [('121', 71), ('515', 749), ('761', 11)]
  Label quality bazinda satir: [('SILVER', 831)]

======================================================================
Split modu: HAT BAZINDA (--per-line): her hat kendi zaman ekseninde ayri ayri split edildi, sonra birlestirildi.
Not: Split arrival_event_id bazinda ve zamansal siralidir (erken -> train, gec -> test). Oranlar event sayisina gore hedeflendi, hicbir event bolunmedi. label_quality=REJECTED satirlar split disi birakildi (dataset_split=NULL).
======================================================================