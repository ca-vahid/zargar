"""Team2 on the real engine (sim broker, real Postgres): plan runs are minted from banked bars,
armed in alert mode, driven bar by bar through the runner's override of the bar loop, and the
read's events land in the plan's audit + journal; the 09:25 completion fills the pre-market
levels; replay over the same bars reproduces the live events (parity)."""
from __future__ import annotations

import datetime as dt

import pytest

from zargar.engine import Engine
from zargar.marketdata import persist_bars
from zargar.marketstructure import aggregate, filter_session
from zargar.marketstructure.sessions import ET, session_date
from zargar.techniques.team2.runner import attach_team2_runner

from .conftest import make_test_config, wait_for
from .test_team2_session import DAY, PREV, prev_day_bars, trend_day


@pytest.fixture
async def rig(fresh_db, monkeypatch):
    config = make_test_config(anthropic_api_key="")
    eng = Engine(config)
    await eng.start()
    await eng.settings.set("execution.arm_expired_plans", True, journal=False)   # synthetic days are in the past
    await eng.settings.set("techniques.team2.symbols", ["SPY"], journal=False)
    await eng.settings.set("techniques.team2.mode", "alert", journal=False)
    # no network: the 09:25 completion and the day-one warm-up fetch Yahoo when nothing is banked
    import zargar.marketstructure.history as hist
    async def _no_fetch(*a, **k):
        return []
    monkeypatch.setattr(hist, "fetch_extended_session", _no_fetch)
    monkeypatch.setattr(hist, "fetch_window", _no_fetch)
    await attach_team2_runner(eng)
    sim = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")
    await eng.settings.set("trading.default_portfolio", sim["id"], journal=False)
    yield eng, sim
    await eng.team2_runner.stop()
    await eng.stop()


async def _bank(eng, bars):
    await persist_bars(eng.sf, bars)


async def test_nightly_plan_arm_and_alert_mode_fire(rig):
    eng, sim = rig
    prev = prev_day_bars()
    today, zones = trend_day(prev)
    await _bank(eng, prev)                                             # the ext-hours bank (E1/B1)
    pre = filter_session(today, "pre")
    await _bank(eng, pre)                                              # pre-market already banked at 09:25
    svc = eng.team2
    out = await svc.nightly_plans(DAY.isoformat(), arm=True)
    assert out["runs"] and out["armed"] and not out["failed"], out
    run_id = out["armed"][0]
    ap = eng.team2_runner.get(run_id)
    assert ap is not None and ap.config.mode == "alert" and ap.technique == "team2"
    assert ap.plan["zones"]["pdh"]["top"] == pytest.approx(zones["pdh"].top)
    # 09:25 completion: PMH/PML from the banked pre-market bars
    done = await svc.preopen_complete()
    assert run_id in done["completed"] and ap.plan["pmh"] and ap.plan["pml"] and ap.plan["complete"]
    assert any(e["event"] == "preopen" for e in ap.events)
    # F-1/F-2: the completed plan and the rules the session runs under are stamped back onto the
    # run, so a replay reproduces the live session instead of re-deriving PMH/PML and the day type
    # from whatever bars exist later (which would pick the 09:30 RTH open, not the 09:25 read).
    run_row = await eng.team2_runner.load_plan(run_id)
    stored_plan = (run_row["result"] or {})["plan"]
    assert stored_plan["complete"] and stored_plan["pmh"] == ap.plan["pmh"]
    assert stored_plan["dayType"] == ap.plan["dayType"]
    assert stored_plan["sizingAtOpen"] == ap.plan["sizingAtOpen"]
    # and the thresholds are the LIVE rules, not whatever was frozen when the plan was minted
    from zargar.techniques.team2.rules import rules_from_settings
    assert (run_row["config"] or {})["thresholds"] == rules_from_settings(eng.settings).to_dict()
    # the Armed page's snapshot speaks the method's words before anything happened
    snap = eng.team2_runner.detail(run_id)
    assert snap["technique"] == "team2" and len(snap["triggers"]) == 2
    assert snap["triggers"][0]["kind"] == "break PDH" and snap["triggers"][1]["direction"] == "short"
    assert "no scenario yet" in snap["summary"] and "PM" in snap["summary"]
    assert snap["team2"]["sheet"] and snap["team2"]["dayType"]
    # drive the regular session bar by bar
    rth = filter_session(today, "rth")
    mid_snap = None
    for i, b in enumerate(rth):
        await eng.team2_runner.on_bar(run_id, b)
        if i == 60:
            mid_snap = eng.team2_runner.detail(run_id)
    assert mid_snap is not None and any(t["kind"].startswith("scenario_") for t in mid_snap["triggers"])
    assert "scenario 1" in mid_snap["summary"] or "in trade" in mid_snap["summary"], mid_snap["summary"]
    events = [e["event"] for e in ap.events]
    assert "scenario" in events and "fired" in events, events[:20]
    trades = list(ap.trades.values())
    assert trades and trades[0].status == "alert" and trades[0].instrument == "options"
    assert trades[0].direction == "long"                                # one banked session → no pivot target yet (L3.1)
    assert any(e["event"] in ("would_trim", "would_exit") for e in ap.events)
    # the journal carries the read (fired + skipped/scenario rows under the run id)
    rows = await eng.team2_runner.audit(run_id)
    kinds = {r.get("kind") or r.get("type") or r.get("event") for r in rows}
    assert rows and any("Fired" in str(k) or "fired" in str(k).lower() for k in kinds)
    # the session closed → plan expired and disarmed; the last read is kept for the UI
    assert ap.status in ("expired", "disarmed")
    assert eng.team2_runner.last_read(run_id)["summary"]["trades"] >= 1
    # parity: the service replay over the same banked bars sees the same fire
    await _bank(eng, rth)
    rep = await svc.replay(run_id)
    rep_fire = next(e for e in rep["result"]["events"] if e["event"] == "fire")
    assert rep_fire["ts"] == trades[0].fired_ts                         # same bar, same read (parity)
    listed = await svc.runs()
    assert listed and listed[0]["runId"] == run_id and listed[0]["planFor"] == DAY.isoformat()


