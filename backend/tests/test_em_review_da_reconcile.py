"""Delivery A review: direct-function regressions, no DB/network/engine start.

Run with the reviewed backend on PYTHONPATH. Session substitutes below expose
commit boundaries; the ORM-detection case uses actual SQLAlchemy attribute history.
Assertions are required behavior and must not be weakened to match the defect.
"""

import asyncio
import copy
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm.attributes import set_committed_value

from zargar.models import TechniqueArmed
from zargar.tools.em_reconcile_fallback import _state_hash, apply
from zargar.marketstructure.outcome import same_plan
from zargar.execution.planrunner import FireJudgement, PlanRunner, Trade


HISTORICAL = pytest.mark.skip(reason=(
    "historical reproduction on a minimal fake session (Delivery A re-review, 2026-09-14); the production tool "
    "no longer carries a fake-session path (closure review). Real-session equivalent: "
    "tests/test_em_reconcile_real_session.py - see its module docstring for the coverage map."))


def trade_record(tid="b1"):
    return {
        "triggerId": tid, "instrument": "shares", "multiplier": 100.0,
        "avgFill": 100.0, "filledQty": 1.0, "realizedPnl": -100.0,
        "entryOrderId": "entry-" + tid,
        "exits": [{"orderId": "exit-" + tid, "filledQty": 1.0, "price": 99.0}],
    }


def row_and_manifest(n=1, orm=False):
    state = {"trades": [trade_record(f"b{i + 1}") for i in range(n)],
             "realizedPnl": -100.0 * n}
    fields = dict(run_id="review-plan", symbol="TEST", portfolio_id="review-book",
                  technique="enhanced_market", status="disarmed", config={})
    if orm:
        row = TechniqueArmed(**fields)
        set_committed_value(row, "state", copy.deepcopy(state))
    else:
        row = SimpleNamespace(**fields, state=copy.deepcopy(state))
    items = [{
        "runId": row.run_id, "symbol": row.symbol, "trigger": t["triggerId"],
        "expectedStateHash": _state_hash(state),
        "old": {"multiplier": 100.0, "realizedPnl": -100.0},
        "new": {"multiplier": 1.0, "realizedPnl": -1.0},
        "haltOld": True, "haltNew": False, "reason": "review fixture",
    } for t in state["trades"]]
    return row, {"generatedAt": 1, "fix": "FIX-01", "items": items}, state


class Session:
    def __init__(self, row, orm=False):
        self.row = row
        self.orm = orm
        self.persisted = copy.deepcopy(row.state)
        self.commit_changes = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, model, key):
        assert model is TechniqueArmed and key == self.row.run_id
        return self.row

    async def commit(self):
        changed = (inspect(self.row).attrs.state.history.has_changes()
                   if self.orm else self.row.state != self.persisted)
        self.commit_changes.append(changed)
        if changed:
            self.persisted = copy.deepcopy(self.row.state)
            if self.orm:
                set_committed_value(self.row, "state", copy.deepcopy(self.row.state))


class Journal:
    def __init__(self, fail=False):
        self.fail = fail
        self.events = []

    async def append(self, kind, payload, **kwargs):
        if self.fail:
            raise RuntimeError("audit write unavailable")
        self.events.append((kind, copy.deepcopy(payload), kwargs))


def engine_for(row, orm=False, journal_fail=False):
    session = Session(row, orm=orm)
    return SimpleNamespace(sf=lambda: session, journal=Journal(journal_fail)), session


@HISTORICAL
def test_apply_produces_an_orm_tracked_json_update():
    row, manifest, original = row_and_manifest(orm=True)
    engine, session = engine_for(row, orm=True)
    assert asyncio.run(apply(engine, manifest)) == 1
    assert session.commit_changes == [True], (
        "The tool must not mutate shared nested JSON before assigning the new state; "
        "the real mapped attribute currently reports no change."
    )
    assert session.persisted != original


