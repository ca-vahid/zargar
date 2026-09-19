"""em-prep-policy-v1 + conditional-review-v1 + model-costs-v1 (integrated plan B, 2026-09-18). Acceptance rows
"Conditional planning", "Deterministic prep" and "Authority". Fixture = the REAL overnight model reviews of the 09-18
session (NVDA / META / MRNA / MU / AMD promote runs, captured read-only). Pure + one Postgres case for the resume
ledger. Zero model calls anywhere in this file."""
import copy
import inspect
import json
import os
from types import SimpleNamespace

import pytest

from zargar.technique import model_costs as mc
from zargar.technique import preparation_policy as pp

FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "em_overnight_reviews_2026_09_18.json"), encoding="utf-8"))
BASE = {"preparationPolicy": "baseline", "gradeFloor": "B", "conditionalReviewFix": "report"}
DET = {**BASE, "preparationPolicy": "deterministic"}


def _t(tid, kind="breakout", valid=True, grade="B", level=100.0, reasons=None):
    return {"id": tid, "kind": kind, "direction": ("short" if kind in ("reject", "breakdown") else "long"), "levelPrice": level, "valid": valid,
            "riskReward": 3.4, "noTradeReasons": reasons or [], "assessment": ({"grade": grade} if grade else {}),
            "stop": {"price": level * 0.99}, "targets": [{"price": level * 1.02}, {"price": level * 1.04}]}


def _plan(*trigs, sym="NVDA"):
    return {"symbol": sym, "planFor": "2026-09-18", "triggers": list(trigs)}


# ------------------------------------------------------------------------------------------- conditional planning
def test_a_not_yet_triggered_plan_can_be_eligible_once_the_invalid_reason_is_removed():
    a = {"verdict": "no_setup", "noTradeReasons": ["k1 breakout @ 100.00 — REJECTED: no breakout has been observed or confirmed on the chart (T3.3a-c)."]}
    rep = pp.decide(symbol="NVDA", plan=_plan(_t("k1")), analysis=a, policy=BASE, origin="batch")
    assert rep["conditionalFix"] == {"mode": "report", "rescued": ["k1"], "applied": False}
    assert rep["disposition"] == "refused" and rep["triggers"][0]["basis"] == "model_reason_invalid__rules_pass", "report mode lists, never arms"
    app = pp.decide(symbol="NVDA", plan=_plan(_t("k1")), analysis=a, policy={**BASE, "conditionalReviewFix": "apply"}, origin="batch")
    assert app["disposition"] == "eligible" and app["eligibleTriggers"] == ["k1"] and app["triggers"][0]["modelReview"]["veto"] == "invalid_only"
    off = pp.decide(symbol="NVDA", plan=_plan(_t("k1")), analysis={"verdict": "setup"}, policy=BASE, origin="batch")
    assert off["disposition"] == "eligible" and off["triggers"][0]["basis"] == "model_setup", "the baseline path is what it was"


def test_removing_one_bad_reason_never_approves_a_plan_whose_rules_fail():
    a = {"verdict": "no_setup", "noTradeReasons": ["k1 breakout @ 100.00 — REJECTED: the level has not been touched this session."]}
    for trig in (_t("k1", grade="C"), _t("k1", grade=None), {**_t("k1"), "targets": []}):
        d = pp.decide(symbol="X", plan=_plan(trig), analysis=a, policy={**BASE, "conditionalReviewFix": "apply"}, origin="batch")
        assert d["disposition"] == "refused" and d["conditionalFix"]["rescued"] == [] and d["triggers"][0]["basis"] == "model_reason_invalid__rules_fail"
    genuine = _t("k1", valid=False, reasons=["R2 reward:risk 2.97 to TP3 below 3.0"])
    d = pp.decide(symbol="AMD", plan=_plan(genuine), analysis=a, policy={**BASE, "conditionalReviewFix": "apply"}, origin="batch")
    assert d["disposition"] == "refused", "a genuine geometry failure still refuses"
    assert pp.decide(symbol="AMD", plan=_plan(genuine), analysis=None, policy=DET, origin="ingest")["disposition"] == "refused"


