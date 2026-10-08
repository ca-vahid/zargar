"""EDGAR -> Scout tables. Idempotent (the `scout_filings` ledger is keyed by accession;
trades are unique on (row_key, insider_cik)), resumable (progress lives in `scout_state`),
throttled (one `EdgarClient`). Shared by the daily job and `zargar.tools.scout_backfill`.
"""
from __future__ import annotations

import datetime as dt
import logging
import tempfile
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...models import ScoutFiling, ScoutInsiderTrade, ScoutState, utcnow
from . import datasets
from .edgar import EdgarClient, EdgarError
from .form4 import FORM4_TYPES, parse_daily_index, parse_form4, parse_header, trade_rows

log = logging.getLogger("zargar.scout.ingest")

EIGHT_K_TYPES = ("8-K",)
_TRADE_COLS = {c.name for c in ScoutInsiderTrade.__table__.columns} - {"id", "created_at"}


# --------------------------------------------------------------------------- state
async def get_state(sf, key: str) -> dict:
    async with sf() as s:
        row = await s.get(ScoutState, key)
        return dict(row.data or {}) if row else {}


async def put_state(sf, key: str, data: dict) -> None:
    async with sf() as s:
        stmt = pg_insert(ScoutState).values(key=key, data=data, updated_at=utcnow())
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"data": data, "updated_at": utcnow()})
        await s.execute(stmt)
        await s.commit()


# --------------------------------------------------------------------------- writes
async def known_accessions(sf, accessions: list[str], *, include_errors: bool = False) -> set[str]:
    """Accessions already in the ledger (errored ones are NOT known unless asked: they retry)."""
    out: set[str] = set()
    async with sf() as s:
        for i in range(0, len(accessions), 1000):
            chunk = accessions[i:i + 1000]
            q = select(ScoutFiling.accession).where(ScoutFiling.accession.in_(chunk))
            if not include_errors:
                q = q.where(ScoutFiling.status != "error")
            out.update((await s.execute(q)).scalars())
    return out


async def write_filings(session, filings: list[dict], *, replace: bool = False) -> None:
    for i in range(0, len(filings), 1000):
        chunk = filings[i:i + 1000]
        stmt = pg_insert(ScoutFiling).values(chunk)
        if replace:
            cols = {k for f in chunk for k in f} - {"accession"}
            stmt = stmt.on_conflict_do_update(index_elements=["accession"],
                                              set_={c: stmt.excluded[c] for c in cols})   # [] - `items` is a method name
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=["accession"])
        await session.execute(stmt)


async def write_trades(session, rows: list[dict]) -> int:
    n = 0
    for i in range(0, len(rows), 1000):
        chunk = [{k: r.get(k) for k in _TRADE_COLS} for r in rows[i:i + 1000]]
        stmt = pg_insert(ScoutInsiderTrade).values(chunk).on_conflict_do_nothing(
            index_elements=["row_key", "insider_cik"])
        res = await session.execute(stmt)
        n += res.rowcount or 0
    return n


