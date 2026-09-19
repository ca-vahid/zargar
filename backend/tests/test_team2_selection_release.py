"""Selection study S1 (`s1-r4`) release boundaries: the ACTUAL operator CLI in subprocesses on this desk's test database, journal-order
precedence (first opening, first bound close) under shuffled transport, and the sealed first finalization against later rows,
later backfills and repeated `final --record`. No runtime database, no network, no orders."""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import random
import subprocess
import sys

import pytest
from sqlalchemy import func, insert, select

from zargar import events as ev
from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.events import Journal
from zargar.marketstructure.market_calendar import trading_days
from zargar.models import BarRow, Event
from zargar.techniques.team2 import selection_study as ss
from zargar.techniques.team2 import selection_study_analysis as an
from zargar.techniques.team2 import selection_study_lifecycle as lc
from zargar.tools import team2_selection_study as tool

from .conftest import TEST_DB_URL
from .test_team2_selection_analysis import _feats, rows_for
from .test_team2_selection_lifecycle import FULL, act, close_of, life, opp

MIN = 60_000
BAD = ("Event loop is closed", "never awaited", "Traceback", "RuntimeError")


# ------------------------------------------------------------------ the actual CLI
def cli(*args, timeout=120):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", ZARGAR_DATABASE_URL=TEST_DB_URL)     # never the runtime database
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "zargar.tools.team2_selection_study", *args], env=env,
                       capture_output=True, text=True, timeout=timeout)
    for word in BAD:
        assert word not in r.stderr, (args, r.stderr[-2000:])
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout)


async def _count(sf, kind):
    async with sf() as s:
        rows = (await s.execute(select(Event.payload).where(Event.type == ev.TECHNIQUE_PLAN_DIAGNOSTIC))).scalars().all()
    return sum(1 for p in rows if (p or {}).get("kind") == kind)


async def test_the_real_cli_status_activate_and_duplicate_activation_on_the_test_database(fresh_db, tmp_path):
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    try:
        rc, out = cli("status")
        assert rc == 0 and out["state"] == "prepared" and out["view"].startswith("coverage only")
        rc, out = cli("activate", "--build", "cli-build", "--confirm", "wrong")
        assert rc == 2 and "refused" in out and await _count(sf, "selection_study_activation") == 0
        rc, out = cli("activate", "--build", "cli-build", "--confirm", ss.REGISTRATION_HASH)
        assert rc == 0 and out["activated"]["registrationHash"] == ss.REGISTRATION_HASH and out["activated"]["build"] == "cli-build"
        rc, out = cli("activate", "--build", "cli-build-2", "--confirm", ss.REGISTRATION_HASH)
        assert rc == 2 and "already activated" in out["refused"]
        assert await _count(sf, "selection_study_activation") == 1
        rc, out = cli("status")
        assert rc == 0 and out["state"] == "collecting" and out["collectorEnabledNow"] is False and out["operatorAction"] is None
        rc, out = cli("final", "--out", str(tmp_path / "f"), "--record")
        assert rc == 2 and "final analysis only after the endpoint" in out["refused"]
        assert await _count(sf, "selection_study_final") == 0 and not (tmp_path / "f" / "final.json").exists()
    finally:
        await eng.dispose()


A_PAST = lc._ms(dt.date(2026, 6, 1), 20, 0)
GAP_DAY = dt.date(2026, 6, 10)


