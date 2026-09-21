const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function getJSON(path, params) {
  const url = new URL(BASE + path);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  meta: () => getJSON("/api/meta"),
  dashboard: () => getJSON("/api/dashboard"),
  hotPaths: (n = 10) => getJSON("/api/hot-paths", { n }),
  corridorMap: () => getJSON("/api/corridor-map"),
  weather: () => getJSON("/api/weather"),
  pairs: () => getJSON("/api/pairs"),
  pairSeries: (source, sink, params) => getJSON(`/api/pairs/${source}/${sink}/series`, params),
  pairParticipants: (source, sink) => getJSON(`/api/pairs/${source}/${sink}/participants`),
  participants: () => getJSON("/api/participants"),
  participantDetail: (name) => getJSON(`/api/participants/${encodeURIComponent(name)}`),
  opportunityScores: () => getJSON("/api/opportunity-scores"),
  liveStatus: () => getJSON("/api/live/status"),
  bindingConstraints: (dateFrom, dateTo) =>
    getJSON("/api/live/binding-constraints", { date_from: dateFrom, date_to: dateTo }),
};
