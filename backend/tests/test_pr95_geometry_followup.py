"""Geometry follow-up: uncertain trim ACK and spread admission, all I/O fake."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from zargar.approvals.proposals import ProposalService
from zargar.models import Proposal
from zargar.techniques.tip import integrity, lifecycle

from .test_geometry_pr91_review import _exception_engine, _state


async def test_attempt_without_order_ack_is_not_submitted_again(monkeypatch):
    # The attempt was durable; broker acceptance happened before the process
    # could record the returned order ID. An empty local exit index does not
    # prove the venue received nothing. Reconcile/hold before another close.
    state = _state(attemptId="accepted-but-ack-lost")
    eng = _exception_engine(state)
    monkeypatch.setattr(lifecycle, "_order_row", AsyncMock(return_value={"status": "FILLED", "filledQty": 5}))
    await lifecycle.run_geometry_exception(eng, "position", state)
    assert eng.position_manager.close.await_count == 0, "durable attempted submission with an unknown ACK must not create another trim"


async def test_unsupported_spread_review_card_cannot_auto_open(monkeypatch):
    row = Proposal(id="proposal", signal_id="signal", portfolio_id="book", symbol="X",
                   sec_type="SPREAD", side="BUY", qty=1, order_type="LMT", limit_price=1,
                   status="pending", bracket=None, context={"techniqueId": "tip",
                   "reviewRequired": "geometry gate does not cover spread vehicles — human decision only",
                   "vehicle": {"underlying": "X", "direction": "long", "legs": []}})

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, key):
            return row

        async def commit(self):
            pass

    eng = NS(settings={"techniques.tip.geometry_gate": "enforce"}, sf=Session,
             positions=NS(portfolio=lambda _: {"id": "book", "kind": "sim"}),
             bus=NS(publish=Mock()), journal=NS(append=AsyncMock()))
    monkeypatch.setattr(integrity, "admission", AsyncMock(return_value=None))
    opening = AsyncMock(return_value={"id": "opened-position"})
    monkeypatch.setattr(lifecycle, "open_spread", opening)
    out = await ProposalService(eng).approve(row.id, via="auto")
    assert opening.await_count == 0, "a geometry review-only spread must not reach the money path"
    assert out.get("refused") and out["proposal"]["status"] == "pending"


def test_shadow_resize_is_not_reported_as_actual_planned_risk():
    # The actual trade kept 100 shares and its $99 stop: $100 planned risk.
    # Shadow WOULD have resized to 50 shares. A real $100 loss is not $50
    # execution slippage merely because the hypothetical plan was smaller.
    position = {"entry": 100.0, "risk": 1.0,
                "policy": {"stop": {"kind": "fixed", "price": 99.0}},
                "legs": [{"symbol": "X", "secType": "STK", "qty": 100, "avgFill": 100.0}],
                "realizedPnl": -100.0,
                "extras": {"riskPlan": {"mode": "shadow", "enforced": False,
                            "qtyRequested": 100, "qty": 50, "plannedRisk": 50.0,
                            "stressRisk": 5000.0, "resized": True}}}
    accounting = lifecycle.position_risk_accounting(position)
    assert accounting.get("plannedRisk") != 50.0, accounting
    assert "slippageVsPlanned" not in accounting or accounting["slippageVsPlanned"] == 0, accounting
