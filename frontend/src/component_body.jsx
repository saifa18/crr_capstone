
import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, ReferenceLine, Legend,
} from "recharts";
import {
  Zap, Activity, Users, GitBranch, TrendingUp, TrendingDown, Minus,
  ChevronRight, Info, Gauge, ArrowRight, Download, Wifi, WifiOff,
  Search, X, Wind, Thermometer, CloudSun, AlertTriangle,
} from "lucide-react";

const TIER_COLOR = {
  High: { text: "#3DDC97", bg: "rgba(61,220,151,0.12)", border: "rgba(61,220,151,0.4)" },
  Medium: { text: "#E8B339", bg: "rgba(232,179,57,0.12)", border: "rgba(232,179,57,0.4)" },
  Low: { text: "#7A8699", bg: "rgba(122,134,153,0.12)", border: "rgba(122,134,153,0.4)" },
};

const FONT_DISPLAY = "'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif";
const FONT_MONO = "'IBM Plex Mono', ui-monospace, 'SF Mono', monospace";

const TOU_OPTIONS = [
  ["ALL", "All Hours"],
  ["PEAK_WD", "Peak Weekday"],
  ["PEAK_WE", "Peak Weekend"],
  ["OFF_PEAK", "Off-Peak"],
];

const COMPARE_COLORS = ["#3DDC97", "#2E7CE0", "#E8B339"];

// Real-world regions behind the tracked corridors, for the live weather
// panel. Wind at West/Panhandle drives renewable output on the exact paths
// this app scores highest (PERMIAN_SOLAR_RN->HB_WEST, HB_WEST->HB_HOUSTON,
// PANHANDLE_WIND_RN->HB_NORTH); temperature at Houston/DFW drives the AC
// load those paths are congested trying to reach. This is real physical
// context for the numbers elsewhere in the app, not a forecast of them.
const WEATHER_REGIONS = [
  { key: "west", label: "West Texas / Permian", relates: "HB_WEST, PERMIAN_SOLAR_RN", lat: 31.9973, lon: -102.0779 },
  { key: "panhandle", label: "Texas Panhandle", relates: "HB_PAN, PANHANDLE_WIND_RN", lat: 35.222, lon: -101.8313 },
  { key: "houston", label: "Houston / Gulf Coast", relates: "HB_HOUSTON, LZ_HOUSTON", lat: 29.7604, lon: -95.3698 },
  { key: "north", label: "North Texas / DFW", relates: "HB_NORTH, LZ_RAYBN", lat: 32.7767, lon: -96.797 },
];

function weatherCodeLabel(code) {
  if (code == null) return "—";
  if (code === 0) return "Clear";
  if (code <= 2) return "Partly cloudy";
  if (code === 3) return "Overcast";
  if (code >= 45 && code <= 48) return "Fog";
  if (code >= 51 && code <= 67) return "Rain/drizzle";
  if (code >= 71 && code <= 77) return "Snow";
  if (code >= 80 && code <= 82) return "Showers";
  if (code >= 95) return "Storms";
  return "—";
}

function pairKey(p) { return `${p.source}__${p.sink}`; }

// ---------------------------------------------------------------------
// Data provider: one interface, two implementations. The rest of the app
// never knows or cares whether it's reading the embedded demo snapshot or
// a live backend -- this is what lets filters, comparison, and every other
// view work identically in both modes instead of forking the UI in two.
// ---------------------------------------------------------------------

function demoProvider(data) {
  const pairByKey = {};
  data.pairs.forEach((p) => { pairByKey[pairKey(p)] = p; });

  return {
    mode: "demo",
    async getMeta() { return data.meta; },
    async getDashboard() {
      const scores = data.scores.slice(0, 5).map((s) => ({ source: s.source, sink: s.sink, score: s.score, tier: s.tier }));

      const tierDistribution = { High: 0, Medium: 0, Low: 0 };
      data.scores.forEach((s) => { tierDistribution[s.tier] = (tierDistribution[s.tier] || 0) + 1; });

      // Sum every participant's monthly MW across the whole market, then
      // keep only the trailing 12 months -- mirrors the backend's
      // monthly_mw_trend exactly so the Overview chart looks identical
      // whether reading the snapshot or a live server.
      const mwByMonth = {};
      Object.values(data.participant_activity).forEach((activity) => {
        activity.monthly_mw.forEach((row) => {
          mwByMonth[row.auction_month] = (mwByMonth[row.auction_month] || 0) + row.mw;
        });
      });
      const months = Object.keys(mwByMonth).sort();
      const trendMonths = months.slice(-12);
      const monthlyMwTrend = trendMonths.map((m) => ({ auction_month: m, total_mw: Math.round(mwByMonth[m] * 10) / 10 }));

      return {
        data_source: "synthetic_demo",
        latest_auction_month: data.meta.latest_month,
        latest_month_mw_awarded: data.meta.latest_month_mw,
        latest_month_participant_count: data.meta.latest_month_participants,
        active_participant_count: data.meta.participant_count,
        tracked_pair_count: data.meta.pair_count,
        tier_distribution: tierDistribution,
        monthly_mw_trend: monthlyMwTrend,
        top_opportunity_pairs: scores,
        top_participants: data.participants.slice(0, 5),
      };
    },
    async getPairs() {
      return data.pairs.map((p) => ({
        source: p.source, source_name: p.source_name, sink: p.sink, sink_name: p.sink_name,
        average_obligation_price: p.obligation_by_tou.ALL.metrics.average,
        trend_direction: p.obligation_by_tou.ALL.metrics.trend_direction,
      }));
    },
    async getScores() { return data.scores; },
    async getParticipants() { return data.participants; },
    async getPairSeries(source, sink, crrType, tou) {
      const p = pairByKey[`${source}__${sink}`];
      if (!p) throw new Error("Unknown pair");
      const bucket = crrType === "OPTION" ? p.option_by_tou : p.obligation_by_tou;
      const chosen = bucket[tou] || bucket.ALL;
      return { source, sink, series: chosen.series, metrics: chosen.metrics };
    },
    async getPairParticipants(source, sink) {
      const p = pairByKey[`${source}__${sink}`];
      if (!p) throw new Error("Unknown pair");
      return { source, sink, participants: p.participants };
    },
    async getParticipantDetail(name) {
      const activity = data.participant_activity[name];
      const summary = data.participants.find((p) => p.participant === name);
      return {
        participant: name,
        summary,
        pairs: activity ? activity.pairs : [],
        monthly_mw: activity ? activity.monthly_mw : [],
      };
    },
  };
}

