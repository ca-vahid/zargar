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

def test_choose_expiry_avoid_0dte_prefers_this_week():
    import datetime as _dt
    today = _dt.date(2026, 8, 21)                       # a Friday with 0DTE listed
    exp, zero = choose_expiry(["2026-08-21", "2026-08-28"], today, avoid_0dte=True)
    assert exp == "2026-08-28" and zero is False
    # no alternative -> still 0DTE rather than nothing
    exp, zero = choose_expiry(["2026-08-21"], today, avoid_0dte=True)
    assert exp == "2026-08-21" and zero is True


def test_select_contract_caps_strike_at_the_target():
    import datetime as _dt
    today = _dt.date(2026, 8, 20)
    chain = [
        {"symbol": "X1", "underlying": "X", "option_type": "call", "strike": 101.0, "bid": 1.0, "ask": 1.1,
         "volume": 500, "open_interest": 500, "greeks": {"delta": 0.45, "mid_iv": 0.3}},
        {"symbol": "X2", "underlying": "X", "option_type": "call", "strike": 106.0, "bid": 0.4, "ask": 0.5,
         "volume": 500, "open_interest": 500, "greeks": {"delta": 0.2, "mid_iv": 0.3}},
    ]
    # TP2 at 104: the 106 strike is beyond the target -> the 101 one wins
    pick = select_contract(chain, 100.5, "long", expiry="2026-08-21", today=today, is_0dte=False, max_strike=104.0)
    assert pick and pick.strike == 101.0 and not any("target cap" in w for w in pick.warnings)
    # spot above every capped strike: falls back to nearest OTM with a warning
    pick = select_contract(chain, 105.0, "long", expiry="2026-08-21", today=today, is_0dte=False, max_strike=104.0)
    assert pick and pick.strike == 106.0 and any("target cap" in w for w in pick.warnings)


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


def test_rejudge_spread_uses_the_nbbo_after_reprice():
    from zargar.technique.options import rejudge_spread
    # chain said wide (delayed row); the NBBO is tight -> the T5.4 warning goes away
    c = {"symbol": "X", "warnings": ["T5.4 wide spread 16.5% (bid 1.0 / ask 1.18)", "T5.2 0DTE: use reduced size"],
         "bid": 1.10, "ask": 1.12, "spreadPct": 1.8, "priced": "opra"}
    rejudge_spread(c)
    assert c["spreadJudgedOn"] == "opra" and c["warnings"] == ["T5.2 0DTE: use reduced size"]
    # chain said fine; the NBBO is wide -> the warning is added on the live numbers
    c = {"symbol": "X", "warnings": [], "bid": 0.10, "ask": 0.20, "spreadPct": 66.7, "priced": "opra"}
    rejudge_spread(c)
    assert any("T5.4 wide spread" in w and "NBBO" in w for w in c["warnings"])
    # no real-time print: the chain's verdict stands, flagged as such
    c = {"symbol": "X", "warnings": ["T5.4 wide spread 16.5% (bid 1.0 / ask 1.18)"], "spreadPct": 16.5, "priced": "chain"}
    rejudge_spread(c)
    assert c["spreadJudgedOn"] == "chain" and len(c["warnings"]) == 1


def test_implied_vol_round_trips_and_rejudge_iv_uses_the_live_mid():
    import datetime as dt
    from zargar.technique.options import ET, bs_price, implied_vol, rejudge_iv
    px = bs_price(100.0, 100.0, 0.25, 0.20, call=True)
    assert abs(implied_vol(px, 100.0, 100.0, 0.25, call=True) - 0.20) < 1e-3
    px = bs_price(100.0, 95.0, 0.1, 0.45, call=False)
    assert abs(implied_vol(px, 100.0, 95.0, 0.1, call=False) - 0.45) < 1e-3
    assert implied_vol(0.0, 100.0, 100.0, 0.25, call=True) is None
    now = dt.datetime(2026, 9, 2, 10, 0, tzinfo=ET)
    t_years = (dt.datetime(2026, 9, 11, 16, 0, tzinfo=ET) - now).total_seconds() / (365 * 24 * 3600)
    # chain said elevated (stale); the live mid implies 25% -> warning dropped, chain IV kept aside
    c = {"symbol": "X", "strike": 100.0, "expiry": "2026-09-11", "optionType": "call", "iv": 0.75,
         "warnings": ["T5.3 elevated IV 0.75 — IV-crush risk"], "priced": "opra",
         "mid": round(bs_price(100.0, 100.0, t_years, 0.25, call=True), 4)}
    rejudge_iv(c, spot=100.0, now=now)
    assert c["ivJudgedOn"] == "opra" and c["ivChain"] == 0.75 and abs(c["iv"] - 0.25) < 0.01
    assert not any("T5.3" in w for w in c["warnings"])
    # chain said calm; the live mid implies 90% -> warning added on the live figure
    c = {"symbol": "X", "strike": 100.0, "expiry": "2026-09-11", "optionType": "put", "iv": 0.30, "warnings": [],
         "priced": "opra", "mid": round(bs_price(100.0, 100.0, t_years, 0.90, call=False), 4)}
    rejudge_iv(c, spot=100.0, now=now)
    assert any("T5.3 elevated IV" in w and "NBBO" in w for w in c["warnings"]) and abs(c["iv"] - 0.90) < 0.01
    # not priced live: chain verdict stands
    c = {"symbol": "X", "iv": 0.75, "warnings": ["T5.3 elevated IV 0.75 — IV-crush risk"], "priced": "chain"}
    rejudge_iv(c, spot=100.0, now=now)
    assert c["ivJudgedOn"] == "chain" and c["iv"] == 0.75
