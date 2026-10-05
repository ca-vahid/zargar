"""Tips v0.9 sizing (V5, 2026-10-05; plan docs/techniques/tip/research/2026-10-04-v09/PLAN.md §V5).

Pure helpers first, then the small DB readers the proposal path calls.

- V5.1 risk-first share sizing: qty = risk budget / stop distance, then capped by the notional budget (budgetPerTip,
  the free-cash glide, the capital cap, the source's open room - `_tip_budget`), the position-% cap and the per-name
  exposure. The card records every candidate and WHICH cap bound (`sizing.binding`). On a Practice book whose geometry
  gate enforces, the gate already derives the qty from the final stop - this module only labels it.
- V5.1 open-risk cap: sum of the book's open tip positions' remaining risk to their stops + this trade's planned risk
  <= `techniques.tip.max_open_risk_pct` of equity, else the card is refused on the record.
- V5.2 per-source grade + fractional Kelly: from the source's graded CLOSED positions in the PRIMARY book, after
  commissions, in R. Edge shrunk toward 0 by n/(n+k); Kelly risk fraction = shrunk mean R / E[R^2] (the small-bet
  log-growth optimum for arbitrary R outcomes); the card's risk = min(risk_pct, fraction x Kelly). A negative shrunk
  edge -> watch-only. `techniques.tip.source_kelly_mode` observe (journal what it would do) | enforce | off.
- V5.3 sector cap: lives in `entry_context` (the profile lookup) + `sector_refusal` here.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import math

log = logging.getLogger(__name__)

SIZING_VERSION = "risk-first-v1"
GRADE_VERSION = "source-grade-v1"

# binding order when two caps give the same quantity: the risk budget is named first (the intended binder)
_ORDER = ("risk", "notional", "positionPct", "nameExposure", "guard")


# ------------------------------------------------------------------ V5.1 pure
def share_caps(*, limit: float, stop: float | None, direction: str, risk_budget: float | None,
               notional_budget: float, position_room: float | None = None,
               name_room: float | None = None, scale: float = 1.0) -> dict:
    """Every candidate share quantity (None = that cap is not in force / not computable) and the one that binds.

    - risk: floor(B / (entry - stop)) for a long (mirrored for a short), the intended binder
    - notional: floor(notional budget / limit)
    - positionPct: floor(room under risk.max_position_pct / limit)
    - nameExposure: floor(room under max_name_exposure_pct / limit)
    - guard: with an enforce-mode size scale < 1 (Kelly / regime / chase) the risk and notional budgets arrive already
      scaled, and the absolute ceilings (position / name) are scaled here too, so "half size" halves the quantity
      whichever cap binds
    """
    out: dict = {"version": SIZING_VERSION, "limit": float(limit)}
    caps: dict[str, int | None] = {k: None for k in _ORDER}
    lim = float(limit or 0)
    if lim <= 0:
        out.update(caps=caps, qty=0, binding=None, note="no price")
        return out
    dist = None
    if stop is not None and risk_budget is not None and risk_budget > 0:
        sgn = 1.0 if direction != "short" else -1.0
        dist = sgn * (lim - float(stop))
        if dist > 0:
            caps["risk"] = int(math.floor(float(risk_budget) / dist + 1e-9))
    caps["notional"] = int(math.floor(max(0.0, float(notional_budget or 0)) / lim + 1e-9))
    if position_room is not None:
        caps["positionPct"] = int(math.floor(max(0.0, float(position_room)) / lim + 1e-9))
    if name_room is not None:
        caps["nameExposure"] = int(math.floor(max(0.0, float(name_room)) / lim + 1e-9))
    sc = max(0.0, min(1.0, float(scale if scale is not None else 1.0)))
    ceil = [v for v in (caps["positionPct"], caps["nameExposure"]) if v is not None]
    if sc < 1.0 and ceil:
        caps["guard"] = int(math.floor(min(ceil) * sc + 1e-9))
    live = {k: v for k, v in caps.items() if v is not None}
    qty = min(live.values()) if live else 0
    binding = next((k for k in _ORDER if caps.get(k) is not None and caps[k] == qty), None)
    out.update(caps=caps, qty=int(qty), binding=binding, stopDistance=(round(dist, 4) if dist is not None else None),
               riskBudget=(round(float(risk_budget), 2) if risk_budget is not None else None),
               notionalBudget=round(float(notional_budget or 0), 2),
               plannedRisk=(round(qty * dist, 2) if (dist is not None and dist > 0) else None))
    if caps["risk"] is None:
        out["note"] = ("no stop on the plan - sized by the notional budget only" if stop is None
                       else "stop on the wrong side of the entry - sized by the notional budget only"
                       if dist is not None else "no risk budget - sized by the notional budget only")
    return out


def position_open_risk(legs: list, config: dict | None, state: dict | None) -> float:
    """Remaining $ risk of one managed tip position to its CURRENT stop (never negative).

    Shares: held qty x (avgFill - stop) for a long (a stop at/above entry = 0 risk); the stop is the policy state's
    live stop, else the policy's fixed stop, else `config.risk` (the entry-time distance). Options: the planned risk
    of the entry riskPlan scaled to the held quantity, else the premium still at stake (cost basis)."""
    cfg, st = config or {}, state or {}
    pst = (st.get("policyState") or {}) if isinstance(st, dict) else {}
    stop = pst.get("stop")
    if stop is None:
        stop = (((cfg.get("policy") or {}).get("stop") or {}).get("price"))
    rp = ((cfg.get("extras") or {}).get("riskPlan") or {})
    total = 0.0
    for leg in legs or []:
        qty = float(leg.get("qty") or 0)
        if qty == 0:
            continue
        avg = float(leg.get("avgFill") or 0)
        mult = float(leg.get("multiplier") or 1.0)
        if str(leg.get("secType") or "STK").upper() == "STK":
            if stop is not None:
                per = (avg - float(stop)) if qty > 0 else (float(stop) - avg)
            else:
                per = float(cfg.get("risk") or 0)
            total += abs(qty) * max(0.0, per) * mult
        else:
            pr, pq = rp.get("plannedRisk"), rp.get("qty")
            if pr is not None and pq:
                total += float(pr) * min(1.0, abs(qty) / float(pq))
            else:
                total += abs(qty) * avg * mult
    return round(total, 2)


def open_risk_refusal(*, equity: float | None, open_risk: float, this_risk: float | None,
                      cap_pct: float) -> str | None:
    """None when the trade fits under the cap (or the cap is off / not judgeable)."""
    if cap_pct <= 0 or not equity or equity <= 0 or this_risk is None:
        return None
    cap = equity * cap_pct / 100.0
    if open_risk + float(this_risk) <= cap + 1e-6:
        return None
    return (f"open-risk cap: open tip positions risk ${open_risk:,.0f} to their stops + this trade ${float(this_risk):,.0f}"
            f" = ${open_risk + float(this_risk):,.0f} > {cap_pct:g}% of ${equity:,.0f} equity (${cap:,.0f}; "
            f"techniques.tip.max_open_risk_pct)")


# ------------------------------------------------------------------ V5.2 pure
def grade_source(rs: list[float], *, min_n: int = 20, k: float = 20.0, fraction: float = 0.25) -> dict:
    """The after-cost record in R and the fractional-Kelly risk it supports.

    status: ungraded (n < min_n) | positive | negative (shrunk edge <= 0 -> watch-only)."""
    xs = [float(r) for r in rs if r is not None and math.isfinite(float(r))]
    n = len(xs)
    out: dict = {"version": GRADE_VERSION, "n": n, "minTrades": int(min_n), "shrinkK": float(k),
                 "kellyFraction": float(fraction)}
    if n == 0:
        out.update(status="ungraded", hits=0, hitRate=None, meanR=None, shrunkEdge=None,
                   kellyPct=None, fractionalKellyPct=None)
        return out
    wins = [x for x in xs if x > 0]
    losses = [x for x in xs if x <= 0]
    mean = sum(xs) / n
    shrink = n / (n + float(k)) if k > 0 else 1.0
    edge = mean * shrink
    m2 = sum(x * x for x in xs) / n
    kelly = (edge / m2) if (m2 > 0 and edge > 0) else 0.0          # fraction of equity risked per 1R
    out.update(hits=len(wins), hitRate=round(len(wins) / n, 4), meanR=round(mean, 4),
               winMeanR=(round(sum(wins) / len(wins), 4) if wins else None),
               lossMeanR=(round(sum(losses) / len(losses), 4) if losses else None),
               shrink=round(shrink, 4), shrunkEdge=round(edge, 4),
               kellyPct=round(kelly * 100.0, 4), fractionalKellyPct=round(kelly * float(fraction) * 100.0, 4))
    if n < int(min_n):
        out["status"] = "ungraded"
    else:
        out["status"] = "positive" if edge > 0 else "negative"
    return out


def kelly_decision(grade: dict, *, risk_pct: float, mode: str) -> dict:
    """What the grade does to this card: scale (risk multiplier, <= 1), watchOnly, applied (enforce only)."""
    mode = mode if mode in ("observe", "enforce", "off") else "observe"
    out = {"mode": mode, "scale": 1.0, "watchOnly": False, "applied": False, "riskPct": float(risk_pct)}
    if mode == "off" or grade.get("status") == "ungraded":
        out["why"] = "off" if mode == "off" else f"ungraded ({grade.get('n', 0)} < {grade.get('minTrades')} graded trades)"
        return out
    if grade.get("status") == "negative":
        out.update(watchOnly=True, scale=0.0, why=f"negative shrunk edge {grade.get('shrunkEdge')}R over {grade.get('n')} trades")
    else:
        fk = float(grade.get("fractionalKellyPct") or 0)
        eff = min(float(risk_pct), fk) if risk_pct > 0 else fk
        out["riskPct"] = round(eff, 4)
        out["scale"] = round(eff / float(risk_pct), 4) if risk_pct > 0 else 1.0
        out["why"] = (f"risk = min({risk_pct:g}%, {grade.get('kellyFraction')} Kelly {fk:.2f}%) = {eff:.2f}% of equity")
    out["applied"] = mode == "enforce"
    return out


# ------------------------------------------------------------------ the idea-level decision (contextvar)
_DECISION: contextvars.ContextVar[dict | None] = contextvars.ContextVar("tip_decision", default=None)


def current_decision() -> dict | None:
    return _DECISION.get()


class use_decision:
    """with sizing.use_decision(d): ... - the per-idea decision inputs (entry context, grade, guards, scale) are
    visible to `_create_for_book` without threading a parameter through the fan-out."""

    def __init__(self, decision: dict | None):
        self.decision, self._tok = decision, None

    def __enter__(self):
        self._tok = _DECISION.set(self.decision)
        return self.decision

    def __exit__(self, *exc):
        _DECISION.reset(self._tok)
        return False


# ------------------------------------------------------------------ DB readers
async def book_open_risk(eng, pid: str) -> float:
    """Sum of `position_open_risk` over the book's open tip positions."""
    from sqlalchemy import select

    from ...models import ManagedPositionRow
    async with eng.sf() as session:
        rows = (await session.execute(select(ManagedPositionRow).where(
            ManagedPositionRow.technique == "tip", ManagedPositionRow.portfolio_id == pid,
            ManagedPositionRow.status.in_(("open", "attention", "opening", "closing"))))).scalars().all()
    return round(sum(position_open_risk(r.legs, r.config, r.state) for r in rows), 2)


