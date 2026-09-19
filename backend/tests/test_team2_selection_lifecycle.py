"""Selection study S1 (`s1-r4`): lifecycle, session accounting, endpoint, frozen sample and reproducible final analysis.
Pure: synthetic durable facts only (no database, no runtime)."""
from __future__ import annotations

import datetime as dt
import json
import random

import pytest

from zargar.marketstructure.market_calendar import is_early_close, trading_days
from zargar.techniques.team2 import selection_study as ss
from zargar.techniques.team2 import selection_study_lifecycle as lc
from zargar.tools import team2_selection_study as tool

from .test_team2_selection_analysis import _feats, rows_for

A = lc._ms(dt.date(2026, 9, 18), 20, 0)                        # activation: Friday 2026-09-18 after the close
DAYS = trading_days(dt.date(2026, 9, 21), dt.date(2027, 1, 29))
FULL = [d for d in DAYS if not is_early_close(d)]               # 2026-11-27 closes at 13:00: objectively excluded


def act(**over):
    return {**tool.activation_payload("test-build", A), **over}


def life(rows=(), *, now, settings=None, restarts=(), outages=None, finals=None):
    return lc.lifecycle(activation_rows=[act(), *rows], setting_events=settings if settings is not None else [(A, "collect")],
                        restart_ts=list(restarts), outages=outages or {}, study_rows=list(rows), final_rows=finals or [], now_ms=now)


def close_of(d):
    return lc.session_bounds(d)[1]


def opp(d, i, ret=5.0, feats=None, **kw):
    return rows_for(d, i, ret, feats=feats or _feats(), **kw)


# ------------------------------------------------------------------ registration and activation
def test_prepared_until_an_activation_of_exactly_this_registration():
    now = close_of(FULL[3])
    assert lc.lifecycle(activation_rows=[], setting_events=[(A, "collect")], restart_ts=[], outages={}, study_rows=[], now_ms=now)["state"] == "prepared"
    for bad in (act(study="s1-r3"), act(registrationHash="0" * 16), act(analysisSha256="f" * 64)):
        r = lc.lifecycle(activation_rows=[bad], setting_events=[(A, "collect")], restart_ts=[], outages={}, study_rows=[], now_ms=now)
        assert r["state"] == "prepared", bad
    a = act()
    assert a["registration"] == ss.REGISTRATION and a["analysisSha256"] == ss.ANALYSIS_SHA256 and a["firstEligibleSession"] == "2026-09-21"


def test_zero_opportunity_sessions_count_and_the_first_eligible_session_is_the_first_full_one():
    r = life(now=close_of(FULL[2]))
    assert r["state"] == "collecting" and r["firstEligibleSession"] == "2026-09-21" and r["countedSessions"] == 3
    assert [s["status"] for s in r["sessions"]] == ["counted", "counted", "counted"]
    mid = life(now=lc.session_bounds(FULL[3])[0] + 60_000)
    assert mid["countedSessions"] == 3 and mid["sessions"][-1]["status"] == "in_progress", "a running session is not counted"


# ------------------------------------------------------------------ endpoint
def test_59_counted_sessions_and_an_opening_on_the_60th_morning_do_not_unlock_the_analysis():
    d60 = FULL[59]
    rows = opp(d60, 0)[:1]                                                      # an opening at 10:00 on the 60th session
    o, c = lc.session_bounds(d60)
    morning = life(rows, now=o + 45 * 60_000)
    assert morning["countedSessions"] == 59 and morning["state"] == "collecting"
    with pytest.raises(ValueError):
        lc.final_sample(morning, rows)
    assert life(rows, now=c - 1)["state"] == "collecting"
    done = life(rows, now=c)
    assert done["state"] == "ready_for_final_analysis" and done["countedSessions"] == 60 and done["endpointMs"] == c
    assert "60th counted session" in done["endpointReason"] and d60 < lc.DEADLINE


def test_the_deadline_is_the_close_of_the_2026_12_18_session_in_et():
    late = lc._ms(dt.date(2026, 10, 30), 20, 0)
    lif = lambda now: lc.lifecycle(activation_rows=[act(activatedAt=late)], setting_events=[(late, "collect")], restart_ts=[], outages={},
                                   study_rows=[], now_ms=now)
    c = close_of(dt.date(2026, 12, 18))
    assert c == int(dt.datetime(2026, 12, 18, 21, 0, tzinfo=dt.timezone.utc).timestamp() * 1000), "16:00 ET = 21:00 UTC in December"
    before, at = lif(c - 1), lif(c)
    assert before["state"] == "collecting" and before["countedSessions"] < 60
    assert at["state"] == "ready_for_final_analysis" and "deadline" in at["endpointReason"] and at["endpointMs"] == c
    # a local calendar date is not the session: 20:30 ET on the deadline is still the 18th in ET (01:30 UTC on the 19th)
    assert lc.et_date(lc._ms(dt.date(2026, 12, 18), 20, 30)) == dt.date(2026, 12, 18)


