======================================================================
FAZ 3 TRAIN/VALIDATION/TEST SPLIT RAPORU
======================================================================

Olusturulma zamani (UTC): 2026-08-17T08:29:21.607404+00:00
Git commit SHA: cd7e8df399ec5d4b0b1c505c4584dc0d8867e4d5

Toplam gecerli (REJECTED disi) benzersiz arrival_event: 1792

--- TRAIN ---
  Event sayisi: 1254
  Zaman araligi: 2026-08-12 08:59:01.049553+00:00  ->  2026-08-14 12:42:02.967115+00:00
  Satir sayisi (eta_training_samples): 9891
  Hat bazinda satir: [('121', 2795), ('515', 6414), ('761', 682)]
  Label quality bazinda satir: [('GOLD', 236), ('SILVER', 9655)]

--- VALIDATION ---
  Event sayisi: 268
  Zaman araligi: 2026-08-14 12:22:48.435352+00:00  ->  2026-08-17 06:42:03.102076+00:00
  Satir sayisi (eta_training_samples): 3060
  Hat bazinda satir: [('121', 866), ('515', 2028), ('761', 166)]
  Label quality bazinda satir: [('GOLD', 91), ('SILVER', 2969)]

--- TEST ---
  Event sayisi: 270
  Zaman araligi: 2026-08-16 11:52:27.227244+00:00  ->  2026-08-17 07:32:39.161642+00:00
  Satir sayisi (eta_training_samples): 2474
  Hat bazinda satir: [('121', 673), ('515', 1629), ('761', 172)]
  Label quality bazinda satir: [('GOLD', 84), ('SILVER', 2390)]

======================================================================
Split modu: HAT BAZINDA (--per-line): her hat kendi zaman ekseninde ayri ayri split edildi, sonra birlestirildi.
Not: Split arrival_event_id bazinda ve zamansal siralidir (erken -> train, gec -> test). Oranlar event sayisina gore hedeflendi, hicbir event bolunmedi. label_quality=REJECTED satirlar split disi birakildi (dataset_split=NULL).
======================================================================