def primary_binding(eng):
    """The primary Tips binding, with the same fallback the proposal fan-out uses (the first plain sim book)."""
    from . import books as _books
    sims = [p for p in eng.positions.portfolios() if p.get("kind") == "sim" and not p.get("book")
            and not p.get("archived")]
    bs = _books.resolve_books(eng.settings, eng.positions.portfolio, fallback_pid=(sims[0]["id"] if sims else None))
    return next((b for b in bs if b.primary), bs[0] if bs else None)


def _initial_risk(row, entry_qty: float) -> float | None:
    cfg = row.config or {}
    rp = ((cfg.get("extras") or {}).get("riskPlan") or {})
    if rp.get("plannedRisk") is not None and float(rp["plannedRisk"]) > 0:
        return float(rp["plannedRisk"])
    legs = row.legs or []
    if legs and str(legs[0].get("secType") or "STK").upper() == "STK" and cfg.get("risk") and entry_qty > 0:
        return float(cfg["risk"]) * entry_qty * float(legs[0].get("multiplier") or 1.0)
    return None


async def source_r_record(eng, source: str) -> list[dict]:
    """The source's graded closed tip positions in the PRIMARY book: one {positionId, symbol, r, net, risk} each,
    net = realized P&L minus the commissions of the entry and exit orders. A position whose initial risk is unknown
    is not graded (never guessed)."""
    from sqlalchemy import select

    from ...models import Execution, ManagedPositionRow
    prim = primary_binding(eng)
    if prim is None:
        return []
    async with eng.sf() as session:
        rows = (await session.execute(select(ManagedPositionRow).where(
            ManagedPositionRow.technique == "tip", ManagedPositionRow.portfolio_id == prim.portfolioId,
            ManagedPositionRow.status == "closed").order_by(ManagedPositionRow.created_at))).scalars().all()
        rows = [r for r in rows if f"source:{source}" in (r.tags or [])]
        oids: set[str] = set()
        for r in rows:
            oids.update(str(leg.get("entryOrderId")) for leg in (r.legs or []) if leg.get("entryOrderId"))
            oids.update(str(x.get("orderId")) for x in ((r.state or {}).get("exits") or []) if x.get("orderId"))
        execs = []
        if oids:
            execs = (await session.execute(select(Execution).where(Execution.order_id.in_(list(oids))))).scalars().all()
    by_order: dict[str, list] = {}
    for e in execs:
        by_order.setdefault(e.order_id, []).append(e)
    out = []
    for r in rows:
        entry_ids = [str(leg.get("entryOrderId")) for leg in (r.legs or []) if leg.get("entryOrderId")]
        exit_ids = [str(x.get("orderId")) for x in ((r.state or {}).get("exits") or []) if x.get("orderId")]
        entry_qty = sum(float(e.qty or 0) for o in entry_ids for e in by_order.get(o, []))
        fees = sum(float(e.commission or 0) for o in {*entry_ids, *exit_ids} for e in by_order.get(o, []))
        risk = _initial_risk(r, entry_qty)
        if not risk or risk <= 0:
            continue
        net = float((r.state or {}).get("realizedPnl") or 0) - fees
        out.append({"positionId": r.id, "symbol": r.symbol, "r": round(net / risk, 4), "net": round(net, 2),
                    "risk": round(risk, 2), "fees": round(fees, 2)})
    return out


async def source_grade(eng, source: str | None) -> dict:
    s = eng.settings
    rec = []
    with contextlib.suppress(Exception):
        rec = await source_r_record(eng, source or "unknown")
    g = grade_source([x["r"] for x in rec],
                     min_n=int(s.get("techniques.tip.source_kelly_min_trades", 20) or 20),
                     k=float(s.get("techniques.tip.source_kelly_shrink_k", 20.0) or 0),
                     fraction=float(s.get("techniques.tip.source_kelly_fraction", 0.25) or 0.25))
    g["source"] = source
    g["basis"] = "closed tip positions in the primary book, realized P&L after entry+exit commissions, R = / initial risk"
    return g
