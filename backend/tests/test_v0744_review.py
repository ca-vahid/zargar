"""Independent v0.7.44 boundaries; fake provider/order I/O only."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.domain import Quote
from zargar.execution.positions import PositionManager

from .test_proposal_fresh_retry import STALE, _proposal
from .test_proposal_fresh_retry import rig as rig  # noqa: PLC0414
from .test_tips_profitability_review import option_position


async def test_retry_actually_refreshes_an_already_tracked_stale_contract(rig, monkeypatch):
    pid = await _proposal(rig)
    symbol = "AAPL260914C00330000"
    now = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    quote = Quote(symbol=symbol, bid=.58, ask=.59, last=.59,
                  source="opra", ts=now - 11_000, source_ts=now - 11_000)
    rig.options._tracked.add(symbol)
    rig.options._served_live.add(symbol)
    monkeypatch.setattr(rig.options, "quote_source", lambda **kw: NS())
    monkeypatch.setattr(rig.quotes, "get", lambda _: quote)
    refresh = AsyncMock(return_value={symbol})
    monkeypatch.setattr(rig.options, "_refresh_live", refresh)
    monkeypatch.setattr(rig.orders, "place", AsyncMock(return_value=dict(STALE)))
    await rig.proposals.approve(pid, via="auto")
    assert refresh.await_count == 1, "Retry reused a tracked stale quote without requesting a new one"


async def test_manual_approval_does_not_enter_auto_retry(rig, monkeypatch):
    pid = await _proposal(rig)
    monkeypatch.setattr(rig.options, "reprice", AsyncMock(return_value=None))
    from zargar.approvals import proposals
    monkeypatch.setattr(proposals, "_live_ask", AsyncMock(return_value=None))
    place = AsyncMock(return_value=dict(STALE))
    monkeypatch.setattr(rig.orders, "place", place)
    await rig.proposals.approve(pid, via="app")
    assert place.await_count == 1, "Auto-only recovery also retried a manual approval"


async def test_tick_premium_stop_uses_source_age_not_refreshed_receipt_age():
    now = int(dt.datetime(2026, 9, 10, 15, 0, tzinfo=dt.UTC).timestamp() * 1000)
    option = Quote(symbol="SPCX270115C00155000", bid=.97, ask=1.05, last=2.02,
                   source="opra", ts=now, source_ts=now - 3_600_000)
    underlying = Quote(symbol="SPCX", bid=153.5, ask=153.7, last=153.6, ts=now)
    manager = PositionManager(NS(settings={}, quotes=NS(
        get=lambda symbol: option if symbol == option.symbol else underlying)))
    manager._now = lambda: now / 1000
    manager.close = AsyncMock()
    manager._persist = AsyncMock()
    position = option_position()
    position.policy["premium_watch"] = True
    manager._pos[position.id] = position
    await manager._watch_once()
    assert manager.close.await_count == 0, manager.close.call_args_list