# ------------------------------------------------------------------ objective exclusions and partial sessions
def test_objective_exclusions_partial_and_disabled_sessions_never_advance_the_count():
    d = FULL
    restarts = [lc._ms(d[0], 11, 7), lc._ms(d[1], 15, 50), lc._ms(d[2], 8, 0)]    # inside / after the cut-off / before the open
    minutes = {s: [] for s in ("SPY", "QQQ", "IWM")}
    for day in d[:8]:
        o, c = lc.session_bounds(day)
        for s in minutes:
            minutes[s] += [t for t in range(o, c, 60_000)]
    o3 = lc.session_bounds(d[3])[0]
    minutes["QQQ"] = [t for t in minutes["QQQ"] if not (o3 + 60 * 60_000 <= t < o3 + 63 * 60_000)]   # three missing minutes
    o4 = lc.session_bounds(d[4])[0]
    minutes["IWM"] = [t for t in minutes["IWM"] if not (o4 + 60 * 60_000 <= t < o4 + 62 * 60_000)]   # two missing minutes: tolerated
    outages = lc.outage_dates(minutes, d[:8])
    assert set(outages) == {d[3].isoformat()} and "QQQ missing 3" in outages[d[3].isoformat()]
    settings = [(A, "collect"), (lc._ms(d[5], 12, 0), "off"), (lc._ms(d[5], 17, 0), "collect"),
                (lc._ms(d[6], 7, 0), "off"), (lc._ms(d[6], 18, 0), "collect")]
    r = life(now=close_of(d[7]), settings=settings, restarts=restarts, outages=outages)
    st = {s["date"]: (s["status"], s["reasons"]) for s in r["sessions"]}
    assert st[d[0].isoformat()] == ("excluded", ["engine restart at 11:07:00 ET"])
    assert st[d[1].isoformat()][0] == "counted" and st[d[2].isoformat()][0] == "counted"
    assert st[d[3].isoformat()][0] == "excluded" and st[d[4].isoformat()][0] == "counted"
    assert st[d[5].isoformat()] == ("partial", ["collector on for only part of the session"])
    assert st[d[6].isoformat()] == ("disabled", ["collector off for the whole session"])
    assert r["countedSessions"] == 4 and r["statusCounts"] == {"excluded": 2, "counted": 4, "partial": 1, "disabled": 1}
    ec = life(now=close_of(dt.date(2026, 11, 27)))
    assert next(s for s in ec["sessions"] if s["date"] == "2026-11-27") == {"date": "2026-11-27", "status": "excluded", "reasons": ["13:00 early close"]}
    mid = lc.lifecycle(activation_rows=[act(activatedAt=lc._ms(d[0], 10, 0))], setting_events=[(A, "collect")], restart_ts=[], outages={},
                       study_rows=[], now_ms=close_of(d[1]))
    assert [s["status"] for s in mid["sessions"]] == ["partial", "counted"] and mid["firstEligibleSession"] == d[1].isoformat()


def test_the_lifecycle_is_a_pure_function_of_durable_records():
    rows = opp(FULL[0], 0) + opp(FULL[1], 0)
    a = life(rows, now=close_of(FULL[5]), restarts=[lc._ms(FULL[2], 12, 0)])
    b = life(list(rows), now=close_of(FULL[5]), restarts=[lc._ms(FULL[2], 12, 0)])
    assert a == b and a["countedSessions"] == 5


# ------------------------------------------------------------------ early stop on poor coverage (coverage only)
@pytest.mark.parametrize("valid_every, state", [(1, "collecting"), (2, "stopped_insufficient_coverage")])
def test_the_poor_coverage_early_stop_is_applied_from_the_15th_session(valid_every, state):
    rows = []
    for i, d in enumerate(FULL[:16]):
        for j in range(2):
            rows += opp(d, j, 5.0, valid=(j % valid_every == 0))
    r = life(rows, now=close_of(FULL[15]))
    assert r["state"] == state
    if state.startswith("stopped"):
        assert r["stopMs"] == close_of(FULL[14]) and "50.0% < 60%" in r["stopReason"]
        assert r["sessions"][-1]["status"] == "after_endpoint"
        with pytest.raises(ValueError):
            lc.final_sample(r, rows)
    view = lc.coverage_view(r, rows)
    text = json.dumps(view)
    for word in ('"primary"', '"primaryRaw"', '"d"', '"favouredMean"', '"ci95"', '"observations"', '"bid"'):
        assert word not in text, word
    assert view["view"].startswith("coverage only") and view["coveragePct"] in (100.0, 50.0)


