"""Tips v0.9 card decisions (V5 sizing + V6 decision-time information), wired into the proposal path
(`approvals/proposals.py::create_for_books` / `_create_for_book`) through a few call sites only.

Per IDEA (once, before the per-book fan-out): `idea_inputs` - the decision-time context (V6.1), the source grade
(V5.2/V6.4), the regime guard (V6.2) and the chase filter (V6.3), each journaled once when it would act.
Per BOOK: `book_scale` (the risk multiplier this book applies in enforce modes), `sector_refusal` (V5.3) and
`size_and_gate` (V5.1 risk-first share sizing + the open-risk cap), `card_fields` (what rides `proposal.context`).

Every guard defaults to OBSERVE: it journals what it would do and the card records it; only `enforce` changes a
size or mints nothing. Nothing here raises into the proposal path - a failure is logged and treated as unknown.
"""
from __future__ import annotations

import contextlib
import logging

from . import entry_context as _ec
from . import sizing as _sz

log = logging.getLogger(__name__)


def _mode(settings, key: str, default: str = "observe") -> str:
    v = str(settings.get(key, default) or default).lower()
    return v if v in ("off", "observe", "enforce") else default


async def idea_inputs(eng, signal_row, sig) -> dict:
    """The per-idea decision inputs. Never raises."""
    s = eng.settings
    sym = str(getattr(signal_row, "ticker", "") or "").upper()
    direction = str(getattr(sig, "direction", None) or getattr(signal_row, "direction", "long") or "long")
    out: dict = {"symbol": sym, "direction": direction}
    ctx = None
    with contextlib.suppress(Exception):
        ctx = await _ec.get(eng, sym)
    out["entryContext"] = ctx
    grade = {"status": "ungraded", "n": 0}
    with contextlib.suppress(Exception):
        grade = await _sz.source_grade(eng, getattr(signal_row, "source_name", None))
    out["sourceGrade"] = grade
    out["kellyMode"] = _mode(s, "techniques.tip.source_kelly_mode")
    try:
        out["regime"] = _ec.regime_decision(ctx, direction=direction, settings=s)
        out["chase"] = _ec.chase_decision(ctx, direction=direction, entry_price=None, settings=s)
    except Exception:                                     # noqa: BLE001
        log.debug("regime/chase decision failed for %s", sym, exc_info=True)
        out["regime"] = out["chase"] = None
    out["watchOnly"] = bool(grade.get("status") == "negative" and out["kellyMode"] != "off")
    sid = getattr(signal_row, "id", None)

    async def note(kind: str, payload: dict) -> None:
        with contextlib.suppress(Exception):
            await eng.journal.append(kind, {"signalId": sid, "symbol": sym, "source": getattr(signal_row, "source_name", None),
                                            **payload}, aggregate_type="signal", aggregate_id=sid or sym)
    if out["watchOnly"]:
        await note("TipSourceWatchOnly", {"mode": out["kellyMode"], "applied": out["kellyMode"] == "enforce",
                                          "wouldBlock": True, "grade": grade,
                                          "why": f"negative shrunk edge {grade.get('shrunkEdge')}R over {grade.get('n')} "
                                                 "graded trades - no proposal is minted in enforce"})
    rg = out.get("regime") or {}
    if rg.get("would"):
        await note("TipRegimeShadow", {**rg, "regime": (ctx or {}).get("regime")})
    ch = out.get("chase") or {}
    if ch.get("would"):
        await note("TipChaseShadow", ch)
    return out


def book_scale(eng, dec: dict | None, binding) -> dict:
    """{scale, kelly, parts}: the risk multiplier this book applies (enforce-mode parts only)."""
    from . import books as _books
    if not dec:
        return {"scale": 1.0, "kelly": None, "parts": {}}
    rp = float(_books.knob(binding, "riskPct", eng.settings, 1.0) or 0)
    kelly = _sz.kelly_decision(dec.get("sourceGrade") or {}, risk_pct=rp, mode=dec.get("kellyMode") or "observe")
    parts = {}
    if kelly.get("applied") and not kelly.get("watchOnly"):
        parts["kelly"] = float(kelly["scale"])
    for k in ("regime", "chase"):
        d = dec.get(k) or {}
        if d.get("applied"):
            parts[k] = float(d.get("scale") or 1.0)
    scale = 1.0
    for v in parts.values():
        scale *= v
    return {"scale": round(max(0.0, min(1.0, scale)), 4), "kelly": kelly, "parts": parts}


