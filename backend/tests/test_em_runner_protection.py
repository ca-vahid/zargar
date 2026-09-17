"""P-06 `tp1-reclaim-runner-exit-v1` after ED-02 (2026-09-17 evening): bound to the trade's own exit orders and their
CONFIRMED executions; underlying proxy for shares AND options unless a covered `tp1-reclaim` observation exists; both
branches followed to their terminal event. Pure tests over synthetic bars, exit records, executions and observations."""
import datetime as dt
from zoneinfo import ZoneInfo

from zargar.tools.em_profitability import P06_POLICY, never_tp1_diag, runner_protection

NY = ZoneInfo("America/New_York")


def _ms(h, m, s=0):
    return int(dt.datetime(2026, 9, 17, h, m, s, tzinfo=NY).timestamp() * 1000)


def _bar(ts, o, h, l, c):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c}


def _ex(order_id, ts, qty, price, commission=0.0, side="SELL"):
    return {"order_id": order_id, "side": side, "qty": qty, "price": price, "commission": commission, "ts": ts}


TP1, ENTRY, STOP = 104.6325, 103.885, 103.3656
CUT = _ms(16, 0)


def _shares_bars():
    # 11:50 bar closed at 11:51 through TP1 (the trim fills at 11:51:03); 11:51 bar closes back BELOW TP1 -> signal at 11:52
    bars = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66), _bar(_ms(11, 51), 104.66, 104.7, 104.55, 104.60),
            _bar(_ms(11, 52), 104.60, 104.9, 104.58, 104.85)]
    bars += [_bar(_ms(11, 53) + i * 60000, 104.7, 104.8, 104.6, 104.72) for i in range(250)]
    return bars


def test_confirmed_trim_then_reclaim_is_an_underlying_proxy_for_shares_with_actual_production_fills():
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "flatten", "orderId": "x-flat", "qty": 33}]
    execs = [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64), _ex("x-flat", _ms(15, 56, 1), 33, 104.7191)]
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, _shares_bars(), CUT, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r["policy"] == P06_POLICY and r["outcome"] == "underlying_proxy_only"
    assert r["tp1FilledQty"] == 14 and r["remainingAtSignal"] == 33 and r["reclaimTs"] == _ms(11, 51) and r["signalTs"] == _ms(11, 52)
    assert r["modeledExitPx"] == 104.60 and r["productionRunner"] == {"qty": 33, "vwap": 104.7191, "fees": 0.0, "kinds": ["flatten"]}
    assert r["underlyingDeltaR"] == round((104.60 - 104.7191) / (ENTRY - STOP), 3)
    assert r["dollarDelta"] is None and r["alternativeRealized"] is None, "shares have no executable quote evidence - no dollars (ED-02)"


def test_cancelled_or_unfilled_trim_is_not_a_trim():
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14, "status": "CANCELLED", "filledQty": 0.0}, {"kind": "flatten", "orderId": "x-flat", "qty": 47}]
    execs = [_ex("x-flat", _ms(15, 56, 1), 47, 104.7191)]
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, _shares_bars(), CUT, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r["outcome"] == "not_eligible" and "never filled" in r["why"]
    assert runner_protection("long", TP1, ENTRY, STOP, [{"kind": "stop", "orderId": "x-s", "qty": 47}], [_ex("x-s", _ms(12, 0), 47, 103.3)], _shares_bars(), CUT,
                             filled_qty=47, multiplier=1.0, instrument="shares")["outcome"] == "not_eligible"


def test_partial_and_intermediate_trims_reduce_the_remainder_and_a_refire_is_ignored():
    # TP1 order for 14 filled 5 (delayed/partial), a tp2 trim of 10 filled before the reclaim, a foreign (refired) order ignored
    bars = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66), _bar(_ms(11, 51), 104.66, 105.3, 104.6, 105.2),
            _bar(_ms(11, 52), 105.2, 105.3, 104.5, 104.55), _bar(_ms(11, 53), 104.55, 104.8, 104.5, 104.7)]
    bars += [_bar(_ms(11, 54) + i * 60000, 104.7, 104.8, 104.6, 104.72) for i in range(250)]
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "tp2", "orderId": "x-tp2", "qty": 10}, {"kind": "flatten", "orderId": "x-flat", "qty": 32}]
    execs = [_ex("x-tp1", _ms(11, 51, 2), 5, 104.64), _ex("x-tp2", _ms(11, 52, 4), 10, 105.29), _ex("x-flat", _ms(15, 56), 32, 104.7191),
             _ex("other-instance", _ms(11, 52, 30), 40, 99.0)]          # not one of this trade's exit orders
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, bars, CUT, filled_qty=47, multiplier=1.0, instrument="shares")
    # the 11:52 bar closes at 11:53 back below TP1; it completed AFTER the tp2 fill at 11:52:04? No: the 11:51 bar completes
    # at 11:52:00 (< 11:52:04) and closed ABOVE TP1; the 11:52 bar completes at 11:53:00 which is after the tp2 fill -> invisible
    assert r["outcome"] == "not_triggered" and "tp2" in r["why"], r


