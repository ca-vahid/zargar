"""Repair the shared `bars` table (F75, 2026-09-09) — audit, quarantine, backfill, version.

    python -m zargar.tools.bars_repair audit  [--symbols SPY,QQQ] [--json out.json]
    python -m zargar.tools.bars_repair quarantine --reason closed_day [--symbols ...] [--apply]
    python -m zargar.tools.bars_repair quarantine --reason sim_feed --symbols SPY --from 2026-08-14 --to 2026-08-19 [--apply]
    python -m zargar.tools.bars_repair backfill --symbols SPY,QQQ,IWM --from 2026-08-14 --to 2026-09-09 [--pace 0.5]
    python -m zargar.tools.bars_repair backfill --all --from 2026-08-14 --to 2026-09-09
    python -m zargar.tools.bars_repair version --symbols SPY,QQQ,IWM --from 2026-08-14 --to 2026-09-09 [--note "..."]

Principles (from the review that found F75):
  * preserve before modifying — `quarantine` copies the selected rows into `bars_quarantine` (with
    the original id, a reason and a batch id), VERIFIES the copy row-for-row, and only then deletes;
    nothing ever deletes from the quarantine table;
  * flatness alone flags, it does not classify — `audit` reports `closed_day`, `degenerate_flat`,
    `outlier_range`, `thin_rth` and `volume_spike` (range/flat flags for STOCKS only: an expiring
    option contract is flat and a 150 % intraday range is normal for one), and only `closed_day`
    (no US equity session exists on that date) is quarantined by reason; a synthetic block is
    quarantined by an EXPLICIT symbol + date range the operator names (`--reason sim_feed`);
  * corrections are authoritative by provenance — `backfill` writes exchange bars with
    `source="exchange"`, which the precedence upsert lets overwrite `sampled`/`unknown` rows and
    never lets a later sampled bar undo; a sampled row in a minute the venue has no bar for keeps its
    price track and gets volume 0 (no bar = no prints);
  * a dataset is identified by CONTENT — `version` hashes every timestamped OHLCV + source row in
    scope together with the data-processing rules, so a volume fix with the same row count is a
    different version.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import sys
import uuid
from collections import Counter
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text

from ..config import get_config
from ..db import create_all, make_engine, make_session_factory
from ..domain import Bar
from ..marketdata import DATA_RULES_VERSION, dataset_version, persist_bars
from ..marketstructure.market_calendar import is_trading_day, trading_days
from ..marketstructure.sessions import session_date
from ..models import BarQuarantineRow, BarRow
from ..techniques.team2.history import FLAT_TOL, MIN_RTH_BARS, OUTLIER_RANGE

log = logging.getLogger("zargar.tools.bars_repair")
ET = ZoneInfo("America/New_York")


def _day_bounds_ms(date: str) -> tuple[int, int]:
    d = dt.date.fromisoformat(date)
    start = dt.datetime.combine(d, dt.time(0, 0), ET)
    end = start + dt.timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _rth(ts_ms: int) -> bool:
    t = dt.datetime.fromtimestamp(ts_ms / 1000, ET)
    m = t.hour * 60 + t.minute
    return 9 * 60 + 30 <= m < 16 * 60


async def _symbols(sf, wanted: list[str] | None) -> list[str]:
    if wanted:
        return [s.upper() for s in wanted]
    async with sf() as s:
        rows = (await s.execute(select(BarRow.symbol).where(BarRow.tf == "1m").distinct())).scalars().all()
    return sorted(rows)


async def _rows(sf, symbol: str, start_ms: int | None = None, end_ms: int | None = None) -> list[BarRow]:
    async with sf() as s:
        stmt = select(BarRow).where(BarRow.symbol == symbol, BarRow.tf == "1m")
        if start_ms is not None:
            stmt = stmt.where(BarRow.ts >= start_ms)
        if end_ms is not None:
            stmt = stmt.where(BarRow.ts < end_ms)
        return list((await s.execute(stmt.order_by(BarRow.ts))).scalars().all())


# ------------------------------------------------------------------ audit
def audit_sessions(rows: list[BarRow]) -> list[dict]:
    """Per session-date facts + flags for one symbol's 1m rows."""
    by_day: dict[str, list[BarRow]] = {}
    for r in rows:
        by_day.setdefault(session_date(r.ts), []).append(r)
    out = []
    for d in sorted(by_day):
        rs = by_day[d]
        rth = [r for r in rs if _rth(r.ts)]
        flags = []
        from ..options import occ
        is_option = occ.is_occ(rs[0].symbol)
        if not is_trading_day(dt.date.fromisoformat(d)):
            flags.append("closed_day")
        hi = max(r.high for r in rth) if rth else None
        lo = min(r.low for r in rth) if rth else None
        rng = (hi - lo) if rth else None
        ref = rth[-1].close if rth else (rs[-1].close if rs else 0)
        if not flags and not is_option:
            if len(rth) < MIN_RTH_BARS:
                flags.append("thin_rth")
            elif ref and rng <= FLAT_TOL * ref:
                flags.append("degenerate_flat")
            elif ref and rng > OUTLIER_RANGE * ref:
                flags.append("outlier_range")
        vol = sum(int(r.volume or 0) for r in rs)
        # the opening/closing auctions legitimately carry a big share of a thin name's day: judge the
        # spike on the other minutes only, and only on rows that are NOT a venue's own bar
        def _hhmm(ts_ms):
            t_ = dt.datetime.fromtimestamp(ts_ms / 1000, ET)
            return t_.hour * 60 + t_.minute
        cand = [r for r in rs if _hhmm(r.ts) not in (9 * 60 + 30, 16 * 60) and (r.source or "unknown") != "exchange"]
        vmax = max((int(r.volume or 0) for r in cand), default=0)
        if vol and vmax > 1_000_000 and vmax > 0.25 * vol:
            flags.append("volume_spike")
        out.append({"symbol": rs[0].symbol, "kind": ("option" if is_option else "stock"), "date": d,
                    "weekday": dt.date.fromisoformat(d).strftime("%a"),
                    "rows": len(rs), "rthRows": len(rth), "flatRows": sum(1 for r in rs if r.low == r.high),
                    "rthLow": round(lo, 4) if lo is not None else None, "rthHigh": round(hi, 4) if hi is not None else None,
                    "rthRangePct": round(100 * rng / ref, 3) if (rth and ref) else None,
                    "volume": vol, "maxMinuteVolume": vmax,
                    "sources": dict(Counter((r.source or "unknown") for r in rs)), "flags": flags})
    return out


