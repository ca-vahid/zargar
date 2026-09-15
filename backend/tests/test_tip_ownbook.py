"""KFIN-08 — MK own-book classification, shadow-first (techniques/tip/ownbook.py).

Proves, on the labeled case set in tests/fixtures/mk_ownbook_cases.json and on
the real Engine + API (sim broker, extraction never called):
  * every labeled case classifies as expected (deterministic text first, the
    extraction's actor/activity second);
  * own-book text from an enrolled source in `shadow` mode never creates a
    proposal, an armed plan, an analyst run or an order outside the dedicated
    own-book shadow book — even with the source on `mode: auto` and unattended
    practice, i.e. "I bought" is never permission for a Practice order;
  * recaps / hypotheticals / third-party screenshots / exits never open;
  * missing or ambiguous evidence (no grounded price, no expiry, stale content,
    ambiguous exit size) stays UNRESOLVED and is journaled as such;
  * grading uses executable evidence (the qualified quote at the decision, our
    own fill) inside the DECLARED cohort; the promotion criteria are reported
    with a human verdict, never acted on;
  * `observe` mode and non-enrolled sources leave the pipeline unchanged.
"""
import datetime as dt
import json
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from zargar.api.app import create_app
from zargar.domain import Quote, new_id
from zargar.engine import Engine
from zargar.models import Order, Proposal, RawContent, Signal, TipAnalystRun
from zargar.signals.extraction import ground_signal
from zargar.signals.schemas import ExtractionResult, TradeSignal
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip import ownbook

from .conftest import make_test_config, wait_for

CASES = json.loads((Path(__file__).parent / "fixtures" / "mk_ownbook_cases.json")
                   .read_text(encoding="utf-8"))
SOURCE = CASES["source"]


def _sig(case: dict) -> TradeSignal:
    base = dict(entry_type="unspecified", timeframe="swing", thesis_summary="x")
    base.update(case["signal"])
    return TradeSignal(**base)


class FakeSettings:
    def __init__(self, **overrides):
        self.values = dict(overrides)

    def get(self, key, default=None):
        return self.values.get(key, default)


def _warm_quote(symbol: str, last: float = 100.0) -> Quote:
    return Quote(symbol=symbol, last=last, bid=last - 0.01, ask=last + 0.01,
                 bid_size=500, ask_size=500, halted=False, ts=int(time.time() * 1000))


# --- (1) the labeled case set: pure classification + evidence resolution -----------

@pytest.mark.parametrize("case", CASES["cases"], ids=[c["id"] for c in CASES["cases"]])
def test_labeled_case_classifies_as_expected(case):
    sig = _sig(case)
    ob = ownbook.classify(sig, case["text"])
    want = case["expect"]
    assert ob["class"] == want["class"], (case["id"], ob)
    if want.get("basis"):
        assert ob["basis"] == want["basis"], (case["id"], ob)
    if ob["class"] == "tip":
        return                      # the normal pipeline's business, not this module's
    grounding = ground_signal(sig, case["text"])
    resolved = ownbook.resolve(ob, sig, grounding=grounding,
                               quote=_warm_quote(sig.ticker, float(sig.entry_price or 100.0)),
                               settings=FakeSettings(), stale=False, age_hours=0.1)
    assert resolved["resolution"] == want["resolution"], (case["id"], resolved["reasons"])
    if want.get("reason_contains"):
        assert any(want["reason_contains"] in r for r in resolved["reasons"]), resolved["reasons"]
    if "fraction" in want:
        assert ownbook.exit_fraction(case["text"]) == want["fraction"]


