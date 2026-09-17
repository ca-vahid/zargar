"""Pure tests for the EM preparation ablation tool (2026-09-17 EOD review, package C step 1): veto classification order,
the exception features (unknown never fails), and the offline pre-open mirror agreeing with the live predicates."""
from zargar.technique.rulebook import Thresholds
from zargar.tools.em_prep_ablation import (RR_TP3_MIN, classify_veto, exception_pass, plan_features, preopen_judgement,
                                            trigger_features)


def _trig(tid, kind, direction, entry, stop, targets, *, valid=True, grade="B", touches=12, basis="next_resistance", rr3=None):
    return {"id": tid, "kind": kind, "direction": direction, "valid": valid, "levelPrice": entry,
            "entry": {"price": entry, "basis": "at_level"}, "stop": {"price": stop},
            "targets": [{"price": p, "basis": basis} for p in targets], "riskReward": 3.5, "riskRewardTp3": rr3,
            "assessment": {"grade": grade, "score": 70}, "level": {"price": entry, "touches": touches}}


def test_provenance_vetoes_are_classified_before_the_generic_rr_pattern():
    assert classify_veto("k1 breakout @ 148.34 - REJECTED: the 4.37 R:R is manufactured. The targets are the 2/4/6% pct-ladder")[0] == "target_provenance"
    assert classify_veto("b1 bounce @ 71.58 - REJECTED: 71.58 is not in the FACTS KEY LEVELS list; R2 would pass")[0] == "level_provenance"
    assert classify_veto("r2 reject @ 275.54 - REJECTED despite R:R 4.05: the level sits 8.14 (3.0%) above last close")[0] == "level_distance"
    assert classify_veto("R3.1 1m volume is 0.49x the time-of-day baseline (belowFloor) - no setup") == ("volume_floor", "already_encoded_at_fire")
    assert classify_veto("b1 bounce @ 77.76 - R2: reward:risk 1.36 to TP3 is below the 3.0 gate")[0] == "rr_to_tp3"
    assert classify_veto("the chart is a mess") == ("unstructured", "unstructured")
    assert classify_veto("MR2 form") == ("unstructured", "unstructured"), "R2 needs word boundaries"


def test_exception_features_never_fail_on_unknowns_and_fail_on_known_breaches():
    ok, fails = exception_pass({"valid": True, "rrTp3": None, "touches": None, "targetsAnchored": None})
    assert ok and fails == []
    ok, fails = exception_pass({"valid": True, "rrTp3": RR_TP3_MIN - 0.01, "touches": 1, "targetsAnchored": False})
    assert not ok and fails == ["rr_to_tp3", "level_provenance", "target_provenance"]


def test_trigger_features_read_the_triggers_own_level_and_bases():
    plan = {"lastClose": 100.0, "levels": [{"price": 99.9, "touches": 1}]}      # a nearby one-touch level must NOT be picked
    f = trigger_features(_trig("b1", "bounce", "long", 100.0, 99.0, [101.0, 102.0, 103.0], touches=31, basis="pct_ladder"), plan)
    assert f["touches"] == 31 and f["targetsAnchored"] is False and f["rrTp3"] == 3.0 and f["levelDistancePct"] == 0.0
    assert plan_features({"triggers": []}) == {"valid": False}
    best = plan_features({"lastClose": 100.0, "triggers": [_trig("b1", "bounce", "long", 100.0, 99.0, [101.0, 102.0, 103.0], valid=False),
                                                           _trig("d1", "breakdown", "short", 98.0, 99.0, [97.0, 96.0, 95.0])]})
    assert best["trigger"] == "d1", "only VALID triggers are arming candidates"


def test_preopen_mirror_matches_the_live_predicates():
    t = Thresholds()
    plan = {"lastClose": 100.0, "triggers": [_trig("b1", "bounce", "long", 100.0, 99.0, [101.0, 102.0, 103.0]),
                                             _trig("k1", "breakout", "long", 104.0, 103.0, [105.0, 106.0, 107.0])]}
    # pre-market 100.5: the bounce waits above its level (ok), the breakout has not been passed (ok) -> no replan
    v = preopen_judgement(plan, 100.5, t)
    assert {r["trigger"]: r["verdict"] for r in v["rows"]} == {"b1": "ok", "k1": "ok"} and v["replan"] is False
    # pre-market 99.2: at/below the bounce's entry (gapped past it) but not through its stop; the breakout is still
    # 4.8 below its level with a 0.8 gap < gap_void_r x risk -> one alive, no replan
    v = preopen_judgement(plan, 99.2, t)
    assert {r["trigger"]: r["verdict"] for r in v["rows"]} == {"b1": "gapped_past", "k1": "ok"} and v["replan"] is False
    # pre-market 98.5: through the bounce's stop AND a 1.5 gap voids the breakout (gap_void_r 1.0 x risk 1.0) -> replan
    v = preopen_judgement(plan, 98.5, t)
    assert {r["trigger"]: r["verdict"] for r in v["rows"]} == {"b1": "gapped_through", "k1": "gap_void"} and v["replan"] is True
    # pre-market 104.5: past the breakout, and the bounce is void (gap > gap_void_r x risk of 1.0) -> every trigger dead -> replan
    v = preopen_judgement(plan, 104.5, t)
    verdicts = {r["trigger"]: r["verdict"] for r in v["rows"]}
    assert verdicts["k1"] == "gapped_past" and verdicts["b1"] == "gap_void" and v["replan"] is True
    # short mirror (FIX-04 predicates): a reject at 100 with its stop at 101 - a print above the stop is gapped_through, a
    # print between the level and the stop is gapped_past (price is already beyond the level), a print BELOW the level
    # that can still rise into it is ok
    short = {"lastClose": 100.0, "triggers": [_trig("r1", "reject", "short", 100.0, 101.0, [99.0, 98.0, 97.0])]}
    assert preopen_judgement(short, 101.5, t)["rows"][0]["verdict"] == "gapped_through"
    assert preopen_judgement(short, 100.5, t)["rows"][0]["verdict"] == "gapped_past"
    assert preopen_judgement(short, 99.5, t)["rows"][0]["verdict"] == "ok"
    # invalid triggers are never judged
    assert preopen_judgement({"lastClose": 100.0, "triggers": [_trig("b1", "bounce", "long", 100.0, 99.0, [101.0], valid=False)]}, 90.0, t)["rows"] == []
