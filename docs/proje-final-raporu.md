# İzmir Otobüs ETA Analiz Sistemi — Proje Final Raporu

**Tarih:** 20 Ağustos 2026
**Repository:** https://github.com/ahmtumut/izmir-bus-eta-ml
**Faz 1-3 son commit (SHA):** `75bccceae06eca8b27b0589025767a0f2fd687b8` ("Faz 3: inference.py eklendi, pipeline tamamlandı")
**Faz 4 commit (SHA):** `7453ef3` ("Faz 4: canlı/replay 3D web görselleştirme (MapLibre+Three.js) + MLOps eklentileri")
**Not:** Faz 2/3 kapanış raporlarında geçen SHA'lar (`c0efcd806...`, `e7414b833...`) 40 hex karakterden uzun görünüyor,
muhtemelen dokümantasyon sırasında transkripsiyon hatası — bu rapor `git log`'dan doğrudan alınan güncel SHA'yı esas alır.

> ✅ **Repo durumu güncellendi:** Faz 4 çalışması (`web/`, `app/api/`, `scripts/run_collector_supervisor.py`,
> `app/ml/ablation_vehicle_id.py`, `scripts/import_gtfs_route_shapes.py` ve `app/ml/features.py`,
> `app/ml/inference.py`, `scripts/detect_arrival_events.py`, `scripts/map_match_observations.py`,
> `scripts/run_dual_collector.py` üzerindeki değişiklikler) `7453ef3` commit'iyle repoya işlendi.
> Bu nedenle repo HEAD'i artık hem Faz 1-3 hem Faz 4'ü yansıtıyor.

---

## 1. Proje Özeti

İzmir'de ESHOT otobüslerinin gerçek zamanlı GPS verisinden yola çıkarak durağa varış süresini (ETA)
tahmin eden uçtan uca bir sistem geliştirildi: ham API verisi → PostgreSQL/PostGIS altyapısı →
map-matching → arrival-event tespiti → ETA ground-truth üretimi → makine öğrenmesi modeli (XGBoost/CatBoost)
→ (plan dışı ek) canlı/replay 3D web görselleştirmesi.

Proje üç resmi faz olarak tanımlandı ve tamamlandı; bu oturumda ayrıca görev tanımının parçası olmayan
ama kullanıcı isteğiyle eklenen bir Faz 4 (Three.js/MapLibre görselleştirme + MLOps eklentileri) yapıldı.

| Faz | Konu | Durum |
|---|---|---|
| Faz 1 | Veri kaynağı doğrulama, collector altyapısı | ✅ Tamamlandı |
| Faz 2 | PostGIS, map-matching, arrival event, ETA ground-truth | ✅ Tamamlandı |
| Faz 2 Kapanış | 5 düzeltme maddesi | ✅ Tamamlandı |
| Faz 3 | Veri büyütme + XGBoost/CatBoost ETA modeli | ✅ Tamamlandı |
| Faz 4 (plan dışı) | Canlı/replay 3D web görselleştirme, MLOps eklentileri | ✅ Tamamlandı, commit `7453ef3` |

---

## 2. Faz 1 — Veri Kaynağı Doğrulama ve Collector Altyapısı

### 2.1 Pilot Hat Seçimi (gerçek API gözlemiyle doğrulandı)

Görev metninin istediği gibi hatlar rastgele değil, önce varsayımla (kısa/orta/uzun karakter), sonra
60 dakikalık gerçek API freshness testiyle doğrulanarak seçildi:

| Hat | Tip | Ortalama anlık araç | Toplam farklı araç (60dk) | Sonuç |
|---|---|---|---|---|
| 515 | Kısa/yoğun şehir içi | 19.5 | 10 | CANLI |
| 121 | Orta mesafe | 8.6 | 4 | CANLI |
| 761 | Uzun güzergah (~71km) | 3.0 | 2 | CANLI |

Sonuçlar başlangıç beklentisini doğruladı: 515 en yoğun, 761 en seyrek. Üç hat da veri akışının
gerçekten değiştiğini (CANLI) kanıtladı. Bilinen kısıt olarak not düşüldü: 761'in düşük araç sayısı
ilerleyen fazlarda daha az örneklem anlamına gelecekti — bu öngörü Faz 3 EDA'sında da doğrulandı
(761 verisi büyük ölçüde tek bir 2 günlük pencereden geldi).

### 2.2 Bilinen Riskler (`docs/known-risks.md`)

