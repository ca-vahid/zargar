"""Reporting boundaries for the FIFO census; all database I/O is fake."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.tools import tip_outcomes

from .test_v0757_review import render


async def test_fees_paid_include_the_entry_fee_on_open_inventory(monkeypatch, capsys):
    rows = await render(monkeypatch, capsys,
                        [("idea-a", 0, 14, .52, 14.56)], [(1, 4, .61, 4.16)])
    assert float(rows[0][10]) == 18.72, rows
    assert float(rows[0][16]) == 10.40, rows


async def unmatched_census(monkeypatch, capsys, *, same_key_buy):
    stamp = dt.datetime(2026, 9, 10, 15, tzinfo=dt.UTC)
    buy = {"order_id": "buy", "portfolio_id": "tips", "symbol": "X",
           "side": "BUY", "qty": 1, "price": 10, "commission": 0, "ts": stamp}
    sell = {**buy, "order_id": "sell", "symbol": "X" if same_key_buy else "Y",
            "side": "SELL", "qty": 2, "price": 20, "ts": stamp + dt.timedelta(minutes=1)}

    class Connection:
        async def fetch(self, query, *args):
            if "FROM signals" in query:
                return [{"id": "idea-a", "source_name": "A", "status": "proposed",
                         "created_at": stamp, "extraction": {}}]
            if "FROM orders" in query:
                return [{"id": "buy", "signal_id": "idea-a", "symbol": "X", "side": "BUY",
                         "filled_qty": 1, "limit_price": 10, "avg_fill_price": 10,
                         "status": "FILLED", "portfolio_id": "tips"}]
            if "FROM executions" in query:
                return [buy, sell]
            return []

        async def close(self):
            pass

    monkeypatch.setattr(tip_outcomes.asyncpg, "connect", AsyncMock(return_value=Connection()))
    monkeypatch.setattr(tip_outcomes.argparse.ArgumentParser, "parse_args",
                        lambda _: NS(db="unused-offline", since="2026-09-08"))
    await tip_outcomes.main()
    return capsys.readouterr().out


async def test_oversell_on_a_known_lot_key_is_reported(monkeypatch, capsys):
    output = await unmatched_census(monkeypatch, capsys, same_key_buy=True)
    assert "Unallocated sells (oversold/pre-lot): 1" in output


async def test_sell_without_any_lot_key_is_still_reported(monkeypatch, capsys):
    # Y was held before the report cutoff: no in-window Y buy, but its sale
    # must still appear in reconciliation exceptions rather than disappear.
    output = await unmatched_census(monkeypatch, capsys, same_key_buy=False)
    assert "Unallocated sells (oversold/pre-lot): 1" in output
