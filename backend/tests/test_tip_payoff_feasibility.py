"""PROF-01/02 (2026-09-15): risk-budget feasibility before a TAKE and the
whole exit path in integer units. Pure arithmetic; no engine."""
from zargar.techniques.tip import feasibility as fz
from zargar.techniques.tip import payoff as po


# ---------------------------------------------------------------- integer ladders
def test_integer_ladder_for_one_two_three_contracts_and_odd_shares():
    # execution's rule: a rung is a fraction of the REMAINING size, an option rung
    # sells round(remaining x fraction) and at least one contract, shares round down
    lad = po.integer_ladder(1, [0.4, 0.35, 0.25])
    assert lad["declaredUnits"] == [0, 0, 0] and lad["units"] == [1, 0, 0] and lad["runner"] == 0
    assert not lad["executable"] and lad["collapsed"] and "one unit" in lad["note"]
    lad2 = po.integer_ladder(2, [0.4, 0.35, 0.25])
    assert lad2["units"] == [1, 1, 0] and lad2["collapsed"]
    lad3 = po.integer_ladder(3, [0.4, 0.35, 0.25])
    assert lad3["units"] == [1, 1, 1] and lad3["runner"] == 0 and lad3["executable"] and lad3["declaredUnits"] == [1, 1, 0]
    ok = po.integer_ladder(5, [0.4, 0.6])
    assert ok["units"] == [2, 3] and ok["runner"] == 0 and ok["executable"]
    odd = po.integer_ladder(89, [0.4, 0.35, 0.25], vehicle="shares")
    assert odd["units"] == [35, 31, 23] and odd["runner"] == 0 and odd["executable"]


def test_rkt_long_only_round_trip_reconciles_and_excess_is_separate():
    # BUY 148 @13.46; trim 59 @13.7373; stop 148 @12.9374 -> the long episode is -30.15,
    # the 59-share excess is reported apart (never scored as the idea)
    r = po.realized_from_fills(entry_qty=148, entry_price=13.46,
                               fills=[{"qty": 59, "price": 13.7373, "kind": "trim"},
                                      {"qty": 148, "price": 12.9374, "kind": "venue_stop"}])
    assert r["parts"][0]["pnl"] == 16.36 and r["parts"][1]["pnl"] == -46.51
    assert r["realized"] == -30.15 and r["excessUnits"] == 59 and r["unclosed"] == 0


def test_payoff_preview_scenarios_and_one_lot_policy():
    # RKT's declared plan on 148 shares: entry 13.46, stop 12.9378, targets 13.8/14.1/14.45 at 40/35/25 %
    gains = po.unit_gains(vehicle="shares", entry_ref=13.46, targets=[13.8, 14.1, 14.45])
    pv = po.payoff_preview(qty=148, fractions=[0.4, 0.35, 0.25], gains=gains, unit_loss=round(13.46 - 12.9378, 4), vehicle="shares")
    assert pv["ladder"]["units"] == [59, 51, 38] and pv["ladder"]["executable"]   # 59 at TP1 = the actual RKT trim
    sc = pv["scenarios"]
    assert sc["stopOnly"]["R"] == -1.0
    assert sc["tp1ThenStop"]["net"] < 0, "a profitable first trim followed by the stop is a losing trade"
    assert abs(sc["allTargets"]["R"] - 1.16) < 0.05, "the whole ladder is about 1.16R gross"
    # one contract cannot follow the ladder: the coherent policy is a single exit
    g1 = po.unit_gains(vehicle="option", entry_ref=74.0, targets=[76.0, 78.5, 81.5], delta=0.29, multiplier=100)
    one = po.payoff_preview(qty=1, fractions=[0.4, 0.3, 0.2], gains=g1, unit_loss=101.25, fee_per_unit=1.04)
    assert one["ladder"]["units"] == [1, 0, 0] and one["ladder"]["collapsed"] and one["oneLot"]["policy"].startswith("single exit")
    single = round(0.29 * 2.0 * 100 - 2 * 1.04, 2)
    assert one["oneLot"]["net"] == single
    # PROF-F2: the whole contract leaves at TP1 - no later target or stop can touch it
    assert one["scenarios"]["allTargets"]["net"] == single and one["scenarios"]["tp1ThenStop"]["net"] == single
    two = po.payoff_preview(qty=2, fractions=[0.4, 0.35, 0.25], gains=[10, 20, 30], unit_loss=5, fee_per_unit=1)
    assert two["ladder"]["units"] == [1, 1, 0]
    assert two["scenarios"]["allTargets"]["net"] == 10 + 20 - 2 - 2 and two["scenarios"]["tp1ThenStop"]["net"] == 10 - 5 - 2 - 2
    missing = po.payoff_preview(qty=1, fractions=[1.0], gains=[None], unit_loss=50.0)
    assert missing["scenarios"] is None and "gain estimate" in missing["reason"]


