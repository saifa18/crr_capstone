import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

const TIER_FILTERS = ["All", "High", "Medium", "Low"];
const FACTOR_COLOR = { value: "var(--cyan)", trend: "var(--cyan)", consistency: "var(--cyan)", liquidity: "var(--cyan)" };

export default function Signals() {
  const [scores, setScores] = useState(null);
  const [tier, setTier] = useState("All");
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    api.opportunityScores().then(setScores).catch((e) => setError(e.message));
  }, []);

  const filtered = useMemo(() => {
    if (!scores) return [];
    const q = query.trim().toLowerCase();
    return scores.filter((s) => {
      if (tier !== "All" && s.tier !== tier) return false;
      if (!q) return true;
      return (
        s.source_name.toLowerCase().includes(q) ||
        s.sink_name.toLowerCase().includes(q) ||
        s.source.toLowerCase().includes(q) ||
        s.sink.toLowerCase().includes(q)
      );
    });
  }, [scores, tier, query]);

  if (error) return <div className="state-msg error">Couldn't reach the backend — {error}</div>;
  if (!scores) return <div className="state-msg">Loading opportunity signals…</div>;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Opportunity signals</h1>
          <p className="subline">
            <span className="dot" />
            {scores.length} scored corridors — explainable Low / Medium / High signal, not a price forecast
          </p>
        </div>
      </header>

      <div className="field-row">
        <div className="seg">
          {TIER_FILTERS.map((t) => (
            <button key={t} className={tier === t ? "active" : ""} onClick={() => setTier(t)}>
              {t}
            </button>
          ))}
        </div>
        <input
          type="search"
          placeholder="Search hub or zone…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 220 }}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="state-msg">No corridors match this filter.</div>
      ) : (
        filtered.map((s) => (
          <div className="score-card" key={`${s.source}-${s.sink}`}>
            <div className="score-head">
              <div>
                <div className="score-path">
                  {s.source_name} → {s.sink_name}
                </div>
                <span className={`tier-chip ${s.tier.toLowerCase()}`}>{s.tier.toUpperCase()}</span>
              </div>
              <div className="score-num mono num">{s.score}</div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px 32px" }}>
              <div>
                {Object.entries(s.factors).map(([name, f]) => (
                  <div className="factor-row" key={name}>
                    <span className="factor-label">{name}</span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${f.score}%`, background: FACTOR_COLOR[name] || "var(--cyan)" }} />
                    </div>
                    <span className="factor-val mono num">{Math.round(f.score)}</span>
                  </div>
                ))}
              </div>
              <div>
                {s.explanation.map((line, i) => (
                  <p className="score-explain" key={i}>
                    {line}
                  </p>
                ))}
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}