async def sector_refusal(eng, pid: str, symbol: str) -> str | None:
    """V5.3: refuse a new tip entry when the book already holds `max_per_sector` open tip positions in this name's
    sector. An unknown sector (this name's or a held one's) never blocks and never counts."""
    from sqlalchemy import select

    from ...models import ManagedPositionRow
    from ...options import occ as _occ
    cap = int(eng.settings.get("techniques.tip.max_per_sector", 2) or 0)
    if cap <= 0:
        return None
    mine = await _ec.sector_of(eng, symbol)
    if not mine:
        return None
    async with eng.sf() as session:
        rows = (await session.execute(select(ManagedPositionRow).where(
            ManagedPositionRow.technique == "tip", ManagedPositionRow.portfolio_id == pid,
            ManagedPositionRow.status.in_(("open", "attention", "opening"))))).scalars().all()
    held = []
    for r in rows:
        o = _occ.parse(str(r.symbol or ""))
        held.append(o.underlying if o else str(r.symbol or "").upper())
    same = []
    for u in held:
        if u == str(symbol).upper():
            continue                                       # the same name is the name cap's business
        sec = None
        with contextlib.suppress(Exception):
            sec = await _ec.sector_of(eng, u)
        if sec and sec == mine:
            same.append(u)
    if len(same) >= cap:
        pf = eng.positions.portfolio(pid) or {}
        return (f"sector cap: {len(same)} open tip positions in {mine} ({', '.join(sorted(same))}) in "
                f"{pf.get('name', pid)} (techniques.tip.max_per_sector {cap})")
    return None


