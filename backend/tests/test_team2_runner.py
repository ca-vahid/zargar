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
    # drive the regular session bar by bar
    rth = filter_session(today, "rth")
    for b in rth:
        await eng.team2_runner.on_bar(run_id, b)
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
