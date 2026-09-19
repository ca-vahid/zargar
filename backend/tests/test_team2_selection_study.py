"""Acceptance tests for the S1 selection-study collector (registration `s1-r2`): default off, order-free, book-independent
opportunity identity, causal features, exact timing, and observations recorded WHEN THEY BEGIN so nothing drops out of the
coverage denominator. Synthetic inputs only: no network, no provider, no orders."""
from __future__ import annotations

import datetime as dt
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import ET
from zargar.settings_service import DEFAULTS
from zargar.techniques.team2 import selection_study as ss
from zargar.techniques.team2.rules import EXPERIMENT_ROLES

from .test_codex_team2_data_eod import rig

DAY = "2026-09-14"
MIN = 60_000


def ms(h, m, s=0):
    return int(dt.datetime(2026, 9, 14, h, m, s, tzinfo=ET).timestamp() * 1000)


def b1(h, m, o, hi, lo, c):
    return Bar(symbol="SPY", tf="1m", ts=ms(h, m), open=o, high=hi, low=lo, close=c, volume=100, source="exchange")


def tape(until_h=10, until_m=30):
    """09:30.. a steady 0.30/bar decline for 12 minutes (the impulse), then a tight 8-minute drift (the flag), then noise."""
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


def sel(quote_ts, *, ask=0.60, bid=0.58, known=True, why=None):
    return {"symbol": "SPY260914P00099000", "ask": ask, "bid": bid, "quoteTs": quote_ts, "receivedTs": quote_ts + 40, "collectedTs": quote_ts + 60,
            "source": "opra", "priceKnown": known, "priceUnknownReason": why, "selected": True}


def feats(T, **kw):
    a = dict(signal_ts=T, direction="short", setup_id="scenario_4@09:45", confirmation_close_ts=ms(9, 45), atr=0.20,
             bars_1m=tape(), target=95.0, actionable_px=96.4)
    a.update(kw)
    return ss.features(**a)


def rec(T, q0, book_role="control", pid="p-control", pending=0, **kw):
    return ss.open_record(date=DAY, symbol="SPY", setup_id="scenario_4@09:45", signal_ts=T, book={"portfolioId": pid, "role": book_role},
                          trigger=kw.pop("trigger", "scenario_4@09:45#1"), direction="short", feats=feats(T), selected=kw.pop("selected", sel(q0)),
                          shadow=False, refusal=None, recorded_ts=q0 + 100, pending_now=pending, **kw)


def quote(ts, bid=0.80, ask=0.82, priced="opra"):
    return {"bid": bid, "ask": ask, "priced": priced, "quoteTs": ts, "receivedTs": ts + 30}


# ------------------------------------------------------------------ default off, order-free
def test_the_collector_ships_off_and_is_not_an_experiment_override():
    assert DEFAULTS["techniques.team2.selection_study"] == "off"
    assert "selection_study" not in EXPERIMENT_ROLES.values() and set(EXPERIMENT_ROLES) == {"sizing", "c1"}


def test_the_collector_has_no_path_to_an_order_a_position_or_a_decision():
    src = inspect.getsource(ss)
    for word in ("OrderIntent", "orders.", "place(", "portfolio_id=", "_refuse_entry", "entry_gate", "risk"):
        assert word not in src, word
    from zargar.techniques.team2 import runner as rn
    for name in ("_study_on", "_study_open", "_study_tick", "_study_observe", "_study_pending", "_study_of"):
        body = inspect.getsource(getattr(rn.Team2Runner, name))
        for word in ("orders", "place(", "_refuse", "trade.status", ".status =", "ap.trades[", "halt", "_persist"):
            assert word not in body.replace('row["status"] =', "").replace("rec[\"status\"] ==", ""), (name, word)


