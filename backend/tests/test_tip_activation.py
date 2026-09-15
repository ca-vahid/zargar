"""The INTENDED active Practice configuration — geometry_gate=enforce AND
entry_pause_mode=integrity together — on the real engine (sim broker):
every automated entry path honours both controls (already-armed plans and
retries included), approved risk budgets are retained, Practice scope holds,
and a restart preserves incidents and unfinished geometry exceptions."""
import datetime as dt
from types import SimpleNamespace as NS

import pytest

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import ManagedPositionRow, Signal, TipExecutionIncident
from zargar.orders import OrderIntent
from zargar.signals.schemas import TradeSignal
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip import integrity as ig
from zargar.techniques.tip.runner import attach_tip_runner

from .conftest import make_test_config, wait_for


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    await attach_tip_runner(eng)
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    await eng.settings.set("techniques.tip.default_portfolio", pid, journal=False)
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)      # the activation values
    await eng.settings.set("techniques.tip.entry_pause_mode", "integrity", journal=False)
    await eng.settings.set("techniques.tip.budget_per_tip", 5000.0, journal=False)
    eng.positions.portfolio(pid)["cash"] = 50_000.0
    yield eng
    await eng.stop()


def _pid(eng) -> str:
    return next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")


async def _quote(eng, sym: str):
    await eng.ensure_symbol(sym)
    await wait_for(lambda: eng.quotes.get(sym) is not None and eng.quotes.get(sym).last > 0, timeout=5)
    return eng.quotes.get(sym)


async def _proposal(eng, sym: str, *, stop_pct: float = 1.5) -> dict:
    q = await _quote(eng, sym)
    px = q.last
    row = Signal(id=new_id(), source_name="Src", ticker=sym, direction="long", action="open",
                 instrument="shares", entry_price=px, target_price=round(px * 1.05, 2),
                 stop_price=round(px * (1 - stop_pct / 100.0), 2), status="verified", extraction={},
                 thesis_summary="t", confidence="explicit_call")
    sig = TradeSignal(ticker=sym, direction="long", instrument="shares", entry_price=px,
                      target_price=row.target_price, stop_price=row.stop_price, thesis_summary="t",
                      confidence="explicit_call", evidence_quotes=["t"], is_actionable=True)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return await eng.proposals.create_from_signal(row, sig, {})


async def test_every_automated_entry_path_honours_both_controls(rig):
    eng = rig
    pid = _pid(eng)
    # a clean enforced card is admitted while nothing pauses the book
    ok = await _proposal(eng, "ACTA")
    rp = ok["context"]["riskPlan"]
    assert rp["enforced"] is True and "reviewRequired" not in ok["context"] and rp["invariantOk"] is True
    out = await eng.proposals.approve(ok["id"], via="auto")
    assert out["order"] is not None and not out.get("refused")
    # a review-gated card (no quantity satisfies the budget) is refused by the geometry control
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)
    review = await _proposal(eng, "ACTB")
    assert review["context"].get("reviewRequired")
    out = await eng.proposals.approve(review["id"], via="auto")
    assert out.get("refused") and "geometry" in out["refused"] and out["proposal"]["status"] == "pending"
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.0, journal=False)      # back to risk_pct policy
    # an incident pauses the SAME book: proposal, already-armed fire and retry are all refused
    pending = await _proposal(eng, "ACTC")
    assert "reviewRequired" not in pending["context"]
    inc = await ig.open_incident(eng, kind="integrity", cause="shared_component",
                                 scope={"technique": "tip", "portfolioId": pid},
                                 evidence=[{"kind": "component", "id": "feed"}], why="feed defect")
    out = await eng.proposals.approve(pending["id"], via="auto")
    assert out.get("refused") and inc["id"][:8] in out["refused"] and out["proposal"]["status"] == "pending"
    runner = eng.plan_runners["tip"]
    ap = NS(run_id="run-armed-before", symbol="ACTD", config=NS(portfolio_id=pid, max_retries=1, mode="auto"))
    trade = NS(trigger_id="t1", status="submitting", reason=None, errors=[], entry_order_id=None, retries=0)
    res = await runner._place_with_retry(ap, trade, OrderIntent(
        portfolio_id=pid, symbol="ACTD", sec_type="STK", side="BUY", qty=1, order_type="LMT",
        limit_price=10.0, source="technique", technique_id="tip"), stage="entry")
    assert res is None and trade.status == "skipped" and inc["id"][:8] in trade.reason
    intent = OrderIntent(portfolio_id=pid, symbol="ACTC", sec_type="STK", side="BUY", qty=1,
                         order_type="LMT", limit_price=10.0, source="signal", proposal_id=pending["id"])
    rejected = {"id": "o-rejected", "status": "REJECTED_RISK", "rejectReason": "quote age 12.0s (max 10s)"}
    same = await eng.proposals._maybe_retry_stale_quote(pending, intent, rejected, via="auto")
    assert same is rejected
    # a person may still act, and protective exits still run while entries are paused
    # readiness-v1 (2026-09-15): a plain click is refused while the incident is
    # open; the person's decision is a labeled override naming that check
    plain = await eng.proposals.approve(pending["id"], via="app")
    assert plain["order"] is None and inc["id"][:8] in plain.get("refused", "")
    human = await eng.proposals.approve(pending["id"], via="app",
                                        override={"checks": ["integrity_incident"],
                                                  "reason": "test: the desk accepts trading through this incident"})
    assert human["order"] is not None
    q = await _quote(eng, "ACTE")
    pos = await eng.position_manager.adopt({
        "portfolioId": pid, "symbol": "ACTE", "direction": "long", "techniqueId": "tip",
        "entry": q.last, "risk": 1.0, "overnight": "day_only",
        "legs": [{"symbol": "ACTE", "secType": "STK", "qty": 3, "avgFill": q.last, "origin": "adoption"}],
        "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": round(q.last * 0.98, 2)}}})
    await eng.position_manager.close(pos["id"], fraction=1.0, kind="stop", reason="protective", force_market=True)
    p = eng.position_manager.get(pos["id"])
    await wait_for(lambda: p is None or p.status == "closed" or all(abs(l.qty) < 1e-9 for l in p.legs), timeout=8)


