/**
 * Route geometrisi uzerinde mesafe->koordinat izdusumu icin yardimcilar.
 * Faz 4 replay animasyonunda iki GPS ornegi arasinda DUZ CIZGI ile
 * interpolasyon yapmak, ornekler arasi (~60sn) mesafe buyukse yol/kiyi
 * seklini yok sayip araci "denizin uzerinden" gecirebiliyordu (kullanicinin
 * bildirdigi hata). Bu modul, GOOD/DEGRADED gozlemler icin distance_along_route_m
 * degerini rota LineString'i uzerinde interpolasyona izin verir - animasyon
 * gercek yol izini takip eder.
 */

function haversineMeters([lon1, lat1], [lon2, lat2]) {
  const R = 6371000;
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLon = (lon2 - lon1) * toRad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

/** routesResponse: /api/routes cevabi. Doner: Map(route_id -> {coordinates, cumDist}) */
export function buildRouteIndex(routesResponse) {
  const index = new Map();
  for (const route of routesResponse.routes) {
    const coords = route.coordinates;
    const cumDist = [0];
    for (let i = 1; i < coords.length; i++) {
      cumDist.push(cumDist[i - 1] + haversineMeters(coords[i - 1], coords[i]));
    }
    index.set(route.route_id, { coordinates: coords, cumDist });
  }
  return index;
}

/** routeEntry: buildRouteIndex'in bir degeri. distanceM: rota uzerindeki hedef mesafe.
 * Doner: [lon, lat] veya (rota bulunamazsa) null. */
export function pointAtDistance(routeEntry, distanceM) {
  if (!routeEntry) return null;
  const { coordinates, cumDist } = routeEntry;
  const total = cumDist[cumDist.length - 1];
  const d = Math.max(0, Math.min(distanceM, total));

  let i = 1;
  while (i < cumDist.length && cumDist[i] < d) i++;
  if (i >= cumDist.length) return coordinates[coordinates.length - 1];

  const segStart = cumDist[i - 1];
  const segEnd = cumDist[i];
  const segFrac = segEnd > segStart ? (d - segStart) / (segEnd - segStart) : 0;
  const [lon1, lat1] = coordinates[i - 1];
  const [lon2, lat2] = coordinates[i];
  return [lon1 + (lon2 - lon1) * segFrac, lat1 + (lat2 - lat1) * segFrac];
}

function bearingRadians(lon1, lat1, lon2, lat2) {
  const toRad = Math.PI / 180;
  const y = Math.sin((lon2 - lon1) * toRad) * Math.cos(lat2 * toRad);
  const x =
    Math.cos(lat1 * toRad) * Math.sin(lat2 * toRad) -
    Math.sin(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.cos((lon2 - lon1) * toRad);
  return Math.atan2(y, x);
}

/** distanceM konumundaki rota TEGETININ (yerel egim) yonu - araci rotanin
 * o andaki kivrimina gore dondurmek icin. Iki komsu nokta (distanceM-adim,
 * distanceM+adim) arasindaki gercek cografi bearing kullanilir - sadece
 * baslangic/bitis GPS noktalari arasindaki DUZ CIZGI acisi kullanilsaydi
 * (eski davranis), arac egri bir yol boyunca ilerlerken govdesi sabit bir
 * acida kalir, "kayarak gidiyor" gibi gorunurdu (kullanicinin bildirdigi
 * sorun) - artik her an rotanin o noktadaki gercek yonune bakiyor.
 *
 * ADIM BUYUKLUGU NEDEN SABIT DEGIL: rota koordinatlari ~4 ondalik basamaga
 * (~11m) yuvarlanmis geliyor, bu yuzden ardisik birkac nokta AYNI koordinata
 * dusebiliyor (0 metre uzunlugunda segmentler). Sabit ±1m'lik bir pencere
 * boyle bir "tekrarli nokta" bolgesine denk gelirse back===fwd olur ve
 * bearingRadians(ayni nokta, ayni nokta) = atan2(0,0) = 0 (sahte "kuzey")
 * doner - bu, bazi araclarin dogru yonde bazilarinin rastgele/sabit bir
 * yonde gorunmesine yol aciyordu (kullanicinin "bazilari duzelmis, bazilari
 * hala boyle" bildirimi). Duzeltme: back/fwd GERCEKTEN FARKLI iki nokta
 * verene kadar adimi kademeli buyuterek dener. */
export function headingAtDistance(routeEntry, distanceM) {
  for (const step of [1, 3, 6, 12, 25, 50, 100]) {
    const back = pointAtDistance(routeEntry, distanceM - step);
    const fwd = pointAtDistance(routeEntry, distanceM + step);
    if (!back || !fwd) return null;
    if (back[0] !== fwd[0] || back[1] !== fwd[1]) {
      return bearingRadians(back[0], back[1], fwd[0], fwd[1]);
    }
  }
  return null;
}