def test_off_records_nothing_and_on_never_mutates_its_inputs(monkeypatch):
    runner, ap = rig()
    ap.plan_for = DAY
    emitted = []
    runner._diag_emit = lambda ap_, kind, payload: emitted.append((kind, payload))
    runner._bars[ap.run_id] = tape()
    T = ms(10, 12)
    attempt = {"setup": "scenario_4@09:45", "entryLocation": {"signalTs": T, "direction": "short", "confirmationCloseTs": ms(9, 45), "atr": 0.2},
               "decisionTime": {"targets": [95.0]}}
    cands = [sel(T + 3000)]
    before = json.dumps([attempt, cands], sort_keys=True)
    runner._study_open(ap, "scenario_4@09:45#1", attempt, cands, 96.4, shadow=False, refusal=None, now=T + 3100)      # knob off
    assert emitted == [] and "_study" not in runner.__dict__
    monkeypatch.setattr(runner, "rt", lambda k, d=None: "collect" if k == "selection_study" else d)
    runner._study_open(ap, "scenario_4@09:45#1", attempt, cands, 96.4, shadow=False, refusal=None, now=T + 3100)
    assert json.dumps([attempt, cands], sort_keys=True) == before and ap.trades == {}
    assert [k for k, _ in emitted] == ["selection_study_open"], "the record is journaled WHEN OBSERVATION BEGINS"
    assert emitted[0][1]["status"] == "open" and emitted[0][1]["opportunityId"] == f"{DAY}|SPY|scenario_4@09:45|{T}"
    runner._study_open(ap, "scenario_4@09:45#1", attempt, cands, 96.4, shadow=False, refusal=None, now=T + 9000)      # a revision
    assert len(emitted) == 1, "a revision of the same opportunity does not open a second record"
    assert runner.state_extras(ap)["selectionStudy"]["records"], "pending observations are persisted with the plan"


# ------------------------------------------------------------------ amendment 1: book-independent identity
def test_identity_ignores_per_book_contact_numbers():
    """2026-09-18: C1's touch #1 was 10:14, Control's touch #1 was 10:22 (C1 called that bar contact #3)."""
    c1_first = ss.opportunity_id(DAY, "spy", "scenario_4@09:45", ms(10, 14))
    control_first = ss.opportunity_id(DAY, "SPY", "scenario_4@09:45", ms(10, 22))
    assert c1_first != control_first, "two different bars are two opportunities even though both books called them #1"
    a = rec(ms(10, 22), ms(10, 22, 3), "control", "p-control", trigger="scenario_4@09:45#1")
    b = rec(ms(10, 22), ms(10, 22, 4), "c1", "p-c1", trigger="scenario_4@09:45#3")
    assert a["opportunityId"] == b["opportunityId"], "the same bar is one opportunity whatever each book numbered it"
    only_c1 = rec(ms(10, 14), ms(10, 14, 2), "c1", "p-c1")
    rows = ss.collapse([b, only_c1, a], [])
    assert len(rows) == 2
    by = {r["opportunityId"]: r for r in rows}
    assert by[a["opportunityId"]]["book"]["role"] == "control" and by[a["opportunityId"]]["books"] == ["c1", "control"]
    assert by[only_c1["opportunityId"]]["c1Only"] is True and by[a["opportunityId"]]["c1Only"] is False


# ------------------------------------------------------------------ features: causal, exact, unknown-aware
def test_features_read_nothing_at_or_after_the_contact_bar():
    T = ms(10, 12)
    base = feats(T, bars_1m=tape(10, 12))
    later = feats(T, bars_1m=tape(10, 30))                                  # bars after T appended
    assert base == later
    tampered = [b for b in tape(10, 12)]
    tampered[-1] = b1(10, 11, 50, 500, 1, 50)                                  # the contact bar itself is wild
    tampered[-2] = b1(10, 10, 50, 500, 1, 50)
    assert ss.features(signal_ts=T, direction="short", setup_id="scenario_4@09:45", confirmation_close_ts=ms(9, 45), atr=0.2,
                       bars_1m=tampered, target=95.0, actionable_px=96.4)["flag"] == base["flag"]


