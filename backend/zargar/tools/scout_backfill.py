"""Scout Form 4 history backfill - resumable, throttled, research only.

    python -m zargar.tools.scout_backfill --since 2023-10-01            # all phases
    python -m zargar.tools.scout_backfill --since 2015-01-01 --no-enrich
    python -m zargar.tools.scout_backfill --enrich-only --enrich-limit 2000
    python -m zargar.tools.scout_backfill --status

Phases (each idempotent; re-running resumes where the last run stopped):

1. **datasets** - one SEC quarterly insider data-set ZIP per completed quarter since
   `--since` (~13 requests for three years). Open-market rows (P/S) only. Filing DATE only.
2. **daily** - the EDGAR daily form index for every trading day after the last published
   quarter (the current quarter), one request per new Form 4 (and per 8-K header for S2).
3. **enrich** - the SGML-header acceptance time for every data-set filing that holds an
   officer/director PURCHASE (what S1 times), newest first. The long one (~1 request per
   filing at <= 5 req/s); stop it any time (Ctrl-C), re-run to continue.

The CMP classifier needs coverage from Jan 1 of (year - 3): start `--since` at a year
boundary three years before the first year you want classified (e.g. 2022-01-01 for
2025 signals). The database is the runtime one (`ZARGAR_DATABASE_URL` / backend/.env)
unless `--db` says otherwise; only the scout_* tables are created/written.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import signal
import tempfile
from pathlib import Path

from ..db import make_engine, make_session_factory
from ..models import SCOUT_TABLES, Base, utcnow
from ..marketstructure import market_calendar as mcal
from ..techniques.scout import datasets as ds
from ..techniques.scout import ingest as ing
from ..techniques.scout.edgar import DEFAULT_UA, EdgarClient, EdgarError
from ..techniques.scout.form4 import ET

_STOP = False


def _on_signal(*_a):
    global _STOP
    _STOP = True
    print("stop requested - finishing the current item", flush=True)


def _stop() -> bool:
    return _STOP


def _db_url(arg: str | None) -> str:
    if arg:
        return arg
    if os.environ.get("ZARGAR_DATABASE_URL"):
        return os.environ["ZARGAR_DATABASE_URL"]
    from ..config import AppConfig
    return AppConfig().database_url


async def _ensure_tables(engine) -> None:
    tables = [Base.metadata.tables[t] for t in SCOUT_TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))


async def _progress(sf, **kw) -> None:
    st = await ing.get_state(sf, "backfill")
    st.update(kw)
    st["updatedAt"] = utcnow().isoformat()
    await ing.put_state(sf, "backfill", st)


async def run(args) -> int:
    engine = make_engine(_db_url(args.db))
    sf = make_session_factory(engine)
    await _ensure_tables(engine)
    if args.status:
        out = {"backfill": await ing.get_state(sf, "backfill"),
               "datasets": sorted(await ing.get_state(sf, "datasets")),
               "dailyDays": len(await ing.get_state(sf, "daily_days")),
               "coverageStart": ing.coverage_start(await ing.get_state(sf, "datasets"),
                                                   await ing.get_state(sf, "daily_days")),
               **(await ing.counts(sf))}
        print(json.dumps(out, indent=2, default=str))
        await engine.dispose()
        return 0
    client = EdgarClient(user_agent=args.user_agent, max_rps=args.rps)
    since = dt.date.fromisoformat(args.since)
    today = dt.datetime.now(ET).date()
    await _progress(sf, since=args.since, startedAt=utcnow().isoformat(), pid=os.getpid())
    try:
        # ---- 1. quarterly data sets
        if not (args.enrich_only or args.skip_datasets):
            done = await ing.get_state(sf, "datasets")
            quarters = [(y, q) for y, q in ds.quarters_between(since, today)
                        if dt.date(y + (q == 4), (3 * q) % 12 + 1, 1) <= today]          # quarter ended
            for y, q in quarters:
                if _STOP:
                    break
                name = ds.quarter_name(y, q)
                if done.get(name, {}).get("published"):
                    continue
                print(f"[datasets] {name} ...", flush=True)
                try:
                    st = await ing.ingest_dataset_quarter(sf, client, y, q, since=args.since,
                                                          workdir=Path(tempfile.gettempdir()) / "scout")
                except (EdgarError, OSError) as exc:
                    print(f"[datasets] {name} failed: {exc}", flush=True)
                    continue
                print(f"[datasets] {name}: {st}", flush=True)
                await _progress(sf, phase="datasets", lastQuarter=name)
        # ---- 2. daily indexes after the last published quarter
        if not (args.enrich_only or args.skip_daily) and not _STOP:
            done_q = await ing.get_state(sf, "datasets")
            pub = sorted(k for k, v in done_q.items() if v.get("published"))
            if pub:
                y, q = int(pub[-1][:4]), int(pub[-1][-1])
                start = dt.date(y + (q == 4), (3 * q) % 12 + 1, 1)
            else:
                start = since
            start = max(start, since)
            have = await ing.get_state(sf, "daily_days")
            d = start
            while d < today and not _STOP:
                if mcal.is_trading_day(d) and d.isoformat() not in have:
                    try:
                        st = await ing.ingest_daily(sf, client, d, forms8k=not args.no_8k, should_stop=_stop)
                        print(f"[daily] {st}", flush=True)
                    except EdgarError as exc:
                        print(f"[daily] {d} failed: {exc}", flush=True)
                    await _progress(sf, phase="daily", lastDay=d.isoformat())
                d += dt.timedelta(days=1)
        # ---- 3. acceptance-time enrichment
        if not args.no_enrich and not _STOP:
            total = 0
            budget = args.enrich_limit if args.enrich_limit > 0 else None
            while not _STOP:
                n = 500 if budget is None else min(500, budget - total)
                if n <= 0:
                    break
                st = await ing.enrich_acceptance(sf, client, limit=n, since=args.since, should_stop=_stop)
                total += st["stamped"]
                print(f"[enrich] {st} total={total} requests={client.requests}", flush=True)
                await _progress(sf, phase="enrich", enriched=total)
                if st["candidates"] == 0 or (st["stamped"] == 0 and st["errors"] == st["candidates"]):
                    break
        await _progress(sf, phase="stopped" if _STOP else "done", finishedAt=utcnow().isoformat(),
                        requests=client.requests)
    finally:
        await client.aclose()
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2023-10-01")
    ap.add_argument("--db", default=None)
    ap.add_argument("--rps", type=float, default=5.0)
    ap.add_argument("--user-agent", default=DEFAULT_UA)
    ap.add_argument("--skip-datasets", action="store_true")
    ap.add_argument("--skip-daily", action="store_true")
    ap.add_argument("--no-8k", action="store_true", help="daily phase: skip 8-K headers (S2 events)")
    ap.add_argument("--no-enrich", action="store_true")
    ap.add_argument("--enrich-only", action="store_true")
    ap.add_argument("--enrich-limit", type=int, default=0, help="0 = until done")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    signal.signal(signal.SIGINT, _on_signal)
    try:
        signal.signal(signal.SIGTERM, _on_signal)
    except (AttributeError, ValueError):  # pragma: no cover - Windows
        pass
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
