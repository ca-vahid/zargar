"""W6 (2026-10-03): the Tips method bound to several books - appraise once, one proposal per book, each book judged
by its own budget/caps/gates; one book's refusal never blocks another."""
import uuid

import pytest

from zargar.engine import Engine
from zargar.models import Portfolio, Proposal
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip import books as B

from .conftest import make_test_config
from .test_tip_geometry_wiring import _events, _quote, _tip


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


PFS = {"pa": {"id": "pa", "kind": "sim", "name": "Practice"},
       "pb": {"id": "pb", "kind": "sim", "name": "Practice B"},
       "pp": {"id": "pp", "kind": "paper", "name": "IBKR paper", "venue": "ibkr"},
       "sh": {"id": "sh", "kind": "shadow", "name": "Shadow", "book": "immediate"},
       "ar": {"id": "ar", "kind": "sim", "name": "Old", "archived": True}}


def pf_of(pid):
    return PFS.get(pid)


# ------------------------------------------------------------------ pure
def test_empty_list_is_the_single_legacy_book():
    bs = B.resolve_books(S({"techniques.tip.default_portfolio": "pa"}), pf_of)
    assert len(bs) == 1 and bs[0].legacy and bs[0].primary and bs[0].portfolioId == "pa" and bs[0].role == "practice"
    assert B.resolve_books(S({}), pf_of, fallback_pid="pb")[0].portfolioId == "pb"
    assert B.resolve_books(S({}), pf_of) == []


def test_validator_rejects_bad_bindings():
    assert B.validate([], pf_of) == []
    errs = B.validate([{"portfolioId": "pa", "role": "live"}, {"portfolioId": "pp", "role": "practice"},
                       {"portfolioId": "sh"}, {"portfolioId": "ar"}, {"portfolioId": "zz"},
                       {"portfolioId": "pa"}, {"portfolioId": "pb", "budgetPerTip": -1}], pf_of)
    text = " | ".join(errs)
    for want in ("role live needs a live or paper", "role practice needs a sim", "shadow/research",
                 "archived", "does not exist", "duplicate portfolio", "budgetPerTip must be >= 0"):
        assert want in text, want
    assert any("primary" in e for e in B.validate([{"portfolioId": "pa", "primary": True},
                                                   {"portfolioId": "pb", "primary": True}], pf_of))


def test_primary_defaults_to_the_practice_book_and_comes_first():
    raw = [{"portfolioId": "pp", "role": "live", "budgetPerTip": 500, "capitalCap": 3000},
           {"portfolioId": "pa", "role": "practice"}]
    bs = B.resolve_books(S({"techniques.tip.books": raw}), pf_of)
    assert [b.portfolioId for b in bs] == ["pa", "pp"] and bs[0].primary and not bs[1].primary
    assert bs[1].armAtLevel is False, "a live book does not arm at-level plans unless asked"
    assert B.knob(bs[1], "budgetPerTip", S({"techniques.tip.budget_per_tip": 2000})) == 500
    assert B.knob(bs[0], "budgetPerTip", S({"techniques.tip.budget_per_tip": 2000})) == 2000
    # an invalid list never silently trades a wrong book: it falls back to the legacy book
    bad = B.resolve_books(S({"techniques.tip.books": [{"portfolioId": "zz"}],
                             "techniques.tip.default_portfolio": "pa"}), pf_of)
    assert bad[0].legacy and bad[0].portfolioId == "pa"


def test_qty_rescale_and_book_settings_view():
    assert B.rescale_qty(20, primary_budget=1000, book_budget=500) == 10
    assert B.rescale_qty(1, primary_budget=1000, book_budget=100) == 1
    assert B.rescale_qty(5, primary_budget=500, book_budget=1000) == 5, "never above the analyst's hint"
    assert B.rescale_qty(None, primary_budget=1, book_budget=1) == 0
    b = B._parse_one({"portfolioId": "pp", "role": "live", "riskPct": 0.5})
    view = B.BookSettings(S({"techniques.tip.risk_pct": 1.0, "x": 1}), b)
    assert view.get("techniques.tip.risk_pct") == 0.5 and view.get("x") == 1
    with B.use(b):
        assert B.current() is b and B.BookSettings(S({"techniques.tip.risk_pct": 1.0})).get("techniques.tip.risk_pct") == 0.5
    assert B.current() is None