function liveProvider(apiBase) {
  const base = apiBase.replace(/\/$/, "");
  async function getJson(path) {
    const res = await fetch(`${base}${path}`);
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail || ""; } catch (e) { /* ignore */ }
      throw new Error(detail || `Request to ${path} failed (HTTP ${res.status})`);
    }
    return res.json();
  }
  return {
    mode: "live",
    async getMeta() { return getJson("/api/meta"); },
    async getDashboard() { return getJson("/api/dashboard"); },
    async getPairs() { return getJson("/api/pairs"); },
    async getScores() { return getJson("/api/opportunity-scores"); },
    async getParticipants() { return getJson("/api/participants"); },
    async getPairSeries(source, sink, crrType, tou) {
      const params = new URLSearchParams({ crr_type: crrType });
      if (tou !== "ALL") params.set("time_of_use", tou);
      return getJson(`/api/pairs/${source}/${sink}/series?${params.toString()}`);
    },
    async getPairParticipants(source, sink) {
      return getJson(`/api/pairs/${source}/${sink}/participants`);
    },
    async getParticipantDetail(name) {
      const body = await getJson(`/api/participants/${encodeURIComponent(name)}`);
      return {
        participant: body.participant,
        summary: body.summary,
        pairs: body.pairs,
        monthly_mw: null, // live API returns recent line items, not a monthly series -- Participants view adapts
        recent_activity: body.recent_activity,
      };
    },
  };
}

