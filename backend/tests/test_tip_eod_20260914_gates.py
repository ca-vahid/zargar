"""EOD gate boundaries; real producers with fake services, no DB or paid calls."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from zargar.approvals.proposals import ProposalService
from zargar.clock import now_ms
from zargar.models import Execution, ManagedPositionRow
from zargar.techniques.tip import geometry, integrity


@pytest.mark.parametrize("greeks_reason", [
    "missing delta — no estimate invented",
    "delta is 901s old (max 900s) — no estimate invented",
])
def test_actual_missing_or_stale_delta_risk_reason_counts_as_systemic(greeks_reason):
    _, plan = geometry.plan_risk(
        mode="enforce", direction="long", vehicle="option", entry_ref=100.0,
        exit_plan={"underlyingStop": 98.0, "targets": [105.0]}, bars=[], settings={},
        limit=2.0, qty_requested=1, multiplier=100, option_type="call", delta=None,
        greeks_meta={"reason": greeks_reason}, budget=100.0, budget_source="test")
    assert plan.reviewRequired and not plan.invariantOk
    assert integrity.systemic_pre_entry_reason(plan.reviewRequired), (
        "the producer's 'no risk estimate' prefix hid an unavailable/stale evidence failure")


def test_actual_stale_underlying_reason_counts_as_systemic():
    reason = "underlying reference quote is 301s old (max 300s)"
    assert integrity.systemic_pre_entry_reason(reason), (
        "the quote producer says 'old', while the incident classifier only recognizes 'stale'")


async def test_valid_share_geometry_supplies_the_evidence_its_classifier_requires():
    quote = NS(last=100.0, bid=99.99, ask=100.0, source="sip", delayed=False,
               ts=now_ms(), source_ts=now_ms())
    eng = NS(settings={"techniques.tip.risk_budget_per_tip": 100.0},
             feed=type("SimQuoteFeed", (), {})(), quotes=NS(get=lambda _symbol: quote),
             positions=NS(equity=AsyncMock(return_value=10_000.0)))
    _, plan = await ProposalService(eng)._compute_risk_plan(
        mode="enforce", underlying="X", direction="long", pid="practice",
        exit_plan={"underlyingStop": 99.0, "targets": [105.0]},
        vehicle={"kind": "shares"}, sec_type="STK", symbol="X", limit=100.0,
        qty=10, entry_hint=100.0)
    assert plan.enforced and plan.invariantOk and not plan.reviewRequired
    verdict, reason = integrity._risk_plan_evidence(plan.to_dict())
    assert verdict == "valid", (
        "a valid fresh-quoted share plan is later treated as missing evidence: " + reason)


async def test_incident_accepts_its_own_option_execution_as_bound_proof():
    contract = "SPY260930P00739000"
    execution = NS(id="fill", portfolio_id="practice", order_id="owned-order",
                   symbol=contract, side="SELL", qty=1.0, price=2.0,
                   ts=dt.datetime.now(dt.UTC))
    position = NS(symbol="SPY", portfolio_id="practice",
                  legs=[{"symbol": contract, "entryOrderId": "entry-order"}],
                  state={"exits": [{"orderId": "owned-order", "leg": contract}]})

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, model, ident):
            if model is Execution and ident == "fill":
                return execution
            if model is ManagedPositionRow and ident == "position":
                return position
            return None

    incident = {"scope": {"technique": "tip", "portfolioId": "practice", "symbol": "SPY"},
                "evidence": [{"kind": "position", "id": "position", "symbol": "SPY"}]}
    valid, reason, _ = await integrity._resolve_proof_meta(
        NS(sf=Session), {"ref": "execution:fill"}, incident)
    assert valid is True, (
        "the option execution belongs to the incident's book, position and exit order: " + reason)
