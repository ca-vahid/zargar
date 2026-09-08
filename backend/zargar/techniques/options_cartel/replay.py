"""Causal underlying-price campaign replay; no broker or portfolio operations."""
from __future__ import annotations

import datetime as dt
import math

from ...domain import Bar
from ...marketstructure.market_calendar import is_trading_day, next_trading_day
from ...marketstructure.sessions import ET, session_bounds
from .data import DailyBar, completed_daily
from .entry import read_entry
from .exits import ExitCampaign, ExitState, decide_exits, record_fill
from .plans import CartelPlan


def next_minute(ts):
    day = dt.datetime.fromtimestamp(ts/1000, ET).date()
    _, closes = session_bounds(day.isoformat())
    return ts+60_000 if ts+60_000 < closes else session_bounds(next_trading_day(day).isoformat())[0]


def replay_campaign(plan: CartelPlan, campaign: ExitCampaign, minutes: list[Bar], daily: list[DailyBar], *,
                    as_of_ms: int, quantity: int = 100, slippage_bps: float = 0):
    if not 1 <= quantity <= 1_000_000 or not 0 <= slippage_bps <= 100:
        raise ValueError("invalid replay quantity or slippage")
    entry = read_entry(plan, minutes, as_of_ms)
    output = {"entryRead": entry, "simulation": True, "placesOrders": False,
              "model": "underlying price; decisions on closed minutes, fills at next available expected minute open",
              "premiumPathSimulated": False, "quoteCrashBrakeSimulated": False, "feesSimulated": False,
              "expirySimulated": False, "limitOrdersSimulated": False, "dataComplete": entry["status"] != "missing_data",
              "quantity": quantity, "slippageBps": slippage_bps, "fills": [], "warnings": [],
              "status": entry["status"], "realizedR": None, "openR": None}
    signal = entry.get("signal")
    # read_entry can find a later observed crossing even when an entire earlier
    # session is absent. A historical outcome cannot assume that unseen session
    # contained neither an entry nor an invalidation.
    coverage_end = min(signal["at"] if signal else as_of_ms,
                       session_bounds(plan.last_session.isoformat())[1])
    present = {b.ts for b in minutes if b.symbol == plan.symbol and b.tf == "1m" and b.ts+60_000 <= as_of_ms}
    day = plan.first_session
    while day <= plan.last_session:
        if is_trading_day(day):
            opens, closes = session_bounds(day.isoformat())
            required = range(opens, min(closes, coverage_end)-59_999, 60_000)
            if any(ts not in present for ts in required):
                output.update(status="missing_data", dataComplete=False)
                output["warnings"].append("Incomplete entry-window history; earlier signals or invalidations cannot be ruled out.")
                return output
        day += dt.timedelta(days=1)
    if signal is None:
        if any(t.get("decision") == "missing_bucket" for t in entry["trace"]) or not any(
                session_bounds(plan.first_session.isoformat())[0] <= b.ts and
                b.ts+60_000 <= min(as_of_ms, session_bounds(plan.last_session.isoformat())[1]) for b in minutes):
            output.update(status="missing_data", dataComplete=False)
        return output
    if signal["at"] >= session_bounds(plan.last_session.isoformat())[1]:
        output.update(status="entry_window_closed")
        return output
    tape = {}
    for bar in minutes:
        if bar.symbol != plan.symbol or bar.tf != "1m" or bar.ts % 60_000:
            raise ValueError("replay needs symbol-matched, aligned minute bars")
        if bar.ts+60_000 > as_of_ms:
            continue
        day = dt.datetime.fromtimestamp(bar.ts/1000, ET).date()
        if not is_trading_day(day):
            continue
        opens, closes = session_bounds(day.isoformat())
        if not opens <= bar.ts < closes:
            continue
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if not all(math.isfinite(v) for v in values) or min(values[:4]) <= 0 or bar.volume < 0 \
                or bar.high < max(values[:4]) or bar.low > min(values[:4]):
            raise ValueError("invalid replay candle values")
        if bar.ts in tape and tape[bar.ts] != bar:
            raise ValueError("conflicting replay minutes")
        tape[bar.ts] = bar
    first = tape.get(signal["at"])
    if first is None:
        output.update(status="entry_pending" if as_of_ms < signal["at"]+60_000 else "missing_data")
        output["dataComplete"] = output["status"] != "missing_data"
        return output
    sign = 1 if plan.direction == "long" else -1
    price = first.open*(1+sign*slippage_bps/10_000)
    if (price-plan.trigger)*sign > abs(plan.trigger-plan.invalidation)*plan.entry.max_chase_r \
            or (price-plan.trigger)*sign < 0 \
            or (price-signal["stop"])*sign <= 0 or (plan.targets[0]-price)*sign <= 0:
        output.update(status="entry_price_rejected")
        return output
    risk = abs(price-signal["stop"])
    state = ExitState(position_id=f"replay:{plan.id}", symbol=plan.symbol, direction=plan.direction,
                      entry=price, stop=signal["stop"], initial_qty=quantity, remaining_qty=quantity)
    output["fills"].append({"kind": "entry", "at": first.ts, "price": price, "qty": quantity})
    pending = []
    expected = first.ts
    realized = 0.
    last_close = price
    for ts, bar in sorted(tape.items()):
        if ts < first.ts:
            continue
        if ts != expected:
            output.update(status="missing_data", dataComplete=False, realizedR=realized/(risk*quantity), state=state.model_dump(mode="json"))
            output["warnings"].append("Missing execution minutes; no fills inferred across the gap.")
            return output
        for index, decision in enumerate(pending):
            fill_price = bar.open*(1-sign*slippage_bps/10_000)
            qty = min(decision["qty"], state.remaining_qty)
            if qty:
                state = record_fill(campaign, state, fill_id=f"{ts}:{index}", rung=decision["rung"], qty=qty)
                realized += sign*(fill_price-price)*qty
                output["fills"].append({"kind": decision["rung"], "at": ts, "price": fill_price, "qty": qty})
        pending = []
        last_close = bar.close
        if state.remaining_qty == 0:
            output["status"] = "closed"
            break
        end = ts+60_000
        day = dt.datetime.fromtimestamp(ts/1000, ET).date()
        history = completed_daily(daily, end)
        is_close = end == session_bounds(day.isoformat())[1]
        if is_close and (not history or history[-1].closes_at != end):
            output["warnings"].append(f"{day}: missing daily close; EMA decisions unavailable.")
            output["dataComplete"] = False
            is_close = False
        read = decide_exits(campaign, state, history, as_of_ms=end, observed_price=bar.close, daily_close=is_close)
        pending = read["decisions"]
        output["warnings"].extend(read["warnings"])
        expected = next_minute(ts)
        output["status"] = "open"
    if state.remaining_qty and expected+60_000 <= as_of_ms:
        output["status"] = "missing_data"
        output["dataComplete"] = False
        output["warnings"].append("Replay tape ends before the requested cutoff.")
    output.update(state=state.model_dump(mode="json"), pending=pending,
                  realizedR=realized/(risk*quantity),
                  openR=sign*(last_close-price)*state.remaining_qty/(risk*quantity))
    output["warnings"] = list(dict.fromkeys(output["warnings"]))
    return output