# --------------------------------------------------------------------------- daily index
async def ingest_daily(sf, client: EdgarClient, day: dt.date, *, forms8k: bool = True,
                       ticker_for_cik: Callable[[str], Awaitable[str | None]] | None = None,
                       should_stop: Callable[[], bool] | None = None) -> dict:
    """One EDGAR daily form index: every new Form 4/4-A body (parsed, P/S rows stored) and,
    with `forms8k`, every new 8-K header (items + acceptance; S2 reads item 2.02)."""
    text = await client.daily_index(day)
    if text is None:
        return {"day": day.isoformat(), "published": False}
    wanted = FORM4_TYPES + (EIGHT_K_TYPES if forms8k else ())
    entries = parse_daily_index(text, forms=wanted)
    have = await known_accessions(sf, [e.accession for e in entries])
    stats = {"day": day.isoformat(), "published": True, "form4": 0, "form4New": 0, "trades": 0,
             "eightK": 0, "eightKNew": 0, "earnings": 0, "errors": 0, "stopped": False}
    for e in entries:
        is4 = e.form_type in FORM4_TYPES
        stats["form4" if is4 else "eightK"] += 1
        if e.accession in have:
            continue
        if should_stop and should_stop():
            stats["stopped"] = True
            break
        try:
            if is4:
                f = parse_form4(await client.submission_text(e.path))
                f.accession = f.accession or e.accession
                rows = trade_rows(f, source="daily")
                filing = {"accession": e.accession, "form_type": e.form_type, "issuer_cik": f.issuer_cik,
                          "ticker": f.ticker, "filed_date": f.filed_date or e.filed_date,
                          "acceptance_ts": f.acceptance_ts, "source": "daily", "status": "parsed"}
                async with sf() as s:
                    await write_filings(s, [filing], replace=True)
                    stats["trades"] += await write_trades(s, rows)
                    await s.commit()
                stats["form4New"] += 1
            else:
                hdr = await client.header(e.cik, e.accession)
                h = parse_header(hdr or "")
                items = ",".join(h["items"]) or None
                ticker = await ticker_for_cik(e.cik) if (ticker_for_cik and items and "2.02" in items) else None
                async with sf() as s:
                    await write_filings(s, [{"accession": e.accession, "form_type": e.form_type,
                                             "issuer_cik": e.cik.lstrip("0") or "0", "ticker": ticker,
                                             "filed_date": h["filed_date"] or e.filed_date,
                                             "acceptance_ts": h["acceptance_ts"], "items": items,
                                             "source": "daily", "status": "header"}], replace=True)
                    await s.commit()
                stats["eightKNew"] += 1
                if items and "2.02" in items:
                    stats["earnings"] += 1
        except (EdgarError, ValueError, SyntaxError) as exc:       # ParseError subclasses SyntaxError
            stats["errors"] += 1
            log.warning("scout ingest %s %s failed: %s", e.form_type, e.accession, exc)
            async with sf() as s:
                await write_filings(s, [{"accession": e.accession, "form_type": e.form_type,
                                         "issuer_cik": e.cik.lstrip("0") or "0", "filed_date": e.filed_date,
                                         "source": "daily", "status": "error", "error": str(exc)[:500]}])
                await s.commit()
    if not stats["stopped"]:
        done = await get_state(sf, "daily_days")
        done[day.isoformat()] = {k: stats[k] for k in ("form4", "form4New", "trades", "eightK", "earnings", "errors")}
        await put_state(sf, "daily_days", done)
    return stats


# --------------------------------------------------------------------------- quarterly data sets
async def ingest_dataset_quarter(sf, client: EdgarClient, year: int, q: int, *, since: str | None = None,
                                 workdir: Path | None = None) -> dict:
    name = datasets.quarter_name(year, q)
    tmpdir = Path(workdir or tempfile.gettempdir())
    tmpdir.mkdir(parents=True, exist_ok=True)
    dest = tmpdir / f"scout_{name}_form345.zip"
    got = await client.dataset_zip(name, dest)
    if got is None:
        return {"quarter": name, "published": False}
    try:
        filings, rows = datasets.parse_quarter(str(got), since=since)
    finally:
        try:
            got.unlink()
        except OSError:
            pass
    have = await known_accessions(sf, [f["accession"] for f in filings])  # daily-ingested filings keep their acceptance
    filings = [{**f, "source": "dataset", "status": "parsed"} for f in filings if f["accession"] not in have]
    keep = {f["accession"] for f in filings}
    rows = [r for r in rows if r["accession"] in keep]
    inserted = 0
    async with sf() as s:
        await write_filings(s, filings)
        inserted = await write_trades(s, rows)
        await s.commit()
    stats = {"quarter": name, "published": True, "filings": len(filings), "skippedKnown": len(have),
             "trades": inserted}
    done = await get_state(sf, "datasets")
    done[name] = {**stats, "at": utcnow().isoformat()}
    await put_state(sf, "datasets", done)
    return stats


