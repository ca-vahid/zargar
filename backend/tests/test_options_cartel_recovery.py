"""Missing-history acquisition never manufactures executions or rewrites observed candles."""
import datetime as dt
from copy import deepcopy

import pytest

from zargar.techniques.options_cartel.data import DailyBar

from .test_options_cartel_position_adapter import minute, prepared


async def test_recovery_preserves_confirmed_fills_and_unrelated_attention(engine):
    rig = await prepared(engine)
    await minute(rig, 0, 110)
    adapter = rig.pm._policy_adapter(rig.p)
    context = rig.p.policy["cartel"]
    missing = context["daily"].pop()
    state, accounted, exits = deepcopy(context["state"]), deepcopy(context["accounted"]), deepcopy(rig.p.exits)
    rig.p.attention.extend(["Daily indicator history is incomplete/stale; EMA and ATR exits await recovery.",
                            "Unrelated venue warning"])
    count = len(engine.orders.placed)
    result = await adapter.recover_daily(rig.pm, rig.p, [missing], source="test recovery", as_of_ms=rig.pm.now_ms())
    assert result["addedSessions"] == [missing["session"]] and result["missedCloses"] == []
    assert rig.p.policy["cartel"]["state"] == state and rig.p.policy["cartel"]["accounted"] == accounted
    assert rig.p.exits == exits and rig.p.legs[0].qty == 6 and rig.p.state.stop == 100
    assert rig.p.attention == ["Unrelated venue warning"] and len(engine.orders.placed) == count


async def test_missed_close_is_persisted_for_review_not_booked_as_a_fill(engine):
    rig = await prepared(engine)
    adapter = rig.pm._policy_adapter(rig.p)
    day = dt.datetime.fromtimestamp(rig.opens/1000, dt.UTC).date()
    daily = DailyBar(symbol="TEST", session=day, open=100, high=110, low=99, close=105, volume=10000)
    rig.pm._now = lambda: rig.closes/1000
    result = await adapter.recover_daily(rig.pm, rig.p, [daily], source="test close recovery", as_of_ms=rig.closes)
    assert result["missedCloses"] == [rig.closes]
    assert rig.p.legs[0].qty == 8 and engine.orders.placed == []
    assert any("no historical fills" in s for s in rig.p.attention)
    again = await adapter.recover_daily(rig.pm, rig.p, [daily], source="same source", as_of_ms=rig.closes)
    assert again["addedSessions"] == [] and again["missedCloses"] == [rig.closes]


async def test_conflict_on_a_known_session_is_recorded_not_merged_and_never_blocks_newer_sessions(engine):
    """2026-10-05 (DHT): a provider candle that disagrees with a session the position already holds is
    evidence, not a reason to leave every newer session (and the daily EMA/ATR exits) unrecovered."""
    rig = await prepared(engine)
    await minute(rig, 0, 110)
    adapter = rig.pm._policy_adapter(rig.p)
    context = rig.p.policy["cartel"]
    missing = context["daily"].pop()
    known = deepcopy(context["daily"][-5])
    conflict = {**known, "volume": known["volume"]+999}
    count = len(engine.orders.placed)
    result = await adapter.recover_daily(rig.pm, rig.p, [conflict, missing], source="provider with a revised old bar",
                                         as_of_ms=rig.pm.now_ms())
    assert result["addedSessions"] == [missing["session"]]
    daily = rig.p.policy["cartel"]["daily"]
    assert next(b for b in daily if b["session"] == known["session"]) == known      # the position's record is kept
    assert rig.p.policy["cartel"]["recovery"]["conflictingKnownSessions"] == [known["session"]]
    assert len(engine.orders.placed) == count                                       # recovery itself places nothing


async def test_conflicting_new_data_or_future_recovery_is_rejected_without_partial_mutation(engine):
    rig = await prepared(engine)
    adapter = rig.pm._policy_adapter(rig.p)
    before = deepcopy(rig.p.policy)
    new = before["cartel"]["daily"][-1]
    rig.p.policy["cartel"]["daily"] = before["cartel"]["daily"][:-1]
    shadow = deepcopy(rig.p.policy)
    with pytest.raises(ValueError, match="conflicting"):   # two different provider bars for the same NEW session
        await adapter.recover_daily(rig.pm, rig.p, [new, {**new, "volume": 999}], source="conflict", as_of_ms=rig.pm.now_ms())
    assert rig.p.policy == shadow
    rig.p.policy = before
    with pytest.raises(ValueError, match="non-future"):
        await adapter.recover_daily(rig.pm, rig.p, [], source="future", as_of_ms=rig.pm.now_ms()+1)
    rewind = DailyBar.model_validate(before["cartel"]["daily"][-2]).closes_at
    with pytest.raises(ValueError, match="rewind"):
        await adapter.recover_daily(rig.pm, rig.p, [], source="old snapshot", as_of_ms=rewind)
    assert rig.p.policy == before and engine.orders.placed == []


async def test_incomplete_recovery_cannot_claim_current_history(engine):
    rig = await prepared(engine)
    rig.pm._now = lambda: rig.closes/1000
    with pytest.raises(ValueError, match="latest completed"):
        await rig.pm._policy_adapter(rig.p).recover_daily(rig.pm, rig.p, [], source="incomplete", as_of_ms=rig.closes)


async def test_catchup_batch_is_persisted_and_repeatable_without_fills(engine):
    from zargar.execution.positions import PositionManager
    from zargar.techniques.options_cartel.position_adapter import CartelPositionAdapter

    rig = await prepared(engine)
    await minute(rig, 0, 100)
    checkpoint = deepcopy(rig.p.policy['cartel']['stateCheckpoint'])
    day = dt.datetime.fromtimestamp(rig.opens/1000, dt.UTC).date()
    daily = DailyBar(symbol='TEST', session=day, open=100, high=112, low=99, close=111, volume=10000)
    rig.pm._now = lambda: rig.closes/1000
    adapter = rig.pm._policy_adapter(rig.p)
    recovered = await adapter.recover_daily(rig.pm, rig.p, [daily], source='test', as_of_ms=rig.closes)
    first = await adapter.prepare_catchup(rig.pm, rig.p)
    assert recovered['catchupReview'] == first
    assert first['review']['requirements'][0]['rung'] == 'target1'
    assert first['review']['requirements'][0]['qty'] == 2
    rig.pm._now = lambda: (rig.closes+1000)/1000
    assert await adapter.prepare_catchup(rig.pm, rig.p) == first
    assert rig.p.policy['cartel']['stateCheckpoint'] == checkpoint
    restored = PositionManager(engine)
    restored._now = rig.pm._now
    restored.register_policy_adapter('options_cartel', CartelPositionAdapter())
    await restored.restore()
    assert restored.get(rig.p.id).policy['cartel']['catchupReview'] == first
    assert engine.orders.placed == [] and rig.p.legs[0].qty == 8
    await restored.stop()


async def test_old_state_without_checkpoint_cannot_gain_invented_history(engine):
    rig = await prepared(engine)
    with pytest.raises(ValueError, match='checkpoint'):
        await rig.pm._policy_adapter(rig.p).prepare_catchup(rig.pm, rig.p)
    assert 'stateCheckpoint' not in rig.p.policy['cartel']
    assert engine.orders.placed == []
