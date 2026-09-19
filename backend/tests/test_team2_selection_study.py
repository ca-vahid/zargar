"""Acceptance tests for the S1 selection-study collector (registration `s1-r3`): default off, order-free, PASSIVE.
R1 strict study-owned quote evidence at both ends; R2 lifecycle and capacity on UNIQUE opportunities, closes bound to the
immutable opening; R3 point-in-time features captured at the signal; R4 isolation proven through the ACTUAL runner with the
collector on and off. Synthetic inputs only: no network, no provider, no database rows, no real orders."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import ET
from zargar.settings_service import DEFAULTS
from zargar.techniques.team2 import diagnostics as diag
from zargar.techniques.team2 import selection_study as ss
from zargar.techniques.team2.rules import EXPERIMENT_ROLES

from . import test_team2_diagnostics as td
from .test_codex_team2_data_eod import rig

DAY = "2026-09-14"
MIN = 60_000
OID_SETUP = "scenario_4@09:45"


def ms(h, m, s=0):
    return int(dt.datetime(2026, 9, 14, h, m, s, tzinfo=ET).timestamp() * 1000)


def b1(h, m, o, hi, lo, c):
    return Bar(symbol="SPY", tf="1m", ts=ms(h, m), open=o, high=hi, low=lo, close=c, volume=100, source="exchange")


def tape(until_h=10, until_m=30):
    """09:30.. a steady 0.30/bar decline for 12 minutes (the impulse), then a tight drift (the flag)."""
    out, px = [], 100.0
    t = dt.datetime(2026, 9, 14, 9, 30, tzinfo=ET)
    end = dt.datetime(2026, 9, 14, until_h, until_m, tzinfo=ET)
    i = 0
    while t < end:
        step = -0.30 if i < 12 else (0.02 if i % 2 else -0.02)
        o, c = px, px + step
        out.append(b1(t.hour, t.minute, o, max(o, c) + 0.01, min(o, c) - 0.01, c))
        px, t, i = c, t + dt.timedelta(minutes=1), i + 1
    return out


def sel(quote_ts, *, ask=0.60, bid=0.58, known=True, why=None, source="opra", collected=None):
    return {"symbol": "SPY260914P00099000", "ask": ask, "bid": bid, "quoteTs": quote_ts, "receivedTs": quote_ts + 40,
            "collectedTs": (quote_ts + 60 if collected is None else collected), "source": source, "priceKnown": known,
            "priceUnknownReason": why, "selected": True}


ACT = {"price": 96.4, "source": "last", "ts": 1}


def feats(T, **kw):
    a = dict(signal_ts=T, direction="short", setup_id=OID_SETUP, confirmation_close_ts=ms(9, 45), atr=0.20,
             bars_1m=tape(), target=95.0, actionable=ACT)
    a.update(kw)
    return ss.features(**a)


def rec(T, q0, book_role="control", pid="p-control", pending=0, **kw):
    return ss.open_record(date=DAY, symbol="SPY", setup_id=OID_SETUP, signal_ts=T, book={"portfolioId": pid, "role": book_role},
                          trigger=kw.pop("trigger", OID_SETUP + "#1"), direction="short", feats=feats(T), selected=kw.pop("selected", sel(q0)),
                          shadow=False, refusal=None, recorded_ts=q0 + 100, followed_now=pending, **kw)


def quote(ts, bid=0.80, ask=0.82, priced="opra"):
    return {"bid": bid, "ask": ask, "priced": priced, "source": priced, "quoteTs": ts, "receivedTs": ts + 30}


def collect(monkeypatch, runner):
    runner.engine.settings = {**(runner.engine.settings or {}), "techniques.team2.selection_study": "collect"}


# ================================================================== default off
def test_the_collector_ships_off_and_is_not_an_experiment_override():
    assert DEFAULTS["techniques.team2.selection_study"] == "off"
    assert set(EXPERIMENT_ROLES) == {"sizing", "c1"} and "selection_study" not in EXPERIMENT_ROLES.values()


# ================================================================== R1 quote evidence, both ends
@pytest.mark.parametrize("q, col, word", [
    (None, 10_000_000, "no quote"),
    ({"bid": None, "ask": .6, "source": "opra", "quoteTs": 9_999_000}, 10_000_000, "bid"),
    ({"bid": 0.0, "ask": .6, "source": "opra", "quoteTs": 9_999_000}, 10_000_000, "bid"),
    ({"bid": .5, "ask": 0, "source": "opra", "quoteTs": 9_999_000}, 10_000_000, "ask"),
    ({"bid": .5, "ask": float("nan"), "source": "opra", "quoteTs": 9_999_000}, 10_000_000, "ask"),
    ({"bid": float("inf"), "ask": .6, "source": "opra", "quoteTs": 9_999_000}, 10_000_000, "bid"),
    ({"bid": .7, "ask": .6, "source": "opra", "quoteTs": 9_999_000}, 10_000_000, "crossed"),
    ({"bid": .5, "ask": .6, "source": None, "quoteTs": 9_999_000}, 10_000_000, "OPRA"),
    ({"bid": .5, "ask": .6, "source": "", "quoteTs": 9_999_000}, 10_000_000, "OPRA"),
    ({"bid": .5, "ask": .6, "source": "chain", "quoteTs": 9_999_000}, 10_000_000, "OPRA"),
    ({"bid": .5, "ask": .6, "source": "derived:opra", "quoteTs": 9_999_000}, 10_000_000, "OPRA"),
    ({"bid": .5, "ask": .6, "source": "opra", "quoteTs": None}, 10_000_000, "source timestamp"),
    ({"bid": .5, "ask": .6, "source": "opra", "quoteTs": 0}, 10_000_000, "source timestamp"),
    ({"bid": .5, "ask": .6, "source": "opra", "quoteTs": 9_999_000}, None, "collection"),
    ({"bid": .5, "ask": .6, "source": "opra", "quoteTs": 10_000_001}, 10_000_000, "future"),
    ({"bid": .5, "ask": .6, "source": "opra", "quoteTs": 10_000_000 - ss.MAX_QUOTE_AGE_MS - 1}, 10_000_000, "stale"),
])
def test_study_quote_evidence_refuses_every_weak_quote(q, col, word):
    clean, why = ss.quote_evidence(q, col)
    assert clean is None and word in why


def test_study_quote_evidence_accepts_the_valid_controls():
    assert ss.quote_evidence({"bid": .5, "ask": .6, "source": "opra", "quoteTs": 10_000_000}, 10_000_000)[0] == {"bid": .5, "ask": .6, "quoteTs": 10_000_000, "ageMs": 0}
    assert ss.quote_evidence({"bid": .5, "ask": .5, "source": "opra", "quoteTs": 10_000_000 - ss.MAX_QUOTE_AGE_MS}, 10_000_000)[0] is not None


def test_entry_is_revalidated_from_the_bound_fields_never_from_the_diagnostics_flag():
    T = ms(10, 12)
    assert rec(T, T + 1000)["entryQuote"]["valid"]
    for bad, word in ((sel(T + 1000, bid=None), "bid"), (sel(T + 1000, bid=0.7, ask=0.6), "crossed"), (sel(T + 1000, source="chain"), "OPRA"),
                      (sel(T + 1000, source=None), "OPRA"), (sel(T + 1000, collected=T + 999), "future"),
                      (sel(T + 1000, collected=T + 1000 + ss.MAX_QUOTE_AGE_MS + 1), "stale")):
        assert bad["priceKnown"] is True                                      # the legacy flag says yes ...
        r = rec(T, T + 1000, selected=bad)
        assert not r["entryQuote"]["valid"] and word in r["entryQuote"]["reason"] and r["schedule"] == [] and r["status"] == "closed"
    # through the REAL producer: the diagnostics accept an ask-only row, the study does not
    raw = {"symbol": "TEST", "strike": 100, "bid": None, "ask": .6, "eligible": True, "source": "opra", "quoteTs": T + 1000, "collectedTs": T + 1100}
    row = diag.candidate_rows([raw], {}, "TEST", floor=.2, band_hi=.9, spot=100, quote_ts=T + 1100)[0]
    assert row["priceKnown"] and not rec(T, T + 1000, selected=row)["entryQuote"]["valid"]


def test_follow_up_validity_on_the_quotes_own_clock_with_no_future_tolerance():
    T, q0 = ms(10, 12), ms(10, 12, 3)
    due = q0 + 30 * MIN
    assert ss.observe(rec(T, q0), 30, due + 900, quote(due + 400))["valid"]                           # control
    assert ss.observe(rec(T, q0), 30, due + 400, quote(due + 400))["valid"]                           # control: same instant
    for taken, q, word in ((due + 1000, quote(due + 3000), "future"), (due + 1000, quote(due + 1001), "future"),
                           (due + 100, quote(due - 1), "predates"), (due + ss.MAX_LATE_MS + 5000, quote(due + ss.MAX_LATE_MS + 1), "late"),
                           (due + 60_000, quote(due + 100), "stale"), (due + 500, quote(due + 200, priced="chain"), "OPRA"),
                           (due + 500, quote(due + 200, priced=None), "OPRA"), (due + 500, quote(due + 200, bid=0.0), "bid"),
                           (due + 500, quote(due + 200, bid=0.9, ask=0.8), "crossed"), (due + 500, None, "no quote")):
        o = ss.observe(rec(T, q0), 30, taken, q)
        assert not o["valid"] and word in o["reason"], (word, o["reason"])


def test_the_runner_never_synthesises_provenance_for_a_follow_up_quote():
    runner, ap = rig()
    ap.plan_for = DAY
    collect(None, runner)
    r = rec(ms(10, 12), ms(10, 12, 3))
    runner._study_of(ap.run_id)["records"][r["opportunityId"]] = r
    due = r["schedule"][0]["dueTs"]
    runner.engine.quotes = SimpleNamespace(get=lambda s: SimpleNamespace(bid=.8, ask=.82, ts=due + 100, source="", source_ts=due + 50))
    runner._study_tick(due + 100)
    assert "10" not in r["observations"], "a quote without its own provenance is not evidence: keep waiting"
    runner._study_tick(due + ss.MAX_LATE_MS + 1)
    assert not r["observations"]["10"]["valid"] and "OPRA" in r["observations"]["10"]["reason"]


# ================================================================== identity
def test_identity_ignores_per_book_contact_numbers():
    """2026-09-18: C1's touch #1 was 10:14, Control's touch #1 was 10:22 (C1 called that bar contact #3)."""
    assert ss.opportunity_id(DAY, "spy", OID_SETUP, ms(10, 14)) != ss.opportunity_id(DAY, "SPY", OID_SETUP, ms(10, 22))
    a = rec(ms(10, 22), ms(10, 22, 3), "control", "p-control", trigger=OID_SETUP + "#1")
    b = rec(ms(10, 22), ms(10, 22, 4), "c1", "p-c1", trigger=OID_SETUP + "#3", duplicate_of={"runId": "x", "portfolioId": "p-control"})
    assert a["opportunityId"] == b["opportunityId"] and b["schedule"] == [] and b["status"] == "closed"
    only_c1 = rec(ms(10, 14), ms(10, 14, 2), "c1", "p-c1")
    rows = {r["opportunityId"]: r for r in ss.collapse([a, b, only_c1], [])}
    assert len(rows) == 2 and rows[a["opportunityId"]]["books"] == ["c1", "control"] and rows[a["opportunityId"]]["openings"] == 2
    assert rows[only_c1["opportunityId"]]["c1Only"] is True and rows[a["opportunityId"]]["c1Only"] is False


