# Faz 3 - Veri Büyütme ve GOLD Validation Bulguları

**Tarih:** 12-17 Ağustos 2026
**Durum:** Faz 3 devam ediyor - veri toplama, GOLD validation, split,
feature engineering, XGBoost/CatBoost eğitimi ve model seçimi tamamlandı;
SHAP analizi ve final rapor henüz yazılmadı (bkz. sondaki "Sırada Ne Var")

## Özet

Faz 2 kapanışında elimizde tek bir 60 dakikalık toplama turu (12 Ağustos
sabahı) ve 45 eta_training_samples (hepsi SILVER) vardı. Bu doküman,
CLAUDE.md'nin Faz 3 talimatına göre yapılan veri büyütme çalışmasının ve
bu sırada bulunan iki önemli veri kalitesi bulgusunun özetidir.

## Veri Toplama

3 pilot hat (515, 121, 761) üzerinde 12-17 Ağustos arası 11 gerçek/test
toplama oturumu çalıştırıldı (`ingestion_run_id` 28-38), farklı gün ve
saat dilimlerini kapsayacak şekilde:

| Gün | Tarih | Dilimler |
|---|---|---|
| Çarşamba | 12 Ağu | sabah |
| Perşembe | 13 Ağu | öğle, öğleden sonra |
| Cuma | 14 Ağu | sabah, öğle-öğleden sonra (GOLD test'leri dahil) |
| Pazar | 16 Ağu | ~10 saatlik sürekli oturum (GOLD burst açık) |
| Pazartesi | 17 Ağu | sadece hat 761 (`--lines 761`), dengesizliği azaltmak için hedefli oturum |

Güncel toplam (bkz. `reports/dataset-summary-20260817.md` için tam
kırılım, run 38 öncesi):
- **eta_training_samples: geçerli 3152 satır** (591 benzersiz
  arrival_event) - REJECTED işaretlenen 1 event/165 satır hariç
- Hat bazında: 515 ~1194, 121 ~440, 761 ~1519
- Gün çeşitliliği: 4 farklı gün (3 hafta içi + 1 hafta sonu)
- **Bilinen sınırlama:** akşam yoğun saat (17:00-19:00) ve
  Pazartesi/Salı/Cumartesi kapsanmadı - dataset saat/gün dağılımı hâlâ
  öğle-öğleden sonrasına ağırlıklı.

### Hat bazında gün dağılımı ve 761'in dengesizlik sorunu

| Hat | 12 Ağu | 13 Ağu | 14 Ağu | 16 Ağu |
|---|---|---|---|---|
| 515 | 29 | 91 | 277 | 797 |
| 121 | 10 | 80 | 208 | 141 |
| 761 | 6 | — | 33 | **1480 (%97)** |

761 hattının verisinin neredeyse tamamı (%97) tek bir günden (16 Ağustos,
10 saatlik oturum) geliyor. Bu, zamansal train/val/test split'te ciddi bir
soruna yol açtı - bkz. Bulgu 3. Düzeltme için 17 Ağustos'ta sadece 761'i
hedefleyen 1 saatlik ek bir oturum (`run_id=38`) başlatıldı.

## Bulgu 1: GOLD/HIGH-confidence arrival event üretimi - kod 3 revizyon geçirdi

Arrival detection'da HIGH confidence şartı (`detect_arrival_events.py`),
aynı aracın support API'de (`hattinyaklasanotobusleri`) yaklaşma
penceresi içinde **≥2 azalan `KalanDurakSayisi` örneği** görülmesidir.

- **v1** (9 durak, ana döngüyle aynı 60sn cadence): 0 HIGH. İç içe sıkı
  poll denemesi HTTP 429 (rate limit) hatası verdi, düzeltildi.
- **v2** (6 durağa indirildi, cycle başına tek pass, 30sn cadence): hala
  0 HIGH. Kök neden: ana GPS'i de sıklaştırınca gerçek fiziksel varış
  penceresi ~30sn'ye düştü (önceki geniş pencereler seyrek GPS
  örneklemesinin yapay ürünüymüş) - support API'nin 30sn cadence'i bu
  pencereye 2 örnek sığdıramadı.
- **v3** (support API ana GPS'ten bağımsız, 12sn cadence; ana GPS ~36sn'de
  bir): 10 saatlik oturumda **1 HIGH/GOLD event** üretildi.

**Ancak bu 1 GOLD event de sorunlu çıktı** - bkz. Bulgu 2.

## Bulgu 2: Aynı response içinde tek OtobusId'nin iki farklı konuma atanması - GOLD event'i geçersiz kıldı

