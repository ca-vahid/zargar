"""Boundary regressions for the research pricing model (v2). Synthetic prints only: no network, no database, no runtime.
Run: PYTHONPATH=<worktree>/backend python -m pytest <this file> -q -p no:cacheprovider
"""
import math, sys, pathlib, datetime as dt
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import realmodel as rm  # noqa: E402

MIN = 60_000
T = int(dt.datetime(2026, 6, 1, 14, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)     # a 2m boundary (10:00 ET)


def bar(o, h=None, l=None, c=None, vw=None):
    return {"o": o, "h": h if h is not None else o, "l": l if l is not None else o, "c": c if c is not None else o,
            "vw": vw if vw is not None else o}


@pytest.fixture(autouse=True)
def ctx():
    rm._mem.clear()
    rm.LOG.clear()
    rm.CTX.update(symbol="SPY", date="2026-06-01", data=None, offline=True, touch_mode="proxy", ladder=3,
                  und={T - 2 * MIN: {"h": 100.4, "l": 100.0}, T - MIN: {"h": 101.2, "l": 100.3}})
    yield


def model():
    return rm.RealPremiumModel(sigma=0.2, fee_per_contract=1.04, slippage_ticks=0)


def put(strike, prints, call=True):
    rm._mem[rm.occ("SPY", "2026-06-01", call, strike)] = prints


def pick(m):
    return m.pick_strike(100.2, T, "long", target_premium=0.60, premium_floor=0.20)


def test_selection_never_uses_a_price_printed_after_the_decision():
    """101C is in band BEFORE the decision; 102C only becomes in band in the decision minute itself. v1 chose on the minute
    that starts at T (and up to two later ones); v2 must choose 101C on what existed at T and execute it afterwards."""
    put(101, {T - MIN: bar(0.58), T: bar(0.62)})
    put(102, {T - MIN: bar(0.05), T: bar(0.60)})                 # exactly on target, but only AFTER the decision
    put(103, {})
    k, px = pick(model())
    assert k == 101 and px == 0.62
    e = [x for x in rm.LOG if x["kind"] == "entry"][-1]
    assert e["observedPx"] == 0.58 and e["observationTs"] == T - MIN and e["execPx"] == 0.62 and e["executionTs"] == T
    assert e["observationTs"] < T <= e["executionTs"]


def test_a_contract_seen_only_after_the_decision_is_not_eligible():
    put(101, {T: bar(0.60), T + MIN: bar(0.61)})
    put(102, {})
    put(103, {})
    assert pick(model()) is None
    assert rm.LOG[-1]["outcome"] == "no_observed_contract_in_band"


def test_a_stale_observation_is_not_carried_into_the_selection():
    put(101, {T - 5 * MIN: bar(0.60), T: bar(0.60)})             # last print five minutes old: beyond SEL_AGE_MIN
    put(102, {})
    put(103, {})
    assert pick(model()) is None


def test_time_dependent_eligibility_is_rechecked_at_the_execution_price():
    put(101, {T - MIN: bar(0.60), T: bar(0.95)})                 # in band when chosen, above the 0.90 chase cap when executed
    put(102, {})
    put(103, {})
    assert pick(model()) is None and rm.LOG[-1]["outcome"] == "refused_above_chase_cap"
    rm.LOG.clear()
    put(101, {T - MIN: bar(0.60), T + 3 * MIN: bar(0.60)})       # no print inside the execution window
    assert pick(model()) is None and rm.LOG[-1]["outcome"] == "no_execution_print"
    rm.LOG.clear()
    put(101, {T - MIN: bar(0.60), T + MIN: bar(0.64)})           # executed one minute late: the lag is carried explicitly
    k, px = pick(model())
    assert (k, px) == (101, 0.64) and rm.LOG[-1]["execLagMin"] == 1


def _mark_from(name, m, spot, strike, ts, reason=""):
    """call model.mark from a frame named like the read's caller, which is how the model tells an exit from a management mark"""
    ns = {}
    exec(f"def {name}(m, spot, strike, ts, reason):\n    return m.mark(spot, strike, ts, call=True)\n", ns)
    return ns[name](m, spot, strike, ts, reason)


def test_a_missing_management_mark_is_unknown_never_zero():
    put(101, {T - 6 * MIN: bar(0.60)})
    v = _mark_from("simulate_session", model(), 100.0, 101, T - 2 * MIN)
    assert math.isnan(v) and rm.LOG[-1]["kind"] == "mark_unknown"
    assert math.isnan(model().sell(v).premium) and math.isnan(model().buy(v).premium)


def test_a_stale_print_is_not_carried_into_a_stop_or_trim_mark():
    put(101, {T - 3 * MIN: bar(0.30), T - MIN: bar(0.55, c=0.57)})
    assert _mark_from("simulate_session", model(), 100.0, 101, T - 2 * MIN) == 0.57        # the print inside the bar
    put(101, {T - 3 * MIN: bar(0.30)})
    assert math.isnan(_mark_from("simulate_session", model(), 100.0, 101, T - 2 * MIN))    # the older print is not reused


def test_an_exit_without_a_print_is_censored_not_priced():
    put(101, {T + 9 * MIN: bar(0.10)})
    v = _mark_from("close_fraction", model(), 100.0, 101, T, "2m close 99.9 through the EMA13 (S1 one-candle stop)")
    assert math.isnan(v) and rm.LOG[-1]["kind"] == "exit_unknown"
    put(101, {T + 2 * MIN: bar(0.41)})
    assert _mark_from("close_fraction", model(), 100.0, 101, T, "premium stop") == 0.41


def test_target_touch_is_a_bounded_scenario_not_one_fill():
    # the underlying touched 101.0 in the minute T-1; that option minute printed between 0.70 and 1.10, VWAP 0.90; the bar closed and
    # the next minute opened at 0.75
    put(101, {T - MIN: bar(0.72, h=1.10, l=0.70, c=0.80, vw=0.90), T: bar(0.75)})
    out = {}
    for mode in ("conservative", "proxy", "optimistic"):
        rm.CTX["touch_mode"] = mode
        out[mode] = _mark_from("close_fraction", model(), 101.0, 101, T, "target 101.00 (planned level) touched — sell at target")
    assert out == {"conservative": 0.75, "proxy": 0.90, "optimistic": 1.10}
    assert out["conservative"] <= out["proxy"] <= out["optimistic"]
    rm.CTX["touch_mode"] = "proxy"
    put(101, {T: bar(0.75)})                                     # no print in the touch minute: fall back to the bar-close exit
    assert _mark_from("close_fraction", model(), 101.0, 101, T, "target 101.00 touched") == 0.75
