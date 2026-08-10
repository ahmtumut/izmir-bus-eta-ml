# Pilot Hatlar

## Secim Kriterleri

Gorev metninde istendigi gibi, hatlar rastgele degil, farkli karakterde
(kisa/yogun, orta, uzun) ve **gercek API gozlemleriyle** dogrulanarak
secildi. Secim once varsayimla yapildi (Izmir'de yasayan proje sahibinin
bilgisiyle), ardindan Adim 1'deki sanity check ve freshness testiyle
gercek veri akisiyla teyit edildi.

| Hat | Tip | Secim gerekcesi |
|---|---|---|
| **515** | Kisa/yogun sehir ici | Sik durak araligina sahip, sehir ici yogun bir hat olarak biliniyor |
| **121** | Orta mesafe | Sehir ici ile banliyo arasi orta uzunlukta bir guzergah |
| **761** | Uzun guzergah | Uctan uca uzun bir hat, farkli hareket/yogunluk karakteri beklentisiyle secildi |

## Gercek API Gozlemleriyle Dogrulama

Secimin "tahminle degil gercek gozlemle" yapildigini kanitlamak icin,
Adim 1'deki 60 dakikalik freshness testi sonuclari asagida ozetlenmistir
(detay: `docs/api-freshness-report.md`):

| Hat | Ortalama anlik arac | Toplam farkli arac (60 dk) | Sonuc |
|---|---|---|---|
| 515 | 19.5 | 10 | CANLI |
| 121 | 8.6 | 4 | CANLI |
| 761 | 3.0 | 2 | CANLI |

Bu sonuclar, baslangictaki "kisa/yogun > orta > uzun" beklentisini
dogruluyor: Hat 515 belirgin sekilde en fazla araca sahip (yogun sehir
ici hatti karakteristigi), Hat 761 en az araca sahip (uzun, seyrek
guzergah). Uc hat da:

- Gercekten arac dondurdu (bos liste degil)
- Zaman icinde degisen (CANLI) veri sagladi
- Farkli hareket karakteri gosterdi (hareket eden arac sayisi, giris/
  cikis oranlari farkli)

Bu nedenle 3 hat da gorev metninin "gunun icerisinde arac uretmesi,
yeterli GPS noktasi saglamasi, veri akisinin gercekten degismesi"
kriterlerini karsiliyor ve pilot hat olarak onaylandi.

## Bilinen Kisitlar

- Hat 761'de test sirasinda dusuk arac sayisi (ortalama 3.0) nedeniyle,
  ilerleyen fazlarda trajectory/ETA egitim verisi bu hatta digerlerine
  gore daha az orneklem icerecek. Bu, Faz 2'de model degerlendirmesi
  yapilirken goz onunde bulundurulmali.
- Hat 761'de 17 dakikalik "stale" (hareketsiz) bir arac gozlemi de
  bu dusuk orneklem sorununu buyutebilir (bkz. `docs/known-risks.md`).
