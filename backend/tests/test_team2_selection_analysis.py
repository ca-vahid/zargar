"""The FROZEN analysis of selection study S1 (`s1-r3`): written, tested and hash-pinned before any observation exists.
Synthetic journal rows only."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import random

import pytest

from zargar.marketstructure.sessions import ET
from zargar.techniques.team2 import selection_study as ss
from zargar.techniques.team2 import selection_study_analysis as an
from zargar.tools import team2_selection_study as tool

FEE = 1.04
MIN = 60_000
# Any edit to the analysis changes this hash: that is a NEW registration, reviewed before collection continues.
FROZEN_ANALYSIS_SHA256 = "ad4b02111a79494ffdc1b71c5ff04e68e88f6c20c611851269814bb79adcb772"


def _ts(day: dt.date, h, m, s=0):
    return int(dt.datetime(day.year, day.month, day.day, h, m, s, tzinfo=ET).timestamp() * 1000)


def _feats(**values):
    f = {k: {"value": ("other" if k == "scenario4" else "later" if k == "first15" else "no_flag" if k == "flag" else "pm" if k == "levelOrigin"
                       else "short" if k == "wait" else "near"), "inputs": {}} for k in ss.FEATURES}
    for k, v in values.items():
        f[k] = {"value": v, "inputs": {}}
    return f


def rows_for(day: dt.date, idx: int, ret_pct: float | None, *, feats, role="control", valid=True, close=True, study=None):
    """one opportunity -> its journal rows (open [+ close]); `ret_pct` sets the 30-minute bid so that R30 == ret_pct"""
    T = _ts(day, 10, 0) + idx * 2 * MIN
    q0 = T + 2000
    sel = {"symbol": "SPY", "ask": 0.60, "bid": 0.58, "quoteTs": q0, "collectedTs": q0 + 50, "source": "opra", "selected": True}
    rec = ss.open_record(date=day.isoformat(), symbol="SPY", setup_id="scenario_1@09:45", signal_ts=T, book={"portfolioId": "p-" + role, "role": role},
                         trigger="t", direction="long", feats=feats, selected=sel, shadow=False, refusal=None, recorded_ts=q0 + 60, followed_now=0)
    opened = json.loads(json.dumps({**rec, "kind": "selection_study_open"}))
    if study:
        opened["study"] = study
    out = [opened]
    if close:
        f = FEE / 100.0
        bid = (ret_pct / 100.0) * (0.60 + f) + 0.60 + 2 * f if ret_pct is not None else 0.7
        for h in ss.HORIZONS_MIN:
            due = q0 + h * MIN
            q = {"bid": bid, "ask": bid + 0.02, "source": "opra" if valid else "chain", "quoteTs": due + 100}
            ss.observe(rec, h, due + 200, q)
        closed = json.loads(json.dumps({**rec, "kind": "selection_study_close"}))
        if study:
            closed["study"] = study
        out.append(closed)
    return out


def dataset(fav_mean, rest_mean, *, feature="flag", value="flag", sessions=30, per_session=(3, 5), sd=20.0, seed=1, fav_valid=True, rest_valid=True):
    rng = random.Random(seed)
    rows, day = [], dt.date(2026, 10, 1)
    for s in range(sessions):
        d = day + dt.timedelta(days=s)
        i = 0
        for _ in range(per_session[0]):
            rows += rows_for(d, i, rng.gauss(fav_mean, sd), feats=_feats(**{feature: value}), valid=fav_valid); i += 1
        for _ in range(per_session[1]):
            rows += rows_for(d, i, rng.gauss(rest_mean, sd), feats=_feats(), valid=rest_valid); i += 1
    return rows


def test_the_analysis_file_is_frozen():
    p = pathlib.Path(an.__file__)
    got = hashlib.sha256(p.read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()
    assert got == FROZEN_ANALYSIS_SHA256, f"selection_study_analysis.py changed: a new registration is required (sha256 {got})"


def test_holm_step_down_is_monotone_and_matches_known_values():
    adj = an.holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5})
    assert adj == pytest.approx({"a": 0.04, "c": 0.09, "b": 0.09, "d": 0.5})
    assert an.holm({}) == {}


def test_a_clearly_better_bucket_passes_and_only_one_feature_goes_forward():
    rows = dataset(40.0, -5.0, sessions=30, per_session=(3, 5))
    rep = an.analyse(rows, FEE, resamples=1500)
    t = next(x for x in rep["tests"] if x["feature"] == "flag")
    assert t["judgeable"] and t["nFavoured"] == 90 and t["nRest"] == 150 and t["sessionsFavoured"] == 30
    assert t["verdict"] == "pass" and t["d"] > 30 and t["ci95"][0] > 0 and t["pHolm"] < 0.05 and t["favouredMean"] > 0
    assert rep["studyOutcome"] == "at least one pass" and rep["featureCarriedForward"] == "flag"
    assert all(x["verdict"] == "insufficient evidence" for x in rep["tests"] if x["feature"] != "flag")


def test_a_significantly_worse_bucket_can_never_pass_even_with_a_positive_mean():
    rows = dataset(10.0, 60.0, sessions=30, per_session=(3, 5))                  # favoured is POSITIVE after costs but much WORSE than the rest
    t = next(x for x in an.analyse(rows, FEE, resamples=1500)["tests"] if x["feature"] == "flag")
    assert t["judgeable"] and t["favouredMean"] > 0 and t["pHolm"] < 0.05 and t["d"] < 0
    assert t["verdict"] == "fail" and any("not positive" in r for r in t["reasons"])


def test_a_better_but_still_losing_bucket_fails():
    t = next(x for x in an.analyse(dataset(-20.0, -60.0), FEE, resamples=1500)["tests"] if x["feature"] == "flag")
    assert t["d"] > 0 and t["ci95"][0] > 0 and t["verdict"] == "fail" and any("own mean" in r for r in t["reasons"])


def test_an_effect_carried_by_three_sessions_fails():
    rows = dataset(-1.0, 0.0, sessions=30, per_session=(3, 5), sd=0.5)      # without the three sessions the favoured bucket is slightly WORSE
    day = dt.date(2026, 10, 1)
    for s in range(3):                                                           # three sessions with an enormous favoured result
        for i in range(40, 46):
            rows += rows_for(day + dt.timedelta(days=s), i, 190.0, feats=_feats(flag="flag"))
    t = next(x for x in an.analyse(rows, FEE, resamples=1500)["tests"] if x["feature"] == "flag")
    assert t["d"] > 0 and t["dWithoutBestSessions"] < 0 and t["verdict"] == "fail" and any("three most favourable" in r for r in t["reasons"])


@pytest.mark.parametrize("kw, word", [
    (dict(sessions=30, per_session=(1, 5)), "valid outcomes"),                   # 30 favoured outcomes only
    (dict(sessions=15, per_session=(5, 5)), "sessions"),                         # enough outcomes, too few sessions
    (dict(sessions=30, per_session=(3, 5), fav_valid=False), "coverage"),        # the favoured side has no valid quotes
])
def test_minimums_give_insufficient_evidence_never_a_pass(kw, word):
    t = next(x for x in an.analyse(dataset(40.0, -5.0, **kw), FEE, resamples=300)["tests"] if x["feature"] == "flag")
    assert t["verdict"] == "insufficient evidence" and any(word in r for r in t["reasons"]), t["reasons"]


def test_a_coverage_gap_between_the_sides_is_insufficient_evidence():
    rows = dataset(40.0, -5.0, sessions=30, per_session=(3, 5))
    day = dt.date(2026, 10, 1)
    for s in range(30):                                                          # 30 extra favoured opportunities that never closed
        rows += rows_for(day + dt.timedelta(days=s), 60, None, feats=_feats(flag="flag"), close=False)
    t = next(x for x in an.analyse(rows, FEE, resamples=300)["tests"] if x["feature"] == "flag")
    assert t["coverageFavouredPct"] == 75.0 and t["coverageRestPct"] == 100.0 and t["verdict"] == "insufficient evidence"


def test_the_population_sets_c1_only_excluded_sessions_and_other_registrations_apart():
    d1, d2 = dt.date(2026, 10, 1), dt.date(2026, 10, 2)
    rows = rows_for(d1, 0, 10.0, feats=_feats()) + rows_for(d1, 1, 10.0, feats=_feats(), role="c1") \
        + rows_for(d2, 0, 10.0, feats=_feats()) + rows_for(d2, 1, 10.0, feats=_feats(), study="s1-r2")
    pop = an.population(rows, excluded_sessions={d2.isoformat()})
    assert len(pop["all"]) == 3 and len(pop["primary"]) == 1 and len(pop["c1Only"]) == 1 and len(pop["excludedSessionRows"]) == 1
    assert pop["otherRegistrations"] == 2, "rows of an earlier registration are counted and never analysed"


def test_several_passers_are_reduced_to_one_by_the_frozen_order():
    tests = [{"feature": "room", "verdict": "pass", "pHolm": 0.01, "ci95": [2.0, 9.0]}, {"feature": "flag", "verdict": "pass", "pHolm": 0.01, "ci95": [2.0, 8.0]},
             {"feature": "wait", "verdict": "pass", "pHolm": 0.01, "ci95": [1.0, 9.0]}, {"feature": "first15", "verdict": "fail", "pHolm": 0.001, "ci95": [5, 9]}]
    assert an.choose(tests) == "flag"                                            # tie on p and on the lower bound: the feature order decides
    tests[2]["ci95"] = [3.0, 9.0]
    assert an.choose(tests) == "wait"                                            # a larger lower bound wins the tie on p
    tests[0]["pHolm"] = 0.001
    assert an.choose(tests) == "room"                                            # the smallest adjusted p wins outright
    assert an.choose([t for t in tests if t["verdict"] != "pass"]) is None


def test_the_tool_shows_coverage_only_until_the_stop_rule():
    assert tool.may_finalise(59, dt.date(2026, 12, 17))[0] is False
    assert tool.may_finalise(60, dt.date(2026, 10, 1))[0] is True and tool.may_finalise(12, dt.date(2026, 12, 18))[0] is True
    view = tool.coverage_only(dataset(40.0, -5.0, sessions=4), FEE)
    text = json.dumps(view)
    assert view["view"].startswith("coverage only") and "primary" not in json.dumps(view["coverage"]) and "observations" not in text
    assert view["coverage"]["flag"]["flag"] == {"opportunities": 12, "valid": 12, "reasons": {}, "coveragePct": 100.0}
