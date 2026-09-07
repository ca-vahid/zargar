"""Source campaigns, actual-fill accounting, small lots and daily causality."""
import pytest

from zargar.techniques.options_cartel.exits import (
    ExitCampaign,
    ExitState,
    allocations,
    decide_exits,
    record_fill,
)

from .test_options_cartel_setups import histories


def position(qty=8):
    return ExitState(position_id="p1", symbol="TEST", direction="long", entry=100, stop=95,
                     initial_qty=qty, remaining_qty=qty)


def evaluate(campaign, state, price=110, **kwargs):
    bars, _ = histories()
    return decide_exits(campaign, state, bars, as_of_ms=bars[-1].closes_at,
                        observed_price=price, daily_close=False, **kwargs)


def test_profile_fractions_and_september_ambiguity_are_explicit():
    may = ExitCampaign.for_profile("may_2026", [110])
    june = ExitCampaign.for_profile("june_2026", [110, 120])
    assert [r.id for r in may.rungs] == ["target1", "ema8", "ema21", "ema50"]
    assert [r.id for r in june.rungs] == ["target1", "target2", "ema8", "ema21"]
    with pytest.raises(ValueError, match="explicitly reviewed"):
        ExitCampaign.for_profile("september_2026", [110])
    sept = ExitCampaign.for_profile("september_2026", [110], september_fractions=[.25, .25, .25, .125, .125])
    assert "reviewer" in sept.allocation_note
    assert ExitCampaign.model_validate_json(sept.model_dump_json()) == sept


def test_january_volume_example_requires_three_targets_and_retains_ema8_runner():
    with pytest.raises(ValueError, match='three reviewed'):
        ExitCampaign.for_profile('january_2026_volume', [110, 120])
    campaign = ExitCampaign.for_profile('january_2026_volume', [110, 120, 130])
    assert [r.id for r in campaign.rungs] == ['target1', 'target2', 'target3', 'ema8']
    assert [r.fraction for r in campaign.rungs] == [.25]*4 and campaign.source_refs == ('S05',)
    state = position()
    for i, price in enumerate([110, 120, 130]):
        decision = evaluate(campaign, state, price=price)['decisions'][0]
        assert decision['rung'] == f'target{i+1}' and decision['qty'] == 2
        state = record_fill(campaign, state, fill_id=f'fill{i}', rung=decision['rung'], qty=2)
    assert state.remaining_qty == 2 and state.breakeven


@pytest.mark.parametrize("qty", [1, 2, 3, 4, 5, 7, 10, 101])
def test_whole_lot_allocation_never_exceeds_position(qty):
    campaign = ExitCampaign.for_profile("may_2026", [110])
    sizes = allocations(campaign, qty)
    assert sum(sizes.values()) == qty
    assert all(isinstance(q, int) and q >= 0 for q in sizes.values())
    assert sizes["ema50"] >= 1


def test_signal_does_not_advance_trim_or_move_stop_until_fill():
    campaign, state = ExitCampaign.for_profile("may_2026", [110]), position()
    read = evaluate(campaign, state)
    assert read["decisions"][0]["qty"] == 2 and not state.breakeven
    partial = record_fill(campaign, state, fill_id="f1", rung="target1", qty=1)
    assert partial.stop == 95 and not partial.breakeven
    filled = record_fill(campaign, partial, fill_id="f2", rung="target1", qty=1)
    assert filled.stop == 100 and filled.breakeven and filled.remaining_qty == 6
    assert record_fill(campaign, filled, fill_id="f2", rung="target1", qty=1) == filled


def test_pending_exit_cannot_stack_but_protective_stop_requests_replacement():
    campaign, state = ExitCampaign.for_profile("may_2026", [110]), position()
    assert evaluate(campaign, state, pending_qty=2)["decisions"] == []
    stop = evaluate(campaign, state, price=94, pending_qty=2)["decisions"][0]
    assert stop["qty"] == 8 and stop["replacePending"] and stop["reduceOnly"]


def test_expiry_floor_precedes_profit_taking():
    campaign, state = ExitCampaign.for_profile("may_2026", [110]), position()
    assert evaluate(campaign, state, dte=1)["decisions"][0]["rung"] == "expiry"


def test_daily_ema_closes_all_remaining_even_if_intermediate_targets_never_hit():
    campaign = ExitCampaign.for_profile("june_2026", [110, 200])
    state = record_fill(campaign, position(), fill_id="f1", rung="target1", qty=2)
    bars, _ = histories()
    bars[-1] = bars[-1].model_copy(update={"open": 110, "close": 110, "low": 109, "high": 111})
    result = decide_exits(campaign, state, bars, as_of_ms=bars[-1].closes_at, observed_price=110, daily_close=True)
    assert sum(d["qty"] for d in result["decisions"]) == 6
    assert result["decisions"][-1]["rung"] == "ema21"


def test_intraday_price_below_ema_does_not_fake_a_daily_exit():
    campaign = ExitCampaign.for_profile("may_2026", [110])
    state = record_fill(campaign, position(), fill_id="f1", rung="target1", qty=2)
    assert evaluate(campaign, state, price=105)["decisions"] == []


def test_one_contract_does_not_invent_fractional_trims_or_unearned_breakeven():
    campaign, state = ExitCampaign.for_profile("may_2026", [110]), position(1)
    assert evaluate(campaign, state)["decisions"] == []
    assert not state.breakeven
    bars, _ = histories()
    bars[-1] = bars[-1].model_copy(update={"open": 110, "close": 110, "low": 109, "high": 111})
    decisions = decide_exits(campaign, state, bars, as_of_ms=bars[-1].closes_at, observed_price=110,
                             daily_close=True)["decisions"]
    assert len(decisions) == 1 and decisions[0]["qty"] == 1


def test_extension_only_uses_completed_daily_indicators_and_filled_first_trim():
    campaign = ExitCampaign.for_profile("september_2026", [110], september_fractions=[.25, .25, .25, .125, .125])
    state = position()
    assert [d["rung"] for d in evaluate(campaign, state, price=180)["decisions"]] == ["target1"]
    state = record_fill(campaign, state, fill_id="f1", rung="target1", qty=2)
    assert [d["rung"] for d in evaluate(campaign, state, price=180)["decisions"]] == ["extension"]


def test_daily_close_requires_exact_session_boundary_and_price():
    campaign, state = ExitCampaign.for_profile("may_2026", [110]), position()
    bars, _ = histories()
    for at, price in [(bars[-1].closes_at-1, bars[-1].close), (bars[-1].closes_at, 200)]:
        with pytest.raises(ValueError, match="actual close boundary"):
            decide_exits(campaign, state, bars, as_of_ms=at, observed_price=price, daily_close=True)


def test_restored_fill_state_reconciles_and_bearish_breakeven_tightens_downward():
    campaign = ExitCampaign.for_profile("may_2026", [90])
    state = position().model_copy(update={"direction": "short", "stop": 105})
    assert evaluate(campaign, state, price=90)["decisions"][0]["qty"] == 2
    state = record_fill(campaign, state, fill_id="f1", rung="target1", qty=2)
    assert state.stop == 100 and ExitState.model_validate_json(state.model_dump_json()) == state
    with pytest.raises(ValueError):
        record_fill(campaign, state, fill_id="f2", rung="target1", qty=99)


def test_missing_indicator_history_never_blocks_protective_exit():
    campaign, state = ExitCampaign.for_profile("may_2026", [110]), position()
    result = decide_exits(campaign, state, [], as_of_ms=0, observed_price=94, daily_close=False)
    assert result["decisions"][0]["rung"] == "stop"
