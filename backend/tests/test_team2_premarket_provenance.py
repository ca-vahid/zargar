"""2026-09-17 EOD review §5 / item 2: a derived pre-market extreme names the bar it came from and the hash of its inputs, and
the read-only audit reconciles a frozen value against the bank and the plan's own revision history without rewriting it.

The day's shape: SPY's plan froze PML 660.65 while the bank held 757.53, because an exchange CORRECTION of the 07:46
minute (760.21 flat -> 760.12/760.24/660.65/760.23, same volume) reached the private tape at 08:02:09 and the bank never
kept it. IWM's 04:00 minute was corrected twice, the second time to a 283.92 low the bank never held either.
"""
from __future__ import annotations

import datetime as dt

from zargar.domain import Bar
from zargar.marketstructure.aggregate import aggregate
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2.plan import build_skeleton, complete_plan, premarket_extrema
from zargar.tools.team2_pm_audit import reconcile, render

from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars


def ms(h, m):
    return int(dt.datetime(DAY.year, DAY.month, DAY.day, h, m, tzinfo=ET).timestamp() * 1000)


def test_premarket_extrema_carry_their_source_bars_and_an_input_hash():
    prev = prev_day_bars()
    today = path_1m(DAY, (4, 0), (10, 0), lambda i: 566.0 + 0.01 * i)
    # a corrupt low on one pre-market minute (the SPY 07:46 shape): the extreme names exactly that bar
    bad_ts = ms(7, 46)
    today = [Bar(b.symbol, b.tf, b.ts, b.open, b.high, 466.65 if b.ts == bad_ts else b.low, b.close, b.volume, source="exchange") for b in today]
    ext = premarket_extrema(today, DAY.isoformat())
    assert ext["pml"]["value"] == 466.65 and ext["pml"]["bar"]["ts"] == bad_ts and ext["pml"]["bar"]["source"] == "exchange"
    assert ext["pmh"]["bar"]["ts"] < ms(9, 30) and ext["inputs"]["bars"] == 330 and len(ext["inputs"]["hash"]) == 16
    assert ext["inputs"]["firstTs"] == ms(4, 0) and ext["inputs"]["sources"] == ["exchange"]
    # the same inputs give the same hash; a changed input changes it
    assert premarket_extrema(today, DAY.isoformat())["inputs"]["hash"] == ext["inputs"]["hash"]
    fixed = [Bar(b.symbol, b.tf, b.ts, b.open, b.high, b.low if b.ts != bad_ts else b.open - 0.05, b.close, b.volume, source=b.source) for b in today]
    assert premarket_extrema(fixed, DAY.isoformat())["inputs"]["hash"] != ext["inputs"]["hash"]
    # complete_plan records it on the plan, beside the values it already froze
    rules = make_rules()
    plan = build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules)
    done = complete_plan(plan, today)
    assert done["pml"] == 466.65 and done["pmExtrema"]["pml"]["bar"]["ts"] == bad_ts and done["pmExtrema"]["inputs"]["hash"] == ext["inputs"]["hash"]
    # no pre-market bars: the record says so instead of failing
    empty = premarket_extrema([], DAY.isoformat())
    assert empty["pmh"] is None and empty["pml"] is None and empty["inputs"]["bars"] == 0


def test_audit_reconciles_a_frozen_extreme_to_its_corrected_minute_without_rewriting_it():
    ts_0746 = ms(7, 46)
    plan = {"pmh": 764.0, "pml": 660.65}                              # a pre-v0.8.11 plan: no pmExtrema recorded
    bank = [{"ts": ms(7, 45), "open": 760.2, "high": 760.3, "low": 760.1, "close": 760.21, "volume": 900, "source": "exchange"},
            {"ts": ts_0746, "open": 760.21, "high": 760.21, "low": 760.21, "close": 760.21, "volume": 615, "source": "exchange"},
            {"ts": ms(7, 47), "open": 760.2, "high": 764.0, "low": 757.53, "close": 760.0, "volume": 900, "source": "exchange"}]
    revisions = [{"ts_": ts_0746, "before": [760.21, 760.21, 760.21, 760.21, 615], "after": [760.12, 760.2369, 660.65, 760.2285, 615],
                  "source": "exchange", "at": "08:02:09"}]
    rec = reconcile("SPY", plan, bank, revisions)
    assert rec["bank"]["pml"] == 757.53 and rec["bank"]["pmh"] == 764.0
    assert [d["side"] for d in rec["discrepancies"]] == ["pml"] and rec["discrepancies"][0]["points"] == -96.88
    minutes = rec["contributingMinutes"]["pml"]
    assert len(minutes) == 1 and minutes[0]["time"] == "07:46" and minutes[0]["evidence"][0]["how"] == "a revision introduced this value"
    assert minutes[0]["bankRow"]["low"] == 760.21 and minutes[0]["bankKeptTheCorrection"] is False
    assert rec["frozen"] == {"pmh": 764.0, "pml": 660.65}            # the decision's inputs are reported, never changed
    text = render("2026-09-17", [rec])
    assert "DISCREPANCY PML: frozen 660.65 vs bank 757.53" in text and "bank kept the correction: False" in text
    # a plan that recorded its source bar (v0.8.11+) names it directly and reconciles when the bank agrees
    plan2 = {"pmh": 764.0, "pml": 757.53, "pmExtrema": {"pml": {"value": 757.53, "bar": {"ts": ms(7, 47), "low": 757.53, "source": "exchange"}},
                                                        "pmh": {"value": 764.0, "bar": {"ts": ms(7, 47), "high": 764.0, "source": "exchange"}},
                                                        "inputs": {"bars": 3, "hash": "abcd", "sources": ["exchange"]}}}
    rec2 = reconcile("SPY", plan2, bank, [])
    assert rec2["discrepancies"] == [] and rec2["contributingMinutes"]["pml"][0]["evidence"][0]["how"] == "recorded source bar"
    assert "reconciled: frozen == bank" in render("2026-09-17", [rec2])
