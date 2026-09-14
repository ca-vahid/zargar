"""KB-06 — the execution-integrity pause: acceptance cases on the real engine
(sim broker, offline) plus the pure classifier. Design:
docs/techniques/tip/reviews/2026-09-13-kb06-execution-integrity-pause.md."""
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
    await attach_tip_runner(eng)                        # the armed lane's final admission lives on the runner
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    await eng.settings.set("techniques.tip.default_portfolio", pid, journal=False)
    await eng.settings.set("techniques.tip.entry_pause_mode", "integrity", journal=False)
    eng.positions.portfolio(pid)["cash"] = 50_000.0
    yield eng
    await eng.stop()


def _pid(eng) -> str:
    return next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")


async def _closed(eng, pid: str, sym: str, *, exits: list, opened_ms: int, extras: dict) -> str:
    row_id = new_id()
    async with eng.sf() as session:
        session.add(ManagedPositionRow(
            id=row_id, technique="tip", symbol=sym, portfolio_id=pid, status="closed",
            tags=["source:Src"], config={"direction": "long", "extras": extras}, legs=[],
            state={"exits": exits, "openedMs": opened_ms, "closeReason": "stop"}))
        await session.commit()
    return row_id


def _stop_exit(ts_ms: int, kind: str = "stop", **kw) -> dict:
    # the fill record carries `filledTs` (the fill's arrival) — the intent time `ts` is not evidence
    return {"kind": kind, "leg": "X", "qty": 1, "orderId": new_id(), "status": "FILLED",
            "filledQty": 1, "price": 1.0, "ts": ts_ms - 500, "filledTs": ts_ms,
            "reason": "bar closed through the stop", **kw}


async def _events(eng, kind: str) -> list[dict]:
    from sqlalchemy import select
    from zargar.models import Event
    async with eng.sf() as session:
        return list((await session.execute(select(Event.payload).where(Event.type == kind)
                                           .order_by(Event.id))).scalars().all())


async def _quote(eng, sym: str):
    await eng.ensure_symbol(sym)
    await wait_for(lambda: eng.quotes.get(sym) is not None and eng.quotes.get(sym).last > 0, timeout=5)
    return eng.quotes.get(sym)


async def _proposal(eng, sym: str) -> dict:
    q = await _quote(eng, sym)
    px = q.last
    row = Signal(id=new_id(), source_name="Src", ticker=sym, direction="long", action="open",
                 instrument="shares", entry_price=px, target_price=round(px * 1.05, 2),
                 stop_price=round(px * 0.98, 2), status="verified", extraction={},
                 thesis_summary="t", confidence="explicit_call")
    sig = TradeSignal(ticker=sym, direction="long", instrument="shares", entry_price=px,
                      target_price=row.target_price, stop_price=row.stop_price, thesis_summary="t",
                      confidence="explicit_call", evidence_quotes=["t"], is_actionable=True)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return await eng.proposals.create_from_signal(row, sig, {})


NOW_MS = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
VALID_PLAN = {"riskPlan": {"enforced": True, "invariantOk": True, "quote": {"delayed": False}}}


