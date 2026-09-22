import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { api } from "../api.js";

const TOU_OPTIONS = [
  ["", "All"],
  ["PEAK_WD", "Peak weekday"],
  ["PEAK_WE", "Peak weekend"],
  ["OFF_PEAK", "Off-peak"],
];

const MAX_COMPARE = 3;
const COMPARE_COLORS = ["#54bedd", "#b98bd9", "#e0708f"];

function pairKey(p) { return `${p.source}__${p.sink}`; }
function pairLabel(p) { return `${p.source_name} → ${p.sink_name}`; }

function mergeSingle(obligation, option) {
  const byMonth = new Map();
  (obligation || []).forEach((r) => {
    byMonth.set(r.auction_month, { auction_month: r.auction_month, obligation: r.avg_clearing_price });
  });
  (option || []).forEach((r) => {
    const row = byMonth.get(r.auction_month) || { auction_month: r.auction_month };
    row.option = r.avg_clearing_price;
    byMonth.set(r.auction_month, row);
  });
  return Array.from(byMonth.values()).sort((a, b) => a.auction_month.localeCompare(b.auction_month));
}

function mergeCompare(seriesByKey) {
  const byMonth = new Map();
  Object.entries(seriesByKey).forEach(([key, series]) => {
    (series || []).forEach((r) => {
      const row = byMonth.get(r.auction_month) || { auction_month: r.auction_month };
      row[key] = r.avg_clearing_price;
      byMonth.set(r.auction_month, row);
    });
  });
  return Array.from(byMonth.values()).sort((a, b) => a.auction_month.localeCompare(b.auction_month));
}