# ================================================================== R3 point-in-time features
def test_features_read_nothing_at_or_after_the_contact_bar():
    T = ms(10, 12)
    base = feats(T, bars_1m=tape(10, 12))
    assert base == feats(T, bars_1m=tape(10, 30))
    tampered = tape(10, 12)
    tampered[-1], tampered[-2] = b1(10, 11, 50, 500, 1, 50), b1(10, 10, 50, 500, 1, 50)
    assert ss.features(signal_ts=T, direction="short", setup_id=OID_SETUP, confirmation_close_ts=ms(9, 45), atr=0.2,
                       bars_1m=tampered, target=95.0, actionable=ACT)["flag"] == base["flag"]


def test_feature_values_and_unknowns():
    T = ms(9, 52)
    f = feats(T, bars_1m=tape(9, 52), atr=0.30)
    assert f["flag"]["value"] == "flag" and f["first15"]["value"] == "first15" and f["wait"]["value"] == "short"
    assert f["scenario4"]["value"] == "scenario_4" and f["levelOrigin"]["value"] == "prior" and f["room"]["value"] == "far"
    assert f["room"]["inputs"]["priceSource"] == "last"
    g = feats(ms(11, 0), setup_id="pm_break_down@10:30", target=None, atr=None, bars_1m=tape(11, 0))
    assert g["levelOrigin"]["value"] == "pm" and g["scenario4"]["value"] == "other" and g["wait"]["value"] == "long"
    assert g["flag"]["value"] == ss.UNKNOWN and g["room"]["value"] == ss.UNKNOWN and g["first15"]["value"] == "later"
    assert feats(ms(9, 36), bars_1m=tape(9, 36))["flag"]["value"] == ss.UNKNOWN
    assert feats(T, confirmation_close_ts=None)["wait"]["value"] == ss.UNKNOWN
    assert feats(T, target=96.0)["room"]["value"] == "mid" and feats(T, target=96.3)["room"]["value"] == "near"
    none = feats(T, actionable={"price": None, "why": "no fresh price evidence"})
    assert none["room"]["value"] == ss.UNKNOWN and "actionable" in none["room"]["inputs"]["reason"]


