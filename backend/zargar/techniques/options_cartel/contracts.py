"""Routine Cartel option selection with explicit reviewed expiry/price preferences.

No expiry or target delta is attributed to Sean beyond S15's routine 0.25 floor.
Candidates lacking independently fresh quote/Greek observations cannot be selected.

Two versioned behaviours live here (2026-09-21 brief, F2/F3):

* ``selection_version``: how the bounded quote refresh is ALLOCATED across the structural
  candidates. ``legacy`` (default, Live and every saved arm) refreshes the ``refresh_limit``
  rows nearest the reviewed DTE/delta, so one expiry can consume the whole budget even when
  its rows fail the known open-interest requirement (NTNX 2026-09-21: six November rows, OI
  0-26, October never refreshed). ``diverse_liquidity_v1`` gives the caller's reviewed
  contract first refresh consideration, partitions by expiry, sets known static failures
  aside, allocates round-robin across expiries, bounds requests/time inside the caller's
  deadline and re-judges freshness after every request completes.
* ``ranking_version``: how fully eligible refreshed candidates are ORDERED. ``legacy`` is
  DTE distance, delta distance, spread, symbol. ``executable_cost_v1`` is displayed-size
  coverage, then (crossing spread + round-trip fees) / entry debit, then DTE distance, delta
  distance, symbol - current friction, never expected return. Eligibility is unchanged by
  either version; the saved 20% spread limit stays the gate.
"""
from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import logging
import math
from collections import deque
from typing import Callable, Literal

from pydantic import Field, model_validator

from ...marketstructure.sessions import ET
from ...options.occ import parse
from .plans import CartelPlan
from .service import WireModel

log = logging.getLogger("zargar.options_cartel.contracts")

SELECTION_VERSIONS = ("legacy", "diverse_liquidity_v1")
RANKING_VERSIONS = ("legacy", "executable_cost_v1")
# One provider request at a time (the OPRA refresh already batches every tracked contract);
# a single refresh may not outlive this many seconds or the caller's remaining deadline.
REFRESH_CONCURRENCY = 1
REFRESH_TIMEOUT_SECONDS = 5.0
QUOTE_MAX_AGE_MS = 10_000
DELTA_MAX_AGE_MS = 120_000
OI_UNKNOWN_REASON = "open interest is unknown for this contract; the reviewed liquidity requirement cannot be confirmed"
OI_BELOW_REASON = "open interest does not meet reviewed liquidity requirement"


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class ContractSelectionInput(WireModel):
    dte_min: int = Field(ge=2, le=730)
    dte_max: int = Field(ge=2, le=730)
    target_dte: int = Field(ge=2, le=730)
    target_abs_delta: float = Field(ge=.25, le=1)
    min_abs_delta: float = Field(default=.25, ge=.25, le=1)
    max_ask: float = Field(gt=0)
    max_spread_pct: float = Field(gt=0, le=100)
    min_open_interest: int = Field(default=0, ge=0)
    refresh_limit: int = Field(default=12, ge=1, le=30)
    # Explicit, snapshotted behaviour versions. Missing keys on a saved arm mean legacy.
    selection_version: Literal["legacy", "diverse_liquidity_v1"] = "legacy"
    ranking_version: Literal["legacy", "executable_cost_v1"] = "legacy"
    # diverse_liquidity_v1 only: further batches of ``refresh_limit`` requests are allowed
    # only while refreshable candidates remain AND the caller's deadline has not passed.
    refresh_batches: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def bounds(self):
        if not self.dte_min <= self.target_dte <= self.dte_max or self.target_abs_delta < self.min_abs_delta:
            raise ValueError("selection targets must be inside the reviewed ranges")
        return self


class SelectionEconomics(WireModel):
    """Cash basis for the executable-cost comparison. Estimates only; never a reservation."""
    # Cash cap/max units may be unknown (pre-open planning on delayed chain rows): friction per
    # contract is still measurable; quantity, coverage and totals then stay None.
    cash_cap_usd: float | None = Field(default=None, ge=0)
    max_units: int | None = Field(default=None, ge=1, le=1_000_000)
    entry_fee_per_contract_usd: float = Field(ge=0)
    exit_fee_per_contract_usd: float = Field(ge=0)
    multiplier: int = Field(default=100, ge=1)
    basis: str = "Frozen Practice simulator fee schedule; cash cap = min(cash, budget, equity x risk%)"


