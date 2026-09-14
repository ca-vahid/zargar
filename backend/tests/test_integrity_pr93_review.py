"""Independent PR 93 boundaries; mocks only, no database/provider/runtime."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.execution import planrunner
from zargar.techniques.tip import integrity as ig
from zargar.techniques.tip.runner import TipRunner


async def test_integrity_lookup_failure_cannot_admit_automatic_entry(monkeypatch):
    eng = NS(settings={"techniques.tip.entry_pause_mode": "integrity"})
    monkeypatch.setattr(ig, "list_incidents", AsyncMock(side_effect=RuntimeError("store unavailable")))
    try:
        result = await ig.admission(eng, portfolio_id="practice", entry_path="proposal")
    except RuntimeError:
        return  # Propagating a refusal-producing store error is also safe.
    assert result, "An unavailable incident store must not mean no open incidents"


def test_missing_quote_and_budget_proof_are_not_a_valid_fast_loss():
    verdict = ig.classify_fast_stop({
        "openedMs": 100_000,
        "exits": [{"kind": "stop", "status": "FILLED", "ts": 160_000}],
        "extras": {"riskPlan": {"enforced": True}},
    })
    assert verdict["verdict"] == "evidence_missing", verdict


def test_confirmation_word_is_not_structured_premium_exit_evidence():
    verdict = ig.classify_fast_stop({
        "openedMs": 100_000,
        "exits": [{"kind": "premium_stop", "status": "FILLED", "ts": 160_000,
                   "reason": "premium stop NOT confirmed; missing observation"}],
        "extras": {"riskPlan": {"enforced": True, "invariantOk": True,
                                "quote": {"delayed": False}}},
    })
    assert verdict["verdict"] == "evidence_missing", verdict


async def test_session_rollover_without_revalidation_does_not_release():
    inc = {"cause": "repeated_pre_entry_failure", "evidence": [],
           "openedAt": (dt.datetime.now(dt.UTC) - dt.timedelta(days=2)).isoformat()}
    valid, _ = await ig._validate_release(NS(), inc, "")
    assert not valid, "The configured release criterion also requires a successful path validation"


async def test_unresolved_evidence_reference_does_not_validate_itself():
    inc = {"cause": "evidence_missing", "evidence": [
        {"kind": "proof", "id": "does-not-exist", "valid": True}]}
    valid, _ = await ig._validate_release(NS(), inc, "")
    assert not valid, "An API-supplied boolean is not validation of the referenced evidence"


async def test_transport_retry_rechecks_incident_before_second_order(monkeypatch):
    paused = False
    orders = []

    async def admission(*_args, **_kwargs):
        return "new incident during retry" if paused else None

    async def place(_intent):
        nonlocal paused
        orders.append(_intent)
        if len(orders) == 1:
            paused = True
            raise ConnectionError("timeout")
        return {"id": "second-order", "status": "SUBMITTED"}

    monkeypatch.setattr(ig, "admission", admission)
    monkeypatch.setattr(planrunner.asyncio, "sleep", AsyncMock())
    runner = object.__new__(TipRunner)
    runner.engine = NS(orders=NS(place=place), journal=NS(append=AsyncMock()))
    runner._log = lambda *_args, **_kwargs: None
    runner._persist = AsyncMock()
    runner._publish = lambda *_args, **_kwargs: None
    ap = NS(run_id="run", symbol="X", config=NS(portfolio_id="practice", max_retries=1))
    trade = NS(trigger_id="t", status="submitting", reason=None, errors=[], retries=0)
    result = await runner._place_with_retry(ap, trade, object(), stage="entry")
    assert len(orders) == 1 and result is None, "Incident opened before retry, but a second entry was submitted"


async def test_proposal_only_incident_does_not_cancel_armed_entries():
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def execute(self, _query):
            return NS(scalars=lambda: NS(all=list))

    armed = NS(cancel_working_entries=AsyncMock(return_value=1))
    eng = NS(sf=Session, plan_runners={"tip": armed})
    await ig._cancel_resting_entries(eng, {"id": "incident", "scope": {
        "technique": "tip", "portfolioId": "practice", "entryPath": "proposal"}})
    armed.cancel_working_entries.assert_not_awaited()
