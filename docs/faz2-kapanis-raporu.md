# Faz 2 Kapanis Raporu

ingestion_run_id = 3 (60 dakikalik gozlem, 12 arac, 3 pilot hat: 515, 121, 761)

## 1. GPS Belirsizligi Arastirmasi (madde 1)

Bkz. `docs/gps-uncertainty-report-run3.md` (v2, nokta/run bazli).

- Nokta bazli siniflandirma: CURRENT_POSITION=1303, STALE_POSITION=0,
  UNKNOWN_POSITION=317.
- STALE_POSITION=0 cikmasi kesin bir "hic donma yok" iddiasi degil;
  3+ ardisik tekrar bloklarinin buyuk cogunlugunda support API
  capraz dogrulamasi mumkun olmadigi icin (sadece 3 pilot durak
  takip ediliyor) bu bloklar UNKNOWN kaldi, STALE denilemedi.
- "Ilk nokta gunceldir" varsayimi hicbir yerde yapilmadi.

## 2. PostgreSQL/PostGIS Altyapisi (madde 2)

- Docker Compose + 6 migration dosyasi, tek komutla (`docker compose up -d`)
  temiz kurulum.
- Collector artik JSON dosyasi yerine dogrudan DB'ye yaziyor
  (raw_snapshots + vehicle_observations + supporting_api_observations).

## 3. Durak/Guzergah Import (madde 3)

- 11.783 durak, ESHOT CSV kaynagindan `stops` tablosuna aktarildi.
- 3 pilot hat icin 6 route (her hat 2 yon), `routes` + `route_shape_points`.
- Kaynak SHA-256 hash'i `data_sources` tablosunda tutuluyor.
- Not: kaynak URL'si tam dogrulanamadi (CSV'ler yerel diskte hazir
  geldi), source_url alaninda bu acikca belirtiliyor.

## 4. Map-Matching (madde 4)

Bkz. `docs/map-matching-findings.md`.

- 1560 gozlem map-matched (60 null-island `(0,0)` gozlem haric tutuldu).
- GOOD=699, DEGRADED=17, REJECTED=844.
- Yuksek REJECTED orani arastirildi: buyuk kismi GERCEK ama rota-disi
  arac konumlarindan kaynaklaniyor (orn. arac 2135, 60 dakikanin
  TAMAMI boyunca 515 guzergahina hic girmedi - muhtemelen o saatte
  sefer disi). Veri hatasi degil, sistem dogru davraniyor.

## 5. Durak Sirasi (madde 5)

- 6 route icin toplam ~700 durak sirlandi.
- 3 pilot ornek (Bahribaba/121, Halkapinar Metro/515, Yesil Yol/761)
  `manual_pilot_sample` olarak dogrulandi; hepsi route'a <35m mesafede
  ve iki yon arasinda tutarli/simetrik sira konumlarinda cikti.
- Geri kalan ~700 durak `spatial_only` olarak isaretli - bu ayrim
  bilerek acikca tutuluyor (madde 5 geregi).

## 6. Arrival Event V1 (madde 6)

- 232 arrival event uretildi (4 sartin hepsi birlikte: dogru hat/yon,
  yaklasma, yakinlik <=50m, sonrasina ilerleme).
- Ilk versiyonda bir mantik hatasi bulundu ve duzeltildi: support API
  capraz dogrulamasi baslangicta target_stop_id kontrolu yapmiyordu,
  bu da yanlis duraga ait "kanit"in baska bir durak icin HIGH confidence
  uretmesine sebep oluyordu. Duzeltme sonrasi 232 event'in TAMAMI
  MEDIUM confidence (gps_only) cikti - HIC HIGH yok.
- Bunun sebebi: support API'nin dar zaman penceresinde (yaklasma-gecis
  arasi genelde 1-3 dk) genelde <2 gozlem yakalanabiliyor, trend
  kurmak icin yetersiz. Bu, madde 8'in dogal bir sinirlamasi olarak
  raporlaniyor.
- `arrival_observed_at` +-60sn (collector interval) belirsizlik payi
  tasiyor, acikca dokumante edildi.

## 7. ETA Training Samples (madde 7)

- 94 eta_training_samples uretildi, 0 future-leakage riski (T0 her
  zaman T1'den once, DB constraint + uygulama kontrolu ikisi de var).
- label_quality dagilimi: buyuk cogunlugu SILVER (MEDIUM confidence
  arrival event'lerden), GOLD orneği yok (yukaridaki HIGH confidence
  eksikligi nedeniyle).

## 8. Support API Capraz Dogrulama (madde 8)

- Ayri response'lardaki farkli araclarin degerleri asla zaman serisi
  kaniti olarak kullanilmadi; sadece AYNI vehicle_id + AYNI target_stop_id
  zaman serisi kontrol edildi.
- Pratikte, dar zaman pencereleri nedeniyle bu capraz dogrulama az
  sayida HIGH confidence event uretti (sifir, bu run'da) - bu bir
  basarisizlik degil, dogru/muhafazakar bir tasarim tercihinin sonucu.

## 9. Baseline ETA (madde 9)

| Baseline | n | MAE | RMSE | +-2dk dogruluk |
|---|---|---|---|---|
| 1: mesafe/hiz | 41 | 7.82 dk | 23.41 dk | %87.8 |
| 2: segment medyani | 94 | 0.06 dk | 0.18 dk | %100.0 |

**ONEMLI UYARI - Baseline 2 sonucu GUVENILMEZ:** Segment basina ornek
sayisi cogunlukla n=1 veya n=2 (94 orneklik kucuk veri setinde ~700
segment var). Medyan hesabi leave-one-out YAPMADIGI icin, cogu
durumda model kendi test degerini (ya da ona cok yakin bir degeri)
"tahmin" olarak geri veriyor - bu bir basari degil, veri sizintisina
yakin bir olcum artefaktidir. Sonuc SAKLANMADI/DEGISTIRILMEDI, ama
gecerli bir baseline performansi olarak YORUMLANMAMALI.

Baseline 1 (mesafe/hiz) daha durust bir sinyal veriyor: MAE (7.82dk)
ile RMSE (23.41dk) arasindaki buyuk fark, birkac asiri sapmali
ornegin istatistikleri cektigini gosteriyor; buna ragmen orneklerin
%87.8'i +-2dk icinde - cogunluk makul, birkac tanesi cok kotu.

## Kalite Kapisi Degerlendirmesi

Faz 2 kabul kriterlerinin cogu karsilandi (DB calisiyor, collector
yaziyor, pilot hat verisi hazir, GPS-route eslesebiliyor, coklu
koordinat arastirildi, support API capraz dogrulama altyapisi calisiyor,
arrival event ve eta_training_samples uretilebiliyor). Ancak veri
hacmi (60dk/12 arac) Faz 3'teki gercek model egitimi icin YETERSIZ -
bu, sonraki adim icin daha uzun/genis bir veri toplama turunun
gerekli oldugunu gosteriyor.
