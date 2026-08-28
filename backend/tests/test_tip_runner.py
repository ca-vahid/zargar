"""TipRunner on the sim rig: a verified tip becomes an armed level-touch plan
through the shared PlanRunner, fires on a touch bar with NO volume requirement,
and (auto mode) places a RiskGate-checked entry on the sim venue."""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from zargar import bus as topics
from zargar.domain import Bar, Quote
from zargar.engine import Engine
from zargar.marketstructure import SESSION_WINDOWS, MarketRules, session_date
from zargar.marketstructure.tracker import TriggerTracker
from zargar.models import TechniqueArmed
from zargar.signals.schemas import ExtractionResult, TradeSignal
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip.runner import TipRunner

from .conftest import make_test_config, wait_for

ET = dt.timezone(dt.timedelta(hours=-4))     # fixture bars use fixed EDT; session math is tz-aware
MIN = 60_000


def _today_et(h: int, m: int) -> int:
    from zargar.marketstructure.sessions import ET as REAL_ET
    now = dt.datetime.now(REAL_ET)
    return int(now.replace(hour=h, minute=m, second=0, microsecond=0).timestamp() * 1000)


def _bars_5m(n: int = 50, around: float = 100.0) -> list[Bar]:
    """History for the plan build: oscillates around `around` (ATR fodder)."""
    end = _today_et(9, 0)
    out = []
    for i in range(n):
        c = around + (i % 5 - 2) * 0.3
        out.append(Bar(symbol="TEST", tf="5m", ts=end - (n - i) * 5 * MIN,
                       open=c - 0.1, high=c + 0.5, low=c - 0.5, close=c, volume=5_000))
    return out


SOURCE_TEXT = "TEST looking strong. Buy the dip at 99.5, stop 98, target 103."


def canned_tip():
    return ExtractionResult(
        signals=[TradeSignal(
            ticker="TEST", direction="long", action="open",
            entry_price=99.5, target_price=103.0, stop_price=98.0,
            entry_type="limit", timeframe="swing", thesis_summary="dip buy",
            evidence_quotes=["Buy the dip at 99.5, stop 98, target 103"],
            confidence="explicit_call", is_actionable=True)],
        source_type="trade_alert")


@pytest.fixture
async def tip_rig(fresh_db, monkeypatch):
    import zargar.brokers.sim as simmod
    monkeypatch.setitem(simmod.KNOWN_PRICES, "TEST", 100.0)
    config = make_test_config(anthropic_api_key="")
    eng = Engine(config)
    await eng.start()
    await attach_signal_layer(eng)
    eng.tip_runner = TipRunner(eng)
    for k, v in {"risk.stale_quote_seconds": 600, "risk.max_position_notional": 1_000_000.0,
                 "risk.max_position_pct": 100.0, "verification.max_price_deviation_pct": 10.0}.items():
        await eng.settings.set(k, v, journal=False)

    async def fake_window(symbol, tf, start, end):
        return _bars_5m()

    async def fake_session(symbol, tf, date, **kw):
        return []

    import zargar.marketstructure.history as hist
    monkeypatch.setattr(hist, "fetch_window", fake_window)
    # planrunner's late-arm opening-bar fetch imports fetch_session at call time
    monkeypatch.setattr(hist, "fetch_session", fake_session)

    await eng.ensure_symbol("TEST")
    await wait_for(lambda: eng.quotes.get("TEST") is not None and eng.quotes.get("TEST").last > 0)
    sim = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")
    yield eng, sim
    await eng.tip_runner.stop()
    await eng.stop()


async def _quote(eng, price: float):
    st = getattr(eng.feed, "_symbols", {}).get("TEST")
    if st is not None:
        st.price = price
        st.sigma_per_min = 0.0
        st.drift_per_min = 0.0
    q = Quote(symbol="TEST", bid=round(price - 0.01, 2), ask=round(price + 0.01, 2), last=price,
              bid_size=100000, ask_size=100000, volume=1_000_000)
    q.ts = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    eng.bus.publish(topics.QUOTES, q)
    await asyncio.sleep(0.15)


