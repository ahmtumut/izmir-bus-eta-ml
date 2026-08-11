# Veri Kalite Kurallari

Bu belge, `app/validation/quality.py` ve `app/trajectory/` icinde
uygulanan tum veri kalite kontrollerini tek yerde toplar. Gorev
madde 8 ve 9'un ozeti niteligindedir.

## Ilke

Supheli veri **silinmez**. `is_valid=False` ve `quality_flags` ile
isaretlenir, ham veri (`data/raw/`) hicbir zaman degistirilmez.
Filtreleme, kullanim aninda (analiz/model asamasinda) yapilir.

## Uygulanan Kontroller

| Kontrol | Flag | Aciklama | Kaynak |
|---|---|---|---|
| Eksik arac ID | `MISSING_VEHICLE_ID` | `OtobusId` alani None/eksik | `quality.py::validate_vehicle` |
| Koordinat parse hatasi | `COORDINATE_PARSE_ERROR` | Virgul->nokta donusumu sonrasi float'a cevrilemeyen deger | `quality.py::parse_koor` |
| Sifir koordinat | `ZERO_COORDINATE` | `KoorX`/`KoorY` = "0" (GPS fix yok isareti) | `quality.py::validate_vehicle` |
| Enlem sinir disi | `LATITUDE_OUT_OF_RANGE` | 38.0-38.9 disinda | `quality.py::validate_vehicle` |
| Boylam sinir disi | `LONGITUDE_OUT_OF_RANGE` | 26.5-27.5 disinda | `quality.py::validate_vehicle` |
| Gercek duplicate | `EXACT_DUPLICATE_IN_RESPONSE` | Ayni ID + ayni (lat,lon) response icinde tekrar ediyor | `quality.py::detect_duplicate_ids` |
| Gercekci olmayan hiz | `is_unrealistic_speed=True` | Hesaplanan hiz > 90 km/h | `movement_metrics.py` |
| Uzun sure hareketsizlik | (ayri rapor, flag degil) | 3+ ardisik ayni koordinat | `detect_stale_positions.py` |

## Esikler ve Gerekceleri

| Parametre | Deger | Gerekce |
|---|---|---|
| `IZMIR_LAT_MIN/MAX` | 38.0 - 38.9 | Izmir ili yaklasik enlem araligi, marj birakildi |
| `IZMIR_LON_MIN/MAX` | 26.5 - 27.5 | Izmir ili yaklasik boylam araligi |
| `MAX_REALISTIC_SPEED_KMH` | 90.0 | Sehir ici otobus icin ust sinir, otoyol segmentlerini de kapsayacak sekilde genis tutuldu |
| `MIN_ELAPSED_SECONDS_FOR_SPEED` | 1.0 | Bu esigin altinda hiz hesaplamasi anlamsiz/asiri hassas olabilir |
| `STALE_THRESHOLD_DEGREES` | 0.0001 (~11m) | Bu mesafenin altindaki fark "hareketsiz" sayilir |
| `MIN_CONSECUTIVE_FOR_STALE` | 3 | 3+ ardisik ayni konum "stale" olarak raporlanir |

## Bilinen Sinirlar (bkz. docs/known-risks.md icin detay)

- Trail-nokta belirsizligi nedeniyle, hareket metrigi ve stale
  detection hesaplamalarinda her response'tan sadece **ilk nokta**
  temsilci olarak kullaniliyor - diger trail noktalari gozardi
  ediliyor.
- Kaynak zaman damgasi (`source_timestamp`) API'de olmadigi icin
  tum zaman bazli kontroller (`observed_at` ilerliyor mu, geriye
  gidiyor mu) bizim client-side `request_time` kaydimiza dayaniyor,
  API'nin gercek veri uretim zamanini yansitmiyor olabilir.
