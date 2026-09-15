"""Terminal cumulative fill must advance both unopened and already-open trades.
Synthetic order updates, no database/provider/real orders. Build a2457fe.
"""
import pytest
from .test_codex_team2_v078_reconciliation import uncertain_trade


@pytest.mark.parametrize("earlier_partial", [False, True])
async def test_terminal_report_books_additional_fill_even_after_an_earlier_partial(earlier_partial):
    runner, ap, trade = await uncertain_trade()
    if earlier_partial:
        await runner.on_order_update({"id": trade.entry_order_id, "status": "PARTIALLY_FILLED",
                                      "filledQty": 1.0, "avgFillPrice": .5})
        assert trade.status == "open" and trade.remaining == 1.0
    # A second contract filled before the remainder was cancelled. Its fill callback was missed.
    await runner.on_order_update({"id": trade.entry_order_id, "status": "CANCELLED",
                                  "filledQty": 2.0, "avgFillPrice": .55})
    assert trade.filled_qty == 2.0, "terminal cumulative fill was ignored because trade was already open"
    assert trade.remaining == 2.0 and trade.status == "open" and trade.avg_fill == .55
    assert trade.trigger_id not in runner.state_extras(ap)["executionRefused"]
