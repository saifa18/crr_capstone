"""
Regenerates data/snapshot.json -- the embedded demo dataset baked into
frontend/src/ErcotCrrDashboard.jsx for offline/standalone use.

Run from backend/: `python scripts/export_snapshot.py`

Includes, per Source/Sink pair: full per-time-of-use series/metrics
(ALL/PEAK_WD/PEAK_WE/OFF_PEAK) for both Obligation and Option CRRs, and the
list of participants active on that specific pair -- everything the
frontend's demoProvider needs to serve the same filtered views the live
backend serves, entirely offline.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data_generator import records_as_dicts
from app import analytics, scoring
from app.domain import SP_BY_CODE, TimeOfUse

records = records_as_dicts()

dashboard_scores = scoring.score_all_pairs(records)

TOU_KEYS = ["ALL"] + [t.value for t in TimeOfUse]

pairs_out = []
for source, sink in analytics.all_pairs(records):
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
        "source": source, "source_name": SP_BY_CODE[source].name,
        "sink": sink, "sink_name": SP_BY_CODE[sink].name,
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
    "source": s.source, "source_name": SP_BY_CODE[s.source].name,
    "sink": s.sink, "sink_name": SP_BY_CODE[s.sink].name,
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
latest_recs = [r for r in records if r["auction_month"] == latest_month]

meta = {
    "record_count": len(records),
    "first_month": months[0],
    "latest_month": latest_month,
    "pair_count": len(pairs_out),
    "participant_count": len(participants_out),
    "latest_month_mw": round(sum(r["awarded_mw"] for r in latest_recs), 1),
    "latest_month_participants": len({r["participant"] for r in latest_recs}),
}

snapshot = {
    "meta": meta, "pairs": pairs_out, "scores": scores_out,
    "participants": participants_out, "participant_activity": participant_activity,
}

out_path = Path(__file__).resolve().parents[2] / "data" / "snapshot.json"
with open(out_path, "w") as f:
    json.dump(snapshot, f, separators=(",", ":"))
print(f"wrote {out_path}, bytes: {out_path.stat().st_size}")
