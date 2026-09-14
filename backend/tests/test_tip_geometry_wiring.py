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
    await eng.settings.set("techniques.tip.budget_per_tip", 5000.0, journal=False)
    q = await _quote(eng, "GEOA")
    # deterministic at ANY sim price: read the plan's own unit loss and requested
    # quantity from a shadow pass, then set the enforce budget to fit exactly half
    row0, sig0 = await _tip(eng, "GEOA", q.last, stop_pct=0.2)
    shadow = await eng.proposals.create_from_signal(row0, sig0, {})
    rp0 = shadow["context"]["riskPlan"]
    assert rp0["enforced"] is False and rp0["qtyRequested"] >= 2 and rp0["unitLoss"] > 0
    # a 20% margin absorbs the sim's tick drift between the two passes: half the
    # requested quantity x 1.2 still fits at least one unit and stays under the request
    budget = round(rp0["unitLoss"] * max(1, rp0["qtyRequested"] // 2) * 1.2, 4)
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", budget, journal=False)
    row, sig = await _tip(eng, "GEOA", q.last, stop_pct=0.2)          # 0.2% stop: inside the 0.75% width floor
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    assert pdict is not None
    rp = pdict["context"]["riskPlan"]
    assert rp["enforced"] is True and rp["phase"] == "pre-entry"
    assert rp["finalStop"] < row.stop_price, "the stop is finalized (widened to the floor) BEFORE entry"
    assert pdict["context"]["exitPlan"]["underlyingStop"] == rp["finalStop"]
    assert rp["unitLoss"] > 0 and pdict["qty"] == rp["qty"]
    assert pdict["qty"] * rp["unitLoss"] <= budget + 1e-6, "qty x unitLoss <= B on the proposal"
    assert rp["quote"]["entryRefBasis"] == "limit" and rp["entryRef"] == pdict["limitPrice"], "shares are sized at the executable limit"
    assert pdict["bracket"]["stop_loss"] == rp["finalStop"], "the bracket carries the FINAL stop"
    assert rp["resized"] and rp["qtyRequested"] > rp["qty"]
    evs = [e for e in await _events(eng, "TipGeometryRepaired") if e.get("phase") == "pre-entry"]
    assert evs and evs[-1]["enforced"] is True and evs[-1]["resizedTo"] == pdict["qty"]
    assert evs[-1]["estimatorVersion"] and "plannedRisk" in evs[-1] and "stressRisk" in evs[-1]


async def test_shadow_mode_records_but_does_not_change_the_card(rig):
    eng = rig
    # deterministic regardless of the sim's per-process price: a one-cent risk
    # budget fits no share at any price, so the shadow plan ALWAYS resizes
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)   # gate default = shadow
    await eng.settings.set("techniques.tip.budget_per_tip", 5000.0, journal=False)
    q = await _quote(eng, "GEOB")
    row, sig = await _tip(eng, "GEOB", q.last, stop_pct=0.2)
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    rp = pdict["context"]["riskPlan"]
    assert rp["enforced"] is False and rp["resized"] is True and rp["qty"] == 0
    assert pdict["qty"] == rp["qtyRequested"] and pdict["qty"] >= 1, "shadow never touches the size"
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


# ---------------------------------------------------------------- reviewer integration coverage (G91-01/02/03/05/06)
async def test_enforce_mode_computation_failure_is_review_gated_not_admitted(rig, monkeypatch):
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)

    async def boom(self, **kw):
        raise RuntimeError("bars provider down")
    monkeypatch.setattr(type(eng.proposals), "_compute_risk_plan", boom)
    q = await _quote(eng, "GEOH")
    row, sig = await _tip(eng, "GEOH", q.last, stop_pct=1.5)
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    assert pdict is not None and "risk evidence unavailable" in pdict["context"]["reviewRequired"]
    assert pdict["context"]["riskPlan"]["enforced"] is True
    out = await eng.proposals.approve(pdict["id"], via="auto")
    assert out.get("refused") and out["order"] is None and out["proposal"]["status"] == "pending"


