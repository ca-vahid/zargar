"""Simulated market: quote generator + local fill engine.

The quote feed produces a plausible random-walk market (24/7, so the app is
always alive in development). The executor fills risk-approved orders against
the current quote stream with conservative semantics:

  - market orders fill at the opposite touch plus slippage (worse with size),
    after a small simulated latency;
  - limit orders fill only when the far side reaches the limit;
  - stops trigger on last trade price, then behave as market/limit;
  - OCA siblings are cancelled on fill (bracket support).

This intentionally errs pessimistic — a mock mode that flatters you is worse
than none.
"""
from __future__ import annotations

import asyncio
import contextlib
import math
import random
import time
from dataclasses import dataclass, field

from ..domain import Bar, OrderSide, OrderType, Quote, now_ms
from .base import BrokerOrder, ExecReport, Executor, QuoteFeed


def option_session_open(ts_ms: int) -> bool:
    """EOD-05 (2026-09-14): a listed equity option can only trade in its
    venue's session — 09:30–16:00 ET on a trading day for every class this
    desk handles (Cboe's 07:30 extended session covers designated index/ETF
    classes only and restricts order types; Alpaca rejects extended-hours
    option orders). A Practice fill outside that window is not market
    evidence: the APLD Oct 30C "sold" at 04:01 ET on an underlying quote
    stop. The intent is kept working and fills when the session opens."""
    from zoneinfo import ZoneInfo
    from ..marketstructure.market_calendar import is_early_close, is_trading_day
    import datetime as _dt
    t = _dt.datetime.fromtimestamp(ts_ms / 1000, ZoneInfo("America/New_York"))
    if not is_trading_day(t.date()):
        return False
    m = t.hour * 60 + t.minute
    end = 13 * 60 if is_early_close(t.date()) else 16 * 60
    return 9 * 60 + 30 <= m < end


# F-HOLD-01 (2026-09-17): the SAME window gates simulated SHARE fills and stop triggers.
# A resting GTC share stop at a real venue triggers on regular-session prints unless the
# order was explicitly placed for extended hours; the sim used to trigger on ANY quote -
# the quarantined ab shadow book's AFRM stop (65.00) "filled" 27 sh @ 44.99 at 03:59:54 ET
# on a pre-market placeholder quote (bid 45.00 / ask 75.00, no source). Practice books
# share this executor, so a Practice share stop could have done the same.
regular_session_open = option_session_open

# Familiar tickers get familiar prices; anything else gets a stable hash price.
KNOWN_PRICES = {
    "AAPL": 232.0, "MSFT": 445.0, "NVDA": 128.0, "AMZN": 186.0, "GOOG": 172.0,
    "META": 512.0, "TSLA": 244.0, "AMD": 158.0, "SPY": 552.0, "QQQ": 478.0,
    "IWM": 218.0, "SHOP.TO": 98.0, "TD.TO": 82.0, "ENB.TO": 49.0, "SU.TO": 53.0,
    "BN.TO": 62.0, "CNQ.TO": 47.0, "XIU.TO": 34.0,
}


def seed_price(symbol: str) -> float:
    if symbol in KNOWN_PRICES:
        return KNOWN_PRICES[symbol]
    h = abs(hash(symbol)) % 10_000
    return round(5.0 + (h / 10_000) * 495.0, 2)


@dataclass
class SymState:
    price: float
    sigma_per_min: float          # fractional stddev per minute
    drift_per_min: float
    volume: int = 0
    spread_bps: float = 4.0
    rng: random.Random = field(default_factory=random.Random)


