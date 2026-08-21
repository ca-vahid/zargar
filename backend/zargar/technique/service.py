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
import datetime as dt
import logging
import math
import time

from sqlalchemy import func, select

from .. import bus as topics
from .. import events as ev
from ..domain import new_id
from ..models import Proposal, TechniqueRun, TechniqueSetup
from .analysis import WINDOW_FOR_TF, AnalysisRequest, compute_facts, gather_bars
from .backtest import run_backtest
from .llm import LLMConfig, config_from_settings, make_client
from .options import CboeClient, TradierClient, pick_for_setup
from .render import render_chart
from .rulebook import RULES, Thresholds, thresholds_from_settings
from .vision import VisionPipeline, transcript_messages

log = logging.getLogger("zargar.technique")

RTH_START = dt.time(9, 30)
RTH_END = dt.time(16, 0)


def run_dict(r: TechniqueRun) -> dict:
    return {
        "id": r.id, "threadId": r.thread_id, "symbol": r.symbol, "asOf": r.as_of,
        "primaryTf": r.primary_tf, "mode": r.mode, "trigger": r.trigger, "status": r.status,
        "verdict": r.verdict, "setupType": r.setup_type, "confidence": r.confidence,
        "grounded": r.grounded, "facts": r.facts or {}, "result": r.result or {},
        "images": r.images or {}, "usage": r.usage or {}, "error": r.error, "llm": r.llm or {},
        "createdAt": r.created_at.isoformat() if r.created_at else None,
        "finishedAt": r.finished_at.isoformat() if r.finished_at else None,
    }


def run_summary(r: TechniqueRun) -> dict:
    d = run_dict(r)
    d.pop("facts", None)
    res = d.pop("result", None) or {}
    d["analysis"] = res.get("analysis")
    d["groundingPassed"] = (res.get("grounding") or {}).get("passed")
    return d


