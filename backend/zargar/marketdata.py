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
from .models import BarRow, BarsDatasetVersion

log = logging.getLogger("zargar.marketdata")

# tfs whose bars sit on fixed UTC-ms buckets; 1d bars are session-anchored and exempt
# from the alignment rule and the stub cleanup
INTRADAY_TF_MS: dict[str, int] = {}

MINUTE_MS = 60_000
TF_MS = {"1m": MINUTE_MS, "5m": 5 * MINUTE_MS, "15m": 15 * MINUTE_MS, "1h": 60 * MINUTE_MS,
         "1d": 24 * 60 * MINUTE_MS}
INTRADAY_TF_MS.update({k: v for k, v in TF_MS.items() if k != "1d"})

# F75 (2026-09-09): provenance precedence at write — a venue's completed bar beats a quote-sampled
# one, which beats a legacy row with no provenance (F79: `unknown` ranks below `sampled`), a sampled
# bar never undoes an exchange correction, a synthetic bar never enters a table that real feeds
# write to (unless a test says so). Exchange-over-exchange is an update (a re-fetch is a correction
# too) whose volume never goes down.
SOURCE_RANK = {"sim": 0, "": 1, "unknown": 1, "sampled": 2, "exchange": 3}   # F79: no provenance < sampled
# the data-processing rules a dataset version is hashed together with — bump when write rules change
DATA_RULES_VERSION = ("bars-rules/2026-09-09: bucket-aligned writes; source precedence exchange>sampled|unknown>sim; "
                      "calendar-gated 04:00-20:00 ET trading days; sim bars isolated")