async def test_final_admission_refusal_reverts_an_automated_approval(rig, monkeypatch):
    """The card passed at creation AND at the approval head; the plan fails
    only at final submission (the budget is cut between the two checks) — the
    automated approval is reverted to pending, no order exists (G91-01: the
    final refusal is honoured, not only the pre-check)."""
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 6.0, journal=False)
    await eng.settings.set("techniques.tip.budget_per_tip", 5000.0, journal=False)
    q = await _quote(eng, "GEOI")
    row, sig = await _tip(eng, "GEOI", q.last, stop_pct=1.5)
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    assert "reviewRequired" not in pdict["context"]
    original = type(eng.proposals)._admit_geometry
    calls = {"n": 0}

    async def admit(self, p, **kw):
        calls["n"] += 1
        if calls["n"] == 2:                                   # between the head check and submission
            await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)
        return await original(self, p, **kw)
    monkeypatch.setattr(type(eng.proposals), "_admit_geometry", admit)
    out = await eng.proposals.approve(pdict["id"], via="auto")
    assert calls["n"] == 2 and out.get("refused") and out["order"] is None
    assert out["proposal"]["status"] == "pending", "the approval was reverted"
    from zargar.models import Proposal
    async with eng.sf() as session:
        prow = await session.get(Proposal, pdict["id"])
    assert prow.status == "pending" and prow.decided_via is None and prow.order_id is None
    paused = [p for p in await _events(eng, "TipAutoPaused") if p.get("proposalId") == pdict["id"]]
    assert paused and paused[-1].get("revertedApproval") is True


async def test_live_book_never_gets_a_plan_even_when_enforced(rig):
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    eng.positions.portfolio(pid)["kind"] = "live"          # the same book, relabeled live
    try:
        q = await _quote(eng, "GEOJ")
        _final, qty, rp, note = await eng.proposals._pre_entry_geometry(
            underlying="GEOJ", direction="long", pid=pid,
            exit_plan={"underlyingStop": round(q.last * 0.998, 2), "targets": [round(q.last * 1.05, 2)]},
            vehicle={"kind": "shares"}, sec_type="STK", symbol="GEOJ", limit=q.last, qty=50,
            entry_hint=q.last, source="t", signal_id=None, analyst_run_id=None)
        assert rp is None and qty == 50 and note == ""
        _q2, _p, refusal = await eng.proposals._admit_geometry(
            {"id": "x", "portfolioId": pid, "secType": "STK", "symbol": "GEOJ",
             "context": {"techniqueId": "tip"}}, limit=q.last, qty=50, via="auto")
        assert refusal is None, "a live book is outside the gate's scope entirely"
    finally:
        eng.positions.portfolio(pid)["kind"] = "sim"


async def test_widen_stop_refuses_stale_caller_state_and_reverts_on_journal_failure(rig, monkeypatch):
    from unittest.mock import AsyncMock
    eng = rig
    mgr = eng.position_manager
    q = await _quote(eng, "GEOK")
    tight, wide = round(q.last * 0.99, 2), round(q.last * 0.97, 2)
    pos = await _adopt_shares(eng, "GEOK", qty=10, stop=tight)
    # (a) the caller claims a trim happened; the position still holds 10
    with pytest.raises(ValueError, match="exceeds the admissible"):
        await mgr.widen_stop(pos["id"], wide, reason="claimed", max_qty=5)
    # (b) the residual does not fit the budget at the wider stop
    with pytest.raises(ValueError, match="exceeds the"):
        await mgr.widen_stop(pos["id"], wide, reason="budget", unit_loss=q.last * 0.03, budget=1.0)
    # (c) a protective exit in flight: the retained stop may be filling
    p = mgr.get(pos["id"])
    p.exits.append({"kind": "stop", "leg": "GEOK", "qty": 10, "orderId": "stop-working", "status": "SUBMITTED",
                    "filledQty": 0, "price": None, "ts": 0, "reason": "test"})
    with pytest.raises(ValueError, match="in flight"):
        await mgr.widen_stop(pos["id"], wide, reason="race")
    p.exits.pop()
    # (d) journal failure at the REAL boundary: nothing exposed, in-memory and persisted stop reverted
    monkeypatch.setattr(eng.journal, "append", AsyncMock(side_effect=OSError("journal down")))
    with pytest.raises(OSError):
        await mgr.widen_stop(pos["id"], wide, reason="journal")
    assert mgr.get(pos["id"]).state.stop == tight and mgr.get(pos["id"]).policy["stop"]["price"] == tight
    async with eng.sf() as session:
        rowdb = await session.get(ManagedPositionRow, pos["id"])
    assert rowdb.config["policy"]["stop"]["price"] == tight
    monkeypatch.undo()
    # (e) a closed (or already-forgotten) position cannot widen — either a refusal or nothing
    await mgr.close(pos["id"], fraction=1.0, kind="close", reason="done", force_market=True)
    await wait_for(lambda: mgr.get(pos["id"]) is None or mgr.get(pos["id"]).status == "closed", timeout=8)
    try:
        out = await mgr.widen_stop(pos["id"], wide, reason="closed")
    except ValueError:
        out = None
    assert out is None, "a closed position must never come back with a wider stop"


