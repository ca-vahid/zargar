"""Routine Cartel option selection with explicit reviewed expiry/price preferences.

No expiry or target delta is attributed to Sean beyond S15's routine 0.25 floor.
Candidates lacking independently fresh quote/Greek observations cannot be selected.
"""
from __future__ import annotations

import datetime as dt
import logging
import math

from pydantic import Field, model_validator

from ...marketstructure.sessions import ET
from ...options.occ import parse
from .plans import CartelPlan
from .service import WireModel

log = logging.getLogger("zargar.options_cartel.contracts")


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

    @model_validator(mode="after")
    def bounds(self):
        if not self.dte_min <= self.target_dte <= self.dte_max or self.target_abs_delta < self.min_abs_delta:
            raise ValueError("selection targets must be inside the reviewed ranges")
        return self


def rank_candidates(plan: CartelPlan, policy: ContractSelectionInput, rows: list[dict], at: int) -> dict:
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

        def numeric(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

        bid, ask, delta = row.get("bid"), row.get("ask"), row.get("delta")
        price_ok = numeric(bid) and numeric(ask) and 0 < bid <= ask
        spread = (ask-bid)/((ask+bid)/2)*100 if price_ok else None
        if not price_ok:
            reasons.append("missing or crossed bid/ask")
        elif ask > policy.max_ask or spread > policy.max_spread_pct:
            reasons.append("premium or spread exceeds reviewed limit")
        delta_ok = numeric(delta) and policy.min_abs_delta <= abs(delta) <= 1 \
            and (delta > 0 if plan.direction == "long" else delta < 0)
        if not delta_ok:
            reasons.append("delta is missing, wrong-sign, or below the routine floor")
        for field, maximum in (("quoteAsOf", 10_000), ("deltaAsOf", 120_000)):
            stamp = row.get(field)
            if not numeric(stamp) or not 0 <= at-stamp <= maximum:
                reasons.append(f"{field} is missing, stale or future-dated")
        if row.get("quoteSource") not in ("opra", "sim"):
            reasons.append("quote is not a current OPRA/sim observation")
        oi = row.get("openInterest")
        if policy.min_open_interest and (not numeric(oi) or oi < policy.min_open_interest):
            reasons.append("open interest does not meet reviewed liquidity requirement")
        candidates.append({"symbol": option.symbol, "expiry": option.expiry.isoformat(), "dte": dte,
                           "strike": option.strike, "delta": delta if numeric(delta) else None,
                           "bid": bid if numeric(bid) else None, "ask": ask if numeric(ask) else None,
                           "spreadPct": spread, "openInterest": oi if numeric(oi) else None,
                           "quoteAsOf": row.get("quoteAsOf") if numeric(row.get("quoteAsOf")) else None,
                           "deltaAsOf": row.get("deltaAsOf") if numeric(row.get("deltaAsOf")) else None,
                           "quoteSource": row.get("quoteSource"),
                           "eligible": not reasons, "reasons": reasons})
    candidates.sort(key=lambda c: (not c["eligible"], abs(c["dte"]-policy.target_dte),
                                    abs(abs(c["delta"])-policy.target_abs_delta) if c["delta"] is not None else 2,
                                    c["spreadPct"] if c["spreadPct"] is not None else 1000, c["symbol"]))
    return {"runId": plan.id, "asOfMs": at, "selected": next((c for c in candidates if c["eligible"]), None),
            "candidates": candidates, "policy": policy.model_dump(mode="json", by_alias=True),
            "placesOrders": False, "ranking": "Eligibility, distance to reviewed DTE, delta distance, spread, symbol."}


async def select_contract(engine, plan: CartelPlan, policy: ContractSelectionInput):
    if engine.options is None:
        raise ValueError("options service is unavailable")
    now = int(dt.datetime.now(dt.UTC).timestamp()*1000)
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
        quote = engine.quotes.get(symbol)
        snapshot = engine.options.snapshot_cached(symbol) or {}
        views.append({"symbol": symbol, "bid": quote.bid if quote else None, "ask": quote.ask if quote else None,
                      "quoteAsOf": (quote.source_ts or quote.ts) if quote else None,
                      "quoteSource": quote.source if quote else None,
                      "delta": (snapshot.get("greeks") or {}).get("delta"),
                      "deltaAsOf": (snapshot.get("greeksFieldAsOf") or {}).get("delta"),
                      "openInterest": row.get("open_interest")})
    result = rank_candidates(plan, policy, views, int(dt.datetime.now(dt.UTC).timestamp()*1000))
    result.update(searchedExpiries=searched, structuralCandidates=len(structural), refreshedCandidates=len(sampled),
                  warnings=warnings, searchComplete=not warnings and len(searched) == len(expiries) and len(sampled) == len(structural),
                  note="Selection covers refreshed candidates only; rerun preflight at the actual entry.")
    return result