@dataclasses.dataclass
class SelectionRequest:
    """Per-call context (not policy): the reviewed contract, the deadline and the cash basis."""
    preferred_contract: str | None = None
    deadline_ms: int | None = None
    economics: SelectionEconomics | None = None
    plan_id: str | None = None
    portfolio_id: str | None = None
    clock: Callable[[], int] | None = None

    def now(self) -> int:
        return self.clock() if self.clock else int(dt.datetime.now(dt.UTC).timestamp()*1000)


async def selection_economics(engine, portfolio_id, *, budget, risk_pct, max_units) -> SelectionEconomics | None:
    """The same cash cap and modeled fees the research observer freezes; None for non-sim books
    (their fee schedule is the broker's, so their economics stay unknown rather than modeled)."""
    book = engine.positions.portfolio(portfolio_id)
    if not book or book.get("kind") != "sim":
        return None
    equity = await engine.positions.equity(portfolio_id)
    fx = engine.positions.fx.rate("USD", book.get("baseCurrency", "USD"))
    cash = book.get("cash")
    fee = engine.settings.get("options.fee_per_contract", .99)
    regulatory = engine.settings.get("sim.reg_fee_per_contract", .05)
    if not all(_numeric(v) for v in (equity, fx, cash, fee, regulatory)) or fx <= 0 or min(fee, regulatory) < 0:
        return None
    cap = max(0., min(cash, budget, equity*risk_pct/100))
    return SelectionEconomics(cash_cap_usd=cap/fx, max_units=max_units,
                              entry_fee_per_contract_usd=fee+regulatory, exit_fee_per_contract_usd=fee+regulatory)


def contract_economics(bid, ask, ask_size, economics: SelectionEconomics | None, *, quantity=None, multiplier=100) -> dict | None:
    """Current friction of buying at the ask and later selling at the bid (F3).

    Spread is reported in quote units, dollars per contract and dollars for the quantity, beside
    fees, the entry debit, the full-debit exposure and spread as a percentage of the premium paid.
    ``quantity`` (an actual sized quantity) overrides the affordability estimate. Missing size or
    cash basis leaves those fields None: unknown, not zero.
    """
    if not (_numeric(bid) and _numeric(ask) and 0 < bid <= ask):
        return None
    mult = economics.multiplier if economics else multiplier
    spread_units = ask-bid
    mid = (ask+bid)/2
    debit_unit = ask*mult
    out = {"basis": "buy at the ask, exit at the bid; displayed size consumed once; fees per contract per side",
           "spreadUnits": round(spread_units, 4), "spreadUsdPerContract": round(spread_units*mult, 2),
           "spreadPctOfMid": round(spread_units/mid*100, 4) if mid else None,
           "spreadPctOfPremium": round(spread_units/ask*100, 4),
           "entryDebitPerContractUsd": round(debit_unit, 2), "displayedAskSize": ask_size if _numeric(ask_size) else None,
           "entryFeePerContractUsd": None, "exitFeePerContractUsd": None, "roundTripFeesPerContractUsd": None,
           "frictionPerContractUsd": None, "frictionPctOfDebit": None,
           "affordableQuantity": None, "coveredQuantity": None, "sizeCoverage": None, "quantity": None,
           "entryDebitUsd": None, "spreadUsdTotal": None, "feesUsd": None, "frictionUsd": None,
           "fullDebitExposureUsd": None, "status": "unknown_funding"}
    if economics is None:
        return out
    entry_fee, exit_fee = economics.entry_fee_per_contract_usd, economics.exit_fee_per_contract_usd
    friction_unit = spread_units*mult+entry_fee+exit_fee
    out.update(entryFeePerContractUsd=round(entry_fee, 4), exitFeePerContractUsd=round(exit_fee, 4),
               roundTripFeesPerContractUsd=round(entry_fee+exit_fee, 4),
               frictionPerContractUsd=round(friction_unit, 2), frictionPctOfDebit=round(friction_unit/debit_unit*100, 4))
    unit_cost = debit_unit+entry_fee
    affordable = None
    if economics.cash_cap_usd is not None and economics.max_units is not None:
        affordable = min(economics.max_units, math.floor(economics.cash_cap_usd/unit_cost)) if unit_cost > 0 else 0
    out["affordableQuantity"] = affordable
    if quantity is not None:
        qty = int(quantity) if _numeric(quantity) and quantity > 0 else 0
    elif affordable is not None:
        qty = affordable
    else:
        out["status"] = "fees_only"
        return out
    covered = min(qty, int(ask_size)) if _numeric(ask_size) else None
    out["quantity"] = qty
    if covered is not None:
        out["coveredQuantity"] = covered
        out["sizeCoverage"] = round(covered/qty, 4) if qty > 0 else 0.
    out.update(entryDebitUsd=round(debit_unit*qty, 2), spreadUsdTotal=round(spread_units*mult*qty, 2),
               feesUsd=round((entry_fee+exit_fee)*qty, 2), frictionUsd=round(friction_unit*qty, 2),
               fullDebitExposureUsd=round((debit_unit+entry_fee)*qty, 2),
               status="estimated" if qty >= 1 else "unaffordable")
    return out