def test_resolution_requires_a_qualified_quote_at_the_decision():
    case = next(c for c in CASES["cases"] if c["id"] == "own_open_shares_priced")
    sig = _sig(case)
    ob = ownbook.classify(sig, case["text"])
    g = ground_signal(sig, case["text"])
    # cold quote → unresolved; halted → unresolved; stale content → unresolved
    r = ownbook.resolve(ob, sig, grounding=g, quote=None, settings=FakeSettings(),
                        stale=False, age_hours=0.1)
    assert r["resolution"] == "unresolved" and any("no market data" in x for x in r["reasons"])
    q = _warm_quote("NVDA", 118.2)
    old = Quote(symbol="NVDA", last=118.2, bid=118.1, ask=118.3, bid_size=1, ask_size=1,
                halted=False, ts=int(time.time() * 1000) - 600_000)
    r = ownbook.resolve(ob, sig, grounding=g, quote=old, settings=FakeSettings(),
                        stale=False, age_hours=0.1)
    assert r["resolution"] == "unresolved" and any("old at the decision" in x for x in r["reasons"])
    r = ownbook.resolve(ob, sig, grounding=g, quote=q, settings=FakeSettings(),
                        stale=True, age_hours=96.0)
    assert r["resolution"] == "unresolved" and any("no qualified quote existed" in x for x in r["reasons"])
    r = ownbook.resolve(ob, sig, grounding=g, quote=q, settings=FakeSettings(),
                        stale=False, age_hours=0.1)
    assert r["resolution"] == "resolved" and r["evidence"]["quote"]["ask"] == pytest.approx(118.21)


def test_text_wins_over_extraction_and_records_disagreement():
    # the extractor calls it a recap; the text says "just added ... today" → own_open,
    # and the disagreement is on the record
    sig = TradeSignal(ticker="NVDA", direction="long", action="add", instrument="shares",
                      entry_price=118.2, evidence_quotes=["Just added NVDA at 118.20 today"],
                      confidence="explicit_call", is_actionable=True, thesis_summary="x",
                      activity="recap", actor="author")
    ob = ownbook.classify(sig, "Just added NVDA at 118.20 today")
    assert ob["class"] == "own_open" and ob["agreement"] is False
    assert ob["extraction"] == {"actor": "author", "activity": "recap", "class": "recap"}


def test_enrollment_is_explicit_and_off_by_default():
    assert not ownbook.enrolled(FakeSettings(), SOURCE)
    assert not ownbook.enrolled(FakeSettings(**{"techniques.tip.mk_ownbook_mode": "shadow"}), SOURCE)
    s = FakeSettings(**{"techniques.tip.mk_ownbook_mode": "shadow",
                        "techniques.tip.mk_ownbook_sources": [SOURCE]})
    assert ownbook.enrolled(s, SOURCE) and ownbook.enrolled(s, SOURCE.lower())
    assert not ownbook.enrolled(s, "SomeoneElse")
    off = FakeSettings(**{"techniques.tip.mk_ownbook_mode": "off",
                          "techniques.tip.mk_ownbook_sources": [SOURCE]})
    assert not ownbook.enrolled(off, SOURCE)


# --- (2) the real pipeline: nothing but the own-book shadow ledger ------------------

