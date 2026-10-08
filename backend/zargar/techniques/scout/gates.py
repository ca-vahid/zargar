"""Preregistered gates (PLAN.md 2.2) - pure verdicts over facts the service gathered.

Every gate answers pass | fail | unknown (+ value, threshold, why). Missing data is
UNKNOWN, never a silent pass; a candidate is `pass` only when every enabled gate passed,
`fail` when any gate failed, else `unknown`. A threshold of None / <= 0 turns a numeric
gate off (`off`), which never blocks and is shown as such.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

PASS, FAIL, UNKNOWN, OFF = "pass", "fail", "unknown", "off"


def verdict(status: str, why: str, *, value=None, threshold=None) -> dict:
    return {"status": status, "value": value, "threshold": threshold, "why": why}


@dataclass(frozen=True)
class GateParams:
    min_price: float = 5.0
    min_adv_usd: float = 5_000_000.0
    adv_days: int = 20
    max_spread_pct: float = 0.5
    min_market_cap_usd: float = 300_000_000.0
    no_earnings_in_hold: bool = True        # S1 only
    corp_action_days: int = 183
    tips_mention_days: int = 5


def _off(threshold) -> bool:
    return threshold is None or (isinstance(threshold, (int, float)) and threshold <= 0)


def gate_price(close: float | None, p: GateParams) -> dict:
    if _off(p.min_price):
        return verdict(OFF, "gate off", threshold=p.min_price)
    if close is None or close <= 0:
        return verdict(UNKNOWN, "no daily close before the signal", threshold=p.min_price)
    ok = close >= p.min_price
    return verdict(PASS if ok else FAIL, f"last close ${close:.2f} {'>=' if ok else '<'} ${p.min_price:g}",
                   value=round(close, 4), threshold=p.min_price)


def gate_adv(daily: Sequence[tuple[float, float]] | None, p: GateParams) -> dict:
    """`daily` = [(close, volume)] for the sessions BEFORE the signal, oldest first."""
    if _off(p.min_adv_usd):
        return verdict(OFF, "gate off", threshold=p.min_adv_usd)
    if not daily or len(daily) < p.adv_days:
        n = len(daily or [])
        return verdict(UNKNOWN, f"only {n} of {p.adv_days} sessions of history", threshold=p.min_adv_usd)
    last = daily[-p.adv_days:]
    adv = sum(c * v for c, v in last) / len(last)
    ok = adv >= p.min_adv_usd
    return verdict(PASS if ok else FAIL, f"{p.adv_days}-day avg dollar volume ${adv / 1e6:.2f}M "
                   f"{'>=' if ok else '<'} ${p.min_adv_usd / 1e6:g}M", value=round(adv, 0), threshold=p.min_adv_usd)


def gate_spread(spread_pct: float | None, p: GateParams, *, pending_why: str | None = None) -> dict:
    """Quoted spread at entry, % of mid. Unknown until the entry session's quotes exist."""
    if _off(p.max_spread_pct):
        return verdict(OFF, "gate off", threshold=p.max_spread_pct)
    if spread_pct is None:
        return verdict(UNKNOWN, pending_why or "no quote history at entry", threshold=p.max_spread_pct)
    ok = spread_pct <= p.max_spread_pct
    return verdict(PASS if ok else FAIL, f"entry spread {spread_pct:.3f}% {'<=' if ok else '>'} {p.max_spread_pct:g}%",
                   value=round(spread_pct, 4), threshold=p.max_spread_pct)


def gate_market_cap(mcap: float | None, p: GateParams, *, why_unknown: str | None = None) -> dict:
    if _off(p.min_market_cap_usd):
        return verdict(OFF, "gate off", threshold=p.min_market_cap_usd)
    if mcap is None or mcap <= 0:
        return verdict(UNKNOWN, why_unknown or "no shares-outstanding fact", threshold=p.min_market_cap_usd)
    ok = mcap >= p.min_market_cap_usd
    return verdict(PASS if ok else FAIL, f"market cap ${mcap / 1e6:,.0f}M {'>=' if ok else '<'} "
                   f"${p.min_market_cap_usd / 1e6:,.0f}M", value=round(mcap, 0), threshold=p.min_market_cap_usd)


def gate_earnings_in_hold(entry_date: str | None, exit_date: str | None, earnings_dates: Iterable[str] | None,
                          p: GateParams, *, source: str = "") -> dict:
    """S1: no scheduled earnings between entry and the time-stop exit (inclusive)."""
    if not p.no_earnings_in_hold:
        return verdict(OFF, "gate off")
    if not entry_date or not exit_date:
        return verdict(UNKNOWN, "no entry/exit window")
    if earnings_dates is None:
        return verdict(UNKNOWN, "no earnings date source for this symbol")
    inside = sorted(d for d in earnings_dates if entry_date <= d <= exit_date)
    src = f" ({source})" if source else ""
    if inside:
        return verdict(FAIL, f"earnings {inside[0]} inside the hold {entry_date}..{exit_date}{src}", value=inside[0])
    return verdict(PASS, f"no earnings in {entry_date}..{exit_date}{src}")


def gate_corporate_actions(actions: Sequence[Mapping] | None, signal_date: str, p: GateParams) -> dict:
    """No reverse split / ticker (name) change in the prior `corp_action_days` (best effort)."""
    if _off(p.corp_action_days):
        return verdict(OFF, "gate off")
    if actions is None:
        return verdict(UNKNOWN, "corporate-actions source unavailable")
    lo = (dt.date.fromisoformat(signal_date) - dt.timedelta(days=p.corp_action_days)).isoformat()
    hits = sorted((a for a in actions if lo <= str(a.get("date") or "")[:10] <= signal_date),
                  key=lambda a: str(a.get("date")))
    if hits:
        a = hits[-1]
        return verdict(FAIL, f"{a.get('type')} on {a.get('date')} within {p.corp_action_days} days", value=a)
    return verdict(PASS, f"no reverse split / symbol change since {lo}")


def gate_tips_mention(mentions: Sequence[Mapping] | None, p: GateParams) -> dict:
    """Not mentioned by a Tips source in the prior `tips_mention_days` days (keeps Scout
    independent of Tips)."""
    if _off(p.tips_mention_days):
        return verdict(OFF, "gate off")
    if mentions is None:
        return verdict(UNKNOWN, "tips signal table unreadable")
    if mentions:
        srcs = sorted({str(m.get("source") or "?") for m in mentions})
        return verdict(FAIL, f"mentioned by Tips source(s) {', '.join(srcs)} in the prior {p.tips_mention_days} days",
                       value=len(mentions))
    return verdict(PASS, f"no Tips mention in the prior {p.tips_mention_days} days", value=0)


def overall(gates: Mapping[str, Mapping]) -> str:
    statuses = [g.get("status") for g in gates.values()]
    if FAIL in statuses:
        return FAIL
    if UNKNOWN in statuses:
        return UNKNOWN
    return PASS