class QuoteCache:
    def __init__(self, bus: Bus) -> None:
        self._bus = bus
        self._quotes: dict[str, Quote] = {}
        # per-symbol field overrides applied to every incoming quote — option
        # contracts get bid/ask from the (delayed) chain while `last` streams live
        self._overlays: dict[str, dict] = {}
        # the last trade the overlay's source (the delayed chain) had seen —
        # when the live tape has printed PAST the chain's band since, the band
        # is re-centred on the live print (see _apply_overlay)
        self._anchors: dict[str, float] = {}

    def on_quote(self, q: Quote) -> None:
        ov = self._overlays.get(q.symbol)
        if ov:
            self._apply_overlay(q, ov)
        self._quotes[q.symbol] = q
        self._bus.publish(topics.QUOTES, q)

    def _apply_overlay(self, q: Quote, ov: dict) -> None:
        for k, v in ov.items():
            setattr(q, k, v)
        bid, ask = float(ov.get("bid") or 0), float(ov.get("ask") or 0)
        anchor = self._anchors.get(q.symbol)
        if bid <= 0 or ask <= 0 or anchor is None or q.last <= 0:
            return
        # 2026-09-02 GOOGL 0DTE 340C: the live tape printed 0.47-0.76 while the
        # ~15-min-delayed chain still said 0.12/0.13 — the practice book "bought"
        # 20 at 0.13, the premium stop measured against a fantasy basis and the
        # risk gate called the quote fresh. A live print outside the delayed
        # band, DIFFERENT from the trade the chain had seen, means the market
        # moved after the chain's snapshot: keep the chain's spread width, but
        # centre it on what is actually trading.
        if abs(q.last - anchor) > 1e-9 and (q.last > ask or q.last < bid):
            half = max((ask - bid) / 2, 0.005)
            q.bid = max(round(q.last - half, 4), 0.01)
            q.ask = round(q.last + half, 4)

    def set_overlay(self, symbol: str, *, anchor_last: float | None = None, **fields) -> None:
        """Override quote fields for a symbol (bid/ask/sizes) until cleared.
        `anchor_last` = the last trade the overlay's source saw (delayed chain),
        so a live print past the band can re-centre it."""
        if not fields:
            self._overlays.pop(symbol, None)
            self._anchors.pop(symbol, None)
            return
        self._overlays[symbol] = dict(fields)
        if anchor_last is not None and anchor_last > 0:
            self._anchors[symbol] = float(anchor_last)
        q = self._quotes.get(symbol)
        if q is not None:
            self._apply_overlay(q, self._overlays[symbol])
            if "bid" in fields or "ask" in fields:
                # a refreshed bid/ask IS fresh information: the premium stop and the
                # risk gate judge freshness by `ts`, which the overlay never moved
                # (an option's quote used to go stale 180 s after it was first seen)
                q.ts = now_ms()

    def clear_overlay(self, symbol: str) -> None:
        self._overlays.pop(symbol, None)
        self._anchors.pop(symbol, None)

    def get(self, symbol: str) -> Quote | None:
        return self._quotes.get(symbol)

    def all(self) -> dict[str, Quote]:
        return dict(self._quotes)

    def age_seconds(self, symbol: str) -> float:
        q = self._quotes.get(symbol)
        if q is None:
            return float("inf")
        return max(0.0, time.time() - q.ts / 1000)

    def source_age_seconds(self, symbol: str) -> float:
        """Age of the PRICE, not of our copy of it: the source's own print time
        when the quote carries one (OPRA quote time; a chain row's fetch time
        less its published delay), else `ts`."""
        q = self._quotes.get(symbol)
        if q is None:
            return float("inf")
        ref = q.source_ts if q.source_ts and q.source_ts > 0 else q.ts
        return max(0.0, time.time() - ref / 1000)


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
        # F75/F78 (2026-09-09): what a quote-built bar is (sampled | sim), whether quotes outside a
        # market minute may form bars at all (never for a real feed), and which symbols' volume comes
        # from print sizes instead of a cumulative counter
        self._sampled_source = "sampled"
        self._calendar_gated = False
        self._volume_from_prints = None      # (symbol) -> bool

    def configure(self, *, hold_seconds=None, expects_exchange=None, sampled_source=None, calendar_gated=None,
                  volume_from_prints=None) -> None:
        if hold_seconds is not None or expects_exchange is not None:
            self._hold_seconds = hold_seconds
            self._expects_exchange = expects_exchange
        if sampled_source is not None:
            self._sampled_source = str(sampled_source)
        if calendar_gated is not None:
            self._calendar_gated = bool(calendar_gated)
        if volume_from_prints is not None:
            self._volume_from_prints = volume_from_prints

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
        if self._calendar_gated:
            from .marketstructure.market_calendar import is_market_minute
            if not is_market_minute(q.ts):
                return                       # F75: a quote on a closed day is not a bar
        bucket = (q.ts // MINUTE_MS) * MINUTE_MS
        prints = False
        if self._volume_from_prints is not None:
            try:
                prints = bool(self._volume_from_prints(q.symbol))
            except Exception:  # noqa: BLE001
                prints = False
        if prints:
            vol_delta = max(0, int(q.trade_size or 0))       # F78: a sum of prints
        else:
            last = self._last_volume.get(q.symbol)
            # first sight, or the counter went DOWN (a session roll / a re-seed): never a fake spike
            vol_delta = 0 if (last is None or q.volume < last) else q.volume - last
            self._last_volume[q.symbol] = q.volume
        forming = self._forming.get(q.symbol)
        if forming is None or forming.ts != bucket:
            if forming is not None and forming.ts < bucket:
                self._close_sampled(q.symbol, forming)
            self._forming[q.symbol] = Bar(
                symbol=q.symbol, tf="1m", ts=bucket,
                open=price, high=price, low=price, close=price, volume=vol_delta,
                source=self._sampled_source,
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
        bar.source = "exchange"
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


async def persist_bars(session_factory: async_sessionmaker, bars: list[Bar], *, allow_sim: bool = False) -> None:
    if not bars:
        return
    # F75 (2026-09-09): provenance at write. A synthetic bar never enters the table unless the caller
    # (tests, or an explicit config) allows it; a real-feed bar outside a market minute is a closed-day
    # artefact (the app ran through a weekend) and is dropped — the one-price "sessions" came from here.
    from .marketstructure.market_calendar import is_market_minute
    kept: list[Bar] = []
    dropped_sim = dropped_closed = 0
    for b in bars:
        src = b.source or "unknown"
        if src == "sim" and not allow_sim:
            dropped_sim += 1
            continue
        if src != "sim" and b.tf in INTRADAY_TF_MS and not is_market_minute(b.ts):
            dropped_closed += 1
            continue
        kept.append(b)
    if dropped_sim:
        log.warning("persist_bars: refused %d synthetic (sim) bar(s) — the shared table holds market data only", dropped_sim)
    if dropped_closed:
        log.warning("persist_bars: dropped %d bar(s) outside a market minute (closed day / after 20:00 ET) — F75", dropped_closed)
    bars = kept
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
    # one row per (symbol, tf, ts) per statement: a sampled bar and its exchange correction routinely
    # share a flush, and an upsert may not touch the same row twice — keep the best provenance
    # (the later write wins a tie, e.g. an exchange re-fetch)
    best: dict[tuple[str, str, int], Bar] = {}
    for b in bars:
        k = (b.symbol, b.tf, b.ts)
        cur = best.get(k)
        if cur is None or SOURCE_RANK.get(b.source or "unknown", 1) >= SOURCE_RANK.get(cur.source or "unknown", 1):
            best[k] = b
    bars = list(best.values())
    rows = [
        {"symbol": b.symbol, "tf": b.tf, "ts": b.ts, "open": b.open,
         "high": b.high, "low": b.low, "close": b.close, "volume": b.volume,
         "source": (b.source or "unknown")}
        for b in bars
    ]
    # asyncpg caps a statement at 32,767 bind parameters (8 per row): a 20-day
    # extended-hours bank (~18k bars) blew past it (Team2 desk, 2026-09-04) — chunk.
    CHUNK = 2000
    async with session_factory() as session:
        dialect = session.bind.dialect.name if session.bind is not None else "postgresql"
        for i in range(0, len(rows), CHUNK):
            part = rows[i:i + CHUNK]
            # precedence upsert (F75): the row with the better provenance wins; an exchange bar may
            # also refresh an exchange bar (a re-fetch is a correction); a sampled bar never clobbers
            # an exchange one. Until 2026-09-09 this was on_conflict_do_nothing, so the exchange
            # correction that replaced a sampled bar in memory never reached storage.
            from sqlalchemy import case
            if dialect == "postgresql":
                ins = pg_insert(BarRow).values(part)
            else:
                ins = sqlite_insert(BarRow).values(part)
            exc_src = ins.excluded.source
            new_rank = case((exc_src == "exchange", 3), (exc_src == "sampled", 2), (exc_src == "sim", 0), else_=1)
            old_rank = case((BarRow.source == "exchange", 3), (BarRow.source == "sampled", 2), (BarRow.source == "sim", 0), else_=1)
            both_exchange = (exc_src == "exchange") & (BarRow.source == "exchange")
            better = (new_rank > old_rank) | both_exchange
            # F79: two exchange sources (Alpaca SIP stream/history, Yahoo consolidated) may both correct a
            # minute; OHLC follows the newer bar, volume is never LOWERED by a re-fetch to a lesser total
            from sqlalchemy import func as _f
            volume_expr = case((both_exchange, _f.greatest(BarRow.volume, ins.excluded.volume)), else_=ins.excluded.volume)
            set_ = {"open": ins.excluded.open, "high": ins.excluded.high, "low": ins.excluded.low,
                    "close": ins.excluded.close, "volume": volume_expr, "source": exc_src}
            if dialect == "postgresql":
                stmt = ins.on_conflict_do_update(constraint="uq_bar", set_=set_, where=better)
            else:
                stmt = ins.on_conflict_do_update(index_elements=["symbol", "tf", "ts"], set_=set_, where=better)
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
            close=r.close, volume=r.volume, source=(r.source or "unknown"))
        for r in reversed(rows)
    ]


