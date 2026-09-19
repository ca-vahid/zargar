"""first-sale-v1 (integrated plan D, 2026-09-18): R2 measured where the position exits, at the FINAL quantity.

SBUX 2026-09-18 (event 165135) is the regression: plan-time R2 measured TP3 (3.63R) because risk-based sizing leaves the
quantity unknown; the sizer bought ONE put; a one-contract position leaves whole at TP2 = 1.316R < 3.0. Pure record +
the runner's caller boundary (`_first_sale_check`) + EM's producer (`PlanArmer.first_sale_record`) on fakes. No engine,
no database, no orders."""
import asyncio
import inspect
from types import SimpleNamespace

import pytest

from zargar.execution.planrunner import PlanRunner
from zargar.technique import first_sale as fs
from zargar.technique.arming import PlanArmer

SBUX = dict(stage="order", symbol="SBUX", run_id="8a79a643", trigger_id="d1", family="breakdown", direction="short",
            session="2026-09-18", plan_entry=96.0907, runner_entry=95.335, stop=97.681,
            targets=[94.1689, 92.2471, 90.3253], observed_underlier=None, instrument="options", multiplier=100.0,
            limit_price=1.05, single_exit="tp2", pinned_gate_target="auto", min_rr=3.0,
            contract={"symbol": "SBUX261002P00095000", "delta": -0.45, "openInterest": 183}, option_quote={"bid": 1.0, "ask": 1.05, "bidSize": 12, "askSize": 9, "sourceTs": 900},
            fee_per_contract=1.04, stock_commission=0.0, plan_gate={"targetIndex": 2, "rr": 3.63, "min": 3.0}, mode="enforce", now_ms=1000)


def _rec(**over):
    kw = {**SBUX, **over}
    kw.setdefault("qty", 1)
    kw.setdefault("affordable_qty", kw["qty"])
    return fs.build_record(**kw)


def test_sbux_one_contract_is_1_316r_at_tp2_and_fails_the_3r_rule():
    r = _rec(qty=1)
    g = r["gate"]
    assert (g["rung"], g["rungIndex"], g["rungBasis"]) == ("tp2-full", 1, "single_contract_exit")
    assert g["rRunnerEntry"] == 1.316 and g["minRiskReward"] == 3.0 and g["verdict"] == "fail" and g["reason"] == "first_sale_rr_below_min"
    assert g["planTime"]["targetIndex"] == 2 and g["differsFromPlanTime"] is True, "plan time measured TP3; the position exits at TP2"
    assert g["rObservedUnderlier"] is None and g["observedProblem"] == "underlier_unobserved", "the missing observation is never invented"
    assert r["underlying"]["observed"] is None
    why = fs.refusal_reason(r)
    assert why and "1.316R" in why and "tp2-full" in why and "3R minimum" in why


@pytest.mark.parametrize("qty,instrument,rung,idx,r_expected,verdict", [
    (1, "options", "tp2-full", 1, 1.316, "fail"),
    (2, "options", "tp2-full", 1, 1.316, "fail"),
    (3, "options", "tp3", 2, 2.135, "fail"),          # the ladder case measures the book's TP3 from the ACTUAL entry: 2.135R, not plan-time 3.63R
    (25, "shares", "tp3", 2, 2.135, "fail"),
])
def test_quantity_dependent_rung_for_one_two_three_contracts_and_shares(qty, instrument, rung, idx, r_expected, verdict):
    r = _rec(qty=qty, instrument=instrument, multiplier=(100.0 if instrument == "options" else 1.0))
    assert (r["gate"]["rung"], r["gate"]["rungIndex"]) == (rung, idx)
    assert r["gate"]["rRunnerEntry"] == r_expected and r["gate"]["verdict"] == verdict


def test_final_repricing_and_quantity_change_the_gate_inputs():
    a = _rec(qty=1, runner_entry=96.0907)            # at the saved plan entry: (96.0907-92.2471)/(97.681-96.0907) = 2.417
    b = _rec(qty=3, runner_entry=96.0907)            # three contracts -> TP3: 3.625
    assert a["gate"]["rRunnerEntry"] == 2.417 and a["gate"]["verdict"] == "fail"
    assert b["gate"]["rRunnerEntry"] == 3.625 and b["gate"]["verdict"] == "pass" and fs.refusal_reason(b) is None
    assert a["firstSale"]["quantitySold"] == 1 and b["firstSale"] == {"rungIndex": 0, "rung": "tp1-ladder", "quantitySold": 1.0, "rRunnerEntry": 1.208}


