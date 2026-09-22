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


# --------------------------------------------------------------------------------------------
# 2026-09-21 brief F2 (diverse_liquidity_v1 refresh allocation) and F3 (executable_cost_v1).
# Chronology, quotes, expiries, open interest and candidate counts below follow the recorded
# NTNX/ULTA session; every delta/OI value that the record did NOT contain is labelled SYNTHETIC.
# --------------------------------------------------------------------------------------------
import asyncio

from zargar.techniques.options_cartel.contracts import (
    OI_BELOW_REASON,
    OI_UNKNOWN_REASON,
    SelectionEconomics,
    SelectionRequest,
    allocate_refresh,
    contract_economics,
)

SEP21_1030 = int(dt.datetime(2026, 9, 21, 10, 30, 36, tzinfo=dt.timezone(dt.timedelta(hours=-4))).timestamp()*1000)
OCT, NOV = "2026-10-16", "2026-11-20"
NTNX_OCT = "NTNX261016C00060000"
NOV_REAL_OI = {65: 0, 67.5: 10, 70: 26, 72.5: 1, 75: 0, 77.5: 0}   # recorded 2026-09-21 refreshed rows


def ntnx_plan():
    return plan(id="ntnx", symbol="NTNX", trigger=70.48, invalidation=69.555, targets=(71., 71.61, 72.42),
                first_session=dt.date(2026, 9, 21), last_session=dt.date(2026, 9, 21), created_at=SEP21_1030-3600000,
                baseline_as_of=SEP21_1030-3600000, rationale="Recorded 2026-09-21 NTNX plan geometry", source_refs=("2026-09-21-eod",))


def ntnx_policy(**changes):
    return ContractSelectionInput(**{"dte_min": 21, "dte_max": 90, "target_dte": 45, "target_abs_delta": .5, "min_abs_delta": .25,
                                     "max_ask": 249.9896, "max_spread_pct": 20, "min_open_interest": 100, "refresh_limit": 6, **changes})


class Rig:
    """Fake options service: chain rows with static OI/delta, refresh stamps fresh OPRA quotes."""

    def __init__(self, expiries, chain, quotes, *, greeks=None, clock=None, hang=(), fail=()):
        self.expiries, self.chain_rows, self.quote_book = expiries, chain, quotes
        self.greeks = greeks or {}
        self.clock = clock or (lambda: SEP21_1030)
        self.hang, self.fail = set(hang), set(fail)
        self.cache, self.quotes, self.refreshed = {}, {}, []
        self.chain_calls = []

    async def expirations(self, symbol):
        return self.expiries

    async def chain(self, symbol, expiry):
        self.chain_calls.append(expiry)
        if expiry in self.fail:
            raise OSError("chain down")
        return [r for r in self.chain_rows if r["expiry"] == expiry]

    def provider(self):
        return self

    async def reprice(self, contract):
        symbol = contract["symbol"]
        if symbol in self.hang:
            await asyncio.sleep(3600)
        if symbol in self.fail:
            raise OSError("refresh down")
        self.refreshed.append(symbol)
        now = self.clock()
        bid, ask, bid_size, ask_size = self.quote_book.get(symbol, (None, None, 0, 0))
        if bid is not None:
            self.quotes[symbol] = Quote(symbol=symbol, bid=bid, ask=ask, last=(bid+ask)/2, bid_size=bid_size,
                                        ask_size=ask_size, source="opra", source_ts=now, ts=now)
        chain_delta = next((r["greeks"]["delta"] for r in self.chain_rows if r["symbol"] == symbol), .5)
        delta = self.greeks.get(symbol, chain_delta)   # SYNTHETIC fresh Greek = the chain's static delta
        self.cache[symbol] = {"greeks": {"delta": delta}, "greeksFieldAsOf": {"delta": now}}

    def snapshot_cached(self, symbol):
        return self.cache.get(symbol)

    def engine(self):
        return SimpleNamespace(options=self, quotes=SimpleNamespace(get=self.quotes.get))


