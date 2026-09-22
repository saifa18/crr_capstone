import React, { useEffect, useRef, useState } from "react";

/**
 * A searchable combobox: a text input that reveals a filterable dropdown of
 * `options` ({key, label}) on focus, and calls onSelect(key) when one is
 * chosen. `selectedLabel` is shown in the input when it isn't focused.
 */
export function Combobox({ options, selectedLabel, onSelect, placeholder }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const q = query.trim().toLowerCase();
  const filtered = q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;

  return (
    <div className="combobox" ref={rootRef}>
      <input
        type="text"
        placeholder={placeholder}
        value={open ? query : selectedLabel || ""}
        onFocus={() => { setOpen(true); setQuery(""); }}
        onChange={(e) => setQuery(e.target.value)}
      />
      {open && (
        <div className="combobox-list">
          {filtered.length === 0 ? (
            <div className="combobox-empty">No matches.</div>
          ) : (
            filtered.slice(0, 200).map((o) => (
              <div
                key={o.key}
                className="combobox-option"
                onClick={() => { onSelect(o.key); setOpen(false); setQuery(""); }}
              >
                {o.label}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
