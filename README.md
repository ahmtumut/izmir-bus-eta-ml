# Izmir Otobus Varis Suresi Tahmin ve Anlik Konum Analiz Sistemi

## Proje Amaci
ESHOT otobuslerine ait anlik konum verilerini duzenli olarak toplayarak
tarihsel bir hareket veri seti olusturmak; ilerleyen fazlarda bu veriden
otobuslerin belirli duraklara gercek varis surelerini (ETA) tahmin eden
bir makine ogrenmesi modeli gelistirmek; ayni zamanda GPS/veri kalitesi
problemlerini tespit edebilen bir analiz altyapisi olusturmak.

## Kullanilan API'ler
- Ana API: `GET /api/iztek/hatotobuskonumlari/{hatId}`
- Destek API: `GET /api/iztek/hattinyaklasanotobusleri/{hatId}/{durakId}`
- Destek API: `GET /api/iztek/duragayaklasanotobusler/{durakId}`

Base URL: `https://openapi.izmir.bel.tr`

## Pilot Hatlar
515 (kisa/yogun sehir ici), 121 (orta mesafe), 761 (uzun guzergah).
Secim gerekcesi: `docs/pilot-lines.md`

## Kurulum
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Proje Yapisi
```
app/
  collectors/    - API'den veri toplama, hata yonetimi
  validation/    - veri kalite kontrolleri
  storage/       - ham/normalize veri kaydetme
  schemas/       - veri modelleri
  trajectory/    - hareket metrikleri, trajectory olusturma

data/
  raw/           - ham API response'lari + ingestion log (git'e girmez)
  processed/     - normalize edilmis veri, hareket metrikleri, trajectory'ler (git'e girmez)

docs/            - Faz 1 dokumanlari (asagida detay)
notebooks/       - EDA notebook
scripts/         - calistirma noktalari
tests/           - unit testler (mock/fixture, gercek API cagrisi yok)
```

## Calistirma

**Collector'i baslat** (surekli calisir, Ctrl+C ile durur):
```powershell
python scripts\run_collector.py
```

**Hareket metriklerini hesapla:**
```powershell
python scripts\compute_movement_metrics.py
```

**Stale (hareketsiz arac) tespiti:**
```powershell
python scripts\detect_stale_positions.py
```

**Trajectory'leri olustur:**
```powershell
python app\trajectory\trajectory_builder.py
```

**Testleri calistir:**
```powershell
python -m pytest tests/ -v
```

**EDA notebook:**
```powershell
jupyter notebook notebooks/eda.ipynb
```

## Faz 1 Dokumanlari

| Dokuman | Icerik |
|---|---|
| `docs/api-freshness-report.md` | API canlilik dogrulamasi, 60 dk freshness testi sonuclari |
| `docs/data-dictionary.md` | Ana + destekleyici API'lerin gercek semasi |
| `docs/problem-definition.md` | ML problem tanimi, ETA/ground-truth stratejisi |
| `docs/pilot-lines.md` | Pilot hat secim gerekcesi |
| `docs/known-risks.md` | Tespit edilen teknik riskler ve cozulmemis sorular |
| `docs/architecture-draft.md` | Sistem mimarisi, veri akisi |
| `docs/data-quality-rules.md` | Uygulanan kalite kontrolleri ve esikler |

## Onemli Teknik Bulgular (ozet, detay docs/known-risks.md'de)

- API'de dokumante edilmemis bir rate limit var (~3 saniyede 1 istek guvenli)
- Koordinatlar virgullu ondalik string olarak geliyor (`"38,46"`)
- Ayni response icinde ayni arac ID'si farkli koordinatlarla birden
  fazla kez donebiliyor (trail noktalari) - bu davranisin tam nedeni
  henuz netlesmedi
- API'de zaman/timestamp alani yok, tum zaman bilgisi client-side uretiliyor

## Durum

Faz 1 buyuk olcude tamamlandi. Devam eden: destekleyici API
sistematik karsilastirmasi (gorev madde 10), 24 saatlik ana veri
toplama kosusu.
