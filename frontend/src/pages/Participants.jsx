import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";

export default function Participants() {
  const [searchParams] = useSearchParams();
  const [list, setList] = useState(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const appliedFocus = React.useRef(false);

  useEffect(() => {
    api.participants().then(setList).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (appliedFocus.current || !list) return;
    const focus = searchParams.get("focus");
    if (focus) {
      appliedFocus.current = true;
      setSelected(focus);
    } else if (list.length) {
      setSelected(list[0].participant);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list]);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    api.participantDetail(selected).then(setDetail).catch((e) => setError(e.message));
  }, [selected]);

  const filtered = useMemo(() => {
    if (!list) return [];
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter((p) => p.participant.toLowerCase().includes(q));
  }, [list, query]);

  if (error) return <div className="state-msg error">Couldn't reach the backend — {error}</div>;
  if (!list) return <div className="state-msg">Loading participants…</div>;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Participants</h1>
          <p className="subline">
            <span className="dot" />
            {list.length} participants active on tracked corridors
          </p>
        </div>
      </header>

      <div className="participants-layout">
        <section className="panel participants-list-panel">
          <input
            type="search"
            placeholder="Search participant name…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: "100%", marginBottom: 10 }}
          />
          <div className="participants-scroll">
            {filtered.length === 0 ? (
              <div className="state-msg">No matches for "{query}".</div>
            ) : (
              filtered.map((p) => (
                <div
                  key={p.participant}
                  className={`participant-row${p.participant === selected ? " participant-row-selected" : ""}`}
                  onClick={() => setSelected(p.participant)}
                >
                  <div className="participant-row-name">{p.participant}</div>
                  <div className="participant-row-stats mono">
                    {Math.round(p.total_notional).toLocaleString()} notional · {p.distinct_pairs} pair{p.distinct_pairs === 1 ? "" : "s"}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="panel participants-detail-panel">
          {!selected ? (
            <div className="state-msg">Select a participant to see their activity.</div>
          ) : !detail ? (
            <div className="state-msg">Loading activity…</div>
          ) : (
            <>
              <div className="panel-head">
                <h2>{selected}</h2>
              </div>
              <div className="kpis" style={{ marginBottom: 16 }}>
                <div className="kpi">
                  <div className="kpi-value mono num" style={{ fontSize: 22 }}>
                    {Math.round(detail.summary.total_awarded_mw).toLocaleString()}
                  </div>
                  <div className="kpi-label">net MW</div>
                </div>
                <div className="kpi">
                  <div className="kpi-value mono num" style={{ fontSize: 22 }}>
                    {Math.round(detail.summary.total_notional).toLocaleString()}
                  </div>
                  <div className="kpi-label">notional ($)</div>
                </div>
                <div className="kpi">
                  <div className="kpi-value mono num" style={{ fontSize: 22 }}>{detail.pairs.length}</div>
                  <div className="kpi-label">distinct corridors</div>
                </div>
                <div className="kpi">
                  <div className="kpi-value mono num" style={{ fontSize: 22 }}>{detail.summary.auction_count}</div>
                  <div className="kpi-label">certificates</div>
                </div>
              </div>

              <p className="panel-note" style={{ marginBottom: 10 }}>Showing the 25 most recent certificates.</p>
              <div className="participants-activity-scroll">
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
                    {detail.recent_activity.map((r, i) => (
                      <tr key={i}>
                        <td>{r.auction_month}</td>
                        <td style={{ fontFamily: "Archivo, sans-serif" }}>
                          {r.source} → {r.sink}
                        </td>
                        <td>{r.crr_type}</td>
                        <td className="num-col num">{r.awarded_mw}</td>
                        <td className="num-col num">{r.clearing_price}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
