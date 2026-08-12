# Map-Matching Bulgulari (Madde 4)

ingestion_run_id = 3 (60 dakikalik gozlem, 12 arac, 3 pilot hat)

## Esikler

- GOOD: distance_to_route_m <= 30
- DEGRADED: 30 < distance_to_route_m <= 100
- REJECTED: distance_to_route_m > 100

## Sonuclar (ilk calistirma, (0,0) duzeltmesi sonrasi)

| Hat | GOOD | DEGRADED | REJECTED |
|---|---|---|---|
| 121 | ~240 | 0 | ~240 |
| 515 | ~339 | 17 | ~604 |
| 761 | 120 | 0 | 0 |

## Onemli Bulgular

### 1. (0,0) "Null Island" Sentinel Degeri
Arac 11371 (Hat 761) icin bir gozlemde raw_lat=0, raw_lon=0 tespit edildi.
Bu, API'nin gercek konum uretemedigi durumlarda dondugu bilinen bir hata
degeri. Map-matching'den once bu degerler artik ayri tespit edilip
haric tutuluyor (collector seviyesinde de UNKNOWN_POSITION olarak
isaretleniyor, bkz. db_storage.save_vehicle_observations).

### 2. Rota Disi Araclar (asil REJECTED kaynagi)
515 ve 121 hatlarindaki yuksek REJECTED oraninin sebebi hatali veri
DEGIL. Ornek: arac 2135 (Hat 515), 60 dakikalik gozlem penceresinin
TAMAMI boyunca (08:58-09:57) sabit ~9641m mesafede, hicbir zaman
515'in güzergahina girmedi. Koordinat tutarli ve gercek gorunuyor -
yorum: arac o saat araliginda 515 seferinde degildi (garajda, farkli
gorevde, ya da arizali olabilir). Benzer sekilde 11785 (515) ve 11789
(121) neredeyse ayni koordinatta (~38.484, 27.069) sabit duruyor - bu
nokta muhtemelen ortak bir terminal/garaj alani.

**Sonuc:** Sistem bu durumlarda dogru davraniyor - rota disi ama gercek
konumlari REJECTED olarak isaretliyor, sessizce rotaya yapistirmiyor.
Yuksek REJECTED orani veri kalitesi sorunu degil, "arac o an aktif
seferde degildi" gercegini yansitiyor.

## Sonraki Adimlar / Oneriler

- REJECTED gozlemler, downstream ETA training/arrival detection
  mantiginda otomatik olarak elenmeli (zaten arrival_events ve
  eta_training_samples GOOD/DEGRADED kaliteli map-match bekliyor).
- Ileride "arac aktif seferde mi" bilgisini ayri tutmak (orn. bir
  route_id'ye XX dakika REJECTED kalan araclar icin
  IN_SERVICE/OUT_OF_SERVICE gibi bir durum alani) faydali olabilir,
  ama bu Faz 2 kapsaminin disinda - not olarak birakiliyor.