@HISTORICAL
def test_two_corrections_for_one_plan_do_not_invalidate_each_other():
    row, manifest, _ = row_and_manifest(n=2)
    engine, session = engine_for(row)
    count = asyncio.run(apply(engine, manifest))
    assert count == 2, "Both reviewed items share one original row hash and must commit as one row transition"
    assert all(t["multiplier"] == 1.0 for t in session.persisted["trades"])


@HISTORICAL
def test_audit_failure_does_not_leave_a_committed_unjournaled_correction():
    row, manifest, original = row_and_manifest()
    engine, session = engine_for(row, journal_fail=True)
    with pytest.raises(RuntimeError, match="audit write unavailable"):
        asyncio.run(apply(engine, manifest))
    assert session.persisted == original, (
        "Correction and its durable audit/receipt must be atomic; a later journal error "
        "cannot strand a committed correction that replay refuses."
    )


@HISTORICAL
def test_apply_updates_the_plan_aggregate_alongside_the_trade():
    row, manifest, _ = row_and_manifest()
    engine, session = engine_for(row)
    asyncio.run(apply(engine, manifest))
    assert session.persisted["realizedPnl"] == -1.0, (
        "The top-level persisted realizedPnl must reconcile with corrected trades."
    )


@HISTORICAL
def test_replay_of_a_corrected_list_trade_is_not_reported_as_a_conflict(capsys):
    row, manifest, _ = row_and_manifest()
    engine, _ = engine_for(row)
    asyncio.run(apply(engine, manifest))
    capsys.readouterr()
    assert asyncio.run(apply(engine, manifest)) == 0
    assert "REFUSE" not in capsys.readouterr().out, (
        "Live persisted trades are lists; exact receipt replay must distinguish "
        "already-corrected from a conflicting row."
    )


def test_outcome_identity_keeps_entry_basis():
    common = {"direction": "long", "stop": {"price": 99.0},
              "targets": [{"price": 103.0}]}
    touch = {**common, "entry": {"price": 100.0, "basis": "at_level"}}
    confirmed = {**common, "entry": {"price": 100.0, "basis": "on_break"}}
    assert not same_plan(touch, confirmed), (
        "simulate_plan uses entry.basis to choose whether/when to fill; "
        "equal prices do not make these the same outcome plan."
    )


def test_exhausted_critic_failure_budget_has_explicit_persisted_disposition():
    saved = []

    async def hook(name, coro):
        return await coro

    async def analyze(*args):
        return FireJudgement(verdict="setup", confidence=0.8)

    async def review(*args):
        raise RuntimeError("review unavailable")

    async def noop(*args, **kwargs):
        return None

    trade = Trade(trigger_id="b1", kind="bounce", fired_ts=1,
                  window="prime_open", entry=100, stop=99, targets=[101, 102, 103])
    ap = SimpleNamespace(run_id="review-plan", status="armed", critic_failures=0,
                         config=SimpleNamespace(mode="alert", instrument="shares", use_critic=True))

    async def persist(plan):
        saved.append(copy.deepcopy(trade.to_dict()))

    runner = SimpleNamespace(
        engine=SimpleNamespace(settings={}), _hook=hook, analyze_fire=analyze,
        reviewer_available=lambda: True, review_fire=review,
        rt=lambda key, default=None: {"critic_fail_budget": 1,
                                     "critic_timeout_seconds": 25}.get(key, default),
        _log=lambda *args, **kwargs: None, _alert=noop, pause=noop,
        _persist=persist, _publish=lambda *args, **kwargs: None,
    )
    runner._critic_failed = lambda *args: PlanRunner._critic_failed(runner, *args)
    asyncio.run(PlanRunner._fire_rest(runner, ap, "b1", SimpleNamespace(),
                                    SimpleNamespace(), 0, trade, journal=True))
    assert trade.status == "critic_unavailable"
    assert saved and saved[-1]["criticDisposition"] == "failure-budget-paused"