async def _seed_completed_study(sf):
    """A study activated on 2026-06-01 whose endpoint (60 counted sessions) is in the past: activation, setting, bars (with a
    three-minute IWM gap on 2026-06-10), and one opportunity per session, all through the real journal."""
    j = Journal(sf, Bus())
    await tool._append(sf, tool.activation_payload("cli-build", A_PAST))
    async with sf() as s:
        s.add(Event(type="SettingChanged", ts=dt.datetime.fromtimestamp(A_PAST / 1000, dt.timezone.utc),
                    payload={"key": lc.SETTING_KEY, "new": "collect", "old": "off"}))
        await s.commit()
    days = trading_days(dt.date(2026, 6, 2), dt.date(2026, 9, 18))
    bars = []
    for d in days:
        o, c = lc.session_bounds(d)
        for sym in ("SPY", "QQQ", "IWM"):
            for t in range(o, c, MIN):
                if d == GAP_DAY and sym == "IWM" and o + 30 * MIN <= t < o + 33 * MIN:
                    continue
                bars.append({"symbol": sym, "tf": "1m", "ts": t, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1,
                             "source": "exchange", "provider": "alpaca"})
    async with sf() as s:
        for k in range(0, len(bars), 20_000):
            await s.execute(insert(BarRow), bars[k:k + 20_000])
        await s.commit()
    for i, d in enumerate(days):
        for row in rows_for(d, 0, 3.0 + i % 5, feats=_feats(flag=("flag" if i % 3 == 0 else "no_flag"))):
            await j.append(ev.TECHNIQUE_PLAN_DIAGNOSTIC, {"runId": "seed", **row}, aggregate_type="technique_run", aggregate_id="seed")
    return days


async def test_the_real_cli_seals_the_first_final_and_later_rows_or_backfills_never_change_it(fresh_db, tmp_path):
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    try:
        days = await _seed_completed_study(sf)
        rc, out = cli("status")
        assert rc == 0 and out["state"] == "ready_for_final_analysis" and out["countedSessions"] == 60
        assert out["operatorAction"] and "never changes a setting" in out["operatorAction"], "the tool tells the operator; it switches nothing"
        assert any(s["date"] == GAP_DAY.isoformat() and s["status"] == "excluded" for s in out["nonCounted"])
        d1, d2, d3 = tmp_path / "d1", tmp_path / "d2", tmp_path / "d3"
        rc, first = cli("final", "--out", str(d1), "--record")
        assert rc == 0 and first["sealed"] is True and await _count(sf, "selection_study_final") == 1
        rc, again = cli("final", "--out", str(d1), "--record")
        assert rc == 2 and "already sealed" in again["refused"] and await _count(sf, "selection_study_final") == 1
        rc, plain = cli("final", "--out", str(d2))
        assert rc == 0 and plain["sealed"] is True and (d2 / "final.json").read_text() == (d1 / "final.json").read_text()
        rc, v = cli("verify", "--out", str(d1))
        assert rc == 0 and v["matchesSeal"] is True and v["sealIntact"] is True and v["resultMatches"] is True
        # ---- later arrivals: rows after the endpoint, a late CONFLICTING duplicate close inside the window, and a BACKFILL of the gap
        j = Journal(sf, Bus())
        seal = json.loads((d1 / "final.json").read_text())
        endpoint_date = lc.et_date(seal["manifest"]["window"]["endpointMs"])
        later_day = next(d for d in days if d > endpoint_date)
        for row in rows_for(later_day, 5, -80.0, feats=_feats()):
            await j.append(ev.TECHNIQUE_PLAN_DIAGNOSTIC, {"runId": "late", **row}, aggregate_type="technique_run", aggregate_id="late")
        first_counted = seal["manifest"]["countedSessions"][0]
        dup = rows_for(dt.date.fromisoformat(first_counted), 0, -99.0, feats=_feats(flag="flag"))[1]
        await j.append(ev.TECHNIQUE_PLAN_DIAGNOSTIC, {"runId": "late", **dup}, aggregate_type="technique_run", aggregate_id="late")
        o = lc.session_bounds(GAP_DAY)[0]
        async with sf() as s:
            await s.execute(insert(BarRow), [{"symbol": "IWM", "tf": "1m", "ts": o + k * MIN, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1,
                                              "source": "exchange", "provider": "alpaca"} for k in (30, 31, 32)])
            await s.commit()
        rc, out = cli("final", "--out", str(d3))
        assert rc == 0 and out["sealed"] is True and (d3 / "final.json").read_text() == (d1 / "final.json").read_text()
        assert GAP_DAY.isoformat() in out["drift"]["sessionsReclassified"] and out["drift"]["manifestWouldChange"] is True
        rc, v = cli("verify", "--out", str(d1))
        assert rc == 0 and v["matchesSeal"] is True and v["sealIntact"] is True and v["drift"]["manifestWouldChange"] is True
        rc, _ = cli("final", "--out", str(d1))                        # identical content: nothing to overwrite
        assert rc == 0
        (tmp_path / "d4").mkdir()
        (tmp_path / "d4" / "final.json").write_text("{}")
        rc, out = cli("final", "--out", str(tmp_path / "d4"))
        assert rc == 2 and "not overwritten" in out["refused"] and (tmp_path / "d4" / "final.json").read_text() == "{}"
        assert await _count(sf, "selection_study_final") == 1
    finally:
        await eng.dispose()


