"""Quote cache and bar aggregation.

The engine consumes unconflated quotes off the bus; the UI gets a conflated
stream (handled by the WS hub). Bars are built from quotes (1m base timeframe),
kept in memory per symbol and persisted so charts have history across restarts.
"""
from __future__ import annotations

import time
import asyncio
import logging
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import bus as topics
from .bus import Bus
from .domain import Bar, Quote, now_ms
from .models import BarRow

log = logging.getLogger("zargar.marketdata")

# tfs whose bars sit on fixed UTC-ms buckets; 1d bars are session-anchored and exempt
# from the alignment rule and the stub cleanup
INTRADAY_TF_MS: dict[str, int] = {}

MINUTE_MS = 60_000
TF_MS = {"1m": MINUTE_MS, "5m": 5 * MINUTE_MS, "15m": 15 * MINUTE_MS, "1h": 60 * MINUTE_MS,
         "1d": 24 * 60 * MINUTE_MS}
INTRADAY_TF_MS.update({k: v for k, v in TF_MS.items() if k != "1d"})


class QuoteCache:
    def __init__(self, bus: Bus) -> None:
        self._bus = bus
        self._quotes: dict[str, Quote] = {}
        # per-symbol field overrides applied to every incoming quote — option
        # contracts get bid/ask from the (delayed) chain while `last` streams live
        self._overlays: dict[str, dict] = {}

    def on_quote(self, q: Quote) -> None:
        ov = self._overlays.get(q.symbol)
        if ov:
            for k, v in ov.items():
                setattr(q, k, v)
        self._quotes[q.symbol] = q
        self._bus.publish(topics.QUOTES, q)

    def set_overlay(self, symbol: str, **fields) -> None:
        """Override quote fields for a symbol (bid/ask/sizes) until cleared."""
        if not fields:
            self._overlays.pop(symbol, None)
            return
        self._overlays[symbol] = dict(fields)
        q = self._quotes.get(symbol)
        if q is not None:
            for k, v in fields.items():
                setattr(q, k, v)
            if "bid" in fields or "ask" in fields:
                # a refreshed bid/ask IS fresh information: the premium stop and the
                # risk gate judge freshness by `ts`, which the overlay never moved
                # (an option's quote used to go stale 180 s after it was first seen)
                q.ts = now_ms()

    def clear_overlay(self, symbol: str) -> None:
        self._overlays.pop(symbol, None)

    def get(self, symbol: str) -> Quote | None:
        return self._quotes.get(symbol)

    def all(self) -> dict[str, Quote]:
        return dict(self._quotes)

    def age_seconds(self, symbol: str) -> float:
        q = self._quotes.get(symbol)
        if q is None:
            return float("inf")
        return max(0.0, time.time() - q.ts / 1000)


