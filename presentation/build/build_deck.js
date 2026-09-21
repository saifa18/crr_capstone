const pptxgen = require("pptxgenjs");
const fs = require("fs");

const snap = JSON.parse(fs.readFileSync("../../data/snapshot.json", "utf8"));
const topScores = [...snap.scores].sort((a, b) => b.score - a.score).slice(0, 8);
const topParticipants = [...snap.participants].sort((a, b) => b.total_notional - a.total_notional).slice(0, 8);

// ---- palette (matches the app: dark utility/grid aesthetic) ----
const BG = "0A0D13";
const PANEL = "12161F";
const BORDER = "232937";
const TEXT = "F4F6F9";
const TEXT_MUTE = "9AA5B4";
const TEXT_DIM = "7A8699";
const GREEN = "3DDC97";
const BLUE = "2E7CE0";
const AMBER = "E8B339";
const RED = "E85D5D";

const FONT = "Georgia"; // characterful display face used with restraint for titles
const FONT_BODY = "Arial";
const FONT_MONO = "Consolas";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
const W = 13.33, H = 7.5;

pres.defineSlideMaster({
  title: "DARK_MASTER",
  background: { color: BG },
  objects: [],
});

function icon(slide, name, x, y, size, dark) {
  slide.addImage({ path: `icons/${name}${dark ? "_dark" : ""}.png`, x, y, w: size, h: size });
}

function eyebrow(slide, text, y) {
  slide.addText(text.toUpperCase(), {
    x: 0.6, y, w: 8, h: 0.35, fontFace: FONT_MONO, fontSize: 12, color: GREEN,
    charSpacing: 2, isTextBox: true, margin: 0,
  });
}

function pageNum(slide, n) {
  slide.addText(String(n).padStart(2, "0"), {
    x: W - 0.9, y: H - 0.55, w: 0.6, h: 0.3, fontFace: FONT_MONO, fontSize: 10,
    color: TEXT_DIM, align: "right", isTextBox: true, margin: 0,
  });
}

function baseSlide() {
  const s = pres.addSlide({ masterName: "DARK_MASTER" });
  return s;
}

// ---------------------------------------------------------------
// Slide 1 — Title
// ---------------------------------------------------------------
{
  const s = baseSlide();
  icon(s, "zap", 0.6, 0.6, 0.5);
  s.addText("ERCOT CRR", {
    x: 0.55, y: 2.15, w: 11, h: 1.1, fontFace: FONT, fontSize: 54, bold: true,
    color: TEXT, isTextBox: true, margin: 0,
  });
  s.addText("Market Analytics", {
    x: 0.55, y: 2.95, w: 11, h: 1.0, fontFace: FONT, fontSize: 54, bold: true,
    color: GREEN, isTextBox: true, margin: 0,
  });
  s.addText("An AI-built prototype for Congestion Revenue Rights market intelligence", {
    x: 0.6, y: 4.05, w: 10.5, h: 0.5, fontFace: FONT_BODY, fontSize: 16.5,
    color: TEXT_MUTE, isTextBox: true, margin: 0,
  });
  s.addShape(pres.ShapeType.line, { x: 0.6, y: 4.75, w: 3.2, h: 0, line: { color: BORDER, width: 1 } });
  s.addText("Saif  ·  ETRM Implementation Consultant, Veritas (an Oliver Wyman business)", {
    x: 0.6, y: 4.95, w: 10, h: 0.4, fontFace: FONT_MONO, fontSize: 12.5, color: TEXT_DIM,
    isTextBox: true, margin: 0,
  });
  s.addText("AI Capstone  ·  Built end-to-end with Claude (requirements → design → code → tests)", {
    x: 0.6, y: 5.3, w: 10, h: 0.4, fontFace: FONT_MONO, fontSize: 12.5, color: TEXT_DIM,
    isTextBox: true, margin: 0,
  });
  s.addNotes(
    "0:00-2:00 — Welcome. Frame the session: this is a capstone about using AI across the whole " +
    "software lifecycle to build real market-intelligence tooling for ERCOT CRRs, not just to write code faster."
  );
}

