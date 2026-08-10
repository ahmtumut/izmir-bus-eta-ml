Get-Content docs\data-dictionary.md | Select-String "HataVarMi"# API Freshness Raporu

## Test Ozeti

- **Test suresi:** ~60 dakika (60 cycle, cycle basina ~60 saniye)
- **Sorgulama sikligi:** Her hat icin ~60 saniyede bir
- **Test edilen API:** `GET /api/iztek/hatotobuskonumlari/{hatId}`
- **Test tarihi:** 2026-08-10

## Pilot Hat Sonuclari

### Hat: 515 (kisa/yogun sehir ici)
```
Hat: 515
Sorgu sayisi: 88
Gorulen arac: 10
Farkli payload: 66
Hareket ettigi gozlenen arac: 10
Ortalama veri degisim suresi: ~60.0 saniye
Sonuc: CANLI
```
- Sorgu sayisi: 88 (basarili: 66, basarisiz: 22 - rate limit + test sirasindaki internet kesintisi)
- Ardisik snapshotlar arasi arac girisi: 1, cikisi: 1
- Uzun sure (3+ ardisik gozlem) ayni konumda kalan arac: yok

### Hat: 121 (orta mesafe)
```
Hat: 121
Sorgu sayisi: 88
Gorulen arac: 4
Farkli payload: 66
Hareket ettigi gozlenen arac: 4
Ortalama veri degisim suresi: ~60.0 saniye
Sonuc: CANLI
```
- Sorgu sayisi: 88 (basarili: 66, basarisiz: 22)
- Ardisik snapshotlar arasi arac girisi: 0, cikisi: 1
- Uzun sure ayni konumda kalan arac: yok

### Hat: 761 (uzun guzergah)
```
Hat: 761
Sorgu sayisi: 88
Gorulen arac: 2
Farkli payload: 65
Hareket ettigi gozlenen arac: 2
Ortalama veri degisim suresi: ~60.0 saniye
Sonuc: CANLI
```
- Sorgu sayisi: 88 (basarili: 66, basarisiz: 22)
- Ardisik snapshotlar arasi arac girisi: 0, cikisi: 0
- **Uzun sure ayni konumda kalan arac: arac 22123, 17 ardisik gozlem
  (~17 dakika)** - trafik/duraklama/GPS sorunu ayrimi netlesmedi,
  bkz. `docs/problem-definition.md`

## Freshness Sorularina Cevaplar

**Aynı arac farkli sorgularda hareket ediyor mu?**
Evet. Hat 515'te 10/10, hat 121'de 4/4, hat 761'de 2/2 arac (birden fazla
gozlemi olan tum araclar) zaman icinde konum degistirdi.

**Koordinatlar degisiyor mu?**
Evet, ardisik gozlemlerde KoorX/KoorY degerleri tutarli sekilde degisiyor.

**Response icerisinde veri zamani bulunuyor mu?**
Hayir. Ana API (`hatotobuskonumlari`) response'unda zaman alani yok.
Sadece `OtobusId`, `Yon`, `KoorX`, `KoorY` donuyor. Bu kritik bir bulgu,
bkz. `docs/known-risks.md`.

**Bulunuyorsa veri zamani ilerliyor mu?**
N/A - API'de veri uretim zamani alani olmadigi icin bu soru
degerlendirilemiyor. Zaman bilgisi tamamen bizim `request_time`
(client-side) kaydimizdan geliyor.

**Ayni response surekli tekrar mi geliyor?**
Hayir. Basarili sorgularin buyuk cogunlugunda (515: 66/66, 121: 66/66,
761: 65/66) payload_hash bir onceki sorgudan farkli cikti.

**Bazi araclar uzun sure ayni koordinatta mi kaliyor?**
Kismen. Hat 515 ve 121'de 3+ ardisik gozlemde hareketsiz kalan arac
gozlenmedi. Ancak **Hat 761'de 22123 numarali arac 17 ardisik gozlem
boyunca (~17 dakika) ayni koordinatta kaldi** - bu, terminalde bekleme,
duraklama veya GPS/veri sorunu olabilir, ayrimi henuz yapilamiyor
(bkz. `docs/problem-definition.md` - "aynı koordinatta uzun sure kalmak
trafik mi, duraklama mi, veri problemi mi" sorusu).

**Arac listesine yeni arac girip cikiyor mu?**
Sinirli olcude. Ardisik snapshotlar arasinda: hat 515'te 1 giris/1 cikis,
hat 121'de 0 giris/1 cikis, hat 761'de 0 giris/0 cikis gozlendi. Bu
hatlardaki filo buyuk olcude sabit, sik arac degisimi yok.

**Payload hash zaman icerisinde degisiyor mu?**
Evet, neredeyse her sorguda (bkz. yukarida farkli payload oranlari).

**Hatlar arasinda veri guncelligi farki var mi?**
Belirgin bir fark yok. Uc hattin da tahmini guncelleme periyodu
60 saniye civarinda cikti (515: ~60.0s, 121: ~60.0s, 761: ~60.9s) -
bu, bizim ornekleme araligimizla (60s) ortusuyor, yani API'nin gercek
guncelleme periyodu muhtemelen 60 saniyeden daha kisa ama bunu net
olcmek icin daha siki araliklarla (orn. 15-20s) ayri bir test gerekir.

**API'nin yaklasik guncelleme periyodu nedir?**
~60 saniye veya daha kisa (yukaridaki not gecerli - 60 saniyelik
ornekleme araliginda pratik olarak her seferinde farkli veri geldigi
icin gercek periyot bu degerden daha kisa olabilir, kesin olcum
yapilamadi).

## Onemli Yan Bulgu: Rate Limit

Dokumantasyonda belirtilmeyen bir rate limit tespit edildi:
`HTTP 429 - "API rate limit exceeded"`. Ardisik istekler (gecikmesiz)
ikinci istekte bu hataya yol aciyor. Test boyunca hatlar arasi 3 saniyelik
bekleme kullanildi, bu genel olarak yeterli oldu (263 sorgunun 65'i
basarisiz oldu, ancak bunlarin bir kismi test sirasinda yasanan internet
kesintisinden kaynaklandi, rate limit'ten degil - detay icin
`docs/known-risks.md`).

## Genel Sonuc

**3 pilot hattin ucu de CANLI olarak dogrulandi.** API gercekten
guncellenen, zaman icinde degisen konum verisi sagliyor. Faz 1'in
collector gelistirme asamasina gecilebilir.