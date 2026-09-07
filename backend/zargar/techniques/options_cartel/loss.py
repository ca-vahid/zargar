"""Daily Cartel trading P&L from executions and explicit marks, with a durable latch.

This is price-and-fee P&L, converted at current FX; FX translation gains/losses
are not attributed to the technique. The book-wide loss guard remains separate.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import math
from collections import defaultdict
from dataclasses import replace
from weakref import WeakKeyDictionary

from sqlalchemy import select

from ... import events as ev
from ...fx import MAX_RATE_AGE_MS, currency_for_symbol, fx_pair_symbol
from ...marketstructure.market_calendar import previous_trading_day
from ...marketstructure.sessions import ET, session_bounds
from ...models import BarRow, Event, Execution, ManagedPositionRow, Order, Portfolio

_locks = WeakKeyDictionary()


def snapshot_quotes(engine):
    return {symbol: replace(quote) for symbol, quote in engine.quotes.all().items()}


async def daily_loss_report(engine, portfolio_id, *, now_ms, quotes=None):
    quotes = snapshot_quotes(engine) if quotes is None else quotes
    moment = dt.datetime.fromtimestamp(now_ms/1000, ET)
    day = moment.date()
    begins = dt.datetime.combine(day, dt.time(), ET).astimezone(dt.UTC)
    previous = previous_trading_day(day)
    previous_open, previous_close = session_bounds(previous.isoformat())
    at = moment.astimezone(dt.UTC)
    async with engine.sf() as session:
        portfolio = await session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio not found")
        rows = (await session.execute(select(Execution, Order).join(Order, Execution.order_id == Order.id).where(
            Order.technique == "options_cartel", Order.portfolio_id == portfolio_id))).all()
        orders = (await session.scalars(select(Order).where(Order.technique == "options_cartel",
                                                          Order.portfolio_id == portfolio_id))).all()
        managed = (await session.scalars(select(ManagedPositionRow).where(
            ManagedPositionRow.technique == "options_cartel", ManagedPositionRow.portfolio_id == portfolio_id,
            ManagedPositionRow.status != "closed"))).all()
        bars = (await session.scalars(select(BarRow).where(BarRow.tf == "1d", BarRow.ts == previous_open))).all()
    issues = []
    ledgers = defaultdict(lambda: {"openingQty": 0., "currentQty": 0., "cashFlow": 0., "fees": 0., "executionIds": []})
    totals = defaultdict(float)
    costs = defaultdict(float)
    for execution, order in rows:
        if execution.portfolio_id != portfolio_id or execution.symbol != order.symbol or execution.side != order.side:
            issues.append(f"Execution {execution.id} disagrees with its owned order.")
            continue
        if execution.ts > at:
            issues.append(f"Execution {execution.id} is future-dated; reconcile timestamps.")
            continue
        if order.sec_type not in ("STK", "OPT") or execution.side not in ("BUY", "SELL") \
                or not all(math.isfinite(x) for x in (execution.qty, execution.price, execution.commission)) \
                or execution.qty <= 0 or execution.price <= 0 or execution.commission < 0:
            issues.append(f"Execution {execution.id} has invalid accounting values.")
            continue
        totals[order.id] += execution.qty
        costs[order.id] += execution.qty*execution.price
        ledger = ledgers[(order.symbol, order.sec_type)]
        signed = execution.qty if execution.side == "BUY" else -execution.qty
        ledger["currentQty"] += signed
        if execution.ts < begins:
            ledger["openingQty"] += signed
        else:
            mult = 100 if order.sec_type == "OPT" else 1
            ledger["cashFlow"] -= signed*execution.price*mult
            ledger["fees"] += execution.commission
            ledger["executionIds"].append(execution.id)
    for order in orders:
        if abs(totals[order.id]-float(order.filled_qty or 0)) > 1e-8:
            issues.append(f"Order {order.id} cumulative fills disagree with the execution ledger.")
        if totals[order.id] and (not order.avg_fill_price or not math.isfinite(order.avg_fill_price)
                                or abs(costs[order.id]/totals[order.id]-order.avg_fill_price) > 1e-7):
            issues.append(f"Order {order.id} average fill price disagrees with the execution ledger.")
    allocated = defaultdict(float)
    for position in managed:
        for leg in position.legs:
            qty = float(leg["qty"])
            if not math.isfinite(qty) or qty < 0:
                issues.append(f"{position.id}: managed inventory has invalid quantities.")
                continue
            allocated[(leg["symbol"], leg["secType"])] += qty
    marks = {b.symbol: b.close for b in bars}
    native = defaultdict(float)
    assets = []
    for key in sorted(set(ledgers) | set(allocated)):
        symbol, sec_type = key
        ledger = ledgers[key]
        opening, current = ledger["openingQty"], ledger["currentQty"]
        if opening < -1e-8 or current < -1e-8 or abs(current-allocated[key]) > 1e-8:
            issues.append(f"{symbol}: execution inventory and managed holdings are not reconciled.")
        mult = 100 if sec_type == "OPT" else 1
        prior = marks.get(symbol) if opening else 0.
        quote = quotes.get(symbol) if current else None
        mark = quote.bid if quote is not None else 0.
        if opening and (prior is None or not math.isfinite(prior) or prior <= 0):
            issues.append(f"{symbol}: missing persisted prior-session close ({previous}).")
            prior = None
        if current and (quote is None or quote.delayed or not math.isfinite(mark) or mark <= 0
                        or not math.isfinite(quote.ask) or quote.ask < mark
                        or not 0 <= now_ms-(quote.source_ts or quote.ts) <=
                        float(engine.settings.get("risk.stale_quote_seconds", 10))*1000):
            issues.append(f"{symbol}: a fresh, non-delayed current bid is required.")
            mark = None
        currency = currency_for_symbol(symbol)
        pnl = None if prior is None or mark is None else ledger["cashFlow"]-ledger["fees"]+(current*mark-opening*prior)*mult
        if pnl is not None and math.isfinite(pnl):
            native[currency] += pnl
        assets.append({"symbol": symbol, "secType": sec_type, **ledger, "priorClose": prior,
                       "priorCloseAt": previous_close if opening else None, "currentBid": mark if current else None,
                       "currency": currency, "nativePnl": pnl})
    converted = 0.
    rates = {}
    for currency, pnl in native.items():
        if pnl == 0:
            continue
        rate = 1.
        if currency != portfolio.base_currency:
            q = quotes.get(fx_pair_symbol(currency, portfolio.base_currency))
            inverse = False
            if q is None:
                q = quotes.get(fx_pair_symbol(portfolio.base_currency, currency))
                inverse = True
            if q is None or q.delayed or not math.isfinite(q.last) or q.last <= 0 \
                    or not 0 <= now_ms-(q.source_ts or q.ts) < MAX_RATE_AGE_MS:
                issues.append(f"{currency}: current FX conversion into {portfolio.base_currency} is unavailable.")
                continue
            rate = 1/q.last if inverse else q.last
        rates[currency] = rate
        converted += pnl*rate
    return {"portfolioId": portfolio_id, "day": day.isoformat(), "asOfMs": now_ms, "available": not issues,
            "pnl": round(converted, 8) if not issues else None, "baseCurrency": portfolio.base_currency,
            "nativePnlByCurrency": dict(native), "fxRates": rates, "assets": assets, "issues": issues,
            "basis": "price-and-fee P&L at current FX; FX translation excluded",
            "commissionBasis": "recorded execution commissions; later broker corrections require reconciliation",
            "executionTimeBasis": "recorded executor-report time; venue timestamp normalization may be required"}


async def loss_gate(engine, portfolio_id, *, now_ms):
    pct = float(engine.settings.get("techniques.options_cartel.daily_loss_halt_pct", 0))
    if not math.isfinite(pct) or pct < 0:
        return {"enabled": True, "passed": False, "reason": "Invalid Cartel daily-loss limit."}
    if pct == 0:
        return {"enabled": False, "passed": True, "reason": "Technique limit disabled; book loss guard remains separate."}
    day = dt.datetime.fromtimestamp(now_ms/1000, ET).date().isoformat()
    quotes = snapshot_quotes(engine)
    lock = _locks.setdefault(engine, {}).setdefault((portfolio_id, day), asyncio.Lock())
    async with lock:
        async with engine.sf() as session:
            prior = await session.scalar(select(Event).where(Event.type == ev.OPTIONS_CARTEL_LOSS_HALT,
                Event.portfolio_id == portfolio_id, Event.payload["day"].as_string() == day).order_by(Event.ts).limit(1))
        if prior is not None:
            return {"enabled": True, "passed": False, "latched": True, "reason": "Cartel loss halt is latched for this session day.",
                    "halt": prior.payload}
        report = await daily_loss_report(engine, portfolio_id, now_ms=now_ms, quotes=quotes)
        equity = float(await engine.positions.equity(portfolio_id))
        if not report["available"] or not math.isfinite(equity) or equity <= 0:
            return {"enabled": True, "passed": False, "reason": "Cartel loss accounting requires complete marks and positive equity.",
                    "report": report}
        limit = equity*pct/100
        breached = report["pnl"] <= -limit
        result = {"enabled": True, "passed": not breached, "latched": breached, "pct": pct,
                  "equity": equity, "limit": limit, "thresholdBasis": "current book equity", "report": report,
                  "reason": "Cartel daily loss limit breached." if breached else "Cartel daily loss is within its limit."}
        if breached:
            await engine.journal.append(ev.OPTIONS_CARTEL_LOSS_HALT,
                {"technique": "options_cartel", "portfolioId": portfolio_id, "day": day, "asOfMs": now_ms,
                 "pnl": report["pnl"], "pct": pct, "equity": equity, "limit": limit, "report": report},
                aggregate_type="technique_risk", aggregate_id=f"options_cartel:{portfolio_id}:{day}", portfolio_id=portfolio_id)
        return result
