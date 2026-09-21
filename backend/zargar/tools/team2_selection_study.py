"""Team2 selection study S1 (registration `s1-r4`): the operator tool. Read-only except `activate` and `final --record`, which each
append ONE journal row, and only when confirmed.

    cd backend
    .venv/bin/python -m zargar.tools.team2_selection_study status                 # lifecycle + session accounting + COVERAGE ONLY
    .venv/bin/python -m zargar.tools.team2_selection_study registration           # the frozen registration and its hash
    .venv/bin/python -m zargar.tools.team2_selection_study activate --build <sha> --confirm <registrationHash>
    .venv/bin/python -m zargar.tools.team2_selection_study final --out <dir> [--record]   # refused before the endpoint
    .venv/bin/python -m zargar.tools.team2_selection_study verify --out <dir>     # recompute and compare with <dir>/final.json
    .venv/bin/python -m zargar.tools.team2_selection_study demo                   # the deterministic synthetic end-to-end example

`activate` does NOT switch the collector on: the operator then sets `techniques.team2.selection_study` to `collect` (journaled as a
SettingChanged row). Collection only counts from the first full session after BOTH.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import pathlib
import random
import time

from .. import events as ev
from ..techniques.team2 import selection_study as ss
from ..techniques.team2 import selection_study_analysis as an
from ..techniques.team2 import selection_study_lifecycle as lc

STUDY_RUN_ID = f"selection-study:{ss.STUDY}"


# ------------------------------------------------------------------ durable facts (read-only)
async def load_facts(sf, now_ms: int) -> dict:
    from sqlalchemy import and_, select
    from ..models import BarRow, Event, TechniqueArmed
    async with sf() as session:
        diag_rows = (await session.execute(select(Event).where(Event.type == ev.TECHNIQUE_PLAN_DIAGNOSTIC).order_by(Event.id))).scalars().all()
        rows = [{**dict(r.payload or {}), "_eventId": int(r.id)} for r in diag_rows      # the journal identity rides along
                if str((r.payload or {}).get("kind", "")).startswith("selection_study_")]
        settings = (await session.execute(select(Event).where(Event.type == "SettingChanged").order_by(Event.id))).scalars().all()
        setting_events = [(int(r.ts.timestamp() * 1000), (r.payload or {}).get("new")) for r in settings if (r.payload or {}).get("key") == lc.SETTING_KEY]
        team2_runs = select(TechniqueArmed.run_id).where(TechniqueArmed.technique == "team2")
        restored = (await session.execute(select(Event.ts).where(and_(Event.type == ev.TECHNIQUE_PLAN_RESTORED,
                                                                      Event.aggregate_id.in_(team2_runs))))).scalars().all()
        restart_ts = sorted({int(t.timestamp() * 1000) for t in restored})
        act = lc.activation_of(rows)
        outages: dict[str, str] = {}
        if act is not None:
            a_ms = int(act["activatedAt"])
            bars = (await session.execute(select(BarRow.symbol, BarRow.ts).where(and_(BarRow.symbol.in_(["SPY", "QQQ", "IWM"]), BarRow.tf == "1m",
                                                                                     BarRow.provider == "alpaca", BarRow.ts >= a_ms, BarRow.ts <= now_ms)))).all()
            by: dict[str, list[int]] = {}
            for sym, ts in bars:
                by.setdefault(sym, []).append(int(ts))
            days = [d for d in lc.trading_days(lc.et_date(a_ms), lc.et_date(now_ms)) if lc.session_bounds(d)[1] <= now_ms]
            outages = lc.outage_dates(by, days)
    return {"rows": rows, "settingEvents": setting_events, "restartTs": restart_ts, "outages": outages}


def life_of(facts: dict, now_ms: int) -> dict:
    return lc.lifecycle(activation_rows=facts["rows"], setting_events=facts["settingEvents"], restart_ts=facts["restartTs"],
                        outages=facts["outages"], study_rows=facts["rows"], final_rows=facts["rows"], now_ms=now_ms)


async def _append(sf, payload: dict) -> None:
    from ..bus import Bus
    from ..events import Journal
    await Journal(sf, Bus()).append(ev.TECHNIQUE_PLAN_DIAGNOSTIC, {"runId": STUDY_RUN_ID, "symbol": "SPY,QQQ,IWM", **payload},
                                    aggregate_type="technique_run", aggregate_id=STUDY_RUN_ID)


def activation_payload(build: str, now_ms: int) -> dict:
    first = next(d for d in lc.trading_days(lc.et_date(now_ms), lc.et_date(now_ms) + dt.timedelta(days=10)) if lc.session_bounds(d)[0] >= now_ms)
    return {"kind": "selection_study_activation", "study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH, "analysisSha256": ss.ANALYSIS_SHA256,
            "registration": ss.REGISTRATION, "build": build, "activatedAt": int(now_ms), "firstEligibleSession": first.isoformat(),
            "targetSessions": lc.TARGET_SESSIONS, "deadline": lc.DEADLINE.isoformat()}


# ------------------------------------------------------------------ the deterministic example (no database, no network)
def demo_facts(seed: int = 7) -> tuple[dict, int]:
    """Activation after the close of 2026-09-30; collector enabled at the same moment; one restart day, one outage day, one day
    switched off, the 2026-11-27 early close, several zero-opportunity sessions; four opportunities on other sessions, one of them
    examined by two books, some with a missing 30-minute quote."""
    rng = random.Random(seed)
    a_ms = lc._ms(dt.date(2026, 9, 30), 20, 0)
    rows = [activation_payload("demo-build", a_ms)]
    settings = [(a_ms, "collect")]
    restart, outages = [], {}
    days = lc.trading_days(dt.date(2026, 10, 1), dt.date(2026, 12, 31))
    for i, d in enumerate(days):
        if i == 5:
            restart.append(lc._ms(d, 11, 7))
        if i == 9:
            outages[d.isoformat()] = "feed outage: QQQ missing 4 consecutive regular-session minutes"
        if i == 12:
            settings += [(lc._ms(d, 8, 0), "off"), (lc._ms(d, 17, 0), "collect")]
        if i % 7 == 3:
            continue                                                        # a zero-opportunity session (it still counts)
        for j in range(4):
            T = lc._ms(d, 10, 0) + j * 26 * 60_000
            q0 = T + 1500
            feats = {k: {"value": v, "inputs": {}} for k, v in (
                ("flag", rng.choice(["flag", "no_flag", "no_flag"])), ("levelOrigin", rng.choice(["pm", "prior"])),
                ("wait", rng.choice(["short", "medium", "long"])), ("first15", "later"), ("scenario4", rng.choice(["scenario_4", "other"])),
                ("room", rng.choice(["near", "mid", "far"])))}
            sel = {"symbol": f"SPY{d:%y%m%d}C00700000", "ask": 0.60, "bid": 0.58, "quoteTs": q0, "collectedTs": q0 + 40, "source": "opra"}
            rec = ss.open_record(date=d.isoformat(), symbol="SPY", setup_id=f"scenario_1@{j}", signal_ts=T, book={"portfolioId": "p-control", "role": "control"},
                                 trigger=f"scenario_1@{j}#1", direction="long", feats=feats, selected=sel, shadow=False, refusal=None,
                                 recorded_ts=q0 + 50, followed_now=0)
            rows.append({"kind": "selection_study_open", **json.loads(json.dumps(rec))})
            if j == 0:                                                      # a second book examined the same opportunity
                dup = ss.open_record(date=d.isoformat(), symbol="SPY", setup_id=f"scenario_1@{j}", signal_ts=T, book={"portfolioId": "p-c1", "role": "c1"},
                                     trigger=f"scenario_1@{j}#3", direction="long", feats=feats, selected=sel, shadow=False, refusal=None,
                                     recorded_ts=q0 + 90, followed_now=1, duplicate_of={"runId": "r", "portfolioId": "p-control", "openHash": rec["openHash"]})
                rows.append({"kind": "selection_study_open", **json.loads(json.dumps(dup))})
            ret = rng.gauss(-2.0 + (12.0 if feats["flag"]["value"] == "flag" else 0.0), 30.0)
            f = 1.04 / 100
            bid = (ret / 100.0) * (0.60 + f) + 0.60 + 2 * f
            for h in ss.HORIZONS_MIN:
                due = q0 + h * 60_000
                q = {"bid": max(bid, 0.01), "ask": max(bid, 0.01) + 0.02, "source": "opra", "quoteTs": due + 300}
                if h == 30 and rng.random() < 0.08:
                    ss.observe(rec, h, due + ss.MAX_LATE_MS + 1, None, reason="no valid quote inside the window (last: no quote)")
                else:
                    ss.observe(rec, h, due + 500, q)
            rows.append({"kind": "selection_study_close", **json.loads(json.dumps(rec))})
    now_ms = lc._ms(dt.date(2027, 1, 4), 12, 0)
    return {"rows": rows, "settingEvents": settings, "restartTs": restart, "outages": outages}, now_ms


def demo() -> dict:
    facts, now_ms = demo_facts()
    life = life_of(facts, now_ms)
    fin = lc.finalise(life, facts["rows"])
    again = lc.finalise(life_of(facts, now_ms), list(facts["rows"]))
    return {"state": life["state"], "firstEligibleSession": life["firstEligibleSession"], "countedSessions": life["countedSessions"],
            "statusCounts": life["statusCounts"], "nonCounted": [s for s in life["sessions"] if s["status"] not in ("counted", "after_endpoint")],
            "endpoint": life["endpointReason"], "records": len(fin["manifest"]["selectedRecords"]), "rowsOutsideSample": fin["diagnostics"]["rowsOutsideSample"],
            "manifestSha256": fin["manifestSha256"], "resultSha256": fin["resultSha256"], "reproduced": again["resultSha256"] == fin["resultSha256"],
            "studyOutcome": fin["report"]["studyOutcome"], "featureCarriedForward": fin["report"]["featureCarriedForward"],
            "verdicts": {t["feature"]: t["verdict"] for t in fin["report"]["tests"]}}


# ------------------------------------------------------------------ CLI: ONE event loop owns the engine from creation to disposal
def _write_artifact(out: pathlib.Path, artifact: dict) -> str | None:
    """Write final.json; an existing file with DIFFERENT content is never overwritten (returns the refusal)."""
    out.mkdir(parents=True, exist_ok=True)
    body = json.dumps(artifact, indent=1, sort_keys=True)
    target = out / "final.json"
    if target.exists() and target.read_text() != body:
        return f"{target} exists with different content; not overwritten"
    target.write_text(body)
    return None


async def _amain(a) -> int:
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    eng = make_engine(get_config().database_url)
    try:
        sf = make_session_factory(eng)
        now_ms = int(time.time() * 1000)
        facts = await load_facts(sf, now_ms)
        life = life_of(facts, now_ms)
        if a.command == "status":
            print(json.dumps({"lifecycle": {k: v for k, v in life.items() if k != "sessions"}, **lc.coverage_view(life, facts["rows"])}, indent=1))
            return 0
        if a.command == "activate":
            if a.confirm != ss.REGISTRATION_HASH or not a.build:
                print(json.dumps({"refused": f"pass --build <reviewed build sha> and --confirm {ss.REGISTRATION_HASH}"}))
                return 2
            if lc.activation_of(facts["rows"]) is not None:
                print(json.dumps({"refused": "this registration is already activated", "activation": life["activation"]}))
                return 2
            payload = activation_payload(a.build, now_ms)
            await _append(sf, payload)
            print(json.dumps({"activated": {k: payload[k] for k in ("study", "registrationHash", "analysisSha256", "build", "activatedAt", "firstEligibleSession")},
                              "next": f"set {lc.SETTING_KEY} = collect (PATCH /api/settings); counting starts at the first full session after both"}, indent=1))
            return 0
        out = pathlib.Path(a.out or ".")
        if a.command == "final":
            sealed = lc.sealed_of(facts["rows"])
            if sealed is None and life["state"] != "ready_for_final_analysis":
                print(json.dumps({"refused": f"the study is {life['state']}; final analysis only after the endpoint",
                                  "countedSessions": life["countedSessions"], "endpoint": life["endpointReason"]}))
                return 2
            if sealed is not None:
                if a.record:
                    print(json.dumps({"refused": "already sealed: the first recorded final is authoritative and is never replaced",
                                      "manifestSha256": sealed["manifestSha256"], "resultSha256": sealed["resultSha256"]}))
                    return 2
                art = {k: sealed[k] for k in ("manifest", "manifestSha256", "report", "resultSha256")}
                why = _write_artifact(out, art)
                print(json.dumps({"sealed": True, "sealIntact": sealed["intact"], "manifestSha256": sealed["manifestSha256"],
                                  "resultSha256": sealed["resultSha256"], "written": None if why else str(out / "final.json"), "refused": why,
                                  "drift": lc.drift(sealed, life, facts["rows"])}, indent=1))
                return 2 if why else 0
            fin = lc.finalise(life, facts["rows"])
            art = {k: fin[k] for k in ("manifest", "manifestSha256", "report", "resultSha256")}
            why = _write_artifact(out, art)
            if why:
                print(json.dumps({"refused": why}))
                return 2
            if a.record:
                await _append(sf, lc.seal_payload(fin))
            print(json.dumps({"sealed": bool(a.record), "manifestSha256": fin["manifestSha256"], "resultSha256": fin["resultSha256"],
                              "written": str(out / "final.json"), "diagnostics": fin["diagnostics"]}, indent=1))
            return 0
        if a.command == "verify":
            target = out / "final.json"
            if not target.exists():
                print(json.dumps({"refused": f"{target} does not exist"}))
                return 2
            try:
                rec = json.loads(target.read_text())
            except json.JSONDecodeError as exc:
                print(json.dumps({"recordedIntact": False, "problems": [f"{target} is not valid JSON: {exc}"], "valid": False}))
                return 2
            res = lc.verify(rec, life, facts["rows"], facts["rows"])
            print(json.dumps(res, indent=1))
            # an edited or missing payload FAILS; later drift on a valid sealed artifact does not
            return 0 if res["valid"] else 2
        return 1
    finally:
        await eng.dispose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "registration", "activate", "final", "verify", "demo"])
    ap.add_argument("--out")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--build")
    ap.add_argument("--confirm")
    a = ap.parse_args(argv)
    if a.command == "registration":
        print(json.dumps({"study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH, "registration": ss.REGISTRATION}, indent=1))
        return 0
    if a.command == "demo":
        print(json.dumps(demo(), indent=1))
        return 0
    return asyncio.run(_amain(a))


if __name__ == "__main__":
    raise SystemExit(main())