def ntnx_rig(**kw):
    """Two expiries / 47 structural calls as recorded; November OI as recorded for the six refreshed
    rows (other November OI SYNTHETIC low); October OI SYNTHETIC (the record has none)."""
    chain = []
    oct_strikes = [50+2.5*i for i in range(23)]        # 23 October calls (SYNTHETIC ladder)
    nov_strikes = [50+2.5*i for i in range(24)]        # 24 November calls (SYNTHETIC ladder)
    for k in oct_strikes:
        chain.append({"symbol": f"NTNX261016C{int(k*1000):08d}", "expiry": OCT, "greeks": {"delta": round(max(.05, min(.95, .5+(60-k)*.04)), 3)},
                      "open_interest": 400 if k == 60 else 150})   # SYNTHETIC OI
    for k in nov_strikes:
        chain.append({"symbol": f"NTNX261120C{int(k*1000):08d}", "expiry": NOV, "greeks": {"delta": round(max(.05, min(.95, .5+(70-k)*.04)), 3)},
                      "open_interest": NOV_REAL_OI.get(k, 5)})      # recorded for the six refreshed rows
    quotes = {NTNX_OCT: (9.80, 11.30, 401, 74),                    # recorded 10:30:33 OPRA book
              "NTNX261120C00070000": (4.50, 5.10, 20, 20), "NTNX261120C00067500": (5.50, 6.70, 20, 20),
              "NTNX261120C00065000": (7.00, 8.20, 20, 20), "NTNX261120C00072500": (3.40, 4.20, 20, 20),
              "NTNX261120C00075000": (2.65, 3.00, 20, 20), "NTNX261120C00077500": (1.40, 2.50, 20, 20)}
    for row_ in chain:
        quotes.setdefault(row_["symbol"], (1., 1.1, 20, 20))       # SYNTHETIC fresh quotes elsewhere
    return Rig([OCT, NOV], chain, quotes, **kw)   # October 60 call carries SYNTHETIC delta .50 (the reviewed target)


def econ(cap=25000., units=10, fee=1.04):
    return SelectionEconomics(cash_cap_usd=cap, max_units=units, entry_fee_per_contract_usd=fee, exit_fee_per_contract_usd=fee)


async def test_legacy_sampler_reproduces_ntnx_november_starvation():
    rig = ntnx_rig()
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(), SelectionRequest(preferred_contract=NTNX_OCT, clock=rig.clock))
    assert result["selectionVersion"] == "legacy" and result["structuralCandidates"] == 47
    assert result["searchedExpiries"] == [NOV, OCT] and result["refreshedCandidates"] == 6
    assert all(s.startswith("NTNX261120") for s in rig.refreshed) and NTNX_OCT not in rig.refreshed
    assert result["selected"] is None and result["searchComplete"] is False
    assert all(OI_BELOW_REASON in c["reasons"] for c in result["candidates"])
    assert result["preferredContract"]["considered"] is False


async def test_diverse_refresh_gives_the_reviewed_october_contract_first_consideration_and_represents_both_expiries():
    rig = ntnx_rig()
    policy = ntnx_policy(selection_version="diverse_liquidity_v1")
    request = SelectionRequest(preferred_contract=NTNX_OCT, deadline_ms=SEP21_1030+120000, economics=econ(),
                               plan_id="ntnx", portfolio_id="book", clock=rig.clock)
    result = await select_contract(rig.engine(), ntnx_plan(), policy, request)
    assert result["selectionVersion"] == "diverse_liquidity_v1"
    assert rig.refreshed[0] == NTNX_OCT
    # Six low-OI November rows cannot starve October: known OI failures are recorded, not refreshed.
    assert result["knownFailureCandidates"] == 24 and not any(s.startswith("NTNX261120") for s in rig.refreshed)
    assert result["byExpiry"][NOV]["knownFailures"] == 24 and result["byExpiry"][NOV]["refreshed"] == 0
    assert result["byExpiry"][OCT]["refreshed"] == 6
    assert result["selected"]["symbol"] == NTNX_OCT and result["preferredContract"]["status"] == "selected"
    assert result["selected"]["spreadPct"] == pytest.approx(14.218, abs=.001)
    assert result["selected"]["economics"]["spreadUsdPerContract"] == 150
    assert result["searchComplete"] is False   # 17 refreshable October rows remain unrefreshed in one batch
    assert result["unrefreshedCandidates"] == 17 and result["incompleteReasons"]
    recorded = [c for c in result["candidates"] if c["symbol"] == "NTNX261120C00070000"][0]
    assert recorded["refreshed"] is False and recorded["openInterest"] == 26 and OI_BELOW_REASON in recorded["reasons"]


