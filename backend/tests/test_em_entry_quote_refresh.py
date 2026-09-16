"""entry-quote-refresh-v1 (2026-09-15): one BOUNDED provider refresh of the contract NBBO after the analysis and
immediately before final pricing/sizing. Corrected finding: the three 09-15 refusals ("quote age 10.9-14.5 s") came
from the RiskGate's freshness check on a quote nobody re-fetched after the 18-23 s analysis; `reprice()` returns the
cached quote for an already-served contract. The refresh never relaxes a check: timed-out, failed, delayed or
still-stale refreshes leave the contract as it was and the existing checks refuse. No DB, no engine, no orders."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from zargar.domain import Quote
from zargar.execution.entry_quality import judge_entry_quote
from zargar.execution.planrunner import ArmConfig, ArmedPlan, PlanRunner, Trade

NOW = 1_800_000_000_000
SYM = "X260918C00101000"


class Quotes(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)

    def source_age_seconds(self, k):
        q = self.get(k)
        if q is None:
            return float("inf")
        return max(0.0, time.time() - (q.source_ts or q.ts) / 1000)


def quote(age_s: float, bid=1.9, ask=2.0, delayed=False, source="opra"):
    ts = int((time.time() - age_s) * 1000)
    # a delayed chain row is badged by its source ("chain"); Quote has no `delayed` field (the gate reads it via getattr)
    return Quote(SYM, bid=bid, ask=ask, last=(bid + ask) / 2, bid_size=40, ask_size=40, ts=ts, source=("chain" if delayed else source), source_ts=ts)


def rig(settings, refresh):
    quotes = Quotes({SYM: quote(13.0)})                                   # the pick's quote is 13 s old by now
    engine = SimpleNamespace(settings=settings, quotes=quotes, journal=SimpleNamespace(append=AsyncMock()),
                             options=SimpleNamespace(refresh_now=refresh))
    r = PlanRunner(engine); r._log = Mock()
    ap = ArmedPlan(run_id="qr", symbol="X", plan={}, plan_for="2026-09-16",
                   config=ArmConfig(portfolio_id="p", mode="auto", instrument="options"), trackers={}, armed_at=0)
    tr = Trade(trigger_id="b1", kind="bounce", fired_ts=NOW, window="prime_open", entry=100.0, stop=99.0, targets=[101.0, 102.0, 103.0],
               instrument="options", order_symbol=SYM)
    return r, ap, tr, quotes


def test_knob_off_by_default_leaves_the_entry_chain_unchanged():
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS["execution.entry_quote_refresh_timeout_s"] == 0.0 and DEFAULTS["techniques.enhanced_market.entry_quote_refresh_timeout_s"] == 2.5
    refresh = AsyncMock()
    r, ap, tr, _ = rig({}, refresh)
    out = asyncio.run(r._refresh_entry_quote(ap, tr, {"symbol": SYM, "bid": 1.8, "ask": 1.9}))
    assert out["attempted"] is False and out["ok"] is False and out["why"] == "off" and refresh.await_count == 0


def test_a_fresh_refresh_advances_the_quote_and_the_checks_run_on_it():
    async def refresh(sym):
        quotes[sym] = quote(0.5, bid=1.95, ask=2.05); return quotes[sym]
    r, ap, tr, quotes = rig({"execution.entry_quote_refresh_timeout_s": 2.5, "risk.stale_quote_seconds": 10}, refresh)
    contract = {"symbol": SYM, "bid": 1.8, "ask": 1.9}
    assert judge_entry_quote(contract, quotes.get(SYM), max_spread_pct=10.0, max_age_s=10.0, refuse_wide=True, now_ms=int(time.time() * 1000), require_current=True)  # stale before
    out = asyncio.run(r._refresh_entry_quote(ap, tr, contract))
    assert out["attempted"] and out["ok"] and out["ageBeforeS"] >= 12 and out["ageAfterS"] < 2 and out["askAfter"] == 2.05 and out["elapsedMs"] >= 0
    # the same final guard now passes on the CURRENT quote; the RiskGate reads the same cache (age < 10 s)
    assert judge_entry_quote({**contract, "bid": 1.95, "ask": 2.05}, quotes.get(SYM), max_spread_pct=10.0, max_age_s=10.0, refuse_wide=True,
                             now_ms=int(time.time() * 1000), require_current=True) is None
    assert quotes.source_age_seconds(SYM) < 10


def test_timeout_failure_delayed_and_still_stale_refreshes_never_relax_a_check():
    async def slow(sym):
        await asyncio.sleep(0.3); return quotes.get(sym)
    r, ap, tr, quotes = rig({"execution.entry_quote_refresh_timeout_s": 0.05, "risk.stale_quote_seconds": 10}, slow)
    out = asyncio.run(r._refresh_entry_quote(ap, tr, {"symbol": SYM, "bid": 1.8, "ask": 1.9}))
    assert out["attempted"] and not out["ok"] and "timed out" in out["why"]
    assert judge_entry_quote({"symbol": SYM, "bid": 1.8, "ask": 1.9}, quotes.get(SYM), max_spread_pct=10.0, max_age_s=10.0, refuse_wide=True,
                             now_ms=int(time.time() * 1000), require_current=True)              # still refused
    r, ap, tr, quotes = rig({"execution.entry_quote_refresh_timeout_s": 2.0}, AsyncMock(side_effect=RuntimeError("provider down")))
    out = asyncio.run(r._refresh_entry_quote(ap, tr, {"symbol": SYM}))
    assert not out["ok"] and "failed" in out["why"]

    async def still_stale(sym):
        return quotes.get(sym)                                            # provider answered but nothing advanced
    r, ap, tr, quotes = rig({"execution.entry_quote_refresh_timeout_s": 2.0, "risk.stale_quote_seconds": 10}, still_stale)
    out = asyncio.run(r._refresh_entry_quote(ap, tr, {"symbol": SYM}))
    assert not out["ok"] and "still stale" in out["why"]

    async def delayed(sym):
        quotes[sym] = quote(0.2, delayed=True, source="chain"); return quotes[sym]
    r, ap, tr, quotes = rig({"execution.entry_quote_refresh_timeout_s": 2.0, "risk.stale_quote_seconds": 10, "options.quotes_source": "alpaca"}, delayed)
    r._live_option_quotes_expected = lambda: True
    out = asyncio.run(r._refresh_entry_quote(ap, tr, {"symbol": SYM}))
    assert not out["ok"] and "delayed" in out["why"]

    async def crossed(sym):
        quotes[sym] = quote(0.2, bid=2.1, ask=2.0); return quotes[sym]
    r, ap, tr, quotes = rig({"execution.entry_quote_refresh_timeout_s": 2.0, "risk.stale_quote_seconds": 10}, crossed)
    out = asyncio.run(r._refresh_entry_quote(ap, tr, {"symbol": SYM}))
    assert not out["ok"] and "two-sided" in out["why"]


def test_refresh_is_bounded_and_diagnostic_travels_on_the_trade():
    async def refresh(sym):
        quotes[sym] = quote(0.1); return quotes[sym]
    r, ap, tr, quotes = rig({"execution.entry_quote_refresh_timeout_s": 2.5, "risk.stale_quote_seconds": 10}, refresh)
    t0 = time.monotonic(); out = asyncio.run(r._refresh_entry_quote(ap, tr, {"symbol": SYM, "bid": 1.8, "ask": 1.9}))
    assert time.monotonic() - t0 < 2.5 and out["version"] == "entry-quote-refresh-v1"
    tr.quote_refresh = out
    assert Trade.__dataclass_fields__["quote_refresh"].default is None and tr.quote_refresh["ok"]
