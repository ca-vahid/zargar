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
    pg = done["pricingGates"]
    assert pg["overall"] == "unknown" and {v["status"] for v in pg["gates"].values()} == {"unknown"} and pg["orderFree"] is True, "no evidence supplied = unknown, never a pass"
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
    assert ok["structure"]["break"]["price"] == 219.7 and ok["structure"]["protect"]["price"] == 217.9 and ok["structure"]["confirmedBarTs"] == ms(9, 45)
    assert ok["structure"]["confirmedCloseTs"] == ms(9, 46) == ok["structure"]["confirmedTs"], "a bar-START timestamp is not its availability time: the pivot is knowable at the confirming bar's CLOSE"
    assert ok["eligibleFromTs"] == ms(9, 46) and ok["parentState"]["invalidatedKnownAtTs"] == ok["parentState"]["invalidatedTs"] + 60_000 and ok["geometry"]["entry"] == 219.7 and ok["geometry"]["entry"] != parent["oldEntry"]
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


def test_a_requalified_candidate_never_sees_bars_from_before_its_own_confirmation():
    child = {"version": rq.VERSION, "variant": "requalification", "candidateId": "rq1-x", "origin": "scenario:s1", "orderFree": True, "symbol": "X", "direction": "long",
             "disposition": "requalification_eligible", "eligibleFromTs": ms(9, 40), "expiresTs": ms(11, 30), "source": {}, "trigger": copy.deepcopy(TRIG)}
    gap_open = [bar(9, 30, 103.0, 103.5, 102.8, 103.2)] + [bar(9, 31 + i, 103.0, 103.2, 102.9, 103.0) for i in range(9)]      # an opening print far through the level
    late = [Bar("X", "1m", ms(9, 41) + i * 60000, *v) for i, v in enumerate([(99.6, 99.8, 99.5, 99.7, 100_000), (99.7, 99.9, 99.6, 99.8, 100_000), (99.8, 100.4, 99.8, 100.3, 400_000),
                                                                             (100.3, 100.6, 100.2, 100.5, 300_000), (100.5, 100.9, 100.4, 100.8, 300_000), (100.8, 101.0, 100.7, 100.9, 100_000)])]
    out = scp.evaluate(child, gap_open + late, thresholds=T, profile=PROFILE, prev_close=99.5)
    assert out["disposition"] == "triggered" and out["firedTs"] == ms(9, 46) and "born after the open" in out["gapRule"], "the 09:30 gap belongs to the parent, not to a structure born at 09:40"
    assert out["barsConsumed"] == 6


# ------------------------------------------------------------------------------ candidate-pricing-v1 (IR-05)
def _constraints(at, **kw):
    ok = [{"name": n, "passed": True, "detail": ""} for n in ("kill_switch", "book_halt", "book_pause", "quote_fresh", "cash_available", "option_premium_cap",
                                                              "max_position_notional", "max_gross_exposure", "daily_loss_limit")]
    return {"atMs": at, "riskVerdict": {"passed": True, "qty": 1.0, "checks": ok}, "tradingHalted": False, "symbolOpenOrWorking": 0, "maxOpenTrades": 1,
            "reservedPremium": 0.0, **kw}


def _evidence(at, *, underlier=100.92, bid=2.95, ask=3.00, size=20, equity=10_000.0, cash=9_000.0, contract=True, age=400, constraints="ok", csym="X260925C00101000",
              cmeta=None):
    ev = {"underlier": {"symbol": "X", "bid": underlier - 0.02, "ask": underlier, "last": underlier, "quoteTs": at - age, "lastTs": at - age, "receivedTs": at - 50,
                        "source": "feed:HybridQuoteFeed", "halted": False},
          "contract": None, "contractQuote": None, "equity": equity, "cash": cash}
    if constraints is not None:
        ev["constraints"] = _constraints(at) if constraints == "ok" else constraints
    if contract:
        sym = csym
        ev["contract"] = {"symbol": sym, "strike": 101.0, "expiry": "2026-09-25", "optionType": "call", "delta": 0.45, **(cmeta or {})}
        ev["contractQuote"] = {"symbol": sym, "bid": bid, "ask": ask, "last": ask, "bidSize": size, "askSize": size, "sizeUnit": "contracts", "source": "opra", "quoteTs": at - age, "receivedTs": at - 50}
    return ev


