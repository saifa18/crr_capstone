import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { InfoTip } from "../InfoTip.jsx";
import { Combobox } from "../Combobox.jsx";

function pairKey(p) { return `${p.source}__${p.sink}`; }
function pairLabel(p) { return `${p.source_name} → ${p.sink_name}`; }

const CERT_PAGE_SIZE = 25;

// Certificates are paginated server-side (25/page) -- the backend applies
// participant/period/path filters FIRST, then slices just that one page,
// so a participant with thousands of matching certificates never has more
// than 25 rows serialized or rendered at once. This component only ever
// receives one page's worth of rows.
function CertificatesTable({ certs, loading, error, page, onPrev, onNext }) {
  if (error) {
    return <div className="state-msg error">Couldn't load certificates — {error}</div>;
  }
  if (!certs) {
    return <div className="state-msg">Loading certificates…</div>;
  }

  const { items, total, total_pages: totalPages } = certs;
  const rangeStart = total === 0 ? 0 : (page - 1) * CERT_PAGE_SIZE + 1;
  const rangeEnd = total === 0 ? 0 : rangeStart + items.length - 1;

  return (
    <>
      <p className="panel-note" style={{ marginBottom: 10 }}>
        {total === 0
          ? "No certificates match the current filters."
          : `Showing ${rangeStart.toLocaleString()}–${rangeEnd.toLocaleString()} of ${total.toLocaleString()} certificates`}
      </p>
      <div style={{ position: "relative" }}>
        {loading && (
          <div className="state-msg" style={{ position: "absolute", inset: 0, background: "var(--panel)", zIndex: 1 }}>
            Loading certificates…
          </div>
        )}
        <table>
          <thead>
            <tr>
              <th>Auction month</th>
              <th>Source → sink</th>
              <th>Type</th>
              <th className="num-col">MW</th>
              <th className="num-col">Price ($/MWh)</th>
            </tr>
          </thead>
          <tbody className="mono">
            {items.length === 0 ? (
              <tr><td colSpan={5} className="state-msg">No certificates match the current filters.</td></tr>
            ) : (
              items.map((r, i) => (
                <tr key={i}>
                  <td>{r.auction_month}</td>
                  <td style={{ fontFamily: "Archivo, sans-serif" }}>{r.source} → {r.sink}</td>
                  <td>{r.crr_type}</td>
                  <td className="num-col num">{r.awarded_mw}</td>
                  <td className="num-col num">{r.clearing_price}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {totalPages > 0 && (
        <div className="field-row" style={{ marginTop: 12, marginBottom: 0, justifyContent: "center" }}>
          <button
            className="seg"
            style={{ padding: "6px 14px", fontSize: 12.5 }}
            disabled={page <= 1}
            onClick={onPrev}
          >
            ← Previous
          </button>
          <span className="panel-note mono">Page {page} of {totalPages}</span>
          <button
            className="seg"
            style={{ padding: "6px 14px", fontSize: 12.5 }}
            disabled={page >= totalPages}
            onClick={onNext}
          >
            Next →
          </button>
        </div>
      )}
    </>
  );
}

const LEADERBOARD_PAGE_SIZE = 25;

// Cross-corridor, cross-participant real settlement value: independent of
// which single participant is selected above (item 6 in the spec -- "I
// want to be able to analyze settlement value across participants, not
// only the currently selected participant"). Participant and Path both
// default to "All" and are searchable comboboxes, not permanent lists (a
// tracked-pair universe here is ~30 corridors and can be hundreds of
// participants). Server-side paginated 25/page, same {items, page,
// page_size, total, total_pages} contract as the Certificates table
// above, including the same Previous-button fix (see the certificates
// effect's comment for why a naive "skip fetching on page===1" is wrong).
function SettlementLeaderboard({ allParticipants, allPairs }) {
  const [participantKey, setParticipantKey] = useState(""); // "" = All participants
  const [pathKey, setPathKey] = useState(""); // "" = All paths
  const [crrType, setCrrType] = useState(""); // "" = All
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const selectedPair = pathKey ? allPairs.find((p) => pairKey(p) === pathKey) : null;
  const filterKey = `${participantKey}||${pathKey}||${crrType}||${month}`;
  const prevFilterKeyRef = React.useRef(null);
  const requestIdRef = React.useRef(0);

  // One effect handles every trigger (participant, path, type, month, or
  // a plain page turn) so "return to page 1" is never a special case that
  // can be skipped -- computing `effectivePage` synchronously here, in the
  // same run that detects the filter change, avoids the stale-page race a
  // separate "reset page" effect would hit (that effect's setState only
  // takes effect on the NEXT render, so a fetch effect keyed on the raw
  // page value would still fire once with the OLD page number and the NEW
  // filters in between).
  useEffect(() => {
    if (!month) return;
    const filtersChanged = prevFilterKeyRef.current !== filterKey;
    prevFilterKeyRef.current = filterKey;
    const effectivePage = filtersChanged ? 1 : page;
    if (filtersChanged && page !== 1) setPage(1);

    setLoading(true);
    setError(null);
    const requestId = ++requestIdRef.current;
    api
      .settlementLeaderboard({
        auction_month: month,
        source: selectedPair?.source,
        sink: selectedPair?.sink,
        participant: participantKey || undefined,
        crr_type: crrType || undefined,
        page: effectivePage,
        page_size: LEADERBOARD_PAGE_SIZE,
      })
      .then((body) => {
        if (requestId !== requestIdRef.current) return; // superseded by a newer request
        setResult(body);
      })
      .catch((e) => {
        if (requestId !== requestIdRef.current) return;
        setError(e.message);
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, page]);

  const participantOptions = useMemo(
    () => [
      { key: "", label: "All participants" },
      ...(allParticipants || []).map((p) => ({ key: p.participant, label: p.participant })),
    ],
    [allParticipants]
  );
  const pathOptions = useMemo(
    () => [{ key: "", label: "All paths" }, ...allPairs.map((p) => ({ key: pairKey(p), label: pairLabel(p) }))],
    [allPairs]
  );

  const items = result?.items || [];
  const total = result?.total ?? 0;
  const totalPages = result?.total_pages ?? 0;
  const rangeStart = total === 0 ? 0 : (page - 1) * LEADERBOARD_PAGE_SIZE + 1;
  const rangeEnd = total === 0 ? 0 : rangeStart + items.length - 1;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Path settlement value by participant</h2>
      </div>
      <p className="panel-note" style={{ marginBottom: 10 }}>
        Real CRR path settlement value — awarded MW × real ERCOT settlement point price spread for
        that path/month — separate from the "notional" figure above, which is what a participant
        paid at auction, not what the path settled for. Settlement value only, not necessarily total
        trading profit: acquisition cost and fees aren't in this dataset. This month selector is its
        own real calendar-month date context, independent of the "Auction period" filter above (which
        can be "All time"/"YTD"/a different month) — the two are never silently mixed.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 14 }}>
        <div>
          <div className="panel-note" style={{ marginBottom: 6 }}>Participant</div>
          <Combobox
            options={participantOptions}
            selectedLabel={participantKey || "All participants"}
            onSelect={setParticipantKey}
            placeholder="Search or select participant…"
          />
        </div>
        <div>
          <div className="panel-note" style={{ marginBottom: 6 }}>Path</div>
          <Combobox
            options={pathOptions}
            selectedLabel={selectedPair ? pairLabel(selectedPair) : "All paths"}
            onSelect={setPathKey}
            placeholder="Search source or sink…"
          />
        </div>
        <div className="field-row" style={{ marginBottom: 0 }}>
          <div className="seg">
            {["", "OBLIGATION", "OPTION"].map((t) => (
              <button key={t || "all"} className={crrType === t ? "active" : ""} onClick={() => setCrrType(t)}>
                {t === "" ? "All types" : t === "OBLIGATION" ? "Obligation" : "Option"}
              </button>
            ))}
          </div>
          <div>
            <div className="panel-note" style={{ marginBottom: 6 }}>Settlement month</div>
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          </div>
        </div>
      </div>

      {error ? (
        <div className="state-msg error">Couldn't load path settlement values — {error}</div>
      ) : !result ? (
        <div className="state-msg">Loading real settlement values…</div>
      ) : total === 0 ? (
        <div className="state-msg">No settlement-value records match this participant/path combination.</div>
      ) : (
        <>
          <p className="panel-note" style={{ marginBottom: 10 }}>
            Showing {rangeStart.toLocaleString()}–{rangeEnd.toLocaleString()} of {total.toLocaleString()} rows for {month}
          </p>
          <div style={{ position: "relative" }}>
            {loading && (
              <div className="state-msg" style={{ position: "absolute", inset: 0, background: "var(--panel)", zIndex: 1 }}>
                Loading…
              </div>
            )}
            <table>
              <thead>
                <tr>
                  <th>Participant</th>
                  <th>Source → sink</th>
                  <th>Type</th>
                  <th className="num-col">MW</th>
                  <th className="num-col">Settlement $/MW</th>
                  <th className="num-col">Path settlement value ($)</th>
                </tr>
              </thead>
              <tbody className="mono">
                {items.map((r, i) => (
                  <tr key={i}>
                    <td style={{ fontFamily: "Archivo, sans-serif" }}>{r.participant}</td>
                    <td style={{ fontFamily: "Archivo, sans-serif" }}>{r.source} → {r.sink}</td>
                    <td>{r.crr_type}</td>
                    <td className="num-col num">{r.awarded_mw}</td>
                    <td className="num-col num">{r.settlement_value_per_mw.toLocaleString()}</td>
                    <td
                      className="num-col num"
                      style={{ color: r.settlement_value >= 0 ? "var(--green)" : "#e0708f" }}
                    >
                      {r.settlement_value.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
          {result.unavailable_pairs?.length > 0 && (
            <p className="panel-note" style={{ marginTop: 10, opacity: 0.7 }}>
              {result.unavailable_pairs.length} corridor(s) skipped this month (no live ERCOT settlement
              data, or backed by synthetic demo data).
            </p>
          )}
        </>
      )}
    </section>
  );
}

export default function Participants() {
  const [searchParams] = useSearchParams();
  const [allParticipants, setAllParticipants] = useState(null);
  const [allPairs, setAllPairs] = useState([]);
  const [auctionMonths, setAuctionMonths] = useState([]);
  const [pathKey, setPathKey] = useState("");
  const [crrType, setCrrType] = useState("");
  const [pathScopedList, setPathScopedList] = useState(null);
  const [period, setPeriod] = useState("all");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [certs, setCerts] = useState(null);
  const [certPage, setCertPage] = useState(1);
  const [certLoading, setCertLoading] = useState(false);
  const [certError, setCertError] = useState(null);
  const [error, setError] = useState(null);
  const appliedFocus = React.useRef(false);

  useEffect(() => {
    api.participants().then(setAllParticipants).catch((e) => setError(e.message));
    api.pairs().then(setAllPairs).catch(() => {});
    api.meta().then((m) => setAuctionMonths(m.auction_months || [])).catch(() => {});
  }, []);

  // The active participant list: every tracked participant by default, or
  // just those active on the selected path (optionally narrowed further by
  // CRR type) -- this is the same real /api/pairs/{s}/{k}/participants
  // cross-reference the Explorer page uses, just feeding a combobox instead
  // of a permanent side list.
  useEffect(() => {
    if (!pathKey) {
      setPathScopedList(null);
      return;
    }
    const pair = allPairs.find((p) => pairKey(p) === pathKey);
    if (!pair) return;
    api
      .pairParticipants(pair.source, pair.sink, crrType || undefined)
      .then((body) => setPathScopedList(body.participants))
      .catch((e) => setError(e.message));
  }, [pathKey, crrType, allPairs]);

  const activeList = pathKey ? pathScopedList : allParticipants;

  // If the path/type filter changes and the currently-selected participant
  // falls out of scope, fall back to the first participant still in scope.
  useEffect(() => {
    if (!activeList || appliedFocus.current === "pending") return;
    if (selected && activeList.some((p) => p.participant === selected)) return;
    if (activeList.length) setSelected(activeList[0].participant);
  }, [activeList, selected]);

  // Deep link from Overview ("?focus=<name>") wins on first load only.
  useEffect(() => {
    if (appliedFocus.current || !allParticipants) return;
    appliedFocus.current = true;
    const focus = searchParams.get("focus");
    if (focus) setSelected(focus);
    else if (allParticipants.length) setSelected(allParticipants[0].participant);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allParticipants]);

  const selectedPair = pathKey ? allPairs.find((p) => pairKey(p) === pathKey) : null;

  // Certificates: ONE effect drives every fetch -- a filter change
  // (participant, period, path, or CRR type) or a plain page turn,
  // including Previous returning to page 1.
  //
  // ROOT CAUSE of the broken "Previous" button this replaces: the old
  // code split this into a "full reload" effect (always fetched page 1,
  // only on filter change) and a separate "page turn" effect that
  // special-cased `if (certPage === 1) return;` -- on the theory that
  // page 1 was always already loaded by the reload effect. That's true
  // right after a filter change, but false after the user paginates away
  // from page 1 and presses Previous back to it: `certPage` becomes 1
  // again, the page-turn effect's guard skipped fetching (since
  // certPage === 1), and `certs` was left holding whatever later page had
  // been fetched last -- so the table kept showing that stale page's rows
  // under a "Page 1" label instead of re-fetching real page-1 data.
  //
  // The fix: fetch unconditionally for every certPage value, including 1.
  // To avoid a wasted/incorrect double-fetch on a genuine filter change
  // (which also resets certPage to 1), `filtersChanged` is computed
  // synchronously in THIS run by comparing against a ref of the last
  // filter key seen -- not via a separate "reset" effect, whose setState
  // wouldn't take effect until a later render and would let this effect
  // fire once in between with the OLD page number and the NEW filters.
  // A `requestId` guard also drops any response that's since been
  // superseded by a newer request (e.g. two quick filter changes), so an
  // out-of-order network response can never overwrite fresher state.
  const certFilterKey = `${selected || ""}||${period}||${selectedPair?.source || ""}||${selectedPair?.sink || ""}||${crrType}`;
  const prevCertFilterKeyRef = React.useRef(null);
  const certRequestIdRef = React.useRef(0);

  useEffect(() => {
    if (!selected) return;
    const filtersChanged = prevCertFilterKeyRef.current !== certFilterKey;
    prevCertFilterKeyRef.current = certFilterKey;
    const effectivePage = filtersChanged ? 1 : certPage;
    if (filtersChanged && certPage !== 1) setCertPage(1);

    if (filtersChanged) {
      setDetail(null);
      setCerts(null);
    }
    setCertLoading(true);
    setCertError(null);
    const requestId = ++certRequestIdRef.current;
    api
      .participantDetail(
        selected, period, selectedPair?.source, selectedPair?.sink,
        effectivePage, CERT_PAGE_SIZE, crrType || undefined
      )
      .then((body) => {
        if (requestId !== certRequestIdRef.current) return; // superseded by a newer request
        // Always set `detail` (not just when this particular run believed
        // itself to be "the" filter-change run): a filter change followed
        // immediately by certPage's own reset-triggered re-render can fire
        // this effect twice for the same logical change (see the comment
        // above), and the FIRST run's response is the one the requestId
        // guard above discards as superseded -- so gating `setDetail` on
        // `filtersChanged` left `detail` stuck at the `null` this same
        // effect had just set, with no request left that both matched
        // filtersChanged AND survived the requestId check. Every surviving
        // response already carries the correct summary/pairs for the
        // CURRENT filters regardless of which page was requested, so
        // setting it unconditionally is always correct, not just harmless.
        setDetail(body);
        setCerts(body.recent_activity);
      })
      .catch((e) => {
        if (requestId !== certRequestIdRef.current) return;
        // Always local (certError), never the page-level `error` that
        // would blank the whole page -- a failed fetch here should only
        // ever affect the activity/certificates section (see the `!detail`
        // render branch below, which shows certError there too when
        // `detail` hasn't loaded yet).
        setCertError(e.message);
      })
      .finally(() => {
        if (requestId === certRequestIdRef.current) setCertLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [certFilterKey, certPage]);

  const participantOptions = useMemo(
    () => (activeList || []).map((p) => ({ key: p.participant, label: p.participant })),
    [activeList]
  );
  const pathOptions = useMemo(
    () => [{ key: "", label: "All paths" }, ...allPairs.map((p) => ({ key: pairKey(p), label: pairLabel(p) }))],
    [allPairs]
  );
  const periodOptions = useMemo(() => {
    const opts = [{ key: "all", label: "All time" }];
    if (auctionMonths.length) {
      const latestYear = auctionMonths[auctionMonths.length - 1].slice(0, 4);
      opts.push({ key: "ytd", label: `${latestYear} YTD` });
    }
    for (const m of [...auctionMonths].reverse()) opts.push({ key: m, label: m });
    return opts;
  }, [auctionMonths]);
  const periodLabel = periodOptions.find((o) => o.key === period)?.label || "All time";
  const selectedPathLabel = pathOptions.find((o) => o.key === pathKey)?.label || "All paths";

  if (error) return <div className="state-msg error">{error}</div>;
  if (!allParticipants) return <div className="state-msg">Loading participants…</div>;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Participants</h1>
          <p className="subline">
            <span className="dot" />
            See participant CRR positions, auction activity, and settlement value — {allParticipants.length} active on tracked paths
          </p>
        </div>
      </header>

      <section className="panel">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <div className="panel-note" style={{ marginBottom: 6 }}>Search participant</div>
            <Combobox
              options={participantOptions}
              selectedLabel={selected || ""}
              onSelect={setSelected}
              placeholder="Search participant name…"
            />
          </div>

          <div className="field-row" style={{ marginBottom: 0 }}>
            <div>
              <div className="panel-note" style={{ marginBottom: 6 }}>Auction period</div>
              <select value={period} onChange={(e) => setPeriod(e.target.value)}>
                {periodOptions.map((o) => (
                  <option key={o.key} value={o.key}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <div className="panel-note" style={{ marginBottom: 6 }}>
              Search path <span style={{ opacity: 0.7 }}>(narrows which participants are listed above)</span>
            </div>
            <div className="field-row" style={{ marginBottom: 0 }}>
              <div style={{ minWidth: 280, flex: "0 0 auto" }}>
                <Combobox
                  options={pathOptions}
                  selectedLabel={selectedPathLabel}
                  onSelect={setPathKey}
                  placeholder="Search source or sink…"
                />
              </div>
              {/* CRR type applies to the Certificates table below regardless of
                  whether a path is selected -- strict match against the real
                  `crr_type` field, never a partial/fallback match (see
                  participant_detail's crr_type param in main.py). */}
              <div className="seg">
                {["", "OBLIGATION", "OPTION"].map((t) => (
                  <button key={t || "all"} className={crrType === t ? "active" : ""} onClick={() => setCrrType(t)}>
                    {t === "" ? "All types" : t === "OBLIGATION" ? "Obligation" : "Option"}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {!selected ? (
        <section className="panel">
          <div className="state-msg">Select a participant to see their activity.</div>
        </section>
      ) : !detail ? (
        <section className="panel">
          <div className={certError ? "state-msg error" : "state-msg"}>
            {certError ? `Couldn't load participant activity — ${certError}` : "Loading activity…"}
          </div>
        </section>
      ) : (
        <section className="panel">
          <div className="panel-head">
            <h2 style={{ fontSize: 17 }}>{selected}</h2>
            <span className="panel-note">{periodLabel}{selectedPair ? ` · ${pairLabel(selectedPair)}` : ""}</span>
          </div>
          <div className="kpis" style={{ marginBottom: 16 }}>
            <div className="kpi">
              <div className="kpi-value mono num" style={{ fontSize: 22 }}>
                {Math.round(detail.summary.total_awarded_mw).toLocaleString()}
              </div>
              <div className="kpi-label">
                Net MW
                <InfoTip>
                  Sum of this participant's awarded MW across the certificates matching the selected
                  auction period and path — signed, so a BUY award adds and a SELL award subtracts.
                </InfoTip>
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-value mono num" style={{ fontSize: 22 }}>
                ${Math.round(detail.summary.total_notional).toLocaleString()}
              </div>
              <div className="kpi-label">
                Notional value
                <InfoTip>
                  Sum of (awarded MW × auction clearing price in $/MWh) across the certificates matching
                  the selected auction period and path — a signed sizing figure for comparing position
                  size, not a fully time-scaled total settlement amount.
                </InfoTip>
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-value mono num" style={{ fontSize: 22 }}>{detail.pairs.length}</div>
              <div className="kpi-label">
                Distinct paths
                <InfoTip>Number of unique source → sink paths represented in this participant's certificates matching the selected filters.</InfoTip>
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-value mono num" style={{ fontSize: 22 }}>{detail.summary.auction_count}</div>
              <div className="kpi-label">
                Certificates
                <InfoTip>Count of CRR award records (certificates) this participant holds matching the selected auction period and path.</InfoTip>
              </div>
            </div>
          </div>
        </section>
      )}

      {selected && detail && (
        <section className="panel">
          <div className="panel-head">
            <h2>Certificates</h2>
          </div>
          <CertificatesTable
            certs={certs}
            loading={certLoading}
            error={certError}
            page={certPage}
            onPrev={() => setCertPage((p) => Math.max(1, p - 1))}
            onNext={() => setCertPage((p) => (certs && p < certs.total_pages ? p + 1 : p))}
          />
        </section>
      )}

      {/* Independent of the participant/path/type filters above -- item 6's
          "analyze settlement value across participants, not only the
          currently selected participant" -- so it renders as soon as the
          page's own data is ready, not gated on a specific participant
          being selected in the Certificates section above. */}
      <SettlementLeaderboard allParticipants={allParticipants} allPairs={allPairs} />
    </>
  );
}