def test_round_robin_allocation_alternates_expiries_deterministically():
    def item(sym, expiry, dist, tier, delta_dist):
        return {"symbol": sym, "expiry": expiry, "dte": 30, "dteDistance": dist, "deltaDistance": delta_dist,
                "openInterest": 500, "liquidity": {1: "known_ok", 2: "unknown", 3: "known_failure"}[tier], "tier": tier, "row": {}}
    structural = [item("A3", OCT, 20, 1, .3), item("A1", OCT, 20, 1, .1), item("A2", OCT, 20, 1, .2), item("AU", OCT, 20, 2, .0),
                  item("B2", NOV, 15, 1, .2), item("B1", NOV, 15, 1, .1), item("BX", NOV, 15, 3, .0)]
    first = allocate_refresh(structural, ntnx_policy(), None)
    assert [c["symbol"] for c in first["order"]] == ["B1", "A1", "B2", "A2", "A3", "AU"]
    assert [c["symbol"] for c in first["knownFailures"]] == ["BX"] and first["expiryOrder"] == [NOV, OCT]
    again = allocate_refresh(list(reversed(structural)), ntnx_policy(), None)
    assert [c["symbol"] for c in again["order"]] == [c["symbol"] for c in first["order"]]
    preferred = allocate_refresh(structural, ntnx_policy(), "A2")
    assert [c["symbol"] for c in preferred["order"]][:3] == ["A2", "B1", "A1"]


async def test_two_refreshable_expiries_share_a_six_request_budget():
    rig = ntnx_rig()
    for row_ in rig.chain_rows:
        row_["open_interest"] = 300    # SYNTHETIC: make November refreshable too
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(clock=rig.clock))
    assert len(rig.refreshed) == 6
    assert sum(s.startswith("NTNX261120") for s in rig.refreshed) == 3 and sum(s.startswith("NTNX261016") for s in rig.refreshed) == 3
    assert result["allocation"]["expiryOrder"] == [NOV, OCT] and result["allocation"]["order"][:6] == rig.refreshed


async def test_now_invalid_preferred_contract_receives_no_grandfathering():
    rig = ntnx_rig()
    rig.quote_book[NTNX_OCT] = (9.80, 14.80, 401, 74)   # SYNTHETIC wide book: 40.65% of mid
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=NTNX_OCT, clock=rig.clock))
    assert rig.refreshed[0] == NTNX_OCT
    assert result["preferredContract"]["status"] == "ineligible_after_refresh"
    assert "premium or spread exceeds reviewed limit" in result["preferredContract"]["reasons"]
    assert result["selected"] is not None and result["selected"]["symbol"] != NTNX_OCT


@pytest.mark.parametrize("bad", ["AAPL261016C00060000", "NTNX261016P00060000", "NTNX261002C00060000", "garbage"])
async def test_preferred_identity_failures_are_recorded_and_not_refreshed(bad):
    rig = ntnx_rig()
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=bad, clock=rig.clock))
    assert result["preferredContract"]["status"] == "identity_rejected" and bad not in rig.refreshed


async def test_preferred_plan_identity_mismatch_is_rejected():
    rig = ntnx_rig()
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=NTNX_OCT, plan_id="another-plan", clock=rig.clock))
    # No special consideration: the contract is at most an ordinary chain candidate in its expiry's queue.
    assert result["preferredContract"]["identity"]["planIdOk"] is False and result["preferredContract"]["status"] == "identity_rejected"
    assert result["preferredContract"]["considered"] is False
    assert all(c["preferred"] is False for c in result["candidates"] if c.get("refreshed"))