async def _ingest_tip(eng) -> str:
    from zargar.domain import new_id
    from zargar.models import RawContent
    row = RawContent(id=new_id(), source_type="manual", source_name="TestRoom",
                     subject="tip", body_text=SOURCE_TEXT)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    out = await eng.signals_service.handle_extraction(row, canned_tip(), source_text=SOURCE_TEXT)
    sig = out[0]["signal"]
    assert sig["status"] in ("verified", "parked"), sig["verification"]
    return sig["id"]


# --- tracker: tips carry no volume rule -------------------------------------------

def test_touch_fires_without_volume_when_floor_is_zero():
    trig = {"id": "t", "kind": "bounce", "direction": "long",
            "entry": {"price": 99.5, "basis": "at_level"}, "stop": {"price": 98.0},
            "targets": [{"price": 103.0}], "valid": True}
    rules = MarketRules(volume_floor_mult=0.0, gap_void_r=1e9, windows=SESSION_WINDOWS)
    tr = TriggerTracker(trig, rules, None, True, True, 100.0)
    ts = _today_et(10, 0)
    # zero-volume bars: EM would refuse (unknown volume); tip rules fire anyway
    assert tr.on_bar(Bar(symbol="T", tf="1m", ts=ts, open=100, high=100.3, low=99.9,
                         close=100.1, volume=0), 0) == "waiting"
    assert tr.on_bar(Bar(symbol="T", tf="1m", ts=ts + MIN, open=99.9, high=100.0, low=99.45,
                         close=99.8, volume=0), 1) == "fired"
    assert tr.fill_price == 99.5


def test_em_floor_still_requires_volume():
    trig = {"id": "t", "kind": "bounce", "direction": "long",
            "entry": {"price": 99.5, "basis": "at_level"}, "stop": {"price": 98.0},
            "targets": [{"price": 103.0}], "valid": True}
    rules = MarketRules(volume_floor_mult=0.5, gap_void_r=1e9, windows=SESSION_WINDOWS)
    tr = TriggerTracker(trig, rules, None, True, True, 100.0)
    ts = _today_et(10, 0)
    st = tr.on_bar(Bar(symbol="T", tf="1m", ts=ts, open=99.9, high=100.0, low=99.45,
                       close=99.8, volume=0), 0)
    assert st == "waiting" and tr.skipped   # unknown volume -> no entry (EM policy intact)


# --- the runner --------------------------------------------------------------------

async def test_tip_arms_fires_and_enters_on_sim(tip_rig):
    eng, sim = tip_rig
    sid = await _ingest_tip(eng)
    snap = await eng.tip_runner.arm_signal(sid, {
        "portfolioId": sim["id"], "mode": "auto", "instrument": "shares",
        "qty": 5, "dailyLossLimit": 200.0})
    assert snap["technique"] == "tip"
    [trig] = snap["triggers"]
    assert trig["kind"] == "bounce" and trig["entry"] == 99.5 and trig["status"] == "waiting"
    run_id = snap["runId"]

    # the armed row is stamped with the technique (restore isolation)
    async with eng.sf() as session:
        row = await session.get(TechniqueArmed, run_id)
    assert row is not None and row.technique == "tip"

    await _quote(eng, 99.6)
    # bars must land on the plan's session (today intra-session, else the next
    # session) and after anything the arm seeded from the live sim feed
    day = snap["planFor"]
    from zargar.marketstructure.sessions import ET as REAL_ET
    y, m, d = (int(x) for x in day.split("-"))
    ts0 = int(dt.datetime(y, m, d, 10, 0, tzinfo=REAL_ET).timestamp() * 1000)
    if snap.get("lastBarTs"):
        ts0 = max(ts0, int(snap["lastBarTs"]) + MIN)
    assert session_date(ts0) == day
    # no touch yet
    s1 = await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0, open=100.0,
                                                 high=100.2, low=99.8, close=100.0, volume=0))
    assert s1["triggers"][0]["status"] == "waiting"
    # touch bar -> fire -> auto entry (no volume on the bar; tip rules don't care)
    await _quote(eng, 99.5)
    s2 = await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0 + MIN, open=99.8,
                                                 high=99.9, low=99.4, close=99.6, volume=0))
    assert s2["triggers"][0]["status"] == "fired"
    trade = s2["trades"][0]
    assert trade["status"] in ("submitting", "working", "open"), trade
    assert trade["entryOrderId"]

    # the entry order carries the technique identity + the source tag
    from zargar.models import Order
    async with eng.sf() as session:
        order = await session.get(Order, trade["entryOrderId"])
    assert order is not None and order.technique == "tip"

    # fill the entry (sim executor fills after its latency on a fresh quote),
    # then the 2b HANDOFF: the filled position leaves the session runner and
    # becomes a durable managed position with the tip exit policy
    for _ in range(6):
        await _quote(eng, 99.5)

    async def handed_off():
        pos = [p for p in eng.position_manager.positions()
               if p.get("technique") == "tip" and p.get("runId") == run_id]
        return pos[0] if pos else None
    pos = await wait_for(handed_off, timeout=15)
    assert pos["symbol"] == "TEST" and pos["status"] in ("open", "attention")
    assert "source:TestRoom" in pos["tags"]
    assert pos["policy"]["stop"]["price"] == 98.0
    assert pos["policy"]["ladder"]["targets"] == [103.0]
    assert pos["policy"]["time_stop_sessions"] >= 1
    assert pos["policy"]["trailing"]["mode"] == "structure"
    # the session runner forgot the trade — end-of-day flatten can't touch it
    # (the pop happens a beat after the position becomes visible: wait for it)
    async def trade_gone():
        snap = next(a for a in eng.tip_runner.armed() if a["runId"] == run_id)
        return all(t["triggerId"] != trade["triggerId"] for t in snap["trades"])
    await wait_for(trade_gone, timeout=10)


