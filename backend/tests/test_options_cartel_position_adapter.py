"""Cartel campaigns through the real PositionManager, with sim and recorded fills."""
from types import SimpleNamespace

import pytest

from zargar.domain import Bar, Quote
from zargar.execution.positions import PositionManager
from zargar.marketstructure.market_calendar import next_trading_day
from zargar.marketstructure.sessions import session_bounds
from zargar.models import Order
from zargar.orders import OrderIntent
from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.position_adapter import CartelPositionAdapter

from .cartel_orders import RecordedOrders
from .conftest import wait_for
from .test_options_cartel_setups import histories


async def prepared(engine, *, fake=True, fill_price=100.):
    history, _ = histories()
    day = next_trading_day(history[-1].session)
    opens, closes = session_bounds(day.isoformat())
    pf = next(p["id"] for p in engine.positions.portfolios() if p["kind"] == "sim")
    pm = PositionManager(engine)
    pm._now = lambda: (opens+60_000)/1000
    pm.register_policy_adapter("options_cartel", CartelPositionAdapter())
    if fake:
        engine.orders = RecordedOrders(engine)
    spec = {"portfolioId": pf, "symbol": "TEST", "direction": "long", "techniqueId": "options_cartel",
            "entry": 100., "risk": 5., "overnight": "app_managed", "overnightAck": True,
            "legs": [{"symbol": "TEST", "secType": "STK", "qty": 8, "avgFill": fill_price}],
            "policy": {"adapter": "options_cartel", "timeframe": "1d", "stop": {"kind": "fixed", "price": 95},
                       "cartel": {"campaign": ExitCampaign.for_profile("may_2026", [110]).model_dump(mode="json"),
                                  "initialQty": 8, "daily": [b.model_dump(mode="json") for b in history]}}}
    # Deterministic direct bars; subscriptions are not needed for these manager tests.
    out = await pm.adopt(spec)
    await pm.stop()
    p = pm.get(out["id"])
    p.opened_ms = opens
    return SimpleNamespace(pm=pm, p=p, spec=spec, opens=opens, closes=closes, engine=engine)


async def minute(rig, index, price):
    ts = rig.opens+index*60_000
    rig.pm._now = lambda: (ts+60_000)/1000
    await rig.pm.on_minute_bar(rig.p, Bar("TEST", "1m", ts, price, price+.1, price-.1, price, 100))


async def test_actual_fill_updates_campaign_before_breakeven_and_duplicate_bar_is_idempotent(engine):
    rig = await prepared(engine)
    engine.orders.script[0] = {"status": "ACCEPTED"}
    await minute(rig, 0, 110)
    assert rig.p.state.stop == 95 and rig.p.legs[0].qty == 8
    rec = rig.p.exits[-1]
    await rig.pm.on_order_update({"id": rec["orderId"], "symbol": "TEST", "status": "PARTIALLY_FILLED",
                                   "filledQty": 1, "avgFillPrice": 110})
    assert rig.p.state.stop == 95 and rig.p.legs[0].qty == 7
    await rig.pm.on_order_update({"id": rec["orderId"], "symbol": "TEST", "status": "FILLED",
                                   "filledQty": 2, "avgFillPrice": 110})
    assert rig.p.state.stop == 100 and rig.p.legs[0].qty == 6
    assert rig.p.policy["cartel"]["state"]["remaining_qty"] == 6
    await minute(rig, 0, 110)
    assert len(engine.orders.placed) == 1


async def test_pending_entry_keeps_stop_protection_but_defers_profit_taking(engine):
    rig = await prepared(engine)
    rig.p.policy["cartel"]["entryPending"] = True
    await minute(rig, 0, 110)
    assert engine.orders.placed == [] and rig.p.legs[0].qty == 8
    await minute(rig, 1, 94)
    assert rig.p.status == "closed"
    assert len(engine.orders.placed) == 1 and engine.orders.placed[0].qty == 8
    assert engine.orders.placed[0].reduce_only


async def test_true_daily_bar_is_built_and_ema_close_uses_it(engine):
    rig = await prepared(engine)
    await minute(rig, 0, 110)  # first quarter fills
    # Seed observed minutes, as the adapter would accumulate during the session.
    context = rig.p.policy["cartel"]
    context["dayBuffer"] = {str(rig.opens+i*60_000): [110, 111, 109, 110, 100] for i in range(389)}
    context["lastMinute"] = rig.opens+388*60_000
    await minute(rig, 389, 110)
    assert not rig.p.open_legs and rig.p.status == "closed"
    daily = rig.p.policy["cartel"]["daily"][-1]
    assert daily["volume"] == 39000 and daily["high"] == 111 and daily["low"] == 109
    assert sum(o.qty for o in engine.orders.placed) == 8
    assert all(o.reduce_only for o in engine.orders.placed)


async def test_missing_day_data_never_substitutes_a_five_minute_ema(engine):
    rig = await prepared(engine)
    await minute(rig, 0, 110)
    await minute(rig, 389, 105)
    assert rig.p.legs[0].qty == 6  # no daily EMA sale from an incomplete session
    assert any("Incomplete session tape" in s for s in rig.p.attention)


