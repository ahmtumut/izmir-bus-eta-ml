import { fetchLiveStatus, fetchLiveObservations, fetchArrivals } from "./api.js";
import { interpolatePositions } from "./replay-controller.js";

const ARRIVALS_WINDOW_MS = 10 * 60 * 1000; // son 10dk - "az once varan" event'leri yakalamak icin

/**
 * Canli mod surucusu: ReplayController'in yerini alir ama gecmis veri
 * yerine periyodik olarak backend'den EN SON durumu ceker. vehicleLayer/
 * arrivalLayer/etaLayer replay ile birebir ayni sekilde kullanilir - onlar
 * icin "zaman" replay'de sanal saat, burada gecikmeli (bkz. asagidaki not)
 * gercek saat.
 *
 * "ANI ISINLANMA" DUZELTMESI: Onceki versiyon her poll'da (15sn) araci
 * DOGRUDAN en son bilinen konuma "atliyordu" - iki konum arasinda ara adim
 * olmadigi icin otobus haritada zipliyormus gibi goruluyordu (kullanicinin
 * bildirdigi sorun). Duzeltme: replay modundaki AYNI interpolatePositions
 * mantigi reuse ediliyor, ama "sanal zaman" gercek `Date.now()` DEGIL,
 * ondan RENDER_DELAY_MS (varsayilan 60sn) GERIDE bir zaman. Boylece
 * gosterilen an icin her zaman GERCEK iki GPS orneği (bir onceki + bir
 * sonraki) elde bulunur ve aralarinda duz interpolasyon/rota-takipli
 * interpolasyon yapilabilir - replay'deki "sanal saat" kavraminin canli
 * moda uyarlanmis hali. Bedeli: gorunen konum, gercek konumdan
 * RENDER_DELAY_MS kadar gerideden. Alttaki veri (ETA sorgusu, "son gozlem"
 * zaman damgasi vb.) yine gecikmeli sanal zamana gore hesaplanir - boylece
 * ETA tahmini de o an EKRANDA GORUNEN konumla tutarli kalir (gercek anlik
 * konumla degil).
 *
 * "ARACLAR TOPLUCA KAYBOLUP GERI GELIYOR" DUZELTMESI: farkli hatlar/araclar
 * collector tarafindan BIRBIRINDEN FARKLI zamanlarda guncelleniyor (sirali
 * per-hat toplama nedeniyle birkac saniyelik dogal kayma var). virtualMs
 * `Date.now() - renderDelayMs` gibi TEK bir duvar-saati degeriyle
 * hesaplanip TUM araclara ayni sekilde uygulanirsa, "onde" olan bir aracin
 * zamanina denk gelen an, "geride" kalan digerlerinin kendi bilinen SON
 * noktasindan ileride olabiliyor - bu da o araclarin (cogu zaman coğunluk)
 * ANIDEN VE TOPLUCA kaybolup, bir sonraki veri onlari yakaladiginda geri
 * gelmesine yol aciyordu (kullanicinin bildirdigi "3-5 saniye gorunup
 * kayboluyor" sorunu). Duzeltme: interpolatePositions'a `freezeAtEnd: true`
 * geciliyor - bir arac icin virtualMs kendi bilinen son noktasini gecerse,
 * o arac GIZLENMEK yerine son konumunda DONDURULUR (bkz. replay-controller.js).
 *
 * "AKICI DEGIL, KADEMELI GORUNUYOR" DUZELTMESI: gorsel interpolasyon
 * onceden setInterval(200ms) ile calisiyordu - saniyede sadece 5 pozisyon
 * guncellemesi, tarayicinin ~60fps ekran yenileme hizina gore belirgin
 * "adim adim" (jerky) hareket olarak goruluyordu. Simdi requestAnimationFrame
 * kullanilarak EKRAN YENILEME HIZINDA (genelde 60fps) her karede yeniden
 * hesaplaniyor - replay modu bilerek setInterval(100ms) kullaniyor (arka
 * plan sekmede rAF durabiliyor), ama canli modda bu bir sorun degil: sekme
 * arka plandayken interpolasyonun duraklamasi kabul edilebilir (kaynak
 * tasarrufu), poll() ayri bir setInterval ile BAGIMSIZ calismaya devam
 * eder, veri kaybı olmaz.
 */
