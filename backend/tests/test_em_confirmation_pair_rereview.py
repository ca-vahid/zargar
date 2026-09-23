"""PFU closure re-review (2026-09-17) reproductions for confirmation_pair: the entry minute counts, incomplete horizons stay
pending, the short mirror works, and the proxy declares which gates it does not evaluate."""
import datetime as dt
from zoneinfo import ZoneInfo

from zargar.tools.em_profitability import P04_CONFIRM_WINDOW_BARS, confirmation_pair

NY = ZoneInfo("America/New_York")


def _ms(h, m):
    return int(dt.datetime(2026, 9, 16, h, m, tzinfo=NY).timestamp() * 1000)


def _bar(ts, o, h, l, c):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c}


def test_reviewer_reproduction_entry_minute_reaching_tp1_is_tp1_first_not_stop_first():
    fired = _ms(9, 31); level, stop, tp1, tp2 = 100.0, 99.0, 105.0, 109.0
    bars = [_bar(fired, 99.5, 100.2, 99.0, 99.8),                    # the touch (firing) bar - never the confirming close
            _bar(fired + 60000, 99.9, 101.3, 99.7, 101.0),           # confirming close 101 > level
            _bar(fired + 120000, 101.0, 106.0, 100.8, 102.0),        # ENTRY bar: open 101; reaches 106 >= TP1 in the fill minute
            _bar(fired + 180000, 102.0, 102.2, 97.9, 98.0)]          # would have been a stop close if the fill minute were skipped
    cp = confirmation_pair(bars, fired, "long", level, stop, tp1, tp2, cutoff_ms=fired + 60 * 60000)
    assert cp["outcome"] == "tp1_first" and cp["entry"] == 101.0 and cp["entryTs"] == fired + 120000
    assert cp["resultR"] == round((tp1 - 101.0) / (101.0 - stop), 2)
    assert cp["policy"].startswith("geometry_only_underlying_proxy") and "never-chase cap" in cp["gatesNotEvaluated"]


def test_entry_bar_with_both_target_and_stop_is_unknown():
    fired = _ms(9, 31); level, stop, tp1 = 100.0, 99.0, 105.0
    bars = [_bar(fired, 99.5, 100.2, 99.0, 99.8), _bar(fired + 60000, 99.9, 101.3, 99.7, 101.0),
            _bar(fired + 120000, 101.0, 106.0, 98.0, 98.5)]          # entry minute touches TP1 AND closes through the stop
    cp = confirmation_pair(bars, fired, "long", level, stop, tp1, 109.0, cutoff_ms=fired + 60 * 60000)   # tp2 so R2 passes and the path is judged
    assert cp["outcome"].startswith("unknown (same-bar target and stop")


def test_short_mirror_enters_below_the_level_and_follows_the_low():
    fired = _ms(9, 31); level, stop, tp1, tp2 = 100.0, 101.0, 95.0, 91.0
    bars = [_bar(fired, 100.5, 101.0, 99.8, 100.2),                  # touch from above
            _bar(fired + 60000, 100.1, 100.4, 98.7, 99.0),           # confirming close 99 < level
            _bar(fired + 120000, 99.0, 99.4, 94.5, 96.0),            # entry at 99.0; low 94.5 <= TP1 in the fill minute
            _bar(fired + 180000, 96.0, 102.0, 95.5, 101.5)]
    cp = confirmation_pair(bars, fired, "short", level, stop, tp1, tp2, cutoff_ms=fired + 60 * 60000)
    assert cp["outcome"] == "tp1_first" and cp["entry"] == 99.0 and cp["rr"] == round((99.0 - tp2) / (stop - 99.0), 2)
    # a short whose next open is ABOVE the stop is refused on the stop side
    bars2 = [_bar(fired, 100.5, 101.0, 99.8, 100.2), _bar(fired + 60000, 100.1, 100.4, 98.7, 99.0), _bar(fired + 120000, 101.5, 101.6, 101.0, 101.2)]
    assert confirmation_pair(bars2, fired, "short", level, stop, tp1, tp2, cutoff_ms=fired + 60 * 60000)["outcome"] == "refused_stop_side"


