"""Collect and persist an independent campaign replay of an owned reviewed plan."""
from __future__ import annotations

import datetime as dt
import math
from typing import Literal

import httpx
from pydantic import Field
from sqlalchemy import select

from ...domain import Bar
from ...execution.sizing import size_by_budget, size_by_risk
from ...fx import MAX_RATE_AGE_MS, currency_for_symbol, fx_pair_symbol
from ...marketstructure.history import UA, fetch_window
from ...marketstructure.sessions import session_bounds
from ...models import BarRow, Portfolio, TechniqueArmed
from .collect import normalize_daily
from .data import DailyBar
from .data_quality import evidence, pack
from .exits import ExitCampaign, allocation_preview
from .plans import CartelPlan
from .replay import replay_campaign
from .service import CartelService, WireModel


class CampaignReplayRequest(WireModel):
    source: Literal["stored", "provider"] = "stored"
    as_of_ms: int | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, ge=1, le=1_000_000)
    slippage_bps: float = Field(default=0, ge=0, le=100)


async def replay_quantity(service, run_id, requested, now):
    """Current observed sizing context, never an invented historical fill."""
    if requested is not None:
        return requested, {"kind": "hypothetical", "note": "Explicit modeled units; account funding is not established."}
    engine = service.engine
    async with engine.sf() as session:
        arm = await session.get(TechniqueArmed, run_id)
        portfolio = await session.get(Portfolio, arm.portfolio_id) if arm and arm.technique == "options_cartel" else None
    if arm is not None and arm.technique == "options_cartel":
        filled = arm.state.get("adoptedEntryQty")
        if isinstance(filled, (int, float)) and not isinstance(filled, bool) and math.isfinite(filled) \
                and 0 < filled <= 1_000_000 and float(filled).is_integer():
            execution = getattr(arm, 'config', {}).get('execution', {})
            return int(filled), {"kind": "recorded_fill", "observedAt": now, "portfolioId": arm.portfolio_id,
                "contractSymbol": execution.get('contract_symbol'), "instrument": execution.get('instrument'),
                "note": "Original confirmed filled units observed now; modeled replay times/prices remain hypothetical."}
        spec = arm.config.get("execution", {})
        symbol = spec.get("contract_symbol")
        quote = engine.quotes.get(symbol) if symbol else None
        if portfolio is not None and spec.get("instrument") == "options" and quote is not None:
            age_limit = float(engine.settings.get("risk.stale_quote_seconds", 10))*1000
            source_at = quote.source_ts or quote.ts
            currency, base = currency_for_symbol(symbol), portfolio.base_currency.upper()
            fx = engine.positions.fx.rate(currency, base)
            fx_quote = (engine.quotes.get(fx_pair_symbol(currency, base)) or
                engine.quotes.get(fx_pair_symbol(base, currency))) if currency != base else None
            fx_ready = fx is not None and math.isfinite(fx) and fx > 0 and (currency == base or
                fx_quote is not None and 0 <= now-fx_quote.ts < MAX_RATE_AGE_MS)
            if quote.source in ('opra', 'sim') and not quote.delayed and not quote.halted and 0 <= now-source_at <= age_limit \
                    and math.isfinite(quote.ask) and math.isfinite(quote.bid) and 0 < quote.bid <= quote.ask and fx_ready:
                equity = float(await engine.positions.equity(arm.portfolio_id))
                budget, risk_pct, maximum = spec.get("budget"), spec.get("risk_pct"), spec.get("max_units", 10)
                if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0
                       for v in (budget, risk_pct, equity, maximum)):
                    units = min(size_by_budget(budget, quote.ask*100*fx, max_units=int(maximum)),
                                size_by_risk(equity, risk_pct, quote.ask*100*fx, max_units=int(maximum)))
                    if units:
                        return units, {"kind": "current_funding_estimate", "observedAt": now,
                            "portfolioId": arm.portfolio_id, "contractSymbol": symbol,
                            "quoteSourceAt": source_at, "ask": quote.ask, "fxRate": fx,
                            "note": "Current quote, premium budget and equity sizing; not historical funding or permission to trade."}
    return 1, {"kind": "hypothetical", "note": "No confirmed filled or fresh funded quantity is available; one hypothetical unit."}


async def replay_from_history(service: CartelService, run_id, body: CampaignReplayRequest, *, fetch=None, now_ms=None):
    now = now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp()*1000)
    at = body.as_of_ms if body.as_of_ms is not None else now
    if at > now:
        raise ValueError("historical replay cutoff cannot be in the future")
    parent = await service._load(run_id)
    if parent.mode != "plan":
        raise ValueError("campaign replay requires an owned reviewed plan")
    plan = CartelPlan.model_validate(parent.result["plan"]["plan"])
    start = session_bounds(plan.first_session.isoformat())[0]
    if at <= start:
        raise ValueError("the plan's entry window has not opened at this cutoff")
    campaign = ExitCampaign.model_validate(parent.result["exitCampaign"])
    quantity, quantity_basis = await replay_quantity(service, run_id, body.quantity, now)
    daily = [DailyBar.model_validate(b) for b in parent.config["inputs"]["history"]]
    warnings = []
    if body.source == "stored":
        async with service.engine.sf() as session:
            rows = (await session.scalars(select(BarRow).where(BarRow.symbol == plan.symbol,
                BarRow.ts >= start, BarRow.ts < at, BarRow.tf.in_(("1m", "1d"))).order_by(BarRow.ts))).all()
        minutes = [Bar(r.symbol, r.tf, r.ts, r.open, r.high, r.low, r.close, r.volume, source=r.source) for r in rows if r.tf == "1m"]
        extra = [Bar(r.symbol, r.tf, r.ts, r.open, r.high, r.low, r.close, r.volume, source=r.source) for r in rows if r.tf == "1d"]
        source = "Stored engine bars with retained source classification; revisions may differ from the live decision."
    else:
        fetch = fetch or fetch_window
        async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=30.) as client:
            minutes = await fetch(plan.symbol, "1m", start, at, client=client)
            extra = await fetch(plan.symbol, "1d", start, at, client=client)
        source = "Shared historical provider; modeled fills, not a replay of broker executions."
        warnings.append("Provider minute-history depth limits apply; missing tape remains unscorable.")
    if len(minutes) > 40_000:
        raise ValueError("replay exceeds the 40,000-minute input limit; choose an earlier cutoff")
    daily.extend(normalize_daily(extra, plan.symbol, at))
    result = replay_campaign(plan, campaign, minutes, daily, as_of_ms=at,
                             quantity=quantity, slippage_bps=body.slippage_bps)
    result["quantityBasis"] = quantity_basis
    result["exitAllocation"] = allocation_preview(campaign, quantity)
    result['dataEvidence'] = evidence({str(b.ts):pack(b) for b in minutes})
    result["warnings"].extend(warnings)
    return await service._store(mode="replay", symbol=plan.symbol, at=at, verdict=result["status"], parent=run_id,
        result=result, config={"request": {**body.model_dump(mode="json"), "quantity": quantity},
            "quantityBasis": quantity_basis, "dataSource": source,
            "planSnapshot": parent.result["plan"], "exitCampaign": campaign.model_dump(mode="json"),
            "baselineMinutes": [b for b in parent.config["inputs"].get("minute_history", [])],
            "minutes": [pack(b) for b in minutes], "daily": [b.model_dump(mode="json") for b in daily]})
