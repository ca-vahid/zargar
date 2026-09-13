"""Live alert observation using shared listener/Armed DTOs and durable Cartel state.

This is the alert lane. Money modes remain unavailable until the entry controller
can protect working partials and reconcile every submission/adoption boundary.
"""
from __future__ import annotations

import datetime as dt
import time

from sqlalchemy import select

from ... import bus as topics
from ...domain import Bar
from ...execution.listener import SessionListener
from ...execution.planrunner import ArmConfig, ArmedPlan
from ...marketstructure.aggregate import bar_session
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import session_bounds, session_date
from ...models import BarRow, Event, TechniqueRun
from .data_quality import evidence, merge, unpack
from .entry import read_entry
from .observation_health import coverage, recovery_record
from .plans import CartelPlan
from .preparation_readiness import baseline_coverage, retain_decisions
from .state import ArmRepository


class CartelObserver(SessionListener):
    TECHNIQUE_ID = "options_cartel"
    OBSERVED_MODES = ("alert",)

    def __init__(self, engine):
        super().__init__(engine, name="cartel-observer")
        self.repository = ArmRepository(engine)
        self.rows = {}
        self.plans = {}
        self.clock = lambda: int(time.time()*1000)

    @property
    def armer(self):
        return self

    async def _remember(self, row):
        async with self.engine.sf() as session:
            run = await session.scalar(select(TechniqueRun).where(TechniqueRun.id == row["runId"],
                                                                  TechniqueRun.technique == self.TECHNIQUE_ID))
        if run is None:
            raise ValueError("owned Cartel plan missing during restore")
        self.plans[row["runId"]] = CartelPlan.model_validate(run.result["plan"]["plan"])
        self.rows[row["runId"]] = row

    async def restore(self):
        rows = await self.repository.active()
        for row in rows:
            if row["mode"] != "alert":
                raise RuntimeError("money-mode Cartel state requires the unfinished execution controller")
            await self._remember(row)
            await self._prepare_observation(row["runId"], advance_cutoff=True)
        await self.on_heartbeat()
        return len(self.rows)

    async def arm(self, run_id, config=None):
        config = config or {}
        if config.get("mode", "alert") != "alert":
            raise ValueError("Only alert observation is currently available; money-mode integration is unfinished")
        if self.engine.settings.get("techniques.options_cartel.paused", False) \
                or not self.engine.settings.get("techniques.options_cartel.enabled", True):
            raise ValueError("Cartel is paused or disabled")
        row = await self.repository.arm(run_id, config.get("portfolioId", ""), "alert", config, now_ms=self.clock())
        await self._remember(row)
        await self._prepare_observation(run_id, advance_cutoff=False)
        self.start()
        self._publish(run_id)
        return self.detail(run_id)

    async def _prepare_observation(self, run_id, *, advance_cutoff):
        """Recover context without replaying a crossing missed while observation was off."""
        try:
            await self.engine.ensure_symbol(self.rows[run_id]["symbol"])
            await self._seed_session(run_id, advance_cutoff=advance_cutoff)
        except Exception as exc:  # noqa: BLE001 - persist a visible pause at the data-service boundary
            async with self.engine.sf() as session, session.begin():
                locked = await self.repository._locked(session, run_id)
                if locked.status in ("armed", "paused"):
                    locked.status = "paused"
                    locked.state = {**locked.state, "observationError":
                                    f"Market data recovery failed: {exc}. Resume to retry."}
                snapshot = self.repository.view(locked)
            self.rows[run_id] = snapshot
            await self.repository._journal(snapshot, "observation_recovery_failed")
            self._publish(run_id)
            return False
        return True

    async def _seed_session(self, run_id, *, advance_cutoff):
        now = self.clock()
        day = session_date(now)
        opens, closes = session_bounds(day)
        symbol = self.rows[run_id]["symbol"]
        async with self.engine.sf() as session, session.begin():
            stored = (await session.scalars(select(BarRow).where(BarRow.symbol == symbol, BarRow.tf == "1m",
                                                                BarRow.ts >= opens, BarRow.ts < closes,
                                                                BarRow.ts+60_000 <= now))).all()
            locked = await self.repository._locked(session, run_id)
            minutes = dict(locked.state.get('minutes', {})) if locked.state.get('day') == day else {}
            for b in stored:
                merge(minutes, Bar(b.symbol, b.tf, b.ts, b.open, b.high, b.low, b.close, b.volume, source=b.source))
            for b in self.engine.bars.bars(symbol, tf="1m", limit=1000, include_forming=False):
                if opens <= b.ts < closes and b.ts+60_000 <= now:
                    merge(minutes, b)
            for values in locked.config.get('preparation', {}).get('contextMinutes', []):
                if opens <= values[0] < closes and values[0]+60_000 <= now:
                    merge(minutes, unpack(symbol, values))
            previous_state = locked.state
            cutoff = locked.state.get("observeAfter", locked.state["armedAt"])
            if advance_cutoff:
                cutoff = max(cutoff, now)
            locked.state = {**locked.state, "day": day, "minutes": minutes,
                            "observeAfter": cutoff, "observationError": None}
            if advance_cutoff:
                locked.state = {**locked.state, 'observationRecoveries': recovery_record(previous_state, now=now,
                    reason='restore_or_resume', added=max(0, len(minutes)-len(previous_state.get('minutes', {}))))}
            seeded = self.repository.view(locked)
        self.rows[run_id] = seeded
        if advance_cutoff:
            await self.repository._journal(seeded, "observation_recovered")

    def get(self, run_id):
        return self.rows.get(run_id)

    def detail(self, run_id):
        row = self.rows.get(run_id)
        if row is None:
            return None
        plan = self.plans[run_id]
        state = row["state"]
        sessions = [plan.first_session+dt.timedelta(days=i) for i in range((plan.last_session-plan.first_session).days+1)
                    if is_trading_day(plan.first_session+dt.timedelta(days=i))]
        today = dt.date.fromisoformat(session_date(self.clock()))
        dto = ArmedPlan(run_id=run_id, symbol=plan.symbol, plan=plan.model_dump(mode="json"),
                        plan_for=row["planFor"], config=ArmConfig(portfolio_id=row["portfolioId"], mode="alert",
                                                                 instrument="options", use_critic=False),
                        trackers={}, armed_at=state["armedAt"]/1000, technique=self.TECHNIQUE_ID,
                        status=row["status"], expires_session=plan.last_session.isoformat())
        dto.horizon_sessions = len(sessions)
        dto.sessions_used = sum(d < today for d in sessions)
        dto.last_bar_ts = state.get("lastMinute")
        dto.bar_index = len(state.get("minutes", {}))
        result = dto.to_dict(portfolio=self.engine.positions.portfolio(row["portfolioId"]),
                             quote=self.engine.quotes.get(plan.symbol), now_ms=self.clock())
        result.update(volumeCoverage=baseline_coverage(plan), observationHealth=coverage(state, self.clock(), day=session_date(self.clock()) if self._window_open(run_id) else None), decisionHistory=state.get("decisionHistory", []), observation=state.get("observation"), signal=state.get("signal"),
                      phase=state["phase"], executionAvailable=False)
        trigger = {"id": "cartel_entry", "label": "Cartel entry",
                   "kind": "breakdown" if plan.direction == "short" and plan.entry.mode == "breakout" else plan.entry.mode,
                   "status": "invalidated" if (state.get("observation") or {}).get("status") == "invalidated" else
                             "fired" if state.get("signal") else "waiting",
                   "entry": plan.trigger, "stop": plan.invalidation, "targets": list(plan.targets),
                   "direction": plan.direction, "firedTs": (state.get("signal") or {}).get("at"),
                   "windowOpenNow": self._window_open(run_id), "gapUnchecked": False,
                   "waitingText": f"waiting for a completed {plan.entry.timeframe_minutes}m {plan.entry.mode} confirmation at {plan.trigger:g} with the reviewed volume and candle-quality checks"}
        if result["lastPrice"]:
            trigger["distancePct"] = (plan.trigger-result["lastPrice"])/result["lastPrice"]*100
        result["triggers"] = [trigger]
        result["plan"] = {**plan.model_dump(mode="json"), "triggerTf": f"{plan.entry.timeframe_minutes}m",
                          "triggers": [{**trigger, "targets": [{"price": target} for target in plan.targets]}]}
        result["summary"] = "Cartel alert triggered; no orders submitted." if state.get("signal") else "Watching reviewed Cartel level (alert only)."
        if state.get("observationError"):
            result.update(needsAttention=True, attentionReasons=[state["observationError"]],
                          summary=state["observationError"])
        elif row["status"] == "paused":
            result["summary"] = "Cartel alert observation paused."
        return result

    def armed(self, *, slim=False):
        return [self.detail(rid) for rid, row in self.rows.items() if row["status"] in ("armed", "paused")]

    def summary(self):
        rows = self.armed()
        watching, timeline = [], []
        attention = []
        for row in rows:
            plan = self.plans[row["runId"]]
            if row["needsAttention"]:
                attention.append({"runId": row["runId"], "symbol": row["symbol"],
                                  "technique": self.TECHNIQUE_ID, "status": row["status"],
                                  "mode": "alert", "instrument": "options", "hasPosition": False,
                                  "workspace": row["portfolio"].get("kind"),
                                  "account": row["portfolio"].get("name"),
                                  "reasons": row["attentionReasons"]})
            if row.get("signal"):
                timeline.append({"runId": row["runId"], "symbol": row["symbol"], "ts": row["signal"]["at"],
                                 "kind": "cartel_alert", "text": "Cartel entry condition confirmed; alert only.", "pnl": None})
            else:
                watching.append({"runId": row["runId"], "symbol": row["symbol"], "technique": self.TECHNIQUE_ID,
                                 "status": row["status"], "mode": "alert", "instrument": "options",
                                 "workspace": row["portfolio"].get("kind"), "account": row["portfolio"].get("name"),
                                 "stale": row["stale"], "lastPrice": row["lastPrice"], "triggers": 1,
                                 "size": {"contracts": None, "riskPct": 0, "qty": None},
                                 "nearest": {"id": "cartel_entry", "label": "Cartel entry", "kind": plan.entry.mode,
                                             "entry": plan.trigger, "stop": plan.invalidation, "direction": plan.direction,
                                             "targets": list(plan.targets), "distancePct": None},
                                 "summary": row["summary"], "windowOpenNow": self._window_open(row["runId"])})
        return {"counts": {"armed": sum(r["status"] == "armed" for r in rows),
                           "paused": sum(r["status"] == "paused" for r in rows), "inTrade": 0,
                           "attention": len(attention), "watching": len(watching)},
                "attention": attention, "inTrade": [], "watching": watching, "timeline": timeline, "stoppedToday": [],
                "pnl": {"realized": 0, "unrealized": 0, "lossLimit": 0},
                "windowOpenNow": any(self._window_open(r["runId"]) for r in rows)}

    def _window_open(self, run_id):
        row = self.rows[run_id]
        return (row["status"] == "armed" and row["state"]["phase"] == "waiting"
                and row["state"]["opensAt"] <= self.clock() < row["state"]["expiresAt"]
                and bar_session(self.clock()) == "rth"
                and not self.engine.settings.get("techniques.options_cartel.paused", False)
                and self.engine.settings.get("techniques.options_cartel.enabled", True))

    def _publish(self, run_id):
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "armed", "event": "cartel_observation",
                                                   "armed": self.detail(run_id)})

    async def on_minute_bar(self, symbol, bar):
        now = self.clock()
        if bar.tf != "1m" or bar_session(bar.ts) != "rth" or bar.ts+60_000 > now or now-(bar.ts+60_000) > 120_000:
            return
        for rid, cached in list(self.rows.items()):
            if cached["symbol"] != symbol:
                continue
            async with self.engine.sf() as session, session.begin():
                row = await self.repository._locked(session, rid)
                if row.mode not in self.OBSERVED_MODES or row.status != "armed" or row.state["phase"] != "waiting":
                    continue
                if self.engine.settings.get("techniques.options_cartel.paused", False) \
                        or not self.engine.settings.get("techniques.options_cartel.enabled", True):
                    continue
                state = row.state
                if bar.ts <= state.get("lastMinute", -1):
                    minutes = dict(state.get('minutes', {}))
                    if merge(minutes, bar):
                        row.state = {**state, 'minutes': minutes,
                                     'observeAfter': max(state.get('observeAfter', state['armedAt']), now)}
                        self.rows[rid] = self.repository.view(row)
                    continue  # correction is context only, never a historical entry
                day = session_date(bar.ts)
                minutes = dict(state.get("minutes", {})) if state.get("day") == day else {}
                merge(minutes, bar)
                plan = self.plans[rid].model_copy(update={"created_at": max(
                    self.plans[rid].created_at, state["armedAt"])})
                tape = [unpack(symbol, values) for values in minutes.values()]
                observation = read_entry(plan, tape, now, entry_after=state.get("observeAfter", state["armedAt"]))
                observation['dataEvidence'] = evidence(minutes)
                row.state = {**state, 'dataEvidence': evidence(minutes), "minutes": minutes, "day": day, "lastMinute": bar.ts,
                             "observation": observation, "decisionHistory": retain_decisions(
                                 state.get("decisionHistory", (state.get("observation") or {}).get("trace", [])), observation)}
                if observation["status"] in ("expired", "invalidated"):
                    row.status = "expired" if observation["status"] == "expired" else "disarmed"
                consumed = bool(observation["signal"]) and self.repository.consume_locked(
                    row, observation["signal"], now_ms=now)
                observed = self.repository.view(row)
            self.rows[rid] = observed
            if observed['state'].get('decisionHistory') and observed['state']['decisionHistory'] != state.get('decisionHistory'):
                await self.repository._journal(observed, 'entry_decision')
            if observation["status"] in ("expired", "invalidated"):
                await self.repository._journal(observed, observation["status"])
            if consumed:
                await self.repository._journal(observed, "signal_consumed")
                await self.after_signal(rid)
            self._publish(rid)
            if self.rows[rid]["status"] not in ("armed", "paused"):
                self.rows.pop(rid, None)

    async def after_signal(self, run_id):
        pass  # alert lane has no execution side effect

    async def pause(self, run_id):
        if run_id not in self.rows:
            raise KeyError("Cartel plan is not active")
        self.rows[run_id] = await self.repository.set_status(run_id, "paused")
        self._publish(run_id)
        return self.detail(run_id)

    async def resume(self, run_id):
        if run_id not in self.rows:
            raise KeyError("Cartel plan is not active")
        if self.rows[run_id]["status"] != "paused":
            raise ValueError("resume applies only to a paused plan")
        if self.engine.settings.get("techniques.options_cartel.paused", False) \
                or not self.engine.settings.get("techniques.options_cartel.enabled", True):
            raise ValueError("technique remains paused or disabled")
        if not await self._prepare_observation(run_id, advance_cutoff=True):
            raise ValueError(self.rows[run_id]["state"]["observationError"])
        self.rows[run_id] = await self.repository.set_status(run_id, "armed")
        self._publish(run_id)
        return self.detail(run_id)

    async def disarm(self, run_id, *, reason="manual", flatten=False):
        if run_id not in self.rows:
            return False
        self.rows[run_id] = await self.repository.set_status(run_id, "disarmed")
        self._publish(run_id)
        self.rows.pop(run_id, None)
        return True

    async def stop_all(self, *, flatten=False, reason="stop all"):
        ids = list(self.rows)
        for rid in ids:
            await self.disarm(rid, reason=reason)
        return len(ids)

    async def set_mode(self, run_id, mode=None, **kwargs):
        if mode not in (None, "alert"):
            raise ValueError("Money-mode execution is not available in the Cartel alert observer")
        return self.detail(run_id)

    async def flatten_trade(self, run_id, trigger_id=None):
        return None  # the shared API returns not-found for the nonexistent position

    async def roll_stale(self):
        before = set(self.rows)
        await self.on_heartbeat()
        return [{"runId": rid, "reason": "Cartel horizon expired"} for rid in before-set(self.rows)]

    async def on_heartbeat(self):
        for rid, row in list(self.rows.items()):
            if self.clock() >= row["state"]["expiresAt"] and row["status"] in ("armed", "paused"):
                self.rows[rid] = await self.repository.set_status(rid, "expired")
                self._publish(rid)
                self.rows.pop(rid, None)

    async def audit(self, run_id, *, limit=200):
        if run_id not in self.plans:
            raise KeyError("Cartel plan not loaded")
        async with self.engine.sf() as session:
            rows = (await session.scalars(select(Event).where(Event.aggregate_id == run_id)
                                            .order_by(Event.ts.desc()).limit(min(limit, 1000)))).all()
        return [{"id": e.id, "ts": e.ts.isoformat(), "type": e.type, "payload": e.payload} for e in rows]


async def attach_cartel_observer(engine):
    if getattr(engine, "cartel_observer", None) is not None:
        return engine.cartel_observer
    from .runtime import CartelRuntime
    from .scan_recovery import recover_interrupted_scans
    await recover_interrupted_scans(engine)
    from .preparation import recover_interrupted_preparations
    await recover_interrupted_preparations(engine)
    observer = CartelRuntime(engine)
    await observer.restore()
    engine.cartel_observer = observer
    if not hasattr(engine, "plan_runners"):
        engine.plan_runners = {}
    if not hasattr(engine, "techniques"):
        engine.techniques = {}
    engine.plan_runners[observer.TECHNIQUE_ID] = observer
    engine.techniques[observer.TECHNIQUE_ID] = observer
    observer.start()
    from .jobs import register_jobs
    register_jobs(engine)
    return observer
