"""`zargar.tools.bars_repair`: audit flags, quarantine preserves-verifies-deletes, backfill corrects by
provenance, and the dataset version changes with content (F75, 2026-09-09)."""
from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select

from zargar.db import make_engine, make_session_factory
from zargar.domain import Bar
from zargar.marketdata import dataset_version, load_bars
from zargar.models import BarQuarantineRow, BarRow
from zargar.tools.bars_repair import audit_sessions, cmd_backfill, cmd_quarantine, select_quarantine

from .conftest import TEST_DB_URL

ET = ZoneInfo("America/New_York")


def rows_for(sym: str, date: dt.date, fn, *, source="sampled", start=(4, 0), end=(20, 0)):
    out = []
    t = dt.datetime.combine(date, dt.time(*start), ET)
    stop = dt.datetime.combine(date, dt.time(*end), ET)
    i = 0
    while t < stop:
        px = fn(i)
        out.append({"symbol": sym, "tf": "1m", "ts": int(t.timestamp() * 1000), "open": px, "high": px + 0.05, "low": px - 0.05,
                    "close": px, "volume": 1000, "source": source})
        t += dt.timedelta(minutes=1)
        i += 1
    return out


async def _plant(sf, rows):
    async with sf() as s:
        await s.execute(insert(BarRow), rows)
        await s.commit()


