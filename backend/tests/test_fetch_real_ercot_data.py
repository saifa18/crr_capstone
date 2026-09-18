from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock

import pytest

from scripts import fetch_real_ercot_data as fetch


def test_month_key_from_friendly_name_parses_standard_pattern():
    assert fetch.month_key_from_friendly_name("OCT2026MonthlyCRRAuctionResults") == "2026-10"
    assert fetch.month_key_from_friendly_name("JAN2025MonthlyCRRAuctionResults") == "2025-01"


def test_month_key_from_friendly_name_returns_none_for_unrecognized_pattern():
    assert fetch.month_key_from_friendly_name("SomeOtherReport") is None


def _make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_extract_market_results_csv_finds_the_right_member():
    zip_bytes = _make_zip({
        "Common_AuctionBidsAndOffers_2026.OCT.Monthly.Auction_AUCTION.csv": b"irrelevant",
        "Common_MarketResults_2026.OCT.Monthly.Auction_AUCTION.csv": b"CRR_ID,Source\n1,HB_WEST\n",
    })
    csv_bytes = fetch.extract_market_results_csv(zip_bytes)
    assert csv_bytes == b"CRR_ID,Source\n1,HB_WEST\n"


def test_extract_market_results_csv_raises_if_missing():
    zip_bytes = _make_zip({"SomethingElse.csv": b"data"})
    with pytest.raises(ValueError, match="Common_MarketResults"):
        fetch.extract_market_results_csv(zip_bytes)


def test_list_documents_calls_correct_endpoint_and_parses_response():
    session = MagicMock()
    session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"ListDocsByRptTypeRes": {"DocumentList": [
            {"Document": {"DocID": "123", "FriendlyName": "OCT2026MonthlyCRRAuctionResults",
                          "PublishDate": "2026-09-17T08:00:00-05:00"}}
        ]}},
    )
    docs = fetch.list_documents(11201, session)
    assert docs == [{"DocID": "123", "FriendlyName": "OCT2026MonthlyCRRAuctionResults",
                     "PublishDate": "2026-09-17T08:00:00-05:00"}]
    assert session.get.call_args.kwargs["params"] == {"reportTypeId": 11201}


def test_fetch_auction_results_skips_already_downloaded_months(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "AUCTION_OUT_DIR", tmp_path)
    existing = tmp_path / "2026-10_MarketResults.csv"
    existing.write_text("already here")

    session = MagicMock()
    session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"ListDocsByRptTypeRes": {"DocumentList": [
            {"Document": {"DocID": "999", "FriendlyName": "OCT2026MonthlyCRRAuctionResults",
                          "PublishDate": "2026-09-17T08:00:00-05:00"}}
        ]}},
    )
    written = fetch.fetch_auction_results(session=session)
    assert written == []
    assert existing.read_text() == "already here"


def test_extract_crrah_participants_parses_sheet():
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    crrah = wb.create_sheet("CRRAH")
    crrah.append(["Some", "Header", "Junk"])
    crrah.append(["NAME", "SHORT NAME", "DUNS NUMBER"])
    crrah.append(["AES MARKETING AND TRADING LLC (CRRAH)", "XAESMT", "1187367255000"])
    buf = io.BytesIO()
    wb.save(buf)

    rows = fetch.extract_crrah_participants(buf.getvalue())
    assert rows == [{
        "name": "AES MARKETING AND TRADING LLC (CRRAH)",
        "short_name": "XAESMT",
        "duns_number": "1187367255000",
    }]
