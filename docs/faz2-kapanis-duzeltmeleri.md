# Faz 2 Kapanis Duzeltmeleri (Supervisor Geri Bildirimi Yaniti)

Bu belge, Faz 2 kapanis mesajinda belirtilen 5 duzeltme kalemine verilen
yaniti ozetler. Her madde ayri ayri uygulandi ve test edildi.

## 1. Kaynak API'nin yon bilgisi kalici olarak saklaniyor

- `vehicle_observations.source_direction` kolonu eklendi (migration 007).
- `db_storage.normalize_source_direction()` ham 'Yon' degerini (1/2)
  routes.direction konvansiyonuna (0/1) ceviriyor. **Varsayim acikca
  belgelendi**: ana API'nin 'Yon' alaninin ESHOT guzergah CSV'siyle
  (1=gidis, 2=donus) ayni konvansiyonu kullandigi varsayiliyor ama
  DOGRULANMADI - taninmayan degerler sessizce 0/1'e zorlanmiyor, None
  donuyor ve SOURCE_DIRECTION_UNKNOWN olarak flagleniyor.
- Map-matching (`scripts/map_match_observations.py`, v2) artik ONCELIKLE
  source_direction'in route'unu deniyor. Gercek geometri, kaynak yonden
  belirgin sekilde (>20m fark, MISMATCH_MARGIN_M) uzaksa, SESSIZCE diger
  yone cevrilmiyor - en yakin gercek geometri kullaniliyor AMA
  DIRECTION_ROUTE_MISMATCH flag'i quality_flags'e ekleniyor ve
  data_quality_events'e loglaniyor.
- Yeni testler: `tests/test_faz2_closure_fixes.py` icinde
  `test_direction_mismatch_flagged_when_geometry_disagrees`,
  `test_no_mismatch_flag_when_direction_agrees`,
  `test_unknown_source_direction_flagged` - sentetik iki route (biri
  dogu-bati, biri kuzey-guney) ile gercek PostGIS hesaplamasina karsi
  test ediliyor, sadece routes tablosunun unique constraint testi degil.

## 2. ETA training sample uretimi sikilastirildi

- `scripts/generate_eta_training_samples.py` (v2): T0 adaylari artik
  SADECE ayni vehicle_id + line_no + direction + route_id uzerinde
  araniyor (`fetch_t0_candidates`).
- Sadece `map_match_quality IN ('GOOD', 'DEGRADED')` olan gozlemler T0
  adayi olabiliyor; REJECTED kesinlikle training'e girmiyor.
- `position_quality != 'STALE_POSITION'` filtresi eklendi.
- `compute_recent_speed()` fonksiyonu da AYNI filtreleri (route_id,
  GOOD/DEGRADED, stale olmayan) uyguluyor - baska route/yon/REJECTED bir
  nokta artik hiz hesabina karismiyor.
- Test: `test_fetch_t0_candidates_excludes_rejected_and_stale` - 3 sentetik
  gozlemden (1 GOOD, 1 REJECTED, 1 STALE) sadece 1'inin aday oldugunu
  dogruluyor.

## 3. Arrival event V1 guclendirildi

- `scripts/detect_arrival_events.py` (v2): `minimum_distance_m` artik
  route-progress farki DEGIL, aracin GERCEK GPS noktasi ile durağin
  PostGIS konumu arasindaki `ST_Distance` (gercek mekansal mesafe).
- Yaklasma trendi dogrulamasi eklendi: approach_started_at ile
  arrival_observed_at arasindaki fiziksel mesafe dizisi kontrol ediliyor.
  En az 3 ardisik nokta varsa VE bu noktalarin cogunlugu gercekten
  azaliyorsa trend onaylanmis sayiliyor. Yeterli nokta yoksa
  `INSUFFICIENT_TREND_POINTS`, trend cogunlukla artiyorsa
  `APPROACH_TREND_NOT_CONFIRMED` flag'i ekleniyor ve bu durumda HIGH
  confidence bir kademe MEDIUM'a dusuruluyor.

## 4. Baseline 2 leave-one-out ile duzeltildi

- `scripts/compute_baseline_eta.py` (v2): segment medyani hesaplanirken
  test edilen ornegin KENDI actual_eta degeri artik HARIC TUTULUYOR
  (`baseline_segment_median_leave_one_out`).