async def test_restart_restores_campaign_accounting_and_does_not_repeat_trim(engine):
    rig = await prepared(engine)
    await minute(rig, 0, 110)
    count = len(engine.orders.placed)
    restored = PositionManager(engine)
    restored._now = rig.pm._now
    restored.register_policy_adapter("options_cartel", CartelPositionAdapter())
    await restored.restore()
    await restored.stop()
    p = restored.get(rig.p.id)
    assert p.policy["cartel"]["state"]["remaining_qty"] == 6 and p.state.stop == 100
    await restored.on_minute_bar(p, Bar("TEST", "1m", rig.opens, 110, 111, 109, 110, 100))
    assert len(engine.orders.placed) == count


async def test_backfill_and_pre_adoption_bars_cannot_trigger_exits(engine):
    rig = await prepared(engine)
    rig.pm._now = lambda: (rig.opens+10*60_000)/1000
    await rig.pm.on_minute_bar(rig.p, Bar("TEST", "1m", rig.opens, 90, 91, 89, 90, 100))
    assert engine.orders.placed == []


async def test_missing_prior_daily_session_suppresses_indicators_but_not_protection(engine):
    rig = await prepared(engine)
    rig.p.policy["cartel"]["daily"] = rig.p.policy["cartel"]["daily"][:-1]
    await minute(rig, 0, 110)
    assert rig.p.legs[0].qty == 6  # target is independent of missing indicators
    assert any("incomplete/stale" in s for s in rig.p.attention)
    await minute(rig, 1, 99)
    assert rig.p.status == "closed"  # confirmed-fill breakeven still protects


async def test_adapter_validation_is_opt_in_and_does_not_change_generic_policy(engine):
    rig = await prepared(engine)
    assert rig.pm._validate_spec({**rig.spec, "techniqueId": "team2"})
    generic = {**rig.spec, "techniqueId": "generic", "policy": {"stop": {"kind": "fixed", "price": 95}}}
    assert rig.pm._validate_spec(generic) == []


async def test_adapter_cannot_be_removed_or_cross_injected_through_policy_update(engine):
    rig = await prepared(engine)
    with pytest.raises(ValueError, match="cannot switch"):
        await rig.pm.set_policy(rig.p.id, {"stop": {"kind": "fixed", "price": 96}})
    changed = {**rig.p.policy, "cartel": {**rig.p.policy["cartel"], "initialQty": 100}}
    with pytest.raises(ValueError, match="reviewed update"):
        await rig.pm.set_policy(rig.p.id, changed)
    assert rig.p.policy["cartel"]["initialQty"] == 8


async def test_unavailable_adapter_retains_protective_stop_and_attention(engine):
    rig = await prepared(engine)
    rig.pm._policy_adapters.clear()
    await minute(rig, 0, 90)
    assert rig.p.status == "closed" and not rig.p.open_legs
    assert engine.orders.placed[-1].reduce_only
    assert any("adapter unavailable" in s for s in rig.p.attention)


async def test_venue_stop_is_resized_after_trim_even_when_price_does_not_change(engine):
    rig = await prepared(engine)
    rig.p.overnight = "venue_stop"
    engine.orders.script[0] = {"status": "ACCEPTED"}
    engine.orders.script[2] = {"status": "ACCEPTED"}
    await rig.pm._ensure_venue_stop(rig.p)
    await minute(rig, 0, 110)
    assert engine.orders.placed[0].qty == 8 and engine.orders.placed[2].qty == 6
    engine.orders.script[4] = {"status": "ACCEPTED"}
    await rig.pm.close(rig.p.id, fraction=1/6, reason="manual trim")
    assert engine.orders.placed[4].qty == 5 and rig.p.state.stop == 100


async def test_real_order_manager_sim_trim_is_reduce_only_and_fill_confirmed(engine):
    pf = next(p["id"] for p in engine.positions.portfolios() if p["kind"] == "sim")
    await engine.ensure_symbol("TEST")
    st = engine.feed._symbols["TEST"]
    st.price, st.sigma_per_min, st.drift_per_min = 100., 0., 0.
    engine.quotes.on_quote(Quote(symbol="TEST", bid=100, ask=100.01, last=100))
    entry = await engine.orders.place(OrderIntent(portfolio_id=pf, symbol="TEST", side="BUY", qty=8,
                                                 order_type="LMT", limit_price=100.01))
    async def entry_filled():
        engine.quotes.on_quote(Quote(symbol="TEST", bid=100, ask=100.01, last=100))
        async with engine.sf() as session:
            return (await session.get(Order, entry["id"])).filled_qty == 8
    await wait_for(entry_filled)
    async with engine.sf() as session:
        entry_price = (await session.get(Order, entry["id"])).avg_fill_price
    rig = await prepared(engine, fake=False, fill_price=entry_price)
    engine.quotes.on_quote(Quote(symbol="TEST", bid=110, ask=110.01, last=110))
    await minute(rig, 0, 110)
    exit_id = rig.p.exits[-1]["orderId"]
    async def exit_filled():
        engine.quotes.on_quote(Quote(symbol="TEST", bid=110, ask=110.01, last=110))
        async with engine.sf() as session:
            order = await session.get(Order, exit_id)
            if order.filled_qty == 2:
                from zargar.orders import order_dict
                await rig.pm.on_order_update(order_dict(order))
                return True
            return False
    await wait_for(exit_filled)
    assert rig.p.legs[0].qty == 6 and rig.p.state.stop == 100
    assert engine.positions.position_qty(pf, "TEST") == 6
    async with engine.sf() as session:
        exit_price = (await session.get(Order, exit_id)).avg_fill_price
    assert rig.p.realized_pnl == pytest.approx((exit_price-entry_price)*2)
