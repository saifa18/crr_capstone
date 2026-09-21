import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";

const TIER_COLOR = { High: "var(--green)", Medium: "var(--amber)", Low: "var(--dim-2)" };

export default function Overview() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState(null);
  const [hotPaths, setHotPaths] = useState(null);
  const [weather, setWeather] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.dashboard(), api.hotPaths(5), api.weather()])
      .then(([d, hp, w]) => {
        setDashboard(d);
        setHotPaths(hp);
        setWeather(w);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="state-msg error">Couldn't reach the backend — {error}</div>;
  if (!dashboard) return <div className="state-msg">Loading dashboard…</div>;

  const tierTotal = Object.values(dashboard.tier_distribution).reduce((a, b) => a + b, 0) || 1;
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
            {dashboard.data_source === "ercot_mis_real"
              ? "Real ERCOT auction data"
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
          <div className="kpi-label">tracked corridors</div>
        </div>
        <div className="kpi">
          <div className="kpi-value mono">{dashboard.latest_auction_month}</div>
          <div className="kpi-label">latest auction month</div>
        </div>
      </section>

      <section className="grid-2">
        <div className="panel" style={{ marginBottom: 0 }}>
          <div className="panel-head">
            <h2>Hot paths</h2>
          </div>
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
        </div>

        <div className="panel" style={{ marginBottom: 0 }}>
          <div className="panel-head">
            <h2>Opportunity tiers</h2>
          </div>
          <div className="tier-bars">
            {["High", "Medium", "Low"].map((tier) => (
              <div className="tier-row" key={tier}>
                <span className="tier-label">{tier}</span>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{
                      width: `${(100 * dashboard.tier_distribution[tier]) / tierTotal}%`,
                      background: TIER_COLOR[tier],
                    }}
                  />
                </div>
                <span className="tier-count mono">{dashboard.tier_distribution[tier]}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Top participants by notional</h2>
        </div>
        <table>
          <thead>
            <tr>
              <th>Participant</th>
              <th className="num-col">Net MW</th>
              <th className="num-col">Notional ($)</th>
              <th className="num-col">Distinct pairs</th>
              <th className="num-col">Certificates</th>
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
                <td className="num-col num">{Math.round(p.total_notional).toLocaleString()}</td>
                <td className="num-col num">{p.distinct_pairs}</td>
                <td className="num-col num">{p.auction_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {weather && (
        <section className="panel" style={{ padding: "14px 20px 16px" }}>
          <div className="panel-head" style={{ marginBottom: 11 }}>
            <h2 style={{ fontSize: 13, color: "var(--dim)" }}>Weather context by ERCOT zone</h2>
            <span className="panel-note">Context only — not a scoring input</span>
          </div>
          <div className="weather-row">
            {weather.map((w) => (
              <div className="weather-tile" key={w.zone}>
                <div className="weather-zone">{w.zone}</div>
                {w.error ? (
                  <div className="weather-temp" style={{ color: "var(--red)", fontSize: 12 }}>
                    unavailable
                  </div>
                ) : (
                  <>
                    <div className="weather-temp mono num">{Math.round(w.temperature_f)}°F</div>
                    <div className="weather-wind mono">wind {Math.round(w.wind_mph)} mph</div>
                  </>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
