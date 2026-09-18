# Lessons Learned & Future Enhancements

## Lessons learned

**1. Data access is a first-class design constraint, not a footnote.**
The single biggest decision in this project — synthetic vs. real data —
came from actually trying to fetch ERCOT's public CRR files programmatically
and hitting a JS-driven, session-gated download center, rather than
assuming access would "probably work." Verifying this *before* designing
the ingestion layer meant the architecture (an ingestion module written
against ERCOT's real published column layout, with a transparent synthetic
fallback) was right the first time, instead of needing a rewrite once the
access limitation surfaced later.

**2. "Explainable" has to be a constraint on the design, not a label
applied after the fact.** Building the opportunity score as a weighted,
inspectable composite of four named factors — rather than any kind of
learned model — was a decision made *before* writing scoring code, driven
directly by the capstone's own framing ("market intelligence... rather than
predicting trading outcomes"). Every score can be traced back to its four
inputs; there is no hidden state.

**3. Tests are the difference between "it ran once" and "it works."**
The scoring engine looked reasonable on first read; the test that actually
proved it (`test_score_all_pairs_ranks_strong_pair_above_weak_pair`)
constructs a deliberately obvious strong/weak pair and checks the ranking
comes out right. Without that test, a sign error in one factor's weighting
could have shipped silently — the numbers would still be *some* number
between 0 and 100, just the wrong one.

**4. Keep the UI dumber than the backend.** The React dashboard never
computes an average, a trend, or a score itself — it only renders
precomputed JSON. This means the exact same tested Python logic is what
the user sees, with zero risk of the display layer quietly reimplementing
(and subtly breaking) the analytics.

**5. Synthetic data needs its own honesty policy.** It would have been easy
to make the demo data "look real" without saying so. Tagging every record
`is_synthetic` and surfacing a persistent UI banner was a deliberate choice
so nobody — including a future version of this project — mistakes the demo
numbers for ERCOT history.

**6. An earlier "no" is worth re-checking, not just repeating.** The first
pass concluded ERCOT's CRR auction data wasn't programmatically reachable
from this environment, which was true — but it turned out to be true of
only one of ERCOT's two separate systems. Re-investigating from scratch
when asked to "make this more usable" (rather than citing the earlier
finding as settled) surfaced a real, free, live Public API for DAM prices
and binding constraints that the first pass had missed entirely. The
lesson isn't "the first answer was wrong" — it's that a data-access
conclusion is scoped to what was checked, and a later, more specific ask
("get real ERCOT data via API") deserves a fresh check against that
specific claim rather than a restatement of the prior, broader one.

**7. An earlier "no" is worth re-checking a second time, too.** Lesson 6
above already documented one case of this (the live Public API). The same
pattern repeated here: this project had assumed CRR auction data required
a browser session because ERCOT's modern `mis.ercot.com` file browser is
JS-driven and session-gated. That's true of that specific interface -- but
ERCOT also runs an older, still-live, completely unauthenticated legacy
servlet (`ercot.com/misapp/servlets/IceDocListJsonWS` +
`ercot.com/misdownload/servlets/mirDownload`) that serves the exact same
files. It was found only by actually trying it -- downloading and parsing
a real file -- rather than re-stating the earlier, broader conclusion.
The fetched data also revealed two real bugs: (1) the real Market
Participants List document is a zip wrapping the xlsx, not raw xlsx bytes
— fixed by adding `extract_xlsx_from_zip()`; (2) the real CRRAH sheet has
a trailing footer/timestamp row that leaked into the participant CSV until
the row filter was tightened to require both NAME and SHORT_NAME present.
Both bugs would have shipped silently in code that only mocked the real
files — further evidence that "verify by actually running it against live
servers, not just against mocks" matters.

## Future enhancements

- ~~**Cross-validation against realized DAM/RTM congestion.**~~ **Done.**
  `ercot_live.py` / `live_congestion.py` now pull real, live Day-Ahead
  Market settlement point prices and compute the real Source/Sink spread
  (= realized Obligation-CRR value per ERCOT's own settlement formula),
  exposed via `/api/pairs/{source}/{sink}/live-lmp-spread`. Still open: use
  this live feed to independently corroborate the "consistency" factor in
  the opportunity score itself, rather than only exposing it as a separate
  endpoint.
- ~~**Live ERCOT MIS ingestion for the auction/participant data itself.**~~
  **Done (2026-09).** `backend/scripts/fetch_real_ercot_data.py` pulls real
  CRR Monthly Auction Results and the real Market Participants List
  directly from ERCOT's public legacy MIS servlet -- no browser session,
  no authentication. See lesson 7 above.
- **Confidence/sample-size indicator on the score.** A pair with 6 months
  of history and a pair with 90 months of history can currently land on the
  same score; a visible confidence band (e.g., score ± uncertainty based on
  `n_months`) would make the "how much should I trust this" question
  explicit rather than implicit.
- **Portfolio view.** Let a user upload their own CRR holdings and see them
  scored/aggregated against the same pair-level analytics, rather than only
  browsing the full tracked universe.
- ~~**Seasonal/time-of-use drill-down in the UI.**~~ **Done in v1.2.** The
  Explorer now has a TOU filter (All/Peak-WD/Peak-WE/Off-Peak) and a
  calendar-month seasonality strip.
- **Alerting on regime change.** Notify when a pair's trailing-12-month
  trend crosses a Low→Medium or Medium→High tier boundary, rather than
  requiring a user to check back manually.
- **Weather integrated into the opportunity score itself**, not just shown
  alongside it. v1.2 added a live weather panel as descriptive context
  (wind at West/Panhandle, temperature at Houston/DFW); a natural next step
  is testing whether recent wind/temperature actually correlates with
  realized congestion on the corresponding corridors in this dataset, and
  if so, surfacing that as a fifth, clearly-labeled scoring factor rather
  than a separate panel — deliberately not done yet, since that's a
  substantive analytical claim that deserves its own validation pass, not
  a bolt-on.
- **Presentation deck (`ERCOT_CRR_Capstone_Presentation.pptx`) has not been
  updated for v1.2.** It still reflects the v1.1 feature set. Should cover
  the connectable-architecture rebuild, the new Explorer capabilities, and
  the weather panel before it's presented.

## Lesson: why Open-Meteo, specifically, for weather

Not every free weather API would have fit the "genuinely runnable" bar
this project holds itself to elsewhere. Open-Meteo was chosen, and
verified before writing any integration code, for three concrete
properties that a typical weather API doesn't all have at once: no API key
(nothing else to configure or leak), CORS explicitly enabled
(`Access-Control-Allow-Origin: *`, confirmed from a working browser
`fetch()` example in search results before committing to it), and a plain
GET request with no custom auth headers (the kind of request least likely
to be blocked by a strict content-security policy, unlike the ERCOT
OAuth flow's POST-with-credentials pattern). That combination is exactly
what a sandboxed browser environment like an embedded artifact needs to
have a real chance of working — and it was verified against the actual
constraint (this build sandbox blocks the domain outright) rather than
assumed to work everywhere just because it worked in principle.