async def test_missing_open_interest_is_unknown_not_zero_and_ranks_after_known_liquidity():
    rig = ntnx_rig()
    for row_ in rig.chain_rows:
        row_["open_interest"] = 300 if row_["expiry"] == NOV else None   # SYNTHETIC: October OI missing
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(clock=rig.clock))
    assert result["byExpiry"][OCT]["unknownLiquidity"] == 23 and result["byExpiry"][OCT]["knownFailures"] == 0
    october = [c for c in result["candidates"] if c["expiry"] == OCT and c["refreshed"]]
    assert october and all(OI_UNKNOWN_REASON in c["reasons"] and c["openInterestSource"] == "missing" for c in october)
    assert result["selected"]["expiry"] == NOV


async def test_refresh_timeout_and_deadline_make_the_search_incomplete_not_empty():
    hang = NTNX_OCT
    rig = ntnx_rig()
    clock = [SEP21_1030]
    rig.clock = lambda: clock[0]
    original = rig.reprice

    async def reprice(contract):
        if contract["symbol"] == hang:
            clock[0] += 1500      # the hung request consumes the remaining deadline
            raise TimeoutError
        return await original(contract)
    rig.reprice = reprice
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=hang, deadline_ms=SEP21_1030+1000, clock=rig.clock))
    # The hung refresh consumed the deadline: the search is EXPIRED (a deadline is never extended).
    assert result["searchComplete"] is False and result["searchStatus"] == "expired" and result["expiredSelection"] is True
    assert result["batches"][0]["timedOut"] == 1 and result["batches"][0]["requested"] == 1
    assert any("deadline reached" in r for r in result["incompleteReasons"])
    assert result["selected"] is None and result["unrefreshedCandidates"] == 22
    assert "not proof that no option qualifies" in result["note"]


async def test_real_refresh_timeout_is_bounded_by_the_deadline():
    rig = ntnx_rig(hang=[NTNX_OCT])
    start = asyncio.get_running_loop().time()
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=NTNX_OCT, deadline_ms=int(dt.datetime.now(dt.UTC).timestamp()*1000)+300))
    assert asyncio.get_running_loop().time()-start < 5
    assert result["batches"][0]["timedOut"] == 1 and NTNX_OCT not in rig.refreshed


async def test_stale_after_refresh_is_judged_at_the_end_of_the_search():
    rig = ntnx_rig()
    clock = [SEP21_1030]
    rig.clock = lambda: clock[0]
    original = rig.reprice

    async def reprice(contract):
        await original(contract)
        clock[0] += 3000   # each request takes three seconds; the first quote is 18 s old at judgement
    rig.reprice = reprice
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=NTNX_OCT, clock=rig.clock))
    october = {c["symbol"]: c for c in result["candidates"] if c.get("refreshed")}
    assert "quoteAsOf is missing, stale or future-dated" in october[NTNX_OCT]["reasons"]
    assert result["preferredContract"]["status"] == "ineligible_after_refresh"
    assert result["selected"] is not None and result["selected"]["symbol"] != NTNX_OCT
    assert result["asOfMs"]-result["selected"]["quoteAsOf"] <= 10000


async def test_second_batch_requires_an_explicit_remaining_time_budget():
    rig = ntnx_rig()
    policy = ntnx_policy(selection_version="diverse_liquidity_v1", refresh_batches=2)
    for row_ in rig.chain_rows:
        row_["open_interest"] = 300
    rig.quote_book = {s: (1., 1.5, 20, 20) for s in rig.quote_book}   # SYNTHETIC: every spread 40% -> no eligible row
    without = await select_contract(rig.engine(), ntnx_plan(), policy, SelectionRequest(clock=rig.clock))
    assert len(without["batches"]) == 1 and "explicit remaining time budget" in " ".join(without["incompleteReasons"])
    rig.refreshed.clear()
    with_deadline = await select_contract(rig.engine(), ntnx_plan(), policy, SelectionRequest(deadline_ms=SEP21_1030+120000, clock=rig.clock))
    assert len(with_deadline["batches"]) == 2 and len(rig.refreshed) == 12 and with_deadline["selected"] is None


