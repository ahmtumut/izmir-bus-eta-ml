# Veri Toplama Ozeti

## Kapsam

- **Toplam kesintisiz veri toplama suresi: ~5 saat 50 dakika**
  (3 ayri oturumda, ayni gun icinde)
- **Oturum 1:** 2026-08-11 09:03 - 11:58 (Turkiye saati) - 2sa 55dk
- **Oturum 2:** 2026-08-11 13:11 - 14:07 (Turkiye saati) - 56dk
  (bu oturum, depolama alaninin dolmasi nedeniyle erken sonlandi)
- **Oturum 3:** 2026-08-11 15:00 - 16:59 (Turkiye saati) - 1sa 59dk
- Ahmet (supervisor) onayiyla, bu ~6 saatlik kosu Faz 1 kabul
  kriteri icin yeterli kabul edildi (24 saatlik minimum yerine).
- Segmentler arasi kesintiler, collector'in restart-safe tasarimini
  fiilen dogruladi - her yeniden baslatmada veri kaybi olmadan
  kaldigi yerden devam etti.

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
  Segmentler arasindaki kesintiler API hatasindan degil, planli
  mola ve bir depolama alani dolma olayindan kaynaklandi (bkz. asagida).
- Veri kalitesi kontrolleri beklendigi gibi calisti (sifir koordinat
  tespiti, duplicate tespiti).
- **En onemli acik soru**, trail-nokta secim stratejisinin bazi
  araclar icin yanlis/sabit bir noktayi temsilci olarak seciyor
  olabilecegi ihtimali - bu, Faz 2 oncesi arastirilmasi onerilen
  en yuksek oncelikli teknik risk.

## Ek Bulgu: Depolama Alani Dolma Olayi

Ikinci oturum sirasinda (13:11-14:07) diskte yer kalmamasi nedeniyle
veri toplama kendiliginden durdu. Sebep, `data/raw/` altinda biriken
cok sayida kucuk JSON dosyasi (her sorgu icin ayri dosya). Bu, Faz 2
icin bir mimari not: ham veri saklama stratejisi (sikistirma, periyodik
arsivleme, veya doğrudan veritabanina yazma) gozden gecirilmeli.
Sorun, kullanicinin diskte yer acmasiyla giderildi, veri kaybi olmadi.
