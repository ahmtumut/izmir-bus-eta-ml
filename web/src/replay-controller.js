import { pointAtDistance, headingAtDistance } from "./route-geometry.js";

/**
 * Zaman ekseni oynatma mantigi: gozlemleri arac bazinda gruplar, iki
 * gozlem arasinda interpolasyon yapar, oynat/durdur/hiz/scrubber
 * kontrollerini yonetir.
 */
export class ReplayController {
  /** routeIndex: route-geometry.js:buildRouteIndex() ciktisi (opsiyonel) -
   * verilirse GOOD/DEGRADED gozlemler icin rota-takipli interpolasyon
   * kullanilir (duz cizgi yerine, bkz. interpolatePositions). */
  constructor({ observations, startMs, endMs, onTick, routeIndex = null }) {
    this._byVehicle = groupByVehicle(observations);
    this._startMs = startMs;
    this._endMs = endMs;
    this._onTick = onTick;
    this._routeIndex = routeIndex;
    this._virtualMs = startMs;
    this._speed = 5;
    this._playing = false;
    this._lastFrameTime = null;
  }

  get durationMs() {
    return this._endMs - this._startMs;
  }

  get virtualMs() {
    return this._virtualMs;
  }

  setSpeed(speed) {
    this._speed = speed;
  }

  seekFraction(fraction) {
    this._virtualMs = this._startMs + fraction * this.durationMs;
    this._emit();
  }

  play() {
    if (this._playing) return;
    this._playing = true;
    this._lastFrameTime = performance.now();
    // setInterval (rAF degil): tab arka plandayken de dogru ilerlemeli
    // (rAF, gorunmeyen sekmelerde tarayici tarafindan durdurulabiliyor).
    this._intervalId = setInterval(() => this._loop(), 100);
  }

  pause() {
    this._playing = false;
    clearInterval(this._intervalId);
  }

  toggle() {
    this._playing ? this.pause() : this.play();
  }

  _loop() {
    if (!this._playing) return;
    const now = performance.now();
    const dtMs = now - this._lastFrameTime;
    this._lastFrameTime = now;

    this._virtualMs += dtMs * this._speed;
    if (this._virtualMs >= this._endMs) {
      this._virtualMs = this._endMs;
      this._playing = false;
      clearInterval(this._intervalId);
    }
    this._emit();
  }

  _emit() {
    const positions = interpolatePositions(this._byVehicle, this._virtualMs, this._routeIndex);
    this._onTick(this._virtualMs, positions);
  }
}

/** API'de dokumante edilmemis bir "null island" sentinel'i var - (0,0)
 * koordinati, gercek GPS okumasi degil (bkz. CLAUDE.md). Ayni observed_at'te
 * gercek bir okumayla birlikte gelebiliyor; interpolasyona karisirsa (lo/hi
 * olarak secilirse) arac Gine Korfezi/Libya yakinlarina "isinlanmis" gibi
 * gorunur - bu yuzden en kaynakta eleniyor, hicbir katmana ulasmiyor. */
function isNullIsland(obs) {
  return obs.raw_lat === 0 && obs.raw_lon === 0;
}

function groupByVehicle(observations) {
  const map = new Map();
  for (const obs of observations) {
    if (isNullIsland(obs)) continue;
    const key = obs.vehicle_id;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push({ ...obs, t: Date.parse(obs.observed_at) });
  }
  for (const list of map.values()) {
    list.sort((a, b) => a.t - b.t);
  }
  return map;
}

const ROUTE_FOLLOW_QUALITIES = new Set(["GOOD", "DEGRADED"]);

// Otobus icin cok comert bir ust hiz siniri (~144 km/h, en hizli sehirlerarasi
// otoyol segmentini bile rahat kapsar). Iki nokta arasindaki ima edilen hiz
// bunu asarsa, bu ciftin GERCEK bir arac hareketini degil bir veri glitch'ini
// (GPS sicramasi, API'nin arac ID'sini farkli bir fiziksel araca yeniden
// atamasi, route_id/kalite degisimi vb.) temsil ettigi kabul edilir -
// interpolasyon YAPILMAZ (bkz. interpolatePositions), araci denizden/havadan
// "ucurmamak" icin.
const MAX_PLAUSIBLE_SPEED_MPS = 40;