async def test_shadow_arm_loop_dual_books(tip_rig):
    eng, sim = tip_rig
    sid = await _ingest_tip(eng)
    out = await eng.tip_runner.shadow_arm_open_tips()
    assert out["armed"] == 1, out
    # the ARMED book portfolio exists next to the immediate one
    books = {p.get("book") for p in eng.positions.portfolios()
             if p["kind"] == "shadow" and p.get("sourceName") == "TestRoom"}
    assert books == {None, "armed"} or books == {"immediate", "armed"}
    # idempotent: the tip is already armed today
    out2 = await eng.tip_runner.shadow_arm_open_tips()
    assert out2["armed"] == 0 and out2["skipped"] >= 1
    # scorecard shows both books
    cards = await eng.signals_service.source_scorecards()
    card = next(c for c in cards if c["source"] == "TestRoom")
    assert "immediate" in card["books"] and "armed" in card["books"]
    assert card["books"]["armed"].get("portfolioId")


async def test_immediate_book_time_exit(tip_rig):
    # a bracket-less immediate-book share buy dies at its closeAfter date —
    # the morning sweep sells it (found 2026-08-28: it lived forever before)
    eng, sim = tip_rig
    sid = await _ingest_tip(eng)
    from zargar.models import Signal
    svc = eng.signals_service
    shadow = await svc.shadow_portfolio("TestRoom", "immediate")

    async def bought():
        return any(p["symbol"] == "TEST" and p["qty"] > 0
                   for p in eng.positions.positions_list(shadow["id"]))
    await wait_for(bought)
    async with eng.sf() as session:               # force the hold cap into the past
        row = await session.get(Signal, sid)
        expr = dict((row.extraction or {}).get("shadowExpression") or {})
        assert expr.get("closeAfter"), expr        # the buy booked its exit date
        expr["closeAfter"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        row.extraction = {**(row.extraction or {}), "shadowExpression": expr}
        await session.commit()
    out = await eng.tip_runner.shadow_arm_open_tips()
    assert out.get("immediateClosed") == 1, out
    await _quote(eng, 100.0)                       # sim needs a quote after latency
    await _quote(eng, 100.0)

    async def flat():
        return all(p["qty"] == 0 for p in eng.positions.positions_list(shadow["id"])
                   if p["symbol"] == "TEST")
    await wait_for(flat)
    # idempotent: expression is marked closed, the sweep won't sell again
    out2 = await eng.tip_runner.shadow_arm_open_tips()
    assert out2.get("immediateClosed") == 0


async def test_expired_option_tip_never_arms(tip_rig):
    eng, sim = tip_rig
    sid = await _ingest_tip(eng)
    from zargar.models import Signal
    async with eng.sf() as session:
        row = await session.get(Signal, sid)
        row.expiry = (dt.date.today() + dt.timedelta(days=1)).isoformat()  # inside the 2d cutoff
        await session.commit()
    with pytest.raises(ValueError, match="too late"):
        await eng.tip_runner.arm_signal(sid, {"portfolioId": sim["id"], "mode": "alert"})
    out = await eng.tip_runner.shadow_arm_open_tips()
    assert out["expired"] == 1 and out["armed"] == 0
    async with eng.sf() as session:
        row = await session.get(Signal, sid)
    assert row.status == "expired"


OPT_SOURCE = "TEST 101c — buy the dip at 99.5, stop 98, target 103."


def canned_option_tip(expiry: str):
    return ExtractionResult(
        signals=[TradeSignal(
            ticker="TEST", direction="long", action="open",
            instrument="call", strike=101.0, expiry=expiry,
            entry_price=99.5, target_price=103.0, stop_price=98.0,
            entry_type="limit", timeframe="swing", thesis_summary="dip buy calls",
            evidence_quotes=["TEST 101c", "buy the dip at 99.5, stop 98, target 103"],
            confidence="explicit_call", is_actionable=True)],
        source_type="trade_alert")


async def _opt_quote(eng, occ_sym: str, mid: float):
    q = Quote(symbol=occ_sym, bid=round(mid - 0.05, 2), ask=round(mid + 0.05, 2), last=mid,
              bid_size=500, ask_size=500, volume=1_000)
    q.ts = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    eng.quotes.on_quote(q)     # cache + bus in one call (gate freshness + sim fills)
    await asyncio.sleep(0.15)


async def test_option_tip_both_books_end_to_end(tip_rig):
    """Phase B: the per-tip vehicle rule — an option-shaped tip buys the
    CONTRACT in the immediate book AND arms as options; a fill hands off an
    OPT managed position with premium stop, dte_close and the app-managed ack."""
    eng, sim = tip_rig
    from zargar.options import occ as occ_mod

    from .test_tip_express import FakeChain, row as chain_row
    exp14 = (dt.date.today() + dt.timedelta(days=14)).isoformat()
    fake = FakeChain(spot=100.0, expiries=(exp14,),
                     rows=[chain_row(101.0, expiry=exp14), chain_row(103.0, expiry=exp14),
                           chain_row(99.0, "put", expiry=exp14)])
    eng.options.use_client(fake)
    occ_sym = occ_mod.make("TEST", exp14, "C", 101.0).symbol

    # ---- immediate book: bought the contract, no bracket, budget-sized ----
    from zargar.domain import new_id
    from zargar.models import RawContent, Signal as SignalRow
    content = RawContent(id=new_id(), source_type="manual", source_name="TestRoom",
                         subject="tip", body_text=OPT_SOURCE)
    async with eng.sf() as session:
        session.add(content)
        await session.commit()
    out = await eng.signals_service.handle_extraction(content, canned_option_tip(exp14),
                                                      source_text=OPT_SOURCE)
    sig = out[0]["signal"]
    assert sig["status"] in ("verified", "parked"), sig["verification"]
    shadow_order = out[0]["shadowOrder"]
    assert shadow_order is not None and shadow_order["secType"] == "OPT", shadow_order
    assert shadow_order["symbol"] == occ_sym
    assert shadow_order["qty"] == 8          # $1000 budget / $1.20 ask x100 -> 8 contracts
    async with eng.sf() as session:
        srow = await session.get(SignalRow, sig["id"])
    assert (srow.extraction.get("shadowExpression") or {}).get("vehicle") == "option"

    # ---- armed book: vehicle rule arms options with the premium budget ----
    snap = await eng.tip_runner.arm_signal(sig["id"], {
        "portfolioId": sim["id"], "mode": "auto", "dailyLossLimit": 200.0})
    assert snap["config"]["instrument"] == "options"
    assert snap["config"]["premiumBudget"] == 1000.0   # default budget_per_tip
    assert snap["config"]["entryFallback"] == "shares"
    run_id = snap["runId"]

    await _quote(eng, 99.6)
    await _opt_quote(eng, occ_sym, 1.1)      # fresh contract quote for the gate
    day = snap["planFor"]
    from zargar.marketstructure.sessions import ET as REAL_ET
    y, m, d = (int(x) for x in day.split("-"))
    ts0 = int(dt.datetime(y, m, d, 10, 0, tzinfo=REAL_ET).timestamp() * 1000)
    if snap.get("lastBarTs"):
        ts0 = max(ts0, int(snap["lastBarTs"]) + MIN)
    await _quote(eng, 99.5)
    s2 = await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0, open=99.8,
                                                 high=99.9, low=99.4, close=99.6, volume=0))
    assert s2["triggers"][0]["status"] == "fired"
    trade = s2["trades"][0]
    assert trade["instrument"] == "options", trade
    assert trade["orderSymbol"] == occ_sym
    assert trade["contract"]["statedContract"] is True
    assert trade["status"] in ("submitting", "working", "open"), trade

    # fill the option entry, then the 2b handoff carries the OPT leg
    for _ in range(6):
        await _opt_quote(eng, occ_sym, 1.15)

    async def handed_off():
        pos = [p for p in eng.position_manager.positions()
               if p.get("technique") == "tip" and p.get("runId") == run_id]
        return pos[0] if pos else None
    pos = await wait_for(handed_off, timeout=15)
    [leg] = pos["legs"]
    assert leg["secType"] == "OPT" and leg["symbol"] == occ_sym and leg["multiplier"] == 100.0
    assert pos["overnight"] == "app_managed" and pos["overnightAck"] is True
    assert pos["policy"]["premium_stop_pct"] == 50.0
    assert pos["policy"]["dte_close"] >= 1
    assert pos["policy"]["stop"]["price"] == 98.0
    assert pos["entry"] == 99.5              # policies judge the UNDERLYING


