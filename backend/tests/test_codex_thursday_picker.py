"""Thursday investigation at 6b54961: supplied quote examples, no live API/data access.

Three diagnostic tests pin observed behavior; the fourth is an unmet execution contract.
"""
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zargar.marketstructure.sessions import ET
from zargar.options.pick import select_by_premium
from zargar.techniques.team2.premium import PremiumModel
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.runner import Team2Runner

DAY = dt.date(2026, 9, 10)


def row(strike, ask, *, expiry=DAY):
    return {"symbol": f"IWM{expiry:%y%m%d}P{int(strike * 1000):08d}",
            "underlying": "IWM", "option_type": "put", "strike": strike,
            "bid": max(0.01, ask - 0.01), "ask": ask, "volume": 33008,
            "open_interest": 717, "greeks": {"delta": -0.385, "mid_iv": 0.2111}}


def select(chain, spot=287.76):
    return select_by_premium(chain, spot, "short", target_premium=0.6, premium_floor=0.2,
                             expiry=DAY.isoformat(), today=DAY, is_0dte=True)


def test_reported_half_strike_is_in_band_but_model_grid_cannot_select_it():
    model = PremiumModel(sigma=0.2111)
    ts = int(dt.datetime(2026, 9, 10, 14, 4, tzinfo=ET).timestamp() * 1000)
    half_mark = model.mark(287.76, 287.5, ts, call=False)
    integer_mark = model.mark(287.76, 287, ts, call=False)
    grid_pick = model.pick_strike(287.76, ts, "short", target_premium=0.6, premium_floor=0.2, step=1)
    listed_pick = select([row(287, 0.10), row(287.5, 0.21), row(288, 0.45)])
    assert 0.2 <= half_mark <= 0.9 and integer_mark < 0.2
    assert grid_pick is None and listed_pick.strike == 287.5
    print({"half_model": half_mark, "integer_model": integer_mark,
           "grid_pick": grid_pick, "listed_pick": listed_pick.strike})


def test_288_put_below_28783_is_itm_and_excluded_by_current_policy():
    spot = 287.83
    assert 288 > spot
    assert select([row(288, 0.45)], spot=spot) is None


def test_queued_target_fix_honors_explicit_targetless_replan_only():
    runner = Team2Runner.__new__(Team2Runner)
    target, refusal = runner.resolve_fire_target({"target": None, "targetKind": "none"},
                                                {"target": 757.90}, 757.0, "short")
    assert target is None and refusal is None
    target, refusal = runner.resolve_fire_target({"target": None}, {"target": 757.90}, 757.0, "short")
    assert refusal is not None


async def test_fresh_option_ask_is_checked_before_cached_chain_floor_refusal():
    today = dt.datetime.now(ET).date()
    provider = SimpleNamespace(expirations=AsyncMock(return_value=[today.isoformat()]),
                               chain=AsyncMock(return_value=[row(287.5, 0.19, expiry=today), row(287, 0.1, expiry=today)]))
    async def fresh(candidate):
        candidate.update(ask=0.21, bid=0.20, source="opra", delayed=False)
        return candidate
    options = SimpleNamespace(provider=lambda: provider, reprice=AsyncMock(side_effect=fresh))
    runner = Team2Runner.__new__(Team2Runner)
    runner.engine = SimpleNamespace(options=options, quotes=SimpleNamespace(get=lambda symbol: SimpleNamespace(last=287.76)))
    runner.rules = lambda: Team2Rules()
    runner._log = lambda *a, **kw: None
    trade = SimpleNamespace(entry=287.76, direction="short", errors=[], trigger_id="diagnostic")
    result = await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade)
    assert result is not None, {"errors": trade.errors, "fresh_quote_requests": options.reprice.await_count}
