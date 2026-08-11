# Faz 2 Onerileri

Faz 1 boyunca tespit edilen bulgulara dayanarak, Faz 2'ye
(PostgreSQL/PostGIS entegrasyonu, durak/guzergah birlestirme, ETA
label uretimi, baseline model) baslamadan once veya baslarken ele
alinmasi onerilen konular, oncelik sirasina gore.

## Yuksek Oncelik

### 1. GPS "donma" hipotezini dogrula (bkz. known-risks.md, api-comparison.md)
Hat 515'teki 4 aracin GPS'i 25+ saat boyunca degismedi, ama
destekleyici API'deki `KalanDurakSayisi` degerleri farkliydi. Bu,
konum alaninin donmus olabilecegini, aracin gercekte hareket
ettigini gosteriyor. Onerilen arastirma:
- Ayni araclari daha uzun sure (orn. 2-3 gun) izleyip GPS'in hic mi
  hic guncellenmiyor, yoksa cok seyrek mi guncelleniyor oldugunu
  netlestir.
- `KalanDurakSayisi` degisimini GPS degisimiyle zaman ekseninde
  karsilastir, gecikme/senkronizasyon farki var mi bak.
- Eger konum gercekten donuyorsa, bu araclarin ETA egitim verisinden
  cikarilip cikarilmayacagina (ya da `KalanDurakSayisi` tabanli
  alternatif bir konum tahmini kullanilip kullanilamayacagina) karar
  ver.

### 2. Trail noktalarinin gercek anlamini coz
Su an her response'tan sadece ilk nokta kullaniliyor, digerleri
gozardi ediliyor. Onerilen yaklasim:
- Tum trail noktalarini ayri ayri sakla (attigimiz gibi silme).
- Bir arac icin ardisik response'lardaki trail'leri karsilastirip,
  hangi noktalarin gercekten yeni oldugunu (onceki response'ta
  olmayan) tespit et - bu, gercek kronolojik sirayi cikarmaya
  yardimci olabilir.
- Alternatif: ESHOT'a/API dokumantasyonuna bu davranisi soran bir
  talep birakmayi degerlendir (kaynak netlesirse en guvenilir yol).

### 3. Durak koordinat eslestirmesini tamamla
Faz 1'de `data/reference/eshot-otobus-duraklari.csv` projeye eklendi
ama sadece madde 10 testinde kullanildi. Faz 2'nin PostGIS asamasinda:
- Tum pilot hat duraklarini (515: 91, 121: 77, 761: 215 durak)
  veritabanina yukle.
- "Duraga ulasti" tanimini (bkz. problem-definition.md) bu gercek
  koordinatlarla test et, mesafe esigini kalibre et.

## Orta Oncelik

### 4. Rate limit'i resmi olarak dogrula/genislet
Su anki 3 saniyelik hat-arasi bekleme deneyerek bulundu, resmi bir
limit dokumani yok. Faz 2'de daha fazla hat/durak sorgulanacaksa
(sistem olcek buyutulecekse), ESHOT ile iletisime gecip resmi limit
ogrenilmesi onerilir - performans/maliyet planlamasi icin onemli.

### 5. `KalanDurakSayisi`'ni ek ozellik olarak degerlendir
Madde 10'da gorulen bu alan, GPS'ten bagimsiz bir ilerleme sinyali
olabilir. ETA modelinde feature olarak kullanilmasi, GPS
guvenilirligi dusuk anlarda modele ek bilgi saglayabilir.

### 6. Coklu-fiziksel-arac / ID tekrar kullanimi ihtimalini arastir
`known-risks.md`'de bahsedilen bir diger hipotez. Uzun sureli
gozlemle (birden fazla gun), ayni `OtobusId`'nin farkli fiziksel
araclara (farkli plaka, farkli vardiya) karsilik gelip gelmedigi
arastirilabilir - eger ESHOT plaka/arac bilgisi baska bir kaynaktan
elde edilebiliyorsa.

## Dusuk Oncelik / Ileride

### 7. Collector'a graceful shutdown ekle
Su an Ctrl+C ile durdurulunca, devam eden istek loglanmadan
kesilebiliyor (bkz. known-risks.md madde 7). SIGINT yakalayip
mevcut istegi tamamlatan bir mekanizma eklenebilir.

### 8. Coklu-proses/olcek
Collector su an tek process, tek makinede calisiyor. Daha fazla hat
eklenirse (pilot 3 hattan tum ESHOT hatlarina genisletme), paralel
calisma veya kuyruk tabanli bir mimari degerlendirilebilir.

### 9. Otomatik veri kalite raporu
Su an `generate_collection_summary.py` ve `analyze_freshness.py`
elle calistiriliyor. Faz 2'de collector'a entegre, periyodik
(orn. gunluk) otomatik rapor uretimi eklenebilir.
