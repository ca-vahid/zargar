"""GEOMETRY rev 2 — the wiring on the real engine (sim broker, offline):
proposal-time gate, automated-approval admission, position extras +
widen_stop, the post-fill trim-first sequence and its restart resume."""
import asyncio

import pytest

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import ManagedPositionRow, Signal
from zargar.signals.schemas import TradeSignal
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config, wait_for


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def _quote(eng, sym: str):
    await eng.ensure_symbol(sym)
    await wait_for(lambda: eng.quotes.get(sym) is not None and eng.quotes.get(sym).last > 0, timeout=5)
    return eng.quotes.get(sym)


async def _tip(eng, sym: str, px: float, *, stop_pct: float, source: str = "GeoSrc"):
    """A verified share tip persisted in `signals` (proposals carry an FK to it)."""
    row = Signal(id=new_id(), source_name=source, ticker=sym, direction="long", action="open",
                 instrument="shares", entry_price=px, target_price=round(px * 1.06, 2),
                 stop_price=round(px * (1 - stop_pct / 100.0), 2), status="verified", extraction={},
                 thesis_summary="geometry test", confidence="explicit_call")
    sig = TradeSignal(ticker=sym, direction="long", instrument="shares", entry_price=px,
                      target_price=row.target_price, stop_price=row.stop_price,
                      thesis_summary="geometry test", confidence="explicit_call",
                      evidence_quotes=["geometry test"], is_actionable=True)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return row, sig


async def _events(eng, kind: str) -> list[dict]:
    from sqlalchemy import select
    from zargar.models import Event
    async with eng.sf() as session:
        rows = (await session.execute(select(Event.payload).where(Event.type == kind)
                                      .order_by(Event.id))).scalars().all()
    return list(rows)


# ---------------------------------------------------------------- proposal-time gate
async def test_enforce_mode_finalizes_stop_and_resizes_before_entry(rig):
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 2.0, journal=False)
    q = await _quote(eng, "GEOA")
    row, sig = await _tip(eng, "GEOA", q.last, stop_pct=0.2)          # 0.2% stop: inside the 0.75% width floor
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    assert pdict is not None
    rp = pdict["context"]["riskPlan"]
    assert rp["enforced"] is True and rp["phase"] == "pre-entry"
    assert rp["finalStop"] < row.stop_price, "the stop is finalized (widened to the floor) BEFORE entry"
    assert pdict["context"]["exitPlan"]["underlyingStop"] == rp["finalStop"]
    assert rp["unitLoss"] > 0 and pdict["qty"] == rp["qty"]
    assert pdict["qty"] * rp["unitLoss"] <= 2.0 + 1e-6, "qty x unitLoss <= B on the proposal"
    assert rp["resized"] and rp["qtyRequested"] > rp["qty"]
    evs = [e for e in await _events(eng, "TipGeometryRepaired") if e.get("phase") == "pre-entry"]
    assert evs and evs[-1]["enforced"] is True and evs[-1]["resizedTo"] == pdict["qty"]
    assert evs[-1]["estimatorVersion"] and "plannedRisk" in evs[-1] and "stressRisk" in evs[-1]


async def test_shadow_mode_records_but_does_not_change_the_card(rig):
    eng = rig
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 2.0, journal=False)   # gate default = shadow
    q = await _quote(eng, "GEOB")
    row, sig = await _tip(eng, "GEOB", q.last, stop_pct=0.2)
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    rp = pdict["context"]["riskPlan"]
    assert rp["enforced"] is False and rp["resized"] is True
    assert pdict["qty"] == rp["qtyRequested"], "shadow never touches the size"
    assert pdict["context"]["exitPlan"]["underlyingStop"] == row.stop_price, "shadow never touches the stop"
    assert "reviewRequired" not in pdict["context"]


# ---------------------------------------------------------------- admission
async def test_review_gated_card_never_auto_approves_but_a_person_may(rig):
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)   # nothing fits
    q = await _quote(eng, "GEOC")
    row, sig = await _tip(eng, "GEOC", q.last, stop_pct=1.5)
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    assert pdict["context"]["reviewRequired"] and pdict["context"]["riskPlan"]["qty"] == 0
    assert pdict["qty"] >= 1, "the card keeps a size for the human to judge"
    out = await eng.proposals.approve(pdict["id"], via="auto")
    assert out.get("refused") and out["order"] is None
    assert out["proposal"]["status"] == "pending" and "geometry review" in out["proposal"]["context"]["autoGate"]
    paused = await _events(eng, "TipAutoPaused")
    assert any(p.get("proposalId") == pdict["id"] for p in paused)
    human = await eng.proposals.approve(pdict["id"], via="app")          # the click IS the review
    assert human["order"] is not None and human["proposal"]["status"] in ("executed", "failed")


async def test_auto_path_leaves_review_gated_cards_pending(rig):
    """The unattended auto-approval loop reads context.reviewRequired as a gate."""
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)
    q = await _quote(eng, "GEOD")
    row, sig = await _tip(eng, "GEOD", q.last, stop_pct=1.5)
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    from zargar.models import Proposal
    async with eng.sf() as session:
        prow = await session.get(Proposal, pdict["id"])
    assert prow.status == "pending" and (prow.context or {}).get("reviewRequired")