# ---------------------------------------------------------------- pure classifier
def test_classifier_uses_structured_kinds_and_execution_times():
    assert ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 600_000)], "openedMs": NOW_MS, "extras": VALID_PLAN}) is None
    v = ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 60_000)], "openedMs": NOW_MS, "extras": VALID_PLAN})
    assert v["verdict"] == "valid" and v["seconds"] == 60.0
    assert ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 60_000, kind="trim")], "openedMs": NOW_MS,
                                  "extras": VALID_PLAN}) is None, "a trim is not a stop, whatever its prose says"
    m = ig.classify_fast_stop({"exits": [_stop_exit(0)], "openedMs": 0, "extras": VALID_PLAN})
    assert m["verdict"] == "evidence_missing"
    bad = ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 60_000)], "openedMs": NOW_MS,
                                 "extras": {"riskPlan": {"enforced": True, "invariantOk": False}}})
    assert bad["verdict"] == "invalid" and "violated" in bad["why"]
    prem = ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 60_000, kind="premium_stop")], "openedMs": NOW_MS,
                                  "extras": VALID_PLAN})
    assert prem["verdict"] == "evidence_missing" and "confirmation" in prem["why"]
    prose = ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 60_000, kind="premium_stop",
                                                        reason="premium stop confirmed (2 observations)")],
                                   "openedMs": NOW_MS, "extras": VALID_PLAN})
    assert prose["verdict"] == "evidence_missing", "prose is not a confirmation record"
    ok_prem = ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 60_000, kind="premium_stop",
                                                          confirmation={"confirmed": True,
                                                                        "observations": [{"sourceTs": {"X": 1}},
                                                                                         {"sourceTs": {"X": 2}}]})],
                                     "openedMs": NOW_MS, "extras": VALID_PLAN})
    assert ok_prem["verdict"] == "valid"
    unconfirmed = ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 60_000, kind="premium_stop",
                                                              confirmation={"confirmed": False, "observations": []})],
                                         "openedMs": NOW_MS, "extras": VALID_PLAN})
    assert unconfirmed["verdict"] == "invalid", "an exit recorded as unconfirmed is a defect at any speed"
    slow_bad = ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 3_600_000)], "openedMs": NOW_MS,
                                      "extras": {"riskPlan": {"enforced": True, "invariantOk": False}}})
    assert slow_bad["verdict"] == "invalid", "a proven violation is not discarded for being slow"
    bare = ig.classify_fast_stop({"exits": [_stop_exit(NOW_MS + 60_000)], "openedMs": NOW_MS,
                                  "extras": {"riskPlan": {"enforced": True}}})
    assert bare["verdict"] == "evidence_missing", "a bare enforced flag proves nothing"


# 1. a valid, budget-compliant fast loss is a diagnostic, never an incident
async def test_case1_valid_fast_loss_is_a_diagnostic_only(rig):
    eng = rig
    pid = _pid(eng)
    await _closed(eng, pid, "FSTA", exits=[_stop_exit(NOW_MS + 45_000)], opened_ms=NOW_MS, extras=VALID_PLAN)
    assert await ig.detect_incidents(eng) == []
    diag = await _events(eng, "TipFastStopDiagnostic")
    assert len(diag) == 1 and diag[0]["verdict"] == "valid"
    assert await ig.entry_paused(eng, portfolio_id=pid) is None
    assert await ig.detect_incidents(eng) == [] and len(await _events(eng, "TipFastStopDiagnostic")) == 1, "classified once"
    assert await ig.gate_reason(eng, portfolio_id=pid, entry_path="proposal") is None


# 2. a filled geometry violation opens an integrity incident scoped to the book; other books untouched
async def test_case2_filled_violation_opens_scoped_incident(rig):
    eng = rig
    pid = _pid(eng)
    await _closed(eng, pid, "FSTB", exits=[_stop_exit(NOW_MS + 45_000)], opened_ms=NOW_MS,
                  extras={"riskPlan": {"enforced": True, "invariantOk": False}})
    opened = await ig.detect_incidents(eng)
    assert len(opened) == 1 and opened[0]["kind"] == "integrity" and opened[0]["cause"] == "geometry_violation_filled"
    assert opened[0]["scope"] == {"technique": "tip", "portfolioId": pid}
    why = await ig.entry_paused(eng, portfolio_id=pid)
    assert why and opened[0]["id"][:8] in why and "release:" in why
    assert await ig.entry_paused(eng, portfolio_id="some-other-book") is None
    assert await ig.entry_paused(eng, portfolio_id=pid, technique="team2") is None
    assert await ig.detect_incidents(eng) == [], "the same defect does not open a second incident"