def coverage_start(datasets_done: dict, daily_done: dict) -> str | None:
    """Start of the CONTIGUOUS history we hold: the earliest quarter of the unbroken run of
    ingested data-set quarters ending at the latest one (daily indexes extend it forward)."""
    qs = sorted(k for k, v in (datasets_done or {}).items() if v.get("published", True))
    if not qs:
        days = sorted(daily_done or {})
        return days[0] if days else None
    run = [qs[-1]]
    for name in reversed(qs[:-1]):
        y, q = int(run[-1][:4]), int(run[-1][-1])
        py, pq = (y, q - 1) if q > 1 else (y - 1, 4)
        if name == datasets.quarter_name(py, pq):
            run.append(name)
        else:
            break
    first = run[-1]
    return dt.date(int(first[:4]), 3 * (int(first[-1]) - 1) + 1, 1).isoformat()


# --------------------------------------------------------------------------- acceptance enrichment
async def enrich_acceptance(sf, client: EdgarClient, *, limit: int = 500, since: str | None = None,
                            should_stop: Callable[[], bool] | None = None) -> dict:
    """Stamp the SGML-header acceptance time on data-set filings that hold an officer/director
    open-market PURCHASE (the only rows S1 times) - newest first."""
    async with sf() as s:
        q = (select(ScoutFiling.accession, ScoutFiling.issuer_cik)
             .where(ScoutFiling.acceptance_ts.is_(None), ScoutFiling.status == "parsed",
                    ScoutFiling.accession.in_(
                        select(ScoutInsiderTrade.accession).where(
                            ScoutInsiderTrade.trans_code == "P",
                            or_(ScoutInsiderTrade.is_officer.is_(True), ScoutInsiderTrade.is_director.is_(True))))))
        if since:
            q = q.where(ScoutFiling.filed_date >= since)
        todo = (await s.execute(q.order_by(ScoutFiling.filed_date.desc()).limit(limit))).all()
    done = errors = 0
    for acc, cik in todo:
        if should_stop and should_stop():
            break
        try:
            h = parse_header(await client.header(cik or "0", acc) or "")
        except EdgarError as exc:
            errors += 1
            log.warning("scout enrich %s: %s", acc, exc)
            continue
        ts = h["acceptance_ts"]
        if ts is None:
            errors += 1
            continue
        async with sf() as s:
            await s.execute(update(ScoutFiling).where(ScoutFiling.accession == acc).values(acceptance_ts=ts))
            await s.execute(update(ScoutInsiderTrade).where(ScoutInsiderTrade.accession == acc)
                            .values(acceptance_ts=ts))
            await s.commit()
        done += 1
    return {"candidates": len(todo), "stamped": done, "errors": errors}


async def counts(sf) -> dict:
    async with sf() as s:
        filings = (await s.execute(select(ScoutFiling.form_type, ScoutFiling.source, func.count())
                                   .group_by(ScoutFiling.form_type, ScoutFiling.source))).all()
        trades = (await s.execute(select(ScoutInsiderTrade.trans_code, func.count())
                                  .group_by(ScoutInsiderTrade.trans_code))).all()
        rng = (await s.execute(select(func.min(ScoutInsiderTrade.trans_date),
                                      func.max(ScoutInsiderTrade.trans_date)))).one()
        unstamped = (await s.execute(select(func.count()).select_from(ScoutFiling).where(and_(
            ScoutFiling.acceptance_ts.is_(None), ScoutFiling.form_type.in_(FORM4_TYPES))))).scalar_one()
    return {"filings": [{"form": f, "source": src, "n": n} for f, src, n in filings],
            "trades": {c: n for c, n in trades}, "tradeDates": {"from": rng[0], "to": rng[1]},
            "form4WithoutAcceptance": unstamped}