# ------------------------------------------------------------------ the frozen sample
def test_pending_observations_at_the_endpoint_and_post_endpoint_records_stay_out_of_the_sample():
    d60, d61 = FULL[59], FULL[60]
    rows = []
    for i, d in enumerate(FULL[:60]):
        rows += opp(d, 0, 5.0)
    late = rows_for(d60, 160, 5.0, feats=_feats())                              # opened 15:20: its 30-minute due is after 15:45
    assert late[0]["observations"].get("30", {}).get("reason", "").startswith("late")
    unclosed = rows_for(d60, 50, None, feats=_feats(), close=False)              # never closed: incomplete
    after = opp(d61, 0, 5.0)                                                     # a session after the endpoint
    forged = json.loads(json.dumps(opp(FULL[10], 7, 5.0)))
    endpoint = close_of(d60)
    forged[1]["observations"]["30"]["quoteTs"] = endpoint + 1                    # an observation dated after the endpoint
    all_rows = rows + late + unclosed + after + forged
    r = life(all_rows, now=close_of(d61) + 1)
    assert r["state"] == "ready_for_final_analysis" and r["endpointMs"] == endpoint
    inc, man = lc.final_sample(r, all_rows)
    oids = {x["opportunityId"] for x in man["records"]}
    assert after[0]["opportunityId"] not in oids and man["rowsOutsideSample"] == {"session not counted": 2}
    assert unclosed[0]["opportunityId"] in oids and late[0]["opportunityId"] in oids
    fr = next(x for x in inc if x["opportunityId"] == forged[1]["opportunityId"] and x["kind"] == "selection_study_close")
    assert fr["observations"]["30"]["valid"] is False and fr["observations"]["30"]["reason"] == "after endpoint"
    rep = lc.finalise(r, all_rows)["report"]
    cov = rep["coverage"]["scenario4"]["other"]
    assert cov["reasons"].get("incomplete") == 1 and cov["reasons"].get("late") == 1 and cov["reasons"].get("after endpoint") == 1


def test_repeated_finalisation_is_identical_order_independent_and_verifiable():
    rows = []
    for i, d in enumerate(FULL[:60]):
        rows += opp(d, 0, 5.0 + i % 7)
    r = life(rows, now=close_of(FULL[59]))
    a = lc.finalise(r, rows)
    shuffled = list(rows)
    random.Random(1).shuffle(shuffled)
    b = lc.finalise(life(shuffled, now=close_of(FULL[59]) + 5_000_000), shuffled)
    assert a["manifestSha256"] == b["manifestSha256"] and a["resultSha256"] == b["resultSha256"]
    assert lc.verify(a, r, rows) == {"manifestMatches": True, "resultMatches": True, "manifestSha256": a["manifestSha256"], "resultSha256": a["resultSha256"]}
    tampered = json.loads(json.dumps(rows))
    tampered[1]["observations"]["30"]["bid"] = 9.99
    v = lc.verify(a, r, tampered)
    assert v["manifestMatches"] is False and v["resultMatches"] is False
    assert a["manifest"]["window"]["endpointMs"] == close_of(FULL[59]) and len(a["manifest"]["countedSessions"]) == 60
    assert a["manifest"]["registrationHash"] == ss.REGISTRATION_HASH and a["manifest"]["analysisSha256"] == ss.ANALYSIS_SHA256


def test_a_recorded_final_row_of_this_registration_marks_the_study_finalized():
    rows = [x for d in FULL[:60] for x in opp(d, 0)]
    now = close_of(FULL[59]) + 1
    fin = {"kind": "selection_study_final", "study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH, "manifestSha256": "m", "resultSha256": "r"}
    assert life(rows, now=now, finals=[fin])["state"] == "finalized"
    assert life(rows, now=now, finals=[{**fin, "registrationHash": "x" * 16}])["state"] == "ready_for_final_analysis"


# ------------------------------------------------------------------ known datasets through the WHOLE final path
def _dataset(fav_mean, rest_mean, fav_per_session, seed=11):
    rng = random.Random(seed)
    rows = []
    for d in FULL[:60]:
        for i in range(fav_per_session):
            rows += rows_for(d, i, rng.gauss(fav_mean, 20.0), feats=_feats(flag="flag"))
        for i in range(fav_per_session, fav_per_session + 3):
            rows += rows_for(d, i, rng.gauss(rest_mean, 20.0), feats=_feats())
    return rows


@pytest.mark.parametrize("fav, rest, per, outcome, verdict", [
    (40.0, -5.0, 2, "at least one pass", "pass"),                               # known positive
    (-20.0, 10.0, 2, "none", "fail"),                                           # known negative (a worse favoured bucket)
    (40.0, -5.0, 0, "none", "insufficient evidence"),                           # no favoured observations at all
])
def test_known_datasets_through_lifecycle_and_final_analysis(fav, rest, per, outcome, verdict):
    rows = _dataset(fav, rest, per)
    r = life(rows, now=close_of(FULL[59]))
    fin = lc.finalise(r, rows)
    flag = next(t for t in fin["report"]["tests"] if t["feature"] == "flag")
    assert fin["report"]["studyOutcome"] == outcome and flag["verdict"] == verdict
    assert fin["report"]["featureCarriedForward"] == ("flag" if verdict == "pass" else None)


def test_the_deterministic_demo_is_stable():
    a, b = tool.demo(), tool.demo()
    assert a == b and a["reproduced"] is True and a["state"] == "ready_for_final_analysis" and "deadline" in a["endpoint"]
    assert {s["status"] for s in a["nonCounted"]} == {"excluded", "disabled"} and a["rowsOutsideSample"] == {"session not counted": 99}