def _under(last, last_ts, bid, ask, quote_ts):
    return SimpleNamespace(last=last, last_ts=last_ts, bid=bid, ask=ask, quote_ts=quote_ts, source_ts=0, ts=quote_ts)


def test_the_room_price_is_bound_to_its_own_field_time_or_is_unknown(monkeypatch):
    runner, ap = rig()
    now = ms(10, 12, 5)
    q = {"v": _under(96.0, now - 10 * MIN, 96.39, 96.41, now - 2000)}              # STALE last, FRESH midpoint
    runner.engine.quotes = SimpleNamespace(get=lambda s: q["v"])
    before = runner.__dict__.get("_last_actionable")
    a = runner._study_actionable(ap, now)
    assert a == {"price": 96.4, "source": "mid", "ts": now - 2000}
    q["v"] = _under(96.2, now - 1000, 96.39, 96.41, now - 2000)
    assert runner._study_actionable(ap, now)["source"] == "last"
    q["v"] = _under(96.2, 0, 96.39, 96.41, 0)                                      # no source evidence at all
    assert runner._study_actionable(ap, now)["price"] is None
    q["v"] = _under(96.2, now + 5000, 0, 0, 0)                                     # future-dated print
    assert runner._study_actionable(ap, now)["price"] is None
    assert runner.__dict__.get("_last_actionable") is before, "the collector never writes the runner's decision evidence"