# 3. missing evidence holds; resolution must VALIDATE against RECORDS, and a stale resolution is refused
async def test_case3_hold_incident_resolution_validates_evidence(rig):
    from zargar.models import Execution, Order
    eng = rig
    pid = _pid(eng)
    stop_order_id = new_id()
    await _closed(eng, pid, "FSTC", exits=[_stop_exit(NOW_MS + 45_000, orderId=stop_order_id)], opened_ms=NOW_MS, extras={})
    (inc,) = await ig.detect_incidents(eng)
    assert inc["kind"] == "hold" and inc["cause"] == "evidence_missing" and inc["revision"] == 1
    with pytest.raises(ValueError, match="no proof evidence"):
        await ig.resolve_incident(eng, inc["id"], resolver="user", examined_revision=1, note="looked fine")
    # an API-supplied flag on a reference that resolves to nothing is not validation
    inc = await ig.append_evidence(eng, inc["id"], {"kind": "proof", "id": "q-nowhere", "valid": True})
    with pytest.raises(ValueError, match="do not resolve"):
        await ig.resolve_incident(eng, inc["id"], resolver="user", examined_revision=2)
    # a proof that resolves to an ACTUAL execution of the incident's OWN position validates
    order_id, exec_id = stop_order_id, new_id()
    async with eng.sf() as session:
        session.add(Order(id=order_id, portfolio_id=pid, symbol="FSTC", sec_type="STK", side="BUY", qty=1.0,
                          order_type="LMT", limit_price=10.0, status="FILLED", filled_qty=1.0, avg_fill_price=10.0,
                          source="signal"))
        await session.commit()                                # the FK needs the order first
        session.add(Execution(id=exec_id, order_id=order_id, portfolio_id=pid, symbol="FSTC", side="SELL",
                              qty=1.0, price=10.0))
        # an UNRELATED execution of the same symbol in the same book: not this position's
        other_order = new_id()
        session.add(Order(id=other_order, portfolio_id=pid, symbol="FSTC", sec_type="STK", side="BUY", qty=1.0,
                          order_type="LMT", limit_price=10.0, status="FILLED", filled_qty=1.0, avg_fill_price=10.0,
                          source="signal"))
        await session.commit()
        unrelated_exec = new_id()
        session.add(Execution(id=unrelated_exec, order_id=other_order, portfolio_id=pid, symbol="FSTC", side="BUY",
                              qty=1.0, price=10.0))
        await session.commit()
    inc = await ig.append_evidence(eng, inc["id"], {"kind": "proof", "ref": f"execution:{unrelated_exec}", "symbol": "FSTC"})
    with pytest.raises(ValueError, match="do not resolve"):
        await ig.resolve_incident(eng, inc["id"], resolver="user", examined_revision=3)
    inc = await ig.append_evidence(eng, inc["id"], {"kind": "proof", "ref": f"execution:{exec_id}", "symbol": "FSTC"})
    assert inc["revision"] == 4
    with pytest.raises(ValueError, match="stale resolution"):
        await ig.resolve_incident(eng, inc["id"], resolver="user", examined_revision=3)
    out = await ig.resolve_incident(eng, inc["id"], resolver="user", examined_revision=4, note="validated")
    assert out["status"] == "resolved" and out["resolution"]["examinedRevision"] == 4
    assert out["resolution"]["override"] is False and "execution" in out["resolution"]["validated"]
    assert await ig.entry_paused(eng, portfolio_id=pid) is None
    # a proof that resolves to a BOUND record showing a DEFECT never releases
    fstc2 = await _closed(eng, pid, "FSTC2", exits=[_stop_exit(NOW_MS + 45_000)], opened_ms=NOW_MS, extras={})
    (inc2,) = await ig.detect_incidents(eng)
    # an unrelated record (another position's fill) is unresolved, not a release
    inc2 = await ig.append_evidence(eng, inc2["id"], {"kind": "proof", "ref": f"execution:{exec_id}", "symbol": "FSTC2"})
    with pytest.raises(ValueError, match="do not resolve"):
        await ig.resolve_incident(eng, inc2["id"], resolver="user", examined_revision=inc2["revision"])
    async with eng.sf() as session:                     # the position's own plan records a violation
        rowdb = await session.get(ManagedPositionRow, fstc2)
        rowdb.config = {**(rowdb.config or {}), "extras": {"riskPlan": {"enforced": True, "invariantOk": False}}}
        await session.commit()
    inc2 = await ig.append_evidence(eng, inc2["id"], {"kind": "proof", "ref": f"position:{fstc2}"})
    with pytest.raises(ValueError, match="proves a defect"):
        await ig.resolve_incident(eng, inc2["id"], resolver="user", examined_revision=inc2["revision"])
    assert await ig.entry_paused(eng, portfolio_id=pid), "still paused"
    acts = [e["action"] for e in await _events(eng, "TipExecutionIncident")]
    assert acts.count("release_refused") == 5 and acts.count("resolved") == 1
    diag = [d for d in await _events(eng, "TipFastStopDiagnostic") if d.get("symbol") == "FSTC"]
    assert diag and diag[0].get("incidentId"), "the diagnostic receipt links its incident (C95-07)"


