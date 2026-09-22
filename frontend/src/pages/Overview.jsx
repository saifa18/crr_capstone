import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { InfoTip } from "../InfoTip.jsx";

export default function Overview() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState(null);
  const [hotPaths, setHotPaths] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.dashboard(), api.hotPaths(5)])
      .then(([d, hp]) => {
        setDashboard(d);
        setHotPaths(hp);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="state-msg error">{error}</div>;
  if (!dashboard) return <div className="state-msg">Loading dashboard…</div>;

  const latestMwPrior = dashboard.monthly_mw_trend.length >= 2
    ? dashboard.monthly_mw_trend[dashboard.monthly_mw_trend.length - 2].total_mw
    : null;
  const mwDelta = latestMwPrior != null
    ? dashboard.latest_month_mw_awarded - latestMwPrior
    : null;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Overview</h1>
          <p className={`subline ${dashboard.data_source_warning ? "warn" : ""}`}>
            <span className="dot" />
            Market-wide CRR auction activity, major paths, and active participants —{" "}
            {dashboard.data_source === "ercot_mis_real"
              ? "real ERCOT auction data"
              : dashboard.data_source}
            {dashboard.data_source_warning ? ` — ${dashboard.data_source_warning}` : ""}
          </p>
        </div>
        <div className="head-right">
          <span className="pill mono">
            as of <b>{dashboard.latest_auction_month}</b>
          </span>
        </div>
      </header>

      <section className="kpis">
        <div className="kpi hero">
          <div className="kpi-value mono num">
            {Math.round(dashboard.latest_month_mw_awarded).toLocaleString()}
          </div>
          <div className="kpi-label">MW awarded, latest month</div>
          {mwDelta != null && (
            <div className={`kpi-delta mono ${mwDelta >= 0 ? "up" : "down"}`}>
              {mwDelta >= 0 ? "▲" : "▼"} {Math.abs(Math.round(mwDelta)).toLocaleString()} vs prior month
            </div>
          )}
        </div>
        <div className="kpi">
          <div className="kpi-value mono num">{dashboard.active_participant_count.toLocaleString()}</div>
          <div className="kpi-label">active participants</div>
        </div>
        <div className="kpi">
          <div className="kpi-value mono num">{dashboard.tracked_pair_count}</div>
          <div className="kpi-label">tracked paths</div>
        </div>
        <div className="kpi">
          <div className="kpi-value mono">{dashboard.latest_auction_month}</div>
          <div className="kpi-label">latest auction month</div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Hot paths</h2>
        </div>
        <p className="panel-note" style={{ marginBottom: 10 }}>
          Ranked by total notional — gross MW-weighted auction activity across all tracked auction
          months (not by participant count or congestion persistence, which are noted per path below).
        </p>
        <ul className="hotpaths">
          {hotPaths.map((p) => (
            <li key={`${p.source}-${p.sink}`}>
              <div className="hp-main">
                <div className="hp-path">
                  {p.source_name} → {p.sink_name}
                </div>
                <div className="hp-reason">{p.reason}</div>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Top participants by notional</h2>
        </div>
        <table>
          <thead>
            <tr>
              <th>Participant</th>
              <th className="num-col">
                Net MW
                <InfoTip>
                  Sum of this participant's awarded MW across every tracked-history certificate — signed,
                  so a BUY award adds and a SELL award subtracts. Net position across all tracked auction
                  months, not just the latest one.
                </InfoTip>
              </th>
              <th className="num-col">
                Notional ($)
                <InfoTip>
                  Sum of (awarded MW × auction clearing price in $/MWh) across this participant's
                  certificates — a signed sizing figure for comparing relative position size, not a
                  fully time-scaled total settlement amount.
                </InfoTip>
              </th>
              <th className="num-col">
                Distinct paths
                <InfoTip>Number of unique source → sink paths represented in this participant's certificates.</InfoTip>
              </th>
              <th className="num-col">
                Certificates
                <InfoTip>Count of CRR award records (certificates) this participant holds across the tracked auction months.</InfoTip>
              </th>
            </tr>
          </thead>
          <tbody className="mono">
            {dashboard.top_participants.map((p) => (
              <tr
                key={p.participant}
                className="clickable"
                onClick={() => navigate(`/participants?focus=${encodeURIComponent(p.participant)}`)}
              >
                <td className="mono" style={{ fontFamily: "Archivo, sans-serif" }}>
                  {p.participant}
                </td>
                <td className="num-col num">{Math.round(p.total_awarded_mw).toLocaleString()}</td>
                <td className="num-col num">${Math.round(p.total_notional).toLocaleString()}</td>
                <td className="num-col num">{p.distinct_pairs}</td>
                <td className="num-col num">{p.auction_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