async def test_approved_risk_budget_policy_is_retained_under_enforce(rig):
    """With no fixed per-tip budget the gate sizes against the approved
    `techniques.tip.risk_pct` share of the book's equity — the existing
    policy knob, never a number invented at activation."""
    from zargar.techniques.tip import geometry as g
    eng = rig
    pid = _pid(eng)
    assert float(eng.settings.get("techniques.tip.risk_budget_per_tip", 0.0)) == 0.0
    equity = float(await eng.positions.equity(pid))
    budget, source = g.risk_budget(eng.settings, equity)
    pct = float(eng.settings.get("techniques.tip.risk_pct", 1.0))
    assert budget == round(equity * pct / 100.0, 2) and "risk_pct" in source
    card = await _proposal(eng, "ACTF")
    rp = card["context"]["riskPlan"]
    assert rp["budget"] == budget and rp["budgetSource"] == source and rp["enforced"] is True
    assert rp["qty"] * rp["unitLoss"] <= budget + 1e-6


async def test_practice_scope_holds_under_the_active_configuration(rig):
    eng = rig
    pid = _pid(eng)
    eng.positions.portfolio(pid)["kind"] = "live"
    try:
        q = await _quote(eng, "ACTG")
        _f, qty, rp, _n = await eng.proposals._pre_entry_geometry(
            underlying="ACTG", direction="long", pid=pid,
            exit_plan={"underlyingStop": round(q.last * 0.998, 2), "targets": [round(q.last * 1.05, 2)]},
            vehicle={"kind": "shares"}, sec_type="STK", symbol="ACTG", limit=q.last, qty=50,
            entry_hint=q.last, source="t", signal_id=None, analyst_run_id=None)
        assert rp is None and qty == 50
    finally:
        eng.positions.portfolio(pid)["kind"] = "sim"


async def test_restart_preserves_incident_and_unfinished_geometry_exception(rig):
    from zargar.techniques.tip.lifecycle import reconcile_geometry_exceptions
    eng = rig
    pid = _pid(eng)
    inc = await ig.open_incident(eng, kind="hold", cause="evidence_missing",
                                 scope={"technique": "tip", "portfolioId": pid},
                                 evidence=[{"kind": "position", "id": "p-x", "symbol": "ACTH"}], why="hold me")
    q = await _quote(eng, "ACTH")
    tight, wide = round(q.last * 0.99, 2), round(q.last * 0.97, 2)
    pos = await eng.position_manager.adopt({
        "portfolioId": pid, "symbol": "ACTH", "direction": "long", "techniqueId": "tip",
        "entry": q.last, "risk": 1.0, "overnight": "day_only",
        "legs": [{"symbol": "ACTH", "secType": "STK", "qty": 10, "avgFill": q.last, "origin": "adoption"}],
        "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": tight}},
        "extras": {"geometryException": {"phase": "reconcile", "tightStop": tight, "wideStop": wide,
                                         "trimQty": 5, "keepQty": 5, "qty": 10, "attemptId": "lost-ack",
                                         "history": [], "stopInForce": tight}}})
    fresh = Engine(make_test_config())              # a second engine over the same store = restart
    await fresh.start()
    try:
        await fresh.settings.set("techniques.tip.entry_pause_mode", "integrity", journal=False)
        assert inc["id"][:8] in (await ig.entry_paused(fresh, portfolio_id=pid) or "")
        restored = fresh.position_manager.get(pos["id"])
        assert restored is not None and restored.extras["geometryException"]["phase"] == "reconcile"
        assert restored.state.stop == tight, "the tight protection survives the restart"
        n = await reconcile_geometry_exceptions(fresh)
        assert n >= 1
        again = fresh.position_manager.get(pos["id"])
        assert again.state.stop == tight and again.extras["geometryException"]["phase"] in ("reconcile", "trim_pending")
        async with fresh.sf() as session:
            row = await session.get(TipExecutionIncident, inc["id"])
        assert row.status == "open"
    finally:
        await fresh.stop()