def test_features_are_frozen_at_the_signal_and_survive_a_correction_during_the_awaited_pick(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner, ap = rig()
    ap.plan_for = DAY
    collect(None, runner)
    T = ms(9, 52)
    monkeypatch.setattr(module.time, "time", lambda: (T + 1500) / 1000)
    runner._bars[ap.run_id] = tape(9, 52)
    runner.engine.quotes = SimpleNamespace(get=lambda s: _under(96.4, T + 1000, 96.39, 96.41, T + 1000))
    emitted = []
    runner._study_emit = lambda run_id, r, kind: emitted.append((kind, json.loads(json.dumps(r, default=str))))
    tid = OID_SETUP + "#1"
    loc = {"signalTs": T, "direction": "short", "confirmationCloseTs": ms(9, 45), "atr": 0.30}
    runner._study_snapshot(ap, tid, loc, OID_SETUP, 95.0)                           # AT THE SIGNAL
    snap = json.loads(json.dumps(runner._diag_attempt(ap, tid)["study"]))
    assert snap["features"]["flag"]["value"] == "flag" and snap["features"]["room"]["inputs"]["priceSource"] == "last"
    # ... the awaited contract walk happens; meanwhile an exchange correction rewrites an EARLIER bar and the quote moves
    runner._bars[ap.run_id][12] = b1(9, 42, 96.4, 99.9, 90.0, 96.4)
    runner.engine.quotes = SimpleNamespace(get=lambda s: _under(80.0, T + 40_000, 0, 0, 0))
    runner._study_snapshot(ap, tid, loc, OID_SETUP, 95.0)                           # a second capture never replaces the first
    runner._diag_attempt(ap, tid)["entryLocation"] = loc
    runner._study_open(ap, tid, runner._diag_attempt(ap, tid), [sel(T + 3000)], shadow=False, refusal=None, now=T + 3100)
    opened = emitted[0][1]
    assert opened["features"] == snap["features"] and opened["inputs"]["barsHash"] == snap["barsHash"]
    late = ss.snapshot(signal_ts=T, direction="short", setup_id=OID_SETUP, confirmation_close_ts=ms(9, 45), atr=0.30,
                       bars_1m=runner._bars[ap.run_id], target=95.0, actionable=ACT, captured_ts=T + 9000)
    assert late["barsHash"] != snap["barsHash"], "the corrected tape really is different: only the frozen capture is point-in-time"
    # without a capture at the signal the features are UNKNOWN, never computed late
    runner._diag_attempt(ap, OID_SETUP + "#2")["entryLocation"] = {**loc, "signalTs": ms(10, 20)}
    runner._study_open(ap, OID_SETUP + "#2", runner._diag_attempt(ap, OID_SETUP + "#2"), [sel(ms(10, 20, 2))], shadow=False, refusal=None, now=ms(10, 20, 3))
    assert {v["value"] for v in emitted[-1][1]["features"].values()} == {ss.UNKNOWN}


# ================================================================== timing
def test_the_entry_quote_delay_is_measured_from_the_signal_and_bounded():
    T = ms(10, 12)
    ok = rec(T, T + 3000)
    assert ok["entryQuote"]["valid"] and ok["entryQuote"]["delayMs"] == 3000 and len(ok["openHash"]) == 16
    assert [s["dueTs"] for s in ok["schedule"]] == [T + 3000 + 10 * MIN, T + 3000 + 30 * MIN]
    for r, word in ((rec(T, T - 1), "predates"), (rec(T, T + ss.MAX_ENTRY_DELAY_MS + 1), "after the signal"), (rec(T, T + 1000, selected=None), "no contract")):
        assert not r["entryQuote"]["valid"] and word in r["entryQuote"]["reason"] and r["schedule"] == [] and r["status"] == "closed"
        assert ss.outcome(r, 1.04)["primaryReason"].startswith("entry:")


def test_late_in_the_day_and_capacity_are_recorded_not_dropped():
    r = rec(ms(15, 20), ms(15, 20, 2))
    assert r["observations"]["30"]["reason"].startswith("late") and [s["status"] for s in r["schedule"]] == ["pending", "done"]
    full = rec(ms(10, 12), ms(10, 12, 2), pending=ss.MAX_FOLLOWED)
    assert full["status"] == "closed" and all(o["reason"] == "capacity" for o in full["observations"].values())


def test_winsorised_primary_and_cost_arithmetic():
    assert ss.after_cost_return(0.50, 0.50, 1.04) == pytest.approx(-0.0208 / 0.5104 * 100)
    r = rec(ms(10, 12), ms(10, 12, 3))
    ss.observe(r, 10, r["schedule"][0]["dueTs"] + 300, quote(r["schedule"][0]["dueTs"] + 100))
    ss.observe(r, 30, r["schedule"][1]["dueTs"] + 300, quote(r["schedule"][1]["dueTs"] + 100, bid=5.0, ask=5.1))
    o = ss.outcome(r, 1.04)
    assert o["primary"] == ss.WINSOR_PCT and o["primaryRaw"] > 600 and "10" in o["secondary"]


# ================================================================== R2 lifecycle, capacity, immutable opening
def _study_runner(n_plans=1):
    runner, ap = rig()
    ap.plan_for = DAY
    collect(None, runner)
    emitted = []
    runner._study_emit = lambda run_id, r, kind: emitted.append((kind, run_id, json.loads(json.dumps(r, default=str))))
    plans = [ap]
    for i in range(1, n_plans):
        other = type(ap)(run_id=f"book-{i}", symbol="SPY", plan_for=DAY, plan={"experiment": {"role": ("sizing", "c1")[i - 1], "label": "x"}},
                         config=type(ap.config)(portfolio_id=f"p-{i}", mode="auto", instrument="options", use_critic=False), trackers={}, armed_at=0)
        runner._armed[other.run_id] = other
        plans.append(other)
    return runner, plans, emitted


def _open(runner, ap, T, q0, tid=OID_SETUP + "#1"):
    att = runner._diag_attempt(ap, tid)
    att["entryLocation"] = {"signalTs": T, "direction": "short", "confirmationCloseTs": ms(9, 45), "atr": 0.2}
    att["setup"] = OID_SETUP
    runner._study_open(ap, tid, att, [sel(q0)], shadow=False, refusal=None, now=q0 + 100)


def test_three_books_on_one_opportunity_use_one_slot_and_one_observation():
    runner, plans, emitted = _study_runner(3)
    T = ms(10, 22)
    for i, ap in enumerate(plans):
        _open(runner, ap, T, T + 2000 + i, tid=OID_SETUP + f"#{i + 1}")             # each book numbers the contact differently
    assert runner._study_pending() == 1, "the capacity unit is the UNIQUE opportunity, not the per-book record"
    opens = [r for k, _, r in emitted if k == "selection_study_open"]
    assert len(opens) == 3 and [bool(r["duplicateOf"]) for r in opens] == [False, True, True]
    assert opens[1]["duplicateOf"]["openHash"] == opens[0]["openHash"] and all(r["schedule"] == [] for r in opens[1:])
    rows = ss.collapse(opens, [])
    assert len(rows) == 1 and rows[0]["books"] == ["c1", "control", "sizing"] and rows[0]["book"]["role"] == "control"


def test_twelve_unique_opportunities_fill_capacity_and_the_thirteenth_is_recorded_as_capacity():
    runner, plans, emitted = _study_runner(1)
    for i in range(ss.MAX_FOLLOWED + 1):
        T = ms(10, 0) + 2 * MIN * i
        _open(runner, plans[0], T, T + 2000, tid=OID_SETUP + f"#{i}")
    assert runner._study_pending() == ss.MAX_FOLLOWED
    last = [r for k, _, r in emitted if k == "selection_study_close"][-1]
    assert all(o["reason"] == "capacity" for o in last["observations"].values())


@pytest.mark.parametrize("when, why", [("before10", "plan removed"), ("between", "plan removed")])
def test_a_removed_plan_is_closed_frees_its_slot_and_stays_in_the_denominator(when, why):
    runner, plans, emitted = _study_runner(1)
    T = ms(10, 12)
    _open(runner, plans[0], T, T + 2000)
    oid = ss.opportunity_id(DAY, "SPY", OID_SETUP, T)
    r = runner._study_of(plans[0].run_id)["records"][oid]
    if when == "between":
        due = r["schedule"][0]["dueTs"]
        runner.engine.quotes = SimpleNamespace(get=lambda s: SimpleNamespace(bid=.8, ask=.82, ts=due + 100, source="opra", source_ts=due + 50))
        runner._study_tick(due + 100)
        assert r["observations"]["10"]["valid"]
    runner._armed.pop(plans[0].run_id)                                              # disarmed / removed
    runner._study_tick(ms(10, 30))
    assert runner._study_pending() == 0 and plans[0].run_id not in runner.__dict__["_study"]
    closes = [x for k, _, x in emitted if k == "selection_study_close"]
    assert len(closes) == 1 and why in closes[0]["observations"]["30"]["reason"] and closes[0]["openHash"] == r["openHash"]
    rows = ss.collapse([x for k, _, x in emitted if k == "selection_study_open"], closes)
    cov = ss.coverage(rows, "scenario4", 1.04)[ss.UNKNOWN]                        # no capture at the signal in this rig: features unknown
    assert cov["opportunities"] == 1 and cov["valid"] == 0 and cov["reasons"] == {"plan removed before the observation": 1}


def test_end_of_session_switch_off_and_a_later_session_all_release_capacity():
    runner, plans, emitted = _study_runner(1)
    ap = plans[0]
    _open(runner, ap, ms(15, 0), ms(15, 0, 2))
    assert runner._study_pending() == 1
    runner._study_tick(ss.flatten_ms(DAY) + ss.MAX_LATE_MS + 1)                      # end of session
    assert runner._study_pending() == 0
    _open(runner, ap, ms(10, 12), ms(10, 12, 2), tid=OID_SETUP + "#2")
    runner.engine.settings = {"techniques.team2.selection_study": "off"}             # switched off mid-flight
    runner._study_tick(ms(10, 13))
    assert runner._study_pending() == 0
    reasons = [x["observations"]["30"]["reason"] for k, _, x in emitted if k == "selection_study_close"]
    assert "session ended" in reasons[0] and "switched off" in reasons[1]
    n = len(emitted)
    _open(runner, ap, ms(10, 40), ms(10, 40, 2), tid=OID_SETUP + "#3")               # off: nothing recorded
    assert len(emitted) == n
    collect(None, runner)                                                            # re-enabled, and a LATER session after abandoned ones
    ap.plan_for = "2026-09-15"
    T2 = int(dt.datetime(2026, 9, 15, 10, 12, tzinfo=ET).timestamp() * 1000)
    _open(runner, ap, T2, T2 + 2000, tid=OID_SETUP + "#1")
    assert runner._study_pending() == 1 and emitted[-1][2]["date"] == "2026-09-15" and emitted[-1][2]["schedule"]


def test_a_revision_never_reopens_and_a_close_is_journaled_once():
    runner, plans, emitted = _study_runner(1)
    T = ms(10, 12)
    _open(runner, plans[0], T, T + 2000)
    _open(runner, plans[0], T, T + 9000)                                            # a revision while pending
    runner._armed.pop(plans[0].run_id)
    runner._study_tick(ms(10, 20))
    runner._armed[plans[0].run_id] = plans[0]
    _open(runner, plans[0], T, T + 12_000)                                          # a revision after the close
    runner._study_tick(ms(10, 21))
    kinds = [k for k, _, _ in emitted]
    assert kinds == ["selection_study_open", "selection_study_close"]


def test_a_close_is_bound_to_the_immutable_opening_and_later_or_foreign_closes_are_ignored():
    a = rec(ms(10, 22), ms(10, 22, 3), "control", "p-control")
    first = json.loads(json.dumps(a))
    ss.observe(a, 10, a["schedule"][0]["dueTs"] + 300, quote(a["schedule"][0]["dueTs"] + 100))
    ss.observe(a, 30, a["schedule"][1]["dueTs"] + 300, quote(a["schedule"][1]["dueTs"] + 100, bid=0.90, ask=0.92))
    good = json.loads(json.dumps(a))
    stale_dup = json.loads(json.dumps(first))
    ss.abandon(stale_dup, "restart", ms(11, 0))                                     # a SECOND close from stale persisted state
    foreign = {**json.loads(json.dumps(good)), "openHash": "deadbeefdeadbeef", "features": ss.unknown_features("tampered"),
               "entryQuote": {**good["entryQuote"], "ask": 9.99}}
    rows = ss.collapse([first], [good, stale_dup, foreign])
    assert len(rows) == 1 and rows[0]["ignoredCloses"] == 2 and rows[0]["complete"]
    assert rows[0]["entryQuote"]["ask"] == 0.60 and rows[0]["features"] == first["features"], "entry and features come from the OPENING"
    assert ss.outcome(rows[0], 1.04)["primary"] == pytest.approx(ss.after_cost_return(0.60, 0.90, 1.04))
    assert ss.collapse([first], [foreign])[0]["status"] == "incomplete", "a close that does not carry the opening's hash is not its close"


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))