async def cmd_audit(sf, symbols: list[str] | None, out_json: str, only_flagged: bool) -> list[dict]:
    report: list[dict] = []
    for sym in await _symbols(sf, symbols):
        report.extend(audit_sessions(await _rows(sf, sym)))
    shown = [r for r in report if r["flags"]] if only_flagged else report
    for r in shown:
        print(f"{r['symbol']:<6} {r['date']} {r['weekday']} rows={r['rows']:<5} rth={r['rthRows']:<4} flat={r['flatRows']:<5} "
              f"range%={r['rthRangePct']!s:<7} vol={r['volume']:<12} maxMin={r['maxMinuteVolume']:<10} {r['sources']} {' '.join(r['flags'])}")
    flagged = Counter(f for r in report for f in r["flags"])
    print(f"-- {len(report)} symbol-sessions audited; flags: {dict(flagged)}; rules: {DATA_RULES_VERSION}")
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"rules": DATA_RULES_VERSION, "sessions": report}, f, indent=1)
        print("saved", out_json)
    return report


# ------------------------------------------------------------------ quarantine
async def select_quarantine(sf, *, reason: str, symbols: list[str] | None, date_from: str | None, date_to: str | None) -> list[BarRow]:
    """The rows a quarantine would take. `closed_day` = every 1m row whose ET session date is not a
    trading day (optionally restricted to symbols / a date range); any other reason REQUIRES an
    explicit symbol list and date range — a synthetic block is named by the operator, never inferred."""
    if reason != "closed_day" and not (symbols and date_from and date_to):
        raise SystemExit(f"--reason {reason} needs --symbols, --from and --to (explicit scope; nothing is inferred)")
    start_ms = _day_bounds_ms(date_from)[0] if date_from else None
    end_ms = _day_bounds_ms(date_to)[1] if date_to else None
    picked: list[BarRow] = []
    for sym in await _symbols(sf, symbols):
        for r in await _rows(sf, sym, start_ms, end_ms):
            if reason == "closed_day":
                if is_trading_day(dt.date.fromisoformat(session_date(r.ts))):
                    continue
            picked.append(r)
    return picked


