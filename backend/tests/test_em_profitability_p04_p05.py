"""P-04 (descriptive entry strata + PAIRED confirmation comparison) and P-05 (session-window / event-phase cohort),
frozen 2026-09-17 after the PFU-02/03 review. Pure. Nothing here activates a rule, changes risk, widens a chase
limit, turns the friction marker into a gate or creates a trading-window rule."""
import datetime as dt
from zoneinfo import ZoneInfo

from zargar.tools.em_profitability import (COHORT_P01, COHORTS_ADDENDUM, EVENT_CALENDAR, P04_MIN_RR, VERSION, confirmation_pair, render,
                                           session_labels, summarize)

NY = ZoneInfo("America/New_York")


def _ms(h, m, d=16):
    return int(dt.datetime(2026, 9, d, h, m, tzinfo=NY).timestamp() * 1000)


def _trade(sym, conf, fired_ts, net, *, closed=True, cohort=COHORT_P01, date="2026-09-16", pair=None, instrument="options"):
    r = {"symbol": sym, "trigger": "b1", "kind": "bounce", "direction": "long", "cohort": cohort, "confirmation": conf, "window": "prime_open",
         "filledQty": 1, "closed": closed, "netRealized": net if closed else None, "fees": 2.08, "roomBin": "1-3R", "instrument": instrument,
         "policyVersion": "deterministic-entry-v1", "decisionId": f"d-{sym}", "runId": f"r-{sym}", "contract": None, **session_labels(fired_ts, date)}
    if pair: r["confirmationPair"] = pair
    return r


def _refused(sym, conf, fired_ts, proxy, *, cohort=COHORT_P01, date="2026-09-16", pair=None):
    r = {"symbol": sym, "trigger": "b1", "kind": "bounce", "direction": "long", "cohort": cohort, "confirmation": conf, "window": "prime_open",
         "refusal": "budget", "underlyingProxy": proxy, "roomBin": "1-3R", "policyVersion": "deterministic-entry-v1", "instrument": "options",
         "decisionId": f"d-{sym}", "runId": f"r-{sym}", "contract": None, **session_labels(fired_ts, date)}
    if pair: r["confirmationPair"] = pair
    return r


def test_p04_strata_are_descriptive_and_a_budget_refused_tp1_touch_is_not_a_sacrificed_winner():
    assert VERSION == "profitability-cohorts-v1" and COHORTS_ADDENDUM.startswith("p04-p05-2026-09-17")   # p06 addendum appended 2026-09-18
    data = {"date": "2026-09-16", "cutoff": "16:00", "attempts": [],
            "trades": [_trade("CRCL", "observed_reclaim", _ms(9, 32), -94.11), _trade("SNDK", "observed_reclaim", _ms(15, 15), 27.16),
                       _trade("CVNA", "anticipated", _ms(9, 34), -29.49)],
            "refused": [_refused("NBIS", "anticipated", _ms(15, 21), "tp1_first"), _refused("NOW", "observed_reclaim", _ms(9, 31), "stop_first"),
                        _refused("BE", "anticipated", _ms(9, 38), "unresolved: no bars")]}
    s = summarize(data)
    p04 = s["p04"]
    assert "sacrificedWinners" not in p04["confirmation=anticipated"], "the misleading name is gone"
    assert p04["confirmation=anticipated"]["underlyingTp1FirstRefused"] == 1 and p04["confirmation=anticipated"]["rejected"] == 2
    assert p04["confirmation=observed_reclaim"] == {"fills": 2, "net": -66.95, "open": 0, "winners": 1, "losers": 1, "rejected": 1, "underlyingTp1FirstRefused": 0, "unknownProxy": 0}
    md = render(data, s)
    assert "DESCRIPTIVE" in md and "not a net winner, not a policy sacrifice" in md


def _bars(start_ts, closes, opens=None, highs=None, lows=None):
    out = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c; h = highs[i] if highs else max(o, c) + 0.2; lo = lows[i] if lows else min(o, c) - 0.2
        out.append({"ts": start_ts + i * 60000, "open": o, "high": h, "low": lo, "close": c})
    return out


def test_paired_comparison_enters_at_the_next_open_after_a_confirming_close_and_follows_the_underlying():
    fired = _ms(9, 31); level, stop, tp1, tp2 = 100.0, 99.5, 102.0, 104.0
    # bars start AT the touch bar (09:31 = fired, excluded from the path); 09:32 closes below the level (no confirmation
    # yet), 09:33 CLOSES above -> confirmed; entry at the 09:34 OPEN (100.4; risk 0.9, R2 to TP2 = 4.0); TP1 touched 09:36.
    bars = _bars(fired, [99.8, 99.9, 100.3, 100.6, 101.2, 102.3], opens=[99.9, 99.8, 99.9, 100.4, 100.7, 101.3])
    cp = confirmation_pair(bars, fired, "long", level, stop, tp1, tp2, cutoff_ms=fired + 60 * 60000)
    assert cp["outcome"] == "tp1_first" and cp["entry"] == 100.4 and cp["barsWaited"] == 2 and cp["confirmTs"] == fired + 2 * 60000 and cp["entryTs"] == fired + 3 * 60000
    assert cp["rr"] == round((tp2 - 100.4) / (100.4 - stop), 2) and cp["resultR"] == round((tp1 - 100.4) / (100.4 - stop), 2)


