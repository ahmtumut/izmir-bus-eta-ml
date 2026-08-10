# Problem Tanimi: Otobus Varis Suresi Tahmini (ETA)

Bu belge, Faz 1 kapsaminda **model gelistirmeden once** ML problemini
kavramsal olarak netlestirmek icin hazirlanmistir. Su an hicbir model
egitilmiyor - amac, ilerleyen fazlarda ground-truth uretimi ve feature
muhendisligi yaparken hangi kararlarin nasil verilecegini onceden
dokumante etmek.

## ETA nedir?

ETA (Estimated Time of Arrival), belirli bir anda (T0) hat uzerinde
seyreden bir aracin, belirli bir hedef durağa (X durağı) fiilen ne
zaman ulaşacağının tahminidir. Bizim baglamimizda iki ayri kavram var:

- **actual_eta**: Gecmise donuk, gercek gozlemlerden hesaplanan
  "gercek" varis suresi (egitim verisi icin hedef degisken/label).
- **predicted_eta**: Modelin, sadece T0 anindaki bilgilerle (mevcut
  konum, onceki konumlar, hat, yon, saat, gun, guzergah ilerlemesi)
  urettigi tahmin.

Faz 1'de sadece **actual_eta** uretim mantigini tasarliyoruz; predicted_eta
ilerleyen fazlarin konusu.

## Ground-truth nasil uretilebilir?

Temel mantik gorev metninde verildigi gibi:

```
T0: Arac A, X durağından uzakta bir konumda gozlemleniyor.
T1: Arac A, X durağına ulastigi ilk an olarak isaretleniyor.
actual_eta = T1 - T0
```

Ancak bunu uygulayabilmek icin once "durağa ulasti" tanimini
(asagidaki soru) netlestirmemiz gerekiyor - o tanim netlesmeden
ground-truth uretimi baslatilmayacak. Genel akis su sekilde olacak:

1. Her arac + hat + yon icin trajectory (ardisik GPS noktalari) cikar.
2. Trajectory uzerinde, "durağa ulasma" kriterini karsilayan ilk
   T1 anini bul.
3. T0'i, T1'den geriye dogru belirli bir zaman/mesafe penceresinde
   secilen referans noktalari olarak tanimla (orn. "T1'den 5, 10, 15
   dakika once nerede oldugu" gibi coklu ornekler uretilebilir - bu,
   tek bir T0 degil, egitim verisi zenginlestirme stratejisi olarak
   ilerleyen fazda degerlendirilecek).
4. actual_eta = T1 - T0 olarak hesapla.

## Bir aracin duraga ulastigini nasil anlayabiliriz?

Bu, gorev metninde de vurgulandigi gibi **simdiden rastgele
belirlenmeyecek**. Ilerleyen fazda asagidaki bilesenlerin birlikte
degerlendirilmesi planlaniyor:

- **Durak koordinati**: Durak listesi (ESHOT/acikveri.bizizmir.com
  durak veri seti) ile durakId'lerin gercek lat/lon'u eslestirilecek.
- **Mesafe esigi**: Aracin durak koordinatina ne kadar yaklastiginda
  "ulasti" sayilacagi (orn. 30-50 metre) - bu esik, GPS hata payi ve
  sehir ici trafik yogunlugu goz onune alinarak Faz 2'de veriyle
  kalibre edilecek, simdiden sabit bir sayi verilmiyor.
- **Guzergah/yon uyumu**: Aracin, durağın bagli oldugu hat ve yon
  uzerinde ilerliyor olmasi sarti (yanlis yondeki bir gecis "ulasti"
  sayilmamali).
- **Aracin durağı gecip gecmedigi**: Sadece mesafe esigine girmek
  yetmez - aracin durak sonrasi guzergahta ilerlemeye devam ettigi
  de (yani durakta gercekten durup gectigi, sadece yakininda GPS
  sicramasi olmadigi) teyit edilmeli.

`duragayaklasanotobusler` ve `hattinyaklasanotobusleri` API'lerindeki
`KalanDurakSayisi` alani, bu tanimin dogrulanmasinda ek bir capraz
kontrol kaynagi olarak kullanilabilir (Faz 1 madde 10'da bu iki API
arasi eslestirme ayrica arastiriliyor).

## Arac kimligi degisirse ne olur?