async def apply_quarantine(sf, rows: list[BarRow], *, reason: str, note: str = "") -> dict:
    """Copy → verify → delete. Returns the batch record. Raises (and deletes nothing) if the copy
    does not match the selection row for row."""
    if not rows:
        return {"batch": None, "rows": 0}
    batch = uuid.uuid4().hex[:12]
    when = dt.datetime.now(dt.timezone.utc)
    ids = [r.id for r in rows]
    async with sf() as s:
        for i in range(0, len(rows), 2000):
            part = rows[i:i + 2000]
            s.add_all([BarQuarantineRow(orig_id=r.id, symbol=r.symbol, tf=r.tf, ts=r.ts, open=r.open, high=r.high,
                                        low=r.low, close=r.close, volume=r.volume, source=r.source or "unknown",
                                        reason=reason, batch=batch, note=note, quarantined_at=when) for r in part])
        await s.commit()
    # verify: same count, same ids, same (ts, close, volume) checksum
    async with sf() as s:
        q = (await s.execute(select(BarQuarantineRow).where(BarQuarantineRow.batch == batch))).scalars().all()
    if len(q) != len(rows) or {x.orig_id for x in q} != set(ids):
        raise RuntimeError(f"quarantine copy MISMATCH for batch {batch}: {len(q)} copied vs {len(rows)} selected — nothing deleted")
    want = sorted((r.ts, r.close, int(r.volume or 0)) for r in rows)
    have = sorted((x.ts, x.close, int(x.volume or 0)) for x in q)
    if want != have:
        raise RuntimeError(f"quarantine content MISMATCH for batch {batch} — nothing deleted")
    async with sf() as s:
        deleted = 0
        for i in range(0, len(ids), 5000):
            res = await s.execute(delete(BarRow).where(BarRow.id.in_(ids[i:i + 5000])))
            deleted += int(res.rowcount or 0)
        await s.commit()
    return {"batch": batch, "rows": len(rows), "deleted": deleted, "reason": reason, "at": when.isoformat(timespec="seconds")}


async def cmd_quarantine(sf, *, reason: str, symbols, date_from, date_to, apply: bool, note: str) -> dict:
    rows = await select_quarantine(sf, reason=reason, symbols=symbols, date_from=date_from, date_to=date_to)
    by = Counter((r.symbol, session_date(r.ts)) for r in rows)
    print(f"{'APPLY' if apply else 'DRY RUN'}: {len(rows)} row(s) in {len(by)} symbol-session(s) selected for reason={reason}")
    for (sym, d), n in sorted(by.items())[:60]:
        print(f"   {sym:<6} {d} {dt.date.fromisoformat(d).strftime('%a')} {n} rows")
    if len(by) > 60:
        print(f"   ... {len(by) - 60} more")
    if not apply or not rows:
        return {"selected": len(rows), "applied": False}
    rec = await apply_quarantine(sf, rows, reason=reason, note=note)
    print(f"quarantined batch {rec['batch']}: {rec['rows']} copied, verified, {rec['deleted']} deleted from bars")
    return {**rec, "applied": True}


