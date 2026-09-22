import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const MARGIN = 8; // gap between the icon and the bubble
const BUBBLE_WIDTH = 260; // must match .info-tip-bubble's width in styles.css

// Renders the bubble in a portal to document.body, positioned in viewport
// ("fixed") coordinates computed from the icon's own bounding rect.
//
// Why a portal: the old version rendered the bubble as a CSS-absolutely-
// positioned descendant of the icon, shown via `:hover`. That silently
// broke wherever the icon sits inside an ancestor with `overflow-x: auto`
// (e.g. Binding Constraints' scrollable "All constraints" table wrapper) --
// per the CSS spec, setting overflow-x to anything but `visible` forces
// overflow-y to `auto` too, so the bubble's upward `bottom: 140%` position
// (needed for a header near the top of that wrapper) landed entirely
// above the wrapper's own top edge and was clipped out of view -- not a
// z-index problem, an overflow-clipping one, confirmed by measuring the
// bubble's rect against its scrolling ancestor's rect live. A portal
// escapes that ancestor's DOM subtree entirely, so no ancestor's overflow
// can ever clip it, on this page or any future one.
export function InfoTip({ children }) {
  const [pos, setPos] = useState(null); // null = closed
  const iconRef = useRef(null);

  const show = () => {
    const el = iconRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;

    // Prefer opening upward (this app's original convention); flip to
    // downward when there isn't reasonable room above the icon's current
    // viewport position, so a header tooltip near the top of the page/a
    // scrolled table never has nowhere to go.
    const openDown = rect.top < 140;
    const top = openDown ? rect.bottom + MARGIN : rect.top - MARGIN;

    // Centered on the icon by default, clamped inward so the fixed-width
    // bubble never extends past the viewport's left/right edge.
    const halfWidth = BUBBLE_WIDTH / 2;
    const left = Math.min(Math.max(rect.left + rect.width / 2, halfWidth + MARGIN), vw - halfWidth - MARGIN);

    setPos({ top, left, openDown });
  };
  const hide = () => setPos(null);

  useEffect(() => {
    if (!pos) return;
    // A brief hover tooltip, not a persistent popover -- closing on
    // scroll/resize is simpler and more robust than re-measuring the
    // icon's position on every scroll frame while it's open.
    const close = () => setPos(null);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [pos]);

  return (
    <span
      ref={iconRef}
      className="info-tip"
      tabIndex={0}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      i
      {pos &&
        createPortal(
          <span
            className="info-tip-bubble"
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              transform: pos.openDown ? "translate(-50%, 0)" : "translate(-50%, -100%)",
            }}
          >
            {children}
          </span>,
          document.body
        )}
    </span>
  );
}
