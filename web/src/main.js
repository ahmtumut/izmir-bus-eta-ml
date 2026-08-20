import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { fetchRoutes, fetchStops, fetchSessions, fetchObservations, fetchArrivals } from "./api.js";
import { drawRoutes } from "./layers/routeLayer.js";
import { drawStops } from "./layers/stopLayer.js";
import { VehicleLayer } from "./layers/vehicleLayer.js";
import { ArrivalLayer } from "./layers/arrivalLayer.js";
import { EtaLayer } from "./layers/etaLayer.js";
import { ReplayController } from "./replay-controller.js";
import { LiveController } from "./live-controller.js";
import { buildRouteIndex } from "./route-geometry.js";
import { clearRouteSelection } from "./layers/routeLayer.js";

// MapLibre [lon, lat] sirasi kullanir (Leaflet'in [lat, lon]'unun tersi).
const IZMIR_CENTER = [27.14, 38.42];
const OPENFREEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

const map = new maplibregl.Map({
  container: "map",
  style: OPENFREEMAP_STYLE,
  center: IZMIR_CENTER,
  zoom: 12,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }));

const viewToggleBtn = document.getElementById("view-toggle-btn");
const VIEW_3D_PITCH = 60;
const VIEW_3D_BEARING = -17;
let is3D = false;

viewToggleBtn.addEventListener("click", () => {
  is3D = !is3D;
  map.easeTo({
    pitch: is3D ? VIEW_3D_PITCH : 0,
    bearing: is3D ? VIEW_3D_BEARING : 0,
    duration: 800,
  });
  viewToggleBtn.textContent = is3D ? "🗺️ 2D Göster" : "🏙️ 3D Göster";
  viewToggleBtn.classList.toggle("active", is3D);
});

// Kullanici sag-tik/iki parmak ile manuel egim verirse buton durumunu
// senkron tut (asiri hassas olmasin diye kucuk bir esik kullanilir).
map.on("pitchend", () => {
  const manualIs3D = map.getPitch() > 5;
  if (manualIs3D !== is3D) {
    is3D = manualIs3D;
    viewToggleBtn.textContent = is3D ? "🗺️ 2D Göster" : "🏙️ 3D Göster";
    viewToggleBtn.classList.toggle("active", is3D);
  }
});

const etaTablePanel = document.getElementById("eta-table-panel");
const etaTableBody = document.getElementById("eta-table-body");
const etaRows = new Map(); // vehicle_id -> latest eta data

function renderEtaTable() {
  const sorted = [...etaRows.entries()].sort((a, b) => a[1].predicted_eta_seconds - b[1].predicted_eta_seconds);
  etaTableBody.innerHTML = sorted
    .map(([vehicleId, eta]) => {
      const cls = eta.extrapolation_warning ? ' class="warn"' : "";
      const minutes = (eta.predicted_eta_seconds / 60).toFixed(1);
      return `<tr${cls}><td>${vehicleId}</td><td>${eta.line_no}</td><td>${eta.stop_name}</td><td>${minutes} dk</td></tr>`;
    })
    .join("");
  etaTablePanel.hidden = etaRows.size === 0;
}

const statusEl = document.getElementById("status");
const sessionSelect = document.getElementById("session-select");
const loadBtn = document.getElementById("load-btn");
const etaToggle = document.getElementById("eta-toggle");
const transportControls = document.getElementById("transport-controls");
const playBtn = document.getElementById("play-btn");
const speedSelect = document.getElementById("speed-select");
const scrubber = document.getElementById("scrubber");
const clockEl = document.getElementById("clock");

const vehicleDetailPanel = document.getElementById("vehicle-detail-panel");
const vehicleDetailBody = document.getElementById("vehicle-detail-body");
const vehicleDetailClose = document.getElementById("vehicle-detail-close");
const vehicleFollowBtn = document.getElementById("vehicle-follow-btn");
const scrubberTicks = document.getElementById("scrubber-ticks");

const modeReplayBtn = document.getElementById("mode-replay-btn");
const modeLiveBtn = document.getElementById("mode-live-btn");
const replayControlsEl = document.getElementById("replay-controls");
const liveControlsEl = document.getElementById("live-controls");
const liveStatusEl = document.getElementById("live-status");