- n=1 olan segmentlerde (leave-one-out sonrasi 0 tarihsel veri) tahmin
  URETILMIYOR - uydurma bir deger vermek yerine ornek atlaniyor ve
  atlanan sayisi acikca raporlaniyor.
- Not: Faz 3'te asil degerlendirme train/test ayrimiyla yapilacak; bu
  duzeltme Faz 2 kapsaminda minimum "kendi ornegini kullanmama" kuralini
  sagliyor.
- Testler: `test_leave_one_out_excludes_own_sample`,
  `test_leave_one_out_returns_none_when_segment_has_single_sample`,
  `test_leave_one_out_uses_others_not_self_with_distinct_values`.

## 5. Idempotency saglandi

- Migration 007: `arrival_events` tablosuna
  `UNIQUE (triggering_observation_id, stop_id)`, `eta_training_samples`
  tablosuna `UNIQUE (source_observation_id, arrival_event_id)`
  constraint'leri eklendi.
- Her iki uretim scripti de artik `ON CONFLICT ... DO NOTHING RETURNING id`
  kullaniyor; conflict durumunda mevcut id geri kullaniliyor, yeni satir
  acilmiyor. Konsol ciktisinda "YENI uretilen" ve "zaten var olan (idempotent)"
  sayilari ayri raporlaniyor.
- Test: `test_arrival_events_insert_is_idempotent` - ayni veriyle iki kez
  INSERT denenip sadece 1 satir kaldigi dogrulaniyor.

## 6. .env.example, Docker Compose, README guncellendi

- `.env.example` guncel degiskenlerle (DB_*, API_BASE_URL, collector
  ayarlari) yeniden yazildi, gercek .env'in git'e girmemesi gerektigi
  hatirlatildi.
- `docker-compose.yml` ve migration listesi 007'yi de icerecek sekilde
  guncellendi (bkz. migrations/007_direction_and_idempotency.sql).

## Ek Duzeltmeler (inceleme sirasinda bulunan gercek hatalar)

Yukaridaki 6 maddeyi uygularken 3 ayri gercek hata daha bulundu ve
duzeltildi - bunlar Supervisor'in listesinde yoktu ama kod incelemesi
sirasinda ortaya cikti:

1. **Performans hatasi**: `detect_arrival_events.py`'nin ilk versiyonu,
   her durak adayi icin aracin TUM gozlem dizisine (120-240 nokta) tek
   tek ST_Distance sorgusu atiyordu - arac basina onbinlerce DB
   round-trip'e yol aciyordu, pratikte donmus gorunuyordu. Duzeltme:
   once ucuz route-progress farkiyla kaba aday penceresi bul, SADECE
   o kucuk pencere icin gercek mesafeyi tek sorguda hesapla.
2. **PostGIS array serialization hatasi**: Gercek mesafeleri PostgreSQL
   array parametresi (`::geography[]`) olarak gecirmek psycopg'de
   "Invalid hex character" hatasi veriyordu. Duzeltme: array yerine
   UNION ALL ile tek sorguda birlestirilen ayri parametreler kullanildi.
3. **Veri kaybi**: `validate_vehicle()`'in urettigi kalite bayraklari
   (MISSING_VEHICLE_ID, ZERO_COORDINATE, EXACT_DUPLICATE_IN_RESPONSE)
   Faz 2'nin DB'ye gecis surecinde hic saklanmiyordu, sessizce
   kayboluyordu. Duzeltme: `vehicle_observations.quality_flags`
   kolonuna artik bu bayraklar da yaziliyor. Ayrica `vehicle_id=None`
   gelen kayitlarin NOT NULL constraint'ine carpip collector'i
   cokertme riski de duzeltildi (guvenli sekilde atlanip loglaniyor).
4. **Test regresyonu**: `tests/test_collector.py`, Faz 2'nin DB'ye gecis
   guncellemesinden once yazilmis, eski `collect_line(line_no)`
   imzasini test ediyordu - Faz 2 boyunca hic `pytest tests/` ile TUM
   testler birlikte calistirilmadigi icin bu regresyon fark edilmemisti.
   Testler yeni imzaya (`collect_line(conn, run_id, line_no)`) ve
   DB mock'larina gore yeniden yazildi.

