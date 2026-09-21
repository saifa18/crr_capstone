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
  { to: "/signals", label: "Opportunity signals" },
  { to: "/constraints", label: "Binding constraints" },
];

export default function App() {
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState(null);

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setMetaError(e.message));
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
          {metaError ? (
            <>
              <span className="dot red" />
              <span className="mono">backend unreachable</span>
            </>
          ) : meta ? (
            <>
              <span className="dot" />
              <span className="mono">{meta.data_source}</span>
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