def _triggered():
    c = _waiting()
    c["geometry"] = {"entry": 100.0, "stop": 99.0, "targets": [101.5, 107.0, 110.0]}
    c["trigger"]["targets"] = [{"price": 101.5}, {"price": 107.0}, {"price": 110.0}]
    return c


def test_complete_contemporaneous_evidence_produces_evaluated_gates_and_the_identical_case_without_it_stays_unknown():
    at = ms(9, 37) + 5_000
    done = scp.evaluate(_triggered(), MORNING, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 38),
                        pricing_evidence=lambda c: {"evidence": _evidence(at), "atMs": at})
    pg = done["pricingGates"]
    assert done["disposition"] == "triggered" and pg["version"] == "candidate-pricing-v2" and pg["evaluatedAt"] == at and pg["orderFree"] is True
    g = pg["gates"]
    assert g["contract"]["status"] == "pass" and g["quote"]["status"] == "pass" and g["spread"] == {"status": "pass", "spreadPct": 1.68, "max": 10.0}
    assert g["sizing"]["status"] == "pass" and g["sizing"]["contracts"] == 1 and g["budget"]["status"] == "pass" and g["budget"]["premium"] == 300.0 and g["budget"]["freeCash"] == 9000.0
    assert g["firstSaleR"]["status"] == "pass" and g["firstSaleR"]["rung"] == "tp2-full" and g["firstSaleR"]["boundBasis"] == "ask" and g["firstSaleR"]["admissionEntry"] == 100.92
    assert g["chase"]["status"] == "pass" and g["chase"]["version"] == "candidate-chase-v1" and g["chase"]["boundBasis"] == "ask" and g["chase"]["ranR"] < 0.25
    assert g["portfolio"]["status"] == "pass" and "daily_loss_limit" in g["portfolio"]["riskChecks"]
    assert pg["overall"] == "feasible" and pg["completeness"] == "complete" and pg["missing"] == [] and set(g) == set(scp.PRICING_GATES)
    assert pg["productionEquivalent"] is False and len(pg["deliberateDifferences"]) == 2, "a research stage says where it differs from production"
    missing = scp.evaluate(_triggered(), MORNING, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 38))
    assert missing["disposition"] == "triggered" and missing["pricingGates"]["overall"] == "unknown"
    assert {v["status"] for v in missing["pricingGates"]["gates"].values()} == {"unknown"}
    assert {k: done[k] for k in ("disposition", "firedTs", "fillProxy")} == {k: missing[k] for k in ("disposition", "firedTs", "fillProxy")}, "evidence never changes the trigger itself"


def test_supplied_evidence_is_really_judged_wide_spread_run_away_budget_and_stale_inputs():
    at = ms(9, 37) + 5_000

    def run(**kw):
        return scp.evaluate(_triggered(), MORNING, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 38),
                            pricing_evidence=lambda c: {"evidence": _evidence(at, **kw), "atMs": at})["pricingGates"]
    wide = run(bid=2.40, ask=3.00)
    assert wide["gates"]["spread"]["status"] == "fail" and wide["overall"] == "infeasible"
    ran = run(underlier=103.0)
    assert ran["gates"]["firstSaleR"]["status"] == "fail" and ran["gates"]["firstSaleR"]["rAdmission"] < 3 and ran["gates"]["chase"]["status"] == "fail" and ran["overall"] == "infeasible"
    small = run(equity=2_000.0)
    assert small["gates"]["sizing"]["status"] == "fail" and small["gates"]["sizing"]["contracts"] == 0 and small["gates"]["budget"]["status"] == "unknown"
    poor = run(cash=100.0)
    assert poor["gates"]["budget"]["status"] == "fail" and poor["gates"]["budget"]["failed"] == ["cash on hand net of existing entry reservations"]
    stale = run(age=20_000)
    assert stale["gates"]["quote"]["status"] == "fail" and "stale_quote" in stale["gates"]["quote"]["problems"] and stale["gates"]["firstSaleR"]["status"] == "unknown" and stale["gates"]["chase"]["status"] == "unknown"
    nocontract = run(contract=False)
    assert nocontract["gates"]["contract"]["status"] == "unknown" and nocontract["gates"]["firstSaleR"]["status"] == "unknown" and nocontract["overall"] == "unknown" and nocontract["completeness"] == "partial", "no contract = no quantity = unknown"
    late = scp.evaluate(_triggered(), MORNING, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 50),
                        pricing_evidence=lambda c: {"evidence": _evidence(ms(9, 45)), "atMs": ms(9, 45)})["pricingGates"]
    assert late["overall"] == "unknown" and "not contemporaneous" in late["why"], "evidence gathered long after the trigger is never back-filled"