# ------------------------------------------------------------------ engine
@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def _second_book(eng, name="Tips Practice B", cash=10_000.0):
    other = Portfolio(id=uuid.uuid4().hex, name=name, kind="sim", starting_cash=cash, cash=cash)
    async with eng.sf() as session:
        session.add(other)
        await session.commit()
    eng.positions.register_portfolio(other)
    return other.id


async def test_one_tip_fans_out_one_proposal_per_book_with_its_own_budget(rig):
    eng = rig
    pa = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    pb = await _second_book(eng)
    await eng.settings.set("techniques.tip.budget_per_tip", 2000.0, journal=False)
    await eng.settings.set("techniques.tip.books", [
        {"portfolioId": pa, "role": "practice", "primary": True},
        {"portfolioId": pb, "role": "practice", "budgetPerTip": 500}], journal=False)
    q = await _quote(eng, "BKSA")
    row, sig = await _tip(eng, "BKSA", q.last, stop_pct=2.0)
    out = await eng.proposals.create_for_books(row, sig, {})
    assert [p["portfolioId"] for p in out] == [pa, pb]
    a, b = out
    assert a["context"]["book"]["primary"] is True and b["context"]["book"]["primary"] is False
    assert a["context"]["book"]["fanOutGroup"] == b["context"]["book"]["fanOutGroup"] == row.id
    assert b["context"]["sizing"]["budget"] <= 500 < a["context"]["sizing"]["budget"]
    assert b["qty"] < a["qty"]
    fan = await _events(eng, "TipBookFanOut")
    assert fan and [x["outcome"] for x in fan[-1]["books"]] == ["proposed", "proposed"]
    # the compatibility entry point returns the primary book's card
    row2, sig2 = await _tip(eng, "BKSA", q.last, stop_pct=2.0)
    assert (await eng.proposals.create_from_signal(row2, sig2, {}))["portfolioId"] == pa


async def test_a_full_book_is_refused_on_the_record_and_the_other_still_proposes(rig):
    eng = rig
    pa = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    pb = await _second_book(eng)
    await eng.settings.set("techniques.tip.books", [
        {"portfolioId": pa, "role": "practice"},
        {"portfolioId": pb, "role": "practice", "maxOpenPositions": 1},
        {"portfolioId": (await _second_book(eng, "Off book")), "role": "practice", "enabled": False}],
        journal=False)
    from zargar.models import ManagedPositionRow
    async with eng.sf() as session:                      # book B already holds one open tip position
        session.add(ManagedPositionRow(id=uuid.uuid4().hex, technique="tip", portfolio_id=pb, symbol="XX",
                                       status="open", tags=["source:GeoSrc"], legs=[], config={}, state={}))
        await session.commit()
    q = await _quote(eng, "BKSB")
    row, sig = await _tip(eng, "BKSB", q.last, stop_pct=2.0)
    out = await eng.proposals.create_for_books(row, sig, {})
    assert [p["portfolioId"] for p in out] == [pa]
    books = (await _events(eng, "TipBookFanOut"))[-1]["books"]
    by = {x["portfolioId"]: x for x in books}
    assert by[pb]["outcome"] == "refused" and "book slots full" in by[pb]["reason"]
    assert [x["outcome"] for x in books if x["portfolioId"] not in (pa, pb)] == ["skipped"]
    refused = [e for e in await _events(eng, "TipLaneDecided") if e.get("lane") == "refused"]
    assert refused and refused[-1]["portfolioId"] == pb