def test_a_reason_naming_one_trigger_never_vetoes_another_without_a_plan_level_reason():
    a = {"verdict": "no_setup", "noTradeReasons": ["k1 breakout @ 100.00 — REJECTED: the target is a manufactured pct-ladder with nothing overhead (T4.4).",
                                                   "k2 breakout @ 104.00 — REJECTED: no breakout there has been observed (T3.3a-c)."]}
    d = pp.decide(symbol="NVDA", plan=_plan(_t("k1"), _t("k2", level=104.0)), analysis=a, policy={**BASE, "conditionalReviewFix": "apply"}, origin="batch")
    rows = {r["id"]: r for r in d["triggers"]}
    assert rows["k1"]["eligible"] is False and rows["k1"]["modelReview"]["veto"] == "substantive"
    assert rows["k2"]["eligible"] is True and d["eligibleTriggers"] == ["k2"], "k1's objection does not reach k2; the whole plan is NOT auto-approved"
    a2 = {"verdict": "no_setup", "noTradeReasons": a["noTradeReasons"] + ["R3.2 — 1h, 30m and 1m structure are all sideways: chop, not structure."]}
    d2 = pp.decide(symbol="NVDA", plan=_plan(_t("k1"), _t("k2", level=104.0)), analysis=a2, policy={**BASE, "conditionalReviewFix": "apply"}, origin="batch")
    assert d2["disposition"] == "refused" and d2["planLevelModelReasons"][0]["scope"] == "plan", "an explicit plan-level objection reaches every trigger"


def test_the_real_09_18_reviews_keep_their_substantive_objections():
    for sym in ("NVDA", "META", "MRNA", "MU"):
        x = FX[sym]
        d = pp.decide(symbol=sym, plan=x["plan"], analysis=x["analysis"], policy={**BASE, "conditionalReviewFix": "apply"}, origin="batch")
        assert d["disposition"] == "refused" and d["conditionalFix"]["rescued"] == [], f"{sym}: the invalid clause was never the ONLY objection"
    k1 = next(r for r in pp.decide(symbol="NVDA", plan=FX["NVDA"]["plan"], analysis=FX["NVDA"]["analysis"], policy=BASE, origin="batch")["triggers"] if r["id"] == "k1")
    disc = [c for row in k1["modelReview"]["kept"] for c in row["discardedClauses"]]
    assert any("no breakout has been observed" in c for c in disc), "the invalid clause is identified and recorded"
    assert any("fakeout tells" in c for row in k1["modelReview"]["kept"] for c in row["keptClauses"]), "the independent objection is preserved"


def test_clause_classifier():
    assert pp.classify_reason("price has not reached 685.16 today") == "not_yet_triggered"
    assert pp.classify_reason("R6.3 outside the prime window") == "session_timing"
    assert pp.classify_reason("no breakout has been observed; the R:R is a manufactured pct-ladder") == "substantive"
    assert pp.classify_reason("the stop is 4.0% away, beyond the risk cap (R1)") == "substantive"
    assert pp.classify_reason("no volume surge behind the last failed break") == "substantive", "a volume objection is never the not-yet clause"


# --------------------------------------------------------------------------------------------- deterministic prep
def test_deterministic_mode_needs_no_model_and_says_the_review_is_absent():
    d = pp.decide(symbol="NVDA", plan=FX["NVDA"]["plan"], analysis=None, policy=DET, origin="batch")
    assert d["mode"] == "deterministic" and d["modelReview"] == "absent" and d["modelCalls"] == 0
    assert d["eligibleTriggers"] == ["k1", "k2", "d2"], "valid geometry + grade floor B; r2 is grade C"
    r2 = next(r for r in d["triggers"] if r["id"] == "r2")
    assert [c["name"] for c in r2["rules"] if c["outcome"] != "pass"] == ["grade_floor"]
    assert "absent" in d["explanation"] and "r2" in d["explanation"] and "grade_floor" in d["explanation"]
    src = inspect.getsource(pp)
    assert "anthropic" not in src and "await " not in src and "settings" not in src.split("def effective")[0].split('"""', 2)[2], "pure: no model, no I/O"
    base = pp.decide(symbol="NVDA", plan=FX["NVDA"]["plan"], analysis=None, policy=BASE, origin="batch")
    assert base["disposition"] == "refused" and base["triggers"][1]["basis"] == "baseline_requires_model_review", "no review is never an old approval"


