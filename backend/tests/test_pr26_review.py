"""Independent exact-contract freshness case for PR26."""
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.domain import Quote
from zargar.options.service import OptionsService
from zargar.techniques.tip.analyst import _run_tool


async def test_exact_contract_does_not_present_stale_opra_as_live():
    symbol = "TEST261016C00105000"
    q = Quote(symbol=symbol, bid=1.0, ask=1.1, last=1.05, source="opra",
              source_ts=int(time.time() * 1000) - 3_600_000)
    eng = NS(quotes=NS(get=lambda _: q))
    service = object.__new__(OptionsService)
    service.engine = eng
    service._served_live = {symbol}
    service._tracked = {symbol}  # real track() takes the already-tracked path
    service.chain = AsyncMock(return_value={"spot": 100, "rows": []})
    eng.options = service
    out = await _run_tool(eng, "get_chain", {"symbol": "TEST", "expiry": "2026-10-16", "contract": symbol})
    assert not out.get("live") or out["live"].get("ageSeconds", 0) >= 3600, out