async def test_sweep_over_banked_days(rig):
    eng, sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await _bank(eng, prev + today)
    res = await eng.team2.sweep(PREV.isoformat(), DAY.isoformat(), symbols=["SPY"], sigma=0.2)
    ok = [r for r in res["rows"] if r["status"] == "ok"]
    assert len(ok) == 1 and ok[0]["date"] == DAY.isoformat()          # PREV has no previous session banked
    assert res["summary"]["trades"] >= 1 and res["summary"]["winRate"] is not None
    # variant harness: a stricter touch rule changes the row set deterministically
    res2 = await eng.team2.sweep(PREV.isoformat(), DAY.isoformat(), symbols=["SPY"], sigma=0.2,
                                 overrides={"pullback_max_touches": 0})
    assert res2["summary"]["trades"] == 0 and res2["thresholds"]["pullback_max_touches"] == 0


async def test_alert_mode_still_reads_the_tape_while_halted(rig):
    """F17: the kill switch blocks the MONEY modes. Alert mode places nothing, so a halt on the
    shared portfolio (another technique's daily loss engages it) must not silence Team2's read —
    it went silent live on 2026-09-04 when Practice halted at 09:38 and QQQ's 10:02 fire became a
    `halt_skip`, which also broke live-vs-replay parity."""
    eng, sim = rig
    prev = prev_day_bars()
    today, _zones = trend_day(prev)
    await _bank(eng, prev)
    await _bank(eng, filter_session(today, "pre"))
    svc = eng.team2
    out = await svc.nightly_plans(DAY.isoformat(), arm=True)
    run_id = out["armed"][0]
    ap = eng.team2_runner.get(run_id)
    await svc.preopen_complete()
    eng.halt.engage("test: another technique's daily loss")             # the shared-portfolio halt
    assert eng.halt.engaged
    for b in filter_session(today, "rth"):
        await eng.team2_runner.on_bar(run_id, b)
    events = [e["event"] for e in ap.events]
    assert "fired" in events, events[:20]                               # the read still happens
    assert "halt_skip" not in events, events[:20]
    fired = next(e for e in ap.events if e["event"] == "fired")
    assert fired["haltedAtFire"] is True                                # ...and says the halt was on
    trades = list(ap.trades.values())
    assert trades and trades[0].status == "alert"                       # nothing was routed
    # parity survives the halt: the replay of the same bars sees the same fire
    await _bank(eng, filter_session(today, "rth"))
    rep = await svc.replay(run_id)
    rep_fire = next(e for e in rep["result"]["events"] if e["event"] == "fire")
    assert rep_fire["ts"] == trades[0].fired_ts