let controller = null;
let currentArrivals = [];
let vehicleLayer, arrivalLayer, etaLayer, liveController;
let routeIndex = null; // route-geometry.js:buildRouteIndex() ciktisi, replay interpolasyonu icin
let shownVehicleId = null; // detay paneli su an hangi arac icin acik
let followedVehicleId = null; // kamera bu araci takip ediyor (null = takip yok)
let currentTimeMs = Date.now(); // replay'de virtualMs, canli modda Date.now() - durak tiklamasinda stop-eta sorgusu icin

function setStatus(msg) {
  statusEl.textContent = msg;
}

function selectedLines() {
  return [...document.querySelectorAll("#line-checkboxes input:checked")].map((el) => el.value);
}

/** Arrival event'lerini scrubber uzerinde kucuk kirmizi cizgiler olarak
 * isaretler - kullanicinin "varis anlarini" zaman ekseninde gormesini saglar. */
function renderScrubberTicks(startMs, endMs) {
  const durationMs = endMs - startMs;
  scrubberTicks.innerHTML = currentArrivals
    .map((a) => {
      const t = Date.parse(a.arrival_observed_at);
      if (t < startMs || t > endMs) return "";
      const pct = ((t - startMs) / durationMs) * 100;
      return `<div class="scrubber-tick" style="left:${pct.toFixed(2)}%" title="${a.stop_name}"></div>`;
    })
    .join("");
}

/** followedVehicleId doluysa, o aracin o anki pozisyonuna kamerayi kaydirir
 * (arac gorunur degilse - ornegin oturum disinda kaldiysa - hicbir sey yapmaz). */
function followVehicleIfNeeded(positions) {
  if (!followedVehicleId) return;
  const pos = positions.get(followedVehicleId);
  if (pos) map.setCenter([pos.lon, pos.lat]);
}

async function loadStaticLayersAndSessions() {
  setStatus("Statik katmanlar yükleniyor...");
  const [routes, stops, sessions] = await Promise.all([fetchRoutes(), fetchStops(), fetchSessions()]);
  const bounds = drawRoutes(map, routes);
  drawStops(map, stops, () => currentTimeMs);
  if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 40, duration: 0 });
  routeIndex = buildRouteIndex(routes);
  liveController?.setRouteIndex(routeIndex);

  for (const s of sessions.sessions) {
    const opt = document.createElement("option");
    opt.value = `${s.started_at}|${s.ended_at}`;
    const started = new Date(s.started_at);
    opt.textContent = `${started.toLocaleString("tr-TR")} — ${s.observation_count} gözlem`;
    sessionSelect.appendChild(opt);
  }
  setStatus(`${routes.routes.length} hat, ${stops.stops.length} durak, ${sessions.sessions.length} oturum yüklendi.`);
}

async function loadSelectedSession() {
  const [start, end] = sessionSelect.value.split("|");
  const lines = selectedLines();
  if (lines.length === 0) {
    setStatus("En az bir hat seçmelisin.");
    return;
  }

  setStatus("Gözlemler yükleniyor...");
  const [obsResp, arrivalsResp] = await Promise.all([
    fetchObservations(start, end, lines),
    fetchArrivals(start, end, lines),
  ]);
  currentArrivals = arrivalsResp.arrivals;
  arrivalLayer.reset();
  etaRows.clear();
  renderEtaTable();

  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  renderScrubberTicks(startMs, endMs);

  controller = new ReplayController({
    observations: obsResp.observations,
    startMs,
    endMs,
    routeIndex,
    onTick: (virtualMs, positions) => {
      currentTimeMs = virtualMs;
      vehicleLayer.updatePositions(positions);
      arrivalLayer.tick(virtualMs, currentArrivals);
      etaLayer.tick(virtualMs, positions);
      followVehicleIfNeeded(positions);
      scrubber.value = Math.round(((virtualMs - startMs) / (endMs - startMs)) * 1000);
      clockEl.textContent = new Date(virtualMs).toLocaleTimeString("tr-TR");
    },
  });
  controller.setSpeed(Number(speedSelect.value));
  controller.seekFraction(0);

  transportControls.hidden = false;
  playBtn.textContent = "▶ Oynat";
  setStatus(`${obsResp.count} gözlem, ${arrivalsResp.count} arrival event yüklendi.`);
}