function downloadCSV(rows, columns, filename) {
  const header = columns.map((c) => c.label).join(",");
  const lines = rows.map((r) => columns.map((c) => (r[c.key] ?? "")).join(","));
  const csv = [header, ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function Explorer() {
  const [searchParams] = useSearchParams();
  const [pairs, setPairs] = useState([]);
  const [selectedKeys, setSelectedKeys] = useState([]);
  const [tou, setTou] = useState("");
  const [crrType, setCrrType] = useState("OBLIGATION");
  const [chartData, setChartData] = useState(null);
  const [participants, setParticipants] = useState(null);
  const [error, setError] = useState(null);
  const initializedFromUrl = React.useRef(false);

  useEffect(() => {
    api.pairs()
      .then((p) => {
        setPairs(p);
        if (!initializedFromUrl.current) {
          initializedFromUrl.current = true;
          const urlSource = searchParams.get("source");
          const urlSink = searchParams.get("sink");
          const urlKey = urlSource && urlSink ? `${urlSource}__${urlSink}` : null;
          const match = urlKey && p.find((pair) => pairKey(pair) === urlKey);
          if (match) setSelectedKeys([urlKey]);
          else if (p.length) setSelectedKeys([pairKey(p[0])]);
        }
      })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedPairs = useMemo(
    () => selectedKeys.map((k) => pairs.find((p) => pairKey(p) === k)).filter(Boolean),
    [selectedKeys, pairs]
  );
  const compareMode = selectedPairs.length > 1;

  useEffect(() => {
    if (selectedPairs.length === 0) return;
    setChartData(null);
    setParticipants(null);

    if (!compareMode) {
      const { source, sink } = selectedPairs[0];
      Promise.all([
        api.pairSeries(source, sink, { crr_type: "OBLIGATION", time_of_use: tou || undefined }).catch(() => null),
        api.pairSeries(source, sink, { crr_type: "OPTION", time_of_use: tou || undefined }).catch(() => null),
        api.pairParticipants(source, sink).catch(() => null),
      ]).then(([obl, opt, parts]) => {
        setChartData(mergeSingle(obl?.series, opt?.series));
        setParticipants(parts?.participants || []);
      });
    } else {
      Promise.all(
        selectedPairs.map((p) =>
          api.pairSeries(p.source, p.sink, { crr_type: crrType, time_of_use: tou || undefined }).catch(() => null)
        )
      ).then((results) => {
        const seriesByKey = {};
        selectedPairs.forEach((p, i) => { seriesByKey[pairKey(p)] = results[i]?.series; });
        setChartData(mergeCompare(seriesByKey));
      });
    }
  }, [selectedPairs, tou, crrType, compareMode]);

  const addPair = (key) => {
    if (!key || selectedKeys.includes(key) || selectedKeys.length >= MAX_COMPARE) return;
    setSelectedKeys([...selectedKeys, key]);
  };
  const removePair = (key) => setSelectedKeys(selectedKeys.filter((k) => k !== key));

  const handleDownload = () => {
    if (!chartData || chartData.length === 0) return;
    if (!compareMode) {
      downloadCSV(
        chartData,
        [
          { key: "auction_month", label: "auction_month" },
          { key: "obligation", label: "obligation_price" },
          { key: "option", label: "option_price" },
        ],
        `${selectedPairs[0].source}_${selectedPairs[0].sink}_series.csv`
      );
    } else {
      const columns = [
        { key: "auction_month", label: "auction_month" },
        ...selectedPairs.map((p) => ({ key: pairKey(p), label: pairKey(p) })),
      ];
      downloadCSV(chartData, columns, "path_comparison.csv");
    }
  };

  if (error) return <div className="state-msg error">{error}</div>;
  if (pairs.length === 0) return <div className="state-msg">Loading paths…</div>;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Source / sink explorer</h1>
          <p className="subline">
            <span className="dot" />
            Compare historical CRR auction prices for source → sink paths — track up to {MAX_COMPARE} at once
          </p>
        </div>
      </header>

      <div className="field-row">
        <select value="" onChange={(e) => addPair(e.target.value)} disabled={selectedKeys.length >= MAX_COMPARE}>
          <option value="">
            {selectedKeys.length >= MAX_COMPARE ? `Max ${MAX_COMPARE} paths` : "+ Add path…"}
          </option>
          {pairs
            .filter((p) => !selectedKeys.includes(pairKey(p)))
            .map((p) => (
              <option key={pairKey(p)} value={pairKey(p)}>{pairLabel(p)}</option>
            ))}
        </select>
        <div className="seg">
          {TOU_OPTIONS.map(([val, label]) => (
            <button key={val} className={tou === val ? "active" : ""} onClick={() => setTou(val)}>
              {label}
            </button>
          ))}
        </div>
        {compareMode && (
          <div className="seg">
            {["OBLIGATION", "OPTION"].map((t) => (
              <button key={t} className={crrType === t ? "active" : ""} onClick={() => setCrrType(t)}>
                {t === "OBLIGATION" ? "Obligation" : "Option"}
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedPairs.length > 0 && (
        <div className="field-row" style={{ marginTop: -8 }}>
          {selectedPairs.map((p, i) => (
            <span key={pairKey(p)} className="pill" style={{ display: "flex", alignItems: "center", gap: 7 }}>
              {compareMode && (
                <span className="legend-swatch" style={{ background: COMPARE_COLORS[i], marginRight: 0 }} />
              )}
              {pairLabel(p)}
              {selectedPairs.length > 1 && (
                <button
                  onClick={() => removePair(pairKey(p))}
                  aria-label={`Remove ${pairLabel(p)}`}
                  style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer", fontSize: 13, padding: 0 }}
                >
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
      )}

      {selectedPairs.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <h2>{compareMode ? "Path comparison" : pairLabel(selectedPairs[0])}</h2>
            <span className="legend-row">
              {!compareMode ? (
                <>
                  <span><span className="legend-swatch" style={{ background: "var(--green)" }} />Obligation</span>
                  <span><span className="legend-swatch" style={{ background: "var(--amber)" }} />Option</span>
                </>
              ) : (
                <span style={{ color: "var(--dim)" }}>{crrType === "OBLIGATION" ? "Obligation" : "Option"} price, per path</span>
              )}
              <button
                onClick={handleDownload}
                disabled={!chartData || chartData.length === 0}
                style={{ background: "none", border: "1px solid var(--line)", color: "var(--dim)", padding: "4px 10px", fontSize: 11.5, cursor: "pointer", borderRadius: 3 }}
              >
                Download CSV
              </button>
            </span>
          </div>

          {!chartData ? (
            <div className="state-msg">Loading series…</div>
          ) : chartData.length === 0 ? (
            <div className="state-msg">No cleared records for this filter combination.</div>
          ) : (
            <div style={{ width: "100%", height: 300 }}>
              <ResponsiveContainer>
                <LineChart data={chartData} margin={{ top: 6, right: 12, left: -6, bottom: 0 }}>
                  <CartesianGrid stroke="#171f29" vertical={false} />
                  <XAxis dataKey="auction_month" tick={{ fill: "#64768a", fontSize: 11 }} axisLine={{ stroke: "#212b37" }} tickLine={false} />
                  <YAxis tick={{ fill: "#64768a", fontSize: 11 }} axisLine={{ stroke: "#212b37" }} tickLine={false} width={54} />
                  <Tooltip
                    contentStyle={{ background: "#10161e", border: "1px solid #212b37", fontSize: 12 }}
                    labelStyle={{ color: "#dee6ec" }}
                  />
                  {!compareMode ? (
                    <>
                      <Line type="monotone" dataKey="obligation" name="Obligation" stroke="#3fbf8f" strokeWidth={2} dot={false} connectNulls />
                      <Line type="monotone" dataKey="option" name="Option" stroke="#de9a4e" strokeWidth={2} dot={false} connectNulls />
                    </>
                  ) : (
                    selectedPairs.map((p, i) => (
                      <Line
                        key={pairKey(p)}
                        type="monotone"
                        dataKey={pairKey(p)}
                        name={pairLabel(p)}
                        stroke={COMPARE_COLORS[i]}
                        strokeWidth={2}
                        dot={false}
                        connectNulls
                      />
                    ))
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>
      )}

      {!compareMode && participants && (
        <section className="panel">
          <div className="panel-head">
            <h2>Participants active on this path</h2>
          </div>
          {participants.length === 0 ? (
            <div className="state-msg">No participants found for this pair.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Participant</th>
                  <th className="num-col">Net MW</th>
                  <th className="num-col">Notional ($)</th>
                  <th className="num-col">Certificates</th>
                </tr>
              </thead>
              <tbody>
                {participants.slice(0, 15).map((p) => (
                  <tr key={p.participant}>
                    <td>{p.participant}</td>
                    <td className="num-col mono num">{Math.round(p.total_awarded_mw).toLocaleString()}</td>
                    <td className="num-col mono num">{Math.round(p.total_notional).toLocaleString()}</td>
                    <td className="num-col mono num">{p.auction_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </>
  );
}
