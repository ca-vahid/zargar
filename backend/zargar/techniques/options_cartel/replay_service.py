"""Collect and persist an independent campaign replay of an owned reviewed plan."""
from __future__ import annotations

import datetime as dt
from typing import Literal

import httpx
from pydantic import Field
from sqlalchemy import select

from ...domain import Bar
from ...marketstructure.history import UA, fetch_window
from ...marketstructure.sessions import session_bounds
from ...models import BarRow
from .collect import normalize_daily
from .data import DailyBar
from .exits import ExitCampaign
from .plans import CartelPlan
from .replay import replay_campaign
from .service import CartelService, WireModel


class CampaignReplayRequest(WireModel):
    source: Literal["stored", "provider"] = "stored"
    as_of_ms: int | None = Field(default=None, ge=0)
    quantity: int = Field(default=100, ge=1, le=1_000_000)
    slippage_bps: float = Field(default=0, ge=0, le=100)


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
    daily = [DailyBar.model_validate(b) for b in parent.config["inputs"]["history"]]
    warnings = []
    if body.source == "stored":
        async with service.engine.sf() as session:
            rows = (await session.scalars(select(BarRow).where(BarRow.symbol == plan.symbol,
                BarRow.ts >= start, BarRow.ts < at, BarRow.tf.in_(("1m", "1d"))).order_by(BarRow.ts))).all()
        minutes = [Bar(r.symbol, r.tf, r.ts, r.open, r.high, r.low, r.close, r.volume) for r in rows if r.tf == "1m"]
        extra = [Bar(r.symbol, r.tf, r.ts, r.open, r.high, r.low, r.close, r.volume) for r in rows if r.tf == "1d"]
        source = "Stored engine bars; per-bar feed identity is not retained and data may be simulated."
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
                             quantity=body.quantity, slippage_bps=body.slippage_bps)
    result["warnings"].extend(warnings)
    return await service._store(mode="replay", symbol=plan.symbol, at=at, verdict=result["status"], parent=run_id,
        result=result, config={"request": body.model_dump(mode="json"), "dataSource": source,
            "planSnapshot": parent.result["plan"], "exitCampaign": campaign.model_dump(mode="json"),
            "baselineMinutes": [b for b in parent.config["inputs"].get("minute_history", [])],
            "minutes": [b.to_row() for b in minutes], "daily": [b.model_dump(mode="json") for b in daily]})
