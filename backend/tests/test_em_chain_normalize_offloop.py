"""Stall #2 (2026-09-16 20:58, 4.8 s): thousands of occ.parse + symbol formats ran on the loop inside the enrichment pass.
Chain normalisation now runs on a worker thread; results and the expiry filter are unchanged."""
import asyncio

from zargar.options import chain as chain_mod


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status; self._payload = payload; self.headers = {}

    def json(self):
        return self._payload


class _Http:
    def __init__(self, responses):
        self.responses = list(responses); self.calls = 0

    async def get(self, url):
        self.calls += 1
        return self.responses.pop(0)


PAYLOAD = {"data": {"options": [
    {"option": "BAC260918P00050000", "bid": 1.0, "ask": 1.1, "iv": 0.3, "open_interest": 10, "volume": 5, "delta": -0.4},
    {"option": "BAC260925C00052000", "bid": 0.5, "ask": 0.6, "iv": 0.3, "open_interest": 3, "volume": 1, "delta": 0.4},
    {"option": "garbage", "bid": 0, "ask": 0}]}}


def test_all_rows_and_chain_normalise_off_loop_with_the_same_results():
    c = chain_mod.CboeClient(client=_Http([_Resp(200, PAYLOAD)]))
    rows = asyncio.run(c.all_rows("bac"))
    assert [r["symbol"] for r in rows] == ["BAC260918P00050000", "BAC260925C00052000"], "unparseable rows dropped, order kept"
    c2 = chain_mod.CboeClient(client=_Http([_Resp(200, PAYLOAD)]))
    week = asyncio.run(c2.chain("BAC", "2026-09-18"))
    assert [r["symbol"] for r in week] == ["BAC260918P00050000"]


def test_loop_keeps_ticking_while_a_large_chain_normalises():
    big = {"data": {"options": [{"option": f"SPY261218C{400000 + i * 5:08d}", "bid": 1.0, "ask": 1.1} for i in range(6000)]}}
    ticks = []

    async def ticker():
        while True:
            ticks.append(1); await asyncio.sleep(0.005)

    async def scenario():
        t = asyncio.create_task(ticker())
        rows = await chain_mod.CboeClient(client=_Http([_Resp(200, big)])).all_rows("SPY")
        t.cancel()
        return rows

    rows = asyncio.run(scenario())
    assert len(rows) == 6000 and len(ticks) >= 2, "the loop ran its own task while 6000 rows normalised on the worker"
