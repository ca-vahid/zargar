"""F75 consumer validation: Team2 plans, warm-ups, replays and sweeps read only valid sessions, the
lookback counts VALID sessions (all ten of them), and the plan records what was used and excluded."""
from __future__ import annotations

import datetime as dt
import math

from zargar.marketdata import persist_bars
from zargar.marketstructure import aggregate, filter_session
from zargar.marketstructure.sessions import session_date
from zargar.techniques.team2.history import validate_sessions
from zargar.techniques.team2.levels import targets_beyond
from zargar.techniques.team2.plan import build_skeleton
from zargar.techniques.team2.rules import Team2Rules

from .test_team2_runner import rig  # noqa: F401
from .test_team2_session import DAY, PREV, path_1m, prev_day_bars, trend_day, zones_of


def _session(date: dt.date, fn, *, flat: float | None = None):
    """One synthetic extended-hours session; `flat` makes it a one-price session (the closed-day artefact)."""
    if flat is not None:
        return path_1m(date, (4, 0), (20, 0), lambda i: flat, spread=0.0, vol=0)   # low == high == close, like the real stubs
    return path_1m(date, (4, 0), (20, 0), fn)


def wave(base, amp, period=90):
    return lambda i: base + amp * math.sin(i / period)


def test_validate_sessions_flags_by_the_sessions_own_bars():
    bars = []
    bars += _session(dt.date(2026, 8, 31), wave(566, 1.5))            # Mon, real
    bars += _session(dt.date(2026, 9, 1), wave(567, 1.5))             # Tue, real
    bars += _session(dt.date(2026, 9, 5), None, flat=570.19)          # Sat, one price
    bars += _session(dt.date(2026, 9, 6), None, flat=570.19)          # Sun
    bars += _session(dt.date(2026, 9, 7), None, flat=570.19)          # Labor Day
    bars += _session(dt.date(2026, 9, 3), None, flat=568.0)           # Thu: a TRADING day the app sat on one price
    bars += _session(dt.date(2026, 9, 2), lambda i: 800 + 300 * math.sin(i / 200))   # Wed: a random walk, 500–1100
    bars += _session(dt.date(2026, 9, 4), wave(569, 1.5))[:40]        # Fri: only 40 pre-market bars banked
    valid, rep = validate_sessions(bars)
    reasons = {x["date"]: x["reason"] for x in rep["excluded"]}
    assert rep["used"] == ["2026-08-31", "2026-09-01"]
    assert reasons == {"2026-09-05": "closed_day", "2026-09-06": "closed_day", "2026-09-07": "closed_day",
                       "2026-09-03": "degenerate_flat", "2026-09-02": "outlier_range", "2026-09-04": "thin_rth"}
    assert {session_date(b.ts) for b in valid} == {"2026-08-31", "2026-09-01"}


def test_lookback_counts_ten_valid_sessions_not_ten_dates_present():
    """Ten real sessions with three flat closed-day sessions interleaved: the targets must equal the
    targets from the ten real sessions alone — every valid session still counts, the flat ones never do."""
    rules = Team2Rules()
    real_days = [dt.date(2026, 8, 24) + dt.timedelta(days=k) for k in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)]   # Aug 24–28, Aug 31–Sep 4
    bars_real = []
    for n, d in enumerate(real_days):
        bars_real += _session(d, wave(560 + n * 0.7, 2.0 + 0.3 * (n % 3), period=60 + 7 * n))
    bars_flat = []
    for d in (dt.date(2026, 8, 29), dt.date(2026, 8, 30), dt.date(2026, 9, 7)):
        bars_flat += _session(d, None, flat=571.1)
    mixed = sorted(bars_real + bars_flat, key=lambda b: b.ts)
    valid, rep = validate_sessions(mixed)
    assert len(rep["used"]) == 10 and len(rep["excluded"]) == 3
    prev15 = [b for b in aggregate([b for b in bars_real if session_date(b.ts) == "2026-09-04"], 15) if b.ts]
    zones = zones_of([b for b in bars_real if session_date(b.ts) == "2026-09-04"]) if False else None
    from zargar.marketstructure.dailylevels import prior_day_zones
    zones = prior_day_zones([b for b in prev15 if filter_session([b], "rth")])
    lb = rules.target_lookback_sessions
    f_valid = [b for b in aggregate(valid, 15) if b.ts and filter_session([b], "rth")]
    f_real = [b for b in aggregate(bars_real, 15) if b.ts and filter_session([b], "rth")]
    f_mixed_old_way = [b for b in aggregate(mixed, 15) if b.ts and filter_session([b], "rth")]
    dates_valid = sorted({session_date(b.ts) for b in f_valid})[-lb:]
    assert dates_valid == [d.isoformat() for d in real_days]                      # all ten valid sessions
    assert targets_beyond(f_valid, zones, lookback_sessions=lb) == targets_beyond(f_real, zones, lookback_sessions=lb)
    # what `history_for` did before F75: the last N session DATES present in the 1m tape, closed days included,
    # so the window held fewer than ten real sessions (the 15m RTH filter downstream could not give them back)
    old_dates = sorted({session_date(b.ts) for b in mixed})[-(lb + 2):]
    assert "2026-09-07" in old_dates and len(set(old_dates) & {d.isoformat() for d in real_days}) < 10
    assert f_mixed_old_way  # (the RTH-filtered 15m set itself never held closed-day bars — the slot loss was upstream)


async def test_plan_records_sessions_used_excluded_and_the_dataset_version(rig):
    eng, sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    flat_sat = _session(dt.date(2026, 8, 29), None, flat=float(prev[-1].close))   # a closed-day artefact before PREV
    for b in flat_sat:
        b.source = "sampled"
    for b in prev:
        b.source = "exchange"
    # the persister refuses closed-day bars now; plant the artefact the way the old writer did
    from sqlalchemy import insert
    from zargar.models import BarRow
    async with eng.sf() as s:
        await s.execute(insert(BarRow), [{"symbol": b.symbol, "tf": "1m", "ts": b.ts, "open": b.open, "high": b.high,
                                          "low": b.low, "close": b.close, "volume": b.volume, "source": "sampled"} for b in flat_sat])
        await s.commit()
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    ap = eng.team2_runner.get(out["armed"][0])
    hist = ap.plan.get("history") or {}
    assert hist.get("sessionsUsed") and PREV.isoformat() in hist["sessionsUsed"]
    assert any(x["date"] == "2026-08-29" and x["reason"] == "closed_day" for x in hist.get("excluded") or [])
    assert hist.get("datasetVersion") and len(hist["datasetVersion"]) == 64
    # the warm-up also refused it, and said so once
    await eng.team2.preopen_complete()
    rth = filter_session(today, "rth")
    for b in rth[:3]:
        await eng.team2_runner.on_bar(ap.run_id, b)
    ex = [e for e in ap.events if e["event"] == "history_excluded"]
    assert len(ex) == 1 and any(x["date"] == "2026-08-29" for x in ex[0]["excluded"])
    # the sweep cites the dataset it ran on
    res = await eng.team2.sweep(PREV.isoformat(), DAY.isoformat(), symbols=["SPY"], sigma=0.2)
    assert res.get("datasetVersion") and len(res["datasetVersion"]) == 64
