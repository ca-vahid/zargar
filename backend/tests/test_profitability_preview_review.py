"""Two minimal arithmetic boundaries for the new decision-support tools."""
from zargar.techniques.tip import feasibility, payoff


def test_zero_allocation_is_not_unlimited_capital():
    result = feasibility.feasibility(budget=100, unit_loss=10, unit_cost=50, allocation_limit=0)
    assert result["feasible"] is False and result["qty"] == 0


def test_one_contract_preview_does_not_credit_later_targets_after_full_tp1_exit():
    # PositionManager.close rounds a positive fractional OPT exit to at least one.
    # Thus this one-lot is completely closed at TP1: later targets/stops cannot apply.
    result = payoff.payoff_preview(qty=1, fractions=[0.4, 0.35, 0.25],
        gains=[10, 20, 30], unit_loss=5, fee_per_unit=1)
    scenarios = result["scenarios"]
    # Either suppress the non-executable declared scenarios, or model the actual exit.
    assert scenarios is None or (
        scenarios["allTargets"]["net"] == 8 and scenarios["tp1ThenStop"]["net"] == 8
    ), "one contract sold at TP1 cannot earn TP3 or subsequently stop out"