# ---------------------------------------------------------------- positions: extras + widen_stop
async def _adopt_shares(eng, sym: str, *, qty: int, stop: float, extras: dict | None = None) -> dict:
    q = await _quote(eng, sym)
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    spec = {"portfolioId": pid, "symbol": sym, "direction": "long", "techniqueId": "tip",
            "entry": q.last, "risk": max(q.last - stop, 0.01),
            "legs": [{"symbol": sym, "secType": "STK", "qty": qty, "avgFill": q.last, "origin": "adoption"}],
            "overnight": "day_only", "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": stop}},
            "extras": extras or {}}
    return await eng.position_manager.adopt(spec)


async def test_set_extras_persists_and_widen_stop_is_the_only_widening_path(rig):
    eng = rig
    mgr = eng.position_manager
    q = await _quote(eng, "GEOE")
    tight = round(q.last * 0.99, 2)
    pos = await _adopt_shares(eng, "GEOE", qty=10, stop=tight, extras={"riskPlan": {"plannedRisk": 10.0}})
    assert pos["extras"]["riskPlan"]["plannedRisk"] == 10.0
    await mgr.set_extras(pos["id"], {"geometryException": {"phase": "reconcile"}})
    async with eng.sf() as session:
        rowdb = await session.get(ManagedPositionRow, pos["id"])
    assert rowdb.config["extras"]["geometryException"]["phase"] == "reconcile"
    assert rowdb.config["extras"]["riskPlan"]["plannedRisk"] == 10.0
    # set_policy may only TIGHTEN the live stop
    wider = round(q.last * 0.97, 2)
    await mgr.set_policy(pos["id"], {"timeframe": "15m", "stop": {"kind": "fixed", "price": wider}})
    assert mgr.get(pos["id"]).state.stop == tight
    with pytest.raises(ValueError):
        await mgr.widen_stop(pos["id"], round(q.last * 0.995, 2), reason="not wider")
    out = await mgr.widen_stop(pos["id"], wider, reason="trim confirmed")
    p = mgr.get(pos["id"])
    assert p.state.stop == wider and p.policy["stop"]["price"] == wider and out["state"]["stop"] == wider
    changed = await _events(eng, "ManagedPositionPolicyChanged")
    assert any((c.get("widened") or {}).get("to") == wider for c in changed)


# ---------------------------------------------------------------- post-fill exception
async def test_trim_first_sequence_widens_only_after_the_trim_fills(rig):
    from zargar.techniques.tip.lifecycle import run_geometry_exception
    eng = rig
    mgr = eng.position_manager
    q = await _quote(eng, "GEOF")
    tight, wide = round(q.last * 0.99, 2), round(q.last * 0.97, 2)
    state = {"phase": "trim_pending", "tightStop": tight, "wideStop": wide, "trimQty": 5, "keepQty": 5,
             "qty": 10, "unitLossAtWide": round(q.last * 0.03, 4), "budget": round(q.last * 0.03 * 5, 4),
             "why": "test", "history": [], "stopInForce": tight}
    pos = await _adopt_shares(eng, "GEOF", qty=10, stop=tight, extras={"geometryException": state})
    assert mgr.get(pos["id"]).state.stop == tight
    final = await run_geometry_exception(eng, pos["id"], state)
    assert final["phase"] == "widened" and final.get("applied") is True, final
    assert [h["event"] for h in final["history"]] == ["trim_submitted", "trim_filled"]
    p = mgr.get(pos["id"])
    assert p.state.stop == wide and sum(abs(l.qty) for l in p.open_legs) == 5
    assert p.extras["geometryException"]["phase"] == "widened"
    trims = [x for x in p.exits if x.get("kind") == "geometry_trim"]
    assert trims and trims[-1]["status"] == "FILLED"


async def test_restart_resume_checks_the_trim_order_instead_of_resubmitting(rig):
    from zargar.techniques.tip.lifecycle import reconcile_geometry_exceptions
    eng = rig
    mgr = eng.position_manager
    q = await _quote(eng, "GEOG")
    tight, wide = round(q.last * 0.99, 2), round(q.last * 0.97, 2)
    pos = await _adopt_shares(eng, "GEOG", qty=10, stop=tight)
    # a trim that was submitted and filled before the "restart"
    await mgr.close(pos["id"], fraction=0.5, kind="geometry_trim", reason="pre-restart trim")
    p = mgr.get(pos["id"])
    rec = next(x for x in reversed(p.exits) if x.get("kind") == "geometry_trim")
    await wait_for(lambda: rec.get("status") == "FILLED", timeout=5)
    exits_before = len(p.exits)
    await mgr.set_extras(pos["id"], {"geometryException": {
        "phase": "trim_pending", "tightStop": tight, "wideStop": wide, "trimQty": 5, "keepQty": 5,
        "qty": 10, "trimOrderId": rec["orderId"], "history": [], "stopInForce": tight}})
    n = await reconcile_geometry_exceptions(eng)
    assert n == 1
    p = mgr.get(pos["id"])
    assert p.extras["geometryException"]["phase"] == "widened" and p.state.stop == wide
    assert len(p.exits) == exits_before, "the restart resumed from the order, it did not trim again"
