"""Codex audit finding 6 / 1b: the analyst's evidence tools — exact-contract
lookup, timestamped OHLCV, quote provenance, honest completeness flags."""
import datetime as dt

import pytest

from zargar.domain import Bar, Quote
from zargar.engine import Engine
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip.analyst import _compact_bars, _compact_chain, _run_tool

from .conftest import make_test_config, wait_for
from .test_tip_express import FakeChain as _FakeChain, row as chain_row


class FakeChain(_FakeChain):
    async def underlying_quote(self, symbol):
        return {"spot": self._spot}


def _bars(n=30, base=100.0):
    return [Bar(symbol="T", tf="1h", ts=1757400000000 + i * 3600_000,
                open=base, high=base + 1, low=base - 1, close=base + 0.5,
                volume=1000 + i) for i in range(n)]


def test_compact_bars_are_timestamped_ohlcv_with_completeness():
    out = _compact_bars(_bars(30), sessions_requested=5)
    assert out["columns"] == ["ts(UTC)", "open", "high", "low", "close", "volume"]
    assert len(out["ohlcv"]) == 24 and out["bars"] == 30
    ts, o, h, l, c, v = out["ohlcv"][0]
    assert "-" in ts and ":" in ts and v >= 1000
    assert out["sessionsRequested"] == 5
    assert _compact_bars([])["complete"] is False


def test_compact_chain_reports_window_vs_total_and_centers_on_want():
    rows = [{"strike": float(k), "call": {"symbol": f"T{k}", "bid": 1, "ask": 1.1,
                                          "spreadPct": 9, "volume": 5,
                                          "openInterest": 10, "delta": 0.3}}
            for k in range(80, 140, 2)]                      # 30 strikes
    chain = {"underlying": "T", "expiry": "2026-10-16", "dte": 30,
             "spot": 100.0, "rows": rows}
    out = _compact_chain(chain)
    assert out["strikesShown"] == 9 and out["strikesTotal"] == 30
    assert "NOT proof" in out["note"]
    far = _compact_chain(chain, want=132.0)
    strikes = [r["strike"] for r in far["strikes"]]
    assert 132.0 in strikes                                  # window centered on want


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def test_get_chain_exact_contract_lookup(rig):
    exp = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    fake = FakeChain(spot=100.0, expiries=(exp,),
                     rows=[chain_row(105.0, "call", expiry=exp),
                           chain_row(99.0, "put", expiry=exp)])
    rig.options.use_client(fake)
    from zargar.options import occ as occ_mod
    occ_sym = occ_mod.make("TEST", exp, "C", 105.0).symbol
    out = await _run_tool(rig, "get_chain",
                          {"symbol": "TEST", "expiry": exp, "contract": occ_sym})
    assert out["found"] is True and out["strike"] == 105.0
    assert "bid" in out["row"] and "openInterest" in out["row"]
    # a contract absent from the chain: explicit, never "illiquid"
    missing = occ_mod.make("TEST", exp, "C", 250.0).symbol
    out2 = await _run_tool(rig, "get_chain",
                           {"symbol": "TEST", "expiry": exp, "contract": missing})
    assert out2["found"] is False and "NOT proof" in out2["note"]
    # garbage OCC: a clear error
    out3 = await _run_tool(rig, "get_chain",
                           {"symbol": "TEST", "expiry": exp, "contract": "NOT-AN-OCC"})
    assert "error" in out3


async def test_get_quote_carries_provenance(rig):
    rig.quotes.on_quote(Quote(symbol="PROV", bid=99.0, ask=101.0, last=100.0,
                              bid_size=10, ask_size=10))
    await wait_for(lambda: rig.quotes.get("PROV") is not None)
    out = await _run_tool(rig, "get_quote", {"symbol": "PROV"})
    assert "source" in out and "ageSeconds" in out and "delayed" in out
    assert out["ageSeconds"] is None or out["ageSeconds"] < 60