def test_hashes_are_deterministic_and_a_changed_input_is_a_new_key():
    kw = dict(symbol="NVDA", session="2026-09-18", as_of=1, bars_hash="b1", source_hashes=["r2", "r1"], adjusted_data_id="d1", thresholds_hash="t1", grade_policy="B|deterministic|report")
    k = pp.causal_input_key(**kw)
    assert k == pp.causal_input_key(**{**kw, "source_hashes": ["r1", "r2"]}), "order-independent, stable"
    for change in ({"bars_hash": "b2"}, {"source_hashes": ["r1"]}, {"adjusted_data_id": "d2"}, {"thresholds_hash": "t2"}, {"grade_policy": "A|deterministic|report"},
                   {"as_of": 2}, {"session": "2026-09-21"}, {"model": "claude-opus-5"}, {"prompt_version": "p2"}, {"horizon": "swing"}):
        assert pp.causal_input_key(**{**kw, **change}) != k, change
    d1 = pp.decide(symbol="NVDA", plan=FX["NVDA"]["plan"], analysis=None, policy=DET, origin="batch")
    d2 = pp.decide(symbol="NVDA", plan=copy.deepcopy(FX["NVDA"]["plan"]), analysis=None, policy=DET, origin="ingest")
    assert d1["decisionHash"] == d2["decisionHash"] and d1["candidateKey"] == d2["candidateKey"], "the path does not change the candidate or the decision"


def test_resume_reuses_done_work_and_retries_only_failed_reads():
    items = [{"inputKey": k, "symbol": s} for k, s in (("a", "NVDA"), ("b", "META"), ("c", "MU"), ("d", "AMD"), ("e", "ARM"))]
    ledger = {"a": {"status": "done", "attempts": 1}, "b": {"status": "failed", "attempts": 1}, "c": {"status": "failed", "attempts": 3},
              "d": {"status": "failed", "attempts": 1, "retryable": False}}
    out = pp.plan_batch(items, ledger)
    assert [i["symbol"] for i in out["reuse"]] == ["NVDA"] and [i["symbol"] for i in out["run"]] == ["META", "ARM"]
    assert [i["symbol"] for i in out["skip"]] == ["MU", "AMD"] and out["run"][0]["retryOf"] == 1


def test_audit_sampler_is_stable_and_zero_by_default():
    ids = [f"cand{i}" for i in range(400)]
    assert not any(pp.audit_sampled(session="2026-09-18", candidate=c, input_key="k", quota_pct=0.0) for c in ids)
    picked = [c for c in ids if pp.audit_sampled(session="2026-09-18", candidate=c, input_key="k", quota_pct=10.0)]
    assert picked == [c for c in ids if pp.audit_sampled(session="2026-09-18", candidate=c, input_key="k", quota_pct=10.0)] and 15 <= len(picked) <= 70
    assert pp.effective(lambda k, d=None: d)["auditQuotaPct"] == 0.0


def test_defaults_are_baseline_and_em_namespaced_and_other_desks_are_untouched():
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS[pp.SETTING_MODE] == "baseline" and DEFAULTS[pp.SETTING_FIX] == "report" and DEFAULTS[pp.SETTING_AUDIT] == 0.0 and "llm.pricing_table" not in DEFAULTS and DEFAULTS["llm.rates"] == {}
    for k in ("preparation_policy", "prep_grade_floor", "conditional_review_fix", "prep_audit_quota_pct", "source_scenarios_observe", "source_candidates_observe"):
        assert [x for x in DEFAULTS if x.endswith("." + k)] == ["techniques.enhanced_market." + k]
    eff = pp.effective(lambda k, d=None: {"techniques.enhanced_market.preparation_policy": "bogus"}.get(k, d))
    assert eff["preparationPolicy"] == "baseline" and eff["invalidSetting"] == "bogus", "an invalid value is never silently a new policy"
    from zargar.execution.planrunner import PlanRunner
    assert "preparationPolicy" not in inspect.getsource(PlanRunner), "the shared runner carries no EM preparation policy"