async def test_an_eligible_first_batch_stops_further_requests():
    rig = ntnx_rig()
    policy = ntnx_policy(selection_version="diverse_liquidity_v1", refresh_batches=3)
    result = await select_contract(rig.engine(), ntnx_plan(), policy,
                                   SelectionRequest(preferred_contract=NTNX_OCT, deadline_ms=SEP21_1030+120000, clock=rig.clock))
    assert len(result["batches"]) == 1 and len(rig.refreshed) == 6 and result["selected"]["symbol"] == NTNX_OCT


async def test_cancellation_propagates_out_of_the_search():
    rig = ntnx_rig()

    async def reprice(contract):
        raise asyncio.CancelledError
    rig.reprice = reprice
    with pytest.raises(asyncio.CancelledError):
        await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                              SelectionRequest(preferred_contract=NTNX_OCT, clock=rig.clock))


async def test_chain_failure_for_one_expiry_leaves_the_other_searchable_and_the_search_incomplete():
    rig = ntnx_rig(fail=[NOV])
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=NTNX_OCT, clock=rig.clock))
    assert result["searchedExpiries"] == [OCT] and result["unsearchedExpiries"] == [NOV]
    assert result["selected"]["symbol"] == NTNX_OCT and result["searchComplete"] is False


async def test_preferred_contract_outside_the_fetched_chain_is_still_refreshed_with_unknown_oi():
    rig = ntnx_rig()
    rig.chain_rows = [r for r in rig.chain_rows if r["symbol"] != NTNX_OCT]
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1", min_open_interest=0),
                                   SelectionRequest(preferred_contract=NTNX_OCT, clock=rig.clock))
    assert rig.refreshed[0] == NTNX_OCT and result["preferredContract"]["inChain"] is False
    chosen = [c for c in result["candidates"] if c["symbol"] == NTNX_OCT][0]
    assert chosen["openInterestSource"] == "not_in_chain" and chosen["openInterest"] is None


async def test_saved_policies_without_version_keys_keep_legacy_behaviour():
    saved = {"dteMin": 21, "dteMax": 90, "targetDte": 45, "minAbsDelta": .25, "targetAbsDelta": .5,
             "maxAsk": 250., "maxSpreadPct": 20., "minOpenInterest": 100, "refreshLimit": 6}
    policy = ContractSelectionInput.model_validate(saved)
    assert policy.selection_version == "legacy" and policy.ranking_version == "legacy" and policy.refresh_batches == 1
    assert policy.model_dump(mode="json", by_alias=True)["selectionVersion"] == "legacy"


# ---- F3: executable-cost ranking -------------------------------------------------------------

def test_ntnx_october_book_economics_are_reported_not_labelled_as_profit():
    e = contract_economics(9.80, 11.30, 74, econ())
    assert e["spreadUnits"] == pytest.approx(1.5) and e["spreadUsdPerContract"] == 150
    assert e["spreadPctOfMid"] == pytest.approx(14.218, abs=.001) and e["spreadPctOfPremium"] == pytest.approx(13.274, abs=.001)
    assert e["roundTripFeesPerContractUsd"] == pytest.approx(2.08) and e["frictionPerContractUsd"] == pytest.approx(152.08)
    assert e["frictionPctOfDebit"] == pytest.approx(152.08/1130*100, abs=1e-4)
    assert e["affordableQuantity"] == 10 and e["coveredQuantity"] == 10 and e["sizeCoverage"] == 1
    assert e["entryDebitUsd"] == 11300 and e["spreadUsdTotal"] == 1500 and e["fullDebitExposureUsd"] == pytest.approx(11310.4)
    assert e["status"] == "estimated" and "profit" not in e["basis"]