async def test_auto_decides_each_book_independently(rig):
    """The shared `_decide_auto`: a proposal-mode book waits for a person while the auto book self-approves."""
    eng = rig
    pa = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    pb = await _second_book(eng)
    await eng.settings.set("techniques.tip.books", [
        {"portfolioId": pa, "role": "practice"},
        {"portfolioId": pb, "role": "practice", "mode": "proposal"}], journal=False)
    q = await _quote(eng, "BKSC")
    row, sig = await _tip(eng, "BKSC", q.last, stop_pct=2.0, source="BooksSrc")
    await eng.settings.set("techniques.tip.sources", {"BooksSrc": {"mode": "auto"}}, journal=False)
    out = await eng.proposals.create_for_books(row, sig, {})
    from zargar.signals.sources import resolve_policy
    pol = resolve_policy(eng.settings, "BooksSrc")
    svc = eng.signals_service
    done = [await svc._decide_auto(row, p, policy=pol, promoted=False, verdict_expected=False) for p in out]
    by = {p["portfolioId"]: p for p in done}
    assert by[pa]["status"] in ("executed", "approved", "failed")
    async with eng.sf() as session:
        assert (await session.get(Proposal, by[pb]["id"])).status == "pending"


async def test_trust_counts_each_idea_once(rig):
    eng = rig
    pa = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    pb = await _second_book(eng)
    from zargar.models import ManagedPositionRow
    async with eng.sf() as session:
        for pid in (pa, pb):                               # the same idea closed in both books
            session.add(ManagedPositionRow(id=uuid.uuid4().hex, technique="tip", portfolio_id=pid, symbol="TT",
                                           status="closed", tags=["source:TrustSrc"], legs=[], config={},
                                           state={"realizedPnl": 10.0}))
        await session.commit()
    assert (await eng.signals_service.source_trust("TrustSrc"))["graded"] >= 2   # legacy: every real book counts
    await eng.settings.set("techniques.tip.books", [{"portfolioId": pa, "role": "practice", "primary": True},
                                                    {"portfolioId": pb, "role": "practice"}], journal=False)
    t = await eng.signals_service.source_trust("TrustSrc")
    assert t["graded"] == 1


async def test_settings_validator_refuses_a_bad_binding(rig):
    eng = rig
    with pytest.raises(KeyError):
        await eng.settings.set("techniques.tip.books", [{"portfolioId": "nope"}], journal=False)


async def test_risk_order_rate_and_day_notional_are_per_book(rig):
    from zargar.orders import OrderIntent
    eng = rig
    keys = eng.risk._exposure_keys(OrderIntent(portfolio_id="p1", symbol="X", side="BUY", qty=1,
                                               technique_id="tip", tags=["source:a"]))
    assert keys == ["tech:tip@p1", "tag:source:a@p1"]


def test_live_book_with_its_own_ack_decides_its_cards():
    live = B._parse_one({"portfolioId": "pp", "role": "live", "allowLiveAuto": True})
    assert B.live_unattended(S({}), live) is True
    assert B.live_unattended(S({"techniques.tip.live_unattended": False}), live) is False
    assert B.live_unattended(S({}), B._parse_one({"portfolioId": "pp", "role": "live"})) is False
    assert B.live_unattended(S({}), B._parse_one({"portfolioId": "pa", "role": "practice", "allowLiveAuto": True})) is False
    assert B.live_unattended(S({}), None) is False


async def test_a_defined_risk_spread_is_sized_by_the_risk_budget(rig):
    eng = rig
    pa = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 100.0, journal=False)
    g = await eng.proposals._spread_risk_plan(pa, qty=5, max_loss=0.40)          # $40 per spread
    assert g["riskPlan"]["qty"] == 2 and g["riskPlan"]["plannedRisk"] == 80.0 and "reviewRequired" not in g
    big = await eng.proposals._spread_risk_plan(pa, qty=5, max_loss=1.50)        # $150 > $100
    assert "reviewRequired" in big and "riskPlan" not in big
    pdict = {"id": "x", "portfolioId": pa, "secType": "SPREAD", "limitPrice": 0.40, "context": {
        "techniqueId": "tip", "riskPlan": g["riskPlan"], "vehicle": {"width": 5.0, "credit": False}}}
    q, _, refusal = await eng.proposals._admit_geometry(pdict, limit=0.45, qty=2, via="auto")
    assert refusal is None and q == 2
    q2, _, refusal2 = await eng.proposals._admit_geometry(pdict, limit=1.20, qty=2, via="auto")
    assert refusal2 and "over the" in refusal2
