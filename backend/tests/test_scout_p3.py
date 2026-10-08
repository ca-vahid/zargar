"""Scout P3: entry-spread rule timing, grounding filter, masking, cost/budget, lanes (fake clients - NO
LLM call is ever made here), research books (shadow, sim executor only, never in money totals), entries
through OrderManager/RiskGate, managed ATR stop / time exits, after-cost accounting, daily report."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from zargar import events as ev
from zargar.api.app import create_app
from zargar.domain import Bar, new_id
from zargar.models import Event, Order, ScoutCandidate, ScoutEntry, ScoutVerdict
from zargar.techniques.scout import analyst as an
from zargar.techniques.scout import books as bk
from zargar.techniques.scout import entry as er
from zargar.techniques.scout.form4 import ET
from zargar.techniques.scout.screens import add_sessions
from zargar.techniques.scout.service import ScoutService

from .conftest import make_test_config, wait_for


def at(day: str, hhmm: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=ET)


# =========================================================================== entry rule (pure)
def test_entry_rule_slots_and_timing():
    r = er.EntryRule(max_spread_pct=0.5)
    assert r.slots() == ["10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30"]
    d = "2026-10-08"
    assert er.decide(at(d, "09:59"), d, 0.1, r)[0] == er.WAIT
    assert er.decide(at("2026-10-07", "10:00"), d, 0.1, r)[0] == er.WAIT          # before the entry session
    assert er.decide(at(d, "10:00"), d, 0.30, r)[0] == er.ENTER
    act, why = er.decide(at(d, "10:00"), d, 0.80, r)
    assert act == er.RETRY and "re-check in 15 min" in why
    assert er.decide(at(d, "11:15"), d, 0.80, r)[0] == er.RETRY
    act, why = er.decide(at(d, "11:30"), d, 0.80, r)
    assert act == er.SKIP and er.reason_code(why) == "spread"
    assert er.decide(at(d, "11:30"), d, 0.49, r)[0] == er.ENTER                   # the last attempt can still enter
    act, why = er.decide(at(d, "11:30"), d, None, r)
    assert act == er.SKIP and er.reason_code(why) == "no_quote"
    act, why = er.decide(at(d, "11:30"), d, None, r, seen_quote=True)
    assert er.reason_code(why) == "spread"
    act, why = er.decide(at(d, "13:00"), d, 0.1, r)                                # the job ran late: never a late fill
    assert act == er.SKIP and er.reason_code(why) == "window_missed"
    assert er.reason_code(er.decide(at("2026-10-09", "10:00"), d, 0.1, r)[1]) == "window_missed"
    assert er.spread_pct(99.9, 100.1) == pytest.approx(0.2)
    assert er.spread_pct(0, 100) is None and er.spread_pct(101, 100) is None


# =========================================================================== analyst (pure)
def packet() -> an.Packet:
    return an.Packet(sources=[
        {"id": "F4-1", "label": "row", "text": "Insider: Insider A\nRole: officer (Chief Executive Officer)\nValue: $250,000"},
        {"id": "PX", "label": "px", "text": "Last close: 52.10\n20-session return: -12.4%"}])


def test_grounding_filter_drops_unquoted_claims():
    reply = {"verdict": "keep", "conviction": 4,
             "claims": [{"text": "CEO bought", "quote": "Chief  Executive officer", "source_id": "F4-1"},   # ws/case ok
                        {"text": "big buy", "quote": "Value: $2,500,000", "source_id": "F4-1"},           # not verbatim
                        {"text": "fell", "quote": "-12.4%", "source_id": "F4-1"},                         # wrong source
                        {"text": "x", "quote": "anything", "source_id": "NOPE"}],
             "reasons": [{"text": "CEO conviction", "claims": [0]},
                         {"text": "large", "claims": [1]},          # cites only a dropped claim -> discarded
                         "uncited reason string"]}
    g = an.ground(reply, packet())
    assert g.verdict == "keep" and g.conviction == 4
    assert [c["quote"] for c in g.claims] == ["Chief  Executive officer"]
    assert {d["why"].split(" ")[0] for d in g.dropped_claims} == {"quote", "unknown"} and len(g.dropped_claims) == 3
    assert g.reasons == [{"text": "CEO conviction", "claims": [0]}]
    # nothing grounded -> drop, reason ungrounded (whatever the model said)
    g2 = an.ground({"verdict": "keep", "conviction": 5, "claims": [{"text": "t", "quote": "made up", "source_id": "PX"}],
                    "reasons": [{"text": "r", "claims": [0]}]}, packet())
    assert g2.verdict == "drop" and g2.reason.startswith("ungrounded") and g2.reasons == []
    with pytest.raises(ValueError):
        an.ground({"verdict": "buy"}, packet())
    assert an.parse_json('```json\n{"verdict": "drop"}\n```')["verdict"] == "drop"


def test_masking_hides_company_ticker_and_insiders():
    txt = "Acme Widgets, Inc. (NASDAQ: ACMW) reported; ACME WIDGETS beat. $ACMW up. John Q. Smith bought. ACMWX stays."
    m = an.mask(txt, names=["ACME WIDGETS INC /DE/"], ticker="ACMW", insiders={"John Q. Smith": "Insider A"})
    assert "Acme" not in m and "ACME" not in m and "John" not in m
    assert "[COMPANY]" in m and "(NASDAQ: [TICKER])" in m and "[TICKER] up" in m and "Insider A bought" in m
    assert "ACMWX" in m                                          # whole words only
    # a two-letter ticker is matched case-sensitively (never the word "it")
    assert an.mask("IT rose; it fell", names=[], ticker="IT") == "[TICKER] rose; it fell"


def test_packet_build_masks_and_carries_sources():
    cd = {"id": "c1", "kind": "s1_insider", "ticker": "ACMW", "entryDate": "2026-10-08", "signalDate": "2026-10-07",
          "config": {"s1HoldSessions": 20},
          "evidence": {"insiders": [{"insiderCik": "9"}], "totalValue": 250000, "window": ["2026-10-01", "2026-10-06"],
                       "exitDate": "2026-11-04",
                       "rows": [{"insider_cik": "9", "insider_name": "SMITH JOHN", "is_officer": True,
                                 "officer_title": "CEO of Acme Widgets", "trans_date": "2026-10-06", "shares": 1000,
                                 "price": 25.0, "value": 25000, "filed_date": "2026-10-07"}]}}
    bars = [Bar("ACMW", "1d", 1_700_000_000_000 + i * 86_400_000, 25, 26, 24, 25 + i * 0.1, 100_000) for i in range(25)]
    p = an.build_packet(cd, bars=bars, sector="Widgets", events=["Next earnings date(s): 2026-12-01 (test)"],
                        filing_text=None, company_names=["ACME WIDGETS INC"])
    ids = [s["id"] for s in p.sources]
    assert ids == ["S1", "F4-1", "PX", "SEC", "EV"]
    body = p.render()
    assert "SMITH" not in body and "Acme" not in body and "Insider A" in body and "[COMPANY]" in body
    assert "Last close" in p.text_of("PX") and len(p.hash) == 64


def test_release_text_picks_the_exhibit():
    raw = ("<SEC-HEADER>COMPANY CONFORMED NAME:\t\t\tACME WIDGETS INC\n</SEC-HEADER>"
           "<DOCUMENT><TYPE>8-K\n<TEXT><html>cover</html></TEXT></DOCUMENT>"
           "<DOCUMENT><TYPE>EX-99.1\n<TEXT><html><p>Revenue grew 12%&nbsp;to $1.0B</p><p>Outlook raised</p></html></TEXT></DOCUMENT>")
    text, names = an.release_text(raw)
    assert "Revenue grew 12% to $1.0B" in text and "Outlook raised" in text and "cover" not in text
    assert names == ["ACME WIDGETS INC"]


def test_cost_and_projection():
    rates = {"claude-opus-5-5": {"in": 4.0, "out": 20.0, "cacheRead": 0.2, "cacheWrite": 5.0},
             "gpt-6.1-sol": {"in": 2.0, "out": 10.0}}
    assert an.cost_usd("claude-opus-5-5", {"in": 1_000_000, "out": 100_000}, rates) == pytest.approx(6.0)
    assert an.cost_usd("claude-opus-5-5", {"in": 0, "out": 0, "cacheRead": 1_000_000, "cacheWrite": 1_000_000},
                       rates) == pytest.approx(5.2)
    assert an.cost_usd("gpt-6.1-sol-2026-09", {"in": 1_000_000, "out": 0}, rates) == pytest.approx(2.0)   # prefix
    assert an.cost_usd("unknown", {"in": 10**6, "out": 10**6}, rates) == 0.0
    assert an.projected_cost("gpt-6.1-sol", 35_000, 8000, rates) == pytest.approx((10_001 * 2 + 8000 * 10) / 1e6)


def test_books_lanes_and_random_draw():
    assert bk.lanes_for("s1_insider", {"claude": "keep", "gpt": None}) == ["s1_screen", "s1_claude_keep"]
    assert bk.lanes_for("s2_earnings", {"claude": "drop", "gpt": "keep"}) == ["s2_screen", "s2_claude_drop", "s2_gpt_keep"]
    assert bk.lanes_for("s1_unclassified", {}) == [] and bk.lanes_for("random", {}) == []
    assert len(bk.all_lanes()) == 11 and bk.lane_label("s1_claude_keep") == "Scout S1 claude keep"
    assert bk.lane_label("s2_gpt_drop") == "Scout S2 gpt drop" and bk.lane_label("random") == "Scout random"
    pool = bk.build_pool(["AAA", "BBB"], set())
    assert len(pool) >= 20 and "AAA" in pool                     # thin pool topped up
    a = bk.draw_random("s1_insider:x", pool, exclude={"AAA"}, max_offset=4)
    assert a == bk.draw_random("s1_insider:x", pool, exclude={"AAA"}, max_offset=4)   # reproducible
    assert a[0] != "AAA" and 0 <= a[1] <= 4


# =========================================================================== integration rig
def daily(sym: str, end: dt.date, *, close: float, n: int = 40) -> list[Bar]:
    import zargar.marketstructure.market_calendar as mcal
    out, d = [], end
    while len(out) < n:
        if mcal.is_trading_day(d):
            ts = int(dt.datetime.combine(d, dt.time(9, 30), ET).timestamp() * 1000)
            out.append(Bar(sym, "1d", ts, close, close * 1.01, close * 0.99, close, 2_000_000))
        d -= dt.timedelta(days=1)
    return sorted(out, key=lambda b: b.ts)


class FakeClaude:
    def __init__(self, reply: dict | str, usage=(3000, 800)):
        self.calls: list[dict] = []
        self.reply, self.usage = reply, usage
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        txt = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=txt)], stop_reason="end_turn",
                               model=kw["model"], usage=SimpleNamespace(input_tokens=self.usage[0],
                                                                        output_tokens=self.usage[1],
                                                                        cache_read_input_tokens=0,
                                                                        cache_creation_input_tokens=0))


class FakeOpenAI:
    def __init__(self, reply: dict):
        self.calls: list[dict] = []
        self.reply = reply
        self.responses = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(output_text=json.dumps(self.reply), status="completed", model=kw["model"],
                               usage=SimpleNamespace(input_tokens=2500, output_tokens=600))


KEEP = {"verdict": "keep", "conviction": 4,
        "claims": [{"text": "two insiders", "quote": "Distinct insiders buying: 2", "source_id": "S1"}],
        "reasons": [{"text": "a real cluster", "claims": [0]}]}
DROP = {"verdict": "drop", "conviction": 3,
        "claims": [{"text": "flat", "quote": "Last close", "source_id": "PX"}],
        "reasons": [{"text": "no momentum", "claims": [0]}]}


@pytest.fixture
async def scout(engine):
    svc = ScoutService(engine)
    engine.scout_service = svc
    today = dt.datetime.now(ET).date()

    async def bars(sym, start, end):
        return daily(sym, end, close=232.0 if sym == "AAPL" else 100.0)

    async def spread(sym, entry_date, now_):
        return None, "pending"

    async def mcap(cik, close, as_of):
        return 5e9, "test"

    async def corp(sym, start, end):
        return []

    async def earnings(sym, cik, as_of):
        return ["2027-02-01"], "test"

    async def tips(sym, a, b):
        return []

    async def issuer(cik):
        return ["APPLE INC"], "Electronic computers"

    svc.daily_bars, svc.entry_spread_pct, svc.market_cap = bars, spread, mcap
    svc.corporate_actions, svc.earnings_dates, svc.tips_mentions = corp, earnings, tips
    svc.desk.issuer_facts = issuer
    svc.desk.fill_poll_s = 0.05
    await engine.settings.set("techniques.scout.entry_fill_wait_s", 8.0)
    return svc, today


async def add_candidate(engine, *, ticker="AAPL", kind="s1_insider", entry: dt.date, key=None, fail_gate=False) -> str:
    cid = new_id()
    gates = {g: {"status": "pass", "why": "test"} for g in
             ("price", "adv", "marketCap", "earningsInHold", "corporateActions", "tipsMention")}
    gates["spread"] = {"status": "unknown", "why": "pending"}
    if fail_gate:
        gates["adv"] = {"status": "fail", "why": "thin"}
    ev_ = {"insiders": [{"insiderCik": "1"}, {"insiderCik": "2"}], "totalValue": 300000.0,
           "window": [entry.isoformat(), entry.isoformat()], "exitDate": add_sessions(entry.isoformat(), 19),
           "rows": [{"accession": "0000000001-26-000001", "insider_cik": "1", "insider_name": "COOK TIM",
                     "is_officer": True, "trans_date": entry.isoformat(), "shares": 1000, "price": 230.0,
                     "value": 230000.0, "filed_date": entry.isoformat()},
                    {"accession": "0000000001-26-000002", "insider_cik": "2", "insider_name": "DOE JANE",
                     "is_director": True, "trans_date": entry.isoformat(), "shares": 300, "price": 230.0,
                     "value": 70000.0, "filed_date": entry.isoformat()}]}
    async with engine.sf() as s:
        s.add(ScoutCandidate(id=cid, key=key or f"{kind}:{ticker}:{cid}", kind=kind, ticker=ticker, issuer_cik="320193",
                             signal_ts=dt.datetime.combine(entry, dt.time(7, 0), ET), signal_date=entry.isoformat(),
                             entry_date=entry.isoformat(), status="unknown", evidence=ev_, gates=gates,
                             config={"s1HoldSessions": 20, "s2HoldSessions": 10}))
        await s.commit()
    return cid


async def count(engine, kind: str) -> int:
    async with engine.sf() as s:
        return (await s.execute(select(func.count()).select_from(Event).where(Event.type == kind))).scalar_one()


# =========================================================================== lanes
async def test_missing_openai_key_skips_the_lane_and_never_fails(scout, engine):
    svc, today = scout
    engine.config.openai_api_key = ""
    svc.desk.claude_client = FakeClaude(KEEP)
    await add_candidate(engine, entry=today)
    await add_candidate(engine, ticker="MSFT", entry=today, fail_gate=True)        # not eligible: no LLM call
    out = await svc.desk.prepare_day(at(today.isoformat(), "09:00"))
    assert out["eligible"] == 1 and out["notEligible"][0]["ticker"] == "MSFT"
    async with engine.sf() as s:
        vs = {v.lane: v for v in (await s.execute(select(ScoutVerdict))).scalars().all()}
    assert vs["gpt"].status == "skipped" and vs["gpt"].reason == "skipped: no OPENAI_API_KEY" and vs["gpt"].cost_usd == 0
    assert vs["claude"].status == "ok" and vs["claude"].verdict == "keep" and vs["claude"].claims
    assert vs["claude"].cost_usd == pytest.approx((3000 * 4 + 800 * 20) / 1e6)
    call = svc.desk.claude_client.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_config"] == {"effort": "medium"}
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"} and "thinking" not in call
    assert "COOK" not in call["messages"][0]["content"] and "AAPL" not in call["messages"][0]["content"]
    async with engine.sf() as s:
        books = sorted((await s.execute(select(ScoutEntry.book).where(ScoutEntry.ticker == "AAPL"))).scalars().all())
    assert books == ["s1_claude_keep", "s1_screen"]                               # no gpt book without a verdict
    assert await count(engine, ev.SCOUT_VERDICT) == 2


async def test_budget_stop_is_shared_and_journaled(scout, engine):
    svc, today = scout
    # each call costs 50k in + 10k out on Opus 5.5 = $0.40; the worst case projection is far above that
    svc.desk.claude_client = FakeClaude(KEEP, usage=(50_000, 10_000))
    svc.desk.openai_client = FakeOpenAI(DROP)
    await engine.settings.set("techniques.scout.llm_budget_usd_day", 0.5)
    for t in ("AAPL", "MSFT", "NVDA"):
        await add_candidate(engine, ticker=t, entry=today)
    await svc.desk.prepare_day(at(today.isoformat(), "09:00"))
    async with engine.sf() as s:
        vs = (await s.execute(select(ScoutVerdict))).scalars().all()
    by = {}
    for v in vs:
        by.setdefault(v.lane, []).append(v.status)
    assert by["claude"].count("ok") == 1 and by["claude"].count("budget") == 2     # $0.40 used, next call can't fit
    assert "budget" in by["gpt"]
    spent = (await svc.desk.spent_today(today.isoformat()))["total"]
    assert spent <= 0.5 + 1e-9
    assert await count(engine, ev.SCOUT_BUDGET_STOP) == 2                         # once per lane per day
    assert len(svc.desk.claude_client.calls) == 1


async def test_unparseable_reply_is_an_error_not_a_crash(scout, engine):
    svc, today = scout
    svc.desk.claude_client = FakeClaude("I think it is fine.")
    svc.desk.openai_client = FakeOpenAI(KEEP)
    await add_candidate(engine, entry=today)
    await svc.desk.prepare_day(at(today.isoformat(), "09:00"))
    async with engine.sf() as s:
        vs = {v.lane: v for v in (await s.execute(select(ScoutVerdict))).scalars().all()}
    assert vs["claude"].status == "error" and "unparseable" in vs["claude"].reason
    assert vs["gpt"].status == "ok" and vs["gpt"].verdict == "keep"
    assert svc.desk.openai_client.calls[0]["reasoning"] == {"effort": "medium"}


# =========================================================================== books, entries, exits
async def test_research_books_entries_and_separation(scout, engine):
    svc, today = scout
    svc.desk.claude_client = FakeClaude(KEEP)
    svc.desk.openai_client = FakeOpenAI(DROP)
    await engine.settings.set("techniques.scout.random_max_offset_sessions", 0)    # twin enters the same day
    cid = await add_candidate(engine, entry=today)
    out = await svc.desk.prepare_day(at(today.isoformat(), "09:00"))
    assert out["entriesPlanned"] == 3 and out["random"] == 1
    await wait_for(lambda: engine.quotes.get("AAPL") is not None)
    async with engine.sf() as s:
        twin = (await s.execute(select(ScoutCandidate).where(ScoutCandidate.kind == "random"))).scalar_one()
    assert twin.evidence["matchedCandidateId"] == cid and twin.ticker != "AAPL"
    await wait_for(lambda: engine.quotes.get(twin.ticker) is not None)
    res = await svc.desk.attempt_entries(at(today.isoformat(), "10:00"))
    assert res["entered"] == 4, res
    async with engine.sf() as s:
        es = {e.book: e for e in (await s.execute(select(ScoutEntry))).scalars().all()}
        orders = (await s.execute(select(Order))).scalars().all()
    assert set(es) == {"s1_screen", "s1_claude_keep", "s1_gpt_drop", "random"}
    for e in es.values():
        assert e.status == "entered" and e.qty >= 1
        assert e.entry_price * e.qty <= 600 * 1.003 and e.fees == 1.0
        assert e.stop_price == pytest.approx(e.entry_price - 2 * e.atr, abs=0.01)
        assert len(e.attempts) == 1 and e.attempts[0]["action"] == "enter"
    # every entry went through the OrderManager (RiskGate) as a technique order on a SHADOW book
    buys = [o for o in orders if o.side == "BUY"]
    assert len(buys) == 4 and all(o.technique == "scout" and o.source == "technique" for o in buys)
    for e in es.values():
        pf = engine.positions.portfolio(e.portfolio_id)
        assert pf["kind"] == "shadow" and pf["book"] == "scout" and pf["sourceName"] == f"scout:{e.book}"
        assert engine.executor_for(pf) is engine.sim_executor                    # never a broker
        p = engine.position_manager.get(e.position_id)
        assert p.technique == "scout" and p.policy["timeframe"] == "1d"
        assert p.policy["stop"]["price"] == e.stop_price and p.policy["time_stop_sessions"] == e.hold_sessions - 1
    # never in a money total: the desk ledger (real books only) has no Scout book
    from zargar.desk import DeskService
    led = await DeskService(engine).ledger(days=1)
    scout_pids = {e.portfolio_id for e in es.values()}
    assert not (scout_pids & {r.get("portfolioId") for r in (led.get("rows") or led.get("trades") or [])})
    # the spread gate was judged live and recorded on the candidate
    async with engine.sf() as s:
        c = await s.get(ScoutCandidate, cid)
    assert c.gates["spread"]["status"] == "pass" and c.status == "pass"
    assert await count(engine, ev.SCOUT_ENTRY) == 4 and await count(engine, ev.SCOUT_ENTRY_ATTEMPT) == 2
    # the API reads: candidates with verdicts + entries + SEC links, lanes, status
    app = create_app(make_test_config(), engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        cands = (await h.get("/api/scout/candidates", params={"days": 30})).json()
        aapl = next(x for x in cands if x["ticker"] == "AAPL")
        assert {v["lane"] for v in aapl["verdicts"]} == {"claude", "gpt"} and len(aapl["entries"]) == 3
        assert aapl["links"][0]["url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")
        lanes = (await h.get("/api/scout/lanes")).json()
        assert {l["lane"] for l in lanes} == set(bk.all_lanes())
        assert next(l for l in lanes if l["lane"] == "s1_screen")["open"] == 1
        st = (await h.get("/api/scout/status")).json()
        assert st["llm"]["budgetUsd"] == 15.0 and "llm_budget_usd_day" in st["settings"]
        assert "api_key" not in json.dumps(st).lower().replace("keypresent", "")


async def test_entry_spread_retry_then_skip(scout, engine):
    svc, today = scout
    svc.desk.claude_client = FakeClaude(KEEP)
    svc.desk.openai_client = FakeOpenAI(KEEP)
    await engine.settings.set("techniques.scout.random_lane_enabled", False)
    await add_candidate(engine, entry=today)
    await svc.desk.prepare_day(at(today.isoformat(), "09:00"))

    async def wide(t):
        return {"bid": 99.0, "ask": 100.0, "ts": 0}                 # ~1% wide
    svc.desk.quote_of = wide
    d = today.isoformat()
    assert (await svc.desk.attempt_entries(at(d, "09:59"))) ["retry"] == 0          # before 10:00: nothing judged
    for hhmm in ("10:00", "10:15", "10:30", "10:45", "11:00", "11:15"):
        r = await svc.desk.attempt_entries(at(d, hhmm))
        assert r["retry"] == 1 and r["entered"] == 0
    r = await svc.desk.attempt_entries(at(d, "11:30"))
    assert r["skipped"] == 3
    async with engine.sf() as s:
        es = (await s.execute(select(ScoutEntry))).scalars().all()
        orders = (await s.execute(select(func.count()).select_from(Order))).scalar_one()
    assert all(e.status == "skipped" and e.reason.startswith("spread:") for e in es)
    assert all(len(e.attempts) == 7 for e in es) and orders == 0


async def test_window_missed_and_kill_switch(scout, engine):
    svc, today = scout
    svc.desk.claude_client = FakeClaude(KEEP)
    svc.desk.openai_client = FakeOpenAI(KEEP)
    await engine.settings.set("techniques.scout.random_lane_enabled", False)
    await add_candidate(engine, entry=today)
    await svc.desk.prepare_day(at(today.isoformat(), "09:00"))
    await engine.engage_halt("test halt")
    r = await svc.desk.attempt_entries(at(today.isoformat(), "10:00"))
    async with engine.sf() as s:
        es = (await s.execute(select(ScoutEntry))).scalars().all()
    assert all(e.status == "skipped" and e.reason.startswith("halted") for e in es) and r.get("skipped", 0) == 3
    await engine.release_halt()
    await add_candidate(engine, ticker="MSFT", entry=today)
    await svc.desk.prepare_day(at(today.isoformat(), "09:00"))
    r = await svc.desk.attempt_entries(at(today.isoformat(), "14:00"))           # the job ran late
    async with engine.sf() as s:
        ms = (await s.execute(select(ScoutEntry).where(ScoutEntry.ticker == "MSFT"))).scalars().all()
    assert ms and all(e.status == "skipped" and e.reason.startswith("window_missed") for e in ms)


async def _entered(svc, engine, today) -> ScoutEntry:
    svc.desk.claude_client = FakeClaude(KEEP)
    engine.config.openai_api_key = ""
    await engine.settings.set("techniques.scout.random_lane_enabled", False)
    await engine.settings.set("techniques.scout.claude_enabled", False)
    await add_candidate(engine, entry=today)
    await svc.desk.prepare_day(at(today.isoformat(), "09:00"))
    await wait_for(lambda: engine.quotes.get("AAPL") is not None)
    r = await svc.desk.attempt_entries(at(today.isoformat(), "10:00"))
    assert r["entered"] == 1, r
    async with engine.sf() as s:
        return (await s.execute(select(ScoutEntry).where(ScoutEntry.status == "entered"))).scalar_one()


def closing_bar(sym: str, day: str, close: float) -> Bar:
    ts = int(dt.datetime.fromisoformat(f"{day}T15:59:00").replace(tzinfo=ET).timestamp() * 1000)
    return Bar(sym, "1m", ts, close, close, close, close, 1000)


async def test_time_exit_through_the_position_manager(scout, engine):
    svc, today = scout
    e = await _entered(svc, engine, today)
    pm = engine.position_manager
    p = pm.get(e.position_id)
    day = p.sessions_seen[0]
    for k in range(1, e.hold_sessions - 1):                                    # 18 closed sessions: still held
        await pm.on_minute_bar(p, closing_bar("AAPL", add_sessions(day, k), e.entry_price))
    assert pm.get(e.position_id) is not None and pm.get(e.position_id).status == "open"
    await pm.on_minute_bar(p, closing_bar("AAPL", add_sessions(day, e.hold_sessions - 1), e.entry_price))
    await wait_for(lambda: pm.get(e.position_id) is None)                      # the time exit filled -> closed
    assert await svc.desk.sync_entries() == 1
    async with engine.sf() as s:
        row = await s.get(ScoutEntry, e.id)
    assert row.status == "closed" and "time" in (row.exit_reason or "") and row.orders_filled == 2
    assert row.fees == 2.0 and row.net_pnl == pytest.approx(row.gross_pnl - 2.0)
    rep = await svc.desk.daily_report(at(today.isoformat(), "16:30"))
    lane = next(l for l in rep["lanes"] if l["lane"] == "s1_screen")
    assert lane["closed"] == 1 and lane["realizedNet"] == pytest.approx(row.net_pnl, abs=0.01)
    assert await count(engine, ev.SCOUT_DAILY_REPORT) == 1
    assert (await svc.desk.reports())[0]["day"] == today.isoformat()


async def test_atr_stop_exit_through_the_position_manager(scout, engine):
    svc, today = scout
    e = await _entered(svc, engine, today)
    pm = engine.position_manager
    p = pm.get(e.position_id)
    day = p.sessions_seen[0]
    # (the first daily decision may read the sim feed's own 5m bar; raw bars decide from the second one on)
    await pm.on_minute_bar(p, closing_bar("AAPL", add_sessions(day, 1), e.entry_price))
    assert pm.get(e.position_id).status == "open"
    await pm.on_minute_bar(p, closing_bar("AAPL", add_sessions(day, 2), e.stop_price - 0.5))   # close below fill - 2 x ATR
    await wait_for(lambda: pm.get(e.position_id) is None)
    await svc.desk.sync_entries()
    async with engine.sf() as s:
        row = await s.get(ScoutEntry, e.id)
    assert row.status == "closed" and "stop" in (row.exit_reason or "").lower()


async def test_attach_registers_the_p3_schedule(engine):
    from zargar.techniques.scout.service import attach_scout_layer
    engine.scout_service = None
    attach_scout_layer(engine)
    names = {j["name"]: j["at"] for j in engine.scheduler.status() if j["name"].startswith("scout_")}
    assert names["scout_daily"] == "07:00" and names["scout_verdicts"] == "09:00" and names["scout_report"] == "16:30"
    assert [n for n in sorted(names) if n.startswith("scout_entry_")] == [
        "scout_entry_1000", "scout_entry_1015", "scout_entry_1030", "scout_entry_1045", "scout_entry_1100",
        "scout_entry_1115", "scout_entry_1130"]
    await engine.scout_service.stop()
    assert not [j for j in engine.scheduler.status() if j["name"].startswith("scout_")]
