"""2026-09-17 EOD review item 3: chain LISTINGS are cached per (provider, symbol, expiry), concurrent requests coalesce,
a rate-limited or transient failure is retried within bounds and may fall back to a labelled stale listing; prices are
never served from the cache (every candidate is still re-quoted live) and the timing gates are untouched.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest

from zargar.options.chain import OptionsError

from .test_team2_diagnostics import FakeOpts, chain, rig


class FlakyProvider:
    name = "cboe"

    def __init__(self, rows, fail_first: int = 0, error: str = "CBOE HTTP 429"):
        self.rows, self.fail_first, self.error, self.calls, self.exp_calls = rows, fail_first, error, 0, 0

    async def chain(self, symbol, expiry):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise OptionsError(self.error)
        await asyncio.sleep(0.01)
        return list(self.rows)

    async def expirations(self, symbol):
        self.exp_calls += 1
        if self.exp_calls <= self.fail_first:
            raise OptionsError(self.error)
        return ["2026-09-14", "2026-09-15"]


def _runner():
    runner, ap = rig(FakeOpts(chain(), {}))
    runner.engine.settings = {"techniques.team2.chain_cache_seconds": 900, "techniques.team2.chain_cache_max_age_seconds": 14400}
    return runner, ap


async def test_listing_is_cached_and_concurrent_callers_share_one_fetch(monkeypatch):
    runner, ap = _runner()
    prov = FlakyProvider(chain())
    rows, meta = await runner._listing(prov, "SPY", "2026-09-14")
    assert len(rows) == 4 and meta["listingSource"] == "fetch" and prov.calls == 1
    rows2, meta2 = await runner._listing(prov, "SPY", "2026-09-14")
    assert meta2["listingSource"] == "cache" and prov.calls == 1 and meta2["listingAgeMs"] >= 0
    # another expiry / symbol is another key
    await runner._listing(prov, "SPY", "2026-09-15"); await runner._listing(prov, "QQQ", "2026-09-14")
    assert prov.calls == 3
    # three plans asking at once for a new key: one request, one fetch + two coalesced
    prov2 = FlakyProvider(chain())
    results = await asyncio.gather(*[runner._listing(prov2, "IWM", "2026-09-14") for _ in range(3)])
    assert prov2.calls == 1 and sorted(m["listingSource"] for _, m in results) == ["coalesced", "coalesced", "fetch"]


async def test_rate_limit_is_retried_within_bounds_and_labelled(monkeypatch):
    import zargar.techniques.team2.runner as module
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    runner, ap = _runner()
    prov = FlakyProvider(chain(), fail_first=2)
    rows, meta = await runner._listing(prov, "SPY", "2026-09-14")
    assert len(rows) == 4 and meta["listingSource"] == "retry" and meta["listingAttempts"] == 3 and prov.calls == 3
    assert [x for x in sleeps if x >= 0.5] == [0.8, 1.6]              # bounded: two back-offs, never more (the fake provider's own tiny sleep aside)
    # a third failure in a row gives up (no cache to fall back on) and the error surfaces as before
    prov3 = FlakyProvider(chain(), fail_first=5)
    with pytest.raises(OptionsError):
        await runner._listing(prov3, "QQQ", "2026-09-14")
    assert prov3.calls == 3
    # a non-transient error is not retried at all
    prov4 = FlakyProvider(chain(), fail_first=5, error="no US-listed options for XYZ (CBOE 404)")
    with pytest.raises(OptionsError):
        await runner._listing(prov4, "XYZ", "2026-09-14")
    assert prov4.calls == 1


async def test_a_stale_listing_serves_only_within_the_bound_and_says_so(monkeypatch):
    import zargar.techniques.team2.runner as module
    real_sleep = asyncio.sleep
    monkeypatch.setattr(module.asyncio, "sleep", lambda s: real_sleep(0))
    runner, ap = _runner()
    prov = FlakyProvider(chain())
    await runner._listing(prov, "SPY", "2026-09-14")
    key = runner._chain_key(prov, "SPY", "2026-09-14")
    runner._chain_cache[key]["ts"] -= 1_000_000            # past the TTL, inside the max age
    prov.fail_first = 99
    rows, meta = await runner._listing(prov, "SPY", "2026-09-14")
    assert len(rows) == 4 and meta["listingSource"] == "stale-cache" and "429" in meta["listingError"]
    runner._chain_cache[key]["ts"] -= 20_000_000           # beyond the max age: the failure surfaces
    with pytest.raises(OptionsError):
        await runner._listing(prov, "SPY", "2026-09-14")


async def test_expiries_are_cached_and_the_picker_re_quotes_every_candidate_live(monkeypatch):
    import zargar.techniques.team2.runner as module
    real_sleep = asyncio.sleep
    monkeypatch.setattr(module.asyncio, "sleep", lambda s: real_sleep(0))
    runner, ap = _runner()
    prov = FlakyProvider(chain(), fail_first=1)
    exps, meta = await runner._expiries(prov, "SPY")
    assert exps == ["2026-09-14", "2026-09-15"] and meta["listingSource"] == "retry"
    exps2, meta2 = await runner._expiries(prov, "SPY")
    assert meta2["listingSource"] == "cache" and prov.exp_calls == 2
    from dataclasses import replace
    rules = replace(runner.rules_for(ap), dte_policy="0dte")
    expiry, why = await runner._expiry_for(prov, "SPY", rules, dt.date(2026, 9, 14))
    assert expiry == "2026-09-14" and why is None and prov.exp_calls == 2
    # the listing never carries a price into the pick: the live re-price decides eligibility
    opts = FakeOpts(chain(), {"SPY260914C00102000": (0.44, 0.46)})
    otm = sorted(chain(), key=lambda c: c["strike"])
    qres = await runner._quote_examined(opts, otm, 100.4, "long", rules, "2026-09-14", dt.date(2026, 9, 14))
    assert [x["eligible"] for x in qres["examined"]] == [False, True, False, False]
    assert qres["pick"] is not None and qres["pick"].symbol == "SPY260914C00102000" and qres["pick"].ask == 0.46
    assert all(x["delayedAsk"] == 0.5 for x in qres["examined"])       # the chain's delayed ask is reported, never the price


# ---------------------------------------------------------------- PR204 review: the shared request is cancellation-safe and bounded
async def test_provider_error_reaches_every_waiter_and_a_fresh_request_follows_a_cancellation():
    runner, _ = _runner()
    started, finish = asyncio.Event(), asyncio.Event()
    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        started.set()
        await finish.wait()
        if calls["n"] == 1:
            raise OptionsError("no US-listed options for XYZ (CBOE 404)")
        return ["listing", "again"]
    key = ("provider", "XYZ", "2026-09-14")
    owner = asyncio.create_task(runner._cached_chain_call(key, fetch, ttl_s=900, max_age_s=14400))
    await started.wait()
    waiter = asyncio.create_task(runner._cached_chain_call(key, fetch, ttl_s=900, max_age_s=14400))
    await asyncio.sleep(0)
    finish.set()
    results = await asyncio.gather(owner, waiter, return_exceptions=True)
    assert all(isinstance(r, OptionsError) for r in results) and calls["n"] == 1     # one fetch, both callers told
    assert key not in runner._chain_inflight
    # a cancelled owner settles its waiter; the NEXT request is a fresh fetch that succeeds
    started.clear(); finish.clear()
    owner2 = asyncio.create_task(runner._cached_chain_call(key, fetch, ttl_s=900, max_age_s=14400))
    await started.wait()
    waiter2 = asyncio.create_task(runner._cached_chain_call(key, fetch, ttl_s=900, max_age_s=14400))
    await asyncio.sleep(0)
    owner2.cancel()
    await asyncio.gather(owner2, return_exceptions=True)
    await asyncio.sleep(0)
    assert waiter2.done() and isinstance((await asyncio.gather(waiter2, return_exceptions=True))[0], RuntimeError)
    assert key not in runner._chain_inflight
    finish.set()
    rows, meta = await runner._cached_chain_call(key, fetch, ttl_s=900, max_age_s=14400)
    assert rows == ["listing", "again"] and meta["listingSource"] == "fetch" and calls["n"] == 3


async def test_a_hung_provider_times_out_and_is_retried_within_bounds(monkeypatch):
    import zargar.techniques.team2.runner as module
    monkeypatch.setattr(module.Team2Runner, "_CHAIN_TIMEOUT_S", 0.05)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(module.asyncio, "sleep", lambda s: real_sleep(0) if s >= 0.5 else real_sleep(s))
    runner, _ = _runner()
    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        if calls["n"] < 3:
            await real_sleep(10)                                    # hangs: the bounded timeout cuts it
        return ["late"]
    key = ("provider", "SPY", "2026-09-14")
    rows, meta = await runner._cached_chain_call(key, fetch, ttl_s=900, max_age_s=14400)
    assert rows == ["late"] and meta["listingSource"] == "retry" and meta["listingAttempts"] == 3 and calls["n"] == 3
    # three hangs in a row surface as a timeout (no stale listing for this key); the stale rule is judged at return time
    calls["n"] = -10
    key2 = ("provider", "QQQ", "2026-09-14")
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await runner._cached_chain_call(key2, fetch, ttl_s=900, max_age_s=14400)
    assert key2 not in runner._chain_inflight