def _legacy_key(policy):
    return lambda c: (not c["eligible"], abs(c["dte"]-policy.target_dte),
                      abs(abs(c["delta"])-policy.target_abs_delta) if c["delta"] is not None else 2,
                      c["spreadPct"] if c["spreadPct"] is not None else 1000, c["symbol"])


def _cost_key(policy):
    def key(c):
        economics = c.get("economics") or {}
        coverage = economics.get("sizeCoverage")
        friction = economics.get("frictionPctOfDebit")
        return (not c["eligible"], -coverage if coverage is not None else 0.,
                friction if friction is not None else float("inf"), abs(c["dte"]-policy.target_dte),
                abs(abs(c["delta"])-policy.target_abs_delta) if c["delta"] is not None else 2, c["symbol"])
    return key


def rank_candidates(plan: CartelPlan, policy: ContractSelectionInput, rows: list[dict], at: int,
                    *, economics: SelectionEconomics | None = None) -> dict:
    today = dt.datetime.fromtimestamp(at/1000, ET).date()
    candidates = []
    seen = set()
    for row in rows:
        option = parse(row.get("symbol"))
        if option is None or option.strike <= 0 or option.underlying != plan.symbol or option.right != ("C" if plan.direction == "long" else "P"):
            continue
        dte = option.dte(today)
        if not policy.dte_min <= dte <= policy.dte_max:
            continue
        if option.symbol in seen:
            raise ValueError("duplicate contract snapshots are ambiguous")
        seen.add(option.symbol)
        reasons = []
        bid, ask, delta = row.get("bid"), row.get("ask"), row.get("delta")
        price_ok = _numeric(bid) and _numeric(ask) and 0 < bid <= ask
        spread = (ask-bid)/((ask+bid)/2)*100 if price_ok else None
        if not price_ok:
            reasons.append("missing or crossed bid/ask")
        elif ask > policy.max_ask or spread > policy.max_spread_pct:
            reasons.append("premium or spread exceeds reviewed limit")
        delta_ok = _numeric(delta) and policy.min_abs_delta <= abs(delta) <= 1 \
            and (delta > 0 if plan.direction == "long" else delta < 0)
        if not delta_ok:
            reasons.append("delta is missing, wrong-sign, or below the routine floor")
        for field, maximum in (("quoteAsOf", QUOTE_MAX_AGE_MS), ("deltaAsOf", DELTA_MAX_AGE_MS)):
            stamp = row.get(field)
            if not _numeric(stamp) or not 0 <= at-stamp <= maximum:
                reasons.append(f"{field} is missing, stale or future-dated")
        if row.get("quoteSource") not in ("opra", "sim"):
            reasons.append("quote is not a current OPRA/sim observation")
        oi = row.get("openInterest")
        if policy.min_open_interest:
            if not _numeric(oi):
                reasons.append(OI_UNKNOWN_REASON)
            elif oi < policy.min_open_interest:
                reasons.append(OI_BELOW_REASON)
        candidate = {"symbol": option.symbol, "expiry": option.expiry.isoformat(), "dte": dte,
                     "strike": option.strike, "delta": delta if _numeric(delta) else None,
                     "bid": bid if _numeric(bid) else None, "ask": ask if _numeric(ask) else None,
                     "bidSize": row.get("bidSize") if _numeric(row.get("bidSize")) else None,
                     "askSize": row.get("askSize") if _numeric(row.get("askSize")) else None,
                     "spreadPct": spread, "openInterest": oi if _numeric(oi) else None,
                     "openInterestSource": row.get("openInterestSource") or ("chain" if _numeric(oi) else "missing"),
                     "quoteAsOf": row.get("quoteAsOf") if _numeric(row.get("quoteAsOf")) else None,
                     "deltaAsOf": row.get("deltaAsOf") if _numeric(row.get("deltaAsOf")) else None,
                     "quoteSource": row.get("quoteSource"), "refreshed": True,
                     "eligible": not reasons, "reasons": reasons}
        if policy.ranking_version == "executable_cost_v1" or economics is not None:
            candidate["economics"] = contract_economics(bid, ask, candidate["askSize"], economics)
        candidates.append(candidate)
    legacy_order = sorted(candidates, key=_legacy_key(policy))
    if policy.ranking_version == "executable_cost_v1":
        candidates.sort(key=_cost_key(policy))
        for c in candidates:
            k = _cost_key(policy)(c)
            c["rankKey"] = {"ineligible": k[0], "sizeCoverageKey": k[1], "frictionPctOfDebit": None if k[2] == float("inf") else k[2],
                            "dteDistance": k[3], "deltaDistance": k[4], "symbol": k[5]}
        ranking = ("executable_cost_v1: eligibility, displayed-size coverage of the affordable quantity, "
                   "(crossing spread + round-trip fees) / entry debit, distance to reviewed DTE, delta distance, symbol. "
                   "Current friction only; not expected return.")
    else:
        candidates = legacy_order
        ranking = "Eligibility, distance to reviewed DTE, delta distance, spread, symbol."
    selected = next((c for c in candidates if c["eligible"]), None)
    legacy_selected = next((c["symbol"] for c in legacy_order if c["eligible"]), None)
    return {"runId": plan.id, "asOfMs": at, "selected": selected, "candidates": candidates,
            "policy": policy.model_dump(mode="json", by_alias=True), "placesOrders": False, "ranking": ranking,
            "rankingVersion": policy.ranking_version, "legacySelected": legacy_selected,
            "selectionChangedFromLegacy": bool(selected) and selected["symbol"] != legacy_selected,
            "economicsBasis": economics.basis if economics else "none: quantity, fees and coverage unknown"}


