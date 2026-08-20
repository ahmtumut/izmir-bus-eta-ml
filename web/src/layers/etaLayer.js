import maplibregl from "maplibre-gl";
import { fetchEta } from "../api.js";

const REFRESH_INTERVAL_MS = 3000;

/**
 * Aktif araclarin ustunde model ETA tahminini gosteren DOM-marker katmani.
 * Performans icin: her tick'te degil, REFRESH_INTERVAL_MS'de bir, ve
 * sadece GOOD/DEGRADED aractlar icin (REJECTED icin model guvenilir
 * degil - route_id/distance_along_route_m genelde yok).
 */
export class EtaLayer {
  /** onChange(vehicleId, etaDataOrNull): panel/tablo gibi disaridaki UI'i guncel tutmak icin. */
  constructor(map, onChange = null) {
    this._map = map;
    this._markers = new Map(); // vehicle_id -> maplibregl.Marker
    this._lastFetch = new Map(); // vehicle_id -> ms epoch (gercek zaman, throttle icin)
    this._enabled = true;
    this._onChange = onChange;
  }

  setEnabled(enabled) {
    this._enabled = enabled;
    if (!enabled) this._clearAll();
  }

  _clearAll() {
    for (const marker of this._markers.values()) marker.remove();
    this._markers.clear();
  }

  /** virtualMs: replay'in sanal zamani. positions: Map(vehicle_id -> {lat, lon, map_match_quality, line_no}) */
  tick(virtualMs, positions) {
    if (!this._enabled) return;
    const nowReal = performance.now();
    const seen = new Set();

    for (const [vehicleId, pos] of positions) {
      if (pos.map_match_quality === "REJECTED") continue;
      seen.add(vehicleId);

      const lastFetch = this._lastFetch.get(vehicleId) ?? -Infinity;
      if (nowReal - lastFetch < REFRESH_INTERVAL_MS) {
        this._moveMarker(vehicleId, pos);
        continue;
      }
      this._lastFetch.set(vehicleId, nowReal);

      const atIso = new Date(virtualMs).toISOString();
      fetchEta(vehicleId, pos.line_no, atIso)
        .then((eta) => {
          this._showEta(vehicleId, pos, eta);
          this._onChange?.(vehicleId, eta);
        })
        .catch(() => {
          this._removeMarker(vehicleId); // 404/422: hedef durak yok veya gozlem uygunsuz - sessizce atla
          this._onChange?.(vehicleId, null);
        });
    }

    for (const vehicleId of this._markers.keys()) {
      if (!seen.has(vehicleId)) {
        this._removeMarker(vehicleId);
        this._onChange?.(vehicleId, null);
      }
    }
  }

  _moveMarker(vehicleId, pos) {
    const marker = this._markers.get(vehicleId);
    if (marker) marker.setLngLat([pos.lon, pos.lat]);
  }

  _showEta(vehicleId, pos, eta) {
    const minutes = (eta.predicted_eta_seconds / 60).toFixed(1);
    const warn = eta.extrapolation_warning ? " ⚠" : "";
    const label = `${minutes} dk → ${eta.stop_name}${warn}`;

    let marker = this._markers.get(vehicleId);
    if (!marker) {
      const el = document.createElement("div");
      el.className = "eta-label";
      marker = new maplibregl.Marker({ element: el, anchor: "bottom", offset: [0, -10] })
        .setLngLat([pos.lon, pos.lat])
        .addTo(this._map);
      this._markers.set(vehicleId, marker);
    } else {
      marker.setLngLat([pos.lon, pos.lat]);
    }
    marker.getElement().textContent = label;
  }

  _removeMarker(vehicleId) {
    const marker = this._markers.get(vehicleId);
    if (marker) {
      marker.remove();
      this._markers.delete(vehicleId);
    }
  }
}
