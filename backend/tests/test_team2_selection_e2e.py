"""Selection study S1 (`s1-r4`) END TO END through the REAL journal, the REAL runner hooks and the REAL persistence boundary, on
this desk's own test database: activation -> collection -> restart -> completion -> final report -> recorded -> verified.
Also the journal-write-failure and restart-before/after-commit cases. No network, no provider, no orders reach a venue."""
from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import insert, select

from zargar import events as ev
from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.events import Journal
from zargar.marketstructure.market_calendar import is_early_close, trading_days
from zargar.models import BarRow, Event, TechniqueArmed
from zargar.techniques.team2 import selection_study as ss
from zargar.techniques.team2 import selection_study_lifecycle as lc
from zargar.tools import team2_selection_study as tool

from . import test_team2_diagnostics as td
from .conftest import TEST_DB_URL
from .test_team2_selection_analysis import _feats, rows_for

MIN = 60_000
DAY_MS = 86_400_000
D1, D2 = dt.date(2026, 9, 14), dt.date(2026, 9, 15)
A = lc._ms(dt.date(2026, 9, 11), 20, 0)                      # activation: Friday evening; first eligible session 2026-09-14


class FlakyJournal:
    """The real journal, except that the first `fail_kinds` rows it is asked to write raise (a lost write)."""

    def __init__(self, inner, fail_kinds=()):
        self.inner, self.fail = inner, list(fail_kinds)

    async def append(self, type_, payload=None, **kw):
        k = (payload or {}).get("kind")
        if k in self.fail:
            self.fail.remove(k)
            raise ConnectionError("journal unavailable")
        return await self.inner.append(type_, payload, **kw)


def _runner(journal, off_ms: int, plan_for: str):
    opts = td.FakeOpts(td.chain(), {r["symbol"]: (0.55, 0.57) for r in td.chain()})
    refreshes = []

    async def refresh_now(sym):
        refreshes.append(sym)
        return opts.quote(sym)
    opts.refresh_now = refresh_now
    runner, ap = td.rig(opts)
    ap.plan_for = plan_for
    runner._bars[ap.run_id] = [dataclasses.replace(b, ts=b.ts + off_ms) for b in runner._bars[ap.run_id]]
    runner.engine.journal = journal
    runner.engine.settings = {"techniques.team2.selection_study": "collect"}
    runner._entry_time_refusal = lambda *a, **k: None
    runner.engine.positions = SimpleNamespace(equity=AsyncMock(return_value=10_000.0), cash=AsyncMock(return_value=10_000.0), get=lambda *a, **k: None)
    intents = []

    async def place(ap_, tr_, intent, **kw):
        intents.append(intent)
        return {"id": "ord-1", "status": "SUBMITTED"}
    runner._place_with_retry = place
    return runner, ap, intents


async def _fire(runner, ap, off_ms):
    ev_ = td.fire_event(td.ms(10, 0) + off_ms)
    st = [{"id": "scenario_1@09:45", "kind": "scenario_1", "direction": "long", "anchor": 100.5, "target": 103.0, "confirmedTs": td.ms(9, 45) + off_ms}]
    res = SimpleNamespace(events=[ev_], setups=st, to_dict=lambda: {"events": [ev_], "setups": st, "summary": {}})
    await runner._fire_from_event(ap, ev_, runner._bars[ap.run_id][-1], res, halted=False, journal=True)
    await runner.wait_fires()                                                      # the fire chain runs in its own task
    await td.drain(runner)


async def _ticks(runner, clock, start, n):
    for k in range(n):
        clock[0] = start + k * MIN
        runner._study_tick(clock[0])
        await td.drain(runner)


async def _study_rows(sf, kind=None):
    async with sf() as s:
        rows = (await s.execute(select(Event).where(Event.type == ev.TECHNIQUE_PLAN_DIAGNOSTIC).order_by(Event.id))).scalars().all()
    out = [dict(r.payload) for r in rows if str((r.payload or {}).get("kind", "")).startswith("selection_study_")]
    return [r for r in out if kind is None or r["kind"] == kind]


async def _reconcile(runner, ap, sf):
    async with sf() as s:
        await runner._study_reconcile(s, ap)


