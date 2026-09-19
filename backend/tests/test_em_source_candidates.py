"""source-continuation-v1 + requalification-v1 (integrated plan C, 2026-09-18). Acceptance rows "Requalification" and the
order-free half of "Authority". Real 09-18 scenarios/plans for the producer; synthetic 1m bars through the PRODUCTION
tracker for the evaluator. Pure: no engine, no database, no orders."""
import copy
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

from zargar.domain import Bar
from zargar.execution.origins import scenario_origin
from zargar.technique import requalification as rq
from zargar.technique import source_candidate_policy as scp
from zargar.technique import source_scenarios as ss
from zargar.technique.rulebook import DEFAULT_THRESHOLDS as T
from zargar.technique.walkforward import build_profile

NY = ZoneInfo("America/New_York")
FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "em_source_notes_2026_09_18.json"), encoding="utf-8"))
AUTHOR, EVA = "ae7cfbc9010e4254bcdb714b821f7c79", "c2846661a72f4e588435538473f4f483"
SESSION = "2026-09-18"


def ms(h, m, day=18):
    return int(dt.datetime(2026, 9, day, h, m, tzinfo=NY).timestamp() * 1000)


def bar(h, m, o, hi, lo, c, v=100_000):
    return Bar("X", "1m", ms(h, m), o, hi, lo, c, v)


PROFILE = build_profile([Bar("X", "1m", ms(9, 30, d) + i * 60000, 99, 99.2, 98.9, 99.1, 100_000) for d in (15, 16, 17) for i in range(390)])


def _payload(nid):
    return ss.build_scenarios(copy.deepcopy(FX[nid]))


def _scn(p, sym, direction=None):
    return next(s for s in p["scenarios"] if s["authorSupplied"]["symbolAsExtracted"] == sym and (direction is None or s["authorSupplied"]["direction"] == direction))


def _plan(prefix):
    return next(v for k, v in FX["plans"].items() if k.startswith(prefix))


def _cand(nid, sym, prefix, direction=None):
    p = _payload(nid); s = _scn(p, sym, direction); pl = _plan(prefix)
    m = ss.match_plan(s, p, pl["plan"], plan_built_at=pl["createdAt"], plan_origin=pl["trigger"])
    return scp.build_candidate(scenario=s, payload=p, match=m, plan=pl["plan"], policy_record=None, session=SESSION)


# ------------------------------------------------------------------------------------ source-conditioned continuation
def test_amd_2_97r_and_the_spcx_long_stay_named_refusals_and_nothing_is_loosened():
    amd = _cand(AUTHOR, "AMD", "17df157e")
    assert amd["disposition"] == "refused" and amd["namedBaselineOutcome"] is True and "2.97" in amd["reason"] and amd["geometry"]["planTrigger"] == "k1"
    spcx = _cand(AUTHOR, "SPCX", "b9953dd0")
    assert spcx["disposition"] == "refused" and spcx["geometry"]["planTrigger"] == "k2", "the author's LONG branch - never the armed short reject r2"
    assert spcx["direction"] == "long" and spcx["trigger"]["kind"] == "breakout"


def test_missing_evidence_is_held_never_invented():
    nvda = _cand(AUTHOR, "NVDA", "3ed6d5cd")
    assert nvda["disposition"] == "held_for_missing_evidence" and "no numeric level" in nvda["reason"] and nvda["source"]["stop"] is None
    tsla = _cand(AUTHOR, "TSLA", "96f11590")
    assert tsla["disposition"] == "held_for_missing_evidence" and "evidence_names_MU_not_TSLA" in tsla["reason"] and tsla["symbol"] is None
    mu = _cand(EVA, "MU", "ae478636")
    assert mu["disposition"] == "held_for_missing_evidence" and mu["matchOverall"] == "same_direction_not_aligned", "EvaPanda's 980 HOLD is not our 986.20 breakout"
    arm = _cand(EVA, "ARM", "62df26d8")
    assert arm["disposition"] == "held_for_missing_evidence" and "swing" in arm["reason"], "a swing idea needs a separately declared horizon"


