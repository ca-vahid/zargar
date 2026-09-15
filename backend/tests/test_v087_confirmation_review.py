"""Exercise actual acknowledged overrides and complete adoption snapshot use."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from zargar.techniques.tip import integrity as ig, lifecycle
from .test_proposal_readiness import rig, _share_tip, _pid  # noqa: F401


@pytest.mark.parametrize("changed", [False, True])
async def test_explicit_incident_set_acknowledgment(rig, monkeypatch, changed):
    eng = rig
    card = await _share_tip(eng, "ACKTEST")
    inc = await ig.open_incident(eng, kind="integrity", cause="shared_component",
        scope={"technique": "tip", "portfolioId": _pid(eng), "entryPath": "proposal"},
        evidence=[{"kind": "component", "id": "ack-component"}], why="Known issue")
    shown = (await eng.proposals.revalidate(card["id"]))["readiness"]
    identity = shown["blockers"][0]["identity"]
    assert identity["incidents"][0]["revision"] == inc["revision"]
    if changed:
        await ig.append_evidence(eng, inc["id"], {"kind": "component", "id": "new-evidence"})
    spy = AsyncMock(wraps=eng.orders.place)
    monkeypatch.setattr(eng.orders, "place", spy)
    out = await eng.proposals.approve(card["id"], expected=shown["fingerprint"], override={
        "checks": ["integrity_incident"], "acknowledged": [identity],
        "reason": "Accept precisely the complete incident evidence shown."})
    assert spy.await_count == (0 if changed else 1), out


async def test_structured_incident_read_failure_is_not_overridable(rig, monkeypatch):
    eng = rig
    card = await _share_tip(eng, "ACKFAIL")
    await ig.open_incident(eng, kind="integrity", cause="shared_component",
        scope={"technique": "tip", "portfolioId": _pid(eng), "entryPath": "proposal"},
        evidence=[{"kind": "component", "id": "known-component"}], why="Known issue")
    # The initial prose lookup succeeds; the subsequent complete-state lookup fails.
    monkeypatch.setattr(ig, "applicable_incidents", AsyncMock(side_effect=OSError("store unavailable")))
    shown = (await eng.proposals.revalidate(card["id"]))["readiness"]
    assert any(b["code"] == "integrity_unavailable" and not b["overridable"] for b in shown["blockers"]), shown


async def test_adoption_uses_claimed_vehicle_not_mutable_context(monkeypatch):
    eng = NS(settings={}, position_manager=object(), ensure_symbol=AsyncMock(),
             quotes={"AAPL": NS(last=100), "MSFT": NS(last=100)}, journal=NS(append=AsyncMock()),
             feed=type("SimQuoteFeed", (), {})())
    frozen_plan = {"underlyingStop": 90, "targets": [110], "fractions": [1], "maxHoldSessions": 5}
    proposal = {"id": "p", "symbol": "AAPL261016C00100000", "secType": "OPT", "portfolioId": "practice",
        "context": {"techniqueId": "tip", "vehicle": {"underlying": "MSFT", "optionType": "put"},
                    "exitPlan": {}, "approvedPlan": {"exitPlan": frozen_plan,
                       "vehicle": {"underlying": "AAPL", "optionType": "call"}, "riskPlan": {"finalStop": 90}}}}
    monkeypatch.setattr(lifecycle, "_order_row", AsyncMock(return_value={"status": "FILLED", "filledQty": 1, "avgFillPrice": 1}))
    def captured(*args, **kwargs):
        raise RuntimeError("captured before position creation")
    monkeypatch.setattr(lifecycle, "check_exit_geometry", captured)
    with pytest.raises(RuntimeError, match="captured"):
        await lifecycle.adopt_when_filled(eng, proposal, {"id": "order"})
    assert eng.ensure_symbol.await_args.args[0] == "AAPL", "adoption borrowed the mutable vehicle instead of the approved snapshot"
