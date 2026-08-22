"""Phase 2 — arm a session plan for live triggers (walk-forward plan §9).

The book's "set alerts above and below key levels" (p. 117), done by the
machine: an armed plan's triggers are evaluated on every closed 1m bar from the
quote bus with the very same `TriggerTracker` the walk-forward uses. A trigger
fires only inside the R6 prime windows; mid-day touches are logged as observed
(data for the R6 claim), not acted on. On fire: the deterministic checks have
passed by construction, the vision critic optionally reviews the live chart,
and the setup follows the existing practice-proposal -> approval -> RiskGate
path. **No new order path.** Every arm / fire / skip / void is journaled
against the plan run, so the evening review is plan-vs-reality.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time
from dataclasses import dataclass, field

from .. import bus as topics
from .. import events as ev
from ..domain import Bar
from .analysis import facts_for_prompt
from .plans import analysis_from_trigger
from .rulebook import ET, session_bounds, session_date, session_window
from .volume import build_profile
from .walkforward import TriggerTracker

log = logging.getLogger("zargar.technique.arming")


@dataclass
class ArmedPlan:
    run_id: str
    symbol: str
    plan: dict
    plan_for: str
    trackers: dict[str, TriggerTracker]
    armed_at: float
    bar_index: int = 0
    last_bar_ts: int | None = None
    fired: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    expired: bool = False
    setup_ids: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "runId": self.run_id, "symbol": self.symbol, "planFor": self.plan_for,
            "armedAt": dt.datetime.fromtimestamp(self.armed_at, dt.timezone.utc).isoformat(),
            "barsSeen": self.bar_index, "lastBarTs": self.last_bar_ts, "expired": self.expired,
            "triggers": [{"id": tid, "kind": tr.kind, "status": tr.status, "entry": tr.entry, "stop": tr.stop,
                          "firedTs": tr.fired_ts, "firedWindow": tr.fired_window,
                          "observedMidday": len(tr.observed_midday), "skipped": tr.skipped[-3:],
                          "setupId": self.setup_ids.get(tid)}
                         for tid, tr in self.trackers.items()],
            "fired": self.fired, "events": self.events[-20:],
        }


class PlanArmer:
    def __init__(self, engine, technique) -> None:
        self.engine = engine
        self.technique = technique
        self._armed: dict[str, ArmedPlan] = {}
        self._task: asyncio.Task | None = None
        self._auto_task: asyncio.Task | None = None
        self._auto_done: set[tuple[str, str]] = set()   # (symbol, session) already auto-armed

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._bar_loop(), name="technique-armer")
        if self._auto_task is None:
            self._auto_task = asyncio.create_task(self._auto_loop(), name="technique-armer-auto")

    async def stop(self) -> None:
        for name in ("_task", "_auto_task"):
            t = getattr(self, name)
            if t:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
                setattr(self, name, None)

    def armed(self) -> list[dict]:
        return [a.to_dict() for a in self._armed.values()]

    def get(self, run_id: str) -> ArmedPlan | None:
        return self._armed.get(run_id)

    # ---------------------------------------------------------------- arm / disarm
    async def arm(self, run_id: str) -> dict:
        if not bool(self.engine.settings.get("technique.arm.enabled", True)):
            raise RuntimeError("technique.arm.enabled is off")
        if run_id in self._armed:
            return self._armed[run_id].to_dict()
        run = await self.technique.get_run(run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        plan = (run.get("result") or {}).get("plan")
        if run.get("mode") != "plan" or not plan:
            raise ValueError("only plan runs (mode=plan) can be armed")
        symbol = run["symbol"]
        enforce = bool(self.engine.settings.get("technique.enforce_session_windows", True))
        t = self.technique.thresholds()
        # volume baseline from the plan's own bar snapshot (prior sessions of the trigger tf)
        profile = None
        with contextlib.suppress(Exception):
            snap = await self.technique.load_bars_snapshot(run_id)
            if snap and snap.get(plan.get("triggerTf") or "1m"):
                profile = build_profile(snap[plan.get("triggerTf") or "1m"])
        trackers = {tg["id"]: TriggerTracker(tg, t, profile, enforce, True, float(plan.get("lastClose") or 0) or None)
                    for tg in plan.get("triggers") or [] if tg.get("valid")}
        ap = ArmedPlan(run_id=run_id, symbol=symbol, plan=plan, plan_for=plan.get("planFor") or "",
                       trackers=trackers, armed_at=time.time())
        self._armed[run_id] = ap
        # make sure quotes flow, then seed with today's bars so far (a plan armed at 10:05 still knows about 9:31)
        with contextlib.suppress(Exception):
            await self.engine.ensure_symbol(symbol)
        seeded = 0
        try:
            todays = [b for b in self.engine.bars.bars(symbol, "1m", limit=2000, include_forming=False)
                      if session_date(b.ts) == ap.plan_for]
            for b in todays:
                await self._on_bar(ap, b, journal=False)
                seeded += 1
        except Exception:
            log.exception("seeding armed plan failed")
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ARMED, {
            "runId": run_id, "symbol": symbol, "planFor": ap.plan_for, "triggers": list(trackers),
            "seededBars": seeded, "enforceWindows": enforce},
            aggregate_type="technique_run", aggregate_id=run_id)
        self.start()
        self._publish(ap, "armed")
        return ap.to_dict()

    async def disarm(self, run_id: str, *, reason: str = "manual") -> bool:
        ap = self._armed.pop(run_id, None)
        if ap is None:
            return False
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_DISARMED, {
            "runId": run_id, "symbol": ap.symbol, "reason": reason, "fired": len(ap.fired),
            "statuses": {tid: tr.status for tid, tr in ap.trackers.items()}},
            aggregate_type="technique_run", aggregate_id=run_id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "disarmed", "runId": run_id, "reason": reason})
        return True

    async def arm_today(self, symbol: str, *, with_vision: bool | None = None) -> dict:
        """Build today's plan (as of just before the open, i.e. from yesterday's
        close) and arm it. Works before or during the session."""
        today = session_date(int(time.time() * 1000))
        open_ms, _ = session_bounds(today)
        run = await self.technique.analyze(symbol, as_of_ms=open_ms - 1000, trigger="arm", plan=True,
                                           with_vision=with_vision, wait=True)
        if run.get("status") != "done":
            raise RuntimeError(f"plan build failed: {run.get('error')}")
        return await self.arm(run["id"])

    # ---------------------------------------------------------------- bar handling
    async def _bar_loop(self) -> None:
        async with self.engine.bus.subscription(topics.BARS) as q:
            while True:
                msg = await q.get()
                try:
                    if msg.get("tf") != "1m":
                        continue
                    bar: Bar = msg.get("bar")
                    sym = msg.get("symbol")
                    for ap in [a for a in self._armed.values() if a.symbol == sym and not a.expired]:
                        await self._on_bar(ap, bar, journal=True)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("armed plan bar handling failed")

    async def on_bar(self, run_id: str, bar: Bar) -> dict | None:
        """Feed one closed bar by hand (tests / replays)."""
        ap = self._armed.get(run_id)
        if ap is None:
            return None
        await self._on_bar(ap, bar, journal=True)
        return ap.to_dict()

    async def _on_bar(self, ap: ArmedPlan, bar: Bar, *, journal: bool) -> None:
        if session_date(bar.ts) != ap.plan_for:
            return
        if ap.last_bar_ts is not None and bar.ts <= ap.last_bar_ts:
            return
        ap.last_bar_ts = bar.ts
        idx = ap.bar_index
        ap.bar_index += 1
        _, close_ms = session_bounds(ap.plan_for)
        for tid, tr in ap.trackers.items():
            if tr.status in ("fired", "gapped_past", "gapped_through", "gap_void", "expired"):
                continue
            before = tr.status
            n_obs, n_skip = len(tr.observed_midday), len(tr.skipped)
            st = tr.on_bar(bar, idx)
            if st != before or len(tr.observed_midday) != n_obs or len(tr.skipped) != n_skip:
                what = st if st != before else ("observed_midday" if len(tr.observed_midday) != n_obs else "skipped")
                rec = {"ts": bar.ts, "trigger": tid, "event": what, "window": session_window(bar.ts),
                       "close": bar.close}
                ap.events.append(rec)
                if journal and what != "fired":
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                        "runId": ap.run_id, "symbol": ap.symbol, **rec,
                        "reason": (tr.skipped[-1]["reason"] if what == "skipped" and tr.skipped else what)},
                        aggregate_type="technique_run", aggregate_id=ap.run_id)
                    self._publish(ap, what)
            if st == "fired" and before != "fired":
                await self._fire(ap, tid, tr, bar, journal=journal)
        if bar.ts >= close_ms - 60_000:
            ap.expired = True
            for tr in ap.trackers.values():
                tr.finish()
            if journal:
                await self.disarm(ap.run_id, reason="session closed")

    async def _fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, bar: Bar, *, journal: bool) -> None:
        window = session_window(bar.ts)
        a = analysis_from_trigger(tr.trigger, ap.symbol, session_window=window)
        critic = None
        use_critic = bool(self.engine.settings.get("technique.arm.use_critic", True))
        cfg = self.technique.llm_config()
        trace: list[dict] = []
        if use_critic and cfg.available and journal:
            try:
                from .analysis import AnalysisRequest, compute_facts
                from .render import render_chart
                from .vision import VisionPipeline
                bars = self.engine.bars.bars(ap.symbol, "1m", limit=600, include_forming=False)
                req = AnalysisRequest(symbol=ap.symbol, primary_tf="1m", context_tfs=(),
                                      thresholds=self.technique.thresholds())
                facts = compute_facts(req, {"1m": bars}, []) if bars else {}
                png = render_chart(bars[-240:], title=f"{ap.symbol} 1m", tf="1m") if bars else None
                vp = VisionPipeline(self.technique._get_client(), cfg, thresholds=self.technique.thresholds(),
                                    max_passes=2, trace=trace)
                critic = await vp.run_critic(a, {"1m": png} if png else {}, facts_for_prompt(facts) if facts else "")
            except Exception as exc:
                log.warning("live critic failed: %s", exc)
                trace.append({"stage": "critic", "step": "error", "reason": str(exc)})
        contract = a.to_contract()
        setup_id = None
        if journal:
            try:
                await self.technique._persist_setup(ap.run_id, ap.symbol, a, contract, None, grounded=True)
                # find the setup row just written
                setups = (await self.technique.get_run(ap.run_id) or {}).get("setups") or []
                if setups:
                    setup_id = setups[-1]["id"]
                    ap.setup_ids[tid] = setup_id
            except Exception:
                log.exception("persisting fired setup failed")
        rec = {"ts": bar.ts, "trigger": tid, "kind": tr.kind, "window": window, "fill": tr.fill_price,
               "entry": tr.entry, "stop": tr.stop, "verdictAfterCritic": a.verdict,
               "confidence": round(a.confidence, 3), "critic": critic and {k: critic.get(k) for k in ("kill", "summary", "violations")},
               "setupId": setup_id}
        ap.fired.append(rec)
        ap.events.append({"ts": bar.ts, "trigger": tid, "event": "fired", "window": window, "close": bar.close})
        if journal:
            await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_FIRED, {
                "runId": ap.run_id, "symbol": ap.symbol, **rec, "trace": trace},
                aggregate_type="technique_run", aggregate_id=ap.run_id)
            if self.technique.chat and ap.plan.get("symbol"):
                run = await self.technique.get_run(ap.run_id)
                if run and run.get("threadId"):
                    with contextlib.suppress(Exception):
                        await self.technique.chat.append_message(
                            run["threadId"], "assistant",
                            [{"type": "text", "text": (
                                f"**Trigger {tid} fired** at {dt.datetime.fromtimestamp(bar.ts / 1000, ET):%H:%M} ET "
                                f"({window}) — {tr.kind} at {tr.fill_price:.2f}, stop {tr.stop:.2f}"
                                + (f"; critic: {'KILLED' if a.verdict != 'setup' else 'survived'} — {critic.get('summary')}"
                                   if critic else "") + (f"; setup {setup_id}" if setup_id else ""))}],
                            {"kind": "plan_trigger", "runId": ap.run_id, "trigger": tid}, run_id=ap.run_id)
            self._publish(ap, "fired")

    def _publish(self, ap: ArmedPlan, what: str) -> None:
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "armed", "event": what, "armed": ap.to_dict()})

    # ---------------------------------------------------------------- auto-arm
    async def _auto_loop(self) -> None:
        await asyncio.sleep(30)
        while True:
            try:
                syms = [str(s).upper() for s in self.engine.settings.get("technique.arm.auto_symbols", [])]
                if syms and bool(self.engine.settings.get("technique.arm.enabled", True)):
                    now = dt.datetime.now(ET)
                    today = now.strftime("%Y-%m-%d")
                    if now.weekday() < 5 and (9 * 60 + 20) <= now.hour * 60 + now.minute < 16 * 60:
                        for s in syms:
                            if (s, today) in self._auto_done or any(a.symbol == s and a.plan_for == today
                                                                    for a in self._armed.values()):
                                continue
                            self._auto_done.add((s, today))
                            try:
                                await self.arm_today(s)
                            except Exception as exc:
                                log.warning("auto-arm %s failed: %s", s, exc)
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("auto-arm loop error")
                await asyncio.sleep(60)
