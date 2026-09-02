"""Counterfactual ledger: what a trade the app MISSED through a bug would have
done (PLATFORM-RULES 2026-09-02, the NOW restart-orphan).

After a bug is fixed we replay the fired order through the runner's own exit
rules on the real 1m bars of the session - the underlying for stop/targets,
the contract's own prints for fill and exit prices - and persist ONE ledger
row + a `TechniqueCounterfactual` journal event. It never touches a
portfolio: Practice stays what actually happened, this table says what the
method would have earned. Technique-agnostic (reads the run's plan trigger
and the armed record's trade).

Rules mirrored from `execution/planrunner.py` / `marketstructure/outcome.py`:
  - the entry works for `plan_entry_window_bars` minutes after the fire, then
    is cancelled (T4.1: never chase); a BUY LMT fills on the first contract
    bar that trades at or below the limit;
  - stops exit on the bar CLOSE through the stop (`technique.stop_on_close`);
  - targets scale out 30/40/15 (T4.4a); options with < 3 contracts exit in
    full at the single-contract target (TP2 by default);
  - whatever is left is flattened `flatten_minutes_before_close` before 16:00;
  - a session still in progress leaves the row `open` (re-run later).
Exit prices come from the contract's 1m print on that minute, else the last
print before it (flagged stale), so thin contracts are judged honestly.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from ..domain import Bar
from ..marketstructure.history import fetch_session
from ..marketstructure.sessions import session_bounds
from ..models import TechniqueArmed, TechniqueCounterfactual

log = logging.getLogger(__name__)

MIN = 60_000
LADDER = (0.30, 0.40, 0.15)     # T4.4a: 30/40/15 with a 15% runner


def _price(x) -> float | None:
    if isinstance(x, dict):
        x = x.get("price")
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _bar_at(bars: list[Bar], ts: int) -> tuple[Bar | None, bool]:
    """The bar on `ts`, else the last one before it (stale=True); (None, False) when nothing."""
    last = None
    for b in bars:
        if b.ts == ts:
            return b, False
        if b.ts > ts:
            break
        last = b
    return last, last is not None


def _split(qty: float, *, single_exit_at: int | None) -> list[float]:
    """Units per target. Options with < 3 contracts: everything at one target."""
    if single_exit_at is not None:
        out = [0.0, 0.0, 0.0]
        out[single_exit_at] = float(qty)
        return out
    if float(qty).is_integer() and qty < 100:
        a = int(qty * LADDER[0])
        b = int(qty * LADDER[1])
        return [float(a), float(b), float(int(qty) - a - b)]
    return [round(qty * LADDER[0], 4), round(qty * LADDER[1], 4),
            round(qty - qty * LADDER[0] - qty * LADDER[1], 4)]


def replay(*, direction: str, entry: float, stop: float, targets: list[float],
           fired_ts: int, limit_price: float, qty: float, multiplier: float,
           underlying: list[Bar], contract: list[Bar], session: str,
           entry_window_bars: int = 12, single_exit: str | None = "tp2",
           flatten_minutes: int = 5, fee_per_unit_side: float = 0.0) -> dict:
    """Pure: the trade's counterfactual on the given bars."""
    sign = 1.0 if direction == "long" else -1.0
    risk = max(abs(entry - stop), 1e-9)
    notes: list[str] = []
    _open_ms, close_ms = session_bounds(session)
    # --- fill: the order works from the bar after the fire, for the entry window
    fill_ts = fill_px = None
    deadline = fired_ts + entry_window_bars * MIN
    for b in contract:
        if b.ts <= fired_ts:
            continue
        if b.ts > deadline:
            break
        if b.low <= limit_price:
            fill_ts = b.ts
            fill_px = float(b.open) if b.open <= limit_price else float(limit_price)
            break
    if fill_ts is None:
        last = max((b.ts for b in contract), default=0)
        status = "open" if last and last < deadline and last < close_ms else "not_filled"
        return {"status": status, "fillTs": None, "fillPrice": None, "exits": [], "pnl": 0.0, "grossPnl": 0.0,
                "fees": 0.0, "rUnderlying": 0.0, "remaining": qty, "mark": None,
                "notes": notes + ["no print at or below the limit inside the entry window"]}
    # --- exits on the underlying's closed bars after the fill bar
    idx_single = {"tp1": 0, "tp2": 1, "tp3": 2}.get(single_exit or "")
    parts = _split(qty, single_exit_at=idx_single if (multiplier > 1 and qty < 3) else None)
    remaining = float(qty)
    exits: list[dict] = []
    tp_done = [False, False, False]
    flatten_at = close_ms - flatten_minutes * MIN
    r_num = 0.0

    def take(kind: str, ts: int, q: float, underlying_px: float) -> None:
        nonlocal remaining, r_num
        q = min(q, remaining)
        if q <= 0:
            return
        cb, stale = _bar_at(contract, ts)
        if cb is None:
            notes.append(f"{kind}: no contract print by that minute; exit valued at the fill")
            px = float(fill_px)
        else:
            px = float(cb.close)
            if stale:
                notes.append(f"{kind}: contract print is stale ({(ts - cb.ts) // MIN}m old)")
        remaining -= q
        r_num += sign * (underlying_px - entry) * q
        exits.append({"kind": kind, "ts": ts, "qty": q, "price": round(px, 4), "underlying": round(underlying_px, 4)})

    last_bar = None
    for b in underlying:
        if b.ts <= fill_ts:
            continue
        if remaining <= 0:
            break
        last_bar = b
        if b.ts >= flatten_at:
            take("flatten", b.ts, remaining, float(b.close))
            break
        stopped = (b.close <= stop) if sign > 0 else (b.close >= stop)
        if stopped:
            take("stop", b.ts, remaining, float(b.close))
            break
        for i, tp in enumerate(targets[:3]):
            if tp_done[i] or remaining <= 0:
                continue
            hit = (b.high >= tp) if sign > 0 else (b.low <= tp)
            if hit:
                tp_done[i] = True
                q = remaining if i == 2 else (parts[i] if i < len(parts) else remaining)
                take(f"tp{i + 1}", b.ts, q, float(tp))
    pnl = sum((e["price"] - fill_px) * e["qty"] * multiplier for e in exits)
    fees = fee_per_unit_side * (qty + sum(e["qty"] for e in exits))
    net = round(pnl - fees, 2)
    status = "open" if remaining > 0 else ("win" if net > 0 else "loss" if net < 0 else "scratch")
    mark = None
    if remaining > 0 and last_bar is not None:
        cb, _ = _bar_at(contract, last_bar.ts)
        mark = float(cb.close) if cb is not None else None
    return {"status": status, "fillTs": fill_ts, "fillPrice": round(fill_px, 4), "exits": exits,
            "pnl": net, "grossPnl": round(pnl, 2), "fees": round(fees, 2),
            "rUnderlying": round(r_num / (risk * qty), 3) if qty else 0.0,
            "remaining": remaining, "mark": mark, "notes": notes}


