"""Transactional Cartel arming/entry state. No broker calls in this repository.

Services must validate preflight/permissions before using money modes. State is
committed before submission; an ambiguous attempt is reconciled, never retried
blindly. Row locks serialize competing callbacks across repository instances.
"""
from __future__ import annotations

from sqlalchemy import select

from ... import events as ev
from ...domain import new_id
from ...marketstructure.sessions import session_bounds
from ...models import Order, Portfolio, TechniqueArmed, TechniqueRun
from .plans import CartelPlan

TECHNIQUE = "options_cartel"


class ArmRepository:
    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def view(row):
        return {"runId": row.run_id, "symbol": row.symbol, "portfolioId": row.portfolio_id,
                "mode": row.mode, "status": row.status, "config": row.config, "state": row.state,
                "planFor": row.plan_for, "technique": row.technique}

    async def _locked(self, session, run_id):
        row = await session.scalar(select(TechniqueArmed).where(TechniqueArmed.run_id == run_id,
                                                               TechniqueArmed.technique == TECHNIQUE).with_for_update())
        if row is None:
            raise KeyError("Cartel armed record not found")
        return row

    async def _journal(self, row, action):
        await self.engine.journal.append(ev.OPTIONS_CARTEL_STATE_CHANGED,
                                        {"runId": row["runId"], "symbol": row["symbol"], "action": action,
                                         "status": row["status"], "phase": row["state"]["phase"]},
                                        aggregate_type="technique_run", aggregate_id=row["runId"],
                                        portfolio_id=row["portfolioId"])

    async def arm(self, run_id, portfolio_id, mode, config, *, now_ms):
        if mode not in ("alert", "proposal", "auto"):
            raise ValueError("invalid arm mode")
        async with self.engine.sf() as session, session.begin():
            # Lock the existing immutable plan as the creation mutex; locking a
            # nonexistent armed row alone does not serialize concurrent INSERTs.
            run = await session.scalar(select(TechniqueRun).where(TechniqueRun.id == run_id,
                                                                  TechniqueRun.technique == TECHNIQUE).with_for_update())
            if run is None or run.mode != "plan":
                raise ValueError("arming requires an owned reviewed plan")
            plan = CartelPlan.model_validate(run.result["plan"]["plan"])
            if not plan.created_at <= now_ms < session_bounds(plan.last_session.isoformat())[1]:
                raise ValueError("plan does not exist yet or its horizon has closed")
            if await session.get(Portfolio, portfolio_id) is None:
                raise ValueError("portfolio not found")
            existing = await session.get(TechniqueArmed, run_id)
            if existing is not None:
                if existing.technique != TECHNIQUE:
                    raise ValueError("armed record belongs to another technique")
                if existing.portfolio_id != portfolio_id or existing.mode != mode or existing.config != config:
                    raise ValueError("existing arming cannot be silently replaced or moved to another account")
                return self.view(existing)  # retry is idempotent; never resets consumed signal
            row = TechniqueArmed(run_id=run_id, technique=TECHNIQUE, symbol=plan.symbol,
                                 plan_for=plan.first_session.isoformat(), portfolio_id=portfolio_id, mode=mode,
                                 config=config, status="armed", state={"version": 1, "phase": "waiting",
                                                                       "armedAt": now_ms, "signal": None,
                                                                       "opensAt": session_bounds(plan.first_session.isoformat())[0],
                                                                       "expiresAt": session_bounds(plan.last_session.isoformat())[1],
                                                                       "attempt": None, "orderId": None})
            session.add(row)
            await session.flush()
            snapshot = self.view(row)
        await self._journal(snapshot, "armed")
        return snapshot

    async def load(self, run_id):
        async with self.engine.sf() as session:
            row = await session.scalar(select(TechniqueArmed).where(TechniqueArmed.run_id == run_id,
                                                                   TechniqueArmed.technique == TECHNIQUE))
            return self.view(row) if row else None

    async def active(self):
        async with self.engine.sf() as session:
            rows = (await session.scalars(select(TechniqueArmed).where(TechniqueArmed.technique == TECHNIQUE,
                TechniqueArmed.status.in_(("armed", "paused", "closing"))))).all()
            return [self.view(row) for row in rows]

    async def consume_signal(self, run_id, signal, *, now_ms):
        async with self.engine.sf() as session, session.begin():
            row = await self._locked(session, run_id)
            if not self.consume_locked(row, signal, now_ms=now_ms):
                return False
            snapshot = self.view(row)
        await self._journal(snapshot, "signal_consumed")
        return True

    @staticmethod
    def consume_locked(row, signal, *, now_ms):
        """Consume within the caller's row-locked transaction with its observation."""
        if row.status != "armed" or row.state["phase"] != "waiting":
            return False
        if now_ms >= row.state["expiresAt"]:
            return False
        if not max(row.state["armedAt"], row.state["opensAt"]) <= signal["at"] <= now_ms:
            raise ValueError("signal predates arming or comes from the future")
        if signal["id"] != f"{row.run_id}:entry:{signal['at']}":
            raise ValueError("signal identity does not match plan and time")
        row.state = {**row.state, "signal": signal, "phase": "signalled"}
        return True

    async def reserve_submission(self, run_id, intent):
        """Only the callback that receives a reservation may call OrderManager.place."""
        async with self.engine.sf() as session, session.begin():
            row = await self._locked(session, run_id)
            if row.status != "armed" or row.state["phase"] != "signalled":
                return None
            if row.mode == "alert":
                raise ValueError("alert plans never reserve an order")
            if intent.portfolio_id != row.portfolio_id or intent.technique_id != TECHNIQUE or intent.dry_run:
                raise ValueError("submission intent ownership or dry-run flag is invalid")
            if intent.side != "BUY" or intent.reduce_only:
                raise ValueError("Cartel entries buy exposure through the reviewed vehicle")
            token = new_id()
            tag = f"cartel_attempt:{token}"
            tagged = intent.model_copy(update={"tags": list(dict.fromkeys([*intent.tags, tag, f"cartel_run:{run_id}"]))})
            row.state = {**row.state, "phase": "submitting", "attempt": token,
                         "intent": tagged.model_dump(), "attemptTag": tag}
            snapshot = self.view(row)
        await self._journal(snapshot, "submission_reserved")
        return tagged

    async def reconcile_submission(self, run_id):
        """Recover only a uniquely matching order. No match is ambiguous, not permission to retry."""
        async with self.engine.sf() as session, session.begin():
            row = await self._locked(session, run_id)
            if not row.state.get("attemptTag"):
                return self.view(row)
            orders = (await session.scalars(select(Order).where(Order.technique == TECHNIQUE,
                                                                 Order.portfolio_id == row.portfolio_id,
                                                                 Order.side == "BUY"))).all()
            matches = [o for o in orders if row.state["attemptTag"] in (o.tags or [])]
            intent = row.state["intent"]
            exact = len(matches) == 1 and all(getattr(matches[0], key) == intent[key]
                for key in ("symbol", "portfolio_id", "sec_type", "side", "qty", "order_type", "limit_price"))
            if not exact:
                row.state = {**row.state, "phase": "needs_attention", "recoveryReason":
                             "Submission outcome is ambiguous or mismatched; reconcile before any retry."}
            else:
                order = matches[0]
                # A disarm cannot erase a still-working entry or its filled exposure.
                row.state = {**row.state, "phase": "working", "orderId": order.id,
                             "orderStatus": order.status, "filledQty": order.filled_qty,
                             "avgFillPrice": order.avg_fill_price}
            snapshot = self.view(row)
        await self._journal(snapshot, "submission_reconciled")
        return snapshot

    async def set_status(self, run_id, status):
        if status not in ("armed", "paused", "disarmed", "expired"):
            raise ValueError("invalid status")
        async with self.engine.sf() as session, session.begin():
            row = await self._locked(session, run_id)
            if row.status in ("disarmed", "expired"):
                if status == row.status:
                    return self.view(row)
                raise ValueError("retired plan cannot be resurrected")
            if row.status == "closing" and status in ("armed", "paused"):
                raise ValueError("closing exposure cannot be resumed as a new entry")
            if status == "armed" and row.status != "paused":
                raise ValueError("resume applies only to a paused plan; it cannot resurrect a retired plan")
            if status in ("disarmed", "expired") and row.state.get("attemptTag") \
                    and not row.state.get("submissionAborted") and row.state["phase"] != "closed":
                row.status = "closing"
                row.state = {**row.state, "retireTo": status}
            else:
                row.status = status
            snapshot = self.view(row)
        await self._journal(snapshot, "status_changed")
        return snapshot