async def test_activation_collection_restart_completion_and_final_report(fresh_db, monkeypatch):
    import time as _time
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    journal = Journal(sf, Bus())
    clock = [td.ms(10, 0) + 1500]
    monkeypatch.setattr(_time, "time", lambda: clock[0] / 1000)
    try:
        # ---- activation (the tool's own payload and write path) and the setting, both durable
        await tool._append(sf, tool.activation_payload("e2e-build", A))
        async with sf() as s:
            s.add(Event(type="SettingChanged", ts=dt.datetime.fromtimestamp(A / 1000, dt.timezone.utc),
                        payload={"key": lc.SETTING_KEY, "new": "collect", "old": "off"}))
            s.add(TechniqueArmed(run_id="diag-run", technique="team2", symbol="SPY", plan_for=D1.isoformat(), portfolio_id="practice", mode="auto",
                                 config={}, status="armed", state={}))
            await s.commit()

        # ---- day 1: the real runner opens an opportunity; the engine RESTARTS mid-session with the record pending
        r1, ap1, intents1 = _runner(journal, 0, D1.isoformat())
        await _fire(r1, ap1, 0)
        assert intents1, "trading went ahead"
        base = clock[0]
        await _ticks(r1, clock, base, 11)                                            # the 10-minute observation is taken
        persisted = json.loads(json.dumps(r1.state_extras(ap1)))                      # what the plan persisted before the crash
        restart_at = base + 12 * MIN
        async with sf() as s:                                                          # the restart itself is durable
            s.add(Event(type=ev.TECHNIQUE_PLAN_RESTORED, ts=dt.datetime.fromtimestamp(restart_at / 1000, dt.timezone.utc),
                        aggregate_type="technique_run", aggregate_id="diag-run", payload={"runId": "diag-run", "symbol": "SPY"}))
            await s.commit()
        r2, ap2, _ = _runner(journal, 0, D1.isoformat())
        r2.restore_extras(ap2, persisted)
        await _reconcile(r2, ap2, sf)                                                  # no close journaled yet: the record stays pending
        assert r2._study_pending() == 1
        stale = json.loads(json.dumps(r2.state_extras(ap2)))
        await _ticks(r2, clock, restart_at, 22)                                        # the 30-minute observation, then the close
        closes = await _study_rows(sf, "selection_study_close")
        assert len(closes) == 1 and all(o["valid"] for o in closes[0]["observations"].values())
        # a SECOND restart with the stale persisted pending state: the journaled close is reconciled, never emitted twice
        r3, ap3, _ = _runner(journal, 0, D1.isoformat())
        r3.restore_extras(ap3, stale)
        await _reconcile(r3, ap3, sf)
        await _ticks(r3, clock, restart_at + 22 * MIN, 5)
        assert len(await _study_rows(sf, "selection_study_close")) == 1 and r3._study_pending() == 0

        # ---- day 2: an ordinary session, no restart
        clock[0] = td.ms(10, 0) + DAY_MS + 1500
        r4, ap4, intents4 = _runner(journal, DAY_MS, D2.isoformat())
        await _fire(r4, ap4, DAY_MS)
        await _ticks(r4, clock, clock[0], 34)
        day2 = [r for r in await _study_rows(sf) if r.get("date") == D2.isoformat()]
        assert [r["kind"] for r in day2] == ["selection_study_open", "selection_study_close"] and intents4

        # ---- the remaining sessions (synthetic rows through the same journal), bars for the outage rule, then the endpoint
        counted_days = [d for d in trading_days(D2, dt.date(2026, 12, 31)) if not is_early_close(d) and d != dt.date(2026, 10, 7)]
        d60 = counted_days[59]
        for d in trading_days(dt.date(2026, 9, 16), d60 + dt.timedelta(days=1)):
            for i in range(2):
                for row in rows_for(d, i, 3.0 + i, feats=_feats()):
                    await journal.append(ev.TECHNIQUE_PLAN_DIAGNOSTIC, {"runId": "synthetic", **row}, aggregate_type="technique_run", aggregate_id="synthetic")
        bars = []
        for d in trading_days(D1, d60 + dt.timedelta(days=3)):
            o, c = lc.session_bounds(d)
            for sym in ("SPY", "QQQ", "IWM"):
                for t in range(o, c, MIN):
                    if d == dt.date(2026, 10, 7) and sym == "IWM" and o + 30 * MIN <= t < o + 33 * MIN:
                        continue                                                       # a three-minute feed outage
                    bars.append({"symbol": sym, "tf": "1m", "ts": t, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1,
                                 "source": "exchange", "provider": "alpaca"})
        async with sf() as s:
            for k in range(0, len(bars), 20_000):
                await s.execute(insert(BarRow), bars[k:k + 20_000])
            await s.commit()

        now = lc.session_bounds(d60)[1]
        facts = await tool.load_facts(sf, now - 1)
        assert tool.life_of(facts, now - 1)["state"] == "collecting", "the 60th session is not complete until its close"
        facts = await tool.load_facts(sf, now)
        life = tool.life_of(facts, now)
        st = {s["date"]: s for s in life["sessions"]}
        assert life["state"] == "ready_for_final_analysis" and life["countedSessions"] == 60 and "60th" in life["endpointReason"]
        assert st[D1.isoformat()]["status"] == "excluded" and st[D1.isoformat()]["reasons"][0].startswith("engine restart at 10:12")
        assert st["2026-10-07"]["status"] == "excluded" and "IWM missing 3" in st["2026-10-07"]["reasons"][0]
        assert st["2026-11-27"] == {"date": "2026-11-27", "status": "excluded", "reasons": ["13:00 early close"]}

        # ---- the final report: frozen sample, reproducible, recorded, verified
        fin = lc.finalise(life, facts["rows"])
        oids = {x["opportunityId"] for x in fin["manifest"]["selectedRecords"]}
        assert day2[0]["opportunityId"] in oids, "the runner-produced opportunity of a counted session is in the sample"
        assert closes[0]["opportunityId"] not in oids and fin["diagnostics"]["rowsOutsideSample"]["session not counted"] >= 2
        again = lc.finalise(tool.life_of(await tool.load_facts(sf, now + 10 * DAY_MS), now + 10 * DAY_MS), (await tool.load_facts(sf, now))["rows"])
        assert again["manifestSha256"] == fin["manifestSha256"] and again["resultSha256"] == fin["resultSha256"]
        await tool._append(sf, lc.seal_payload(fin))
        facts = await tool.load_facts(sf, now + 1)
        life = tool.life_of(facts, now + 1)
        assert life["state"] == "finalized" and life["finalRecorded"]["resultSha256"] == fin["resultSha256"] and life["finalRecorded"]["intact"]
        v = lc.verify(life["finalRecorded"], life, facts["rows"], facts["rows"])
        assert v["resultMatches"] is True and v["matchesSeal"] is True and v["sealIntact"] is True
        view = lc.coverage_view(life, facts["rows"])
        assert view["countedSessions"] == 60 and view["collectorHealth"].get("journalWriteFailures", 0) == 0
    finally:
        await eng.dispose()


