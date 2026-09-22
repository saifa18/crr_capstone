import React, { useEffect, useState } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import { api } from "./api.js";
import Overview from "./pages/Overview.jsx";
import Explorer from "./pages/Explorer.jsx";
import Participants from "./pages/Participants.jsx";
import Signals from "./pages/Signals.jsx";
import BindingConstraints from "./pages/BindingConstraints.jsx";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/explorer", label: "Source / sink explorer" },
  { to: "/participants", label: "Participants" },
  { to: "/signals", label: "Path settlements" },
  { to: "/constraints", label: "Binding constraints" },
];

export default function App() {
  const [meta, setMeta] = useState(null);
  // Connectivity (the sidebar dot) is driven by /health, not /api/meta --
  // /health never touches the dataset or ERCOT, so it answers exactly one
  // question ("is this FastAPI process alive") without an unrelated data-
  // loading or upstream-ERCOT problem ever getting mislabeled as "backend
  // unreachable." /api/meta is still fetched for the data-source label
  // text, but a failure there no longer flips the dot to red on its own.
  const [healthy, setHealthy] = useState(null); // null = checking, true/false once known

  useEffect(() => {
    api.health().then(() => setHealthy(true)).catch(() => setHealthy(false));
    api.meta().then(setMeta).catch(() => {});
  }, []);

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <div className="brand-mark mono">CRR</div>
          <div className="brand-sub">Grid congestion console</div>
        </div>
        <nav className="rail-nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          {healthy === false ? (
            <>
              <span className="dot red" />
              <span className="mono">backend unreachable</span>
            </>
          ) : healthy === true && meta ? (
            <>
              <span className="dot" />
              <span className="mono">{meta.data_source}</span>
            </>
          ) : healthy === true ? (
            <>
              <span className="dot" />
              <span className="mono">backend reachable</span>
            </>
          ) : (
            <>
              <span className="dot amber" />
              <span className="mono">connecting…</span>
            </>
          )}
        </div>
      </aside>

      <main className="content">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/explorer" element={<Explorer />} />
          <Route path="/participants" element={<Participants />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/constraints" element={<BindingConstraints />} />
        </Routes>
      </main>
    </div>
  );
}