# 4. every automated entry path is refused while paused; a person may still act
async def test_case4_automated_paths_are_refused_human_proceeds(rig):
    eng = rig
    pid = _pid(eng)
    pdict = await _proposal(eng, "PAUA")
    inc = await ig.open_incident(eng, kind="integrity", cause="shared_component",
                                 scope={"technique": "tip", "portfolioId": pid},
                                 evidence=[{"kind": "component", "id": "quote-feed"}], why="feed defect")
    # (a) proposal auto-approval
    out = await eng.proposals.approve(pdict["id"], via="auto")
    assert out.get("refused") and out["order"] is None and out["proposal"]["status"] == "pending"
    assert inc["id"][:8] in out["proposal"]["context"]["autoGate"]
    # (b) a queued stale-quote retry
    pdict2 = await _proposal(eng, "PAUB")
    intent = OrderIntent(portfolio_id=pid, symbol="PAUB", sec_type="STK", side="BUY", qty=1,
                         order_type="LMT", limit_price=10.0, source="signal", proposal_id=pdict2["id"])
    fake = {"id": "o-rejected", "status": "REJECTED_RISK", "rejectReason": "quote age 12.0s (max 10s)"}
    same = await eng.proposals._maybe_retry_stale_quote(pdict2, intent, fake, via="auto")
    assert same is fake
    from zargar.models import Proposal
    async with eng.sf() as session:
        prow = await session.get(Proposal, pdict2["id"])
    assert "execution-integrity" in ((prow.context or {}).get("freshRetry") or {}).get("retryRefused", "")
    # (c) an armed plan's fire — final admission right before the order
    runner = eng.plan_runners["tip"]
    ap = NS(run_id="run-x", symbol="PAUC", config=NS(portfolio_id=pid, max_retries=0, mode="auto"))
    trade = NS(trigger_id="t1", status="submitting", reason=None, errors=[], entry_order_id=None, retries=0)
    res = await runner._place_with_retry(ap, trade, OrderIntent(
        portfolio_id=pid, symbol="PAUC", sec_type="STK", side="BUY", qty=1, order_type="LMT",
        limit_price=10.0, source="technique", technique_id="tip"), stage="entry")
    assert res is None and trade.status == "skipped" and "execution-integrity" in trade.reason
    # a person's click is a decision, not an automated entry
    human = await eng.proposals.approve(pdict["id"], via="app")
    assert human["order"] is not None


