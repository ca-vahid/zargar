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

from .options import MAX_SPREAD_PCT, rejudge_iv, rejudge_spread
from .. import bus as topics
from .. import events as ev
from ..domain import Bar, now_ms
from ..execution.entry_quality import judge_entry_quote
from ..execution.planrunner import (  # noqa: F401 — re-exported for existing importers
    MODES, TRANSIENT_ERRORS, ArmConfig, ArmedPlan, FireJudgement, PlanRunner, Trade, _et_day_start_ms,
)
from ..marketstructure.tracker import TriggerTracker
from ..models import TechniqueSetup
from .analysis import facts_for_prompt
from dataclasses import asdict as _asdict

from .entry_decision import DECISION_VERSION, evaluate_entry, normalize_fire_mode, policy_from_thresholds, snapshot_from_tracker
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
        # ED-04 (book-snapshot-v1): EM-owned bounded recorder, DEFAULT OFF; the runner's `_book_snap` is a no-op without it
        from .profit_capture_runtime import build_observer
        self._book_observer = build_observer(self)

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
        # the WEEKDAY comes from the test-pinnable clock (production = real time): the reviewers' dispatch cases were
        # sized x0.5 and skipped whenever the suite ran on a Friday (found 2026-09-18, a Friday evening)
        from ..clock import now_ms as _clock_ms
        if dt.datetime.fromtimestamp(_clock_ms() / 1000.0, ET).weekday() == 4:
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

    # ---- deterministic-entry-v1 (2026-09-15, user decision): EM's live entry decision is made by application rules.
    # The authoritative EM setting decides per fire attempt; a stored arm's `useCritic` is a legacy compatibility
    # field that cannot resurrect the awaited critic under `deterministic`. `legacy` is an explicit, journaled
    # rollback to the old reviewer branch (veto / momentum_only / advisory semantics unchanged there).
    def fire_review_policy(self, ap) -> str:
        return normalize_fire_mode(self.engine.settings.get("techniques.enhanced_market.fire_decision_mode", "deterministic"))

    # ---- em-prep-policy-v1 (2026-09-18, integrated plan B): the effective PREPARATION policy rides every preflight and
    # every armed snapshot beside the fire-decision policy - the two are distinct settings
    def _em_policy_extras(self) -> dict:
        from .preparation_policy import effective
        try:
            out = effective(self.engine.settings.get)
        except Exception:                                  # noqa: BLE001
            out = {"preparationPolicy": "baseline"}
        out["firstSaleGate"] = self.first_sale_policy(None)
        return out

    def _preflight_policy(self) -> dict:
        return {**super()._preflight_policy(), **self._em_policy_extras()}

    def fire_policy_view(self, ap) -> dict:
        return {**super().fire_policy_view(ap), **self._em_policy_extras()}

    # ---- first-sale-v2 (2026-09-19, IR-01 / IR-04): R2 at the gate target of the FINAL quantity, from the validated current
    # executable underlying bound. DEFAULT OFF. observe = non-authoritative record; enforce = fail closed (refuse / defer).
    def first_sale_policy(self, ap) -> str:
        from .first_sale import normalize_mode
        return normalize_mode(self.engine.settings.get("techniques.enhanced_market.first_sale_rr_gate", "off"))

    async def first_sale_prepare(self, ap) -> None:
        """Resolve the policy-defining pin (`technique.rr_gate_target`) from the plan's FROZEN run config, once per plan,
        bounded. Never a fresh read of the live legacy key. Unresolved stays unresolved (enforce then defers)."""
        cache = self.__dict__.setdefault("_fs_pins", {})
        if ap.run_id in cache:
            return
        try:
            run = await asyncio.wait_for(self.load_plan(ap.run_id), timeout=2.0)
            cfg = (run or {}).get("config") or {}
            pin = (cfg.get("settings") or {}).get("technique.rr_gate_target")
            cache[ap.run_id] = {"pin": str(pin or "auto"), "source": ("run_config" if cfg else "unresolved"),
                                "planRrGateTarget": (cfg.get("thresholds") or {}).get("rr_gate_target")}
        except Exception:                                  # noqa: BLE001 - unresolved is a value; enforce defers on it
            cache[ap.run_id] = {"pin": "auto", "source": "unresolved", "planRrGateTarget": None}
        if len(cache) > 500:
            for k in list(cache)[:250]:
                cache.pop(k, None)

    def first_sale_record(self, ap, trade, qty, limit, mode, stage="order"):
        from .first_sale import build_record, compare_vehicles
        from .research_recorder import feed_identity, quote_evidence
        s = self.engine.settings
        trig = next((t for t in ((ap.plan or {}).get("triggers") or []) if t.get("id") == trade.trigger_id), {}) or {}
        uq = self.engine.quotes.get(ap.symbol)
        ue = quote_evidence(uq, symbol=ap.symbol, is_option=False, feed=feed_identity(self.engine))
        oq = None
        if trade.instrument == "options" and trade.order_symbol:
            oq = quote_evidence(self.engine.quotes.get(trade.order_symbol), symbol=trade.order_symbol, is_option=True, feed=None)
            if oq is not None:
                oq["derived"] = bool(str(oq.get("source") or "").startswith("derived:") or oq.get("transform"))
        trk = (getattr(ap, "trackers", None) or {}).get(trade.trigger_id)
        th = getattr(trk, "thresholds", None)
        if th is None or not hasattr(th, "min_risk_reward"):
            th = self.technique.thresholds()
        pin = (self.__dict__.get("_fs_pins") or {}).get(ap.run_id) or {"pin": "auto", "source": "unresolved", "planRrGateTarget": None}
        plan_gate = None
        if trig.get("riskReward") is not None:
            plan_gate = {"targetIndex": (pin.get("planRrGateTarget") if pin.get("planRrGateTarget") is not None else getattr(th, "rr_gate_target", None)),
                         "rr": trig.get("riskReward"), "rrTp3": trig.get("riskRewardTp3"), "min": getattr(th, "min_risk_reward", None)}
        fee = float(s.get("options.fee_per_contract", 0.99)) + float(s.get("sim.reg_fee_per_contract", 0.05))
        entry = trig.get("entry")
        rec = build_record(stage=stage, symbol=ap.symbol, run_id=ap.run_id, trigger_id=trade.trigger_id, family=trade.kind,
                           direction=trade.direction, session=ap.plan_for, plan_entry=(entry.get("price") if isinstance(entry, dict) else entry),
                           runner_entry=trade.entry, stop=trade.stop, targets=trade.targets, underlier_evidence=ue, instrument=trade.instrument,
                           qty=qty, multiplier=trade.multiplier, limit_price=limit, single_exit=str(ap.config.single_contract_exit or "tp2"),
                           pinned_gate_target=pin["pin"], pin_source=pin["source"], min_rr=float(getattr(th, "min_risk_reward", 3.0)),
                           contract=trade.contract, option_quote=oq, fee_per_contract=fee, stock_commission=float(s.get("sim.stock_commission", 0.0)),
                           affordable_qty=qty, plan_gate=plan_gate, mode=mode, now_ms=now_ms(),
                           max_underlier_age_ms=int(float(s.get("risk.stale_quote_seconds", 10) or 10) * 1000))
        if stage == "order":
            try:                                          # order-free vehicle comparison on rows already in hand - never a gate
                vr = (getattr(trade, "timing", None) or {}).get("vehicleRows") or {}
                if vr.get("rows"):
                    cash = float(((self.engine.positions.portfolio(ap.config.portfolio_id) or {}).get("cash")) or 0.0)
                    sq = ({"ask": (ue or {}).get("ask") or None, "last": (ue or {}).get("last") or None, "askSize": (ue or {}).get("askSize")} if ue else None)
                    rec["vehicleComparison"] = {**compare_vehicles(
                        setup={"symbol": ap.symbol, "direction": trade.direction, "entry": trade.entry, "stop": trade.stop, "targets": trade.targets,
                               "singleExit": str(ap.config.single_contract_exit or "tp2")},
                        contracts=vr["rows"], share_quote=sq, budget=float(s.get("risk.max_option_premium_notional", 1000.0) or 0.0),
                        risk_budget=cash * float(ap.config.risk_pct or 0.0) / 100.0, fee_per_contract=fee,
                        stock_commission=float(s.get("sim.stock_commission", 0.0)), allow_shares=(str(ap.config.entry_fallback or "") == "shares")),
                        "rowsCapturedTs": vr.get("ts"), "riskBudgetBasis": "cash x risk_pct (approximation; the sizer uses equity)"}
            except Exception:                              # noqa: BLE001
                pass
        return rec

    def first_sale_decide(self, rec, mode, error=None) -> dict:
        from .first_sale import decide
        return decide(rec, mode, error=error)

    def first_sale_publish(self, ap, rec: dict) -> None:
        """Research persistence of the record: bounded, never awaited by the entry (IR-04). The REFUSAL itself is journaled
        on the established durable path by the runner (`_refuse_entry` / the order's own rejection)."""
        r = self.__dict__.get("_fs_recorder")
        if r is None:
            from .research_recorder import BoundedRecorder
            journal = self.engine.journal

            async def write(item: dict) -> None:
                await journal.append(ev.TECHNIQUE_FIRST_SALE, item["rec"], aggregate_type="technique_run", aggregate_id=item["runId"],
                                     portfolio_id=item["portfolioId"])
            r = self._fs_recorder = BoundedRecorder(write, name="em-first-sale", maxsize=128)
        r.put({"rec": rec, "runId": ap.run_id, "portfolioId": ap.config.portfolio_id})

    def fire_evidence_mode(self, ap) -> str:
        raw = str(self.engine.settings.get("techniques.enhanced_market.fire_evidence_mode", "off") or "off").strip().lower()
        return raw if raw in ("off", "after_close") else "off"

    async def fire_decision(self, ap, tid: str, tr: TriggerTracker, trade: Trade, *, attempt_id: str) -> dict | None:
        """Freeze the ACTUAL tracker transition and judge it with the pure `evaluate_entry` - no I/O, no model,
        no chart, no clock inside the decision. Returns the versioned decision dict the runner journals."""
        snapshot = snapshot_from_tracker(attempt_id=attempt_id, run_id=ap.run_id, plan=ap.plan or {}, plan_status=ap.status,
                                         trigger_id=tid, tracker=tr, signal_bar=trade.signal_bar,
                                         received_ts=(getattr(trade, "timing", None) or {}).get("receivedTs"), decided_ts=None)
        # DE-01 / DR-03: judge the transition under the RULES THAT FIRED IT - the tracker's own threshold object and
        # window-enforcement flag, never a fresh settings read (an armed tracker keeps the rule set it was built with)
        policy = policy_from_thresholds(tr.thresholds, enforce_windows=bool(getattr(tr, "enforce_windows", True)))
        decision = evaluate_entry(snapshot, policy).to_dict()
        # DE-05: the decision travels WITH its frozen inputs (serialised once; the evidence command may only use these)
        decision["snapshot"] = _asdict(snapshot)
        decision["policy"] = {"mode": policy.mode, "ruleVersion": policy.rule_version, "thresholds": dict(policy.thresholds),
                              "enforceWindows": policy.enforce_windows}
        return decision

    def fire_evidence_capture(self, ap, tid: str, tr: TriggerTracker, trade: Trade) -> list[dict] | None:
        """DE-05: raw source bars for the optional later evidence, frozen at decision time from the engine's in-memory
        bar cache (no I/O, no rendering, no model): the last 240 completed 1m bars whose close is at or before the
        signal bar's close. None when no bar cache is available (the evidence stays `unavailable`, never fabricated)."""
        bars_api = getattr(getattr(self.engine, "bars", None), "bars", None)
        if bars_api is None or not trade.signal_bar:
            return None
        close_ts = int(trade.signal_bar["ts"]) + int((trade.timing or {}).get("barCloseTs", trade.signal_bar["ts"] + 60_000) - trade.signal_bar["ts"])
        try:
            bars = bars_api(ap.symbol, "1m", limit=600, include_forming=False)
        except TypeError:
            bars = bars_api(ap.symbol, "1m", limit=600)
        out = [{"ts": int(b.ts), "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": int(b.volume or 0),
                "source": getattr(b, "source", None)} for b in bars if int(b.ts) + 60_000 <= close_ts]
        return out[-240:] if out else None

    async def review_fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, trade: Trade,
                          judgement: FireJudgement) -> tuple[str, float, dict | None]:
        """The vision critic: prompt assembly (live context incl. gap_unchecked and the
        mid-day experiment, plan provenance, data-quality guidance) and the verdict.
        Timeout, fail-open budget, cooldown, kill cap and re-arming are the runner's."""
        a, window, cfg = judgement.extra, trade.window, ap.config
        llm = self.technique.llm_config()
        from dataclasses import replace as dc_replace

        from .analysis import AnalysisRequest, compute_facts
        from .render import render_chart_async
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
        png = (await render_chart_async(bars[-240:], title=f"{ap.symbol} 1m", tf="1m")) if bars else None
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
        # DE-02: the EXECUTED decision owns the persisted setup. A deterministic refusal/deferral is written as such
        # (verdict no_setup, the reason codes on the record); the pre-gate analysis is not persisted as "setup".
        d = getattr(trade, "decision", None)
        if d and d.get("verdict") in ("refuse", "defer"):
            a.verdict = "no_setup"
            a.confidence = 0.0
            codes = ", ".join(d.get("reasonCodes") or [])
            a.rationale = f"deterministic {d['verdict']} ({d.get('decisionVersion')}): {codes} | " + (a.rationale or "")
            try:
                a.no_trade_reasons = list(a.no_trade_reasons or []) + [f"deterministic-entry: {c}" for c in (d.get("reasonCodes") or [])]
            except Exception:
                pass
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
                               if critic else "")
                            + (f"; live decision: deterministic {trade.decision.get('verdict')} ({trade.decision.get('decisionVersion')})"
                               + (" — " + ", ".join(trade.decision.get("reasonCodes") or []) if trade.decision.get("reasonCodes") else "")
                               if trade.decision else ""))}],
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
                                                    max_strike=max_strike, min_strike=min_strike, avoid_0dte=avoid_0dte,
                                                    near_money=(self.first_sale_policy(ap) in ("observe", "enforce")))
            pick = await self._repick_after_rate_limit(ap, trade, pick, max_strike=max_strike, min_strike=min_strike, avoid_0dte=avoid_0dte)
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
        if pick.get("nearMoney"):
            trade.timing["vehicleRows"] = {"ts": now_ms(), "rows": pick["nearMoney"]}    # first-sale-v1: contemporaneous alternatives (evidence only)
        # the chain's bid/ask picked the strike; the real-time NBBO prices the
        # trade (sizing, entry limit, caps) — never the delayed row
        with contextlib.suppress(Exception):
            if getattr(self.engine, "options", None) is not None:
                await self.engine.options.reprice(trade.contract)
        # T5.4 is re-judged on the NBBO the trade will actually pay (the chain's
        # spread was 15 min stale); the runner's skip_wide_spread reads these warnings
        rejudge_spread(trade.contract)
        rejudge_iv(trade.contract, spot=float(trade.last_price or trade.entry or 0))
        warns = trade.contract.get("warnings") or []
        self._log(ap, "option_picked", f"{trade.trigger_id}: {pick.get('display') or pick['symbol']} "
                  f"bid/ask {trade.contract.get('bid')}/{trade.contract.get('ask')}"
                  f" ({trade.contract.get('priced') or 'chain'}; spread judged on {trade.contract.get('spreadJudgedOn') or 'chain'}, IV on {trade.contract.get('ivJudgedOn') or 'chain'})"
                  + (f"; warnings: {'; '.join(warns)}" if warns else ""),
                  trigger=trade.trigger_id, contract=trade.contract)
        return trade.contract

    async def _repick_after_rate_limit(self, ap, trade, pick, **kw):
        """SKHY 2026-09-18: the provider's 429 outlasted the client's ~1.8 s back-off and a fired put entry sent nothing.
        ONE more pick after `techniques.enhanced_market.pick_retry_after_429_s` (default 0 = OFF, capped at 8 s) - never a
        loop, never stale chain data. The entry is then only allowed if the underlying has NOT run away meanwhile (no-chase:
        at most 0.25R beyond the entry in the trade's direction); every later check (NBBO reprice, spread, sizing, first
        sale, final guard, RiskGate) still runs. The fire chain is off the bar loop, so the wait blocks nothing else."""
        err = str((pick or {}).get("error") or "")
        if (pick or {}).get("available") or "429" not in err:
            return pick
        try:
            wait = min(8.0, float(self.engine.settings.get("techniques.enhanced_market.pick_retry_after_429_s", 0.0) or 0.0))
        except (TypeError, ValueError):
            wait = 0.0
        if wait <= 0:
            return pick
        self._log(ap, "option_pick_retry", f"{trade.trigger_id}: provider rate limit - one more pick in {wait:g}s", trigger=trade.trigger_id)
        await asyncio.sleep(wait)
        q = self.engine.quotes.get(ap.symbol)
        last = float(q.last) if q is not None and q.last and q.last > 0 else None
        risk = abs(float(trade.entry) - float(trade.stop)) if trade.stop is not None else 0.0
        if last is None or risk <= 0:
            return {**(pick or {}), "error": err + "; no re-pick: the underlying cannot be re-checked"}
        ran = (float(trade.entry) - last) if trade.direction == "short" else (last - float(trade.entry))
        if ran > 0.25 * risk:
            return {**(pick or {}), "error": err + f"; no re-pick: the underlying moved {ran / risk:.2f}R past the entry during the provider outage (no chase)"}
        trade.timing["pickRetryAfter429S"] = wait
        return await self.technique.option_pick(ap.symbol, "short" if trade.direction == "short" else "long", spot=last, **kw)

    async def rejudge_contract(self, ap, trade, contract: dict) -> None:
        """EM's quality re-judgement on the fresh NBBO (DA-01): T5.4 spread and T5.3 IV, the same
        functions the pick used, so the final admission sees the book's warnings on the final quote."""
        rejudge_spread(contract)
        rejudge_iv(contract, spot=float(trade.last_price or trade.entry or 0))

    def judge_entry_quote(self, ap, trade, contract: dict, quote) -> str | None:
        """EM's final verdict on the CURRENT NBBO (FC-01): T5.4's own 10% spread limit (`MAX_SPREAD_PCT`, the
        number the pick and `rejudge_spread` use), a two-sided book, CURRENT evidence (no quote / a delayed row
        when a real-time source is configured = refusal, FC-02) fresher than the ENTRY policy
        `risk.stale_quote_seconds`. Synchronous and pure; the runner raises on a reason."""
        return judge_entry_quote(contract, quote, max_spread_pct=MAX_SPREAD_PCT,
                                 max_age_s=self._entry_quote_max_age(), refuse_wide=bool(ap.config.skip_wide_spread),
                                 now_ms=now_ms(), require_current=self._live_option_quotes_expected())

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
            # FIX-04 (2026-09-14): the SAME direction-aware predicates as the opening tracker
            # (`TriggerTracker.on_bar`). Ten short breakdowns were called gapped_past on 09-14 with the
            # pre-market print still between entry and stop (IBIT 44.0 vs 43.43/44.04) and replaced.
            short = tr.direction == "short"
            if tr.kind in ("bounce", "reject"):
                through = (last > tr.stop) if short else (last < tr.stop)
                past = (last >= tr.entry) if short else (last <= tr.entry)
                if through:
                    verdict = "gapped_through"
                elif past:
                    verdict = "gapped_past"
            else:
                past = (last < tr.entry) if short else (last > tr.entry)
                if past:
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
        run = await self.technique.analyze(ap.symbol, as_of_ms=int(ap.plan.get("builtFromMs") or 0) or None,
                                           primary_tf=str(ap.plan.get("triggerTf") or "1m"),
                                           trigger="preopen_replan", plan=True, with_vision=False, wait=True,
                                           parent_run_id=ap.run_id, reference_price=reference_price)
        # em-prep-policy-v1: under the PROPOSED policy the re-plan is a candidate like any other and passes the SAME
        # eligibility owner (baseline keeps today's behaviour: any valid trigger replaces the dead plan)
        try:
            from .preparation_policy import effective
            if run and effective(self.engine.settings.get)["preparationPolicy"] == "deterministic":
                d = await self.technique.prep_decide(run["id"], origin="preopen_replan", persist=True, run=run)
                if d.get("disposition") != "eligible":
                    self._log(ap, "preopen_replan_ineligible", f"re-plan {run['id'][:8]} is not eligible under the preparation policy: {d.get('explanation', '')[:200]}")
                    return None
        except Exception:                                  # noqa: BLE001 - the policy record must never break the pre-open path
            log.exception("prep decision for the pre-open re-plan failed")
        return run

