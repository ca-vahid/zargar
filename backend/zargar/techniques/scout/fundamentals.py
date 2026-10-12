"""Company fundamentals from the SEC's XBRL `companyfacts` JSON - pure, no I/O.

The dossier's numbers come from here and nowhere else, so every rule is conservative:

- a metric is the FIRST tag of its candidate list that has data; older tags only fill periods the
  preferred one lacks (companies switch tags over the years);
- one value per (start, end) period: the most recently FILED statement of it (restatements win);
- a quarter is a reported ~3-month period, or the DIFFERENCE of two cumulative periods that share a
  start (cash flow is filed year-to-date; Q4 is never filed on its own), or FY minus its three quarters;
- trailing twelve months = the last four quarters only when they are contiguous; otherwise the last
  fiscal year, and the label says so;
- a missing number stays None - nothing is estimated, interpolated or carried forward.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

# metric -> candidate tags, preferred first (us-gaap unless prefixed)
DURATION_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "ifrs-full:Revenue"),
    "grossProfit": ("GrossProfit", "ifrs-full:GrossProfit"),
    "operatingIncome": ("OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"),
    "netIncome": ("NetIncomeLoss", "ProfitLoss", "ifrs-full:ProfitLoss"),
    "operatingCashFlow": ("NetCashProvidedByUsedInOperatingActivities",
                          "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
                          "ifrs-full:CashFlowsFromUsedInOperatingActivities"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
}
INSTANT_TAGS: dict[str, tuple[str, ...]] = {
    "cash": ("CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "ifrs-full:CashAndCashEquivalents"),
    "longTermDebt": ("LongTermDebt", "LongTermDebtNoncurrent", "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings"),
    "assets": ("Assets", "ifrs-full:Assets"),
    "liabilities": ("Liabilities", "ifrs-full:Liabilities"),
    "equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "ifrs-full:Equity"),
}
SHARE_TAGS = ("WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic")
EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")

QUARTER_DAYS = (75, 105)
YEAR_DAYS = (350, 380)


def _d(s: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _days(a: str, b: str) -> int:
    da, db = _d(a), _d(b)
    return (db - da).days if da and db else -1


def _is(span: tuple[int, int], days: int) -> bool:
    return span[0] <= days <= span[1]


def _tag_units(facts: Mapping, tag: str) -> Mapping:
    ns, _, name = tag.rpartition(":")
    return (((facts or {}).get(ns or "us-gaap") or {}).get(name) or {}).get("units") or {}


def pick_unit(units: Mapping, prefer: str | None = None) -> str | None:
    """USD when present (or `prefer`), else the unit with the most rows."""
    if not units:
        return None
    for u in (prefer, "USD"):
        if u and units.get(u):
            return u
    return max(units, key=lambda u: len(units[u] or []))


def _rows(facts: Mapping, tag: str, unit: str | None) -> tuple[list[dict], str | None]:
    units = _tag_units(facts, tag)
    u = pick_unit(units, unit)
    return (list(units.get(u) or []) if u else []), u


def duration_periods(rows: Iterable[Mapping]) -> dict[tuple[str, str], float]:
    """(start, end) -> value, the most recently filed statement of each period."""
    best: dict[tuple[str, str], tuple[str, float]] = {}
    for r in rows:
        s, e, v = r.get("start"), r.get("end"), r.get("val")
        if not s or not e or v is None or _d(s) is None or _d(e) is None:
            continue
        filed = str(r.get("filed") or "")
        k = (str(s)[:10], str(e)[:10])
        if k not in best or filed >= best[k][0]:
            best[k] = (filed, float(v))
    return {k: v for k, (_, v) in best.items()}


def instant_points(rows: Iterable[Mapping]) -> dict[str, float]:
    """end date -> value for balance-sheet (instant) facts, most recently filed."""
    best: dict[str, tuple[str, float]] = {}
    for r in rows:
        e, v = r.get("end"), r.get("val")
        if r.get("start") or not e or v is None or _d(e) is None:
            continue
        filed = str(r.get("filed") or "")
        k = str(e)[:10]
        if k not in best or filed >= best[k][0]:
            best[k] = (filed, float(v))
    return {k: v for k, (_, v) in best.items()}


def quarters_from(periods: Mapping[tuple[str, str], float]) -> dict[str, dict]:
    """quarter end -> {value, start, derived}. Reported 3-month periods first; then differences of
    cumulative periods sharing a start; then FY minus its three quarters."""
    out: dict[str, dict] = {}
    for (s, e), v in periods.items():
        if _is(QUARTER_DAYS, _days(s, e)):
            out[e] = {"value": v, "start": s, "derived": False}
    by_start: dict[str, list[tuple[str, float]]] = {}
    for (s, e), v in periods.items():
        by_start.setdefault(s, []).append((e, v))
    for s, items in by_start.items():
        items.sort()
        for (e0, v0), (e1, v1) in zip(items, items[1:]):
            if e1 not in out and _is(QUARTER_DAYS, _days(e0, e1)):
                out[e1] = {"value": v1 - v0, "start": e0, "derived": True}
    for (s, e), v in periods.items():
        if e in out or not _is(YEAR_DAYS, _days(s, e)):
            continue
        inside = [q for qe, q in out.items() if s < qe < e and q["start"] >= _shift(s, -5)]
        if len(inside) == 3:
            out[e] = {"value": v - sum(q["value"] for q in inside), "start": max(qe for qe in out if s < qe < e),
                      "derived": True}
    return dict(sorted(out.items()))


def _shift(day: str, n: int) -> str:
    d = _d(day)
    return (d + dt.timedelta(days=n)).isoformat() if d else day


def annuals_from(periods: Mapping[tuple[str, str], float]) -> dict[str, float]:
    return dict(sorted((e, v) for (s, e), v in periods.items() if _is(YEAR_DAYS, _days(s, e))))


def contiguous_tail(quarters: Mapping[str, dict], n: int = 4) -> list[str] | None:
    """The last `n` quarter ends when each follows the previous by about three months."""
    ends = sorted(quarters)[-n:]
    if len(ends) < n:
        return None
    for a, b in zip(ends, ends[1:]):
        if not _is(QUARTER_DAYS, _days(a, b)):
            return None
    return ends


@dataclass
class Series:
    metric: str
    tag: str | None = None
    unit: str | None = None
    quarters: dict[str, dict] = field(default_factory=dict)      # end -> {value, start, derived}
    annuals: dict[str, float] = field(default_factory=dict)      # FY end -> value
    points: dict[str, float] = field(default_factory=dict)       # instants: end -> value

    def ttm(self) -> tuple[float | None, str]:
        """(value, basis). Four contiguous quarters ending at the latest one, else the last fiscal year."""
        tail = contiguous_tail(self.quarters)
        last_fy = max(self.annuals) if self.annuals else None
        if tail and (last_fy is None or tail[-1] >= last_fy):
            return sum(self.quarters[e]["value"] for e in tail), f"four quarters to {tail[-1]}"
        if last_fy:
            return self.annuals[last_fy], f"fiscal year to {last_fy}"
        return None, "not reported"

    def latest_point(self) -> tuple[str | None, float | None]:
        if not self.points:
            return None, None
        e = max(self.points)
        return e, self.points[e]

    def yoy(self, end: str) -> float | None:
        """Growth of the quarter ending `end` over the quarter ending about a year earlier."""
        cur = self.quarters.get(end)
        if not cur:
            return None
        for e, q in self.quarters.items():
            if _is((350, 380), _days(e, end)) and q["value"]:
                return cur["value"] / q["value"] - 1.0 if q["value"] > 0 else None
        return None


def duration_series(facts: Mapping, metric: str, tags: Iterable[str], unit: str | None = None, *,
                    additive: bool = True) -> Series:
    """`additive=False` (per-share figures, weighted share counts): only REPORTED quarters count - a
    difference of two cumulative averages means nothing."""
    s = Series(metric=metric)
    merged: dict[tuple[str, str], float] = {}
    for tag in tags:
        rows, u = _rows(facts, tag, unit or s.unit)
        if not rows:
            continue
        if s.tag is None:
            s.tag, s.unit = tag, u
        elif u != s.unit:
            continue                                   # never mix currencies
        for k, v in duration_periods(rows).items():
            merged.setdefault(k, v)
    s.quarters, s.annuals = quarters_from(merged), annuals_from(merged)
    if not additive:
        s.quarters = {e: q for e, q in s.quarters.items() if not q["derived"]}
    return s


def instant_series(facts: Mapping, metric: str, tags: Iterable[str], unit: str | None = None) -> Series:
    s = Series(metric=metric)
    for tag in tags:
        rows, u = _rows(facts, tag, unit or s.unit)
        pts = instant_points(rows)
        if not pts:
            continue
        if s.tag is None:
            s.tag, s.unit = tag, u
        elif u != s.unit:
            continue
        for k, v in pts.items():
            s.points.setdefault(k, v)
    s.points = dict(sorted(s.points.items()))
    return s


def build(companyfacts: Mapping) -> dict[str, Series]:
    """Every metric's series from one companyfacts document. The reporting currency is whatever revenue
    (else net income) is tagged in; metrics in another currency are left empty."""
    facts = (companyfacts or {}).get("facts") or {}
    out: dict[str, Series] = {}
    rev = duration_series(facts, "revenue", DURATION_TAGS["revenue"])
    ni = duration_series(facts, "netIncome", DURATION_TAGS["netIncome"])
    unit = rev.unit or ni.unit
    out["revenue"], out["netIncome"] = rev, (ni if ni.unit == unit or not unit else Series("netIncome"))
    for m, tags in DURATION_TAGS.items():
        if m not in out:
            out[m] = duration_series(facts, m, tags, unit)
    for m, tags in INSTANT_TAGS.items():
        out[m] = instant_series(facts, m, tags, unit)
    out["dilutedShares"] = duration_series(facts, "dilutedShares", SHARE_TAGS, "shares", additive=False)
    eps_unit = f"{unit}/shares" if unit else None
    out["eps"] = duration_series(facts, "eps", EPS_TAGS, eps_unit, additive=False)
    return out


def currency(series: Mapping[str, Series]) -> str | None:
    return series["revenue"].unit or series["netIncome"].unit
