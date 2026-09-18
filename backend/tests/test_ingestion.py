from __future__ import annotations

from pathlib import Path

import pytest

from app import ingestion


REAL_HEADERS = [
    "CRR_ID", "OriginalCRR_ID", "AccountHolder", "HedgeType", "BidType",
    "CRRType", "Source", "Sink", "StartDate", "EndDate", "TimeOfUse",
    "Bid24Hour", "MW", "ShadowPricePerMWH",
]


def _real_row(
    account_holder="XSARAC", hedge_type="OPT", bid_type="BUY", crr_type="PREAWARD",
    source="LONEWOLF_ALL", sink="PIONR_DJ_RN", start_date="10/01/2026",
    end_date="10/31/2026", tou="PeakWD", mw="5.8", price="2.727068",
):
    return [
        "225506479", "", account_holder, hedge_type, bid_type, crr_type,
        source, sink, start_date, end_date, tou, "No", mw, price,
    ]


def test_map_row_reads_hedgetype_not_crrtype_for_crr_type():
    mapped = ingestion._map_row(REAL_HEADERS, _real_row(hedge_type="OBL", crr_type="STANDARD"))
    assert mapped["crr_type"] == "OBLIGATION"
    assert mapped["award_type"] == "STANDARD"


def test_map_row_normalizes_hedgetype_abbreviations():
    assert ingestion._map_row(REAL_HEADERS, _real_row(hedge_type="OPT"))["crr_type"] == "OPTION"
    assert ingestion._map_row(REAL_HEADERS, _real_row(hedge_type="OBL"))["crr_type"] == "OBLIGATION"


def test_map_row_normalizes_time_of_use_values():
    assert ingestion._map_row(REAL_HEADERS, _real_row(tou="PeakWD"))["time_of_use"] == "PEAK_WD"
    assert ingestion._map_row(REAL_HEADERS, _real_row(tou="PeakWE"))["time_of_use"] == "PEAK_WE"
    assert ingestion._map_row(REAL_HEADERS, _real_row(tou="Off-peak"))["time_of_use"] == "OFF_PEAK"


def test_map_row_derives_auction_month_from_start_date():
    mapped = ingestion._map_row(REAL_HEADERS, _real_row(start_date="10/01/2026"))
    assert mapped["auction_month"] == "2026-10"


def test_map_row_signs_awarded_mw_by_bid_type():
    buy = ingestion._map_row(REAL_HEADERS, _real_row(bid_type="BUY", mw="5.8"))
    sell = ingestion._map_row(REAL_HEADERS, _real_row(bid_type="SELL", mw="5.8"))
    assert buy["awarded_mw"] == 5.8
    assert sell["awarded_mw"] == -5.8


def test_map_row_preserves_price_sign_regardless_of_bid_type():
    buy = ingestion._map_row(REAL_HEADERS, _real_row(bid_type="BUY", price="-1.5"))
    sell = ingestion._map_row(REAL_HEADERS, _real_row(bid_type="SELL", price="-1.5"))
    assert buy["clearing_price"] == -1.5
    assert sell["clearing_price"] == -1.5


def test_map_row_joins_participant_registry_for_real_name():
    registry = {"XSARAC": "SOME REAL COMPANY LLC (CRRAH)"}
    mapped = ingestion._map_row(REAL_HEADERS, _real_row(account_holder="XSARAC"), registry)
    assert mapped["participant"] == "SOME REAL COMPANY LLC (CRRAH)"
    assert mapped["participant_short_code"] == "XSARAC"


def test_map_row_falls_back_to_short_code_when_registry_missing_entry():
    mapped = ingestion._map_row(REAL_HEADERS, _real_row(account_holder="XUNKNOWN"), {})
    assert mapped["participant"] == "XUNKNOWN"
    assert mapped["participant_short_code"] == "XUNKNOWN"


def test_map_row_award_type_defaults_to_standard_when_column_absent():
    old_headers = ["Source", "Sink", "CRRType", "TimeOfUse", "MW", "ClearingPrice",
                   "AccountHolder", "AuctionMonth"]
    old_row = ["HB_WEST", "HB_HOUSTON", "OBLIGATION", "PEAK_WD", "10.0", "5.0", "X", "2024-01"]
    mapped = ingestion._map_row(old_headers, old_row)
    assert mapped["crr_type"] == "OBLIGATION"
    assert mapped["award_type"] == "STANDARD"


def test_load_participant_registry_reads_short_name_to_name(tmp_path):
    path = tmp_path / "participants.csv"
    path.write_text("short_name,name,duns_number\nXAESMT,AES MARKETING AND TRADING LLC (CRRAH),1187367255000\n")
    registry = ingestion._load_participant_registry(path)
    assert registry["XAESMT"] == "AES MARKETING AND TRADING LLC (CRRAH)"


def test_load_participant_registry_returns_empty_dict_when_missing(tmp_path):
    assert ingestion._load_participant_registry(tmp_path / "nope.csv") == {}


def test_load_real_csvs_from_reads_all_csvs_in_directory(tmp_path):
    (tmp_path / "a.csv").write_text(
        ",".join(REAL_HEADERS) + "\n" + ",".join(_real_row(source="HB_WEST", sink="HB_HOUSTON"))
    )
    records = ingestion._load_real_csvs_from(tmp_path)
    assert len(records) == 1
    assert records[0]["source"] == "HB_WEST"
    assert records[0]["is_synthetic"] is False


def test_load_bulk_real_auction_data_falls_back_to_load_records_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, "BULK_AUCTION_DIR", tmp_path / "does_not_exist")
    monkeypatch.setattr(ingestion, "PARTICIPANT_REGISTRY_PATH", tmp_path / "no_registry.csv")
    records, source, warning = ingestion.load_bulk_real_auction_data()
    assert source == ingestion.SOURCE_SYNTHETIC
    assert len(records) > 0


def test_load_bulk_real_auction_data_uses_real_files_when_present(tmp_path, monkeypatch):
    bulk_dir = tmp_path / "crr_auction"
    bulk_dir.mkdir()
    (bulk_dir / "2026-10_MarketResults.csv").write_text(
        ",".join(REAL_HEADERS) + "\n" + ",".join(_real_row())
    )
    registry_path = tmp_path / "participants.csv"
    registry_path.write_text("short_name,name,duns_number\nXSARAC,REAL NAME LLC,123\n")

    monkeypatch.setattr(ingestion, "BULK_AUCTION_DIR", bulk_dir)
    monkeypatch.setattr(ingestion, "PARTICIPANT_REGISTRY_PATH", registry_path)

    records, source, warning = ingestion.load_bulk_real_auction_data()
    assert source == ingestion.SOURCE_CSV
    assert len(records) == 1
    assert records[0]["participant"] == "REAL NAME LLC"


def test_map_row_returns_none_for_truncated_row_instead_of_crashing():
    truncated_row = _real_row()[:5]  # fewer fields than REAL_HEADERS has columns
    assert ingestion._map_row(REAL_HEADERS, truncated_row) is None
