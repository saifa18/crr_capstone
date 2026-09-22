import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { InfoTip } from "../InfoTip.jsx";
import { Combobox } from "../Combobox.jsx";

function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

const PAGE_SIZE = 25;

// Hour + Constraint are intentionally kept as ONE combined field/column
// here (not split into two), per explicit product direction -- the value
// itself is still built from two clean, already-normalized real ERCOT
// fields (hour_ending: a plain hour-ending int; constraint_name: ERCOT's
// trimmed element identifier), joined with a readable " : " separator
// rather than concatenated raw, so the combined field stays demo-legible.
const COLUMNS = [
  { key: "delivery_date", label: "Date" },
  {
    key: "hour_ending", label: "HourEnding : Constraint",
    info: "ERCOT's hour-ending interval (e.g. \"24\" is the hour ending at midnight) followed by ERCOT's identifier for the binding transmission constraint — an internal ERCOT element name, not a plain-English line description.",
  },
  {
    key: "contingency_name", label: "Contingency",
    info: "The system outage/scenario being evaluated when this constraint is binding. \"BASE CASE\" means no modeled contingency — the element is binding under normal system conditions. Any other value is an ERCOT contingency identifier (an assumed outage/event); this data does not map it to a specific piece of equipment.",
  },
  {
    key: "from_station", label: "Element endpoints",
    info: "The from/to grid locations associated with the monitored transmission element (ERCOT's \"From Station\" / \"To Station\" fields) — not a CRR Source/Sink settlement point.",
  },
  {
    key: "shadow_price", label: "Shadow price ($/MWh)", num: true,
    info: "The marginal economic impact of this transmission constraint. Larger values generally indicate more costly congestion. This is NOT the same thing as a CRR path settlement price (Sink SPP − Source SPP), an auction price, or participant profit.",
  },
];

