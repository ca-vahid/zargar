"""Terminal cumulative fill evidence must survive a missing intermediate update.
Synthetic only; real order callback/restore, mocked storage and transport.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from .test_codex_team2_v078_reconciliation import uncertain_trade
from .test_codex_team2_data_eod import rig


@pytest.mark.parametrize("restore", [False, True])
async def test_cancelled_with_cumulative_fill_keeps_position_without_prior_fill_callback(restore):
    runner, ap, trade = await uncertain_trade()
    if restore:
        state = {"trades": [trade.to_dict()]}
        runner, ap = rig()
        row = SimpleNamespace(status="CANCELLED", filled_qty=1.0, avg_fill_price=.5,
                              reject_reason="remaining quantity cancelled")
        session = SimpleNamespace(get=AsyncMock(return_value=row))
        class Context:
            async def __aenter__(self): return session
            async def __aexit__(self, *args): return False
        runner.engine.sf = Context
        await runner._restore_trades(ap, state=state)
        trade = ap.trades[trade.trigger_id]
    else:
        await runner.on_order_update({"id": trade.entry_order_id, "status": "CANCELLED",
                                      "filledQty": 1.0, "avgFillPrice": .5})
    assert trade.filled_qty == 1.0, "terminal report's cumulative fill was discarded"
    assert trade.status == "open" and trade.remaining == 1.0
    assert trade.trigger_id not in runner.state_extras(ap)["executionRefused"]