@pytest.fixture
async def app_client(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    await attach_signal_layer(eng)
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, eng
    await eng.stop()


async def _enroll(eng, *, mode="shadow", cohort="", min_age=5):
    await eng.settings.set("techniques.tip.mk_ownbook_mode", mode)
    await eng.settings.set("techniques.tip.mk_ownbook_sources", [SOURCE])
    await eng.settings.set("techniques.tip.mk_ownbook_cohort", cohort)
    await eng.settings.set("techniques.tip.mk_ownbook_min_age_sessions", min_age)
    # the hostile configuration: the source is on full AUTO and practice is
    # unattended — own-book text must STILL never reach a proposal
    await eng.settings.set("techniques.tip.sources", {SOURCE: {"mode": "auto"}})
    await eng.settings.set("techniques.tip.unattended", True)
    await eng.settings.set("verification.max_price_deviation_pct", 100.0)


async def _wait_quote(eng, symbol):
    await eng.ensure_symbol(symbol)
    await wait_for(lambda: (eng.quotes.get(symbol) is not None
                            and float(eng.quotes.get(symbol).last or 0) > 0
                            and float(eng.quotes.get(symbol).ask or 0) > 0))


def _case(case_id: str) -> dict:
    return next(c for c in CASES["cases"] if c["id"] == case_id)


async def _run(eng, case: dict, *, source=SOURCE, text=None, stated_at=None, signal=None):
    text = text or case["text"]
    sig = signal or _sig(case)
    if text != case["text"]:
        sig = sig.model_copy(update={"evidence_quotes": [text]})
    row = RawContent(id=new_id(), source_type="manual", source_name=source,
                     subject="mk", body_text=text)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    result = ExtractionResult(signals=[sig], source_type="portfolio_update",
                              **({"stated_at": stated_at} if stated_at else {}))
    return await eng.signals_service.handle_extraction(row, result, source_text=text)


async def _assert_nothing_but_ownbook(eng, client):
    """The whole point: no proposal, no analyst run, no armed plan, and no
    order on any portfolio that is not the own-book shadow book."""
    async with eng.sf() as session:
        assert (await session.execute(select(Proposal))).scalars().all() == []
        assert (await session.execute(select(TipAnalystRun))).scalars().all() == []
        orders = (await session.execute(select(Order))).scalars().all()
    for o in orders:
        pf = eng.positions.portfolio(o.portfolio_id) or {}
        assert pf.get("kind") == "shadow" and pf.get("book") == ownbook.BOOK, (o.symbol, pf)
        assert "ownbook" in (o.tags or [])
    assert (await client.get("/api/proposals")).json() == []
    runner = getattr(eng, "tip_runner", None)
    if runner is not None:                      # no armed plan for anything own-book
        assert not [ap for ap in runner._armed.values() if ap.status in ("armed", "paused")]
    # the source's tip books (immediate / armed) were never created for own-book text
    assert not [p for p in eng.positions.portfolios()
                if p.get("kind") == "shadow" and p.get("sourceName") == SOURCE
                and (p.get("book") or "immediate") in ("immediate", "armed")]


async def test_own_open_books_only_the_ownbook_ledger(app_client):
    client, eng = app_client
    await _enroll(eng, cohort="c1")
    await _wait_quote(eng, "AAPL")
    case = _case("own_open_shares_priced")
    text = "Just added $50k of AAPL at $231.50 to the portfolio this morning."
    sig = TradeSignal(ticker="AAPL", direction="long", action="add", instrument="shares",
                      entry_price=231.5, evidence_quotes=["Just added $50k of AAPL at $231.50"],
                      confidence="explicit_call", is_actionable=True, thesis_summary="x",
                      timeframe="swing")
    out = await _run(eng, case, text=text, signal=sig)
    assert len(out) == 1
    s = out[0]["signal"]
    assert s["status"] == "ownbook", s["verification"]
    assert out[0]["proposal"] is None and out[0]["armed"] is None and out[0]["shadowOrder"] is None
    ob = out[0]["ownbook"]
    assert ob["class"] == "own_open" and ob["resolution"] == "resolved" and ob["cohort"] == "c1"
    assert ob["booked"]["vehicle"] == "shares" and ob["booked"]["qty"] >= 1
    assert ob["evidence"]["quote"]["ask"] > 0
    pf = eng.positions.portfolio(ob["booked"]["portfolioId"])
    assert pf["kind"] == "shadow" and pf["book"] == "ownbook" and pf["sourceName"] == SOURCE
    assert "(own book)" in pf["name"]
    # the record on the signal + the journal entry
    assert s["extraction"]["ownbook"]["route"] == "ownbook"
    check = next(c for c in s["verification"]["checks"] if c["name"] == "ownbook")
    assert not check["fatal"] and "never a proposal" in check["detail"]
    events = (await client.get("/api/events", params={"limit": 200})).json()
    mine = [e for e in events if e["type"] == "TipOwnBookClassified"]
    assert mine and mine[0]["payload"]["route"] == "ownbook" and mine[0]["payload"]["booked"]
    await _assert_nothing_but_ownbook(eng, client)
    # the fill lands in the own-book book only
    await wait_for(lambda: eng.positions.position_qty(pf["id"], "AAPL") >= 1)
    assert eng.positions.position_qty(pf["id"], "AAPL") == ob["booked"]["qty"]


async def test_own_open_without_price_or_contract_stays_unresolved(app_client, monkeypatch):
    client, eng = app_client
    await _enroll(eng)
    await _wait_quote(eng, "AAPL")

    async def no_chain(*a, **k):                 # hermetic: never reach a chain provider
        return {"available": False, "error": "no chain (test)"}
    monkeypatch.setattr("zargar.techniques.tip.express.pick_tip_contract", no_chain)
    # shares without a grounded price
    out = await _run(eng, _case("own_open_shares_no_price"),
                     text="I added more AAPL this morning, another $200k basket.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="add",
                                        instrument="shares",
                                        evidence_quotes=["I added more AAPL this morning"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    s = out[0]["signal"]
    assert s["status"] == "ownbook_unresolved"
    assert "booked" not in out[0]["ownbook"]
    assert any("grounded entry price" in r for r in out[0]["ownbook"]["reasons"])
    # an option without an expiry
    out = await _run(eng, _case("own_open_option_no_expiry"),
                     text="I picked up some AAPL 250 calls.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="open",
                                        instrument="call", strike=250.0,
                                        evidence_quotes=["I picked up some AAPL 250 calls"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    assert out[0]["signal"]["status"] == "ownbook_unresolved"
    assert any("without an expiry" in r for r in out[0]["ownbook"]["reasons"])
    # a stated contract that is not quotable (no chain) — booking turns it unresolved
    out = await _run(eng, _case("own_open_option_contract"),
                     text="Bought AAPL 250c 12/18 for 3.40 today.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="open",
                                        instrument="call", strike=250.0, expiry="2026-12-18",
                                        premium=3.4,
                                        evidence_quotes=["Bought AAPL 250c 12/18 for 3.40"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    assert out[0]["signal"]["status"] == "ownbook_unresolved"
    assert any("not quotable" in r for r in out[0]["ownbook"]["reasons"]), out[0]["ownbook"]
    async with eng.sf() as session:
        assert (await session.execute(select(Order))).scalars().all() == []
    await _assert_nothing_but_ownbook(eng, client)


async def test_own_open_option_books_the_stated_contract_only_in_the_ledger(app_client, monkeypatch):
    """A grounded option disclosure buys the STATED contract in the own-book
    shadow book (sized by the budget on a live ask) — and nothing else.
    On a FAKE underlying (like the runner rig): a real ticker's OCC symbol
    would pull a real quote from Yahoo through ensure_symbol and the test
    would price on the live market."""
    client, eng = app_client
    await _enroll(eng, cohort="c1")
    import zargar.brokers.sim as simmod
    monkeypatch.setitem(simmod.KNOWN_PRICES, "TEST", 100.0)
    occ_sym = "TEST261218C00101000"
    monkeypatch.setitem(simmod.KNOWN_PRICES, occ_sym, 3.4)   # the sim ticks the contract near its premium
    await _wait_quote(eng, "TEST")

    async def fake_pick(engine, *, symbol, direction, strike, expiry, **k):
        assert symbol == "TEST" and strike == 101.0 and expiry == "2026-12-18"
        # the runtime's reprice() puts the contract's NBBO into the quote cache;
        # here the fake pick does — RiskGate's quote_fresh (invariant 14) sees it
        engine.quotes.on_quote(Quote(symbol=occ_sym, bid=3.3, ask=3.4, last=3.35,
                                     bid_size=50, ask_size=50, halted=False,
                                     ts=int(time.time() * 1000)))
        return {"available": True, "symbol": occ_sym, "ask": 3.4, "mid": 3.35,
                "display": "TEST 18 Dec 26 101 C", "warnings": []}
    monkeypatch.setattr("zargar.techniques.tip.express.pick_tip_contract", fake_pick)
    out = await _run(eng, _case("own_open_option_contract"),
                     text="Bought TEST 101c 12/18 for 3.40 today.",
                     signal=TradeSignal(ticker="TEST", direction="long", action="open",
                                        instrument="call", strike=101.0, expiry="2026-12-18",
                                        premium=3.4,
                                        evidence_quotes=["Bought TEST 101c 12/18 for 3.40"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    s = out[0]["signal"]
    assert s["status"] == "ownbook", out[0]["ownbook"].get("reasons")
    b = out[0]["ownbook"]["booked"]
    assert b["vehicle"] == "option" and b["symbol"] == occ_sym and b["qty"] == 2   # $1000 / (3.40 x 100)
    async with eng.sf() as session:
        orders = (await session.execute(select(Order))).scalars().all()
    assert len(orders) == 1 and orders[0].symbol == occ_sym and orders[0].sec_type == "OPT"
    pf = eng.positions.portfolio(orders[0].portfolio_id)
    assert pf["kind"] == "shadow" and pf["book"] == "ownbook"
    await _assert_nothing_but_ownbook(eng, client)


async def test_stale_own_open_is_unresolved_not_replayed_or_booked(app_client):
    client, eng = app_client
    await _enroll(eng)
    await _wait_quote(eng, "AAPL")
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=9)).strftime("%Y-%m-%dT%H:%M")
    out = await _run(eng, _case("own_open_shares_priced"),
                     text="Just added $50k of AAPL at $231.50 to the portfolio this morning.",
                     stated_at=old,
                     signal=TradeSignal(ticker="AAPL", direction="long", action="add",
                                        instrument="shares", entry_price=231.5,
                                        evidence_quotes=["Just added $50k of AAPL at $231.50"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    s = out[0]["signal"]
    assert s["status"] == "ownbook_unresolved"
    assert any("no qualified quote existed" in r for r in out[0]["ownbook"]["reasons"])
    assert "replay" not in s["extraction"]          # nothing is back-filled from history
    async with eng.sf() as session:
        assert (await session.execute(select(Order))).scalars().all() == []


async def test_context_classes_never_open(app_client):
    client, eng = app_client
    await _enroll(eng)
    await _wait_quote(eng, "AAPL")
    # the same ticker on purpose: a recap must NOT swallow the later messages
    # through dedupe (own-book context rows are not tips)
    for cid, text in (("recap_scorecard", "Bought AAPL at 95 last year - up 40% since. Here's how the portfolio did this quarter."),
                      ("hypothetical_dip", "If AAPL dips to 200 I'd buy more."),
                      ("third_party_screenshot", "A member sent me his AAPL position - nice fills at 231.")):
        case = _case(cid)
        sig = _sig(case).model_copy(update={"ticker": "AAPL", "evidence_quotes": [text]})
        out = await _run(eng, case, text=text, signal=sig)
        assert "duplicateOf" not in out[0], (cid, out[0])
        s = out[0]["signal"]
        assert s["status"] == "ownbook_context", (cid, s["verification"])
        assert out[0]["ownbook"]["class"] == case["expect"]["class"]
        assert out[0]["ownbook"]["resolution"] == "noop"
    async with eng.sf() as session:
        assert (await session.execute(select(Order))).scalars().all() == []
    await _assert_nothing_but_ownbook(eng, client)


async def test_own_exit_reduces_only_and_never_opens(app_client):
    client, eng = app_client
    await _enroll(eng)
    await _wait_quote(eng, "AAPL")
    # an exit with NOTHING held is context — nothing is opened, nothing sold
    await _wait_quote(eng, "MSFT")
    out = await _run(eng, _case("own_exit_out"),
                     text="I'm out of MSFT, closed the whole position at 242.",
                     signal=TradeSignal(ticker="MSFT", direction="long", action="close",
                                        instrument="shares",
                                        evidence_quotes=["I'm out of MSFT, closed the whole position at 242"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    assert out[0]["signal"]["status"] == "ownbook_context"
    assert any("no own-book position" in r for r in out[0]["ownbook"]["reasons"])
    async with eng.sf() as session:
        assert (await session.execute(select(Order))).scalars().all() == []
    # open first, wait for the fill
    out = await _run(eng, _case("own_open_shares_priced"),
                     text="Just added $50k of AAPL at $231.50 to the portfolio this morning.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="add",
                                        instrument="shares", entry_price=231.5,
                                        evidence_quotes=["Just added $50k of AAPL at $231.50"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    booked = out[0]["ownbook"]["booked"]
    pid, qty = booked["portfolioId"], booked["qty"]
    assert qty >= 2
    await wait_for(lambda: eng.positions.position_qty(pid, "AAPL") == qty)
    # ambiguous size → unresolved, nothing reduced
    out = await _run(eng, _case("own_exit_size_ambiguous"), text="Trimmed some AAPL into the pop.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="trim",
                                        instrument="shares", evidence_quotes=["Trimmed some AAPL"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    assert out[0]["signal"]["status"] == "ownbook_unresolved"
    assert any("ambiguous" in r for r in out[0]["ownbook"]["reasons"])
    assert eng.positions.position_qty(pid, "AAPL") == qty
    # "sold half" → a reduce-only SELL of half in the own-book book
    out = await _run(eng, _case("own_exit_half"), text="Sold half my AAPL today, still holding the rest.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="trim",
                                        instrument="shares",
                                        evidence_quotes=["Sold half my AAPL today"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    assert out[0]["signal"]["status"] == "ownbook"
    ex = out[0]["ownbook"]["booked"]
    assert ex["side"] == "SELL" and ex["orders"][0]["qty"] == qty // 2
    await wait_for(lambda: eng.positions.position_qty(pid, "AAPL") == qty - qty // 2)
    async with eng.sf() as session:
        orders = (await session.execute(select(Order))).scalars().all()
    assert sorted(o.side for o in orders) == ["BUY", "SELL"]
    assert all(o.portfolio_id == pid for o in orders)
    sell = next(o for o in orders if o.side == "SELL")
    assert sell.reduce_only if hasattr(sell, "reduce_only") else True
    await _assert_nothing_but_ownbook(eng, client)


async def test_observe_mode_records_but_leaves_the_pipeline_unchanged(app_client):
    client, eng = app_client
    await _enroll(eng, mode="observe")
    await eng.settings.set("techniques.tip.sources", {SOURCE: {"mode": "shadow"}})
    await _wait_quote(eng, "AAPL")
    out = await _run(eng, _case("own_open_shares_priced"),
                     text="Just added $50k of AAPL at $231.50 to the portfolio this morning.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="add",
                                        instrument="shares", entry_price=231.5,
                                        evidence_quotes=["Just added $50k of AAPL at $231.50"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    s = out[0]["signal"]
    assert s["status"] in ("verified", "parked"), s["verification"]      # the old path
    assert s["extraction"]["ownbook"]["class"] == "own_open"
    assert s["extraction"]["ownbook"]["route"] == "pipeline"
    assert out[0]["shadowOrder"] is not None                             # immediate book as before
    assert not any(c["name"] == "ownbook" for c in s["verification"]["checks"])


async def test_non_enrolled_source_is_untouched(app_client):
    client, eng = app_client
    await _enroll(eng)                          # enrolls MK only
    await eng.settings.set("techniques.tip.sources", {})
    await _wait_quote(eng, "AAPL")
    out = await _run(eng, _case("own_open_shares_priced"), source="OtherLetter",
                     text="Just added $50k of AAPL at $231.50 to the portfolio this morning.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="add",
                                        instrument="shares", entry_price=231.5,
                                        evidence_quotes=["Just added $50k of AAPL at $231.50"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    s = out[0]["signal"]
    assert "ownbook" not in s["extraction"]
    assert s["status"] in ("verified", "parked")
    assert "ownbook" not in out[0]
    assert not [p for p in eng.positions.portfolios() if p.get("book") == "ownbook"]


async def test_ledger_api_grades_on_evidence_inside_the_declared_cohort(app_client):
    client, eng = app_client
    await _enroll(eng, cohort="c1", min_age=0)
    await _wait_quote(eng, "AAPL")
    r = await client.get(f"/api/tip/ownbook/{SOURCE}")
    assert r.status_code == 200
    empty = r.json()
    assert empty["entries"] == [] and empty["book"] is None and empty["enrolled"] is True
    assert empty["promotion"]["allMet"] is False and empty["promotion"]["verdict"] == "human"

    out = await _run(eng, _case("own_open_shares_priced"),
                     text="Just added $50k of AAPL at $231.50 to the portfolio this morning.",
                     signal=TradeSignal(ticker="AAPL", direction="long", action="add",
                                        instrument="shares", entry_price=231.5,
                                        evidence_quotes=["Just added $50k of AAPL at $231.50"],
                                        confidence="explicit_call", is_actionable=True,
                                        thesis_summary="x"))
    booked = out[0]["ownbook"]["booked"]
    await wait_for(lambda: eng.positions.position_qty(booked["portfolioId"], "AAPL") == booked["qty"])
    # a second disclosure booked under NO declared cohort never grades
    await eng.settings.set("techniques.tip.mk_ownbook_cohort", "")
    await _wait_quote(eng, "MSFT")
    out2 = await _run(eng, _case("own_open_shares_priced"),
                      text="Just added $20k of MSFT at $410.00 today.",
                      signal=TradeSignal(ticker="MSFT", direction="long", action="add",
                                         instrument="shares", entry_price=410.0,
                                         evidence_quotes=["Just added $20k of MSFT at $410.00"],
                                         confidence="explicit_call", is_actionable=True,
                                         thesis_summary="x"))
    assert out2[0]["signal"]["status"] == "ownbook" and out2[0]["ownbook"]["cohort"] == ""
    # an unresolved one counts against the evidence-quality criterion (a
    # different ticker: a same-key repeat of the booked AAPL entry would —
    # correctly — attach to it as seen-again instead of a second row)
    await _wait_quote(eng, "NVDA")
    await _run(eng, _case("own_open_shares_no_price"),
               text="I added more NVDA this morning, another $200k basket.",
               signal=TradeSignal(ticker="NVDA", direction="long", action="add",
                                  instrument="shares",
                                  evidence_quotes=["I added more NVDA this morning"],
                                  confidence="explicit_call", is_actionable=True,
                                  thesis_summary="x"))
    await eng.settings.set("techniques.tip.mk_ownbook_cohort", "c1")
    body = (await client.get(f"/api/tip/ownbook/{SOURCE}")).json()
    assert body["book"]["book"] == "ownbook" and body["book"]["kind"] == "shadow"
    assert body["counts"]["own_open"] == 3
    by_ticker = {(e["ticker"], e["status"]): e for e in body["entries"]}
    graded = by_ticker[("AAPL", "ownbook")]
    assert graded["graded"] is True and graded["cohort"] == "c1"
    assert graded["quoteAtDecision"]["ask"] > 0 and "returnPct" in graded
    assert by_ticker[("MSFT", "ownbook")]["graded"] is False
    assert "never grades" in by_ticker[("MSFT", "ownbook")]["gradeNote"]
    assert by_ticker[("NVDA", "ownbook_unresolved")]["graded"] is False
    g = body["grading"]
    assert g["graded"] == 1 and g["ownActivity"] == 3 and g["unresolved"] == 1
    assert g["unresolvedPct"] == pytest.approx(100 / 3)
    p = body["promotion"]
    assert p["criteria"]["minGraded"] == 20 and p["checks"]["graded"]["met"] is False
    assert p["checks"]["unresolvedPct"]["met"] is False           # 33% > 25%
    assert p["allMet"] is False and p["verdict"] == "human"
    assert "no calendar deadline" in p["note"]
    # the read is a read: nothing changed
    await _assert_nothing_but_ownbook(eng, client)