def test_puts_are_signed_for_the_side_and_a_wrong_side_target_fails():
    assert fs.r_multiple(direction="short", entry=100, stop=102, target=94) == (3.0, None)
    assert fs.r_multiple(direction="long", entry=100, stop=98, target=106) == (3.0, None)
    assert fs.r_multiple(direction="short", entry=100, stop=102, target=101)[1] == "target_wrong_side"
    assert fs.r_multiple(direction="short", entry=100, stop=99, target=94) == (None, "stop_wrong_side")
    r = _rec(qty=1, targets=[94.0, 96.5, 90.0])
    assert r["gate"]["verdict"] == "fail" and r["gate"]["reason"] == "target_wrong_side"


def test_unknowns_stay_unknown_and_never_refuse():
    r = _rec(qty=None, affordable_qty=None)
    assert r["gate"]["verdict"] == "unknown" and r["gate"]["reason"] == "quantity_unknown" and fs.refusal_reason(r) is None
    r2 = _rec(qty=1, stop=None)
    assert r2["gate"]["verdict"] == "unknown" and fs.refusal_reason(r2) is None
    r3 = _rec(qty=1, option_quote=None, contract={"symbol": "X"})
    assert r3["quote"] is None and r3["payoffProxy"] is None and r3["spreadCost"] is None, "no quote / no delta = unknown economics"
    r4 = _rec(qty=1, observed_underlier={"price": 95.40, "sourceTs": 990, "receivedTs": 995, "source": "alpaca"})
    assert r4["gate"]["rObservedUnderlier"] == 1.382 and r4["underlying"]["observed"]["sourceTs"] == 990


def test_the_3r_minimum_is_not_weakened_and_a_pinned_target_is_honoured():
    r = _rec(qty=1, runner_entry=95.0, stop=96.0, targets=[94.0, 92.01, 90.0])       # 2.99R
    assert r["gate"]["rRunnerEntry"] == 2.99 and r["gate"]["verdict"] == "fail"
    assert _rec(qty=1, runner_entry=95.0, stop=96.0, targets=[94.0, 92.0, 90.0])["gate"]["verdict"] == "pass"
    p = _rec(qty=1, pinned_gate_target="tp3")
    assert p["gate"]["rung"] == "tp3" and p["gate"]["rungBasis"] == "pinned"


# ------------------------------------------------------------------------------------ the caller boundary in the runner
class _Journal:
    def __init__(self):
        self.rows = []

    async def append(self, type_, payload, **kw):
        self.rows.append((type_, payload, kw))


def _runner(mode, rec):
    j = _Journal()
    me = SimpleNamespace(engine=SimpleNamespace(journal=j), first_sale_policy=lambda ap: mode,
                         first_sale_record=lambda ap, trade, qty, limit, m: (rec(m) if callable(rec) else rec))
    return me, j


def _ap():
    return SimpleNamespace(run_id="run1", symbol="SBUX", config=SimpleNamespace(portfolio_id="book"))


def test_base_runner_is_off_and_other_desks_run_no_first_sale_code():
    assert PlanRunner.first_sale_policy(SimpleNamespace(), _ap()) == "off"
    me, j = _runner("off", lambda m: (_ for _ in ()).throw(AssertionError("must not build")))
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), SimpleNamespace(timing={}, trigger_id="d1"), 1, 1.05)) is None and j.rows == []


def test_observe_journals_and_never_refuses_and_enforce_refuses_only_a_fail():
    trade = SimpleNamespace(timing={}, trigger_id="d1")
    me, j = _runner("observe", lambda m: _rec(qty=1, mode=m))
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)) is None
    assert [t for t, _, _ in j.rows] == ["TechniqueFirstSale"] and j.rows[0][1]["mode"] == "observe" and j.rows[0][2]["aggregate_id"] == "run1"
    assert trade.timing["firstSale"] == {"verdict": "fail", "rung": "tp2-full", "r": 1.316, "mode": "observe"}
    me, j = _runner("enforce", lambda m: _rec(qty=1, mode=m))
    why = asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05))
    assert why and why.startswith("first-sale gate: 1.316R") and len(j.rows) == 1
    me, j = _runner("enforce", lambda m: _rec(qty=None, affordable_qty=None, mode=m))
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)) is None, "unknown never refuses"


def test_a_failing_hook_never_blocks_an_entry():
    me, j = _runner("enforce", lambda m: (_ for _ in ()).throw(RuntimeError("boom")))
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), SimpleNamespace(timing={}, trigger_id="d1"), 1, 1.05)) is None


def test_the_check_sits_on_the_entry_path_only_after_sizing_and_before_the_intent():
    src = inspect.getsource(PlanRunner._enter)
    assert src.index("trade.qty = qty") < src.index("_first_sale_check") < src.index("OrderIntent(portfolio_id")
    assert src.count("_first_sale_check") == 1
    whole = inspect.getsource(PlanRunner)
    assert whole.count("self._first_sale_check(") == 1, "exits never pass through the first-sale gate"