def setup_dict(s: TechniqueSetup) -> dict:
    return {
        "id": s.id, "runId": s.run_id, "symbol": s.symbol, "setupType": s.setup_type,
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
        self._running: dict[str, asyncio.Task] = {}
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
        (Tradier's developer signup needs a US address). `technique.options.provider`
        can force tradier for anyone who does have a token."""
        pref = str(self.engine.settings.get("technique.options.provider", "cboe"))
        if pref == "tradier":
            t = self.tradier()
            if t is not None:
                return t
        if self._cboe is None:
            self._cboe = CboeClient()
        return self._cboe

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
            "rules": RULES,
        }

    # ------------------------------------------------------------ queries
    async def runs_today(self) -> int:
        start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.engine.sf() as session:
            n = (await session.execute(select(func.count()).select_from(TechniqueRun)
                                       .where(TechniqueRun.created_at >= start))).scalar()
        return int(n or 0)

    async def list_runs(self, *, limit: int = 50, symbol: str | None = None,
                        verdict: str | None = None) -> list[dict]:
        async with self.engine.sf() as session:
            stmt = select(TechniqueRun).order_by(TechniqueRun.created_at.desc()).limit(limit)
            if symbol:
                stmt = stmt.where(TechniqueRun.symbol == symbol.upper())
            if verdict:
                stmt = stmt.where(TechniqueRun.verdict == verdict)
            rows = (await session.execute(stmt)).scalars().all()
        return [run_summary(r) for r in rows]

    async def get_run(self, run_id: str) -> dict | None:
        async with self.engine.sf() as session:
            r = await session.get(TechniqueRun, run_id)
            if r is None:
                return None
            setups = (await session.execute(
                select(TechniqueSetup).where(TechniqueSetup.run_id == run_id))).scalars().all()
        d = run_dict(r)
        d["setups"] = [setup_dict(s) for s in setups]
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
    async def analyze(self, symbol: str, *, as_of_ms: int | None = None, primary_tf: str | None = None,
                      trigger: str = "manual", image: bytes | None = None, note: str = "",
                      thread_id: str | None = None, wait: bool = False) -> dict:
        """Start a run. Returns the run row immediately (status=running) unless
        `wait=True`, in which case the finished run is returned."""
        cfg = self.llm_config()
        if not cfg.available:
            raise RuntimeError("ZARGAR_ANTHROPIC_API_KEY is not configured")
        if not bool(self.engine.settings.get("technique.enabled", True)):
            raise RuntimeError("technique.enabled is off")
        cap = int(self.engine.settings.get("technique.max_runs_per_day", 40))
        if trigger != "chat" and await self.runs_today() >= cap:
            raise RuntimeError(f"daily run cap reached ({cap}); raise technique.max_runs_per_day")

        symbol = (symbol or "").upper().strip()
        tf = primary_tf or str(self.engine.settings.get("technique.default_tf", "1m"))
        mode = "image_only" if (image is not None and not symbol) else "full"
        if not symbol and image is None:
            raise ValueError("symbol or image required")

        if thread_id is None:
            title = f"{symbol or 'chart'} analysis · {tf}" + (" · image" if image else "")
            thread = await self.chat.create_thread(title=title, kind="run", symbol=symbol or None)
            thread_id = thread["id"]

        run = TechniqueRun(id=new_id(), thread_id=thread_id, symbol=symbol or "IMAGE", as_of=as_of_ms,
                           primary_tf=tf, mode=mode, trigger=trigger, status="running",
                           llm={"model": cfg.model, "effort": cfg.effort,
                                "thinkingDisplay": cfg.thinking_display})
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
            "trigger": trigger, "threadId": thread_id, "llm": run.llm},
            aggregate_type="technique_run", aggregate_id=run.id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "run", "run": run_summary(run)})

        task = asyncio.create_task(self._execute(run.id, thread_id, symbol, tf, as_of_ms, mode,
                                                 image, note, trigger), name=f"technique-{run.id[:8]}")
        self._running[run.id] = task
        if wait:
            await task
            return await self.get_run(run.id) or rd
        return rd

    async def _execute(self, run_id: str, thread_id: str, symbol: str, tf: str, as_of_ms: int | None,
                       mode: str, image: bytes | None, note: str, trigger: str) -> None:
        cfg = self.llm_config()
        client = self._get_client()
        t = self.thresholds()
        chat = self.chat
        t0 = time.time()

        live = self._live.setdefault(run_id, {"passes": [], "grounding": None, "facts": None})

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
            chat.publish(thread_id, e, run_id=run_id)

        facts: dict = {}
        images_meta: dict = {}
        result = None
        try:
            max_passes = int(self.engine.settings.get("llm.max_passes", 6))
            vp = VisionPipeline(client, cfg, thresholds=t, max_passes=max_passes, on_event=on_event)
            if mode == "image_only":
                aid = await chat.store_asset(image, None, thread_id=thread_id, meta={"kind": "user_image"})
                images_meta["user"] = aid
                result = await vp.run_image_only(image, note=note, symbol_hint=symbol)
            else:
                req = AnalysisRequest(symbol=symbol, as_of_ms=as_of_ms, primary_tf=tf, thresholds=t)
                bars, notes = await gather_bars(req)
                facts = compute_facts(req, bars, notes)
                if not bars:
                    raise RuntimeError("no bars available for " + symbol + " — " + "; ".join(notes))
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
                await on_event({"type": "facts", "keyLevels": facts.get("keyLevels", [])[:8],
                                "volume": (facts.get("volume") or {}).get(facts.get("primaryTf")),
                                "trend": facts.get("trend")})
                result = await vp.run(facts, imgs, user_image=image, user_note=note)

                # annotated chart with the final plan (or the levels, if no setup)
                a = result.analysis
                ptf = facts.get("primaryTf") or tf
                setup_overlay = None
                if a and a.verdict == "setup" and a.entry and a.stop:
                    setup_overlay = {"entry": {"price": a.entry.price}, "stop": {"price": a.stop.price},
                                     "targets": [{"price": x.price} for x in a.targets]}
                lv_overlay = [{"price": lv.price, "kind": lv.kind, "touches": lv.touches,
                               "strong": lv.touches >= 3} for lv in (a.levels if a else [])][:8]
                if ptf in bars:
                    png = render_chart(bars[ptf][-WINDOW_FOR_TF.get(ptf, 150):],
                                       title=f"{symbol} {ptf} — {a.verdict if a else 'n/a'}", tf=ptf,
                                       levels=lv_overlay, setup=setup_overlay,
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
            if a and a.verdict == "setup" and bool(self.engine.settings.get("technique.options.enabled", True)):
                options = await self.option_pick(symbol, a.direction or "long",
                                                 spot=float(facts.get("lastClose") or 0) or None)

            usage = dict(result.total_usage)
            res_d = result.to_dict()
            res_d["options"] = options
            res_d["seconds"] = round(time.time() - t0, 1)
            async with self.engine.sf() as session:
                r = await session.get(TechniqueRun, run_id)
                r.status = "done"
                r.verdict = a.verdict if a else None
                r.setup_type = a.setup_type if a else None
                r.confidence = a.confidence if a else None
                r.grounded = bool(result.grounding.get("passed")) if result.mode == "full" else None
                r.facts = _slim_facts(facts)
                r.result = res_d
                r.images = images_meta
                r.usage = usage
                r.error = result.error
                r.finished_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
                rd = run_dict(r)

            # ---- setups --------------------------------------------------------------
            if a is not None:
                await self._persist_setup(run_id, symbol or a.symbol, a, contract, options,
                                          grounded=bool(result.grounding.get("passed")))

            await self.engine.journal.append(ev.TECHNIQUE_RUN_COMPLETED, {
                "runId": run_id, "symbol": symbol, "verdict": rd["verdict"], "setupType": rd["setupType"],
                "confidence": rd["confidence"], "grounded": rd["grounded"], "usage": usage,
                "seconds": res_d["seconds"], "rulesFired": (contract or {}).get("rulesFired", []),
                "noTradeReasons": (contract or {}).get("noTradeReasons", [])},
                aggregate_type="technique_run", aggregate_id=run_id)
            if result.mode == "full" and not result.grounding.get("passed"):
                await self.engine.journal.append(ev.TECHNIQUE_GROUNDING_FAILED, {
                    "runId": run_id, "checks": [c for c in result.grounding.get("checks", [])
                                               if not c.get("passed")]},
                    aggregate_type="technique_run", aggregate_id=run_id)
            summary_text = _summary_text(contract, result.grounding, options)
            await chat.append_message(thread_id, "assistant", [{"type": "text", "text": summary_text}],
                                      {"kind": "run_summary", "runId": run_id,
                                       "annotatedAssetId": images_meta.get("annotated")},
                                      run_id=run_id)
            chat.publish(thread_id, {"type": "run_done", "run": run_summary_from_dict(rd)}, run_id=run_id)
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "run_done", "run": run_summary_from_dict(rd)})
        except asyncio.CancelledError:
            await self._fail(run_id, thread_id, "cancelled")
            raise
        except Exception as exc:
            log.exception("technique run failed")
            await self._fail(run_id, thread_id, f"{type(exc).__name__}: {exc}")
        finally:
            self._running.pop(run_id, None)
            self._live.pop(run_id, None)

    async def _fail(self, run_id: str, thread_id: str, error: str) -> None:
        async with self.engine.sf() as session:
            r = await session.get(TechniqueRun, run_id)
            if r is not None:
                r.status = "failed"
                r.error = error
                r.finished_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
                rd = run_dict(r)
            else:
                rd = {"id": run_id, "status": "failed", "error": error}
        await self.engine.journal.append(ev.TECHNIQUE_RUN_FAILED, {"runId": run_id, "error": error},
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
                             *, grounded: bool) -> None:
        e, s = a.entry, a.stop
        valid = a.verdict == "setup" and e is not None and s is not None and grounded \
            and not [r for r in a.no_trade_reasons if not r.startswith("CRITIC-WARN")]
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
        if valid and bool(self.engine.settings.get("technique.emit_proposals", False)):
            with contextlib.suppress(Exception):
                await self._emit_proposal(row, a)

    async def _emit_proposal(self, setup: TechniqueSetup, a) -> None:
        """Practice-only: a proposal the user approves in the Signals page; approval
        routes through OrderManager → RiskGate like every other order."""
        eng = self.engine
        pid = str(eng.settings.get("trading.default_portfolio", ""))
        if not pid or eng.positions.portfolio(pid) is None:
            sims = [p for p in eng.positions.portfolios() if p["kind"] == "sim"]
            if not sims:
                return
            pid = sims[0]["id"]
        equity = await eng.positions.equity(pid)
        risk_pct = float(eng.settings.get("technique.default_risk_pct", 1.0))
        risk_pct = min(risk_pct, float(eng.settings.get("technique.max_risk_pct", 5.0)))
        per_share = max(setup.entry - setup.stop, 0.01)
        qty = max(1, math.floor(equity * risk_pct / 100 / per_share))
        ttl = int(eng.settings.get("signals.default_ttl_minutes", 30))
        row = Proposal(
            id=new_id(), signal_id=None, portfolio_id=pid, symbol=setup.symbol, side="BUY",
            qty=float(qty), order_type="LMT", limit_price=round(setup.entry, 2),
            bracket={"take_profit": (setup.targets[0]["price"] if setup.targets else None),
                     "stop_loss": setup.stop, "take_profit_pct": None, "stop_loss_pct": None},
            rationale=a.rationale[:500],
            context={"sourceName": "technique", "confidence": a.confidence,
                     "technique": {"setupId": setup.id, "runId": setup.run_id,
                                   "setupType": setup.setup_type, "rules": setup.rules},
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

    # ------------------------------------------------------------ options
    async def option_pick(self, symbol: str, direction: str = "long", *, spot: float | None = None) -> dict:
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
        out = await pick_for_setup(client, symbol, spot, direction)
        out["spot"] = spot
        return out

    # ------------------------------------------------------------ backtest
    async def backtest(self, symbol: str, tf: str = "5m", *, days: int = 10, start_ms: int | None = None,
                       end_ms: int | None = None, horizon_bars: int = 60, step_bars: int = 5) -> dict:
        end_ms = end_ms or int(time.time() * 1000)
        start_ms = start_ms or end_ms - days * 86400 * 1000
        return await run_backtest(symbol, tf, start_ms, end_ms, horizon_bars=horizon_bars,
                                  step_bars=step_bars, thresholds=self.thresholds())

    # ------------------------------------------------------------ scans
    def start(self) -> None:
        if self._scan_task is None:
            self._scan_task = asyncio.create_task(self._scan_loop(), name="technique-scan")

    async def stop(self) -> None:
        for t in list(self._running.values()):
            t.cancel()
        if self._scan_task:
            self._scan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scan_task
            self._scan_task = None
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

    async def _scan_loop(self) -> None:
        while True:
            try:
                interval = max(5, int(self.engine.settings.get("technique.scan.interval_minutes", 30)))
                if bool(self.engine.settings.get("technique.scan.enabled", False)):
                    if not bool(self.engine.settings.get("technique.scan.rth_only", True)) or self._in_rth():
                        await self.scan_once()
                await asyncio.sleep(interval * 60)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("scan loop error")
                await asyncio.sleep(60)


# --- helpers --------------------------------------------------------------------

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
    res = d.pop("result", None) or {}
    d["analysis"] = res.get("analysis")
    d["groundingPassed"] = (res.get("grounding") or {}).get("passed")
    d["options"] = res.get("options")
    d["seconds"] = res.get("seconds")
    return d


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
    """Create and wire TechniqueService + ChatService onto the engine."""
    from .chat import ChatService
    svc = TechniqueService(engine)
    chat = ChatService(engine, svc)
    svc.chat = chat
    engine.technique = svc
    engine.chat = chat
    svc.start()