# ------------------------------------------------------------------ journal-order precedence (pure)
def _journaled(rows):
    return [dict(r, _eventId=i + 1) for i, r in enumerate(rows)]


def _study():
    rows = []
    for i, d in enumerate(FULL[:60]):
        rows += opp(d, 0, 5.0, feats=_feats(flag=("flag" if i % 2 else "no_flag")))
    return rows


def _selected(inc, oid):
    return next(r for r in an.population(inc)["all"] if r["opportunityId"] == oid)


def test_the_first_journaled_close_wins_under_any_transport_order_and_price_never_decides():
    rows = _journaled(_study())
    first_close = rows[1]
    worse = copy.deepcopy(first_close)
    worse["observations"]["30"]["bid"] = 0.01
    better = copy.deepcopy(first_close)
    better["observations"]["30"]["bid"] = 5.0
    rows += [dict(worse, _eventId=10_001), dict(better, _eventId=10_002)]      # two LATER conflicting closes bound to the same opening
    now = close_of(FULL[59])
    base = lc.finalise(life(rows, now=now), rows)
    for seed in range(5):
        shuffled = list(rows)
        random.Random(seed).shuffle(shuffled)
        inc, man = lc.final_sample(life(shuffled, now=now), shuffled)
        sel = _selected(inc, first_close["opportunityId"])
        assert sel["selectedClose"] == first_close["_eventId"], "the FIRST journaled close is selected, whatever the transport order"
        assert ss.outcome(sel, 1.04)["primary"] == pytest.approx(5.0), "neither the worse nor the better later close replaces it"
        assert lc.sha(man) == base["manifestSha256"]
    assert next(x for x in base["manifest"]["selectedRecords"] if x["opportunityId"] == first_close["opportunityId"])["closeEventId"] == 2


def test_the_first_journaled_opening_owns_and_a_later_opening_cannot_take_over():
    rows = _journaled(_study())
    op1, cl1 = rows[2], rows[3]                                        # day 2's opening and close
    reopened = ss.open_record(date=op1["date"], symbol="SPY", setup_id=op1["setup"], signal_ts=op1["signalTs"], book=op1["book"],
                              trigger=op1["trigger"], direction="long", feats=_feats(flag="flag"),
                              selected={**op1["entryQuote"], "symbol": op1["entryQuote"]["contract"]}, shadow=False, refusal=None,
                              recorded_ts=op1["recordedTs"] + 99_000, followed_now=0)
    assert reopened["openHash"] != op1["openHash"] and reopened["opportunityId"] == op1["opportunityId"]
    o2 = dict(json.loads(json.dumps(reopened)), kind="selection_study_open", _eventId=20_001)
    for h in ss.HORIZONS_MIN:
        due = reopened["schedule"][0]["dueTs"] if h == 10 else reopened["schedule"][1]["dueTs"]
        ss.observe(reopened, h, due + 200, {"bid": 0.02, "ask": 0.04, "source": "opra", "quoteTs": due + 100})
    c2 = dict(json.loads(json.dumps(reopened)), kind="selection_study_close", _eventId=20_002)
    rows += [o2, c2]
    random.Random(3).shuffle(rows)
    lf = life(rows, now=close_of(FULL[59]))
    inc, man = lc.final_sample(lf, rows)
    sel = _selected(inc, op1["opportunityId"])
    assert sel["selectedOpening"] == op1["_eventId"] and sel["selectedClose"] == cl1["_eventId"] and sel["openings"] == 2
    assert sel["features"] == op1["features"] and not any(r.get("_eventId") == 20_002 for r in inc), "the later opening's close never enters"
    rec = next(x for x in man["selectedRecords"] if x["opportunityId"] == op1["opportunityId"])
    assert (rec["openingEventId"], rec["closeEventId"]) == (op1["_eventId"], cl1["_eventId"])
    assert lc.inside_diagnostics(lf, rows) == {"closesNotSelected": 1, "recoveredOpenings": 0, "opportunitiesWithRepeatedOpenings": 1}