# ---------------------------------------------------------------- feasibility
def test_feasibility_reproduces_the_reviewers_five_cases_and_a_fitting_one():
    cases = {"MSFT 505C": (96.00, 88.93), "TSLA 340P": (100.11, 89.43), "AMZN 300C": (191.53, 89.60),
             "AFRM 80C": (200.08, 89.11), "PLTR 195C": (130.00, 89.62)}
    for name, (unit, budget) in cases.items():
        f = fz.feasibility(budget=budget, unit_loss=unit, unit_cost=250.0, allocation_limit=2000.0)
        assert f["feasible"] is False and f["qty"] == 0 and "above the" in f["reason"], name
    hims = fz.feasibility(budget=88.36, unit_loss=46.0, unit_cost=50.0, allocation_limit=2000.0)
    assert hims["feasible"] and hims["qty"] == 1
    # the purchase allocation binds too
    f2 = fz.feasibility(budget=500.0, unit_loss=10.0, unit_cost=300.0, allocation_limit=1000.0)
    assert f2["qty"] == 3 and f2["qtyByRisk"] == 50 and f2["qtyByAllocation"] == 3
    nope = fz.feasibility(budget=89.0, unit_loss=None)
    assert nope["feasible"] is None and "review" in nope["reason"]
    # PROF-F1: $0 allocation is no capital, None is unknown, negatives are invalid
    zero = fz.feasibility(budget=100, unit_loss=10, unit_cost=50, allocation_limit=0)
    assert zero["feasible"] is False and zero["qty"] == 0 and "allocation" in zero["reason"]
    unknown = fz.feasibility(budget=None, unit_loss=10, unit_cost=50, allocation_limit=None)
    assert unknown["feasible"] is None and "unknown" in unknown["reason"]
    bad = fz.feasibility(budget=100, unit_loss=10, unit_cost=-5, allocation_limit=1000)
    assert bad["feasible"] is None and "invalid" in bad["reason"]
    assert fz.share_alternative(entry=74.0, stop=68.0, direction="long", budget=89.11, allocation_limit=0) is None


def test_unit_risk_and_labelled_alternatives_at_equal_risk():
    ul, basis, _ = fz.unit_risk(vehicle="shares", entry_ref=146.27, stop=134.4871, direction="long")
    assert basis == "stop-distance" and abs(ul - 11.7829) < 1e-4
    ul2, basis2, _ = fz.unit_risk(vehicle="option", entry_ref=74.0, stop=68.0, direction="long", premium=2.25,
                                  delta=0.29, option_type="call", multiplier=100)
    assert basis2 == "delta-linear" and ul2 > 0
    alt = fz.share_alternative(entry=74.0, stop=68.0, direction="long", budget=89.11, allocation_limit=2000.0)
    assert alt and alt["qty"] == 14 and alt["plannedRisk"] <= 89.11 and alt["cost"] <= 2000.0 and "research" in alt["label"]
    assert fz.share_alternative(entry=74.0, stop=68.0, direction="short", budget=89.11, allocation_limit=2000.0) is None
    rows = [{"strike": 80, "call": {"symbol": "AFRM261016C00080000", "ask": 2.25, "delta": 0.29}},
            {"strike": 85, "call": {"symbol": "AFRM261016C00085000", "ask": 0.60, "delta": 0.12}},
            {"strike": 90, "call": {"symbol": "AFRM261016C00090000", "ask": 0.20}}]        # no delta: skipped
    alts = fz.chain_alternatives(rows, direction="long", entry_ref=74.0, stop=68.0, budget=89.11,
                                 allocation_limit=2000.0, exclude_symbol="AFRM261016C00080000")
    assert [a["symbol"] for a in alts] == ["AFRM261016C00085000"] and alts[0]["qty"] >= 1


def test_apply_gate_annotates_by_default_and_downgrades_only_when_asked():
    op = {"verdict": "take", "rationale": "good thesis"}
    infeasible = {"feasible": False, "reason": "one unit risks $200 - above the $89 budget"}
    ann = fz.apply_gate(op, infeasible, "annotate")
    assert ann["verdict"] == "take" and ann["thesisVerdict"] == "take" and ann["expression"]["feasible"] is False
    down = fz.apply_gate(op, infeasible, "downgrade")
    assert down["verdict"] == "watch" and down["thesisVerdict"] == "take" and "does not fit" in down["rationale"]
    fine = fz.apply_gate(op, {"feasible": True, "qty": 1}, "downgrade")
    assert fine["verdict"] == "take" and fine["expressionGate"] == "annotated"
