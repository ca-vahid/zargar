"""executable_cost_v2 (2026-09-22): cost ranking bounded to the reviewed delta window.

Live Practice arms of 2026-09-22 under executable_cost_v1 moved to deep in-the-money contracts
(NOW 60C on a ~$140 stock; NVT 110C on ~$160; NTNX 60C on ~$70) because friction as a percent of
the debit always favours expensive contracts. The quotes below are SYNTHETIC books that reproduce
that ordering; they are not recorded prices.
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from zargar.options.occ import Occ
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy, planning_contract
from zargar.techniques.options_cartel.contracts import (
    ContractSelectionInput,
    SelectionEconomics,
    in_delta_band,
    rank_candidates,
)

from .test_options_cartel_entry import OPEN, plan

ECON = SelectionEconomics(cash_cap_usd=25000., max_units=10, entry_fee_per_contract_usd=1.04, exit_fee_per_contract_usd=1.04)


def policy(version, **changes):
    return ContractSelectionInput(**{"dte_min": 10, "dte_max": 60, "target_dte": 24, "target_abs_delta": .5,
                                     "max_ask": 250, "max_spread_pct": 20, "ranking_version": version, **changes})


def row(symbol, bid, ask, delta):
    return {"symbol": symbol, "bid": bid, "ask": ask, "delta": delta, "quoteAsOf": OPEN, "deltaAsOf": OPEN,
            "quoteSource": "opra", "openInterest": 500, "askSize": 50}


DEEP = row("HOOD260529C00030000", 19.6, 20.0, .97)      # deep ITM: 2.0% friction of debit
NEAR = row("HOOD260529C00050000", 1.95, 2.10, .52)      # near the money: 7.6% friction of debit
NEAR_CHEAP = row("HOOD260529C00049000", 2.40, 2.50, .58)  # in band, lower friction than NEAR
OTM = row("HOOD260529C00060000", .40, .44, .26)         # below the band


def test_v1_prefers_the_deep_itm_contract_that_v2_refuses_to_promote():
    rows = [DEEP, NEAR, OTM]
    v1 = rank_candidates(plan(), policy("executable_cost_v1"), rows, OPEN, economics=ECON)
    assert v1["selected"]["symbol"] == DEEP["symbol"]
    v2 = rank_candidates(plan(), policy("executable_cost_v2"), rows, OPEN, economics=ECON)
    assert v2["selected"]["symbol"] == NEAR["symbol"] and v2["selected"]["rankKey"]["inDeltaBand"] is True
    assert [c["symbol"] for c in v2["candidates"]][1:] == [DEEP["symbol"], OTM["symbol"]] or \
        {c["symbol"] for c in v2["candidates"][1:]} == {DEEP["symbol"], OTM["symbol"]}
    assert "delta window |delta| 0.35-0.65" in v2["ranking"]


def test_v2_uses_cost_inside_the_band():
    v2 = rank_candidates(plan(), policy("executable_cost_v2"), [DEEP, NEAR, NEAR_CHEAP], OPEN, economics=ECON)
    assert v2["selected"]["symbol"] == NEAR_CHEAP["symbol"]


def test_v2_falls_back_to_legacy_order_when_nothing_is_in_the_band():
    v2 = rank_candidates(plan(), policy("executable_cost_v2"), [DEEP, OTM], OPEN, economics=ECON)
    legacy = rank_candidates(plan(), policy("legacy"), [DEEP, OTM], OPEN, economics=ECON)
    assert v2["selected"]["symbol"] == legacy["selected"]["symbol"]


def test_band_is_configurable_and_bounded():
    assert in_delta_band(.64, policy("executable_cost_v2")) and not in_delta_band(.66, policy("executable_cost_v2"))
    assert in_delta_band(.97, policy("executable_cost_v2", cost_delta_band=.5))
    with pytest.raises(ValueError):
        policy("executable_cost_v2", cost_delta_band=.01)
    saved = ContractSelectionInput.model_validate({"dteMin": 21, "dteMax": 90, "targetDte": 45, "targetAbsDelta": .5,
                                                   "maxAsk": 250, "maxSpreadPct": 20, "rankingVersion": "executable_cost_v1"})
    assert saved.cost_delta_band == .15   # existing saved policies validate unchanged


async def test_planning_path_keeps_the_near_the_money_contract_under_v2():
    first = dt.date(2026, 9, 8)
    expiry = first+dt.timedelta(days=45)
    deep, near = Occ('TEST', expiry, 'C', 60).symbol, Occ('TEST', expiry, 'C', 140).symbol

    class Provider:
        async def expirations(self, symbol):
            return [expiry.isoformat()]

        async def chain(self, symbol, date):
            return [{'symbol': deep, 'bid': 79.5, 'ask': 80.0, 'greeks': {'delta': .98}, 'open_interest': 200},
                    {'symbol': near, 'bid': 6.4, 'ask': 6.8, 'greeks': {'delta': .52}, 'open_interest': 200}]
    engine = SimpleNamespace(options=SimpleNamespace(provider=lambda: Provider()), settings={})
    target = SimpleNamespace(symbol='TEST', direction='long', first_session=first)
    base = PreparationPolicy().contract_policy.model_copy(update={'max_ask': 250.})
    v1 = await planning_contract(engine, target, base.model_copy(update={'ranking_version': 'executable_cost_v1'}))
    assert v1['selected']['symbol'] == deep
    v2 = await planning_contract(engine, target, base.model_copy(update={'ranking_version': 'executable_cost_v2'}))
    assert v2['selected']['symbol'] == near and 'executable_cost_v2' in v2['audit']['ranking']