# ------------------------------------------------------------------ the seal (pure)
def test_the_seal_is_the_first_recorded_final_and_later_data_only_shows_as_drift():
    rows = _journaled(_study())
    now = close_of(FULL[59])
    fin = lc.finalise(life(rows, now=now), rows)
    seal_row = dict(lc.seal_payload(fin), _eventId=30_000)
    later = rows + [seal_row] + [dict(r, _eventId=40_000 + i) for i, r in enumerate(opp(FULL[61], 0, -90.0))]
    dup = copy.deepcopy(rows[1])
    dup["observations"]["30"]["bid"] = 0.01
    later.append(dict(dup, _eventId=50_000))
    second = dict(lc.seal_payload(lc.finalise(life(later, now=close_of(FULL[62])), later)), _eventId=60_000)
    later.append(dict(second, manifestSha256="0" * 64))                        # a conflicting second "final"
    lf = life(later, now=close_of(FULL[62]), finals=later)
    assert lf["state"] == "finalized" and lf["finalRecorded"]["eventId"] == 30_000 and lf["finalRecorded"]["intact"] is True
    res = lc.resolve_final(lf, later, later)
    assert res["sealed"] and res["artifact"]["manifestSha256"] == fin["manifestSha256"] and res["artifact"]["resultSha256"] == fin["resultSha256"]
    assert res["drift"]["manifestWouldChange"] is False and res["drift"]["sessionsReclassified"] == [], \
        "a later duplicate close and rows after the endpoint change nothing: the first close still wins"
    # a later BACKFILL that reclassifies a session: reported as drift, never applied
    re_life = lc.lifecycle(activation_rows=[act(), *later], setting_events=[(lc._ms(dt.date(2026, 9, 18), 20, 0), "collect")], restart_ts=[lc._ms(FULL[4], 11, 0)],
                           outages={}, study_rows=later, final_rows=later, now_ms=close_of(FULL[62]))
    d = lc.resolve_final(re_life, later, later)
    assert d["artifact"]["manifestSha256"] == fin["manifestSha256"] and FULL[4].isoformat() in d["drift"]["sessionsReclassified"]
    tampered = [dict(r, report={**r["report"], "studyOutcome": "at least one pass"}) if r.get("_eventId") == 30_000 else r for r in later]
    assert lc.sealed_of(tampered)["intact"] is False


def test_status_tells_the_operator_to_switch_off_and_never_claims_to_do_it():
    rows = _study()
    on = lc.coverage_view(life(rows, now=close_of(FULL[59])), rows)
    off = lc.coverage_view(life(rows, now=close_of(FULL[59]) + 1, settings=[(lc._ms(dt.date(2026, 9, 18), 20, 0), "collect"),
                                                                             (close_of(FULL[59]), "off")]), rows)
    assert on["collectorEnabledNow"] is True and "switch techniques.team2.selection_study to off" in on["operatorAction"]
    assert off["collectorEnabledNow"] is False and off["operatorAction"] is None