async def test_a_lost_journal_write_is_visible_and_the_opportunity_stays_in_the_denominator(fresh_db, monkeypatch):
    import time as _time
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    clock = [td.ms(10, 0) + 1500]
    monkeypatch.setattr(_time, "time", lambda: clock[0] / 1000)
    try:
        flaky = FlakyJournal(Journal(sf, Bus()), fail_kinds=["selection_study_open"])   # the OPENING row is lost
        r, ap, intents = _runner(flaky, 0, D1.isoformat())
        await _fire(r, ap, 0)
        await _ticks(r, clock, clock[0], 34)
        assert intents and r._study_health()["journalWriteFailures"] == 1
        rows = await _study_rows(sf)
        assert [x["kind"] for x in rows] == ["selection_study_close"]
        assert rows[0]["studyHealth"]["journalWriteFailures"] == 1, "the failure rides on the next row that is written"
        pop = ss.collapse([], rows)
        assert len(pop) == 1 and pop[0]["openingRecovered"] is True and pop[0]["complete"] is True
        life = {"countedDates": [D1.isoformat()], "state": "collecting", "study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH,
                "countedSessions": 1, "targetSessions": 60, "deadline": "2026-12-18", "statusCounts": {"counted": 1}, "sessions": []}
        view = lc.coverage_view(life, rows)
        assert view["opportunitiesInCountedSessions"] == 1 and view["recoveredOpenings"] == 1 and view["collectorHealth"]["journalWriteFailures"] == 1
        # the counters survive a restart through the persisted plan state
        persisted = json.loads(json.dumps(r.state_extras(ap))) if r.state_extras(ap).get("selectionStudy") else {"selectionStudy": {"records": {}, "health": r._study_health()}}
        r2, ap2, _ = _runner(Journal(sf, Bus()), 0, D1.isoformat())
        r2.restore_extras(ap2, persisted)
        assert r2._study_health()["journalWriteFailures"] == 1
        # an opening that WAS journaled while its close is lost stays `incomplete` (restart before the close is committed)
        clock[0] = td.ms(10, 0) + DAY_MS + 1500
        r3, ap3, _ = _runner(FlakyJournal(Journal(sf, Bus()), fail_kinds=["selection_study_close"]), DAY_MS, D2.isoformat())
        await _fire(r3, ap3, DAY_MS)
        await _ticks(r3, clock, clock[0], 34)
        day2 = [x for x in await _study_rows(sf) if x.get("date") == D2.isoformat()]
        assert [x["kind"] for x in day2] == ["selection_study_open"]
        assert ss.collapse(day2, [])[0]["status"] == "incomplete"
    finally:
        await eng.dispose()


def test_the_synchronous_hooks_create_no_coroutine_without_a_running_loop(recwarn):
    runner, ap = td.rig()
    runner.engine.settings = {"techniques.team2.selection_study": "collect"}
    rec = rows_for(D1, 0, 5.0, feats=_feats(), close=False)[0]
    runner._study_emit(ap.run_id, rec, "selection_study_open")
    assert runner._study_health()["noEventLoop"] == 1
    assert not [w for w in recwarn.list if "never awaited" in str(w.message)]