Test suremizde (60 dakikalik freshness testi) `OtobusId` degerlerinin
zaman icinde tutarli kaldigi gozlemlendi (bkz.
`docs/api-freshness-report.md` - giris/cikis sayilari dusuk). Ancak
API dokumantasyonunda ID'lerin kalici/degismez oldugu garanti
edilmiyor. Bu nedenle:

- Trajectory olusturma mantigi, bir aracin ID'sinin gun icinde ayni
  kalacagini varsayacak, ancak bu varsayimin gecerliligi collector
  calisirken surekli izlenecek (ID kaybolup farkli bir ID ile ayni
  konumdan devam eden bir arac tespit edilirse bu bir veri kalite
  bulgusu olarak loglanacak).
- ID degisimi supheli gorulen (orn. bir ID kaybolup ayni anda o
  konuma cok yakin yeni bir ID ortaya cikan) durumlar, ground-truth
  uretiminde trajectory'yi bolecek - yani boyle bir durumda o
  arac/segment icin T1 hesaplamasi guvenilir sayilmayacak ve
  egitim verisinden disarida birakilacak.

## Ayni hatta iki yon nasil ayrilacak?

Ana API'de `Yon`, destekleyici API'lerde `HattinYonu` alani var
(gozlemlenen degerler: 0 ve 1). Bu kod, gidis/donus yonunu temsil
ediyor gibi gorunuyor ancak API dokumantasyonunda hangi degerin
hangi fiziksel yone karsilik geldigi acik degil. Planlanan yaklasim:

- Trajectory'ler her zaman `(hat_no, yon)` ciftine gore ayri ayri
  gruplanacak - yani ayni hattin 0 ve 1 yonleri hicbir zaman ayni
  trajectory/model girdisi icinde karistirilmayacak.
- Yon kodunun fiziksel anlami (hangi yonun "gidis" hangisinin
  "donus" oldugu), guzergah/durak sirasi verisiyle karsilastirilarak
  Faz 2'de netlestirilecek - simdiden varsayim yapilmiyor.

## GPS noktalari eksik oldugunda ne yapilacak?

- Eksik/gecersiz nokta (orn. `KoorX`/`KoorY` = `"0"`, veya
  parse edilemeyen deger) trajectory'den **silinmeyecek, ama
  `is_valid=false` ve uygun `quality_flags` ile isaretlenecek**
  (bkz. `docs/data-quality-rules.md`).
- Trajectory'de eksik nokta oldugu donemler icin, ETA hesaplamasinda
  o bosluk dogrudan enterpolasyonla doldurulmayacak - bunun yerine
  bosluk suresi kaydedilecek ve belirli bir esigi (orn. 3+ ardisik
  eksik gozlem) asan trajectory segmentleri ground-truth uretiminde
  "guvenilir degil" olarak isaretlenip egitim verisi disi
  birakilacak.

## Arac bir sure GPS gondermedigin de nasil isaretlenecek?

Bir aracin `OtobusId`'si belirli sayida ardisik cycle'da response'ta
hic gorunmemesi durumu (bizim testimizde giris/cikis olarak
olcduk - bkz. freshness raporu). Bu durum icin:

- Arac response'tan kayboldugunda, en son gozlenen konum ve zaman
  `last_seen_at` olarak trajectory kaydinda tutulacak.
- Belirli bir esigi (orn. 3+ cycle, yani ~3 dakika) asan
  kayboluslar `vehicle_dropped_out` seklinde bir quality flag ile
  isaretlenecek - bu, aracin seferi bitirdigi, GPS'inin
  kapandigini, ya da API'nin gecici olarak o araci dondurmedigi
  anlamina gelebilir, ayrimi Faz 2'de yapilacak.

## Ayni koordinatta uzun sure kalmak trafik mi, duraklama mi, veri problemi mi?

Bu soruya **Faz 1'de kesin cevap verilmiyor** - test sirasinda somut
bir ornek gozlemlendi: Hat 761'de 22123 numarali arac 17 ardisik
gozlem (~17 dakika) boyunca ayni koordinatta kaldi (bkz.
`docs/api-freshness-report.md`). Bu, asagidaki senaryolardan
herhangi biri olabilir:

1. Arac gercekten trafikte sikismis (yogun trafik/kirmizi isik
   dizisi).
