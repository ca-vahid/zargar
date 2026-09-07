"""Opt-in Cartel campaign adapter; PositionManager remains the sole exit router."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json

from ...events import MANAGED_POSITION_HISTORY_RECOVERED
from ...execution.serialization import position_guard
from ...marketstructure.market_calendar import is_trading_day, previous_trading_day
from ...marketstructure.sessions import ET, session_bounds
from .catchup import review_missed_closes
from .catchup_runtime import drain_catchup
from .data import DailyBar, completed_daily, require_contiguous
from .exit_router import TERMINAL, CartelExitRouter
from .exits import ExitCampaign, ExitState, decide_exits, record_fill


class CartelPositionAdapter:
    POLICY_KEYS = frozenset({"adapter", "timeframe", "stop", "dte_close", "cartel"})

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self.exit_router = CartelExitRouter()

    async def before_close(self, manager, p, *, fraction=1., reason="manual", kind="close", force_market=False):
        if not p.policy["cartel"].get("residualOf"):
            await self.exit_router.close(manager, p, fraction=fraction, reason=reason, kind=kind, force_market=force_market)
            return True
        from .residuals import drain_residual
        await drain_residual(manager, p)
        return True

    async def on_watch(self, manager, p):
        if p.policy["cartel"].get("residualOf"):
            return await self.before_close(manager, p)
        await self.exit_router.poll(manager, p)
        await drain_catchup(self, manager, p)
        return False

    def pending_qty(self, p, symbol):
        return self.exit_router.pending_qty(p, symbol)

    handles_exit_retries = True

    async def ensure_venue_stop(self, manager, p):
        if not p.policy["cartel"].get("residualOf"):
            await self.exit_router.ensure_stop(manager, p)
        return True

    def validate(self, spec):
        try:
            if set(spec["policy"]) - self.POLICY_KEYS:
                raise ValueError("unsupported additional exit authority in Cartel policy")
            if spec["policy"].get("stop", {}).get("kind") != "fixed" or float(spec.get("entry", 0)) <= 0:
                raise ValueError("Cartel adoption needs an underlying entry and fixed protective stop")
            context = spec["policy"]["cartel"]
            ExitCampaign.model_validate(context["campaign"])
            history = [DailyBar.model_validate(b) for b in context["daily"]]
            if any(b.symbol != spec["symbol"] for b in history):
                raise ValueError("daily history must match position")
            legs = spec["legs"]
            if len(legs) != 1 or float(legs[0].get("qty", 0)) <= 0:
                raise ValueError("Cartel campaign manages one bought vehicle")
            qty = float(legs[0]["qty"])
            if not qty.is_integer() or int(context["initialQty"]) != qty:
                raise ValueError("campaign quantity must match confirmed whole-unit holdings")
            if context.get("state") is not None or context.get("accounted"):
                raise ValueError("new adoption cannot inject prior exit state")
        except (KeyError, TypeError, ValueError) as exc:
            return [f"invalid Cartel policy: {exc}"]
        return []

    def validate_update(self, p, policy):
        if set(policy) - self.POLICY_KEYS:
            return ["unsupported additional exit authority in Cartel policy"]
        if policy.get("cartel") != p.policy.get("cartel") or policy.get("timeframe") != p.policy.get("timeframe"):
            return ["campaign state requires a technique-specific reviewed update"]
        return []

    def _sync(self, p, *, observed_at=None):
        context = dict(p.policy["cartel"])
        campaign = ExitCampaign.model_validate(context["campaign"])
        state = ExitState.model_validate(context["state"]) if context.get("state") else ExitState(
            position_id=p.id, symbol=p.symbol, direction=p.direction, entry=p.entry,
            stop=p.state.stop, initial_qty=context["initialQty"], remaining_qty=context["initialQty"])
        accounted = dict(context.get("accounted") or {})
        for rec in p.exits:
            oid = rec.get("orderId")
            filled = float(rec.get("filledQty") or 0)
            if not oid or filled <= float(accounted.get(oid, 0)):
                continue
            delta = filled-float(accounted.get(oid, 0))
            if not delta.is_integer():
                raise ValueError("fractional fill requires reconciliation before whole-unit campaign accounting")
            kind = rec.get("kind", "manual")
            rung = kind.removeprefix("cartel:") if kind.startswith("cartel:") else "stop" \
                if kind in ("stop", "venue_stop", "premium_stop") else "expiry" if kind == "dte" else "manual"
            state = record_fill(campaign, state, fill_id=f"{oid}:{filled}", rung=rung, qty=int(delta))
            accounted[oid] = filled
        held = sum(abs(leg.qty) for leg in p.open_legs)
        if abs(held-state.remaining_qty) > 1e-8:
            raise ValueError("campaign holdings disagree with managed filled quantity")
        # External safety/manual actions may tighten the manager's stop; never loosen it.
        if p.state.stop is not None:
            stop = max(state.stop, p.state.stop) if p.direction == "long" else min(state.stop, p.state.stop)
            state = state.model_copy(update={"stop": stop})
        snapshot = state.model_dump(mode="json")
        if observed_at is not None and (not context.get("stateCheckpoint")
                or context["stateCheckpoint"]["state"] != snapshot):
            context["stateCheckpoint"] = {"at": observed_at, "state": snapshot}
        context.update(state=snapshot, accounted=accounted)
        p.policy = {**p.policy, "cartel": context}
        p.state.stop = state.stop
        return campaign, state

    async def after_fill(self, manager, p):
        old = p.state.stop
        accounted = p.policy["cartel"].get("accounted", {})
        stop_filled = any(r["kind"] == "venue_stop" and r.get("filledQty", 0) > accounted.get(r.get("orderId"), 0)
                          for r in p.exits)
        self._sync(p, observed_at=manager.now_ms())
        if p.open_legs and stop_filled:
            p.status = "closing"
            p.policy = {**p.policy, "cartel": {**p.policy["cartel"], "closeRequest": {
                "remaining": 0, "kind": "stop", "forceMarket": True,
                "reason": "Venue stop filled; close remaining Cartel exposure."}}}
        if p.open_legs and (old != p.state.stop or p.venue_stop_order_id):
            # An unchanged stop price can still protect the wrong quantity after
            # a partial trim. Force the manager's cancel/replace size refresh.
            if p.venue_stop_order_id:
                p.venue_stop_at = None
            await manager._ensure_venue_stop(p)
        context = dict(p.policy['cartel'])
        batch = context.get('catchupReview')
        if not p.open_legs and batch and batch['status'] == 'executing':
            context['catchupReview'] = {**batch, 'status': 'complete',
                'cursor': len(batch['actions']), 'completedAt': manager.now_ms()}
            context['missedCloses'] = sorted(set(context.get('missedCloses', []))-set(batch['review']['missedCloses']))
            p.policy = {**p.policy, 'cartel': context}
        await manager._persist(p)

    async def prepare_catchup(self, manager, p):
        """Persist a repeatable decision batch before any catch-up submission.

        Old rows without a timestamped state checkpoint require review. Do not
        retroactively stamp their current fill/stop state at the position open.
        """
        if p.technique != "options_cartel" or p.policy.get("adapter") != "options_cartel":
            raise ValueError("catch-up requires an owned Cartel position")
        async with position_guard(manager, p.id):
            active = p.policy['cartel'].get('catchupReview')
            if active and active['status'] == 'executing':
                return active
            if not await self.exit_router.refresh(manager, p):
                raise ValueError('exit orders require reconciliation before catch-up')
            if not p.policy["cartel"].get("stateCheckpoint"):
                raise ValueError("catch-up requires a persisted position-state checkpoint")
            campaign, state = self._sync(p)
            context = dict(p.policy["cartel"])
            if context.get("entryPending") or context.get("closeRequest") or any(
                    r.get("status") not in TERMINAL and not (
                        r['kind'] == 'venue_stop' and r.get('status') in ('ACCEPTED', 'SUBMITTED')) for r in p.exits):
                raise ValueError("reconcile pending entry/exit orders before catch-up review")
            missed = context.get("missedCloses", [])
            checkpoint = context["stateCheckpoint"]
            if checkpoint["state"] != state.model_dump(mode="json"):
                raise ValueError("position state changed after its checkpoint; reconcile before catch-up")
            review = review_missed_closes(campaign, state,
                [DailyBar.model_validate(b) for b in context["daily"]], missed,
                state_since_ms=checkpoint["at"], as_of_ms=manager.now_ms())
            digest = hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest()
            # The decision identity excludes wall-clock review time; repeated
            # inspection of the same state and closes returns the same batch.
            identity = hashlib.sha256(json.dumps({"position": p.id, "state": review["state"],
                "closes": missed, "requirements": review["requirements"]}, sort_keys=True).encode()).hexdigest()
            old = context.get("catchupReview")
            if old and old["id"] == identity:
                return old
            batch = {"id": identity, "inputSha256": digest, "status": "reviewed",
                     "review": review, "placesOrders": False}
            context["catchupReview"] = batch
            p.policy = {**p.policy, "cartel": context}
            await manager._persist(p)
            return batch

    async def recover_daily(self, manager, p, recovered, *, source: str, as_of_ms: int):
        """Restore missing completed candles without replaying trades or changing fills.

        Existing candles are immutable here: conflicting provider data needs
        explicit review. Missed closes remain visible for the catch-up decision
        path; acquiring history is not proof that a historical exit occurred.
        """
        if p.technique != "options_cartel" or p.policy.get("adapter") != "options_cartel":
            raise ValueError("history recovery requires an owned Cartel position")
        if not source.strip() or as_of_ms > manager.now_ms():
            raise ValueError("recovery needs a source and a non-future as-of time")
        incoming = [DailyBar.model_validate(b) for b in recovered]
        if any(b.symbol != p.symbol or b.closes_at > as_of_ms for b in incoming):
            raise ValueError("recovery includes another symbol or an unfinished/future session")
        async with position_guard(manager, p.id), self._locks.setdefault(p.id, asyncio.Lock()):
            context = dict(p.policy["cartel"])
            existing = [DailyBar.model_validate(b) for b in context["daily"]]
            if any(b.closes_at > as_of_ms for b in existing):
                raise ValueError("recovery cannot rewind the position's already-observed history")
            # completed_daily rejects conflicting duplicates, including conflicts
            # against the original plan/observed record; never silently revise it.
            merged = completed_daily(existing + incoming, as_of_ms)
            require_contiguous(merged)
            today = dt.datetime.fromtimestamp(as_of_ms/1000, ET).date()
            expected = today if is_trading_day(today) and session_bounds(today.isoformat())[1] <= as_of_ms \
                else previous_trading_day(today)
            if not merged or merged[-1].session != expected:
                raise ValueError("recovery does not reach the latest completed exchange session")
            campaign = ExitCampaign.model_validate(context["campaign"])
            warmup = max(campaign.atr_period, *(r.ema_period for r in campaign.rungs))
            if len(merged) < warmup:
                raise ValueError("recovery still lacks indicator warm-up history")
            known = {b.session for b in existing}
            added = [b for b in merged if b.session not in known]
            pending = sorted(set(context.get("missedCloses", [])) |
                             {b.closes_at for b in added if b.closes_at > p.opened_ms})
            context.update(daily=[b.model_dump(mode="json") for b in merged[-600:]],
                           missedCloses=pending,
                           recovery={"source": source, "asOfMs": as_of_ms,
                                     "addedSessions": [b.session.isoformat() for b in added]})
            p.policy = {**p.policy, "cartel": context}
            # Clear only this adapter's data-gap notices, preserving all others.
            p.attention = [s for s in p.attention if not s.startswith(("Incomplete session tape;",
                "Daily indicator history is incomplete/stale;", "Insufficient daily history"))]
            if pending:
                message = "Recovered missed daily closes need execution review; no historical fills were created."
                if message not in p.attention:
                    p.attention.append(message)
            await manager._persist(p)
            await manager._journal(MANAGED_POSITION_HISTORY_RECOVERED, p,
                                   {"source": source, "asOfMs": as_of_ms,
                                    "addedSessions": [b.session.isoformat() for b in added],
                                    "missedCloses": pending})
            catchup = None
            if pending:
                try:
                    catchup = await self.prepare_catchup(manager, p)
                except ValueError as exc:
                    catchup = {"status": "needs_review", "reason": str(exc), "placesOrders": False}
            return {"positionId": p.id, "addedSessions": [b.session.isoformat() for b in added],
                    "missedCloses": pending, "catchupReview": catchup, "placesOrders": False}

    async def on_minute_bar(self, manager, p, bar):
        if p.policy["cartel"].get("residualOf") and await self.before_close(manager, p):
            return
        async with self._locks.setdefault(p.id, asyncio.Lock()):
            day = dt.datetime.fromtimestamp(bar.ts/1000, ET).date()
            if not is_trading_day(day):
                return
            opens, closes = session_bounds(day.isoformat())
            if bar.symbol != p.symbol or bar.tf != "1m" or not opens <= bar.ts < closes:
                return
            context = dict(p.policy["cartel"])
            if bar.ts <= context.get("lastMinute", -1):
                return
            if bar.ts+60_000 > manager.now_ms():
                return
            if bar.ts+60_000 <= p.opened_ms or manager.now_ms()-(bar.ts+60_000) > 120_000:
                return  # historical/backfill bars cannot close today's actual exposure
            buffer = dict(context.get("dayBuffer") or {}) if context.get("bufferDay") == day.isoformat() else {}
            buffer[str(bar.ts)] = [bar.open, bar.high, bar.low, bar.close, bar.volume]
            history = completed_daily([DailyBar.model_validate(b) for b in context["daily"]], bar.ts+60_000)
            daily_close = bar.ts+60_000 == closes
            complete = daily_close and all(str(ts) in buffer for ts in range(opens, closes, 60_000))
            if complete:
                ordered = [buffer[str(ts)] for ts in range(opens, closes, 60_000)]
                daily = DailyBar(symbol=p.symbol, session=day, open=ordered[0][0],
                                 high=max(b[1] for b in ordered), low=min(b[2] for b in ordered),
                                 close=ordered[-1][3], volume=sum(b[4] for b in ordered))
                history = [b for b in history if b.session != day] + [daily]
            if daily_close and not complete:
                message = "Incomplete session tape; daily EMA exits require recovered daily history."
                if message not in p.attention:
                    p.attention.append(message)
                await manager._alert(p, message,
                                     stage="cartel_daily_history")
            context.update(lastMinute=bar.ts, bufferDay=day.isoformat(), dayBuffer=buffer,
                           daily=[b.model_dump(mode="json") for b in history[-600:]])
            p.policy = {**p.policy, "cartel": context}
            if day.isoformat() not in p.sessions_seen:
                p.sessions_seen.append(day.isoformat())
            campaign, state = self._sync(p, observed_at=manager.now_ms())
            pending = int(sum(max(0., r["qty"]-float(r.get("filledQty") or 0)) for r in p.exits
                              if r["kind"] != "venue_stop" and r.get("status") not in TERMINAL))
            indicator_history = history
            expected = day if complete else previous_trading_day(day)
            try:
                require_contiguous(history)
                if not history or history[-1].session != expected:
                    raise ValueError("latest required daily session is missing")
            except ValueError:
                indicator_history = []
                message = "Daily indicator history is incomplete/stale; EMA and ATR exits await recovery."
                if message not in p.attention:
                    p.attention.append(message)
                    await manager._alert(p, message, stage="cartel_daily_history")
            result = decide_exits(campaign, state, indicator_history, as_of_ms=bar.ts+60_000,
                                  observed_price=bar.close, daily_close=complete and bool(indicator_history), pending_qty=pending,
                                  dte=p.dte_min(day), min_dte=manager.min_dte_floor())
            if context.get("entryPending"):
                result["decisions"] = [d for d in result["decisions"] if d["rung"] in ("stop", "expiry")]
            for warning in result["warnings"]:
                if warning.startswith("Insufficient") and warning not in p.attention:
                    p.attention.append(warning)
                    await manager._alert(p, warning, stage="cartel_daily_history")
            await manager._persist(p)  # minute watermark and campaign state before routing
            for decision in result["decisions"]:
                remaining = sum(abs(l.qty) for l in p.open_legs)
                if remaining <= 0:
                    break
                protective = decision["rung"] in ("stop", "expiry")
                await manager.close(p.id, fraction=min(1, decision["qty"]/remaining),
                                    reason=decision["reason"], kind=f"cartel:{decision['rung']}",
                                    force_market=protective)


def register_cartel_policy(engine):
    manager = engine.position_manager
    if "options_cartel" not in manager._policy_adapters:
        manager.register_policy_adapter("options_cartel", CartelPositionAdapter())
