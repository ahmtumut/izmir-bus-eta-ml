const BASE_URL = "http://127.0.0.1:8000";

async function getJson(path) {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`${path} -> HTTP ${res.status}`);
  }
  return res.json();
}

export function fetchRoutes() {
  return getJson("/api/routes");
}

export function fetchStops() {
  return getJson("/api/stops");
}

export function fetchSessions() {
  return getJson("/api/replay/sessions");
}

export function fetchObservations(start, end, lineNos) {
  const params = new URLSearchParams({ start, end, line_no: lineNos.join(",") });
  return getJson(`/api/replay/observations?${params}`);
}

export function fetchArrivals(start, end, lineNos) {
  const params = new URLSearchParams({ start, end, line_no: lineNos.join(",") });
  return getJson(`/api/replay/arrivals?${params}`);
}

export function fetchEta(vehicleId, lineNo, at) {
  const params = new URLSearchParams({ vehicle_id: vehicleId, line_no: lineNo, at });
  return getJson(`/api/replay/eta?${params}`);
}

export function fetchLiveStatus() {
  return getJson("/api/live/status");
}

export function fetchLiveObservations(lineNos, maxAgeSeconds = 90) {
  const params = new URLSearchParams({ line_no: lineNos.join(","), max_age_seconds: maxAgeSeconds });
  return getJson(`/api/live/observations?${params}`);
}

export function fetchStopEta(targetStopId, at) {
  const params = new URLSearchParams({ target_stop_id: targetStopId, at });
  return getJson(`/api/replay/stop-eta?${params}`);
}