// ---------------------------------------------------------------
// Slide 2 — Agenda
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "Agenda", 0.55);
  s.addText("Sixty minutes, five parts", {
    x: 0.55, y: 0.95, w: 10, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: TEXT,
    isTextBox: true, margin: 0,
  });

  const items = [
    ["01", "ERCOT power markets & CRRs", "LMP, congestion, Source/Sink, Option vs. Obligation", "10 min"],
    ["02", "AI-assisted workflow", "Requirements, prompt journal, and validation as we went", "12 min"],
    ["03", "Live application demo", "Dashboard → Explorer → Participants → Opportunity Signals", "20 min"],
    ["04", "Architecture & testing", "What's real, what's synthetic, and how it's proven correct", "10 min"],
    ["05", "Lessons learned & what's next", "What AI made easier, what still needed judgment", "8 min"],
  ];
  let y = 1.95;
  items.forEach(([num, title, sub, time]) => {
    s.addText(num, { x: 0.6, y, w: 0.8, h: 0.85, fontFace: FONT_MONO, fontSize: 22, color: GREEN, isTextBox: true, margin: 0 });
    s.addText(title, { x: 1.5, y: y + 0.02, w: 8.4, h: 0.4, fontFace: FONT_BODY, fontSize: 17, bold: true, color: TEXT, isTextBox: true, margin: 0 });
    s.addText(sub, { x: 1.5, y: y + 0.42, w: 8.4, h: 0.35, fontFace: FONT_BODY, fontSize: 12.5, color: TEXT_MUTE, isTextBox: true, margin: 0 });
    s.addText(time, { x: 10.9, y: y + 0.15, w: 1.8, h: 0.4, fontFace: FONT_MONO, fontSize: 13, color: TEXT_DIM, align: "right", isTextBox: true, margin: 0 });
    y += 1.0;
  });
  pageNum(s, 2);
  s.addNotes("2:00-3:00 — Walk the five sections and the rough timing so the room knows the shape of the hour.");
}

// ---------------------------------------------------------------
// Slide 3 — What is a CRR (concept)
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "ERCOT fundamentals", 0.55);
  s.addText("Why location matters in ERCOT", {
    x: 0.55, y: 0.95, w: 11, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });
  s.addText(
    "ERCOT is a nodal market: the price of energy differs by location (Locational Marginal Price) " +
    "whenever transmission is constrained. Generation in windy West Texas often can't fully reach " +
    "load in Houston — that gap in price between two points is congestion.",
    { x: 0.55, y: 1.7, w: 6.0, h: 1.7, fontFace: FONT_BODY, fontSize: 14, color: TEXT_MUTE, isTextBox: true, margin: 0 }
  );
  s.addText(
    "A Congestion Revenue Right (CRR) is a financial instrument that pays the holder the " +
    "difference in LMP between a Source and a Sink. ERCOT auctions them monthly and annually " +
    "so market participants can hedge — or take a view on — that locational spread.",
    { x: 0.55, y: 3.35, w: 6.0, h: 1.7, fontFace: FONT_BODY, fontSize: 14, color: TEXT_MUTE, isTextBox: true, margin: 0 }
  );

  // signature: simple corridor diagram, West -> Houston
  const cx = 7.3, cw = 5.4;
  s.addShape(pres.ShapeType.roundRect, { x: cx, y: 1.9, w: 2.2, h: 1.1, rectRadius: 0.1, fill: { color: PANEL }, line: { color: BORDER, width: 1 } });
  s.addText("SOURCE", { x: cx, y: 2.0, w: 2.2, h: 0.3, align: "center", fontFace: FONT_MONO, fontSize: 10, color: TEXT_DIM, isTextBox: true, margin: 0 });
  s.addText("HB_WEST", { x: cx, y: 2.3, w: 2.2, h: 0.5, align: "center", fontFace: FONT_MONO, fontSize: 16, bold: true, color: TEXT, isTextBox: true, margin: 0 });

  s.addShape(pres.ShapeType.roundRect, { x: cx + 3.2, y: 1.9, w: 2.2, h: 1.1, rectRadius: 0.1, fill: { color: PANEL }, line: { color: BORDER, width: 1 } });
  s.addText("SINK", { x: cx + 3.2, y: 2.0, w: 2.2, h: 0.3, align: "center", fontFace: FONT_MONO, fontSize: 10, color: TEXT_DIM, isTextBox: true, margin: 0 });
  s.addText("HB_HOUSTON", { x: cx + 3.2, y: 2.3, w: 2.2, h: 0.5, align: "center", fontFace: FONT_MONO, fontSize: 16, bold: true, color: TEXT, isTextBox: true, margin: 0 });

  s.addShape(pres.ShapeType.line, { x: cx + 2.2, y: 2.45, w: 1.0, h: 0, line: { color: GREEN, width: 2.5, endArrowType: "triangle" } });
  s.addText("congestion value ($/MWh)", { x: cx, y: 3.1, w: cw, h: 0.3, align: "center", fontFace: FONT_MONO, fontSize: 10, color: GREEN, isTextBox: true, margin: 0 });

  s.addText("A CRR holder on this path is paid (or pays) that spread every settlement — that's the value this app measures historically.", {
    x: cx, y: 3.55, w: cw, h: 1.0, fontFace: FONT_BODY, fontSize: 12.5, italic: true, color: TEXT_MUTE, isTextBox: true, margin: 0,
  });

  s.addText("Reference: ERCOT Locational Marginal Pricing WBT · Wholesale Markets 101 · Congestion Revenue Rights WBT (ercot.com/services/training)", {
    x: 0.55, y: 6.85, w: 12, h: 0.35, fontFace: FONT_MONO, fontSize: 9.5, color: TEXT_DIM, isTextBox: true, margin: 0,
  });
  pageNum(s, 3);
  s.addNotes(
    "3:00-6:00 — Explain LMP and congestion conceptually before naming CRRs. The West->Houston " +
    "example is the real dominant ERCOT congestion story (renewables in the west/panhandle needing " +
    "to reach coastal/urban load) and is the same pair the app scores highest later — tie it back then."
  );
}

