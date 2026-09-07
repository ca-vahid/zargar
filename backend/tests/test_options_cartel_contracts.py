"""Contract eligibility, deterministic ranking, and honest bounded collection."""
import datetime as dt
from types import SimpleNamespace

import pytest

from zargar.domain import Quote
from zargar.techniques.options_cartel.contracts import (
    ContractSelectionInput,
    rank_candidates,
    select_contract,
)

from .test_options_cartel_entry import OPEN, plan


def policy(**changes):
    return ContractSelectionInput(**{"dte_min": 10, "dte_max": 60, "target_dte": 24,
                                      "target_abs_delta": .5, "max_ask": 3, "max_spread_pct": 15, **changes})


def row(symbol="HOOD260529C00050000", **changes):
    return {"symbol": symbol, "bid": 1, "ask": 1.1, "delta": .45, "quoteAsOf": OPEN,
            "deltaAsOf": OPEN, "quoteSource": "opra", "openInterest": 500, **changes}


def test_ranking_obeys_reviewed_expiry_then_delta_and_spread():
    result = rank_candidates(plan(), policy(), [row(), row("HOOD260529C00055000", delta=.5),
                                                row("HOOD260605C00055000", delta=.5)], OPEN)
    assert result["selected"]["symbol"] == "HOOD260529C00055000"
    assert not result["placesOrders"]


@pytest.mark.parametrize("changes", [{"quoteSource": "chain"}, {"quoteAsOf": OPEN-11000},
                                     {"deltaAsOf": OPEN-121000}, {"deltaAsOf": OPEN+1},
                                     {"ask": 4}, {"bid": 2}, {"delta": .2}, {"delta": -.5},
                                     {"delta": None}, {"ask": float("nan")}])
def test_unqualified_quotes_and_contracts_cannot_be_selected(changes):
    result = rank_candidates(plan(), policy(), [row(**changes)], OPEN)
    assert result["selected"] is None and result["candidates"][0]["reasons"]


def test_wrong_underlying_right_and_expiry_are_excluded():
    result = rank_candidates(plan(), policy(), [row("AAPL260529C00050000"), row("HOOD260529P00050000"),
                                                row("HOOD260508C00050000")], OPEN)
    assert result["candidates"] == []


def test_bearish_contract_uses_negative_delta_and_reviewed_liquidity():
    short = plan(direction="short", trigger=51.2, invalidation=51.68, targets=(45,))
    rows = [row("HOOD260529P00050000", delta=-.5)]
    assert rank_candidates(short, policy(), rows, OPEN)["selected"] is not None
    assert rank_candidates(short, policy(min_open_interest=1000), rows, OPEN)["selected"] is None


def test_duplicate_snapshots_and_invalid_preferences_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        rank_candidates(plan(), policy(), [row(), row()], OPEN)
    with pytest.raises(ValueError, match="reviewed ranges"):
        policy(target_dte=100)


async def test_collection_reports_search_bounds_and_uses_refreshed_observations():
    today = dt.datetime.now(dt.UTC).date()
    dates = [(today+dt.timedelta(days=20+i*7)).isoformat() for i in range(7)]
    cache, quotes = {}, {}

    class Provider:
        async def expirations(self, symbol):
            return dates

        async def chain(self, symbol, expiry):
            return [{"symbol": f"HOOD{dt.date.fromisoformat(expiry):%y%m%d}C00050000",
                     "greeks": {"delta": .5}, "open_interest": 500}]

    class Options:
        def provider(self):
            return Provider()

        async def reprice(self, contract):
            symbol = contract["symbol"]
            now = int(dt.datetime.now(dt.UTC).timestamp()*1000)
            cache[symbol] = {"greeks": {"delta": .5}, "greeksFieldAsOf": {"delta": now}}
            quotes[symbol] = Quote(symbol=symbol, bid=1, ask=1.1, last=1.05, source="opra", ts=now)

        def snapshot_cached(self, symbol):
            return cache.get(symbol)

    result = await select_contract(SimpleNamespace(options=Options(), quotes=SimpleNamespace(get=quotes.get)),
                                   plan(), policy(dte_max=90, refresh_limit=2))
    assert result["selected"] is not None
    assert len(result["searchedExpiries"]) == 6 and result["refreshedCandidates"] == 2
    assert result["searchComplete"] is False and result["warnings"]
