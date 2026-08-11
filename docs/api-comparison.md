# Destekleyici API Karsilastirmasi (Gorev Madde 10)

## Amac

Ana konum API'si (`hatotobuskonumlari`) ile destekleyici "hatta
duraga yaklasan otobusler" API'sini (`hattinyaklasanotobusleri`)
karsilastirip, iki kaynaktaki araclarin birbiriyle eslesip
eslesmedigini arastirmak. Hangisinin daha dogru oldugu VARSAYILMADI,
sadece iliskilendirme arastirildi.

## Yontem

Gercek ESHOT durak verisinden (`data/reference/eshot-otobus-duraklari.csv`)
her pilot hat icin gercekten o hattin gectigi bir durak secildi:

| Hat | Durak ID | Durak Adi |
|---|---|---|
| 515 | 10454 | Halkapinar Metro |
| 121 | 10019 | Bahribaba |
| 761 | 50576 | Yesil Yol |

Her hat icin ayni anda iki API cagirildi (3sn araliklarla, rate
limit'e uyumlu), donen `OtobusId` kumeleri karsilastirildi.

## Sonuclar

### Hat 515 (Halkapinar Metro durağı)
- Ana API: 20 kayit, 9 benzersiz arac
- Destek API: 4 arac (bu duraga yaklasan)
- **Eslesen: 4/4** - destek API'deki tum araclar ana API'de de var
- Destek API'deki `KalanDurakSayisi` degerleri: 5, 17, 25, 25 -
  farkli ve makul, her arac gercekten farkli bir ilerleme asamasinda

**Onemli:** Eslesen 4 arac (12001, 12154, 11515, 2002) tam olarak
25.5 saatlik ana kosuda "353/356 sorguda hareketsiz" olarak
isaretlenen araclarla ayni (bkz. `docs/known-risks.md`). Bu, konum
verisinin donmus olabilecegi ama aracin gercekte hareket ettigi
hipotezini destekliyor.

### Hat 121 (Bahribaba durağı)
- Ana API: 8 kayit, 4 benzersiz arac
- Destek API: 2 arac
- **Eslesen: 2/2**
- `KalanDurakSayisi`: 8, 28 - farkli ve makul

### Hat 761 (Yesil Yol durağı)
- Ana API: 5 kayit, 4 benzersiz arac
- Destek API: 0 arac
- **Eslesen: 0/0**

Bu durakta o an yaklasan arac olmamasi beklenen bir durum olabilir -
API hatasi degil (HTTP 200 donuldu, sadece bos liste). Muhtemel
aciklama: o anda hicbir arac bu spesifik duraga yeterince yakin/
yaklasan durumda degildi, ya da yon (`HattinYonu`) filtrelemesi
nedeniyle bu durakta gorunmedi.

## Genel Degerlendirme

- Iki API arasinda **tutarli bir iliskilendirme mumkun** - `OtobusId`
  her iki kaynakta da ayni araci temsil ediyor, capraz dogrulama
  yapilabilir.
- Destek API'nin `KalanDurakSayisi` alani, ana API'nin sadece
  koordinat sagladigi yerde **ek, potansiyel olarak GPS'ten
  bagimsiz bir ilerleme sinyali** sagliyor - bu, "stale GPS"
  supheli araclarin gercekten hareket edip etmedigini capraz
  kontrol etmek icin degerli bir kaynak olabilir (Faz 2 onerisi).
- Bos sonuc donmesi (Hat 761 ornegi) hata degil, normal bir durum
  olarak degerlendirilmeli - collector'in hata yonetiminde bu
  ayrim zaten yapiliyor (bos liste != API hatasi).

## Faz 2 Onerisi

`KalanDurakSayisi` alanini, GPS-bazli stale detection'a **ek bir
capraz kontrol katmani** olarak entegre etmek: eger bir aracin GPS
konumu degismiyor ama `KalanDurakSayisi` degeri zaman icinde
degisiyor ise, bu "gercekten hareket ediyor ama GPS alani
guncellenmiyor" seklinde ayri bir quality flag ile isaretlenebilir
(`STALE_GPS_BUT_PROGRESSING` gibi).
