# Bilinen Riskler ve Teknik Bulgular

Bu belge, Faz 1 boyunca API ve veri kalitesiyle ilgili tespit edilen,
dokumante edilmemis veya beklenmedik davranislari toplar.

## 1. Rate limit dokumante degil ama gercekte var

`hatotobuskonumlari` endpoint'i, ardisik hizli isteklerde
`HTTP 429 - "API rate limit exceeded"` donduruyor. Resmi bir rate
limit dokumani bulunamadi. Test sirasinda hatlar arasi 3 saniyelik
bekleme kullanildi, bu genel olarak yeterli oldu.

**Etki:** Collector, hat sorgulari arasina mutlaka bekleme koymali
(su an 3 saniye).

## 2. Koordinatlar string, virgullu ondalik

`KoorX`/`KoorY` API'de `"38,46577667"` formatinda string olarak
geliyor (Turkce/Windows locale ondalik ayraci). Dogrudan `float()`
ile parse edilemez, once virgul->nokta donusumu sart.

**Etki:** Tum parsing kodu `value.replace(",", ".")` uygulamak
zorunda (bkz. `app/validation/quality.py::parse_koor`).

## 3. Koordinat "0","0" olabilir - gecersiz GPS isareti

Bazi araclarda `KoorX: "0", KoorY: "0"` degeri gozlemlendi - bu,
GPS fix alinamadigini gosteren bir isaret olarak yorumlaniyor.

**Etki:** `ZERO_COORDINATE` quality flag'i ile isaretlenip
`is_valid=False` yapiliyor, silinmiyor.

## 4. Ayni response icinde ayni arac ID'si birden fazla kez - ANCAK bu bir hata degil