def test_every_candidate_is_order_free_by_origin_and_has_one_id_per_branch_and_session():
    for c in (_cand(AUTHOR, "AMD", "17df157e"), _cand(AUTHOR, "NVDA", "3ed6d5cd"), _cand(EVA, "MU", "ae478636")):
        assert c["orderFree"] is True and c["origin"].startswith("scenario:")
        assert scenario_origin({"config": {"origin": c["origin"]}}) == c["origin"], "the runner's arm boundary recognises and refuses this origin"
    a, b = _cand(AUTHOR, "AMD", "17df157e"), _cand(AUTHOR, "AMD", "17df157e")
    assert a["candidateId"] == b["candidateId"] and a["candidateId"] != _cand(AUTHOR, "SPCX", "b9953dd0")["candidateId"]
    app = [_cand(AUTHOR, "APP", "e9cbcf2f", d) for d in ("long", "short")]
    assert app[0]["pairId"] == app[1]["pairId"] and app[0]["candidateId"] != app[1]["candidateId"], "two branches, two candidates, one pair"


TRIG = {"id": "k1", "kind": "breakout", "direction": "long", "levelPrice": 100.0, "valid": True, "riskReward": 3.5, "entry": {"price": 100.0, "basis": "on_break"},
        "stop": {"price": 99.0}, "targets": [{"price": 101.5}, {"price": 103.0}, {"price": 104.0}]}
MORNING = [bar(9, 30, 99.5, 99.7, 99.4, 99.6), bar(9, 31, 99.6, 99.8, 99.5, 99.7), bar(9, 32, 99.7, 99.9, 99.6, 99.8), bar(9, 33, 99.8, 100.4, 99.8, 100.3, 400_000),
           bar(9, 34, 100.3, 100.6, 100.2, 100.5, 300_000), bar(9, 35, 100.5, 100.9, 100.4, 100.8, 300_000), bar(9, 36, 100.8, 101.0, 100.7, 100.9)]


def _waiting(usable="2026-09-18T13:20:00+00:00", horizon=None):
    exp, der = scp.source_expiry_ts(SESSION, horizon)
    return {"version": scp.VERSION, "variant": "source_continuation", "candidateId": "sc1-x", "scenarioId": "s1", "origin": "scenario:s1", "orderFree": True, "symbol": "X",
            "direction": "long", "session": SESSION, "source": {"usableAt": usable}, "expiresTs": exp, "expiryDerivation": der, "disposition": "waiting", "trigger": copy.deepcopy(TRIG)}


def test_the_evaluator_is_causal_uses_its_own_tracker_and_keeps_the_outcome_apart():
    c = _waiting()
    before = json.dumps(c, sort_keys=True)
    early = scp.evaluate(c, MORNING, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 36))
    assert early["disposition"] == "waiting" and early["barsConsumed"] == 6, "the 09:36 bar has not CLOSED at 09:36 - no same-close knowledge"
    done = scp.evaluate(c, MORNING, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 37))
    assert done["disposition"] == "triggered" and done["firedTs"] == ms(9, 36) and done["fillProxy"] == 100.9
    assert done["pricingGates"]["contract"].startswith("unknown") and done["pricingGates"]["sizing"] == "unknown", "a triggered candidate is not an executable entry"
    assert done["outcomeProxy"]["evidenceClass"] == "underlying_walkforward_proxy"
    assert json.dumps(c, sort_keys=True) == before, "the candidate definition (and any baseline state) is never mutated"
    spike = MORNING + [bar(9, 37 + i, 101, 110, 100.9, 109) for i in range(5)]                       # a later target touch
    again = scp.evaluate(c, spike, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 37))
    assert {k: again[k] for k in ("disposition", "firedTs", "fillProxy")} == {k: done[k] for k in ("disposition", "firedTs", "fillProxy")}, "the future cannot alter eligibility"