async def test_accounting_is_read_from_serialized_positions(rig):
    from zargar.techniques.tip.lifecycle import position_risk_accounting
    from zargar.techniques.tip.analyst import _our_positions
    eng = rig
    mgr = eng.position_manager
    q = await _quote(eng, "GEOL")
    tight = round(q.last * 0.99, 2)
    pos = await _adopt_shares(eng, "GEOL", qty=4, stop=tight,
                              extras={"riskPlan": {"plannedRisk": 12.0, "unitLoss": 3.0, "qty": 4, "stressRisk": 400.0,
                                                   "enforced": True}})
    acc = position_risk_accounting(mgr.get(pos["id"]).to_dict())
    assert acc["plannedRisk"] == 12.0 and acc["plannedRiskBasis"] == "enforced-plan" and acc["realizedLoss"] == 0.0
    assert "hypothetical" not in acc
    async with eng.sf() as session:
        rowdb = await session.get(ManagedPositionRow, pos["id"])
    row_acc = position_risk_accounting({"config": rowdb.config, "state": rowdb.state, "legs": rowdb.legs})
    assert row_acc["plannedRisk"] == 12.0, "the DB row shape reads the same plan"
    ours = _our_positions(eng, "GEOL")
    managed = [m for m in (ours.get("managed") or []) if m.get("symbol") == "GEOL"]
    assert managed and managed[0]["riskAccounting"]["plannedRisk"] == 12.0
    # a SHADOW plan is hypothetical: the executed plan is what counts (C95-02)
    pos2 = await _adopt_shares(eng, "GEOM", qty=4, stop=round(q.last * 0.99, 2),
                               extras={"riskPlan": {"mode": "shadow", "enforced": False, "qty": 2, "qtyRequested": 4,
                                                    "plannedRisk": 1.0, "resized": True}})
    acc2 = position_risk_accounting(mgr.get(pos2["id"]).to_dict())
    assert acc2["plannedRiskBasis"] == "executed-plan" and acc2["plannedRisk"] != 1.0
    assert acc2["hypothetical"]["plannedRisk"] == 1.0 and acc2["hypothetical"]["enforced"] is False


# ---------------------------------------------------------------- durable trim attempt (activation blocker 1)
async def test_attempt_write_failure_stops_the_trim_with_zero_orders(rig, monkeypatch):
    """The attempt/state write goes through the REAL set_extras -> strict persist
    chain; a database failure stops the sequence before any trim order exists,
    the tighter protection stays, and nothing is left "pending"."""
    from unittest.mock import AsyncMock
    from zargar.techniques.tip.lifecycle import run_geometry_exception
    eng = rig
    mgr = eng.position_manager
    q = await _quote(eng, "GEON")
    tight, wide = round(q.last * 0.99, 2), round(q.last * 0.97, 2)
    state = {"phase": "trim_pending", "tightStop": tight, "wideStop": wide, "trimQty": 5, "keepQty": 5,
             "qty": 10, "unitLossAtWide": round(q.last * 0.03, 4), "budget": round(q.last * 0.03 * 5, 4) + 0.01,
             "why": "test", "history": [], "stopInForce": tight}
    pos = await _adopt_shares(eng, "GEON", qty=10, stop=tight, extras={"geometryException": state})
    real_sf = eng.sf

    class FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, *_a, **_k):
            return None

        def add(self, _row):
            pass

        async def commit(self):
            raise OSError("database unavailable")
    close_spy = AsyncMock(wraps=mgr.close)
    monkeypatch.setattr(mgr, "close", close_spy)
    eng.sf = FailingSession
    try:
        final = await run_geometry_exception(eng, pos["id"], dict(state))
    finally:
        eng.sf = real_sf
    assert close_spy.await_count == 0, "a failed attempt write must produce zero trim orders"
    p = mgr.get(pos["id"])
    assert p.state.stop == tight and not [x for x in p.exits if x.get("kind") == "geometry_trim"]
    assert final["phase"] == "trim_pending" and "attemptId" not in final and final["stopInForce"] == tight
    assert any("NOT submitted" in a for a in p.attention)
    # with the database back, the same exception proceeds: attempt written, trim submitted, widened
    final2 = await run_geometry_exception(eng, pos["id"], {k: v for k, v in final.items() if k != "history"} | {"history": []})
    assert final2["phase"] == "widened" and final2.get("attemptId") and close_spy.await_count == 1
    trims = [x for x in mgr.get(pos["id"]).exits if x.get("kind") == "geometry_trim"]
    assert trims and trims[-1].get("attemptTag") == f"geometry_trim:{final2['attemptId']}"