function clearAllLayers() {
  vehicleLayer.updatePositions(new Map());
  arrivalLayer.reset();
  etaRows.clear();
  renderEtaTable();
  hideVehicleDetail();
  followedVehicleId = null;
}

const QUALITY_LABELS = {
  GOOD: "GOOD (yüksek güven)",
  DEGRADED: "DEGRADED (orta güven)",
  REJECTED: "REJECTED (görsel amaçlı, modele dahil değil)",
};

function updateFollowBtn() {
  const isFollowingShown = shownVehicleId != null && shownVehicleId === followedVehicleId;
  vehicleFollowBtn.textContent = isFollowingShown ? "⏹ Takibi durdur" : "📍 Bu aracı takip et";
  vehicleFollowBtn.classList.toggle("active", isFollowingShown);
}

/** speedHistory: vehicleLayer.pick()'ten gelen [{observedAt, speedMps}, ...]
 * (kronolojik). Son birkac GERCEK gozlem arasindaki hizi kucuk bir inline
 * SVG cizgi grafik olarak gosterir - "bu arac az once ne kadar hizliydi/
 * yavasladi mi" sorusuna tek bakista cevap verir. En az 2 hiz orneği
 * (3 gozlem) yoksa null doner (henuz cizecek yeterli veri yok). */