Faz 1 sırasında 7 risk dokümante edildi, en kritikleri:
- **Dokümante edilmemiş rate limit** — API'de resmi bir limit belirtilmiyor.
- **Virgüllü ondalık koordinatlar** ve **(0,0) null-island sentinel** — ayrıştırma/temizlik gerektirdi.
- **Response-içi "trail point" fenomeni** — aynı `OtobusId` bir response içinde birden fazla kez, farklı
  koordinatlarla görünebiliyor; hangisinin "güncel" olduğu belirsiz. Hareket-metriği hesaplamasında bir
  hata bulunup düzeltildi.
- **Sabitlik belirsizliği** — bir aracın gerçekten duruyor mu yoksa GPS'i mi donmuş, ayırt edilemiyor
  (bu belirsizlik Faz 2'de `position_quality` sınıflandırmasıyla resmi olarak ele alındı, "ilk nokta
  güncel" varsayımı YAPILMADI).
- 25.5 saatlik ana koleksiyon turunda 4 "donmuş" araç, farklı `KalanDurakSayisi` değerleriyle
  ilişkilendirildi — yeni hipotez: GPS koordinat alanı donarken trip-progress verisinin bağımsız
  güncellenebileceği. Bu hipotez daha sonraki fazlarda ayrıca doğrulanmadı, açık bir gözlem olarak kaldı.

### 2.3 Öneriler (`docs/faz2-onerileri.md`)

Faz 1 sonunda 9 öneri önceliklendirildi (Yüksek: GPS freeze hipotezinin doğrulanması, trail-point
anlamının çözülmesi, durak koordinat eşleştirmesinin tamamlanması; Orta: resmi rate-limit doğrulaması,
`KalanDurakSayisi`'nin feature olarak kullanılması, ID-reuse araştırması; Düşük: graceful shutdown,
çoklu-process ölçekleme, otomatik kalite raporları). Bunların çoğu Faz 2/3'te ele alındı — özellikle
durak eşleştirmesi (`route_stop_sequence`), `KalanDurakSayisi` support-API cross-validation olarak
kullanıldı.

---

## 3. Faz 2 — PostgreSQL/PostGIS, Map-Matching, ETA Ground-Truth

### 3.1 Altyapı

Docker Compose ile PostGIS 16, 6 migration dosyasıyla şema kuruldu (`ingestion_runs`, `raw_snapshots`,
`stops` — 11.783 durak, `routes`, `route_shape_points`, `route_stop_sequence`, `vehicle_observations`,
`supporting_api_observations`, `arrival_events`, `eta_training_samples`, `data_quality_events`).

### 3.2 Kritik Tasarım Kararları (bilinçli olarak Faz 3'e taşındı)

1. **"İlk nokta güncel" varsayımı yapılmadı** — GPS kalite sınıflandırması run-length analiziyle yapıldı,
   belirsiz durumlar `UNKNOWN_POSITION` olarak bırakıldı, zorla sınıflandırılmadı.
2. **Rota dışı gözlemler silinmedi, sadece flag'lendi** (`map_match_quality=REJECTED`) — örn. bir araç
   60 dakika boyunca hiç 515 güzergahına girmedi, bu veri korunarak işaretlendi, silinmedi.
3. **Future-leakage koruması DB seviyesinde**: `eta_training_samples` tablosunda
   `CHECK (observed_at < actual_arrival_at)` constraint'i var.
4. **Support API cross-validation SADECE aynı `vehicle_id` + aynı `target_stop_id` için** — bu kural bir
   kez yanlış uygulanıp düzeltildi (bkz. `scripts/detect_arrival_events.py`).

### 3.3 Faz 2 Kapanış Düzeltmeleri

Faz 2'nin resmi kapanışından önce 5 düzeltme maddesi uygulandı: `source_direction` kalıcılığı,
idempotency garantisi, sıkılaştırılmış ETA filtreleri, leave-one-out ile düzeltilmiş segment-medyan
baseline'ı, performans/test regresyon düzeltmeleri. Bu düzeltmeler olmadan Faz 3'e geçilmemesi
CLAUDE.md'de açık bir kabul kriteriydi — düzeltmeler `c0efcd8` civarı commit'lerde tamamlandı.

### 3.4 Faz 2 Sonundaki Veri Durumu (Faz 3 başlangıç noktası)

Sadece **1 gözlem turu**: 60 dakika, 12 araç, 3 pilot hat → **94 eta_training_samples, tamamı SILVER
kalite (GOLD=0, REJECTED=0)**. Bu, pipeline'ın uçtan uca çalıştığını kanıtladı ama istatistiksel olarak
güvenilir bir model eğitmek için yetersizdi — raporun kendisi bunu açıkça belirtti ve Faz 3'e "önce veri
büyütülmeli" şartıyla geçildi.

**Baseline sonuçları (94 satır üzerinde, ön-gösterge niteliğinde):**
- Baseline 1 (mesafe/hız): MAE=7.82dk, RMSE=23.41dk, ±2dk doğruluk=%87.8
- Baseline 2 (segment medyanı): **GÜVENİLMEZ** olarak işaretlendi — çoğu segment n=1-2 örneklem, leave-one-out
  uygulanmadan model kendi test değerini geri veriyordu.

---

## 4. Faz 3 — Veri Büyütme ve ETA Makine Öğrenmesi Modelleri

### 4.1 Veri Büyütme

12–17 Ağustos 2026 arasında **11 toplama oturumu**, aynı 3 pilot hat (515, 121, 761) üzerinden farklı
gün ve saat dilimlerini kapsayacak şekilde yürütüldü. Sonuç: **27.749 ham GPS gözlemi**, final ML
dataset'inde **15.425 eta_training_samples satırı**, **1.792 benzersiz arrival_event**.

**Bilinen veri sınırlamaları (görev metninde talep edilen dürüst raporlama gereği açıkça belirtiliyor):**
- Akşam yoğun saat (17:00–19:00) ve Cumartesi hiç toplanmadı.
- 761 hattının verisi ağırlıklı olarak 16-17 Ağustos'a ait (Faz 1'deki düşük-örneklem öngörüsü doğrulandı).
- `distance_remaining_m` eğitim verisinde ~3200m'yi hiç geçmiyor (`COARSE_APPROACH_WINDOW_M=3000`
  sabiti nedeniyle) — model bu aralığın dışında güvenilir değil, bu kısıt `inference.py`'de açıkça
  kontrol ediliyor (sessizce yanlış tahmin üretmiyor).

