"""Full incident state and protection identity beyond the AP85 examples."""
from unittest.mock import AsyncMock
import pytest
from zargar.models import Proposal
from zargar.techniques.tip import integrity as ig
from .test_proposal_readiness import rig, _share_tip, _pid  # noqa: F401


@pytest.mark.parametrize("scenario", ["revision", "hidden_incident"])
async def test_override_binds_full_real_incident_state(rig, monkeypatch, scenario):
    eng = rig
    card = await _share_tip(eng, "FINALINC")
    scope = {"technique": "tip", "portfolioId": _pid(eng), "entryPath": "proposal"}
    if scenario == "hidden_incident":
        await ig.open_incident(eng, kind="integrity", cause="shared_component", scope=scope,
            evidence=[{"kind": "component", "id": "older-unreviewed-component"}], why="Older separate failure")
    inc = await ig.open_incident(eng, kind="integrity", cause="shared_component", scope=scope,
        evidence=[{"kind": "component", "id": "shown-component"}], why="Displayed failure")
    shown = (await eng.proposals.revalidate(card["id"]))["readiness"]
    assert {b["code"] for b in shown["blockers"]} == {"integrity_incident"}
    if scenario == "revision":
        newer = await ig.append_evidence(eng, inc["id"], {"kind": "component", "id": "new-severe-evidence"})
        assert newer["revision"] > inc["revision"]
    spy = AsyncMock(wraps=eng.orders.place)
    monkeypatch.setattr(eng.orders, "place", spy)
    await eng.proposals.approve(card["id"], expected=shown["fingerprint"],
        override={"checks": ["integrity_incident"], "reason": "Accept only the incident evidence displayed on this card."})
    assert spy.await_count == 0, f"order placed despite unacknowledged {scenario}"


async def test_changed_exit_policy_after_assess_cannot_be_claimed(rig, monkeypatch):
    eng = rig
    card = await _share_tip(eng, "FINALPLAN")
    shown = (await eng.proposals.revalidate(card["id"]))["readiness"]
    assert shown["state"] == "ready"
    real_assess = eng.proposals.assess
    async def other_writer(*args, **kwargs):
        result = await real_assess(*args, **kwargs)
        async with eng.sf() as session:
            row = await session.get(Proposal, card["id"])
            row.context = {**row.context, "exitPlan": {**row.context.get("exitPlan", {}), "maxHoldSessions": 999}}
            await session.commit()
        return result
    monkeypatch.setattr(eng.proposals, "assess", other_writer)
    spy = AsyncMock(wraps=eng.orders.place)
    monkeypatch.setattr(eng.orders, "place", spy)
    await eng.proposals.approve(card["id"], expected=shown["fingerprint"])
    assert spy.await_count == 0, "changed exit policy was accepted because the stored fingerprint was not recomputed"
