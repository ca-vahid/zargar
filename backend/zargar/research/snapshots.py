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
    for sym in symbols:
        try:
            rows = await provider.all_rows(sym)
        except Exception as exc:
            failures.append(f"{sym}: {exc}")
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
        await asyncio.sleep(0.25)          # gentle on the free endpoint
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
           "failed": len(failures), "pruned": pruned}
    if failures:
        out["failures"] = failures[:10]
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


def register_jobs(engine) -> None:
    s = engine.settings
    engine.scheduler.register("chain_snapshots", str(s.get("research.chain_snapshots.at", "16:30")),
                              lambda: snapshot_chains(engine))
    engine.scheduler.register("daily_bars", str(s.get("research.daily_bars.at", "20:05")),
                              lambda: snapshot_daily_bars(engine))
