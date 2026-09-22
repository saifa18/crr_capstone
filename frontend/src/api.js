const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Distinguishes two genuinely different failure modes so pages can show the
// right message instead of always saying "can't reach the backend":
//   - a NETWORK failure (fetch() itself threw -- the browser never got an
//     HTTP response at all: FastAPI isn't running, wrong port, DNS, etc.)
//   - an HTTP-level error response (FastAPI IS reachable and answered --
//     e.g. a 502 wrapping a real ERCOT upstream failure, a 422, a 404).
// Both surface as a plain Error with a clear, self-describing message; the
// `isNetworkError` flag lets a caller branch on it if it needs to, but
// every page today just renders `error.message` directly, so getting the
// message itself right is what actually fixes the "backend unreachable"
// mislabeling for an unrelated ERCOT-side error.
async function getJSON(path, params) {
  const url = new URL(BASE + path);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }

  let res;
  try {
    res = await fetch(url.toString());
  } catch (networkErr) {
    const err = new Error(
      `Backend unavailable -- couldn't reach ${BASE}. Is the FastAPI server running ` +
        `(cd backend && uvicorn app.main:app --reload --port 8000)? (${networkErr.message})`
    );
    err.isNetworkError = true;
    throw err;
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  health: () => getJSON("/health"),
  meta: () => getJSON("/api/meta"),
  dashboard: () => getJSON("/api/dashboard"),
  hotPaths: (n = 10) => getJSON("/api/hot-paths", { n }),
  corridorMap: () => getJSON("/api/corridor-map"),
  weather: () => getJSON("/api/weather"),
  pairs: () => getJSON("/api/pairs"),
  pairSeries: (source, sink, params) =>
    getJSON(`/api/pairs/${encodeURIComponent(source)}/${encodeURIComponent(sink)}/series`, params),
  pairParticipants: (source, sink, crrType) =>
    getJSON(`/api/pairs/${encodeURIComponent(source)}/${encodeURIComponent(sink)}/participants`, { crr_type: crrType }),
  participants: () => getJSON("/api/participants"),
  participantDetail: (name, period, source, sink, page, pageSize, crrType) =>
    getJSON(`/api/participants/${encodeURIComponent(name)}`, {
      period, source, sink, page, page_size: pageSize, crr_type: crrType,
    }),
  opportunityScores: () => getJSON("/api/opportunity-scores"),
  liveStatus: () => getJSON("/api/live/status"),
  // Server-side paginated/filtered/sorted ({items, page, page_size, total,
  // total_pages}), plus constraint_options/summary/tier_thresholds computed
  // from the full window regardless of the current page/filter -- see
  // live_binding_constraints's docstring in main.py.
  bindingConstraints: (params) => getJSON("/api/live/binding-constraints", params),
  settlementHistory: (source, sink, params) =>
    getJSON(`/api/pairs/${encodeURIComponent(source)}/${encodeURIComponent(sink)}/settlement-history`, params),
  settlementSummary: (params) => getJSON("/api/pairs/settlement-summary", params),
  // Cross-corridor settlement leaderboard: omit source/sink for "all
  // tracked paths", omit participant for "all participants". Server-side
  // paginated ({items, page, page_size, total, total_pages}), same
  // contract as participantDetail's recent_activity.
  settlementLeaderboard: (params) => getJSON("/api/settlement-leaderboard", params),
};
