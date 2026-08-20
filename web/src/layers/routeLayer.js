import maplibregl from "maplibre-gl";

const LINE_COLORS = { 515: "#1f77b4", 121: "#2ca02c", 761: "#9467bd" };
const DIMMED_OPACITY = 0.12;
const NORMAL_OPACITY = 0.6;
const SELECTED_OPACITY = 0.95;

let selectedLine = null;

function opacityExpression() {
  if (!selectedLine) return NORMAL_OPACITY;
  return ["case", ["==", ["get", "line_no"], selectedLine], SELECTED_OPACITY, DIMMED_OPACITY];
}

function applySelection(map) {
  const expr = opacityExpression();
  map.setPaintProperty("routes-line-solid", "line-opacity", expr);
  map.setPaintProperty("routes-line-dashed", "line-opacity", expr);
  map.setPaintProperty("routes-arrows", "text-opacity", selectedLine ? opacityExpression() : 0.8);
}

/** Doner: maplibregl.LngLatBounds - tum route noktalarini kapsayan sinir
 * (main.js'de ilk yuklemede zoom-to-fit icin kullanilir). */
export function drawRoutes(map, routesResponse) {
  const bounds = new maplibregl.LngLatBounds();
  const features = routesResponse.routes.map((route) => {
    for (const c of route.coordinates) bounds.extend(c);
    return {
      type: "Feature",
      properties: {
        line_no: route.line_no,
        direction: route.direction,
        color: LINE_COLORS[route.line_no] ?? "#555",
        width: route.direction === 0 ? 3 : 2,
        dash: route.direction === 1,
      },
      geometry: { type: "LineString", coordinates: route.coordinates },
    };
  });

  const featureCollection = { type: "FeatureCollection", features };
  map.addSource("routes", { type: "geojson", data: featureCollection });
  // Oklar icin AYRI bir kaynak (ayni veri, farkli source id) - ayni geojson
  // source uzerinde hem "line" hem "symbol" (text-field) katmani birlikte
  // bulunursa MapLibre'de line katmanlarinin hic render edilmedigi bir
  // hataya rastlandi (arastirildi - line-only source'lar sorunsuz calisiyor,
  // symbol eklenince AYNI source'taki line katmanlari da bozuluyor). Ayri
  // source kullanmak bu sorunu tamamen atlatiyor.
  map.addSource("routes-arrows-src", { type: "geojson", data: featureCollection });

  // line-dasharray MapLibre'de data-expression (per-feature) kabul etmiyor,
  // sabit olmali - bu yuzden yon=0 (duz) / yon=1 (kesikli) icin iki ayri
  // katman, ayni source uzerinde filter ile ayriliyor.
  map.addLayer({
    id: "routes-line-solid",
    type: "line",
    source: "routes",
    filter: ["==", ["get", "dash"], false],
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": ["get", "color"], "line-width": ["get", "width"], "line-opacity": NORMAL_OPACITY },
  });
  map.addLayer({
    id: "routes-line-dashed",
    type: "line",
    source: "routes",
    filter: ["==", ["get", "dash"], true],
    layout: { "line-join": "round", "line-cap": "round" },
    paint: {
      "line-color": ["get", "color"],
      "line-width": ["get", "width"],
      "line-opacity": NORMAL_OPACITY,
      "line-dasharray": [2, 1.5],
    },
  });

  // Hat yonunu gostermek icin cizgi boyunca tekrar eden ok isaretleri -
  // symbol-placement:line + text-rotation-alignment:map, cizginin egimini
  // otomatik takip eder (ozel ikon/resim gerekmiyor). ONEMLI: "▶" (U+25B6)
  // gibi ozel Unicode semboller OpenFreeMap'in glyph setinde bulunmuyor -
  // eksik bir glyph, MapLibre'de bu source'u paylasan DIGER katmanlarin da
  // (routes-line-solid/dashed) render edilmemesine yol acan bir hataya
  // neden oluyordu (arastirildi - glyph'i kaldirinca diger katmanlar
  // duzeldi). Duz ASCII ">" karakteri her font setinde bulunur, guvenli.
  map.addLayer({
    id: "routes-arrows",
    type: "symbol",
    source: "routes-arrows-src",
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 100,
      "text-field": ">",
      "text-font": ["Noto Sans Regular"],
      "text-size": 13,
      "text-rotation-alignment": "map",
      "text-keep-upright": false,
      "text-allow-overlap": true,
      "text-ignore-placement": true,
    },
    paint: { "text-color": ["get", "color"], "text-opacity": 0.8 },
  });

  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
  for (const layerId of ["routes-line-solid", "routes-line-dashed"]) {
    map.on("mouseenter", layerId, (e) => {
      map.getCanvas().style.cursor = "pointer";
      const props = e.features[0].properties;
      popup.setLngLat(e.lngLat).setText(`Hat ${props.line_no} (yön ${props.direction})`).addTo(map);
    });
    map.on("mouseleave", layerId, () => {
      map.getCanvas().style.cursor = "";
      popup.remove();
    });
    // Tiklayinca secili hatti vurgula, digerlerini soluklastir - ayni hatta
    // tekrar tiklayinca (veya reset cagrilinca) normale doner.
    map.on("click", layerId, (e) => {
      const clicked = e.features[0].properties.line_no;
      selectedLine = selectedLine === clicked ? null : clicked;
      applySelection(map);
    });
  }

  return bounds;
}

/** Secili hat vurgulamasini temizler (dis modullerden cagirilabilir, orn.
 * bos harita alanina tiklaninca main.js'den). */
export function clearRouteSelection(map) {
  if (!selectedLine) return;
  selectedLine = null;
  applySelection(map);
}