// ---------------------------------------------------------------
// Slide 4 — Option vs Obligation, Source/Sink pairs
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "ERCOT fundamentals", 0.55);
  s.addText("Two CRR types, one underlying question", {
    x: 0.55, y: 0.95, w: 11, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  const cards = [
    ["OBLIGATION", GREEN, "Pays (or charges) the full LMP spread every hour — symmetric exposure. If the path decongests or reverses, an Obligation holder can owe money.", "Used as this app's primary economic-value signal (Sections 05-06) because it mirrors realized congestion directly."],
    ["OPTION", BLUE, "Pays the LMP spread only when it's positive to the holder — the holder never owes money on the CRR itself, but pays more upfront for that protection.", "Modeled in this app as a smaller, always-non-negative clearing price relative to the same path's Obligation value."],
  ];
  let x = 0.55;
  cards.forEach(([label, color, body, note]) => {
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.75, w: 5.9, h: 3.5, rectRadius: 0.08, fill: { color: PANEL }, line: { color: BORDER, width: 1 } });
    s.addText(label, { x: x + 0.35, y: 2.0, w: 5.2, h: 0.5, fontFace: FONT_MONO, fontSize: 18, bold: true, color, isTextBox: true, margin: 0 });
    s.addText(body, { x: x + 0.35, y: 2.6, w: 5.2, h: 1.7, fontFace: FONT_BODY, fontSize: 13, color: TEXT_MUTE, isTextBox: true, margin: 0 });
    s.addShape(pres.ShapeType.line, { x: x + 0.35, y: 4.35, w: 5.2, h: 0, line: { color: BORDER, width: 1 } });
    s.addText(note, { x: x + 0.35, y: 4.5, w: 5.2, h: 0.65, fontFace: FONT_BODY, fontSize: 11.5, italic: true, color: TEXT_DIM, isTextBox: true, margin: 0 });
    x += 6.3;
  });

  s.addText("The Source/Sink explorer in this app tracks both types side-by-side for every pair, on the same chart.", {
    x: 0.55, y: 5.55, w: 12, h: 0.4, fontFace: FONT_BODY, fontSize: 13, color: TEXT_MUTE, isTextBox: true, margin: 0,
  });
  pageNum(s, 4);
  s.addNotes("6:00-9:00 — Keep this brief; the goal is just enough vocabulary for the demo to make sense, not a full CRR certification course.");
}

