"""
Downloads real ERCOT CRR Monthly Auction Results (NP7-803-M) and the real
Market Participants List (NP12-215-ER) directly from ERCOT's public MIS
legacy servlet endpoints -- confirmed reachable and unauthenticated during
this project's 2026-09 real-data investigation, contradicting this
project's own earlier assumption (see domain.py's original docstring and
lessons_learned_and_future_work.md) that CRR auction data required a
browser session. Lesson 6 already in this project applies again: "an
earlier no is worth re-checking."

Run from backend/: `python scripts/fetch_real_ercot_data.py`

Idempotent: re-running only downloads auction months not already present
in data/raw/crr_auction/, so this is safe to run again next month after a
new auction posts. The participant registry is always re-downloaded and
overwritten (it's a single small file, refreshed daily by ERCOT).

Writes:
  data/raw/crr_auction/<YYYY-MM>_MarketResults.csv  (one per auction month)
  data/reference/participants.csv                    (short_name,name,duns_number)

Deliberately separate from ingestion.py's flat data/raw/*.csv tier (used by
the FastAPI backend's SQL->CSV->synthetic priority) -- see
ingestion.load_bulk_real_auction_data()'s docstring for why.
"""

from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from pathlib import Path

import requests

DOC_LIST_URL = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS"
DOWNLOAD_URL = "https://www.ercot.com/misdownload/servlets/mirDownload"
AUCTION_REPORT_TYPE_ID = 11201       # NP7-803-M, Monthly Auction Results
PARTICIPANT_REPORT_TYPE_ID = 21129   # NP12-215-ER, List of Market Participants
REQUEST_TIMEOUT = 60

DATA_DIR = Path(os.environ.get("CRR_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
AUCTION_OUT_DIR = DATA_DIR / "raw" / "crr_auction"
PARTICIPANTS_OUT_PATH = DATA_DIR / "reference" / "participants.csv"

_MONTH_NAME_RE = re.compile(r"^([A-Z]{3})(\d{4})MonthlyCRRAuctionResults$")
_MONTH_NUMBERS = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def list_documents(report_type_id: int, session: requests.Session) -> list[dict]:
    """Real, public, unauthenticated ERCOT MIS document list for a report
    type -- e.g. every currently-retained Monthly Auction Results zip."""
    resp = session.get(DOC_LIST_URL, params={"reportTypeId": report_type_id}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return [d["Document"] for d in data["ListDocsByRptTypeRes"]["DocumentList"]]


def month_key_from_friendly_name(friendly_name: str) -> str | None:
    """'OCT2026MonthlyCRRAuctionResults' -> '2026-10'. Returns None for any
    name that doesn't match this exact pattern (defensive against ERCOT
    changing its naming convention without notice)."""
    match = _MONTH_NAME_RE.match(friendly_name)
    if not match:
        return None
    month_abbr, year = match.groups()
    month_num = _MONTH_NUMBERS.get(month_abbr)
    if month_num is None:
        return None
    return f"{year}-{month_num}"


def download_document(doc_id: str, session: requests.Session) -> bytes:
    resp = session.get(DOWNLOAD_URL, params={"doclookupId": doc_id}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def extract_market_results_csv(zip_bytes: bytes) -> bytes:
    """Pulls just the Common_MarketResults_*.csv member out of a Monthly
    Auction Results zip -- the awarded-results file this project needs.
    The zip also contains AuctionBidsAndOffers/BaseLoading/
    BindingConstraint/SourceAndSinkShadowPrices files (and XML duplicates
    of everything), multiple times larger and not needed here, so they're
    never extracted to disk at all."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.startswith("Common_MarketResults_") and name.endswith(".csv"):
                return zf.read(name)
    raise ValueError("No Common_MarketResults_*.csv member found in this zip")


def extract_crrah_participants(xlsx_bytes: bytes) -> list[dict[str, str]]:
    """Pulls the CRRAH sheet (NAME, SHORT NAME, DUNS NUMBER columns) out of
    the real Market Participants List workbook."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
    try:
        ws = wb["CRRAH"]
        out = []
        header_seen = False
        for row in ws.iter_rows(values_only=True):
            if not header_seen:
                if row and row[0] == "NAME":
                    header_seen = True
                continue
            if not row or not row[0]:
                continue
            name, short_name, duns = row[0], row[1], row[2]
            out.append({
                "name": str(name).strip(),
                "short_name": str(short_name).strip(),
                "duns_number": str(duns).strip() if duns is not None else "",
            })
        return out
    finally:
        wb.close()


def fetch_auction_results(session: requests.Session | None = None) -> list[Path]:
    """Downloads every currently-retained real Monthly Auction Results file
    not already present locally. Returns the list of newly-written paths
    (empty if everything was already up to date)."""
    sess = session or requests.Session()
    AUCTION_OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for doc in list_documents(AUCTION_REPORT_TYPE_ID, sess):
        month_key = month_key_from_friendly_name(doc["FriendlyName"])
        if month_key is None:
            continue
        out_path = AUCTION_OUT_DIR / f"{month_key}_MarketResults.csv"
        if out_path.exists():
            continue
        zip_bytes = download_document(doc["DocID"], sess)
        csv_bytes = extract_market_results_csv(zip_bytes)
        out_path.write_bytes(csv_bytes)
        written.append(out_path)
        print(f"wrote {out_path} ({len(csv_bytes):,} bytes)")
    return written


def fetch_participant_registry(session: requests.Session | None = None) -> Path:
    """Downloads the current real Market Participants List and writes the
    CRRAH sheet as a small, plain CSV (short_name -> real company name)."""
    sess = session or requests.Session()
    docs = list_documents(PARTICIPANT_REPORT_TYPE_ID, sess)
    if not docs:
        raise RuntimeError("ERCOT returned no Market Participants List documents")
    latest = max(docs, key=lambda d: d["PublishDate"])
    xlsx_bytes = download_document(latest["DocID"], sess)
    rows = extract_crrah_participants(xlsx_bytes)

    PARTICIPANTS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PARTICIPANTS_OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["short_name", "name", "duns_number"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {PARTICIPANTS_OUT_PATH} ({len(rows)} participants)")
    return PARTICIPANTS_OUT_PATH


def main() -> None:
    fetch_auction_results()
    fetch_participant_registry()


if __name__ == "__main__":
    main()
