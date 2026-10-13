"""Tips measured record (2026-10-12), pure: the option replay's entry/exit rules, the journaled snapshot's shape and
the lines the analyst's header carries. No network, no LLM, no database."""
import datetime as dt
from zoneinfo import ZoneInfo

from zargar.techniques.tip import record as R
from zargar.tools import tip_option_replay as T

ET = ZoneInfo("America/New_York")


def _ms(h, m, day=dt.date(2026, 10, 7)):
    return int(dt.datetime.combine(day, dt.time(h, m), ET).timestamp() * 1000)


def _bar(ts, o, h, l, c):
    return {"ts": ts, "o": o, "h": h, "l": l, "c": c, "px": c, "v": 10}


def test_contract_symbol_and_sessions():
    assert T.alpaca_symbol("AMD", dt.date(2026, 10, 14), "C", 610) == "AMD261014C00610000"
    assert T.alpaca_symbol("BRK.B", dt.date(2026, 10, 16), "P", 742.5) == "BRKB261016P00742500"
    assert T.add_sessions(dt.date(2026, 10, 9), 1) == dt.date(2026, 10, 12)      # Friday -> Monday
    assert T.add_sessions(dt.date(2026, 10, 9), 0) == dt.date(2026, 10, 9)


def test_entry_is_the_first_minute_that_starts_after_the_tip():
    tip = _ms(10, 0) + 20_000
    bars = [_bar(_ms(10, 0), 1, 1, 1, 1), _bar(_ms(10, 1), 2, 2, 2, 2)]
    assert T.pick_entry(bars, tip)["c"] == 2                      # the 10:00 bar holds prints from BEFORE the tip
    assert T.pick_entry([_bar(_ms(10, 45), 2, 2, 2, 2)], tip) is None            # nothing within 30 minutes
    evening = _ms(18, 0)
    nxt = _ms(9, 31, dt.date(2026, 10, 8))
    assert T.pick_entry([_bar(nxt, 3, 3, 3, 3)], evening)["c"] == 3              # an after-hours tip buys the next open
    assert T.pick_entry([_bar(_ms(11, 0, dt.date(2026, 10, 8)), 3, 3, 3, 3)], evening) is None


def test_exit_rules_read_a_shared_minute_stop_first_and_fill_gaps_at_the_open():
    entry = _bar(_ms(10, 1), 2.0, 2.0, 2.0, 2.0)
    both = [_bar(_ms(10, 2), 2.0, 4.5, 0.9, 3.0)]
    assert T.run_variant(entry, both, stop_pct=50, target_pct=100, same_day=False, settle=None) == (1.0, "stop")
    gap = [_bar(_ms(10, 2), 0.6, 0.7, 0.5, 0.6)]
    assert T.run_variant(entry, gap, stop_pct=50, target_pct=100, same_day=False, settle=None) == (0.6, "stop")
    win = [_bar(_ms(10, 2), 2.1, 2.7, 2.0, 2.6)]
    assert T.run_variant(entry, win, stop_pct=30, target_pct=30, same_day=True, settle=None) == (2.6, "target")
    drift = [_bar(_ms(15, 59), 2.1, 2.2, 2.0, 2.2), _bar(_ms(9, 31, dt.date(2026, 10, 8)), 9, 9, 9, 9)]
    assert T.run_variant(entry, drift, stop_pct=30, target_pct=30, same_day=True, settle=None) == (2.2, "day_close")
    assert T.run_variant(entry, drift[:1], stop_pct=None, target_pct=None, same_day=False, settle=0.0) == (0.0, "expiry")
    assert T.run_variant(entry, drift[:1], stop_pct=None, target_pct=None, same_day=False, settle=None) == (2.2, "horizon")


def _rule(n, hit, mean, verdict="negative"):
    return {"n": n, "days": 20, "hitRate": hit, "meanPct": mean, "medianPct": mean, "ci90": [mean - 5, mean + 5],
            "verdict": verdict}