def test_the_effective_policy_rides_the_em_preflight_and_armed_views():
    from zargar.technique.arming import PlanArmer
    s = {"techniques.enhanced_market.preparation_policy": "deterministic", "techniques.enhanced_market.first_sale_rr_gate": "enforce"}
    me = SimpleNamespace(engine=SimpleNamespace(settings=SimpleNamespace(get=lambda k, d=None: s.get(k, d))))
    me.first_sale_policy = lambda ap: PlanArmer.first_sale_policy(me, ap)
    ex = PlanArmer._em_policy_extras(me)
    assert ex["preparationPolicy"] == "deterministic" and ex["preparationPolicyVersion"] == "em-prep-policy-v1" and ex["firstSaleGate"] == "enforce"


def test_lazy_charts_in_every_deterministic_preparation_path_with_the_on_demand_endpoint_kept():
    from zargar.technique import service
    from zargar.api import routes_technique
    src = inspect.getsource(service)
    assert 'render_charts = not (mode == "plan" and not with_vision and (trigger == "preopen_replan" or _det_prep))' in src
    assert "async def technique_chart" in inspect.getsource(routes_technique), "charts stay available on demand"


# ------------------------------------------------------------------------------------------------------ authority
def test_one_owner_one_arm_per_candidate_across_batch_ingestion_and_preopen():
    plan = FX["META"]["plan"]
    ds = [pp.decide(symbol="META", plan=plan, analysis=None, policy=DET, origin=o, run_id=f"run-{o}") for o in ("batch", "ingest", "preopen_replan")]
    assert {d["owner"] for d in ds} == {"em-preparation-policy"} and len({d["candidateKey"] for d in ds}) == 1
    sel = pp.select(ds)
    assert [a["runId"] for a in sel["arm"]] == ["run-batch"] and [s["why"] for s in sel["skipped"]] == ["duplicate_of_armed_candidate"] * 2
    again = pp.select(ds, already_armed_keys={ds[0]["candidateKey"]})
    assert again["arm"] == [], "a candidate that is already armed is never armed again (restart / reuse)"
    held = pp.decide(symbol="TSLA", plan=plan, analysis=None, policy=DET, origin="ingest", source_hold=["conflict: evidence names MU"])
    assert held["disposition"] == "held_for_resolution" and held["eligibleTriggers"] == [] and pp.select([held])["arm"] == []


def test_the_ingestion_path_keeps_its_baseline_branch_and_routes_the_proposed_policy_through_the_owner():
    from zargar.technique import arming, ingest
    src = inspect.getsource(ingest.MethodIngestService.board_check)
    assert src.index('prep["preparationPolicy"] == "deterministic"') < src.index('elif self._get("ingest.auto_arm", False):'), "baseline branch intact after the policy branch"
    assert "prep_select" in src and "supersedesModelVeto" in src and "validTriggers" in src
    rp = inspect.getsource(arming.PlanArmer.build_replacement_plan)
    assert 'origin="preopen_replan"' in rp and "prep_decide" in rp