10 saatlik oturumda üretilen tek HIGH-confidence event'in (id=2555, hat
121, durak Bahribaba/10019, araç 12263) yaklaşma penceresi anormal
derecede uzundu: **12:28 -> 15:34 (3 saat 6 dakika)**.

İncelemede, `vehicle_id=12263` için AYNI `observed_at` zaman damgasında
VE **AYNI `raw_snapshot_id` (=6419, yani tek bir API çağrısının cevabı)
içinde** iki farklı konum bulundu (`response_index` 1 ve 4 ile ayrı ayrı
kaydedilmiş):

| response_index | Koordinat | Konum | map_match |
|---|---|---|---|
| 1 | lat=38.670, lon=26.762 | Çeşme/Alaçatı yönü - hat 121 güzergahının tamamen dışında | REJECTED |
| 4 | lat=38.415, lon=27.127 | İzmir şehir merkezi, hat güzergahına yakın | GOOD |

Yani bu, **gün içinde ID'nin sırayla farklı araçlara yeniden atanması
değil** - İzmir API'sinin **tek bir response'ta aynı `OtobusId`'yi iki
farklı gerçek konum için birden döndürmesi**. Üstelik REJECTED
konumdaki koordinat (`26.76222167, 38.67049333`) 3 saat boyunca
**hiç değişmeden birebir tekrar etti** - bu, gerçekten hareket eden
ikinci bir araç değil, API'nin backend'inde askıda kalmış/statik bir
"hayalet" (ghost) kayıt olduğunu düşündürüyor (örn. servis dışı kalmış
bir aracın son bilinen konumunun, aynı ID yeni bir araca atanmışken
response'a sızmaya devam etmesi).

**Sonuç:** `detect_arrival_events.py`'nin gözlemleri `(vehicle_id,
route_id)` bazında gruplaması, bu response-içi ID çakışması nedeniyle
gerçek yolculuğu hayalet kayıtla karıştırdı. Support API tarafında
görülen "36'dan 1'e düzenli azalan KalanDurakSayisi" trendi muhtemelen
bu ID altındaki gerçek aracın (hayalet kayıttan bağımsız) normal
seyrini yansıtıyor, ama GPS trajectory'si hayalet noktayla kirlenmiş
durumda.

**Aksiyon alındı:** event 2555 `arrival_confidence='LOW'` ve
`quality_flags += 'VEHICLE_ID_REUSE_SUSPECTED'` olarak güncellendi; buna
bağlı 165 `eta_training_samples` satırı `label_quality='REJECTED'`
yapılıp dataset'ten çıkarıldı.

**Kapsamı henüz tam doğrulanmadı** - sistematik bir tarama yapılmadı,
sadece bu 1 vaka bulundu ve düzeltildi. Bu response-içi ID çakışması
prensipte herhangi bir oturumda (kısa ya da uzun) oluşabilir, ama uzun
(10 saatlik gibi) oturumlarda görünürlüğü/etkisi artar çünkü hayalet
kayıt kalıcıysa daha fazla arrival-detection penceresine karışma şansı
bulur. İleride `map_match_observations.py` veya
`detect_arrival_events.py`'ye, aynı `raw_snapshot_id` içinde aynı
`vehicle_id`'nin birden fazla kez göründüğü ve konumlardan birinin
güzergahtan çok uzak olduğu durumları otomatik flag'leyen bir kontrol
eklenmesi düşünülebilir - bu Faz 3'ün mevcut kapsamında yapılmadı.

## Bulgu 3: Zamansal split'te hat dağılımı dengesizliği

`app/ml/split.py` ile yapılan ilk global zamansal split (arrival_event_id
bazında, erken->train / orta->validation / geç->test, %70/15/15 event
oranı) teknik olarak doğru çalıştı ama sonuç dengesiz çıktı:

| Split | Event | Satır | Hat dağılımı (515/121/761) |
|---|---|---|---|
| Train | 413 (%70) | 713 (%18) | 384 / 290 / 39 |
| Validation | 89 (%15) | 154 (%4) | 63 / 86 / 5 |
| Test | 89 (%15) | 2285 (%58) | 747 / 63 / 1475 |

İki sorun: (1) satır oranları event oranlarını yansıtmıyor - 16
Ağustos'un uzun oturumu her event'ten çok daha fazla T0 sample'ı
ürettiği için zaman ekseninin sonunu (test'i) domine ediyor; (2) hat
dağılımı split'ler arası tutarsız - train'de 761 neredeyse yok (39),
test'te baskın (1475, test'in %65'i).

**Kök sebep:** 761 hattının verisinin %97'si tek bir günden geliyor
(bkz. yukarıdaki tablo). **Çözüm olarak** 17 Ağustos'ta 761'e özel 1
saatlik bir toplama oturumu (`run_id=38`, `--lines 761` desteği
`run_dual_collector.py`'ye eklendi) başlatıldı; bu tamamlandıktan sonra
hat bazında ayrı zamansal split (her hat kendi içinde erken/orta/geç
ayrımı) uygulanacak. **Bilinen sınırlama:** 761'in verisi hâlâ ağırlıklı
olarak 16-17 Ağustos'tan geleceği için, bu hat için split
"gün-arası" değil kısmen "gün-içi" genelleme test edecek - 515/121 için
bu sorun yok.

## Bulgu 4: Sistemik "round-trip" arrival window hatası - dataset'in çoğunu etkiliyordu

Hat bazında split'i çalıştırdıktan sonra 761'in validation split'inde
ciddi bir anomali fark edildi: sadece 7 event, 1078 satır üretmişti
(ortalama ~154 satır/event). İncelemede, event 2821 (araç 2222, durak
"Balıkçı") için `distance_along_route_m` şu şekilde hareket ettiği
görüldü: **55451 → 0'a kadar düşüyor → 55893'e kadar tekrar çıkıyor**
- yani araç, tek bir "yaklaşma penceresi" içinde **71km'lik güzergahın
tamamını gidip geri dönmüş** (muhtemelen gerçek bir Urla-Karaburun-Urla
turu), ve `detect_arrival_events.py`'nin `passed_idx` mantığı
(`dist_along > stop_dist_along + 5` ilk gerçekleştiği an) bunu tek bir
anormal derecede uzun (3 saat 6 dakika) "yaklaşma" olarak yorumlamış.

**Sistematik tarama sonucu:** Bu izole bir vaka değildi. Tüm
arrival_events'te (`passed_at - approach_started_at`) süresine bakılınca
net bir doğal ayrım bulundu:

| Pencere süresi | Event sayısı |
|---|---|
| 0-300sn (normal) | 2192 (%96.3) |
| 300-1200sn (kabul edilebilir, örn. trafik) | 24 |
| **1200-1800sn** | **0 (boşluk)** |
| **1800sn+ (anomali)** | **53** |

53 event (515: 12, 121: 16, 761: 25), **2268 eta_training_samples**
satırı üretmişti - mevcut "geçerli" verinin büyük çoğunluğu
(3164 satırın 2268'i, yani **%72'si**). Bunların hepsi muhtemelen aynı
mekanizmadan (uzun bir round-trip'in tek pencereye sıkışması, özellikle
761 gibi uzun güzergahlarda, ama 515/121'de de daha küçük ölçekte
oluşabiliyor) kaynaklanıyor.

**Aksiyon alındı:** 1800sn (30dk) eşiği üzerindeki tüm event'ler
`arrival_confidence='LOW'` + `quality_flags +=
'ANOMALOUS_LONG_WINDOW_SUSPECTED_ROUTE_LOOP'` olarak güncellendi; buna
bağlı 2268 `eta_training_samples` satırı `label_quality='REJECTED'`
yapıldı. **Sonuç: dataset 3164 → 896 geçerli satıra düştü (575
benzersiz event).** Hacim ciddi şekilde azaldı ama veri artık çok daha
güvenilir - ayrıca bu düzeltme, 761'in gün dengesizliğini de kısmen
iyileştirdi (16 Ağustos'un payı %97'den %64'e düştü, çünkü şişkinliğin
büyük kısmı zaten bu hatalı event'lerden geliyordu).

Split scripti bu temiz veri üzerinde tekrar çalıştırıldı
(`reports/split-report-20260817-perline-v2.md`):

| Split | Event | Satır | Hat dağılımı (515/121/761) |
|---|---|---|---|
| Train | 401 | 577 | 317/223/37 |
| Validation | 86 | 174 | 63/33/78 |
| Test | 88 | 145 | 67/70/8 |

**Kök neden düzeltilmedi, sadece etkisi filtrelendi.**
`detect_arrival_events.py`'nin `find_candidate_window` /
`passed_idx` mantığı, bir aracın durağı geçtikten sonra güzergahın
tamamını kat edip GERİ DÖNMESİ durumunu (özellikle uzun/turlu
güzergahlarda gerçek bir senaryo) ayırt edemiyor. İleride bu
fonksiyona bir üst süre/mesafe sınırı (örn. "approach_idx'ten X dakika
sonra hâlâ passed_idx bulunamadıysa bu event'i iptal et") eklenmesi
önerilir - Faz 3'ün mevcut kapsamında yapılmadı, sadece post-hoc
filtreleme (1800sn eşiği) uygulandı.

## Bulgu 5: T0 aday penceresinin genişletilmesi - dataset 896'dan 15.425 satıra çıktı, GOLD bonus olarak ortaya çıktı

Model karşılaştırma sonrası (896 satırlık dataset ile) hem CatBoost hem
XGBoost'un ortak bir zaafı vardı: **uzun ETA'larda (10dk+) pratik olarak
işe yaramıyorlardı** (MAE 8-17dk). Kök sebep araştırıldığında, "121 hattı
kötü" ile "uzun ETA kötü" bulgularının **aynı sorunun iki görünümü**
olduğu ortaya çıktı (yukarıdaki Model Eğitimi bölümüne bkz.) - asıl
suçlu, `detect_arrival_events.py`'deki bir sabitti:

```python
PROXIMITY_M = 50
COARSE_APPROACH_WINDOW_M = PROXIMITY_M * 4  # = 200 metre
```

**Bu değer İzmir API'sinden gelmiyor, tamamen bizim kodumuza ait bir
tasarım kararıydı.** Bir aracın bir durağa "yaklaşıyor" sayılıp T0 adayı
üretmeye başlaması için durağa **200 metreden** yakın olması
gerekiyordu. 200m, otobüs hızında (~5-10 m/s) sadece ~20-40 saniyeye
denk geliyor - yani `generate_eta_training_samples.py`'nin ürettiği T0
adaylarının ezici çoğunluğu, tanım gereği durağa çok yakın (dolayısıyla
kısa ETA'lı) anlardan geliyordu. Daha fazla veri toplamak bu oranı
DEĞİŞTİRMEZDİ - aynı dar pencereyle her zaman ~%90 kısa/%10 uzun ETA
üretilirdi.

**Düzeltme:** `COARSE_APPROACH_WINDOW_M` 200m'den **3000m (3km)**'ye
çıkarıldı. Risk: geniş pencere, Bulgu 4'teki round-trip artifact'lerini
daha sık tetikleyebilirdi - bu yüzden aynı 1800sn'lik post-hoc filtre
korundu (bkz. aşağıda).

### Yeniden üretim süreci (mevcut veriden, YENİDEN TOPLAMA YAPILMADI)

Sabit değiştikten sonra, DB'deki `vehicle_observations` (GPS ham verisi)
dokunulmadan, sadece TÜRETİLEN katmanlar baştan üretildi:

1. `arrival_events` ve `eta_training_samples` tabloları tamamen
   temizlendi (2275 event, 3329 satır silindi).
2. `detect_arrival_events.py` tüm 11 ingestion_run için yeniden
   çalıştırıldı (yeni 3km eşiğiyle) → **1943 yeni arrival_event**
   (öncekinden az çünkü aynı GPS noktası artık birden fazla yakın
   durak için aday olabiliyor, ama çoğu `closest_dist > PROXIMITY_M`
   testinde elendi).
3. `generate_eta_training_samples.py` tüm run'lar için yeniden
   çalıştırıldı → **18.315 ham T0 satırı** (900m→3km genişleme, her
   yaklaşma penceresinde çok daha fazla GPS noktasının T0 adayı
   olmasını sağladı - beklenen ve istenen sonuç).
4. Bulgu 4'ün aynı 1800sn eşiği tekrar uygulandı: bu sefer **38 event /
   2890 satır** REJECTED işaretlendi (dağılımda artık 0-60-120-...-1200sn
   arası sağlıklı bir doluluk vardı, 1200-1800sn arası sadece 14 event -
   hâlâ net bir kuyruk ayrımı korunuyordu).
5. Sonuç: **15.425 geçerli satır, 1792 benzersiz event.**

### GOLD satırları nereden çıktı?

HIGH-confidence şartı (support API'de aynı pencere içinde ≥2 azalan
`KalanDurakSayisi` örneği) değişmedi - ama pencere 20-40 saniyeden
ortalama ~8 dakikaya (medyan) çıkınca, support API'nin periyodik
sorgularının (GOLD burst'te 12sn, normal cycle'da pilot duraklarda
~60sn) bu daha uzun pencerenin içine **2+ örnek düşürmesi** artık çok
daha olası hale geldi. Sonuç: **41 benzersiz HIGH-confidence event,
411 GOLD eta_training_samples satırı** - hiçbiri Bulgu 4/2'deki gibi
şüpheli değil (pencere süreleri 2-28dk arası, medyan 8dk, hepsi 1800sn
eşiğinin güvenle altında). Bu, GOLD üretme çabalarımızın (v1-v3)
başarısız görünmesinin de gerçek kök nedeninin aynı dar-pencere sorunu
olduğunu doğruluyor - v3'teki cadence düzeltmesi doğruydu ama pencere
zaten çok dar olduğu için hiçbir cadence yeterli olamazdı.

### Sonuç dağılımı

| | Önce (896 satır) | Sonra (15.425 satır) |
|---|---|---|
| 0-5dk | ~%90.5 (train) | 8604 satır (%55.8) |
| 5-10dk | - | 5012 satır (%32.5) |
| 10-20dk | - | 1770 satır (%11.5) |
| 20+dk | %0.2 (1 satır) | 39 satır (%0.25, hâlâ az) |
| GOLD | 0 | 411 |
| Hat dağılımı | 515/121/761 dengesiz | 515: 10071, 121: 4334, 761: 1020 |

Split ve model eğitimi bu yeni veriyle tekrarlandı - **güncel sonuçlar
aşağıdaki "Model Eğitimi ve Karşılaştırma" bölümünde** (v2 olarak
güncellendi).

## Feature Engineering (`app/ml/features.py`)

Temel feature'lar (`eta_training_samples`'ta zaten mevcut, Faz 2'den):
`distance_remaining_m`, `progress_along_route`, `recent_speed_mps` (180sn),
`hour_of_day`, `day_of_week`, `line_no`, `direction`, `target_stop_id`.

Eklenen yeni feature'lar (hepsi T0 ve ÖNCESİ gözlemlerden, `observed_at <= T0`
filtresiyle):
- `distance_to_route_m` - T0 gözleminin map-match mesafesi (GPS/eşleştirme
  belirsizliği sinyali)
- `time_since_previous_obs_s` - T0'dan hemen önceki gözlemle arasındaki süre
- `speed_avg_last3_mps` / `speed_std_last3_mps` - son 3 gözlem arasındaki hız
  örneklerinin ortalaması/std'si (trafik/duraklama sinyali)
- `speed_avg_5min_mps` - 300sn'lik pencerede baştan-sona hız (180sn'lik
  `recent_speed_mps`'ten farklı, daha geniş bir pencere)

**Eksik veri oranları (imputation yapılmadı, dürüstçe NaN bırakıldı):**
`distance_to_route_m` %0, `time_since_previous_obs_s`/`speed_avg_last3_mps`
%1.2, `speed_std_last3_mps` %2.5, `speed_avg_5min_mps` %4.1 (15.425 satır
üzerinden, Bulgu 5 sonrası güncel dataset).

**Model feature listesi (12 aday, `vehicle_id` hariç tutuldu - gorev
talimatı):** 3 kategorik (`line_no`, `direction`, `target_stop_id`) + 9
sayısal (`distance_remaining_m`, `progress_along_route`, `recent_speed_mps`,
`hour_of_day`, `day_of_week`, `distance_to_route_m`,
`time_since_previous_obs_s`, `speed_avg_last3_mps`, `speed_std_last3_mps`,
`speed_avg_5min_mps`).

Çıktı: `data/processed/eta_features_20260817_v2.csv` (15.425 satır, 22
kolon - kimlik/label/metadata kolonları dahil, model feature listesi ayrı
dokümante edildi). İlk versiyon (`..._20260817.csv`, 896 satır, Bulgu 5
öncesi) tarihsel referans için saklandı.

## Model Eğitimi ve Karşılaştırma

`app/ml/train_xgboost.py` ve `app/ml/train_catboost.py`: her ikisi de CPU
üzerinde (`device=cpu` / `task_type=CPU`), 12 thread, sınırlı randomized
search (20 aday) ile eğitildi. Hiperparametre araması SADECE train+validation
üzerinde yapıldı, test setine arama sırasında hiç dokunulmadı.

`app/ml/baselines.py`: Baseline 2 (tarihsel medyan) artık gerçek bir
leave-out - medyanlar SADECE train'den hesaplanıp val/test'e uygulandı
(Faz 2'deki "leave-one-out yapılmadı, güvenilmez" sorunu bu split
yapısıyla doğal olarak çözüldü).

### Final Karşılaştırma Tablosu - v1 (896 satır, Bulgu 5 öncesi, tarihsel referans)

| Model | MAE(dk) | RMSE(dk) | MedAE(dk) | ±2dk% | ±3dk% |
|---|---|---|---|---|---|
| Baseline 1 (mesafe/hız) | 4.04 | 8.25 | 0.52 | 74.5% | 76.6% |
| Baseline 2 (tarihsel medyan, leave-out) | 2.81 | 6.00 | 0.40 | 75.9% | 77.9% |
| XGBoost | 2.72 | 5.51 | 0.51 | 73.8% | 75.9% |
| CatBoost | 2.58 | 5.58 | 0.37 | 74.5% | 79.3% |

v1'de CatBoost'un baseline üzerindeki kazancı istatistiksel olarak
anlamlıydı ama küçüktü (~14sn), XGBoost'unki ise anlamlı değildi. Kök
sebep araştırması Bulgu 5'e (T0 penceresi darlığı) yol açtı - aşağıdaki
v2 sonuçları GÜNCEL ve GEÇERLİ olandır.

### Final Karşılaştırma Tablosu - v2 (15.425 satır, Bulgu 5 sonrası - GÜNCEL)

| Model | MAE(dk) | RMSE(dk) | MedAE(dk) | ±2dk% | ±3dk% | n |
|---|---|---|---|---|---|---|
| Baseline 1 (mesafe/hız) | 2.36 | 5.68 | 1.11 | 69.2% | 81.3% | 2474 |
| Baseline 2 (tarihsel medyan, leave-out) | 2.30 | 3.03 | 1.96 | 51.2% | 71.0% | 2474 |
| XGBoost | 1.45 | 2.28 | 0.97 | 78.1% | 88.3% | 2474 |
| **CatBoost** | **1.30** | 2.11 | 0.85 | 80.2% | 91.4% | 2474 |

### İstatistiksel anlamlılık - v2 (bootstrap, 3000 tekrar, aynı test satırları üzerinde eşleştirilmiş)

| Karşılaştırma | Ort. MAE farkı | %95 CI | Sonuç |
|---|---|---|---|
| CatBoost vs Baseline 2 | 1.004dk | [0.922, 1.084] | **Kesinlikle anlamlı** |
| CatBoost vs XGBoost | 0.153dk | [0.122, 0.184] | **Anlamlı** (CatBoost tutarlı şekilde daha iyi) |
| XGBoost vs Baseline 2 | 0.852dk | [0.768, 0.933] | **Kesinlikle anlamlı** (v1'de anlamlı DEĞİLDİ - Bulgu 5 bunu da düzeltti) |
| CatBoost vs Baseline 1 | 1.061dk | [0.864, 1.274] | **Kesinlikle anlamlı** |

### "121 hattı kötü" / "uzun ETA kötü" sorunu da düzeldi

v1'de bulunan "121'in kötülüğü aslında uzun-ETA veri kıtlığının test
setinde 121'e yığılmasıydı" teşhisi doğrulandı - Bulgu 5 düzeltmesinden
sonra (CatBoost, test seti):

| Hat | MAE(dk) | ±2dk% |
|---|---|---|
| 121 | 1.00 | 87.7% |
| 515 | 1.47 | 75.9% |
| 761 | 0.80 | 91.9% |

Üç hat da artık tutarlı aralıkta (0.80-1.47dk), hiçbiri kopuk değil.
ETA aralığı bazında da belirgin iyileşme: 10-20dk MAE 8.4dk→5.3dk,
5-10dk ~2dk'ya indi. **20dk+ hâlâ zayıf ama artık sadece 4 test
satırı var** (istatistiksel yorum için yetersiz, ayrı ve küçük bir
sınırlama olarak not edilmeli - train setinde de sadece 39 satır var).

### Model seçimi ve gerekçe (v2, güncel)

- **Test MAE:** CatBoost (1.30dk) XGBoost'tan (1.45dk) ve her iki
  baseline'dan (2.30-2.36dk) belirgin şekilde düşük.
- **Test RMSE:** CatBoost (2.11dk) burada da XGBoost'tan (2.28dk) iyi -
  v1'deki ters yönlü RMSE anomalisi v2'de kayboldu, CatBoost artık her
  iki ana metrikte de önde.
- **İstatistiksel anlamlılık:** Her karşılaştırma (CatBoost/XGBoost vs
  her iki baseline, CatBoost vs XGBoost) %95 güvenle anlamlı - v1'in
  aksine artık hiçbir sonuç "şüpheli" değil.
- **Hat/ETA-aralığı stabilitesi:** Üç hat da tutarlı; sadece 20dk+
  aralığında (n=4) hâlâ zayıflık var ama bu artık izole, küçük bir
  sınırlama.
- **Inference süresi:** CatBoost ~3.6x daha hızlı (0.63µs vs 2.3µs/satır,
  9891 satırlık train setiyle yeniden ölçüldü). **Düzeltme:** Model
  boyutu v1'de "CatBoost 15x küçük" olarak yanlış raporlanmıştı - o
  rakam 577 satırlık küçük train setinden kalmıştı. 9891 satırlık
  gerçek train setiyle ikisi de büyüdü ve birbirine yakınsadı (CatBoost
  592KB, XGBoost 690KB, ~%14 fark) - boyut artık ayırt edici değil.

**Karar: CatBoost.** v1'deki gerekçe (native kategorik destek, hız,
boyut) v2'de de geçerli, üstelik artık istatistiksel üstünlük de çok
daha net ve sağlam.

**Dürüst sınırlama (güncel):** Kazanç artık gerçek ve büyük (baseline'a
göre ~1 dakika, sadece 14 saniye değil), ama **20dk+ ETA'lar** hâlâ
yeterince temsil edilmiyor (train: 39/9891 satır, test: 4/2474 satır) -
bu aralıkta model performansı hakkında güvenilir bir sonuç çıkarılamaz.
İleride en uzun güzergah uçlarına (örn. 761'in Karaburun/Mordoğan
terminalleri) daha yakın T0'lar hedefleyen ek toplama bu boşluğu
kapatabilir - Faz 3'ün mevcut kapsamında yapılmadı.

## SHAP Analizi (`app/ml/explain.py`)

Test seti üzerinde (2474 satır), hem XGBoost hem CatBoost (final model)
için `shap.TreeExplainer` ile hesaplandı. Sonuçlar iki model arasında
tutarlı:

| Feature | CatBoost ort. \|SHAP\| (dk) | Sıra |
|---|---|---|
| `distance_remaining_m` | 2.23 | 1 |
| `target_stop_id` | 0.75 | 2 |
| `progress_along_route` | 0.47 | 3 |
| `hour_of_day` | 0.17 | 4 |
| `speed_avg_5min_mps` | 0.14 | 5 |
| `line_no` | 0.14 | 6 |
| `recent_speed_mps` | 0.09 | 7 |

**Sorulara cevaplar:**
- **distance_remaining_m beklendiği kadar güçlü mü?** Evet, açık ara
  1. sırada (2.23dk) - v1'deki (896 satırlık dataset) tersine, burada
  `target_stop_id` onu geçmiyor. Bu, Bulgu 5 düzeltmesinin modelin
  doğru sinyale odaklanmasını sağladığının bağımsız bir kanıtı.
- **recent_speed ne kadar etkili?** Orta düzey (7. sıra, 0.09dk) -
  300sn'lik pencere (`speed_avg_5min_mps`, 5. sıra) 180sn'lik olandan
  (`recent_speed_mps`) biraz daha etkili.
- **Saat etkisi oluşuyor mu?** Evet, belirgin (`hour_of_day` 4. sırada,
  0.17dk) - `day_of_week` çok daha zayıf (9. sıra) çünkü dataset sadece
  4 farklı gün kapsıyor, model günler arası farkı güvenilir öğrenecek
  çeşitliliği görmedi.
- **Hat ve durak bilgisi ne kadar önemli?** `target_stop_id` (2. sıra)
  `line_no`'dan (6. sıra) çok daha güçlü - beklenen bir sonuç, çünkü
  durak kimliği rotanın o segmentine özgü tipik seyahat süresini
  (örn. trafik ışığı yoğunluğu, yol tipi) örtük olarak taşıyor,
  hat kimliği ise çok daha kaba bir sinyal.

Çıktı: `reports/shap-analysis.json` (ham değerler), `reports/shap-feature-importance.png` (grafik).

## Supervisor'a Bildirilmesi Önerilen Özet

> Veri toplama sırasında İzmir açık API'sinin bazı response'larında aynı
> `OtobusId`'nin (vehicle_id) iki farklı konum için birden
> döndürüldüğü tespit edildi - biri gerçek aracın konumu, diğeri
> güzergah dışında sabit kalan bir "hayalet" kayıt (muhtemelen servis
> dışı bir aracın son bilinen konumunun API'de askıda kalması). Bu,
> arrival detection'ın araç bazlı gruplamasını nadiren bozabiliyor; 1
> vakada (10 saatlik bir oturumda) fark edilip düzeltildi. Sistematik
> bir tarama yapılmadı, etki alanı sınırlı görünüyor ama sıfır değil.
>
> Ayrıca 761 hattının (uzun güzergah, ~71km) verisi büyük ölçüde tek
> bir güne yığıldı; bu hattın train/test değerlendirmesi diğer iki
> hatta göre daha az güvenilir olacak, raporda ayrıca belirtilecek.
>
> En önemlisi: arrival detection mantığı, bir aracın durağı geçip
> güzergahın tamamını kat ederek geri dönmesi (round-trip) durumunu
> ayırt edemediği için, mevcut "geçerli" training verisinin **%72'si**
> (2268/3164 satır) yanlış etiketlenmiş anormal derecede uzun (30
> dakika - 3+ saat) "yaklaşma pencerelerinden" üretilmişti. Bu satırlar
> tespit edilip REJECTED olarak işaretlendi; dataset 3164'ten 896
> geçerli satıra düştü. Hacim azaldı ama veri artık çok daha güvenilir.
> Kök neden (arrival detection'ın round-trip'i ayırt edememesi) henüz
> kod seviyesinde düzeltilmedi, sadece etkisi post-hoc filtrelendi.
>
> İlk model turunda (896 satır) CatBoost baseline'ı sadece ~14 saniyelik
> mütevazı bir farkla geçti ve iki model de uzun ETA'larda (10dk+)
> pratik olarak başarısızdı. Kök neden araştırılınca bunun da bir kod
> sorunu olduğu bulundu: arrival detection'da "yaklaşma" sayılmak için
> durağa 200m'den yakın olma şartı vardı (bizim kod sabitimiz, API'den
> gelmiyor) - bu, üretilen ETA'ların %90'ının 0-5dk'da yığılmasına yol
> açıyordu. Eşik 3km'ye çıkarılıp tüm training verisi (GPS ham verisine
> dokunmadan) yeniden üretildi: dataset 896'dan **15.425 satıra** çıktı,
> ayrıca bonus olarak **411 GOLD (HIGH-confidence) satır** ortaya çıktı
> (önceki v1-v3 denemelerinde 0-1 taneydi - asıl sorun cadence değil dar
> pencereymiş). Yeni sonuç: CatBoost test MAE 1.30dk (XGBoost 1.45dk,
> baseline'lar 2.30-2.36dk), fark artık ~1 dakika ve tüm karşılaştırmalar
> istatistiksel olarak kesin anlamlı. "121 hattı kötü" sorunu da
> düzeldi (üç hat da artık 0.80-1.47dk aralığında tutarlı). Kalan tek
> sınırlama: 20dk+ ETA'lar hâlâ yeterince temsil edilmiyor (test'te
> sadece 4 satır) - bu aralıkta güvenilir bir sonuç yok.

## Sırada Ne Var (Faz 3 devam)

1. ~~Train/Validation/Test split scripti~~ - `app/ml/split.py`,
   `--per-line` modu. Bulgu 5 sonrası son kez çalıştırıldı
   (`reports/split-report-20260817-v3-widened.md`). **Tamam.**
2. ~~Feature engineering scripti~~ - `app/ml/features.py`. **Tamam.**
3. ~~XGBoost + CatBoost model eğitimi~~ - `app/ml/train_xgboost.py`,
   `app/ml/train_catboost.py`. **Tamam** (v2 sonuçları güncel).
4. ~~Baseline karşılaştırması, model seçim gerekçesi~~ - `app/ml/baselines.py`
   + bootstrap anlamlılık testi. **Tamam.**
5. **SHAP analizi** - henüz yapılmadı, sırada.
6. Final rapor (repo/commit SHA, veri toplama özeti, tüm bulgular,
   sonuçlar, seçilen model gerekçesi) - henüz yazılmadı.
7. ~~`inference.py`~~ - yazıldı, tek arac/durak için canlı tahmin
   üretiyor. Test sırasında önemli bir sınırlama bulundu: model sadece
   `distance_remaining_m <= ~3200m` için güvenilir (COARSE_APPROACH_WINDOW_M
   nedeniyle train setinin doğal sınırı) - bunun dışında sorgulanırsa
   fiziksel olarak anlamsız sonuç üretebiliyor, script artık bunu
   tespit edip uyarıyor. Detay: `docs/faz3-final-raporu.md` madde 12.
8. `app/ml/` pipeline dosyaları TAMAM: `__init__.py`, `dataset.py`,
   `features.py`, `split.py`, `evaluate.py`, `baselines.py`,
   `train_xgboost.py`, `train_catboost.py`, `explain.py`, `inference.py`.

**Kalan bilinen sınırlamalar:** (a) 20dk+ ETA'lar dataset'te az temsil
ediliyor (test'te 4 satır) - bu aralıkta model güvenilir değil; (b)
761 hattının verisi hâlâ ağırlıklı olarak 16-17 Ağustos'tan geliyor
(gün-arası genelleme sınırlı); (c) akşam yoğun saat (17:00-19:00) ve
hafta sonu (Cumartesi) hiç toplanmadı.