def test_ulta_book_stays_ineligible_under_the_saved_spread_rule_regardless_of_capital():
    ulta = plan(id="ulta", symbol="ULTA", trigger=547.58, invalidation=544.43, targets=(548., 560.),
                first_session=dt.date(2026, 9, 21), last_session=dt.date(2026, 9, 21), created_at=SEP21_1030-3600000,
                baseline_as_of=SEP21_1030-3600000, rationale="Recorded 2026-09-21 ULTA geometry", source_refs=("2026-09-21-eod",))
    row_ = {"symbol": "ULTA261016C00560000", "bid": 10., "ask": 14.80, "delta": .45, "quoteAsOf": SEP21_1030,   # delta SYNTHETIC
            "deltaAsOf": SEP21_1030, "quoteSource": "opra", "openInterest": 500, "askSize": 50}
    for cap in (500., 25000., 1_000_000.):
        result = rank_candidates(ulta, ntnx_policy(max_ask=250, ranking_version="executable_cost_v1"), [row_], SEP21_1030,
                                 economics=econ(cap=cap, units=10))
        assert result["selected"] is None
        assert result["candidates"][0]["reasons"] == ["premium or spread exceeds reviewed limit"]
        assert result["candidates"][0]["spreadPct"] == pytest.approx(38.71, abs=.01)
        assert result["candidates"][0]["economics"]["spreadUsdPerContract"] == 480


def cost_rows():
    fresh = {"quoteAsOf": SEP21_1030, "deltaAsOf": SEP21_1030, "quoteSource": "opra", "openInterest": 500, "delta": .5}
    near = {"symbol": "NTNX261120C00070000", "bid": 4.0, "ask": 5.0, "askSize": 50, **fresh}      # dte 60: |60-45|=15, 22% of mid
    far = {"symbol": "NTNX261016C00060000", "bid": 9.80, "ask": 10.30, "askSize": 50, **fresh}    # dte 25: |25-45|=20, ~5% of mid
    return near, far


def test_cost_ranking_prefers_lower_friction_over_expiry_proximity_and_records_the_legacy_choice():
    near, far = cost_rows()
    near = {**near, "bid": 4.2}   # 17.4% of mid: eligible under the saved 20% limit, still costlier than far
    legacy = rank_candidates(ntnx_plan(), ntnx_policy(), [near, far], SEP21_1030, economics=econ())
    assert legacy["selected"]["symbol"] == near["symbol"] and legacy["rankingVersion"] == "legacy"
    cost = rank_candidates(ntnx_plan(), ntnx_policy(ranking_version="executable_cost_v1"), [near, far], SEP21_1030, economics=econ())
    assert cost["selected"]["symbol"] == far["symbol"] and cost["legacySelected"] == near["symbol"]
    assert cost["selectionChangedFromLegacy"] is True
    key = cost["selected"]["rankKey"]
    assert key["sizeCoverageKey"] == -1 and key["frictionPctOfDebit"] == pytest.approx((50+2.08)/1030*100, abs=1e-3)
    assert key["dteDistance"] == 20 and key["deltaDistance"] == 0
    assert cost["candidates"][1]["rankKey"]["frictionPctOfDebit"] == pytest.approx((80+2.08)/500*100, abs=1e-3)


def test_displayed_size_coverage_ranks_before_friction():
    near, far = cost_rows()
    near = {**near, "bid": 4.2}
    far = {**far, "askSize": 1}   # cheaper friction, but the book shows one contract against ten affordable
    cost = rank_candidates(ntnx_plan(), ntnx_policy(ranking_version="executable_cost_v1"), [near, far], SEP21_1030, economics=econ())
    assert cost["selected"]["symbol"] == near["symbol"]
    thin = [c for c in cost["candidates"] if c["symbol"] == far["symbol"]][0]
    assert thin["economics"]["sizeCoverage"] == pytest.approx(.1) and thin["economics"]["coveredQuantity"] == 1


def test_cost_ranking_never_promotes_an_ineligible_row():
    near, far = cost_rows()
    near = {**near, "bid": 4.2}
    far = {**far, "openInterest": 5}
    cost = rank_candidates(ntnx_plan(), ntnx_policy(ranking_version="executable_cost_v1"), [near, far], SEP21_1030, economics=econ())
    assert cost["selected"]["symbol"] == near["symbol"] and cost["candidates"][-1]["eligible"] is False