2. Arac bir terminalde/durakta bekliyor (mola, sefer arasi bekleme).
3. Aracin GPS cihazi veri gondermeyi durdurmus ama API son bilinen
   konumu tekrar tekrar donduruyor (stale cache).
4. Arac gercekten calismiyor (arizali, park halinde).

Planlanan ayrim stratejisi (Faz 2'de uygulanacak, simdi sadece
tasarlaniyor):
- Konumun bir **durak yakininda** olup olmadigina bakilacak (terminal/
  duraklama ihtimalini artirir).
- Ayni sure zarfinda **ayni hattaki diger araclarin** da benzer bolgede
  yavaslayip yavaslamadigina bakilacak (trafik ise coklu arac etkilenir,
  tek arac ise cihaz/veri sorunu ihtimali artar).
- Durus suresi belirli bir esigi (orn. 20-30+ dakika) asarsa, bu
  sure "muhtemelen veri/cihaz sorunu" olarak varsayilacak ve
  ground-truth hesaplamasindan cikarilacak.

## Tahmin basarisi hangi metriklerle olculebilir?

Ilerleyen fazda model degerlendirmesi icin planlanan metrikler:

- **MAE (Mean Absolute Error)**: Ortalama mutlak hata, dakika
  cinsinden - yorumlanmasi en kolay metrik, kullanicilarin
  anlayacagi birim.
- **RMSE (Root Mean Squared Error)**: Buyuk hatalari daha agir
  cezalandirir, ozellikle "cok yanlis" tahminleri yakalamak icin.
- **MAPE (Mean Absolute Percentage Error)**: Kisa ve uzun ETA'lari
  karsilastirilabilir kilar (orn. 1 dakikalik hata, 2 dakikalik
  bir ETA icin cok daha kotudur, 30 dakikalik bir ETA icin onemsizdir).
- **Esik-bazli dogruluk (orn. "±2 dakika icinde tahmin orani")**:
  Son kullanici perspektifinden en anlasilir metrik olabilir.

Baseline karsilastirmasi icin: sabit hiz varsayimiyla (mesafe/ortalama
hiz) hesaplanan naive bir ETA tahmini, gelistirilen modelin bu
baseline'i gercekten gecip gecmedigini gostermek icin kullanilacak.

## 40 is gununde toplanacak veri hangi modeller icin yeterli olabilir?

40 is günü (~8 hafta, günde ortalama kaç saat toplanacağına bağlı
olarak tahmini büyüklük):

- 3 pilot hatta, 60 saniyelik örnekleme ile, günde ~10-12 saatlik
  aktif toplama varsayılırsa, hat başına günde ~600-720 gözlem,
  40 günde hat başına ~24.000-29.000 gözlem seviyesinde bir hacim
  öngörülüyor. Trajectory/ETA çiftlerine dönüştüğünde bu sayı,
  durak sayısına ve yolculuk sıklığına bağlı olarak daha da
  büyüyecek ama tam rakam Faz 2'de gerçek durak eşleştirmesi
  yapılınca netleşecek.

- Bu hacim ile **uygun olabilecek modeller**:
  - Basit **baseline modeller** (ortalama hız, tarihsel ortalama
    ETA, doğrusal regresyon) - küçük veri ile bile anlamlı.
  - **Gradient boosting (XGBoost/LightGBM benzeri) ağaç modelleri**
    - orta büyüklükteki tablo verisiyle iyi çalışırlar, önceki
      capstone projesinde (NSL-KDD) de benzer bir yaklaşım
      kullanılmıştı.
  - Basit **zaman serisi / sekans modelleri** (küçük LSTM, GRU) -
    mümkün ama 40 günlük veriyle overfitting riski yüksek, dikkatli
    regularizasyon ve cross-validation gerekir (BIST projesindeki
    LSTM deneyiminden bildiğimiz gibi, küçük veri + karmaşık model
    kombinasyonu riskli).

- **Muhtemelen yetersiz olacak modeller**: Derin, çok katmanlı
  transformer tabanlı sekans modelleri (bu ölçekte veri az, aşırı
  parametre sayısı overfitting'e yol açar).

- Genel değerlendirme: 40 iş günü, **basit-orta karmaşıklıkta
  modeller için makul bir başlangıç**, ancak nihai model seçimi
  Faz 2'de gerçek veri hacmi ve durak eşleştirme kalitesi
  görüldükten sonra netleştirilecek.