# 5. protective exits continue while paused
async def test_case5_exits_continue_while_paused(rig):
    eng = rig
    pid = _pid(eng)
    q = await _quote(eng, "EXTA")
    pos = await eng.position_manager.adopt({
        "portfolioId": pid, "symbol": "EXTA", "direction": "long", "techniqueId": "tip",
        "entry": q.last, "risk": 1.0, "overnight": "day_only",
        "legs": [{"symbol": "EXTA", "secType": "STK", "qty": 5, "avgFill": q.last, "origin": "adoption"}],
        "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": round(q.last * 0.98, 2)}}})
    await ig.open_incident(eng, kind="integrity", cause="shared_component",
                           scope={"technique": "tip", "portfolioId": pid},
                           evidence=[{"kind": "component", "id": "x"}], why="paused")
    await eng.position_manager.close(pos["id"], fraction=1.0, kind="stop", reason="protective exit", force_market=True)
    p = eng.position_manager.get(pos["id"])
    await wait_for(lambda: all(abs(l.qty) < 1e-9 for l in (p.legs if p else [])) or p is None or p.status == "closed", timeout=8)
    assert any(x.get("kind") == "stop" for x in (p.exits if p else [])) or p is None


# 6. an incident is a row: a restart cannot clear it
async def test_case6_incident_survives_restart(rig):
    eng = rig
    pid = _pid(eng)
    inc = await ig.open_incident(eng, kind="integrity", cause="shared_component",
                                 scope={"technique": "tip", "portfolioId": pid},
                                 evidence=[{"kind": "component", "id": "x"}], why="persist me")
    async with eng.sf() as session:
        row = await session.get(TipExecutionIncident, inc["id"])
    assert row is not None and row.status == "open" and row.scope["portfolioId"] == pid
    fresh = Engine(make_test_config())              # a second engine over the same store
    await fresh.start()
    try:
        await fresh.settings.set("techniques.tip.entry_pause_mode", "integrity", journal=False)
        assert inc["id"][:8] in (await ig.entry_paused(fresh, portfolio_id=pid) or "")
    finally:
        await fresh.stop()


# 7. incidents and loss halts are independent
async def test_case7_incident_and_loss_halt_are_independent(rig):
    eng = rig
    pid = _pid(eng)
    inc = await ig.open_incident(eng, kind="integrity", cause="shared_component",
                                 scope={"technique": "tip", "portfolioId": pid},
                                 evidence=[{"kind": "component", "id": "x"}], why="independent")
    await eng.engage_book_halt(pid, "test halt", source="test")
    assert eng.trading_halted(pid)
    with pytest.raises(ValueError, match="labeled override"):
        await ig.resolve_incident(eng, inc["id"], resolver="owner", examined_revision=1,
                                  note="component owner confirmed healthy after inspection")
    out = await ig.resolve_incident(eng, inc["id"], resolver="owner", examined_revision=1, override=True,
                                    note="component owner confirmed healthy after inspection")
    assert out["resolution"]["override"] is True and out["resolution"]["validated"].startswith("OVERRIDE")
    assert eng.trading_halted(pid), "resolving an incident never clears a loss halt"
    inc2 = await ig.open_incident(eng, kind="integrity", cause="shared_component",
                                  scope={"technique": "tip", "portfolioId": pid},
                                  evidence=[{"kind": "component", "id": "y"}], why="second")
    await eng.release_book_halt(pid, source="test")
    assert not eng.trading_halted(pid)
    assert inc2["id"][:8] in (await ig.entry_paused(eng, portfolio_id=pid) or ""), "lifting a halt never resolves an incident"


# 8. a shared-component incident pauses exactly its journaled scope
async def test_case8_scope_is_exact(rig):
    eng = rig
    pid = _pid(eng)
    await ig.open_incident(eng, kind="integrity", cause="shared_component",
                           scope={"technique": "tip", "portfolioId": pid, "entryPath": "retry"},
                           evidence=[{"kind": "component", "id": "retry-path"}], why="retry path only")
    assert await ig.entry_paused(eng, portfolio_id=pid, entry_path="proposal") is None
    assert await ig.entry_paused(eng, portfolio_id=pid, entry_path="retry")
    assert await ig.entry_paused(eng, portfolio_id=pid, entry_path="retry", technique="enhanced_market") is None


