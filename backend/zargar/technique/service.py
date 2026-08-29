"""TechniqueService — orchestration, persistence, journaling, scheduled scans.

One `analyze()` call = one `technique_runs` row + one chat thread holding the
pipeline transcript. Every lifecycle step is journaled; valid setups land in
`technique_setups` and, when `technique.emit_proposals` is on, become practice
proposals that go through the normal approval → RiskGate path (no code path
here submits an order).
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime as dt
import functools
import gzip
import json
import logging
import math
import os
import pickle
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from sqlalchemy import func, select

from .. import bus as topics
from .. import events as ev
from ..domain import Bar, new_id
from ..models import (
    Proposal,
    TechniqueOutcome,
    TechniqueReview,
    TechniqueRun,
    TechniqueSetup,
    TechniqueSweep,
    TechniqueWalkforward,
)
from .analysis import WINDOW_FOR_TF, AnalysisRequest, compute_facts, facts_for_prompt, gather_bars
from .arming import PlanArmer
from .backtest import run_backtest
from . import history as history_mod
from .history import fetch_session
from .llm import LLMConfig, config_from_settings, make_client
from .options import CboeClient, TradierClient, pick_for_setup
from .outcome import (
    bars_to_rows,
    describe_outcome,
    fetch_after,
    horizon_still_fetchable,
    outcome_dict,
    path_summary,
    plan_from_candidate,
    plan_from_contract,
    rows_to_bars,
    same_plan,
    simulate_plan,
)
from .plans import build_session_plan, plan_summary_text
from .provenance import snapshot as provenance_snapshot
from .provenance import sweep_version, technique_source_version
from .render import render_chart
from .review import diff_runs, review_dict, validate_review
from .rulebook import (
    ET,
    PRIME_WINDOWS,
    RULES,
    WINDOW_RULE,
    Thresholds,
    next_session_date,
    session_bounds,
    session_date,
    session_window,
    thresholds_from_settings,
)
from .vision import PipelineResult, VisionPipeline, transcript_messages
from .volume import build_profile
from .walkforward import aggregate as aggregate_sweep
from .walkforward import (
    compute_symbol_plan,
    compute_symbol_rows,
    fetch_symbol_bars,
    last_completed_session,
    replay_plan,
    score_pending_row,
)

log = logging.getLogger("zargar.technique")

RTH_START = dt.time(9, 30)
RTH_END = dt.time(16, 0)


def run_dict(r: TechniqueRun) -> dict:
    return {
        "id": r.id, "technique": getattr(r, "technique", None) or "enhanced_market",
        "tags": list(getattr(r, "tags", None) or []),
        "threadId": r.thread_id, "symbol": r.symbol, "asOf": r.as_of,
        "primaryTf": r.primary_tf, "mode": r.mode, "trigger": r.trigger, "status": r.status,
        "verdict": r.verdict, "setupType": r.setup_type, "confidence": r.confidence,
        "grounded": r.grounded, "facts": r.facts or {}, "result": r.result or {},
        "images": r.images or {}, "usage": r.usage or {}, "error": r.error, "llm": r.llm or {},
        "config": r.config or {}, "parentRunId": r.parent_run_id,
        "processVersion": (r.config or {}).get("processVersion"),
        "createdAt": r.created_at.isoformat() if r.created_at else None,
        "finishedAt": r.finished_at.isoformat() if r.finished_at else None,
    }


def run_summary(r: TechniqueRun) -> dict:
    d = run_dict(r)
    d.pop("facts", None)
    d.pop("config", None)
    res = d.pop("result", None) or {}
    d["analysis"] = res.get("analysis")
    d["groundingPassed"] = (res.get("grounding") or {}).get("passed")
    d["traceSteps"] = len(res.get("trace") or [])
    d["seconds"] = res.get("seconds")
    d["sessionWindow"] = res.get("sessionWindow")
    d["plan"] = _slim_plan_summary(res.get("plan"))
    return d


def setup_dict(s: TechniqueSetup) -> dict:
    return {
        "id": s.id, "technique": getattr(s, "technique", None) or "enhanced_market",
        "runId": s.run_id, "symbol": s.symbol, "setupType": s.setup_type,
        "direction": s.direction, "entry": s.entry, "stop": s.stop, "targets": s.targets or [],
        "riskReward": s.risk_reward, "confidence": s.confidence, "valid": s.valid,
        "rules": s.rules or [], "noTradeReasons": s.no_trade_reasons or [], "options": s.options,
        "proposalId": s.proposal_id, "status": s.status,
        "createdAt": s.created_at.isoformat() if s.created_at else None,
    }


class TechniqueService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.chat = None                     # set by attach
        self._client = None
        self._client_key: str | None = None
        self._tradier: TradierClient | None = None
        self._cboe: CboeClient | None = None
        self._scan_task: asyncio.Task | None = None
        self._outcome_task: asyncio.Task | None = None
        self._running: dict[str, asyncio.Task] = {}
        self._sweeps: dict[str, asyncio.Task] = {}
        # Ad-hoc runs (scan-now, bulk analyst-checks) queue past this — a 13-symbol
        # burst was rendering 13x3 charts at once and starving the event loop.
        # Sized from technique.max_concurrent_runs on first use (settings load later).
        self._run_sem: asyncio.Semaphore | None = None
        self.armer = PlanArmer(engine, self)
        # Live progress for running runs so a client that connects mid-run (or
        # reloads) can seed its view: {run_id: {"passes": [...], "grounding", "facts"}}
        self._live: dict[str, dict] = {}

    # ------------------------------------------------------------ config
    def llm_config(self) -> LLMConfig:
        return config_from_settings(self.engine.config.anthropic_api_key, self.engine.settings.get)

    def thresholds(self) -> Thresholds:
        return thresholds_from_settings(self.engine.settings.get)

    def _get_client(self):
        cfg = self.llm_config()
        if self._client is None or self._client_key != cfg.api_key:
            self._client = make_client(cfg)
            self._client_key = cfg.api_key
        return self._client

    def tradier(self) -> TradierClient | None:
        tok = self.engine.config.tradier_token
        if not tok:
            return None
        if self._tradier is None:
            self._tradier = TradierClient(tok, sandbox=bool(self.engine.config.tradier_sandbox))
        return self._tradier

    def options_provider(self):
        """CBOE by default — free, no credentials, reachable from Canada
        (Tradier's developer signup needs a US address). `options.provider`
        can force tradier for anyone who does have a token."""
        opts = getattr(self.engine, "options", None)
        if opts is not None:
            return opts.provider()
        pref = str(self.engine.settings.get("options.provider", "cboe"))
        if pref == "tradier":
            t = self.tradier()
            if t is not None:
                return t
        if self._cboe is None:
            self._cboe = CboeClient()
        return self._cboe

    # ------------------------------------------------------------ universe
    def universe_cached(self) -> dict:
        """The resolved universe as last computed (today's if refreshed today)."""
        from . import universe as uni
        s = self.engine.settings
        cached = s.get("technique.universe.resolved", {}) or {}
        if cached.get("date") == uni.today_key() and cached.get("symbols"):
            return dict(cached)
        core = list(s.get("technique.walkforward.symbols", []) or [])
        r = uni.resolve(core=core, extra=list(s.get("technique.universe.extra", []) or []),
                        exclude=list(s.get("technique.universe.exclude", []) or []), auto=[],
                        min_price=float(s.get("technique.universe.min_price", 20.0) or 0),
                        auto_top=int(s.get("technique.universe.auto_top", 40) or 0))
        return {"date": None, "refreshedAt": None, "autoSource": None, **r}

    async def refresh_universe(self, *, force: bool = False) -> dict:
        """Recompute the working universe: core + extras + today's most-active US
        stocks (price-floored). Cached per ET date in `technique.universe.resolved`
        so the evening sheet and the picker see one list."""
        from . import universe as uni
        s = self.engine.settings
        cached = s.get("technique.universe.resolved", {}) or {}
        if not force and cached.get("date") == uni.today_key() and cached.get("symbols"):
            return dict(cached)
        auto: list[dict] = []
        source = None
        if bool(s.get("technique.universe.auto_refresh", True)):
            try:
                auto = await uni.fetch_most_actives(alpaca_key=self.engine.config.alpaca_key_id,
                                                    alpaca_secret=self.engine.config.alpaca_secret,
                                                    top=max(50, int(s.get("technique.universe.auto_top", 40) or 0) * 3))
                source = auto[0]["source"] if auto else None
            except Exception as exc:
                log.warning("universe auto-refresh failed: %s", exc)
        prices: dict[str, float] = {}
        need = [r["symbol"] for r in auto if r.get("price") is None]
        for sym in need[:120]:
            q = self.engine.quotes.get(sym)
            if q is not None and q.last > 0:
                prices[sym] = float(q.last)
        flow_syms: list[str] = []
        flow_svc = getattr(self.engine, "flow_service", None)
        if flow_svc is not None:
            with contextlib.suppress(Exception):
                flow_syms = await flow_svc.universe_layer()
        r = uni.resolve(core=list(s.get("technique.walkforward.symbols", []) or []),
                        extra=list(s.get("technique.universe.extra", []) or []),
                        exclude=list(s.get("technique.universe.exclude", []) or []), auto=auto,
                        min_price=float(s.get("technique.universe.min_price", 20.0) or 0),
                        auto_top=int(s.get("technique.universe.auto_top", 40) or 0), prices=prices,
                        flow=flow_syms)
        out = {"date": uni.today_key(), "refreshedAt": int(time.time() * 1000), "autoSource": source, **r}
        await s.set("technique.universe.resolved", out, journal=False)
        log.info("universe refreshed: %d symbols (%s)", len(out["symbols"]), out["counts"])
        return out

    async def universe(self) -> list[str]:
        """The symbols to plan/sheet by default (refreshes once per day)."""
        try:
            return list((await self.refresh_universe())["symbols"])
        except Exception:
            return list(self.universe_cached()["symbols"])

    async def status(self) -> dict:
        cfg = self.llm_config()
        return {
            "llmAvailable": cfg.available, "model": cfg.model, "effort": cfg.effort,
            "thinkingDisplay": cfg.thinking_display,
            "optionsAvailable": bool(self.engine.settings.get("technique.options.enabled", True)),
            "optionsProvider": getattr(self.options_provider(), "name", "?"),
            "runsToday": await self.runs_today(),
            "maxRunsPerDay": int(self.engine.settings.get("technique.max_runs_per_day", 40)),
            "scanEnabled": bool(self.engine.settings.get("technique.scan.enabled", False)),
            "scanSymbols": list(self.engine.settings.get("technique.scan.symbols", [])),
            "running": [rid for rid, t in self._running.items() if not t.done()],
            # tasks actually holding a semaphore slot right now (the rest of
            # `running` are queued) — lets the scan panel show real progress
            "activeRuns": {rid: {"symbol": lv.get("symbol"),
                                 "stage": (lv["passes"][-1]["name"] if lv.get("passes") else "preparing")}
                           for rid, lv in self._live.items()
                           if rid in self._running and not self._running[rid].done()},
            "outcomeEnabled": bool(self.engine.settings.get("technique.outcome.enabled", True)),
            "outcomeHorizonBars": int(self.engine.settings.get("technique.outcome.horizon_bars", 60)),
            "sessionWindow": session_window(int(time.time() * 1000)),
            "enforceSessionWindows": bool(self.engine.settings.get("technique.enforce_session_windows", True)),
            "structureTfs": list(self.engine.settings.get("technique.structure_tfs", ["1h", "30m"])),
            "triggerTf": str(self.engine.settings.get("technique.trigger_tf", "1m")),
            # every technique's runner — the restart guard (scripts/start.ps1 via
            # /api/health) counts these to protect armed plans across restarts
            "armed": self.armed_plans(),
            "sweepsRunning": [sid for sid, t in self._sweeps.items() if not t.done()],
            "sweepVersion": sweep_version(thresholds=self.thresholds(), structure_tfs=list(self.structure_tfs()),
                                          trigger_tf=self.trigger_tf()),
            "techniqueSource": technique_source_version(),
            "rules": RULES,
        }

    def structure_tfs(self) -> tuple[str, ...]:
        return tuple(str(x) for x in self.engine.settings.get("technique.structure_tfs", ["1h", "30m"]))

    def trigger_tf(self) -> str:
        return str(self.engine.settings.get("technique.trigger_tf", "1m"))

    # ------------------------------------------------------------ queries
    async def runs_today(self) -> int:
        start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.engine.sf() as session:
            n = (await session.execute(select(func.count()).select_from(TechniqueRun)
                                       .where(TechniqueRun.created_at >= start))).scalar()
        return int(n or 0)

    async def list_runs(self, *, limit: int = 50, symbol: str | None = None,
                        verdict: str | None = None, reviewed: bool | None = None,
                        outcome: str | None = None, review_verdict: str | None = None,
                        process_version: str | None = None, trigger: str | None = None,
                        tag: str | None = None, technique: str | None = None) -> list[dict]:
        """Recent runs (newest first) with their outcome + review summaries.
        `reviewed`, `outcome` (e.g. stopped / tp1 / not_filled, matched on the
        analysis plan, or `scored` / `pending` for any) and `review_verdict`
        filter post-hoc so the review loop can ask for "unreviewed losers"."""
        post_filter = reviewed is not None or outcome or review_verdict or process_version
        fetch = min(limit * 6, 1500) if post_filter else limit
        async with self.engine.sf() as session:
            stmt = select(TechniqueRun).order_by(TechniqueRun.created_at.desc()).limit(fetch)
            if technique:
                stmt = stmt.where(TechniqueRun.technique == technique)
            if symbol:
                stmt = stmt.where(TechniqueRun.symbol == symbol.upper())
            if verdict:
                stmt = stmt.where(TechniqueRun.verdict == verdict)
            if trigger:
                stmt = stmt.where(TechniqueRun.trigger == trigger)
            rows = (await session.execute(stmt)).scalars().all()
            ids = [r.id for r in rows]
            outs = (await session.execute(
                select(TechniqueOutcome).where(TechniqueOutcome.run_id.in_(ids)))).scalars().all() if ids else []
            revs = (await session.execute(
                select(TechniqueReview).where(TechniqueReview.run_id.in_(ids))
                .order_by(TechniqueReview.created_at))).scalars().all() if ids else []
        by_out: dict[str, list[dict]] = {}
        for o in outs:
            by_out.setdefault(o.run_id, []).append(outcome_dict(o))
        by_rev: dict[str, list[dict]] = {}
        for rv in revs:
            by_rev.setdefault(rv.run_id, []).append(review_dict(rv))
        out: list[dict] = []
        for r in rows:
            d = run_summary(r)
            d["outcomes"] = [_slim_outcome(o) for o in by_out.get(r.id, [])]
            rl = by_rev.get(r.id, [])
            d["reviewCount"] = len(rl)
            d["lastReview"] = ({"reviewVerdict": rl[-1]["reviewVerdict"],
                                "rootCauseStage": rl[-1]["rootCauseStage"],
                                "createdAt": rl[-1]["createdAt"], "reviewer": rl[-1]["reviewer"]}
                               if rl else None)
            if reviewed is True and not rl:
                continue
            if reviewed is False and rl:
                continue
            if review_verdict and not any(x["reviewVerdict"] == review_verdict for x in rl):
                continue
            if process_version and d.get("processVersion") != process_version:
                continue
            if outcome and not _outcome_matches(d["outcomes"], outcome):
                continue
            out.append(d)
            if len(out) >= limit:
                break
        if tag:
            _r = out
            return [d for d in _r if tag in (d.get("tags") or [])]
        return out

    async def get_run(self, run_id: str) -> dict | None:
        async with self.engine.sf() as session:
            r = await session.get(TechniqueRun, run_id)
            if r is None:
                return None
            setups = (await session.execute(
                select(TechniqueSetup).where(TechniqueSetup.run_id == run_id))).scalars().all()
            outs = (await session.execute(
                select(TechniqueOutcome).where(TechniqueOutcome.run_id == run_id)
                .order_by(TechniqueOutcome.created_at))).scalars().all()
            revs = (await session.execute(
                select(TechniqueReview).where(TechniqueReview.run_id == run_id)
                .order_by(TechniqueReview.created_at))).scalars().all()
            children = (await session.execute(
                select(TechniqueRun.id, TechniqueRun.created_at, TechniqueRun.verdict,
                       TechniqueRun.setup_type, TechniqueRun.confidence, TechniqueRun.status)
                .where(TechniqueRun.parent_run_id == run_id)
                .order_by(TechniqueRun.created_at))).all()
        d = run_dict(r)
        d["setups"] = [setup_dict(s) for s in setups]
        d["outcomes"] = [outcome_dict(o) for o in outs]
        d["reviews"] = [review_dict(x) for x in revs]
        d["replays"] = [{"id": c.id, "createdAt": c.created_at.isoformat() if c.created_at else None,
                         "verdict": c.verdict, "setupType": c.setup_type, "confidence": c.confidence,
                         "status": c.status} for c in children]
        if run_id in self._live:
            d["live"] = self._live[run_id]
        return d

    async def list_setups(self, *, limit: int = 100, valid_only: bool = False) -> list[dict]:
        async with self.engine.sf() as session:
            stmt = select(TechniqueSetup).order_by(TechniqueSetup.created_at.desc()).limit(limit)
            if valid_only:
                stmt = stmt.where(TechniqueSetup.valid.is_(True))
            rows = (await session.execute(stmt)).scalars().all()
        return [setup_dict(s) for s in rows]

    # ------------------------------------------------------------ analyze
    async def analyze(self, symbol: str, *, tags: list[str] | None = None,
                      as_of_ms: int | None = None, primary_tf: str | None = None,
                      trigger: str = "manual", image: bytes | None = None, note: str = "",
                      thread_id: str | None = None, wait: bool = False,
                      parent_run_id: str | None = None, thresholds_override: dict | None = None,
                      bars_override: dict[str, list[Bar]] | None = None,
                      plan: bool | None = None, with_vision: bool | None = None,
                      reference_price: float | None = None) -> dict:
        """Start a run. Returns the run row immediately (status=running) unless
        `wait=True`, in which case the finished run is returned.

        Modes: `full` (live / intraday as-of), `image_only`, and `plan` — chosen
        automatically when the as-of instant is outside the regular session
        (R6.4: nothing to fill, so the output is a plan for the next session),
        or forced with `plan=True/False`. Plan mode is deterministic unless
        `with_vision` (or `technique.plan.with_vision`) is on.

        `parent_run_id` / `thresholds_override` / `bars_override` are the replay
        hooks: re-run an earlier moment with the bars it saw (so Yahoo's history
        limit does not matter) and optionally different thresholds, linked to
        the parent so the two can be diffed."""
        cfg = self.llm_config()
        if not bool(self.engine.settings.get("technique.enabled", True)):
            raise RuntimeError("technique.enabled is off")

        symbol = (symbol or "").upper().strip()
        tf = primary_tf or self.trigger_tf()
        mode = "image_only" if (image is not None and not symbol) else "full"
        if not symbol and image is None:
            raise ValueError("symbol or image required")
        if mode == "full":
            if plan is True or (plan is None and as_of_ms is not None and session_window(as_of_ms) == "extended"):
                mode = "plan"
                tf = primary_tf or self.trigger_tf()
        vision_requested = with_vision
        if with_vision is None:
            with_vision = bool(self.engine.settings.get("technique.plan.with_vision", True))
        # A plan can always be built without the model; if vision was merely the
        # default (not explicitly requested) and there is no key, fall back to the
        # deterministic plan instead of failing.
        if mode == "plan" and with_vision and not cfg.available and vision_requested is None:
            with_vision = False
        needs_llm = not (mode == "plan" and not with_vision)
        if needs_llm and not cfg.available:
            raise RuntimeError("ZARGAR_ANTHROPIC_API_KEY is not configured")
        cap = int(self.engine.settings.get("technique.max_runs_per_day", 40))
        if needs_llm and trigger != "chat" and await self.runs_today() >= cap:
            raise RuntimeError(f"daily run cap reached ({cap}); raise technique.max_runs_per_day")

        thresholds = self.thresholds()
        if thresholds_override:
            fields = {f.name for f in dataclasses.fields(Thresholds)}
            bad = [k for k in thresholds_override if k not in fields]
            if bad:
                raise ValueError(f"unknown threshold(s): {bad}; valid: {sorted(fields)}")
            thresholds = dataclasses.replace(thresholds, **thresholds_override)
        max_passes = int(self.engine.settings.get("llm.max_passes", 6))
        if mode == "plan":
            tfs = AnalysisRequest(symbol=symbol, primary_tf=tf, context_tfs=self.structure_tfs()).timeframes
        else:
            tfs = AnalysisRequest(symbol=symbol or "IMAGE", primary_tf=tf).timeframes if mode == "full" else []
        config = provenance_snapshot(
            thresholds=thresholds, settings_all=self.engine.settings.all(), model=cfg.model,
            effort=cfg.effort, thinking_display=cfg.thinking_display, max_passes=max_passes,
            timeframes=tfs, parent_run_id=parent_run_id,
            overrides={"thresholds": dict(thresholds_override or {}),
                       "barsFromSnapshot": bars_override is not None})
        if mode == "plan":
            config["planMode"] = {"structureTfs": list(self.structure_tfs()), "triggerTf": tf,
                                  "withVision": bool(with_vision),
                                  "planFor": next_session_date(as_of_ms) if as_of_ms else None,
                                  "referencePrice": reference_price}
        # options-flow context rides along as an informational note (never a rule —
        # UI-PLAN F1); recorded in provenance so reviews can judge whether it helped
        flow_line = None
        flow_svc = getattr(self.engine, "flow_service", None)
        if symbol and flow_svc is not None:
            with contextlib.suppress(Exception):
                flow_line = await flow_svc.context_for(symbol)
        if flow_line:
            config["flowContext"] = flow_line
            note = (note + "\n\n" if note else "") + f"OPTIONS FLOW (context, not a rule): {flow_line}"

        if thread_id is None:
            title = (f"{symbol} plan for {next_session_date(as_of_ms) if as_of_ms else 'next session'}"
                     if mode == "plan" else f"{symbol or 'chart'} analysis · {tf}") \
                + (" · image" if image else "") + (" · replay" if parent_run_id else "")
            thread = await self.chat.create_thread(title=title, kind="run", symbol=symbol or None)
            thread_id = thread["id"]

        run = TechniqueRun(id=new_id(), tags=[str(t) for t in (tags or [])],
                           thread_id=thread_id, symbol=symbol or "IMAGE", as_of=as_of_ms,
                           primary_tf=tf, mode=mode, trigger=trigger, status="running",
                           llm={"model": cfg.model, "effort": cfg.effort,
                                "thinkingDisplay": cfg.thinking_display},
                           config=config, parent_run_id=parent_run_id)
        async with self.engine.sf() as session:
            session.add(run)
            # link the thread to its run
            from ..models import ChatThread
            t = await session.get(ChatThread, thread_id)
            if t is not None and not t.run_id:
                t.run_id = run.id
            await session.commit()
        rd = run_dict(run)
        await self.engine.journal.append(ev.TECHNIQUE_RUN_STARTED, {
            "runId": run.id, "symbol": symbol, "tf": tf, "asOf": as_of_ms, "mode": mode,
            "trigger": trigger, "threadId": thread_id, "llm": run.llm,
            "processVersion": config.get("processVersion"), "parentRunId": parent_run_id,
            "overrides": config.get("overrides")},
            aggregate_type="technique_run", aggregate_id=run.id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "run", "run": run_summary(run)})
        if flow_line:
            # journal the delivery against this run (the Symbol Story's "where it went")
            with contextlib.suppress(Exception):
                await flow_svc.context_for(symbol, consumer="em", ref_id=run.id)

        task = asyncio.create_task(self._execute(run.id, thread_id, symbol, tf, as_of_ms, mode,
                                                 image, note, trigger, thresholds=thresholds,
                                                 bars_override=bars_override, with_vision=bool(with_vision),
                                                 reference_price=reference_price),
                                   name=f"technique-{run.id[:8]}")
        self._running[run.id] = task
        if wait:
            await task
            return await self.get_run(run.id) or rd
        return rd

    async def _execute(self, run_id: str, thread_id: str, symbol: str, tf: str, as_of_ms: int | None,
                       mode: str, image: bytes | None, note: str, trigger: str, *,
                       thresholds: Thresholds | None = None,
                       bars_override: dict[str, list[Bar]] | None = None,
                       with_vision: bool = False, reference_price: float | None = None) -> None:
      # re-read live (EM team #4): a changed cap applies to the NEXT run without a
      # restart (runs already inside the old semaphore finish under it)
      want = max(1, int(self.engine.settings.get("technique.max_concurrent_runs", 8)))
      if self._run_sem is None or getattr(self, "_run_sem_size", 0) != want:
          self._run_sem = asyncio.Semaphore(want)
          self._run_sem_size = want
      async with self._run_sem:
        cfg = self.llm_config()
        client = self._get_client() if cfg.available else None
        t = thresholds or self.thresholds()
        chat = self.chat
        t0 = time.time()

        live = self._live.setdefault(run_id, {"passes": [], "grounding": None, "facts": None,
                                              "symbol": symbol})

        async def on_event(e: dict) -> None:
            t_ = e.get("type")
            if t_ == "pass_start":
                live["passes"] = [p for p in live["passes"] if p["name"] != e["pass"]] + [
                    {"name": e["pass"], "status": "running", "call": e.get("call"),
                     "thinking": "", "text": ""}]
            elif t_ == "pass_done":
                for p in live["passes"]:
                    if p["name"] == e["pass"]:
                        p.update({"status": "done", "usage": e.get("usage"), "seconds": e.get("seconds")})
            elif t_ == "grounding":
                live["grounding"] = {"passed": e["passed"], "checks": e["checks"], "attempt": e["attempt"]}
            elif t_ == "facts":
                live["facts"] = {"keyLevels": e.get("keyLevels"), "volume": e.get("volume"),
                                 "trend": e.get("trend")}
            elif t_ == "trace":
                live.setdefault("trace", []).append({k: v for k, v in e.items() if k != "type"})
            chat.publish(thread_id, e, run_id=run_id)

        facts: dict = {}
        images_meta: dict = {}
        result = None
        trace: list[dict] = []
        bars_asset: str | None = None
        plan_d: dict | None = None
        try:
            max_passes = int(self.engine.settings.get("llm.max_passes", 6))
            vp = VisionPipeline(client, cfg, thresholds=t, max_passes=max_passes, on_event=on_event,
                                trace=trace, t0=t0)
            await vp.note("run", "start", f"run started ({trigger}) for {symbol or 'image'} on {tf}"
                          + (f" as of {dt.datetime.fromtimestamp(as_of_ms / 1000, dt.timezone.utc).isoformat()}"
                             if as_of_ms else " (live)"),
                          mode=mode, trigger=trigger, model=cfg.model, effort=cfg.effort,
                          maxPasses=max_passes, userImage=image is not None, userNote=bool(note))
            if mode == "image_only":
                aid = await chat.store_asset(image, None, thread_id=thread_id, meta={"kind": "user_image"})
                images_meta["user"] = aid
                await vp.note("data", "image_only", "no symbol given: analysing the user's screenshot alone, "
                              "no bars fetched and nothing to ground against", assetId=aid)
                result = await vp.run_image_only(image, note=note, symbol_hint=symbol)
            else:
                if mode == "plan":
                    req = AnalysisRequest(symbol=symbol, as_of_ms=as_of_ms, primary_tf=tf,
                                          context_tfs=self.structure_tfs(), thresholds=t)
                    await vp.note("plan", "mode", "as-of instant is outside the regular session: building a "
                                  "session plan for the next session instead of a live setup (R6.4)",
                                  planFor=next_session_date(as_of_ms) if as_of_ms else None,
                                  structureTfs=list(self.structure_tfs()), triggerTf=tf, withVision=with_vision)
                else:
                    req = AnalysisRequest(symbol=symbol, as_of_ms=as_of_ms, primary_tf=tf, thresholds=t)
                td = time.time()
                if bars_override is not None:
                    bars = {k: list(v) for k, v in bars_override.items() if v}
                    notes = ["bars loaded from the parent run's snapshot (replay)"]
                    await vp.note("data", "snapshot", "bars loaded from the parent run's snapshot instead "
                                  "of Yahoo, so the replay sees exactly what the original saw",
                                  perTf={k: len(v) for k, v in bars.items()})
                else:
                    bars, notes = await gather_bars(req)
                    await vp.note("data", "fetch",
                                  f"fetched {sum(len(v) for v in bars.values())} bars across "
                                  f"{len(bars)} timeframe(s) from Yahoo in {time.time() - td:.1f}s"
                                  + ("; notes: " + "; ".join(notes) if notes else ""),
                                  perTf={k: {"bars": len(v), "firstTs": v[0].ts, "lastTs": v[-1].ts}
                                         for k, v in bars.items()},
                                  requested=req.timeframes, notes=list(notes), asOf=as_of_ms,
                                  seconds=round(time.time() - td, 2))
                facts = compute_facts(req, bars, notes)
                if not bars:
                    await vp.note("data", "abort", "no bars for any timeframe; run cannot proceed",
                                  notes=list(notes))
                    raise RuntimeError("no bars available for " + symbol + " — " + "; ".join(notes))
                cands = facts.get("candidateSetups") or []
                ptf = facts.get("primaryTf") or tf
                await vp.note("data", "facts",
                              f"detectors on {ptf}: {len(facts.get('keyLevels') or [])} key level(s), "
                              f"trend {(facts.get('trend') or {}).get(ptf, {}).get('direction', '?') if isinstance((facts.get('trend') or {}).get(ptf), dict) else (facts.get('trend') or {}).get(ptf, '?')}, "
                              f"{len(cands)} deterministic candidate setup(s)"
                              + (f"; first candidate {cands[0].get('setupType')} entry "
                                 f"{(cands[0].get('entry') or {}).get('price')} R:R {cands[0].get('riskReward')} "
                                 f"valid={cands[0].get('valid')}" if cands else ""),
                              lastClose=facts.get("lastClose"), primaryTf=ptf,
                              keyLevels=[{"price": lv.get("price"), "kind": lv.get("kind"),
                                          "touches": lv.get("touches"), "position": lv.get("position")}
                                         for lv in (facts.get("keyLevels") or [])[:10]],
                              candidateSetups=[{"setupType": c.get("setupType"), "valid": c.get("valid"),
                                                "entry": (c.get("entry") or {}).get("price"),
                                                "stop": (c.get("stop") or {}).get("price"),
                                                "riskReward": c.get("riskReward"),
                                                "noTradeReasons": list(c.get("noTradeReasons") or [])}
                                               for c in cands],
                              volume=(facts.get("volume") or {}).get(ptf),
                              recentBreak=bool(facts.get("recentBreak")),
                              wedge=bool((facts.get("wedge") or {}).get(ptf)))
                # Full bar windows, saved so the run can be replayed / re-scored
                # after Yahoo's history limit has passed.
                snap = {"symbol": symbol, "asOf": as_of_ms, "primaryTf": tf,
                        "bars": {k: bars_to_rows(v) for k, v in bars.items()}}
                blob = gzip.compress(json.dumps(snap).encode("utf-8"))
                bars_asset = await chat.store_asset(blob, "application/gzip", thread_id=thread_id,
                                                    meta={"kind": "bars_snapshot", "runId": run_id,
                                                          "symbol": symbol, "tf": tf})
                await vp.note("data", "snapshot_saved",
                              "full bar windows saved as an asset for replay / outcome scoring",
                              assetId=bars_asset, bytes=len(blob),
                              perTf={k: len(v) for k, v in bars.items()})
                imgs: dict[str, bytes] = {}
                for tfx in req.timeframes:
                    if tfx in bars:
                        png = render_chart(bars[tfx][-WINDOW_FOR_TF.get(tfx, 150):],
                                           title=f"{symbol} {tfx}", tf=tfx)
                        imgs[tfx] = png
                        images_meta[tfx] = await chat.store_asset(png, "image/png", thread_id=thread_id,
                                                                  meta={"kind": "pass_chart", "tf": tfx})
                if image is not None:
                    images_meta["user"] = await chat.store_asset(image, None, thread_id=thread_id,
                                                                 meta={"kind": "user_image"})
                await vp.note("data", "charts",
                              f"rendered {len(imgs)} chart(s) for the model: "
                              + ", ".join(f"{k} ({min(len(bars[k]), WINDOW_FOR_TF.get(k, 150))} bars)"
                                          for k in imgs),
                              images={k: images_meta[k] for k in imgs}, userImage=images_meta.get("user"))
                await on_event({"type": "facts", "keyLevels": facts.get("keyLevels", [])[:8],
                                "volume": (facts.get("volume") or {}).get(facts.get("primaryTf")),
                                "trend": facts.get("trend")})
                if mode == "plan":
                    plan_obj = build_session_plan(facts, thresholds=t, structure_tfs=list(self.structure_tfs()),
                                                  trigger_tf=tf, reference_price=reference_price)
                    plan_d = plan_obj.to_dict()
                    await vp.note("plan", "levels", f"{len(plan_d['levels'])} level(s) kept for the map "
                                  f"({sum(1 for l in plan_d['levels'] if l.get('priorDayExtreme'))} prior-day extremes)",
                                  levels=[{k: l.get(k) for k in ("price", "effectiveKind", "touches", "sources",
                                                                 "distancePct", "priorDayExtreme")} for l in plan_d["levels"][:12]])
                    for tg in plan_d["triggers"]:
                        await vp.note("plan", f"trigger_{tg['id']}",
                                      f"{tg['kind']} at {tg['levelPrice']:.2f}: "
                                      + ("VALID — " if tg["valid"] else "not tradeable — ")
                                      + (", ".join(tg["noTradeReasons"]) if tg["noTradeReasons"] else
                                         f"R:R {tg['riskReward']:.2f}, {len(tg['conditions'])} conditions"),
                                      trigger={k: tg.get(k) for k in ("id", "kind", "entry", "stop", "riskReward",
                                                                        "valid", "confluences", "conditions", "voidIf")})
                    if not plan_d["triggers"]:
                        await vp.note("plan", "no_triggers", "no level within reach: a plan with nothing to do")
                    await vp.note("plan", "invalidations", "gap policy and expiry recorded (our extrapolation, Q11-Q13)",
                                  gapPolicy=plan_d["gapPolicy"])
                    if with_vision:
                        # The analyst judges THE PLAN, with everything the grader knew —
                        # otherwise it re-derives from the closing print and answers a
                        # different question (BKNG 2026-08-24: argued about a 213.26
                        # candidate while the graded trigger was the 206.34 zone floor).
                        assess_lines = []
                        for tg in plan_d["triggers"]:
                            a = tg.get("assessment") or {}
                            assess_lines.append(
                                f"- {tg['id']} {tg['kind']} @ {tg['levelPrice']:.2f} "
                                + ("VALID" + (f", grade {a.get('grade')} ({a.get('score')}/100)" if a.get("grade") else "")
                                   if tg["valid"] else "not tradeable")
                                + (": strengths: " + "; ".join(a.get("strengths") or []) if a.get("strengths") else "")
                                + (" | cautions: " + "; ".join(a.get("cautions") or []) if a.get("cautions") else ""))
                        preamble = (
                            f"PLAN MODE: the market is closed; this is a plan for {plan_d['planFor']}.\n\n"
                            "THE DETERMINISTIC PLAN (built by the rulebook code from the same FACTS — "
                            "judge THIS plan; do not re-derive your own):\n"
                            f"{plan_summary_text(plan_d)}\n\n"
                            "Trigger assessments (deterministic; A strong / B decent / C weak):\n"
                            + ("\n".join(assess_lines) or "- (no triggers)") + "\n\n"
                            "How those numbers were made: stops sit below the invalidating structure "
                            "(the merged zone's floor or the recent low under the level, T4.3d), capped at "
                            f"{t.max_stop_pct:.1%} of entry (wider = no-trade); levels within {t.zone_merge_pct:.1%} "
                            "merge into ONE zone (entry at the zone top); a pct-ladder target means no resistance "
                            "overhead (T4.4) and caps the grade at B.\n\n"
                            "YOUR JOB: judge each trigger BY ID against the charts. verdict='setup' means at least "
                            "one VALID trigger is worth watching next session — copy that trigger's entry/stop/targets "
                            "as your plan and name its id in the rationale (plus what you'd change, if anything). "
                            "verdict='no_setup' means you reject EVERY valid trigger — give one reason per trigger id "
                            "in no_trade_reasons, grounded in the charts/FACTS. The as-of instant being outside the "
                            "session is NOT a reason: every trigger is already conditional on the next session's prime "
                            "windows, so do not cite R6.3/R6.4 against them. Do not emit a fill; set plan_mode=true.\n\n")
                        result = await vp.run(facts, imgs, user_image=image, user_note=preamble + (note or ""))
                        # Plan-mode facts are deterministic; never trust the model to set them.
                        if result.analysis is not None:
                            result.analysis.plan_mode = True
                            result.analysis.session_window = facts.get("sessionWindow") or "extended"
                    else:
                        result = PipelineResult(analysis=None, grounding={"passed": None, "checks": [],
                                                                           "note": "plan mode: deterministic, no model passes"},
                                                mode="plan", trace=trace)
                        await vp.note("loop", "skipped", "deterministic plan; vision passes not requested")
                else:
                    result = await vp.run(facts, imgs, user_image=image, user_note=note)
                    # R6 — outside the prime windows a setup is watch-only (when enforced).
                    sw = facts.get("sessionWindow")
                    a0 = result.analysis
                    if (a0 is not None and a0.verdict == "setup" and sw not in PRIME_WINDOWS
                            and bool(self.engine.settings.get("technique.enforce_session_windows", True))):
                        rid = WINDOW_RULE.get(sw, "R6.3")
                        a0.no_trade_reasons = list(a0.no_trade_reasons) + [
                            f"{rid} outside the prime windows ({sw}) — watch only, do not enter"]
                        await vp.note("window", "watch_only",
                                      f"setup claimed at {sw}; R6 says trade only 09:30-10:30 / 14:45-16:00 ET — "
                                      "kept as watch-only, not valid", sessionWindow=sw, rule=rid)
                    elif a0 is not None:
                        await vp.note("window", "ok" if sw in PRIME_WINDOWS else "note",
                                      f"as-of instant is in {sw}", sessionWindow=sw)

                # annotated chart with the final plan (or the levels, if no setup)
                a = result.analysis
                ptf = facts.get("primaryTf") or tf
                setup_overlay = rejected_overlay = None
                caption = ""
                if plan_d is not None:
                    # plan mode: the map (levels near price) + the best valid trigger drawn as
                    # the conditional plan, the best invalid one dashed
                    last = float(facts.get("lastClose") or 0) or 1.0
                    lv_overlay = [{"price": l["price"], "kind": l["effectiveKind"], "touches": l.get("touches") or 1,
                                   "strong": (l.get("touches") or 0) >= 3 or bool(l.get("priorDayExtreme"))}
                                  for l in plan_d["levels"] if abs(l["price"] - last) / last <= 0.05][:8]
                    valid = [x for x in plan_d["triggers"] if x["valid"]]
                    best = max(valid, key=lambda x: x["confidence"]) if valid else None
                    if best:
                        setup_overlay = {"entry": {"price": best["entry"]["price"]}, "stop": {"price": best["stop"]["price"]},
                                         "targets": [{"price": t["price"]} for t in best["targets"]]}
                    inval = [x for x in plan_d["triggers"] if not x["valid"]]
                    if inval:
                        w = inval[0]
                        rejected_overlay = {"entry": {"price": w["entry"]["price"]}, "stop": {"price": w["stop"]["price"]},
                                            "targets": [{"price": t["price"]} for t in w["targets"][:1]],
                                            "riskReward": w["riskReward"], "setupType": w["setupType"]}
                    caption = (f"PLAN for {plan_d['planFor']} · {len(valid)} tradeable trigger(s)"
                               + (f"\n{best['id']} {best['kind']}: IF price reaches {best['entry']['price']:.2f} in a prime window "
                                  f"THEN long, stop {best['stop']['price']:.2f}, R:R {best['riskReward']:.2f}" if best else
                                  "\nnothing within reach — watch only")
                               + (f"\n{inval[0]['id']} rejected: {inval[0]['noTradeReasons'][0][:70]}" if inval and inval[0].get("noTradeReasons") else ""))
                else:
                    if a and a.verdict == "setup" and a.entry and a.stop:
                        setup_overlay = {"entry": {"price": a.entry.price}, "stop": {"price": a.stop.price},
                                         "targets": [{"price": x.price} for x in a.targets]}
                    elif a:
                        # No setup: draw the candidate that was considered and rejected,
                        # so the chart shows *why* rather than only asserting a verdict.
                        rejected_overlay = _rejected_overlay(facts, a)
                    lv_overlay = [{"price": lv.price, "kind": lv.kind, "touches": lv.touches,
                                   "strong": lv.touches >= 3} for lv in (a.levels if a else [])][:8]
                    caption = _chart_caption(a, rejected_overlay)
                if ptf in bars:
                    png = render_chart(bars[ptf][-WINDOW_FOR_TF.get(ptf, 150):],
                                       title=f"{symbol} {ptf}" + (f" — plan for {plan_d['planFor']}" if plan_d else ""),
                                       tf=ptf, levels=lv_overlay, setup=setup_overlay,
                                       rejected=rejected_overlay, caption=caption,
                                       wedge=(facts.get("wedge") or {}).get(ptf))
                    images_meta["annotated"] = await chat.store_asset(
                        png, "image/png", thread_id=thread_id, meta={"kind": "annotated", "tf": ptf})

            # ---- persist transcript into the thread ------------------------------
            for m in transcript_messages(result.passes):
                await chat.append_message(thread_id, m["role"], m["blocks"], m["meta"],
                                          publish=False, run_id=run_id)

            a = result.analysis
            contract = a.to_contract() if a else None
            options = None
            if mode == "plan":
                await vp.note("options", "skipped", "plan mode: the contract is picked when a trigger fires")
            elif a and a.verdict == "setup" and bool(self.engine.settings.get("technique.options.enabled", True)):
                await vp.note("options", "pick", "setup verdict: picking the contract the method would trade (T5)",
                              provider=getattr(self.options_provider(), "name", "?"),
                              direction=a.direction or "long")
                options = await self.option_pick(symbol, a.direction or "long",
                                                 spot=float(facts.get("lastClose") or 0) or None)
                if options and options.get("available") and options.get("symbol"):
                    await vp.note("options", "result",
                                  f"picked {options['symbol']} {options.get('optionType')} {options.get('strike')} "
                                  f"exp {options.get('expiry')}"
                                  + (f"; warnings: {'; '.join(options.get('warnings') or [])}"
                                     if options.get("warnings") else ""),
                                  contract=options.get("symbol"), warnings=list(options.get("warnings") or []))
                else:
                    await vp.note("options", "result", f"no contract: {(options or {}).get('error', 'unknown')}",
                                  provider=(options or {}).get("provider"))
            elif a and a.verdict == "setup":
                await vp.note("options", "skipped", "technique.options.enabled is off")
            else:
                await vp.note("options", "skipped", "no setup, no contract to pick")

            # ---- setups (before the run row so their trace notes land in it) --------
            if mode == "plan":
                await vp.note("setup", "skipped", "plan mode: triggers are scored (walk-forward) or armed (live); "
                              "no setup row until one fires")
            elif a is not None:
                await self._persist_setup(run_id, symbol or a.symbol, a, contract, options,
                                          grounded=bool(result.grounding.get("passed")), vp=vp)

            usage = dict(result.total_usage)
            await vp.note("run", "done", f"run finished in {time.time() - t0:.1f}s, "
                          f"{usage.get('input', 0)} in / {usage.get('output', 0)} out tokens",
                          usage=usage, seconds=round(time.time() - t0, 1))
            res_d = result.to_dict()
            res_d["options"] = options
            res_d["seconds"] = round(time.time() - t0, 1)
            res_d["trace"] = list(trace)
            res_d["sessionWindow"] = facts.get("sessionWindow")
            if plan_d is not None:
                res_d["plan"] = plan_d
            top = None
            if plan_d is not None:
                valid = [x for x in plan_d["triggers"] if x["valid"]]
                top = max(valid, key=lambda x: x["confidence"]) if valid else None
            async with self.engine.sf() as session:
                r = await session.get(TechniqueRun, run_id)
                r.status = "done"
                if mode == "plan":
                    r.verdict = "plan"
                    r.setup_type = top["setupType"] if top else None
                    r.confidence = top["confidence"] if top else (a.confidence if a else None)
                else:
                    r.verdict = a.verdict if a else None
                    r.setup_type = a.setup_type if a else None
                    r.confidence = a.confidence if a else None
                r.grounded = bool(result.grounding.get("passed")) if result.mode == "full" else None
                r.facts = _slim_facts(facts)
                r.result = res_d
                r.images = images_meta
                r.usage = usage
                r.error = result.error
                if bars_asset:
                    cfg_d = dict(r.config or {})
                    cfg_d["barsAssetId"] = bars_asset
                    r.config = cfg_d
                r.finished_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
                rd = run_dict(r)

            await self.engine.journal.append(ev.TECHNIQUE_RUN_COMPLETED, {
                "runId": run_id, "symbol": symbol, "verdict": rd["verdict"], "setupType": rd["setupType"],
                "confidence": rd["confidence"], "grounded": rd["grounded"], "usage": usage,
                "seconds": res_d["seconds"], "rulesFired": (contract or {}).get("rulesFired", []),
                "noTradeReasons": (contract or {}).get("noTradeReasons", []),
                "traceSteps": len(trace), "processVersion": (rd.get("config") or {}).get("processVersion"),
                "parentRunId": rd.get("parentRunId")},
                aggregate_type="technique_run", aggregate_id=run_id)
            if result.mode == "full" and not result.grounding.get("passed"):
                await self.engine.journal.append(ev.TECHNIQUE_GROUNDING_FAILED, {
                    "runId": run_id, "checks": [c for c in result.grounding.get("checks", [])
                                               if not c.get("passed")]},
                    aggregate_type="technique_run", aggregate_id=run_id)
            summary_text = (plan_summary_text(plan_d) if plan_d is not None
                            else _summary_text(contract, result.grounding, options))
            await chat.append_message(thread_id, "assistant", [{"type": "text", "text": summary_text}],
                                      {"kind": "run_summary", "runId": run_id,
                                       "annotatedAssetId": images_meta.get("annotated")},
                                      run_id=run_id)
            chat.publish(thread_id, {"type": "run_done", "run": run_summary_from_dict(rd)}, run_id=run_id)
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "run_done", "run": run_summary_from_dict(rd)})

            # A backdated run already has its future: score it right away.
            if (mode in ("full", "plan") and as_of_ms is not None
                    and bool(self.engine.settings.get("technique.outcome.enabled", True))):
                with contextlib.suppress(Exception):
                    await self.score_run(run_id)
        except asyncio.CancelledError:
            await self._fail(run_id, thread_id, "cancelled", trace=trace)
            raise
        except Exception as exc:
            log.exception("technique run failed")
            await self._fail(run_id, thread_id, f"{type(exc).__name__}: {exc}", trace=trace)
        finally:
            self._running.pop(run_id, None)
            self._live.pop(run_id, None)

    async def _fail(self, run_id: str, thread_id: str, error: str, *, trace: list[dict] | None = None) -> None:
        async with self.engine.sf() as session:
            r = await session.get(TechniqueRun, run_id)
            if r is not None:
                r.status = "failed"
                r.error = error
                if trace is not None:
                    res = dict(r.result or {})
                    res["trace"] = list(trace) + [{"seq": len(trace) + 1, "stage": "run", "step": "failed",
                                                   "reason": error, "t": None, "call": None}]
                    r.result = res
                r.finished_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
                rd = run_dict(r)
            else:
                rd = {"id": run_id, "status": "failed", "error": error}
        await self.engine.journal.append(ev.TECHNIQUE_RUN_FAILED,
                                         {"runId": run_id, "symbol": rd.get("symbol"), "error": error},
                                         aggregate_type="technique_run", aggregate_id=run_id)
        if self.chat:
            await self.chat.append_message(thread_id, "assistant",
                                           [{"type": "text", "text": f"Run failed: {error}"}],
                                           {"error": True, "runId": run_id}, run_id=run_id)
            self.chat.publish(thread_id, {"type": "run_done", "run": rd, "error": error}, run_id=run_id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "run_done", "run": rd, "error": error})

    async def cancel_run(self, run_id: str) -> bool:
        t = self._running.get(run_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    async def _persist_setup(self, run_id: str, symbol: str, a, contract: dict, options: dict | None,
                             *, grounded: bool, vp=None) -> None:
        e, s = a.entry, a.stop
        blocking = [r for r in a.no_trade_reasons if not r.startswith("CRITIC-WARN")]
        valid = a.verdict == "setup" and e is not None and s is not None and grounded and not blocking
        if vp is not None:
            why = ("valid: setup verdict, entry+stop present, grounded, no blocking reasons" if valid else
                   "not valid: " + "; ".join(filter(None, [
                       "verdict is no_setup" if a.verdict != "setup" else "",
                       "missing entry/stop" if (e is None or s is None) else "",
                       "not grounded" if not grounded else "",
                       f"{len(blocking)} blocking no-trade reason(s)" if blocking else ""])))
            await vp.note("setup", "persist", f"setup row written; {why}", valid=valid,
                          setupType=a.setup_type, entry=e.price if e else None, stop=s.price if s else None,
                          grounded=grounded, blockingReasons=blocking)
        row = TechniqueSetup(
            id=new_id(), run_id=run_id, symbol=symbol.upper(), setup_type=a.setup_type or "none",
            direction=a.direction or "none", entry=e.price if e else 0.0, stop=s.price if s else 0.0,
            targets=[{"price": t.price, "trimPct": t.trim_pct, "basis": t.basis} for t in a.targets],
            risk_reward=float(a.risk_reward or 0.0), confidence=float(a.confidence or 0.0),
            valid=bool(valid), rules=list(a.rules_fired), no_trade_reasons=list(a.no_trade_reasons),
            options=options, status="open")
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        sd = setup_dict(row)
        await self.engine.journal.append(ev.TECHNIQUE_SETUP_EMITTED, sd, aggregate_type="technique_setup",
                                         aggregate_id=row.id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "setup", "setup": sd})
        emit = bool(self.engine.settings.get("technique.emit_proposals", False))
        if valid and emit:
            try:
                pid = await self._emit_proposal(row, a)
                if vp is not None:
                    await vp.note("proposal", "emit" if pid else "skipped",
                                  ("practice proposal created; it still needs approval and passes RiskGate"
                                   if pid else "no sim portfolio available for a practice proposal"),
                                  proposalId=pid, setupId=row.id)
            except Exception as exc:
                log.exception("proposal emission failed")
                if vp is not None:
                    await vp.note("proposal", "error", f"proposal emission failed: {exc}", setupId=row.id)
        elif vp is not None:
            await vp.note("proposal", "skipped",
                          "setup not valid" if not valid else "technique.emit_proposals is off",
                          valid=valid, emitProposals=emit)

    async def _emit_proposal(self, setup: TechniqueSetup, a, *, portfolio_id: str | None = None,
                             risk_pct: float | None = None, max_qty: float | None = None,
                             fixed_qty: float | None = None, contract: dict | None = None,
                             contracts: int | None = None, managed: bool = False) -> str | None:
        """A proposal the user approves in the Signals page; approval routes
        through OrderManager → RiskGate like every other order. Returns the
        proposal id (None when no portfolio could take it). Armed plans pass the
        account / sizing they were configured with."""
        eng = self.engine
        pid = portfolio_id or str(eng.settings.get("trading.default_portfolio", ""))
        if not pid or eng.positions.portfolio(pid) is None:
            sims = [p for p in eng.positions.portfolios() if p["kind"] == "sim"]
            if not sims:
                return None
            pid = sims[0]["id"]
        equity = await eng.positions.equity(pid)
        risk_pct = float(risk_pct if risk_pct is not None else eng.settings.get("technique.default_risk_pct", 1.0))
        risk_pct = min(risk_pct, float(eng.settings.get("technique.max_risk_pct", 5.0)))
        per_share = max(setup.entry - setup.stop, 0.01)
        qty = max(1, math.floor(equity * risk_pct / 100 / per_share))
        if fixed_qty:
            qty = max(1, int(fixed_qty))
        if max_qty:
            qty = max(1, min(qty, int(max_qty)))
        if contract and contract.get("symbol"):
            # the book's expression: the just-OTM contract, bought at the ask (T5)
            prem = float(contract.get("ask") or contract.get("mid") or 0)
            n = int(contracts or 1)
            ttl = int(eng.settings.get("signals.default_ttl_minutes", 30))
            row = Proposal(
                id=new_id(), signal_id=None, portfolio_id=pid, symbol=contract["symbol"], sec_type="OPT", side="BUY",
                qty=float(n), order_type="LMT", limit_price=round(prem, 2) if prem > 0 else None, bracket=None,
                rationale=(a.rationale or "")[:500],
                context={"sourceName": "technique", "confidence": a.confidence,
                         "technique": {"setupId": setup.id, "runId": setup.run_id, "setupType": setup.setup_type,
                                       "rules": setup.rules, "managed": managed,
                                       "underlying": {"entry": setup.entry, "stop": setup.stop,
                                                      "targets": setup.targets}},
                         "contract": contract, "sizing": {"contracts": n, "premium": prem, "riskPct": risk_pct,
                                                          "notional": round(prem * 100 * n, 2)}},
                expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=ttl))
            async with eng.sf() as session:
                session.add(row)
                s = await session.get(TechniqueSetup, setup.id)
                if s is not None:
                    s.proposal_id = row.id
                    s.status = "proposed"
                await session.commit()
            from ..approvals.proposals import proposal_dict
            pd = proposal_dict(row)
            await eng.journal.append(ev.PROPOSAL_CREATED, pd, aggregate_type="proposal",
                                     aggregate_id=row.id, portfolio_id=pid)
            eng.bus.publish(topics.PROPOSALS, pd)
            return row.id
        ttl = int(eng.settings.get("signals.default_ttl_minutes", 30))
        # A *managed* proposal (from an armed plan) carries no broker bracket — the
        # armer manages the stop/ladder/flatten after approval (and SnapTrade rejects
        # brackets). A standalone technique proposal keeps its bracket.
        bracket = None if managed else {"take_profit": (setup.targets[0]["price"] if setup.targets else None),
                                        "stop_loss": setup.stop, "take_profit_pct": None, "stop_loss_pct": None}
        row = Proposal(
            id=new_id(), signal_id=None, portfolio_id=pid, symbol=setup.symbol, side="BUY",
            qty=float(qty), order_type="LMT", limit_price=round(setup.entry, 2),
            bracket=bracket,
            rationale=a.rationale[:500],
            context={"sourceName": "technique", "confidence": a.confidence,
                     "technique": {"setupId": setup.id, "runId": setup.run_id,
                                   "setupType": setup.setup_type, "rules": setup.rules,
                                   "underlying": {"entry": setup.entry, "stop": setup.stop, "targets": setup.targets},
                                   "managed": managed},
                     "sizing": {"equity": round(equity, 2), "riskPct": risk_pct, "qty": qty}},
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=ttl))
        async with eng.sf() as session:
            session.add(row)
            s = await session.get(TechniqueSetup, setup.id)
            if s is not None:
                s.proposal_id = row.id
                s.status = "proposed"
            await session.commit()
        from ..approvals.proposals import proposal_dict
        pd = proposal_dict(row)
        await eng.journal.append(ev.PROPOSAL_CREATED, pd, aggregate_type="proposal",
                                 aggregate_id=row.id, portfolio_id=pid)
        eng.bus.publish(topics.PROPOSALS, pd)
        return row.id

    # ------------------------------------------------------------ outcomes
    async def score_run(self, run_id: str, *, horizon_bars: int | None = None,
                        force: bool = False) -> list[dict]:
        """Score what price did after the run (the analysis plan and, when it
        declined, the deterministic candidate it rejected). Idempotent: rows are
        upserted per (run, plan_source); `partial` rows are re-scored as more
        bars arrive. Returns the outcome dicts."""
        async with self.engine.sf() as session:
            r = await session.get(TechniqueRun, run_id)
            if r is None:
                raise KeyError(f"run {run_id} not found")
            existing = {o.plan_source: o for o in (await session.execute(
                select(TechniqueOutcome).where(TechniqueOutcome.run_id == run_id))).scalars().all()}
            setups = (await session.execute(
                select(TechniqueSetup).where(TechniqueSetup.run_id == run_id))).scalars().all()
        if r.status != "done":
            return [outcome_dict(o) for o in existing.values()]
        if not force and existing and all(o.status in ("scored", "unscorable") for o in existing.values()):
            return [outcome_dict(o) for o in existing.values()]

        horizon = int(horizon_bars or self.engine.settings.get("technique.outcome.horizon_bars", 60))
        entry_window = int(self.engine.settings.get("technique.outcome.entry_window_bars", 12))
        res = r.result or {}
        facts = r.facts or {}
        contract = res.get("analysis")
        tf = r.primary_tf
        as_of = r.as_of or int(r.created_at.timestamp() * 1000)
        setup_id = setups[0].id if setups else None
        symbol = r.symbol
        if r.mode == "plan":
            return await self._score_plan_run(r, existing)

        plans: list[tuple[str, dict | None]] = []
        pa = plan_from_contract(contract)
        if pa:
            plans.append(("analysis", pa))
        pc = plan_from_candidate((facts.get("candidateSetups") or [None])[0])
        if pc and not same_plan(pc, pa):
            plans.append(("candidate", pc))
        if not plans:
            plans.append(("market", None))

        async def upsert(source: str, **fields) -> TechniqueOutcome:
            async with self.engine.sf() as session:
                o = existing.get(source)
                if o is not None:
                    o = await session.get(TechniqueOutcome, o.id)
                else:
                    o = TechniqueOutcome(id=new_id(), run_id=run_id, plan_source=source,
                                         setup_id=setup_id if source == "analysis" else None)
                    session.add(o)
                o.horizon_bars = horizon
                for k, v in fields.items():
                    setattr(o, k, v)
                await session.commit()
                existing[source] = o
                return o

        # --- unscorable cases ----------------------------------------------------------
        if r.mode == "image_only" or symbol == "IMAGE":
            for src, plan in plans:
                await upsert(src, status="unscorable", plan=plan or {},
                             note="image-only run: no symbol, nothing to fetch",
                             scored_at=dt.datetime.now(dt.timezone.utc))
            return [outcome_dict(o) for o in existing.values()]

        bars_after: list[Bar] = []
        reused = False
        prior_asset = next((o.bars_asset_id for o in existing.values() if o.bars_asset_id), None)
        if horizon_still_fetchable(tf, as_of):
            try:
                bars_after = await fetch_after(symbol, tf, as_of, horizon=horizon, entry_window=entry_window)
            except Exception as exc:           # Yahoo hiccup: keep pending, try again later
                log.warning("outcome fetch failed for %s: %s", run_id, exc)
                for src, plan in plans:
                    if src not in existing:
                        await upsert(src, status="pending", plan=plan or {}, note=f"fetch failed: {exc}")
                return [outcome_dict(o) for o in existing.values()]
        if not bars_after and prior_asset:
            data = await self.chat.get_asset_bytes(prior_asset)
            if data:
                try:
                    bars_after = rows_to_bars(symbol, tf, json.loads(data)["bars"])
                    reused = True
                except Exception:
                    bars_after = []
        if not bars_after:
            age_days = (time.time() - as_of / 1000) / 86400
            if not horizon_still_fetchable(tf, as_of):
                status, note = "unscorable", f"{tf} bars for that date are no longer served by Yahoo"
            elif age_days > 4:
                status, note = "unscorable", "no bars after as_of in 4 days (unknown symbol or data gap)"
            else:
                status, note = "pending", "no bars after as_of yet (after-hours / weekend)"
            for src, plan in plans:
                await upsert(src, status=status, plan=plan or {}, note=note, bars_after=0,
                             scored_at=dt.datetime.now(dt.timezone.utc) if status == "unscorable" else None)
            out = [outcome_dict(o) for o in existing.values()]
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "outcome", "runId": run_id, "outcomes": out})
            return out

        # --- score ------------------------------------------------------------------------
        last_close = float(facts.get("lastClose") or bars_after[0].open)
        decision = Bar(symbol=symbol, tf=tf, ts=as_of, open=last_close, high=last_close,
                       low=last_close, close=last_close, volume=0)
        series = [decision] + bars_after
        asset_id = prior_asset if reused else None
        if asset_id is None:
            blob = json.dumps({"symbol": symbol, "tf": tf, "asOf": as_of,
                               "bars": bars_to_rows(bars_after)}).encode("utf-8")
            asset_id = await self.chat.store_asset(blob, "application/json", thread_id=r.thread_id,
                                                   meta={"kind": "bars_after", "runId": run_id})
        path = path_summary(bars_after, last_close)
        now = dt.datetime.now(dt.timezone.utc)
        scored: list[dict] = []
        for src, plan in plans:
            if plan is None:
                o = await upsert(src, status="scored" if len(bars_after) >= horizon else "partial",
                                 plan={}, outcome=None, r_multiple=None, mfe_r=None, mae_r=None,
                                 bars_held=None, bars_after=len(bars_after), path=path,
                                 bars_asset_id=asset_id, scored_at=now,
                                 note="no plan to score (no setup and no candidate); path only")
            else:
                sim = simulate_plan(series, 0, plan, entry_window=entry_window, horizon=horizon,
                                    stop_on="close" if self.thresholds().stop_on_close else "low")
                o = await upsert(src, status="scored" if sim["resolved"] else "partial",
                                 plan={**plan, "entryWindow": entry_window}, outcome=sim["outcome"],
                                 r_multiple=sim["rMultiple"], mfe_r=sim["mfeR"], mae_r=sim["maeR"],
                                 bars_held=sim["barsHeld"], bars_after=len(bars_after), path=path,
                                 bars_asset_id=asset_id, scored_at=now, note=sim.get("note") or None)
            scored.append(outcome_dict(o))
        await self.engine.journal.append(ev.TECHNIQUE_OUTCOME_SCORED, {
            "runId": run_id, "symbol": symbol, "tf": tf, "asOf": as_of, "horizonBars": horizon,
            "barsAfter": len(bars_after),
            "outcomes": [{"planSource": o["planSource"], "status": o["status"], "outcome": o["outcome"],
                          "rMultiple": o["rMultiple"], "mfeR": o["mfeR"], "maeR": o["maeR"]} for o in scored],
            "summary": "; ".join(describe_outcome(o) for o in scored)},
            aggregate_type="technique_run", aggregate_id=run_id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "outcome", "runId": run_id, "outcomes": scored})
        return scored

    async def _score_plan_run(self, r: TechniqueRun, existing: dict[str, TechniqueOutcome]) -> list[dict]:
        """Score a plan run against the planned session's bars: one outcome row per
        trigger (`plan_source="trigger:<id>"`) plus a `levels` row with the level
        respect scorecard. Re-scored while the session is still open."""
        res = r.result or {}
        plan = res.get("plan") or {}
        plan_for = plan.get("planFor")
        tf = plan.get("triggerTf") or r.primary_tf
        symbol = r.symbol
        now = dt.datetime.now(dt.timezone.utc)

        async def upsert(source: str, **fields) -> TechniqueOutcome:
            async with self.engine.sf() as session:
                o = existing.get(source)
                if o is not None:
                    o = await session.get(TechniqueOutcome, o.id)
                else:
                    o = TechniqueOutcome(id=new_id(), run_id=r.id, plan_source=source)
                    session.add(o)
                for k, v in fields.items():
                    setattr(o, k, v)
                await session.commit()
                existing[source] = o
                return o

        if not plan_for or not plan.get("triggers") and not plan.get("levels"):
            o = await upsert("levels", status="unscorable", plan={}, note="plan has no levels or triggers",
                             scored_at=now)
            return [outcome_dict(o)]
        open_ms, close_ms = session_bounds(plan_for)
        now_ms = time.time() * 1000
        if now_ms < open_ms + 60_000:
            o = await upsert("levels", status="pending", plan={}, note=f"session {plan_for} has not started")
            return [outcome_dict(o)]
        try:
            bars = await fetch_session(symbol, tf, plan_for)
        except Exception as exc:
            o = await upsert("levels", status="pending", plan={}, note=f"fetch failed: {exc}")
            return [outcome_dict(o)]
        if not bars:
            stale = (now_ms - close_ms) > 4 * 86_400_000
            o = await upsert("levels", status="unscorable" if stale else "pending", plan={},
                             note=("no bars for the planned session (holiday / symbol / Yahoo depth)" if stale
                                   else "no bars yet for the planned session"),
                             scored_at=now if stale else None)
            out = [outcome_dict(o)]
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "outcome", "runId": r.id, "outcomes": out})
            return out
        complete = bars[-1].ts >= close_ms - 2 * 60_000 * max(1, {"1m": 1, "5m": 5, "15m": 15}.get(tf, 1))
        profile = None
        with contextlib.suppress(Exception):
            snap = await self.load_bars_snapshot(r.id)
            if snap and snap.get(tf):
                profile = build_profile(snap[tf])
        thr = self._thresholds_of(r)
        rep = replay_plan(plan, bars, thresholds=thr, profile=profile)
        blob = json.dumps({"symbol": symbol, "tf": tf, "asOf": r.as_of, "session": plan_for,
                           "bars": bars_to_rows(bars)}).encode("utf-8")
        asset_id = next((o.bars_asset_id for o in existing.values() if o.bars_asset_id), None)
        if asset_id is None:
            asset_id = await self.chat.store_asset(blob, "application/json", thread_id=r.thread_id,
                                                   meta={"kind": "bars_after", "runId": r.id, "session": plan_for})
        last_close = float(plan.get("lastClose") or bars[0].open)
        path = path_summary(bars, last_close)
        status = "scored" if complete else "partial"
        scored: list[dict] = []
        for tg in rep.get("triggers") or []:
            sim = tg.get("sim") or {}
            fired = tg.get("status") == "fired"
            o = await upsert(f"trigger:{tg['id']}", status=status if tg.get("valid") else "unscorable",
                             plan={k: tg.get(k) for k in ("id", "kind", "valid", "levelPrice", "entry", "stop",
                                                          "riskReward", "firedTs", "firedWindow", "fillPrice",
                                                          "observedMidday", "skipped", "counterfactual", "reasons")},
                             outcome=(sim.get("outcome") if fired else tg.get("status")),
                             r_multiple=sim.get("rMultiple") if fired else None,
                             mfe_r=sim.get("mfeR") if fired else None, mae_r=sim.get("maeR") if fired else None,
                             bars_held=sim.get("barsHeld") if fired else None, bars_after=len(bars), path=path,
                             bars_asset_id=asset_id, scored_at=now,
                             note=(f"fired {tg.get('firedWindow')}" if fired else tg.get("status")))
            scored.append(outcome_dict(o))
        o = await upsert("levels", status=status, plan={"levels": rep.get("levels"), "summary": rep.get("summary")},
                         outcome=None, bars_after=len(bars), path=path, bars_asset_id=asset_id, scored_at=now,
                         note=(f"{rep['summary'].get('levelsRespected', 0)} respected / "
                               f"{rep['summary'].get('levelsBroken', 0)} broken / "
                               f"{rep['summary'].get('levelsUntested', 0)} untested"))
        scored.append(outcome_dict(o))
        await self.engine.journal.append(ev.TECHNIQUE_OUTCOME_SCORED, {
            "runId": r.id, "symbol": symbol, "tf": tf, "planFor": plan_for, "mode": "plan",
            "complete": complete, "summary": rep.get("summary"),
            "triggers": [{"id": x["plan"].get("id"), "status": x["outcome"], "rMultiple": x["rMultiple"]}
                         for x in scored if x["planSource"].startswith("trigger:")]},
            aggregate_type="technique_run", aggregate_id=r.id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "outcome", "runId": r.id, "outcomes": scored})
        return scored

    def _thresholds_of(self, r: TechniqueRun) -> Thresholds:
        """The thresholds the run was built with (so a re-score is faithful)."""
        cfg = (r.config or {}).get("thresholds") or {}
        if not cfg:
            return self.thresholds()
        fields = {f.name for f in dataclasses.fields(Thresholds)}
        kw = {k: (tuple(v) if isinstance(v, list) else v) for k, v in cfg.items() if k in fields}
        try:
            return dataclasses.replace(self.thresholds(), **kw)
        except TypeError:
            return self.thresholds()

    # ------------------------------------------------------------ walk-forward sweeps
    async def start_sweep(self, symbols: list[str], start: str, end: str, *, structure_tfs: list[str] | None = None,
                          trigger_tf: str | None = None, include_invalid: bool = False, label: str = "",
                          wait: bool = False) -> dict:
        symbols = [str(s).upper().strip() for s in symbols if str(s).strip()]
        if not symbols:
            raise ValueError("at least one symbol")
        stf = list(structure_tfs or self.structure_tfs())
        ttf = trigger_tf or self.trigger_tf()
        t = self.thresholds()
        row = TechniqueSweep(id=new_id(), label=label or f"{len(symbols)} symbols {start}..{end}", symbols=symbols,
                             start=start, end=end, status="running",
                             params={"structureTfs": stf, "triggerTf": ttf, "includeInvalid": include_invalid,
                                     "sweepVersion": sweep_version(thresholds=t, structure_tfs=stf, trigger_tf=ttf),
                                     "techniqueSource": technique_source_version(),
                                     "thresholds": provenance_snapshot(thresholds=t, settings_all=self.engine.settings.all(),
                                                                       model="-", effort="-", thinking_display="-",
                                                                       max_passes=0, timeframes=stf + [ttf])["thresholds"],
                                     "processVersion": provenance_snapshot(
                                         thresholds=t, settings_all=self.engine.settings.all(), model="-", effort="-",
                                         thinking_display="-", max_passes=0, timeframes=stf + [ttf])["processVersion"]},
                             progress={"done": 0, "total": len(symbols)})
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        d = sweep_dict(row)
        await self.engine.journal.append(ev.TECHNIQUE_SWEEP_STARTED, d, aggregate_type="technique_sweep",
                                         aggregate_id=row.id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "sweep", "sweep": d})
        task = asyncio.create_task(self._run_sweep(row.id, symbols, start, end, stf, ttf, include_invalid, t),
                                   name=f"technique-sweep-{row.id[:8]}")
        self._sweeps[row.id] = task
        if wait:
            await task
            return await self.get_sweep(row.id) or d
        return d

    def _sweep_pool(self):
        """Executor for the CPU half of a sweep. `technique.walkforward.workers`:
        0 = auto (CPU count - 1, max 8) processes, 1 = one background thread (no
        extra processes — tests, tiny machines), N = N processes. Processes matter:
        each symbol-session is ~1 s of pure Python and the engine's event loop must
        keep serving quotes and the risk gate while a 45-symbol sweep runs."""
        want = int(self.engine.settings.get("technique.walkforward.workers", 0) or 0)
        if want == 1:
            return ThreadPoolExecutor(max_workers=1, thread_name_prefix="technique-sweep"), "thread"
        # auto: 4 is the sweet spot — each worker is a full Python process (~150 MB);
        # 7 of them plus the engine thrashed an 8-core box. Compute is ~2 s/symbol,
        # so 4 workers finish a 250-symbol sheet's CPU half in ~2 min anyway.
        n = want if want > 1 else max(1, min(4, (os.cpu_count() or 2) - 1))
        try:
            return ProcessPoolExecutor(max_workers=n, max_tasks_per_child=32), f"{n} processes"
        except Exception:                                    # pragma: no cover — exotic hosts
            log.exception("process pool unavailable, falling back to a thread")
            return ThreadPoolExecutor(max_workers=1, thread_name_prefix="technique-sweep"), "thread"

    async def _run_sweep(self, sweep_id: str, symbols: list[str], start: str, end: str, stf: list[str], ttf: str,
                         include_invalid: bool, t: Thresholds) -> None:
        """Fetch every symbol concurrently (history's semaphore bounds Yahoo), score
        each in the worker pool as soon as its bars land, persist per symbol."""
        all_rows: list[dict] = []
        errors: list[dict] = []
        done = 0
        loop = asyncio.get_running_loop()
        pool, pool_desc = self._sweep_pool()
        in_flight = asyncio.Semaphore(max(1, int(self.engine.settings.get("technique.walkforward.concurrency", 8) or 8)))
        lock = asyncio.Lock()
        fallback = ThreadPoolExecutor(max_workers=1, thread_name_prefix="technique-sweep-fb")

        async def one(sym: str) -> None:
            nonlocal done
            rows: list[dict] = []
            try:
                async with in_flight:
                    bars = await fetch_symbol_bars(sym, start, end, structure_tfs=stf, trigger_tf=ttf,
                                                   bars_override=self._sweep_bars_override(sym))
                    fn = functools.partial(compute_symbol_rows, sym, start, end, structure_tfs=stf, trigger_tf=ttf,
                                           thresholds=t, bars_by_tf=bars, include_invalid=include_invalid)
                    try:
                        rows = await loop.run_in_executor(pool, fn)
                    except (BrokenProcessPool, pickle.PicklingError, AttributeError) as exc:
                        log.warning("sweep worker pool failed for %s (%s) — computing in a thread", sym, exc)
                        rows = await loop.run_in_executor(fallback, fn)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("sweep symbol failed")
                errors.append({"symbol": sym, "error": str(exc)})
                rows = []
            if rows and rows[0].get("error"):
                errors.append({"symbol": sym, "error": rows[0]["error"]})
                rows = []
            async with lock:
                done += 1
                async with self.engine.sf() as session:
                    for r in rows:
                        session.add(TechniqueWalkforward(id=new_id(), sweep_id=sweep_id, symbol=sym, session=r["session"],
                                                         plan_for=r.get("planFor"), plan=r.get("plan") or {},
                                                         result=r.get("result") or {}))
                    sw = await session.get(TechniqueSweep, sweep_id)
                    if sw is not None:
                        sw.progress = {"done": done, "total": len(symbols), "rows": len(all_rows) + len(rows),
                                       "errors": errors, "workers": pool_desc}
                    await session.commit()
                all_rows.extend(rows)
                self.engine.bus.publish(topics.TECHNIQUE, {"kind": "sweep_progress", "sweepId": sweep_id,
                                                           "done": done, "total": len(symbols), "symbol": sym})

        try:
            log.info("sweep %s: %d symbols %s..%s on %s", sweep_id[:8], len(symbols), start, end, pool_desc)
            await asyncio.gather(*(one(sym) for sym in symbols))
            summary = aggregate_sweep(all_rows)
            summary["errors"] = errors
            async with self.engine.sf() as session:
                sw = await session.get(TechniqueSweep, sweep_id)
                sw.status = "done"
                sw.summary = summary
                sw.finished_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
                d = sweep_dict(sw)
            await self.engine.journal.append(ev.TECHNIQUE_SWEEP_COMPLETED, {
                "sweepId": sweep_id, "sessions": summary.get("sessions"), "fired": (summary.get("sample") or {}).get("fired"),
                "claims": [{"claim": c["claim"], "verdict": c["verdict"]} for c in summary.get("claims") or []],
                "errors": errors}, aggregate_type="technique_sweep", aggregate_id=sweep_id)
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "sweep", "sweep": d})
        except asyncio.CancelledError:
            async with self.engine.sf() as session:
                sw = await session.get(TechniqueSweep, sweep_id)
                if sw is not None:
                    sw.status = "failed"
                    sw.error = "cancelled"
                    await session.commit()
            raise
        except Exception as exc:
            log.exception("sweep failed")
            async with self.engine.sf() as session:
                sw = await session.get(TechniqueSweep, sweep_id)
                if sw is not None:
                    sw.status = "failed"
                    sw.error = f"{type(exc).__name__}: {exc}"
                    await session.commit()
        finally:
            self._sweeps.pop(sweep_id, None)
            pool.shutdown(wait=False, cancel_futures=True)
            fallback.shutdown(wait=False)

    # ------------------------------------------------------------ plan sheet ("prepare the next session")
    async def start_plan_sheet(self, symbols: list[str], *, label: str = "", wait: bool = False) -> dict:
        """Build the NEXT session's plan for every symbol at the last completed close —
        deterministic, free, no LLM, no technique runs minted (so it does not touch
        the runs/day budget). Stored as a sweep with `params.kind == "next"`; rows
        are pending until the session has happened, then `score_sheet` replays them
        and the sheet becomes an ordinary validation."""
        symbols = [str(s).upper().strip() for s in symbols if str(s).strip()]
        if not symbols:
            raise ValueError("at least one symbol")
        day = last_completed_session()
        plan_for = next_session_date(session_bounds(day)[1] + 1)
        stf, ttf, t = list(self.structure_tfs()), self.trigger_tf(), self.thresholds()
        row = TechniqueSweep(id=new_id(), label=label or f"Setups for {plan_for} · {len(symbols)} symbols", symbols=symbols,
                             start=day, end=day, status="running",
                             params={"kind": "next", "planFor": plan_for, "structureTfs": stf, "triggerTf": ttf,
                                     "includeInvalid": False,
                                     "sweepVersion": sweep_version(thresholds=t, structure_tfs=stf, trigger_tf=ttf),
                                     "techniqueSource": technique_source_version(),
                                     "thresholds": provenance_snapshot(thresholds=t, settings_all=self.engine.settings.all(),
                                                                       model="-", effort="-", thinking_display="-",
                                                                       max_passes=0, timeframes=stf + [ttf])["thresholds"]},
                             progress={"done": 0, "total": len(symbols)})
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        d = sweep_dict(row)
        await self.engine.journal.append(ev.TECHNIQUE_SWEEP_STARTED, {**d, "kind": "next"}, aggregate_type="technique_sweep",
                                         aggregate_id=row.id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "sweep", "sweep": d})
        task = asyncio.create_task(self._run_plan_sheet(row.id, symbols, day, plan_for, stf, ttf, t),
                                   name=f"technique-sheet-{row.id[:8]}")
        self._sweeps[row.id] = task
        if wait:
            await task
            return await self.get_sweep(row.id) or d
        return d

    async def _run_plan_sheet(self, sweep_id: str, symbols: list[str], day: str, plan_for: str, stf: list[str], ttf: str,
                              t: Thresholds) -> None:
        errors: list[dict] = []
        done = 0
        n_setups = 0
        loop = asyncio.get_running_loop()
        pool, pool_desc = self._sweep_pool()
        in_flight = asyncio.Semaphore(max(1, int(self.engine.settings.get("technique.walkforward.concurrency", 8) or 8)))
        lock = asyncio.Lock()
        fallback = ThreadPoolExecutor(max_workers=1, thread_name_prefix="technique-sheet-fb")

        async def one(sym: str) -> None:
            nonlocal done, n_setups
            row: dict | None = None
            try:
                async with in_flight:
                    bars = await fetch_symbol_bars(sym, day, day, structure_tfs=stf, trigger_tf=ttf,
                                                   bars_override=self._sweep_bars_override(sym))
                    fn = functools.partial(compute_symbol_plan, sym, day, structure_tfs=stf, trigger_tf=ttf,
                                           thresholds=t, bars_by_tf=bars)
                    try:
                        row = await loop.run_in_executor(pool, fn)
                    except (BrokenProcessPool, pickle.PicklingError, AttributeError) as exc:
                        log.warning("sheet worker pool failed for %s (%s) — computing in a thread", sym, exc)
                        row = await loop.run_in_executor(fallback, fn)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("plan sheet symbol failed")
                errors.append({"symbol": sym, "error": str(exc)})
                row = None
            if row and row.get("error"):
                errors.append({"symbol": sym, "error": row["error"]})
                row = None
            async with lock:
                done += 1
                if row and (row["plan"].get("validTriggers") or 0) > 0:
                    n_setups += 1
                async with self.engine.sf() as session:
                    if row:
                        session.add(TechniqueWalkforward(id=new_id(), sweep_id=sweep_id, symbol=sym, session=row["session"],
                                                         plan_for=row.get("planFor"), plan=row.get("plan") or {},
                                                         result=row.get("result") or {}))
                    sw = await session.get(TechniqueSweep, sweep_id)
                    if sw is not None:
                        sw.progress = {"done": done, "total": len(symbols), "errors": errors, "workers": pool_desc,
                                       "setups": n_setups}
                    await session.commit()
                self.engine.bus.publish(topics.TECHNIQUE, {"kind": "sweep_progress", "sweepId": sweep_id,
                                                           "done": done, "total": len(symbols), "symbol": sym})

        try:
            log.info("plan sheet %s: %d symbols for %s on %s", sweep_id[:8], len(symbols), plan_for, pool_desc)
            await asyncio.gather(*(one(sym) for sym in symbols))
            summary = {"kind": "next", "planFor": plan_for, "builtFrom": day, "symbols": sorted(symbols),
                       "setups": n_setups, "pending": True, "errors": errors,
                       "sample": {"fired": 0, "target": 100, "note": "scores after the session closes"}}
            async with self.engine.sf() as session:
                sw = await session.get(TechniqueSweep, sweep_id)
                sw.status = "done"
                sw.summary = summary
                sw.finished_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
                d = sweep_dict(sw)
            await self.engine.journal.append(ev.TECHNIQUE_SWEEP_COMPLETED, {
                "sweepId": sweep_id, "kind": "next", "planFor": plan_for, "symbols": len(symbols), "setups": n_setups,
                "errors": errors}, aggregate_type="technique_sweep", aggregate_id=sweep_id)
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "sweep", "sweep": d})
        except asyncio.CancelledError:
            async with self.engine.sf() as session:
                sw = await session.get(TechniqueSweep, sweep_id)
                if sw is not None:
                    sw.status = "failed"; sw.error = "cancelled"
                    await session.commit()
            raise
        except Exception as exc:
            log.exception("plan sheet failed")
            async with self.engine.sf() as session:
                sw = await session.get(TechniqueSweep, sweep_id)
                if sw is not None:
                    sw.status = "failed"; sw.error = f"{type(exc).__name__}: {exc}"
                    await session.commit()
        finally:
            self._sweeps.pop(sweep_id, None)
            pool.shutdown(wait=False, cancel_futures=True)
            fallback.shutdown(wait=False)

    async def score_sheet(self, sweep_id: str) -> dict | None:
        """Replay every still-pending row of a plan sheet whose session has closed;
        when none is pending the sheet's summary becomes the usual aggregate."""
        async with self.engine.sf() as session:
            sw = await session.get(TechniqueSweep, sweep_id)
            if sw is None:
                return None
            rows = (await session.execute(select(TechniqueWalkforward).where(TechniqueWalkforward.sweep_id == sweep_id))).scalars().all()
            params = dict(sw.params or {})
            pend = [r for r in rows if (r.result or {}).get("pending")]
            ids = [(r.id, r.symbol, r.session, dict(r.plan or {})) for r in pend]
        if not ids:
            return await self.get_sweep(sweep_id)
        stf = list(params.get("structureTfs") or self.structure_tfs()); ttf = params.get("triggerTf") or self.trigger_tf()
        t = self._thresholds_from(params.get("thresholds") or {})
        scored = 0
        for rid, sym, day, plan in ids:
            try:
                bars = await fetch_symbol_bars(sym, day, day, structure_tfs=stf, trigger_tf=ttf,
                                               bars_override=self._sweep_bars_override(sym))
                rep = score_pending_row(plan, bars, trigger_tf=ttf, thresholds=t,
                                        include_invalid=bool(params.get("includeInvalid")))
            except Exception as exc:
                log.warning("score sheet %s %s failed: %s", sweep_id[:8], sym, exc)
                rep = None
            if rep is None:
                continue
            async with self.engine.sf() as session:
                r = await session.get(TechniqueWalkforward, rid)
                if r is not None:
                    r.result = rep
                    await session.commit()
            scored += 1
        async with self.engine.sf() as session:
            sw = await session.get(TechniqueSweep, sweep_id)
            rows = (await session.execute(select(TechniqueWalkforward).where(TechniqueWalkforward.sweep_id == sweep_id))).scalars().all()
            still = sum(1 for r in rows if (r.result or {}).get("pending"))
            if sw is not None:
                if still == 0:
                    summ = aggregate_sweep([{"symbol": r.symbol, "session": r.session, "planFor": r.plan_for,
                                             "plan": r.plan, "result": r.result} for r in rows])
                    summ.update({"kind": "next", "planFor": params.get("planFor"), "scoredAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                                 "errors": (sw.summary or {}).get("errors") or []})
                    sw.summary = summ
                else:
                    sw.summary = {**(sw.summary or {}), "pendingRows": still, "scoredRows": scored}
                await session.commit()
        d = await self.get_sweep(sweep_id)
        if d:
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "sweep", "sweep": {k: v for k, v in d.items() if k != "rows"}})
        return d

    def _thresholds_from(self, snap: dict) -> Thresholds:
        try:
            return dataclasses.replace(self.thresholds(), **{k: (tuple(v) if isinstance(v, list) else v)
                                                             for k, v in snap.items() if hasattr(self.thresholds(), k)})
        except TypeError:
            return self.thresholds()

    def _sweep_bars_override(self, symbol: str) -> dict[str, list[Bar]] | None:
        """Hook for tests (monkeypatched) — production always fetches from Yahoo."""
        return None

    async def list_sweeps(self, *, limit: int = 50) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(select(TechniqueSweep).order_by(TechniqueSweep.created_at.desc())
                                          .limit(limit))).scalars().all()
        return [sweep_dict(x) for x in rows]

    async def rename_sweep(self, sweep_id: str, label: str) -> dict | None:
        """Cosmetic: the label shown in the validation history (rows/summary untouched)."""
        async with self.engine.sf() as session:
            sw = await session.get(TechniqueSweep, sweep_id)
            if sw is None:
                return None
            sw.label = (label or "").strip()[:120] or sw.label
            await session.commit()
            d = sweep_dict(sw)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "sweep", "sweep": d})
        return d

    async def get_sweep(self, sweep_id: str, *, rows: bool = True) -> dict | None:
        async with self.engine.sf() as session:
            sw = await session.get(TechniqueSweep, sweep_id)
            if sw is None:
                return None
            d = sweep_dict(sw)
            if rows:
                rs = (await session.execute(select(TechniqueWalkforward).where(TechniqueWalkforward.sweep_id == sweep_id)
                                            .order_by(TechniqueWalkforward.symbol, TechniqueWalkforward.session))).scalars().all()
                d["rows"] = [walkforward_row_dict(x) for x in rs]
        return d

    async def promote(self, sweep_id: str, symbol: str, session_day: str, *, with_vision: bool = False,
                      wait: bool = True, force: bool = False) -> dict:
        """Turn one sweep row into a full, reviewable plan run (same as-of).

        With `with_vision`, a FINISHED analyst read for the same symbol and plan
        close is reused instead of paid for again (unless `force`): a second
        "Check & arm" after a restart re-reads only what is still missing."""
        async with self.engine.sf() as session:
            row = (await session.execute(select(TechniqueWalkforward).where(
                TechniqueWalkforward.sweep_id == sweep_id, TechniqueWalkforward.symbol == symbol.upper(),
                TechniqueWalkforward.session == session_day))).scalars().first()
            sw = await session.get(TechniqueSweep, sweep_id)
        if row is None or sw is None:
            raise KeyError("sweep row not found")
        _, close_ms = session_bounds(session_day)
        params = sw.params or {}
        if with_vision and not force:
            async with self.engine.sf() as session:
                prior = (await session.execute(
                    select(TechniqueRun).where(TechniqueRun.symbol == symbol.upper(), TechniqueRun.as_of == close_ms + 1,
                                               TechniqueRun.status == "done", TechniqueRun.mode == "plan")
                    .order_by(TechniqueRun.created_at.desc()).limit(6))).scalars().all()
            for pr in prior:
                if (pr.result or {}).get("passes"):
                    async with self.engine.sf() as session:
                        r2 = await session.get(TechniqueWalkforward, row.id)
                        if r2 is not None:
                            r2.promoted_run_id = pr.id
                            await session.commit()
                    d = run_dict(pr)
                    d["reused"] = True
                    return d
        rd = await self.analyze(symbol, as_of_ms=close_ms + 1, primary_tf=params.get("triggerTf"),
                                trigger="promote", plan=True, with_vision=with_vision, wait=wait)
        async with self.engine.sf() as session:
            r2 = await session.get(TechniqueWalkforward, row.id)
            if r2 is not None:
                r2.promoted_run_id = rd["id"]
                await session.commit()
        return rd

    # ------------------------------------------------------------ arming (phase 2)
    async def arm_plan(self, run_id: str, config: dict | None = None) -> dict:
        return await self.armer.arm(run_id, config)

    # --- the multi-technique armed hub -------------------------------------------
    # Every PlanRunner on the engine (EM's armer, the tip runner, future
    # techniques) registers in `engine.plan_runners`; the /api/technique/armed
    # hub endpoints aggregate across ALL of them so a plan armed by any
    # technique shows up — the WS deltas already come from every runner
    # (PlanRunner._publish), and a REST list that disagreed with them made
    # tip plans flicker in and out of the UI (found 2026-08-29).
    def _runners(self) -> list:
        rs = list((getattr(self.engine, "plan_runners", None) or {}).values())
        if self.armer not in rs:
            rs.insert(0, self.armer)
        return rs

    def runner_for(self, run_id: str):
        """The PlanRunner holding this armed plan, or None."""
        for r in self._runners():
            if r.get(run_id) is not None:
                return r
        return None

    def _runner_or_raise(self, run_id: str):
        r = self.runner_for(run_id)
        if r is None:
            raise KeyError(run_id)
        return r

    async def disarm_plan(self, run_id: str, *, flatten: bool = False, reason: str = "manual") -> bool:
        r = self.runner_for(run_id)
        if r is None:
            return False
        return await r.disarm(run_id, reason=reason, flatten=flatten)

    async def pause_plan(self, run_id: str) -> dict:
        return await self._runner_or_raise(run_id).pause(run_id)

    async def resume_plan(self, run_id: str) -> dict:
        return await self._runner_or_raise(run_id).resume(run_id)

    async def stop_all_armed(self, *, flatten: bool = False) -> int:
        n = 0
        for r in self._runners():
            n += await r.stop_all(flatten=flatten)
        return n

    async def arm_today(self, symbol: str, config: dict | None = None, *, with_vision: bool | None = None) -> dict:
        return await self.armer.arm_today(symbol, config, with_vision=with_vision)

    async def arm_preflight(self, run_id: str, config: dict | None = None) -> dict:
        return await self.armer.preflight(run_id, config)

    def armed_plans(self, *, slim: bool = False) -> list[dict]:
        return [d for r in self._runners() for d in r.armed(slim=slim)]

    async def armed_summary(self) -> dict:
        """The phone's "Now" payload: the live summary plus the plans that
        ended today (loss halt, disarm, expiry) — which the live list forgets."""
        from zoneinfo import ZoneInfo
        from ..models import TechniqueArmed
        runners = self._runners()
        out = runners[0].summary()
        for r in runners[1:]:
            s = r.summary()
            for k, v in (s.get("counts") or {}).items():
                out["counts"][k] = out["counts"].get(k, 0) + v
            for k in ("attention", "inTrade", "watching", "timeline", "stoppedToday"):
                out[k].extend(s.get(k) or [])
            for k in ("realized", "unrealized", "lossLimit"):
                out["pnl"][k] = round(out["pnl"][k] + (s.get("pnl") or {}).get(k, 0.0), 2)
        if len(runners) > 1:
            out["timeline"].sort(key=lambda x: -(x.get("ts") or 0))
            out["timeline"] = out["timeline"][:100]
            out["watching"].sort(key=lambda w: (w.get("stale") or False,
                                                abs((w.get("nearest") or {}).get("distancePct") or 999)))
            ll = out["pnl"]["lossLimit"]
            used = (-(out["pnl"]["realized"] + out["pnl"]["unrealized"]) / ll * 100) if ll > 0 else None
            out["pnl"]["lossLimitUsedPct"] = round(max(0.0, used), 1) if used is not None else None
        today = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        seen = {s["runId"] for s in out["stoppedToday"]}
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TechniqueArmed).where(TechniqueArmed.plan_for == today,
                                             TechniqueArmed.status.in_(("disarmed", "expired")))
                .order_by(TechniqueArmed.updated_at.desc()).limit(100))).scalars().all()
        for r in rows:
            if r.run_id in seen:
                continue
            st = r.state or {}
            trades = st.get("trades") or []
            realized = 0.0
            for t in trades if isinstance(trades, list) else trades.values():
                try:
                    realized += float((t or {}).get("realizedPnl") or (t or {}).get("realized_pnl") or 0)
                except (TypeError, ValueError):
                    pass
            out["stoppedToday"].append({
                "runId": r.run_id, "symbol": r.symbol, "status": r.status, "mode": r.mode,
                "reason": st.get("stopReason") or ("expired at the close" if r.status == "expired" else "disarmed"),
                "realizedPnl": round(realized, 2),
                "at": r.updated_at.isoformat() if r.updated_at else None,
            })
        out["counts"]["stoppedToday"] = len(out["stoppedToday"])
        return out

    def armed_detail(self, run_id: str) -> dict | None:
        for r in self._runners():
            d = r.detail(run_id)
            if d is not None:
                return d
        return None

    async def armed_audit(self, run_id: str, *, limit: int = 200) -> list[dict]:
        r = self.runner_for(run_id) or self.armer
        return await r.audit(run_id, limit=limit)

    async def armed_history(self, *, limit: int = 50) -> list[dict]:
        from ..models import TechniqueArmed
        async with self.engine.sf() as session:
            rows = (await session.execute(select(TechniqueArmed).order_by(TechniqueArmed.created_at.desc())
                                          .limit(limit))).scalars().all()
        return [{"runId": r.run_id, "symbol": r.symbol, "planFor": r.plan_for, "portfolioId": r.portfolio_id,
                 "technique": getattr(r, "technique", None) or "enhanced_market",
                 "mode": r.mode, "status": r.status, "config": r.config or {}, "state": r.state or {},
                 "createdAt": r.created_at.isoformat() if r.created_at else None,
                 "updatedAt": r.updated_at.isoformat() if r.updated_at else None} for r in rows]

    def arm_options(self) -> dict:
        """What the Arm dialog needs: accounts (with cash + options capability),
        defaults, and the live/auto gate state."""
        s = self.engine.settings
        ports = []
        for p in self.engine.positions.portfolios():
            ok, why = self.armer.options_capability(p)
            ports.append({**{k: p.get(k) for k in ("id", "name", "kind", "venue", "baseCurrency", "cash", "isDefault",
                                                   "sourceName")},
                          "optionsOk": ok, "optionsNote": why})
        return {
            "portfolios": ports,
            "defaults": {"portfolioId": str(s.get("technique.arm.default_portfolio", "")) or str(s.get("trading.default_portfolio", "")),
                         "mode": str(s.get("technique.arm.mode", "proposal")),
                         "instrument": str(s.get("technique.arm.instrument", "options")),
                         "contracts": int(s.get("technique.arm.contracts", 1)),
                         "maxContracts": int(s.get("technique.arm.max_contracts", 5)),
                         "singleContractExit": str(s.get("technique.arm.single_contract_exit", "tp2")),
                         "riskPct": float(s.get("technique.arm.risk_pct", 0.5)),
                         "maxRiskPct": float(s.get("technique.max_risk_pct", 5.0)),
                         "maxQty": float(s.get("technique.arm.max_qty", 100)),
                         "useCritic": bool(s.get("technique.arm.use_critic", True)),
                         "flattenMinutesBeforeClose": int(s.get("technique.arm.flatten_minutes_before_close", 5)),
                         "slippagePct": float(s.get("technique.arm.slippage_pct", 0.1)),
                         "maxOpenTrades": int(s.get("technique.arm.max_open_trades", 1)),
                         "dailyLossLimit": float(s.get("technique.arm.daily_loss_limit", 0.0)),
                         "skipWideSpread": bool(s.get("technique.arm.skip_wide_spread", True)),
                         "skipElevatedIv": bool(s.get("technique.arm.skip_elevated_iv", False)),
                         "entryFallback": str(s.get("technique.arm.entry_fallback", "off"))},
            "haltAllowsExits": bool(s.get("risk.halt_allows_exits", True)),
            "optionsEnabled": bool(s.get("technique.options.enabled", True)),
            "optionsProvider": getattr(self.options_provider(), "name", "?"),
            "tradingMode": str(s.get("trading.mode", "practice")),
            "allowLiveAuto": bool(s.get("technique.arm.allow_live_auto", False)),
            "enabled": bool(s.get("technique.arm.enabled", True)),
            "llmAvailable": self.llm_config().available,
            "halt": getattr(self.engine.halt, "to_dict", lambda: {})(),
            "emitProposals": bool(s.get("technique.emit_proposals", False)),
        }

    async def score_pending(self, *, limit: int = 25) -> dict:
        """Score every finished run that has no outcome yet or a still-open one.
        Called by the outcome loop and `POST /api/technique/outcomes/score`."""
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=25)
        async with self.engine.sf() as session:
            runs = (await session.execute(
                select(TechniqueRun.id, TechniqueRun.as_of, TechniqueRun.created_at)
                .where(TechniqueRun.status == "done", TechniqueRun.mode.in_(("full", "plan")),
                       TechniqueRun.created_at >= cutoff)
                .order_by(TechniqueRun.created_at.desc()).limit(400))).all()
            ids = [x.id for x in runs]
            outs = (await session.execute(
                select(TechniqueOutcome).where(TechniqueOutcome.run_id.in_(ids)))).scalars().all() if ids else []
        by_run: dict[str, list[TechniqueOutcome]] = {}
        for o in outs:
            by_run.setdefault(o.run_id, []).append(o)
        todo: list[str] = []
        now_ms = time.time() * 1000
        for x in runs:
            as_of = x.as_of or int(x.created_at.timestamp() * 1000)
            if now_ms - as_of < 5 * 60 * 1000:
                continue                        # give the first bars a chance to print
            rows = by_run.get(x.id, [])
            if not rows or any(o.status in ("pending", "partial") for o in rows):
                todo.append(x.id)
        scored, failed = [], []
        for rid in todo[:limit]:
            try:
                await self.score_run(rid)
                scored.append(rid)
            except Exception as exc:
                log.warning("score_run %s failed: %s", rid, exc)
                failed.append({"runId": rid, "error": str(exc)})
        return {"scored": scored, "failed": failed, "remaining": max(0, len(todo) - limit)}

    async def _outcome_loop(self) -> None:
        await asyncio.sleep(20)               # let the engine settle first
        while True:
            try:
                interval = max(5, int(self.engine.settings.get("technique.outcome.interval_minutes", 30)))
                if bool(self.engine.settings.get("technique.outcome.enabled", True)):
                    await self.score_pending()
                await asyncio.sleep(interval * 60)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("outcome loop error")
                await asyncio.sleep(60)

    # ------------------------------------------------------------ reviews
    async def add_review(self, run_id: str, *, review_verdict: str, reviewer: str = "user",
                         expected_verdict: str | None = None, expected_setup_type: str | None = None,
                         expected_plan: dict | None = None, expectation_note: str = "",
                         root_cause_stage: str | None = None, notes: str = "",
                         actions: list[dict] | None = None) -> dict:
        validate_review(review_verdict=review_verdict, root_cause_stage=root_cause_stage,
                        reviewer=reviewer, expected_verdict=expected_verdict)
        async with self.engine.sf() as session:
            r = await session.get(TechniqueRun, run_id)
            if r is None:
                raise KeyError(f"run {run_id} not found")
            cfg = r.config or {}
            row = TechniqueReview(
                id=new_id(), run_id=run_id, reviewer=reviewer, expected_verdict=expected_verdict,
                expected_setup_type=expected_setup_type, expected_plan=expected_plan or {},
                expectation_note=expectation_note or "", review_verdict=review_verdict,
                root_cause_stage=root_cause_stage, notes=notes or "",
                actions=[{"desc": str(a.get("desc", a)) if isinstance(a, dict) else str(a),
                          "file": (a.get("file") if isinstance(a, dict) else None),
                          "status": (a.get("status", "planned") if isinstance(a, dict) else "planned")}
                         for a in (actions or [])],
                process_version={k: cfg.get(k) for k in ("processVersion", "promptVersion",
                                                         "rulebookVersion", "codeVersion", "model", "effort")})
            session.add(row)
            await session.commit()
        d = review_dict(row)
        await self.engine.journal.append(ev.TECHNIQUE_REVIEW_ADDED, {**d, "symbol": r.symbol,
                                                                     "runVerdict": r.verdict},
                                         aggregate_type="technique_run", aggregate_id=run_id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "review", "runId": run_id, "review": d})
        if r.thread_id and self.chat:
            txt = (f"**Review ({reviewer})** — {review_verdict}"
                   + (f" · root cause: {root_cause_stage}" if root_cause_stage else "")
                   + (f"\nExpected: {expected_verdict}"
                      + (f" ({expected_setup_type})" if expected_setup_type else "") if expected_verdict else "")
                   + (f"\n{expectation_note}" if expectation_note else "")
                   + (f"\n{notes}" if notes else "")
                   + ("\nActions:\n- " + "\n- ".join(a["desc"] for a in d["actions"]) if d["actions"] else ""))
            with contextlib.suppress(Exception):
                await self.chat.append_message(r.thread_id, "user", [{"type": "text", "text": txt}],
                                               {"kind": "review", "reviewId": row.id}, run_id=run_id)
        return d

    async def list_reviews(self, run_id: str | None = None, *, limit: int = 200) -> list[dict]:
        async with self.engine.sf() as session:
            stmt = select(TechniqueReview).order_by(TechniqueReview.created_at.desc()).limit(limit)
            if run_id:
                stmt = stmt.where(TechniqueReview.run_id == run_id)
            rows = (await session.execute(stmt)).scalars().all()
        return [review_dict(x) for x in rows]

    # ------------------------------------------------------------ replay / diff
    async def load_bars_snapshot(self, run_id: str) -> dict[str, list[Bar]] | None:
        async with self.engine.sf() as session:
            r = await session.get(TechniqueRun, run_id)
        if r is None:
            raise KeyError(f"run {run_id} not found")
        aid = (r.config or {}).get("barsAssetId")
        if not aid or not self.chat:
            return None
        data = await self.chat.get_asset_bytes(aid)
        if not data:
            return None
        snap = json.loads(gzip.decompress(data).decode("utf-8"))
        return {tf: rows_to_bars(r.symbol, tf, rows) for tf, rows in (snap.get("bars") or {}).items()}

    async def replay_run(self, run_id: str, *, thresholds: dict | None = None, use_snapshot: bool = True,
                         note: str = "", wait: bool = False) -> dict:
        """Re-run an earlier moment, linked to the parent. With `use_snapshot`
        (default) the exact bars the parent saw are reused, so a replay isolates
        the effect of prompt/threshold/code changes from data drift."""
        async with self.engine.sf() as session:
            parent = await session.get(TechniqueRun, run_id)
        if parent is None:
            raise KeyError(f"run {run_id} not found")
        if parent.mode not in ("full", "plan"):
            raise ValueError("image-only runs cannot be replayed (no bars)")
        bars = await self.load_bars_snapshot(run_id) if use_snapshot else None
        as_of = parent.as_of or int(parent.created_at.timestamp() * 1000)
        rd = await self.analyze(parent.symbol, as_of_ms=as_of, primary_tf=parent.primary_tf,
                                trigger="replay", note=note, parent_run_id=run_id,
                                thresholds_override=thresholds, bars_override=bars, wait=wait,
                                plan=(True if parent.mode == "plan" else False))
        await self.engine.journal.append(ev.TECHNIQUE_RUN_REPLAYED, {
            "parentRunId": run_id, "runId": rd["id"], "symbol": parent.symbol, "asOf": as_of,
            "thresholds": thresholds or {}, "barsFromSnapshot": bars is not None, "note": note},
            aggregate_type="technique_run", aggregate_id=run_id)
        return rd

    async def diff(self, run_a: str, run_b: str) -> dict:
        a = await self.get_run(run_a)
        b = await self.get_run(run_b)
        if a is None or b is None:
            raise KeyError("run not found: " + (run_a if a is None else run_b))
        return diff_runs(a, b)

    # ------------------------------------------------------------ options
    async def option_pick(self, symbol: str, direction: str = "long", *, spot: float | None = None,
                          max_strike: float | None = None, min_strike: float | None = None,
                          avoid_0dte: bool = False) -> dict:
        client = self.options_provider()
        if spot is None:
            q = self.engine.quotes.get(symbol.upper())
            spot = float(q.last) if q and q.last > 0 else None
        if spot is None:
            try:
                spot = await client.spot(symbol)
            except Exception as exc:
                return {"available": False, "error": f"no spot price: {exc}",
                        "provider": getattr(client, "name", "?")}
        if not spot:
            return {"available": False, "error": "no spot price",
                    "provider": getattr(client, "name", "?")}
        out = await pick_for_setup(client, symbol, spot, direction, max_strike=max_strike,
                                   min_strike=min_strike, avoid_0dte=avoid_0dte)
        out["spot"] = spot
        return out

    # ------------------------------------------------------------ backtest
    async def backtest(self, symbol: str, tf: str = "5m", *, days: int = 10, start_ms: int | None = None,
                       end_ms: int | None = None, horizon_bars: int = 60, step_bars: int = 5,
                       prime_windows_only: bool | None = None) -> dict:
        end_ms = end_ms or int(time.time() * 1000)
        start_ms = start_ms or end_ms - days * 86400 * 1000
        if prime_windows_only is None:
            prime_windows_only = bool(self.engine.settings.get("technique.enforce_session_windows", True))
        return await run_backtest(symbol, tf, start_ms, end_ms, horizon_bars=horizon_bars,
                                  step_bars=step_bars, thresholds=self.thresholds(),
                                  prime_windows_only=prime_windows_only)

    # ------------------------------------------------------------ scans
    async def fail_orphaned_sweeps(self) -> int:
        """A sweep / sheet that was `running` when the process died can never
        finish (its task died with the process): mark it so the UI stops showing
        a frozen progress bar and the evening automation rebuilds the sheet."""
        n = 0
        async with self.engine.sf() as session:
            rows = (await session.execute(select(TechniqueSweep).where(TechniqueSweep.status == "running"))).scalars().all()
            for sw in rows:
                sw.status = "failed"
                sw.error = "interrupted by a restart — re-run it (a sheet rebuilds itself in the evening window)"
                sw.finished_at = dt.datetime.now(dt.timezone.utc)
                n += 1
            # the same for analysis runs: an LLM read that was mid-flight when the
            # process died never finishes (88 analyst checks died to a restart on
            # 2026-08-26 and sat 'running' — the scan panel waited on them for ever)
            runs = (await session.execute(select(TechniqueRun).where(TechniqueRun.status == "running"))).scalars().all()
            for r in runs:
                r.status = "failed"
                r.error = "interrupted by a restart — run it again"
                r.finished_at = dt.datetime.now(dt.timezone.utc)
                n += 1
            if n:
                await session.commit()
        if n:
            log.warning("marked %d orphaned running sweep(s)/run(s) as interrupted", n)
        return n

    def start(self) -> None:
        if self._scan_task is None:
            self._scan_task = asyncio.create_task(self._scan_loop(), name="technique-scan")
        asyncio.create_task(self.fail_orphaned_sweeps(), name="technique-orphaned-sweeps")
        if self._outcome_task is None:
            self._outcome_task = asyncio.create_task(self._outcome_loop(), name="technique-outcome")
        if getattr(self, "_sheet_task", None) is None:
            self._sheet_task = asyncio.create_task(self._sheet_loop(), name="technique-sheet-auto")
        self.armer.start()
        asyncio.create_task(self._restore_armed(), name="technique-armer-restore")

    async def _sheet_exists_for(self, plan_for: str) -> bool:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TechniqueSweep).order_by(TechniqueSweep.created_at.desc()).limit(12))).scalars().all()
        return any((r.params or {}).get("kind") == "next"
                   and str((r.params or {}).get("planFor") or "") == plan_for
                   and r.status in ("running", "done") for r in rows)

    async def _sheet_loop(self) -> None:
        """The evening ritual, automated (technique.sheet.auto):
        off      — nothing.
        build    — after the close, build the next session's graded sheet.
        analyst  — build, then analyst-check every grade-A row (LLM cost applies).
        Runs inside a window after the close so one sheet per session, built
        from that day's completed bars."""
        while True:
            try:
                await asyncio.sleep(60)
                mode = str(self.engine.settings.get("technique.sheet.auto", "off"))
                if mode not in ("build", "analyst"):
                    continue
                now_et = dt.datetime.now(ET)
                if now_et.weekday() >= 5:
                    continue
                at = str(self.engine.settings.get("technique.sheet.build_at", "16:15"))
                try:
                    hh, mm = (int(x) for x in at.split(":"))
                except ValueError:
                    hh, mm = 16, 15
                mins = now_et.hour * 60 + now_et.minute
                if not (hh * 60 + mm <= mins < hh * 60 + mm + 45):
                    continue
                plan_for = next_session_date(int(time.time() * 1000))
                if await self._sheet_exists_for(plan_for):
                    continue
                syms = [str(s).upper() for s in (self.engine.settings.get("technique.sheet.symbols", []) or [])]
                if not syms:
                    syms = await self.universe()          # core + your extras + today's most active
                if not syms:
                    continue
                log.info("auto sheet: building %d symbols for %s", len(syms), plan_for)
                sweep = await self.start_plan_sheet(syms, label=f"Auto sheet for {plan_for}", wait=True)
                self.engine.bus.publish(topics.TECHNIQUE, {
                    "kind": "alert", "level": "info",
                    "text": f"Auto sheet for {plan_for} built: {len(syms)} symbols"})
                if mode == "analyst" and sweep.get("id"):
                    full = await self.get_sweep(sweep["id"], rows=True) or {}
                    picked = []
                    for row in full.get("rows") or []:
                        trig = [t for t in ((row.get("plan") or {}).get("triggers") or []) if t.get("valid")]
                        best = max(trig, key=lambda t: (t.get("assessment") or {}).get("score") or 0, default=None)
                        if best and (best.get("assessment") or {}).get("grade") == "A":
                            picked.append(row)
                    log.info("auto sheet: analyst-checking %d grade-A rows", len(picked))
                    for row in picked:
                        with contextlib.suppress(Exception):
                            await self.promote(sweep["id"], row["symbol"], row["session"],
                                               with_vision=True, wait=False)
                    if picked:
                        self.engine.bus.publish(topics.TECHNIQUE, {
                            "kind": "alert", "level": "info",
                            "text": f"Analyst check started on {len(picked)} grade-A setup(s) for {plan_for}"})
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("auto sheet loop error")

    async def _restore_armed(self) -> None:
        try:
            n = await self.armer.restore()
            if n:
                log.info("re-armed %d plan(s) after restart", n)
        except Exception:
            log.exception("re-arming plans failed")

    async def stop(self) -> None:
        for t in list(self._running.values()):
            t.cancel()
        for t in list(self._sweeps.values()):
            t.cancel()
        await self.armer.stop()
        for name in ("_scan_task", "_outcome_task"):
            task = getattr(self, name)
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                setattr(self, name, None)
        if self._tradier:
            with contextlib.suppress(Exception):
                await self._tradier.aclose()
        if self._cboe:
            with contextlib.suppress(Exception):
                await self._cboe.aclose()

    def _in_rth(self) -> bool:
        try:
            from zoneinfo import ZoneInfo
            now = dt.datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=4)
        if now.weekday() >= 5:
            return False
        return RTH_START <= now.time() <= RTH_END

    async def scan_once(self, *, force: bool = False) -> dict:
        symbols = [str(s).upper() for s in self.engine.settings.get("technique.scan.symbols", [])]
        started, skipped = [], []
        for sym in symbols:
            try:
                rd = await self.analyze(sym, trigger="scan")
                started.append(rd["id"])
            except Exception as exc:
                skipped.append({"symbol": sym, "reason": str(exc)})
                if "daily run cap" in str(exc):
                    break
        await self.engine.journal.append(ev.TECHNIQUE_SCAN, {"started": started, "skipped": skipped,
                                                             "forced": force})
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "scan", "started": started, "skipped": skipped})
        return {"started": started, "skipped": skipped}

    def _scan_allowed(self) -> bool:
        """R6 — scheduled scans run in the prime windows only (when enforced);
        otherwise the old RTH-only behaviour."""
        if bool(self.engine.settings.get("technique.enforce_session_windows", True)):
            wanted = set(self.engine.settings.get("technique.scan.windows", ["prime_open", "prime_close"]))
            return session_window(int(time.time() * 1000)) in wanted
        return not bool(self.engine.settings.get("technique.scan.rth_only", True)) or self._in_rth()

    async def _scan_loop(self) -> None:
        while True:
            try:
                interval = max(5, int(self.engine.settings.get("technique.scan.interval_minutes", 30)))
                if bool(self.engine.settings.get("technique.scan.enabled", False)):
                    if self._scan_allowed():
                        await self.scan_once()
                await asyncio.sleep(interval * 60)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("scan loop error")
                await asyncio.sleep(60)