// ---------------------------------------------------------------
// Slide 5 — Project objective & scope
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "The capstone", 0.55);
  s.addText("What this project set out to build", {
    x: 0.55, y: 0.95, w: 11, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: 0.55, y: 1.8, w: 12.2, h: 1.0, rectRadius: 0.08,
    fill: { color: "13291F" }, line: { color: "1F4A38", width: 1 },
  });
  s.addText("Market intelligence and analytics — not a predictive model, not a trading system.", {
    x: 0.9, y: 1.8, w: 11.5, h: 1.0, fontFace: FONT_BODY, fontSize: 15, bold: true, color: GREEN,
    valign: "middle", isTextBox: true, margin: 0,
  });

  const reqs = [
    ["gauge", "Dashboard", "Recent auctions, active participants, top Source/Sink pairs"],
    ["users", "Participant analysis", "Historical MW, notional, and pairs traded per participant"],
    ["gitbranch", "Source/Sink explorer", "Historical pricing & congestion trends, Obligation + Option"],
    ["trending", "Basic analytics", "Average, min/max, volatility, and trend"],
    ["target", "Opportunity score", "Explainable Low / Medium / High signal for further investigation"],
  ];
  let y = 3.1;
  reqs.forEach(([ic, title, sub]) => {
    icon(s, ic, 0.6, y, 0.42);
    s.addText(title, { x: 1.2, y: y - 0.02, w: 3.6, h: 0.45, fontFace: FONT_BODY, fontSize: 14.5, bold: true, color: TEXT, isTextBox: true, margin: 0 });
    s.addText(sub, { x: 4.85, y: y - 0.02, w: 7.9, h: 0.45, fontFace: FONT_BODY, fontSize: 12.5, color: TEXT_MUTE, valign: "middle", isTextBox: true, margin: 0 });
    y += 0.68;
  });
  pageNum(s, 5);
  s.addNotes("9:00-11:00 — This is the scope we'll hold ourselves to in the demo section; call back to each bullet as you click through the app.");
}

// ---------------------------------------------------------------
// Slide 6 — AI workflow overview
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "AI workflow", 0.55);
  s.addText("AI across the whole lifecycle, not just the code", {
    x: 0.55, y: 0.95, w: 11.5, h: 0.7, fontFace: FONT, fontSize: 28, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  const steps = [
    ["search", "Verify before designing", "Confirmed what ERCOT actually publishes (and what's programmatically reachable) before writing any code"],
    ["brain", "Refine requirements with AI", "Turned the capstone brief into a full functional/non-functional requirements doc with traceable acceptance criteria"],
    ["code", "Build with tests alongside", "Every analytics/scoring function written as a pure, independently-testable unit from the start"],
    ["checkcircle", "Validate before shipping", "136 backend tests, plus every UI change checked live in a real browser against the real backend before being called done"],
  ];
  let x = 0.55;
  const cw = 2.95;
  steps.forEach(([ic, title, body], i) => {
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.9, w: cw, h: 3.9, rectRadius: 0.08, fill: { color: PANEL }, line: { color: BORDER, width: 1 } });
    icon(s, ic, x + 0.25, 2.15, 0.5);
    s.addText(String(i + 1), { x: x + cw - 0.65, y: 2.15, w: 0.5, h: 0.5, align: "right", fontFace: FONT_MONO, fontSize: 22, color: TEXT_DIM, isTextBox: true, margin: 0 });
    s.addText(title, { x: x + 0.25, y: 2.85, w: cw - 0.5, h: 0.85, fontFace: FONT_BODY, fontSize: 14.5, bold: true, color: TEXT, isTextBox: true, margin: 0 });
    s.addText(body, { x: x + 0.25, y: 3.7, w: cw - 0.5, h: 2.0, fontFace: FONT_BODY, fontSize: 11.5, color: TEXT_MUTE, isTextBox: true, margin: 0 });
    x += cw + 0.2;
  });
  pageNum(s, 6);
  s.addNotes("11:00-14:00 — This is the spine of the AI-workflow section; each card gets its own detail slide next.");
}