def test_a_condition_completed_before_the_source_was_usable_is_not_a_source_entry_and_expiry_holds():
    late_source = scp.evaluate(_waiting(usable="2026-09-18T13:45:00+00:00"), MORNING, thresholds=T, profile=PROFILE, prev_close=99.5)
    assert late_source["disposition"] == "expired" and "before the source became usable" in late_source["reason"]
    assert scp.source_expiry_ts(SESSION, None) == (ms(11, 30), "source-morning-expiry-v1") and scp.source_expiry_ts(SESSION, "0dte")[0] == ms(16, 0)
    afternoon = [bar(15, 50 + i, *vals) for i, vals in enumerate([(99.5, 99.7, 99.4, 99.6), (99.6, 99.8, 99.5, 99.7), (99.8, 100.4, 99.8, 100.3, 400_000),
                                                                   (100.3, 100.6, 100.2, 100.5, 300_000), (100.5, 100.9, 100.4, 100.8, 300_000), (100.8, 101, 100.7, 100.9)])]
    quiet = [Bar("X", "1m", ms(9, 30) + i * 60000, 99.5, 99.6, 99.4, 99.5, 100_000) for i in range(125)]
    out = scp.evaluate(_waiting(), quiet + afternoon, thresholds=T, profile=PROFILE, prev_close=99.5)
    assert out["disposition"] == "expired" and out.get("firedTs") is None, "an 11:30 source idea is never stretched to a 15:55 move"


# ------------------------------------------------------------------------------------------------ requalification-v1
def _parent(**over):
    return {"scenarioId": "scn-nvda", "symbol": "NVDA", "direction": "long", "session": SESSION, "invalidatedTs": ms(9, 31), "invalidatedStatus": "invalidated",
            "sourceTargets": [222.0], "expiresTs": ms(11, 30), "oldEntry": 220.2367, **over}


def _path(prices, start=(9, 30)):
    out = []
    for i, p in enumerate(prices):
        h, m = divmod(start[0] * 60 + start[1] + i, 60)
        out.append(Bar("NVDA", "1m", ms(h, m), p, p + 0.10, p - 0.10, p, 100_000))
    return out


# down into a pivot LOW at 218.0 (09:36), up into a pivot HIGH at 219.6 (09:42), then a pullback
STRUCT = _path([219.0, 218.6, 218.5, 218.4, 218.3, 218.2, 218.0, 218.3, 218.6, 218.9, 219.2, 219.4, 219.6, 219.4, 219.2, 219.1, 219.0, 219.1, 219.2])


def test_no_reset_fresh_confirmed_structure_is_required_and_pivots_are_unavailable_before_confirmation():
    parent = _parent()
    snap = json.dumps(parent, sort_keys=True)
    rebound_only = _path([219.0, 218.6] + [218.6 + 0.2 * i for i in range(12)])                       # straight back up through the old entry: no pivots
    w = rq.build_child(parent=parent, bars=rebound_only, thresholds=T)
    assert w["disposition"] == "waiting" and "rebound through the old entry is not structure" in w["reason"] and w["parentState"]["untouched"] is True
    too_early = rq.build_child(parent=parent, bars=rq.bars_upto(STRUCT, ms(9, 45)), thresholds=T)     # the 09:42 pivot high confirms on the 09:45 bar, closed 09:46
    assert too_early["disposition"] == "waiting"
    ok = rq.build_child(parent=parent, bars=rq.bars_upto(STRUCT, ms(9, 46)), thresholds=T)
    assert ok["structure"]["break"]["price"] == 219.7 and ok["structure"]["protect"]["price"] == 217.9 and ok["structure"]["confirmedTs"] == ms(9, 45)
    assert ok["eligibleFromTs"] == ms(9, 45) and ok["geometry"]["entry"] == 219.7 and ok["geometry"]["entry"] != parent["oldEntry"]
    assert ok["geometry"]["stop"] < 217.9 and "fresh pivot" in ok["geometry"]["stopProvenance"] and ok["confirmation"]["sameCloseFill"] is False
    assert json.dumps(parent, sort_keys=True) == snap, "the parent (and its tracker state) is read-only"
    assert ok["origin"] == "scenario:scn-nvda" and ok["orderFree"] is True