# ---------------------------------------------------------------------------------------------------------- costs
def test_costs_are_never_invented_and_the_four_kinds_stay_apart():
    reqs = [{"runId": "a", "provider": "anthropic", "model": "claude-opus-5", "at": "2026-09-17", "status": "completed", "attempts": 2, "usage": {"input": 1_000_000, "output": 100_000, "cacheRead": 0, "cacheWrite": 0}},
            {"runId": "b", "provider": "anthropic", "model": "claude-opus-5", "at": "2026-09-17", "status": "interrupted", "attempts": 1, "usage": None}]
    none = mc.summarize(reqs, table=[])
    assert none["estimated"]["usd"] is None and none["unknown"]["requests"] == 2 and none["tokens"]["input"] == 1_000_000 and none["retries"] == 1
    assert none["requestsWithoutCompletion"] == 1, "an interrupted request is counted and is NOT free"
    table = [{"provider": "anthropic", "model": "claude-opus-5", "from": "2026-10-01", "inputPerMTok": 9.0, "outputPerMTok": 9.0, "cacheReadPerMTok": 1.0, "cacheWritePerMTok": 1.0},
             {"provider": "anthropic", "model": "claude-opus-5", "from": "2026-09-01", "inputPerMTok": 2.0, "outputPerMTok": 10.0, "cacheReadPerMTok": 0.2, "cacheWritePerMTok": 2.5, "source": "test row"}]
    priced = mc.summarize(reqs, table=table, invoices=[{"usd": 12.5}], subscription={"usd": 200, "basis": "flat plan"})
    assert priced["estimated"] == {"usd": 3.0, "requests": 1} and priced["invoiceVerified"]["usd"] == 12.5 and priced["subscriptionAllocation"]["usd"] == 200
    assert priced["unknown"]["requests"] == 1 and mc.price_row(table, "anthropic", "claude-opus-5", "2026-08-01") is None, "a price is never applied before its date"
    card = {"claude-opus-5": {"in": 2.0, "out": 10.0, "cacheRead": 0.2, "cacheWrite": 2.5, "verifiedAt": "2026-09-17", "source": "list price"}}
    via_card = mc.summarize(reqs, table=card)
    assert via_card["estimated"] == {"usd": 3.0, "requests": 1} and via_card["unknown"]["requests"] == 1, "ONE price source: the platform llm.rates card (owner review)"
    assert mc.summarize(reqs, table={"other-model": {"in": 1, "out": 1}})["estimated"]["usd"] is None
    runs = [{"id": "r1", "created_at": "2026-09-17", "status": "failed", "llm": {"model": "claude-opus-5"}, "usage": {}, "result": {"visionRequested": True}},
            {"id": "r2", "created_at": "2026-09-17", "status": "done", "llm": {"model": "claude-opus-5"}, "usage": {}, "result": {"modelRequests": [
                {"pass": "entry", "status": "completed", "attempts": 2, "usage": {"input": 10, "output": 5}}, {"pass": "critic", "status": "failed", "attempts": 1, "usage": None}]}},
            {"id": "r3", "created_at": "2026-09-17", "status": "done", "llm": {}, "usage": {}, "result": {}}]
    rq = mc.requests_from_runs(runs)
    assert [(r["runId"], r["status"]) for r in rq] == [("r1", "interrupted"), ("r2", "completed"), ("r2", "failed")], "a deterministic run made no request"


def test_the_pipeline_keeps_a_request_ledger():
    from zargar.technique import vision
    src = inspect.getsource(vision.VisionPipeline._call)
    assert '"status": "started"' in src and src.count('req_row["status"] = "failed"') == 2 and 'req_row["status"] = "completed"' in src and "unknownAttempts" in src
    assert "modelRequests" in inspect.getsource(vision.PipelineResult.to_dict)


# ----------------------------------------------------------------------------------- resume ledger (Postgres)
@pytest.mark.usefixtures("fresh_db")
async def test_the_decision_ledger_is_idempotent_and_a_changed_input_makes_a_new_decision():
    from sqlalchemy import select
    from tests.conftest import TEST_DB_URL
    from zargar.db import make_engine, make_session_factory
    from zargar.models import TechniquePrepDecision
    from zargar.technique import prep_service as ps
    eng = make_engine(TEST_DB_URL); sf = make_session_factory(eng)
    settings = {"techniques.enhanced_market.preparation_policy": "deterministic"}
    run = {"id": "run-1", "symbol": "META", "asOf": 1, "trigger": "promote", "config": {"barsAssetId": "bars-1", "thresholds": {"min_risk_reward": 3.0}}, "llm": {},
           "result": {"plan": FX["META"]["plan"], "analysis": None}}
    calls = []

    async def get_run(rid):
        calls.append(rid)
        return run
    svc = SimpleNamespace(engine=SimpleNamespace(sf=sf, settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d))), get_run=get_run)
    a = await ps.prep_decide(svc, "run-1", persist=True)
    b = await ps.prep_decide(svc, "run-1", persist=True)
    assert a["disposition"] == "eligible" and a["origin"] == "batch" and b.get("reused") is True and b["decisionHash"] == a["decisionHash"]
    run["config"] = {**run["config"], "barsAssetId": "bars-2"}                       # the bars changed: a NEW decision, the old row untouched
    c = await ps.prep_decide(svc, "run-1", persist=True)
    assert c.get("reused") is None and c["inputKey"] != a["inputKey"]
    preview = await ps.prep_decide(svc, "run-1", persist=False)
    async with sf() as s:
        rows = (await s.execute(select(TechniquePrepDecision))).scalars().all()
    assert len(rows) == 2 and preview["inputKey"] == c["inputKey"], "a read-only preview writes nothing"
    await eng.dispose()