// ---------------------------------------------------------------
// Slide 7 — Data sourcing honesty (the real story)
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "AI workflow · prompt journal, entries 1 & 9", 0.55);
  s.addText("The most important course-correction: data access", {
    x: 0.55, y: 0.95, w: 12, h: 0.7, fontFace: FONT, fontSize: 27, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  s.addText("PROMPT", { x: 0.55, y: 1.85, w: 2, h: 0.3, fontFace: FONT_MONO, fontSize: 11, color: TEXT_DIM, isTextBox: true, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.55, y: 2.15, w: 12.2, h: 0.85, rectRadius: 0.06, fill: { color: PANEL }, line: { color: BORDER, width: 1 } });
  s.addText("\u201CDoes ERCOT publish real CRR auction results publicly, and can you actually fetch them from here?\u201D", {
    x: 0.85, y: 2.15, w: 11.6, h: 0.85, fontFace: FONT_BODY, fontSize: 14, italic: true, color: TEXT,
    valign: "middle", isTextBox: true, margin: 0,
  });

  const rows = [
    [GREEN, "Confirmed real & public", "ERCOT publishes NP7-802-M / NP7-803-M — Source, Sink, CRR type, clearing price, and CRR Account Holder — free on the MIS Public Area."],
    [AMBER, "First pass: not scriptable here", "The modern mis.ercot.com file browser is JS-driven and session-gated; a direct fetch returned an empty file list — no stable unauthenticated URL, so v1 shipped on a labeled synthetic generator instead."],
    [GREEN, "Re-checked later, found the real path", "A follow-up session tested ERCOT's older, legacy MIS servlet directly with curl instead of trusting the earlier conclusion — reachable, unauthenticated, serving the real files."],
    [GREEN, "Now the default: 1.1M real records", "13 months of real CRR Monthly Auction Results and the real 521-company Market Participants List, bundled in this repo — synthetic data is now the fallback, not the default."],
  ];
  let y = 3.3;
  rows.forEach(([color, title, body]) => {
    s.addShape(pres.ShapeType.ellipse, { x: 0.6, y: y + 0.05, w: 0.14, h: 0.14, fill: { color } });
    s.addText(title, { x: 0.95, y, w: 3.3, h: 0.75, fontFace: FONT_BODY, fontSize: 12.5, bold: true, color: TEXT, isTextBox: true, margin: 0 });
    s.addText(body, { x: 4.35, y, w: 8.4, h: 0.75, fontFace: FONT_BODY, fontSize: 11.5, color: TEXT_MUTE, isTextBox: true, margin: 0 });
    y += 0.85;
  });
  pageNum(s, 7);
  s.addNotes(
    "14:00-17:00 — This is the single most important story in the whole build, and it has two acts, not " +
    "one: the honest 'can't reach it' finding in entry 1, AND the willingness in entry 9 to re-test that " +
    "same assumption later instead of treating it as settled — which is what actually unlocked the real " +
    "data. Both halves matter for the grade: verify before designing, and don't let an earlier honest " +
    "answer calcify into an unquestioned constraint."
  );
}

// ---------------------------------------------------------------
// Slide 8 — Architecture diagram
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "Architecture", 0.55);
  s.addText("One tested core, one real dataset, one console", {
    x: 0.55, y: 0.95, w: 11, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  const boxes = [
    [0.55, "Data", "1.1M real ERCOT\nMIS auction records\n(bundled) or\nsynthetic fallback", "database"],
    [3.55, "Analytics core", "analytics.py\nscoring.py\n(pure functions,\nno I/O)", "layers"],
    [6.55, "FastAPI", "/api/dashboard\n/api/pairs\n/api/participants\n/api/opportunity-scores", "code"],
    [9.55, "React console", "Overview · Explorer\nParticipants · Signals\n· Binding constraints", "gitbranch"],
  ];
  boxes.forEach(([x, title, body, ic]) => {
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.0, w: 2.7, h: 2.6, rectRadius: 0.08, fill: { color: PANEL }, line: { color: BORDER, width: 1 } });
    icon(s, ic, x + 0.25, 2.25, 0.45);
    s.addText(title, { x: x + 0.25, y: 2.85, w: 2.2, h: 0.4, fontFace: FONT_BODY, fontSize: 13.5, bold: true, color: TEXT, isTextBox: true, margin: 0 });
    s.addText(body, { x: x + 0.25, y: 3.3, w: 2.2, h: 1.2, fontFace: FONT_MONO, fontSize: 10, color: TEXT_MUTE, isTextBox: true, margin: 0 });
  });
  [3.35, 6.35, 9.35].forEach((x) => {
    s.addText("→", { x: x - 0.15, y: 3.0, w: 0.4, h: 0.6, fontFace: FONT_BODY, fontSize: 22, bold: true, color: GREEN, align: "center", isTextBox: true, margin: 0 });
  });

  s.addShape(pres.ShapeType.roundRect, { x: 0.55, y: 5.0, w: 11.7, h: 0.7, rectRadius: 0.08, fill: { color: "1A1E12" }, line: { color: "3A3D1F", width: 1 } });
  s.addText(
    "136 pytest tests exercise the analytics core AND the API layer. The React console never computes " +
    "an average, a trend, or a score itself — it only renders what the tested core already produced.",
    { x: 0.9, y: 5.0, w: 11.0, h: 0.7, fontFace: FONT_BODY, fontSize: 13, color: AMBER, valign: "middle", isTextBox: true, margin: 0 }
  );
  pageNum(s, 8);
  s.addNotes("34:00-37:00 (post-demo) — Emphasize the pure-function core: it's the reason the demo you just saw and the numbers in the tests are guaranteed to agree.");
}