def test_r2_target_provenance_the_stop_cap_and_the_one_child_limit():
    bars = rq.bars_upto(STRUCT, ms(9, 46))
    low_rr = rq.build_child(parent=_parent(), bars=bars, thresholds=T)
    assert low_rr["disposition"] == "refused" and "R2" in low_rr["reason"] and low_rr["gate"]["min"] == 3.0, "222 from 219.70 with a stop under 217.90 is ~1.2R - refused, threshold untouched"
    good = rq.build_child(parent=_parent(sourceTargets=[222.0, 226.0, 232.0]), bars=bars, thresholds=T)
    assert good["disposition"] == "requalification_eligible" and good["trigger"]["kind"] == "breakout" and good["trigger"]["origin"] == "scenario:scn-nvda"
    assert [x["basis"] for x in good["trigger"]["targets"]] == ["author"] * 3
    none = rq.build_child(parent=_parent(sourceTargets=[219.0]), bars=bars, thresholds=T)
    assert none["disposition"] == "held_for_missing_evidence" and "none invented" in none["reason"]
    again = rq.build_child(parent=_parent(sourceTargets=[222.0, 226.0, 232.0]), bars=bars, thresholds=T, existing_children=[good["childId"]])
    assert again["disposition"] == "refused" and again["reason"] == "one_requalified_candidate_per_branch_per_session" and again["childId"] == good["childId"]
    assert rq.build_child(parent=_parent(invalidatedStatus="waiting"), bars=bars, thresholds=T)["reason"] == "parent_not_invalidated"


def test_the_source_horizon_is_not_extended_and_the_future_cannot_change_the_child():
    late = _path([219.0, 218.6] + [218.5] * 130 + [218.4, 218.3, 218.2, 218.0, 218.3, 218.6, 218.9, 219.2, 219.4, 219.6, 219.4, 219.2, 219.1, 219.0])
    out = rq.build_child(parent=_parent(sourceTargets=[222.0, 226.0, 232.0]), bars=late, thresholds=T)
    assert out["disposition"] == "expired" and "not extended" in out["reason"], "NVDA's afternoon recovery is outside the morning idea"
    base = rq.build_child(parent=_parent(sourceTargets=[222.0, 226.0, 232.0]), bars=rq.bars_upto(STRUCT, ms(9, 46)), thresholds=T)
    future = STRUCT + _path([223.0, 226.5, 232.5], start=(9, 49))
    same = rq.build_child(parent=_parent(sourceTargets=[222.0, 226.0, 232.0]), bars=rq.bars_upto(future, ms(9, 46)), thresholds=T)
    assert same["geometry"] == base["geometry"] and same["disposition"] == base["disposition"]


def test_requalify_wraps_a_real_scenario_without_touching_the_baseline():
    p = _payload(AUTHOR); nvda = _scn(p, "NVDA")
    state = {"status": "invalidated", "ts": ms(9, 31), "entry": 220.2367}
    child = scp.requalify(scenario=nvda, payload=p, baseline_trigger_state=state, bars=STRUCT, session=SESSION, thresholds=T, upto_ts=ms(9, 46))
    assert child["variant"] == "requalification" and child["parentScenarioId"] == nvda["scenarioId"] and child["disposition"] == "refused" and "R2" in child["reason"]
    assert state == {"status": "invalidated", "ts": ms(9, 31), "entry": 220.2367}
    row = scp.table_row(child, baseline={"k1": "invalidated 09:31", "k2": "invalidated 09:31"})
    assert row["disposition"] in scp.DISPOSITIONS and row["orderFree"] is True and row["baseline"]["k2"].startswith("invalidated")


def test_exclusion_diagnostics_report_cost_and_benefit_and_change_nothing():
    quiet_break = [bar(9, 30, 99.5, 99.7, 99.4, 99.6), bar(9, 31, 99.6, 99.8, 99.5, 99.7), bar(9, 32, 99.7, 99.9, 99.6, 99.8), bar(9, 33, 99.8, 100.4, 99.8, 100.3, 90_000),
                   bar(9, 34, 100.3, 100.6, 100.2, 100.5, 90_000), bar(9, 35, 100.5, 100.9, 100.4, 100.8, 90_000), bar(9, 36, 100.8, 101.0, 100.7, 100.9, 90_000)]
    as_is = scp.exclusion_diagnostic("MU volume skip", TRIG, quiet_break, thresholds=T, profile=PROFILE, prev_close=99.5)
    assert as_is["status"] != "fired", "the production volume rule still excludes it"
    assert "HINDSIGHT" in as_is["label"] and T.volume_spike_mult > 0, "the production thresholds object is untouched"
