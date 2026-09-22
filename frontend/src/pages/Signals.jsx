import React, { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";
import { api } from "../api.js";

function pairKey(p) { return `${p.source}__${p.sink}`; }
function pairLabel(p) { return `${p.source_name} → ${p.sink_name}`; }

function currentYearJan1() {
  return `${new Date().getFullYear()}-01-01`;
}
function firstOfThisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}
function today() {
  return new Date().toISOString().slice(0, 10);
}

function MiniSparkline({ data }) {
  if (!data || data.length === 0) {
    return <div style={{ width: 100, height: 30, fontSize: 10, color: "var(--dim)" }}>no data</div>;
  }
  return (
    <div style={{ width: 100, height: 30 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
          <ReferenceLine y={0} stroke="var(--dim-2)" strokeDasharray="2 2" />
          <Line type="monotone" dataKey="obligation_price" stroke="var(--cyan)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function StatTile({ label, value }) {
  return (
    <div className="kpi">
      <div className="kpi-value mono num" style={{ fontSize: 18 }}>{value == null ? "—" : value.toFixed(2)}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

function PathDetail({ pair, legacyScore }) {
  const [range, setRange] = useState("ytd"); // "ytd" | "month"
  const [viewMode, setViewMode] = useState("settlement"); // "settlement" | "raw"
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    const dateFrom = range === "ytd" ? currentYearJan1() : firstOfThisMonth();
    api
      .settlementHistory(pair.source, pair.sink, { date_from: dateFrom, date_to: today() })
      .then(setDetail)
      .catch((e) => setError(e.message));
  }, [pair, range]);

  return (
    <section className="panel participants-detail-panel">
      <div className="panel-head">
        <h2>{pairLabel(pair)}</h2>
        <div className="seg">
          <button className={range === "ytd" ? "active" : ""} onClick={() => setRange("ytd")}>
            YTD (Jan 1 → today)
          </button>
          <button className={range === "month" ? "active" : ""} onClick={() => setRange("month")}>
            This month
          </button>
        </div>
      </div>

      {error ? (
        <div className="state-msg error">Couldn't load real settlement history — {error}</div>
      ) : !detail ? (
        <div className="state-msg">Loading real ERCOT settlement price history…</div>
      ) : (
        <>
          <p className="panel-note" style={{ marginBottom: 14 }}>
            If you held this path as an <strong>Obligation</strong>, you'd have been paid (or owed) the
            raw Sink SPP − Source SPP every hour. If you held it as an <strong>Option</strong>, you'd
            never owe money — the floor is $0. Real ERCOT Day-Ahead settlement point prices, {detail.date_from} → {detail.date_to}.
          </p>

          <div className="kpis" style={{ marginBottom: 16 }}>
            <StatTile label="latest obligation ($/MWh)" value={detail.summary.obligation.latest} />
            <StatTile label="average obligation ($/MWh)" value={detail.summary.obligation.average} />
            <StatTile label="min obligation ($/MWh)" value={detail.summary.obligation.min} />
            <StatTile label="max obligation ($/MWh)" value={detail.summary.obligation.max} />
          </div>
          <div className="kpis" style={{ marginBottom: 16 }}>
            <StatTile label="latest option ($/MWh)" value={detail.summary.option.latest} />
            <StatTile label="average option ($/MWh)" value={detail.summary.option.average} />
            <StatTile label="min option ($/MWh)" value={detail.summary.option.min} />
            <StatTile label="max option ($/MWh)" value={detail.summary.option.max} />
          </div>

          <div className="field-row" style={{ marginBottom: 6 }}>
            <div className="seg">
              <button className={viewMode === "settlement" ? "active" : ""} onClick={() => setViewMode("settlement")}>
                Path settlement
              </button>
              <button className={viewMode === "raw" ? "active" : ""} onClick={() => setViewMode("raw")}>
                Source SPP vs sink SPP
              </button>
            </div>
          </div>

          <div style={{ width: "100%", height: 300 }}>
            <ResponsiveContainer>
              {viewMode === "settlement" ? (
                <LineChart data={detail.daily_series} margin={{ top: 6, right: 12, left: -6, bottom: 0 }}>
                  <CartesianGrid stroke="#171f29" vertical={false} />
                  <ReferenceLine y={0} stroke="var(--dim-2)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fill: "#64768a", fontSize: 10 }} axisLine={{ stroke: "#212b37" }} tickLine={false} />
                  <YAxis tick={{ fill: "#64768a", fontSize: 11 }} axisLine={{ stroke: "#212b37" }} tickLine={false} width={54} />
                  <Tooltip contentStyle={{ background: "#10161e", border: "1px solid #212b37", fontSize: 12 }} labelStyle={{ color: "#dee6ec" }} />
                  <Line type="monotone" dataKey="obligation_price" name="Obligation ($/MWh)" stroke="#3fbf8f" strokeWidth={2} dot={false} connectNulls />
                  <Line type="monotone" dataKey="option_price" name="Option ($/MWh)" stroke="#de9a4e" strokeWidth={2} dot={false} connectNulls />
                </LineChart>
              ) : (
                <LineChart margin={{ top: 6, right: 12, left: -6, bottom: 0 }}>
                  <CartesianGrid stroke="#171f29" vertical={false} />
                  <XAxis dataKey="date" type="category" allowDuplicatedCategory={false}
                    tick={{ fill: "#64768a", fontSize: 10 }} axisLine={{ stroke: "#212b37" }} tickLine={false} />
                  <YAxis tick={{ fill: "#64768a", fontSize: 11 }} axisLine={{ stroke: "#212b37" }} tickLine={false} width={54} />
                  <Tooltip contentStyle={{ background: "#10161e", border: "1px solid #212b37", fontSize: 12 }} labelStyle={{ color: "#dee6ec" }} />
                  <Line data={detail.source_daily} type="monotone" dataKey="price" name={`${pair.source_name} SPP`} stroke="#54bedd" strokeWidth={2} dot={false} connectNulls />
                  <Line data={detail.sink_daily} type="monotone" dataKey="price" name={`${pair.sink_name} SPP`} stroke="#b98bd9" strokeWidth={2} dot={false} connectNulls />
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>

          {legacyScore && (
            <p className="panel-note" style={{ marginTop: 14 }}>
              Legacy auction-based signal for this path (built from historical CRR bid/clearing
              prices, not settlement prices): <strong>{legacyScore.tier}</strong> ({legacyScore.score}/100).
            </p>
          )}
        </>
      )}
    </section>
  );
}

const PATH_PAGE_SIZE = 10;

export default function Signals() {
  const [summary, setSummary] = useState(null);
  const [scores, setScores] = useState(null);
  const [query, setQuery] = useState("");
  const [selectedKey, setSelectedKey] = useState(null);
  const [error, setError] = useState(null);
  const [pathPage, setPathPage] = useState(1);

  useEffect(() => {
    // The always-visible mini sparkline for every tracked path defaults to
    // the current calendar month, not full YTD -- YTD across ~20 distinct
    // nodes would mean many sequential paginated ERCOT calls just to draw
    // the list. A trader can still open any one path's detail view and
    // switch to the full YTD range there, where it's just 2 nodes.
    api
      .settlementSummary({ date_from: firstOfThisMonth(), date_to: today() })
      .then((body) => {
        setSummary(body);
        if (body.pairs.length) setSelectedKey(pairKey(body.pairs[0]));
      })
      .catch((e) => setError(e.message));
    api.opportunityScores().then(setScores).catch(() => {});
  }, []);

  const scoreByKey = useMemo(() => {
    const map = {};
    (scores || []).forEach((s) => { map[pairKey(s)] = s; });
    return map;
  }, [scores]);

  // The search box filters the FULL tracked-path list (already entirely
  // loaded client-side -- summary.pairs is a small, bulk-fetched set, not
  // thousands of rows, so no server round-trip is needed here) before
  // pagination, so narrowing the search to a handful of paths correctly
  // collapses to a single page rather than just hiding non-matches on
  // whichever page happened to be showing.
  const filteredPairs = useMemo(() => {
    if (!summary) return [];
    const q = query.trim().toLowerCase();
    if (!q) return summary.pairs;
    return summary.pairs.filter(
      (p) =>
        p.source_name.toLowerCase().includes(q) ||
        p.sink_name.toLowerCase().includes(q) ||
        p.source.toLowerCase().includes(q) ||
        p.sink.toLowerCase().includes(q)
    );
  }, [summary, query]);

  // Changing the search query resets the path list back to page 1 -- a
  // stale page number from a larger, differently-filtered result set can
  // never be left pointing past the end of the new one.
  useEffect(() => {
    setPathPage(1);
  }, [query]);

  const pathTotalPages = Math.max(1, Math.ceil(filteredPairs.length / PATH_PAGE_SIZE));
  const clampedPathPage = Math.min(pathPage, pathTotalPages);
  const pagedPairs = filteredPairs.slice(
    (clampedPathPage - 1) * PATH_PAGE_SIZE,
    clampedPathPage * PATH_PAGE_SIZE
  );

  // Deliberately looked up against the FULL, unfiltered/unpaginated
  // summary.pairs, not `pagedPairs` or `filteredPairs` -- so paginating or
  // searching the LIST never disturbs which path the DETAIL panel is
  // showing. The selection only changes when the user clicks a different
  // row; it is never crashed or reset just because the row it came from
  // scrolled off the current page or out of the current search filter.
  const selectedPair = summary?.pairs.find((p) => pairKey(p) === selectedKey);

  if (error) return <div className="state-msg error">{error}</div>;
  if (!summary) return <div className="state-msg">Loading real ERCOT settlement price history for every path…</div>;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Path settlements</h1>
          <p className="subline">
            <span className="dot" />
            See how each CRR path actually settled using real ERCOT Day-Ahead SPPs — Sink SPP minus
            Source SPP, not an arbitrary High/Medium/Low score. This list shows {summary.date_from} → {summary.date_to};
            open a path for the full January 1st → today history.
          </p>
        </div>
      </header>

      <div className="field-row">
        <input
          type="search"
          placeholder="Search hub or zone…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 220 }}
        />
      </div>

      <div className="participants-layout">
        <section className="panel participants-list-panel">
          <div className="participants-scroll">
            {filteredPairs.length === 0 ? (
              <div className="state-msg">No paths match this filter.</div>
            ) : (
              pagedPairs.map((p) => (
                <div
                  key={pairKey(p)}
                  className={`participant-row${pairKey(p) === selectedKey ? " participant-row-selected" : ""}`}
                  style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}
                  onClick={() => setSelectedKey(pairKey(p))}
                >
                  <div>
                    <div className="participant-row-name">{pairLabel(p)}</div>
                    <div className="participant-row-stats mono">
                      obligation avg {p.summary.obligation.average.toFixed(2)} $/MWh
                    </div>
                  </div>
                  <MiniSparkline data={p.daily_series} />
                </div>
              ))
            )}

            {summary.unavailable_pairs.length > 0 && (
              <>
                <div className="participant-row-stats" style={{ padding: "10px 14px 4px", textTransform: "uppercase", letterSpacing: "0.4px" }}>
                  No live settlement data
                </div>
                {summary.unavailable_pairs.map((p) => (
                  <div key={pairKey(p)} className="participant-row" style={{ cursor: "default", opacity: 0.55 }}>
                    <div className="participant-row-name">{p.source_name} → {p.sink_name}</div>
                    <div className="participant-row-stats">{p.reason}</div>
                  </div>
                ))}
              </>
            )}
          </div>

          {filteredPairs.length > 0 && pathTotalPages > 1 && (
            <div className="field-row" style={{ marginTop: 10, marginBottom: 0, justifyContent: "center" }}>
              <button
                className="seg"
                style={{ padding: "5px 12px", fontSize: 12 }}
                disabled={clampedPathPage <= 1}
                onClick={() => setPathPage(Math.max(1, clampedPathPage - 1))}
              >
                ← Previous
              </button>
              <span className="panel-note mono" style={{ fontSize: 11 }}>
                Page {clampedPathPage} of {pathTotalPages}
              </span>
              <button
                className="seg"
                style={{ padding: "5px 12px", fontSize: 12 }}
                disabled={clampedPathPage >= pathTotalPages}
                onClick={() => setPathPage(Math.min(pathTotalPages, clampedPathPage + 1))}
              >
                Next →
              </button>
            </div>
          )}
        </section>

        {selectedPair ? (
          <PathDetail pair={selectedPair} legacyScore={scoreByKey[pairKey(selectedPair)]} />
        ) : (
          <section className="panel participants-detail-panel">
            <div className="state-msg">Select a path to see how it settled.</div>
          </section>
        )}
      </div>
    </>
  );
}
