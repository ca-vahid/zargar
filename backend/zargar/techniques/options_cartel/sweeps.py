"""Paired entry-parameter experiments on immutable campaign replay inputs."""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from ...domain import Bar
from .data import DailyBar
from .exits import ExitCampaign
from .plans import CartelPlan, EntryPolicy
from .preparation_readiness import baseline_coverage
from .replay import replay_campaign
from .service import WireModel


class SweepVariant(WireModel):
    name: str = Field(min_length=1, max_length=80)
    timeframe_minutes: Literal[5, 15, 30] | None = None
    mode: Literal["breakout", "retest"] | None = None
    volume_multiple: float | None = Field(default=None, gt=0, le=100)
    min_close_location: float | None = Field(default=None, ge=0, le=1)
    max_chase_r: float | None = Field(default=None, ge=0, le=10)


class SweepRequest(WireModel):
    replay_ids: list[str] = Field(min_length=1, max_length=20)
    variants: list[SweepVariant] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_inputs(self):
        names = [v.name.strip() for v in self.variants]
        if len(set(self.replay_ids)) != len(self.replay_ids) or len(set(names)) != len(names) \
                or any(not name or name == "baseline" for name in names):
            raise ValueError("replays and variant names must be unique; baseline is reserved")
        return self


def evaluate_sweep(snapshots, variants):
    rows = []
    for saved in snapshots:
        config = saved["config"]
        original = CartelPlan.model_validate(config["planSnapshot"]["plan"])
        campaign = ExitCampaign.model_validate(config["exitCampaign"])
        minutes = [Bar(original.symbol, "1m", *b) for b in config["minutes"]]
        daily = [DailyBar.model_validate(b) for b in config["daily"]]
        for name, overrides in [("baseline", {})] + [
                (v.name.strip(), v.model_dump(exclude_none=True, exclude={"name"})) for v in variants]:
            policy = EntryPolicy.model_validate({**original.entry.model_dump(), **overrides})
            updates = {"entry": policy}
            if policy.timeframe_minutes != original.entry.timeframe_minutes:
                from .prepare import build_volume_baseline
                source = config.get('baselineMinutes', [])
                if not source:
                    raise ValueError('Timeframe comparisons need historical baseline minutes. Create a new campaign replay from the original plan.')
                historical = [Bar(original.symbol, '1m', b['ts'], b['open'], b['high'], b['low'], b['close'], b['volume']) for b in source]
                updates['volume_baseline'] = build_volume_baseline(historical, original.symbol,
                    policy.timeframe_minutes, original.created_at)['baselines']
            plan = original.model_copy(update=updates)
            result = replay_campaign(plan, campaign, minutes, daily, as_of_ms=saved["asOfMs"],
                quantity=config["request"]["quantity"], slippage_bps=config["request"]["slippage_bps"])
            coverage = baseline_coverage(plan)
            if policy.timeframe_minutes != original.entry.timeframe_minutes and not coverage['ready']:
                result['dataComplete'] = False
                result['warnings'].append(f"Variant baseline incomplete: {coverage['available']}/{coverage['expected']} periods; not scored.")
            rows.append({"baselineCoverage": coverage, "replayId": saved["runId"], "symbol": original.symbol, "variant": name,
                         "entryPolicy": policy.model_dump(mode="json"), "result": result})
    summaries = []
    baseline = {r["replayId"]: r["result"] for r in rows if r["variant"] == "baseline"}
    for name in ["baseline"] + [v.name.strip() for v in variants]:
        group = [r["result"] for r in rows if r["variant"] == name]
        scored = [r["realizedR"] for r in group if r["status"] == "closed" and r["dataComplete"]]
        paired = [(r["result"]["realizedR"], baseline[r["replayId"]]["realizedR"]) for r in rows
                  if r["variant"] == name and r["result"]["status"] == "closed" and r["result"]["dataComplete"]
                  and baseline[r["replayId"]]["status"] == "closed" and baseline[r["replayId"]]["dataComplete"]]
        summaries.append({"variant": name, "cases": len(group), "closedScored": len(scored),
                          "incomplete": sum(not r["dataComplete"] for r in group),
                          "open": sum(r["status"] == "open" for r in group),
                          "meanClosedR": sum(scored)/len(scored) if scored else None,
                          "pairedClosed": len(paired),
                          "pairedMeanDeltaR": sum(value-base for value, base in paired)/len(paired) if paired else None,
                          "winRate": sum(r > 0 for r in scored)/len(scored) if scored else None})
    return {"simulation": True, "placesOrders": False, "rows": rows, "summaries": summaries,
            "warnings": ["Selected-plan experiment, not a universe walk-forward study. Selection bias remains.",
                         "Closed-case averages may use different cases per variant; inspect paired rows.",
                         "Underlying-price outcomes omit option premiums, fees and live execution behavior."]}


async def run_sweep(service, body: SweepRequest):
    snapshots = []
    seen_plans = set()
    total = 0
    for rid in body.replay_ids:
        row = await service._load(rid)
        if row.mode != "replay" or "exitCampaign" not in row.config:
            raise ValueError("sweeps require campaign replay records")
        if row.parent_run_id in seen_plans:
            raise ValueError("select only one replay per plan to avoid counting it twice")
        seen_plans.add(row.parent_run_id)
        total += len(row.config["minutes"])
        if total*(len(body.variants)+1) > 400_000:
            raise ValueError("sweep exceeds 400,000 minute evaluations; select fewer cases or variants")
        snapshots.append({"runId": row.id, "asOfMs": row.as_of, "config": row.config})
    result = await asyncio.to_thread(evaluate_sweep, snapshots, body.variants)
    digest = hashlib.sha256(json.dumps(snapshots, sort_keys=True).encode()).hexdigest()
    return await service._store(mode="sweep", symbol="MULTI", at=max(s["asOfMs"] for s in snapshots),
        verdict="experiment", result=result, config={"request": body.model_dump(mode="json"),
            "inputSha256": digest, "codeVersion": "cartel-sweep-2", "snapshots": snapshots})