### 4.2 GOLD Label Çalışması

Görev talimatına uygun olarak tüm durakların sürekli izlenmesi yerine, seçilmiş doğrulama duraklarında
kontrollü validation pencereleri açılarak GPS trajectory + `KalanDurakSayisi` trendi birlikte toplandı.
Sonuç: **411 satır GOLD/HIGH-confidence, 41 benzersiz arrival event'ten** üretildi — amaç tüm dataset'i
GOLD yapmak değil, arrival-detection yönteminin doğruluğunu gösteren bir alt-küme oluşturmaktı; bu
hedefe ulaşıldı.

### 4.3 Kritik Veri Kalitesi Bulgusu

5 önemli veri kalitesi bulgusu düzeltildi; en önemlisi **Bulgu 5**: `COARSE_APPROACH_WINDOW_M`
200m'den 3000m'ye çıkarılınca dataset **896 → 15.425 satıra** çıktı. Bu düzeltmeden önce
model-baseline karşılaştırması istatistiksel olarak **anlamsızdı** — bu bulgu raporlarda açıkça
belirtiliyor, gizlenmiyor.

### 4.4 Train/Validation/Test Split

Görev talimatına tam uygun şekilde: satır bazlı rastgele split değil, **`arrival_event_id` bazında**
gruplama + **zamansal sıralı** ayrım (erken dönem→train, orta→validation, son dönem→test), hat bazında
uygulandı (`scripts/split.py --per-line`). Aynı arrival event'in sample'ları asla iki farklı split'e
bölünmedi.

### 4.5 Feature Seti

`line_no`, `direction`, `target_stop_id`, `distance_remaining_m`, `progress_along_route`,
`recent_speed_mps`, `hour_of_day`, `day_of_week` + ek olarak son-3-gözlem ortalama hız/std, son-5dk
ortalama ilerleme hızı, `time_since_previous_observation`, `distance_to_route_m`. **`vehicle_id` ana
modelde kullanılmadı** (talimat gereği — araç kimliğini ezberlemeyen, genellenebilir bir model hedefi).

### 4.6 Model Sonuçları

| Model | MAE | RMSE | ±2dk doğruluk |
|---|---|---|---|
| Baseline 1 (mesafe/hız) | daha yüksek | daha yüksek | daha düşük |
| Baseline 2 (segment medyanı, düzeltilmiş) | daha yüksek | daha yüksek | daha düşük |
| XGBoost | CatBoost'a yakın, biraz zayıf | — | — |
| **CatBoost (final model)** | **1.30 dk** | **2.11 dk** | **%80.2** |