# ------------------------------------------------------------------------------------------------- EM's producer
def _armer(settings, quotes):
    eng = SimpleNamespace(settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)), quotes=SimpleNamespace(get=lambda s: quotes.get(s)))
    th = SimpleNamespace(min_risk_reward=3.0, rr_gate_target=2)
    return SimpleNamespace(engine=eng, technique=SimpleNamespace(thresholds=lambda: th))


def test_em_default_is_observe_and_bad_values_fall_to_off():
    a = _armer({}, {})
    assert PlanArmer.first_sale_policy(a, None) == "observe"
    assert PlanArmer.first_sale_policy(_armer({"techniques.enhanced_market.first_sale_rr_gate": "ENFORCE"}, {}), None) == "enforce"
    assert PlanArmer.first_sale_policy(_armer({"techniques.enhanced_market.first_sale_rr_gate": "yes"}, {}), None) == "off"
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS["techniques.enhanced_market.first_sale_rr_gate"] == "observe"
    assert not any(k.endswith("first_sale_rr_gate") and not k.startswith("techniques.enhanced_market.") for k in DEFAULTS)


def test_em_producer_freezes_the_live_inputs_without_inventing_the_underlier():
    oq = SimpleNamespace(bid=1.0, ask=1.05, bid_size=12, ask_size=0, source_ts=900, quote_ts=0, source="opra", derived=False)
    a = _armer({"technique.rr_gate_target": "auto"}, {"SBUX261002P00095000": oq})          # no underlying quote at all
    ap = SimpleNamespace(run_id="run1", symbol="SBUX", plan_for="2026-09-18", trackers={},
                         plan={"triggers": [{"id": "d1", "entry": 96.0907, "riskReward": 3.63, "riskRewardTp3": 3.63}], "thresholds": {"rr_gate_target": 2}},
                         config=SimpleNamespace(single_contract_exit="tp2", portfolio_id="book"))
    trade = SimpleNamespace(trigger_id="d1", kind="breakdown", direction="short", entry=95.335, stop=97.681, targets=[94.1689, 92.2471, 90.3253],
                            instrument="options", order_symbol="SBUX261002P00095000", multiplier=100.0, contract={"symbol": "SBUX261002P00095000", "delta": -0.45})
    rec = PlanArmer.first_sale_record(a, ap, trade, 1, 1.05, "observe")
    assert rec["version"] == "first-sale-v1" and rec["gate"]["rRunnerEntry"] == 1.316 and rec["gate"]["verdict"] == "fail"
    assert rec["underlying"]["observed"] is None and rec["underlying"]["planEntry"] == 96.0907
    assert rec["quote"]["askSize"] is None and rec["quote"]["source"] == "opra" and rec["gate"]["planTime"]["rr"] == 3.63
    assert rec["fees"]["roundTrip"] == 2.08


# ------------------------------------------------------------------------------------------- vehicle comparison
def test_vehicle_comparison_keeps_unknowns_and_never_gates_on_friction_or_open_interest():
    setup = {"symbol": "DRAM", "direction": "short", "entry": 59.2, "stop": 59.9, "targets": [58.0833, 57.0, 56.0], "singleExit": "tp2"}
    rows = fs.compare_vehicles(setup=setup, contracts=[
        {"symbol": "DRAM260921P00058000", "strike": 58, "dte": 3, "delta": -0.35, "bid": 0.30, "ask": 0.36, "bidSize": 5, "askSize": 7, "openInterest": 88},
        {"symbol": "DRAM260921P00057000", "strike": 57, "dte": 3, "delta": None, "bid": 0.1, "ask": 0.2, "bidSize": 1, "askSize": 1},
        {"symbol": "DRAM260925P00058000", "strike": 58, "dte": 7, "delta": -0.4, "bid": 0, "ask": 0},
    ], share_quote=None, budget=750, risk_budget=100, fee_per_contract=1.04)["rows"]
    a, b, c, sh = rows
    assert a["status"] == "scored" and a["affordableQty"] == 4 and a["firstSaleRung"] == "tp1-ladder" and a["openInterest"] == 88
    assert a["overFrictionMarker"] is True and a["payoffProxyNet"] is not None, "the 8% marker is reported, never a refusal"
    assert b["status"] == "unknown" and "no_delta" in b["unknown"] and b["payoffProxyGross"] is None
    assert c["status"] == "unknown" and "no_two_sided_quote" in c["unknown"]
    assert sh["status"] == "not_permitted"
    longs = fs.compare_vehicles(setup={**setup, "direction": "long", "stop": 58.5, "targets": [60.3, 61, 62]}, contracts=[],
                                share_quote={"ask": 59.21, "askSize": 300}, budget=2000, risk_budget=100, fee_per_contract=1.04)["rows"]
    assert longs[0]["vehicle"] == "shares" and longs[0]["affordableQty"] == 33 and longs[0]["status"] == "scored"
