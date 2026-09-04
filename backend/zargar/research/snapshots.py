"""Nightly research feeds (techniques research B4/B5, 2026-08-27).

Two scheduled jobs, registered on the engine scheduler at start:

- **Daily option-chain snapshots** (`research.chain_snapshots.*`, 16:30 ET):
  one row per (date, contract) — volume, open interest, IV, bid/ask/mid — from
  the chain provider we already poll (CBOE delayed by default). OI history is
  NOT backfillable from anywhere, so every day this does not run is walk-forward
  data lost for the Flow/Premium families; that is why it lands first. When the
  Alpaca options subscription is active, price history can come from Alpaca —
  the snapshot still runs for the OI/IV columns.

- **Daily bars** (`research.daily_bars.*`, 20:05 ET): tf="1d" rows into the
  bars table for the working universe, so daily-close techniques (Flow, Drift)
  have a local daily layer instead of re-fetching Yahoo per scan.

Both journal through the scheduler (`ScheduledJobRan/Failed`) and alert on
failure. Universe = the technique universe (falls back to the walk-forward core).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..models import OptionChainSnapshot

ET = ZoneInfo("America/New_York")
log = logging.getLogger("zargar.research.snapshots")


async def _universe(engine) -> list[str]:
    svc = getattr(engine, "technique", None)
    if svc is not None:
        try:
            return list(await svc.universe())
        except Exception:
            log.exception("universe unavailable; using the core list")
    return [str(x) for x in engine.settings.get("technique.walkforward.symbols", []) or []]


async def snapshot_chains(engine) -> dict:
    """One nightly row per (date, contract) for every optionable universe symbol."""
    from ..technique.universe import is_us_optionable_symbol
    s = engine.settings
    if not bool(s.get("research.chain_snapshots.enabled", True)):
        return {"skipped": "disabled"}
    opts = getattr(engine, "options", None)
    if opts is None:
        return {"skipped": "options service not attached"}
    provider = opts.provider()
    day = dt.datetime.now(ET).strftime("%Y-%m-%d")
    symbols = [x for x in await _universe(engine) if is_us_optionable_symbol(x)]
    rows_written = 0
    failures: list[str] = []
    rate_limited = 0
    # F45 (2026-09-04): back-to-back requests earned 185 HTTP 429s in three minutes and lost half
    # the universe for five sessions — pace the sweep and retry a 429 after a backoff
    delay = float(s.get("research.chain_snapshots.delay_s", 0.75) or 0)
    retries = int(s.get("research.chain_snapshots.retries", 2) or 0)
    for sym in symbols:
        rows = None
        for attempt in range(retries + 1):
            try:
                rows = await provider.all_rows(sym)
                break
            except Exception as exc:
                if "429" in str(exc) and attempt < retries:
                    rate_limited += 1
                    await asyncio.sleep(3.0 * (attempt + 1))
                    continue
                failures.append(f"{sym}: {exc}")
                break
        if rows is None:
            await asyncio.sleep(delay)
            continue
        skip_dead = bool(s.get("research.chain_snapshots.skip_dead", True))
        values = []
        for r in rows:
            g = r.get("greeks") or {}
            # a contract nobody holds and nobody traded today carries no signal for the
            # repeat-hit / OI-delta / IV-percentile consumers — first live night was
            # 366k rows across 145 names, ~60%+ of them dead (2026-08-27)
            if skip_dead and not int(r.get("volume") or 0) and not int(r.get("open_interest") or 0):
                continue
            bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
            values.append({
                "date": day, "occ": r["symbol"], "underlying": sym,
                "expiry": r.get("expiry"), "strike": float(r.get("strike") or 0),
                "option_type": r.get("option_type"),
                "volume": int(r.get("volume") or 0), "open_interest": int(r.get("open_interest") or 0),
                "iv": (float(g.get("mid_iv")) if g.get("mid_iv") else None),
                "delta": (float(g.get("delta")) if g.get("delta") is not None else None),
                "bid": bid or None, "ask": ask or None,
                "mid": (round((bid + ask) / 2, 4) if bid and ask else None),
                "last": (float(r.get("last")) if r.get("last") else None),
            })
        if not values:
            continue
        async with engine.sf() as session:
            dialect = session.bind.dialect.name if session.bind is not None else "postgresql"
            for i in range(0, len(values), 1000):
                chunk = values[i:i + 1000]
                if dialect == "postgresql":
                    stmt = pg_insert(OptionChainSnapshot).values(chunk).on_conflict_do_nothing(
                        constraint="uq_chain_snapshot")
                else:
                    stmt = sqlite_insert(OptionChainSnapshot).values(chunk).prefix_with("OR IGNORE")
                await session.execute(stmt)
            await session.commit()
        rows_written += len(values)
        await asyncio.sleep(delay)         # gentle on the free endpoint (research.chain_snapshots.delay_s)
    # prune beyond the retention window
    keep_days = int(s.get("research.chain_snapshots.keep_days", 400) or 0)
    pruned = 0
    if keep_days > 0:
        cutoff = (dt.datetime.now(ET) - dt.timedelta(days=keep_days)).strftime("%Y-%m-%d")
        async with engine.sf() as session:
            res = await session.execute(text("DELETE FROM option_chain_snapshots WHERE date < :c"), {"c": cutoff})
            pruned = int(res.rowcount or 0)
            await session.commit()
    out = {"date": day, "symbols": len(symbols), "rows": rows_written,
           "failed": len(failures), "rateLimitedRetries": rate_limited, "pruned": pruned}
    if failures:
        out["failures"] = failures[:10]
    if symbols and len(failures) > len(symbols) * 0.2:
        log.warning("chain snapshots: %d of %d underlyings failed — the universe is half-dark tonight", len(failures), len(symbols))
    log.info("chain snapshots: %s", out)
    return out


async def snapshot_daily_bars(engine) -> dict:
    """tf='1d' bars into the bars table for the universe (daily-close techniques)."""
    from ..marketdata import persist_bars
    s = engine.settings
    if not bool(s.get("research.daily_bars.enabled", True)):
        return {"skipped": "disabled"}
    feed = engine.feed
    if not hasattr(feed, "fetch_bars"):
        return {"skipped": "feed has no history"}
    rng = str(s.get("research.daily_bars.range", "1mo"))
    symbols = await _universe(engine)
    written = 0
    failures = 0
    for sym in symbols:
        try:
            bars = await feed.fetch_bars(sym, tf="1d", range_=rng)
        except Exception:
            failures += 1
            continue
        bars = [b for b in bars if b.close and b.close > 0]
        if bars:
            await persist_bars(engine.sf, bars)
            written += len(bars)
        await asyncio.sleep(0.1)
    out = {"symbols": len(symbols), "rows": written, "failed": failures, "range": rng}
    log.info("daily bars: %s", out)
    return out


async def snapshot_ext_bars(engine, *, days: int | None = None) -> dict:
    """Extended-hours (04:00–20:00 ET) 1m bars for `research.ext_bars.symbols` into the bars
    table (tf='1m'; pre/post rows share the timeframe and are told apart by wall clock —
    `marketstructure.aggregate.bar_session`). Yahoo serves ~20 days of 1m history, so this
    runs nightly and re-upserts the last `backfill_days`; the table is the only place a
    60-session sweep can read from (Team2 desk, 2026-09-03; PLAN §3c B1)."""
    from ..marketdata import persist_bars
    from ..marketstructure.history import HistoryError, fetch_window
    s = engine.settings
    if not bool(s.get("research.ext_bars.enabled", True)):
        return {"skipped": "disabled"}
    symbols = [str(x).upper() for x in (s.get("research.ext_bars.symbols", []) or [])]
    if not symbols:
        return {"skipped": "no symbols"}
    span_days = int(days or s.get("research.ext_bars.backfill_days", 20) or 20)
    end_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    start_ms = end_ms - span_days * 86_400_000
    written = 0
    failures: list[str] = []
    per_symbol: dict[str, int] = {}
    for sym in symbols:
        try:
            bars = await fetch_window(sym, "1m", start_ms, end_ms, session="ext")
        except HistoryError as exc:
            failures.append(f"{sym}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - one symbol must not sink the job
            failures.append(f"{sym}: {type(exc).__name__}: {exc}")
            continue
        bars = [b for b in bars if b.close and b.close > 0]
        if bars:
            await persist_bars(engine.sf, bars)
        per_symbol[sym] = len(bars)
        written += len(bars)
        await asyncio.sleep(0.2)
    out = {"symbols": len(symbols), "rows": written, "perSymbol": per_symbol,
           "days": span_days, "failed": len(failures)}
    if failures:
        out["failures"] = failures[:10]
    log.info("extended-hours bars: %s", out)
    return out


async def snapshot_vix(engine) -> dict:
    """Daily closes of the volatility indices (^VIX, ^VIX1D, ^VIX9D) into the bars table
    (tf='1d'). They are the intraday IV proxy for the 0DTE premium-path scorer (PLAN §3c B2)."""
    from ..marketdata import persist_bars
    from ..marketstructure.history import HistoryError, fetch_window
    s = engine.settings
    if not bool(s.get("research.vix.enabled", True)):
        return {"skipped": "disabled"}
    symbols = [str(x) for x in (s.get("research.vix.symbols", []) or [])]
    end_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    start_ms = end_ms - 400 * 86_400_000
    written = 0
    failures: list[str] = []
    for sym in symbols:
        try:
            bars = await fetch_window(sym, "1d", start_ms, end_ms)
        except HistoryError as exc:
            failures.append(f"{sym}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{sym}: {type(exc).__name__}: {exc}")
            continue
        bars = [b for b in bars if b.close and b.close > 0]
        if bars:
            await persist_bars(engine.sf, bars)
        written += len(bars)
        await asyncio.sleep(0.2)
    out = {"symbols": len(symbols), "rows": written, "failed": len(failures)}
    if failures:
        out["failures"] = failures[:10]
    log.info("vix bars: %s", out)
    return out


def register_jobs(engine) -> None:
    s = engine.settings
    engine.scheduler.register("chain_snapshots", str(s.get("research.chain_snapshots.at", "16:30")),
                              lambda: snapshot_chains(engine))
    engine.scheduler.register("daily_bars", str(s.get("research.daily_bars.at", "20:05")),
                              lambda: snapshot_daily_bars(engine))
    engine.scheduler.register("ext_bars", str(s.get("research.ext_bars.at", "20:10")),
                              lambda: snapshot_ext_bars(engine))
    engine.scheduler.register("vix_bars", str(s.get("research.ext_bars.at", "20:10")),
                              lambda: snapshot_vix(engine))