def test_the_pricing_stage_cannot_arm_or_order_and_the_research_fetch_is_separately_configured():
    import inspect
    from zargar.settings_service import DEFAULTS
    from zargar.technique import source_candidates_runtime as rt_mod
    assert "orders.place" not in inspect.getsource(scp) and "arm_plan" not in inspect.getsource(scp) and "arm_plan" not in inspect.getsource(rt_mod)
    assert DEFAULTS["techniques.enhanced_market.source_candidates_chain_fetch"] is False and DEFAULTS["techniques.enhanced_market.source_candidates_observe"] is False
    g = inspect.getsource(rt_mod.gather_evidence)
    assert 'cboe_priority("background")' in g and "wait_for" in g and "CHAIN_KNOB" in g



# ------------------------------------------------------------------------------ candidate-pricing-v2 (R2-02)
def _price(at=None, **kw):
    at = at or (ms(9, 37) + 5_000)
    return scp.evaluate(_triggered(), MORNING, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 38),
                        pricing_evidence=lambda c: {"evidence": _evidence(at, **kw), "atMs": at})["pricingGates"]


def test_r2_02_a_contract_is_bound_to_its_candidate_by_identity_wrong_underlying_expired_and_conflicts_fail():
    """The reviewers' reproduction: underlying WRONG, expiry 2026-01-01, a fresh MATCHING quote, enough cash - was `feasible`."""
    wrong = _price(csym="WRONG260101C00101000", cmeta={"expiry": "2026-01-01"})
    why = wrong["gates"]["contract"]["why"]
    assert wrong["gates"]["contract"]["status"] == "fail" and "wrong underlying" in why and "expired contract" in why and wrong["overall"] == "infeasible"
    assert wrong["gates"]["quote"]["status"] == "unknown", "a matching quote symbol alone binds nothing: nothing downstream is evaluated on a foreign contract"
    assert "wrong right" in _price(csym="X260925P00101000", cmeta={"optionType": "put"})["gates"]["contract"]["why"]
    assert "conflicting metadata: optionType" in _price(cmeta={"optionType": "put"})["gates"]["contract"]["why"]
    assert "conflicting metadata: expiry" in _price(cmeta={"expiry": "2026-10-02"})["gates"]["contract"]["why"]
    assert "conflicting metadata: strike" in _price(cmeta={"strike": 105.0})["gates"]["contract"]["why"]
    norm = _price(cmeta={"optionType": None})
    assert norm["gates"]["contract"]["status"] == "pass" and norm["gates"]["contract"]["optionType"] == "call", "a missing right in the metadata is READ from the OCC identity, never assumed"
    unk = _price(csym="X1260925C00101000")
    assert unk["gates"]["contract"]["status"] == "unknown" and unk["overall"] == "unknown", "a non-standard symbol: right, expiry and multiplier are unknown"
    zero = int(dt.datetime(2026, 9, 25, 10, 45, tzinfo=NY).timestamp() * 1000)
    c = {**_triggered(), "disposition": "triggered", "firedTs": zero - 65_000, "fillProxy": 100.9}
    assert "0DTE after the production cut-off" in scp.pricing_gates(c, _evidence(zero), now_ms=zero)["gates"]["contract"]["why"]


def test_r2_02_adequate_r_never_substitutes_for_a_chase_pass():
    """The reviewers' reproduction: entry 100, ask 105, distant targets -> R stays high. It was `noChase: pass`."""
    at = ms(9, 37) + 5_000
    c = {**_triggered(), "disposition": "triggered", "firedTs": ms(9, 36), "fillProxy": 100.0, "geometry": {"entry": 100.0, "stop": 99.0, "targets": [120.0, 150.0, 160.0]}}
    pg = scp.pricing_gates(c, _evidence(at, underlier=105.0), now_ms=at)
    assert pg["gates"]["firstSaleR"]["status"] == "pass" and pg["gates"]["firstSaleR"]["rAdmission"] >= 3, "R is still adequate at the run-away price"
    assert pg["gates"]["chase"]["status"] == "fail" and pg["gates"]["chase"]["ranR"] == 5.0 and pg["overall"] == "infeasible", "and the chase gate fails all the same"
    short = {**c, "direction": "short", "geometry": {"entry": 100.0, "stop": 101.0, "targets": [80.0, 60.0, 50.0]}}
    ev = _evidence(at, underlier=95.0, csym="X260925P00099000", cmeta={"optionType": "put", "strike": 99.0})
    assert scp.pricing_gates(short, ev, now_ms=at)["gates"]["chase"]["status"] == "fail", "mirrored for puts: the BID ran below the entry"
    only_print = _evidence(at)
    only_print["underlier"].update({"bid": None, "ask": None})
    g = scp.pricing_gates(c, only_print, now_ms=at)["gates"]["chase"]
    assert g["status"] == "unknown" and "not an executable quote" in g["why"], "a print is never called an executable quote"