class BarAggregator:
    """Builds 1m bars from the quote stream; higher timeframes are resampled on read.

    When a symbol is expected to deliver real exchange bars (Alpaca), a closed
    quote-sampled bar is HELD for a few seconds so the exchange bar for that
    minute can replace it before consumers see either — live consumers then
    trade on one bar per minute, the accurate one. Until 2026-08-26 the
    exchange bar always arrived after the sampled one had been published and
    the armer's per-minute dedupe dropped it, so the trading path never saw a
    correction (charts and the end-of-day replay did)."""

    def __init__(self, bus: Bus, max_bars: int = 3000) -> None:
        self._bus = bus
        self._max = max_bars
        self._bars: dict[str, deque[Bar]] = defaultdict(lambda: deque(maxlen=max_bars))
        self._forming: dict[str, Bar] = {}
        self._last_volume: dict[str, int] = {}
        self._hold_seconds = None            # () -> float; 0 = publish sampled bars at once
        self._expects_exchange = None        # (symbol) -> bool
        self._pending: dict[str, tuple[Bar, object]] = {}   # held sampled bar + timer handle
        self._early: dict[str, Bar] = {}     # exchange bar that arrived before the sampled minute rolled

    def configure(self, *, hold_seconds=None, expects_exchange=None) -> None:
        self._hold_seconds = hold_seconds
        self._expects_exchange = expects_exchange

    def _hold_for(self, symbol: str) -> float:
        if self._hold_seconds is None or self._expects_exchange is None:
            return 0.0
        try:
            return float(self._hold_seconds()) if self._expects_exchange(symbol) else 0.0
        except Exception:
            return 0.0

    def _publish(self, bar: Bar, source: str | None) -> None:
        msg = {"symbol": bar.symbol, "tf": "1m", "bar": bar}
        if source:
            msg["source"] = source
        self._bus.publish(topics.BARS, msg)

    def _close_sampled(self, symbol: str, forming: Bar) -> None:
        dq = self._bars[symbol]
        early = self._early.pop(symbol, None)
        if early is not None and early.ts == forming.ts:
            dq.append(early)                          # the exchange bar was already here
            self._publish(early, "exchange")
            return
        dq.append(forming)
        hold = self._hold_for(symbol)
        if hold > 0:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                handle = loop.call_later(hold, self._flush_pending, symbol, forming.ts)
                self._pending[symbol] = (forming, handle)
                return
        self._publish(forming, None)

    def _flush_pending(self, symbol: str, ts: int) -> None:
        p = self._pending.get(symbol)
        if p is not None and p[0].ts == ts:
            self._pending.pop(symbol, None)
            self._publish(p[0], None)                 # no exchange bar came: the sampled one stands

    def on_quote(self, q: Quote) -> None:
        price = q.last if q.last > 0 else q.mid
        if price <= 0:
            return
        bucket = (q.ts // MINUTE_MS) * MINUTE_MS
        vol_delta = max(0, q.volume - self._last_volume.get(q.symbol, q.volume))
        self._last_volume[q.symbol] = q.volume
        forming = self._forming.get(q.symbol)
        if forming is None or forming.ts != bucket:
            if forming is not None and forming.ts < bucket:
                self._close_sampled(q.symbol, forming)
            self._forming[q.symbol] = Bar(
                symbol=q.symbol, tf="1m", ts=bucket,
                open=price, high=price, low=price, close=price, volume=vol_delta,
            )
        else:
            forming.high = max(forming.high, price)
            forming.low = min(forming.low, price)
            forming.close = price
            forming.volume += vol_delta

    def seed(self, symbol: str, bars: list[Bar]) -> None:
        dq = self._bars[symbol]
        for b in bars:
            dq.append(b)
        if bars:
            self._last_volume.setdefault(symbol, 0)

    def ingest_exchange_bar(self, bar: Bar) -> None:
        """An authoritative completed 1-minute exchange bar (from the data feed's
        1m history), used to *correct* the bar we built by sampling quotes — real
        OHLC and real volume, which the relative-volume gate depends on. Overwrites
        the in-memory bar for that minute (or appends a minute we missed) and
        republishes so live consumers re-read accurate history; the still-forming
        minute is never touched, and same-minute DB writes conflict-ignore."""
        if bar.tf != "1m" or bar.close <= 0:
            return
        forming = self._forming.get(bar.symbol)
        if forming is not None and bar.ts >= forming.ts:
            if bar.ts == forming.ts:
                self._early[bar.symbol] = bar          # keep it: it replaces the sampled bar on the roll
            return                                   # don't clobber the live/forming minute
        dq = self._bars[bar.symbol]
        pending = self._pending.get(bar.symbol)
        held = pending is not None and pending[0].ts == bar.ts
        if held:
            pending[1].cancel()
            self._pending.pop(bar.symbol, None)
        for i in range(len(dq) - 1, -1, -1):
            if dq[i].ts == bar.ts:
                same = (dq[i].open, dq[i].high, dq[i].low, dq[i].close, dq[i].volume) == \
                       (bar.open, bar.high, bar.low, bar.close, bar.volume)
                if same and not held:
                    return                           # already accurate and already published
                dq[i] = bar
                self._publish(bar, "exchange")
                return
            if dq[i].ts < bar.ts:
                break
        if not dq or bar.ts > dq[-1].ts:
            dq.append(bar)
            self._publish(bar, "exchange")

    def bars(self, symbol: str, tf: str = "1m", limit: int = 500, include_forming: bool = True) -> list[Bar]:
        base = list(self._bars.get(symbol, ()))
        forming = self._forming.get(symbol)
        if include_forming and forming is not None:
            base = base + [forming]
        if tf == "1m":
            return base[-limit:]
        step = TF_MS.get(tf)
        if step is None:
            raise ValueError(f"unsupported timeframe: {tf}")
        out: list[Bar] = []
        for b in base:
            bucket = (b.ts // step) * step
            if out and out[-1].ts == bucket:
                agg = out[-1]
                agg.high = max(agg.high, b.high)
                agg.low = min(agg.low, b.low)
                agg.close = b.close
                agg.volume += b.volume
            else:
                out.append(Bar(symbol=symbol, tf=tf, ts=bucket,
                               open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume))
        return out[-limit:]


async def persist_bars(session_factory: async_sessionmaker, bars: list[Bar]) -> None:
    if not bars:
        return
    # Bucket alignment is enforced AT WRITE (EM team #5, 2026-08-27): a bar whose ts
    # is not on its timeframe's boundary is a stub (a seed fragment / restart seam),
    # and stubs in the table read as phantom duplicates to every consumer.
    aligned = [b for b in bars if b.tf not in INTRADAY_TF_MS or b.ts % INTRADAY_TF_MS[b.tf] == 0]
    if len(aligned) != len(bars):
        log.warning("persist_bars: dropped %d non-bucket-aligned stub bar(s)", len(bars) - len(aligned))
    bars = aligned
    if not bars:
        return
    rows = [
        {"symbol": b.symbol, "tf": b.tf, "ts": b.ts, "open": b.open,
         "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
        for b in bars
    ]
    async with session_factory() as session:
        dialect = session.bind.dialect.name if session.bind is not None else "postgresql"
        if dialect == "postgresql":
            stmt = pg_insert(BarRow).values(rows).on_conflict_do_nothing(constraint="uq_bar")
        else:
            stmt = sqlite_insert(BarRow).values(rows).prefix_with("OR IGNORE")
        await session.execute(stmt)
        await session.commit()


async def cleanup_stub_bars(session_factory: async_sessionmaker) -> dict[str, int]:
    """One-time-per-boot hygiene (EM team #5): delete rows whose ts is not on the
    timeframe's bucket boundary — the 'duplicate' rows were these stubs. The unique
    index (symbol, tf, ts) already prevents true duplicates; alignment at write
    prevents new stubs. Returns {tf: deleted}."""
    from sqlalchemy import text
    out: dict[str, int] = {}
    async with session_factory() as session:
        for tf, step in INTRADAY_TF_MS.items():
            res = await session.execute(
                text("DELETE FROM bars WHERE tf = :tf AND ts % :step != 0"),
                {"tf": tf, "step": step})
            if res.rowcount:
                out[tf] = int(res.rowcount)
        await session.commit()
    return out


async def load_bars(
    session_factory: async_sessionmaker, symbol: str, tf: str = "1m", limit: int = 3000
) -> list[Bar]:
    async with session_factory() as session:
        stmt = (
            select(BarRow)
            .where(BarRow.symbol == symbol, BarRow.tf == tf)
            .order_by(BarRow.ts.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [
        Bar(symbol=r.symbol, tf=r.tf, ts=r.ts, open=r.open, high=r.high, low=r.low,
            close=r.close, volume=r.volume)
        for r in reversed(rows)
    ]


class BarPersister:
    """Consumes closed bars off the bus and batches them into the DB."""

    def __init__(self, bus: Bus, session_factory: async_sessionmaker) -> None:
        self._bus = bus
        self._sf = session_factory
        self._pending: list[Bar] = []
        self._last_flush = now_ms()

    async def run(self) -> None:
        async with self._bus.subscription(topics.BARS) as q:
            while True:
                msg = await q.get()
                self._pending.append(msg["bar"])
                if len(self._pending) >= 50 or now_ms() - self._last_flush > 15_000:
                    await self.flush()

    async def flush(self) -> None:
        if self._pending:
            batch, self._pending = self._pending, []
            await persist_bars(self._sf, batch)
        self._last_flush = now_ms()
