"""Scout agent (PLAN section 9): chart tools, the code checks on proposals, sizing/policy, the scorecard and gate,
and the end-to-end day on fake provider clients (NO model call is ever made here): tools -> proposals -> checks
-> research-book entries (agent, random twin, screen lane) -> fills through OrderManager on shadow books."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from zargar import events as ev
from zargar.domain import Bar, new_id
from zargar.models import Event, Order, ScoutAgentLesson, ScoutAgentRun, ScoutCandidate, ScoutEntry
from zargar.techniques.scout import agent_plan as ap
from zargar.techniques.scout import agent_score as sc
from zargar.techniques.scout import agent_tools as at
from zargar.techniques.scout.form4 import ET
from zargar.techniques.scout.service import ScoutService

from .conftest import wait_for


def trend_bars(sym: str, end: dt.date, *, last: float, n: int = 260, drift: float = 0.002, rng: float = 0.01) -> list[Bar]:
    """n daily bars ending the session before `end`, rising by `drift` a day into `last`."""
    import zargar.marketstructure.market_calendar as mcal
    days, d = [], end - dt.timedelta(days=1)
    while len(days) < n:
        if mcal.is_trading_day(d):
            days.append(d)
        d -= dt.timedelta(days=1)
    days.reverse()
    out = []
    for i, day in enumerate(days):
        c = last / ((1 + drift) ** (n - 1 - i))
        ts = int(dt.datetime.combine(day, dt.time(9, 30), ET).timestamp() * 1000)
        out.append(Bar(sym, "1d", ts, c * (1 - rng / 4), c * (1 + rng / 2), c * (1 - rng / 2), c, 3_000_000))
    return out


# =========================================================================== tools (pure)
def test_chart_read_and_render_are_numbers_only():
    end = dt.date(2026, 10, 14)
    r = at.chart_read(trend_bars("AAA", end, last=100.0), trend_bars("SPY", end, last=500.0, drift=0.0005))
    assert r["trend"] == "uptrend" and r["last"] == pytest.approx(100.0)
    assert r["sma20"] < 100 and r["sma50"] < r["sma20"] and r["sma200"] < r["sma50"]
    assert r["atr14"] == pytest.approx(1.0, rel=0.25) and r["vsSpy"]["60d"] > 0
    assert len(r["recent"]) == 10 and r["support"] == []        # a straight line has no swing low
    txt = at.render_chart("AAA", r)
    assert "trend: uptrend" in txt and "ATR(14):" in txt and "last 10 sessions" in txt
    assert "support: no swing low below the last close" in txt
    # a zigzag: swing lows near 90 and highs near 110, last close 100
    zz = []
    for i in range(60):
        c = 100 + 10 * (1 if (i // 5) % 2 else -1) * (1 - abs((i % 5) - 2) / 2.5)
        zz.append(Bar("Z", "1d", 1_760_000_000_000 + i * 86_400_000, c, c + 0.5, c - 0.5, c, 1_000_000))
    zz.append(Bar("Z", "1d", 1_760_000_000_000 + 60 * 86_400_000, 100, 100.5, 99.5, 100, 1_000_000))
    lv = at.levels(zz)
    assert any(x["kind"] == "support" and x["price"] < 95 and x["touches"] >= 2 for x in lv)
    assert any(x["kind"] == "resistance" and x["price"] > 105 for x in lv)
    assert at.chart_read([], None) == {} and "not enough daily history" in at.render_chart("X", {})


def test_screen_ranks_strength_and_filters_weak_and_illiquid():
    end = dt.date(2026, 10, 14)
    spy = trend_bars("SPY", end, last=500.0, drift=0.0005)
    reads = {"UP": at.chart_read(trend_bars("UP", end, last=50.0, drift=0.004), spy),
             "MILD": at.chart_read(trend_bars("MILD", end, last=50.0, drift=0.001), spy),
             "DOWN": at.chart_read(trend_bars("DOWN", end, last=50.0, drift=-0.003), spy),
             "PENNY": at.chart_read(trend_bars("PENNY", end, last=3.0, drift=0.004), spy)}
    rows = at.screen(reads)
    assert [x["ticker"] for x in rows] == ["UP", "MILD"]                    # below the 50-day / under $5 never shown
    txt = at.render_screen(rows, [{"ticker": "ZZZ", "what": "earnings reaction"}], universe=4)
    assert txt.splitlines()[1].startswith("1. UP score") and "ZZZ: earnings reaction" in txt


def test_expected_move_from_iv_and_straddle():
    em = at.expected_move(spot=100.0, straddle_mid=4.0, dte=10, iv30=0.32)
    assert em["straddlePct"] == pytest.approx(4.0) and em["move10dPct"] == pytest.approx(32 * (10 / 252) ** 0.5, rel=1e-6)
    assert at.expected_move(spot=100.0, straddle_mid=None, dte=None, iv30=32.0)["move1dPct"] == pytest.approx(
        32 / 252 ** 0.5, rel=1e-6)                                         # 32 and 0.32 read the same
    assert "no option chain" in at.render_options("X", {"spot": None}, expiry=None, provider=None)


# =========================================================================== proposal checks (pure)
CHART = {"last": 100.0, "atr14": 2.0, "advUsd20": 2e8}
RESULTS = {"T3": "AAA daily chart\ntrend: uptrend\nsupport 96.00 (-4.00% away, 2 touch(es), last 2026-10-01)",
           "T4": "AAA next earnings date(s): 2026-11-20 (test)"}
GOOD = {"ticker": "aaa", "side": "long", "entry": {"kind": "now"}, "stop": 95.5, "targets": [107.0, 111.0],
        "horizon_sessions": 10, "conviction": 4, "thesis": "uptrend pullback to support",
        "evidence": [{"result_id": "T3", "quote": "trend:   UPTREND"},                  # whitespace/case-insensitive
                     {"result_id": "t3", "quote": "support 96.00 (-4.00% away"},
                     {"result_id": "T4", "quote": "this is not in the result"}]}
AHEAD = [(dt.date(2026, 10, 14) + dt.timedelta(days=k)).isoformat() for k in range(1, 60)
         if (dt.date(2026, 10, 14) + dt.timedelta(days=k)).weekday() < 5]


def chk(p, **kw):
    args = dict(chart=CHART, results=RESULTS, held=set(), proposed=set(), earnings=["2026-11-20"],
                today="2026-10-14", sessions_ahead=AHEAD)
    args.update(kw)
    return ap.check(p, **args)


def test_a_grounded_proposal_passes_with_its_plan():
    c = chk(GOOD)
    assert c.ok and c.ticker == "AAA" and len(c.evidence) == 2 and len(c.dropped_evidence) == 1
    assert c.plan["stop"] == 95.5 and c.plan["stopAtr"] == pytest.approx(2.25) and c.plan["targetsR"][0] == pytest.approx(1.556, abs=1e-3)
    assert c.plan["horizon"] == 10 and c.plan["entry"] == {"kind": "now", "limit": None, "ref": 100.0}


@pytest.mark.parametrize("patch,needle", [
    ({"evidence": [{"result_id": "T3", "quote": "trend: uptrend"}]}, "ungrounded"),
    ({"stop": 99.5}, "inside normal noise"),
    ({"stop": 90.0}, "max 4"),
    ({"stop": 101.0}, "not below the entry"),
    ({"targets": [104.0]}, "first target is"),
    ({"targets": [110.0, 105.0]}, "not ascending"),
    ({"side": "short"}, "long only"),
    ({"horizon_sessions": 30}, "horizon 30"),
    ({"conviction": 9}, "conviction"),
    ({"entry": {"kind": "limit", "limit_price": 101.0}}, "above the last close"),
])
def test_bad_proposals_are_refused(patch, needle):
    c = chk({**GOOD, **patch})
    assert not c.ok and any(needle in r for r in c.reasons), c.reasons


def test_eligibility_and_earnings_cut():
    assert "call chart first" in chk(GOOD, chart=None).reasons[0]
    assert any("already held" in r for r in chk(GOOD, held={"AAA"}).reasons)
    assert any("below $5M" in r or "dollar volume" in r for r in chk(GOOD, chart={**CHART, "advUsd20": 1e6}).reasons)
    # earnings on the 5th session after today: the hold is cut to 5 sessions (exit the session before)
    c = chk(GOOD, earnings=[AHEAD[4]])
    assert c.ok and c.plan["horizon"] == 5 and "horizon cut 10 -> 5" in c.notes[0]
    c2 = chk(GOOD, earnings=[AHEAD[1]])
    assert not c2.ok and "only 2 session(s)" in c2.reasons[0]
    # a limit entry below the last close: the plan is built on the limit
    c3 = chk({**GOOD, "entry": {"kind": "limit", "limit_price": 98.0}, "stop": 94.0, "targets": [104.0]})
    assert c3.ok and c3.plan["entry"]["ref"] == 98.0 and c3.plan["limitAtr"] == pytest.approx(1.0)


def test_sizing_policy_and_limit_gate():
    q, why = ap.size(equity=10_000, cash=10_000, fill=100.0, stop=96.0, risk_pct=1.0, max_position_pct=20.0)
    assert q == 20 and "position cap" in why                                 # risk says 25, the 20% cap says 20
    assert ap.size(equity=10_000, cash=10_000, fill=100.0, stop=90.0, risk_pct=1.0, max_position_pct=20.0)[0] == 10
    assert ap.size(equity=10_000, cash=500, fill=100.0, stop=96.0, risk_pct=1.0, max_position_pct=20.0)[0] == 5
    assert ap.size(equity=10_000, cash=10_000, fill=95.0, stop=96.0, risk_pct=1.0, max_position_pct=20.0)[0] == 0
    plan = chk(GOOD).plan
    pol = ap.policy(plan, stop=95.5, targets=[107.0, 111.0])
    assert pol["ladder"] == {"targets": [107.0, 111.0], "fractions": [0.5, 0.5]} and pol["breakeven_on_trim"]
    assert pol["time_stop_sessions"] == 9 and pol["stop"] == {"kind": "fixed", "price": 95.5}
    assert ap.policy(plan, stop=95.5, targets=[107.0])["ladder"]["fractions"] == [1.0]
    lim = {"entry": {"kind": "limit", "limit": 98.0}}
    assert ap.limit_gate(lim, 98.5)[0] is False and ap.limit_gate(lim, 98.0)[0] is True
    assert ap.limit_gate(plan, 150.0)[0] is True and ap.limit_gate(None, None)[0] is True
    twin = ap.like_plan(plan, {"last": 50.0, "atr14": 1.0})
    assert twin["stop"] == pytest.approx(50 - 2.25) and twin["targetsR"] == plan["targetsR"]
    assert twin["targets"][0] == pytest.approx(50 + plan["targetsR"][0] * 2.25, abs=0.01)
    d = ap.default_plan({"last": 40.0, "atr14": 1.0})
    assert d["stop"] == 38.0 and d["targets"] == [44.0, 46.0] and d["horizon"] == 10
    assert ap.draw_twin("k", ["B", "C", "A"], {"A"}) == ap.draw_twin("k", ["C", "B"], set())   # reproducible


# =========================================================================== scorecard + gate (pure)
def entry(day: str, net: float, *, qty=10, entry_px=100.0, stop=95.0) -> dict:
    return {"entryDate": day, "netPnl": net, "qty": qty, "entryPrice": entry_px, "stopPrice": stop}


def test_r_multiple_and_clustered_comparison():
    assert sc.r_multiple(entry("2026-10-15", 100.0)) == pytest.approx(2.0)
    assert sc.r_multiple({"netPnl": 1}) is None
    days = [f"2026-10-{d:02d}" for d in range(15, 31)]
    a = [entry(d, 75.0) for d in days for _ in range(3)]            # +1.5R every trade
    b = [entry(d, -25.0) for d in days]                             # -0.5R
    cmp = sc.clustered_diff(a, b, resamples=500)
    assert cmp["diff"] == pytest.approx(2.0) and cmp["lo"] == pytest.approx(2.0) and cmp["sessions"] == 16
    st = sc.lane_stats(a)
    assert st["closed"] == 48 and st["meanR"] == pytest.approx(1.5) and st["hitRate"] == 1.0


def test_gate_needs_sample_size_time_and_a_positive_lower_bound():
    days = [f"2026-1{m}-{d:02d}" for m in (0, 1) for d in range(1, 29)]
    a = [entry(d, 30.0 if i % 2 else -20.0) for i, d in enumerate(days)]
    b = [entry(d, -10.0) for d in days]
    g = sc.gate(a, b, start="2026-10-01", today="2026-12-15")
    assert {c["name"]: c["ok"] for c in g["checks"]}["closed trades"] is True
    assert g["passed"] is True and g["verdict"].startswith("passed")
    g2 = sc.gate(a[:10], b, start="2026-10-01", today="2026-10-20")
    assert g2["passed"] is False and g2["verdict"] == "no proven edge yet"
    assert [c["ok"] for c in g2["checks"]][:2] == [False, False]


# =========================================================================== end to end (fake providers)
def blk(**kw):
    return SimpleNamespace(**kw)


class ScriptedClaude:
    """Turn 1: chart AAPL + events AAPL; turn 2: submit (one good proposal, one for a name never charted)."""

    def __init__(self, propose):
        self.calls: list[dict] = []
        self.propose = propose
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append({**kw, "messages": json.loads(json.dumps(kw["messages"], default=lambda o: o.__dict__))})
        usage = SimpleNamespace(input_tokens=5000, output_tokens=900, cache_read_input_tokens=2000,
                                cache_creation_input_tokens=1000)
        if len(self.calls) == 1:
            content = [blk(type="text", text="Looking at AAPL."),
                       blk(type="tool_use", id="tu1", name="chart", input={"ticker": "AAPL"}),
                       blk(type="tool_use", id="tu2", name="events", input={"ticker": "AAPL"})]
        else:
            content = [blk(type="tool_use", id="tu3", name="submit_proposals", input=self.propose())]
        return SimpleNamespace(content=content, stop_reason="tool_use", model=kw["model"], usage=usage)


class ScriptedOpenAI:
    def __init__(self):
        self.calls: list[dict] = []
        self.responses = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        u = SimpleNamespace(input_tokens=4000, output_tokens=500)
        if len(self.calls) == 1:
            out = [blk(type="reasoning"), blk(type="function_call", call_id="c1", name="chart",
                                              arguments=json.dumps({"ticker": "MSFT"}))]
        else:
            out = [blk(type="function_call", call_id="c2", name="submit_proposals",
                       arguments=json.dumps({"proposals": [], "no_trade_reason": "nothing clean today"}))]
        return SimpleNamespace(id=f"resp{len(self.calls)}", output=out, usage=u, model=kw["model"])


UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMD", "META", "KO"]


@pytest.fixture
async def agent_rig(engine):
    svc = ScoutService(engine)
    engine.scout_service = svc
    today = dt.datetime.now(ET).date()
    for t in UNIVERSE + ["SPY"]:
        await engine.ensure_symbol(t)
    await wait_for(lambda: all(engine.quotes.get(t) is not None and engine.quotes.get(t).last > 0 for t in UNIVERSE))
    base = {t: float(engine.quotes.get(t).last) for t in UNIVERSE}
    drift = {"AAPL": 0.004, "MSFT": 0.003, "NVDA": 0.0035, "AMD": 0.0025, "META": 0.002, "KO": -0.002}

    async def bars(sym, start, end):
        if sym == "SPY":
            return trend_bars("SPY", end + dt.timedelta(days=1), last=500.0, drift=0.0005)
        return trend_bars(sym, end + dt.timedelta(days=1), last=base[sym], drift=drift.get(sym, 0.001))

    async def earnings(sym, cik, as_of):
        return ["2027-02-01"], "test"

    svc.daily_bars, svc.earnings_dates = bars, earnings
    svc.agent.universe = lambda: list(UNIVERSE)

    async def no_cik(t):
        return None
    svc.dossier.cik_for_ticker = no_cik
    svc.desk.fill_poll_s = 0.05
    await engine.settings.set("techniques.scout.entry_fill_wait_s", 8.0)
    await engine.settings.set("risk.max_position_notional", 25_000.0)        # the runtime value (test default $1k)
    return svc, today


def morning(today: dt.date, hhmm: str = "07:30") -> dt.datetime:
    return dt.datetime.combine(today, dt.time(int(hhmm[:2]), int(hhmm[3:])), ET)


async def test_the_agent_day_end_to_end(agent_rig, engine):
    svc, today = agent_rig
    day = today.isoformat()
    engine.config.openai_api_key = ""                                    # the GPT lane records skipped

    def propose():
        r = svc.agent._reads[day]["AAPL"]
        last, a = r["last"], r["atr14"]
        stop = round(last - 2.2 * a, 2)
        return {"proposals": [
            {"ticker": "AAPL", "side": "long", "entry": {"kind": "now"}, "stop": stop,
             "targets": [round(last + 2.5 * (last - stop), 2), round(last + 4 * (last - stop), 2)],
             "horizon_sessions": 8, "conviction": 4, "thesis": "steady uptrend, leading SPY",
             "invalidation": "a close under the 20-day average",
             "evidence": [{"result_id": "T3", "quote": "trend: uptrend", "point": "trend up"},
                          {"result_id": "T3", "quote": "50-day average slope over 10 sessions", "point": "rising"}]},
            {"ticker": "NVDA", "side": "long", "entry": {"kind": "now"}, "stop": 1, "targets": [2],
             "horizon_sessions": 8, "conviction": 3, "thesis": "x", "evidence": []}]}

    svc.agent.claude_client = ScriptedClaude(propose)
    out = await svc.agent.run_day(morning(today))
    assert out["lanes"]["claude"]["status"] == "ok", out
    assert out["lanes"]["gpt"]["status"] == "skipped" and "OPENAI" in out["lanes"]["gpt"]["reason"]
    call0, call1 = svc.agent.claude_client.calls
    assert call0["model"] == "claude-opus-5-5" and call0["output_config"] == {"effort": "high"}
    assert call0["system"][0]["cache_control"] == {"type": "ephemeral"} and "thinking" not in call0
    assert {t["name"] for t in call0["tools"]} >= {"chart", "fundamentals", "options_view", "submit_proposals"}
    first = call0["messages"][0]["content"][0]["text"]
    assert "[T1] momentum / relative-strength screen" in first and "[T2] research book Scout Agent Claude" in first
    # one moving cache breakpoint: only the newest user block carries it
    marks = [b for m in call1["messages"] if m["role"] == "user" for b in m["content"]
             if isinstance(b, dict) and b.get("cache_control")]
    assert len(marks) == 1 and call1["messages"][-1]["content"][-1].get("cache_control")
    tr = call1["messages"][-1]["content"]
    assert tr[0]["type"] == "tool_result" and tr[0]["content"].startswith("[T3] AAPL daily chart")
    async with engine.sf() as s:
        run = (await s.execute(select(ScoutAgentRun).where(ScoutAgentRun.lane == "claude"))).scalar_one()
        entries = {e.book: e for e in (await s.execute(select(ScoutEntry))).scalars().all() if e.book != "agent_screen"}
        screen = (await s.execute(select(ScoutEntry).where(ScoutEntry.book == "agent_screen"))).scalars().all()
    assert run.status == "ok" and run.tool_calls == 2 and run.cost_usd > 0 and len(run.transcript) == 4
    ok = [p for p in run.proposals if p["check"]["ok"]]
    bad = [p for p in run.proposals if not p["check"]["ok"]]
    assert [p["ticker"] for p in ok] == ["AAPL"] and bad[0]["ticker"] == "NVDA"
    assert any("call chart first" in r for r in bad[0]["check"]["reasons"])
    assert set(entries) == {"agent_claude", "agent_random"}
    twin = entries["agent_random"]
    assert twin.ticker not in ("AAPL",) and twin.config["plan"]["stopAtr"] == entries["agent_claude"].config["plan"]["stopAtr"]
    assert entries["agent_claude"].hold_sessions == 8 and entries["agent_claude"].status == "pending"
    assert 1 <= len(screen) <= 3 and all(e.config["plan"]["stopAtr"] == 2.0 for e in screen)
    assert await _count(engine, ev.SCOUT_AGENT_RUN) == 2 and await _count(engine, ev.SCOUT_AGENT_PROPOSAL) == 2
    # the agent's picks are not Scout screen candidates
    assert all(not c["kind"].startswith("agent") for c in await svc.candidates(days=3))
    # idempotent: a second run the same day makes no new call and no new entry
    again = await svc.agent.run_day(morning(today))
    assert again["lanes"]["claude"]["id"] == run.id and len(svc.agent.claude_client.calls) == 2
    # 10:00 ET: the usual entry rule fills them on SHADOW books, sized by risk
    for t in {e.ticker for e in entries.values()} | {e.ticker for e in screen}:
        await wait_for(lambda t=t: engine.quotes.get(t) is not None)
    res = await svc.desk.attempt_entries(morning(today, "10:00"))
    async with engine.sf() as s:
        es = {e.id: e for e in (await s.execute(select(ScoutEntry))).scalars().all()}
        buys = (await s.execute(select(Order).where(Order.side == "BUY"))).scalars().all()
    assert res.get("entered", 0) == len(es), (res, [(x.book, x.ticker, x.status, x.reason, x.attempts) for x in es.values()])
    e = es[entries["agent_claude"].id]
    plan = e.config["plan"]
    assert e.status == "entered" and e.stop_price == plan["stop"]
    pf = engine.positions.portfolio(e.portfolio_id)
    assert pf["kind"] == "shadow" and pf["name"] == "Scout Agent Claude" and engine.executor_for(pf) is engine.sim_executor
    assert pf["startingCash"] == 10_000 if "startingCash" in pf else True
    want, _ = ap.size(equity=10_000, cash=10_000, fill=e.entry_price, stop=plan["stop"], risk_pct=1.0,
                      max_position_pct=20.0)
    assert abs(e.qty - want) <= 1
    p = engine.position_manager.get(e.position_id)
    assert p.policy["ladder"]["targets"] == [t for t in plan["targets"] if t > e.entry_price]
    assert p.policy["time_stop_sessions"] == 7 and p.policy["stop"]["price"] == plan["stop"]
    assert all(o.technique == "scout" for o in buys) and len(buys) == len(es)
    # the scorecard and the report section read
    card = await svc.agent.scorecard(day)
    assert card["lanes"]["agent_claude"]["open"] == 1 and card["gate"]["passed"] is False
    rep = await svc.desk.daily_report(morning(today, "16:30"))
    assert rep["agent"]["runs"] and rep["agent"]["budgetUsd"] == 10.0


async def test_gpt_lane_tool_loop_and_no_trade(agent_rig, engine):
    svc, today = agent_rig
    await engine.settings.set("techniques.scout.agent_claude_enabled", False)
    await engine.settings.set("techniques.scout.agent_screen_lane_enabled", False)
    svc.agent.openai_client = ScriptedOpenAI()
    out = await svc.agent.run_day(morning(today))
    assert out["lanes"]["claude"]["status"] == "skipped"
    g = out["lanes"]["gpt"]
    assert g["status"] == "no_trade" and g["reason"] == "nothing clean today" and g["toolCalls"] == 1
    c0, c1 = svc.agent.openai_client.calls
    assert c0["model"] == "gpt-6.1-sol" and c0["reasoning"] == {"effort": "high"} and "previous_response_id" not in c0
    assert c1["previous_response_id"] == "resp1" and c1["input"][0]["type"] == "function_call_output"
    assert c1["input"][0]["output"].startswith("[T3] MSFT daily chart")
    async with engine.sf() as s:
        assert (await s.execute(select(func.count()).select_from(ScoutEntry))).scalar_one() == 0


def test_a_limit_is_worked_for_its_sessions_then_expires():
    from zargar.techniques.scout import entry as er
    from zargar.techniques.scout.screens import add_sessions
    d0 = "2026-10-21"                                                       # a Wednesday
    d1, d2, d3 = add_sessions(d0, 1), add_sessions(d0, 2), add_sessions(d0, 3)
    assert er.session_index(d0, d0) == 0 and er.session_index(d0, d2) == 2 and er.session_index(d0, "2026-10-20") is None
    assert er.limit_window(d0, d0, 3) == (d0, True) and er.limit_window(d0, d1, 3) == (d1, True)
    assert er.limit_window(d0, d2, 3) == (d2, False)                         # the last session: no carry
    assert er.limit_window(d0, d3, 3) is None and er.limit_window(d0, d1, 1) is None


async def test_an_unreached_limit_carries_to_the_next_session_and_fills_there(agent_rig, engine):
    """2026-10-21 (PLAN 9.8): 3 of 18 agent picks filled when a limit was tried 10:00-11:30 ET on day 1 only."""
    from zargar.techniques.scout.screens import add_sessions
    svc, today = agent_rig
    day = today.isoformat()
    engine.config.openai_api_key = ""
    await engine.settings.set("techniques.scout.agent_screen_lane_enabled", False)
    await engine.settings.set("techniques.scout.agent_random_lane_enabled", False)

    def propose():
        r = svc.agent._reads[day]["AAPL"]
        last, a = r["last"], r["atr14"]
        lim = round(last - 0.8 * a, 2)                                       # well under the market: not reached
        stop = round(lim - 2.0 * a, 2)
        return {"proposals": [
            {"ticker": "AAPL", "side": "long", "entry": {"kind": "limit", "limit_price": lim}, "stop": stop,
             "targets": [round(lim + 2.5 * (lim - stop), 2)], "horizon_sessions": 8, "conviction": 3,
             "thesis": "pullback buy", "invalidation": "a close under the stop",
             "evidence": [{"result_id": "T3", "quote": "trend: uptrend", "point": "trend up"},
                          {"result_id": "T3", "quote": "50-day average slope over 10 sessions", "point": "rising"}]}]}

    svc.agent.claude_client = ScriptedClaude(propose)
    await svc.agent.run_day(morning(today))
    async with engine.sf() as s:
        e = (await s.execute(select(ScoutEntry).where(ScoutEntry.book == "agent_claude"))).scalar_one()
    d0 = e.entry_date
    await wait_for(lambda: engine.quotes.get("AAPL") is not None)
    day0 = dt.date.fromisoformat(d0)
    # 15:30 ET on the entry session: past the old 11:30 end, the limit is still worked, then carried
    await svc.desk.attempt_entries(morning(day0, "15:30"))
    async with engine.sf() as s:
        e = await s.get(ScoutEntry, e.id)
    assert e.status == "pending" and "carried to the next session" in e.attempts[-1]["reason"], e.attempts
    # next session: the price has come to the limit (moved above the live ask) -> it fills, keeping the END date
    ask = float(engine.quotes.get("AAPL").ask)
    async with engine.sf() as s:
        row = await s.get(ScoutEntry, e.id)
        cfg = dict(row.config)
        cfg["plan"] = {**cfg["plan"], "entry": {**cfg["plan"]["entry"], "limit": round(ask * 1.01, 2)},
                       "stop": round(ask * 0.95, 2), "targets": [round(ask * 1.2, 2)]}
        row.config = cfg
        await s.commit()
    d1 = dt.date.fromisoformat(add_sessions(d0, 1))
    res = await svc.desk.attempt_entries(morning(d1, "13:00"))
    async with engine.sf() as s:
        e = await s.get(ScoutEntry, e.id)
    assert e.status == "entered", (res, e.status, e.reason, e.attempts)
    p = engine.position_manager.get(e.position_id)
    assert p.policy["time_stop_sessions"] == 8 - 1 - 1                     # one session waited off the horizon


async def test_a_limit_expires_after_its_last_session(agent_rig, engine):
    from zargar.techniques.scout.screens import add_sessions
    svc, today = agent_rig
    day = today.isoformat()
    engine.config.openai_api_key = ""
    await engine.settings.set("techniques.scout.agent_screen_lane_enabled", False)
    await engine.settings.set("techniques.scout.agent_random_lane_enabled", False)
    await engine.settings.set("techniques.scout.agent_limit_sessions", 2)

    def propose():
        r = svc.agent._reads[day]["AAPL"]
        last, a = r["last"], r["atr14"]
        lim = round(last - 0.8 * a, 2)
        stop = round(lim - 2.0 * a, 2)
        return {"proposals": [
            {"ticker": "AAPL", "side": "long", "entry": {"kind": "limit", "limit_price": lim}, "stop": stop,
             "targets": [round(lim + 2.5 * (lim - stop), 2)], "horizon_sessions": 8, "conviction": 3,
             "thesis": "pullback buy", "invalidation": "a close under the stop",
             "evidence": [{"result_id": "T3", "quote": "trend: uptrend", "point": "trend up"},
                          {"result_id": "T3", "quote": "50-day average slope over 10 sessions", "point": "rising"}]}]}

    svc.agent.claude_client = ScriptedClaude(propose)
    await svc.agent.run_day(morning(today))
    async with engine.sf() as s:
        e = (await s.execute(select(ScoutEntry).where(ScoutEntry.book == "agent_claude"))).scalar_one()
    await wait_for(lambda: engine.quotes.get("AAPL") is not None)
    d1 = dt.date.fromisoformat(add_sessions(e.entry_date, 1))
    await svc.desk.attempt_entries(morning(d1, "15:30"))                   # the last session's last slot
    async with engine.sf() as s:
        e = await s.get(ScoutEntry, e.id)
    assert e.status == "skipped" and "level_not_reached" in (e.reason or ""), (e.status, e.reason)


async def test_budget_stop_records_the_run(agent_rig, engine):
    svc, today = agent_rig
    await engine.settings.set("techniques.scout.agent_budget_usd_day", 0.01)
    await engine.settings.set("techniques.scout.agent_gpt_enabled", False)
    svc.agent.claude_client = ScriptedClaude(lambda: {"proposals": []})
    out = await svc.agent.run_day(morning(today))
    assert out["lanes"]["claude"]["status"] == "budget" and not svc.agent.claude_client.calls


async def test_weekly_review_adds_cited_lessons_from_next_week(agent_rig, engine):
    svc, today = agent_rig
    ids = []
    async with engine.sf() as s:
        for k, net in enumerate((60.0, -25.0, 80.0, -30.0, 40.0)):
            eid = new_id()
            ids.append(eid)
            s.add(ScoutEntry(id=eid, candidate_id=new_id(), book="agent_claude", ticker=f"T{k}", entry_date="2026-10-01",
                             hold_sessions=10, status="closed", qty=10, entry_price=100.0, stop_price=96.0,
                             entry_ts=dt.datetime(2026, 10, 1, 15, tzinfo=dt.timezone.utc),
                             exit_ts=dt.datetime(2026, 10, 8, 20, tzinfo=dt.timezone.utc), exit_price=100 + net / 10,
                             exit_reason="time", net_pnl=net, gross_pnl=net + 2, fees=2.0,
                             config={"plan": {"thesis": "t", "stopAtr": 2.0, "targetsR": [2.0], "horizon": 10}}))
        await s.commit()
    reply = {"lessons": [{"text": "Prefer pullbacks within 1 ATR of the 20-day average.", "cases": [ids[0][:8], ids[2][:8]]},
                         {"text": "One case only.", "cases": [ids[1][:8]]}], "retire": [], "summary": "ok"}

    class Once:
        def __init__(self):
            self.messages = SimpleNamespace(create=self._create)

        async def _create(self, **kw):
            return SimpleNamespace(content=[blk(type="text", text=json.dumps(reply))], stop_reason="end_turn",
                                   model=kw["model"], usage=SimpleNamespace(input_tokens=3000, output_tokens=400,
                                                                            cache_read_input_tokens=0,
                                                                            cache_creation_input_tokens=0))
    svc.agent.claude_client = Once()
    fri = dt.date(2026, 10, 16)
    out = await svc.agent.review_week(dt.datetime.combine(fri, dt.time(16, 45), ET))
    assert out["status"] == "ok" and out["added"] == 1, out
    async with engine.sf() as s:
        ls = (await s.execute(select(ScoutAgentLesson))).scalars().all()
    assert len(ls) == 1 and ls[0].effective_from == "2026-10-19" and sorted(ls[0].cases) == sorted([ids[0], ids[2]])
    assert await svc.agent.active_lessons("2026-10-16") == []                 # never mid-week
    assert [x["text"] for x in await svc.agent.active_lessons("2026-10-19")] == [ls[0].text]
    assert (await svc.agent.review_week(dt.datetime.combine(fri, dt.time(16, 46), ET)))["skipped"]


async def test_routes_read_the_agent(agent_rig, engine):
    import httpx
    from zargar.api.app import create_app
    from .conftest import make_test_config
    svc, _ = agent_rig
    app = create_app(make_test_config(), engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        r = (await h.get("/api/scout/agent")).json()
        assert {"runs", "scorecard", "lessons", "lanes"} <= set(r)
        assert {l["lane"] for l in r["lanes"]} == {"agent_claude", "agent_gpt", "agent_random", "agent_screen"}
        assert r["scorecard"]["gate"]["verdict"] == "no proven edge yet"
        assert (await h.get("/api/scout/agent/runs/nope")).status_code == 404


async def _count(engine, kind: str) -> int:
    async with engine.sf() as s:
        return (await s.execute(select(func.count()).select_from(Event).where(Event.type == kind))).scalar_one()
