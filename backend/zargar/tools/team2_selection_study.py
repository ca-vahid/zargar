"""Team2 selection study S1: READ-ONLY reader of the collector's journal rows.

    cd backend
    .venv/bin/python -m zargar.tools.team2_selection_study                  # COVERAGE ONLY: counts and coverage, never an outcome
    .venv/bin/python -m zargar.tools.team2_selection_study --final          # the frozen analysis; refused before the stop rule

The default view is the only one allowed while collection runs (the registration forbids an interim look at outcomes by
feature). `--final` runs `selection_study_analysis.analyse` once the stop rule is met: 60 collected sessions, or 2026-12-18.
Nothing is written anywhere; the runtime database is only read.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json

from ..techniques.team2 import selection_study as ss
from ..techniques.team2 import selection_study_analysis as an

STOP_SESSIONS = 60
STOP_DATE = dt.date(2026, 12, 18)


def may_finalise(sessions_collected: int, today: dt.date) -> tuple[bool, str]:
    if sessions_collected >= STOP_SESSIONS:
        return True, f"{sessions_collected} sessions collected (stop rule: {STOP_SESSIONS})"
    if today >= STOP_DATE:
        return True, f"deadline {STOP_DATE.isoformat()} reached with {sessions_collected} sessions"
    return False, (f"collection is still running: {sessions_collected} of {STOP_SESSIONS} sessions and the deadline is {STOP_DATE.isoformat()}; "
                   f"outcomes by feature are not shown before the stop rule")


def coverage_only(rows: list[dict], fee: float) -> dict:
    pop = an.population(rows)
    primary = pop["primary"]
    return {"study": ss.STUDY, "view": "coverage only (no outcome is shown)", "opportunities": len(pop["all"]), "primaryPopulation": len(primary),
            "c1Only": len(pop["c1Only"]), "sessions": sorted({r["date"] for r in primary}), "ignoredCloses": pop["ignoredCloses"],
            "otherRegistrations": pop["otherRegistrations"],
            "coverage": {f: {b: {k: v for k, v in t.items()} for b, t in ss.coverage(primary, f, fee).items()} for f in an.FEATURE_ORDER}}


async def _load() -> list[dict]:
    from sqlalchemy import select
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..models import Event
    eng = make_engine(get_config().database_url)
    sf = make_session_factory(eng)
    async with sf() as session:
        rows = (await session.execute(select(Event).where(Event.type == "TechniquePlanDiagnostic").order_by(Event.id))).scalars().all()
    await eng.dispose()
    return [dict(r.payload or {}) for r in rows if str((r.payload or {}).get("kind", "")).startswith("selection_study")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--exclude", default="", help="comma-separated session dates excluded under the frozen exclusion rules")
    ap.add_argument("--fee", type=float, default=1.04)
    a = ap.parse_args(argv)
    rows = asyncio.run(_load())
    if not a.final:
        print(json.dumps(coverage_only(rows, a.fee), indent=1))
        return 0
    sessions = len({r.get("date") for r in rows if r.get("kind") == "selection_study_open" and r.get("study") == ss.STUDY})
    ok, why = may_finalise(sessions, dt.date.today())
    if not ok:
        print(json.dumps({"refused": why}, indent=1))
        return 2
    print(json.dumps({"stopRule": why, **an.analyse(rows, a.fee, excluded_sessions={x for x in a.exclude.split(",") if x})}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