CatBoost, XGBoost'u ve her iki baseline'ı **bootstrap anlamlılık testiyle (%95 CI) istatistiksel olarak
anlamlı** şekilde geçti. Seçim gerekçesi tek bir metrikle değil; hat bazında stabilite, uzun-ETA
performansı, inference süresi ve model boyutu birlikte değerlendirilerek yapıldı (görev talimatının
"tek bir skorla karar verme" şartına uygun).

### 4.7 Açıklanabilirlik (SHAP)

En güçlü feature: `distance_remaining_m` (SHAP |değer| 2.23dk), ardından `target_stop_id` (0.75dk),
`progress_along_route` (0.47dk). Beklenen fiziksel ilişki (mesafe azaldıkça ETA azalır) doğrulandı;
durak kimliğinin de anlamlı katkısı olduğu görüldü (muhtemelen o duraktaki tipik trafik/yol
karakteristiğini temsil ediyor).

### 4.8 Ablation Testi — `vehicle_id` (Faz 3 sonrası, bu oturumda eklendi)

`app/ml/ablation_vehicle_id.py`: aynı split, aynı hiperparametreler kullanılarak `vehicle_id`'nin
feature olarak eklenmesinin etkisi kontrollü şekilde ölçüldü (raporlanmış final model hiperparametreleri
aynen tekrar kullanılıyor, sadece "eklendi mi eklenmedi mi" farkı izole ediliyor). Script,
%5 eşik üzerinden otomatik yorum üretiyor: MAE önemli ölçüde düşerse bu araç-kimliği ezberlemesine işaret
eder (mevcut "vehicle_id dışarıda bırakma" kararını doğrular ama endişe verici bir sinyaldir); önemli
ölçüde değişmez ya da kötüleşirse, kararı farklı bir gerekçeyle (faydasız/karmaşıklık artırıcı feature)
doğrular. *(Bu betik bu oturumda yazıldı; sonuç `reports/ablation-vehicle-id.json`'a kaydediliyor —
gerçek sayısal sonucu görmek için betiğin çalıştırılmış olması ve raporun okunması gerekir; bu final
raporun hazırlandığı anda çıktı dosyasının içeriği doğrulanmadı, bu nedenle burada sayısal sonuç
iddia edilmiyor.)*

### 4.9 Tekrarlanabilirlik

`app/ml/` altında modüler pipeline (`dataset.py`, `features.py`, `split.py`, `train_xgboost.py`,
`train_catboost.py`, `evaluate.py`, `explain.py`, `inference.py`), `models/` ve `reports/` içinde
model dosyası + feature listesi + hiperparametreler + dataset snapshot + git commit SHA + metrics.json
saklanıyor. Migration 008 ile `dataset_split` kolonu eklendi.

---

## 5. Faz 4 (plan dışı) — Canlı/Replay 3D Web Görselleştirmesi

Bu faz orijinal görev tanımının **parçası değildi**; kullanıcının bu oturumda ayrıca istediği "projeyi
Three.js ile görselleştir" talebiyle başladı ve kapsamı iteratif olarak netleşti. Kod tamamlandı ve
`7453ef3` commit'iyle repoya işlendi.

### 5.1 Backend (`app/api/`)

FastAPI tabanlı yeni bir API katmanı: replay modu için geçmiş oturum/gözlem/arrival/ETA endpoint'leri,
canlı mod için `app/api/live.py` (`/api/live/status`, `/api/live/observations`) — collector'ın aktif
olup olmadığını `ingestion_runs.ended_at IS NULL` + son gözlemin tazeliği (≤90sn) birlikte kontrol
ederek belirliyor. Dış API'ye ek çağrı eklemiyor, sadece iç Postgres'i sorguluyor (rate-limit riski yok).

### 5.2 Frontend (`web/`)

İlk sürüm Leaflet (düz 2D) + üzerine gömülü Three.js otobüs katmanıydı; bu, haritanın hiç eğilememesi
(tilt yok) nedeniyle sınırlı bir "3D" deneyimiydi. **MapLibre GL JS + OpenFreeMap**'e (ücretsiz, API-key
gerektirmeyen vektör tile kaynağı) geçilerek gerçek `pitch`/`bearing` desteği kazanıldı; Three.js sahnesi
`CustomLayerInterface` üzerinden haritanın kendi projeksiyon matrisiyle her frame senkronize ediliyor —
bu, "harita düz kalıp otobüs yoldan kayması" sınıfı hataları yapısal olarak ortadan kaldırıyor.

Özellikler: replay modu (geçmiş oturum seçimi, scrubber, hız kontrolü), canlı mod (collector durum
göstergesi, 15sn polling), araç/hat/durak/arrival-event/ETA-etiket katmanları, araç tıklanınca detay
paneli (son gözlem zamanı, hız sparkline, güven), mobil uyumlu responsive panel düzeni, ayrı bir
`dashboard.html`/`dashboard.js` (model canlı performans/tahmin-hata görselleştirmesi).