async def test_restore_through_the_real_persistence_hooks_reconciles_journaled_closes(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner, plans, emitted = _study_runner(1)
    ap = plans[0]
    T = ms(10, 12)
    _open(runner, ap, T, T + 2000)
    _open(runner, ap, ms(10, 20), ms(10, 20, 2), tid=OID_SETUP + "#2")
    state = json.loads(json.dumps(runner.state_extras(ap)))                         # what the plan persists
    assert len(state["selectionStudy"]["records"]) == 2
    closed_oid = ss.opportunity_id(DAY, "SPY", OID_SETUP, T)
    closed_hash = state["selectionStudy"]["records"][closed_oid]["openHash"]
    # the process journaled the FIRST record's close, then died before persisting it
    fresh, fap = rig()
    fap.plan_for = DAY
    collect(None, fresh)
    out = []
    fresh._study_emit = lambda run_id, r, kind: out.append((kind, r["opportunityId"]))
    fresh.restore_extras(fap, state)
    fresh._study_tick(ms(12, 0))
    assert out == [] and fresh._study_pending() == 2, "restored records wait for the journal reconciliation"
    journal_rows = [SimpleNamespace(payload={"kind": "selection_study_close", "opportunityId": closed_oid, "openHash": closed_hash}),
                    SimpleNamespace(payload={"kind": "selection_study_close", "opportunityId": "other", "openHash": "x"})]
    await fresh._study_reconcile(_FakeSession(journal_rows), fap)
    assert fresh._study_pending() == 1
    fresh._study_tick(ms(12, 0))
    assert [k for k, _ in out] == ["selection_study_close"] and out[0][1] != closed_oid, "no second close for the reconciled record"
    # and when the journal cannot be read the wait is BOUNDED, never a permanent slot
    stuck, sap = rig()
    sap.plan_for = DAY
    collect(None, stuck)
    stuck._study_emit = lambda *a: None
    stuck.restore_extras(sap, state)
    real = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: real + 61)
    stuck._study_tick(ms(12, 0))
    assert stuck._study_pending() == 0


