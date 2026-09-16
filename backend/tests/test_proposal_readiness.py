"""Approval-card readiness (readiness-v1, 2026-09-15): the ACTUAL blocking
reasons, separate from the analyst's opinion; refresh-and-revalidate with
zero orders; a manual approval submits the displayed, freshly validated plan
or is refused; overrides are explicit, named, reasoned and journaled; other
desks' proposals keep their old path."""
import asyncio
import datetime as dt

import pytest
from sqlalchemy import select

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import Event, Order, Proposal, Signal
from zargar.signals.schemas import TradeSignal
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip import integrity as ig

from .conftest import make_test_config, wait_for


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    await eng.settings.set("techniques.tip.default_portfolio", pid, journal=False)
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.entry_pause_mode", "integrity", journal=False)
    eng.positions.portfolio(pid)["cash"] = 50_000.0
    yield eng
    await eng.stop()


def _pid(eng) -> str:
    return next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")


async def _quote(eng, sym: str):
    await eng.ensure_symbol(sym)
    await wait_for(lambda: eng.quotes.get(sym) is not None and eng.quotes.get(sym).last > 0, timeout=5)
    return eng.quotes.get(sym)


async def _share_tip(eng, sym: str, *, stop_pct: float = 2.0, source: str = "RdSrc"):
    q = await _quote(eng, sym)
    px = q.last
    row = Signal(id=new_id(), source_name=source, ticker=sym, direction="long", action="open",
                 instrument="shares", entry_price=px, target_price=round(px * 1.05, 2),
                 stop_price=round(px * (1 - stop_pct / 100.0), 2), status="verified", extraction={},
                 thesis_summary="readiness test", confidence="explicit_call")
    sig = TradeSignal(ticker=sym, direction="long", instrument="shares", entry_price=px,
                      target_price=row.target_price, stop_price=row.stop_price,
                      thesis_summary="readiness test", confidence="explicit_call",
                      evidence_quotes=["readiness test"], is_actionable=True)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return await eng.proposals.create_from_signal(row, sig, {})


async def _orders(eng) -> list:
    async with eng.sf() as session:
        return list((await session.execute(select(Order))).scalars().all())


async def _events(eng, kind: str) -> list[dict]:
    async with eng.sf() as session:
        return list((await session.execute(select(Event.payload).where(Event.type == kind)
                                           .order_by(Event.id))).scalars().all())


async def _card(eng, pid_: str) -> dict:
    from zargar.approvals.proposals import proposal_dict
    async with eng.sf() as session:
        return proposal_dict(await session.get(Proposal, pid_))