class BarPersister:
    """Consumes closed bars off the bus and batches them into the DB."""

    def __init__(self, bus: Bus, session_factory: async_sessionmaker, *, allow_sim: bool = False) -> None:
        self._bus = bus
        self._sf = session_factory
        self._allow_sim = allow_sim
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
            await persist_bars(self._sf, batch, allow_sim=self._allow_sim)
        self._last_flush = now_ms()


async def dataset_version(session_factory: async_sessionmaker, symbols: list[str], *, tf: str = "1m",
                          start: str | None = None, end: str | None = None, note: str = "",
                          record: bool = True) -> dict:
    """The CONTENT identity of a slice of `bars` (F75, 2026-09-09): sha256 over every row's
    (symbol, ts, open, high, low, close, volume, source) in scope, ordered, plus the data-processing
    rules (`DATA_RULES_VERSION`). A volume repair with the same row count is a different version;
    the same bytes hash the same on any machine. `start`/`end` are ET session dates (inclusive).
    Recorded in `bars_dataset_versions` so a sweep / plan can cite it."""
    import datetime as _dt
    import hashlib
    import json
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    syms = sorted({s.upper() for s in symbols})
    start_ms = int(_dt.datetime.combine(_dt.date.fromisoformat(start), _dt.time(0, 0), et).timestamp() * 1000) if start else None
    end_ms = int((_dt.datetime.combine(_dt.date.fromisoformat(end), _dt.time(0, 0), et) + _dt.timedelta(days=1)).timestamp() * 1000) if end else None
    h = hashlib.sha256()
    # the scope is part of the identity: the same rows asked for as "SPY" and as "SPY+QQQ" are two datasets
    h.update(json.dumps({"symbols": syms, "tf": tf, "start": start, "end": end, "rules": DATA_RULES_VERSION},
                        sort_keys=True).encode("utf-8"))
    n = 0
    async with session_factory() as session:
        for sym in syms:
            stmt = select(BarRow.ts, BarRow.open, BarRow.high, BarRow.low, BarRow.close, BarRow.volume, BarRow.source).where(
                BarRow.symbol == sym, BarRow.tf == tf)
            if start_ms is not None:
                stmt = stmt.where(BarRow.ts >= start_ms)
            if end_ms is not None:
                stmt = stmt.where(BarRow.ts < end_ms)
            res = await session.execute(stmt.order_by(BarRow.ts))
            for ts, o, hi, lo, c, v, src in res:
                h.update(f"{sym}|{ts}|{o!r}|{hi!r}|{lo!r}|{c!r}|{int(v or 0)}|{src or 'unknown'}\n".encode("utf-8"))
                n += 1
    digest = h.hexdigest()
    scope = {"symbols": syms, "tf": tf, "start": start, "end": end, "rules": DATA_RULES_VERSION}
    if record:
        async with session_factory() as session:
            if (await session.get(BarsDatasetVersion, digest)) is None:
                session.add(BarsDatasetVersion(id=digest, scope=scope, rows=n, note=note[:200]))
                await session.commit()
    return {"hash": digest, "rows": n, **scope, "note": note}
