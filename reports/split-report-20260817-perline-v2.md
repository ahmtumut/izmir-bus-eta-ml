======================================================================
FAZ 3 TRAIN/VALIDATION/TEST SPLIT RAPORU
======================================================================

Olusturulma zamani (UTC): 2026-08-17T07:43:57.282142+00:00
Git commit SHA: cd7e8df399ec5d4b0b1c505c4584dc0d8867e4d5

Toplam gecerli (REJECTED disi) benzersiz arrival_event: 575

--- TRAIN ---
  Event sayisi: 401
  Zaman araligi: 2026-08-12 09:01:01.050421+00:00  ->  2026-08-16 12:55:47.382539+00:00
  Satir sayisi (eta_training_samples): 577
  Hat bazinda satir: [('121', 223), ('515', 317), ('761', 37)]
  Label quality bazinda satir: [('SILVER', 577)]

--- VALIDATION ---
  Event sayisi: 86
  Zaman araligi: 2026-08-14 12:43:12.472840+00:00  ->  2026-08-17 06:38:27.094131+00:00
  Satir sayisi (eta_training_samples): 174
  Hat bazinda satir: [('121', 33), ('515', 63), ('761', 78)]
  Label quality bazinda satir: [('SILVER', 174)]

--- TEST ---
  Event sayisi: 88
  Zaman araligi: 2026-08-16 13:07:36.345522+00:00  ->  2026-08-17 07:15:27.139582+00:00
  Satir sayisi (eta_training_samples): 145
  Hat bazinda satir: [('121', 70), ('515', 67), ('761', 8)]
  Label quality bazinda satir: [('SILVER', 145)]

======================================================================
Split modu: HAT BAZINDA (--per-line): her hat kendi zaman ekseninde ayri ayri split edildi, sonra birlestirildi.
Not: Split arrival_event_id bazinda ve zamansal siralidir (erken -> train, gec -> test). Oranlar event sayisina gore hedeflendi, hicbir event bolunmedi. label_quality=REJECTED satirlar split disi birakildi (dataset_split=NULL).
======================================================================