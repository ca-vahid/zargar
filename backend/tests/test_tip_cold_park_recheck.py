"""Cold-park fast path (2026-09-19): a tip parked ONLY for a cold ticker re-runs the ordinary recovery sweep as soon as
its quote is warm - never on a price-position park, never without a real quote, never two sweeps at once."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.signals.service import SignalService

COLD = {"checks": [{"name": "quote_grounding", "passed": True}, {"name": "ticker_resolves", "passed": False}]}
PRICE = {"checks": [{"name": "ticker_resolves", "passed": True}, {"name": "price_deviation", "passed": False}]}
MIXED = {"checks": [{"name": "ticker_resolves", "passed": False}, {"name": "not_past_target", "passed": False}]}


def _svc(quotes: dict, *, wait=5):
    eng = NS(settings={"signals.cold_park_recheck_seconds": wait}, quotes=NS(get=lambda s: quotes.get(s)),
             ensure_symbol=AsyncMock(), journal=NS(append=AsyncMock()))
    svc = NS(engine=eng, recovery_sweep=AsyncMock(return_value={}))
    svc.cold_only_park = SignalService.cold_only_park
    svc._cold_park_recheck = lambda *a: SignalService._cold_park_recheck(svc, *a)
    return svc


def test_only_a_cold_ticker_park_qualifies():
    assert SignalService.cold_only_park(COLD) is True
    assert SignalService.cold_only_park(PRICE) is False          # a price-position park is the level watch's job
    assert SignalService.cold_only_park(MIXED) is False
    assert SignalService.cold_only_park({"checks": []}) is False and SignalService.cold_only_park(None) is False


async def test_recheck_waits_for_a_real_quote_then_sweeps_once(monkeypatch):
    quotes: dict = {}
    svc = _svc(quotes)
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 2:
            quotes["SBLK"] = NS(last=31.9)                      # the feed warms on the third look
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    assert await SignalService._cold_park_recheck(svc, "sig-1", "sblk", 5) is True
    svc.engine.ensure_symbol.assert_awaited_once_with("SBLK")
    svc.recovery_sweep.assert_awaited_once()
    assert svc.engine.journal.append.await_args.args[1] == {"signalId": "sig-1", "ticker": "SBLK", "waitedS": 2.0}


async def test_no_quote_inside_the_bound_means_no_sweep(monkeypatch):
    svc = _svc({})

    async def fake_sleep(_s):
        return None
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    assert await SignalService._cold_park_recheck(svc, "sig-1", "SBLK", 3) is False
    svc.recovery_sweep.assert_not_awaited()                     # the periodic sweep still owns the signal
    assert await SignalService._cold_park_recheck(_svc({"SBLK": NS(last=0.0)}), "sig-1", "SBLK", 2) is False   # a zero print is not a quote


async def test_spawn_respects_the_park_kind_and_the_off_switch():
    svc = _svc({"SBLK": NS(last=31.9)})
    SignalService._spawn_cold_park_recheck(svc, "sig-1", "SBLK", PRICE)
    assert not svc.__dict__.get("_cold_park_tasks")
    off = _svc({"SBLK": NS(last=31.9)}, wait=0)
    SignalService._spawn_cold_park_recheck(off, "sig-1", "SBLK", COLD)
    assert not off.__dict__.get("_cold_park_tasks")
    SignalService._spawn_cold_park_recheck(svc, "sig-1", "SBLK", COLD)
    await asyncio.gather(*list(svc.__dict__["_cold_park_tasks"]))
    svc.recovery_sweep.assert_awaited_once()


async def test_two_sweeps_never_run_at_once():
    running, peak = 0, 0

    async def locked():
        nonlocal running, peak
        running += 1; peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return {}
    svc = NS(_recovery_sweep_locked=locked)
    await asyncio.gather(SignalService.recovery_sweep(svc), SignalService.recovery_sweep(svc), SignalService.recovery_sweep(svc))
    assert peak == 1