def test_stop_first_wins_and_a_missing_minute_is_unknown():
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "stop", "orderId": "x-stop", "qty": 33}]
    bars = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66), _bar(_ms(11, 51), 104.66, 104.7, 103.2, 103.3)]
    execs = [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64), _ex("x-stop", _ms(11, 51, 40), 33, 103.25)]   # stop filled before the 11:51 bar completed
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, bars, CUT, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r["outcome"] == "not_triggered" and "stop" in r["why"]
    gap = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66), _bar(_ms(11, 53), 104.66, 104.7, 104.55, 104.60)]   # 11:51 and 11:52 missing
    r2 = runner_protection("long", TP1, ENTRY, STOP, exits[:1] + [{"kind": "flatten", "orderId": "x-flat", "qty": 33}],
                           [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64), _ex("x-flat", _ms(15, 56), 33, 104.72)], gap, CUT, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r2["outcome"] == "unknown" and "bar gap" in r2["why"]


def test_options_use_a_covered_reclaim_observation_for_dollars_else_stay_a_proxy():
    tp1, entry, stop = 23.3548, 23.5906, 23.7501
    bars = [_bar(_ms(9, 31), 23.6, 23.62, 23.3, 23.34), _bar(_ms(9, 32), 23.35, 23.6, 23.33, 23.55), _bar(_ms(9, 33), 23.54, 23.7, 23.5, 23.65)]
    bars += [_bar(_ms(9, 34) + i * 60000, 23.65, 23.85, 23.6, 23.80) for i in range(30)]
    exits = [{"kind": "tp1", "orderId": "o-tp1", "qty": 1}, {"kind": "stop", "orderId": "o-stop", "qty": 3}]
    execs = [_ex("o-tp1", _ms(9, 32, 1), 1, 0.80, 1.04), _ex("o-stop", _ms(9, 53, 26), 3, 0.60, 3.12)]
    common = dict(filled_qty=4, multiplier=100.0, instrument="options", avg_fill=0.86, entry_fee_per_unit=1.04, fee_side=1.04)
    r = runner_protection("short", tp1, entry, stop, exits, execs, bars, CUT, **common)
    assert r["outcome"] == "underlying_proxy_only" and r["dollarDelta"] is None and r["remainingAtSignal"] == 3
    assert r["signalTs"] == _ms(9, 33) and r["modeledExitPx"] == 23.54 and r["productionRunner"]["vwap"] == 0.6
    # the underlying-R proxy compares underlying to underlying: the close of the bar containing the stop fill (23.80), not the premium
    assert r["productionRunner"]["underlyingRef"] == 23.80 and r["underlyingDeltaR"] == round((23.80 - 23.54) / (stop - entry), 3)
    obs = [{"rung": "tp1-reclaim", "observedAt": _ms(9, 33, 2), "modeled": {"scorable": True, "bid": 0.78, "coveredQty": 3}}]
    r2 = runner_protection("short", tp1, entry, stop, exits, execs, bars, CUT, observations=obs, **common)
    assert r2["outcome"] == "compared" and r2["modeledExitPx"] == 0.78
    alt = 3 * ((0.78 - 0.86) * 100 - 1.04 - 1.04); prod = 3 * ((0.60 - 0.86) * 100 - 1.04) - 3.12
    assert r2["alternativeRealized"] == round(alt, 2) and r2["productionRealized"] == round(prod, 2) and r2["dollarDelta"] == round(alt - prod, 2)
    # an observation BEFORE the signal, or one that covers only part of the remainder, never makes dollars
    early = [{"rung": "tp1-reclaim", "observedAt": _ms(9, 32, 30), "modeled": {"scorable": True, "bid": 0.78, "coveredQty": 3}}]
    assert runner_protection("short", tp1, entry, stop, exits, execs, bars, CUT, observations=early, **common)["outcome"] == "underlying_proxy_only"
    thin = [{"rung": "tp1-reclaim", "observedAt": _ms(9, 33, 2), "modeled": {"scorable": True, "bid": 0.78, "coveredQty": 1}}]
    r3 = runner_protection("short", tp1, entry, stop, exits, execs, bars, CUT, observations=thin, **common)
    assert r3["outcome"] == "underlying_proxy_only" and "covers only part" in r3["why"]


def test_runner_open_at_the_cutoff_is_partial_never_a_result():
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}]
    execs = [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64)]
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, _shares_bars(), CUT, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r["outcome"] == "partial"


def test_never_tp1_diag_is_descriptive_and_skips_filled_trims():
    bars = [_bar(_ms(9, 40) + i * 60000, 258.0, 258.5 + (i == 5) * 1.9, 257.8, 258.2) for i in range(20)]
    d = never_tp1_diag("long", 258.4742, 255.4297, _ms(9, 40), _ms(10, 0), [(0, {"kind": "flatten", "qty": 19})], bars)
    assert d["heldBars"] == 19 and d["mfeR"] == round((260.4 - 258.4742) / (258.4742 - 255.4297), 3)
    assert never_tp1_diag("long", 258.4742, 255.4297, _ms(9, 40), _ms(10, 0), [(0, {"kind": "tp1", "qty": 5})], bars) is None


def test_tp1_reclaim_signal_is_pure_and_side_aware():
    from zargar.execution.exits import tp1_reclaim_signal
    assert tp1_reclaim_signal("long", 104.6325, 104.60) and not tp1_reclaim_signal("long", 104.6325, 104.70)
    assert tp1_reclaim_signal("short", 23.3548, 23.55) and not tp1_reclaim_signal("short", 23.3548, 23.30)
    assert not tp1_reclaim_signal("long", None, 100.0) and not tp1_reclaim_signal("long", 100.0, None)