def test_feature_values_and_unknowns():
    T = ms(9, 52)                                                             # 22 minutes in: 6 impulse + 4 flag 2m bars before the contact bar
    f = feats(T, bars_1m=tape(9, 52), atr=0.30)
    assert f["flag"]["value"] == "flag" and f["flag"]["inputs"]["impulseAtr"] >= 1.5 and f["flag"]["inputs"]["rangeAtr"] <= 1.25
    assert f["first15"]["value"] == "first15" and f["wait"]["value"] == "short" and f["scenario4"]["value"] == "scenario_4"
    assert f["levelOrigin"]["value"] == "prior" and f["room"]["value"] == "far"
    g = feats(ms(11, 0), setup_id="pm_break_down@10:30", confirmation_close_ts=ms(9, 45), target=None, atr=None, bars_1m=tape(11, 0))
    assert g["levelOrigin"]["value"] == "pm" and g["scenario4"]["value"] == "other" and g["wait"]["value"] == "long"
    assert g["flag"]["value"] == ss.UNKNOWN and g["room"]["value"] == ss.UNKNOWN and g["first15"]["value"] == "later"
    assert feats(ms(9, 36), bars_1m=tape(9, 36))["flag"]["value"] == ss.UNKNOWN          # too few closed session bars
    assert feats(T, confirmation_close_ts=None)["wait"]["value"] == ss.UNKNOWN
    assert feats(T, target=96.4 - 0.2 * 2.0)["room"]["value"] == "mid" and feats(T, target=96.3)["room"]["value"] == "near"


# ------------------------------------------------------------------ amendment 3: timing
def test_the_entry_quote_delay_is_measured_from_the_signal_and_bounded():
    T = ms(10, 12)
    ok = rec(T, T + 3000)
    assert ok["entryQuote"]["valid"] and ok["entryQuote"]["delayMs"] == 3000
    assert [s["dueTs"] for s in ok["schedule"]] == [T + 3000 + 10 * MIN, T + 3000 + 30 * MIN], "clocks start at the quote's SOURCE time"
    early = rec(T, T - 1)
    late = rec(T, T + ss.MAX_ENTRY_DELAY_MS + 1)
    bad = rec(T, T + 1000, selected=sel(T + 1000, known=False, why="stale source"))
    none = rec(T, T + 1000, selected=None)
    for r, word in ((early, "predates"), (late, "after the signal"), (bad, "not valid evidence"), (none, "no contract")):
        assert not r["entryQuote"]["valid"] and word in r["entryQuote"]["reason"] and r["schedule"] == [] and r["status"] == "closed"
        assert ss.outcome(r, 1.04)["primary"] is None and ss.outcome(r, 1.04)["primaryReason"].startswith("entry:")


def test_an_observation_counts_only_inside_its_window_on_the_quotes_own_clock():
    T, q0 = ms(10, 12), ms(10, 12, 3)
    due = q0 + 30 * MIN
    r = rec(T, q0)
    assert ss.observe(r, 10, q0 + 10 * MIN + 500, quote(q0 + 10 * MIN + 200))["valid"]
    assert not ss.observe(rec(T, q0), 30, due + 100, quote(due - 1))["valid"]                         # quote older than its due time
    lateq = ss.observe(rec(T, q0), 30, due + ss.MAX_LATE_MS + 5000, quote(due + ss.MAX_LATE_MS + 1))
    assert not lateq["valid"] and "late" in lateq["reason"]
    stale = ss.observe(rec(T, q0), 30, due + 60_000, quote(due + 100))                                # source time far from collection
    assert not stale["valid"]
    assert not ss.observe(rec(T, q0), 30, due + 500, quote(due + 200, priced="chain"))["valid"]       # not a live quote
    assert not ss.observe(rec(T, q0), 30, due + 500, quote(due + 200, bid=0.0))["valid"]
    good = ss.observe(r, 30, due + 900, quote(due + 400, bid=0.80))
    assert good["valid"] and good["lateMs"] == 400 and r["status"] == "closed"
    o = ss.outcome(r, 1.04)
    assert o["primary"] == pytest.approx((0.80 - 0.60 - 0.0208) / (0.60 + 0.0104) * 100) and "10" in o["secondary"]