function speedSparklineSvg(speedHistory) {
  const speeds = speedHistory.filter((p) => p.speedMps != null).map((p) => p.speedMps * 3.6); // km/h
  if (speeds.length < 2) return null;

  const w = 220;
  const h = 40;
  const pad = 4;
  const max = Math.max(...speeds, 1);
  const min = 0; // hiz ekseni her zaman 0'dan baslasin - "duruyor" ile "yavas" ayrimi net olsun
  const stepX = (w - pad * 2) / (speeds.length - 1);
  const points = speeds
    .map((s, i) => {
      const x = pad + i * stepX;
      const y = h - pad - ((s - min) / (max - min || 1)) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = speeds[speeds.length - 1];

  return `
    <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" class="speed-sparkline">
      <polyline points="${points}" fill="none" stroke="#2c6ecb" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
    </svg>
    <span class="speed-sparkline-label">şu an ~${last.toFixed(0)} km/h (son ${speeds.length} örnek)</span>
  `;
}

function showVehicleDetail(hit) {
  shownVehicleId = hit.vehicleId;
  const obs = hit.meta ?? {};
  const qualityLabel = QUALITY_LABELS[hit.quality] ?? "Bilinmiyor (henüz map-match edilmemiş)";
  const observedAt = obs.observed_at ? new Date(obs.observed_at).toLocaleTimeString("tr-TR") : "—";
  const rows = [
    ["Araç ID", hit.vehicleId],
    ["Hat", obs.line_no ?? "—"],
    ["Konum kalitesi", qualityLabel],
    ["Son gözlem", observedAt],
    ["Koordinat", `${hit.lat.toFixed(5)}, ${hit.lon.toFixed(5)}`],
  ];
  if (obs.distance_to_route_m != null) rows.push(["Rotaya mesafe", `${obs.distance_to_route_m.toFixed(0)} m`]);
  if (obs.progress_along_route != null) rows.push(["Rota ilerlemesi", `${(obs.progress_along_route * 100).toFixed(0)}%`]);

  const sparkline = speedSparklineSvg(hit.speedHistory ?? []);

  vehicleDetailBody.innerHTML =
    rows.map(([label, value]) => `<div class="detail-row"><span>${label}</span><strong>${value}</strong></div>`).join("") +
    (sparkline ? `<div class="detail-sparkline"><span>Son hız geçmişi</span>${sparkline}</div>` : "");
  vehicleDetailPanel.hidden = false;
  updateFollowBtn();
}

function hideVehicleDetail() {
  vehicleDetailPanel.hidden = true;
  shownVehicleId = null;
}

function selectedLiveLines() {
  return [...document.querySelectorAll("#live-line-checkboxes input:checked")].map((el) => el.value);
}

function switchToReplay() {
  liveController.stop();
  clearAllLayers();
  modeReplayBtn.classList.add("active");
  modeLiveBtn.classList.remove("active");
  replayControlsEl.hidden = false;
  liveControlsEl.hidden = true;
  setStatus("Replay moduna geçildi.");
}

function switchToLive() {
  if (controller) controller.pause();
  clearAllLayers();
  modeLiveBtn.classList.add("active");
  modeReplayBtn.classList.remove("active");
  replayControlsEl.hidden = true;
  liveControlsEl.hidden = false;
  liveController.start(selectedLiveLines());
}

map.on("load", () => {
  vehicleLayer = new VehicleLayer();
  map.addLayer(vehicleLayer);
  arrivalLayer = new ArrivalLayer(map);
  etaLayer = new EtaLayer(map, (vehicleId, eta) => {
    if (eta) etaRows.set(vehicleId, eta);
    else etaRows.delete(vehicleId);
    renderEtaTable();
  });

  liveController = new LiveController((nowMs, positions, arrivals, status) => {
    currentTimeMs = nowMs;
    vehicleLayer.updatePositions(positions);
    arrivalLayer.tick(nowMs, arrivals);
    etaLayer.tick(nowMs, positions);
    followVehicleIfNeeded(positions);

    if (status.error) {
      liveStatusEl.className = "inactive";
      liveStatusEl.textContent = `Bağlantı hatası: ${status.error}`;
    } else if (status.collector_active) {
      liveStatusEl.className = "active";
      liveStatusEl.textContent =
        `🟢 Collector aktif — ${positions.size} araç görünüyor, ` +
        `son gözlem ${status.seconds_since_last_observation.toFixed(0)}sn önce.`;
    } else {
      const ageMin = status.seconds_since_last_observation != null
        ? (status.seconds_since_last_observation / 60).toFixed(1)
        : "?";
      liveStatusEl.className = "inactive";
      liveStatusEl.textContent =
        `🔴 Collector çalışmıyor gibi görünüyor (son gözlem ${ageMin}dk önce). ` +
        `Ayrı bir terminalde çalıştır: python -m scripts.run_dual_collector --minutes 90`;
    }
  });

  loadBtn.addEventListener("click", () => {
    loadSelectedSession().catch((err) => setStatus(`Hata: ${err.message}`));
  });

  playBtn.addEventListener("click", () => {
    if (!controller) return;
    controller.toggle();
    playBtn.textContent = controller._playing ? "⏸ Duraklat" : "▶ Oynat";
  });

  speedSelect.addEventListener("change", () => {
    controller?.setSpeed(Number(speedSelect.value));
  });

  etaToggle.addEventListener("change", () => {
    etaLayer.setEnabled(etaToggle.checked);
    if (!etaToggle.checked) {
      etaRows.clear();
      renderEtaTable();
    }
  });

  scrubber.addEventListener("input", () => {
    if (!controller) return;
    controller.pause();
    playBtn.textContent = "▶ Oynat";
    controller.seekFraction(Number(scrubber.value) / 1000);
  });

  modeReplayBtn.addEventListener("click", switchToReplay);
  modeLiveBtn.addEventListener("click", switchToLive);

  map.on("click", (e) => {
    const hit = vehicleLayer.pick(map, e.point);
    if (hit) {
      showVehicleDetail(hit);
      return;
    }
    hideVehicleDetail();
    // Bos alana (arac/route/durak disi) tiklayinca hat vurgulamasini da temizle.
    const featuresHere = map.queryRenderedFeatures(e.point, {
      layers: ["routes-line-solid", "routes-line-dashed", "stops-circle"],
    });
    if (featuresHere.length === 0) clearRouteSelection(map);
  });
  vehicleDetailClose.addEventListener("click", hideVehicleDetail);

  vehicleFollowBtn.addEventListener("click", () => {
    followedVehicleId = followedVehicleId === shownVehicleId ? null : shownVehicleId;
    updateFollowBtn();
  });

  document.querySelectorAll("#live-line-checkboxes input").forEach((el) => {
    el.addEventListener("change", () => {
      liveController.stop();
      clearAllLayers();
      liveController.start(selectedLiveLines());
    });
  });

  loadStaticLayersAndSessions().catch(
    (err) => setStatus(`Yükleme hatası: ${err.message} (backend çalışıyor mu? uvicorn app.api.main:app --port 8000)`)
  );
});
