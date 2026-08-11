# Mimari Taslak

## Genel Akis

```
İzmir Açık Veri API
(hatotobuskonumlari)
        |
        v
app/collectors/bus_location_collector.py
  - HTTP istegi atar (hat basina, rate-limit'e uyumlu araliklarla)
  - Hata yonetimi: timeout, 429, 5xx, bozuk JSON, bilinmeyen sema
        |
        v
  +-----+-----+
  |           |
  v           v
Ham veri     Normalize + Validate
(data/raw)   app/validation/quality.py
             - koordinat parse (virgul->nokta)
             - sinir kontrolu (Izmir bbox)
             - duplicate tespiti (ayni ID + ayni koordinat)
             - is_valid + quality_flags
                    |
                    v
             data/processed/normalized_positions.csv
                    |
        +-----------+-----------+
        |           |           |
        v           v           v
  Trajectory   Hareket       Stale
  builder      metrikleri    detection
  (madde 7)    (madde 9)     (madde 8)
        |           |           |
        v           v           v
  data/processed/trajectories/   movement_metrics.csv   stale_report.csv
```

## Katman Sorumluluklari

| Katman | Sorumluluk | Dosya |
|---|---|---|
| Collector | API cagrisi, hata yonetimi, orkestrasyon | `app/collectors/bus_location_collector.py` |
| Schema | Veri modelleri (normalize edilmis kayit tanimi) | `app/schemas/vehicle.py` |
| Validation | Kalite kontrolleri, koordinat parse, duplicate tespiti | `app/validation/quality.py` |
| Storage | Diske yazma (ham + normalize + log) | `app/storage/raw_storage.py` |
| Trajectory | Zaman sirali arac hareketi + hareket metrikleri | `app/trajectory/` |

## Veri Akisi Ilkeleri

1. **Ham veri hicbir zaman degistirilmez.** `data/raw/` altinda API'den
   gelen response oldugu gibi saklanir.
2. **Supheli veri silinmez, isaretlenir.** `is_valid=False` +
   `quality_flags` ile. Filtreleme, kullanim aninda (analiz/model
   asamasinda) yapilir.
3. **Hata toleransli calisma.** Bir hattaki hata (429, timeout, 5xx),
   diger hatlarin sorgulanmasini veya collector'in genel calismasini
   durdurmaz.
4. **Restart-safe.** Tum loglar (`ingestion_log.csv`,
   `normalized_positions.csv`) append-only oldugu icin, collector
   yeniden baslatildiginda veri kaybi olmadan kaldigi yerden devam
   eder. Bu, 10-11 Agustos arasi gerceklesen bir restart sirasinda
   fiilen dogrulandi (bkz. trajectory index'teki zaman bosluklari).
5. **Turetilmis veri (movement metrics, stale report, trajectory)
   ayri dosyalarda, normalize veriden bagimsiz olarak yeniden
   uretilebilir** - yani bu scriptler istenildigi zaman tekrar
   calistirilip guncellenebilir, veri kaybi riski yok.

## Bilinen Mimari Sinirlar

- Trail-nokta belirsizligi (bkz. `docs/known-risks.md` madde 4) -
  su an her response'tan tek nokta aliniyor, potansiyel ek bilgi
  gozardi ediliyor.
- Collector tek process, tek makinede calisiyor - olcek/paralel
  calisma Faz 2'nin kapsami disinda.
- PostgreSQL/PostGIS entegrasyonu henuz yok - Faz 1 tamamen dosya
  tabanli (CSV/JSON) calisiyor, Faz 2'de veritabanina tasinacak.
