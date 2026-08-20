import maplibregl from "maplibre-gl";

const FLASH_DURATION_MS = 4000;

/** arrival_observed_at zamani gecildiginde durakta kisa bir vurgulama halkasi (CSS pulse) gosterir. */
export class ArrivalLayer {
  constructor(map) {
    this._map = map;
    this._triggered = new Set();
    this._markers = [];
  }

  reset() {
    for (const marker of this._markers) marker.remove();
    this._markers = [];
    this._triggered.clear();
  }

  /** virtualNowMs: replay'in su anki zamani (epoch ms). arrivals: [{id, lat, lon, stop_name, arrival_observed_at}] */
  tick(virtualNowMs, arrivals) {
    for (const a of arrivals) {
      const t = Date.parse(a.arrival_observed_at);
      if (t <= virtualNowMs && !this._triggered.has(a.id)) {
        this._triggered.add(a.id);
        this._flash(a);
      }
    }
  }

  _flash(arrival) {
    const el = document.createElement("div");
    el.className = "arrival-pulse";
    el.title = `Varış: ${arrival.stop_name} (araç ${arrival.vehicle_id})`;

    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([arrival.lon, arrival.lat])
      .addTo(this._map);
    this._markers.push(marker);

    setTimeout(() => {
      marker.remove();
      this._markers = this._markers.filter((m) => m !== marker);
    }, FLASH_DURATION_MS);
  }
}
