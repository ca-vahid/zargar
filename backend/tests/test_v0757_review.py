"""Independent follow-up boundaries; fake census I/O and offline positions only."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.domain import Bar
from zargar.tools import tip_outcomes

from .test_premium_stop_debounce import BASE, _mgr, _pos, _q, _tick, _und


async def test_markless_bar_preserves_pending_sighting():
    p, m = _pos(), _mgr(lambda s: None)
    await _tick(m, p, _q(.82, BASE), BASE + 1000)
    pending = dict(m._premium_confirm[p.id])
    now = BASE + 2000
    m._now = lambda: now / 1000
    m.engine.quotes = NS(get=lambda s: _und(now) if s == "DAL" else None)
    bar = Bar(symbol="DAL", tf="1m", ts=now, open=91.3, high=91.4, low=91.2, close=91.35)
    await m._decide(p, bar, [bar])
    assert m._premium_confirm[p.id] == pending
    assert m.close.await_count == 0


async def test_quantity_only_reduction_preserves_contract_confirmation():
    p, m = _pos(), _mgr(lambda s: None)
    await _tick(m, p, _q(.82, BASE), BASE + 1000)
    p.legs[0].qty = 2
    await _tick(m, p, _q(.81, BASE + 3000), BASE + 4000)
    assert m.close.await_count == 1
    assert m.close.call_args.kwargs["kind"] == "premium_stop"


async def render(monkeypatch, capsys, buys, sells):
    """Tuple inputs are (idea, minute, qty, price, fee) and (minute, qty, price, fee)."""
    stamp = dt.datetime(2026, 9, 10, 15, tzinfo=dt.UTC)
    signals, orders, executions = {}, [], []
    for i, (idea, minute, qty, price, fee) in enumerate(buys):
        ts = stamp + dt.timedelta(minutes=minute)
        signals.setdefault(idea, {"id": idea, "source_name": idea, "status": "proposed",
                                  "created_at": ts, "extraction": {}})
        orders.append({"id": f"buy-{i}", "signal_id": idea, "symbol": "X", "side": "BUY",
                       "filled_qty": qty, "limit_price": price, "avg_fill_price": price,
                       "status": "FILLED", "portfolio_id": "tips"})
        executions.append({"order_id": f"buy-{i}", "portfolio_id": "tips", "symbol": "X",
                           "side": "BUY", "qty": qty, "price": price, "commission": fee, "ts": ts})
    for i, (minute, qty, price, fee) in enumerate(sells):
        executions.append({"order_id": f"sell-{i}", "portfolio_id": "tips", "symbol": "X",
                           "side": "SELL", "qty": qty, "price": price, "commission": fee,
                           "ts": stamp + dt.timedelta(minutes=minute)})

    class Connection:
        async def fetch(self, query, *args):
            if "FROM signals" in query:
                return list(signals.values())
            if "FROM orders" in query:
                return orders
            if "FROM executions" in query:
                return executions
            return []

        async def close(self):
            pass

    monkeypatch.setattr(tip_outcomes.asyncpg, "connect", AsyncMock(return_value=Connection()))
    monkeypatch.setattr(tip_outcomes.argparse.ArgumentParser, "parse_args",
                        lambda _: NS(db="unused-offline", since="2026-09-08"))
    await tip_outcomes.main()
    return [[c.strip() for c in line.split("|")[1:-1]]
            for line in capsys.readouterr().out.splitlines() if line.startswith("| idea-")]


async def test_exit_fill_is_consumed_once_across_ideas(monkeypatch, capsys):
    # Two ideas own one share each, with $1 entry fee each. One shared exit
    # sells both shares, earning $20 gross less $4 total fees = $16 net.
    rows = await render(monkeypatch, capsys,
                        [("idea-a", 0, 1, 10, 1), ("idea-b", 1, 1, 10, 1)],
                        [(2, 2, 20, 2)])
    assert sum(float(r[9]) for r in rows) == 16, rows
    assert sum(float(r[10]) for r in rows) == 4, rows
    assert all(float(r[16]) >= 0 for r in rows), rows


async def test_reentry_cannot_change_prior_realized_basis(monkeypatch, capsys):
    # Buy 10 -> sell 12 realizes $2; a later buy at 20 remains open.
    # Aggregating every buy before calculating realization rewrites the
    # already-closed episode's basis to 15, falsely reporting a $3 loss.
    rows = await render(monkeypatch, capsys,
                        [("idea-a", 0, 1, 10, 0), ("idea-a", 2, 1, 20, 0)],
                        [(1, 1, 12, 0)])
    assert float(rows[0][9]) == 2, rows
    assert float(rows[0][6]) == 20, rows