def _view(engine, symbol, row, *, oi_source="chain"):
    quote = engine.quotes.get(symbol)
    snapshot = engine.options.snapshot_cached(symbol) or {}
    oi = row.get("open_interest") if row else None
    return {"symbol": symbol, "bid": quote.bid if quote else None, "ask": quote.ask if quote else None,
            "bidSize": quote.bid_size if quote else None, "askSize": quote.ask_size if quote else None,
            "quoteAsOf": (quote.source_ts or quote.ts) if quote else None,
            "quoteSource": quote.source if quote else None,
            "delta": (snapshot.get("greeks") or {}).get("delta"),
            "deltaAsOf": (snapshot.get("greeksFieldAsOf") or {}).get("delta"),
            "openInterest": oi if _numeric(oi) else None,
            "openInterestSource": oi_source if _numeric(oi) else ("missing" if row else "not_in_chain")}


async def select_contract(engine, plan: CartelPlan, policy: ContractSelectionInput, request: SelectionRequest | None = None):
    if engine.options is None:
        raise ValueError("options service is unavailable")
    request = request or SelectionRequest()
    if policy.selection_version == "diverse_liquidity_v1":
        return await _select_diverse(engine, plan, policy, request)
    return await _select_legacy(engine, plan, policy, request)


def call_selector(choose, engine, plan, policy, request: SelectionRequest | None):
    """Invoke ``choose`` (a select_contract-compatible callable or a test seam). Selectors that do not
    accept the per-call request (legacy 3-argument seams) are called without it; the request then
    has no effect, which is the legacy behaviour they were written against."""
    import inspect
    selector = choose or select_contract
    try:
        parameters = inspect.signature(selector).parameters
    except (TypeError, ValueError):
        return selector(engine, plan, policy, request)
    accepts = len(parameters) >= 4 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in parameters.values()) \
        or "request" in parameters
    return selector(engine, plan, policy, request) if accepts else selector(engine, plan, policy)


