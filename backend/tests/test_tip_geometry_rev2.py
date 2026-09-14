"""GEOMETRY-RISK-PLAN revision 2 — the ten acceptance cases, on the pure
module (`techniques/tip/geometry.py`). No I/O, no clock, no LLM."""
from zargar.domain import Bar
from zargar.techniques.tip import geometry as g


def _bars(entry: float, *, rng: float = 1.0, n: int = 60):
    return [Bar(symbol="X", tf="15m", ts=i * 900_000, open=entry, high=entry + rng / 2,
                low=entry - rng / 2, close=entry) for i in range(n)]


class _Settings:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, key, default=None):
        return self.kv.get(key, default)


def _plan(**kw):
    base = dict(mode="enforce", direction="long", vehicle="shares", entry_ref=100.0,
                exit_plan={"targets": [105.0], "fractions": [1.0], "underlyingStop": 99.0},
                bars=_bars(100.0), settings=_Settings(), limit=100.0, qty_requested=100,
                budget=50.0, budget_source="test")
    base.update(kw)
    return g.plan_risk(**base)


# 1. wider repaired stop -> qty resized down; qty x unit_loss <= B holds
def test_case1_wider_repaired_stop_resizes_down():
    final, rp = _plan(exit_plan={"targets": [105.0], "fractions": [1.0], "underlyingStop": 99.5})
    assert rp.finalStop < 99.5 and any("re-placed stop" in r for r in rp.repairs)
    assert rp.unitLoss >= 1.0 and rp.resized and rp.qty * rp.unitLoss <= 50.0 + 1e-9
    assert rp.invariantOk is True and rp.plannedRisk == rp.qty * rp.unitLoss


# 2. a SMALL widening below the materiality threshold still triggers the resize
def test_case2_materiality_threshold_never_waives_the_invariant():
    final, rp = _plan(exit_plan={"targets": [105.0], "fractions": [1.0], "underlyingStop": 99.2},
                      settings=_Settings(**{"techniques.tip.geometry_resize_threshold_pct": 50.0}),
                      budget=40.0)
    assert rp.widenPct is not None and rp.widenPct < 50.0 and rp.severity == "log"
    assert rp.resized and rp.qty == 40 and rp.invariantOk is True


# 3. resize below 1 contract -> review-gated, never auto
def test_case3_resize_below_one_contract_is_review_gated():
    final, rp = _plan(vehicle="option", limit=5.0, multiplier=100.0, option_type="call",
                      delta=0.5, qty_requested=3, budget=100.0,
                      exit_plan={"targets": [105.0], "fractions": [1.0], "underlyingStop": 98.0})
    # delta-linear: 0.5 x 2.0 = 1.00 premium -> $100/contract, floor 25% x $500 = $125 -> 125 > 100
    assert rp.unitLoss == 125.0 and rp.greeks.get("floorApplied") is True
    assert rp.qty == 0 and rp.reviewRequired and "no quantity" in rp.reviewRequired


# 4. unchanged geometry that satisfies B is untouched; one that violates B is flagged, not grandfathered
def test_case4_no_grandfathering():
    final, ok = _plan(qty_requested=40, budget=50.0)          # 40 x $1 = $40 <= $50
    assert ok.repairs == [] and not ok.resized and ok.qty == 40 and ok.invariantOk is True
    final, bad = _plan(qty_requested=80, budget=50.0)         # same geometry, 80 x $1 > $50
    assert bad.repairs == [] and bad.resized and bad.qty == 50 and bad.invariantOk is True
    assert any("resized 80" in d for d in bad.decisions)


# 5. fresh-quote retry re-runs validation; the limit is never raised and size never grows
def test_case5_revalidation_at_submission():
    final, rp = _plan(vehicle="option", limit=4.0, multiplier=100.0, option_type="call",
                      delta=0.6, qty_requested=2, budget=400.0,
                      exit_plan={"targets": [105.0], "fractions": [1.0], "underlyingStop": 98.0})
    d = rp.to_dict()
    d["quote"] = {**d["quote"], "limit": 4.0}
    assert rp.qty == 2                                        # 2 x $120 = $240 <= $400
    qty, d2 = g.revalidate_for_submit(d, new_limit=3.0)       # improved limit: fewer $ at risk, size unchanged
    assert qty == 2 and d2["quote"]["revalidated"] and d2["unitLoss"] <= d["unitLoss"]
    qty3, d3 = g.revalidate_for_submit(d, new_limit=9.0)      # a higher premium can only shrink the size
    assert qty3 <= 2 and d3["stressRisk"] == 9.0 * 100 * qty3


