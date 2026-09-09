"""Cartel signal -> reviewed execution -> durable submission -> fill reconciliation.

The public observer remains alert-only until the controller's runtime lifecycle
and primary exit cancellation gates are connected and verified.
"""
from __future__ import annotations

import asyncio
import math
import time
from weakref import WeakKeyDictionary

from sqlalchemy import select

from ... import events as ev
from ...marketstructure.aggregate import bar_session
from ...models import TechniqueRun
from ...orders import OrderIntent
from .data import DailyBar
from .execution import ExecutionInput, preflight
from .exits import ExitCampaign
from .loss import loss_gate
from .plans import CartelPlan
from .readiness import execution_readiness
from .settlement import settle_entry
from .state import ArmRepository

_locks = WeakKeyDictionary()
_inflight = WeakKeyDictionary()


def reviewed_execution_plan(run):
    if run is None or run.mode != "plan" or run.technique != "options_cartel":
        raise ValueError("entry requires an owned reviewed plan")
    plan = CartelPlan.model_validate(run.result["plan"]["plan"])
    campaign = ExitCampaign.model_validate(run.result.get("exitCampaign"))
    targets = [r.target for r in campaign.rungs if r.kind == "target"]
    if targets != list(plan.targets[:len(targets)]):
        raise ValueError("exit campaign targets differ from the reviewed plan")
    history = [DailyBar.model_validate(b) for b in run.config.get("inputs", {}).get("history", [])]
    if not history or any(b.symbol != plan.symbol or b.closes_at > plan.created_at for b in history):
        raise ValueError("entry requires owned pre-plan history for position management")
    return plan


