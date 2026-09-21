"""
Regenerates data/snapshot.json -- a static export of the real, tracked
top-30-corridor dataset, used by presentation/build/build_deck.js so the
capstone deck's charts are generated from the app's own real output rather
than hand-picked or hardcoded numbers.

Run from backend/: `python scripts/export_snapshot.py`

Sources the same real bulk ERCOT MIS data (and the same top-30-by-notional
tracked-pair restriction) as main.py and the Streamlit app -- see
ingestion.load_bulk_real_auction_data and analytics.discover_top_pairs --
so this snapshot never drifts from what a grader would see live.

Includes, per tracked Source/Sink pair: full per-time-of-use series/metrics
(ALL/PEAK_WD/PEAK_WE/OFF_PEAK) for both Obligation and Option CRRs, and the
list of participants active on that specific pair.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ingestion import load_bulk_real_auction_data
from app import analytics, scoring
from app.domain import SP_BY_CODE, TimeOfUse

TOP_N_PAIRS = 30

all_records, data_source, _warning = load_bulk_real_auction_data()
top_pairs = analytics.discover_top_pairs(all_records, n=TOP_N_PAIRS)
tracked_keys = {(p["source"], p["sink"]) for p in top_pairs}
records = [r for r in all_records if (r["source"], r["sink"]) in tracked_keys]

dashboard_scores = scoring.score_all_pairs(records)

TOU_KEYS = ["ALL"] + [t.value for t in TimeOfUse]


def _sp_name(code: str) -> str:
    sp = SP_BY_CODE.get(code)
    return sp.name if sp else code


pairs_out = []
for source, sink in sorted(tracked_keys):
    recs = analytics.filter_records(records, source=source, sink=sink)
    obligation_all = [r for r in recs if r["crr_type"] == "OBLIGATION"]
    option_all = [r for r in recs if r["crr_type"] == "OPTION"]

    obligation_by_tou = {}
    option_by_tou = {}
    for tou_key in TOU_KEYS:
        ob = obligation_all if tou_key == "ALL" else [r for r in obligation_all if r["time_of_use"] == tou_key]
        op = option_all if tou_key == "ALL" else [r for r in option_all if r["time_of_use"] == tou_key]
        obligation_by_tou[tou_key] = {
            "series": analytics.monthly_price_series(ob),
            "metrics": analytics.basic_metrics(ob),
        }
        option_by_tou[tou_key] = {
            "series": analytics.monthly_price_series(op),
            "metrics": analytics.basic_metrics(op),
        }

    pair_participants = analytics.participant_summary(recs)

    pairs_out.append({
        "source": source, "source_name": _sp_name(source),
        "sink": sink, "sink_name": _sp_name(sink),
        "obligation_by_tou": obligation_by_tou,
        "option_by_tou": option_by_tou,
        # kept for backward compatibility with anything reading the old flat shape
        "obligation_series": obligation_by_tou["ALL"]["series"],
        "option_series": option_by_tou["ALL"]["series"],
        "obligation_metrics": obligation_by_tou["ALL"]["metrics"],
        "option_metrics": option_by_tou["ALL"]["metrics"],
        "participants": pair_participants,
    })

scores_out = [{
    "source": s.source, "source_name": _sp_name(s.source),
    "sink": s.sink, "sink_name": _sp_name(s.sink),
    "score": s.score, "tier": s.tier, "factors": s.factors,
    "explanation": s.explanation, "metrics": s.metrics,
} for s in dashboard_scores]

participants_out = analytics.participant_summary(records)

top_names = [p["participant"] for p in participants_out]
by_participant_month = defaultdict(lambda: defaultdict(float))
by_participant_pairs = defaultdict(set)
for r in records:
    by_participant_month[r["participant"]][r["auction_month"]] += r["awarded_mw"]
    by_participant_pairs[r["participant"]].add((r["source"], r["sink"]))

months_sorted = sorted({r["auction_month"] for r in records})
participant_activity = {}
for name in top_names:
    series = [{"auction_month": m, "mw": round(by_participant_month[name].get(m, 0.0), 1)} for m in months_sorted]
    participant_activity[name] = {
        "monthly_mw": series,
        "pairs": [{"source": s, "sink": k} for s, k in sorted(by_participant_pairs[name])],
    }

months = months_sorted
latest_month = months[-1]
# Latest-month MW/participant figures reflect the FULL real dataset (matches
# the /api/dashboard and Streamlit Overview definitions), not just the
# tracked top-30 -- the tracked restriction is for pair-level analysis only.
all_latest_recs = [r for r in all_records if r["auction_month"] == latest_month]

meta = {
    "data_source": data_source,
    "record_count": len(all_records),
    "first_month": months[0],
    "latest_month": latest_month,
    "pair_count": len(pairs_out),
    "participant_count": len({r["participant"] for r in all_records}),
    "latest_month_mw": round(sum(r["awarded_mw"] for r in all_latest_recs), 1),
    "latest_month_participants": len({r["participant"] for r in all_latest_recs}),
}

snapshot = {
    "meta": meta, "pairs": pairs_out, "scores": scores_out,
    "participants": participants_out, "participant_activity": participant_activity,
}

out_path = Path(__file__).resolve().parents[2] / "data" / "snapshot.json"
with open(out_path, "w") as f:
    json.dump(snapshot, f, separators=(",", ":"))
print(f"wrote {out_path}, bytes: {out_path.stat().st_size}")