// ---------------------------------------------------------------
// Slide 9 — Demo intro / script
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "Live demo", 0.55);
  s.addText("Five pages, one real dataset", {
    x: 0.55, y: 0.95, w: 10, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });
  const demoSteps = [
    ["Overview", "Latest real auction month, MW awarded, top opportunity corridors, top participants by notional"],
    ["Source/Sink Explorer", "Pick any of the 30 tracked corridors (or compare up to 3 at once); Obligation vs. Option price history"],
    ["Participants", "Search 377 real CRR Account Holders; drill into any participant's recent certificate-level activity"],
    ["Opportunity Signals", "Every corridor's Low/Medium/High score with its four factor sub-scores and plain-language explanation"],
    ["Binding Constraints", "Live ERCOT transmission constraints right now — a separate, real-time clock from the settled auction data"],
  ];
  let y = 1.75;
  demoSteps.forEach(([title, body], i) => {
    s.addText(`0${i + 1}`, { x: 0.6, y, w: 0.7, h: 0.75, fontFace: FONT_MONO, fontSize: 22, color: GREEN, isTextBox: true, margin: 0 });
    s.addText(title, { x: 1.5, y: y + 0.02, w: 4.2, h: 0.35, fontFace: FONT_BODY, fontSize: 15.5, bold: true, color: TEXT, isTextBox: true, margin: 0 });
    s.addText(body, { x: 1.5, y: y + 0.4, w: 10.8, h: 0.4, fontFace: FONT_BODY, fontSize: 12, color: TEXT_MUTE, isTextBox: true, margin: 0 });
    y += 0.85;
  });
  s.addText("[ SWITCH TO LIVE APPLICATION — return here only if the connection drops ]", {
    x: 0.55, y: 6.3, w: 12, h: 0.4, fontFace: FONT_MONO, fontSize: 11, color: TEXT_DIM, align: "center", isTextBox: true, margin: 0,
  });
  pageNum(s, 9);
  s.addNotes("17:00-37:00 — This slide is the live-demo cue card. Actually tab through the running application here for ~20 minutes; the next four slides are a fallback in case of technical issues.");
}

