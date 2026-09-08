"""Recover missing prior-session risk marks through shared historical data.

Existing daily rows are never overwritten. Simulated quotes need simulated
benchmarks; this helper does not mix live historical closes into a sim tape.
"""
from __future__ import annotations

import datetime as dt
import re

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ... import events as ev
from ...brokers.sim import SimQuoteFeed
from ...marketstructure.history import UA, fetch_window
from ...marketstructure.market_calendar import previous_trading_day
from ...marketstructure.sessions import ET, session_bounds
from ...models import BarRow
from .collect import normalize_daily
from .loss import daily_loss_report, snapshot_quotes


async def recover_prior_marks(engine, portfolio_id, *, now_ms, fetch=None):
    quotes = snapshot_quotes(engine)
    before = await daily_loss_report(engine, portfolio_id, now_ms=now_ms, quotes=quotes)
    day = previous_trading_day(dt.datetime.fromtimestamp(now_ms/1000, ET).date())
    opens, closes = session_bounds(day.isoformat())
    needed = sorted({a["symbol"] for a in before["assets"] if a["openingQty"] > 0 and a["priorClose"] is None})
    result = {"portfolioId": portfolio_id, "session": day.isoformat(), "requested": needed,
              "recovered": [], "preserved": [], "unavailable": [], "placesOrders": False}
    if not needed:
        result["report"] = before
        return result
    fetch = fetch or fetch_window
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=30.) as client:
        for symbol in needed[:64]:
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,31}", symbol):
                result["unavailable"].append({"symbol": symbol, "reason": "Unsupported historical symbol."})
                continue
            async with engine.sf() as session:
                existing = await session.scalar(select(BarRow).where(BarRow.symbol == symbol,
                    BarRow.tf == "1d", BarRow.ts == opens))
            if existing is not None:
                result["preserved"].append(symbol)
                result["unavailable"].append({"symbol": symbol, "reason": "Existing invalid mark requires review; not overwritten."})
                continue
            quote = quotes.get(symbol)
            source = quote.source if quote is not None else ""
            if source == "sim" or not source and (engine.config.quote_source == "sim" or isinstance(engine.feed, SimQuoteFeed)):
                result["unavailable"].append({"symbol": symbol, "reason": "Simulated tape requires its own prior-session mark; real history is not substituted."})
                continue
            if not source and engine.feed is None and engine.config.quote_source != "yahoo":
                result["unavailable"].append({"symbol": symbol, "reason": "Quote-source identity is unavailable; recovery cannot establish a compatible benchmark."})
                continue
            try:
                bars = normalize_daily(await fetch(symbol, "1d", opens, closes, client=client), symbol, closes)
                prior = next((b for b in bars if b.session == day), None)
                if prior is None:
                    raise ValueError("Provider returned no completed bar for the required session.")
                async with engine.sf() as session, session.begin():
                    added = await session.scalar(insert(BarRow).values(symbol=symbol, tf="1d", ts=opens,
                        open=prior.open, high=prior.high, low=prior.low, close=prior.close, volume=prior.volume)
                        .on_conflict_do_nothing(index_elements=["symbol", "tf", "ts"]).returning(BarRow.id))
                result["recovered" if added is not None else "preserved"].append(symbol)
            except (ValueError, httpx.HTTPError) as exc:
                result["unavailable"].append({"symbol": symbol, "reason": str(exc)})
    result["unavailable"].extend({"symbol": s, "reason": "Recovery batch limit reached."} for s in needed[64:])
    result["report"] = await daily_loss_report(engine, portfolio_id, now_ms=now_ms, quotes=quotes)
    await engine.journal.append(ev.OPTIONS_CARTEL_MARKS_RECOVERED,
        {"portfolioId": portfolio_id, "session": day.isoformat(), "source": "shared daily history",
         "recovered": result["recovered"], "preserved": result["preserved"], "unavailable": result["unavailable"]},
        aggregate_type="technique_risk", aggregate_id=f"options_cartel:{portfolio_id}:{day}", portfolio_id=portfolio_id)
    return result