def test_incomplete_observations_stay_in_the_coverage_denominator():
    done = rec(ms(10, 12), ms(10, 12, 3))
    opened_done = json.loads(json.dumps(done))
    ss.observe(done, 10, done["schedule"][0]["dueTs"] + 300, quote(done["schedule"][0]["dueTs"] + 100))
    ss.observe(done, 30, done["schedule"][1]["dueTs"] + 300, quote(done["schedule"][1]["dueTs"] + 100))
    crashed = rec(ms(10, 40), ms(10, 40, 2))                                        # opened, journaled, never closed
    rows = ss.collapse([opened_done, json.loads(json.dumps(crashed))], [done])
    assert sorted(r["status"] for r in rows) == ["closed", "incomplete"]
    cov = ss.coverage(rows, "scenario4", 1.04)["scenario_4"]
    assert cov["opportunities"] == 2 and cov["valid"] == 1 and cov["reasons"] == {"incomplete": 1} and cov["coveragePct"] == 50.0


# ================================================================== R4 isolation through the ACTUAL runner
async def _drive(monkeypatch, study_on: bool, quote_cache_fails: bool = False):
    """The real chain: read event -> `_fire_from_event` -> gates -> `pick_contract` (where the collector opens) -> sizing ->
    the real `OrderIntent` handed to the placement boundary; then 31 minutes of quote-watch ticks."""
    import time as _time
    clock = [ms(10, 0) + 1500]
    monkeypatch.setattr(_time, "time", lambda: clock[0] / 1000)
    opts = td.FakeOpts(td.chain(), {r["symbol"]: (0.55, 0.57) for r in td.chain()})
    refreshes = []

    async def refresh_now(sym):                                                     # the SHARED entry path may call this; the collector may not
        refreshes.append(sym)
        return opts.quote(sym)
    opts.refresh_now = refresh_now
    runner, ap = td.rig(opts)
    intents = []

    async def place(ap_, tr_, intent, **kw):
        intents.append({k: getattr(intent, k, None) for k in ("portfolio_id", "symbol", "sec_type", "side", "qty", "order_type", "limit_price", "tif")})
        return {"id": "ord-1", "status": "SUBMITTED"}
    runner._place_with_retry = place
    runner._entry_time_refusal = lambda *a, **k: None                                # the rig's wall clock is not the plan's session
    runner.engine.positions = SimpleNamespace(equity=AsyncMock(return_value=10_000.0), cash=AsyncMock(return_value=10_000.0), get=lambda *a, **k: None)
    runner.engine.settings = {"techniques.team2.selection_study": "collect" if study_on else "off"}
    res = td.read()
    await runner._fire_from_event(ap, res.events[0], runner._bars[ap.run_id][-1], res, halted=False, journal=True)
    await runner.wait_fires()                                                      # the whole fire chain, deterministically
    await td.drain(runner)
    await asyncio.sleep(0)
    provider_calls = list(opts.calls)
    if quote_cache_fails:
        real_get = runner.engine.quotes.get
        runner.engine.quotes = SimpleNamespace(get=lambda s: (_ for _ in ()).throw(RuntimeError("quote cache down")) if s != "SPY" else real_get(s))
    refreshes_at_entry = list(refreshes)
    base = clock[0]
    for k in range(0, 34):
        clock[0] = base + k * MIN
        runner._study_tick(clock[0])
    await td.drain(runner)
    trade = ap.trades["scenario_1@09:45#1"]
    rows = [(c.args[0], {k: v for k, v in c.args[1].items() if k not in ("recordedAt",)}) for c in runner.engine.journal.append.await_args_list]
    core = [r for r in rows if not str(r[1].get("kind", "")).startswith("selection_study")]
    studyrows = [r[1] for r in rows if str(r[1].get("kind", "")).startswith("selection_study")]
    state = runner.state_extras(ap)
    state.pop("selectionStudy", None)
    att = {k: v for k, v in runner._diag_of(ap.run_id)["attempts"]["scenario_1@09:45#1"].items() if k != "study"}
    snapshot = {"intents": intents, "tradeStatus": trade.status, "tradeReason": trade.reason, "qty": trade.qty, "limit": trade.limit_price,
                "orderSymbol": trade.order_symbol, "providerCallsAtEntry": provider_calls, "providerCallsAfterTicks": list(opts.calls),
                "refreshesAtEntry": refreshes_at_entry, "refreshesAfterTicks": list(refreshes),
                "journalKinds": [(t, p.get("kind") or p.get("event") or p.get("stage")) for t, p in core], "stateKeys": sorted(state)}
    return snapshot, studyrows, att, opts