# ---------------------------------------------------------------- pure classification
def test_readiness_module_classifies_and_fingerprints():
    from zargar.approvals import readiness as rd
    rp = {"enforced": True, "reviewRequired": "no live underlying reference quote; no quantity satisfies the $90 risk budget",
          "reviewClass": "budget", "resizeReason": "no quantity satisfies the $90 risk budget: one unit risks $101",
          "evidence": [{"code": "quote_missing", "detail": "no live underlying reference quote"}],
          "unitLoss": 101.25, "budget": 89.62, "qty": 3, "qtyRequested": 3, "multiplier": 100.0, "quote": {}}
    bl = rd.plan_blockers(rp, enforced_scope=True)
    codes = [b["code"] for b in bl]
    assert codes == ["quote_missing", "risk_budget_exceeded"]
    assert not bl[0]["overridable"] and bl[1]["overridable"]
    pdict = {"secType": "OPT", "limitPrice": 2.25, "qty": 3, "context": {"sizing": {"budget": 2000.0}}}
    out = rd.build(pdict=pdict, rp=rp, blockers=bl, info=[rd.blocker("source_not_qualified", "0/5 graded")],
                   limit=2.25, qty=3, scope_mode="enforce", phase="revalidate", via="app", valid_for_s=300)
    assert out["state"] == "blocked" and out["overridable"] is False
    plan = out["plan"]
    assert plan["allocationLimit"] == 2000.0 and plan["riskBudget"] == 89.62 and plan["unitLoss"] == 101.25
    assert plan["plannedRisk"] == 303.75 and plan["withinBudget"] is False and plan["cost"] == 675.0
    assert out["info"][0]["scope"] == "auto"
    # the same numbers + blockers fingerprint identically; a different limit does not
    again = rd.build(pdict=pdict, rp=rp, blockers=bl, info=[], limit=2.25, qty=3, scope_mode="enforce",
                     phase="submit", via="app", valid_for_s=300)
    assert again["fingerprint"] == out["fingerprint"], "the same displayed plan fingerprints identically across phases"
    cheaper = rd.build(pdict=pdict, rp=rp, blockers=bl, info=[], limit=2.10, qty=3, scope_mode="enforce",
                       phase="submit", via="app", valid_for_s=300)
    assert cheaper["fingerprint"] != out["fingerprint"], "AP85-02: the approved maximum limit is part of the plan"
    other = rd.build(pdict=pdict, rp={**rp, "finalStop": 60.0}, blockers=bl, info=[], limit=2.25, qty=3,
                     scope_mode="enforce", phase="submit", via="app", valid_for_s=300)
    assert other["fingerprint"] != out["fingerprint"], "a moved stop is a different plan"
    fewer = rd.build(pdict=pdict, rp=rp, blockers=[bl[1]], info=[], limit=2.25, qty=3, scope_mode="enforce",
                     phase="submit", via="app", valid_for_s=300)
    assert fewer["fingerprint"] != out["fingerprint"], "a different blocker set is a different plan"
    # override validation: every failed check named, overridable only, substantive reason
    soft = rd.build(pdict=pdict, rp=rp, blockers=[bl[1]], info=[], limit=2.25, qty=1, scope_mode="enforce",
                    phase="submit", via="app", valid_for_s=300)
    with pytest.raises(ValueError, match="blocked"):
        rd.validate_override(soft, None)
    with pytest.raises(ValueError, match="substantive reason"):
        rd.validate_override(soft, {"checks": ["risk_budget_exceeded"], "reason": "ok"})
    with pytest.raises(ValueError, match="acknowledge every"):
        rd.validate_override(soft, {"checks": [], "reason": "the desk accepts one contract of risk today"})
    with pytest.raises(ValueError, match="cannot be overridden"):
        rd.validate_override(out, {"checks": ["quote_missing", "risk_budget_exceeded"],
                                   "reason": "the desk accepts one contract of risk today"})
    acc, reason = rd.validate_override(soft, {"checks": ["risk_budget_exceeded"],
                                              "reason": "the desk accepts one contract of risk today"})
    assert [b["code"] for b in acc] == ["risk_budget_exceeded"] and reason
    assert rd.classify_refusal("execution-integrity integrity incident 4e93b293 (x): y") == "integrity_incident"
    assert rd.classify_refusal("auto not yet earned: 0/5 graded tips") == "source_not_qualified"


# ---------------------------------------------------------------- AFRM shape: budget + missing quote
async def test_budget_exceeded_card_shows_both_failures_and_half_size_does_not_fit(rig):
    """One unit already exceeds the approved budget: the card is BLOCKED with
    the budget reason (and a missing-quote reason is separate), plain Approve
    and half size are refused with zero orders, and an override cannot skip a
    non-overridable check."""
    eng = rig
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)   # nothing fits
    pdict = await _share_tip(eng, "RDA")
    assert pdict["context"]["reviewRequired"]
    out = await eng.proposals.revalidate(pdict["id"])
    rd = out["readiness"]
    assert out["order"] is None and rd["state"] == "blocked"
    codes = {b["code"] for b in rd["blockers"]}
    assert "risk_budget_exceeded" in codes
    assert rd["plan"]["unitLoss"] is not None and rd["plan"]["withinBudget"] is False
    assert rd["plan"]["allocationLimit"] == pdict["context"]["sizing"]["budget"]
    # the analyst's opinion is not touched by readiness
    assert "analyst" in pdict["context"]
    before = len(await _orders(eng))
    noconf = await eng.proposals.approve(pdict["id"], via="app")
    assert noconf["order"] is None and "confirmation" in noconf["refused"], "AP85-02: no fingerprint, no submission"
    plain = await eng.proposals.approve(pdict["id"], via="app", expected=rd["fingerprint"])
    assert plain["order"] is None and plain.get("refused") and "blocked" in plain["refused"]
    half = await eng.proposals.approve(pdict["id"], via="app", half=True, expected=rd["fingerprint"])
    assert half["order"] is None and half.get("refused")
    assert len(await _orders(eng)) == before, "refusals place nothing"
    card = await _card(eng, pdict["id"])
    assert card["status"] == "pending" and card["context"]["readiness"]["state"] == "blocked"
    refused = [e for e in await _events(eng, "ProposalRevalidated") if e.get("action") == "approval_refused"]
    assert len(refused) == 3 and all(e["orders"] == 0 for e in refused)


