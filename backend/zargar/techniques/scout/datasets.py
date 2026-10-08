"""SEC "Insider Transactions Data Sets" (Form 3/4/5, quarterly ZIP of TSVs) -> trade rows.

https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets - one
~5-10 MB ZIP per quarter back to 2006q1 (verified 2026-10-07). It carries FILING_DATE but
NOT the acceptance time; `scout_backfill --enrich` stamps acceptance from the SGML header
for the filings the screens care about. Pure over a local ZIP path (streams one TSV at a
time; the caller downloads).

Row identity matches the daily-index parser: `row_key = accession:seq` where seq is the
document-order index of the non-derivative transaction (NONDERIV_TRANS_SK ranked within the
accession across ALL codes - SKs are assigned in document order).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from collections import defaultdict
from typing import Iterator

from .form4 import OPEN_MARKET_CODES, clean_ticker

csv.field_size_limit(10_000_000)

_MON = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                    "NOV", "DEC"), start=1)}


def ds_date(s: str | None) -> str | None:
    """'28-SEP-2026' -> '2026-09-28' (also accepts ISO)."""
    if not s:
        return None
    s = s.strip()
    try:
        if len(s) == 11 and s[2] == "-":
            return dt.date(int(s[7:]), _MON[s[3:6].upper()], int(s[:2])).isoformat()
        return dt.date.fromisoformat(s[:10]).isoformat()
    except (KeyError, ValueError):
        return None


def _f(s: str | None) -> float | None:
    if s is None or s.strip() == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _rows(z: zipfile.ZipFile, name: str) -> Iterator[dict]:
    with z.open(name) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
                                  delimiter="\t", quoting=csv.QUOTE_NONE)


def quarter_name(year: int, q: int) -> str:
    return f"{year}q{q}"


def quarters_between(since: dt.date, until: dt.date) -> list[tuple[int, int]]:
    out = []
    y, q = since.year, (since.month - 1) // 3 + 1
    while (y, q) <= (until.year, (until.month - 1) // 3 + 1):
        out.append((y, q))
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def parse_quarter(path: str, *, codes: tuple[str, ...] = OPEN_MARKET_CODES,
                  forms: tuple[str, ...] = ("4", "4/A"), since: str | None = None) -> tuple[list[dict], list[dict]]:
    """-> (filings, trade_rows). Filings: one per accession of an accepted form type
    (with any open-market row or not - the ledger records what was seen)."""
    z = zipfile.ZipFile(path)
    subs: dict[str, dict] = {}
    for r in _rows(z, "SUBMISSION.tsv"):
        if r.get("DOCUMENT_TYPE") not in forms:
            continue
        filed = ds_date(r.get("FILING_DATE"))
        if since and filed and filed < since:
            continue
        subs[r["ACCESSION_NUMBER"]] = {
            "accession": r["ACCESSION_NUMBER"], "form_type": r["DOCUMENT_TYPE"],
            "issuer_cik": (r.get("ISSUERCIK") or "").lstrip("0") or "0",
            "ticker": clean_ticker(r.get("ISSUERTRADINGSYMBOL")), "filed_date": filed,
        }
    owners: dict[str, list[dict]] = defaultdict(list)
    for r in _rows(z, "REPORTINGOWNER.tsv"):
        acc = r["ACCESSION_NUMBER"]
        if acc not in subs:
            continue
        rel = {p.strip().lower() for p in (r.get("RPTOWNER_RELATIONSHIP") or "").split(",")}
        owners[acc].append({
            "insider_cik": (r.get("RPTOWNERCIK") or "").lstrip("0") or "0", "insider_name": r.get("RPTOWNERNAME"),
            "is_director": "director" in rel, "is_officer": "officer" in rel,
            "is_ten_pct": "tenpercentowner" in rel, "is_other": "other" in rel,
            "officer_title": (r.get("RPTOWNER_TITLE") or None),
        })
    trans: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for r in _rows(z, "NONDERIV_TRANS.tsv"):
        acc = r["ACCESSION_NUMBER"]
        if acc not in subs:
            continue
        try:
            sk = int(r.get("NONDERIV_TRANS_SK") or 0)
        except ValueError:
            sk = 0
        trans[acc].append((sk, r))
    out: list[dict] = []
    for acc, lst in trans.items():
        lst.sort(key=lambda p: p[0])
        s = subs[acc]
        for seq, (_sk, r) in enumerate(lst):
            code = (r.get("TRANS_CODE") or "").strip()
            tdate = ds_date(r.get("TRANS_DATE"))
            if code not in codes or not tdate:
                continue
            shares, price = _f(r.get("TRANS_SHARES")), _f(r.get("TRANS_PRICEPERSHARE"))
            value = round(shares * price, 2) if shares is not None and price is not None else None
            for o in owners.get(acc, []):
                out.append({
                    "accession": acc, "row_key": f"{acc}:{seq}", "form_type": s["form_type"],
                    "issuer_cik": s["issuer_cik"], "ticker": s["ticker"], **o,
                    "security_title": r.get("SECURITY_TITLE"), "trans_date": tdate, "trans_code": code,
                    "acq_disp": r.get("TRANS_ACQUIRED_DISP_CD") or None, "shares": shares, "price": price,
                    "value": value, "direct_indirect": r.get("DIRECT_INDIRECT_OWNERSHIP") or None,
                    "filed_date": s["filed_date"], "acceptance_ts": None, "source": "dataset",
                })
    z.close()
    return list(subs.values()), out