def _stable(x):
    """drop wall-clock stamps so two runs a few milliseconds apart compare equal"""
    if isinstance(x, dict):
        return {k: _stable(v) for k, v in x.items() if not any(w in k.lower() for w in ("ts", "time", "recordedat", "agems", "elapsed"))}
    if isinstance(x, list):
        return [_stable(v) for v in x]
    return x


async def test_the_actual_runner_takes_identical_decisions_and_order_intents_with_the_collector_on_and_off(monkeypatch):
    off, off_rows, off_att, _ = await _drive(monkeypatch, False)
    on, on_rows, on_att, opts = await _drive(monkeypatch, True)
    assert off["intents"] and off["intents"][0]["symbol"].startswith("SPY260914C") and off["intents"][0]["qty"] >= 1, "the rig really reaches an order intent"
    assert _stable(on) == _stable(off), "decisions, order intents, provider calls, journal and persisted keys are identical"
    assert _stable(on_att) == _stable(off_att), "the diagnostics record is identical apart from the study capture"
    assert off_rows == [] and [r["kind"] for r in on_rows] == ["selection_study_open", "selection_study_close"]
    assert on["providerCallsAfterTicks"] == on["providerCallsAtEntry"] and on["refreshesAfterTicks"] == on["refreshesAtEntry"], \
        "33 minutes of collection made NO provider request and NO forced refresh"
    assert on_rows[0]["entryQuote"]["valid"] and on_rows[0]["features"]["scenario4"]["value"] == "other"
    assert all(o["valid"] for o in on_rows[1]["observations"].values()) and on_rows[1]["openHash"] == on_rows[0]["openHash"]