### 5.3 Operasyonel Eklentiler

- `scripts/run_collector_supervisor.py` — collector'ı sürekli/kalıcı çalıştırmak için denetleyici script.
- Canlı map-matching artık collector döngüsüne gömüldü (`scripts/map_match_observations.py`'a
  `only_unmatched` parametresi eklendi) — böylece Faz 2/3'teki gibi ayrı bir offline script çalıştırmaya
  gerek kalmadan, her collector cycle'ı kendi gözlemlerini anında map-match ediyor. Bu, sadece Faz 4'ü
  değil, gelecekteki tüm collector çalıştırmalarını iyileştiren kalıcı bir altyapı düzeltmesi.
- `scripts/import_gtfs_route_shapes.py` — GTFS kaynağından route geometrisi normalizasyonu.

### 5.4 Faz 4 İçin Açık Nokta

Faz 4'ün kapsamı bir plan dosyasında (`sprightly-sprouting-moth.md`) adım adım genişletildi (önce
canlı map-matching kalıcılığı, sonra görsel cila, sonra analitik katman) — kullanıcı onayına dayalı,
iteratif ilerleyen bir çalışma tarzıydı, resmi bir kabul kriteri seti yoktu. Kod `7453ef3` ile commit
edildi; ancak Faz 1-3'teki gibi resmi bir "kapanış raporu" (ayrı doküman) henüz yazılmadı — bu rapor o
işlevi de üstleniyor.

---

## 6. Genel Açık Riskler ve Sınırlamalar (tüm fazlar)

1. **Faz 4 için ayrı bir resmi kapanış raporu yok** — kod `7453ef3` ile commit edildi ve repo HEAD'i
   artık Faz 4'ü yansıtıyor, ama Faz 1-3'teki gibi ayrı bir kapanış dokümanı henüz yazılmadı.
2. **Akşam yoğun saat ve Cumartesi verisi hiç toplanmadı** — model bu koşullar için doğrulanmadı.
3. **`distance_remaining_m` >3200m aralığında model güvenilir değil** (COARSE_APPROACH_WINDOW_M kısıtı) —
   `inference.py` bunu açıkça flag'liyor, sessizce yanlış tahmin üretmiyor.
4. **761 hattı düşük örneklemli** — hem Faz 1'de öngörüldü hem Faz 3'te doğrulandı, hat-bazlı model
   performansı yorumlanırken göz önünde bulundurulmalı.
5. **GPS "freeze" hipotezi** (Faz 1'de gözlendi) hiçbir fazda kesin olarak doğrulanmadı/çürütülmedi —
   açık bir araştırma sorusu olarak kalıyor.
6. Ablation testi (`vehicle_id`) kodu yazıldı ama bu raporun hazırlandığı anda sayısal sonucu
   doğrulanmadı — çalıştırılıp `reports/ablation-vehicle-id.json` okunmalı.

---

## 7. Sonuç ve Öneriler

Proje, orijinal 3 fazlık görev tanımının **tamamını** karşılıyor: dürüst bir veri-kaynağı doğrulaması ile
başladı, sağlam bir coğrafi veri altyapısı kurdu, veri kalitesi sorunlarını gizlemeden düzeltti, ve
sonunda iki baseline'ı istatistiksel olarak anlamlı şekilde geçen, açıklanabilir bir ML modeli üretti.
Faz 3'ün "94 satır üzerinden model başarısı ilan etme" kısıtı ihlal edilmedi — model eğitimi ancak veri
15.425 satıra büyütüldükten ve kritik `COARSE_APPROACH_WINDOW_M` hatası düzeltildikten sonra yapıldı.

Buna ek olarak, görev tanımının dışında, kullanıcı talebiyle kapsamlı bir canlı/replay 3D görselleştirme
katmanı ve destekleyici MLOps araçları (collector supervisor, ablation testi, GTFS entegrasyonu)
geliştirildi.

**Önerilen sıradaki adımlar:**
1. Faz 4 için ayrı, resmi bir kapanış raporu yazmak (Faz 1-3 formatına uygun).
2. Eksik zaman dilimlerini (akşam yoğun saat, Cumartesi) kapsayan ek bir veri toplama turu.
3. `ablation-vehicle-id.json` sonucunu okuyup Faz 3 raporuna resmi olarak eklemek.
4. GPS freeze hipotezini doğrulamak için hedefli bir inceleme (Faz 1'den beri açık).