def row_dict(r: TechniqueCounterfactual) -> dict:
    return {"id": r.id, "technique": r.technique, "runId": r.run_id, "triggerId": r.trigger_id,
            "symbol": r.symbol, "session": r.session, "reason": r.reason, "status": r.status,
            "result": r.result or {}, "createdAt": r.created_at.isoformat() if r.created_at else None}


async def reconstruct(engine, run_id: str, trigger_id: str, *, reason: str,
                      order_symbol: str | None = None, limit_price: float | None = None,
                      qty: float | None = None, fired_ts: int | None = None) -> dict:
    """Build + persist the counterfactual for one fired trigger of an armed run.
    Overrides fill in what the armed record no longer carries (a re-armed plan
    keeps the fire but not the order)."""
    svc = engine.technique
    run = await svc.get_run(run_id)
    if not run:
        raise KeyError(f"run {run_id} not found")
    plan = ((run.get("result") or {}).get("plan")) or {}
    trig = next((t for t in plan.get("triggers") or [] if t.get("id") == trigger_id), None)
    if trig is None:
        raise KeyError(f"trigger {trigger_id} not in the plan of {run_id}")
    symbol = str(plan.get("symbol") or run.get("symbol"))
    session = str(plan.get("planFor") or "")
    direction = str(trig.get("direction") or "long")
    entry, stop = _price(trig.get("entry")), _price(trig.get("stop"))
    targets = [p for p in (_price(t) for t in trig.get("targets") or []) if p is not None]
    if entry is None or stop is None or not targets:
        raise ValueError("the trigger has no entry/stop/targets to replay")
    async with engine.sf() as s:
        armed = (await s.execute(select(TechniqueArmed).where(TechniqueArmed.run_id == run_id))).scalar_one_or_none()
    technique = (getattr(armed, "technique", None) if armed else None) or str(run.get("technique") or "enhanced_market")
    rec = next((t for t in ((armed.state or {}).get("trades") or []) if t.get("triggerId") == trigger_id), {}) if armed else {}
    cfg = (armed.config or {}) if armed else {}
    fired_ts = int(fired_ts or rec.get("firedTs") or 0)
    if not fired_ts:
        raise ValueError("the trigger never fired (no firedTs on record) - pass firedTs for a hypothetical")
    order_symbol = str(order_symbol or rec.get("orderSymbol") or symbol)
    instrument = "options" if order_symbol != symbol else "shares"
    if instrument == "shares" and direction == "short":
        raise ValueError("short shares are never traded (puts only) - pass the put's OCC symbol as orderSymbol")
    multiplier = float(rec.get("multiplier") or (100.0 if instrument == "options" else 1.0))
    qty = float(qty or rec.get("qty") or 1.0)
    limit_price = float(limit_price or rec.get("limitPrice") or 0.0)
    if limit_price <= 0:
        raise ValueError("no limit price on record - pass limitPrice (the order's price)")
    entry_window = 12
    try:
        entry_window = int(svc.armer.rules().plan_entry_window_bars)
    except Exception:  # noqa: BLE001
        pass
    fee = 0.0
    if instrument == "options":
        fee = float(engine.settings.get("options.fee_per_contract", 0.99)) + float(engine.settings.get("sim.reg_fee_per_contract", 0.05))
    underlying = await fetch_session(symbol, "1m", session)
    contract = await fetch_session(order_symbol, "1m", session) if instrument == "options" else underlying
    if not underlying:
        raise ValueError(f"no 1m bars for {symbol} on {session} (Yahoo keeps about 20 days)")
    if not contract:
        raise ValueError(f"no 1m prints for {order_symbol} on {session}")
    res = replay(direction=direction, entry=entry, stop=stop, targets=targets, fired_ts=fired_ts,
                 limit_price=limit_price, qty=qty, multiplier=multiplier, underlying=underlying,
                 contract=contract, session=session, entry_window_bars=entry_window,
                 single_exit=str(cfg.get("singleContractExit") or "tp2"),
                 flatten_minutes=int(cfg.get("flattenMinutesBeforeClose") or 5), fee_per_unit_side=fee)
    res.update({"direction": direction, "instrument": instrument, "orderSymbol": order_symbol, "qty": qty,
                "multiplier": multiplier, "limitPrice": limit_price, "firedTs": fired_ts,
                "entry": entry, "stop": stop, "targets": targets,
                "bars": {"underlying": len(underlying), "contract": len(contract)}})
    row = TechniqueCounterfactual(id=uuid.uuid4().hex, technique=technique, run_id=run_id, trigger_id=trigger_id,
                                  symbol=symbol, session=session, reason=reason, status=res["status"], result=res)
    async with engine.sf() as s:
        s.add(row)
        await s.commit()
        await s.refresh(row)
    out = row_dict(row)
    await engine.journal.append("TechniqueCounterfactual", {
        "runId": run_id, "symbol": symbol, "trigger": trigger_id, "reason": reason, "status": res["status"],
        "pnl": res["pnl"], "r": res["rUnderlying"], "fill": res["fillPrice"], "exits": res["exits"], "id": row.id,
    }, aggregate_type="technique_run", aggregate_id=run_id)
    log.info("counterfactual %s %s/%s: %s pnl %.2f (%s)", row.id[:8], symbol, trigger_id, res["status"], res["pnl"], reason)
    return out


async def list_rows(engine, *, limit: int = 100, technique: str | None = None) -> list[dict]:
    async with engine.sf() as s:
        q = select(TechniqueCounterfactual).order_by(TechniqueCounterfactual.created_at.desc()).limit(limit)
        if technique:
            q = q.where(TechniqueCounterfactual.technique == technique)
        rows = (await s.execute(q)).scalars().all()
    return [row_dict(r) for r in rows]