def test_paired_comparison_keeps_refusals_distinct_and_never_uses_a_same_close_fill():
    fired = _ms(9, 31); level, stop, tp1 = 100.0, 99.0, 102.0
    # no completed close beyond the level within the window -> no_confirmation (NOT a budget refusal)
    bars = _bars(fired, [99.8] * 12)
    assert confirmation_pair(bars, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 60 * 60000)["outcome"] == "no_confirmation"
    # a confirming close whose next open is at TP1 -> refused_no_room; whose next open leaves R2 below the frozen bar -> refused_r2
    bars = _bars(fired, [100.5, 102.0, 102.1], opens=[99.9, 100.2, 102.0])
    assert confirmation_pair(bars, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 60 * 60000)["outcome"] == "refused_no_room"
    bars = _bars(fired, [100.5, 101.0, 101.9], opens=[99.9, 100.2, 101.0])
    cp = confirmation_pair(bars, fired, "long", level, stop, tp1, 103.0, cutoff_ms=fired + 60 * 60000)
    assert cp["outcome"] == "refused_r2" and cp["rr"] < P04_MIN_RR
    # the entry is the NEXT bar's open, never the confirming bar's close: with no following bar the outcome is unknown
    bars = _bars(fired, [99.8, 100.5], opens=[99.9, 99.9])
    assert confirmation_pair(bars, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 60 * 60000)["outcome"].startswith("unknown (no executable bar")
    # a bar gap (before or after the confirming close) is unknown, not a result
    bars = _bars(fired, [99.8, 100.5, 100.6]); bars[2]["ts"] += 60000
    assert confirmation_pair(bars, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 60 * 60000)["outcome"].startswith("unknown (")
    bars = _bars(fired, [99.8, 99.9, 100.6]); bars[1]["ts"] += 60000
    assert confirmation_pair(bars, fired, "long", level, stop, tp1, None, cutoff_ms=fired + 60 * 60000)["outcome"].startswith("unknown (bar gap before")


def test_paired_summary_keeps_baseline_winners_and_losers_and_marks_option_dollars_unknown():
    win_pair = {"policy": "confirmed_close_then_next_open", "outcome": "stop_first", "resultR": -1.0, "entry": 100.4, "rr": 3.2, "barsWaited": 2}
    lose_pair = {"policy": "confirmed_close_then_next_open", "outcome": "tp1_first", "resultR": 1.6, "entry": 100.2, "rr": 3.8, "barsWaited": 1}
    data = {"date": "2026-09-16", "cutoff": "16:00", "attempts": [],
            "trades": [_trade("W", "anticipated", _ms(9, 32), 27.16, pair=win_pair, instrument="shares"), _trade("L", "anticipated", _ms(9, 40), -94.11, pair=lose_pair)],
            "refused": [_refused("R", "anticipated", _ms(15, 21), "tp1_first", pair={"policy": "confirmed_close_then_next_open", "outcome": "no_confirmation", "resultR": None, "barsWaited": 10})]}
    s = summarize(data); pp = s["p04Paired"]
    assert pp["baselineWinnersInSample"] == 1 and pp["baselineLosersInSample"] == 1
    assert pp["outcomes"] == {"no_confirmation": 1, "stop_first": 1, "tp1_first": 1} and pp["resolvedR"] == {"n": 2, "sumR": 0.6}
    by = {r["symbol"]: r for r in pp["rows"]}
    assert by["L"]["dollarsAtDelayedEntry"].startswith("unknown (no option quote") and by["W"]["dollarsAtDelayedEntry"].startswith("shares")
    assert by["R"]["baseline"]["kind"] == "refused" and by["R"]["confirmation"]["outcome"] == "no_confirmation"
    assert s["baseline"]["fills"] == 2 and s["cohort"]["fills"] == 2, "the paired rows must not clobber the summary's baseline block"
    md = render(data, s)
    assert "| Baseline (all EM fills) | 2 |" in md and "P-04 PAIRED" in md


def test_p05_uses_the_shared_clock_and_event_phase_with_unknown_calendar_coverage():
    assert EVENT_CALENDAR["2026-09-16"]["atEt"] == "14:00" and EVENT_CALENDAR["2026-09-16"]["retrospective"] is True
    lab = session_labels(_ms(10, 45), "2026-09-16")
    assert lab["sessionWindow"] == "midday", "10:45 ET is midday, not afternoon"
    assert lab["eventPhase"] == "pre_event:FOMC" and lab["firedAtIso"].endswith("-04:00")
    assert session_labels(_ms(13, 59), "2026-09-16")["eventPhase"] == "pre_event:FOMC"
    assert session_labels(_ms(14, 0), "2026-09-16")["eventPhase"] == "post_event:FOMC"
    assert session_labels(_ms(15, 0), "2026-09-16")["sessionWindow"] == "prime_close"
    other = session_labels(_ms(10, 0, d=17), "2026-09-17")
    assert other["eventPhase"] == "unknown_calendar" and other["eventProvenance"] == "no calendar entry", "no calendar entry is unknown coverage, never ordinary"
    data = {"date": "2026-09-16", "cutoff": "16:00", "attempts": [],
            "trades": [_trade("A", "observed_reclaim", _ms(9, 32), -94.11), _trade("B", "observed_reclaim", _ms(15, 15), 27.16), _trade("C", "anticipated", _ms(10, 45), -5.0, cohort=None)],
            "refused": [_refused("D", "anticipated", _ms(15, 21), "tp1_first"), _refused("E", "anticipated", _ms(10, 0, d=17), "unknown", date="2026-09-17")]}
    s = summarize(data); p05 = s["p05"]
    assert p05["prime_open|pre_event:FOMC"]["fills"] == 1 and p05["midday|pre_event:FOMC"]["fills"] == 1
    assert p05["prime_close|post_event:FOMC"] == {"fills": 1, "net": 27.16, "open": 0, "winners": 1, "losers": 0, "rejected": 1, "underlyingTp1FirstRefused": 1, "unknownProxy": 0}
    assert p05["prime_open|unknown_calendar"]["rejected"] == 1
    md = render(data, s)
    assert "never a trading-window rule" in md and "unknown_calendar" in md