function downloadPairCsv(source, sink, obligationSeries, optionSeries) {
  const map = {};
  obligationSeries.forEach((d) => {
    map[d.auction_month] = { month: d.auction_month, obligation: d.avg_clearing_price, option: "" };
  });
  optionSeries.forEach((d) => {
    map[d.auction_month] = { ...(map[d.auction_month] || { month: d.auction_month, obligation: "" }), option: d.avg_clearing_price };
  });
  const rows = Object.values(map).sort((a, b) => a.month.localeCompare(b.month));
  const lines = ["auction_month,obligation_avg_clearing_price,option_avg_clearing_price"];
  rows.forEach((r) => lines.push(`${r.month},${r.obligation},${r.option}`));
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${source}_${sink}_series.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function TrendIcon({ direction, size = 14 }) {
  if (direction === "rising") return <TrendingUp size={size} color="#3DDC97" />;
  if (direction === "falling") return <TrendingDown size={size} color="#E85D5D" />;
  return <Minus size={size} color="#7A8699" />;
}

function TierPill({ tier }) {
  const c = TIER_COLOR[tier] || TIER_COLOR.Low;
  return (
    <span style={{
      color: c.text, background: c.bg, border: `1px solid ${c.border}`,
      fontFamily: FONT_MONO, fontSize: 11, letterSpacing: "0.06em",
      padding: "3px 9px", borderRadius: 4, textTransform: "uppercase", whiteSpace: "nowrap",
    }}>
      {tier}
    </span>
  );
}

function StatCard({ label, value, sub, icon: Icon }) {
  return (
    <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, padding: "16px 18px", flex: "1 1 180px", minWidth: 160 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, color: "#7A8699" }}>
        {Icon ? <Icon size={14} /> : null}
        <span style={{ fontFamily: FONT_MONO, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</span>
      </div>
      <div style={{ fontFamily: FONT_DISPLAY, fontSize: 26, fontWeight: 600, color: "#F4F6F9", lineHeight: 1.1 }}>{value}</div>
      {sub ? <div style={{ marginTop: 6, fontSize: 12, color: "#7A8699" }}>{sub}</div> : null}
    </div>
  );
}

function CorridorBar({ score, onClick }) {
  const c = TIER_COLOR[score.tier] || TIER_COLOR.Low;
  return (
    <div onClick={onClick} style={{
      display: "grid", gridTemplateColumns: "1fr auto 1fr auto 56px", alignItems: "center",
      gap: 10, padding: "10px 14px", borderRadius: 8, background: "#12161F",
      border: "1px solid #232937", cursor: "pointer",
    }}>
      <div style={{ fontFamily: FONT_MONO, fontSize: 12.5, color: "#DCE3ED", textAlign: "right", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {score.source_name}
      </div>
      <ArrowRight size={13} color={c.text} />
      <div style={{ fontFamily: FONT_MONO, fontSize: 12.5, color: "#DCE3ED", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {score.sink_name}
      </div>
      <div style={{ fontFamily: FONT_MONO, fontSize: 12, color: c.text, textAlign: "right" }}>{score.score}</div>
      <TierPill tier={score.tier} />
    </div>
  );
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div style={{ background: "#0D1017", border: "1px solid #2B3242", borderRadius: 6, padding: "8px 11px", fontFamily: FONT_MONO, fontSize: 12, color: "#DCE3ED" }}>
      <div style={{ color: "#7A8699", marginBottom: 4 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.color }}>{p.name}: ${Number(p.value).toFixed(2)}/MWh</div>
      ))}
    </div>
  );
}

function MetricGrid({ metrics }) {
  const items = [
    ["Trailing 12mo Avg", metrics.trailing_12mo_average != null ? `$${metrics.trailing_12mo_average.toFixed(2)}` : "—"],
    ["All-Time Average", metrics.average != null ? `$${metrics.average.toFixed(2)}` : "—"],
    ["Min", metrics.min != null ? `$${metrics.min.toFixed(2)}` : "—"],
    ["Max", metrics.max != null ? `$${metrics.max.toFixed(2)}` : "—"],
    ["Volatility (σ)", metrics.volatility != null ? `$${metrics.volatility.toFixed(2)}` : "—"],
    ["12mo Trend", metrics.recent_vs_prior_year_pct != null ? `${metrics.recent_vs_prior_year_pct > 0 ? "+" : ""}${metrics.recent_vs_prior_year_pct}%` : "n/a"],
    ["Months negative", metrics.pct_months_negative != null ? `${metrics.pct_months_negative}%` : "—"],
    ["Months tracked", metrics.n_months],
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
      {items.map(([label, value], i) => (
        <div key={label} style={{
          background: i === 0 ? "#12201A" : "#0D1017", border: `1px solid ${i === 0 ? "#245240" : "#232937"}`,
          borderRadius: 8, padding: "10px 12px",
        }}>
          <div style={{ fontFamily: FONT_MONO, fontSize: 10.5, color: i === 0 ? "#3DDC97" : "#7A8699", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
          <div style={{ fontFamily: FONT_DISPLAY, fontSize: 17, color: "#F4F6F9", marginTop: 3 }}>{value}</div>
        </div>
      ))}
    </div>
  );
}

function FactorBar({ label, factor }) {
  const pct = Math.round(factor.score);
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", marginBottom: 4 }}>
        <span style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>{label} · {Math.round(factor.weight * 100)}% weight</span>
        <span>{pct}/100</span>
      </div>
      <div style={{ height: 6, background: "#0D1017", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: "linear-gradient(90deg, #2E7CE0, #3DDC97)" }} />
      </div>
    </div>
  );
}

function SeasonalityStrip({ series }) {
  // Groups a monthly "YYYY-MM" series by calendar month and averages,
  // giving a 12-cell strip so a trader can see which months this path
  // actually congests in, independent of which years happened to be sampled.
  const byMonth = useMemo(() => {
    const buckets = Array.from({ length: 12 }, () => []);
    series.forEach((d) => {
      const monthIdx = parseInt(d.auction_month.slice(5, 7), 10) - 1;
      if (monthIdx >= 0 && monthIdx < 12) buckets[monthIdx].push(d.avg_clearing_price);
    });
    return buckets.map((vals) => (vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null));
  }, [series]);

  const valid = byMonth.filter((v) => v != null);
  if (!valid.length) return null;
  const max = Math.max(...valid.map(Math.abs));
  const labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  return (
    <div>
      <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
        Seasonality (avg Obligation value by calendar month, all years)
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 4 }}>
        {byMonth.map((v, i) => {
          const intensity = v == null || max === 0 ? 0 : Math.min(1, Math.abs(v) / max);
          const positive = v != null && v >= 0;
          const bg = v == null
            ? "#12161F"
            : positive
              ? `rgba(61,220,151,${0.12 + intensity * 0.7})`
              : `rgba(232,93,93,${0.12 + intensity * 0.7})`;
          return (
            <div key={labels[i]} style={{
              background: bg, border: "1px solid #232937", borderRadius: 6,
              padding: "8px 4px", textAlign: "center",
            }} title={v != null ? `${labels[i]}: $${v.toFixed(2)}/MWh` : `${labels[i]}: no data`}>
              <div style={{ fontFamily: FONT_MONO, fontSize: 9.5, color: "#9AA5B4" }}>{labels[i]}</div>
              <div style={{ fontFamily: FONT_MONO, fontSize: 10.5, color: "#F4F6F9", marginTop: 2 }}>
                {v != null ? `$${v.toFixed(1)}` : "—"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Nav({ tab, setTab }) {
  const tabs = [
    ["overview", "Overview", Gauge],
    ["explorer", "Source / Sink Explorer", GitBranch],
    ["participants", "Participants", Users],
    ["signals", "Opportunity Signals", Zap],
  ];
  return (
    <div style={{ display: "flex", gap: 4, marginBottom: 22, borderBottom: "1px solid #232937" }}>
      {tabs.map(([key, label, Icon]) => {
        const active = tab === key;
        return (
          <button key={key} onClick={() => setTab(key)} style={{
            display: "flex", alignItems: "center", gap: 7, background: "transparent", border: "none", cursor: "pointer",
            color: active ? "#F4F6F9" : "#7A8699", fontFamily: FONT_DISPLAY, fontSize: 13.5, fontWeight: active ? 600 : 500,
            padding: "10px 14px", borderBottom: active ? "2px solid #3DDC97" : "2px solid transparent", marginBottom: -1,
          }}>
            <Icon size={14} /> {label}
          </button>
        );
      })}
    </div>
  );
}

function ConnectionBar({ mode, apiBase, status, onConnect, onDisconnect }) {
  const [draft, setDraft] = useState(apiBase || "http://localhost:8000");
  const live = mode === "live";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10, background: "#12161F", border: "1px solid #232937",
      borderRadius: 8, padding: "8px 12px", marginBottom: 16, flexWrap: "wrap",
    }}>
      {live ? <Wifi size={14} color="#3DDC97" /> : <WifiOff size={14} color="#7A8699" />}
      <span style={{ fontFamily: FONT_MONO, fontSize: 11.5, color: live ? "#3DDC97" : "#9AA5B4" }}>
        {live ? `Connected — live backend at ${apiBase}` : "Demo dataset (not connected to a backend)"}
      </span>
      <div style={{ flex: 1 }} />
      {!live && (
        <>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="http://localhost:8000"
            style={{
              background: "#0D1017", border: "1px solid #232937", borderRadius: 6, padding: "5px 9px",
              color: "#DCE3ED", fontFamily: FONT_MONO, fontSize: 11.5, width: 220,
            }}
          />
          <button onClick={() => onConnect(draft)} disabled={status === "connecting"} style={{
            background: "#1B2230", border: "1px solid #2E7CE0", borderRadius: 6, padding: "5px 12px",
            color: "#DCE3ED", fontFamily: FONT_DISPLAY, fontSize: 11.5, cursor: "pointer",
          }}>
            {status === "connecting" ? "Connecting…" : "Connect"}
          </button>
        </>
      )}
      {live && (
        <button onClick={onDisconnect} style={{
          background: "transparent", border: "1px solid #232937", borderRadius: 6, padding: "5px 12px",
          color: "#9AA5B4", fontFamily: FONT_DISPLAY, fontSize: 11.5, cursor: "pointer",
        }}>
          Disconnect
        </button>
      )}
      {status === "error" && (
        <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#E85D5D" }}>Couldn't reach that backend.</span>
      )}
    </div>
  );
}

function DataSourceBanner({ meta, mode }) {
  if (mode === "live") return null;
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6, fontSize: 12, color: "#9AA5B4",
      background: "#171B24", border: "1px solid #2B3242", borderRadius: 8, padding: "10px 13px", marginBottom: 20,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Info size={13} color="#E8B339" />
        <span>
          Showing the <strong style={{ color: "#E8B339" }}>synthetic demo dataset</strong> — realistic ERCOT
          hub/load-zone names and seasonality, {meta.first_month} – {meta.latest_month},{" "}
          {meta.record_count.toLocaleString()} auction records. Connect to a running backend above (or run this
          file as a standalone app) for real or live data — see README.
        </span>
      </div>
    </div>
  );
}

function WeatherPanel() {
  // Genuinely live: fetches real current conditions from Open-Meteo
  // directly in the browser on every load -- no API key, CORS-open
  // (Access-Control-Allow-Origin: *), so unlike the ERCOT integration this
  // has a real chance of working from inside a sandboxed preview as well
  // as a normally-deployed app. Fails open with a clear message rather
  // than a blank panel if the fetch is blocked or unreachable.
  const [state, setState] = useState({ status: "loading", data: null });

  useEffect(() => {
    let live = true;
    const lats = WEATHER_REGIONS.map((r) => r.lat).join(",");
    const lons = WEATHER_REGIONS.map((r) => r.lon).join(",");
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${lats}&longitude=${lons}` +
      `&current=temperature_2m,wind_speed_10m,cloud_cover,weather_code` +
      `&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FChicago`;

    fetch(url)
      .then((res) => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
      .then((json) => {
        if (!live) return;
        // Open-Meteo returns a single object for one location, or an array
        // for multiple -- normalize to an array either way.
        const rows = Array.isArray(json) ? json : [json];
        setState({ status: "ok", data: rows });
      })
      .catch(() => { if (live) setState({ status: "error", data: null }); });

    return () => { live = false; };
  }, []);

  return (
    <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, padding: "14px 16px", marginBottom: 22 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <CloudSun size={14} color="#7A8699" />
        <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Live Grid-Region Weather — Open-Meteo
        </span>
        {state.status === "ok" && <span style={{ fontFamily: FONT_MONO, fontSize: 9.5, color: "#3DDC97", marginLeft: "auto" }}>● LIVE</span>}
      </div>

      {state.status === "loading" && (
        <div style={{ fontFamily: FONT_MONO, fontSize: 11.5, color: "#7A8699" }}>Fetching current conditions…</div>
      )}

      {state.status === "error" && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: FONT_MONO, fontSize: 11.5, color: "#E8B339" }}>
          <AlertTriangle size={13} />
          Couldn't reach Open-Meteo from this environment right now. This is a real live external
          fetch (no fallback data is shown) — it works when this app runs as a normal deployed page.
        </div>
      )}

      {state.status === "ok" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 10 }}>
            {WEATHER_REGIONS.map((region, i) => {
              const c = state.data[i] && state.data[i].current;
              return (
                <div key={region.key} style={{ background: "#0D1017", border: "1px solid #232937", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontFamily: FONT_DISPLAY, fontSize: 12, color: "#DCE3ED", marginBottom: 2 }}>{region.label}</div>
                  <div style={{ fontFamily: FONT_MONO, fontSize: 10, color: "#7A8699", marginBottom: 8 }}>{region.relates}</div>
                  {c ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: FONT_MONO, fontSize: 13, color: "#F4F6F9" }}>
                        <Thermometer size={12} color="#E8B339" /> {Math.round(c.temperature_2m)}°F
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: FONT_MONO, fontSize: 13, color: "#F4F6F9" }}>
                        <Wind size={12} color="#2E7CE0" /> {Math.round(c.wind_speed_10m)} mph
                      </div>
                      <div style={{ fontFamily: FONT_MONO, fontSize: 10.5, color: "#7A8699" }}>
                        {weatherCodeLabel(c.weather_code)} · {Math.round(c.cloud_cover)}% cloud
                      </div>
                    </div>
                  ) : (
                    <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#7A8699" }}>No data</div>
                  )}
                </div>
              );
            })}
          </div>
          <div style={{ fontFamily: FONT_DISPLAY, fontSize: 11, color: "#7A8699", fontStyle: "italic" }}>
            Context, not a forecast of CRR value: high West/Panhandle wind raises renewable output on
            paths like PERMIAN_SOLAR_RN → HB_WEST and HB_WEST → HB_HOUSTON, which historically
            correlates with elevated congestion on those export corridors; high Houston/DFW
            temperature raises the AC load those corridors are trying to reach.
          </div>
        </>
      )}
    </div>
  );
}


function TierDistributionBar({ distribution }) {
  const total = Object.values(distribution).reduce((a, b) => a + b, 0) || 1;
  const order = [["High", "#3DDC97"], ["Medium", "#E8B339"], ["Low", "#7A8699"]];
  return (
    <div>
      <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", marginBottom: 8 }}>
        {order.map(([tier, color]) => (
          <div key={tier} style={{ width: `${(100 * distribution[tier]) / total}%`, background: color }} />
        ))}
      </div>
      <div style={{ display: "flex", gap: 14 }}>
        {order.map(([tier, color]) => (
          <div key={tier} style={{ display: "flex", alignItems: "center", gap: 5, fontFamily: FONT_MONO, fontSize: 11 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: color, display: "inline-block" }} />
            <span style={{ color: "#9AA5B4" }}>{tier}</span>
            <span style={{ color: "#F4F6F9" }}>{distribution[tier]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MonthlyTrendChart({ trend }) {
  return (
    <ResponsiveContainer width="100%" height={110}>
      <BarChart data={trend} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
        <XAxis dataKey="auction_month" tick={{ fontFamily: FONT_MONO, fontSize: 9, fill: "#7A8699" }} tickFormatter={(m) => m.slice(2)} interval={1} />
        <YAxis hide />
        <Tooltip contentStyle={{ background: "#0D1017", border: "1px solid #2B3242", fontFamily: FONT_MONO, fontSize: 11 }}
          formatter={(v) => [`${v.toLocaleString()} MW`, "Total awarded"]} />
        <Bar dataKey="total_mw" fill="#2E7CE0" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function Overview({ provider, meta, goToPair, mode }) {
  const [dash, setDash] = useState(null);
  useEffect(() => { let live = true; provider.getDashboard().then((d) => { if (live) setDash(d); }); return () => { live = false; }; }, [provider]);
  if (!dash) return <div style={{ color: "#7A8699", fontFamily: FONT_MONO, fontSize: 12 }}>Loading…</div>;

  return (
    <div>
      <DataSourceBanner meta={meta} mode={mode} />
      {dash.data_source_warning && (
        <div style={{
          display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12, color: "#E8B339",
          background: "#221D0F", border: "1px solid #3A3013", borderRadius: 8, padding: "10px 13px", marginBottom: 20,
        }}>
          <AlertTriangle size={14} style={{ marginTop: 1, flexShrink: 0 }} />
          <span>
            <strong>Data source degraded:</strong> {dash.data_source_warning} Currently serving
            from <code style={{ fontFamily: FONT_MONO }}>{dash.data_source}</code>.
          </span>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 22 }}>
        <StatCard label="Latest Auction Month" value={dash.latest_auction_month} icon={Activity}
          sub={`${dash.latest_month_mw_awarded.toLocaleString()} MW awarded`} />
        <StatCard label="Active Participants" value={dash.active_participant_count} icon={Users}
          sub={`${dash.latest_month_participant_count} active last auction`} />
        <StatCard label="Tracked Source/Sink Pairs" value={dash.tracked_pair_count} icon={GitBranch} />
        <StatCard label="Data Source" value={mode === "live" ? "Live" : "Demo"} icon={mode === "live" ? Wifi : WifiOff} />
      </div>

      <WeatherPanel />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginBottom: 22 }}>
        <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, padding: "14px 16px" }}>
          <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
            Opportunity Tier Distribution — All {dash.tracked_pair_count} Pairs
          </div>
          <TierDistributionBar distribution={dash.tier_distribution} />
        </div>
        <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, padding: "14px 16px" }}>
          <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
            Trailing 12-Month Market MW Awarded
          </div>
          <MonthlyTrendChart trend={dash.monthly_mw_trend} />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 18 }}>
        <div>
          <div style={{ fontFamily: FONT_DISPLAY, fontSize: 13, color: "#9AA5B4", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Top Opportunity Corridors
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {dash.top_opportunity_pairs.map((s) => (
              <CorridorBar key={pairKey(s)} score={s} onClick={() => goToPair(s)} />
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontFamily: FONT_DISPLAY, fontSize: 13, color: "#9AA5B4", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Top Participants by Notional
          </div>
          <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, overflow: "hidden" }}>
            {dash.top_participants.map((p, i) => (
              <div key={p.participant} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderBottom: i < dash.top_participants.length - 1 ? "1px solid #1C212C" : "none" }}>
                <div style={{ fontFamily: FONT_DISPLAY, fontSize: 12.5, color: "#DCE3ED" }}>{p.participant}</div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 12, color: "#3DDC97" }}>${Math.round(p.total_notional).toLocaleString()}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Explorer({ provider, selected, setSelected }) {
  const [pairsList, setPairsList] = useState([]);
  const [tou, setTou] = useState("ALL");
  const [obligation, setObligation] = useState(null);
  const [option, setOption] = useState(null);
  const [seasonalitySeries, setSeasonalitySeries] = useState([]);
  const [pairParticipants, setPairParticipants] = useState([]);
  const [compareMode, setCompareMode] = useState(false);
  const [comparePairs, setComparePairs] = useState([]); // pairKeys, excluding `selected`
  const [compareData, setCompareData] = useState({}); // pairKey -> series

  useEffect(() => { provider.getPairs().then(setPairsList); }, [provider]);

  const pair = pairsList.find((p) => pairKey(p) === selected);

  useEffect(() => {
    if (!pair) return;
    let live = true;
    Promise.all([
      provider.getPairSeries(pair.source, pair.sink, "OBLIGATION", tou),
      provider.getPairSeries(pair.source, pair.sink, "OPTION", tou),
    ]).then(([ob, op]) => { if (live) { setObligation(ob); setOption(op); } });
    provider.getPairParticipants(pair.source, pair.sink).then((r) => { if (live) setPairParticipants(r.participants); }).catch(() => setPairParticipants([]));
    return () => { live = false; };
  }, [provider, pair && pair.source, pair && pair.sink, tou]);

  // Seasonality always reflects the full ALL-hours Obligation series,
  // independent of the TOU filter above, so switching TOU doesn't make the
  // seasonal shape flicker for a filter that's about hour-of-day, not month.
  useEffect(() => {
    if (!pair) return;
    let live = true;
    provider.getPairSeries(pair.source, pair.sink, "OBLIGATION", "ALL").then((r) => { if (live) setSeasonalitySeries(r.series); });
    return () => { live = false; };
  }, [provider, pair && pair.source, pair && pair.sink]);

  useEffect(() => {
    if (!compareMode || comparePairs.length === 0) { setCompareData({}); return; }
    let live = true;
    Promise.all(comparePairs.map((key) => {
      const [source, sink] = key.split("__");
      return provider.getPairSeries(source, sink, "OBLIGATION", tou).then((r) => [key, r.series]);
    })).then((entries) => { if (live) setCompareData(Object.fromEntries(entries)); });
    return () => { live = false; };
  }, [provider, compareMode, comparePairs, tou]);

  const chartData = useMemo(() => {
    if (!obligation || !option) return [];
    const map = {};
    obligation.series.forEach((d) => { map[d.auction_month] = { month: d.auction_month, Obligation: d.avg_clearing_price }; });
    option.series.forEach((d) => {
      map[d.auction_month] = { ...(map[d.auction_month] || { month: d.auction_month }), Option: d.avg_clearing_price };
    });
    if (compareMode) {
      Object.entries(compareData).forEach(([key, series]) => {
        const label = key.replace("__", " → ");
        series.forEach((d) => {
          map[d.auction_month] = { ...(map[d.auction_month] || { month: d.auction_month }), [label]: d.avg_clearing_price };
        });
      });
    }
    return Object.values(map).sort((a, b) => a.month.localeCompare(b.month));
  }, [obligation, option, compareMode, compareData]);

  if (!pair) return <div style={{ color: "#7A8699", fontFamily: FONT_MONO, fontSize: 12 }}>Loading…</div>;

  const toggleCompare = (key) => {
    setComparePairs((prev) => {
      if (prev.includes(key)) return prev.filter((k) => k !== key);
      if (prev.length >= 2) return prev; // main pair + 2 more = 3 lines max
      return [...prev, key];
    });
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 18 }}>
      <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, maxHeight: 640, overflowY: "auto" }}>
        <div style={{ padding: "10px 13px", borderBottom: "1px solid #1C212C", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontFamily: FONT_MONO, fontSize: 10.5, color: "#7A8699", textTransform: "uppercase" }}>Pairs</span>
          <button onClick={() => { setCompareMode((v) => !v); setComparePairs([]); }} style={{
            background: compareMode ? "#1B2230" : "transparent", border: "1px solid #232937", borderRadius: 5,
            padding: "3px 8px", color: compareMode ? "#3DDC97" : "#7A8699", fontFamily: FONT_MONO, fontSize: 10, cursor: "pointer",
          }}>
            Compare {compareMode ? `(${comparePairs.length + 1}/3)` : ""}
          </button>
        </div>
        {pairsList.map((p) => {
          const key = pairKey(p);
          const active = key === selected;
          const checked = comparePairs.includes(key);
          return (
            <div key={key} style={{
              display: "flex", alignItems: "center", gap: 8, width: "100%",
              background: active ? "#1B2230" : "transparent", borderLeft: active ? "3px solid #3DDC97" : "3px solid transparent",
              padding: "10px 13px",
            }}>
              {compareMode && !active && (
                <input type="checkbox" checked={checked} onChange={() => toggleCompare(key)} style={{ cursor: "pointer" }} />
              )}
              <button onClick={() => setSelected(key)} style={{
                display: "flex", flexDirection: "column", gap: 2, flex: 1, textAlign: "left",
                background: "transparent", border: "none", cursor: "pointer", color: "#DCE3ED", padding: 0,
              }}>
                <span style={{ fontFamily: FONT_MONO, fontSize: 12 }}>{p.source} → {p.sink}</span>
                <span style={{ fontFamily: FONT_DISPLAY, fontSize: 11, color: "#7A8699" }}>{p.source_name} → {p.sink_name}</span>
              </button>
            </div>
          );
        })}
      </div>

      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontFamily: FONT_DISPLAY, fontSize: 18, fontWeight: 600, color: "#F4F6F9" }}>
              {pair.source_name} <ArrowRight size={15} style={{ display: "inline", verticalAlign: "-2px", margin: "0 4px" }} /> {pair.sink_name}
            </div>
            <div style={{ fontFamily: FONT_MONO, fontSize: 12, color: "#7A8699" }}>{pair.source} → {pair.sink}</div>
          </div>
          {obligation && option && (
            <button onClick={() => downloadPairCsv(pair.source, pair.sink, obligation.series, option.series)} style={{
              display: "flex", alignItems: "center", gap: 6, background: "#12161F", border: "1px solid #232937",
              borderRadius: 7, padding: "7px 12px", color: "#9AA5B4", fontFamily: FONT_DISPLAY, fontSize: 12, cursor: "pointer",
            }}>
              <Download size={13} /> Download CSV
            </button>
          )}
        </div>

        <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
          {TOU_OPTIONS.map(([key, label]) => (
            <button key={key} onClick={() => setTou(key)} style={{
              background: tou === key ? "#1B2230" : "#12161F", border: `1px solid ${tou === key ? "#3DDC97" : "#232937"}`,
              borderRadius: 6, padding: "5px 11px", color: tou === key ? "#3DDC97" : "#9AA5B4",
              fontFamily: FONT_MONO, fontSize: 11, cursor: "pointer",
            }}>
              {label}
            </button>
          ))}
        </div>

        <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, padding: "16px 8px 8px 0", marginBottom: 18 }}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData} margin={{ top: 4, right: 20, left: 8, bottom: 4 }}>
              <CartesianGrid stroke="#1C212C" vertical={false} />
              <XAxis dataKey="month" tick={{ fontFamily: FONT_MONO, fontSize: 10, fill: "#7A8699" }}
                tickFormatter={(m) => m.slice(2)} interval={Math.max(0, Math.floor(chartData.length / 8))} />
              <YAxis tick={{ fontFamily: FONT_MONO, fontSize: 10, fill: "#7A8699" }} width={44} />
              <Tooltip content={<ChartTooltip />} />
              <Legend wrapperStyle={{ fontFamily: FONT_DISPLAY, fontSize: 12, color: "#9AA5B4" }} />
              <ReferenceLine y={0} stroke="#2B3242" />
              <Line type="monotone" dataKey="Obligation" stroke="#3DDC97" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="Option" stroke="#2E7CE0" dot={false} strokeWidth={2} strokeDasharray="4 3" />
              {compareMode && comparePairs.map((key, i) => (
                <Line key={key} type="monotone" dataKey={key.replace("__", " → ")} stroke={COMPARE_COLORS[(i + 1) % COMPARE_COLORS.length]} dot={false} strokeWidth={1.5} strokeDasharray="2 2" />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {obligation && option && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 18 }}>
              <div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                  Obligation CRR Metrics — {TOU_OPTIONS.find(([k]) => k === tou)[1]}
                </div>
                <MetricGrid metrics={obligation.metrics} />
              </div>
              <div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                  Option CRR Metrics — {TOU_OPTIONS.find(([k]) => k === tou)[1]}
                </div>
                <MetricGrid metrics={option.metrics} />
              </div>
            </div>

            <div style={{ marginBottom: 18 }}>
              <SeasonalityStrip series={seasonalitySeries} />
            </div>

            <div>
              <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                Active Participants on This Pair
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {pairParticipants.slice(0, 10).map((p) => (
                  <span key={p.participant} style={{
                    fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", background: "#171B24",
                    border: "1px solid #232937", borderRadius: 5, padding: "3px 8px",
                  }}>
                    {p.participant} · ${Math.round(p.total_notional).toLocaleString()}
                  </span>
                ))}
                {pairParticipants.length === 0 && (
                  <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#7A8699" }}>No participant data for this source.</span>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Participants({ provider }) {
  const [list, setList] = useState([]);
  const [sortKey, setSortKey] = useState("total_notional");
  const [selectedName, setSelectedName] = useState(null);
  const [detail, setDetail] = useState(null);

  useEffect(() => { provider.getParticipants().then((l) => { setList(l); if (l.length) setSelectedName(l[0].participant); }); }, [provider]);
  useEffect(() => { if (selectedName) provider.getParticipantDetail(selectedName).then(setDetail); }, [provider, selectedName]);

  const sorted = useMemo(() => [...list].sort((a, b) => b[sortKey] - a[sortKey]), [list, sortKey]);

  const cols = [
    ["participant", "Participant", null],
    ["total_awarded_mw", "MW Awarded", (v) => Math.round(v).toLocaleString()],
    ["total_notional", "Notional ($)", (v) => `$${Math.round(v).toLocaleString()}`],
    ["distinct_pairs", "Pairs Traded", null],
    ["auction_count", "Auction Line Items", null],
  ];

  const chartData = detail && detail.monthly_mw ? detail.monthly_mw.slice(-36) : [];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 18 }}>
      <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {cols.map(([key, label]) => (
                <th key={key} onClick={() => key !== "participant" && setSortKey(key)} style={{
                  textAlign: key === "participant" ? "left" : "right", padding: "10px 12px",
                  fontFamily: FONT_MONO, fontSize: 10.5, color: "#7A8699", textTransform: "uppercase",
                  letterSpacing: "0.05em", cursor: key !== "participant" ? "pointer" : "default", borderBottom: "1px solid #232937",
                }}>
                  {label}{sortKey === key ? " ▾" : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <tr key={p.participant} onClick={() => setSelectedName(p.participant)} style={{ cursor: "pointer", background: p.participant === selectedName ? "#1B2230" : "transparent" }}>
                {cols.map(([key, _, fmt]) => (
                  <td key={key} style={{
                    padding: "9px 12px", fontFamily: key === "participant" ? FONT_DISPLAY : FONT_MONO,
                    fontSize: 12.5, color: "#DCE3ED", textAlign: key === "participant" ? "left" : "right", borderBottom: "1px solid #1C212C",
                  }}>
                    {fmt ? fmt(p[key]) : p[key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        {detail && (
          <>
            <div style={{ fontFamily: FONT_DISPLAY, fontSize: 15, fontWeight: 600, color: "#F4F6F9", marginBottom: 4 }}>{detail.participant}</div>
            <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#7A8699", marginBottom: 12 }}>
              {detail.pairs.length} distinct Source/Sink pairs
            </div>
            {chartData.length > 0 ? (
              <div style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, padding: "14px 8px 6px 0" }}>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={chartData} margin={{ top: 4, right: 16, left: 4, bottom: 4 }}>
                    <CartesianGrid stroke="#1C212C" vertical={false} />
                    <XAxis dataKey="auction_month" tick={{ fontFamily: FONT_MONO, fontSize: 9.5, fill: "#7A8699" }} tickFormatter={(m) => m.slice(2)} interval={5} />
                    <YAxis tick={{ fontFamily: FONT_MONO, fontSize: 10, fill: "#7A8699" }} width={38} />
                    <Tooltip contentStyle={{ background: "#0D1017", border: "1px solid #2B3242", fontFamily: FONT_MONO, fontSize: 12 }} />
                    <Bar dataKey="mw" name="MW awarded" fill="#2E7CE0" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#7A8699" }}>
                No monthly activity series available from this data source for this participant.
              </div>
            )}
            <div style={{ marginTop: 14 }}>
              <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#7A8699", textTransform: "uppercase", marginBottom: 8 }}>Pairs This Participant Has Traded</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {detail.pairs.map((pr) => (
                  <span key={`${pr.source}-${pr.sink}`} style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#9AA5B4", background: "#171B24", border: "1px solid #232937", borderRadius: 5, padding: "3px 8px" }}>
                    {pr.source} → {pr.sink}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Signals({ provider, goToPair }) {
  const [scores, setScores] = useState([]);
  const [tierFilter, setTierFilter] = useState("All");
  const [search, setSearch] = useState("");

  useEffect(() => { provider.getScores().then(setScores); }, [provider]);

  const filtered = useMemo(() => {
    return scores.filter((s) => {
      if (tierFilter !== "All" && s.tier !== tierFilter) return false;
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        const hay = `${s.source} ${s.sink} ${s.source_name} ${s.sink_name}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [scores, tierFilter, search]);

  return (
    <div>
      <div style={{ fontSize: 12.5, color: "#9AA5B4", marginBottom: 12, maxWidth: 720 }}>
        Every score is a transparent, rule-based composite of four historical descriptive factors
        (value level, 12-month trend, directional consistency, and market liquidity) — never a
        prediction of future prices or a trading recommendation. Click a corridor to open it in the explorer.
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
        {["All", "High", "Medium", "Low"].map((t) => (
          <button key={t} onClick={() => setTierFilter(t)} style={{
            background: tierFilter === t ? "#1B2230" : "#12161F",
            border: `1px solid ${tierFilter === t ? "#3DDC97" : "#232937"}`,
            borderRadius: 6, padding: "5px 12px", color: tierFilter === t ? "#3DDC97" : "#9AA5B4",
            fontFamily: FONT_MONO, fontSize: 11.5, cursor: "pointer",
          }}>
            {t}
          </button>
        ))}
        <div style={{ position: "relative", flex: "0 0 220px", marginLeft: "auto" }}>
          <Search size={13} color="#7A8699" style={{ position: "absolute", left: 9, top: 8 }} />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search hub/zone…" style={{
            width: "100%", background: "#0D1017", border: "1px solid #232937", borderRadius: 6,
            padding: "6px 9px 6px 28px", color: "#DCE3ED", fontFamily: FONT_MONO, fontSize: 11.5,
          }} />
          {search && (
            <X size={13} color="#7A8699" style={{ position: "absolute", right: 9, top: 8, cursor: "pointer" }} onClick={() => setSearch("")} />
          )}
        </div>
      </div>

      <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#7A8699", marginBottom: 10 }}>
        {filtered.length} of {scores.length} pairs
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {filtered.map((s) => (
          <div key={pairKey(s)} onClick={() => goToPair(s)} style={{ background: "#12161F", border: "1px solid #232937", borderRadius: 10, padding: 16, cursor: "pointer" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div>
                <div style={{ fontFamily: FONT_DISPLAY, fontSize: 14.5, fontWeight: 600, color: "#F4F6F9" }}>
                  {s.source_name} <ArrowRight size={13} style={{ display: "inline", verticalAlign: "-1px", margin: "0 3px" }} /> {s.sink_name}
                </div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: "#7A8699" }}>{s.source} → {s.sink}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <TrendIcon direction={s.metrics.trend_direction} />
                <span style={{ fontFamily: FONT_MONO, fontSize: 20, color: "#F4F6F9" }}>{s.score}</span>
                <TierPill tier={s.tier} />
                <ChevronRight size={16} color="#4A5468" />
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              <div><FactorBar label="Value" factor={s.factors.value} /><FactorBar label="Trend" factor={s.factors.trend} /></div>
              <div><FactorBar label="Consistency" factor={s.factors.consistency} /><FactorBar label="Liquidity" factor={s.factors.liquidity} /></div>
            </div>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, color: "#9AA5B4", fontSize: 12, lineHeight: 1.6 }}>
              {s.explanation.map((line, i) => <li key={i}>{line}</li>)}
            </ul>
          </div>
        ))}
        {filtered.length === 0 && (
          <div style={{ fontFamily: FONT_MONO, fontSize: 12, color: "#7A8699", padding: "20px 0" }}>No pairs match that filter.</div>
        )}
      </div>
    </div>
  );
}

