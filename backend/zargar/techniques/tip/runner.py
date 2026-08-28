"""TipRunner — the tip technique on the shared PlanRunner.

The runner owns everything that moves money (BUILDING-A-TECHNIQUE.md §2);
this class supplies the tip's opinions, which are deliberately few:

- rules(): touch-fire mechanics with NO volume requirement (volume_floor_mult=0
  — the tracker's opt-out, platform plan §2.1), no gap-magnitude void
  (gapped past/through the level still kills — those are real), all RTH
  windows (extended-hours suppression stays runner-core).
- no reviewer in v1 (the human/source policy is the judge); analyze_fire says
  "setup" with the trigger's own confidence.
- arms **level-touch** tips only. A tip-time tip is an immediate proposal
  (the signals pipeline already does that); arming is for the waiting game.

Beyond the session runner (user decisions 2026-08-27):
- **The armed shadow book**: every open level-touch tip is auto-armed each
  morning in the source's "(armed)" shadow portfolio (dual-book scorecards —
  the immediate book buys at tip time; this book waits for the level). The
  loop runs on `engine.scheduler` and stops re-arming a tip once it has been
  played, or when its contract's expiry cutoff passes (options tips die at
  expiry — `techniques.tip.entry_cutoff_dte`).
- **The 2b handoff**: a tip position must outlive the session (the thesis is
  days, not minutes), so when an auto entry FILLS, the trade is handed to
  `engine.position_manager` with the tip exit policy (ladder 50/50, structure
  trail after +1R, time stop capped at the thesis expiry, earnings flatten)
  and removed from the session runner — the runner's end-of-day flatten never
  touches it.

Settings resolve `techniques.tip.<key>` → `execution.<key>` via `self.rt`.
Expression follows the per-tip vehicle rule (BUILD-PLAN §0): an option-shaped
tip arms as options (the stated contract verbatim via `express.pick_tip_contract`
when the tip named one), anything else as shares; a dead chain falls back to
shares and says so. `techniques.tip.instrument` is only the non-option fallback.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time

from sqlalchemy import select

from ... import bus as topics
from ... import events as ev
from ...domain import new_id
from ...execution.planrunner import ArmConfig, FireJudgement, PlanRunner
from ...execution.sizing import size_by_budget
from ...marketstructure import SESSION_WINDOWS, MarketRules
from ...models import Order, Signal, TechniqueRun
from .horizon import effective_wait_sessions, hold_sessions_cap, tip_expiry

log = logging.getLogger("zargar.techniques.tip")

ARMABLE_STATUSES = ("verified", "parked", "proposed", "shadow")
HANDOFF_POLL_SECONDS = 1.0
HANDOFF_WINDOW_SECONDS = 600.0     # give an entry 10 min to fill before leaving it session-scoped


class TipRunner(PlanRunner):
    TECHNIQUE_ID = "tip"

    def __init__(self, engine) -> None:
        super().__init__(engine, name="tip-runner")
        self._handoff_tasks: dict[str, asyncio.Task] = {}

    async def stop(self) -> None:
        self.engine.scheduler.unregister("tip_shadow_arm")
        for t in list(self._handoff_tasks.values()):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._handoff_tasks.clear()
        await super().stop()

    # ------------------------------------------------------------- hooks
    def rules(self) -> MarketRules:
        s = self.engine.settings
        return MarketRules(
            level_tolerance_pct=float(s.get("techniques.tip.touch_tolerance_pct", 0.002)),
            volume_floor_mult=0.0,          # tips carry no volume rule (tracker opt-out)
            gap_void_r=1e9,                 # no gap-magnitude void; gapped past/through still applies
            windows=SESSION_WINDOWS,        # any RTH window may fire
            stop_on_close=True,
        )

    async def load_plan(self, run_id: str) -> dict | None:
        async with self.engine.sf() as session:
            row = await session.get(TechniqueRun, run_id)
        if row is None or row.technique != self.TECHNIQUE_ID:
            return None
        return {"id": row.id, "symbol": row.symbol, "mode": row.mode,
                "result": row.result or {}, "config": row.config or {}, "tags": row.tags or []}

    async def analyze_fire(self, ap, tid, tr, trade) -> FireJudgement:
        conf = float((tr.trigger.get("confidence") or 0.5))
        return FireJudgement(verdict="setup", confidence=conf)

    async def pick_contract(self, ap, trade):
        """The tip's expression policy (BUILD-PLAN T2): the stated contract
        verbatim when the tip named one, else the source policy's DTE window —
        never EM's weekly/0DTE pick."""
        import contextlib as _ctx

        from ...signals.sources import resolve_policy
        from .express import pick_tip_contract

        trade.contract_attempted = True
        ctx = ap.plan.get("context") or {}
        sig = None
        if ctx.get("signalId"):
            async with self.engine.sf() as session:
                sig = await session.get(Signal, ctx["signalId"])
        policy = resolve_policy(self.engine.settings, ctx.get("source"))
        cap = float(trade.targets[-1]) if trade.targets else None
        pick = await pick_tip_contract(
            self.engine, symbol=ap.symbol, direction=trade.direction,
            dte_min=policy.dte_min, dte_max=policy.dte_max,
            strike=(sig.strike if sig else None), expiry=(sig.expiry if sig else None),
            spot=float(trade.last_price or trade.entry),
            max_strike=cap if trade.direction == "long" else None,
            min_strike=cap if trade.direction == "short" else None)
        if not pick.get("available") or not pick.get("symbol"):
            why = pick.get("error") or "no usable contract"
            trade.errors.append(f"option pick: {why}")
            self._log(ap, "option_pick_failed", f"{trade.trigger_id}: {why}",
                      trigger=trade.trigger_id)
            return None
        trade.contract = {k: pick.get(k) for k in (
            "symbol", "display", "underlying", "expiry", "strike", "optionType",
            "bid", "ask", "mid", "spreadPct", "delta", "theta", "iv", "dte",
            "is0dte", "openInterest", "volume", "warnings", "provider", "statedContract")}
        trade.order_symbol = pick["symbol"]
        self._log(ap, "option_picked",
                  f"{trade.trigger_id}: {pick.get('display') or pick['symbol']} "
                  f"bid/ask {pick.get('bid')}/{pick.get('ask')}"
                  + ("; stated by the tip" if pick.get("statedContract") else "")
                  + (f"; warnings: {'; '.join(pick.get('warnings') or [])}"
                     if pick.get("warnings") else ""),
                  trigger=trade.trigger_id, contract=trade.contract)
        with _ctx.suppress(Exception):
            if getattr(self.engine, "options", None) is not None:
                await self.engine.options.track(pick["symbol"])
        return trade.contract

    # ------------------------------------------------------------- tip-specific
    async def arm_signal(self, signal_id: str, config: ArmConfig | dict | None = None) -> dict:
        """Signal → today's tip plan → a minted `technique="tip"` run → armed.
        Level-touch tips only (a tip-time tip proposes immediately instead)."""
        svc = getattr(self.engine, "signals_service", None)
        if svc is None:
            raise RuntimeError("signals layer not attached")
        async with self.engine.sf() as session:
            sig = await session.get(Signal, signal_id)
        if sig is None:
            raise ValueError("unknown signal")
        if sig.status not in ARMABLE_STATUSES:
            raise ValueError(f"signal is {sig.status} — only verified/parked tips arm")
        from ...signals.sources import resolve_policy
        policy = resolve_policy(self.engine.settings, sig.source_name)
        if policy.entry != "level_touch":
            raise ValueError("this source's policy is tip_time — tip-time tips propose "
                             "immediately; arming is for level-touch tips")
        plan_dict = await svc.build_tip_plan_for(signal_id)   # raises "too late" past the expiry cutoff
        if not any(t.get("valid") for t in plan_dict.get("triggers") or []):
            reasons = "; ".join((plan_dict.get("triggers") or [{}])[0].get("noTradeReasons") or [])
            raise ValueError(f"the tip plan has no valid trigger ({reasons or 'degenerate'})")
        # the per-tip vehicle rule (BUILD-PLAN §0): an option-shaped tip arms as
        # options, anything else as shares; an explicit config wins either way
        from .express import tip_is_option
        if isinstance(config, dict):
            vehicle = "options" if tip_is_option(sig) else "shares"
            config.setdefault("instrument", vehicle)
            # a blocked contract expresses the idea in shares (SNOW lesson)
            config.setdefault("entryFallback", "shares")
            if config["instrument"] == "options":
                config.pop("budgetSize", None)
                config.setdefault("premiumBudget", policy.budget_per_tip)
                config.setdefault("contracts", None)      # risk-based, budget-clamped
            # shares: qty from the source's per-tip budget at the plan's entry
            elif config.pop("budgetSize", False) and not config.get("qty"):
                entry_px = float((plan_dict["triggers"][0].get("entry") or {}).get("price") or 0)
                if entry_px > 0:
                    config["qty"] = max(1, size_by_budget(policy.budget_per_tip, entry_px,
                                                          max_units=10_000))
        source = sig.source_name or "unknown"
        run_id = new_id()
        # snapshot the TIP rules into the run (provenance): the outcome scorer
        # replays with `config.thresholds` — without this it would replay a tip
        # plan under EM's rules (volume floor, prime-only windows) and the
        # scored outcome would contradict what the live tracker did
        import dataclasses as _dc
        rules = self.rules()
        thresholds = {f.name: (list(v) if isinstance(v := getattr(rules, f.name), tuple) else v)
                      for f in _dc.fields(type(rules))}
        row = TechniqueRun(
            id=run_id, technique=self.TECHNIQUE_ID, tags=[f"source:{source}"],
            symbol=sig.ticker, as_of=int(time.time() * 1000),
            primary_tf=str(plan_dict.get("triggerTf") or "5m"),
            mode="plan", trigger="tip", status="done", verdict="plan",
            result={"plan": plan_dict, "signalId": signal_id},
            config={"technique": self.TECHNIQUE_ID, "signalId": signal_id,
                    "source": source, "policy": policy.to_dict(),
                    "thresholds": thresholds},
        )
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        await self.engine.journal.append(
            ev.TECHNIQUE_RUN_COMPLETED,
            {"runId": run_id, "technique": self.TECHNIQUE_ID, "symbol": sig.ticker,
             "mode": "plan", "verdict": "plan", "signalId": signal_id, "source": source},
            aggregate_type="technique_run", aggregate_id=run_id)
        return await self.arm(run_id, config)

    async def runs_for_signal(self, signal_id: str) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TechniqueRun).where(TechniqueRun.technique == self.TECHNIQUE_ID)
                .order_by(TechniqueRun.created_at.desc()).limit(200))).scalars().all()
        return [{"id": r.id, "symbol": r.symbol, "status": r.status,
                 "createdAt": r.created_at.isoformat() if r.created_at else None}
                for r in rows if (r.result or {}).get("signalId") == signal_id]

    # ------------------------------------------------------------- the armed shadow book
    async def arm_shadow(self, signal_id: str) -> dict:
        """Arm one tip in its source's ARMED shadow book: auto mode on the sim
        venue, sized by the source's per-tip budget. This is the level-touch
        counterfactual the scorecard compares against the immediate book."""
        svc = self.engine.signals_service
        async with self.engine.sf() as session:
            sig = await session.get(Signal, signal_id)
        if sig is None:
            raise ValueError("unknown signal")
        source = sig.source_name or "unknown"
        shadow = await svc.shadow_portfolio(source, "armed")
        from ...signals.sources import resolve_policy
        policy = resolve_policy(self.engine.settings, source)
        return await self.arm_signal(signal_id, {
            "portfolioId": shadow["id"], "mode": "auto", "instrument": "shares",
            "budgetSize": True, "dailyLossLimit": policy.budget_per_tip,
            "flattenMinutesBeforeClose": 5,   # only un-handed-off remainders; fills hand off to the manager
        })

    async def shadow_arm_open_tips(self) -> dict:
        """The morning loop (engine.scheduler): every open level-touch tip gets
        today's plan armed in the armed shadow book — until it is played, or its
        contract's entry cutoff passes (then it is EXPIRED, which is itself a
        scorecard datum: 'the level never came')."""
        eng = self.engine
        if not bool(eng.settings.get("techniques.tip.shadow_auto", True)):
            return {"skipped": "techniques.tip.shadow_auto is off"}
        if eng.signals_service is None:
            return {"skipped": "signals layer not attached"}
        from ...signals.sources import resolve_policy
        cutoff = int(eng.settings.get("techniques.tip.entry_cutoff_dte", 2))
        async with eng.sf() as session:
            open_tips = (await session.execute(select(Signal).where(
                Signal.status.in_(ARMABLE_STATUSES)))).scalars().all()
        armed, skipped, expired, errors = 0, 0, 0, []
        today = dt.datetime.now(dt.timezone.utc).date()
        for sig in open_tips:
            policy = resolve_policy(eng.settings, sig.source_name)
            if policy.entry != "level_touch":
                skipped += 1          # tip-time sources live in the immediate book only
                continue
            expiry = tip_expiry(sig.expiry, sig.dte_hint_days,
                                (sig.created_at.date() if sig.created_at else today))
            wait = effective_wait_sessions(
                policy_horizon=policy.horizon_sessions, tip_horizon=sig.horizon_sessions,
                expiry=expiry, today=today, entry_cutoff_dte=cutoff)
            if wait <= 0:
                await self._expire_signal(sig, expiry)
                expired += 1
                continue
            if await self._signal_played(sig.id) or self._armed_today(sig.id):
                skipped += 1
                continue
            try:
                await self.arm_shadow(sig.id)
                armed += 1
            except Exception as exc:
                errors.append(f"{sig.ticker}: {exc}")
                log.warning("shadow arm failed for %s: %s", sig.ticker, exc)
        out = {"armed": armed, "skipped": skipped, "expired": expired}
        try:
            out["immediateClosed"] = await self._close_due_immediate(open_tips, today)
        except Exception:                          # never let cleanup kill arming
            log.exception("immediate-book close sweep failed")
        if errors:
            out["errors"] = errors[:5]
        return out

    async def _close_due_immediate(self, open_tips: list, today) -> int:
        """The immediate book's time exit: a bracket-less share buy records a
        `closeAfter` date at expression time (the tip's hold cap) — once it
        passes, sell what was bought. Options settle at their own expiry; this
        sweep is shares only. Without it a bracket-less tip lives forever
        (found 2026-08-28: the PeloSwing CRM replay)."""
        from ...orders import OrderIntent
        eng = self.engine
        svc = eng.signals_service
        closed = 0
        for sig in open_tips:
            expr = ((sig.extraction or {}).get("shadowExpression") or {})
            due = expr.get("closeAfter")
            if (expr.get("vehicle") != "shares" or not due or expr.get("closed")
                    or not expr.get("qty")):
                continue
            if dt.date.fromisoformat(due) > today:
                continue
            shadow = await svc.shadow_portfolio(sig.source_name or "unknown", "immediate")
            pos = next((p for p in eng.positions.positions_list(shadow["id"])
                        if p["symbol"] == sig.ticker and p["qty"] > 0), None)
            qty = min(float(expr["qty"]), float(pos["qty"])) if pos else 0
            if qty > 0:
                await eng.orders.place(OrderIntent(
                    portfolio_id=shadow["id"], symbol=sig.ticker, side="SELL",
                    qty=qty, order_type="MKT", reduce_only=True,
                    source="auto", signal_id=sig.id,
                    technique_id="tip", tags=[f"source:{sig.source_name or 'unknown'}"]))
                closed += 1
            await svc._record_expression(sig.id, {**expr, "closed": True,
                                                  "closedOn": today.isoformat()})
        return closed

    def _armed_today(self, signal_id: str) -> bool:
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        for ap in self._armed.values():
            if (ap.plan.get("context") or {}).get("signalId") == signal_id \
                    and ap.plan_for >= today and ap.status in ("armed", "paused"):
                return True
        return False

    async def _signal_played(self, signal_id: str) -> bool:
        """A tip is played once any of its armed plans produced a fill — a
        managed position (open or closed) or a filled trade in an armed row."""
        run_ids = {r["id"] for r in await self.runs_for_signal(signal_id)}
        if not run_ids:
            return False
        mgr = getattr(self.engine, "position_manager", None)
        if mgr is not None and any((p.get("runId") in run_ids) for p in mgr.positions()):
            return True
        from ...models import TechniqueArmed
        async with self.engine.sf() as session:
            rows = (await session.execute(select(TechniqueArmed).where(
                TechniqueArmed.run_id.in_(run_ids)))).scalars().all()
        for row in rows:
            for t in ((row.state or {}).get("trades") or []):
                if float(t.get("filledQty") or 0) > 0:
                    return True
        return False

    async def _expire_signal(self, sig: Signal, expiry) -> None:
        from ...signals.service import signal_dict
        async with self.engine.sf() as session:
            row = await session.get(Signal, sig.id)
            if row is None or row.status not in ARMABLE_STATUSES:
                return
            row.status = "expired"
            await session.commit()
            sig = row
        await self.engine.journal.append(
            ev.SIGNAL_EXPIRED_UNFILLED,
            {"ticker": sig.ticker, "source": sig.source_name,
             "expiry": expiry.isoformat() if expiry else None,
             "reason": "the level never came before the tip's contract/horizon died"},
            aggregate_type="signal", aggregate_id=sig.id)
        self.engine.bus.publish(topics.SIGNALS, signal_dict(sig))

    # ------------------------------------------------------------- the 2b handoff
    async def after_fire(self, ap, tid, tr, trade, judgement, bar) -> None:
        """A filled tip entry must OUTLIVE the session: watch the entry order
        and hand the position to the durable manager the moment it fills."""
        if ap.config.mode == "auto" and trade.entry_order_id \
                and trade.status in ("submitting", "working", "open"):
            key = f"{ap.run_id}:{tid}"
            self._handoff_tasks[key] = asyncio.create_task(
                self._handoff_when_filled(ap, tid, trade), name=f"tip-handoff-{key}")
            self._handoff_tasks[key].add_done_callback(
                lambda t, k=key: self._handoff_tasks.pop(k, None))

    async def _handoff_when_filled(self, ap, tid, trade) -> None:
        deadline = time.monotonic() + HANDOFF_WINDOW_SECONDS
        order = None
        while time.monotonic() < deadline:
            async with self.engine.sf() as session:
                order = await session.get(Order, trade.entry_order_id)
            if order is None:
                return
            if order.status == "FILLED":
                break
            if order.status in ("REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED"):
                return
            await asyncio.sleep(HANDOFF_POLL_SECONDS)
        else:
            self._log(ap, "handoff_skipped",
                      f"{tid}: entry not filled within {HANDOFF_WINDOW_SECONDS:.0f}s — "
                      "stays session-scoped (flatten applies)", trigger=tid)
            return
        try:
            await self._handoff(ap, tid, trade, order)
        except Exception as exc:
            log.exception("tip handoff failed for %s %s", ap.symbol, tid)
            await self._alert(ap, f"{tid}: handing the filled position to the durable manager "
                                  f"FAILED ({exc}) — it stays session-scoped and will flatten at "
                                  "the close", level="critical", stage="handoff")

    async def _handoff(self, ap, tid, trade, order) -> None:
        mgr = getattr(self.engine, "position_manager", None)
        if mgr is None:
            raise RuntimeError("position manager not attached")
        ctx = ap.plan.get("context") or {}
        signal_id = ctx.get("signalId")
        sig = None
        if signal_id:
            async with self.engine.sf() as session:
                sig = await session.get(Signal, signal_id)
        today = dt.datetime.now(dt.timezone.utc).date()
        expiry = tip_expiry(sig.expiry, sig.dte_hint_days,
                            (sig.created_at.date() if sig.created_at else today)) if sig else None
        fallback = int(ctx.get("horizonSessions") or 10)
        hold_cap = hold_sessions_cap(expiry=expiry, today=today, fallback=fallback)
        is_opt = trade.instrument == "options"
        fill = float(order.avg_fill_price or trade.entry)     # OPT: this is the PREMIUM
        entry_ref = float(trade.entry) if is_opt else fill    # policies judge the UNDERLYING
        risk = abs(entry_ref - trade.stop) or abs(trade.entry - trade.stop)
        policy: dict = {
            "timeframe": "15m",
            "stop": {"kind": "fixed", "price": trade.stop},
            "ladder": {"targets": [float(t) for t in trade.targets[:2]],
                       "fractions": [0.5, 0.5][:max(1, len(trade.targets[:2]))]},
            "trailing": {"mode": "structure",
                         "after_r": float(self.engine.settings.get("techniques.tip.trailing_after_r", 1.0))},
            "time_stop_sessions": hold_cap,      # the thesis dies with the contract
        }
        if is_opt:
            policy["premium_stop_pct"] = float(self.rt("premium_stop_pct", 50.0) or 50.0)
            policy["dte_close"] = max(1, int(self.engine.settings.get("execution.min_dte", 1)))
        catalyst = (sig.catalyst or "").lower() if sig else ""
        if "earnings" not in catalyst:
            policy["flatten_before"] = {"event": "earnings", "days": 1}
        source = ctx.get("source") or "unknown"
        qty = float(order.filled_qty or trade.filled_qty or trade.qty)
        # options are always LONG the contract (calls for longs, puts for shorts);
        # a positive leg qty is correct for both directions
        leg = ({"symbol": trade.order_symbol or order.symbol, "secType": "OPT",
                "qty": qty, "avgFill": fill, "multiplier": 100.0,
                "entryOrderId": order.id, "origin": "adoption"}
               if is_opt else
               {"symbol": ap.symbol, "secType": "STK",
                "qty": qty if trade.direction == "long" else -qty,
                "avgFill": fill, "entryOrderId": order.id, "origin": "adoption"})
        pos = await mgr.adopt({
            "portfolioId": ap.config.portfolio_id, "symbol": ap.symbol,
            "direction": trade.direction, "techniqueId": self.TECHNIQUE_ID,
            "tags": [f"source:{source}"], "runId": ap.run_id,
            "entry": entry_ref, "risk": risk,
            "legs": [leg],
            # options cannot rest a venue stop (probed 2026-08-27): app-managed
            # with the acknowledgement — shadow books auto-ack; a LIVE arm
            # already required the per-arm allowLive acknowledgement upstream
            "overnight": "app_managed" if is_opt else "venue_stop",
            "overnightAck": True if is_opt else False,
            "policy": policy,
        })
        # the manager owns it now — the session runner forgets the trade so the
        # end-of-day flatten and the session expiry never touch it
        ap.trades.pop(tid, None)
        self.forget_order(order.id)
        for oid in trade.exit_order_ids:
            self.forget_order(oid)
        await self._persist(ap)
        self._log(ap, "handoff",
                  f"{tid}: filled {qty:g} @ {fill:.2f} — handed to the durable manager "
                  f"(position {pos['id']}, hold cap {hold_cap} session(s)"
                  + (f", thesis expiry {expiry}" if expiry else "") + ")",
                  trigger=tid, positionId=pos["id"])
        self._publish(ap, "handoff")


async def attach_tip_runner(engine) -> None:
    """Called from the FastAPI lifespan after the engine + signals layer start."""
    if getattr(engine, "tip_runner", None) is not None:
        return
    engine.tip_runner = TipRunner(engine)
    try:
        restored = await engine.tip_runner.restore()
        if restored:
            log.info("tip runner restored %d armed plan(s)", restored)
    except Exception:  # pragma: no cover - restore must never block startup
        log.exception("tip runner restore failed")
    # the armed shadow book's morning loop (after the 09:05 managed-positions
    # reconciliation; a post-09:12 restart still runs it that day)
    at = str(engine.settings.get("techniques.tip.shadow_arm_at", "09:12"))
    engine.scheduler.register("tip_shadow_arm", at,
                              lambda: engine.tip_runner.shadow_arm_open_tips())