function haversineMeters(lon1, lat1, lon2, lat2) {
  const R = 6371000;
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLon = (lon2 - lon1) * toRad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

/** Bir tek gozlemin haritada gosterilecegi konumu, KOMSUSUNDAN BAGIMSIZ
 * OLARAK, TEK ve TUTARLI bir sekilde belirler: kalite GOOD/DEGRADED ve
 * rota biliniyorsa rota-izdusumu (distance_along_route_m -> pointAtDistance),
 * aksi halde ham GPS. Bu fonksiyon olmadan, ayni gozlem noktasi bir
 * ONCEKI komsusuyla eslesirken "dondurulmus son konum" olarak HAM GPS
 * gosterilip, hemen ardindan YENI bir komsuyla eslestiginde (rota
 * interpolasyonu bu kez basarili oldugu icin) aninda RASTA-IZDUSUMU
 * konumuna sicrayabiliyordu - kullanicinin ekran kaydinda yakaladigi
 * "bir anda zipliyor" sorununun asil kaynagi buydu. Simdi bir noktanin
 * gosterim konumu HANGI komsuyla eslestigine gore DEGISMEZ. */
function pointDisplayPosition(p, routeIndex) {
  if (routeIndex && p.route_id != null && ROUTE_FOLLOW_QUALITIES.has(p.map_match_quality) && p.distance_along_route_m != null) {
    const routeEntry = routeIndex.get(p.route_id);
    if (routeEntry) {
      const pt = pointAtDistance(routeEntry, p.distance_along_route_m);
      if (pt) return pt;
    }
  }
  return [p.raw_lon, p.raw_lat];
}

/** lo/hi ayni route_id'ye map-match edilmisse (GOOD/DEGRADED) ve routeIndex'te
 * o rota varsa, distance_along_route_m'i zaman icinde interpolayip rota
 * geometrisi uzerine izdusuruyor - duz cizgi yerine yolu takip eder (bkz.
 * route-geometry.js). Aksi halde (REJECTED/unmatched/farkli route) ham
 * lat/lon duz-cizgi interpolasyonuna geri duser - baska secenek yok.
 * Doner: {point:[lon,lat], heading} ya da null.
 *
 * heading ONEMLI: baslangic/bitis GPS noktalari arasindaki DUZ CIZGI acisi
 * degil, o anki mesafedeki rota TEGETI kullanilir - aksi halde arac egri
 * bir yol boyunca ilerlerken govdesi sabit bir acida kalir, gercekte
 * mumkun olmayan bir sekilde yola paralel "kayarak" gidiyormus gibi
 * gorunur (kullanicinin bildirdigi sorun).
 *
 * ROTA-MESAFESI HIZ KONTROLU: interpolatePositions'daki ham-GPS hiz
 * kontrolu SADECE lo/hi'nin fiziksel konumlarinin birbirine yakin olup
 * olmadigini denetler - ama BURADA kullanilan distance_along_route_m
 * (rota uzerindeki ilerleme), rota kendi uzerine kivrilan/gecen bir
 * segmentte veya bir map-matching glitch'inde ham GPS ham GPS'ten
 * BAGIMSIZ olarak sicrayabilir (ornegin GPS neredeyse ayni yerde ama
 * projeksiyon rotanin çok ileri/geri bir noktasina duselebilir) - bu da
 * "rota disinda/asiri hizli gidiyor" seklinde gozlemlenen sorunu
 * acikliyordu. Bu yuzden rota-mesafesi ilerlemesinin ima ettigi hiz da
 * ayrica MAX_PLAUSIBLE_SPEED_MPS ile sinirlaniyor. */
function interpolateAlongRoute(lo, hi, frac, routeIndex, spanMs) {
  if (!routeIndex) return null;
  if (lo.route_id == null || lo.route_id !== hi.route_id) return null;
  if (!ROUTE_FOLLOW_QUALITIES.has(lo.map_match_quality) || !ROUTE_FOLLOW_QUALITIES.has(hi.map_match_quality)) return null;
  if (lo.distance_along_route_m == null || hi.distance_along_route_m == null) return null;

  const routeDistanceM = Math.abs(hi.distance_along_route_m - lo.distance_along_route_m);
  const routeSpeedMps = spanMs > 0 ? routeDistanceM / (spanMs / 1000) : 0;
  if (routeSpeedMps > MAX_PLAUSIBLE_SPEED_MPS) return null;

  const routeEntry = routeIndex.get(lo.route_id);
  if (!routeEntry) return null;

  const distance = lo.distance_along_route_m + (hi.distance_along_route_m - lo.distance_along_route_m) * frac;
  const point = pointAtDistance(routeEntry, distance);
  if (!point) return null;
  const heading = headingAtDistance(routeEntry, distance);
  return { point, heading };
}

/** Her arac icin virtualMs'e en yakin iki gozlem arasinda interpolasyon.
 * Disariya (live-controller.js) da acik - canli modda "ani isinlanma"
 * sorununu ayni interpolasyon mantigiyla cozmek icin reuse ediliyor (bkz.
 * live-controller.js basindaki not). byVehicle: Map(vehicle_id -> [{...,
 * t}, ...]) KUCUKTEN BUYUGE t'ye gore sirali olmali.
 *
 * freezeAtEnd (varsayilan false, sadece REPLAY icin dogru): virtualMs bir
 * aracin bilinen SON noktasini gectiginde ne olacagini belirler.
 * - false (replay): arac GIZLENIR - kayittaki gozlemleri bitmis demektir,
 *   dogru/beklenen davranis (arac o an gercekten "takip disi").
 * - true (live-controller.js): arac, bilinen SON konumunda DONDURULUR
 *   (gizlenmez). Canlida farkli araclar/hatlar collector tarafindan
 *   BIRBIRINDEN FARKLI zamanlarda guncelleniyor - tek bir global virtualMs
 *   kullanilinca, "onde" olan bir aracin zamanina denk gelen an, "geride"
 *   kalan digerlerinin kendi son noktalarindan ileride olabiliyor. Bunlari
 *   gizlemek, aslinda hala guncel olan araclarin coğunun ANIDEN VE
 *   TOPLUCA kaybolup geri gelmesine yol aciyordu (kullanicinin bildirdigi
 *   "3-5 saniye gorunup kayboluyor" sorunu) - dondurmak bunun yerine
 *   dogru cozum, cunku o arac icin elimizdeki EN GUNCEL bilgi zaten o. */
export function interpolatePositions(byVehicle, virtualMs, routeIndex, { freezeAtEnd = false } = {}) {
  const result = new Map();
  for (const [vehicleId, obsList] of byVehicle) {
    if (virtualMs < obsList[0].t) continue; // henuz hic veri yok - baslangic bekleme donemi
    const lastT = obsList[obsList.length - 1].t;
    if (virtualMs > lastT && !freezeAtEnd) continue;
    const effectiveMs = Math.min(virtualMs, lastT);

    let lo = obsList[0];
    let hi = obsList[obsList.length - 1];
    for (let i = 0; i < obsList.length - 1; i++) {
      if (obsList[i].t <= effectiveMs && effectiveMs <= obsList[i + 1].t) {
        lo = obsList[i];
        hi = obsList[i + 1];
        break;
      }
    }

    const span = hi.t - lo.t;
    const frac = span > 0 ? (effectiveMs - lo.t) / span : 0;
    const source = frac < 0.5 ? lo : hi;

    // Her iki komsu noktanin da TUTARLI (komsusundan bagimsiz) gosterim
    // konumu - bkz. pointDisplayPosition ustundeki not.
    //
    // lo/hi FARKLI bir route_id'ye (ornegin ayni hattin ZIT YONUNE)
    // eslesmisse, ikisinin rota-izdusumlerini birbiriyle KIYASLAMAK
    // guvenilmez: ayni fiziksel rota, zit yonde BASKA UCTAN olculdugu icin
    // distance_along_route_m tamamen farkli bir referansa sahip olur - ham
    // GPS neredeyse hic degismese bile izdusum kilometrelerce "sicrar" (bu,
    // ekran kaydinda yakalanan buyuk sicramalarin asil kaynagi - backend'in
    // map-matching'i bazi araclarda yon atamasini pollar arasi degistirebiliyor).
    // Bu yuzden route_id UYUSMUYORSA, KARSILASTIRMA icin HER IKI nokta de
    // kendi HAM GPS'ine geri duser (rota-izdusumu degil) - ham GPS ayni
    // fiziksel anlar icin normalde zaten birbirine yakindir.
    const sameRoute = lo.route_id != null && lo.route_id === hi.route_id;
    const [loLon, loLat] = sameRoute ? pointDisplayPosition(lo, routeIndex) : [lo.raw_lon, lo.raw_lat];
    const [hiLon, hiLat] = sameRoute ? pointDisplayPosition(hi, routeIndex) : [hi.raw_lon, hi.raw_lat];

    // Iki noktanin GOSTERIM konumlari arasindaki ima edilen hiz fiziksel
    // olarak imkansizsa (bkz. MAX_PLAUSIBLE_SPEED_MPS) bu cift GUVENILMEZ
    // kabul edilir - ne rota-takipli ne duz-cizgi interpolasyonu yapilir,
    // sadece EN GUNCEL (hi) noktanin gosterim konumu gosterilir
    // (kullanicinin bildirdigi "denizden gidiyor" / "cok hizli" / "bir
    // anda zipliyor" sorunlari - route_id/kalite degisimi veya arac
    // ID'nin API tarafinda farkli bir araca yeniden atanmasi gibi bir veri
    // glitch'inde duz-cizgi fallback'i cok uzak iki noktayi birlestirip
    // araci kiyi/deniz farki gozetmeden "ucuruyordu").
    //
    // ONEMLI: `frac<0.5?lo:hi` gibi zamana bagli bir kaynak SECMEK YERINE
    // HER ZAMAN `hi` kullaniliyor - aksi halde konum, AYNI bracket icinde
    // frac 0.5'i gectigi anda lo'dan hi'ye (kilometrelerce uzak olabilen
    // iki nokta arasinda) SIRF BU SECIM YUZUNDEN aniden siçrardi (ekran
    // kaydinda yakalanan "bir anda zipliyor" sorununun asil kaynagi buydu).
    // Boylece siçrama sadece YENI bir (guvenilmez) veri noktasi geldiginde,
    // TEK SEFERLIK ve kacinilmaz sekilde olur - bracket icinde degil.
    const boundaryDistanceM = haversineMeters(loLon, loLat, hiLon, hiLat);
    const impliedSpeedMps = span > 0 ? boundaryDistanceM / (span / 1000) : 0;
    const plausible = impliedSpeedMps <= MAX_PLAUSIBLE_SPEED_MPS;

    let lon, lat, heading;
    if (plausible) {
      const routeResult = interpolateAlongRoute(lo, hi, frac, routeIndex, span);
      [lon, lat] = routeResult?.point ?? [
        loLon + (hiLon - loLon) * frac,
        loLat + (hiLat - loLat) * frac,
      ];
      heading = routeResult?.heading ?? null; // null: vehicleLayer kendi raw-konum bearing'ine geri duser
    } else {
      lon = hiLon;
      lat = hiLat;
      heading = null;
    }

    result.set(vehicleId, {
      lat,
      lon,
      map_match_quality: source.map_match_quality,
      line_no: source.line_no,
      observed_at: source.observed_at,
      distance_to_route_m: source.distance_to_route_m,
      progress_along_route: source.progress_along_route,
      heading,
    });
  }
  return result;
}
