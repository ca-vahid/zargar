"""C59 follow-up boundaries; all database operations are fake."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.tools import tip_outcomes


async def _render(monkeypatch, capsys, *, orphan_buy=False, setting='{"v":"tips"}'):
    stamp = dt.datetime(2026, 9, 10, 15, tzinfo=dt.UTC)
    order = {"id": "known-buy", "signal_id": "idea-a", "symbol": "X", "side": "BUY",
             "filled_qty": 1, "limit_price": 20, "avg_fill_price": 20,
             "status": "FILLED", "portfolio_id": "tips"}
    known = {"id": "known-execution", "order_id": "known-buy", "portfolio_id": "tips",
             "symbol": "X", "side": "BUY", "qty": 1, "price": 20,
             "commission": 0, "ts": stamp + dt.timedelta(minutes=1)}
    executions = [known, {**known, "id": "sell-execution", "order_id": "sell",
                           "side": "SELL", "price": 30,
                           "ts": stamp + dt.timedelta(minutes=2)}]
    if orphan_buy:
        # Real execution is in-window, but its order/signal was created before
        # the report cutoff and is omitted by the current query boundary.
        executions.insert(0, {**known, "id": "earlier-execution", "order_id": "older-order",
                              "price": 10, "ts": stamp})

    class Connection:
        async def fetch(self, query, *args):
            if "FROM signals" in query:
                return [{"id": "idea-a", "source_name": "A", "status": "proposed",
                         "created_at": stamp, "extraction": {}}]
            if "FROM orders" in query:
                return [order]
            if "FROM executions" in query:
                return executions
            return []

        async def fetchrow(self, query, *args):
            return {"value": setting}

        async def close(self):
            pass

    monkeypatch.setattr(tip_outcomes.asyncpg, "connect", AsyncMock(return_value=Connection()))
    monkeypatch.setattr(tip_outcomes.argparse.ArgumentParser, "parse_args",
                        lambda _: NS(db="unused-offline", since="2026-09-08", portfolio=""))
    await tip_outcomes.main()
    output = capsys.readouterr().out
    row = next([c.strip() for c in line.split("|")[1:-1]]
               for line in output.splitlines() if line.startswith("| A |"))
    return row, output


async def test_json_settings_scope_preserves_matched_trades(monkeypatch, capsys):
    row, output = await _render(monkeypatch, capsys)
    assert "Scope: portfolio tips." in output
    assert float(row[9]) == 10


async def test_unlinked_earlier_buy_cannot_close_later_idea(monkeypatch, capsys):
    row, output = await _render(monkeypatch, capsys, orphan_buy=True)
    # FIFO: the earlier $10 lot is sold; the later known idea still owns its
    # $20 lot. Unknown ownership must be loaded or reported, never ignored.
    assert float(row[6]) == 20, output
    assert float(row[9]) == 0, output