# --- helpers --------------------------------------------------------------------

def _rejected_overlay(facts: dict, a) -> dict | None:
    """The deterministic candidate the analysis declined, as a drawable plan."""
    cands = facts.get("candidateSetups") or []
    if not cands:
        return None
    c = cands[0]
    return {"entry": {"price": c["entry"]["price"]}, "stop": {"price": c["stop"]["price"]},
            "targets": [{"price": t["price"]} for t in (c.get("targets") or [])[:1]],
            "riskReward": c.get("riskReward"), "setupType": c.get("setupType")}


def _chart_caption(a, rejected: dict | None) -> str:
    """One or two lines drawn on the chart summarising the verdict."""
    if a is None:
        return ""
    if a.verdict == "setup":
        return f"SETUP · {a.setup_type.replace('_', ' ')} · R:R {a.risk_reward:.2f}"
    lines = ["NO SETUP"]
    if rejected:
        rr = rejected.get("riskReward")
        kind = (rejected.get("setupType") or "candidate").replace("_", " ")
        lines.append(f"rejected {kind}: entry {rejected['entry']['price']:.2f}, "
                     f"stop {rejected['stop']['price']:.2f}"
                     + (f", R:R {rr:.2f} (need 3.0)" if rr is not None else ""))
    reason = next((r for r in a.no_trade_reasons if not r.startswith("CRITIC")), "")
    if reason:
        lines.append(reason[:96] + ("…" if len(reason) > 96 else ""))
    return "\n".join(lines)


