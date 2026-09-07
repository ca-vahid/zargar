"""Campaign replay must score actual modeled allocations and preserve causality."""
import datetime as dt
from dataclasses import replace

import pytest

from tests.test_options_cartel_entry import MIN, OPEN, plan, tape
from zargar.domain import Bar
from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.replay import replay_campaign


def candle(index, opens, closes):
    return Bar("HOOD", "1m", OPEN + index * MIN, opens,
               max(opens, closes) + .01, min(opens, closes) - .01, closes, 500)


def replay(bars, cutoff, **kwargs):
    return replay_campaign(plan(), ExitCampaign.for_profile("may_2026", [55.]),
                           bars, [], as_of_ms=OPEN + cutoff * MIN, **kwargs)


def test_entry_and_exit_fill_only_at_subsequent_open_with_weighted_return():
    bars = tape() + [candle(10, 48.92, 55.), candle(11, 54., 48.92), candle(12, 48.9, 49.)]
    result = replay(bars, 13)
    assert result["status"] == "closed"
    assert [(f["kind"], f["qty"], f["at"]) for f in result["fills"]] == [
        ("entry", 100, OPEN + 10 * MIN), ("target1", 25, OPEN + 11 * MIN),
        ("stop", 75, OPEN + 12 * MIN)]
    assert result["realizedR"] == pytest.approx(((54.-48.92)*25 + (48.9-48.92)*75)/(.52*100))
    assert result["state"]["breakeven"] is True
    assert result["openR"] == 0
    assert result["placesOrders"] is False
    assert result["premiumPathSimulated"] is False


def test_unclosed_future_bars_cannot_change_the_result():
    bars = tape() + [candle(10, 48.92, 55.)]
    first = replay(bars, 11)
    future = candle(11, 100., 10.)
    assert replay(bars + [future], 11) == first
    assert len(first["fills"]) == 1
    assert first["state"]["breakeven"] is False
    assert first["pending"][0]["rung"] == "target1"


def test_missing_next_open_does_not_invent_target_fill():
    result = replay(tape() + [candle(10, 48.92, 55.), candle(12, 55., 55.)], 13)
    assert result["status"] == "missing_data"
    assert result["dataComplete"] is False
    assert len(result["fills"]) == 1


def test_missing_entry_open_and_empty_history_are_unscorable():
    assert replay(tape(), 10)["status"] == "entry_pending"
    assert replay(tape(), 11)["status"] == "missing_data"
    assert replay([], 400)["status"] == "missing_data"


def test_gap_beyond_chase_limit_rejects_modeled_entry():
    result = replay(tape() + [candle(10, 50., 50.)], 11)
    assert result["status"] == "entry_price_rejected"
    assert result["fills"] == []


def test_conflicting_completed_minutes_are_rejected():
    bar = candle(10, 48.92, 49.)
    with pytest.raises(ValueError, match="conflicting"):
        replay(tape() + [bar, replace(bar, volume=501)], 11)


def test_absent_earlier_session_cannot_be_replaced_by_later_signal():
    p = plan(first_session=plan().first_session-dt.timedelta(days=1), created_at=OPEN-86_400_000-MIN,
             baseline_as_of=OPEN-86_400_000-MIN)
    result = replay_campaign(p, ExitCampaign.for_profile("may_2026", [55.]),
                             tape() + [candle(10, 48.92, 49.)], [], as_of_ms=OPEN+11*MIN)
    assert result["entryRead"]["signal"] is not None
    assert result["status"] == "missing_data"
    assert result["fills"] == []