async def test_short_tip_puts_end_to_end(tip_rig):
    """A short tip (puts) arms, fires on the reject touch, buys the PUT, and
    hands off — the armed book's short-side measurement gap is closed."""
    eng, sim = tip_rig
    from zargar.options import occ as occ_mod

    from .test_tip_express import FakeChain, row as chain_row
    exp14 = (dt.date.today() + dt.timedelta(days=14)).isoformat()
    fake = FakeChain(spot=100.0, expiries=(exp14,),
                     rows=[chain_row(99.0, "put", expiry=exp14),
                           chain_row(97.0, "put", expiry=exp14)])
    eng.options.use_client(fake)
    occ_sym = occ_mod.make("TEST", exp14, "P", 99.0).symbol

    src = "TEST 99p — fade this pop at 100.5, stop 102, target 96."
    ext = ExtractionResult(
        signals=[TradeSignal(
            ticker="TEST", direction="short", action="open",
            instrument="put", strike=99.0, expiry=exp14,
            entry_price=100.5, target_price=96.0, stop_price=102.0,
            entry_type="limit", timeframe="swing", thesis_summary="fade",
            evidence_quotes=["TEST 99p", "fade this pop at 100.5, stop 102, target 96"],
            confidence="explicit_call", is_actionable=True)],
        source_type="trade_alert")
    from zargar.domain import new_id
    from zargar.models import RawContent
    content = RawContent(id=new_id(), source_type="manual", source_name="TestRoom",
                         subject="tip", body_text=src)
    async with eng.sf() as session:
        session.add(content)
        await session.commit()
    out = await eng.signals_service.handle_extraction(content, ext, source_text=src)
    sig = out[0]["signal"]
    assert sig["status"] in ("verified", "parked"), sig["verification"]
    # immediate book: BUYS the put (never a share short)
    assert out[0]["shadowOrder"] is not None
    assert out[0]["shadowOrder"]["secType"] == "OPT"
    assert out[0]["shadowOrder"]["side"] == "BUY"

    snap = await eng.tip_runner.arm_signal(sig["id"], {
        "portfolioId": sim["id"], "mode": "auto", "dailyLossLimit": 200.0})
    assert snap["config"]["instrument"] == "options"
    [trig] = snap["triggers"]
    assert trig["kind"] == "reject" and trig["direction"] == "short"
    run_id = snap["runId"]

    await _quote(eng, 100.2)
    await _opt_quote(eng, occ_sym, 1.1)
    day = snap["planFor"]
    from zargar.marketstructure.sessions import ET as REAL_ET
    y, m, d = (int(x) for x in day.split("-"))
    ts0 = int(dt.datetime(y, m, d, 10, 0, tzinfo=REAL_ET).timestamp() * 1000)
    if snap.get("lastBarTs"):
        ts0 = max(ts0, int(snap["lastBarTs"]) + MIN)
    s2 = await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0, open=100.2,
                                                 high=100.6, low=100.1, close=100.3, volume=0))
    assert s2["triggers"][0]["status"] == "fired", s2["triggers"]
    trade = s2["trades"][0]
    assert trade["instrument"] == "options" and trade["orderSymbol"] == occ_sym, trade

    for _ in range(6):
        await _opt_quote(eng, occ_sym, 1.15)

    async def handed_off():
        pos = [p for p in eng.position_manager.positions()
               if p.get("technique") == "tip" and p.get("runId") == run_id]
        return pos[0] if pos else None
    pos = await wait_for(handed_off, timeout=15)
    assert pos["direction"] == "short"
    [leg] = pos["legs"]
    assert leg["secType"] == "OPT" and leg["qty"] > 0     # long the PUT
    assert pos["policy"]["stop"]["price"] == 102.0        # above entry: the short mirror


