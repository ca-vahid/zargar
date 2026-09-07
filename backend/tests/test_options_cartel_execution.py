"""Real RiskGate/DB preflight; no engine start and no order rows or broker calls."""
import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from zargar.domain import Quote
from zargar.engine import Engine
from zargar.marketstructure.market_calendar import next_trading_day
from zargar.marketstructure.sessions import ET
from zargar.models import Order, Portfolio
from zargar.techniques.options_cartel.execution import ExecutionInput, preflight
from zargar.techniques.options_cartel.plans import CartelPlan

from .conftest import make_test_config


@pytest.fixture
async def rig(fresh_db):
    engine = Engine(make_test_config())
    async with engine.sf() as session:
        session.add(Portfolio(id="cartel-sim", name="Cartel test", kind="sim", base_currency="USD",
                              cash=10000, starting_cash=10000))
        await session.commit()
    await engine.positions.load()
    at = int(dt.datetime.now(dt.UTC).timestamp()*1000)
    first = next_trading_day(dt.datetime.now(ET).date())
    last = next_trading_day(first+dt.timedelta(days=20))
    plan = CartelPlan(id="p", symbol="TEST", direction="long", setup="base", created_at=at-60000,
                      first_session=first, last_session=last, trigger=100, invalidation=95, targets=(110,),
                      source_refs=("test",), rationale="Synthetic preflight", baseline_as_of=at-60000)
    engine.quotes.on_quote(Quote(symbol="TEST", bid=100, ask=100.1, last=100.05))
    yield engine, plan
    await engine.db.dispose()


def spec(**overrides):
    return ExecutionInput(**{"portfolio_id": "cartel-sim", "instrument": "shares", "budget": 1000,
                              "risk_pct": 1, "max_units": 10, **overrides})


async def test_shared_risk_gate_preflight_is_read_only_and_repeatable(rig):
    engine, plan = rig
    first = await preflight(engine, plan, spec())
    assert first["passed"], first
    assert first["expression"]["quantity"] == 9
    assert first["intent"]["dry_run"] and first["intent"]["technique_id"] == "options_cartel"
    for _ in range(3):
        assert (await preflight(engine, plan, spec()))["passed"]
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0
    assert not engine.started and engine.orders is None


async def test_shared_risk_caps_cannot_be_bypassed_by_technique_sizing(rig):
    engine, plan = rig
    result = await preflight(engine, plan, spec(budget=10000, risk_pct=10, max_units=100))
    assert result["risk"] and not result["risk"]["passed"] and not result["passed"]


async def test_share_risk_budget_uses_current_limit_price_not_old_trigger(rig):
    engine, plan = rig
    engine.quotes.on_quote(Quote(symbol="TEST", bid=100.9, ask=101., last=100.95))
    result = await preflight(engine, plan, spec(budget=10000, max_units=100, risk_pct=.3))
    assert result["passed"], result
    assert result["expression"]["quantity"] == 5  # $30 risk / ($101 ask - $95 stop)
    engine.position_manager._entry_halted.add("TEST")
    assert not (await preflight(engine, plan, spec()))["passed"]


@pytest.mark.parametrize("issue", ["stale", "delayed", "future", "crossed"])
async def test_quote_quality_blocks_sizing(rig, issue):
    engine, plan = rig
    q = engine.quotes.get("TEST")
    if issue == "stale":
        q.ts -= 3600000
    elif issue == "future":
        q.ts += 3600000
    elif issue == "delayed":
        q.source = "chain"
    else:
        q.bid = 110
    result = await preflight(engine, plan, spec())
    assert not result["passed"] and result["intent"] is None


async def test_global_book_and_technique_pause_block_entries(rig):
    engine, plan = rig
    engine.halt.engage("test")
    assert not (await preflight(engine, plan, spec()))["passed"]
    engine.halt.release()
    engine.halt.engage_book("cartel-sim", "test")
    assert not (await preflight(engine, plan, spec()))["passed"]
    engine.halt.release_book("cartel-sim")
    await engine.settings.set("techniques.options_cartel.paused", True)
    assert not (await preflight(engine, plan, spec()))["passed"]


async def test_options_reserve_full_premium_and_validate_direction_and_overnight(rig):
    engine, plan = rig
    expiry = next_trading_day(plan.last_session+dt.timedelta(days=30))
    symbol = f"TEST{expiry:%y%m%d}C00100000"
    engine.quotes.on_quote(Quote(symbol=symbol, bid=1.9, ask=2., last=1.95, source="opra"))
    greeks_at = int(dt.datetime.now(dt.UTC).timestamp()*1000)
    engine.options = SimpleNamespace(snapshot_cached=lambda _: {
        "greeks": {"delta": .45}, "greeksFieldAsOf": {"delta": greeks_at}})
    request = spec(instrument="options", contract_symbol=symbol, overnight_ack=True, risk_pct=5)
    result = await preflight(engine, plan, request)
    assert result["expression"]["quantity"] == 2 and result["expression"]["riskBasis"] == "full option debit"
    assert result["intent"] is not None
    no_ack = await preflight(engine, plan, request.model_copy(update={"overnight_ack": False}))
    assert not no_ack["passed"]
    wrong = plan.model_copy(update={"direction": "short", "invalidation": 105, "targets": (90,)})
    assert not (await preflight(engine, wrong, request))["passed"]
    assert not (await preflight(engine, wrong, spec()))["passed"]


