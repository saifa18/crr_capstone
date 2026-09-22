# Demo Walkthrough — CRR Trading Console

A speaking guide for a live walkthrough with power traders. Five pages,
each answering one question, in order. Total run time: roughly 5–6
minutes if you move briskly through each section.

Every page is driven by real ERCOT data — bulk CRR auction results, real
participant records, and (on Path Settlements / Binding Constraints) the
live ERCOT Public API. Nothing on screen is synthetic or invented.

---

## 1. Overview — 30–45 seconds

**What I click:** Overview (the landing page)

**What I say:**
"This page gives the market-wide picture. At the top we can see MW
awarded in the latest auction month, active participants, tracked
paths, and the latest auction month itself."

**Then explain:**
- **Hot paths** — the corridors with the most real notional activity, each
  with a plain-language reason it's active.
- **Top participants by notional** — who's sizing up the biggest positions
  right now.
- Why these matter: this is the 30-second "what's going on in this
  market" view before drilling into any one path or participant.

**Transition:**
"Now that we know what's active overall, let's look at how individual
paths are priced."

---

## 2. Source / Sink Explorer — 45–60 seconds

**What I click:** a path from the list — recommended: **West Hub → West
Load Zone** (a consistently active, well-populated real corridor)

**What I say:**
"This is the auction side of the story. These curves show what
participants paid for Obligation and Option CRRs on this path over
time."

**Explain:**
- **Obligation vs. Option** — the green and amber lines; two different CRR
  instrument types, priced separately.
- **Auction price** — this is what was bid/cleared at auction, not what
  the path later settled for.
- **Participants active on this path** — the panel below the chart, who
  else is holding this corridor.
- (Optional, if time allows) Compare mode — stack up to 3 paths side by
  side.

**Transition:**
"But auction price only tells us what the CRR cost. The important
question is how the path actually settled."

---

## 3. Participants — 45–75 seconds

**What I click:** Participants — recommended example: **LUMINANT ENERGY
COMPANY LLC REPS (CRRAH)** (a real participant with thousands of real
certificates, so every feature below has something to show)

**Explain, pointing at each control/number as you go:**
- **Search participant** — searchable, not a giant static list.
- **Net MW** — signed sum of awarded MW across matching certificates.
- **Notional value** — sizing figure (MW × clearing price), not a
  settlement amount.
- **Distinct paths** / **Certificates** — how spread out and how large
  their book is.
- **Auction period filter** — All time / YTD / a specific month.
- **CRR type filter** — Obligation / Option / All, strict (no mixing).
- **Certificate pagination** — real server-side paging, 25 rows at a
  time, so a 2,800-certificate book never dumps onto one screen.
- **Path settlement value by participant** — the section below the
  certificates table: real settlement $ (awarded MW × real ERCOT
  settlement spread), searchable by participant and by path
  independently of who's currently selected above.

**Transition:**
"Now we move from what participants bought to how those positions
actually performed."

---

## 4. Path Settlements — 60–90 seconds

**What I click:** Path settlements — recommended example: **West Hub →
West Load Zone** again (same corridor as step 2, so the "auction price
vs. settlement" contrast lands)

**What I say, writing/pointing out the formula:**
"Settlement = Sink SPP − Source SPP. That's the literal ERCOT Obligation
CRR payoff formula, computed here from real Day-Ahead settlement point
prices, not from the auction bid price."

**Explain:**
- **Obligation** — can be positive or negative (you can owe ERCOT).
- **Option** — floored at zero (you never owe).
- **Latest / average / min / max** stat tiles for both instrument types.
- The **chart** and the **YTD vs. this month** toggle.
- The **Path settlement / Source SPP vs. Sink SPP** toggle — same data,
  two views.

**VERY IMPORTANT — say this explicitly:**
"Historical settlement performance alone does not automatically mean a
path is currently a profitable trade. What a participant actually paid
to acquire the CRR at auction — the notional figure from the
Participants page — has to be weighed against this settlement value.
This page shows what a position was worth; it doesn't show whether it
was bought cheap or expensive."

**Transition:**
"Now let's close the loop — why did this path separate in price at
all?"

---

## 5. Binding Constraints — 60–90 seconds

**What I click:** Binding constraints — recommended example: search or
click **6437__F** in "Most active constraints" (a real, currently-active
transmission element with a high shadow price and a real named
contingency, so it reads clearly on screen)

**What I say:**
"These are the live grid conditions that help explain why nodal prices
separate in the first place — this is a completely different, real-time
clock from the settled auction data on the other pages."

**Explain:**
- **Most active constraints** — ranked by how often each element was
  reported binding in the selected window (7d / 14d / 30d).
- **HourEnding : Constraint** — ERCOT's hour-ending interval plus its
  internal identifier for the binding transmission element, kept
  together as one field.
- **Contingency** — the outage/scenario being evaluated when this
  constraint binds. **BASE CASE** means no modeled contingency — the
  element is binding under normal system conditions.
- **Element endpoints** — the from/to substations the monitored element
  connects.
- **Shadow price ($/MWh)** — the marginal economic impact of that
  constraint; larger values mean more costly congestion. This is a
  different number from CRR settlement price, auction price, or profit
  — say that explicitly if anyone asks.
- The table itself is server-side paginated (9,000+ real rows in a
  7-day window) — Previous/Next both work, and the search box searches
  every real constraint in the window, not just the current page.

**Transition / closing line for this section:**
"This closes the loop: constraints create congestion, congestion
creates price separation, and that price separation is exactly what
drives CRR settlement value on the page before this one."

---

## Closing statement

"The app connects the full CRR story: what paths were auctioned, who
holds them, how they actually settled, and what live grid constraints
were driving the underlying congestion — all from real ERCOT data, end
to end."

---

## Notes for you, not for the room

- **Recommended stable examples** (chosen because they reliably have
  rich real data as of this pass):
  - Path: **West Hub → West Load Zone** (`HB_WEST` → `LZ_WEST`) — top
    corridor by notional, works for both Explorer and Path Settlements.
  - Participant: **LUMINANT ENERGY COMPANY LLC REPS (CRRAH)** — largest
    real book by notional, ~2,800 certificates.
  - Binding constraint: **6437__F** — consistently one of the most
    active real constraints in a trailing 7-day window.
  - These are **not hardcoded** anywhere in the app — they're just
    reliable picks in the current real dataset. If the live data has
    moved on by demo day, "Hot paths" (Overview) and "Most active
    constraints" (Binding Constraints) will show you the current
    equivalents live.
- **Binding Constraints and Path Settlements both call ERCOT's live
  Public API**, which has a real, documented rate limit. If either page
  shows a rate-limit error during the demo, that's expected occasional
  behavior, not a bug — click **Retry** once, or narrow the trailing
  window (7d) before you go on stage to warm the 15-minute server-side
  cache.
- Auction data (Overview, Explorer, Participants) and live ERCOT data
  (Path Settlements, Binding Constraints) are two different clocks —
  the app says this explicitly on both live pages. Don't imply they're
  the same "as of" date if asked.