def _option_rep():
    grp = lambda s, b, h, **kw: {"tips": 100, "scored": 90, "scalp": _rule(90, 0.44, s, **kw),  # noqa: E731
                                 "bracket": _rule(90, 0.3, b, **kw), "hold": _rule(90, 0.26, h, **kw)}
    rows = [{"ok": True, "day": "2026-10-13", "verdict": "take",
             **{v: {"resolved": True, "netPct": x} for v, x in (("scalp", 10.0), ("bracket", -50.0), ("hold", 4.0))}},
            {"ok": True, "day": "2026-10-01", "verdict": "take",
             **{v: {"resolved": True, "netPct": -9.0} for v in R.RULES}},
            {"ok": False, "day": "2026-10-13", "verdict": "skip"}]
    return {"version": "v", "since": "2026-08-28", "optCost": 0.08, "minN": 20, "tips": 400, "scored": 228,
            "byAnalystVerdict": {"ALL": grp(-6.3, -13.9, -21.2), "take": grp(-7.0, -16.6, -39.3),
                                 "skip": grp(-7.6, -13.3, -7.6)},
            "bySource": {"ALL": grp(-6.3, -13.9, -21.2), "room": grp(-6.0, -16.8, -32.6),
                         "thin": {"tips": 3, "scored": 3, "scalp": _rule(3, 0.0, -30.0, verdict="not enough"),
                                  "bracket": _rule(3, 0.3, 7.0, verdict="not enough"),
                                  "hold": _rule(3, 0.0, -50.0, verdict="not enough")}},
            "rows": rows}


def _source_rep():
    return {"version": "s", "costPct": 0.3,
            "bySource": {"room": {"tips": 142, "armedUnfilled": 3,
                                  "immediate": {"n": 120, "hitRate": 0.64, "meanR": 0.88, "ci90": [-0.18, 1.93],
                                                "verdict": "no edge shown"},
                                  "armed": {"n": 40, "hitRate": 0.4, "meanR": -0.16, "ci90": None, "verdict": "not enough"}}}}


def test_snapshot_drops_the_rows_and_keeps_the_running_check():
    snap = R.compact(_option_rep(), _source_rep(), as_of="2026-10-12T22:00:00+00:00", supply_since="2026-10-13")
    assert "rows" not in snap and snap["scored"] == 228
    assert snap["options"]["byVerdict"]["take"]["hold"]["meanPct"] == -39.3
    assert snap["underlying"]["bySource"]["room"]["immediate"]["hitRate"] == 0.64
    # only the tip from the supply date on is in the running check
    assert snap["sinceSupply"] == {"take": {"scalp": {"n": 1, "meanPct": 10.0, "hitRate": 1.0},
                                            "bracket": {"n": 1, "meanPct": -50.0, "hitRate": 0.0},
                                            "hold": {"n": 1, "meanPct": 4.0, "hitRate": 1.0}}}


def test_header_block_states_rates_not_stories():
    snap = R.compact(_option_rep(), _source_rep(), as_of="2026-10-12T22:00:00+00:00", supply_since=None)
    txt = R.block(snap, "room")
    assert txt.startswith("MEASURED RECORD") and txt.endswith("\n")
    assert "every source, option tips: scalp 44% winners, mean -6.3% (n=90)" in txt
    assert "NEGATIVE under every rule" in txt
    assert "THIS source's option tips: scalp 44% winners, mean -6.0%" in txt
    assert "right 64% of 120, mean +0.88% versus the market" in txt and "no edge shown" in txt
    assert "Your takes beat your skips under 1 of 3 rules - so far your take carries no information." in txt
    assert "a premium under $0.80" in txt and 'open your rationale with it as "EDGE: ..."' in txt
    thin = R.block(snap, "thin")
    assert "fewer than 20 priced - it has no record of its own" in thin
    assert R.block(None, "room") == "" and R.block({"options": {"byVerdict": {}}}, "room") == ""


def test_a_record_that_is_not_losing_does_not_tell_the_analyst_to_refuse():
    rep = _option_rep()
    rep["byAnalystVerdict"]["ALL"]["scalp"] = _rule(90, 0.6, 4.0, verdict="promising")
    txt = R.block(R.compact(rep, None, as_of="2026-10-12", supply_since=None), "room")
    assert "base rate of a take is a LOSS" not in txt and "promising under scalp" in txt
