"""Independent submission boundaries; use the disposable Codex database."""
import pytest
from unittest.mock import AsyncMock
from zargar.models import Proposal
from zargar.techniques.tip import integrity as ig
from zargar.approvals import readiness as rd
from .test_proposal_readiness import rig, _share_tip  # noqa: F401


@pytest.mark.parametrize("last_check", [
    "execution-integrity state unavailable: database disconnected",
    "execution-integrity incident NEW-INCIDENT: a different failure",
])
async def test_incident_override_cannot_accept_new_or_unavailable_state(rig, monkeypatch, last_check):
    eng = rig
    card = await _share_tip(eng, "OVONE")
    old = "execution-integrity incident ORIGINAL: known reviewed issue"
    monkeypatch.setattr(ig, "admission", AsyncMock(return_value=old))
    shown = (await eng.proposals.revalidate(card["id"]))["readiness"]
    assert {b["code"] for b in shown["blockers"]} == {"integrity_incident"}
    monkeypatch.setattr(ig, "admission", AsyncMock(side_effect=[old, last_check]))
    real_place = eng.orders.place
    spy = AsyncMock(wraps=real_place)
    monkeypatch.setattr(eng.orders, "place", spy)
    await eng.proposals.approve(card["id"], expected=shown["fingerprint"],
        override={"checks": ["integrity_incident"], "reason": "Review accepts only the original known incident."})
    assert spy.await_count == 0, "original incident override bypassed a new non-acknowledged integrity result"


async def test_plan_changed_after_assessment_cannot_submit_another_stop(rig, monkeypatch):
    eng = rig
    card = await _share_tip(eng, "OVTWO")
    shown = (await eng.proposals.revalidate(card["id"]))["readiness"]
    assert shown["state"] == "ready"
    real_assess = eng.proposals.assess
    async def competing_refresh(*args, **kwargs):
        result = await real_assess(*args, **kwargs)
        # Another writer commits a different protection plan between assessment and claim.
        async with eng.sf() as session:
            row = await session.get(Proposal, card["id"])
            row.bracket = {**row.bracket, "stop_loss": shown["plan"]["finalStop"] * 0.8}
            await session.commit()
        return result
    monkeypatch.setattr(eng.proposals, "assess", competing_refresh)
    real_place = eng.orders.place
    spy = AsyncMock(wraps=real_place)
    monkeypatch.setattr(eng.orders, "place", spy)
    await eng.proposals.approve(card["id"], expected=shown["fingerprint"])
    assert spy.await_count == 0, "approval used a changed database bracket without rechecking the approved plan"


@pytest.mark.parametrize("change", ["exposure", "incident"])
def test_fingerprint_binds_risk_and_incident_identity(change):
    plan = {"finalStop": 90, "planQty": 1, "unitLoss": 10, "plannedRisk": 10, "riskBudget": 20}
    old = [rd.blocker("integrity_incident", "incident original revision 1")]
    new_plan = {**plan, "unitLoss": 19, "plannedRisk": 19} if change == "exposure" else plan
    new_blocks = [rd.blocker("integrity_incident", "incident replacement revision 2")] if change == "incident" else old
    assert rd.fingerprint(plan, old) != rd.fingerprint(new_plan, new_blocks), f"changed {change} was not bound"


async def test_manual_submission_without_displayed_plan_token_refuses(rig, monkeypatch):
    eng = rig
    card = await _share_tip(eng, "OVTHREE")
    spy = AsyncMock(wraps=eng.orders.place)
    monkeypatch.setattr(eng.orders, "place", spy)
    await eng.proposals.approve(card["id"], via="telegram")
    assert spy.await_count == 0, "manual approval submitted without evidence of which plan the person saw"


async def test_half_action_submits_half_of_displayed_plan(rig):
    eng = rig
    card = await _share_tip(eng, "OVFOUR")
    shown = (await eng.proposals.revalidate(card["id"]))["readiness"]
    assert shown["state"] == "ready" and shown["plan"]["qty"] >= 2
    result = await eng.proposals.approve(card["id"], expected=shown["fingerprint"], half=True)
    assert not result.get("refused"), result.get("refused")
    assert result["order"]["qty"] == max(1, shown["plan"]["qty"] // 2)