def _slim_facts(facts: dict) -> dict:
    """Facts without the raw bar arrays (the UI fetches bars itself)."""
    if not facts:
        return {}
    out = dict(facts)
    out["bars"] = {tf: rows[-60:] for tf, rows in (facts.get("bars") or {}).items()}
    return out


def run_summary_from_dict(rd: dict) -> dict:
    d = dict(rd)
    d.pop("facts", None)
    d.pop("config", None)
    res = d.pop("result", None) or {}
    d["analysis"] = res.get("analysis")
    d["groundingPassed"] = (res.get("grounding") or {}).get("passed")
    d["options"] = res.get("options")
    d["seconds"] = res.get("seconds")
    d["traceSteps"] = len(res.get("trace") or [])
    return d


def _slim_plan_summary(plan: dict | None) -> dict | None:
    if not plan:
        return None
    return {"planFor": plan.get("planFor"), "builtFromSession": plan.get("builtFromSession"),
            "levels": len(plan.get("levels") or []), "triggers": len(plan.get("triggers") or []),
            "validTriggers": plan.get("validTriggers"),
            "kinds": sorted({t.get("kind") for t in (plan.get("triggers") or []) if t.get("valid")})}


def sweep_dict(s: TechniqueSweep) -> dict:
    return {"id": s.id, "technique": getattr(s, "technique", None) or "enhanced_market",
            "label": s.label, "symbols": list(s.symbols or []), "start": s.start, "end": s.end,
            "params": s.params or {}, "status": s.status, "progress": s.progress or {}, "summary": s.summary or {},
            "error": s.error, "createdAt": s.created_at.isoformat() if s.created_at else None,
            "finishedAt": s.finished_at.isoformat() if s.finished_at else None}