class CartelEntryController:
    def __init__(self, engine):
        self.engine = engine
        self.repository = ArmRepository(engine)
        self.clock = lambda: int(time.time()*1000)

    def _guard(self, run_id):
        return _locks.setdefault(self.engine, {}).setdefault(run_id, asyncio.Lock())

    def _entry_conditions(self, row, plan, spec):
        now = self.clock()
        from .accounts import validate_account
        book = self.engine.positions.portfolio(spec.portfolio_id)
        if book:
            validate_account(self.engine, book)
        preparation = row.get('config', {}).get('preparation')
        if preparation:
            from .preparation_scope import read_policy, require_execution_scope
            if now >= preparation.get('validUntil', 0):
                raise ValueError('Automatic preparation evidence expired')
            scope = preparation.get('workspace', 'practice' if preparation.get('practiceOnly') else None)
            if scope not in ('practice', 'live'):
                raise ValueError('Automatic preparation workspace is missing')
            require_execution_scope(self.engine, read_policy(self.engine, scope))
            book = self.engine.positions.portfolio(spec.portfolio_id)
            if not book or book['kind'] not in (('sim',) if scope == 'practice' else ('live', 'paper')):
                raise ValueError('Prepared account no longer belongs to its workspace')
        signal = row["state"].get("signal") or {}
        if row["status"] != "armed" or row["state"]["phase"] not in ("signalled", "submitting"):
            raise ValueError("entry is no longer armed and signalled")
        if row["mode"] not in ("proposal", "auto") or spec.mode != row["mode"] or spec.portfolio_id != row["portfolioId"]:
            raise ValueError("reviewed execution does not match the armed mode/account")
        if not row["state"]["opensAt"] <= now < row["state"]["expiresAt"] or bar_session(now) != "rth":
            raise ValueError("entry requires an open regular exchange session within the plan horizon")
        if signal.get("id") != f"{plan.id}:entry:{signal.get('at')}" or not 0 <= now-signal.get("at", -1) <= 120_000:
            raise ValueError("entry signal is missing, stale, future-dated or mismatched")
        if signal.get("direction") != plan.direction or signal.get("targets") != list(plan.targets):
            raise ValueError("signal direction/targets differ from the reviewed plan")
        quote = self.engine.quotes.get(plan.symbol)
        if quote is None or quote.delayed or not 0 <= now-(quote.source_ts or quote.ts) <= \
                float(self.engine.settings.get("risk.stale_quote_seconds", 10))*1000:
            raise ValueError("current underlying quote is unavailable or stale")
        price = quote.ask if spec.instrument == "shares" else quote.last
        sign = 1 if plan.direction == "long" else -1
        stop = float(signal.get("stop", 0))
        if not math.isfinite(price) or price <= 0 or not math.isfinite(stop) or stop <= 0 \
                or (price-stop)*sign <= 0 or (price-plan.trigger)*sign < 0:
            raise ValueError("current price no longer holds the entry/stop geometry")
        if (price-plan.trigger)*sign > abs(plan.trigger-plan.invalidation)*plan.entry.max_chase_r:
            raise ValueError("current underlying price exceeds the reviewed chase limit")
        if (plan.targets[0]-price)*sign <= 0:
            raise ValueError("first target has already been reached")
        if self.engine.trading_halted(spec.portfolio_id) or self.engine.settings.get("techniques.options_cartel.paused", False) \
                or not self.engine.settings.get("techniques.options_cartel.enabled", True):
            raise ValueError("entry halted or technique paused/disabled")
        if self.engine.position_manager.entries_halted(plan.symbol):
            raise ValueError("position reconciliation has halted entries on this symbol")
        portfolio = self.engine.positions.portfolio(spec.portfolio_id)
        if portfolio and portfolio["kind"] in ("live", "paper") and plan.rules.market_alignment != "strict":
            raise ValueError("Moderate market-alignment plans cannot execute on Live accounts")
        if portfolio and portfolio["kind"] in ("live", "paper") and (not spec.allow_live
                or self.engine.settings.get("trading.mode") != "live"
                or row["mode"] == "auto" and not self.engine.settings.get("techniques.options_cartel.allow_live_auto", False)):
            raise ValueError("live execution permissions changed")
        loss_limit = float(self.engine.settings.get("risk.daily_loss_halt_pct", 0))
        if row["mode"] == "auto" and (not math.isfinite(loss_limit) or loss_limit <= 0):
            raise ValueError("auto entry requires an enabled book daily-loss halt")
        # A share fill's risk uses the maximum price we will pay and the actual
        # signal stop, not the earlier plan's trigger-to-invalidation distance.
        return plan.model_copy(update={"trigger": price, "invalidation": stop})

    def _vehicle_conditions(self, intent, spec, plan):
        quote = self.engine.quotes.get(intent.symbol)
        now = self.clock()
        if quote is None or quote.delayed or not 0 <= now-(quote.source_ts or quote.ts) <= \
                float(self.engine.settings.get("risk.stale_quote_seconds", 10))*1000 \
                or not all(math.isfinite(v) for v in (quote.bid, quote.ask)) \
                or not 0 < quote.bid <= quote.ask <= intent.limit_price:
            raise ValueError("vehicle quote changed during preflight; fresh evaluation required")
        if spec.instrument == "options":
            snapshot = self.engine.options.snapshot_cached(intent.symbol) or {}
            delta = (snapshot.get("greeks") or {}).get("delta")
            stamp = (snapshot.get("greeksFieldAsOf") or {}).get("delta")
            if not isinstance(delta, (int, float)) or isinstance(delta, bool) or not math.isfinite(delta) \
                    or not spec.min_abs_delta <= abs(delta) <= 1 or (delta <= 0 if plan.direction == "long" else delta >= 0) \
                    or not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not 0 <= now-stamp <= 120_000:
                raise ValueError("option delta changed or expired during preflight")

    async def _reconciled(self, run_id, spec, plan):
        report = await execution_readiness(self.engine, spec.portfolio_id, plan.symbol, ignore_attempt_run_id=run_id)
        if not report["passed"]:
            raise ValueError("Prior execution needs reconciliation: " + "; ".join(b["reason"] for b in report["blockers"]))
        losses = await loss_gate(self.engine, spec.portfolio_id, now_ms=self.clock())
        if not losses["passed"]:
            raise ValueError(losses["reason"])

    async def submit(self, run_id, *, approval_signal_id=None):
        prepared = await self._prepare_submission(run_id, approval_signal_id=approval_signal_id)
        if not isinstance(prepared, OrderIntent):
            return prepared
        try:
            await self.engine.orders.place(prepared)
        except Exception as exc:  # noqa: BLE001 - reconcile unknown submission outcomes
            async with self.engine.sf() as session, session.begin():
                locked = await self.repository._locked(session, run_id)
                locked.state = {**locked.state, "submissionError": f"{type(exc).__name__}: {exc}"}
        finally:
            _inflight.setdefault(self.engine, set()).discard(run_id)
        result = await self.poll(run_id)
        return {**result, "submissionAttempted": True, "placesEntryOrders": True}

    async def _prepare_submission(self, run_id, *, approval_signal_id=None):
        async with self._guard(run_id):
            row = await self.repository.load(run_id)
            if row is None:
                raise KeyError("Cartel armed record not found")
            if row["state"].get("attemptTag"):
                return await self._poll(run_id)
            spec = ExecutionInput.model_validate(row["config"].get("execution") or {})
            async with self.engine.sf() as session:
                run = await session.scalar(select(TechniqueRun).where(TechniqueRun.id == run_id,
                                                                      TechniqueRun.technique == "options_cartel"))
            plan = reviewed_execution_plan(run)
            priced = self._entry_conditions(row, plan, spec)
            client = row["config"].get("clientKind", "desktop")
            if client not in ("desktop", "tablet", "phone"):
                raise ValueError("invalid reviewed client kind")
            report = await preflight(self.engine, priced, spec, client_kind=client, clock=self.clock)
            await self.engine.journal.append(ev.OPTIONS_CARTEL_PREFLIGHT,
                {"runId": run_id, "symbol": plan.symbol, "portfolioId": spec.portfolio_id, "report": report},
                aggregate_type="technique_run", aggregate_id=run_id, portfolio_id=spec.portfolio_id)
            if not report["passed"]:
                return {"runId": run_id, "status": "preflight_rejected", "report": report, "placesEntryOrders": False}
            if row["mode"] == "proposal" and approval_signal_id != row["state"]["signal"]["id"]:
                return {"runId": run_id, "status": "awaiting_approval", "report": report, "placesEntryOrders": False}
            latest = await self.repository.load(run_id)
            await self._reconciled(run_id, spec, plan)
            self._entry_conditions(latest, plan, spec)
            intent = OrderIntent.model_validate(report["intent"]).model_copy(update={"dry_run": False})
            self._vehicle_conditions(intent, spec, plan)
            reserved = await self.repository.reserve_submission(run_id, intent)
            if reserved is None:
                return await self._poll(run_id)
            try:
                latest = await self.repository.load(run_id)
                await self._reconciled(run_id, spec, plan)
                self._entry_conditions(latest, plan, spec)
                self._vehicle_conditions(reserved, spec, plan)
            except ValueError as exc:
                async with self.engine.sf() as session, session.begin():
                    locked = await self.repository._locked(session, run_id)
                    locked.status = "disarmed"
                    locked.state = {**locked.state, "phase": "closed", "submissionAborted": True,
                                    "abortReason": str(exc)}
                    snapshot = self.repository.view(locked)
                await self.repository._journal(snapshot, "submission_aborted_before_routing")
                return {"runId": run_id, "status": "pre_submit_rejected", "reason": str(exc), "placesEntryOrders": False}
            # Release the reservation mutex before broker I/O so incoming partial
            # fills can be protected while the submission response is still pending.
            _inflight.setdefault(self.engine, set()).add(run_id)
            return reserved

    async def poll(self, run_id, *, request_cancel=False):
        async with self._guard(run_id):
            return await self._poll(run_id, request_cancel=request_cancel)

    async def _poll(self, run_id, *, request_cancel=False):
        row = await self.repository.load(run_id)
        if row is None:
            raise KeyError("Cartel armed record not found")
        if row["state"].get("submissionAborted"):
            return {"runId": run_id, "status": "pre_submit_rejected", "placesEntryOrders": False}
        if not row["state"].get("attemptTag"):
            return {"runId": run_id, "status": row["state"]["phase"], "placesEntryOrders": False}
        if not row["state"].get("orderId"):
            if run_id in _inflight.get(self.engine, set()):
                from ...models import Order
                async with self.engine.sf() as session:
                    orders = (await session.scalars(select(Order).where(Order.technique == "options_cartel",
                        Order.portfolio_id == row["portfolioId"], Order.side == "BUY"))).all()
                if not any(row["state"]["attemptTag"] in (order.tags or []) for order in orders):
                    return {"runId": run_id, "status": "submitting", "placesEntryOrders": False}
            row = await self.repository.reconcile_submission(run_id)
        if not row["state"].get("orderId"):
            return {"runId": run_id, "status": "needs_attention", "reason": row["state"].get("recoveryReason"),
                    "placesEntryOrders": False}
        return await settle_entry(self.engine, run_id, request_cancel=request_cancel, wait_seconds=0)
