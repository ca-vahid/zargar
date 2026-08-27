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
    await _quote(eng, 99.5)   # sim executor fills after its latency on a fresh quote
    await _quote(eng, 99.5)


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