import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function summarize(constraints) {
  const byName = new Map();
  constraints.forEach((c) => {
    const key = c.constraint_name || "—";
    const entry = byName.get(key) || { name: key, count: 0, maxShadow: 0, sumShadow: 0 };
    entry.count += 1;
    entry.sumShadow += Math.abs(c.shadow_price || 0);
    entry.maxShadow = Math.max(entry.maxShadow, Math.abs(c.shadow_price || 0));
    byName.set(key, entry);
  });
  return Array.from(byName.values()).sort((a, b) => b.count - a.count);
}

// Severity is relative to the current window's own distribution (an even
// tertile split by |shadow price|), not a fixed ERCOT price-cap threshold
// -- there's no single dollar figure that means "severe" across every
// window size, so this ranks what's actually in front of the trader right
// now, the same way the opportunity-score tiers rank pairs against each
// other rather than against a hardcoded number.
function tierThresholds(constraints) {
  const mags = constraints.map((c) => Math.abs(c.shadow_price || 0)).sort((a, b) => a - b);
  if (mags.length === 0) return { low: 0, high: Infinity };
  return {
    low: mags[Math.floor(mags.length / 3)],
    high: mags[Math.floor((mags.length * 2) / 3)],
  };
}

function tierFor(shadowPrice, thresholds) {
  const mag = Math.abs(shadowPrice || 0);
  if (mag >= thresholds.high) return "High";
  if (mag >= thresholds.low) return "Medium";
  return "Low";
}

const TIER_FILTERS = ["All", "High", "Medium", "Low"];

const COLUMNS = [
  { key: "delivery_date", label: "Date" },
  { key: "hour_ending", label: "Hour", num: true },
  { key: "constraint_name", label: "Constraint" },
  { key: "contingency_name", label: "Contingency" },
  { key: "from_station", label: "From → to" },
  { key: "shadow_price", label: "Shadow price", num: true },
];