# 6. contract multiplier in unit AND stress loss; puts use |delta|; missing greeks -> review, no guess
def test_case6_multiplier_puts_and_missing_greeks():
    final, put = _plan(direction="short", vehicle="option", limit=2.0, multiplier=100.0,
                       option_type="put", delta=-0.4, qty_requested=1, budget=500.0,
                       exit_plan={"targets": [95.0], "fractions": [1.0], "underlyingStop": 102.0})
    assert put.stopDistance == 2.0 and put.greeks["delta"] == 0.4 and put.greeks["thesisMatch"] is True
    assert put.unitLoss == 80.0 and put.stressUnitLoss == 200.0 and put.stressRisk == 200.0
    final, none = _plan(vehicle="option", limit=2.0, multiplier=100.0, option_type="call",
                        delta=None, qty_requested=1, budget=500.0,
                        exit_plan={"targets": [105.0], "fractions": [1.0], "underlyingStop": 98.0})
    assert none.unitLoss is None and none.reviewRequired and "missing delta" in none.reviewRequired
    # a mini contract (multiplier 10) risks a tenth per contract
    final, mini = _plan(vehicle="option", limit=2.0, multiplier=10.0, option_type="call",
                        delta=0.5, qty_requested=1, budget=500.0,
                        exit_plan={"targets": [105.0], "fractions": [1.0], "underlyingStop": 98.0})
    assert mini.unitLoss == 10.0 and mini.stressUnitLoss == 20.0


# 7. post-fill widen is trim-FIRST; rejected trim keeps the tight stop; partial recomputes; unknown reconciles; restart resumes
def test_case7_trim_first_state_machine():
    d = g.post_fill_decision(direction="long", entry_ref=100.0, current_stop=99.0, proposed_stop=97.0,
                             qty=10, unit_loss_at_proposed=3.0, budget=15.0)
    assert d["action"] == "trim_first" and d["keepQty"] == 5 and d["trimQty"] == 5
    st = {"phase": "trim_pending", "tightStop": 99.0, "wideStop": 97.0, "trimQty": 5, "keepQty": 5}
    st = g.advance_exception(st, {"kind": "trim_submitted", "orderId": "o1"})
    assert st["phase"] == "trim_pending" and st["stopInForce"] == 99.0
    rejected = g.advance_exception(st, {"kind": "trim_rejected"})
    assert rejected["phase"] == "kept_tight" and rejected["stopInForce"] == 99.0
    partial = g.advance_exception(st, {"kind": "trim_filled", "filledQty": 2})
    assert partial["phase"] == "trim_pending" and partial["partial"] and partial["stopInForce"] == 99.0
    unknown = g.advance_exception(st, {"kind": "trim_unknown"})
    assert unknown["phase"] == "reconcile" and unknown["stopInForce"] == 99.0
    # restart between steps: the persisted dict resumes from its phase
    resumed = g.advance_exception(dict(unknown), {"kind": "reconciled", "filledQty": 5})
    assert resumed["phase"] == "widened" and resumed["stopInForce"] == 97.0
    assert [h["to"] for h in resumed["history"]] == ["trim_pending", "reconcile", "widened"]
    # no estimate at the wider stop -> hold the tight stop and ask a person
    hold = g.post_fill_decision(direction="long", entry_ref=100.0, current_stop=99.0, proposed_stop=97.0,
                                qty=10, unit_loss_at_proposed=None, budget=15.0)
    assert hold["action"] == "reconcile" and hold["stop"] == 99.0


# 8. post-fill tighten -> immediate
def test_case8_tighten_is_immediate():
    d = g.post_fill_decision(direction="long", entry_ref=100.0, current_stop=97.0, proposed_stop=98.5,
                             qty=10, unit_loss_at_proposed=1.5, budget=15.0)
    assert d["action"] == "tighten" and d["stop"] == 98.5
    s = g.post_fill_decision(direction="short", entry_ref=100.0, current_stop=103.0, proposed_stop=101.5,
                             qty=10, unit_loss_at_proposed=1.5, budget=15.0)
    assert s["action"] == "tighten"


