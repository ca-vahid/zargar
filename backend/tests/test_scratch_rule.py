"""T-14 (2026-09-10): the scratch rule - once a trade is `scratch_r` R in favour, trim
`scratch_trim` and move the stop to breakeven. Off by default (scratch_r=0) so the
walk-forward can sweep it; the simulator and the live exit decision must agree."""
from dataclasses import dataclass, field

from zargar.domain import Bar
from zargar.execution.exits import plan_exit
from zargar.marketstructure.outcome import simulate_plan


def _bar(i, o, hi, lo, c):
    return Bar(symbol="X", tf="1m", ts=1_000_000 + i * 60_000, open=o, high=hi, low=lo, close=c, volume=1000)


def _plan():
    return {"entry": {"price": 100.0, "basis": "on_break"}, "stop": {"price": 99.0}, "direction": "long",
            "targets": [{"price": 105.0}, {"price": 108.0}, {"price": 111.0}], "setupType": "support_bounce"}


def _up_then_back_to_stop():
    # fill at 100 (bar 0), runs to 101.2 (+1.2R), then reverses and closes through 99
    return [_bar(0, 100, 100.2, 99.8, 100), _bar(1, 100, 100.6, 99.9, 100.5), _bar(2, 100.5, 101.2, 100.3, 101.0),
            _bar(3, 101, 101.1, 100.2, 100.3), _bar(4, 100.3, 100.4, 99.6, 99.7), _bar(5, 99.7, 99.8, 98.7, 98.8)]


def test_simulator_without_scratch_gives_the_full_loss():
    sim = simulate_plan(_up_then_back_to_stop(), 0, _plan(), entry_window=1, horizon=60, stop_on="close")
    assert sim["outcome"] == "stopped" and sim["rMultiple"] < -1.0 and sim["scratched"] is False


def test_simulator_scratch_banks_half_and_exits_the_rest_at_breakeven():
    sim = simulate_plan(_up_then_back_to_stop(), 0, _plan(), entry_window=1, horizon=60, stop_on="close",
                        scratch_r=0.75, scratch_trim=0.5)
    assert sim["scratched"] is True and sim["outcome"] == "scratched"
    # half sold at +0.75R; the rest leaves at the breakeven stop's quote brake (0.25R beyond, on the original risk)
    assert abs(sim["rMultiple"] - (0.5 * 0.75 + 0.5 * -0.25)) < 1e-6


def test_simulator_scratch_does_not_touch_a_winner():
    bars = [_bar(0, 100, 100.2, 99.8, 100), _bar(1, 100, 102, 99.9, 101.9), _bar(2, 101.9, 105.5, 101.5, 105.2),
            _bar(3, 105, 108.5, 104.9, 108.2), _bar(4, 108, 111.5, 107.9, 111.2)]
    base = simulate_plan(bars, 0, _plan(), entry_window=1, horizon=60, stop_on="close")
    sc = simulate_plan(bars, 0, _plan(), entry_window=1, horizon=60, stop_on="close", scratch_r=0.75)
    assert base["outcome"] == "tp3" and sc["outcome"] == "tp2"       # the trimmed half means the ladder runs out at TP2
    assert sc["rMultiple"] < base["rMultiple"]          # the trimmed half caps the upside - the sweep decides if it pays


@dataclass
class FakeTrade:
    remaining: float
    filled_qty: float
    trims_done: int
    targets: list[float]
    stop: float
    entry: float = 100.0
    sec_type: str = "STK"
    direction: str = "long"
    scratched: bool = False
    exits: list[dict] = field(default_factory=list)

    @property
    def pending_exit_qty(self) -> float:
        return 0.0


def test_live_exit_scratch_decision_then_breakeven_stop():
    tr = FakeTrade(remaining=10, filled_qty=10, trims_done=0, targets=[105, 108, 111], stop=99.0)
    d = plan_exit(tr, _bar(1, 100, 100.9, 99.9, 100.8), close_ms=10**12, flatten_minutes=5, stop_on="close",
                  scratch_r=0.75, scratch_trim=0.5)
    assert d is not None and d.kind == "scratch" and d.qty == 5 and d.new_trims_done == 0
    tr.scratched = True; tr.stop = tr.entry; tr.remaining = 5          # what the runner does
    assert plan_exit(tr, _bar(2, 100.8, 101, 100.2, 100.5), close_ms=10**12, flatten_minutes=5, stop_on="close",
                     scratch_r=0.75) is None                             # no second scratch
    d2 = plan_exit(tr, _bar(3, 100.5, 100.6, 99.8, 99.9), close_ms=10**12, flatten_minutes=5, stop_on="close",
                   scratch_r=0.75)
    assert d2 is not None and d2.kind == "stop" and d2.qty == 5       # breakeven stop on the close through 100


def test_live_exit_scratch_keeps_a_single_contract_and_only_moves_the_stop():
    tr = FakeTrade(remaining=1, filled_qty=1, trims_done=0, targets=[105, 108, 111], stop=99.0, sec_type="OPT")
    d = plan_exit(tr, _bar(1, 100, 100.9, 99.9, 100.8), close_ms=10**12, flatten_minutes=5, stop_on="close",
                  scratch_r=0.75, scratch_trim=0.5)
    assert d is not None and d.kind == "scratch" and d.qty == 0


def test_scratch_is_off_by_default():
    tr = FakeTrade(remaining=10, filled_qty=10, trims_done=0, targets=[105, 108, 111], stop=99.0)
    assert plan_exit(tr, _bar(1, 100, 100.9, 99.9, 100.8), close_ms=10**12, flatten_minutes=5, stop_on="close") is None