// ---------------------------------------------------------------
// Slide 10 — Fallback: Opportunity scores chart (real data)
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "Demo fallback · opportunity signals", 0.55);
  s.addText("Top-scoring Source/Sink corridors", {
    x: 0.55, y: 0.95, w: 11, h: 0.7, fontFace: FONT, fontSize: 28, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  const chartData = [{
    name: "Opportunity score",
    labels: topScores.map((r) => `${r.source} \u2192 ${r.sink}`),
    values: topScores.map((r) => r.score),
  }];
  s.addChart(pres.ChartType.bar, chartData, {
    x: 0.55, y: 1.75, w: 12.2, h: 4.3, barDir: "bar",
    showTitle: false, showLegend: false, showValue: true,
    dataLabelColor: TEXT, dataLabelFontSize: 10, dataLabelPosition: "outEnd",
    chartColors: [GREEN],
    catAxisLabelColor: TEXT_MUTE, catAxisLabelFontSize: 10, catAxisLabelFontFace: FONT_MONO,
    valAxisLabelColor: TEXT_MUTE, valAxisLabelFontSize: 10,
    valAxisMinVal: 0, valAxisMaxVal: 100,
    valGridLine: { color: BORDER, size: 0.75 },
    catGridLine: { style: "none" },
    plotArea: { fill: { color: PANEL } },
    chartArea: { fill: { color: BG } },
  });
  s.addText("Generated from the app's own scoring.py output — not hand-picked for the deck.", {
    x: 0.55, y: 6.2, w: 12, h: 0.35, fontFace: FONT_BODY, fontSize: 11, italic: true, color: TEXT_DIM, isTextBox: true, margin: 0,
  });
  pageNum(s, 10);
  s.addNotes("Fallback only. This chart is generated from real, settled ERCOT auction data (regenerate via `python scripts/export_snapshot.py` after any data refresh) — whatever tops this list is genuinely today's highest-scoring tracked corridor, not a fixed example.");
}

// ---------------------------------------------------------------
// Slide 11 — Fallback: Participants chart (real data)
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "Demo fallback · participant analysis", 0.55);
  s.addText("Top participants by total notional value", {
    x: 0.55, y: 0.95, w: 11.5, h: 0.7, fontFace: FONT, fontSize: 28, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  const chartData = [{
    name: "Total notional ($)",
    labels: topParticipants.map((p) => p.participant),
    values: topParticipants.map((p) => Math.round(p.total_notional)),
  }];
  s.addChart(pres.ChartType.bar, chartData, {
    x: 0.55, y: 1.75, w: 12.2, h: 4.3, barDir: "bar",
    showTitle: false, showLegend: false, showValue: true,
    dataLabelColor: TEXT, dataLabelFontSize: 9.5, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "$#,##0",
    chartColors: [BLUE],
    catAxisLabelColor: TEXT_MUTE, catAxisLabelFontSize: 10, catAxisLabelFontFace: FONT_BODY,
    valAxisLabelColor: TEXT_MUTE, valAxisLabelFontSize: 10, valAxisLabelFormatCode: "$#,##0",
    valAxisMinVal: 0,
    valGridLine: { color: BORDER, size: 0.75 },
    catGridLine: { style: "none" },
    plotArea: { fill: { color: PANEL } },
    chartArea: { fill: { color: BG } },
  });
  s.addText(`Across ${snap.meta.participant_count} tracked participants and ${snap.meta.record_count.toLocaleString()} auction records, ${snap.meta.first_month} \u2013 ${snap.meta.latest_month}.`, {
    x: 0.55, y: 6.2, w: 12, h: 0.35, fontFace: FONT_BODY, fontSize: 11, italic: true, color: TEXT_DIM, isTextBox: true, margin: 0,
  });
  pageNum(s, 11);
  s.addNotes("Fallback only. These are real CRR Account Holder names from ERCOT's own Market Participants List (NP12-215-ER) — not the fictional placeholders used only when no real data is present, see slide 7.");
}

// ---------------------------------------------------------------
// Slide 12 — Testing & validation summary
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "Proof, not just a demo", 0.55);
  s.addText("How we know it's actually correct", {
    x: 0.55, y: 0.95, w: 11, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  const proofs = [
    ["flask", "136/136 backend tests pass", "Analytics, scoring, ingestion (including real ERCOT column parsing), live-API client, and every FastAPI endpoint — re-run after every change, not just once"],
    ["target", "Scoring engine is behavior-tested, not just shape-tested", "A synthetic strong pair (high/rising/consistent/liquid) is asserted to outrank a synthetic weak pair — the score reacts to what it claims to"],
    ["search", "A real bug the tests alone wouldn't have caught", "The backend was quietly serving synthetic data through one code path while Streamlit showed real data through another — found by comparing the two live, not by re-reading either one"],
    ["checkcircle", "Every UI change verified in a real running browser", "Live backend + live frontend, clicked/hovered/typed through with real data on screen, not just component tests against mocks"],
  ];
  let y = 1.9;
  proofs.forEach(([ic, title, body]) => {
    icon(s, ic, 0.6, y, 0.4);
    s.addText(title, { x: 1.2, y: y - 0.05, w: 10.9, h: 0.4, fontFace: FONT_BODY, fontSize: 15, bold: true, color: TEXT, isTextBox: true, margin: 0 });
    s.addText(body, { x: 1.2, y: y + 0.35, w: 10.9, h: 0.55, fontFace: FONT_BODY, fontSize: 12, color: TEXT_MUTE, isTextBox: true, margin: 0 });
    y += 1.1;
  });
  pageNum(s, 12);
  s.addNotes("37:00-45:00 — Show the terminal output of `python -m pytest -q` live if possible: `30 passed`.");
}

// ---------------------------------------------------------------
// Slide 13 — Lessons learned
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "Reflection", 0.55);
  s.addText("What AI made easier — and what still needed judgment", {
    x: 0.55, y: 0.95, w: 12, h: 0.7, fontFace: FONT, fontSize: 26, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  const left = [
    "Scaffolding a full-stack app (API + tests + UI) in one sitting",
    "Writing comprehensive unit tests alongside — not after — the logic",
    "Producing a requirements doc with traceable acceptance criteria",
    "Rebuilding the whole frontend around a new design system in one review cycle",
  ];
  const right = [
    "Verifying real-world data access before designing around it",
    "Deciding scoring should be explainable rules, not a black box",
    "Being explicit — in the UI itself — about synthetic vs. real data",
    "Scrapping a working map feature once it stopped serving the trader, rather than polishing it further",
  ];
  s.addText("AI ACCELERATED", { x: 0.6, y: 1.85, w: 5.8, h: 0.3, fontFace: FONT_MONO, fontSize: 12, color: GREEN, isTextBox: true, margin: 0 });
  left.forEach((t, i) => {
    s.addText("•  " + t, { x: 0.6, y: 2.2 + i * 0.58, w: 5.8, h: 0.52, fontFace: FONT_BODY, fontSize: 12, color: TEXT_MUTE, isTextBox: true, margin: 0 });
  });
  s.addText("JUDGMENT CALLS THAT STILL NEEDED A HUMAN FRAME", { x: 6.75, y: 1.85, w: 6.0, h: 0.3, fontFace: FONT_MONO, fontSize: 12, color: AMBER, isTextBox: true, margin: 0 });
  right.forEach((t, i) => {
    s.addText("•  " + t, { x: 6.75, y: 2.2 + i * 0.58, w: 6.0, h: 0.52, fontFace: FONT_BODY, fontSize: 12, color: TEXT_MUTE, isTextBox: true, margin: 0 });
  });

  s.addShape(pres.ShapeType.line, { x: 0.6, y: 4.6, w: 12.15, h: 0, line: { color: BORDER, width: 1 } });
  s.addText("Full write-up: docs/lessons_learned_and_future_work.md", {
    x: 0.6, y: 4.75, w: 12, h: 0.4, fontFace: FONT_MONO, fontSize: 11.5, color: TEXT_DIM, isTextBox: true, margin: 0,
  });
  pageNum(s, 13);
  s.addNotes("45:00-53:00 — Be candid here; this is the reflective core of a capstone grade.");
}

// ---------------------------------------------------------------
// Slide 14 — Future enhancements
// ---------------------------------------------------------------
{
  const s = baseSlide();
  eyebrow(s, "What's next", 0.55);
  s.addText("Future enhancements", {
    x: 0.55, y: 0.95, w: 10, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });

  const items = [
    ["database", "Auto-refreshing data cache", "Backend caches the real dataset for process lifetime; a new auction month needs a restart to appear"],
    ["trending", "Cross-validate against DAM/RTM", "Compare realized congestion to auction-cleared CRR value"],
    ["shield", "Confidence bands on the score", "Surface sample-size uncertainty, not just a single number"],
    ["users", "Portfolio view", "Score a user's own CRR holdings, not just the tracked universe"],
    ["gitbranch", "Link constraints to corridors", "Binding Constraints is a real, live, searchable list today; connecting a constraint to the specific tracked pair it affects is the next step"],
    ["lightbulb", "Regime-change alerting", "Notify when a pair crosses a tier boundary"],
  ];
  let x = 0.55, y = 1.9;
  items.forEach(([ic, title, body], i) => {
    if (i === 3) { x = 0.55; y = 4.05; }
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 3.95, h: 1.95, rectRadius: 0.08, fill: { color: PANEL }, line: { color: BORDER, width: 1 } });
    icon(s, ic, x + 0.25, y + 0.25, 0.4);
    s.addText(title, { x: x + 0.25, y: y + 0.8, w: 3.5, h: 0.5, fontFace: FONT_BODY, fontSize: 13, bold: true, color: TEXT, isTextBox: true, margin: 0 });
    s.addText(body, { x: x + 0.25, y: y + 1.28, w: 3.5, h: 0.6, fontFace: FONT_BODY, fontSize: 10.5, color: TEXT_MUTE, isTextBox: true, margin: 0 });
    x += 4.15;
  });
  pageNum(s, 14);
  s.addNotes("53:00-56:00 — Move briskly; full detail lives in the lessons-learned doc.");
}

