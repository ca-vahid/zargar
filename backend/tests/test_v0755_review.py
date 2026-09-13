"""v0.7.55 shared-state and census acceptance. All I/O is fake."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.domain import Bar
from zargar.tools import tip_outcomes

from .test_premium_stop_debounce import BASE, SYM, _mgr, _pos, _q, _tick, _und


async def test_healthy_bar_resets_prior_tick_breach():
    p, m = _pos(), _mgr(lambda s: None)
    await _tick(m, p, _q(.82, BASE), BASE + 1000)
    now = BASE + 2000
    m._now = lambda: now / 1000
    m.engine.quotes = NS(get=lambda s: _q(1.53, now) if s == SYM else _und(now))
    bar = Bar(symbol="DAL", tf="1m", ts=now, open=91.3, high=91.4, low=91.2, close=91.35)
    await m._decide(p, bar, [bar])
    await _tick(m, p, _q(.81, BASE + 3000), BASE + 4000)
    assert m.close.await_count == 0, "A healthy intervening bar did not reset the first breach"


async def census(monkeypatch, capsys, buys, sells):
    stamp = dt.datetime(2026, 9, 10, 15, tzinfo=dt.UTC)
    symbol = buys[0]["symbol"]
    signal = {"id": "idea-1", "source_name": "AuditSource", "status": "proposed",
              "created_at": stamp, "extraction": {}}
    order = {"id": "buy-1", "signal_id": "idea-1", "symbol": symbol, "side": "BUY",
             "filled_qty": buys[0]["qty"], "limit_price": buys[0]["price"],
             "avg_fill_price": buys[0]["price"], "status": "FILLED", "portfolio_id": "tips"}

    class Connection:
        async def fetch(self, query, *args):
            if "FROM signals" in query:
                return [signal]
            if "FROM proposals" in query:
                return []
            if "FROM orders" in query:
                return [order]
            if "FROM executions" in query:
                return [{**e, "ts": stamp} for e in buys + sells]
            return []

        async def close(self):
            pass

    monkeypatch.setattr(tip_outcomes.asyncpg, "connect", AsyncMock(return_value=Connection()))
    monkeypatch.setattr(tip_outcomes.argparse.ArgumentParser, "parse_args",
                        lambda _: NS(db="unused-offline", since="2026-09-08"))
    await tip_outcomes.main()
    line = next(s for s in capsys.readouterr().out.splitlines() if s.startswith("| AuditSource |"))
    return [s.strip() for s in line.split("|")[1:-1]]


async def test_census_does_not_borrow_another_books_sell(monkeypatch, capsys):
    buy = {"order_id": "buy-1", "symbol": "X", "side": "BUY", "qty": 1,
           "price": 10, "commission": 0, "portfolio_id": "tips"}
    other_sell = {**buy, "order_id": "other-sell", "side": "SELL", "price": 20,
                  "portfolio_id": "other-sim"}
    cells = await census(monkeypatch, capsys, [buy], [other_sell])
    assert cells[5] == "0" and float(cells[9]) == 0, cells


async def test_census_reports_partial_realization_with_allocated_entry_fees(monkeypatch, capsys):
    buy = {"order_id": "buy-1", "symbol": "T270115C00029000", "side": "BUY",
           "qty": 14, "price": .52, "commission": 14.56, "portfolio_id": "tips"}
    sell = {**buy, "order_id": "sell-1", "side": "SELL", "qty": 4,
            "price": .61, "commission": 4.16}
    cells = await census(monkeypatch, capsys, [buy], [sell])
    assert float(cells[9]) == 27.68, cells
