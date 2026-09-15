"""Practice execution realism: an option intent can wait, not fill at 04:01 ET."""
import datetime as dt

from zargar.brokers import sim
from zargar.brokers.base import BrokerOrder
from zargar.domain import OrderSide, OrderType, Quote


async def test_equity_option_exit_waits_for_an_eligible_session(monkeypatch):
    stamp = int(dt.datetime(2026, 9, 14, 8, 1, tzinfo=dt.UTC).timestamp() * 1000)
    monkeypatch.setattr(sim, "now_ms", lambda: stamp)
    reports = []

    async def record(report):
        reports.append(report)

    executor = sim.SimExecutor(latency_ms=0)
    executor.on_report = record
    symbol = "APLD261016C00030000"
    await executor.submit(BrokerOrder(
        id="protective-exit", symbol=symbol, sec_type="OPT", side=OrderSide.SELL,
        qty=3, order_type=OrderType.MKT, portfolio_id="practice", option_action="SELL_TO_CLOSE"))
    await executor.on_quote(Quote(symbol=symbol, bid=1.57, ask=1.62, last=1.6,
                                  ts=stamp, source_ts=stamp, source="opra"))
    assert any(r.kind == "accepted" for r in reports), "Keep the protective intent recorded"
    assert not any(r.kind == "fill" for r in reports), (
        "04:01 ET is not an eligible equity-option execution session; a paper fill is not market evidence")