class SimQuoteFeed(QuoteFeed):
    def __init__(
        self,
        on_quote,                              # Callable[[Quote], None]
        tick_interval: float = 0.35,
        seed: int = 0,
    ) -> None:
        self._on_quote = on_quote
        self._tick_interval = tick_interval
        self._seed = seed
        self._symbols: dict[str, SymState] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def connected(self) -> bool:
        return self._running

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    async def watch(self, symbol: str) -> None:
        symbol = symbol.upper()
        if symbol in self._symbols:
            return
        rng = random.Random(self._seed ^ hash(symbol)) if self._seed else random.Random()
        price = seed_price(symbol)
        vol = rng.uniform(0.0004, 0.0016)  # 0.04%–0.16% per minute
        self._symbols[symbol] = SymState(
            price=price,
            sigma_per_min=vol,
            drift_per_min=rng.uniform(-0.00003, 0.00005),
            spread_bps=rng.uniform(2.0, 12.0),
            rng=rng,
        )

    def synthesize_history(self, symbol: str, minutes: int = 2 * 24 * 60) -> list[Bar]:
        """Walk 1m closes backward from the current seed price so history ends
        exactly where the live feed begins."""
        symbol = symbol.upper()
        st = self._symbols[symbol]
        rng = random.Random(self._seed ^ hash(symbol) ^ 0xBAA5) if self._seed else random.Random()
        end_bucket = (now_ms() // 60_000) * 60_000
        closes = [st.price]
        for _ in range(minutes):
            z = rng.gauss(0, 1)
            prev = closes[-1] / math.exp(st.sigma_per_min * z + st.drift_per_min)
            closes.append(max(0.5, prev))
        closes.reverse()  # oldest → newest, ending at current price
        bars: list[Bar] = []
        for i in range(minutes):
            o, c = closes[i], closes[i + 1]
            hi = max(o, c) * (1 + abs(rng.gauss(0, st.sigma_per_min / 3)))
            lo = min(o, c) * (1 - abs(rng.gauss(0, st.sigma_per_min / 3)))
            ts = end_bucket - (minutes - i) * 60_000
            vol = int(abs(rng.gauss(12_000, 8_000))) + 500
            bars.append(Bar(symbol=symbol, tf="1m", ts=ts, source="sim",
                            open=round(o, 4), high=round(hi, 4), low=round(lo, 4),
                            close=round(c, 4), volume=vol))
        return bars

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run(), name="sim-quote-feed")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        # per-tick sigma scaled from per-minute sigma
        while self._running:
            dt_min = self._tick_interval / 60.0
            for symbol, st in self._symbols.items():
                z = st.rng.gauss(0, 1)
                st.price = max(0.5, st.price * math.exp(
                    st.sigma_per_min * math.sqrt(dt_min) * z + st.drift_per_min * dt_min))
                if st.rng.random() < 0.002:  # occasional small jump
                    st.price *= math.exp(st.rng.gauss(0, st.sigma_per_min * 6))
                half_spread = st.price * st.spread_bps / 10_000 / 2
                tick = 0.01 if st.price >= 1 else 0.0001
                bid = max(tick, round((st.price - half_spread) / tick) * tick)
                ask = max(bid + tick, round((st.price + half_spread) / tick) * tick)
                st.volume += int(abs(st.rng.gauss(80, 60)))
                self._on_quote(Quote(
                    symbol=symbol,
                    bid=round(bid, 4), ask=round(ask, 4), last=round(st.price, 4),
                    bid_size=int(abs(st.rng.gauss(300, 200))) + 100,
                    ask_size=int(abs(st.rng.gauss(300, 200))) + 100,
                    volume=st.volume,
                ))
            await asyncio.sleep(self._tick_interval)


@dataclass
class _Working:
    order: BrokerOrder
    eligible_at: int          # epoch ms — simulated submit latency
    triggered: bool = False   # for stop orders
    waiting_reason: str = ""