@pytest.mark.parametrize("quantity,size,coverage", [(1, 1, 1.), (2, 1, .5), (3, 2, pytest.approx(2/3, abs=1e-3)), (3, 0, 0.)])
def test_unit_allocations_and_partial_displayed_size(quantity, size, coverage):
    e = contract_economics(9.80, 11.30, size, econ(), quantity=quantity)
    assert e["quantity"] == quantity and e["coveredQuantity"] == min(quantity, size) and e["sizeCoverage"] == coverage
    assert e["frictionUsd"] == pytest.approx(152.08*quantity) and e["feesUsd"] == pytest.approx(2.08*quantity)


def test_unknown_economics_stay_unknown():
    assert contract_economics(None, 11.30, 74, econ()) is None
    assert contract_economics(11.30, 9.80, 74, econ()) is None
    unknown = contract_economics(9.80, 11.30, 74, None)
    assert unknown["status"] == "unknown_funding" and unknown["quantity"] is None and unknown["frictionPctOfDebit"] is None
    assert unknown["spreadUsdPerContract"] == 150
    fees_only = contract_economics(9.80, 11.30, None, SelectionEconomics(entry_fee_per_contract_usd=1.04, exit_fee_per_contract_usd=1.04))
    assert fees_only["status"] == "fees_only" and fees_only["frictionPctOfDebit"] == pytest.approx(152.08/1130*100)
    assert fees_only["affordableQuantity"] is None and fees_only["sizeCoverage"] is None
    unsized = contract_economics(9.80, 11.30, None, econ())
    assert unsized["sizeCoverage"] is None and unsized["affordableQuantity"] == 10
    unaffordable = contract_economics(9.80, 11.30, 74, econ(cap=1000.))
    assert unaffordable["status"] == "unaffordable" and unaffordable["quantity"] == 0


# ---- R4 (2026-09-21 review): discovery and chain requests obey the same deadline as refreshes ----

async def test_stalled_expiry_discovery_is_bounded_and_reported_incomplete():
    rig = ntnx_rig()

    async def expirations(symbol):
        await asyncio.sleep(3600)
    rig.expirations = expirations
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(deadline_ms=int(dt.datetime.now(dt.UTC).timestamp()*1000)+300))
    assert result["searchComplete"] is False and result["selected"] is None and rig.chain_calls == []
    assert any("expiry discovery timed out" in r for r in result["incompleteReasons"])


async def test_stalled_chain_request_is_bounded_and_the_other_expiry_still_searched():
    rig = ntnx_rig()
    original = rig.chain

    async def chain(symbol, expiry):
        if expiry == NOV:
            await asyncio.sleep(3600)
        return await original(symbol, expiry)
    rig.chain = chain
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=NTNX_OCT, deadline_ms=int(dt.datetime.now(dt.UTC).timestamp()*1000)+600))
    assert NOV in result["unsearchedExpiries"] and result["searchComplete"] is False
    assert any("chain request timed out" in r for r in result["incompleteReasons"])


async def test_already_expired_request_issues_no_provider_calls():
    rig = ntnx_rig()
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(deadline_ms=SEP21_1030-1, clock=rig.clock))
    assert rig.chain_calls == [] and rig.refreshed == [] and result["selected"] is None
    assert result["searchStatus"] == "expired" and result["searchComplete"] is False


async def test_result_arriving_after_the_deadline_is_not_a_selection():
    rig = ntnx_rig()
    clock = [SEP21_1030]
    rig.clock = lambda: clock[0]
    original = rig.reprice

    async def reprice(contract):
        await original(contract)
        clock[0] += 450   # the fifth refresh ends past the 2 s deadline
    rig.reprice = reprice
    result = await select_contract(rig.engine(), ntnx_plan(), ntnx_policy(selection_version="diverse_liquidity_v1"),
                                   SelectionRequest(preferred_contract=NTNX_OCT, deadline_ms=SEP21_1030+2000, clock=rig.clock))
    assert result["expiredSelection"] is True and result["selected"] is None and result["searchStatus"] == "expired"
    assert any(c["symbol"] == NTNX_OCT and c["eligible"] for c in result["candidates"])   # recorded, not selected
