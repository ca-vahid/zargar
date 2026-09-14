"""Independent PR91 boundaries. Fake services only; no broker or database I/O."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.approvals.proposals import ProposalService
from zargar.techniques.tip import lifecycle


def _proposal_service(*, kind="sim", delta_asof=1):
    settings = {"techniques.tip.geometry_gate": "enforce",
                "techniques.tip.risk_budget_per_tip": 50.0}
    underlying = NS(last=100.0, ask=102.0, source="sip", delayed=False)
    option = NS(last=2.0, ask=2.0, source="opra", delayed=False)
    eng = NS(settings=settings, ensure_symbol=AsyncMock(),
             quotes=NS(get=lambda symbol: underlying if symbol == "X" else option),
             feed=type("SimQuoteFeed", (), {})(),
             positions=NS(equity=AsyncMock(return_value=10_000),
                          portfolio=lambda _: {"id": "book", "kind": kind}),
             options=NS(snapshot_cached=lambda _: {"greeks": {"delta": 0.5},
                                                   "greeksLive": True,
                                                   "greeksFieldAsOf": {"delta": delta_asof},
                                                   "asOf": delta_asof}),
             journal=NS(append=AsyncMock()))
    return ProposalService(eng)


async def _pre(service, *, sec_type="OPT"):
    return await service._pre_entry_geometry(
        underlying="X", direction="long", pid="book",
        exit_plan={"underlyingStop": 99.0, "targets": [105.0]},
        vehicle={"kind": "option", "optionType": "call", "multiplier": 100}
        if sec_type == "OPT" else {"kind": "shares"},
        sec_type=sec_type, symbol="Xopt" if sec_type == "OPT" else "X",
        limit=2.0 if sec_type == "OPT" else 102.0, qty=50,
        entry_hint=100.0, source="test", signal_id="signal", analyst_run_id="run")


async def test_stale_delta_cannot_authorize_enforced_risk(monkeypatch):
    _, _, risk, _ = await _pre(_proposal_service(delta_asof=1))
    assert risk.reviewRequired, risk.to_dict()


async def test_missing_enforced_risk_plan_cannot_auto_admit():
    service = _proposal_service()
    _, _, refusal = await service._admit_geometry(
        {"id": "proposal", "portfolioId": "book", "secType": "OPT",
         "symbol": "Xopt", "context": {"techniqueId": "tip"}},
        limit=2.0, qty=50, via="auto")
    assert refusal, "enforce mode must not treat missing risk evidence as admission"


async def test_share_budget_uses_executable_limit_not_lower_last_trade():
    final, qty, risk, _ = await _pre(_proposal_service(), sec_type="STK")
    assert qty * (102.0 - final["underlyingStop"]) <= risk.budget, risk.to_dict()


async def test_practice_geometry_cannot_resize_live_book():
    original_stop, original_qty = 99.0, 50
    final, qty, risk, _ = await _pre(_proposal_service(kind="live"), sec_type="STK")
    assert (risk is None or not risk.enforced) and qty == original_qty, risk.to_dict() if risk else None
    assert final["underlyingStop"] == original_stop


def _exception_engine(state, *, existing_exit=False):
    p = NS(id="position", symbol="X", portfolio_id="book", entry=100.0,
           technique="tip", status="open", attention=[], extras={"geometryException": state},
           open_legs=[NS(symbol="X", sec_type="STK", qty=10, multiplier=1)],
           exits=([{"kind": "geometry_trim", "orderId": "already-filled", "status": "FILLED",
                    "qty": 5, "filledQty": 5}] if existing_exit else []))

    async def set_extras(_, patch):
        p.extras.update(patch)

    async def close(*args, **kwargs):
        p.exits.append({"kind": "geometry_trim", "orderId": "second-trim", "status": "FILLED",
                        "qty": 5, "filledQty": 5})

    mgr = NS(get=lambda _: p, _pos={p.id: p}, close=AsyncMock(side_effect=close),
             set_extras=AsyncMock(side_effect=set_extras), widen_stop=AsyncMock())
    return NS(position_manager=mgr, journal=NS(append=AsyncMock()))


def _state(**patch):
    return {"phase": "trim_pending", "tightStop": 99.0, "wideStop": 97.0,
            "trimQty": 5, "keepQty": 5, "qty": 10, "unitLossAtWide": 3.0,
            "budget": 15.0, "why": "review", "history": [], "stopInForce": 99.0, **patch}


async def test_filled_trim_before_geometry_stamp_must_not_be_submitted_again(monkeypatch):
    state = _state()
    eng = _exception_engine(state, existing_exit=True)
    monkeypatch.setattr(lifecycle, "_order_row", AsyncMock(return_value={"status": "FILLED", "filledQty": 5}))
    await lifecycle.run_geometry_exception(eng, "position", state)
    assert eng.position_manager.close.await_count == 0, "restart must recover the existing trim or hold, never trim twice"


async def test_timed_out_known_trim_is_reconciled_when_it_later_fills(monkeypatch):
    state = _state(phase="reconcile", trimOrderId="eventually-filled")
    eng = _exception_engine(state)
    lookup = AsyncMock(return_value={"status": "FILLED", "filledQty": 5})
    monkeypatch.setattr(lifecycle, "_order_row", lookup)
    await lifecycle.reconcile_geometry_exceptions(eng)
    assert lookup.await_count == 1, "unknown outcome with a durable order ID must be reconciled"
    assert eng.position_manager.close.await_count == 0