async def test_share_tip_stays_shares_and_no_chain_falls_back(tip_rig):
    """A bare 'buy TEST' tip stays shares in both books; an option tip whose
    chain is unreachable falls back to shares with the reason recorded."""
    eng, sim = tip_rig

    from .test_tip_express import FakeChain
    class Dead(FakeChain):
        async def expirations(self, symbol):
            from zargar.options.chain import OptionsError
            raise OptionsError("no US-listed options (CBOE 404)")
    eng.options.use_client(Dead())

    # share tip -> shares (vehicle rule)
    sid = await _ingest_tip(eng)
    snap = await eng.tip_runner.arm_signal(sid, {"portfolioId": sim["id"], "mode": "alert"})
    assert snap["config"]["instrument"] == "shares"

    # option tip, dead chain -> immediate book expressed in SHARES with the reason
    from zargar.domain import new_id
    from zargar.models import RawContent, Signal as SignalRow
    exp14 = (dt.date.today() + dt.timedelta(days=14)).isoformat()
    content = RawContent(id=new_id(), source_type="manual", source_name="OtherRoom",
                         subject="tip", body_text=OPT_SOURCE)
    async with eng.sf() as session:
        session.add(content)
        await session.commit()
    out = await eng.signals_service.handle_extraction(content, canned_option_tip(exp14),
                                                      source_text=OPT_SOURCE)
    shadow_order = out[0]["shadowOrder"]
    assert shadow_order is not None and shadow_order["secType"] == "STK"
    async with eng.sf() as session:
        srow = await session.get(SignalRow, out[0]["signal"]["id"])
    expr = srow.extraction.get("shadowExpression") or {}
    assert expr.get("vehicle") == "shares" and "404" in str(expr.get("fallback"))