# 9. shares and options both honor B; caps apply after
def test_case9_shares_and_options_both_honor_budget():
    final, sh = _plan(qty_requested=500, budget=120.0)
    assert sh.qty == 120 and sh.qty * sh.unitLoss <= 120.0
    final, op = _plan(vehicle="option", limit=3.0, multiplier=100.0, option_type="call", delta=0.5,
                      qty_requested=10, budget=300.0,
                      exit_plan={"targets": [105.0], "fractions": [1.0], "underlyingStop": 98.0})
    assert op.unitLoss == 100.0 and op.qty == 3 and op.stressRisk == 900.0


# 10. planned vs stress vs realized recorded separately
def test_case10_accounting_keeps_planned_stress_realized_apart():
    enforced = {"enforced": True, "plannedRisk": 120.0, "unitLoss": 40.0, "qty": 3, "stressRisk": 900.0}
    legs = [{"symbol": "X", "secType": "OPT", "qty": 3, "avgFill": 3.0, "multiplier": 100}]
    pos = {"config": {"riskPlan": enforced}, "legs": legs, "realizedPnl": -160.0}
    acc = g.risk_accounting(pos)
    assert acc["plannedRisk"] == 120.0 and acc["plannedRiskBasis"] == "enforced-plan"
    assert acc["stressRisk"] == 900.0 and acc["realizedPnl"] == -160.0 and acc["realizedLoss"] == 160.0
    assert acc["slippageVsPlanned"] == 40.0 and "hypothetical" not in acc
    win = g.risk_accounting({"config": {"riskPlan": enforced}, "legs": legs, "realizedPnl": 50.0})
    assert win["realizedLoss"] == 0.0 and "slippageVsPlanned" not in win
    # a shadow plan never becomes the executed plan's risk (C95-02)
    shadow = {"mode": "shadow", "enforced": False, "plannedRisk": 50.0, "qty": 50, "qtyRequested": 100, "resized": True}
    sh = g.risk_accounting({"entry": 100.0, "policy": {"stop": {"kind": "fixed", "price": 99.0}},
                            "legs": [{"symbol": "X", "secType": "STK", "qty": 100, "avgFill": 100.0}],
                            "realizedPnl": -100.0, "extras": {"riskPlan": shadow}})
    assert sh["plannedRisk"] == 100.0 and sh["plannedRiskBasis"] == "executed-plan" and sh["slippageVsPlanned"] == 0.0
    assert sh["hypothetical"]["plannedRisk"] == 50.0
    none = g.risk_accounting({"legs": [{"symbol": "O", "secType": "OPT", "qty": 1, "avgFill": 2.0}],
                              "realizedPnl": -30.0, "extras": {"riskPlan": shadow}})
    assert none["plannedRisk"] is None and none["plannedRiskBasis"] == "unavailable" and "slippageVsPlanned" not in none


# budget authority: approved policy only, never the model's quantity
def test_budget_comes_from_policy():
    assert g.risk_budget(_Settings(**{"techniques.tip.risk_budget_per_tip": 250.0}), 10_000.0) == (250.0, "techniques.tip.risk_budget_per_tip")
    b, src = g.risk_budget(_Settings(**{"techniques.tip.risk_pct": 1.0}), 10_000.0)
    assert b == 100.0 and "risk_pct" in src
    assert g.risk_budget(_Settings(), None)[0] == 0.0
    assert g.gate_mode(_Settings()) == "shadow" and g.gate_mode(_Settings(**{"techniques.tip.geometry_gate": "enforce"})) == "enforce"


# a stop-less option plan is bounded by its declared premium stop, else the whole debit
def test_stopless_option_plan_uses_declared_premium_stop():
    final, rp = _plan(vehicle="option", limit=2.0, multiplier=100.0, option_type="call", delta=0.5,
                      qty_requested=4, budget=250.0, exit_plan={"targets": [110.0], "premiumStopPct": 50.0})
    assert rp.unitLossBasis == "premium-stop" and rp.unitLoss == 100.0 and rp.qty == 2
    final, full = _plan(vehicle="option", limit=2.0, multiplier=100.0, option_type="call", delta=0.5,
                        qty_requested=4, budget=250.0, exit_plan={"targets": [110.0]})
    assert full.unitLossBasis == "full-premium" and full.unitLoss == 200.0 and full.qty == 1


# shadow mode computes everything but enforces nothing
def test_shadow_mode_reports_without_enforcing():
    final, rp = _plan(mode="shadow", qty_requested=80, budget=50.0)
    assert rp.enforced is False and rp.resized and rp.qty == 50 and rp.qtyRequested == 80
