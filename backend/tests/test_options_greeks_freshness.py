"""A quote or partial Greek refresh cannot launder an older delta observation."""
from types import SimpleNamespace

from zargar.bus import Bus
from zargar.marketdata import QuoteCache
from zargar.options.service import OptionsService


async def test_greek_observation_times_are_per_field_and_survive_chain_merges(monkeypatch):
    from zargar.options import service as module

    sym = "TEST261218C00100000"
    clock = [1000]
    monkeypatch.setattr(module, "now_ms", lambda: clock[0])

    class Source:
        def __init__(self):
            self.values = {"delta": .4, "gamma": .1}

        async def latest(self, symbols):
            return {sym: {"bid": 1.9, "ask": 2.0, "last": 1.95}}

        async def greeks(self, symbols):
            return {sym: self.values}

    source = Source()
    service = OptionsService(SimpleNamespace(settings={}, config=SimpleNamespace(), quotes=QuoteCache(Bus())))
    service.use_quote_source(source)
    service._tracked.add(sym)
    await service._refresh_live()
    assert service.snapshot_cached(sym)["greeksFieldAsOf"] == {"delta": 1000, "gamma": 1000}
    clock[0] = 2000
    source.values = {"delta": None, "gamma": .2}
    service._greeks_cycle = 15
    await service._refresh_live()
    snapshot = service.snapshot_cached(sym)
    assert snapshot["greeks"]["delta"] == .4
    assert snapshot["greeksFieldAsOf"] == {"delta": 1000, "gamma": 2000}
    clock[0] = 3000
    await service._refresh_live()  # quote-only pass
    assert service.snapshot_cached(sym)["greeksFieldAsOf"]["delta"] == 1000
    merged = service._merge_row({"symbol": sym, "greeks": {"delta": .9}}, 4000)
    assert merged["greeks"]["delta"] == .4
    assert merged["greeksFieldAsOf"]["delta"] == 1000