export default function ErcotCrrDashboard() {
  const [mode, setMode] = useState("demo");
  const [apiBase, setApiBase] = useState("");
  const [connectStatus, setConnectStatus] = useState("idle");
  const [provider, setProvider] = useState(() => demoProvider(DATA));
  const [tab, setTab] = useState("overview");
  const [selectedPair, setSelectedPair] = useState(pairKey(DATA.pairs[0]));

  const goToPair = (p) => { setSelectedPair(pairKey(p)); setTab("explorer"); };

  const handleConnect = async (url) => {
    setConnectStatus("connecting");
    try {
      const lp = liveProvider(url);
      await lp.getMeta(); // cheap reachability check
      setProvider(lp);
      setApiBase(url.replace(/\/$/, ""));
      setMode("live");
      setConnectStatus("connected");
    } catch (e) {
      setConnectStatus("error");
    }
  };

  const handleDisconnect = () => {
    setProvider(demoProvider(DATA));
    setMode("demo");
    setApiBase("");
    setConnectStatus("idle");
  };

  return (
    <div style={{ background: "#0A0D13", minHeight: "100%", padding: "22px 26px 40px", fontFamily: FONT_DISPLAY, color: "#DCE3ED" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <Zap size={20} color="#3DDC97" />
        <div style={{ fontFamily: FONT_DISPLAY, fontSize: 20, fontWeight: 700, color: "#F4F6F9", letterSpacing: "-0.01em" }}>
          ERCOT CRR Market Analytics
        </div>
      </div>
      <div style={{ fontSize: 12.5, color: "#7A8699", marginBottom: 14 }}>
        Congestion Revenue Rights · Source/Sink pricing intelligence · explainable opportunity signals
      </div>

      <ConnectionBar mode={mode} apiBase={apiBase} status={connectStatus} onConnect={handleConnect} onDisconnect={handleDisconnect} />

      <Nav tab={tab} setTab={setTab} />

      {tab === "overview" && <Overview provider={provider} meta={DATA.meta} goToPair={goToPair} mode={mode} />}
      {tab === "explorer" && <Explorer provider={provider} selected={selectedPair} setSelected={setSelectedPair} />}
      {tab === "participants" && <Participants provider={provider} />}
      {tab === "signals" && <Signals provider={provider} goToPair={goToPair} />}
    </div>
  );
}
