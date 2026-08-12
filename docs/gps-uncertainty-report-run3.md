# GPS Belirsizligi Analiz Raporu (v2 - nokta/run bazli)

ingestion_run_id = 3, STALE_RUN_THRESHOLD = 3


Toplam arac/hat kombinasyonu: 12


## Arac Bazli Sonuclar

- Arac **11189** (Hat 121): 120 gozlem -> CURRENT=88, STALE=0, UNKNOWN=32
- Arac **11287** (Hat 121): 120 gozlem -> CURRENT=86, STALE=0, UNKNOWN=34
- Arac **11371** (Hat 761): 120 gozlem -> CURRENT=86, STALE=0, UNKNOWN=34
- Arac **11515** (Hat 515): 120 gozlem -> CURRENT=96, STALE=0, UNKNOWN=24
- Arac **11542** (Hat 515): 120 gozlem -> CURRENT=80, STALE=0, UNKNOWN=40
- Arac **11781** (Hat 121): 120 gozlem -> CURRENT=90, STALE=0, UNKNOWN=30
- Arac **11785** (Hat 515): 120 gozlem -> CURRENT=90, STALE=0, UNKNOWN=30
- Arac **11789** (Hat 121): 120 gozlem -> CURRENT=90, STALE=0, UNKNOWN=30
- Arac **12001** (Hat 515): 180 gozlem -> CURRENT=152, STALE=0, UNKNOWN=28
- Arac **2002** (Hat 515): 180 gozlem -> CURRENT=160, STALE=0, UNKNOWN=20
- Arac **2135** (Hat 515): 240 gozlem -> CURRENT=228, STALE=0, UNKNOWN=12
- Arac **9030** (Hat 761): 60 gozlem -> CURRENT=57, STALE=0, UNKNOWN=3
  - Uzun donuk blok: 3 gozlem, 2026-08-12 08:58:08.776277+00:00 -> 2026-08-12 09:00:08.090675+00:00 : UNKNOWN (dogrulanamadi)

## Genel Ozet (nokta bazli)

- CURRENT_POSITION: 1303
- STALE_POSITION: 0
- UNKNOWN_POSITION: 317

## Bilinen Sinirlamalar

- STALE_RUN_THRESHOLD=3 keyfi bir esik; 1-2 gozlemlik tekrarlar (trafik isigi vb. ile karistirilabilecegi icin) her zaman UNKNOWN olarak birakildi, STALE denmedi.
- Support API capraz dogrulamasi yalnizca 3 pilot durakta yaklasan araclar icin mumkun; bu disinda kalan uzun donuk bloklar STALE degil UNKNOWN kaliyor - bu, gercek stale orani muhtemelen raporlanandan yuksek demektir.
- 'Ilk nokta gunceldir' varsayimi yapilmadi; ilk run'in siniflandirmasi da diger run'larla ayni kurala tabi tutuldu.