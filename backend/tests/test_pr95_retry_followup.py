"""Combined gate ordering on the stale-quote retry; all I/O is fake."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.approvals.proposals import ProposalService
from zargar.orders import OrderIntent
from zargar.techniques.tip import integrity


async def test_incident_opened_during_geometry_refresh_blocks_quote_retry(monkeypatch):
    row = NS(context={})

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, *_args, **_kwargs):
            return row

        async def commit(self):
            pass

    incident_open = False

    async def admission(*_args, **_kwargs):
        return "incident opened while geometry fetched evidence" if incident_open else None

    async def geometry(pdict, **_kwargs):
        nonlocal incident_open
        incident_open = True
        return 1.0, pdict, None

    eng = NS(sf=Session, settings={},
             positions=NS(portfolio=lambda _pid: {"kind": "sim"}),
             quotes=NS(get=lambda _symbol: NS(ask=10, ts=1000, source_ts=1000)),
             orders=NS(place=AsyncMock(return_value={"id": "retry", "status": "FILLED"})),
             journal=NS(append=AsyncMock()))
    service = ProposalService(eng)
    service._admit_geometry = geometry
    monkeypatch.setattr(integrity, "admission", admission)
    pdict = {"id": "proposal", "portfolioId": "practice", "symbol": "X",
             "context": {"techniqueId": "tip", "vehicle": {"underlying": "X"}}}
    intent = OrderIntent(portfolio_id="practice", symbol="X", sec_type="STK",
                         side="BUY", qty=1, order_type="LMT", limit_price=10)
    await service._maybe_retry_stale_quote(
        pdict, intent, {"id": "original", "status": "REJECTED_RISK",
                       "rejectReason": "quote age 10.5s (max 10s)"}, via="auto")
    eng.orders.place.assert_not_awaited()