# R1. an incident opened AFTER an automated entry was armed still blocks: the resting order is cancelled
async def test_r1_incident_after_arming_cancels_the_resting_entry(rig, monkeypatch):
    """Two automated entries are already ARMED when the incident opens: an
    executed tip card whose LMT entry still rests at the venue, and an armed
    plan's working entry trade. Both resting entries are cancelled; nothing is
    resubmitted; exits are never touched (cancel is recorded, not simulated)."""
    from unittest.mock import AsyncMock
    from zargar.models import Order, Proposal
    eng = rig
    pid = _pid(eng)
    pdict = await _proposal(eng, "RESA")
    resting_id = new_id()
    async with eng.sf() as session:
        session.add(Order(id=resting_id, portfolio_id=pid, symbol="RESA", sec_type="STK", side="BUY", qty=1.0,
                          order_type="LMT", limit_price=1.0, status="WORKING", source="signal",
                          proposal_id=pdict["id"]))
        prow = await session.get(Proposal, pdict["id"])
        prow.status, prow.decided_via, prow.order_id = "executed", "auto", resting_id
        await session.commit()
    runner = eng.plan_runners["tip"]
    runner._armed["run-resting"] = NS(run_id="run-resting", symbol="RESB", config=NS(portfolio_id=pid),
                                      trades={"t1": NS(trigger_id="t1", status="working", entry_order_id="arm-order-1"),
                                              "t2": NS(trigger_id="t2", status="filled", entry_order_id="arm-order-2")})
    cancelled: list[str] = []

    async def fake_cancel(order_id: str) -> dict:
        cancelled.append(order_id)
        return {"id": order_id, "status": "CANCELLED"}
    monkeypatch.setattr(eng.orders, "cancel", AsyncMock(side_effect=fake_cancel))
    inc = await ig.open_incident(eng, kind="integrity", cause="shared_component",
                                 scope={"technique": "tip", "portfolioId": pid},
                                 evidence=[{"kind": "component", "id": "late"}], why="opened after arming")
    assert set(cancelled) == {resting_id, "arm-order-1"}, cancelled     # the filled trade's order is untouched
    acts = await _events(eng, "TipExecutionIncident")
    assert any(a.get("action") == "cancelled_resting_entry" and a.get("orderId") == resting_id for a in acts)
    # a hold incident for ANOTHER book cancels nothing here
    cancelled.clear()
    await ig.open_incident(eng, kind="hold", cause="evidence_missing",
                           scope={"technique": "tip", "portfolioId": "other-book"},
                           evidence=[{"kind": "position", "id": "p-other"}], why="elsewhere")
    assert cancelled == []
    runner._armed.pop("run-resting", None)
    assert inc["status"] == "open"


# default mode keeps the clock gate and records incidents without pausing
async def test_default_clock_mode_records_without_pausing(rig):
    eng = rig
    pid = _pid(eng)
    await eng.settings.set("techniques.tip.entry_pause_mode", "clock", journal=False)
    await _closed(eng, pid, "FSTD", exits=[_stop_exit(NOW_MS + 45_000)], opened_ms=NOW_MS,
                  extras={"riskPlan": {"enforced": True, "invariantOk": False}})
    (inc,) = await ig.detect_incidents(eng)
    assert inc["status"] == "open"
    assert await ig.entry_paused(eng, portfolio_id=pid), "the incident exists as evidence"
    assert ig.pauses(eng.settings) is False
    pdict = await _proposal(eng, "CLKA")
    out = await eng.proposals.approve(pdict["id"], via="auto")
    assert out["order"] is not None and not out.get("refused"), "clock mode: incidents do not pause"
