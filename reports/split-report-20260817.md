======================================================================
FAZ 3 TRAIN/VALIDATION/TEST SPLIT RAPORU
======================================================================

Olusturulma zamani (UTC): 2026-08-17T06:21:55.628765+00:00
Git commit SHA: cd7e8df399ec5d4b0b1c505c4584dc0d8867e4d5

Toplam gecerli (REJECTED disi) benzersiz arrival_event: 591

--- TRAIN ---
  Event sayisi: 413
  Zaman araligi: 2026-08-12 09:01:01.050421+00:00  ->  2026-08-14 12:46:48.479823+00:00
  Satir sayisi (eta_training_samples): 713
  Hat bazinda satir: [('121', 290), ('515', 384), ('761', 39)]
  Label quality bazinda satir: [('SILVER', 713)]

--- VALIDATION ---
  Event sayisi: 89
  Zaman araligi: 2026-08-14 12:46:49.697613+00:00  ->  2026-08-16 13:20:32.843993+00:00
  Satir sayisi (eta_training_samples): 154
  Hat bazinda satir: [('121', 86), ('515', 63), ('761', 5)]
  Label quality bazinda satir: [('SILVER', 154)]

--- TEST ---
  Event sayisi: 89
  Zaman araligi: 2026-08-16 13:22:36.339854+00:00  ->  2026-08-16 20:34:32.179678+00:00
  Satir sayisi (eta_training_samples): 2285
  Hat bazinda satir: [('121', 63), ('515', 747), ('761', 1475)]
  Label quality bazinda satir: [('SILVER', 2285)]

======================================================================
Not: Split arrival_event_id bazinda ve zamansal siralidir (erken -> train, gec -> test). Oranlar event sayisina gore hedeflendi, hicbir event bolunmedi. label_quality=REJECTED satirlar split disi birakildi (dataset_split=NULL).
======================================================================