def test_r2_02_portfolio_constraints_decide_feasibility_and_missing_constraints_are_partial_never_feasible():
    at = ms(9, 37) + 5_000
    assert _price()["overall"] == "feasible"
    none = _price(constraints=None)
    assert none["gates"]["portfolio"]["status"] == "unknown" and none["overall"] == "unknown" and none["completeness"] == "partial" and none["missing"] == ["budget", "portfolio"]
    loss = _constraints(at, riskVerdict={"passed": False, "qty": 1.0, "checks": [{"name": "daily_loss_limit", "passed": False, "detail": "daily P&L -3.20% breaches -3.0% halt"}]})
    out = _price(constraints=loss)
    assert out["gates"]["portfolio"]["status"] == "fail" and "daily_loss_limit" in out["gates"]["portfolio"]["why"] and out["overall"] == "infeasible", "an exhausted day budget"
    full = _price(constraints=_constraints(at, symbolOpenOrWorking=1))
    assert full["gates"]["portfolio"]["status"] == "fail" and "no open-position slot" in full["gates"]["portfolio"]["why"]
    expo = _constraints(at, riskVerdict={"passed": False, "qty": 1.0, "checks": [{"name": "max_gross_exposure", "passed": False, "detail": "gross 104% > 100%"}]})
    assert "max_gross_exposure" in _price(constraints=expo)["gates"]["portfolio"]["why"]
    assert _price(constraints=_constraints(at, tradingHalted="book halted: daily loss"))["gates"]["portfolio"]["status"] == "fail"
    res = _price(cash=400.0, constraints=_constraints(at, reservedPremium=250.0))
    assert res["gates"]["budget"]["status"] == "fail" and res["gates"]["budget"]["freeCash"] == 150.0, "cash already promised to a working entry is not spendable twice"
    old = _price(constraints=_constraints(at - 60_000))
    assert old["gates"]["portfolio"]["status"] == "unknown" and "fresh snapshot" in old["gates"]["portfolio"]["missing"], "constraints are snapshotted causally, not reused"
    other_qty = _price(constraints=_constraints(at, riskVerdict={"passed": True, "qty": 3.0, "checks": []}))
    assert other_qty["gates"]["portfolio"]["status"] == "unknown", "a verdict for a different quantity is not evidence for this one"


# ------------------------------------------------------------------------------ final-completion goal section 3 (pure boundaries)
def test_the_plan_at_birth_is_used_never_the_latest_plan_of_the_symbol():
    iso = lambda h, m: dt.datetime(2026, 9, 18, h, m, tzinfo=NY).isoformat()               # noqa: E731
    overnight, ingest, replan = ({"runId": r, "createdAt": iso(*t)} for r, t in (("overnight", (8, 0)), ("ingest", (9, 22)), ("replan", (10, 15))))
    usable = ms(9, 20)
    assert scp.birth_plan([overnight, ingest, replan], usable, ms(11, 0))[0]["runId"] == "overnight", "the newest plan AT the source's usable time"
    assert scp.birth_plan([ingest, replan], usable, ms(11, 0)) == (ingest, "the first plan built after the source became usable"), "a later same-session re-plan never reinterprets the idea"
    assert scp.birth_plan([replan], usable, ms(9, 40)) == (None, "no saved plan existed yet"), "a plan built after the evaluation time does not exist yet"
    assert scp.birth_plan([replan, overnight], None, None)[0]["runId"] == "overnight"


