"""TMR-02 must reach the actual final-plan card, not just the pure helper."""
from .test_proposal_readiness import rig, _share_tip  # noqa: F401
from zargar.techniques.tip import execcost


async def test_qualified_card_contains_execution_cost(rig):
    eng = rig
    card = await _share_tip(eng, "COSTWIRE")
    direct = execcost.diagnose(eng, symbol="COSTWIRE", qty=1, sec_type="STK", multiplier=1)
    assert direct["status"] == "known", direct
    result = await eng.proposals.revalidate(card["id"])
    rp = result["proposal"]["context"]["riskPlan"]
    assert rp.get("execCost", {}).get("status") == "known", "qualified cost calculation did not reach the persisted risk plan"
    assert result["readiness"]["plan"]["execCost"]["roundTrip"] is not None
    assert result["order"] is None
