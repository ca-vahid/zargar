"""Pure pieces of the entry-grid replay: the declared outcome rule and the grid itself."""
from zargar.domain import Bar
from zargar.tools.cartel_entry_grid import outcome, variants

MIN = 60_000


def bars(rows, t0=1_000_000):
    return [Bar("T", "1m", t0+i*MIN, o, h, l, c, 100, source="exchange") for i, (o, h, l, c) in enumerate(rows)]


SIGNAL = {"at": 1_000_000, "referencePrice": 100., "stop": 98.}


def test_target_first_scores_positive_r_net_of_costs():
    o = outcome(SIGNAL, [103.], bars([(100, 101, 99.5, 100.5), (100.5, 103.2, 100.4, 103)]), horizon_end=10**9)
    assert o["exit"] == "target" and o["price"] == 103 and o["r"] == 1.5 and o["rNet"] < 1.5


def test_stop_first_and_gap_through_the_stop_uses_the_open():
    o = outcome(SIGNAL, [103.], bars([(100, 100.5, 97.9, 98.2)]), horizon_end=10**9)
    assert o["exit"] == "stop" and o["r"] == -1.0
    gap = outcome(SIGNAL, [103.], bars([(97, 97.5, 96.5, 97)]), horizon_end=10**9)
    assert gap["price"] == 97 and gap["r"] == -1.5


def test_time_exit_and_no_data():
    o = outcome(SIGNAL, [110.], bars([(100, 101, 99, 101)]), horizon_end=10**9)
    assert o["exit"] == "time" and o["r"] == .5
    assert outcome(SIGNAL, [110.], [], horizon_end=10**9)["exit"] == "no_data"
    assert outcome({**SIGNAL, "stop": 101.}, [110.], [], horizon_end=10**9) is None


def test_grid_is_predeclared_and_complete():
    names = [v[0] for v in variants()]
    assert len(names) == len(set(names)) == 16
    assert "breakout_15m_v1.5_nogap" in names and "breakout_5m_v1_gap" in names and "pivot_30m_5m" in names