@pytest.mark.usefixtures("fresh_db")
async def test_no_cached_approval_survives_a_new_hold_a_correction_a_new_review_or_a_policy_change():
    """IR-05: the cache key carries every input that can change eligibility. An ALLOWED decision is never reused once a
    source hold, a corrected scenario, a different analyst review, another origin or a policy change arrives."""
    from sqlalchemy import select
    from tests.conftest import TEST_DB_URL
    from zargar.db import make_engine, make_session_factory
    from zargar.models import TechniquePrepDecision
    from zargar.technique import prep_service as ps
    eng = make_engine(TEST_DB_URL); sf = make_session_factory(eng)
    settings = {"techniques.enhanced_market.preparation_policy": "deterministic"}
    run = {"id": "run-1", "symbol": "META", "asOf": 1, "trigger": "ingest", "config": {"barsAssetId": "bars-1", "thresholds": {"min_risk_reward": 3.0}}, "llm": {"model": "m"},
           "result": {"plan": FX["META"]["plan"], "analysis": None}}

    async def get_run(rid):
        return run
    svc = SimpleNamespace(engine=SimpleNamespace(sf=sf, settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d))), get_run=get_run)
    allowed = await ps.prep_decide(svc, "run-1", persist=True, origin="ingest", source_ids=["scn-1"])
    assert allowed["disposition"] == "eligible"
    assert (await ps.prep_decide(svc, "run-1", persist=True, origin="ingest", source_ids=["scn-1"])).get("reused") is True, "identical inputs reuse the decision"
    held = await ps.prep_decide(svc, "run-1", persist=True, origin="ingest", source_ids=["scn-1"], source_hold=["conflict: evidence names MU"])
    assert held.get("reused") is None and held["disposition"] == "held_for_resolution" and held["inputKey"] != allowed["inputKey"], "a NEW hold is a new decision - the cached approval is not reused"
    corrected = await ps.prep_decide(svc, "run-1", persist=True, origin="ingest", source_ids=["scn-1-corrected"])
    assert corrected.get("reused") is None and corrected["inputKey"] not in (allowed["inputKey"], held["inputKey"])
    other_origin = await ps.prep_decide(svc, "run-1", persist=True, origin="preopen_replan", source_ids=["scn-1"])
    assert other_origin.get("reused") is None and other_origin["inputKey"] != allowed["inputKey"]
    settings["techniques.enhanced_market.preparation_policy"] = "baseline"
    run["result"] = {**run["result"], "analysis": {"verdict": "setup", "noTradeReasons": []}}
    base_setup = await ps.prep_decide(svc, "run-1", persist=True, origin="batch")
    run["result"] = {**run["result"], "analysis": {"verdict": "no_setup", "noTradeReasons": ["k1 breakout @ 685.16 - the target is a manufactured pct-ladder (T4.4)"]}}
    base_veto = await ps.prep_decide(svc, "run-1", persist=True, origin="batch")
    assert base_setup["disposition"] == "eligible" and base_veto.get("reused") is None and base_veto["disposition"] == "refused", "a different analyst review is different evidence"
    async with sf() as s:
        rows = (await s.execute(select(TechniquePrepDecision))).scalars().all()
    assert len(rows) == 6 and len({r.id for r in rows}) == 6
    await eng.dispose()
