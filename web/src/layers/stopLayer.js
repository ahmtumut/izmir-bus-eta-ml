import maplibregl from "maplibre-gl";
import { fetchStopEta } from "../api.js";

const PILOT_LINES = new Set(["515", "121", "761"]);

/** getCurrentTimeMs: () => number - o anki replay sanal zamani ya da (canli
 * modda) Date.now(). Duraga tiklaninca "buraya en yakin otobus ne zaman
 * varir" sorgusu bu zamana gore yapilir. */
export function drawStops(map, stopsResponse, getCurrentTimeMs) {
  const seen = new Set();
  const features = [];
  for (const stop of stopsResponse.stops) {
    if (seen.has(stop.stop_id)) continue;
    seen.add(stop.stop_id);
    const linesThrough = stop.lines_through ?? [];
    const isPilot = linesThrough.some((l) => PILOT_LINES.has(String(l)));
    features.push({
      type: "Feature",
      properties: {
        stop_id: stop.stop_id,
        stop_name: stop.stop_name,
        lines_through: linesThrough.join(", ") || "—",
        is_pilot: isPilot,
      },
      geometry: { type: "Point", coordinates: [stop.lon, stop.lat] },
    });
  }

  // Pilot hat disindaki duraklar SILINMIYOR (source'ta hepsi kalir, ileride
  // istenirse filtre degistirilip tekrar gosterilebilir) - sadece varsayilan
  // olarak haritada gizleniyor, gorsel karmasayi azaltmak icin.
  map.addSource("stops", { type: "geojson", data: { type: "FeatureCollection", features } });
  map.addLayer({
    id: "stops-circle",
    type: "circle",
    source: "stops",
    filter: ["==", ["get", "is_pilot"], true],
    paint: {
      "circle-radius": 3,
      "circle-color": "#fff",
      "circle-stroke-color": "#333",
      "circle-stroke-width": 1,
    },
  });

  const hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
  map.on("mouseenter", "stops-circle", (e) => {
    map.getCanvas().style.cursor = "pointer";
    const props = e.features[0].properties;
    hoverPopup.setLngLat(e.lngLat).setText(props.stop_name).addTo(map);
  });
  map.on("mouseleave", "stops-circle", () => {
    map.getCanvas().style.cursor = "";
    hoverPopup.remove();
  });

  // Tiklamada kalici bir popup - hangi hatlarin gectigini ve en yakin
  // otobusun ETA'sini gosterir (once temel bilgi + "yukleniyor", sonra
  // /api/replay/stop-eta cevabiyla guncellenir).
  const clickPopup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: "260px" });
  map.on("click", "stops-circle", (e) => {
    const props = e.features[0].properties;
    const requestId = Symbol();
    clickPopup._stopEtaRequestId = requestId;

    clickPopup
      .setLngLat(e.lngLat)
      .setHTML(renderStopPopup(props, null, true))
      .addTo(map);

    const atIso = new Date(getCurrentTimeMs()).toISOString();
    fetchStopEta(props.stop_id, atIso)
      .then((resp) => {
        if (clickPopup._stopEtaRequestId !== requestId) return; // baska bir durak tiklandi, gecersiz
        clickPopup.setHTML(renderStopPopup(props, resp.candidates, false));
      })
      .catch(() => {
        if (clickPopup._stopEtaRequestId !== requestId) return;
        clickPopup.setHTML(renderStopPopup(props, [], false));
      });
  });
}

function renderStopPopup(props, candidates, loading) {
  let etaHtml;
  if (loading) {
    etaHtml = `<div style="color:#888;font-size:11px;margin-top:6px;">Yaklaşan otobüsler sorgulanıyor...</div>`;
  } else if (!candidates || candidates.length === 0) {
    etaHtml = `<div style="color:#888;font-size:11px;margin-top:6px;">Şu an yaklaşan bilinen bir otobüs yok.</div>`;
  } else {
    const rows = candidates
      .slice(0, 5)
      .map((c) => {
        const minutes = (c.predicted_eta_seconds / 60).toFixed(1);
        const warn = c.extrapolation_warning ? " ⚠" : "";
        return `<div style="display:flex;justify-content:space-between;gap:8px;font-size:12px;padding:2px 0;">
          <span>Araç ${c.vehicle_id} (Hat ${c.line_no})</span><strong>${minutes} dk${warn}</strong>
        </div>`;
      })
      .join("");
    etaHtml = `<div style="margin-top:6px;border-top:1px solid #eee;padding-top:4px;">
      <div style="font-size:11px;color:#666;margin-bottom:2px;">En yakın otobüsler:</div>
      ${rows}
    </div>`;
  }

  return (
    `<strong>${props.stop_name}</strong><br/>` +
    `<span style="color:#666;font-size:11px;">Durak ${props.stop_id}</span><br/>` +
    `<span style="font-size:12px;">Hatlar: ${props.lines_through}</span>` +
    etaHtml
  );
}