export class LiveController {
  /** routeIndex: route-geometry.js:buildRouteIndex() ciktisi (opsiyonel) -
   * verilirse GOOD/DEGRADED araclar HAM (gurultulu) GPS yerine rota
   * geometrisi uzerine snap edilir, yon de rota teğetinden hesaplanir -
   * replay modundaki "yola paralel kayma" duzeltmesiyle ayni gerekce
   * (bkz. replay-controller.js). */
  constructor(
    onTick,
    { pollIntervalMs = 15000, maxAgeSeconds = 90, routeIndex = null, renderDelayMs = 60000 } = {}
  ) {
    this._onTick = onTick;
    this._pollIntervalMs = pollIntervalMs;
    this._maxAgeSeconds = maxAgeSeconds;
    this._routeIndex = routeIndex;
    this._renderDelayMs = renderDelayMs;
    this._lineNos = [];
    this._pollTimerId = null;
    this._renderFrameId = null;
    this._history = new Map(); // vehicle_id -> [{...obs, t}, ...] artan t sirasiyla
    this._latestArrivals = [];
    this._latestStatus = { collector_active: false };
  }

  /** routeIndex, LiveController olusturuldugu anda henuz hazir olmayabilir
   * (main.js'de harita 'load' olur olmaz olusturuluyor, routeIndex ise
   * /api/routes cevabi geldikten sonra hazirlaniyor) - bu yuzden sonradan
   * enjekte edilebiliyor. */
  setRouteIndex(routeIndex) {
    this._routeIndex = routeIndex;
  }

  start(lineNos) {
    this._lineNos = lineNos;
    this._history.clear();
    this._poll();
    this._pollTimerId = setInterval(() => this._poll(), this._pollIntervalMs);
    this._renderFrameId = requestAnimationFrame(() => this._renderLoop());
  }

  stop() {
    clearInterval(this._pollTimerId);
    if (this._renderFrameId != null) cancelAnimationFrame(this._renderFrameId);
    this._pollTimerId = null;
    this._renderFrameId = null;
  }

  _renderLoop() {
    this._render();
    this._renderFrameId = requestAnimationFrame(() => this._renderLoop());
  }

  async _poll() {
    const nowMs = Date.now();
    const nowIso = new Date(nowMs).toISOString();
    const windowStartIso = new Date(nowMs - ARRIVALS_WINDOW_MS).toISOString();

    try {
      const [status, obsResp, arrivalsResp] = await Promise.all([
        fetchLiveStatus(),
        fetchLiveObservations(this._lineNos, this._maxAgeSeconds),
        fetchArrivals(windowStartIso, nowIso, this._lineNos),
      ]);

      this._latestStatus = status;
      this._latestArrivals = arrivalsResp.arrivals;
      this._ingestObservations(obsResp.observations);
    } catch (err) {
      this._latestStatus = { collector_active: false, error: err.message };
    }
  }

  /** Yeni gelen gozlemleri arac bazinda gecmis dizisine ekler (ayni
   * observed_at tekrar eklenmez) ve render penceresinin cok gerisinde
   * kalan eski noktalari budar - bkz. sinif basi not. */
  _ingestObservations(observations) {
    for (const obs of observations) {
      if (obs.raw_lat === 0 && obs.raw_lon === 0) continue; // null island sentinel - bkz. replay-controller.js
      const t = Date.parse(obs.observed_at);
      let hist = this._history.get(obs.vehicle_id);
      if (!hist) {
        hist = [];
        this._history.set(obs.vehicle_id, hist);
      }
      if (hist.length === 0 || hist[hist.length - 1].t < t) {
        hist.push({ ...obs, t });
      }
    }

    // Render penceresinden (simdi - renderDelayMs) daha eski, artik hic
    // kullanilmayacak noktalari at - ama interpolasyon icin daima EN AZ
    // bir "gecmis" nokta kalsin diye son elemani asla silme.
    const cutoff = Date.now() - this._renderDelayMs - this._pollIntervalMs;
    for (const [vehicleId, hist] of this._history) {
      while (hist.length > 1 && hist[1].t < cutoff) hist.shift();
      if (hist[hist.length - 1].t < cutoff - this._maxAgeSeconds * 1000) {
        this._history.delete(vehicleId); // arac uzun suredir hic veri gondermiyor
      }
    }
  }

  _render() {
    const virtualMs = Date.now() - this._renderDelayMs;
    // freezeAtEnd:true - bkz. sinif basi "ARACLAR TOPLUCA KAYBOLUP GERI
    // GELIYOR" notu. Veri gecikirse (collector/ag) araclar kaybolmak
    // yerine bilinen son konumlarinda kisa sure donuyor.
    const positions = interpolatePositions(this._history, virtualMs, this._routeIndex, { freezeAtEnd: true });
    this._onTick(virtualMs, positions, this._latestArrivals, this._latestStatus);
  }
}
