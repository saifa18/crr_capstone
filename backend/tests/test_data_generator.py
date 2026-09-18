from app.data_generator import generate_auction_records, records_as_dicts
from app.domain import CRR_PAIRS, TimeOfUse, CRRType


def test_generates_nonempty_dataset():
    records = generate_auction_records()
    assert len(records) > 1000


def test_deterministic_given_seed():
    a = records_as_dicts()
    b = records_as_dicts()
    assert a == b, "Generator must be fully deterministic (fixed SEED)"


def test_all_pairs_present():
    records = records_as_dicts()
    pairs_seen = {(r["source"], r["sink"]) for r in records}
    assert pairs_seen == set(CRR_PAIRS)


def test_all_crr_types_and_tou_present_per_pair():
    records = records_as_dicts()
    for source, sink in CRR_PAIRS:
        subset = [r for r in records if r["source"] == source and r["sink"] == sink]
        types = {r["crr_type"] for r in subset}
        tous = {r["time_of_use"] for r in subset}
        assert types == {t.value for t in CRRType}
        assert tous == {t.value for t in TimeOfUse}


def test_awarded_mw_and_price_are_sane():
    records = records_as_dicts()
    for r in records:
        assert r["awarded_mw"] > 0
        assert isinstance(r["clearing_price"], float)
        # option clearing prices are never negative and never huge given the model
        if r["crr_type"] == "OPTION":
            assert r["clearing_price"] >= 0


def test_covers_expected_month_range():
    records = records_as_dicts()
    months = {r["auction_month"] for r in records}
    assert "2019-01" in months
    assert "2026-07" in months
    assert "2018-12" not in months
    assert "2026-08" not in months