async def test_audit_quarantine_and_backfill(fresh_db, monkeypatch):
    sf = make_session_factory(make_engine(TEST_DB_URL))
    real = rows_for("TST", dt.date(2026, 9, 1), lambda i: 100 + 1.5 * math.sin(i / 60))
    sat = [dict(r, high=r["close"], low=r["close"], volume=0) for r in rows_for("TST", dt.date(2026, 9, 5), lambda i: 101.0)]
    labor = [dict(r, high=r["close"], low=r["close"]) for r in rows_for("TST", dt.date(2026, 9, 7), lambda i: 101.0, start=(13, 47))]
    walk = rows_for("TST", dt.date(2026, 8, 18), lambda i: 800 + 300 * math.sin(i / 200))
    flat_trading = [dict(r, high=r["close"], low=r["close"]) for r in rows_for("TST", dt.date(2026, 9, 3), lambda i: 100.0)]
    spike = rows_for("TST", dt.date(2026, 9, 8), lambda i: 100 + math.sin(i / 50))
    spike[400]["volume"] = 43_000_000                                # 10:40 ET, a sampled row: flagged
    auction = rows_for("TST", dt.date(2026, 9, 2), lambda i: 100.0 + math.sin(i / 40), source="exchange")
    auction[330]["volume"] = 40_000_000                             # 09:30 ET on an exchange row: an auction, not a spike
    missing = spike.pop(500)                                   # a minute the app never banked (it was down)
    await _plant(sf, real + sat + labor + walk + flat_trading + spike + auction)

    rows = list((await load_bars(sf, "TST", "1m", limit=100000)))
    async with sf() as s:
        db_rows = (await s.execute(select(BarRow).where(BarRow.symbol == "TST").order_by(BarRow.ts))).scalars().all()
    rep = {r["date"]: r for r in audit_sessions(db_rows)}
    assert rep["2026-09-01"]["flags"] == [] and rep["2026-09-01"]["kind"] == "stock"
    # an option contract is never flagged for its range or flatness
    opt = [dict(r, symbol="TST260918C00100000", high=r["close"], low=r["close"]) for r in rows_for("TST260918C00100000", dt.date(2026, 9, 2), lambda i: 0.05)]
    await _plant(sf, opt)
    async with sf() as s:
        opt_rows = (await s.execute(select(BarRow).where(BarRow.symbol == "TST260918C00100000"))).scalars().all()
    orep = audit_sessions(opt_rows)
    assert orep[0]["kind"] == "option" and orep[0]["flags"] == []
    assert rep["2026-09-05"]["flags"] == ["closed_day"] and rep["2026-09-07"]["flags"] == ["closed_day"]
    assert rep["2026-08-18"]["flags"] == ["outlier_range"]
    assert rep["2026-09-03"]["flags"] == ["degenerate_flat"]
    assert "volume_spike" in rep["2026-09-08"]["flags"]
    assert rep["2026-09-02"]["flags"] == []                                # the 09:30 auction print on a venue bar is not a spike

    # quarantine by reason = closed_day takes ONLY the closed days; the flat trading day and the walk stay
    picked = await select_quarantine(sf, reason="closed_day", symbols=["TST"], date_from=None, date_to=None)
    assert {r.ts for r in picked} == {r["ts"] for r in sat + labor}
    dry = await cmd_quarantine(sf, reason="closed_day", symbols=["TST"], date_from=None, date_to=None, apply=False, note="")
    assert dry["applied"] is False and len(await load_bars(sf, "TST", "1m", limit=100000)) == len(db_rows)
    done = await cmd_quarantine(sf, reason="closed_day", symbols=["TST"], date_from=None, date_to=None, apply=True, note="test")
    assert done["applied"] and done["rows"] == len(sat) + len(labor) == done["deleted"] and done["missingAtApply"] == []
    left = await load_bars(sf, "TST", "1m", limit=100000)
    assert {b.ts for b in left} == {r["ts"] for r in real + walk + flat_trading + spike + auction}
    async with sf() as s:
        q = (await s.execute(select(BarQuarantineRow).where(BarQuarantineRow.batch == done["batch"]))).scalars().all()
    assert len(q) == done["rows"] and all(x.reason == "closed_day" and x.orig_id for x in q)
    # a synthetic block is quarantined by an explicit scope only
    try:
        await select_quarantine(sf, reason="sim_feed", symbols=None, date_from=None, date_to=None)
        assert False, "explicit scope required"
    except SystemExit:
        pass
    done2 = await cmd_quarantine(sf, reason="sim_feed", symbols=["TST"], date_from="2026-08-18", date_to="2026-08-18", apply=True, note="walk")
    assert done2["rows"] == len(walk)
    assert not any(b.ts == walk[0]["ts"] for b in await load_bars(sf, "TST", "1m", limit=100000))

    # backfill: the exchange tape replaces the sampled rows (the spike minute included) and adds missing minutes
    v_before = await dataset_version(sf, ["TST"], start="2026-09-08", end="2026-09-08", record=False)

    async def fake_fetch(symbol, tf, start_ms, end_ms, *, session="ext", **kw):
        out = []
        for r in spike:
            out.append(Bar(symbol=symbol, tf="1m", ts=r["ts"], open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=812))
        out.append(Bar(symbol=symbol, tf="1m", ts=missing["ts"], open=1, high=1, low=1, close=1, volume=1))
        return out

    # one sampled minute the venue never returns (no prints there) that carries a bogus volume
    orphan_ts = spike[-1]["ts"] - 60_000
    spike[:] = [r for r in spike if r["ts"] != orphan_ts]
    from sqlalchemy import update
    async with sf() as s_:
        await s_.execute(update(BarRow).where(BarRow.symbol == "TST", BarRow.ts == orphan_ts).values(volume=7_000_000))
        await s_.commit()
    res = await cmd_backfill(sf, symbols=["TST"], all_symbols=False, date_from="2026-09-08", date_to="2026-09-08", pace=0, fetch=fake_fetch)
    st = res["symbols"]["TST"]
    assert st["changed"] == len(spike) + 1 and st["added"] == 1 and st["sources"] == {"exchange": len(spike) + 1, "sampled": 1}   # +1: the zeroed orphan
    assert st["volumeZeroed"] == 1 and st["provider"] == "alpaca" and st["coveredDays"] == ["2026-09-08"]
    orphan_row = [b for b in await load_bars(sf, "TST", "1m", limit=100000) if b.ts == orphan_ts][0]
    assert orphan_row.volume == 0 and orphan_row.source == "sampled"
    # a PARTIAL venue answer (a handful of bars) covers nothing and zeroes nothing (R5)
    async with sf() as s_:
        await s_.execute(update(BarRow).where(BarRow.symbol == "TST", BarRow.ts == orphan_ts).values(volume=7_000_000, source="sampled"))
        await s_.commit()

    async def partial_fetch(symbol, tf, start_ms, end_ms, *, session="ext", **kw):
        return [Bar(symbol=symbol, tf="1m", ts=r_["ts"], open=r_["open"], high=r_["high"], low=r_["low"], close=r_["close"], volume=812)
                for r_ in spike[:5]]

    res2 = await cmd_backfill(sf, symbols=["TST"], all_symbols=False, date_from="2026-09-08", date_to="2026-09-08", pace=0, fetch=partial_fetch)
    st2 = res2["symbols"]["TST"]
    assert st2["volumeZeroed"] == 0 and st2["uncoveredDays"] == ["2026-09-08"]
    assert [b for b in await load_bars(sf, "TST", "1m", limit=100000) if b.ts == orphan_ts][0].volume == 7_000_000
    fixed = [b for b in await load_bars(sf, "TST", "1m", limit=100000) if b.ts == spike[400]["ts"]][0]
    assert fixed.volume == 812 and fixed.source == "exchange"
    v_after = await dataset_version(sf, ["TST"], start="2026-09-08", end="2026-09-08", record=False)
    assert v_after["hash"] != v_before["hash"]