def walkforward_row_dict(r: TechniqueWalkforward) -> dict:
    res = r.result or {}
    return {"id": r.id, "sweepId": r.sweep_id, "symbol": r.symbol, "session": r.session, "planFor": r.plan_for,
            "plan": r.plan or {}, "result": res, "summary": res.get("summary") or {},
            "promotedRunId": r.promoted_run_id,
            "createdAt": r.created_at.isoformat() if r.created_at else None}


def _slim_outcome(o: dict) -> dict:
    return {k: o.get(k) for k in ("id", "planSource", "status", "outcome", "rMultiple", "mfeR", "maeR",
                                  "barsHeld", "barsAfter", "scoredAt")}


def _outcome_matches(outs: list[dict], want: str) -> bool:
    """`want` is an outcome value (stopped, tp1..3, horizon, not_filled) matched
    on the analysis plan first, then any plan; or a status (scored, pending,
    partial, unscorable); or 'win' / 'loss' on realised R; or 'none'."""
    if want == "none":
        return not outs
    if want in ("scored", "pending", "partial", "unscorable"):
        return any(o.get("status") == want for o in outs)
    primary = next((o for o in outs if o.get("planSource") == "analysis"), None) or \
        next((o for o in outs if o.get("planSource") == "candidate"), None)
    if primary is None:
        return False
    if want == "win":
        return (primary.get("rMultiple") or 0) > 0
    if want == "loss":
        return (primary.get("rMultiple") or 0) < 0
    return primary.get("outcome") == want


