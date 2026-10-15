"""Scout agent scorecard and graduation gate (PLAN section 9.4 / 9.6). Pure.

A closed trade's result is measured in R: net P&L after fees over the planned risk ((entry - stop) x qty).
Lanes are compared on mean R per trade, and the agent against its random twins with a DATE-CLUSTERED
bootstrap: trades opened on the same session share the same market, so sessions (not trades) are resampled.
The graduation gate is preregistered: >= 40 closed agent trades, >= 8 weeks since the sample start, agent net
P&L > 0 after fees, and the 95% lower bound of (agent mean R - random mean R) above 0. Anything less is
"no proven edge". Passing the gate unlocks nothing by itself - the next step (paper approval cards) is the
user's decision.
"""
from __future__ import annotations

import datetime as dt
import random as _random
from dataclasses import dataclass

GATE_VERSION = "scout-agent-gate-v1"


@dataclass(frozen=True)
class GateRule:
    min_closed: int = 40
    min_weeks: int = 8
    min_lower_bound: float = 0.0
    resamples: int = 2000
    seed: int = 20261014


def r_multiple(e: dict) -> float | None:
    """Net P&L / planned risk for a closed entry dict (entry_dict shape)."""
    try:
        qty, entry, stop, net = float(e["qty"]), float(e["entryPrice"]), float(e["stopPrice"]), float(e["netPnl"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = (entry - stop) * qty
    return net / risk if risk > 0 else None


def lane_stats(closed: list[dict]) -> dict:
    rs = [r for r in (r_multiple(e) for e in closed) if r is not None]
    net = sum(float(e.get("netPnl") or 0) for e in closed)
    wins = sum(1 for e in closed if float(e.get("netPnl") or 0) > 0)
    ex = [float((e.get("case") or {}).get("excessVsSpy")) for e in closed
          if (e.get("case") or {}).get("excessVsSpy") is not None]
    return {"closed": len(closed), "netPnl": round(net, 2), "hitRate": round(wins / len(closed), 4) if closed else None,
            "meanR": round(sum(rs) / len(rs), 4) if rs else None, "totalR": round(sum(rs), 3) if rs else 0.0,
            "meanExcessVsSpy": round(sum(ex) / len(ex), 5) if ex else None, "withSpy": len(ex)}


def clustered_diff(a: list[dict], b: list[dict], *, resamples: int = 2000, seed: int = 1) -> dict:
    """Mean R of `a` minus mean R of `b`, with a 95% interval from resampling entry SESSIONS."""
    by: dict[str, tuple[list[float], list[float]]] = {}
    for e in a:
        r = r_multiple(e)
        if r is not None:
            by.setdefault(str(e.get("entryDate")), ([], []))[0].append(r)
    for e in b:
        r = r_multiple(e)
        if r is not None:
            by.setdefault(str(e.get("entryDate")), ([], []))[1].append(r)
    days = sorted(by)
    xa = [r for d in days for r in by[d][0]]
    xb = [r for d in days for r in by[d][1]]
    if not xa or not xb:
        return {"diff": None, "lo": None, "hi": None, "sessions": len(days), "nA": len(xa), "nB": len(xb)}
    diff = sum(xa) / len(xa) - sum(xb) / len(xb)
    rng = _random.Random(seed)
    sims = []
    for _ in range(max(100, resamples)):
        pick = [days[rng.randrange(len(days))] for _ in days]
        sa = [r for d in pick for r in by[d][0]]
        sb = [r for d in pick for r in by[d][1]]
        if sa and sb:
            sims.append(sum(sa) / len(sa) - sum(sb) / len(sb))
    sims.sort()
    lo = sims[int(0.025 * (len(sims) - 1))] if sims else None
    hi = sims[int(0.975 * (len(sims) - 1))] if sims else None
    return {"diff": round(diff, 4), "lo": None if lo is None else round(lo, 4),
            "hi": None if hi is None else round(hi, 4), "sessions": len(days), "nA": len(xa), "nB": len(xb)}


def gate(agent_closed: list[dict], random_closed: list[dict], *, start: str, today: str,
         rule: GateRule = GateRule()) -> dict:
    stats = lane_stats(agent_closed)
    weeks = (dt.date.fromisoformat(today) - dt.date.fromisoformat(start)).days / 7.0 if start else 0.0
    cmp = clustered_diff(agent_closed, random_closed, resamples=rule.resamples, seed=rule.seed)
    checks = [
        {"name": "closed trades", "need": f">= {rule.min_closed}", "have": stats["closed"],
         "ok": stats["closed"] >= rule.min_closed},
        {"name": "weeks of sample", "need": f">= {rule.min_weeks}", "have": round(weeks, 1),
         "ok": weeks >= rule.min_weeks},
        {"name": "agent net P&L after fees", "need": "> 0", "have": stats["netPnl"], "ok": stats["netPnl"] > 0},
        {"name": "agent minus random, mean R, 95% lower bound (date-clustered)", "need": f"> {rule.min_lower_bound:g}",
         "have": cmp["lo"], "ok": cmp["lo"] is not None and cmp["lo"] > rule.min_lower_bound},
    ]
    passed = all(c["ok"] for c in checks)
    return {"version": GATE_VERSION, "start": start, "today": today, "passed": passed,
            "verdict": "passed - eligible for the user's paper decision" if passed else "no proven edge yet",
            "checks": checks, "agentVsRandom": cmp, "agent": stats}
