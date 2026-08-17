# Faz 3 Final Raporu — ETA Makine Öğrenmesi Modeli

**Tarih:** 17 Ağustos 2026
**Repository:** https://github.com/ahmtumut/izmir-bus-eta-ml
**Final commit SHA:** `e7414b8337dba8180416437655e8d06d693f017f`
(Faz 3 çalışmasının tamamı - kod, migration, model dosyaları, rapor
dosyaları - bu commit'te)

Bu doküman, CLAUDE.md'nin Faz 3 kabul kriterinde istenen tüm kalemleri
tek bir yerde toplar. Ayrıntılı keşif/hata-ayıklama süreci (v1→v3
GOLD denemeleri, Bulgu 1-5) için bkz.
[docs/faz3-veri-toplama-ve-gold-bulgulari.md](faz3-veri-toplama-ve-gold-bulgulari.md).

---

## 1. Veri Toplama Özeti

3 pilot hat (515, 121, 761), 12-17 Ağustos 2026 arası, 11 gerçek toplama
oturumu (`ingestion_run_id` 3, 28-38), farklı gün/saat dilimlerini
kapsayacak şekilde (sabah/öğle/öğleden sonra × 4 farklı gün: Çar/Per/Cum
+ Pazar 10 saatlik sürekli oturum + Pazartesi 761'e özel oturum).

**Bilinen kapsam sınırlaması:** akşam yoğun saat (17:00-19:00) ve
Cumartesi hiç toplanmadı; dataset saat dağılımı öğle-öğleden sonrasına
ağırlıklı.

## 2. Faz 2 Kapanış Düzeltmeleri

Faz 3 başlamadan önce Faz 2 kapanışında tamamlanmıştı (bkz.
`docs/faz2-kapanis-raporu.md`, `docs/faz2-kapanis-duzeltmeleri.md`):
source_direction bazlı map-matching, idempotent script'ler, sıkı ETA
filtreleri, leave-one-out baseline uyarısı, performans/test regresyon
düzeltmeleri.

## 3. Dataset Kalite Raporu

Ham GPS observation: 27.749 (`vehicle_observations`).

Map-match kalite dağılımı: GOOD %39.5, DEGRADED %2.6, NULL(null-island)
%7.8, REJECTED kalan - REJECTED'lerin çoğu `SOURCE_DIRECTION_UNKNOWN`
(API'nin `HattinYonu` alanının boş gelmesi) kaynaklı, tasarım gereği
sessizce düzeltilmiyor (bkz. CLAUDE.md kritik tasarım kararı #2).

**Beş önemli veri kalitesi bulgusu tespit edilip düzeltildi** (tam
detay için bkz. bulgular dokümanı):

1. **GOLD/HIGH-confidence üretimi** - arrival detection cadence'i 3 kez
   revize edildi (rate-limit → derinlik → bağımsız cadence).
2. **Response-içi ID çakışması** - İzmir API'sinin aynı `OtobusId`'yi
   tek response'ta iki farklı konuma (biri gerçek, biri "hayalet" statik
   kayıt) atadığı tespit edildi; 1 vaka düzeltildi.
3. **Zamansal split'te hat dengesizliği** - 761 hattının verisinin
   tamamına yakını tek güne yığılmıştı; hat-bazında split'e geçilerek
   ve 761'e özel ek toplamayla azaltıldı.
4. **Sistemik round-trip arrival-window hatası** - araçların durağı
   geçip güzergahın tamamını kat edip geri dönmesi, tek bir anormal
   uzun (30dk-3+saat) "yaklaşma penceresi" olarak yanlış algılanıyordu;
   sistematik taramada dataset'in büyük kısmını etkilediği bulundu,
   1800sn eşiğiyle filtrelendi.
5. **T0 aday penceresinin darlığı (kök neden)** - `COARSE_APPROACH_WINDOW_M`
   sabiti (200m, bizim kod tasarımımız, API'den gelmiyor) T0 adaylarının
   %90'ının 0-5dk ETA aralığında yığılmasına yol açıyordu. 3000m'ye
   çıkarılıp tüm türetilmiş veri (GPS ham veri korunarak) yeniden
   üretildi: **896 → 15.425 geçerli satır**, ayrıca 411 GOLD satır
   bonus olarak ortaya çıktı.

**Final dataset:** 15.425 `eta_training_samples` satırı, 1.792 benzersiz
`arrival_event`. Satır/event ayrımı önemli - bir event birden fazla T0
üretebiliyor (bkz. `scripts/generate_eta_training_samples.py`).

| Hat | Satır | Label quality |
|---|---|---|
| 515 | 10.071 | SILVER ağırlıklı |
| 121 | 4.334 | SILVER ağırlıklı |
| 761 | 1.020 | SILVER ağırlıklı |
| **GOLD (HIGH-confidence)** | **411** | 41 benzersiz event'ten |

ETA aralığı dağılımı: 0-5dk %55.8, 5-10dk %32.5, 10-20dk %11.5, 20dk+
%0.25 (**bilinen sınırlama** - bu aralıkta yeterli veri yok).

## 4. Train/Validation/Test Split Raporu

`app/ml/split.py --per-line`: her hat KENDİ zaman ekseninde ayrı ayrı
zamansal sıralı split edildi (erken→train, orta→validation, geç→test,
~%70/15/15 event oranı), sonra birleştirildi. Bir `arrival_event`'in
tüm satırları HER ZAMAN aynı split'te (leakage koruması).
`label_quality='REJECTED'` satırlar split dışı bırakıldı.

| Split | Event | Satır | Zaman aralığı |
|---|---|---|---|
| Train | 1.254 | 9.891 | 2026-08-12 → 2026-08-14 |
| Validation | 268 | 3.060 | 2026-08-14 → 2026-08-17 |
| Test | 270 | 2.474 | 2026-08-16 → 2026-08-17 |

Hiperparametre araması ve model seçimi SADECE train+validation üzerinde
yapıldı; test setine model seçimi tamamlanana kadar dokunulmadı.

## 5. Baseline Sonuçları

`app/ml/baselines.py`. Baseline 2 (tarihsel medyan) artık gerçek bir
leave-out - medyanlar SADECE train'den hesaplanıp val/test'e uygulandı
(Faz 2'deki güvenilmezlik sorunu düzeltildi).

| Baseline | Test MAE(dk) | Test RMSE(dk) |
|---|---|---|
| 1: mesafe/hız | 2.36 | 5.68 |
| 2: tarihsel medyan (leave-out) | 2.30 | 3.03 |

## 6. XGBoost Sonucu

`app/ml/train_xgboost.py` - CPU, `tree_method=hist`, `device=cpu`,
`n_jobs=12`, 20 adaylık randomized search (train+validation).

- Test MAE: **1.45dk**, RMSE: 2.28dk, ±2dk: %78.1
- Eğitim süresi (final model): 0.54sn, arama süresi: 29.3sn
- Inference: ~2.3µs/satır
- Model boyutu: 690KB

## 7. CatBoost Sonucu

`app/ml/train_catboost.py` - CPU (`task_type=CPU`), `thread_count=12`,
kategorik feature'lar (`line_no`, `direction`, `target_stop_id`) native
`cat_features` ile verildi, 20 adaylık randomized search.

- Test MAE: **1.30dk**, RMSE: 2.11dk, ±2dk: %80.2
- Eğitim süresi (final model): 8.60sn, arama süresi: 240.6sn (~4dk)
- Inference: ~0.63µs/satır
- Model boyutu: 592KB

## 8. Karşılaştırma Tablosu

| Model | MAE(dk) | RMSE(dk) | ±1dk% | ±2dk% | ±3dk% |
|---|---|---|---|---|---|
| Baseline 1 (mesafe/hız) | 2.36 | 5.68 | 46.7% | 69.2% | 81.3% |
| Baseline 2 (tarihsel medyan) | 2.30 | 3.03 | 27.1% | 51.2% | 71.0% |
| XGBoost | 1.45 | 2.28 | 51.0% | 78.1% | 88.3% |
| **CatBoost** | **1.30** | **2.11** | **56.3%** | **80.2%** | **91.4%** |

**İstatistiksel anlamlılık** (bootstrap, 3000 tekrar, aynı test satırları
üzerinde eşleştirilmiş):

| Karşılaştırma | Ort. fark (dk) | %95 CI | Anlamlı mı? |
|---|---|---|---|
| CatBoost vs Baseline 2 | 1.004 | [0.922, 1.084] | Evet |
| CatBoost vs XGBoost | 0.153 | [0.122, 0.184] | Evet |
| XGBoost vs Baseline 2 | 0.852 | [0.768, 0.933] | Evet |
| CatBoost vs Baseline 1 | 1.061 | [0.864, 1.274] | Evet |

Her iki model de her iki baseline'ı istatistiksel olarak anlamlı şekilde
geçiyor - bu, dataset'in ilk (896 satırlık, Bulgu 5 öncesi) versiyonunda
GEÇERLİ DEĞİLDİ (XGBoost'un baseline üstünlüğü o zaman anlamsızdı).

### Kırılımlar (CatBoost, test seti)

| Hat | MAE(dk) | ±2dk% |
|---|---|---|
| 121 | 1.00 | 87.7% |
| 515 | 1.47 | 75.9% |
| 761 | 0.80 | 91.9% |

| ETA aralığı | MAE(dk) | n |
|---|---|---|
| 0-5dk | 0.89 | 1597 |
| 5-10dk | 1.76 | 822 |
| 10-20dk | 5.35 | 51 |
| 20+dk | 16.54 | 4 |

| Label quality | MAE(dk) | n |
|---|---|---|
| GOLD | 1.25 | 84 |
| SILVER | 1.30 | 2390 |

## 9. Feature Importance / SHAP Analizi

`app/ml/explain.py` - `shap.TreeExplainer`, test seti (2474 satır).

| Feature | CatBoost ort. \|SHAP\| (dk) |
|---|---|
| `distance_remaining_m` | 2.23 |
| `target_stop_id` | 0.75 |
| `progress_along_route` | 0.47 |
| `hour_of_day` | 0.17 |
| `speed_avg_5min_mps` | 0.14 |
| `line_no` | 0.14 |
| `recent_speed_mps` | 0.09 |

- **distance_remaining_m** beklendiği gibi en güçlü sinyal (1. sıra) -
  Bulgu 5 düzeltmesinden önce bu SIRADA DEĞİLDİ (`target_stop_id`
  önündeydi), düzeltmenin modelin doğru sinyale yöneldiğinin bağımsız
  kanıtı.
- **recent_speed** orta düzeyde etkili (7. sıra); 300sn'lik pencere
  180sn'likten biraz daha güçlü.
- **Saat etkisi** belirgin (`hour_of_day` 4. sırada); `day_of_week`
  zayıf çünkü dataset sadece 4 gün kapsıyor.
- **Durak bilgisi** (`target_stop_id`, 2. sıra) hat bilgisinden
  (`line_no`, 6. sıra) çok daha güçlü - durak kimliği segment-özgü
  tipik seyahat süresini örtük taşıyor.

Grafik: `reports/shap-feature-importance.png`.

## 10. Eğitim/Inference Süreleri ve Model Boyutu

| | XGBoost | CatBoost |
|---|---|---|
| Hiperparametre arama süresi | 29.3sn | 240.6sn (~4dk) |
| Final eğitim süresi | 0.54sn | 8.60sn |
| Inference (satır başı) | ~2.3µs | ~0.63µs |
| Model dosya boyutu | 690KB | 592KB |

(9891 satırlık train seti üzerinden - v1'deki 577 satırlık ilk ölçümler,
çok daha küçük veriyle yapıldığı için burada referans alınmadı.)

Donanım: Intel Core i9-13900H, CPU-only (`device=cpu`/`task_type=CPU`),
12 thread (`n_jobs`/`thread_count`), Intel Iris Xe GPU kullanılmadı
(gorev talimatı gereği).

## 11. Final Model ve Seçim Gerekçesi

**Seçilen model: CatBoost.**

Gerekçe (tek bir skora değil, birlikte değerlendirilen kriterlere göre):

1. **Test MAE ve RMSE'nin ikisinde de önde** (1.30dk / 2.11dk vs
   XGBoost'un 1.45dk / 2.28dk) - v1'deki (896 satır) RMSE anomalisi
   (XGBoost'un RMSE'de öne geçmesi) v2'de kayboldu.
2. **İstatistiksel anlamlılık** - CatBoost'un hem baseline'lara hem
   XGBoost'a üstünlüğü bootstrap ile %95 güvenle doğrulandı.
3. **Kategorik feature'ları native işlemesi** (`line_no`, `direction`,
   `target_stop_id`) - bu veri yapısına daha uygun bir tasarım.
4. **Inference hızı ~3.6x daha iyi** (0.63µs vs 2.3µs/satır) - model
   boyutu ise pratik olarak birbirine yakın (592KB vs 690KB, ~%14 fark)
   ve hiperparametre araması CatBoost'ta belirgin şekilde daha yavaş
   (240.6sn vs 29.3sn) - bu tek seferlik bir maliyet olduğu için
   deployment kararını etkilemiyor, ama "CatBoost her açıdan daha
   hafif" iddiası abartılı olur; asıl ayırt edici üstünlüğü test
   MAE/RMSE ve istatistiksel anlamlılıkta.
5. **Hat/ETA-aralığı stabilitesi** iki modelde de benzer (ikisi de
   20dk+ aralığında zayıf) - bu bir model seçimi farkı değil, ortak bir
   veri sınırlaması.

**Dürüst sınırlamalar (kalan):**
- **20dk+ ETA'lar** yeterince temsil edilmiyor (test'te sadece 4 satır)
  - bu aralıkta model performansı hakkında güvenilir sonuç çıkarılamaz.
- 761 hattının verisi hâlâ ağırlıklı olarak 16-17 Ağustos'tan geliyor -
  gün-arası genelleme bu hat için diğer ikisi kadar güçlü test edilmedi.
- Akşam yoğun saat ve hafta sonu (Cumartesi) hiç toplanmadı.
- Response-içi ID çakışması (Bulgu 2) için sistematik bir tarama
  yapılmadı, sadece 1 vaka bulunup düzeltildi - kapsamı tam bilinmiyor.

## 12. Inference (`app/ml/inference.py`)

Kaydedilmiş final model (CatBoost) ile canlı tahmin üreten script.
`vehicle_id` + `line_no` + `target_stop_id` verilince, aracın **en son
bilinen** GOOD/DEGRADED gözlemini T0 kabul edip (gerçek deployment
senaryosu - "şu an için tahmin üret"), `features.py` ile birebir aynı
sorgu/pencere mantığıyla tüm feature'ları canlı hesaplar ve tahmini
saniye/dakika cinsinden basar.

**Test sırasında önemli bir sınırlama bulundu:** `COARSE_APPROACH_WINDOW_M=3000`
nedeniyle train setinde `distance_remaining_m` hiçbir zaman ~3200m'yi
geçmiyor. Model bu aralığın dışında hiç örnek görmedi - kasıtlı olarak
26km uzaklıktaki bir durak sorulduğunda model **fiziksel olarak imkânsız**
bir tahmin üretti (5.8dk → ~270km/h gerektirir). Makul bir mesafede
(2121m) test edilince tahmin tutarlıydı (4.6dk → ~28km/h, gerçekçi otobüs
hızı). `inference.py`'ye bu durumu tespit edip açıkça uyaran bir kontrol
eklendi (`TRAINING_MAX_DISTANCE_REMAINING_M`) - **model sadece durağa
~3km'den yakın T0'lar için güvenilir**, bu inference katmanında
belgelenmiş bir kullanım sınırı.

## 13. Tekrarlanabilirlik

`app/ml/` pipeline: `dataset.py`, `features.py`, `split.py`,
`evaluate.py`, `baselines.py`, `train_xgboost.py`, `train_catboost.py`,
`explain.py`, `inference.py`. Migration `008_dataset_split.sql` ile
`dataset_split` kolonu eklendi.

Artifact'ler:
- `models/xgboost_eta_model.json`, `models/catboost_eta_model.cbm`
- `reports/xgboost-metrics.json`, `reports/catboost-metrics.json` -
  her biri: hiperparametreler, eğitim tarihi, dataset SHA-256 hash'i,
  git commit SHA, feature listesi, train/val/test tarih aralıkları,
  tüm metrikler ve kırılımlar
- `reports/shap-analysis.json`, `reports/shap-feature-importance.png`
- `data/processed/eta_features_20260817_v2.csv` (gitignore'da -
  `data/processed/` repository'ye yüklenmiyor, mevcut proje kuralı;
  yeniden üretim için `python -m app.ml.features` yeterli, dataset
  hash'i metrics.json'da saklı)

Aynı commit ve aynı DB durumuyla `python -m app.ml.train_xgboost
--features <csv>` / `train_catboost` komutları deterministik
(`random_state=42`) aynı sonucu üretir.