def _summary_text(contract: dict | None, grounding: dict, options: dict | None) -> str:
    if not contract:
        return "Analysis produced no result."
    L = [f"**{contract['symbol']} — {contract['verdict'].upper()}"
         + (f" ({contract['setupType']})" if contract['verdict'] == 'setup' else "")
         + f"**  confidence {contract['confidence']:.2f} · trend {contract['trend']}"
         + f" · grounded {'yes' if grounding.get('passed') else 'no'}"]
    if contract.get("entry"):
        e, s = contract["entry"], contract["stop"]
        L.append(f"Entry {e['price']:.2f} ({e['basis']}{', needs confirmation' if e['requiresConfirmation'] else ''})"
                 f" · Stop {s['price']:.2f} ({s['kind']}) · R:R {contract['riskReward']:.2f}")
        L.append("Targets: " + ", ".join(f"{t['price']:.2f} ({t['trimPct']:.0f}%)" for t in contract["targets"])
                 + f" · runner {contract['runnerPct']:.0f}%")
    if contract.get("levels"):
        L.append("Levels: " + "; ".join(f"{lv['price']:.2f} {lv['kind']} ×{lv['touches']}"
                                        for lv in contract["levels"][:6]))
    L.append("Volume: " + contract.get("volumeVerdict", ""))
    if contract.get("noTradeReasons"):
        L.append("No-trade reasons:\n- " + "\n- ".join(contract["noTradeReasons"]))
    if options:
        if options.get("available") and options.get("symbol"):
            L.append(f"Option: {options['symbol']} {options['optionType']} {options['strike']} exp {options['expiry']}"
                     f" bid/ask {options['bid']}/{options['ask']} delta {options.get('delta')} IV {options.get('iv')}"
                     + (" · " + "; ".join(options.get("warnings", [])) if options.get("warnings") else ""))
        elif options.get("error"):
            L.append(f"Options: {options['error']}")
    L.append("Rules: " + ", ".join(contract.get("rulesFired", [])))
    L.append(contract.get("rationale", ""))
    return "\n".join(L)


async def attach_technique_layer(engine) -> None:
    with __import__("contextlib").suppress(Exception):
        history_mod.set_concurrency(int(engine.settings.get("technique.history.concurrency", 6)))
        history_mod.set_alpaca_credentials(engine.config.alpaca_key_id, engine.config.alpaca_secret)
    """Create and wire TechniqueService + ChatService onto the engine."""
    from .chat import ChatService
    svc = TechniqueService(engine)
    chat = ChatService(engine, svc)
    svc.chat = chat
    engine.technique = svc
    if getattr(engine, "techniques", None) is None:
        engine.techniques = {}
    engine.techniques["enhanced_market"] = engine.technique   # service registry (phase 3): /api/techniques/{id}
    if getattr(engine, "plan_runners", None) is None:
        engine.plan_runners = {}
    engine.plan_runners["enhanced_market"] = svc.armer        # the /api/technique/armed hub aggregates these
    engine.chat = chat
    svc.start()