def test_incomplete_horizon_is_pending_unless_the_session_ended():
    fired = _ms(9, 31); level, stop, tp1 = 100.0, 99.0, 105.0
    one = [_bar(fired, 99.5, 100.2, 99.0, 99.8), _bar(fired + 60000, 99.6, 99.9, 99.2, 99.7)]   # one non-confirming bar observed, hours left
    cp = confirmation_pair(one, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 60 * 60000)
    assert cp["outcome"].startswith("pending (horizon incomplete: 1 of") and cp["barsWaited"] == 1
    # the same single bar as the session's LAST bar (explicit close right after it): the horizon is closed by the day's end
    cp2 = confirmation_pair(one, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 2 * 60000, session_close_ms=fired + 2 * 60000)
    assert cp2["outcome"] == "no_confirmation"


def test_intraday_report_cutoff_is_not_the_session_close():
    """Re-review follow-up: a 10:02 ET report with ONE observed bar after a 10:00 touch must stay pending - the report
    cutoff is not the close. The same shape at 15:59 -> 16:00 IS closed by the session (default 16:00 ET close)."""
    level, stop, tp1 = 100.0, 99.0, 105.0
    fired = _ms(10, 0)
    one = [_bar(fired, 99.5, 100.2, 99.0, 99.8), _bar(fired + 60000, 99.6, 99.9, 99.2, 99.7)]   # 10:00 touch, 10:01 bar observed
    cp = confirmation_pair(one, fired, "long", level, stop, tp1, None, cutoff_ms=_ms(10, 2))   # report generated at 10:02 ET
    assert cp["outcome"].startswith("pending (horizon incomplete: 1 of"), cp["outcome"]
    # the clock alone never promotes a truncated observation: a 16:00 report whose bars still end at 10:01 stays pending
    cp_late = confirmation_pair(one, fired, "long", level, stop, tp1, None, cutoff_ms=_ms(16, 0))
    assert cp_late["outcome"].startswith("pending"), "a truncated observation is never promoted to no_confirmation by the clock alone"
    # the session's actual last bar closes it: touch 15:58, one bar 15:59, report at 16:00
    fired2 = _ms(15, 58)
    last = [_bar(fired2, 99.5, 100.2, 99.0, 99.8), _bar(fired2 + 60000, 99.6, 99.9, 99.2, 99.7)]
    cp2 = confirmation_pair(last, fired2, "long", level, stop, tp1, None, cutoff_ms=_ms(16, 0))
    assert cp2["outcome"] == "no_confirmation"
    # and an intraday report at 15:59:30-equivalent (cutoff 16:00 but bars only to 15:58) stays pending - the 15:59 bar is missing
    cp3 = confirmation_pair(last[:1] + [], fired2, "long", level, stop, tp1, None, cutoff_ms=_ms(15, 59))
    assert cp3["outcome"].startswith("pending"), cp3["outcome"]
    # a full window of non-confirming bars is no_confirmation
    full = [_bar(fired, 99.5, 100.2, 99.0, 99.8)] + [_bar(fired + (i + 1) * 60000, 99.6, 99.9, 99.2, 99.7) for i in range(P04_CONFIRM_WINDOW_BARS)]
    assert confirmation_pair(full, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 60 * 60000)["outcome"] == "no_confirmation"


def test_firing_bar_that_already_closed_beyond_the_level_does_not_count_as_the_confirmation():
    fired = _ms(9, 31); level, stop, tp1 = 100.0, 99.0, 105.0
    bars = [_bar(fired, 99.8, 100.6, 99.5, 100.4),                   # firing bar closed ABOVE the level (observed_reclaim)
            _bar(fired + 60000, 100.4, 100.9, 100.1, 100.7),         # first COMPLETED close after it -> this is the confirmation
            _bar(fired + 120000, 100.7, 101.0, 100.5, 100.9)]        # entry at 100.7
    cp = confirmation_pair(bars, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 60 * 60000)
    assert cp["confirmTs"] == fired + 60000 and cp["entry"] == 100.7, "the touch bar is never the confirming close"