**Ilk gozlemde** (collector'in ilk versiyonu) bu durum "duplicate"
olarak yanlislikla is_valid=False isaretlenmisti. Ham veri incelenince
gercek durum ortaya cikti: **API, her sorguda ayni arac icin birden
fazla, FARKLI koordinatli kayit donduruyor** - muhtemelen aracin son
birkac GPS noktasindan olusan kisa bir hareket izi (trail).

Ornek (Hat 515, tek bir response, OtobusId 2221):
```
2221 -> (38.43857833, 27.167825)
2221 -> (38.43732333, 27.16739667)
2221 -> (38.37034667, 27.20560167)  <- ayni response icinde 3. farkli konum
2221 -> (38.43754,    27.16754)     <- 4. farkli konum
```

Bu durum **duplicate degil**, potansiyel olarak **degerli ek veri** -
tek bir API cagrisinda aracin kisa bir gecmis hareketi elde
edilebiliyor olabilir. Ancak bu noktalarin **hangi sirada / ne zaman**
olustugu API'de belirtilmiyor (timestamp yok, bkz. madde 6), bu yuzden
sirlama/yorumlama net degil.

**Guncellenmis mantik:** Sadece **ayni ID + ayni (lat, lon)** ikilisi
tekrar ederse gercek/anlamsiz duplicate sayilir
(`EXACT_DUPLICATE_IN_RESPONSE` flag'i). Farkli koordinatli tekrarlar
normal kabul edilir ve `is_valid=True` olarak isaretlenir.

**Acik soru (Faz 2'ye tasiniyor):** Bu tekrar eden noktalarin
gercek sira/zaman bilgisi olmadan trajectory olusturmada nasil
kullanilacagi netlestirilmeli - simdilik hepsi ayni `observed_at`
(bizim client-side sorgu zamanimiz) ile kaydediliyor, bu da gercek
kronolojik sirayi kaybediyor olabilir.

**Hareket metrigi hesaplamasina etkisi (dogrulandi):** Ilk denemede,
trail noktalari ayiklanmadan hareket metrigi hesaplanmisti ve 108
satirin 28'i (%26) "gercekci olmayan hiz" (300-560 km/h) olarak
cikti - hepsinin `elapsed_seconds` degeri tam 60.0 idi, yani sorun
cycle'lar arasi degil, **ayni cycle icindeki farkli trail noktalarinin
yanlis eslesmesinden** kaynaklaniyordu. Duzeltme: her
`(hat, arac, observed_at)` icin sadece response'taki ilk nokta
temsilci olarak aliniyor (`scripts/compute_movement_metrics.py::dedupe_trail_points`).
Bu duzeltmeyle gercekci olmayan hiz sayisi 0'a dustu, ancak bu
yaklasim potansiyel ek bilgiyi (trail'deki diger noktalari) gozardi
ediyor - Faz 2'de trail noktalarinin sirasi netlesirse bu karar
gozden gecirilebilir.

**YENI BULGU - trail noktalari beklenenden farkli davraniyor
(cozulmemis soru):** Stale detection testinde (3 cycle, 60s araliklarla)
Hat 515 / Arac 2221 icin trail'deki 4 noktadan 3'unun **3 cycle boyunca
neredeyse birebir sabit kaldigi**, sadece 1 noktanin cok az kaydigi
gozlemlendi:

```
Cycle 1: (38.43857833,27.167825) (38.43732333,27.16739667) (38.386275,27.176935)   (38.43754,27.16754)
Cycle 2: (38.43857833,27.167825) (38.43732333,27.16739667) (38.387195,27.17591667) (38.43754,27.16754)
Cycle 3: (38.43857833,27.167825) (38.43732333,27.16739667) (38.38755167,27.175665) (38.43754,27.16754)
```

Bu, ilk varsayimimizin ("trail = aracin son birkac GPS noktasi, her
cycle'da guncellenir") **tam dogru olmayabilecegini** gosteriyor.
Olasi aciklamalar (henuz ayirt edilemedi):
1. API'de bazi trail girdileri cache'lenip guncellenmeden tekrar
   donduruluyor olabilir.
2. `OtobusId` fiziksel olarak birden fazla arac/sefere karsilik
   geliyor olabilir (ID tekrar kullanimi/cakismasi).
3. Trail'deki bazi noktalar sabit bir referans konum olabilir.

**Durum:** Bu soru Faz 1 kapsaminda cozulemedi - 3 cycle'lik (3 dakika)
pencere ayirt etmeye yetmiyor. 24 saatlik ana veri toplama sonrasi
cok daha genis bir pencereyle tekrar incelenmesi planlaniyor.

**Etki:** Su anki stale detection (`scripts/detect_stale_positions.py`)
sonuclari bu belirsizlik nedeniyle **temkinli yorumlanmali** - "arac X
hareketsiz kaldi" sonucu, gercekte "trail'in sabit kalan bir bileseni
secildi" anlamina da gelebilir. Faz 2'ye kadar bu script'in ciktisi
kesin/nihai kabul edilmemeli.

**25.5 saatlik ana kosu sonrasi guncel bulgu (madde 10 karsilastirmasi
ile):** Hat 515'te 353/356 sorguda "hareketsiz" gorunen 4 arac
(12001, 12154, 11515, 2002), destekleyici `hattinyaklasanotobusleri`
API'sinde de tam olarak bu 4 ID ile eslesti - VE bu API'deki
`KalanDurakSayisi` degerleri birbirinden farkli ve makul cikti
(5, 17, 25, 25). Bu, onceki "trail noktasi sabit bir referans/cache
olabilir" hipotezini zayiflatiyor; bunun yerine yeni bir hipotez
guclendi: **arac GPS koordinati donmus olabilir, ama aracin sefer
ilerlemesi (KalanDurakSayisi, muhtemelen GPS'ten bagimsiz bir
kaynaktan hesaplaniyor) gercekten degisiyor.** Yani sorun "sahte
arac/duplicate ID" degil, muhtemelen **konum alaninin (KoorX/KoorY)
guncellenmeme sorunu** - bu, Faz 2'de arastirilmasi gereken daha
spesifik bir teknik risk.

## 5. `HataVarMi` alani dokumantasyonda yok

Gercek response'ta `HataVarMi: false` seklinde bir ust-seviye alan
var, ancak resmi API dokumaninda bu alandan bahsedilmiyor.

**Etki:** API semasi tam guvenilir degil, collector'da "bilinmeyen
alan gelirse uygulamayi bozma" prensibiyle defensive parsing
uygulaniyor (`data.get(...)`, KeyError yerine `.get()` kullanimi).

## 6. Uzun sureli hareketsizlik - trafik mi, duraklama mi, veri sorunu mu belirsiz

60 dakikalik freshness testinde Hat 761'de 22123 numarali arac
17 ardisik gozlem (~17 dakika) boyunca ayni koordinatta kaldi.
Ayrim stratejisi henuz belirlenmedi, bkz. `docs/problem-definition.md`.

## 7. Test kesintiye ugrarsa son log satiri eksik kalabilir

Freshness testi sirasinda `Ctrl+C` ile durdurma, tam bir HTTP istegi
devam ederken yapilirsa, o istek hic loglanmiyor (script'in atomik
olmayan bir noktada kesilmesi). Veri kaybi/bozulmasi degil, sadece
eksik bir kayit anlamina geliyor.

**Ileride iyilestirme onerisi:** Graceful shutdown (SIGINT yakalayip
mevcut istegi tamamlatma) Faz 2'de eklenebilir.
