# Veri Toplama Ozeti

## Kapsam

- **Baslangic:** 2026-08-10 12:32:26 UTC
- **Bitis:** 2026-08-11 13:59:37 UTC
- **Toplam sure:** ~25.5 saat (araya 1 saatlik planli internet
  kesintisi/mola girdi, collector durdurulup ayni gun tekrar
  baslatildi - veri kaybi olmadan devam etti, restart-safe
  tasarimin fiili dogrulamasi)
- Ahmet (supervisor) onayiyla 24 saatlik minimum kabul kriteri
  bu kosuyla karsilanmis kabul edildi.

## Hat Bazinda Sorgu Sayisi

| Hat | Sorgu sayisi | Sonuc |
|---|---|---|
| 515 | 356 | 356/356 OK |
| 121 | 355 | 355/355 OK |
| 761 | 355 | 355/355 OK |

**API hata/timeout sayisi: 0 / 1066 (%0.0)** - kosu boyunca hicbir
baglanti hatasi, timeout, rate limit veya sema hatasi yasanmadi.

## Hat Bazinda Benzersiz Arac Sayisi

| Hat | Benzersiz arac |
|---|---|
| 515 | 21 |
| 121 | 9 |
| 761 | 8 |

## Toplam GPS Gozlem Sayisi

- **Toplam:** 11.869
- **Gecerli:** 11.380 (%95.9)
- **Gecersiz:** 489 (%4.1) - tamami `ZERO_COORDINATE` (GPS fix
  alinamamis kayitlar)

## Duplicate Orani

**0 / 11.869 (%0.00)** - gercek (ayni ID + ayni koordinat) duplicate
hic gozlenmedi. (Trail noktalarindaki farkli-koordinatli tekrarlar
bu sayima dahil degil, bkz. known-risks madde 4.)

## Stale (Uzun Sure Hareketsiz) GPS Orani

**48 stale seri tespit edildi.**

### KRITIK BULGU: Bazi araclar neredeyse tum kosu boyunca "hareketsiz"

En carpici sonuclar:

| Hat | Arac | Ardisik hareketsiz gozlem | Toplam sorgu | Oran |
|---|---|---|---|---|
| 515 | 12154 | 353 | 356 | %99.2 |
| 515 | 12001 | 353 | 356 | %99.2 |
| 515 | 12109 | 353 | 356 | %99.2 |
| 515 | 11515 | 353 | 356 | %99.2 |
| 121 | 11189 | 352 | 355 | %99.2 |
| 121 | 11287 | 352 | 355 | %99.2 |
| 121 | 12225 | 352 | 355 | %99.2 |
| 121 | 11750 | 352 | 355 | %99.2 |

**Yorum:** Bu, gercekci bir "otobus butun gun park halinde" senaryosundan
cok, daha once `docs/known-risks.md` madde 4'te supheleneilen **trail-nokta
belirsizligi** sorununun guclu bir kaniti. Hareket metrigi ve stale
detection hesaplamalarinda her response'tan **sadece ilk trail noktasi**
temsilci olarak aliniyor - bu sonuc, secilen "ilk nokta"nin bazi araclar
icin gercekten hic guncellenmeyen sabit bir referans (ornegin depo/park
konumu) olabilecegini, aracin gercek canli konumunun trail'in baska bir
sirasinda kayboluyor olabilecegini gosteriyor.

**Bu, Faz 1'de cozulmedi.** Faz 2'de trail noktalarinin anlaminin
netlestirilmesi (ornegin tum trail noktalarini ayri ayri saklayip
hangisinin gercekten "canli" oldugunu belirleme) oncelikli bir arastirma
konusu olarak onerilir.

Daha kisa sureli (3-30 ardisik gozlem) stale seriler ise muhtemelen
gercek trafik/duraklama durumlarini yansitiyor olabilir - bunlar
supheli degil.

## Genel Degerlendirme

- API kosu boyunca **tamamen kesintisiz ve hatasiz** calisti (0 hata).
- Veri kalitesi kontrolleri beklendigi gibi calisti (sifir koordinat
  tespiti, duplicate tespiti).
- **En onemli acik soru**, trail-nokta secim stratejisinin bazi
  araclar icin yanlis/sabit bir noktayi temsilci olarak seciyor
  olabilecegi ihtimali - bu, Faz 2 oncesi arastirilmasi onerilen
  en yuksek oncelikli teknik risk.
