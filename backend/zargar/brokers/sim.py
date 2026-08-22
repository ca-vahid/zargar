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
            bars.append(Bar(symbol=symbol, tf="1m", ts=ts,
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


class SimExecutor(Executor):
    def __init__(
        self,
        latency_ms: int = 120,
        slippage_bps: float = 2.0,
        size_impact_bps: float = 5.0,   # extra slippage when qty exceeds displayed size
    ) -> None:
        super().__init__()
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
            self._working[order.id] = _Working(order=order, eligible_at=now_ms() + self._latency_ms)
            if order.oca_group:
                self._oca.setdefault(order.oca_group, set()).add(order.id)
        await self.emit(ExecReport(kind="accepted", order_id=order.id))

    async def cancel(self, order_id: str) -> None:
        async with self._lock:
            w = self._working.pop(order_id, None)
            if w and w.order.oca_group:
                self._oca.get(w.order.oca_group, set()).discard(order_id)
        if w is not None:
            await self.emit(ExecReport(kind="cancelled", order_id=order_id, reason="user_cancelled"))

    async def on_quote(self, q: Quote) -> None:
        """Check working orders against a fresh quote."""
        now = now_ms()
        fills: list[tuple[_Working, float]] = []
        cancels: list[str] = []
        async with self._lock:
            for oid, w in list(self._working.items()):
                o = w.order
                if o.symbol != q.symbol or now < w.eligible_at or q.halted:
                    continue
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
        for sibling in cancels:
            await self.emit(ExecReport(kind="cancelled", order_id=sibling, reason="oca_sibling_filled"))
        for w, price in fills:
            o = w.order
            await self.emit(ExecReport(
                kind="fill", order_id=o.id, fill_qty=o.qty, fill_price=round(price, 4),
                commission=self._commission(o),
            ))

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
        if o.sec_type == "OPT":
            return round(0.99 * o.qty + 0.05 * o.qty, 2)  # Webull CA-like: per contract + reg fees
        return round(min(max(1.0, 0.005 * o.qty), 0.01 * o.qty * 200), 2)
