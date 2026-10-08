"""EDGAR parsing - pure functions over text (no I/O). Verified first-hand 2026-10-07
(docs/techniques/scout/DATA-NOTES.md):

- the full submission `.txt` = SGML header (`<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS`, ET wall
  clock) + the ownershipDocument XML between `<XML>` and `</XML>`;
- the header-only `.hdr.sgml` carries the same acceptance stamp plus `<ITEMS>` for 8-Ks;
- the daily form index is fixed-width text; a Form 4 is listed once per party (issuer AND
  each reporting owner), so rows dedupe on the accession number;
- booleans in the XML are `1/0` or `true/false`; prices may be absent (gifts, awards).
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET_XML
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

OPEN_MARKET_CODES = ("P", "S")          # the only codes Scout stores (CMP + S1 need nothing else)
FORM4_TYPES = ("4", "4/A")

_ACC_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")
_INDEX_LINE = re.compile(
    r"^(?P<form>\S+(?: \S+)?)\s{2,}(?P<company>.+?)\s{2,}(?P<cik>\d+)\s+(?P<date>\d{8})\s+"
    r"(?P<path>edgar/data/\S+\.txt)\s*$")


@dataclass(frozen=True)
class IndexEntry:
    form_type: str
    company: str
    cik: str
    filed_date: str        # YYYY-MM-DD
    path: str              # edgar/data/<cik>/<accession>.txt
    accession: str


@dataclass
class Owner:
    cik: str
    name: str | None
    is_director: bool = False
    is_officer: bool = False
    is_ten_pct: bool = False
    is_other: bool = False
    officer_title: str | None = None


@dataclass
class Transaction:
    seq: int
    security_title: str | None
    trans_date: str | None
    code: str | None
    shares: float | None
    price: float | None
    acq_disp: str | None
    direct_indirect: str | None

    @property
    def value(self) -> float | None:
        if self.shares is None or self.price is None:
            return None
        return round(self.shares * self.price, 2)


@dataclass
class Form4:
    accession: str
    form_type: str
    acceptance_ts: dt.datetime | None
    filed_date: str | None
    issuer_cik: str
    issuer_name: str | None
    ticker: str | None
    owners: list[Owner] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)


# --------------------------------------------------------------------------- times
def parse_acceptance(stamp: str | None) -> dt.datetime | None:
    """`20261006090030` (EDGAR header, ET wall clock) -> aware datetime in ET."""
    if not stamp:
        return None
    s = stamp.strip()
    if not re.fullmatch(r"\d{14}", s):
        return None
    naive = dt.datetime.strptime(s, "%Y%m%d%H%M%S")
    return naive.replace(tzinfo=ET)


def submissions_json_acceptance(value: str | None) -> dt.datetime | None:
    """The `acceptanceDateTime` of data.sec.gov/submissions JSON is NOT the UTC instant its
    `Z` claims: checked 2026-10-07 against the SGML headers of three filings (AAPL 8-K
    header 16:30:28 ET -> JSON 2026-07-31T00:30:28Z; AAPL winter 16:30:33 EST -> 02:30:33Z;
    BGS 08:00:45 EDT -> 16:00:45Z) the JSON value is the true UTC instant PLUS the ET UTC
    offset again (the ET wall time converted twice). Undo it: true UTC = json - |offset|.
    The header remains the authority; this is a fast path for history only."""
    if not value:
        return None
    try:
        claimed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=dt.timezone.utc)
    # offset of ET at (approximately) the true instant; DST edges are 02:00 Sundays - no filings
    guess = claimed - dt.timedelta(hours=4)
    off = -guess.astimezone(ET).utcoffset()          # +4h (EDT) / +5h (EST)
    return (claimed - off).astimezone(ET)


# --------------------------------------------------------------------------- index
def parse_daily_index(text: str, forms: tuple[str, ...] | None = FORM4_TYPES) -> list[IndexEntry]:
    """`form.YYYYMMDD.idx` -> entries, deduped on accession (first listing wins)."""
    out: list[IndexEntry] = []
    seen: set[str] = set()
    body = False
    for line in text.splitlines():
        if not body:
            if line.startswith("-----"):
                body = True
            continue
        m = _INDEX_LINE.match(line.rstrip())
        if not m:
            continue
        form = m.group("form").strip()
        if forms is not None and form not in forms:
            continue
        acc_m = _ACC_RE.search(m.group("path"))
        if not acc_m:
            continue
        acc = acc_m.group(1)
        if acc in seen:
            continue
        seen.add(acc)
        d = m.group("date")
        out.append(IndexEntry(form_type=form, company=m.group("company").strip(), cik=m.group("cik"),
                              filed_date=f"{d[:4]}-{d[4:6]}-{d[6:]}", path=m.group("path"), accession=acc))
    return out


# --------------------------------------------------------------------------- header
def parse_header(text: str) -> dict:
    """SGML header (from `.hdr.sgml` or the top of a full `.txt`) -> facts."""
    def one(tag: str) -> str | None:
        m = re.search(rf"<{tag}>([^\r\n<]*)", text)
        return m.group(1).strip() if m else None

    items = re.findall(r"<ITEMS>([^\r\n<]*)", text)
    acc = one("ACCESSION-NUMBER")
    if acc is None:
        m = re.search(r"ACCESSION NUMBER:\s*(\S+)", text)
        acc = m.group(1) if m else None
    form = one("TYPE")
    if form is None:
        m = re.search(r"CONFORMED SUBMISSION TYPE:\s*(\S+)", text)
        form = m.group(1) if m else None
    filed = one("FILING-DATE")
    if filed is None:
        m = re.search(r"FILED AS OF DATE:\s*(\d{8})", text)
        filed = m.group(1) if m else None
    if not items:
        m = re.findall(r"ITEM INFORMATION:\s*([^\r\n]+)", text)
        items = m
    return {
        "accession": acc,
        "form_type": form,
        "acceptance_ts": parse_acceptance(one("ACCEPTANCE-DATETIME")),
        "filed_date": f"{filed[:4]}-{filed[4:6]}-{filed[6:]}" if filed and len(filed) == 8 else None,
        "items": [i.strip() for i in items if i.strip()],
    }


# --------------------------------------------------------------------------- Form 4 XML
def _bool(el) -> bool:
    if el is None or el.text is None:
        return False
    return el.text.strip().lower() in ("1", "true")


def _text(node, path: str) -> str | None:
    if node is None:
        return None
    el = node.find(path)
    if el is None or el.text is None:
        return None
    s = el.text.strip()
    return s or None


def _num(node, path: str) -> float | None:
    s = _text(node, path)
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def clean_ticker(raw: str | None) -> str | None:
    """`issuerTradingSymbol` is free text: 'NONE', 'N/A', 'ABC, ABCD', 'brk.b'. Keep the
    first token, upper-cased; refuse placeholders."""
    if not raw:
        return None
    tok = re.split(r"[,;/\s]+", raw.strip())[0].upper()
    if tok in ("", "NONE", "N/A", "NA", "-"):
        return None
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", tok):
        return None
    return tok


def parse_form4(text: str) -> Form4:
    """A full submission `.txt` (or bare ownershipDocument XML) -> Form4."""
    hdr = parse_header(text)
    m = re.search(r"<XML>\s*(.*?)\s*</XML>", text, re.S)
    xml = m.group(1) if m else text
    xml = xml[xml.find("<ownershipDocument"):] if "<ownershipDocument" in xml else xml
    root = ET_XML.fromstring(xml.strip())
    issuer = root.find("issuer")
    owners: list[Owner] = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        owners.append(Owner(
            cik=(_text(ro, "reportingOwnerId/rptOwnerCik") or "").lstrip("0") or "0",
            name=_text(ro, "reportingOwnerId/rptOwnerName"),
            is_director=_bool(rel.find("isDirector")) if rel is not None else False,
            is_officer=_bool(rel.find("isOfficer")) if rel is not None else False,
            is_ten_pct=_bool(rel.find("isTenPercentOwner")) if rel is not None else False,
            is_other=_bool(rel.find("isOther")) if rel is not None else False,
            officer_title=_text(rel, "officerTitle"),
        ))
    txs: list[Transaction] = []
    table = root.find("nonDerivativeTable")
    if table is not None:
        for i, t in enumerate(table.findall("nonDerivativeTransaction")):
            txs.append(Transaction(
                seq=i,
                security_title=_text(t, "securityTitle/value"),
                trans_date=_text(t, "transactionDate/value"),
                code=_text(t, "transactionCoding/transactionCode"),
                shares=_num(t, "transactionAmounts/transactionShares/value"),
                price=_num(t, "transactionAmounts/transactionPricePerShare/value"),
                acq_disp=_text(t, "transactionAmounts/transactionAcquiredDisposedCode/value"),
                direct_indirect=_text(t, "ownershipNature/directOrIndirectOwnership/value"),
            ))
    return Form4(
        accession=hdr["accession"] or "",
        form_type=hdr["form_type"] or (_text(root, "documentType") or "4"),
        acceptance_ts=hdr["acceptance_ts"],
        filed_date=hdr["filed_date"],
        issuer_cik=(_text(issuer, "issuerCik") or "").lstrip("0") or "0",
        issuer_name=_text(issuer, "issuerName"),
        ticker=clean_ticker(_text(issuer, "issuerTradingSymbol")),
        owners=owners,
        transactions=txs,
    )


def trade_rows(f: Form4, *, source: str = "daily", codes: tuple[str, ...] = OPEN_MARKET_CODES) -> list[dict]:
    """Form4 -> `scout_insider_trades` rows (one per open-market transaction x owner)."""
    rows: list[dict] = []
    for t in f.transactions:
        if (t.code or "") not in codes or not t.trans_date:
            continue
        for o in f.owners:
            rows.append({
                "accession": f.accession, "row_key": f"{f.accession}:{t.seq}", "form_type": f.form_type,
                "issuer_cik": f.issuer_cik, "ticker": f.ticker, "insider_cik": o.cik, "insider_name": o.name,
                "is_director": o.is_director, "is_officer": o.is_officer, "is_ten_pct": o.is_ten_pct,
                "is_other": o.is_other, "officer_title": o.officer_title, "security_title": t.security_title,
                "trans_date": t.trans_date[:10], "trans_code": t.code, "acq_disp": t.acq_disp,
                "shares": t.shares, "price": t.price, "value": t.value, "direct_indirect": t.direct_indirect,
                "filed_date": f.filed_date, "acceptance_ts": f.acceptance_ts, "source": source,
            })
    return rows