def test_irregular_bars_are_held_and_a_missing_minute_inside_the_structure_window_holds_the_child():
    assert rq.bars_integrity(STRUCT) == {**rq.bars_integrity(STRUCT), "ok": True, "missingMinutes": 0}
    dup = STRUCT[:5] + [STRUCT[4]] + STRUCT[5:]
    ooo = STRUCT[:5] + [STRUCT[6], STRUCT[5]] + STRUCT[7:]
    for bad, key in ((dup, "duplicates"), (ooo, "outOfOrder")):
        integ = rq.bars_integrity(bad)
        assert integ["ok"] is False and integ[key] >= 1
        held = rq.build_child(parent=_parent(), bars=bad, thresholds=T)
        assert held["disposition"] == "held_for_missing_evidence" and "not a clean minute series" in held["reason"] and "trigger" not in held
    ok = rq.build_child(parent=_parent(), bars=STRUCT, thresholds=T)
    assert ok["disposition"] in ("requalification_eligible", "refused", "held_for_missing_evidence") and ok.get("structure")
    lo, hi = ok["structure"]["protect"]["index"], ok["structure"]["confirmedIndex"]
    holed = STRUCT[:lo + 1] + STRUCT[lo + 2:]                                              # one minute vanishes between the protecting pivot and its confirmation
    child = rq.build_child(parent=_parent(), bars=holed, thresholds=T)
    assert rq.bars_integrity(holed)["missingMinutes"] == 1
    assert child["disposition"] == "held_for_missing_evidence" and "missing inside the structure window" in child["reason"], "pivots across a hole are not trusted"
    assert hi > lo


def test_a_shortened_session_and_a_holiday_use_the_exchange_calendar():
    close, why = scp.source_expiry_ts("2026-11-27", "0dte")                                # the day after Thanksgiving closes at 13:00 ET
    assert dt.datetime.fromtimestamp(close / 1000, NY).strftime("%H:%M") == "13:00" and why == "source-session-expiry-v1"
    morning, _ = scp.source_expiry_ts("2026-11-27", None)
    assert dt.datetime.fromtimestamp(morning / 1000, NY).strftime("%H:%M") == "11:30"
    assert scp.source_expiry_ts("2026-11-26", "0dte")[0] is None and "not a trading session" in scp.source_expiry_ts("2026-11-26", "0dte")[1]
    assert dt.datetime.fromtimestamp(scp.source_expiry_ts("2026-09-18", "0dte")[0] / 1000, NY).strftime("%H:%M") == "16:00"


def test_one_child_per_branch_survives_a_source_edit_and_a_terminal_candidate_is_never_re_decided():
    p = _parent(branchKey="br1-abc")
    assert rq.build_child(parent=p, bars=STRUCT, thresholds=T, existing_children={"br1-abc"})["reason"] == "one_requalified_candidate_per_branch_per_session", (
        "an edit makes new scenario ids - it does not make a second branch")
    # a stored TRIGGERED candidate: a later pass replays the bars differently (a corrected bar) - the first observation stands
    first = scp.evaluate(_waiting(), MORNING, thresholds=T, profile=PROFILE, prev_close=99.5, upto_ts=ms(9, 38))
    assert first["disposition"] == "triggered"
    stored = {**first, "definition": scp.definition_of(_waiting()), "pricingGates": {"overall": "unknown", "evaluatedAt": None}}
    same = scp._resume(stored, MORNING, ctx=(T, PROFILE, 99.5), upto_ts=ms(9, 45), pricing_evidence=None, pricing_rules=None)
    assert same["disposition"] == "triggered" and same["firedTs"] == first["firedTs"] and same["fillProxy"] == first["fillProxy"] and same["frozen"] == "terminal"
    assert "replayDisagreement" not in same and same["pricingGates"] == stored["pricingGates"], "pricing decided at the trigger is never recomputed on later evidence"
    quiet = [Bar("X", "1m", b.ts, 99.5, 99.6, 99.4, 99.5, 100_000) for b in MORNING]          # the same minutes, now WITHOUT the break
    changed = scp._resume(stored, quiet, ctx=(T, PROFILE, 99.5), upto_ts=ms(9, 45), pricing_evidence=None, pricing_rules=None)
    assert changed["disposition"] == "triggered" and changed["firedTs"] == first["firedTs"] and changed["replayDisagreement"]["replayFiredTs"] is None
    # a born, not yet terminal candidate is continued from its FROZEN definition, not from a rebuilt one
    waiting = {**_waiting(), "definition": scp.definition_of(_waiting()), "disposition": "waiting"}
    cont = scp._resume(waiting, MORNING, ctx=(T, PROFILE, 99.5), upto_ts=ms(9, 38), pricing_evidence=None, pricing_rules=None)
    assert cont["disposition"] == "triggered" and cont["definition"] == waiting["definition"] and cont["trigger"] == _waiting()["trigger"]