class SimExecutor(Executor):
    def __init__(
        self,
        latency_ms: int = 120,
        slippage_bps: float = 2.0,
        size_impact_bps: float = 5.0,   # extra slippage when qty exceeds displayed size
        settings=None,                  # engine settings (fee schedule); None = Webull CA defaults
        synthetic_quotes: bool = False,
        option_sessions: bool = True,   # EOD-05: options fill only in an eligible venue session
        stock_sessions: bool = False,   # F-HOLD-01: shares fill / stops trigger only in the regular session (the engine turns it ON from config)
        max_spread_pct: float = 0.0,    # F-HOLD-01: a share quote wider than this (spread / mid) cannot price a fill (engine: 5%)
        max_option_spread_pct: float = 0.0,   # EM 2026-09-18 (ORCL 148C): an OPENING option order cannot be priced by a quote
                                              # wider than this (spread / mid); 0 = off (proposal - activation is a user decision).
                                              # ED-01: keyed on the position-derived option_action - closing / reducing orders
                                              # (SELL_TO_CLOSE, BUY_TO_CLOSE) and orders with UNKNOWN intent are never capped.
        clock=None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self.synthetic_quotes = synthetic_quotes
        self._option_sessions = bool(option_sessions)
        self._stock_sessions = bool(stock_sessions)
        self._max_spread_pct = float(max_spread_pct or 0.0)
        self._max_option_spread_pct = float(max_option_spread_pct or 0.0)
        self.clock = clock or (lambda: now_ms())
        self._working: dict[str, _Working] = {}
        self._oca: dict[str, set[str]] = {}
        self._latency_ms = latency_ms
        self._slippage_bps = slippage_bps
        self._size_impact_bps = size_impact_bps
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return True

    @property
    def working_count(self) -> int:
        return len(self._working)

    async def submit(self, order: BrokerOrder) -> None:
        async with self._lock:
            self._working[order.id] = _Working(order=order, eligible_at=self.clock() + self._latency_ms)
            if order.oca_group:
                self._oca.setdefault(order.oca_group, set()).add(order.id)
        await self.emit(ExecReport(kind="accepted", order_id=order.id))

    async def restore(self, order: BrokerOrder) -> None:
        """Put an order that was ACCEPTED by a previous process back in the book
        WITHOUT a new 'accepted' report (the manager already has it). A restart
        used to empty the book silently: resting stops stopped protecting and
        entries could never fill or cancel (PLATFORM-RULES 2026-09-02)."""
        async with self._lock:
            if order.id in self._working:
                return
            self._working[order.id] = _Working(order=order, eligible_at=self.clock())
            if order.oca_group:
                self._oca.setdefault(order.oca_group, set()).add(order.id)

    # native multi-leg (NEXT-GAPS M2): the sim "venue" accepts a spread as one
    # combined order; each leg then fills off its own contract quote at its leg
    # price — close enough to an atomic venue for practice/testing purposes.
    supports_mleg = True

    async def submit_mleg(self, orders: list[BrokerOrder], *, net_limit: float,
                          price_effect: str, gid: str) -> None:
        for o in orders:
            await self.submit(o)

    async def cancel(self, order_id: str) -> bool:
        """True when the order was in the book (a 'cancelled' report follows);
        False when this executor never held it - e.g. it was accepted by a
        previous process and lost in a restart - so the manager can close it."""
        async with self._lock:
            w = self._working.pop(order_id, None)
            if w and w.order.oca_group:
                self._oca.get(w.order.oca_group, set()).discard(order_id)
        if w is not None:
            await self.emit(ExecReport(kind="cancelled", order_id=order_id, reason="user_cancelled"))
            return True
        return False

    async def on_quote(self, q: Quote) -> None:
        """Check working orders against a fresh quote."""
        now = self.clock()
        fills: list[tuple[_Working, float]] = []
        cancels: list[str] = []
        waiting = []
        async with self._lock:
            for oid, w in list(self._working.items()):
                o = w.order
                if o.symbol != q.symbol or now < w.eligible_at or q.halted:
                    continue
                sec = str(getattr(o, "sec_type", "") or "").upper()
                if self._option_sessions and sec == "OPT" and not option_session_open(now):
                    continue                       # EOD-05: resting, not filled — no session
                if self._stock_sessions and sec != "OPT" and not getattr(o, "outside_rth", False) \
                        and not regular_session_open(now):
                    # F-HOLD-01: a share order (stop, market or limit) placed for the regular
                    # session rests outside it - no pre-market trigger, no after-hours fill
                    reason = "Share orders fill and stops trigger only in the regular session (09:30-16:00 ET)"
                    if reason != w.waiting_reason:
                        waiting.append(ExecReport(kind="fill_waiting", order_id=o.id, reason=reason,
                            evidence=self.quote_evidence(q, now)))
                    w.waiting_reason = reason
                    continue
                reason = self.quote_rejection(o, q, now)
                if reason:
                    if reason != w.waiting_reason:
                        waiting.append(ExecReport(kind="fill_waiting", order_id=o.id, reason=reason,
                            evidence=self.quote_evidence(q, now)))
                    w.waiting_reason = reason
                    continue
                w.waiting_reason = ""
                price = self._try_fill(w, q)
                if price is not None:
                    fills.append((w, price))
                    del self._working[oid]
                    if o.oca_group:
                        group = self._oca.pop(o.oca_group, set())
                        group.discard(oid)
                        for sibling in group:
                            if sibling in self._working:
                                del self._working[sibling]
                                cancels.append(sibling)
        for report in waiting:
            await self.emit(report)
        for sibling in cancels:
            await self.emit(ExecReport(kind="cancelled", order_id=sibling, reason="oca_sibling_filled"))
        for w, price in fills:
            o = w.order
            await self.emit(ExecReport(
                kind="fill", order_id=o.id, ts=now, fill_qty=o.qty, fill_price=round(price, 4),
                commission=self._commission(o),
                evidence={**self.quote_evidence(q, now), "eligibleAt": w.eligible_at,
                    "slippageBps": self._slippage_bps, "sizeImpactBps": self._size_impact_bps},
            ))

    def quote_rejection(self, order, q, at):
        if not all(math.isfinite(v) for v in (q.bid, q.ask, q.ts, q.source_ts, q.bid_size, q.ask_size)) or not 0 < q.bid <= q.ask or min(q.bid_size, q.ask_size) < 0:
            return "A finite uncrossed two-sided quote is required for a simulated fill"
        if getattr(q, "transform", "") or str(q.source or "").startswith("derived:"):
            return ("Locally derived prices cannot price a simulated fill "
                    f"({q.transform or 'derived'} from {getattr(q, 'raw_source', '') or 'unknown'}; raw venue quote preserved apart)")
        if q.delayed or q.source == "chain":
            return "Delayed quotes cannot price simulated fills"
        if not 0 <= at-q.ts <= 15_000:
            return "Quote receipt is stale or future-dated"
        if order.sec_type != "OPT" and self._max_spread_pct > 0:
            mid = (q.bid + q.ask) / 2.0
            if mid > 0 and (q.ask - q.bid) / mid > self._max_spread_pct:
                # F-HOLD-01: a 45.00 / 75.00 "quote" is a placeholder book, not a market -
                # it cannot trigger a stop or price a fill (waits for a plausible quote)
                return (f"Quote spread implausible for a simulated share fill "
                        f"(bid {q.bid:.2f} / ask {q.ask:.2f} = {100 * (q.ask - q.bid) / mid:.0f}% of mid, "
                        f"limit {100 * self._max_spread_pct:.0f}%)")
        if (order.sec_type == "OPT" and self._max_option_spread_pct > 0
                and str(getattr(order, "option_action", "") or "").endswith("_TO_OPEN")):
            # ED-01 (2026-09-17): OPENING orders only - `option_action` is derived by the order manager from the book's
            # position (BUY_TO_CLOSE when short, SELL_TO_CLOSE when long), never from the side alone; a protective
            # stop / flatten / reducing exit (…_TO_CLOSE) or an order of unknown intent (None) is never capped here and
            # keeps every other quote-quality check below.
            mid = (q.bid + q.ask) / 2.0
            if mid > 0 and (q.ask - q.bid) / mid > self._max_option_spread_pct:
                # EM 2026-09-17: a resting 2.29 limit on ORCL 148C filled at 1.12 seven seconds after a 2.10/2.29 book, on an
                # OPRA snapshot of 0.76/1.12 (38% of mid) inconsistent with that minute's prints (2.48-2.88). Simulator
                # EVIDENCE validation only: the entry RESTS until a plausible book.
                return (f"Quote spread implausible for a simulated option entry "
                        f"(bid {q.bid:.2f} / ask {q.ask:.2f} = {100 * (q.ask - q.bid) / mid:.0f}% of mid, "
                        f"limit {100 * self._max_option_spread_pct:.0f}%)")
        if self.synthetic_quotes and q.source in ("", "sim"):
            return None
        if order.sec_type == "OPT" and (q.source not in ("opra", "ibkr") or q.source_ts <= 0):
            return "Option fill source identity or timestamp is unknown"
        if not 0 <= at-(q.source_ts or q.ts) <= 15_000:
            return "Quote source is stale or future-dated"
        return None

    def quote_evidence(self, q, at):
        tr = getattr(q, "transform", "") or ""
        result = {"policy": "sim_fill_v1", "syntheticMode": self.synthetic_quotes,
            "observedAt": at, "source": q.source, "sourceAt": q.source_ts or None,
            "receivedAt": q.ts, "symbol": q.symbol, "bid": q.bid, "ask": q.ask,
            "bidSize": q.bid_size, "askSize": q.ask_size, "delayed": q.delayed, "halted": q.halted,
            # E17-01: a transformed quote keeps its parents on the record (None when untouched)
            "transform": tr,
            "rawBid": getattr(q, "raw_bid", 0.0) if tr else None, "rawAsk": getattr(q, "raw_ask", 0.0) if tr else None,
            "rawSource": (getattr(q, "raw_source", "") or None) if tr else None,
            "rawSourceAt": (getattr(q, "raw_source_ts", 0) or None) if tr else None}
        return {key: None if isinstance(value, float) and not math.isfinite(value) else value for key, value in result.items()}

    def _try_fill(self, w: _Working, q: Quote) -> float | None:
        o = w.order
        if q.bid <= 0 or q.ask <= 0:
            return None
        buy = o.side == OrderSide.BUY

        if o.order_type in (OrderType.STP, OrderType.STP_LMT) and not w.triggered:
            assert o.stop_price is not None
            hit = q.last >= o.stop_price if buy else q.last <= o.stop_price
            if not hit:
                return None
            w.triggered = True

        if o.order_type == OrderType.MKT or (o.order_type == OrderType.STP and w.triggered):
            return self._market_price(o, q)

        # limit-style: LMT, or triggered STP_LMT
        limit = o.limit_price
        assert limit is not None
        if buy and q.ask <= limit:
            return min(q.ask, limit)
        if not buy and q.bid >= limit:
            return max(q.bid, limit)
        return None

    def _market_price(self, o: BrokerOrder, q: Quote) -> float:
        buy = o.side == OrderSide.BUY
        touch = q.ask if buy else q.bid
        displayed = q.ask_size if buy else q.bid_size
        slip_bps = self._slippage_bps
        if displayed > 0 and o.qty > displayed:
            slip_bps += self._size_impact_bps * min(4.0, o.qty / displayed - 1)
        slip = touch * slip_bps / 10_000
        return touch + slip if buy else max(0.01, touch - slip)

    def _commission(self, o: BrokerOrder) -> float:
        """Webull Canada's schedule (audited 2026-09-01, webull.ca/pricing):
        stocks/ETFs $0 commission; options $0.99 USD/contract + regulatory
        fees (~$0.05). All three are settings so the practice book can mirror
        whichever venue the user is heading to."""
        s = self._settings
        if o.sec_type == "OPT":
            per = float(s.get("options.fee_per_contract", 0.99)) if s else 0.99
            reg = float(s.get("sim.reg_fee_per_contract", 0.05)) if s else 0.05
            return round((per + reg) * o.qty, 2)
        flat = float(s.get("sim.stock_commission", 0.0)) if s else 0.0
        return round(flat, 2)
