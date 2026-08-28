"""EnhancedMarket's live arming — `PlanArmer`, the EM subclass of the shared
`execution.planrunner.PlanRunner` (platform plan phase 2, 2026-08-27).

Everything that moves money lives in the runner. This file holds the book's
opinions only: which rules the trackers read (R6 windows, gap policy, volume
floor …), the fire-time analysis + vision critic, the setup row and proposal,
the just-OTM weekly / 0DTE contract pick (T5), Friday / 0DTE sizing (T5.2), the
09:25 pre-open judgement with re-plan (Q5), and building today's plan on demand.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time

from .. import bus as topics
from .. import events as ev
from ..domain import Bar
from ..execution.planrunner import (  # noqa: F401 — re-exported for existing importers
    MODES, TRANSIENT_ERRORS, ArmConfig, ArmedPlan, FireJudgement, PlanRunner, Trade, _et_day_start_ms,
)
from ..marketstructure.tracker import TriggerTracker
from ..models import TechniqueSetup
from .analysis import facts_for_prompt
from .plans import analysis_from_trigger
from .rulebook import ET, session_bounds, session_date, session_window

log = logging.getLogger("zargar.technique.arming")

TECHNIQUE_ID = "enhanced_market"   # registry id (zargar.techniques) stamped on plans and order intents


class PlanArmer(PlanRunner):
    """Arms EnhancedMarket session plans on the shared runner. The live loops,
    persistence, fire chain, entry/exit management, loss halt, watchdogs and
    alerts are the runner's; this class supplies the technique's hooks."""

    def __init__(self, engine, technique) -> None:
        super().__init__(engine, name="technique-armer")
        self.technique = technique

    # ================================================================ hooks — the EM opinions
    TECHNIQUE_ID = TECHNIQUE_ID

    def rules(self):
        return self.technique.thresholds()

    async def load_plan(self, run_id: str) -> dict | None:
        return await self.technique.get_run(run_id)

    async def load_baseline_bars(self, run_id: str, tf: str) -> list:
        snap = await self.technique.load_bars_snapshot(run_id)
        return list(snap.get(tf) or []) if snap else []

    def entry_windows_enforced(self) -> bool:
        # R6.3 experiment (technique.arm.midday_trading): fires allowed outside the
        # prime windows — LIVE ARMER ONLY. Sweeps/backtests/plans build their own
        # trackers and never read this, so the deterministic record stays R6-true
        # and the execution scorecard's live-vs-replay diff becomes the experiment's
        # own counterfactual.
        s_ = self.engine.settings
        return (bool(s_.get("technique.enforce_session_windows", True))
                and not bool(s_.get("technique.arm.midday_trading", False)))

    async def pick_contract(self, ap: ArmedPlan, trade: Trade) -> dict | None:
        return await self._pick_contract(ap, trade)

    def size_multiplier(self, contract: dict) -> tuple[float, list[str]]:
        """Fridays are scaled by `technique.arm.friday_size_mult`, 0DTE by a further
        half (T5.2 "reduced size")."""
        s = self.engine.settings
        mult, why = 1.0, []
        if dt.datetime.now(ET).weekday() == 4:
            fm = float(s.get("technique.arm.friday_size_mult", 0.5) or 1.0)
            mult *= fm
            why.append(f"Friday x{fm:g}")
        if contract.get("is0dte"):
            mult *= 0.5
            why.append("0DTE x0.5 (T5.2)")
        return mult, why

    def preopen_due(self, now: dt.datetime) -> bool:
        return self._preopen_window(now)


    async def analyze_fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, trade: Trade) -> FireJudgement:
        """The deterministic read of the trigger that fired (T-rules, no model)."""
        a = analysis_from_trigger(tr.trigger, ap.symbol, session_window=trade.window)
        return FireJudgement(verdict=a.verdict, confidence=float(a.confidence), extra=a)

    def reviewer_available(self) -> bool:
        return bool(self.technique.llm_config().available)

    async def review_fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, trade: Trade,
                          judgement: FireJudgement) -> tuple[str, float, dict | None]:
        """The vision critic: prompt assembly (live context incl. gap_unchecked and the
        mid-day experiment, plan provenance, data-quality guidance) and the verdict.
        Timeout, fail-open budget, cooldown, kill cap and re-arming are the runner's."""
        a, window, cfg = judgement.extra, trade.window, ap.config
        llm = self.technique.llm_config()
        from dataclasses import replace as dc_replace

        from .analysis import AnalysisRequest, compute_facts
        from .render import render_chart
        from .vision import VisionPipeline
        # fire-time reads don't need deep thinking — latency IS cost here
        eff = str(self.engine.settings.get("technique.arm.critic_effort", "low") or "low")
        if eff and eff != llm.effort:
            llm = dc_replace(llm, effort=eff)
        bars = self.engine.bars.bars(ap.symbol, "1m", limit=600, include_forming=False)
        if ap.baseline_bars and bars:
            # prepend the plan snapshot's prior sessions so the live FACTS
            # have a volume baseline (else rel volume reads 0.0x/unmeasurable)
            pre = [b for b in ap.baseline_bars if b.ts < bars[0].ts]
            bars = pre[-1500:] + bars
        req = AnalysisRequest(symbol=ap.symbol, primary_tf="1m", context_tfs=(), thresholds=self.technique.thresholds())
        facts = compute_facts(req, {"1m": bars}, []) if bars else {}
        png = render_chart(bars[-240:], title=f"{ap.symbol} 1m", tf="1m") if bars else None
        vp = VisionPipeline(self.technique._get_client(), llm, thresholds=self.technique.thresholds(),
                            max_passes=2, trace=judgement.trace)
        # give the critic the whole live picture, not just the draft: which
        # R6 window we are in, the plan's other triggers, and — for options —
        # the contract it would buy (spread / IV / delta warnings)
        live_ctx = [f"LIVE CONTEXT — trigger {tid} fired at {trade.entry:.2f} in the {window} window."]
        if window == "midday" and bool(self.engine.settings.get("technique.arm.midday_trading", False)):
            live_ctx.append(
                "MID-DAY EXPERIMENT: R6.3's no-midday rule is DELIBERATELY suspended for this fire "
                "(controlled data collection on whether the rule earns its keep). The session window "
                "is NOT a kill reason here — judge the setup purely on the tape and the plan.")
        if tr.gap_unchecked:
            live_ctx.append(
                "LATE START: the plan was armed after the open and the overnight gap rules "
                "(gapped past / through / gap void) were NOT evaluated — judge the level against the "
                "tape since the open, and treat an open far beyond the level as a chase (T4.1).")
        if tr.kind in ("reject", "breakdown"):
            live_ctx.append(
                "DIRECTION: this is a SHORT-side trigger (rejection at resistance / breakdown), a "
                "planned part of the method expressed via PUTS (technique.long_only is OFF — the "
                "2026-08-26 decision plans both sides). Being short is NEVER a kill reason; judge "
                "the level, volume and tape exactly as you would the long mirror.")
        others = [f"{t2}: {trk.kind} @ {trk.entry:.2f} ({trk.status})"
                  for t2, trk in ap.trackers.items() if t2 != tid]
        if others:
            live_ctx.append("Other triggers in this plan: " + "; ".join(others) + ".")
        if cfg.instrument == "options" and trade.contract:
            c = trade.contract
            live_ctx.append(
                f"Contract to buy (T5): {c.get('display') or c.get('symbol')} — bid/ask "
                f"{c.get('bid')}/{c.get('ask')}, IV {c.get('iv')}, delta {c.get('delta')}, "
                f"DTE {c.get('dte')}."
                + (" WARNINGS: " + "; ".join(c.get("warnings") or []) if c.get("warnings") else ""))
        # The critic must know where the level CAME FROM — a ZS fire was
        # killed as "level does not exist in FACTS" because today's live
        # window (post-gap) no longer re-detects Monday's zone floor.
        tg0 = next((t for t in (ap.plan.get("triggers") or []) if t.get("id") == tid), None)
        if tg0:
            lv0 = tg0.get("level") or {}
            z0 = lv0.get("zone") or {}
            a0 = tg0.get("assessment") or {}
            live_ctx.append(
                f"PLAN PROVENANCE: trigger {tid} comes from the session plan built at the "
                f"{ap.plan.get('builtFromSession')} close. Level {tg0.get('levelPrice')}: "
                f"{lv0.get('touches')} touch(es), sources {','.join(lv0.get('sources') or []) or '?'}"
                + (f", zone {z0.get('low')}-{z0.get('high')}" if z0 else "")
                + (f", deterministic grade {a0.get('grade')} ({a0.get('score')}/100)" if a0.get("grade") else "")
                + ". Plan levels are detected from the BUILD window; after an overnight gap they can be "
                  "absent from today's FACTS — that is expected, NOT fabrication. Judge the level by its "
                  "provenance plus today's tape, never by whether today's FACTS re-detect it.")
            if a0.get("cautions"):
                live_ctx.append("Plan cautions (already priced into the grade): " + "; ".join(a0["cautions"]))
        live_ctx.append(
            "DATA QUALITY: if FACTS volume is unmeasurable (relative 0.0x, baseline 0 sessions, or the "
            "current bar shows v=0), treat volume as UNKNOWN — a data-feed outage, not a rule violation; "
            "do not kill on R3.1/T2 grounds alone in that case.")
        facts_ctx = (facts_for_prompt(facts) + "\n\n" + "\n".join(live_ctx)) if facts else "\n".join(live_ctx)
        critic = await vp.run_critic(a, {"1m": png} if png else {}, facts_ctx)
        return a.verdict, float(a.confidence), critic

    async def record_fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, trade: Trade,
                          judgement: FireJudgement) -> None:
        """The setup row (always, so the run shows what fired)."""
        a = judgement.extra
        judgement.contract = a.to_contract()          # after the reviewer: the verdict is final here
        await self.technique._persist_setup(ap.run_id, ap.symbol, a, judgement.contract, None, grounded=True)
        setups = (await self.technique.get_run(ap.run_id) or {}).get("setups") or []
        if setups:
            trade.setup_id = setups[-1]["id"]
            ap.setup_ids[tid] = trade.setup_id

    async def emit_proposal(self, ap: ArmedPlan, trade: Trade, judgement: FireJudgement,
                            contract: dict | None, *, contracts: int | None) -> str | None:
        cfg = ap.config
        setup_row = await self._setup_row(trade.setup_id)
        if setup_row is None:
            return None
        return await self.technique._emit_proposal(
            setup_row, judgement.extra, portfolio_id=cfg.portfolio_id, risk_pct=cfg.risk_pct, max_qty=cfg.max_qty,
            fixed_qty=cfg.qty, contract=contract, managed=True, contracts=contracts)

    async def after_fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, trade: Trade,
                         judgement: FireJudgement, bar: Bar) -> None:
        a, critic, window, cfg = judgement.extra, judgement.critic, trade.window, ap.config
        if self.technique.chat:
            run = await self.technique.get_run(ap.run_id)
            if run and run.get("threadId"):
                with contextlib.suppress(Exception):
                    await self.technique.chat.append_message(
                        run["threadId"], "assistant",
                        [{"type": "text", "text": (
                            f"**Trigger {tid} fired** at {dt.datetime.fromtimestamp(bar.ts / 1000, ET):%H:%M} ET "
                            f"({window}) — {tr.kind} at {trade.entry:.2f}, stop {tr.stop:.2f}; mode {cfg.mode}: {trade.status}"
                            + (f" — {trade.reason}" if trade.reason else "")
                            + (f"; critic: {'KILLED' if a.verdict != 'setup' else 'survived'} — {critic.get('summary')}"
                               if critic else ""))}],
                        {"kind": "plan_trigger", "runId": ap.run_id, "trigger": tid}, run_id=ap.run_id)


    async def arm_today(self, symbol: str, config: dict | None = None, *, with_vision: bool | None = None) -> dict:
        """Build today's plan (as of just before the open) and arm it."""
        today = session_date(int(time.time() * 1000))
        open_ms, _ = session_bounds(today)
        run = await self.technique.analyze(symbol, as_of_ms=open_ms - 1000, trigger="arm", plan=True,
                                           with_vision=with_vision, wait=True)
        if run.get("status") != "done":
            raise RuntimeError(f"plan build failed: {run.get('error')}")
        return await self.arm(run["id"], config)

    async def _setup_row(self, setup_id: str | None):
        if not setup_id:
            return None
        async with self.engine.sf() as session:
            return await session.get(TechniqueSetup, setup_id)

    async def _pick_contract(self, ap: ArmedPlan, trade: Trade) -> dict | None:
        """T5: the just-OTM call, current-week Friday / 0DTE, from the live chain."""
        s = self.engine.settings
        trade.contract_attempted = True
        max_strike = min_strike = None
        if bool(s.get("technique.arm.strike_within_targets", True)) and trade.targets:
            cap = float(trade.targets[1] if len(trade.targets) >= 2 else trade.targets[0])
            if trade.direction == "short":
                min_strike = cap                # a put struck below the downside target is worthless leverage
            else:
                max_strike = cap
        avoid_0dte = False
        cutoff = str(s.get("technique.arm.avoid_0dte_after", "15:15") or "")
        if cutoff:
            with contextlib.suppress(ValueError):
                hh, mm = (int(x) for x in cutoff.split(":"))
                now = dt.datetime.now(ET)
                avoid_0dte = (now.hour * 60 + now.minute) >= hh * 60 + mm
        try:
            pick = await self.technique.option_pick(ap.symbol, "short" if trade.direction == "short" else "long",
                                                    spot=float(trade.last_price or trade.entry),
                                                    max_strike=max_strike, min_strike=min_strike, avoid_0dte=avoid_0dte)
        except Exception as exc:
            trade.errors.append(f"option chain: {exc}")
            self._log(ap, "option_pick_failed", f"{trade.trigger_id}: option chain error {exc}", trigger=trade.trigger_id)
            return None
        if not pick or not pick.get("available") or not pick.get("symbol"):
            why = (pick or {}).get("error") or "no contract just OTM"
            trade.errors.append(f"option pick: {why}")
            self._log(ap, "option_pick_failed", f"{trade.trigger_id}: {why}", trigger=trade.trigger_id)
            return None
        trade.contract = {k: pick.get(k) for k in ("symbol", "display", "underlying", "expiry", "strike", "optionType",
                                                    "bid", "ask", "mid", "spreadPct", "delta", "theta", "iv", "dte",
                                                    "is0dte", "openInterest", "volume", "warnings", "provider")}
        trade.order_symbol = pick["symbol"]
        self._log(ap, "option_picked", f"{trade.trigger_id}: {pick.get('display') or pick['symbol']} "
                  f"bid/ask {pick.get('bid')}/{pick.get('ask')}" + (f"; warnings: {'; '.join(pick.get('warnings') or [])}"
                                                                    if pick.get("warnings") else ""),
                  trigger=trade.trigger_id, contract=trade.contract)
        with contextlib.suppress(Exception):
            if getattr(self.engine, "options", None) is not None:
                await self.engine.options.track(pick["symbol"])
        return trade.contract

    def _preopen_window(self, now: dt.datetime) -> bool:
        at = str(self.engine.settings.get("technique.arm.preopen_at", "09:25") or "09:25")
        try:
            hh, mm = (int(x) for x in at.split(":"))
        except ValueError:
            hh, mm = 9, 25
        m = now.hour * 60 + now.minute
        return hh * 60 + mm <= m < 9 * 60 + 30

    async def preopen_check(self, ap: ArmedPlan, premarket: float) -> dict | None:
        """Q5 (user decision 2026-08-26) — judge the plan against the pre-market print,
        without trading on it (R6.4/R6.5): which triggers the open would gap past /
        through / void, and whether EVERY valid trigger is already dead (then the
        runner asks for a replacement plan). Judgement only — the runner journals."""
        last = premarket
        prev = float(ap.plan.get("referencePrice") or ap.plan.get("lastClose") or 0)
        t = self.technique.thresholds()
        rows = []
        dead = 0
        alive = 0
        for tid, tr in ap.trackers.items():
            if tr.status not in ("waiting", "observed"):
                continue
            verdict = "ok"
            if tr.kind == "bounce":
                if last < tr.stop:
                    verdict = "gapped_through"
                elif last <= tr.entry:
                    verdict = "gapped_past"
            elif last > tr.entry:
                verdict = "gapped_past"
            if verdict == "ok" and prev and abs(last - prev) > t.gap_void_r * tr.risk:
                verdict = "gap_void"
            (dead := dead + 1) if verdict != "ok" else (alive := alive + 1)
            rows.append({"trigger": tid, "kind": tr.kind, "entry": tr.entry, "stop": tr.stop,
                         "verdict": verdict, "gapR": round(abs(last - prev) / tr.risk, 2) if prev else None})
        pct = ((last - prev) / prev * 100) if prev else 0.0
        replan = bool(rows) and alive == 0 and bool(self.engine.settings.get("technique.arm.preopen_replan", True))
        return {"rows": rows, "reference": prev, "gapPct": pct, "replan": replan}

    async def build_replacement_plan(self, ap: ArmedPlan, *, reference_price: float) -> dict | None:
        return await self.technique.analyze(ap.symbol, as_of_ms=int(ap.plan.get("builtFromMs") or 0) or None,
                                            primary_tf=str(ap.plan.get("triggerTf") or "1m"),
                                            trigger="preopen_replan", plan=True, with_vision=False, wait=True,
                                            parent_run_id=ap.run_id, reference_price=reference_price)