async def test_override_is_named_reasoned_journaled_and_submits_the_shown_exposure(rig):
    eng = rig
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)
    pdict = await _share_tip(eng, "RDB")
    out = await eng.proposals.revalidate(pdict["id"])
    rd = out["readiness"]
    assert rd["state"] == "blocked" and rd["overridable"], rd["blockers"]
    # a short reason is refused; naming nothing is refused; nothing is placed
    r1 = await eng.proposals.approve(pdict["id"], via="app", expected=rd["fingerprint"],
                                     override={"checks": ["risk_budget_exceeded"], "reason": "short"})
    assert r1.get("refused") and "substantive" in r1["refused"] and r1["order"] is None
    r2 = await eng.proposals.approve(pdict["id"], via="app", expected=rd["fingerprint"],
                                     override={"checks": [], "reason": "the desk accepts the full stop risk today"})
    assert r2.get("refused") and "acknowledge every" in r2["refused"]
    assert not await _orders(eng)
    # the real override: the exact checks, a reason, the exposure on the record
    ok = await eng.proposals.approve(pdict["id"], via="app", expected=rd["fingerprint"],
                                     override={"checks": ["risk_budget_exceeded"],
                                               "reason": "the desk accepts the full stop risk today"})
    assert ok["order"] is not None and not ok.get("refused")
    ov = (await _events(eng, "ProposalOverridden"))
    assert len(ov) == 1 and ov[0]["checks"] == ["risk_budget_exceeded"] and ov[0]["reason"].startswith("the desk")
    assert ov[0]["exposure"]["plannedRisk"] is not None and ov[0]["exposure"]["riskBudget"] == 0.01
    approved = await _events(eng, "ProposalApproved")
    assert approved[-1].get("override", {}).get("checks") == ["risk_budget_exceeded"]
    orders = await _orders(eng)
    assert len(orders) == 1 and orders[0].qty == ov[0]["exposure"]["qty"], "the order is the shown exposure"


# ---------------------------------------------------------------- MRNA shape: resolved incident
async def test_resolved_incident_label_clears_on_revalidation_and_plan_matches_order(rig):
    eng = rig
    pid = _pid(eng)
    pdict = await _share_tip(eng, "RDC")
    inc = await ig.open_incident(eng, kind="integrity", cause="shared_component",
                                 scope={"technique": "tip", "portfolioId": pid, "entryPath": "proposal"},
                                 evidence=[{"kind": "component", "id": "quote-feed"}], why="feed defect")
    out = await eng.proposals.revalidate(pdict["id"])
    assert out["readiness"]["state"] == "blocked"
    assert [b["code"] for b in out["readiness"]["blockers"]] == ["integrity_incident"]
    assert out["readiness"]["blockers"][0]["overridable"] is True
    blocked = await eng.proposals.approve(pdict["id"], via="app", expected=out["readiness"]["fingerprint"])
    assert blocked["order"] is None and "incident" in blocked["refused"]
    # the incident is resolved by its own path - the card still carries the old label
    await ig.resolve_incident(eng, inc["id"], resolver="test", examined_revision=inc["revision"],
                              note="component repaired and verified in this test", override=True)
    card = await _card(eng, pdict["id"])
    assert "incident" in (card["context"].get("autoGate") or "")
    out2 = await eng.proposals.revalidate(pdict["id"])
    assert out2["readiness"]["state"] == "ready" and out2["readiness"]["blockers"] == []
    card = await _card(eng, pdict["id"])
    assert "incident" not in (card["context"].get("autoGate") or ""), "no permanent stale blocking label"
    assert "reviewRequired" not in card["context"]
    # approve exactly what is shown: the order carries the displayed limit, size and stop
    rd = out2["readiness"]
    ok = await eng.proposals.approve(pdict["id"], via="app", expected=rd["fingerprint"])
    assert ok["order"] is not None and not ok.get("refused")
    order = ok["order"]
    # the limit is never ABOVE what was displayed (a live ask may only improve it); size and stop are exact
    assert float(order["limitPrice"]) <= float(rd["plan"]["limit"]) + 1e-9 and float(order["qty"]) == float(rd["plan"]["qty"])
    final = await _card(eng, pdict["id"])
    assert final["status"] in ("executed", "failed")
    assert abs(float(final["bracket"]["stop_loss"]) - float(rd["plan"]["finalStop"])) < 1e-6