# ------------------------------------------------------------------ backfill
async def cmd_backfill(sf, *, symbols: list[str] | None, all_symbols: bool, date_from: str, date_to: str, pace: float,
                       fetch=None) -> dict:
    """Exchange 1m bars (Alpaca SIP via `fetch_window`, extended hours) for the range, written with
    source=exchange so they overwrite sampled/unknown rows. One request per symbol for the whole
    range (Alpaca pages 10k bars) — paced so the live feed's REST budget is not starved."""
    from ..marketstructure.history import fetch_window, set_alpaca_credentials
    cfg = get_config()
    if fetch is None:
        if not (cfg.alpaca_key_id and cfg.alpaca_secret):
            raise SystemExit("backfill needs ZARGAR_ALPACA_KEY_ID / SECRET (Yahoo's 1m depth is ~20 days; the sim block is older)")
        set_alpaca_credentials(cfg.alpaca_key_id, cfg.alpaca_secret)
        fetch = fetch_window
    syms = await _symbols(sf, None if all_symbols else symbols)
    if all_symbols:
        from ..options import occ
        skipped = [x for x in syms if occ.is_occ(x) or "." in x or "=" in x or x.startswith("^")]
        syms = [x for x in syms if x not in skipped]
        if skipped:
            print(f"--all: skipping {len(skipped)} symbol(s) Alpaca's stock bars cannot serve (option contracts, non-US listings, indices)")
    if not syms:
        raise SystemExit("backfill: no symbols (use --symbols A,B or --all)")
    start_ms = _day_bounds_ms(date_from)[0]
    end_ms = _day_bounds_ms(date_to)[1]
    days = [d.isoformat() for d in trading_days(date_from, date_to)]
    out = {"symbols": {}, "days": days, "from": date_from, "to": date_to}
    for i, sym in enumerate(syms):
        try:
            bars = await fetch(sym, "1m", start_ms, end_ms, session="ext")
        except Exception as exc:  # noqa: BLE001
            print(f"{sym}: fetch failed: {exc}")
            out["symbols"][sym] = {"error": str(exc)[:120]}
            continue
        for b in bars:
            b.source = "exchange"
        before = await _rows(sf, sym, start_ms, end_ms)
        before_by = {r.ts: (r.open, r.high, r.low, r.close, r.volume, r.source) for r in before}
        await persist_bars(sf, bars)
        # a minute the venue has NO bar for had no prints: a surviving quote-sampled row there keeps its
        # price track but its volume was a counter artefact (SPY 2026-08-20 pre-market: 39.8M in one
        # minute) - it is zero by definition (F78)
        zeroed = 0
        if bars:
            have = {b.ts for b in bars}
            lo_ts, hi_ts = min(have), max(have)
            async with sf() as s:
                res = await s.execute(
                    text("UPDATE bars SET volume = 0 WHERE symbol = :sym AND tf = '1m' AND ts >= :lo AND ts <= :hi "
                         "AND source <> 'exchange' AND volume <> 0"),
                    {"sym": sym, "lo": lo_ts, "hi": hi_ts})
                zeroed = int(res.rowcount or 0)
                await s.commit()
        after = await _rows(sf, sym, start_ms, end_ms)
        changed = sum(1 for r in after if r.ts in before_by and before_by[r.ts] != (r.open, r.high, r.low, r.close, r.volume, r.source))
        added = sum(1 for r in after if r.ts not in before_by)
        srcs = Counter((r.source or "unknown") for r in after)
        out["symbols"][sym] = {"fetched": len(bars), "changed": changed, "added": added, "rowsAfter": len(after),
                               "volumeZeroed": zeroed, "sources": dict(srcs)}
        print(f"{sym:<6} fetched={len(bars):<6} changed={changed:<6} added={added:<6} zeroed={zeroed:<6} rows={len(after):<6} {dict(srcs)}")
        if pace and i + 1 < len(syms):
            await asyncio.sleep(pace)
    return out


# ------------------------------------------------------------------ version
async def cmd_version(sf, *, symbols: list[str] | None, date_from: str, date_to: str, note: str) -> dict:
    syms = await _symbols(sf, symbols)
    v = await dataset_version(sf, syms, start=date_from, end=date_to, note=note)
    print(json.dumps(v, indent=1))
    return v


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", default="", help="override ZARGAR_DATABASE_URL (tests)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit"); a.add_argument("--symbols", default=""); a.add_argument("--json", default=""); a.add_argument("--all-sessions", action="store_true")
    q = sub.add_parser("quarantine"); q.add_argument("--reason", required=True); q.add_argument("--symbols", default="")
    q.add_argument("--from", dest="date_from", default=None); q.add_argument("--to", dest="date_to", default=None)
    q.add_argument("--apply", action="store_true"); q.add_argument("--note", default="")
    b = sub.add_parser("backfill"); b.add_argument("--symbols", default=""); b.add_argument("--all", action="store_true")
    b.add_argument("--from", dest="date_from", required=True); b.add_argument("--to", dest="date_to", required=True)
    b.add_argument("--pace", type=float, default=0.5)
    v = sub.add_parser("version"); v.add_argument("--symbols", default=""); v.add_argument("--from", dest="date_from", required=True)
    v.add_argument("--to", dest="date_to", required=True); v.add_argument("--note", default="")
    args = p.parse_args(argv)
    url = args.database_url or get_config().database_url
    syms = [s for s in (getattr(args, "symbols", "") or "").split(",") if s] or None

    async def run():
        eng = make_engine(url)
        await create_all(eng)
        sf = make_session_factory(eng)
        try:
            if args.cmd == "audit":
                await cmd_audit(sf, syms, args.json, only_flagged=not args.all_sessions)
            elif args.cmd == "quarantine":
                await cmd_quarantine(sf, reason=args.reason, symbols=syms, date_from=args.date_from, date_to=args.date_to,
                                     apply=args.apply, note=args.note)
            elif args.cmd == "backfill":
                await cmd_backfill(sf, symbols=syms, all_symbols=args.all, date_from=args.date_from, date_to=args.date_to, pace=args.pace)
            elif args.cmd == "version":
                await cmd_version(sf, symbols=syms, date_from=args.date_from, date_to=args.date_to, note=args.note)
        finally:
            await eng.dispose()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