async def _select_legacy(engine, plan, policy, request):
    now = request.now()
    today = dt.datetime.fromtimestamp(now/1000, ET).date()
    provider = engine.options.provider()
    expiries = [e for e in await provider.expirations(plan.symbol)
                if policy.dte_min <= (dt.date.fromisoformat(e)-today).days <= policy.dte_max]
    expiries.sort(key=lambda e: (abs((dt.date.fromisoformat(e)-today).days-policy.target_dte), e))
    searched, raw, warnings = [], [], []
    for expiry in expiries[:6]:
        try:
            rows = await provider.chain(plan.symbol, expiry)
            raw.extend(rows)
            searched.append(expiry)
        except Exception as exc:
            log.exception("Cartel chain selection failed for %s %s", plan.symbol, expiry)
            warnings.append(f"{expiry}: chain unavailable ({type(exc).__name__})")
    if len(expiries) > 6:
        warnings.append("Search limited to the six expiries closest to the reviewed target DTE.")
    structural = []
    for row in raw:
        o = parse(row.get("symbol"))
        if o and o.underlying == plan.symbol and o.right == ("C" if plan.direction == "long" else "P") \
                and policy.dte_min <= o.dte(today) <= policy.dte_max:
            delta = (row.get("greeks") or {}).get("delta")
            distance = abs(abs(delta)-policy.target_abs_delta) if isinstance(delta, (int, float)) \
                and math.isfinite(delta) else 2
            structural.append((abs(o.dte(today)-policy.target_dte), distance, o.symbol, row))
    structural.sort(key=lambda item: item[:3])
    sampled = structural[:policy.refresh_limit]
    views = []
    for _, _, symbol, row in sampled:
        try:
            await engine.options.reprice({"symbol": symbol})
        except Exception as exc:
            log.exception("Cartel contract refresh failed for %s", symbol)
            warnings.append(f"{symbol}: refresh unavailable ({type(exc).__name__})")
        views.append(_view(engine, symbol, row))
    result = rank_candidates(plan, policy, views, request.now(), economics=request.economics)
    result.update(selectionVersion="legacy", searchedExpiries=searched, structuralCandidates=len(structural),
                  refreshedCandidates=len(sampled), warnings=warnings,
                  searchComplete=not warnings and len(searched) == len(expiries) and len(sampled) == len(structural),
                  preferredContract={"symbol": request.preferred_contract, "considered": False,
                                     "note": "legacy selection gives the reviewed contract no special consideration"}
                  if request.preferred_contract else None,
                  note="Selection covers refreshed candidates only; rerun preflight at the actual entry.")
    return result


def _preferred_identity(plan, policy, symbol, today, request):
    option = parse(symbol) if symbol else None
    identity = {"symbol": symbol, "parsed": option is not None,
                "underlyingOk": bool(option and option.underlying == plan.symbol),
                "rightOk": bool(option and option.right == ("C" if plan.direction == "long" else "P")),
                "dteInRange": bool(option and policy.dte_min <= option.dte(today) <= policy.dte_max),
                "planId": plan.id, "portfolioId": request.portfolio_id,
                "planIdOk": request.plan_id is None or request.plan_id == plan.id}
    identity["ok"] = all(identity[k] for k in ("parsed", "underlyingOk", "rightOk", "dteInRange", "planIdOk"))
    return option, identity


