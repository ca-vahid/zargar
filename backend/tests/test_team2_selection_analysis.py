"""The FROZEN analysis of selection study S1 (`s1-r4`): written, tested and hash-pinned before any observation exists.
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

FEE = 1.04
MIN = 60_000


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
            if not any(x["horizonMin"] == h and x["status"] == "pending" for x in rec["schedule"]):
                continue                                                      # already resolved at the opening (late / capacity)
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


def test_the_analysis_file_is_frozen_and_pinned_by_the_registration():
    p = pathlib.Path(an.__file__)
    got = hashlib.sha256(p.read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()
    assert got == ss.ANALYSIS_SHA256, f"selection_study_analysis.py changed: a new registration is required (sha256 {got})"
    assert ss.REGISTRATION["analysis"]["sha256"] == got and ss.REGISTRATION["study"] == ss.STUDY == "s1-r4"
    reg = json.loads(json.dumps(ss.REGISTRATION, sort_keys=True))
    assert hashlib.sha256(json.dumps(reg, sort_keys=True).encode()).hexdigest()[:16] == ss.REGISTRATION_HASH
    assert reg["outcome"]["feePerContract"] == an.FEE_PER_CONTRACT == 1.04 and reg["outcome"]["winsorUpperPct"] == ss.WINSOR_PCT == 200.0
    assert reg["featureOrder"] == list(an.FEATURE_ORDER) and reg["outcome"]["secondaryTested"] is False


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


def test_the_holm_family_is_all_six_features_with_unjudgeable_ones_at_p_one():
    tests = [{"feature": f, "judgeable": f == "flag", "p": (0.004 if f == "flag" else 0.0001)} for f in an.FEATURE_ORDER]
    fam = an.family_pvalues(tests)
    assert fam == {"flag": 0.004, "levelOrigin": 1.0, "wait": 1.0, "first15": 1.0, "scenario4": 1.0, "room": 1.0}
    assert an.holm(fam)["flag"] == pytest.approx(0.024), "the family size stays six even when five features cannot be judged"


def test_resampling_whole_sessions_keeps_within_session_dependence():
    """Favoured returns share a strong SESSION effect: resampling sessions must give a much wider interval than resampling
    observations as if they were independent."""
    rng = random.Random(3)
    rows, day = [], dt.date(2026, 10, 1)
    for s_ in range(30):
        d = day + dt.timedelta(days=s_)
        shock = rng.gauss(0.0, 40.0)
        for i in range(4):
            rows += rows_for(d, i, 10.0 + shock + rng.gauss(0, 2.0), feats=_feats(flag="flag"))
        for i in range(4, 9):
            rows += rows_for(d, i, rng.gauss(0.0, 2.0), feats=_feats())
    pop = an.population(rows)["primary"]
    t = an.feature_test(pop, "flag", FEE, resamples=2000)
    fav = [ss.outcome(r, FEE)["primary"] for r in pop if r["features"]["flag"]["value"] == "flag"]
    rest = [ss.outcome(r, FEE)["primary"] for r in pop if r["features"]["flag"]["value"] != "flag"]
    r2 = random.Random(5)
    naive = sorted(sum(r2.choices(fav, k=len(fav))) / len(fav) - sum(r2.choices(rest, k=len(rest))) / len(rest) for _ in range(2000))
    naive_w = naive[1949] - naive[50]
    clustered_w = t["ci95"][1] - t["ci95"][0]
    assert clustered_w > 1.6 * naive_w, (clustered_w, naive_w)


def test_fees_winsorisation_and_descriptive_secondary_outcomes_match_the_registration():
    r = rows_for(dt.date(2026, 10, 1), 0, 500.0, feats=_feats(flag="flag"))
    o = ss.outcome(an.population(r)["primary"][0], FEE)
    assert o["primary"] == ss.WINSOR_PCT and o["primaryRaw"] == pytest.approx(500.0)
    assert set(o["secondary"]) == {"10", "30_oneTickWorse"} and o["secondary"]["30_oneTickWorse"] < o["primaryRaw"]
    t = an.analyse(dataset(40.0, -5.0), resamples=300)["tests"][0]
    assert set(t["secondaryDescriptive"]["fav"]) == {"10", "30_oneTickWorse"}, "secondary outcomes are reported, never tested"
    import inspect
    from zargar.techniques.team2 import selection_study_lifecycle as lc
    assert list(inspect.signature(lc.finalise).parameters) == ["life", "study_rows"], "the final analysis takes no cost, window or exclusion argument"


def test_rows_of_another_registration_hash_are_never_analysed():
    d = dt.date(2026, 10, 1)
    rows = rows_for(d, 0, 10.0, feats=_feats())
    forged = [dict(r, registrationHash="0000000000000000") for r in rows_for(d, 1, 10.0, feats=_feats())]
    pop = an.population(rows + forged)
    assert len(pop["all"]) == 1 and pop["otherRegistrations"] == 2
