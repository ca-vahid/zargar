"""Cartel expression and shared-RiskGate preflight. Never submits an order.

The actual fire adapter must rerun this read after its final slow operation;
preflight is evidence at an instant, not an authorization token for later prices.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Literal

from pydantic import Field, model_validator

from ...execution.sizing import size_by_budget, size_by_risk
from ...fx import MAX_RATE_AGE_MS, currency_for_symbol, fx_pair_symbol
from ...marketstructure.sessions import ET, session_bounds
from ...models import Portfolio
from ...options.occ import parse
from ...orders import OrderIntent
from .loss import loss_gate
from .plans import CartelPlan
from .readiness import execution_readiness
from .service import WireModel


class ExecutionInput(WireModel):
    portfolio_id: str = Field(min_length=1, max_length=64)
    instrument: Literal["shares", "options"] = "options"
    mode: Literal["proposal", "auto"] = "proposal"
    contract_symbol: str | None = Field(default=None, max_length=32)
    budget: float = Field(gt=0, le=10_000_000)
    risk_pct: float = Field(default=1, gt=0, le=10)
    max_units: int = Field(default=10, ge=1, le=1_000_000)
    max_premium: float | None = Field(default=None, gt=0)
    overnight_ack: bool = False
    allow_live: bool = False
    min_abs_delta: float = Field(default=.25, ge=0, le=1)
    delta_exception_reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def delta_override(self):
        if self.instrument == "options" and self.min_abs_delta < .25 and not self.delta_exception_reason.strip():
            raise ValueError("a delta threshold below Sean's routine 0.25 guidance needs an explicit exception reason")
        return self


async def preflight(engine, plan: CartelPlan, spec: ExecutionInput, *, client_kind="desktop", now_ms=None, clock=None):
    read_clock = clock or (lambda: now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp()*1000))
    at = read_clock()
    today = dt.datetime.fromtimestamp(at/1000, ET).date()
    checks = []

    def check(name, passed, reason):
        checks.append({"name": name, "passed": bool(passed), "reason": reason})

    check("plan_horizon", at >= plan.created_at and at < session_bounds(plan.last_session.isoformat())[1],
          "Plan must exist and its final session must not have closed.")
    check("technique_pause", not engine.settings.get("techniques.options_cartel.paused", False),
          "Cartel pause stops new entries.")
    check("technique_enabled", engine.settings.get("techniques.options_cartel.enabled", True),
          "Cartel must be enabled for entry evaluation.")
    async with engine.sf() as session:
        portfolio = await session.get(Portfolio, spec.portfolio_id)
    if portfolio is None:
        raise ValueError("portfolio not found")
    real = portfolio.kind in ("live", "paper")
    check("live_acknowledgements", not real or (spec.allow_live
          and (spec.mode != "auto" or engine.settings.get("techniques.options_cartel.allow_live_auto", False))
          and engine.settings.get("trading.mode") == "live"),
          "Real accounts require Live workspace and acknowledgement; auto also requires technique permission.")
    check("book_and_global_halt", not engine.trading_halted(spec.portfolio_id),
          "Global and portfolio entry halts must be clear.")
    check("position_reconciliation_halt", not engine.position_manager.entries_halted(plan.symbol),
          "Shared position reconciliation must allow new entries on this symbol.")
    readiness = await execution_readiness(engine, spec.portfolio_id, plan.symbol)
    check("execution_reconciled", readiness["passed"],
          "; ".join(b["reason"] for b in readiness["blockers"]) or "Prior Cartel execution is reconciled.")
    losses = await loss_gate(engine, spec.portfolio_id, now_ms=read_clock())
    check("technique_daily_loss", losses["passed"], losses["reason"])
    order_symbol = plan.symbol
    if spec.instrument == "shares":
        check("no_share_shorting", plan.direction == "long", "Bearish ideas must use long puts, not short shares.")
    else:
        contract = parse(spec.contract_symbol)
        if contract is None:
            raise ValueError("choose a valid OCC option contract")
        order_symbol = contract.symbol
        check("contract_underlying", contract.underlying == plan.symbol, "Contract must match the plan underlying.")
        check("contract_direction", contract.right == ("C" if plan.direction == "long" else "P"),
              "Bullish plans buy calls; bearish plans buy puts.")
        minimum_dte = max(1, int(engine.settings.get("execution.min_dte", 1)))
        check("expiry_floor", contract.dte(today) > minimum_dte, "Entry must leave time above the managed-position expiry floor.")
        check("overnight_ack", spec.overnight_ack, "Multi-day options require acknowledgement of app-managed overnight protection.")
    quote = engine.quotes.get(order_symbol)
    # Subscribe only when needed. No connection or key configuration is changed.
    if quote is None and engine.started:
        await engine.ensure_symbol(order_symbol)
        quote = engine.quotes.get(order_symbol)
    at = read_clock()
    delta, delta_age = None, None
    valid_delta = False
    if spec.instrument == "options":
        snapshot = engine.options.snapshot_cached(order_symbol) if engine.options is not None else None
        if snapshot:
            delta = (snapshot.get("greeks") or {}).get("delta")
            measured = (snapshot.get("greeksFieldAsOf") or {}).get("delta")
            delta_age = (at-measured)/1000 if isinstance(measured, (int, float)) \
                and not isinstance(measured, bool) and math.isfinite(measured) else None
        valid_delta = isinstance(delta, (int, float)) and not isinstance(delta, bool) \
            and math.isfinite(delta) and -1 <= delta <= 1
        fresh_delta = valid_delta and delta_age is not None and 0 <= delta_age <= 120
        check("fresh_delta", fresh_delta,
              "Option delta needs its own recent observation timestamp; refreshed quotes do not refresh Greeks.")
        check("delta_direction", valid_delta and (delta > 0 if plan.direction == "long" else delta < 0),
              "Call delta must be positive and put delta negative.")
        check("delta_floor", valid_delta and abs(delta) >= spec.min_abs_delta,
              "Routine absolute delta floor is 0.25 (S15); lower reviewed exceptions remain explicit.")
    check("horizon_after_refresh", at < session_bounds(plan.last_session.isoformat())[1],
          "Plan horizon must remain open after data refresh.")
    age = (at-(quote.source_ts or quote.ts))/1000 if quote else None
    max_age = float(engine.settings.get("risk.stale_quote_seconds", 10))
    fresh = quote is not None and age is not None and 0 <= age <= max_age and not quote.delayed
    check("fresh_quote", fresh, "Sizing requires a current, non-delayed bid/ask for the chosen vehicle.")
    bid, ask = (quote.bid, quote.ask) if quote else (0, 0)
    valid_price = all(math.isfinite(v) for v in (bid, ask)) and 0 < bid <= ask
    check("two_sided_quote", valid_price, "A finite positive uncrossed bid/ask is required.")
    check("share_stop_geometry", spec.instrument != "shares" or ask > plan.invalidation,
          "The current share entry price must be above its reviewed protective stop.")
    check("premium_limit", spec.instrument != "options" or spec.max_premium is None or ask <= spec.max_premium,
          "Option ask must be within the reviewed premium limit.")
    equity = float(await engine.positions.equity(spec.portfolio_id))
    check("positive_equity", math.isfinite(equity) and equity > 0, "Sizing requires positive current account equity.")
    currency = currency_for_symbol(order_symbol)
    base_currency = portfolio.base_currency.upper()
    fx = engine.positions.fx.rate(currency, base_currency)
    fx_valid = fx is not None and math.isfinite(fx) and fx > 0
    if currency != base_currency:
        fx_quote = engine.quotes.get(fx_pair_symbol(currency, base_currency)) \
            or engine.quotes.get(fx_pair_symbol(base_currency, currency))
        fx_valid = fx_valid and fx_quote is not None and 0 <= at-fx_quote.ts < MAX_RATE_AGE_MS
    check("currency_conversion", fx_valid, "Cross-currency sizing requires a current FX rate; no 1:1 fallback.")
    qty = 0
    multiplier = 100 if spec.instrument == "options" else 1
    # Options reserve the full debit as risk; an underlying stop does not imply
    # a reliable option-loss percentage across overnight gaps, IV and theta.
    risk_unit = ask*multiplier if spec.instrument == "options" else abs(ask-plan.invalidation)
    if fresh and valid_price and fx_valid and math.isfinite(equity) and equity > 0 and risk_unit > 0:
        qty = min(size_by_budget(spec.budget, ask*multiplier*fx, max_units=spec.max_units),
                  size_by_risk(equity, spec.risk_pct, risk_unit*fx, max_units=spec.max_units))
    check("affordable_quantity", qty >= 1, "Both cash budget and risk budget must fund at least one whole unit.")
    intent = None
    risk = None
    if all(c["passed"] for c in checks):
        intent = OrderIntent(portfolio_id=spec.portfolio_id, symbol=order_symbol,
                             sec_type="OPT" if spec.instrument == "options" else "STK", side="BUY",
                             qty=qty, order_type="LMT", limit_price=ask, tif="DAY", source="technique",
                             technique_id="options_cartel", tags=[f"cartel_run:{plan.id}"],
                             dry_run=True, client=client_kind)
        risk = (await engine.risk.evaluate(intent, portfolio)).to_dict()
    return {"runId": plan.id, "asOfMs": at, "passed": all(c["passed"] for c in checks)
            and bool(risk and risk["passed"]), "checks": checks, "risk": risk,
            "expression": {"symbol": order_symbol, "instrument": spec.instrument, "quantity": qty,
                           "bid": bid, "ask": ask, "quoteAgeSeconds": age,
                           "notional": qty*ask*multiplier if valid_price else None,
                           "quoteCurrency": currency, "budgetCurrency": base_currency, "fxRate": fx,
                           "delta": delta if valid_delta else None,
                           "deltaAgeSeconds": delta_age, "minAbsDelta": spec.min_abs_delta,
                           "deltaExceptionReason": spec.delta_exception_reason or None,
                           "riskBasis": "full option debit" if spec.instrument == "options" else "current share ask to reviewed stop distance"},
            "intent": intent.model_dump() if intent else None, "placesOrders": False,
            "executionReadiness": readiness, "dailyLoss": losses,
            "note": "Preflight only. Entry trigger, price, sizing, halts and RiskGate must be rechecked at submission."}