async def test_a_failing_quote_cache_is_recorded_and_never_raises_or_holds_a_slot(monkeypatch):
    on, rows, _, opts = await _drive(monkeypatch, True, quote_cache_fails=True)
    assert on["intents"], "trading went ahead"
    kinds = [r["kind"] for r in rows]
    assert kinds == ["selection_study_open", "selection_study_close"]
    close = rows[-1]
    assert all(not o["valid"] and "no valid quote inside the window" in o["reason"] for o in close["observations"].values())
    assert on["refreshesAfterTicks"] == on["refreshesAtEntry"]


def test_every_study_hook_is_synchronous_and_the_observation_path_awaits_nothing():
    import inspect
    from zargar.techniques.team2.runner import Team2Runner
    for name in ("_study_on", "_study_of", "_study_following", "_study_pending", "_study_close", "_study_actionable", "_study_snapshot",
                 "_study_open", "_study_tick"):
        assert not inspect.iscoroutinefunction(getattr(Team2Runner, name)), name
    body = inspect.getsource(Team2Runner._study_tick) + inspect.getsource(Team2Runner._study_open) + inspect.getsource(Team2Runner._study_snapshot)
    for word in ("await ", "create_task", "refresh_now", ".track(", "untrack", "reprice("):
        assert word not in body, word
