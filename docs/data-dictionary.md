# API Veri Sozlugu

## 1. Ana API: hatotobuskonumlari

`GET /api/iztek/hatotobuskonumlari/{hatId}`

Ust seviye response yapisi: `{ "HataMesaj": string, "HatOtobusKonumlari": [...], "HataVarMi": bool }`

**Not:** `HataVarMi` alani dokumanda belirtilmemis, sadece gercek response'ta
gozlemlendi. Dokumandaki ornek response'ta bu alan yoktu.

| Alan | Veri tipi | Ornek deger | Zorunlu mu? | Aciklama | Veri kalite riski |
|---|---|---|---|---|---|
| HataMesaj | string (top-level) | `""` | Evet | Hata mesaji, hata yoksa bos string | Dusuk |
| HataVarMi | boolean (top-level) | `false` | Belirsiz | Hata olup olmadigini belirtir | Dokumanda yok, her zaman gelip gelmedigi test edilmeli |
| HatOtobusKonumlari | array | `[...]` | Evet | Arac listesi | Bos gelebilir (arac yoksa) |
| OtobusId | int | `11088` | Evet | Arac benzersiz kimligi | **Ayni response icinde ayni OtobusId birden fazla kez gorulebiliyor** (bkz. known-risks) |
| Yon | int | `0` veya `1` | Evet | Hat yonu kodu | Kodun hangi yone (gidis/donus) karsilik geldigi API'de acik degil, harici referansla eslestirilmeli |
| KoorX | string (virgullu ondalik) | `"38,485035"` | Evet | Enlem (latitude) - dokumanda "double" deniyor ama gercekte string | Virgul->nokta donusumu sart; **"0" degeri gecersiz/GPS-fix-yok anlamina geliyor** |
| KoorY | string (virgullu ondalik) | `"27,07038833"` | Evet | Boylam (longitude) - ayni riskler | Ayni |

## 2. Destekleyici API: duragayaklasanotobusler

`GET /api/iztek/duragayaklasanotobusler/{durakId}`

Sadece `durakId` alir, `hatId` almaz - o durağa yaklaşan **tüm hatlardaki**
araçları döndürür (test sırasında aynı durakta 446, 346, 816 numaralı 3 farklı
hat görüldü).

| Alan | Veri tipi | Ornek deger | Zorunlu mu? | Aciklama | Veri kalite riski |
|---|---|---|---|---|---|
| KalanDurakSayisi | int | `7` | Evet | Sorgulanan durağa kalan durak sayısı | Trafik/duraklama etkisiyle dalgalanabilir |
| HattinYonu | int | `1` | Evet | Hattın yönü (ana API'deki `Yon` ile aynı mantık) | Kod anlamı belirsiz |
| KoorY | string (virgüllü ondalık) | `"27,05269667"` | Evet | Boylam | Aynı virgül riski |
| BisikletAparatliMi | boolean | `false` | Evet | Bisiklet aparatı var mı | Düşük |
| KoorX | string (virgüllü ondalık) | `"38,516545"` | Evet | Enlem | Aynı virgül riski |
| EngelliMi | boolean | `true` | Evet | Engelli erişimi var mı | Düşük |
| HatNumarasi | int | `446` | Evet | Hat numarası | - |
| HatAdi | string | `"EVKA.5 - BOSTANLI İSKELE"` | Evet | Hat adı (güzergah açıklaması) | Türkçe karakter encoding'e dikkat |
| OtobusId | int | `3058` | Evet | Araç kimliği | Ana API'deki OtobusId ile eşleşiyor (çapraz doğrulandı: 3058 iki API'de de aynı konuma yakın çıktı) |

## 3. Destekleyici API: hattinyaklasanotobusleri

`GET /api/iztek/hattinyaklasanotobusleri/{hatId}/{durakId}`

Aynı şema, ancak hem `hatId` hem `durakId` verildiği için sonuç tek bir
hatta filtrelenmiş oluyor (test sırasında 1 sonuç döndü, `duragayaklasanotobusler`
3 sonuç döndürmüştü aynı durak için).

Şema `duragayaklasanotobusler` ile birebir aynı (yukarıdaki tablo geçerli).

## API'lerde Bulunmayan Alanlar (Görev Metninde Sorulan)

| Aranan bilgi | Bulunuyor mu? | Not |
|---|---|---|
| Araç kimliği | ✅ Var | `OtobusId` |
| Hat numarası | ⚠️ Kısmi | Ana API'de yok (sadece URL path'inde), destekleyici API'lerde `HatNumarasi` alanı var |
| Enlem | ✅ Var | `KoorX` (isim kafa karıştırıcı ama değer enlem) |
| Boylam | ✅ Var | `KoorY` |
| Yön | ✅ Var | `Yon` / `HattinYonu` - ama kod anlamı (0/1 hangi yön) dokümante değil |
| Veri üretim zamanı | ❌ Yok | Hiçbir API'de yok |
| Son güncelleme zamanı | ❌ Yok | Hiçbir API'de yok |
| Durak bilgisi | ⚠️ Kısmi | Ana API'de yok; destekleyici API'lerde `KalanDurakSayisi` var ama bu "hangi durakta" değil "sorgulanan durağa kaç durak kaldı" bilgisi |
| Araç sırası | ❌ Yok | Hiçbir API'de yok |
| Sefer bilgisi | ❌ Yok | Hiçbir API'de yok |
| Hedef/yön bilgisi | ⚠️ Kısmi | Sadece sayısal yön kodu, hedef durak/güzergah adı yok |
| Durum bilgisi | ❌ Yok | Araç bazında "aktif/pasif/arızalı" gibi bir durum alanı yok |

## Ozet Teknik Riskler (docs/known-risks.md ile capraz referans)

1. Koordinatlar string ve virgullu ondalik - parse oncesi donusum sart
2. `KoorX`/`KoorY` degeri `"0"` olabilir - gecersiz/GPS-fix-yok isareti, filtrelenmeli
3. Ayni response icinde ayni `OtobusId` birden fazla kez gorulebiliyor (farkli koordinatlarla) - duplicate detection sart
4. Hicbir API'de zaman alani yok - tum zaman bilgisi client-side (`request_time`) uretilmek zorunda
5. `HataVarMi` alani dokumantasyonda yok, gercek response'ta var - API semasi tam guvenilir degil, defensive parsing gerekli
6. Rate limit dokumante degil ama gercekte var (~3 saniyede bir istek guvenli)
