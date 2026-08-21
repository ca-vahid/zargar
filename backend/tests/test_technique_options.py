"""Options providers and T5 contract selection.

CBOE is the default provider (free, no credentials, reachable from Canada);
these tests exercise the OCC parsing, normalization, expiry choice, and the
just-OTM pick with T5 warnings against a stubbed CBOE payload — no network.
"""
import datetime as dt
import json

import httpx
import pytest

from zargar.technique.options import (
    CboeClient,
    OptionsError,
    choose_expiry,
    parse_occ,
    pick_for_setup,
    select_contract,
)


# --- OCC symbology --------------------------------------------------------------

def test_parse_occ_basic():
    assert parse_occ("SPY260821C00360000") == ("SPY", "2026-08-21", "call", 360.0)
    assert parse_occ("SPY261218P00765500") == ("SPY", "2026-12-18", "put", 765.5)


def test_parse_occ_weekly_root_and_garbage():
    assert parse_occ("SPXW260821C05000000") == ("SPXW", "2026-08-21", "call", 5000.0)
    assert parse_occ("not-an-occ") is None
    assert parse_occ("") is None


# --- choose_expiry (T5.2) --------------------------------------------------------

def test_choose_expiry_prefers_0dte():
    today = dt.date(2026, 8, 21)   # a Friday
    exp, zero = choose_expiry(["2026-08-21", "2026-08-24", "2026-08-28"], today)
    assert exp == "2026-08-21" and zero is True


def test_choose_expiry_this_weeks_friday():
    today = dt.date(2026, 8, 19)   # Wednesday
    exp, zero = choose_expiry(["2026-08-20", "2026-08-21", "2026-08-28"], today)
    assert exp == "2026-08-21" and zero is False


def test_choose_expiry_falls_through_to_next():
    today = dt.date(2026, 8, 19)
    exp, zero = choose_expiry(["2026-08-28", "2026-09-18"], today)
    assert exp == "2026-08-28" and zero is False
    assert choose_expiry([], today) == (None, False)
    assert choose_expiry(["garbage"], today) == (None, False)


# --- CBOE provider (stubbed transport) --------------------------------------------

def _cboe_row(occ, bid, ask, vol, oi, delta, theta, iv):
    return {"option": occ, "bid": bid, "ask": ask, "volume": vol, "open_interest": oi,
            "delta": delta, "theta": theta, "iv": iv, "gamma": 0.1, "vega": 0.2}


def _cboe_payload():
    return {"data": {
        "current_price": 765.3,
        "close": 765.72,
        "options": [
            _cboe_row("SPY260821C00764000", 2.10, 2.16, 5000, 9000, 0.61, -0.4, 0.14),
            _cboe_row("SPY260821C00766000", 1.05, 1.09, 8000, 12000, 0.45, -0.38, 0.13),
            _cboe_row("SPY260821C00768000", 0.48, 0.52, 6000, 15000, 0.30, -0.30, 0.13),
            _cboe_row("SPY260821P00764000", 1.20, 1.26, 4000, 8000, -0.40, -0.35, 0.14),
            _cboe_row("SPY260828C00766000", 3.30, 3.42, 900, 4000, 0.52, -0.22, 0.15),
            {"option": "BROKEN", "bid": 1},   # ignored, not OCC
        ],
    }}


def _stub_client(payload=None, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=payload or _cboe_payload())
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_cboe_expirations_and_chain_normalized():
    c = CboeClient(client=_stub_client())
    assert await c.expirations("SPY") == ["2026-08-21", "2026-08-28"]
    chain = await c.chain("SPY", "2026-08-21")
    assert len(chain) == 4                      # broken row dropped, other expiry excluded
    row = next(x for x in chain if x["strike"] == 766.0 and x["option_type"] == "call")
    assert row["greeks"]["delta"] == 0.45
    assert row["greeks"]["mid_iv"] == 0.13
    assert row["underlying"] == "SPY"
    assert await c.spot("SPY") == 765.3
    await c.aclose()


async def test_cboe_rejects_canadian_suffix_and_404():
    c = CboeClient(client=_stub_client())
    with pytest.raises(OptionsError, match="US options only"):
        await c.chain("SHOP.TO", "2026-08-21")
    c404 = CboeClient(client=_stub_client(status=404))
    with pytest.raises(OptionsError, match="404"):
        await c404.expirations("ZZZZ")
    await c.aclose()
    await c404.aclose()


async def test_cboe_caches_payload():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_cboe_payload())
    c = CboeClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await c.expirations("SPY")
    await c.chain("SPY", "2026-08-21")
    await c.spot("SPY")
    assert calls["n"] == 1
    await c.aclose()


# --- selection (T5.1 / T5.3 / T5.4) ------------------------------------------------

async def test_pick_for_setup_takes_first_otm_call():
    c = CboeClient(client=_stub_client())
    out = await pick_for_setup(c, "SPY", 765.3, "long", today=dt.date(2026, 8, 19))
    assert out["available"] and out["provider"] == "cboe"
    assert out["expiry"] == "2026-08-21"        # this week's Friday, not next
    assert out["strike"] == 766.0               # first strike above spot (T5.1)
    assert out["optionType"] == "call"
    assert out["delta"] == 0.45
    assert out["warnings"] == []                # liquid, tight, sane IV
    await c.aclose()


async def test_pick_for_setup_0dte_warns_reduced_size():
    c = CboeClient(client=_stub_client())
    out = await pick_for_setup(c, "SPY", 765.3, "long", today=dt.date(2026, 8, 21))
    assert out["is0dte"] is True
    assert any("0DTE" in w for w in out["warnings"])
    await c.aclose()


def test_select_contract_warnings_fire():
    chain = [{
        "symbol": "SPY260821C00766000", "underlying": "SPY", "expiry": "2026-08-21",
        "option_type": "call", "strike": 766.0, "bid": 0.10, "ask": 0.30,
        "volume": 2, "open_interest": 5,
        "greeks": {"delta": 0.10, "theta": -0.5, "mid_iv": 0.95},
    }]
    p = select_contract(chain, 765.3, "long", expiry="2026-08-21",
                        today=dt.date(2026, 8, 20), is_0dte=False)
    joined = " ".join(p.warnings)
    assert "wide spread" in joined
    assert "thin open interest" in joined
    assert "low volume" in joined
    assert "low delta" in joined
    assert "elevated IV" in joined
    assert "T5.3" in p.rules and "T5.4" in p.rules


def test_select_contract_put_side_and_no_otm():
    chain = [{"symbol": "X", "underlying": "SPY", "expiry": "2026-08-21",
              "option_type": "put", "strike": 764.0, "bid": 1.2, "ask": 1.26,
              "volume": 500, "open_interest": 800, "greeks": {"delta": -0.4, "theta": -0.3, "mid_iv": 0.2}}]
    p = select_contract(chain, 765.3, "short", expiry="2026-08-21",
                        today=dt.date(2026, 8, 20), is_0dte=False)
    assert p is not None and p.option_type == "put" and p.strike == 764.0
    # no put below spot → nothing just-OTM for a short
    assert select_contract(chain, 700.0, "short", expiry="2026-08-21",
                           today=dt.date(2026, 8, 20), is_0dte=False) is None


async def test_pick_for_setup_reports_provider_errors():
    c = CboeClient(client=_stub_client(status=500))
    out = await pick_for_setup(c, "SPY", 765.3, "long")
    assert out["available"] is False and "CBOE HTTP 500" in out["error"]
    await c.aclose()
