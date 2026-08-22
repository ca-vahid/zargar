"""RiskGate: the mandatory pre-trade check pipeline.

Every order — manual or automated, live or simulated — passes through here
before routing. Each check produces a named verdict; the full list is journaled
so there is always an answer to "why was this allowed/blocked".
"""
from __future__ import annotations

import datetime as dt
import time
from collections import deque
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from .domain import OrderSide, OrderType
from .options import occ

ET = ZoneInfo("America/New_York")


@dataclass(slots=True)
class RiskCheck:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(slots=True)
class RiskVerdict:
    passed: bool
    checks: list[RiskCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[RiskCheck]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "checks": [c.to_dict() for c in self.checks]}


class HaltState:
    """Soft kill switch. Engaged state survives restarts via the settings table."""

    def __init__(self) -> None:
        self.engaged = False
        self.reason = ""
        self.ts: float = 0.0

    def engage(self, reason: str) -> None:
        self.engaged = True
        self.reason = reason
        self.ts = time.time()

    def release(self) -> None:
        self.engaged = False
        self.reason = ""
        self.ts = time.time()

    def to_dict(self) -> dict:
        return {"engaged": self.engaged, "reason": self.reason, "ts": self.ts}


def is_us_market_hours(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(tz=ET)
    now = now.astimezone(ET)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


class RiskGate:
    def __init__(self, settings, quote_cache, position_keeper, halt: HaltState) -> None:
        self._settings = settings
        self._quotes = quote_cache
        self._positions = position_keeper
        self._halt = halt
        self._recent: deque[tuple[float, str]] = deque(maxlen=500)  # (ts, dedupe_key)

    def note_submission(self, symbol: str, side: str, qty: float, order_type: str) -> None:
        self._recent.append((time.time(), f"{symbol}|{side}|{float(qty):g}|{order_type}"))

    async def evaluate(self, intent, portfolio) -> RiskVerdict:
        """intent: OrderManager's OrderIntent; portfolio: Portfolio row."""
        s = self._settings
        symbol = intent.symbol
        side = OrderSide(intent.side)
        qty = float(intent.qty)
        is_option = intent.sec_type == "OPT"
        mult = 100.0 if is_option else 1.0
        reduces = False

        # Reduce-only exits (a stop / flatten / trim) run a SAFETY-ONLY check
        # list: they must never be blocked by an entry cap, the order-rate or
        # duplicate window, or the daily-loss halt — those exist to stop you
        # opening risk, and an exit removes risk. The kill switch still applies
        # unless `risk.halt_allows_exits` is on (default), so a panic-halt can
        # still close positions.
        if getattr(intent, "reduce_only", False):
            return self._evaluate_reduce_only(intent, symbol, is_option)

        checks: list[RiskCheck] = []

        # 1. kill switch -----------------------------------------------------
        checks.append(RiskCheck(
            "kill_switch", not self._halt.engaged,
            "" if not self._halt.engaged else f"halted: {self._halt.reason}"))

        # 2. quote freshness / halt -------------------------------------------
        quote = self._quotes.get(symbol)
        stale_after = float(s.get("risk.stale_quote_seconds", 10))
        age = self._quotes.age_seconds(symbol)
        fresh = quote is not None and age <= stale_after
        checks.append(RiskCheck(
            "quote_fresh", fresh,
            f"no quote for {symbol}" if quote is None else f"quote age {age:.1f}s (max {stale_after:.0f}s)"))
        if quote is not None:
            checks.append(RiskCheck("not_halted", not quote.halted,
                                    "instrument is halted" if quote.halted else ""))

        ref_price = None
        if quote is not None and quote.mid > 0:
            ref_price = quote.mid
        if intent.limit_price:
            ref_price = ref_price or float(intent.limit_price)

        # 3. price collar -----------------------------------------------------
        collar = float(s.get("risk.price_collar_pct", 5.0))
        if intent.limit_price and is_option and quote is not None and (quote.mid > 0 or quote.last > 0):
            # options: measure against the mid (bid/ask is the market) and floor
            # the tolerance at a few ticks — a 1-cent move on a 2-cent premium is
            # "50%" yet entirely normal
            ref = quote.mid if (quote.bid > 0 and quote.ask > 0) else quote.last
            tol = max(ref * collar / 100, 0.05, (quote.ask - quote.bid) if quote.ask > quote.bid > 0 else 0.0)
            dev = abs(float(intent.limit_price) - ref)
            checks.append(RiskCheck(
                "price_collar", dev <= tol + 1e-9,
                f"limit {intent.limit_price} is {dev:.2f} from mid {ref:.2f} (max {tol:.2f})"
                if dev > tol + 1e-9 else ""))
        elif intent.limit_price and quote is not None and quote.last > 0:
            dev = abs(float(intent.limit_price) - quote.last) / quote.last * 100
            checks.append(RiskCheck(
                "price_collar", dev <= collar,
                f"limit {intent.limit_price} is {dev:.1f}% from last {quote.last:.2f} (max {collar:.1f}%)"))

        # position context ------------------------------------------------------
        pos_qty = self._positions.position_qty(intent.portfolio_id, symbol, intent.sec_type)
        signed = qty if side == OrderSide.BUY else -qty
        new_qty = pos_qty + signed
        equity = await self._positions.equity(intent.portfolio_id)
        if ref_price:
            old_notional = abs(pos_qty) * ref_price * mult
            new_notional = abs(new_qty) * ref_price * mult
            reduces = new_notional < old_notional

        # 4. shorting ------------------------------------------------------------
        allow_short = bool(s.get("risk.allow_short", False))
        goes_short = new_qty < -1e-9
        checks.append(RiskCheck(
            "short_allowed", allow_short or not goes_short,
            f"order would result in short position of {new_qty:g} {symbol}" if goes_short else ""))

        # 5. options -----------------------------------------------------------
        if is_option:
            checks.append(RiskCheck("options_allowed", bool(s.get("risk.allow_options", True)),
                                    "options trading disabled in settings"))
            if side == OrderSide.BUY and ref_price and equity > 0:
                premium = qty * ref_price * mult
                cap_pct = float(s.get("risk.max_option_premium_pct", 5.0))
                ok = premium <= equity * cap_pct / 100
                checks.append(RiskCheck(
                    "option_premium_cap", ok,
                    f"premium ${premium:,.0f} exceeds {cap_pct:.1f}% of equity (${equity:,.0f})"
                    if not ok else ""))
            checks.append(RiskCheck(
                "no_naked_short_option", not (goes_short and is_option),
                "naked short options are blocked" if (goes_short and is_option) else ""))
            checks.extend(self._option_checks(intent, quote, ref_price, qty, side, reduces))

        # 6/7. per-position and gross caps (only when increasing exposure) -----
        if ref_price and not reduces:
            max_notional = float(s.get("risk.max_position_notional", 1000.0))
            new_notional = abs(new_qty) * ref_price * mult
            checks.append(RiskCheck(
                "max_position_notional", new_notional <= max_notional,
                f"resulting position ${new_notional:,.0f} exceeds cap ${max_notional:,.0f}"
                if new_notional > max_notional else ""))
            if equity > 0:
                max_pct = float(s.get("risk.max_position_pct", 10.0))
                pct = new_notional / equity * 100
                checks.append(RiskCheck(
                    "max_position_pct", pct <= max_pct,
                    f"resulting position {pct:.1f}% of equity exceeds {max_pct:.1f}%"
                    if pct > max_pct else ""))
                gross = await self._positions.gross_exposure(intent.portfolio_id)
                added = new_notional - abs(pos_qty) * ref_price * mult
                max_gross_pct = float(s.get("risk.max_gross_exposure_pct", 100.0))
                gpct = (gross + max(0, added)) / equity * 100
                checks.append(RiskCheck(
                    "max_gross_exposure", gpct <= max_gross_pct,
                    f"gross exposure would be {gpct:.0f}% of equity (max {max_gross_pct:.0f}%)"
                    if gpct > max_gross_pct else ""))

        # 8. order rate --------------------------------------------------------
        now = time.time()
        per_min = int(s.get("risk.max_orders_per_minute", 10))
        recent = sum(1 for ts, _ in self._recent if now - ts <= 60)
        checks.append(RiskCheck(
            "order_rate", recent < per_min,
            f"{recent} orders in the last 60s (max {per_min})" if recent >= per_min else ""))

        # 9. duplicate ------------------------------------------------------------
        window = float(s.get("risk.duplicate_window_seconds", 10))
        key = f"{symbol}|{side.value}|{qty:g}|{intent.order_type}"
        dup = any(k == key and now - ts <= window for ts, k in self._recent)
        checks.append(RiskCheck(
            "duplicate_order", not dup,
            f"identical order submitted within the last {window:.0f}s" if dup else ""))

        # 10. daily loss halt ---------------------------------------------------
        loss_pct = await self._positions.daily_loss_pct(intent.portfolio_id)
        halt_pct = float(s.get("risk.daily_loss_halt_pct", 3.0))
        breached = loss_pct is not None and loss_pct <= -abs(halt_pct)
        checks.append(RiskCheck(
            "daily_loss_limit", not breached,
            f"daily P&L {loss_pct:.2f}% breaches -{halt_pct:.1f}% halt" if breached else ""))

        # 11. market hours (live/paper only, if configured; options have no
        #     extended session, so for them it is always enforced) ---------------
        if portfolio.kind in ("live", "paper") and (
                is_option or bool(s.get("risk.require_market_hours", False))):
            open_now = is_us_market_hours()
            checks.append(RiskCheck("market_hours", open_now,
                                    "outside regular trading hours" if not open_now else ""))

        return RiskVerdict(passed=all(c.passed for c in checks), checks=checks)

    def _evaluate_reduce_only(self, intent, symbol: str, is_option: bool) -> RiskVerdict:
        """Safety-only checks for an exit that reduces exposure. The kill switch
        applies only if `risk.halt_allows_exits` is off; instrument-halt and a
        parseable option symbol are the only hard blocks."""
        s = self._settings
        checks: list[RiskCheck] = []
        halt_allows_exits = bool(s.get("risk.halt_allows_exits", True))
        checks.append(RiskCheck(
            "kill_switch", (not self._halt.engaged) or halt_allows_exits,
            "" if (not self._halt.engaged) or halt_allows_exits
            else f"halted and risk.halt_allows_exits is off: {self._halt.reason}"))
        quote = self._quotes.get(symbol)
        if quote is not None:
            checks.append(RiskCheck("not_halted", not quote.halted,
                                    "instrument is halted" if quote.halted else ""))
        if is_option:
            o = occ.parse(symbol)
            checks.append(RiskCheck("option_symbol", o is not None,
                                    "" if o else f"{symbol} is not a valid OCC option symbol"))
        return RiskVerdict(passed=all(c.passed for c in checks), checks=checks)

    def _option_checks(self, intent, quote, ref_price, qty: float, side: OrderSide,
                       reduces: bool) -> list[RiskCheck]:
        """Contract-specific checks: expiry, size, absolute premium, spread."""
        s = self._settings
        out: list[RiskCheck] = []
        o = occ.parse(intent.symbol)
        out.append(RiskCheck("option_symbol", o is not None,
                             "" if o else f"{intent.symbol} is not a valid OCC option symbol"))
        if o is None:
            return out
        dte = o.dte()
        if dte < 0:
            out.append(RiskCheck("option_not_expired", False,
                                 f"{o.display()} expired on {o.expiry.isoformat()}"))
        elif dte == 0:
            allow = bool(s.get("risk.allow_0dte", True))
            out.append(RiskCheck("option_not_expired", allow,
                                 "" if allow else "0DTE contracts disabled (risk.allow_0dte)"))
        else:
            out.append(RiskCheck("option_not_expired", True, ""))
        max_contracts = int(s.get("risk.max_option_contracts", 10))
        out.append(RiskCheck(
            "option_max_contracts", qty <= max_contracts or reduces,
            f"{qty:g} contracts exceeds per-order cap {max_contracts}"
            if (qty > max_contracts and not reduces) else ""))
        if side == OrderSide.BUY and ref_price and not reduces:
            premium = qty * ref_price * 100.0
            cap = float(s.get("risk.max_option_premium_notional", 1000.0))
            out.append(RiskCheck(
                "option_premium_notional", premium <= cap,
                f"premium ${premium:,.0f} exceeds per-order cap ${cap:,.0f}" if premium > cap else ""))
        if quote is not None and quote.bid > 0 and quote.ask > 0:
            spread = quote.spread_pct
            max_spread = float(s.get("risk.max_option_spread_pct", 10.0))
            wide = spread > max_spread
            is_mkt = intent.order_type == OrderType.MKT.value
            out.append(RiskCheck(
                "option_spread", not (wide and is_mkt),
                (f"bid/ask spread {spread:.1f}% exceeds {max_spread:.0f}%"
                 + (" - market order rejected, use a limit" if is_mkt else " (limit order, warning only)"))
                if wide else ""))
        return out
