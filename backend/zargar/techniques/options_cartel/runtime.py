"""Live Cartel observation and execution lifecycle on the shared engine loops."""
from __future__ import annotations

import asyncio
import datetime as dt
import math

from sqlalchemy import select

from ...execution.planrunner import Trade
from ...marketstructure.sessions import session_bounds, session_date
from ...models import ManagedPositionRow, Portfolio, TechniqueArmed, TechniqueRun
from ...options.occ import parse
from .controller import CartelEntryController, reviewed_execution_plan
from .execution import ExecutionInput
from .loss import loss_gate
from .observer import CartelObserver


class CartelRuntime(CartelObserver):
    OBSERVED_MODES = ("alert", "proposal", "auto")

    def __init__(self, engine):
        super().__init__(engine)
        self.controller = CartelEntryController(engine)
        self.controller.clock = lambda: self.clock()
        self.fires = {}
        self.polls = {}
        self.dirty = set()
        self.stopping = False
        self.position_views = {}
        self.preparation_quote_task = None
        self.preparation_quote_at = 0
        self.preparation_quote_status = {}
        self.preparation_activation_task = None
        self.preparation_activation_at = 0
        from .quote_observations import QuoteRecorder
        from .service import CartelService
        self.quote_recorder = QuoteRecorder(CartelService(engine), clock=lambda: self.clock())

    async def arm(self, run_id, config=None):
        if self.stopping:
            raise ValueError("Cartel runtime is stopping")
        config = config or {}
        if config.get("mode", "alert") == "alert":
            return await super().arm(run_id, config)
        spec = ExecutionInput.model_validate(config.get("execution") or {})
        if config.get("clientKind", "desktop") not in ("desktop", "tablet", "phone"):
            raise ValueError("invalid client kind")
        loss_pct = float(self.engine.settings.get("risk.daily_loss_halt_pct", 0) or 0)
        if spec.mode == "auto" and (not math.isfinite(loss_pct) or loss_pct <= 0):
            raise ValueError("auto arming requires an enabled book daily-loss halt")
        if config.get("mode") != spec.mode or config.get("portfolioId") != spec.portfolio_id:
            raise ValueError("execution configuration must match arm mode and account")
        if self.engine.settings.get("techniques.options_cartel.paused", False) \
                or not self.engine.settings.get("techniques.options_cartel.enabled", True):
            raise ValueError("Cartel is paused or disabled")
        async with self.engine.sf() as session:
            portfolio = await session.get(Portfolio, spec.portfolio_id)
            plan = reviewed_execution_plan(await session.get(TechniqueRun, run_id))
        if not plan.created_at <= self.clock() < session_bounds(plan.last_session.isoformat())[1]:
            raise ValueError("plan horizon is not valid for arming")
        if portfolio is None:
            raise ValueError("portfolio not found")
        from .accounts import validate_account
        validate_account(self.engine, portfolio)
        if config.get('preparation'):
            from .preparation_scope import read_policy, require_execution_scope
            scope = config['preparation'].get('workspace', 'practice')
            if portfolio.kind not in (('sim',) if scope == 'practice' else ('live', 'paper')):
                raise ValueError('Prepared plan account does not belong to its workspace')
            require_execution_scope(self.engine, read_policy(self.engine, scope))
        cached = self.engine.positions.portfolio(spec.portfolio_id)
        if cached is None or cached["kind"] != portfolio.kind:
            raise ValueError("refresh portfolio identity before arming")
        if portfolio.kind in ("live", "paper"):
            if config.get("clientKind") == "phone" and self.engine.settings.get("mobile.exit_only", True):
                raise ValueError("phones are exit-only on real accounts")
            if not spec.allow_live or self.engine.settings.get("trading.mode") != "live" \
                    or spec.mode == "auto" and not self.engine.settings.get("techniques.options_cartel.allow_live_auto", False):
                raise ValueError("real-account arming requires live permissions and acknowledgement")
            executor = self.engine.executor_for(self.engine.positions.portfolio(spec.portfolio_id))
            if executor is None or not executor.connected:
                raise ValueError("real-account arming requires a connected broker")
        if spec.instrument == "options" and (not spec.contract_symbol or not spec.overnight_ack):
            raise ValueError("options require a reviewed contract and overnight acknowledgement")
        if spec.instrument == "options":
            contract = parse(spec.contract_symbol)
            if contract is None or contract.underlying != plan.symbol or contract.right != ("C" if plan.direction == "long" else "P"):
                raise ValueError("reviewed option must match the plan's underlying and direction")
            if contract.dte(dt.date.fromisoformat(session_date(self.clock()))) <= max(1, int(self.engine.settings.get("execution.min_dte", 1))):
                raise ValueError("reviewed contract has reached the entry expiry floor")
        elif plan.direction != "long":
            raise ValueError("bearish Cartel plans require long puts")
        if self.engine.orders is None:
            raise ValueError("order service has not started")
        existing = await self.repository.load(run_id)
        if existing is not None and existing["status"] not in ("armed", "paused"):
            raise ValueError("retired or closing plans require a new reviewed arm")
        if existing is not None and existing["config"] != config:
            async with self.engine.sf() as session, session.begin():
                stored = await self.repository._locked(session, run_id)
                if stored.status not in ("armed", "paused") or stored.state.get("attemptTag"):
                    raise ValueError("execution settings cannot replace a retired or submitted arm")
                prior = [*stored.state.get("configHistory", []), {"at": self.clock(), "config": stored.config,
                                                                 "signal": stored.state.get("signal")}]
                stored.config, stored.mode, stored.portfolio_id, stored.status = config, spec.mode, spec.portfolio_id, "armed"
                stored.state = {**stored.state, "configHistory": prior[-20:], "signal": None, "phase": "waiting",
                                "approvedSignalId": None, "observeAfter": self.clock(), "runtimeError": None}
                row = self.repository.view(stored)
            await self.repository._journal(row, "execution_settings_reviewed")
        else:
            row = await self.repository.arm(run_id, spec.portfolio_id, spec.mode, config, now_ms=self.clock())
        await self._remember(row)
        await self._prepare_observation(run_id, advance_cutoff=False)
        if spec.contract_symbol and getattr(self.engine, "options", None) is not None:
            try:
                await self.engine.options.track(spec.contract_symbol)
            except Exception as exc:  # noqa: BLE001 - report feed warmup failure without creating an order
                await self._error(run_id, exc)
        self.start()
        self._publish(run_id)
        return self.detail(run_id)

    async def restore(self):
        async with self.engine.sf() as session:
            rows = (await session.scalars(select(TechniqueArmed).where(TechniqueArmed.technique == self.TECHNIQUE_ID))).all()
        for stored in rows:
            book = self.engine.positions.portfolio(stored.portfolio_id)
            if book and book.get('archived'):
                continue
            row = self.repository.view(stored)
            if row["status"] not in ("armed", "paused", "closing") and not row["state"].get("orderId"):
                continue
            await self._remember(row)
            await self._load_positions(row["runId"])
            if row["state"].get("orderId"):
                self.register_order(row["state"]["orderId"], row["runId"])
            if row["status"] in ("armed", "paused") and row["state"]["phase"] == "waiting":
                await self._prepare_observation(row["runId"], advance_cutoff=True)
        await self.on_heartbeat()
        return len(self.armed())

    def watches_order(self, order):
        return super().watches_order(order) or order.get("technique") == self.TECHNIQUE_ID

    async def on_order(self, order):
        run_id = self.owner_of(order.get("id"))
        if run_id is None:
            ids = [tag.removeprefix("cartel_run:") for tag in order.get("tags", []) if tag.startswith("cartel_run:")]
            if len(ids) != 1 or ids[0] not in self.rows:
                return
            run_id = ids[0]
            if order.get("portfolioId") != self.rows[run_id]["portfolioId"]:
                return
            self.register_order(order["id"], run_id)
        if self.rows[run_id]["mode"] != "alert":
            self._schedule_poll(run_id)

    async def after_signal(self, run_id):
        if self.rows[run_id]["mode"] in ("auto", "proposal"):
            self._schedule_fire(run_id)

    def _schedule_fire(self, run_id, approval=None):
        if not self.stopping and (run_id not in self.fires or self.fires[run_id].done()):
            self.fires[run_id] = asyncio.create_task(self._fire(run_id, approval), name=f"cartel-fire-{run_id}")

    def _schedule_poll(self, run_id):
        if self.stopping:
            return
        self.dirty.add(run_id)
        if run_id not in self.polls or self.polls[run_id].done():
            self.polls[run_id] = asyncio.create_task(self._poll_loop(run_id), name=f"cartel-poll-{run_id}")

    async def _error(self, run_id, error):
        async with self.engine.sf() as session, session.begin():
            row = await self.repository._locked(session, run_id)
            row.state = {**row.state, "runtimeError": str(error)}
            snapshot = self.repository.view(row)
        self.rows[run_id] = snapshot
        await self.repository._journal(snapshot, "runtime_attention")
        self._publish(run_id)

    async def _reload(self, run_id, result=None):
        if result is not None:
            reason = result.get("reason")
            if result.get("status") == "preflight_rejected":
                report = result.get("report") or {}
                reasons = [c["reason"] for c in report.get("checks", []) if not c["passed"]]
                reasons += [c.get("detail") or c["name"] for c in (report.get("risk") or {}).get("checks", []) if not c["passed"]]
                reason = "Entry checks blocked: " + "; ".join(reasons)
            async with self.engine.sf() as session, session.begin():
                row = await self.repository._locked(session, run_id)
                row.state = {**row.state, "lastExecutionResult": result,
                             "runtimeError": reason if result.get("status") in
                             ("needs_attention", "pre_submit_rejected", "preflight_rejected") else None}
        self.rows[run_id] = await self.repository.load(run_id)
        await self._load_positions(run_id)
        self._publish(run_id)

    async def _load_positions(self, run_id):
        async with self.engine.sf() as session:
            rows = (await session.scalars(select(ManagedPositionRow).where(
                ManagedPositionRow.technique == self.TECHNIQUE_ID,
                ManagedPositionRow.portfolio_id == self.rows[run_id]["portfolioId"],
                ManagedPositionRow.config["runId"].as_string() == run_id))).all()
        self.position_views[run_id] = [self.engine.position_manager._from_row(row).to_dict() for row in rows]

    async def load_detail(self, run_id):
        row = await self.repository.load(run_id)
        if row is None:
            return None
        book = self.engine.positions.portfolio(row['portfolioId'])
        if book and book.get('archived'):
            return None  # Historical run APIs remain available; a read must not restore observation.
        await self._remember(row)
        await self._load_positions(run_id)
        return self.detail(run_id)

    async def _fire(self, run_id, approval):
        try:
            await self._reload(run_id, await self.controller.submit(run_id, approval_signal_id=approval))
        except Exception as exc:  # noqa: BLE001 - failures must remain visible and durable
            await self._error(run_id, exc)

    async def _poll_loop(self, run_id):
        while run_id in self.dirty:
            self.dirty.discard(run_id)
            try:
                row = await self.repository.load(run_id)
                cancel = row["status"] != "armed" or self.clock() >= row["state"]["expiresAt"]
                result = await self.controller.poll(run_id, request_cancel=cancel)
                if row["state"].get("flattenRequested"):
                    for p in self._positions(run_id):
                        await self.engine.position_manager.close(p["id"], force_market=True, reason="Cartel flatten requested")
                await self._reload(run_id, result)
            except Exception as exc:  # noqa: BLE001
                await self._error(run_id, exc)

    async def approve(self, run_id, signal_id):
        if self.stopping:
            raise ValueError("Cartel runtime is stopping")
        row = await self.repository.load(run_id)
        if row is None or row["mode"] != "proposal" or row["status"] != "armed" \
                or (row["state"].get("signal") or {}).get("id") != signal_id:
            raise ValueError("approval must match this armed proposal's current signal")
        async with self.engine.sf() as session, session.begin():
            stored = await self.repository._locked(session, run_id)
            if stored.status != "armed" or stored.mode != "proposal" or stored.state["phase"] != "signalled" \
                    or (stored.state.get("signal") or {}).get("id") != signal_id \
                    or not 0 <= self.clock()-stored.state["signal"]["at"] <= 120_000:
                raise ValueError("proposal changed before approval could be recorded")
            stored.state = {**stored.state, "approvedSignalId": signal_id}
            snapshot = self.repository.view(stored)
        await self.repository._journal(snapshot, "proposal_approved")
        pending = self.fires.get(run_id)
        if pending is not None and not pending.done():
            await asyncio.shield(pending)
        self._schedule_fire(run_id, signal_id)
        await asyncio.shield(self.fires[run_id])
        return self.detail(run_id)

    def _positions(self, run_id, include_closed=False):
        views = {p["id"]: p for p in self.position_views.get(run_id, [])}
        views.update({p["id"]: p for p in self.engine.position_manager.positions()
                      if p["technique"] == self.TECHNIQUE_ID and p["runId"] == run_id
                      and p["portfolioId"] == self.rows[run_id]["portfolioId"]})
        return [p for p in views.values() if include_closed or p["status"] != "closed"]

    async def disarm(self, run_id, *, reason="manual", flatten=False):
        row = self.rows.get(run_id)
        if row is None:
            return False
        if row["mode"] == "alert":
            return await super().disarm(run_id, reason=reason, flatten=flatten)
        if flatten:
            async with self.engine.sf() as session, session.begin():
                stored = await self.repository._locked(session, run_id)
                stored.state = {**stored.state, "flattenRequested": True}
        self.rows[run_id] = await self.repository.set_status(run_id, "disarmed")
        self._schedule_poll(run_id)
        self._publish(run_id)
        return True

    async def stop_all(self, *, flatten=False, reason="stop all"):
        ids = [rid for rid, row in self.rows.items() if row["status"] in ("armed", "paused", "closing")]
        for rid in ids:
            await self.disarm(rid, reason=reason, flatten=flatten)
        return len(ids)

    async def set_mode(self, run_id, mode=None, **kwargs):
        row = self.rows.get(run_id)
        if row is None:
            raise KeyError("Cartel plan is not active")
        if mode is None or mode == row["mode"]:
            return self.detail(run_id)
        if mode not in ("proposal", "auto") or "execution" not in row["config"]:
            raise ValueError("Review execution settings on the Cartel plan before changing its mode")
        config = {**row["config"], "mode": mode,
                  "execution": {**row["config"]["execution"], "mode": mode}}
        return await self.arm(run_id, config)

    async def pause(self, run_id):
        if run_id in self.rows and self.rows[run_id]["status"] == "closing":
            return self.detail(run_id)  # no new entry remains to pause; protection continues
        result = await super().pause(run_id)
        if self.rows[run_id]["mode"] != "alert" and self.rows[run_id]["state"].get("attemptTag"):
            self._schedule_poll(run_id)
        return result

    async def resume(self, run_id):
        row = self.rows.get(run_id)
        if row and row["status"] == "paused" and row["mode"] != "alert" and not row["state"].get("attemptTag"):
            await self._reset_signal(run_id, "resumed_waiting_for_fresh_signal")
        return await super().resume(run_id)

    async def _reset_signal(self, run_id, action):
        async with self.engine.sf() as session, session.begin():
            row = await self.repository._locked(session, run_id)
            if row.state.get("attemptTag") or row.status not in ("armed", "paused"):
                self.rows[run_id] = self.repository.view(row)
                return
            history = list(row.state.get("signalHistory", []))
            if row.state.get("signal"):
                history.append(row.state["signal"])
            row.state = {**row.state, "signal": None, "phase": "waiting", "observeAfter": self.clock(),
                         "approvedSignalId": None, "signalHistory": history[-20:], "runtimeError": None}
            snapshot = self.repository.view(row)
        self.rows[run_id] = snapshot
        await self.repository._journal(snapshot, action)

    async def on_heartbeat(self):
        loss_reports = {}
        for rid, row in list(self.rows.items()):
            if row["mode"] == "alert":
                if self.clock() >= row["state"]["expiresAt"] and row["status"] in ("armed", "paused"):
                    self.rows[rid] = await self.repository.set_status(rid, "expired")
                    self._publish(rid)
                continue
            state = row["state"]
            preparation = row.get('config', {}).get('preparation')
            if preparation and row['status'] in ('armed', 'paused') and not state.get('attemptTag') and self.clock() >= preparation.get('validUntil', 0):
                self.rows[rid] = await self.repository.set_status(rid, 'expired')
                self._publish(rid)
                continue
            if state.get("attemptTag") and row["status"] in ("armed", "paused", "closing"):
                self._schedule_poll(rid)
            elif row["status"] in ("armed", "paused"):
                if self.clock() >= state["expiresAt"]:
                    self.rows[rid] = await self.repository.set_status(rid, "expired")
                elif state.get("signal"):
                    if self.clock()-state["signal"]["at"] > 120_000:
                        await self._reset_signal(rid, "signal_expired")
                    elif row["status"] == "armed" and (row["mode"] == "auto" or state.get("approvedSignalId")):
                        self._schedule_fire(rid, state.get("approvedSignalId"))
            if row["status"] == "armed":
                pid = row["portfolioId"]
                if pid not in loss_reports:
                    loss_reports[pid] = await loss_gate(self.engine, pid, now_ms=self.clock())
                if loss_reports[pid].get("latched"):
                    await self.pause(rid)
                    await self._error(rid, "Cartel daily loss halt is latched for this book.")
            self._publish(rid)

    async def on_quote_watch(self):
        self.quote_recorder.observe(list(self.rows.values()))
        from .preparation_scope import active_workspace, setting_key
        scope = active_workspace(self.engine)
        preparation_settings = self.engine.settings.get(setting_key(scope), {})
        if isinstance(preparation_settings, dict) and preparation_settings.get('enabled') and not self.stopping \
                and self.clock()-self.preparation_activation_at >= 60_000 \
                and (self.preparation_activation_task is None or self.preparation_activation_task.done()):
            from .preparation import activate_pending
            self.preparation_activation_at = self.clock()
            self.preparation_activation_workspace = scope
            self.preparation_activation_task = asyncio.create_task(self._activate_preparation(activate_pending))
        if not self.stopping and self.clock()-self.preparation_quote_at >= 30_000 \
                and (self.preparation_quote_task is None or self.preparation_quote_task.done()):
            contracts = {row['config']['execution'].get('contract_symbol') for row in self.rows.values()
                         if row.get('config', {}).get('preparation') and row['status'] in ('armed', 'paused', 'closing')}
            contracts.discard(None)
            if contracts:
                self.preparation_quote_at = self.clock()
                self.preparation_quote_task = asyncio.create_task(self._refresh_preparation_quotes(contracts))
        # Reconciliation only; new entries are never triggered from quote ticks.
        for rid, row in list(self.rows.items()):
            if row["mode"] != "alert" and row["status"] in ("armed", "paused", "closing") and row["state"].get("attemptTag"):
                self._schedule_poll(rid)

    async def _refresh_preparation_quotes(self, contracts):
        errors = {}
        for contract in contracts:
            if self.stopping:
                break
            try:
                await self.engine.options.reprice({'symbol': contract})
            except Exception as exc:  # noqa: BLE001 - data refresh cannot interrupt execution
                errors[contract] = f'{type(exc).__name__}: option data refresh unavailable'
        self.preparation_quote_status = {'at': self.clock(), 'errors': errors}

    async def _activate_preparation(self, activate):
        try:
            await activate(self.engine, clock=self.clock)
        except Exception as exc:  # noqa: BLE001 - report preparation failures without interrupting orders
            if not hasattr(self.engine, '_cartel_preparation_activations'):
                self.engine._cartel_preparation_activations = {}
            self.engine._cartel_preparation_activations[self.preparation_activation_workspace] = {'at': self.clock(), 'error': f'{type(exc).__name__}: activation unavailable'}

    async def flatten_trade(self, run_id, trigger_id=None):
        positions = self._positions(run_id)
        for p in positions:
            await self.engine.position_manager.close(p["id"], force_market=True, reason="Cartel flatten")
        if positions:
            self._schedule_poll(run_id)
            return self.detail(run_id)
        return None

    async def wait_idle(self):
        while True:
            pending = [t for t in [*self.fires.values(), *self.polls.values()] if not t.done()]
            if not pending:
                return
            await asyncio.shield(asyncio.gather(*pending))

    async def stop(self):
        self.stopping = True
        from .preparation import stop_preparation
        await stop_preparation(self.engine)
        if self.preparation_activation_task is not None and not self.preparation_activation_task.done():
            self.preparation_activation_task.cancel()
            await asyncio.gather(self.preparation_activation_task, return_exceptions=True)
        if self.preparation_quote_task is not None and not self.preparation_quote_task.done():
            self.preparation_quote_task.cancel()
            await asyncio.gather(self.preparation_quote_task, return_exceptions=True)
        await self.quote_recorder.stop()
        from .jobs import unregister_jobs
        unregister_jobs(self.engine)
        from .scan_tasks import stop_background_scans
        await stop_background_scans(self.engine)
        await self.wait_idle()  # never cancel a task while its order outcome is unknown
        await super().stop()

    def armed(self, *, slim=False):
        return [self.detail(rid) for rid, row in self.rows.items() if row["status"] in ("armed", "paused", "closing")]

    def summary(self):
        result = super().summary()
        details = {row["runId"]: row for row in self.armed()}
        for item in [*result["watching"], *result["attention"]]:
            detail = details[item["runId"]]
            item.update(mode=detail["config"]["mode"], instrument=detail["config"]["instrument"])
            if "hasPosition" in item:
                item["hasPosition"] = detail["openPositions"] > 0
        for item in result["timeline"]:
            mode = details[item["runId"]]["config"]["mode"]
            if mode != "alert":
                item.update(kind="cartel_signal", text=f"Cartel entry condition confirmed ({mode}).")
        for rid, detail in details.items():
            for trade in detail["trades"]:
                if trade["remaining"] <= 0:
                    continue
                unreal = trade["unrealizedPnl"]
                result["inTrade"].append({**trade, "runId": rid, "symbol": detail["symbol"], "technique": self.TECHNIQUE_ID,
                    "status": detail["status"], "mode": detail["config"]["mode"], "instrument": trade["instrument"],
                    "workspace": detail["portfolio"].get("kind"), "account": detail["portfolio"].get("name"),
                    "stale": unreal is None, "lastPrice": detail["lastPrice"],
                    "entry": trade["avgFill"], "underlyingEntry": trade["entry"], "nextTarget": trade["targets"][0],
                    "unrealizedPnl": unreal, "unrealizedR": None, "tradeStatus": trade["status"],
                    "pnlBasis": "gross managed P&L; daily risk report includes recorded fees"})
        result["counts"]["inTrade"] = len(result["inTrade"])
        return result

    def detail(self, run_id):
        result = super().detail(run_id)
        if result is None or self.rows[run_id]["mode"] == "alert":
            return result
        row = self.rows[run_id]
        state = row["state"]
        spec = ExecutionInput.model_validate(row["config"]["execution"])
        result["config"].update(mode=row["mode"], instrument=spec.instrument, riskPct=spec.risk_pct,
                                premiumBudget=spec.budget, allowLive=spec.allow_live, maxQty=spec.max_units,
                                maxContracts=spec.max_units, contracts=None, flattenMinutesBeforeClose=0,
                                management="durable", lossHaltPolicy="required")
        result["reviewerAvailable"] = False
        positions = self._positions(run_id)
        signal = state.get("signal") or {}
        trades = []
        for p in self._positions(run_id, include_closed=True):
            leg = p["legs"][0]
            trade = Trade(trigger_id=p["id"], kind="cartel", fired_ts=signal.get("at", p["openedMs"]),
                window="regular", entry=p["entry"], stop=p["state"].get("stop") or p["policy"]["stop"]["price"],
                targets=list(self.plans[run_id].targets), status="closed" if p["status"] == "closed" else "open",
                direction=p["direction"], instrument=spec.instrument, order_symbol=leg["symbol"],
                multiplier=leg["multiplier"], filled_qty=p["policy"]["cartel"]["initialQty"], remaining=leg["qty"],
                avg_fill=leg["avgFill"], qty=p["policy"]["cartel"]["initialQty"], exits=p["exits"],
                realized_pnl=p["realizedPnl"], opened_ts=p["openedMs"], closed_ts=p["closedMs"],
                contract=parse(leg["symbol"]).to_dict() if spec.instrument == "options" else None)
            view = trade.to_dict()
            quote = self.engine.quotes.get(leg["symbol"])
            mark = None
            if quote is not None and not quote.delayed and math.isfinite(quote.bid) and quote.bid > 0 \
                    and 0 <= self.clock()-(quote.source_ts or quote.ts) <= float(self.engine.settings.get("risk.stale_quote_seconds", 10))*1000:
                mark = (quote.bid-leg["avgFill"])*leg["qty"]*leg["multiplier"]
            view["unrealizedPnl"] = mark if leg["qty"] else 0.
            trades.append(view)
        result.update(executionAvailable=True, execution=state.get("lastExecutionResult"), managedPositions=positions,
                      executionSettings=spec.model_dump(mode="json", by_alias=True), submissionReserved=bool(state.get("attemptTag")),
                      openPositions=len(positions), trades=trades, fired=trades,
                      awaitingApproval=row["mode"] == "proposal" and row["status"] == "armed" and state["phase"] == "signalled"
                      and not state.get("attemptTag") and 0 <= self.clock()-signal.get("at", -1) <= 120_000)
        reasons = [state[k] for k in ("runtimeError", "observationError") if state.get(k)]
        reasons.extend(message for p in positions for message in p["attention"])
        result.update(needsAttention=bool(reasons), attentionReasons=reasons,
                      summary=reasons[0] if reasons else "Managing confirmed Cartel exposure." if positions else
                      f"Cartel {row['mode']} is paused." if row["status"] == "paused" else
                      "Cartel signal awaits approval." if result["awaitingApproval"] else
                      "Entry window expired without a purchase." if row['status'] == 'expired' and not state.get('signal') else
                      "Last entry check: " + state['decisionHistory'][-1]['reason'] if state.get('decisionHistory') else
                      f"Cartel {row['mode']}: {state['phase']}.")
        return result