# ---------------------------------------------------------------- changes between refresh and submission
async def test_changed_plan_or_new_incident_between_refresh_and_submit_is_refused(rig):
    eng = rig
    pid = _pid(eng)
    pdict = await _share_tip(eng, "RDD")
    out = await eng.proposals.revalidate(pdict["id"])
    fp = out["readiness"]["fingerprint"]
    # a stale fingerprint (the person saw a different plan) is refused, nothing placed
    stale = await eng.proposals.approve(pdict["id"], via="app", expected="0000000000000000")
    assert stale.get("refused") and stale.get("changed") and stale["order"] is None
    assert (await _card(eng, pdict["id"]))["status"] == "pending"
    # an incident that opens after the refresh blocks the submission even with the right fingerprint
    await ig.open_incident(eng, kind="integrity", cause="shared_component",
                           scope={"technique": "tip", "portfolioId": pid, "entryPath": "proposal"},
                           evidence=[{"kind": "component", "id": "feed"}], why="new defect")
    blocked = await eng.proposals.approve(pdict["id"], via="app", expected=fp)
    assert blocked.get("refused") and blocked["order"] is None
    assert (await _card(eng, pdict["id"]))["status"] == "pending"
    assert not await _orders(eng)


# ---------------------------------------------------------------- expiry, duplicate clicks, refresh = zero orders
async def test_expired_cards_and_duplicate_clicks_cannot_create_orders(rig):
    eng = rig
    pdict = await _share_tip(eng, "RDE")
    async with eng.sf() as session:
        row = await session.get(Proposal, pdict["id"])
        row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        await session.commit()
    out = await eng.proposals.revalidate(pdict["id"])
    assert out["readiness"]["state"] == "expired" and out["proposal"]["status"] == "expired"
    with pytest.raises(ValueError):
        await eng.proposals.approve(pdict["id"], via="app")
    assert not await _orders(eng)
    # duplicate clicks: two concurrent approvals -> exactly one order
    p2 = await _share_tip(eng, "RDF")
    rd = (await eng.proposals.revalidate(p2["id"]))["readiness"]
    assert rd["state"] == "ready"

    async def click():
        try:
            return await eng.proposals.approve(p2["id"], via="app", expected=rd["fingerprint"])
        except ValueError as exc:
            return {"error": str(exc), "order": None}
    a, b = await asyncio.gather(click(), click())
    placed = [r for r in (a, b) if r.get("order") is not None]
    assert len(placed) == 1, (a, b)
    assert len(await _orders(eng)) == 1
    # refresh journal: never an order
    refreshes = [e for e in await _events(eng, "ProposalRevalidated") if e.get("action") == "refresh"]
    assert refreshes and all(e["orders"] == 0 for e in refreshes)


# ---------------------------------------------------------------- other desks unchanged
async def test_non_tip_proposals_keep_the_old_approval_path(rig):
    """A card another technique created (no readiness, no override) approves
    on the plain click exactly as before."""
    eng = rig
    pid = _pid(eng)
    await _quote(eng, "RDG")
    q = eng.quotes.get("RDG")
    row = Proposal(id=new_id(), signal_id=None, portfolio_id=pid, symbol="RDG", sec_type="STK", side="BUY",
                   qty=1.0, order_type="LMT", limit_price=round(q.ask, 2), bracket=None, rationale="other desk",
                   context={"techniqueId": "options_cartel"}, status="pending",
                   expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1))
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    out = await eng.proposals.approve(row.id, via="app")
    assert out["order"] is not None and not out.get("refused")
    card = await _card(eng, row.id)
    assert "readiness" not in card["context"] and card["status"] in ("executed", "failed")
    # and a second click on the decided card is told so (the locked flip), no second order
    with pytest.raises(ValueError, match="not pending"):
        await eng.proposals.approve(row.id, via="app")
    assert len(await _orders(eng)) == 1
