"""Tip expression (BUILD-PLAN T1): the vehicle rule, the DTE-window expiry
chooser, and contract picks — stated strike verbatim, just-OTM otherwise,
short-put mirror. Pure + fake chain client, no network."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from zargar.options import occ as occ_mod
from zargar.techniques.tip.express import (
    choose_expiry_window,
    pick_tip_contract,
    tip_is_option,
)

TODAY = dt.date(2026, 8, 27)
EXP3 = (TODAY + dt.timedelta(days=3)).isoformat()
EXP14 = (TODAY + dt.timedelta(days=14)).isoformat()
EXP45 = (TODAY + dt.timedelta(days=45)).isoformat()


def row(strike: float, opt: str = "call", expiry: str = EXP14, *, bid=1.05, ask=1.15,
        vol=600, oi=800, delta=0.4, iv=0.35, underlying="TEST"):
    sym = occ_mod.make(underlying, expiry, "C" if opt == "call" else "P", strike).symbol
    return {"symbol": sym, "underlying": underlying, "expiry": expiry, "option_type": opt,
            "strike": strike, "bid": bid, "ask": ask, "last": (bid + ask) / 2,
            "volume": vol, "open_interest": oi,
            "greeks": {"delta": delta if opt == "call" else -delta, "gamma": 0.01,
                       "theta": -0.04, "vega": 0.1, "mid_iv": iv}}


class FakeChain:
    """Provider-shaped mock (expirations/chain/spot/all_rows)."""
    name = "fake"
    delayed = True

    def __init__(self, spot=100.0, expiries=(EXP3, EXP14, EXP45), rows=None):
        self._spot = spot
        self._exp = list(expiries)
        self._rows = rows if rows is not None else [
            row(99.0), row(101.0), row(103.0),
            row(99.0, "put"), row(97.0, "put"), row(95.0, "put"),
        ]

    @property
    def available(self):
        return True

    async def expirations(self, symbol):
        return list(self._exp)

    async def chain(self, symbol, expiry):
        return [r for r in self._rows if r["expiry"] == expiry]

    async def all_rows(self, symbol):
        return list(self._rows)

    async def spot(self, symbol):
        return self._spot

    async def aclose(self):
        return None


def fake_engine(client: FakeChain):
    return SimpleNamespace(
        options=SimpleNamespace(provider=lambda: client),
        quotes=SimpleNamespace(get=lambda s: None),
    )


# --- the vehicle rule -------------------------------------------------------------

def test_vehicle_rule():
    S = SimpleNamespace
    assert tip_is_option(S(instrument="call", strike=None, expiry=None, dte_hint_days=None))
    assert tip_is_option(S(instrument="put", strike=None, expiry=None, dte_hint_days=None))
    assert tip_is_option(S(instrument="unspecified", strike=180.0, expiry=None, dte_hint_days=None))
    assert tip_is_option(S(instrument="unspecified", strike=None, expiry="2026-09-19", dte_hint_days=None))
    assert tip_is_option(S(instrument="either", strike=None, expiry=None, dte_hint_days=7))
    assert not tip_is_option(S(instrument="shares", strike=180.0, expiry=None, dte_hint_days=None))
    assert not tip_is_option(S(instrument="unspecified", strike=None, expiry=None, dte_hint_days=None))


# --- expiry window ----------------------------------------------------------------

def test_stated_expiry_wins_when_listed():
    exp, warns = choose_expiry_window([EXP3, EXP14, EXP45], TODAY, dte_min=10, dte_max=30,
                                      stated=EXP14)
    assert exp == EXP14 and warns == []


def test_stated_expiry_past_is_fatal():
    exp, warns = choose_expiry_window([EXP14], TODAY, dte_min=10, dte_max=30,
                                      stated="2026-08-20")
    assert exp is None and "passed" in warns[0]


def test_window_pick_prefers_first_inside():
    exp, warns = choose_expiry_window([EXP3, EXP14, EXP45], TODAY, dte_min=10, dte_max=30)
    assert exp == EXP14 and warns == []


def test_only_far_expiry_warns():
    exp, warns = choose_expiry_window([EXP45], TODAY, dte_min=10, dte_max=30)
    assert exp == EXP45 and "no expiry inside" in warns[0]


def test_only_short_expiry_is_fatal():
    exp, warns = choose_expiry_window([EXP3], TODAY, dte_min=10, dte_max=30)
    assert exp is None and "outlives the chain" in warns[0]


# --- contract picks ---------------------------------------------------------------

async def test_stated_strike_is_used_verbatim():
    eng = fake_engine(FakeChain())
    pick = await pick_tip_contract(eng, symbol="TEST", direction="long",
                                   dte_min=10, dte_max=30, strike=101.0, expiry=EXP14,
                                   today=TODAY)
    assert pick["available"] and pick["statedContract"]
    assert pick["strike"] == 101.0 and pick["expiry"] == EXP14
    assert pick["symbol"] == occ_mod.make("TEST", EXP14, "C", 101.0).symbol


async def test_missing_stated_strike_falls_to_otm_with_warning():
    eng = fake_engine(FakeChain())
    pick = await pick_tip_contract(eng, symbol="TEST", direction="long",
                                   dte_min=10, dte_max=30, strike=102.0, expiry=EXP14,
                                   today=TODAY)
    assert pick["available"] and not pick.get("statedContract")
    assert pick["strike"] == 101.0            # first strike just OTM of spot 100
    assert any("not listed" in w for w in pick["warnings"])


async def test_short_tip_picks_put_with_min_strike_mirror():
    eng = fake_engine(FakeChain())
    pick = await pick_tip_contract(eng, symbol="TEST", direction="short",
                                   dte_min=10, dte_max=30, min_strike=96.0, today=TODAY)
    assert pick["available"] and pick["optionType"] == "put"
    assert pick["strike"] >= 96.0             # never struck below the downside target


async def test_no_chain_is_a_soft_error():
    class Dead(FakeChain):
        async def expirations(self, symbol):
            from zargar.options.chain import OptionsError
            raise OptionsError("no US-listed options for TEST.TO (CBOE 404)")
    pick = await pick_tip_contract(fake_engine(Dead()), symbol="TEST.TO", direction="long",
                                   dte_min=10, dte_max=30, today=TODAY)
    assert not pick["available"] and "CBOE 404" in pick["error"]
