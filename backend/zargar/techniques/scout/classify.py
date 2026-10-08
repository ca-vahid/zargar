"""Cohen-Malloy-Pomorski (2012, "Decoding Inside Information") routine/opportunistic filter.

At the START of calendar year Y, an insider is classified from PAST trades only:

- **routine**: traded in the same calendar month in each of Y-1, Y-2 and Y-3;
- **opportunistic**: traded at least once in each of Y-1, Y-2 and Y-3, but no month repeats
  across all three;
- **unclassified**: not enough history (missed a year, or our data coverage does not
  include all of Y-3) - tracked separately, never silently folded into either group.

"Traded" = an open-market purchase or sale (codes P/S) on Form 4. No look-ahead: a trade
counts only if it was KNOWN before Y began (filed_date <= Y-1-12-31; the transaction date
alone is used only when the filing date is missing). Pure: no I/O.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

ROUTINE = "routine"
OPPORTUNISTIC = "opportunistic"
UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class Classification:
    label: str
    reason: str
    year: int


def _known_by(row: Mapping, cutoff: str) -> bool:
    known = row.get("filed_date") or row.get("trans_date")
    return bool(known) and str(known)[:10] <= cutoff


def history_by_insider(trades: Iterable[Mapping], year: int, *, years: int = 3) -> dict[str, dict[int, set[int]]]:
    """insider -> {past year -> months traded}, only years Y-years..Y-1 and only rows known before Y."""
    cutoff = f"{year - 1}-12-31"
    lo = year - years
    out: dict[str, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    for r in trades:
        if (r.get("trans_code") or "") not in ("P", "S"):
            continue
        td = str(r.get("trans_date") or "")[:10]
        if len(td) != 10:
            continue
        y, m = int(td[:4]), int(td[5:7])
        if not (lo <= y <= year - 1) or not _known_by(r, cutoff):
            continue
        if r.get("filed_date") and td > str(r["filed_date"])[:10]:
            continue                                   # dated after its own filing: a filer typo
        out[str(r["insider_cik"])][y].add(m)
    return out


def classify_one(months_by_year: Mapping[int, set[int]], year: int, *, years: int = 3,
                 coverage_start: str | None = None) -> Classification:
    need_from = f"{year - years}-01-01"
    if coverage_start is None or coverage_start > need_from:
        return Classification(UNCLASSIFIED, f"data coverage starts {coverage_start or 'unknown'}, "
                                            f"classification for {year} needs {need_from}", year)
    past = [months_by_year.get(year - k, set()) for k in range(1, years + 1)]
    missing = [year - k for k, s in zip(range(1, years + 1), past) if not s]
    if missing:
        return Classification(UNCLASSIFIED, f"no open-market trade in {', '.join(map(str, missing))}", year)
    common = set.intersection(*past)
    if common:
        return Classification(ROUTINE, f"traded in month(s) {sorted(common)} in each of {year - years}..{year - 1}", year)
    return Classification(OPPORTUNISTIC, f"traded every year {year - years}..{year - 1}, no repeating month", year)


def classify_insiders(trades: Iterable[Mapping], year: int, *, years: int = 3,
                      coverage_start: str | None = None, insiders: Iterable[str] | None = None) -> dict[str, Classification]:
    """Classification of every insider seen (or of `insiders`) for calendar year `year`."""
    trades = list(trades)
    hist = history_by_insider(trades, year, years=years)
    who = set(insiders) if insiders is not None else ({str(r["insider_cik"]) for r in trades} | set(hist))
    return {cik: classify_one(hist.get(cik, {}), year, years=years, coverage_start=coverage_start) for cik in who}


def year_of(date_iso: str) -> int:
    return dt.date.fromisoformat(date_iso[:10]).year