def allocate_refresh(structural: list[dict], policy: ContractSelectionInput, preferred: str | None) -> dict:
    """Deterministic refresh order (F2 item 3): reviewed contract first, then round-robin across expiries
    ordered by distance to the reviewed DTE, each expiry's queue ordered by static liquidity tier
    (known acceptable OI, unknown OI), delta distance and symbol. Known static failures (OI below the
    reviewed minimum, which no quote refresh can change) are recorded, never refreshed. When expiries
    exceed the budget, the nearest-to-target expiries receive one request each in distance order."""
    known_failures = [c for c in structural if c["tier"] >= 3]
    queues: dict[str, deque] = {}
    for c in sorted(structural, key=lambda c: (c["tier"], c["deltaDistance"], c["symbol"])):
        if c["tier"] >= 3 or c["symbol"] == preferred:
            continue
        queues.setdefault(c["expiry"], deque()).append(c)
    expiry_order = sorted(queues, key=lambda e: (queues[e][0]["dteDistance"], e))
    order = [c for c in structural if c["symbol"] == preferred]
    while any(queues[e] for e in expiry_order):
        for expiry in expiry_order:
            if queues[expiry]:
                order.append(queues[expiry].popleft())
    return {"order": order, "knownFailures": known_failures, "expiryOrder": expiry_order,
            "rule": ("reviewed contract first; then one candidate per expiry per pass in reviewed-DTE distance "
                     "order (known-OI rows before unknown-OI rows, then delta distance, then symbol); known "
                     "open-interest failures are recorded without refresh; expiries beyond the budget wait "
                     "for the next batch")}


def _remaining_seconds(request):
    return None if request.deadline_ms is None else (request.deadline_ms-request.now())/1000


async def _bounded(request, coroutine_factory, label, incomplete):
    """Run one provider request inside the per-call ceiling AND the remaining deadline (R4).

    Returns (value, ok). A request is never started once the deadline has passed; a timeout or
    provider error is recorded as incomplete work, never as an empty result.
    """
    remaining = _remaining_seconds(request)
    if remaining is not None and remaining <= 0:
        incomplete.append(f"deadline reached before {label}")
        return None, False
    timeout = REFRESH_TIMEOUT_SECONDS if remaining is None else min(REFRESH_TIMEOUT_SECONDS, remaining)
    try:
        return await asyncio.wait_for(coroutine_factory(), timeout), True
    except TimeoutError:
        incomplete.append(f"{label} timed out after {timeout:g}s")
        return None, False
    except Exception as exc:  # noqa: BLE001 - provider failures are incomplete work, not evidence of absence
        log.exception("Cartel selection request failed: %s", label)
        incomplete.append(f"{label} unavailable ({type(exc).__name__})")
        return None, False


