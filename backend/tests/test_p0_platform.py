"""P0 of the 2026-09-24 plan: reserved DB pool for money paths, market-hours option enrichment, restart readiness that waits
for a Cartel preparation, and the Alpaca chain behind CBOE."""
import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import httpx
import pytest

from zargar.options.chain import AlpacaChainClient, FallbackChain, OptionsError, cboe_priority
from zargar.options.service import OptionsService
from zargar.ops import CARTEL_PREP_BLOCK_MINUTES, readiness_from_state

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------------------------- P0.2 reserved pool
def test_the_money_paths_use_the_reserved_pool():
    from zargar.engine import Engine
    from .conftest import make_test_config
    eng = Engine(make_test_config())
    try:
        assert eng.sf_critical is not eng.sf, "a separate session factory"
        assert eng.journal._sf is eng.sf_critical, "the journal (write-ahead decisions) writes through the reserved pool"
        assert eng.positions._sf is eng.sf_critical, "the position ledger too"
        assert eng.db.pool.size() == 10 and eng.db_critical.pool.size() == 5
    finally:
        asyncio.run(eng.db.dispose()); asyncio.run(eng.db_critical.dispose())


# ---------------------------------------------------------------------------------------------- P0.3 market hours
@pytest.mark.parametrize("when,active", [
    (dt.datetime(2026, 9, 24, 8, 59, tzinfo=ET), False),
    (dt.datetime(2026, 9, 24, 9, 0, tzinfo=ET), True),        # the pre-open warm-up
    (dt.datetime(2026, 9, 24, 16, 14, tzinfo=ET), True),
    (dt.datetime(2026, 9, 24, 16, 15, tzinfo=ET), False),
    (dt.datetime(2026, 9, 24, 23, 0, tzinfo=ET), False),      # overnight: was polling CBOE all night
    (dt.datetime(2026, 9, 26, 11, 0, tzinfo=ET), False),      # Saturday
])
def test_enrichment_runs_at_full_cadence_only_in_market_hours(when, active):
    assert OptionsService.active_window(when) is active


# ---------------------------------------------------------------------------------------------- P0.5b readiness
def _state(prep):
    return {"cartelPreparation": prep}


def test_a_young_cartel_preparation_holds_a_restart_back_and_an_old_one_only_warns():
    r = readiness_from_state(_state({"live": True, "ageMinutes": 3.0}))
    assert not r["safe"] and "Options Cartel preparation is running" in r["reasons"][0]
    r = readiness_from_state(_state({"live": True, "ageMinutes": CARTEL_PREP_BLOCK_MINUTES + 5}))
    assert r["safe"] and "retry loop" in r["warnings"][0], "the uncapped retry loop never blocks a restart forever"
    r = readiness_from_state(_state({"live": False, "ageMinutes": 40.0}))
    assert r["safe"] and "no live task" in r["warnings"][0]
    assert readiness_from_state(_state(None))["safe"]


# ---------------------------------------------------------------------------------------------- P0.6 Alpaca chain
TODAY = dt.datetime.now(ET).date().isoformat()


def _alpaca_transport():
    snaps_p1 = {"snapshots": {"VRT260925P00245000": {"latestQuote": {"bp": 6.4, "ap": 6.6}, "latestTrade": {"p": 6.5},
                                                    "dailyBar": {"v": 117, "t": TODAY + "T04:00:00Z"},
                                                    "greeks": {"delta": -0.45}, "impliedVolatility": 0.55}},
                "next_page_token": "p2"}
    snaps_p2 = {"snapshots": {"VRT260925C00250000": {"latestQuote": {"bp": 5.0, "ap": 5.2}, "latestTrade": {"p": 5.1},
                                                    "dailyBar": {"v": 40, "t": "2026-09-16T04:00:00Z"}}}}
    contracts = {"option_contracts": [{"symbol": "VRT260925P00245000", "open_interest": "217", "expiration_date": "2026-09-25"},
                                      {"symbol": "VRT260925C00250000", "open_interest": "12", "expiration_date": "2026-09-25"}]}

    def handler(request: httpx.Request):
        if "/options/snapshots/" in request.url.path:
            return httpx.Response(200, json=snaps_p2 if request.url.params.get("page_token") == "p2" else snaps_p1)
        if request.url.path.endswith("/v2/options/contracts"):
            if request.url.host.startswith("paper-api"):
                return httpx.Response(200, json=contracts)
            return httpx.Response(401, json={})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_the_alpaca_chain_pages_joins_open_interest_and_counts_only_todays_volume():
    async def run():
        c = AlpacaChainClient("k", "s", httpx.AsyncClient(transport=_alpaca_transport()))
        return await c.chain("VRT", "2026-09-25"), await c.expirations("VRT")
    rows, exps = asyncio.run(run())
    by = {r["symbol"]: r for r in rows}
    assert set(by) == {"VRT260925P00245000", "VRT260925C00250000"}, "both pages"
    put = by["VRT260925P00245000"]
    assert (put["bid"], put["ask"], put["open_interest"], put["volume"], put["provider"]) == (6.4, 6.6, 217, 117, "alpaca")
    assert put["greeks"]["delta"] == -0.45 and put["greeks"]["mid_iv"] == 0.55
    assert by["VRT260925C00250000"]["volume"] == 0, "a daily bar from another day is not today's volume"
    assert exps == ["2026-09-25"]


class _Primary:
    name, delayed = "cboe", True

    def __init__(self, exc):
        self.exc = exc

    async def chain(self, symbol, expiry):
        raise self.exc


class _Secondary:
    name = "alpaca"

    def __init__(self):
        self.calls = 0

    async def chain(self, symbol, expiry):
        self.calls += 1
        return [{"symbol": "X", "provider": "alpaca"}]


def test_the_fallback_answers_entries_but_never_background_or_a_real_404():
    sec = _Secondary()
    fb = FallbackChain(_Primary(OptionsError("CBOE HTTP 429 (rate limited; 3 retries)")), sec)

    async def entry():
        with cboe_priority("entry"):
            return await fb.chain("VRT", "2026-09-25")
    assert asyncio.run(entry())[0]["provider"] == "alpaca" and fb.fallbacks == 1 and fb.name == "cboe"

    async def bg():
        with cboe_priority("background"):
            return await fb.chain("VRT", "2026-09-25")
    with pytest.raises(OptionsError, match="429"):
        asyncio.run(bg())
    assert sec.calls == 1, "background never falls back: the quiet window and cooldown stand it down on purpose"
    fb404 = FallbackChain(_Primary(OptionsError("no US-listed options for ZZZ (CBOE 404)")), sec)
    with pytest.raises(OptionsError, match="404"):
        asyncio.run(fb404.chain("ZZZ", "2026-09-25"))
    assert sec.calls == 1, "a symbol with no options is an answer, not a failure"


def test_provider_wraps_cboe_only_with_keys_and_the_setting_on():
    from types import SimpleNamespace
    settings = {"options.chain_fallback": "alpaca"}
    eng = SimpleNamespace(settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)),
                          config=SimpleNamespace(alpaca_key_id="k", alpaca_secret="s"))
    svc = OptionsService.__new__(OptionsService)
    svc.engine, svc._cboe, svc._tradier = eng, None, None
    p = svc.provider()
    assert isinstance(p, FallbackChain) and p.name == "cboe"
    settings["options.chain_fallback"] = "off"
    assert svc.provider() is svc._cboe
    settings["options.chain_fallback"] = "alpaca"
    eng.config.alpaca_key_id = ""
    svc._fallback = None
    assert svc.provider() is svc._cboe, "no keys: CBOE alone"