async def test_cross_currency_requires_fx_and_sizes_in_account_currency(rig):
    engine, plan = rig
    async with engine.sf() as session:
        p = await session.get(Portfolio, "cartel-sim")
        p.base_currency = "CAD"
        await session.commit()
    await engine.positions.load()
    assert not (await preflight(engine, plan, spec()))["passed"]
    engine.quotes.on_quote(Quote(symbol="USDCAD=X", last=1.4))
    result = await preflight(engine, plan, spec())
    assert result["expression"]["quantity"] == 7
    assert result["expression"]["budgetCurrency"] == "CAD"


async def test_expired_plan_and_unknown_portfolio_are_rejected(rig):
    engine, plan = rig
    past = next_trading_day(dt.date(2020, 1, 1))
    expired = plan.model_copy(update={"first_session": past, "last_session": past})
    assert not (await preflight(engine, expired, spec()))["passed"]
    with pytest.raises(ValueError, match="portfolio not found"):
        await preflight(engine, plan, spec(portfolio_id="missing"))


async def test_real_account_manual_and_auto_permissions_are_distinct(rig):
    engine, plan = rig
    async with engine.sf() as session:
        p = await session.get(Portfolio, "cartel-sim")
        p.kind = "live"
        await session.commit()
    await engine.positions.load()
    request = spec(allow_live=True)
    read = await preflight(engine, plan, request)
    assert not next(c for c in read["checks"] if c["name"] == "live_acknowledgements")["passed"]
    await engine.settings.set("trading.mode", "live")
    read = await preflight(engine, plan, request)
    assert next(c for c in read["checks"] if c["name"] == "live_acknowledgements")["passed"]
    read = await preflight(engine, plan, request.model_copy(update={"mode": "auto"}))
    assert not next(c for c in read["checks"] if c["name"] == "live_acknowledgements")["passed"]
    await engine.settings.set("techniques.options_cartel.allow_live_auto", True)
    read = await preflight(engine, plan, request.model_copy(update={"mode": "auto"}), client_kind="phone")
    assert next(c for c in read["checks"] if c["name"] == "live_acknowledgements")["passed"]
    assert read["risk"] and not read["risk"]["passed"]  # phone exit-only remains a shared gate


@pytest.mark.parametrize("delta,age", [(.2, 0), (.4, 121000), (.4, -1000), (None, 0), (float("nan"), 0), (True, 0), (-.4, 0)])
async def test_missing_stale_low_or_wrong_sign_delta_never_qualifies(rig, delta, age):
    engine, plan = rig
    expiry = next_trading_day(plan.last_session+dt.timedelta(days=30))
    symbol = f"TEST{expiry:%y%m%d}C00100000"
    now = int(dt.datetime.now(dt.UTC).timestamp()*1000)
    engine.quotes.on_quote(Quote(symbol=symbol, bid=1.9, ask=2., last=1.95, source="opra"))
    engine.options = SimpleNamespace(snapshot_cached=lambda _: {
        "greeks": {"delta": delta}, "greeksFieldAsOf": {"delta": now-age}})
    result = await preflight(engine, plan, spec(instrument="options", contract_symbol=symbol,
                                               overnight_ack=True, risk_pct=5), now_ms=now)
    assert not result["passed"] and result["intent"] is None


async def test_low_delta_exception_requires_review_and_still_needs_fresh_greeks(rig):
    engine, plan = rig
    expiry = next_trading_day(plan.last_session+dt.timedelta(days=30))
    symbol = f"TEST{expiry:%y%m%d}C00100000"
    with pytest.raises(ValueError, match="exception reason"):
        spec(instrument="options", min_abs_delta=.1)
    now = int(dt.datetime.now(dt.UTC).timestamp()*1000)
    engine.quotes.on_quote(Quote(symbol=symbol, bid=1.9, ask=2., last=1.95, source="opra"))
    snapshot = {"greeks": {"delta": .2}, "greeksFieldAsOf": {"delta": now}}
    engine.options = SimpleNamespace(snapshot_cached=lambda _: snapshot)
    request = spec(instrument="options", contract_symbol=symbol, overnight_ack=True, risk_pct=5,
                   min_abs_delta=.15, delta_exception_reason="Explicitly reviewed source exception")
    result = await preflight(engine, plan, request, now_ms=now)
    assert result["intent"] is not None and result["expression"]["deltaExceptionReason"]
    snapshot["greeksFieldAsOf"] = {}
    assert not (await preflight(engine, plan, request, now_ms=now))["passed"]


async def test_put_uses_absolute_negative_delta(rig):
    engine, original = rig
    plan = original.model_copy(update={"direction": "short", "invalidation": 105, "targets": (90,)})
    expiry = next_trading_day(plan.last_session+dt.timedelta(days=30))
    symbol = f"TEST{expiry:%y%m%d}P00100000"
    now = int(dt.datetime.now(dt.UTC).timestamp()*1000)
    engine.quotes.on_quote(Quote(symbol=symbol, bid=1.9, ask=2., last=1.95, source="opra"))
    engine.options = SimpleNamespace(snapshot_cached=lambda _: {
        "greeks": {"delta": -.45}, "greeksFieldAsOf": {"delta": now}})
    result = await preflight(engine, plan, spec(instrument="options", contract_symbol=symbol,
                                               overnight_ack=True, risk_pct=5), now_ms=now)
    assert result["intent"] is not None and result["intent"]["side"] == "BUY"
    assert result["expression"]["delta"] == -.45