export default function BindingConstraints() {
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [liveError, setLiveError] = useState(null);
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState("All");
  const [sort, setSort] = useState({ key: "delivery_date", dir: "desc" });
  const [focusConstraint, setFocusConstraint] = useState(null);

  useEffect(() => {
    api.liveStatus().then(setStatus).catch((e) => setStatusError(e.message));
  }, []);

  const fetchConstraints = useCallback(() => {
    if (!status || !status.configured) return;
    setLoading(true);
    setData(null);
    setLiveError(null);
    setFocusConstraint(null);
    api
      .bindingConstraints(isoDaysAgo(days), isoDaysAgo(0))
      .then(setData)
      .catch((e) => setLiveError(e.message))
      .finally(() => setLoading(false));
  }, [status, days]);

  useEffect(fetchConstraints, [fetchConstraints]);

  const summary = useMemo(() => (data ? summarize(data.constraints).slice(0, 5) : []), [data]);
  const thresholds = useMemo(() => (data ? tierThresholds(data.constraints) : { low: 0, high: Infinity }), [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    let rows = data.constraints;
    if (focusConstraint) rows = rows.filter((c) => c.constraint_name === focusConstraint);
    if (tier !== "All") rows = rows.filter((c) => tierFor(c.shadow_price, thresholds) === tier);
    if (q) {
      rows = rows.filter(
        (c) =>
          (c.constraint_name || "").toLowerCase().includes(q) ||
          (c.from_station || "").toLowerCase().includes(q) ||
          (c.to_station || "").toLowerCase().includes(q)
      );
    }
    const { key, dir } = sort;
    const sorted = [...rows].sort((a, b) => {
      let va = a[key], vb = b[key];
      if (key === "from_station") { va = `${a.from_station}${a.to_station}`; vb = `${b.from_station}${b.to_station}`; }
      if (typeof va === "string") va = va || "";
      if (typeof vb === "string") vb = vb || "";
      if (va < vb) return dir === "asc" ? -1 : 1;
      if (va > vb) return dir === "asc" ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [data, query, sort, focusConstraint, tier, thresholds]);

  const toggleSort = (key) => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  };

  if (statusError) {
    return <div className="state-msg error">Couldn't reach the backend — {statusError}</div>;
  }
  if (!status) return <div className="state-msg">Checking live ERCOT API status…</div>;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Binding constraints</h1>
          <p className={`subline ${status.configured ? "" : "warn"}`}>
            <span className="dot" style={{ background: status.configured ? "var(--cyan)" : "var(--amber)" }} />
            Live ERCOT transmission constraints — a separate, real-time clock from the auction data elsewhere
          </p>
        </div>
      </header>

      {!status.configured ? (
        <section className="panel">
          <p className="state-msg" style={{ textAlign: "left" }}>{status.message}</p>
        </section>
      ) : (
        <>
          <div className="field-row">
            <span className="panel-note">Trailing window:</span>
            <div className="seg">
              {[7, 14, 30].map((n) => (
                <button key={n} className={days === n ? "active" : ""} onClick={() => setDays(n)}>
                  {n}d
                </button>
              ))}
            </div>
          </div>

          {loading ? (
            <div className="state-msg">Fetching live constraints…</div>
          ) : liveError ? (
            <section className="panel">
              <div className="state-msg error" style={{ textAlign: "left" }}>
                ERCOT's live API didn't answer this time — {liveError}
                <div style={{ marginTop: 10 }}>
                  <button className="seg" style={{ padding: "7px 13px", fontSize: 12.5 }} onClick={fetchConstraints}>
                    Retry
                  </button>
                </div>
              </div>
            </section>
          ) : !data || data.constraints.length === 0 ? (
            <section className="panel">
              <div className="state-msg">No binding constraints reported in this window.</div>
            </section>
          ) : (
            <>
              <section className="panel">
                <div className="panel-head">
                  <h2>Most active constraints, {isoDaysAgo(days)} to {isoDaysAgo(0)}</h2>
                  <span className="panel-note">By how often each one bound in this window — click to filter the table below</span>
                </div>
                <div className="hotpaths">
                  {summary.map((s) => (
                    <div
                      key={s.name}
                      className="clickable"
                      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--line-soft)" }}
                      onClick={() => setFocusConstraint(focusConstraint === s.name ? null : s.name)}
                    >
                      <span className="hp-path" style={{ color: focusConstraint === s.name ? "var(--cyan)" : "var(--paper)" }}>
                        {s.name}
                      </span>
                      <span className="mono" style={{ fontSize: 12, color: "var(--dim)" }}>
                        {s.count} hour{s.count === 1 ? "" : "s"} · max ${s.maxShadow.toFixed(2)}/MWh
                      </span>
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel">
                <div className="panel-head">
                  <h2>All constraints</h2>
                  <span className="panel-note">
                    Auction data elsewhere on this console is as of a separate, settled auction month — these
                    are two different clocks, shown side by side, never merged
                  </span>
                </div>

                <div className="field-row">
                  <input
                    type="search"
                    placeholder="Search constraint or station…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    style={{ minWidth: 240 }}
                  />
                  <div className="seg">
                    {TIER_FILTERS.map((t) => (
                      <button key={t} className={tier === t ? "active" : ""} onClick={() => setTier(t)}>
                        {t}
                      </button>
                    ))}
                  </div>
                  {focusConstraint && (
                    <span className="pill">
                      {focusConstraint}{" "}
                      <button
                        onClick={() => setFocusConstraint(null)}
                        style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer" }}
                      >
                        ×
                      </button>
                    </span>
                  )}
                  <span className="panel-note">{filtered.length} of {data.constraints.length} rows</span>
                </div>

                {data.truncated && (
                  <p className="panel-note" style={{ marginBottom: 10 }}>
                    Truncated at 15,000 rows for this window — narrow the window for a complete result.
                  </p>
                )}

                {filtered.length === 0 ? (
                  <div className="state-msg">No rows match this filter.</div>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        {COLUMNS.map((c) => (
                          <th
                            key={c.key}
                            className={`sortable${c.num ? " num-col" : ""}`}
                            onClick={() => toggleSort(c.key)}
                          >
                            {c.label}
                            {sort.key === c.key && <span className="sort-arrow">{sort.dir === "asc" ? "▲" : "▼"}</span>}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="mono">
                      {filtered.slice(0, 200).map((c, i) => {
                        const rowTier = tierFor(c.shadow_price, thresholds);
                        return (
                          <tr key={i}>
                            <td>{c.delivery_date}</td>
                            <td className="num-col num">{c.hour_ending}</td>
                            <td style={{ fontFamily: "Archivo, sans-serif" }}>{c.constraint_name}</td>
                            <td style={{ fontFamily: "Archivo, sans-serif" }}>{c.contingency_name}</td>
                            <td style={{ fontFamily: "Archivo, sans-serif" }}>
                              {c.from_station} → {c.to_station}
                            </td>
                            <td className="num-col num">
                              <span className={`tier-chip ${rowTier.toLowerCase()}`} style={{ marginRight: 8 }}>
                                {rowTier.toUpperCase()}
                              </span>
                              {c.shadow_price}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
                {filtered.length > 200 && (
                  <p className="panel-note" style={{ marginTop: 10 }}>Showing the first 200 of {filtered.length} matching rows.</p>
                )}
              </section>
            </>
          )}
        </>
      )}
    </>
  );
}