async def test_scorecard_expectancy_from_outcomes(tip_rig):
    """T3: scored tip-run outcomes roll up per source (expectancy counts an
    unfilled tip as 0R) and the trust bar flips on R once enough are scored."""
    eng, sim = tip_rig
    await eng.settings.set("techniques.tip.scorecard_min_n", 3, journal=False)
    await _ingest_tip(eng)                     # mints the TestRoom source
    from zargar.domain import new_id
    from zargar.models import TechniqueOutcome, TechniqueRun

    async def seed(source: str, rs: list[float | None]):
        rids = []
        async with eng.sf() as session:
            for _ in rs:
                rid = new_id()
                rids.append(rid)
                session.add(TechniqueRun(
                    id=rid, technique="tip", symbol="TEST", mode="plan", trigger="tip",
                    status="done", verdict="plan", result={"plan": {}},
                    config={"technique": "tip", "source": source}))
            await session.commit()
        async with eng.sf() as session:
            for rid, r in zip(rids, rs):
                session.add(TechniqueOutcome(
                    id=new_id(), run_id=rid, plan_source="trigger:tip-x", status="scored",
                    plan={}, outcome=("not_triggered" if r is None else "tp1" if r > 0 else "stopped"),
                    r_multiple=r))
            await session.commit()

    await seed("TestRoom", [1.5, -1.0, None])       # 2 fired + 1 never-triggered
    await seed("LoserRoom", [-1.0, -1.0, -0.5])

    cards = await eng.signals_service.source_scorecards()
    card = next(c for c in cards if c["source"] == "TestRoom")
    oc = card["books"]["armed"]["outcomes"]
    assert oc["scored"] == 3 and oc["fired"] == 2 and oc["neverTriggered"] == 1
    assert oc["winRate"] == 0.5 and oc["avgR"] == 0.25
    assert abs(oc["expectancyR"] - 0.167) < 0.001
    assert card["barBasis"] == "expectancyR" and card["barCleared"] is True

    loser = next(c for c in cards if c["source"] == "LoserRoom")
    assert loser["books"]["armed"]["outcomes"]["expectancyR"] < 0
    assert loser["barBasis"] == "expectancyR" and loser["barCleared"] is False