def test_late_in_the_day_and_capacity_are_recorded_not_dropped():
    T = ms(15, 20)
    r = rec(T, T + 2000)
    assert r["observations"]["30"]["reason"].startswith("late") and r["observations"].get("10") is None
    assert [s["status"] for s in r["schedule"]] == ["pending", "done"]
    full = rec(ms(10, 12), ms(10, 12, 2), pending=ss.MAX_PENDING)
    assert full["status"] == "closed" and all(o["reason"] == "capacity" for o in full["observations"].values())


def test_winsorised_primary_and_cost_arithmetic():
    assert ss.after_cost_return(0.50, 0.50, 1.04) == pytest.approx(-0.0208 / 0.5104 * 100)
    r = rec(ms(10, 12), ms(10, 12, 3))
    ss.observe(r, 10, r["schedule"][0]["dueTs"] + 300, quote(r["schedule"][0]["dueTs"] + 100))
    ss.observe(r, 30, r["schedule"][1]["dueTs"] + 300, quote(r["schedule"][1]["dueTs"] + 100, bid=5.0, ask=5.1))
    o = ss.outcome(r, 1.04)
    assert o["primary"] == ss.WINSOR_PCT and o["primaryRaw"] > 600


# ------------------------------------------------------------------ amendment 4: the denominator keeps everything
def test_incomplete_and_abandoned_observations_stay_in_the_coverage_denominator():
    done = rec(ms(10, 12), ms(10, 12, 3))
    ss.observe(done, 10, done["schedule"][0]["dueTs"] + 300, quote(done["schedule"][0]["dueTs"] + 100))
    ss.observe(done, 30, done["schedule"][1]["dueTs"] + 300, quote(done["schedule"][1]["dueTs"] + 100))
    crashed = rec(ms(10, 40), ms(10, 40, 2))                                   # opened, journaled, never closed (crash / disarm)
    restarted = rec(ms(11, 0), ms(11, 0, 2))
    ss.abandon(restarted, "restart", ms(11, 50))
    opens = [json.loads(json.dumps(x)) for x in (done, crashed, restarted)]
    opens[0]["status"], opens[0]["observations"] = "open", {}                  # what was journaled at the START
    rows = ss.collapse(opens, [done, restarted])
    assert len(rows) == 3 and sorted(r["status"] for r in rows) == ["closed", "closed", "incomplete"]
    cov = ss.coverage(rows, "scenario4", 1.04)["scenario_4"]
    assert cov["opportunities"] == 3 and cov["valid"] == 1 and cov["reasons"] == {"incomplete": 1, "restart": 1}
    assert cov["coveragePct"] == pytest.approx(33.3)


async def test_an_overdue_observation_after_a_restart_is_unknown_never_backfilled(monkeypatch):
    runner, ap = rig()
    ap.plan_for = DAY
    emitted = []
    runner._diag_emit = lambda ap_, kind, payload: emitted.append((kind, payload))
    monkeypatch.setattr(runner, "rt", lambda k, d=None: "collect" if k == "selection_study" else (True if k == "diagnostics" else d))
    r = rec(ms(10, 12), ms(10, 12, 3))
    r["schedule"][0]["status"] = "inflight"                                    # the process died mid-observation
    runner.restore_extras(ap, {"selectionStudy": {"records": {r["opportunityId"]: r}}})
    restored = runner._study_of(ap.run_id)["records"][r["opportunityId"]]
    assert restored["schedule"][0]["status"] == "pending"
    runner.engine.options = SimpleNamespace(refresh_now=AsyncMock(side_effect=AssertionError("an overdue observation must not be quoted")))
    runner._study_tick(r["schedule"][1]["dueTs"] + ss.MAX_LATE_MS + 1)
    assert restored["status"] == "closed" and all("late" in o["reason"] for o in restored["observations"].values())
    assert [k for k, _ in emitted] == ["selection_study_close"]
    assert ss.outcome(restored, 1.04)["primary"] is None