export default function BindingConstraints() {
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [days, setDays] = useState(7);
  const [focusConstraint, setFocusConstraint] = useState(null);
  const [sort, setSort] = useState({ key: "delivery_date", dir: "desc" });
  const [page, setPage] = useState(1);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [liveError, setLiveError] = useState(null);

  useEffect(() => {
    api.liveStatus().then(setStatus).catch((e) => setStatusError(e.message));
  }, []);

  // One effect drives every fetch -- the trailing window, constraint
  // filter, or a sort/page change. Filters/sort are always applied to the
  // FULL window server-side before pagination (see live_binding_
  // constraints in main.py), so `total`/`total_pages` here always reflect
  // the fully filtered set. Uses the same "compute effectivePage
  // synchronously in this run" pattern the Participants page's
  // Certificates table uses to fix its own Previous-button bug: a naive
  // separate "reset page to 1" effect would let a stale page number slip
  // through to the very next fetch after a filter changes.
  const filterKey = `${days}||${focusConstraint || ""}||${sort.key}||${sort.dir}`;
  const prevFilterKeyRef = React.useRef(null);
  const requestIdRef = React.useRef(0);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    if (!status || !status.configured) return;
    const filtersChanged = prevFilterKeyRef.current !== filterKey;
    prevFilterKeyRef.current = filterKey;
    const effectivePage = filtersChanged ? 1 : page;
    if (filtersChanged && page !== 1) setPage(1);

    setLoading(true);
    setLiveError(null);
    const requestId = ++requestIdRef.current;
    api
      .bindingConstraints({
        date_from: isoDaysAgo(days),
        date_to: isoDaysAgo(0),
        constraint_name: focusConstraint || undefined,
        sort_key: sort.key,
        sort_dir: sort.dir,
        page: effectivePage,
        page_size: PAGE_SIZE,
      })
      .then((body) => {
        if (requestId !== requestIdRef.current) return; // superseded by a newer request
        setData(body);
      })
      .catch((e) => {
        if (requestId !== requestIdRef.current) return;
        setLiveError(e.message);
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false);
      });
    // `retryToken` is a dependency purely to let the Retry button force a
    // fresh fetch (e.g. after a transient ERCOT error) through this same
    // effect instead of duplicating its fetch logic -- it's deliberately
    // NOT part of `filterKey`, so a retry keeps the current page/filters
    // rather than being treated as a filter change back to page 1.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, filterKey, page, retryToken]);

  const retry = () => setRetryToken((t) => t + 1);

  const constraintOptions = React.useMemo(() => {
    const names = data?.constraint_options || [];
    return [{ key: "", label: "All constraints" }, ...names.map((n) => ({ key: n, label: n }))];
  }, [data]);

  const toggleSort = (key) => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  };

  if (statusError) {
    return <div className="state-msg error">{statusError}</div>;
  }
  if (!status) return <div className="state-msg">Checking live ERCOT API status…</div>;

  const items = data?.items || [];
  const total = data?.total ?? 0;
  const totalPages = data?.total_pages ?? 0;
  const summary = data?.summary || [];
  const rangeStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = total === 0 ? 0 : rangeStart + items.length - 1;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Binding constraints</h1>
          <p className={`subline ${status.configured ? "" : "warn"}`}>
            <span className="dot" style={{ background: status.configured ? "var(--cyan)" : "var(--amber)" }} />
            Live ERCOT transmission constraints that can drive congestion and nodal price differences.
          </p>
        </div>
      </header>

      {!status.configured ? (
        <section className="panel">
          <p className="state-msg" style={{ textAlign: "left" }}>{status.message}</p>
        </section>
      ) : (
        <>
          <section className="panel">
            <div className="panel-head">
              <h2>Search constraint</h2>
            </div>
            <div style={{ maxWidth: 420, marginBottom: 10 }}>
              <Combobox
                options={constraintOptions}
                selectedLabel={focusConstraint || "All constraints"}
                onSelect={(key) => setFocusConstraint(key || null)}
                placeholder="Search constraint name or ID…"
              />
            </div>
            <div className="field-row" style={{ marginBottom: 0 }}>
              <span className="panel-note">Trailing window:</span>
              <div className="seg">
                {[7, 14, 30].map((n) => (
                  <button key={n} className={days === n ? "active" : ""} onClick={() => setDays(n)}>
                    {n}d
                  </button>
                ))}
              </div>
            </div>
          </section>

          {liveError ? (
            <section className="panel">
              <div className="state-msg error" style={{ textAlign: "left" }}>
                ERCOT's live API didn't answer this time — {liveError}
                <div style={{ marginTop: 10 }}>
                  <button className="seg" style={{ padding: "7px 13px", fontSize: 12.5 }} onClick={retry}>
                    Retry
                  </button>
                </div>
              </div>
            </section>
          ) : !data ? (
            <div className="state-msg">Fetching live constraints…</div>
          ) : data.total === 0 && !focusConstraint ? (
            <section className="panel">
              <div className="state-msg">No binding constraints reported in this window.</div>
            </section>
          ) : (
            <>
              <section className="panel">
                <div className="panel-head">
                  <h2>Most active constraints, {isoDaysAgo(days)} to {isoDaysAgo(0)}</h2>
                  <span className="panel-note">
                    Ranked by how often each constraint was binding during the selected window — click a row
                    to filter the table below
                    <InfoTip>
                      "Binding intervals" counts the hourly rows in this window where ERCOT reported this
                      element as a binding constraint (one interval per hour it was limiting) — not a
                      duration or a percentage. "Max shadow price" is the largest shadow price this element
                      reached during any of those hours in this window.
                    </InfoTip>
                  </span>
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
                        {s.count} binding interval{s.count === 1 ? "" : "s"} · Max shadow price: ${s.max_shadow.toFixed(2)}/MWh
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
                  <span className="panel-note">
                    {total === 0 ? "0 rows" : `Showing ${rangeStart.toLocaleString()}–${rangeEnd.toLocaleString()} of ${total.toLocaleString()} rows`}
                  </span>
                </div>

                {data.truncated && (
                  <p className="panel-note" style={{ marginBottom: 10 }}>
                    Truncated at 15,000 rows for this window — narrow the window for a complete result.
                  </p>
                )}

                {total === 0 ? (
                  <div className="state-msg">No rows match this filter.</div>
                ) : (
                  <div style={{ position: "relative" }}>
                    {loading && (
                      <div className="state-msg" style={{ position: "absolute", inset: 0, background: "var(--panel)", zIndex: 1 }}>
                        Loading…
                      </div>
                    )}
                    <div style={{ overflowX: "auto" }}>
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
                                {c.info && <InfoTip>{c.info}</InfoTip>}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="mono">
                          {items.map((c, i) => (
                            <tr key={i}>
                              <td>{c.delivery_date}</td>
                              <td>{c.hour_ending != null ? c.hour_ending : "—"} : {c.constraint_name}</td>
                              <td style={{ fontFamily: "Archivo, sans-serif" }}>{c.contingency_name}</td>
                              <td style={{ fontFamily: "Archivo, sans-serif" }}>
                                {c.from_station} → {c.to_station}
                              </td>
                              <td className="num-col num">{c.shadow_price}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {totalPages > 0 && (
                  <div className="field-row" style={{ marginTop: 12, marginBottom: 0, justifyContent: "center" }}>
                    <button
                      className="seg"
                      style={{ padding: "6px 14px", fontSize: 12.5 }}
                      disabled={page <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                      ← Previous
                    </button>
                    <span className="panel-note mono">Page {page} of {totalPages}</span>
                    <button
                      className="seg"
                      style={{ padding: "6px 14px", fontSize: 12.5 }}
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => (p < totalPages ? p + 1 : p))}
                    >
                      Next →
                    </button>
                  </div>
                )}
              </section>
            </>
          )}
        </>
      )}
    </>
  );
}
