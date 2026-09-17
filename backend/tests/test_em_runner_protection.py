"""P-06 `tp1-reclaim-runner-exit-v1` (frozen 2026-09-18, review package B) and the never-TP1 diagnostic: pure tests over
synthetic bars and exit events. The 09-17 shapes: SCHW (long shares) closed back through TP1 on the bar after the
trim -> the candidate exits 33 shares at the next open (worse than the flatten); BMNR (short puts) reclaimed on the
trim bar's successor -> underlying-R only, premium unknown."""
import datetime as dt
from zoneinfo import ZoneInfo

from zargar.tools.em_profitability import P06_POLICY, never_tp1_diag, runner_protection

NY = ZoneInfo("America/New_York")


def _ms(h, m):
    return int(dt.datetime(2026, 9, 17, h, m, tzinfo=NY).timestamp() * 1000)


def _bar(ts, o, h, l, c):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c}


def test_long_shares_reclaim_exits_at_the_next_open_and_is_compared_in_dollars():
    tp1 = 104.6325; cutoff = _ms(16, 0)
    bars = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66),     # this bar's close at 11:51 triggered the trim
            _bar(_ms(11, 51), 104.66, 104.7, 104.55, 104.60),    # closes back BELOW TP1 -> reclaim
            _bar(_ms(11, 52), 104.60, 104.9, 104.58, 104.85),    # next open 104.60 = the candidate's exit
            _bar(_ms(11, 53), 104.85, 104.96, 104.7, 104.9)] + [_bar(_ms(12, 0) + i * 60000, 104.7, 104.8, 104.6, 104.72) for i in range(236)]
    exits = [(_ms(11, 51), {"kind": "tp1", "qty": 14}), (_ms(15, 56), {"kind": "flatten", "qty": 33})]
    r = runner_protection("long", tp1, 103.885, 103.3656, exits, bars, cutoff, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r["policy"] == P06_POLICY and r["outcome"] == "compared" and r["remainingQty"] == 33
    assert r["reclaimTs"] == _ms(11, 51) and r["modeledExitPx"] == 104.60 and r["productionExitRef"] == 104.72
    assert r["dollarDelta"] == round((104.60 - 104.72) * 33, 2) < 0, "the candidate gave up the later flatten price here"
    assert r["premium"] is None


def test_short_options_reclaim_is_underlying_proxy_only():
    tp1 = 23.3548; cutoff = _ms(16, 0)
    bars = [_bar(_ms(9, 31), 23.6, 23.62, 23.3, 23.34),          # trim bar (close through TP1 at 09:32)
            _bar(_ms(9, 32), 23.35, 23.6, 23.33, 23.55),         # closes back ABOVE TP1 -> reclaim (short)
            _bar(_ms(9, 33), 23.54, 23.7, 23.5, 23.65)] + [_bar(_ms(9, 34) + i * 60000, 23.65, 23.85, 23.6, 23.80) for i in range(20)]
    exits = [(_ms(9, 32), {"kind": "tp1", "qty": 1}), (_ms(9, 53), {"kind": "stop", "qty": 3})]
    r = runner_protection("short", tp1, 23.5906, 23.7501, exits, bars, cutoff, filled_qty=4, multiplier=100.0, instrument="options")
    assert r["outcome"] == "underlying_proxy_only" and r["dollarDelta"] is None and r["premium"] == "unknown"
    assert r["modeledExitPx"] == 23.54 and r["productionExitRef"] == 23.80
    assert r["underlyingDeltaR"] == round((23.80 - 23.54) / (23.7501 - 23.5906), 3) > 0, "the candidate exits before the later stop on the underlying proxy"


def test_no_reclaim_and_no_trim_cases_are_labelled_not_invented():
    tp1 = 104.6325; cutoff = _ms(16, 0)
    bars = [_bar(_ms(11, 50) + i * 60000, 104.7, 104.9, 104.65, 104.8) for i in range(30)]   # never closes back below TP1
    exits = [(_ms(11, 51), {"kind": "tp1", "qty": 14}), (_ms(12, 15), {"kind": "tp2", "qty": 33})]
    r = runner_protection("long", tp1, 103.885, 103.3656, exits, bars, cutoff, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r["outcome"] == "not_triggered"
    r2 = runner_protection("long", tp1, 103.885, 103.3656, [(_ms(12, 15), {"kind": "stop", "qty": 47})], bars, cutoff, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r2["outcome"] == "not_eligible" and "no completed TP1 trim" in r2["why"]
    r3 = runner_protection("long", tp1, 103.885, 103.3656, [(_ms(11, 51), {"kind": "tp1", "qty": 47})], bars, cutoff, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r3["outcome"] == "not_eligible", "a trim that closed the whole position leaves no runner"
    # runner still open at the cutoff (the only exit is the trim) = partial, never a result
    r4 = runner_protection("long", tp1, 103.885, 103.3656, [(_ms(11, 51), {"kind": "tp1", "qty": 14})], bars, cutoff, filled_qty=47, multiplier=1.0, instrument="shares")
    assert r4["outcome"] == "partial"


def test_never_tp1_diag_is_descriptive_and_skips_trimmed_positions():
    bars = [_bar(_ms(9, 40) + i * 60000, 258.0, 258.5 + (i == 5) * 1.9, 257.8, 258.2) for i in range(20)]   # one spike to 260.4
    d = never_tp1_diag("long", 258.4742, 255.4297, _ms(9, 40), _ms(10, 0), [(_ms(10, 0), {"kind": "flatten", "qty": 19})], bars)
    assert d["heldBars"] == 19 and d["mfeR"] == round((260.4 - 258.4742) / (258.4742 - 255.4297), 3)
    assert never_tp1_diag("long", 258.4742, 255.4297, _ms(9, 40), _ms(10, 0), [(_ms(9, 50), {"kind": "tp1", "qty": 5})], bars) is None
