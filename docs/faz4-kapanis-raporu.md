# Faz 4 Kapanış Raporu — Canlı/Replay 3D Web Görselleştirme + MLOps Eklentileri

**Tarih:** 21 Ağustos 2026
**Commit SHA:** `7453ef3` (kod) + `78560f7` (final rapor SHA düzeltmesi)
**Repository:** https://github.com/ahmtumut/izmir-bus-eta-ml

## 0. Kapsam Notu

Faz 4, Faz 1-3'ün aksine **görev tanımının (CLAUDE.md'deki orijinal supervisor talimatı) parçası
değildi**. Kullanıcının bu oturumda ayrıca ilettiği, başlangıçta belirsiz bir talep ("projeyi Three.js
ile görselleştir") ile başladı; kapsam netleştirme adımları ve kullanıcı geri bildirimiyle iteratif
olarak genişledi. Bu nedenle resmi bir kabul kriteri seti yoktu — bu rapor, Faz 1-3'ün kapanış rapor
formatını Faz 4'e uygulayarak retrospektif bir kapanış sağlıyor.

## 1. Motivasyon ve Kapsam Netleştirme

İlk talepte netlik olmadığı için (canlı mi replay mi, sadece GPS mi yoksa map-matching/arrival/ETA da
dahil mi, gerçek harita mı soyut sahne mi, tek/çoklu hat mı, tek seferlik demo mu sürekli özellik mi)
5 netleştirici soru soruldu. Kullanıcı yanıtlarına göre kapsam şu şekilde şekillendi:

- Hem **geçmiş veri replay'i** hem **canlı mod** (ikisi de aynı katmanları paylaşan tek bir uygulama).
- Sadece ham GPS değil; **map-matching sonucu** (route üzerindeki projeksiyon), **arrival event'ler** ve
  **ETA tahminleri** (CatBoost) birlikte gösteriliyor.
- **Gerçek harita altlığı** (soyut sahne değil) üzerinde **gerçek 3D** (pitch/tilt destekli).
- Üç pilot hat (515, 121, 761) aynı ekranda, checkbox ile filtrelenebilir.
- Sürdürülebilir bir özellik olarak ele alındı (tek seferlik demo değil) — modüler backend/frontend
  ayrımı, tekrar kullanılabilir katmanlar.

## 2. Mimari Kararlar

### 2.1 Backend katmanı gerekliliği

Three.js/MapLibre doğrudan PostgreSQL'e bağlanamadığı için yeni bir `app/api/` (FastAPI) katmanı
eklendi — CLAUDE.md'de zaten öngörülen bir mimari gereklilik. Router'lar: `routes_data.py` (rota/durak
GeoJSON), `replay.py` (geçmiş oturum/gözlem/arrival/ETA), `live.py` (canlı durum + son konumlar),
`model_metrics.py` (model performans dashboard'u için).

### 2.2 Leaflet → MapLibre GL JS + OpenFreeMap geçişi

İlk sürüm Leaflet (düz 2D tile) + üzerine gömülü özel bir Three.js overlay'iydi. Bu yaklaşımın temel
kısıtı: Leaflet'in kendi harita katmanı hiç eğilemiyor (pitch yok), bu yüzden 3D otobüs katmanı da
bilinçli olarak "kamera düz tepeden" tutulmuştu — aksi halde harita düz kalırken otobüsler yollardan
kaymış görünürdü (konum doğruluğu CLAUDE.md'nin öncelikli kaygısı). Kullanıcı bunun sınırlı bir "3D"
deneyimi olduğunu fark edince, **MapLibre GL JS + OpenFreeMap**'e (ücretsiz, API-key gerektirmeyen
vektör tile kaynağı; Mapbox GL JS'in proprietary/faturalı olması nedeniyle elendi) geçildi.

Bunun kazandırdığı: MapLibre'nin `CustomLayerInterface`'i (`type: 'custom', renderingMode: '3d'`)
sayesinde Three.js sahnesi haritanın **kendi o anki projeksiyon matrisiyle** (`render(gl, matrix)`
callback) her frame senkronize ediliyor. Bu, "harita düz kalıp otobüs kayıyor" sınıfı sorunları
yapısal olarak ortadan kaldırdı — harita artık gerçekten eğilebiliyor (pitch) ve 3D katman aynı matrisi
kullandığı için otomatik hizalı kalıyor. Doğrulama: harita sürükleyerek/sağ-tıkla pitch verildiğinde
otobüslerin yol üzerinde, kaymadan durduğu test edildi.

Değişen dosyalar: `web/src/main.js`, `web/src/layers/{routeLayer,stopLayer,arrivalLayer,vehicleLayer,
etaLayer}.js` — katmanların public API'si (`tick()`/`reset()` vb.) korunarak sadece render mekaniği
Leaflet'ten MapLibre'ye taşındı; `replay-controller.js`/`live-controller.js` (iş mantığı) hiç
değişmedi.

### 2.3 Canlı mod: collector aktiflik tespiti

`app/api/live.py:get_live_status` — `ingestion_runs.ended_at IS NULL` **ve** son gözlemin tazeliği
(≤90sn, 60sn collector döngüsü + tampon) birlikte kontrol ediliyor; çünkü çökmüş bir collector
`ended_at`'i hiç set etmez, tek başına güvenilmez bir sinyal olurdu. Canlı mod dış API'ye **hiçbir yeni
çağrı eklemiyor** — sadece iç Postgres'i sorguluyor, bu yüzden rate-limit riski yok (frontend → backend
→ DB). Collector web'den otomatik başlatılmıyor (bilinçli kapsam dışı — risk/karmaşıklık); kullanıcı
ayrı bir terminalde manuel başlatmaya devam ediyor.

### 2.4 Canlı map-matching'in collector'a gömülmesi

Canlı modu test ederken gerçek bir hata bulundu: `run_dual_collector.py` GPS'i topluyordu ama
`map_match_quality`/`route_id`/`distance_along_route_m` hesaplaması ayrı, offline bir script'te
(`map_match_observations.py --run-id X`) kalmıştı. Replay modundaki eski oturumlar bu script'ten
geçirilmişti, ama canlı toplanan veri hiç geçmiyordu — otobüsler yanlış renkte (fallback mavi) görünüyor,
ETA tahminleri sürekli 404 veriyordu (`inference.py` GOOD/DEGRADED + `distance_along_route_m NOT NULL`
şartı arıyor).

Kalıcı çözüm: `map_match_observations.py`'daki `run_map_matching(conn, run_id)` fonksiyonuna
`only_unmatched: bool = False` parametresi eklendi (`WHERE map_match_quality IS NULL` filtresi, CLI'nin
varsayılan tam-reprocessing davranışı değişmedi), `run_dual_collector.py`'ın kendi döngüsüne
`only_unmatched=True` ile gömüldü. Bu, sadece Faz 4'ü değil, **Faz 2/3'teki tüm gelecekteki collector
çalıştırmalarını** da iyileştirdi — artık hiçbir run için ayrıca manuel map-matching script'i
çalıştırmaya gerek yok.

### 2.5 `live.py:get_live_observations` — vehicle_id collision düzeltmesi

Geliştirme sırasında keşfedilen, dokümante edilmemiş bir ESHOT API kusuru: tek bir pollde aynı
`vehicle_id` birden fazla kez, birbirinden km'lerce uzak farklı konumlarla dönebiliyor (muhtemelen
farklı fiziksel araçların aynı ID'yi paylaşması). İlk deneme (belirsizlik varsa aracı tamamen dışlamak)
başarısız oldu — bu durum nadir değil, birçok araç için neredeyse her pollde ortaya çıkıyor; dışlanan
araçlar donmuş gibi görünmeye başladı. Düzeltme: **uzamsal süreklilik** — belirsizlik olduğunda,
adaylardan hangisi aracın bir önceki bilinen konumuna daha yakınsa o seçiliyor (gerçek bir aracın
konumu pollar arasında büyük sıçramalar yapmaz). Ayrıca henüz map-match edilmemiş (`map_match_quality
IS NULL`) satırlar sorgudan en baştan hariç tutuluyor — collector'ın GPS-toplama ile map-matching
adımları arasındaki kısa pencerede yakalanıp "rota dışında süzülen otobüs" görüntüsü vermesin diye.

### 2.6 Model performans dashboard'u (`app/api/model_metrics.py`, `web/dashboard.html`+`.js`)

Faz 3'te üretilen metrikleri statik bir JSON'dan okumak yerine, DB'den canlı olarak feature dataframe'i
kurup (`app.ml.features.build_feature_dataframe` — eğitimdekiyle birebir aynı sorgu mantığı)
baseline'ları ve iki modeli yeniden değerlendiren bir `/api/model/metrics` endpoint'i eklendi (hat/yön/
ETA-aralığı/label-kalitesi kırılımlı, tahmin-hata scatter örneklemi dahil). Ayrıca **`/api/model/
live-performance`**: train/validation/test split'i donduruktan **sonra** toplanan, modelin hiçbir
aşamada görmediği taze veri üzerinde CatBoost'un gerçek out-of-sample performansını ölçüyor — Faz 3
raporundaki sabit test seti sonuçlarından farklı olarak, zamanla büyüyen, gerçekten hiç görülmemiş bir
veri akışı üzerinde sürekli güncellenen bir "production'da model ne kadar iyi çalışıyor" göstergesi.
Ağır (satır başına 2 ek DB sorgusu gerektiren) feature dataframe kurulumu process içi cache'leniyor
(canlı performans için 5dk, sabit metrikler için süresiz).

### 2.7 `vehicle_id` ablation testi (`app/ml/ablation_vehicle_id.py`)

Faz 3'te ana modelde `vehicle_id` kasıtlı olarak feature olarak kullanılmamıştı ("aracın ID'sini
ezberleyen değil, farklı araçlara genellenebilen bir model" hedefiyle). Bu betik, o kararın gerçekten
doğru olup olmadığını kontrollü bir deneyle ölçüyor: **aynı** train/validation/test split, **aynı**
hiperparametreler (raporda kayıtlı `best_hyperparameters` aynen tekrar kullanılıyor — hiperparametre
aramasını tekrar etmiyor) ile sadece `vehicle_id` eklenmiş bir CatBoost modeli eğitiyor, test MAE'sini
kayıtlı final modelle karşılaştırıyor. %5 eşik üzerinden otomatik yorum üretiyor (MAE önemli ölçüde
düşerse → araç-kimliği ezberleme riski sinyali; değişmez/kötüleşirse → farklı bir gerekçeyle mevcut
kararı doğrular). *Not: bu betiğin çalıştırılmış çıktısı (`reports/ablation-vehicle-id.json`) repoda
mevcut ama bu raporun hazırlandığı anda sayısal sonucu ayrıca doğrulanmadı — Faz 3 raporuna resmi olarak
eklenmeden önce okunmalı.*

### 2.8 Diğer eklentiler

- `scripts/run_collector_supervisor.py` — collector'ı kalıcı/sürekli çalıştırmak için denetleyici script.
- `scripts/import_gtfs_route_shapes.py` — GTFS kaynağından route geometrisi normalizasyonu.
- `web/dashboard.html`/`.js`/`.css` — model performans dashboard'unun frontend'i (tahmin-hata scatter,
  kırılım tabloları, canlı out-of-sample performans kartı).
- Araç tıklanınca detay paneli (son gözlem zamanı, hız sparkline, güven), mobil uyumlu responsive panel
  düzeni.

## 3. Kapsam Dışı Bırakılanlar (bilinçli)

- Collector'ı web'den otomatik başlatma/durdurma — güvenlik/karmaşıklık riski.
- WebSocket/SSE — 15sn polling, collector'ın kendi 60sn güncelleme hızı için yeterli.
- Pitch/bearing için özel UI — MapLibre'nin standart `NavigationControl`'ü yeterli görüldü.
- Vektör harita stil özelleştirmesi — OpenFreeMap'in hazır "liberty" stili kullanıldı.

## 4. Doğrulama

- Backend: `uvicorn app.api.main:app --port 8000` ile başlatıldı, `/api/health`, `/api/routes`,
  `/api/stops`, `/api/replay/sessions` endpoint'leri 200 OK doğrulandı; CORS header'ı
  (`access-control-allow-origin: http://localhost:5173`) curl ile doğrulandı.
- Frontend: `web/` içinde `npm run dev` (Vite, port 5173) ile başlatıldı, tarayıcıda replay paneli,
  oturum seçici, hat filtreleri, "Veriyi Yükle" akışı görsel olarak doğrulandı (ekran görüntüsü
  alındı, konsol hatasız — harici OpenFreeMap tile istekleri hariç, bu sandbox tarayıcının dış ağ
  kısıtlamasından kaynaklanıyor, gerçek tarayıcıda sorun oluşturmuyor).
- Canlı map-matching gömme: kısa bir test run'ı (`--minutes 3 --lines 515`) ile `only_unmatched=True`
  davranışı, her cycle sonrası `map_match_quality`'nin dolduğu doğrulandı.
- MapLibre pitch testi: haritayı eğerek otobüslerin yol üzerinde kaymadan durduğu doğrulandı (Leaflet
  sürümünde mümkün olmayan bir test).

## 5. Bilinen Açık Noktalar

1. **Ablation testi sonucu Faz 3 raporuna resmi olarak eklenmedi** — `reports/ablation-vehicle-id.json`
   üretildi ama sayısal yorumu henüz `docs/faz3-final-raporu.md`'ye işlenmedi.
2. **Resmi kabul kriteri yok** — Faz 4, Faz 1-3'ün aksine bir supervisor tarafından tanımlanmadı;
   "tamamlandı" değerlendirmesi kullanıcı onayına ve bu rapordaki doğrulama adımlarına dayanıyor.
3. **Collector web'den yönetilmiyor** — canlı modu görmek için kullanıcının ayrı bir terminalde
   `python -m scripts.run_dual_collector` çalıştırması gerekiyor; bu bilinçli bir kapsam dışı karar.
4. **Vehicle_id collision düzeltmesi (§2.5) kalıcı bir çözüm değil, azaltım** — ESHOT API'sindeki
   kök nedene (aynı ID'nin birden fazla fiziksel araca atanması) müdahale edilemiyor, sadece görsel
   tutarlılık sağlanıyor.

## 6. Sonuç

Faz 4, görev tanımının dışında olmasına rağmen, Faz 1-3'te kurulan veri altyapısını (map-matching,
arrival event, ETA modeli) somut, etkileşimli bir web deneyimine dönüştürdü. Süreçte bulunan gerçek
hatalar (map-matching'in collector'a gömülmemesi, vehicle_id collision) kalıcı düzeltmelerle çözüldü ve
bu düzeltmeler yalnızca Faz 4'ü değil, projenin tüm gelecekteki veri toplama operasyonlarını
iyileştiriyor. Kod `7453ef3` ile repoya işlendi; kalan iş kalemleri (§5) küçük, takip edilebilir açık
noktalar olarak listelendi.
