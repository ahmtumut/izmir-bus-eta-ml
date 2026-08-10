# Izmir Otobus Varis Suresi Tahmin ve Anlik Konum Analiz Sistemi

## Proje Amaci
ESHOT otobuslerine ait anlik konum verilerini duzenli olarak toplayarak
tarihsel bir hareket veri seti olusturmak; ilerleyen fazlarda bu veriden
otobuslerin belirli duraklara gercek varis surelerini (ETA) tahmin eden
bir makine ogrenmesi modeli gelistirmek.

## Faz 1 Kapsami
Veri kaynagi dogrulama ve anlik konum veri toplama altyapisi.
Detaylar icin: `docs/problem-definition.md`

## Kullanilan API'ler
- Ana API: `GET /api/iztek/hatotobuskonumlari/{hatId}`
- Destek API: `GET /api/iztek/hattinyaklasanotobusleri/{hatId}/{durakId}`
- Destek API: `GET /api/iztek/duragayaklasanotobusler/{durakId}`

Base URL: `https://openapi.izmir.bel.tr`

## Kurulum
```
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Durum
Faz 1 devam ediyor.