async def size_and_gate(eng, *, pid: str, binding, sec_type: str, symbol: str, underlying: str, direction: str,
                        limit: float, qty: int, budget: float, exit_plan: dict, risk_plan, decision: dict | None
                        ) -> dict:
    """V5.1 on the final vehicle: risk-first share sizing (where the geometry gate did not already size) + the
    open-risk cap; V6.3 enforce shortens the time box. Returns {qty, sizing, refusal, exitPlan, note}."""
    from . import books as _books
    from . import geometry as _geo
    s = eng.settings
    out = {"qty": int(qty), "sizing": {}, "refusal": None, "exitPlan": exit_plan, "note": ""}
    pf = eng.positions.portfolio(pid) or {}
    if pf.get("kind") == "shadow":
        return out
    equity = None
    with contextlib.suppress(Exception):
        equity = float(await eng.positions.equity(pid) or 0) or None
    enforced = bool(risk_plan is not None and getattr(risk_plan, "enforced", False))
    notes: list[str] = []
    planned = None
    if sec_type == "STK":
        B, src = _geo.risk_budget(_books.BookSettings(s, binding), equity)
        stop = getattr(risk_plan, "finalStop", None) if enforced else None
        if stop is None:
            stop = (exit_plan or {}).get("underlyingStop")
        pos_room = name_room = None
        with contextlib.suppress(Exception):
            if equity:
                cap_pct = float(s.get("risk.max_position_pct", 50.0))
                held = abs(eng.positions.position_qty(pid, underlying, "STK")) * float(limit)
                pos_room = max(0.0, equity * cap_pct / 100.0 * 0.97 - held)
                npct = float(s.get("techniques.tip.max_name_exposure_pct", 0) or 0)
                if npct > 0:
                    name_cost = 0.0
                    if getattr(eng, "proposals", None) is not None:
                        _t, name_cost = await eng.proposals._book_exposure(pid, underlying)
                    name_room = max(0.0, equity * npct / 100.0 - name_cost)
        caps = _sz.share_caps(limit=float(limit), stop=stop, direction=direction, risk_budget=(B if B > 0 else None),
                              notional_budget=float(budget), position_room=pos_room, name_room=name_room,
                              scale=_books.risk_scale())
        caps["riskBudgetSource"] = src
        caps["sizedBy"] = "geometry gate (enforce)" if enforced else "risk-first sizing"
        new_q = min(int(qty), int(caps["qty"]))
        rf_on = bool(s.get("techniques.tip.risk_first_sizing", True))
        shadow_gate = risk_plan is not None and not enforced
        if (not rf_on and not enforced) or shadow_gate or (enforced and getattr(risk_plan, "reviewRequired", None)):
            # off; or the geometry gate observes this book in SHADOW (its contract: sizes untouched - the caps are only
            # recorded); or a review-gated geometry plan (the card already waits for a person): the size is left alone
            caps["applied"] = False
            if shadow_gate:
                caps["sizedBy"] = "notional (geometry gate shadow: sizes untouched, caps recorded)"
            new_q = int(qty)
        else:
            caps["applied"] = True
        if caps["applied"] and new_q < 1 and caps["caps"].get("risk") is not None and caps["caps"]["risk"] < 1:
            out["refusal"] = (f"risk-first sizing: one share risks ${caps.get('stopDistance') or 0:,.2f} at the stop "
                              f"{stop}, over the ${B:,.2f} risk budget ({src})")
        elif caps["applied"] and new_q < 1:
            out["refusal"] = f"no share fits the caps ({caps.get('binding')} binds)"
        if new_q != int(qty) and new_q >= 1:
            notes.append(f"Sized {qty} → {new_q} sh ({caps.get('binding')} binds: risk "
                         f"{caps['caps'].get('risk')} / notional {caps['caps'].get('notional')} / position "
                         f"{caps['caps'].get('positionPct')}).")
        out["qty"] = max(0, new_q)
        dist = caps.get("stopDistance")
        planned = (round(out["qty"] * dist, 2) if (dist and dist > 0) else None)
        caps["plannedRisk"] = planned
        out["sizing"] = {"riskFirst": caps}
    elif sec_type == "OPT":
        if risk_plan is not None and getattr(risk_plan, "plannedRisk", None) is not None:
            planned = float(risk_plan.plannedRisk)
        else:
            pct = (exit_plan or {}).get("premiumStopPct")
            cost = float(limit) * int(qty) * 100.0
            planned = round(cost * (float(pct) / 100.0 if pct else 1.0), 2)
    # ---- the open-risk cap (V5.1)
    cap_pct = float(_books.knob(binding, "maxOpenRiskPct", s, 5.0) or 0)
    if out["refusal"] is None and cap_pct > 0:
        open_r = 0.0
        with contextlib.suppress(Exception):
            open_r = await _sz.book_open_risk(eng, pid)
        why = _sz.open_risk_refusal(equity=equity, open_risk=open_r, this_risk=planned, cap_pct=cap_pct)
        out["sizing"]["openRisk"] = {"open": open_r, "this": planned, "capPct": cap_pct,
                                     "cap": (round(equity * cap_pct / 100.0, 2) if equity else None),
                                     "judged": planned is not None and bool(equity)}
        if why:
            out["refusal"] = why
    # ---- V6.3 enforce: the short horizon's time box
    ch = (decision or {}).get("chase") or {}
    if ch.get("applied") and ch.get("maxHoldSessions"):
        cur = (exit_plan or {}).get("maxHoldSessions")
        mh = int(ch["maxHoldSessions"])
        if cur is None or int(cur) > mh:
            out["exitPlan"] = {**(exit_plan or {}), "maxHoldSessions": mh}
            notes.append(f"Chased entry ({ch.get('entryVsPrevClosePct')}% over the prior close): time box {mh} sessions.")
    out["note"] = " ".join(notes)
    return out


def card_fields(decision: dict | None, scale: dict | None) -> dict:
    """What rides `proposal.context`: entryContext, sourceGrade (+ the Kelly decision), the guards and the scale."""
    if not decision:
        return {}
    g = dict(decision.get("sourceGrade") or {})
    if scale and scale.get("kelly"):
        g["kelly"] = scale["kelly"]
    out = {"sourceGrade": g}
    ec = _ec.card_context(decision.get("entryContext"))
    if ec:
        out["entryContext"] = ec
    guards = {k: decision.get(k) for k in ("regime", "chase") if decision.get(k)}
    if guards:
        out["guards"] = guards
    if scale and scale.get("parts"):
        out["riskScale"] = {"scale": scale["scale"], "parts": scale["parts"]}
    return out