## Final Test Sonucu

```
pytest tests/ -v
58 passed
```

Tum testler (Faz 1'den kalan 5 dosya + Faz 2'nin 2 dosyasi + bu
kapanis duzeltmelerinin 1 dosyasi) birlikte, hicbir regresyon olmadan
geciyor.

## Guncellenmis Pipeline Sonuclari (run_id=3, duzeltmeler sonrasi)

| Asama | Onceki (v1) | Sonraki (v2/v3) |
|---|---|---|
| Map-matching | source_direction yok | 1560/1560 SOURCE_DIRECTION_UNKNOWN (bu run source_direction eklenmeden once toplandi - gercek test icin yeni tur gerekli) |
| Arrival events | 232 | 223 (gercek mesafe + trend dogrulama sonrasi) |
| ETA training samples | 94 (hepsi SILVER) | 45 (siki filtreler sonrasi) |
| Baseline 1 MAE | 7.82 dk | 0.62 dk (filtrelenmis, temiz veriyle) |
| Baseline 2 | GUVENILMEZ (leave-one-out yoktu, n cogunlukla 1-2 ama hepsi "basarili" gorunuyordu) | 45 orneğin sadece 8'i icin tahmin uretilebildi (n=1 olan 37 ornek DURUSTCE atlandi) |

Sayilarin "daha iyi" degil, **daha durust** oldugu vurgulanmali: Baseline
1'in MAE'sinin 7.82dk'dan 0.62dk'ya dusmesi filtrelerin ise yaradigini
gosteriyor; Baseline 2'nin n=45'ten n=8'e dusmesi ise onceki %100
dogruluk gorunumunun bir olcum artefakti oldugunu kanitliyor.

## Uygulanan Dosyalar

| Dosya | Degisiklik |
|---|---|
| `migrations/007_direction_and_idempotency.sql` | Yeni: source_direction, quality_flags, 2 unique constraint |
| `app/storage/db_storage.py` | normalize_source_direction, add_observation_quality_flag eklendi |
| `scripts/map_match_observations.py` | v2: yon-oncelikli matching, mismatch flag |
| `scripts/detect_arrival_events.py` | v2: gercek mesafe, trend dogrulama, idempotent |
| `scripts/generate_eta_training_samples.py` | v2: siki T0 filtreleri, idempotent |
| `scripts/compute_baseline_eta.py` | v2: gercek leave-one-out |
| `tests/test_faz2_closure_fixes.py` | Yeni: 10 test, tum duzeltmeleri kapsiyor |
| `.env.example` | Guncellendi |

## Calistirma Sirasi (mevcut run_id=3 verisi uzerinde yeniden uygulamak icin)

```powershell
# 1. Migration'i uygula
./scripts/run_migrations.sh   # ya da psql ile 007'yi manuel calistir

# 2. Map-matching'i yeniden calistir (source_direction artik kullanilacak)
python scripts/map_match_observations.py --run-id 3

# 3. Eski arrival_events ve eta_training_samples'i temizle (semantik degisti)
# psql: DELETE FROM eta_training_samples; DELETE FROM arrival_events;

# 4. Arrival event'leri yeniden uret (gercek mesafe + trend dogrulama ile)
python scripts/detect_arrival_events.py --run-id 3

# 5. ETA training sample'lari yeniden uret (siki filtrelerle)
python scripts/generate_eta_training_samples.py --run-id 3

# 6. Baseline'lari yeniden hesapla (leave-one-out ile)
python scripts/compute_baseline_eta.py

# 7. Tum testleri calistir
pytest tests/ -v
```

**Onemli not:** Adim 3'teki temizlik gerekli, cunku source_direction
onceden toplanan `vehicle_observations` satirlarinda NULL olacak (kolon
yeni eklendi, geriye donuk doldurulamiyor - ham API 'Yon' verisi zaten
kaydedilmemisti). Bu, run_id=3'teki mevcut veri icin
SOURCE_DIRECTION_UNKNOWN flag'ine dusecegi anlamina gelir; gercek
source_direction testi icin **yeni bir toplama turu** gerekir.