async def _select_diverse(engine, plan, policy, request):
    started = request.now()
    today = dt.datetime.fromtimestamp(started/1000, ET).date()
    provider = engine.options.provider()
    warnings, incomplete = [], []
    all_expiries, ok = await _bounded(request, lambda: provider.expirations(plan.symbol), "expiry discovery", incomplete)
    if not ok:
        all_expiries = []
    expiries = [e for e in all_expiries if policy.dte_min <= (dt.date.fromisoformat(e)-today).days <= policy.dte_max]
    expiries.sort(key=lambda e: (abs((dt.date.fromisoformat(e)-today).days-policy.target_dte), e))
    searched, unsearched, raw = [], [], []
    for expiry in expiries[:6]:
        rows, ok = await _bounded(request, lambda e=expiry: provider.chain(plan.symbol, e), f"{expiry} chain request", incomplete)
        if ok:
            raw.extend(rows)
            searched.append(expiry)
        else:
            warnings.append(f"{expiry}: chain not searched ({incomplete[-1]})")
            unsearched.append(expiry)
    for expiry in expiries[6:]:
        unsearched.append(expiry)
    if unsearched:
        incomplete.append("expiries in the reviewed DTE range were not searched: " + ", ".join(unsearched))
    if not ok and not all_expiries:
        incomplete.append("expiry discovery did not complete; the reviewed DTE range may hold unsearched expiries")
    right = "C" if plan.direction == "long" else "P"
    structural, by_symbol = [], {}
    for row in raw:
        o = parse(row.get("symbol"))
        if not (o and o.underlying == plan.symbol and o.right == right and policy.dte_min <= o.dte(today) <= policy.dte_max):
            continue
        if o.symbol in by_symbol:
            continue
        delta = (row.get("greeks") or {}).get("delta")
        oi = row.get("open_interest")
        if policy.min_open_interest and _numeric(oi) and oi < policy.min_open_interest:
            tier, liquidity = 3, "known_failure"
        elif policy.min_open_interest and not _numeric(oi):
            tier, liquidity = 2, "unknown"
        else:
            tier, liquidity = 1, "known_ok"
        item = {"symbol": o.symbol, "expiry": o.expiry.isoformat(), "dte": o.dte(today),
                "dteDistance": abs(o.dte(today)-policy.target_dte),
                "deltaDistance": abs(abs(delta)-policy.target_abs_delta) if _numeric(delta) else 2,
                "openInterest": oi if _numeric(oi) else None, "liquidity": liquidity, "tier": tier, "row": row}
        structural.append(item)
        by_symbol[o.symbol] = item
    preferred = None
    preferred_record = None
    if request.preferred_contract:
        option, identity = _preferred_identity(plan, policy, request.preferred_contract, today, request)
        preferred_record = {"symbol": request.preferred_contract, "identity": identity, "considered": identity["ok"],
                            "inChain": request.preferred_contract in by_symbol, "status": "pending"}
        if identity["ok"]:
            preferred = request.preferred_contract
            if preferred not in by_symbol:
                item = {"symbol": preferred, "expiry": option.expiry.isoformat(), "dte": option.dte(today),
                        "dteDistance": abs(option.dte(today)-policy.target_dte), "deltaDistance": 2,
                        "openInterest": None, "liquidity": "unknown", "tier": 0, "row": None}
                structural.append(item)
                by_symbol[preferred] = item
            else:
                by_symbol[preferred]["tier"] = 0
        else:
            preferred_record["status"] = "identity_rejected"
    allocation = allocate_refresh(structural, policy, preferred)
    order = allocation["order"]
    refreshed, batches = [], []
    cursor = 0
    while cursor < len(order) and len(batches) < policy.refresh_batches:
        if batches and (request.deadline_ms is None or request.now() >= request.deadline_ms):
            incomplete.append("a further refresh batch needs an explicit remaining time budget")
            break
        batch = {"index": len(batches)+1, "requested": 0, "refreshed": 0, "timedOut": 0, "errors": 0, "startedAt": request.now()}
        for item in order[cursor:cursor+policy.refresh_limit]:
            remaining = None if request.deadline_ms is None else (request.deadline_ms-request.now())/1000
            if remaining is not None and remaining <= 0:
                incomplete.append(f"deadline reached before refreshing {item['symbol']}")
                break
            batch["requested"] += 1
            cursor += 1
            timeout = REFRESH_TIMEOUT_SECONDS if remaining is None else min(REFRESH_TIMEOUT_SECONDS, remaining)
            try:
                await asyncio.wait_for(engine.options.reprice({"symbol": item["symbol"]}), timeout)
                batch["refreshed"] += 1
                item["refreshStatus"] = "refreshed"
            except TimeoutError:
                batch["timedOut"] += 1
                item["refreshStatus"] = "timeout"
                warnings.append(f"{item['symbol']}: refresh timed out after {timeout:g}s")
            except Exception as exc:
                log.exception("Cartel contract refresh failed for %s", item["symbol"])
                batch["errors"] += 1
                item["refreshStatus"] = "error"
                warnings.append(f"{item['symbol']}: refresh unavailable ({type(exc).__name__})")
            refreshed.append(item)
        batch["finishedAt"] = request.now()
        batches.append(batch)
        if cursor >= len(order):
            break
        # Judge the batch before spending more: a fully eligible candidate ends the search.
        interim = rank_candidates(plan, policy, [_view(engine, i["symbol"], i["row"]) for i in refreshed],
                                  request.now(), economics=request.economics)
        if interim["selected"] is not None:
            break
    # Freshness, Greeks, spread and size are judged once, after every request completed (item 5).
    at = request.now()
    views = [_view(engine, i["symbol"], i["row"], oi_source="chain") for i in refreshed]
    result = rank_candidates(plan, policy, views, at, economics=request.economics)
    for c in result["candidates"]:
        item = by_symbol.get(c["symbol"])
        c["refreshStatus"] = item.get("refreshStatus") if item else None
        c["liquidity"] = item["liquidity"] if item else None
        c["preferred"] = c["symbol"] == preferred
    unrefreshed = []
    for item in order[cursor:]:
        unrefreshed.append({"symbol": item["symbol"], "expiry": item["expiry"], "dte": item["dte"],
                            "openInterest": item["openInterest"], "liquidity": item["liquidity"], "refreshed": False,
                            "eligible": False, "reasons": ["not refreshed: request budget or deadline exhausted"]})
    for item in allocation["knownFailures"]:
        unrefreshed.append({"symbol": item["symbol"], "expiry": item["expiry"], "dte": item["dte"],
                            "openInterest": item["openInterest"], "liquidity": item["liquidity"], "refreshed": False,
                            "eligible": False, "reasons": [OI_BELOW_REASON, "not refreshed: known static failure"]})
    result["candidates"].extend(unrefreshed)
    if preferred_record and preferred:
        chosen = next((c for c in result["candidates"] if c["symbol"] == preferred), None)
        preferred_record["status"] = ("selected" if result["selected"] and result["selected"]["symbol"] == preferred
                                      else "ineligible_after_refresh" if chosen and chosen.get("refreshed") else
                                      "not_refreshed")
        preferred_record["reasons"] = chosen["reasons"] if chosen else []
    by_expiry = {}
    for item in structural:
        e = by_expiry.setdefault(item["expiry"], {"dte": item["dte"], "structural": 0, "knownFailures": 0, "unknownLiquidity": 0,
                                                  "refreshed": 0, "unrefreshed": 0, "eligible": 0})
        e["structural"] += 1
        if item["tier"] >= 3:
            e["knownFailures"] += 1
        elif item["liquidity"] == "unknown":
            e["unknownLiquidity"] += 1
        if item.get("refreshStatus") == "refreshed":
            e["refreshed"] += 1
        elif item["tier"] < 3:
            e["unrefreshed"] += 1
    for c in result["candidates"]:
        if c["eligible"]:
            by_expiry[c["expiry"]]["eligible"] += 1
    refreshable_left = len(order)-cursor
    if refreshable_left:
        incomplete.append(f"{refreshable_left} refreshable candidate(s) were not refreshed within the request budget")
    failed = [i for i in refreshed if i.get("refreshStatus") != "refreshed"]
    if failed:
        incomplete.append(f"{len(failed)} refresh request(s) timed out or failed")
    expired = request.deadline_ms is not None and at > request.deadline_ms
    result["expiredSelection"] = expired
    if expired:
        incomplete.append("the signal deadline passed before the result could be used; no contract is selected")
        result["selected"] = None
    complete = not incomplete
    result.update(selectionVersion="diverse_liquidity_v1", searchedExpiries=searched, unsearchedExpiries=unsearched,
                  structuralCandidates=len(structural), requestedCandidates=len(refreshed),
                  refreshedCandidates=len(refreshed)-len(failed), unrefreshedCandidates=refreshable_left, knownFailureCandidates=len(allocation["knownFailures"]),
                  byExpiry=by_expiry, batches=batches, allocation={"rule": allocation["rule"], "expiryOrder": allocation["expiryOrder"],
                  "order": [i["symbol"] for i in order], "concurrency": REFRESH_CONCURRENCY,
                  "perRequestTimeoutSeconds": REFRESH_TIMEOUT_SECONDS, "deadlineMs": request.deadline_ms},
                  preferredContract=preferred_record, warnings=warnings, searchComplete=complete,
                  searchStatus="complete" if complete else "expired" if expired else "incomplete", incompleteReasons=incomplete,
                  startedAt=started, finishedAt=at,
                  note=("Complete search: every refreshable candidate in the reviewed range was refreshed and judged."
                        if complete else "Incomplete search: an unrefreshed candidate may still be eligible; this is not proof that no option qualifies.")
                  + " Rerun preflight at the actual entry.")
    return result