async def test_tip_run_snapshots_its_rules(tip_rig):
    """The outcome scorer replays with config.thresholds — a tip run must carry
    TIP rules (no volume floor, RTH windows), never EM's."""
    eng, sim = tip_rig
    sid = await _ingest_tip(eng)
    snap = await eng.tip_runner.arm_signal(sid, {"portfolioId": sim["id"], "mode": "alert"})
    from zargar.models import TechniqueRun
    async with eng.sf() as session:
        run = await session.get(TechniqueRun, snap["runId"])
    thr = (run.config or {}).get("thresholds") or {}
    assert thr.get("volume_floor_mult") == 0.0
    assert thr.get("gap_void_r") == 1e9
    assert "midday" in (thr.get("windows") or [])


async def test_source_auto_detection(tip_rig):
    """source_name='auto' resolves from the extractor's source_hint: exact/fuzzy
    match to a known source, else the hint becomes a new source's name."""
    eng, sim = tip_rig
    from zargar.domain import new_id
    from zargar.models import RawContent
    await eng.settings.set("sources.registry",
                           [{"name": "Alpha Alerts", "emails": []}], journal=False)

    async def ingest(hint, source_name="auto", text=SOURCE_TEXT):
        row = RawContent(id=new_id(), source_type="manual", source_name=source_name,
                         subject="tip", body_text=text)
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        ext = canned_tip()
        ext.source_hint = hint
        return await eng.signals_service.handle_extraction(row, ext, source_text=text)

    # fuzzy match: '#alpha-alerts' -> the registered 'Alpha Alerts'
    out = await ingest("#alpha-alerts")
    assert out[0]["signal"]["sourceName"] == "Alpha Alerts"

    # a genuinely new hint becomes its own source (new dedupe scope, so no dup)
    out2 = await ingest("TraderJoe")
    assert out2[0]["signal"]["sourceName"] == "TraderJoe"
    assert "duplicateOf" not in out2[0]

    # an explicit source name is never overridden
    out3 = await ingest("SomebodyElse", source_name="MyPick")
    assert out3[0]["signal"]["sourceName"] == "MyPick"

    # no hint at all -> 'unknown'
    row = RawContent(id=new_id(), source_type="manual", source_name="auto",
                     subject="tip", body_text=SOURCE_TEXT)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    ext = canned_tip()
    assert ext.source_hint is None
    out4 = await eng.signals_service.handle_extraction(row, ext, source_text=SOURCE_TEXT)
    assert out4[0]["signal"]["sourceName"] == "unknown"

    names = await eng.signals_service.known_sources()
    assert "Alpha Alerts" in names and "TraderJoe" in names and "MyPick" in names


async def test_tip_time_sources_cannot_arm(tip_rig):
    eng, sim = tip_rig
    await eng.settings.set("techniques.tip.sources",
                           {"TestRoom": {"entry": "tip_time"}}, journal=False)
    sid = await _ingest_tip(eng)
    with pytest.raises(ValueError, match="tip_time"):
        await eng.tip_runner.arm_signal(sid, {"portfolioId": sim["id"], "mode": "alert"})


async def test_unverified_signal_cannot_arm(tip_rig):
    eng, sim = tip_rig
    from zargar.models import Signal
    sid = await _ingest_tip(eng)
    async with eng.sf() as session:
        row = await session.get(Signal, sid)
        row.status = "verification_failed"
        await session.commit()
    with pytest.raises(ValueError, match="verified"):
        await eng.tip_runner.arm_signal(sid, {"portfolioId": sim["id"], "mode": "alert"})