// ---------------------------------------------------------------
// Slide 15 — Close / Q&A
// ---------------------------------------------------------------
{
  const s = baseSlide();
  icon(s, "zap", 0.6, 0.7, 0.5);
  s.addText("Questions", {
    x: 0.55, y: 2.4, w: 10, h: 1.1, fontFace: FONT, fontSize: 54, bold: true, color: TEXT, isTextBox: true, margin: 0,
  });
  s.addText("& discussion", {
    x: 0.55, y: 3.3, w: 10, h: 1.0, fontFace: FONT, fontSize: 40, bold: true, color: GREEN, isTextBox: true, margin: 0,
  });
  s.addShape(pres.ShapeType.line, { x: 0.6, y: 4.5, w: 3.2, h: 0, line: { color: BORDER, width: 1 } });
  s.addText("Repository: ercot-crr-analytics/  ·  136/136 tests passing  ·  README.md has full setup instructions", {
    x: 0.6, y: 4.7, w: 11, h: 0.4, fontFace: FONT_MONO, fontSize: 12.5, color: TEXT_DIM, isTextBox: true, margin: 0,
  });
  pageNum(s, 15);
  s.addNotes("56:00-60:00 — Open floor. Likely questions: how the synthetic data was calibrated, why rule-based scoring over ML, and what real MIS access would change.");
}

pres.writeFile({ fileName: "../ERCOT_CRR_Capstone_Presentation.pptx" }).then(() => {
  console.log("Deck written.");
});
