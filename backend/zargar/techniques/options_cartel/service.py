"""Persisted Cartel research/plan/review service. No order or broker side effects."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import select

from ... import events as ev
from ...domain import Bar, new_id
from ...models import TechniqueReview, TechniqueRun
from .data import DailyBar, completed_daily
from .entry import read_entry
from .exits import ExitCampaign
from .plans import CartelPlan, EntryPolicy
from .prepare import prepare_plan
from .rules import CartelRules
from .screen import ListingFacts, screen_listing
from .setups import SetupParameters, analyze_setups

TECHNIQUE = "options_cartel"


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel,
                              allow_inf_nan=False)


class FactsInput(ListingFacts):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel,
                              allow_inf_nan=False)


class MinuteInput(WireModel):
    symbol: str = Field(min_length=1, max_length=32)
    ts: int = Field(ge=0)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def candle(self):
        if self.ts % 60_000 or self.high < max(self.open, self.low, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid aligned minute OHLC")
        return self

    def bar(self):
        return Bar(tf="1m", **self.model_dump())


class ResearchInput(WireModel):
    membership_snapshot_id: str | None = Field(default=None, max_length=64)
    fundamentals_snapshot_id: str | None = Field(default=None, max_length=64)
    industry_snapshot_id: str | None = Field(default=None, max_length=64)
    history: list[DailyBar] = Field(min_length=1, max_length=3000)
    indices: dict[str, list[DailyBar]]
    facts: FactsInput
    rules: CartelRules = Field(default_factory=CartelRules)
    parameters: SetupParameters = Field(default_factory=SetupParameters)
    minute_history: list[MinuteInput] = Field(default_factory=list, max_length=40_000)
    as_of_ms: int = Field(ge=0)
    direction: Literal["long", "short"] = "long"
    data_source: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def bounded_indices(self):
        if set(self.indices) - {"SPY", "QQQ"} or any(len(v) > 3000 for v in self.indices.values()):
            raise ValueError("indices must be bounded SPY/QQQ histories")
        if not self.data_source.strip() or len(self.facts.symbol) > 32:
            raise ValueError("invalid source or symbol")
        return self


class PlanInput(WireModel):
    setup: str = Field(min_length=1, max_length=24)
    horizon_sessions: int = Field(ge=1, le=60)
    entry_policy: EntryPolicy = Field(default_factory=EntryPolicy)
    reviewed_targets: tuple[float, ...] | None = None
    review_note: str = Field(min_length=1, max_length=10000)
    target_source: str | None = Field(default=None, max_length=2000)
    exit_campaign: ExitCampaign


class ReplayInput(WireModel):
    minutes: list[MinuteInput] = Field(max_length=40_000)
    as_of_ms: int = Field(ge=0)
    data_source: str = Field(min_length=1, max_length=2000)


class ReviewInput(WireModel):
    verdict: Literal["correct", "wrong_levels", "wrong_plan", "data_issue", "unclear"]
    stage: Literal["data", "setup", "entry", "exit", "expression", "execution", "other"]
    notes: str = Field(min_length=1, max_length=10000)


class CartelService:
    def __init__(self, engine):
        self.engine = engine
        from .position_adapter import register_cartel_policy
        register_cartel_policy(engine)

    async def _load(self, run_id: str) -> TechniqueRun:
        async with self.engine.sf() as session:
            row = await session.scalar(select(TechniqueRun).where(TechniqueRun.id == run_id,
                                                                  TechniqueRun.technique == TECHNIQUE))
        if row is None:
            raise KeyError("Cartel run not found")
        return row

    @staticmethod
    def _view(row, *, detail=False):
        out = {"runId": row.id, "technique": row.technique, "symbol": row.symbol, "mode": row.mode,
               "status": row.status, "verdict": row.verdict, "asOfMs": row.as_of,
               "parentRunId": row.parent_run_id, "createdAt": row.created_at.isoformat()}
        if detail:
            out.update(result=row.result, config=row.config)
            if row.mode == 'industry':
                from .industry import IndustrySnapshot, captured_ranks
                ranks = captured_ranks(IndustrySnapshot.model_validate(row.config['inputs']))
                out['result'] = {**row.result, 'rows': [
                    {**entry, 'capturedRanks': ranks[entry['industry']]} for entry in row.result['rows']]}
            source = row.config.get("inputs", {}).get("history") if row.mode in ("analysis", "plan") else \
                row.config.get("daily") if row.mode == "replay" else None
            if source is not None:
                out["chart"] = {"asOfMs": row.as_of, "daily": [b.model_dump(mode="json") for b in
                    completed_daily([DailyBar.model_validate(b) for b in source], row.as_of)]}
        return out

    async def _store(self, *, mode, symbol, at, result, config, verdict, parent=None, run_id=None):
        row = TechniqueRun(id=run_id or new_id(), technique=TECHNIQUE, symbol=symbol,
                           as_of=at, primary_tf="1d", mode=mode, trigger="manual", status="done",
                           verdict=verdict, result=result, config=config, parent_run_id=parent,
                           finished_at=dt.datetime.now(dt.UTC), tags=[f"cartel:{mode}"])
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        await self.engine.journal.append(ev.TECHNIQUE_RUN_COMPLETED,
                                        {"runId": row.id, "symbol": symbol, "technique": TECHNIQUE,
                                         "mode": mode, "verdict": verdict},
                                        aggregate_type="technique_run", aggregate_id=row.id)
        return self._view(row, detail=True)

    async def analyze(self, body: ResearchInput, *, collection: dict | None = None, parent_run_id=None):
        if body.membership_snapshot_id:
            record = await self._load(body.membership_snapshot_id)
            if record.mode != 'membership' or record.symbol != body.facts.symbol or record.verdict != 'verified':
                raise ValueError('selected membership must be a verified owned capture for this symbol')
            evidence = record.config['inputs']
            facts = FactsInput.model_validate({**body.facts.model_dump(),
                'industry': evidence['industry'], 'membership_observed_at': evidence['observedAt'],
                'membership_source': evidence['source'], 'membership_snapshot_id': record.id})
            body = body.model_copy(update={'facts': facts})
        if body.fundamentals_snapshot_id:
            from .fundamentals import normalize
            record = await self._load(body.fundamentals_snapshot_id)
            if record.mode != 'fundamentals' or record.symbol != body.facts.symbol:
                raise ValueError('selected fundamentals must be an owned capture for this symbol')
            raw = record.config['inputs']
            evidence = normalize(body.facts.symbol, raw['summary'], observed_at=raw['observedAt'])
            facts = FactsInput.model_validate({**body.facts.model_dump(),
                'market_cap': evidence['marketCapUsd'], 'cap_observed_at': evidence['observedAt'],
                'cap_data_as_of_ms': evidence['providerPriceAt'], 'cap_source': evidence['source'],
                'fundamentals_snapshot_id': record.id})
            body = body.model_copy(update={'facts': facts})
        if body.industry_snapshot_id:
            from .industry import IndustrySnapshot, read_industry
            record = await self._load(body.industry_snapshot_id)
            if record.mode != 'industry':
                raise ValueError('selected industry evidence must be an owned industry snapshot')
            snapshot = IndustrySnapshot.model_validate(record.config['inputs'])
            ranked = read_industry(snapshot, body.facts.industry or '', at=body.as_of_ms,
                                   direction=body.direction, top_n=body.rules.industry_top_n,
                                   max_age_days=body.rules.max_metadata_age_days)
            facts = FactsInput.model_validate({**body.facts.model_dump(),
                'industry_snapshot_id': record.id, 'rank_source': snapshot.source,
                'rank_observed_at': snapshot.observed_at, 'rank_data_as_of_ms': snapshot.data_as_of_ms,
                'rank_freshness_basis': snapshot.freshness_basis,
                'rank_direction': body.direction,
                'week_rank': (ranked['weekRank'] or {}).get('worst'),
                'week_rank_best': (ranked['weekRank'] or {}).get('best'),
                'month_rank': (ranked['monthRank'] or {}).get('worst'),
                'month_rank_best': (ranked['monthRank'] or {}).get('best')})
            body = body.model_copy(update={'facts': facts})
        screen = screen_listing(body.history, body.facts, body.indices, body.rules, body.as_of_ms,
                                direction=body.direction)
        analysis = analyze_setups(body.history, body.indices.get("SPY", []), screen, body.parameters,
                                  body.as_of_ms, direction=body.direction)
        inputs = body.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        return await self._store(mode="analysis", symbol=body.facts.symbol, at=body.as_of_ms,
                                 result={"screen": screen, "analysis": analysis, "collection": collection},
                                 config={"inputs": inputs, "inputSha256": digest, "dataSource": body.data_source,
                                         "thresholds": body.rules.model_dump(mode="json"), "codeVersion": "cartel-research-1"},
                                 verdict="setup" if any(c["contextPassed"] for c in analysis["candidates"]) else "watch_only",
                                 parent=parent_run_id)

    async def collect_and_analyze(self, body):
        from .collect import collect_inputs
        research, provenance = await collect_inputs(body)
        return await self.analyze(research, collection=provenance)

    async def prepare(self, run_id: str, body: PlanInput, *, plan_id=None, preparation=None):
        parent = await self._load(run_id)
        if parent.mode != "analysis":
            raise ValueError("prepare requires an analysis run")
        inputs = ResearchInput.model_validate(parent.config["inputs"])
        new = plan_id or new_id()
        prepared = prepare_plan(plan_id=new, history=inputs.history, indices=inputs.indices, facts=inputs.facts,
                                rules=inputs.rules, parameters=inputs.parameters, entry_policy=body.entry_policy,
                                minute_history=[b.bar() for b in inputs.minute_history], as_of_ms=inputs.as_of_ms,
                                direction=inputs.direction, setup=body.setup, horizon_sessions=body.horizon_sessions,
                                reviewed_targets=body.reviewed_targets, review_note=body.review_note,
                                target_source=body.target_source)
        plan = CartelPlan.model_validate(prepared["plan"]["plan"])
        targets = [r.target for r in body.exit_campaign.rungs if r.kind == "target"]
        if targets != list(plan.targets[:len(targets)]):
            raise ValueError("exit campaign target levels must match the reviewed plan targets")
        prepared["exitCampaign"] = body.exit_campaign.model_dump(mode="json")
        return await self._store(mode="plan", symbol=parent.symbol, at=parent.as_of, result=prepared,
                                 config={**parent.config, "reviewedPlan": body.model_dump(mode="json"),
                                         **({'preparation': preparation} if preparation is not None else {})},
                                 verdict="plan", parent=parent.id, run_id=new)

    async def replay(self, run_id: str, body: ReplayInput):
        parent = await self._load(run_id)
        if parent.mode != "plan":
            raise ValueError("entry replay requires a plan run")
        plan = CartelPlan.model_validate(parent.result["plan"]["plan"])
        result = read_entry(plan, [b.bar() for b in body.minutes], body.as_of_ms)
        return await self._store(mode="replay", symbol=parent.symbol, at=body.as_of_ms,
                                 result={"entryRead": result, "simulation": True, "placesOrders": False},
                                 config={"replayInputs": body.model_dump(mode="json"),
                                         "planSnapshot": parent.result["plan"], "dataSource": body.data_source},
                                 verdict=result["status"], parent=parent.id)

    async def runs(self, limit=50, symbol=None, mode=None):
        query = select(TechniqueRun).where(TechniqueRun.technique == TECHNIQUE)
        if symbol:
            query = query.where(TechniqueRun.symbol == symbol.upper())
        if mode:
            query = query.where(TechniqueRun.mode == mode)
        async with self.engine.sf() as session:
            rows = (await session.scalars(query.order_by(TechniqueRun.created_at.desc(), TechniqueRun.id)
                                         .limit(min(200, max(1, limit))))).all()
        return [self._view(row) for row in rows]

    async def detail(self, run_id):
        row = await self._load(run_id)
        async with self.engine.sf() as session:
            reviews = (await session.scalars(select(TechniqueReview).where(TechniqueReview.run_id == row.id)
                                              .order_by(TechniqueReview.created_at, TechniqueReview.id))).all()
        return {**self._view(row, detail=True), "reviews": [
            {"id": r.id, "verdict": r.review_verdict, "stage": r.root_cause_stage,
             "notes": r.notes, "createdAt": r.created_at.isoformat()} for r in reviews]}

    async def review(self, run_id, body: ReviewInput):
        parent = await self._load(run_id)
        row = TechniqueReview(id=new_id(), run_id=parent.id, reviewer="user", review_verdict=body.verdict,
                              root_cause_stage=body.stage, notes=body.notes,
                              process_version={"inputSha256": parent.config.get("inputSha256"),
                                               "codeVersion": parent.config.get("codeVersion")})
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        await self.engine.journal.append(ev.TECHNIQUE_REVIEW_ADDED,
                                        {"runId": parent.id, "reviewId": row.id, "technique": TECHNIQUE},
                                        aggregate_type="technique_run", aggregate_id=parent.id)
        return {"id": row.id, "runId": parent.id}
