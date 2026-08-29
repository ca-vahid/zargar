"""The practice-soak report (NEXT-GAPS R1) — is the multi-day machinery ready
for the real-money gate?

Reads the journal + rows (read-only, no running server needed) and scores the
soak checklist:

- multi-day ROLLS observed (`TechniquePlanRolled`), and whether any plan ever
  outlived its horizon (a roll past `expiresSession` would be a bug),
- adopt-on-fill HANDOFFS (`TipPositionAdopted`), including partials,
- CRITICAL alerts (`TechniquePlanError` level=critical) — each one must be
  explained before real money,
- learning volume: retros, unfilled retros, lane grades, rule audits,
- the calendar span of evidence.

    python -m zargar.tools.soak_report [--days 30] [--json]
    ZARGAR_REVIEW_DATABASE_URL=... overrides the DB.

Thresholds (the R1 bar): >= 14 days span, >= 10 clean rolls, >= 5 handoffs
(>= 1 partial), 0 unexplained criticals, >= 5 retros, >= 3 lane grades.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys

from sqlalchemy import func, select

from ..config import AppConfig
from ..engine import Engine
from ..models import Event, ManagedPositionRow, TipAnalystRun

BAR = {"spanDays": 14, "rolls": 10, "handoffs": 5, "partialHandoffs": 1,
       "criticals": 0, "retros": 5, "laneGrades": 3}


async def collect(eng, days: int) -> dict:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    async with eng.sf() as session:
        async def count(ev_type: str, **jsonw) -> int:
            q = select(func.count()).select_from(Event).where(
                Event.type == ev_type, Event.ts >= cutoff)
            return int((await session.execute(q)).scalar_one())

        rolls = (await session.execute(
            select(Event.payload).where(Event.type == "TechniquePlanRolled",
                                        Event.ts >= cutoff))).scalars().all()
        # a roll whose target is past its own expiresSession would be a bug
        bad_rolls = [p for p in rolls
                     if p.get("expiresSession") and p.get("to")
                     and str(p["to"]) > str(p["expiresSession"])]
        adopted = (await session.execute(
            select(Event.payload).where(Event.type == "TipPositionAdopted",
                                        Event.ts >= cutoff))).scalars().all()
        criticals = (await session.execute(
            select(Event.payload).where(Event.type == "TechniquePlanError",
                                        Event.ts >= cutoff))).scalars().all()
        criticals = [c for c in criticals if (c or {}).get("level") == "critical"]
        retros = int((await session.execute(
            select(func.count()).select_from(TipAnalystRun).where(
                TipAnalystRun.kind == "retro", TipAnalystRun.status == "done",
                TipAnalystRun.created_at >= cutoff))).scalar_one())
        audits = int((await session.execute(
            select(func.count()).select_from(TipAnalystRun).where(
                TipAnalystRun.kind == "rule_audit", TipAnalystRun.status == "done",
                TipAnalystRun.created_at >= cutoff))).scalar_one())
        lanes = await count("TipLaneGraded")
        first_ev = (await session.execute(
            select(func.min(Event.ts)).where(Event.type.in_(
                ("TechniquePlanRolled", "TipPositionAdopted"))))).scalar_one()
        open_pos = (await session.execute(
            select(func.count()).select_from(ManagedPositionRow).where(
                ManagedPositionRow.technique == "tip",
                ManagedPositionRow.status.in_(("open", "attention"))))).scalar_one()

    span = (dt.datetime.now(dt.timezone.utc) - first_ev).days if first_ev else 0
    partials = sum(1 for a in adopted if (a or {}).get("partial"))
    out = {
        "spanDays": span, "rolls": len(rolls), "badRolls": len(bad_rolls),
        "handoffs": len(adopted), "partialHandoffs": partials,
        "criticals": len(criticals),
        "criticalSamples": [str((c or {}).get("error"))[:120] for c in criticals[:5]],
        "retros": retros, "ruleAudits": audits, "laneGrades": lanes,
        "openTipPositions": int(open_pos),
    }
    checks = {
        "spanDays": out["spanDays"] >= BAR["spanDays"],
        "rolls": out["rolls"] >= BAR["rolls"] and out["badRolls"] == 0,
        "handoffs": out["handoffs"] >= BAR["handoffs"]
        and out["partialHandoffs"] >= BAR["partialHandoffs"],
        "criticals": out["criticals"] == BAR["criticals"],
        "retros": out["retros"] >= BAR["retros"],
        "laneGrades": out["laneGrades"] >= BAR["laneGrades"],
    }
    out["checks"] = checks
    out["ready"] = all(checks.values())
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cfg = AppConfig()
    if os.environ.get("ZARGAR_REVIEW_DATABASE_URL"):
        cfg = AppConfig(database_url=os.environ["ZARGAR_REVIEW_DATABASE_URL"])
    eng = Engine(cfg)
    try:
        from ..db import create_all
        await create_all(eng.db)
        out = await collect(eng, args.days)
        if args.json:
            print(json.dumps(out, indent=1))
        else:
            ok = {True: "PASS", False: "…"}
            c = out["checks"]
            print(f"Practice soak — last {args.days}d "
                  f"({'READY for the real-money gate' if out['ready'] else 'still soaking'})")
            print(f" {ok[c['spanDays']]:>4}  evidence span         {out['spanDays']}d (need {BAR['spanDays']})")
            print(f" {ok[c['rolls']]:>4}  multi-day rolls       {out['rolls']} clean"
                  + (f", {out['badRolls']} PAST-HORIZON (BUG!)" if out['badRolls'] else "")
                  + f" (need {BAR['rolls']})")
            print(f" {ok[c['handoffs']]:>4}  adopt-on-fill         {out['handoffs']} "
                  f"({out['partialHandoffs']} partial) (need {BAR['handoffs']}/{BAR['partialHandoffs']})")
            print(f" {ok[c['criticals']]:>4}  critical alerts       {out['criticals']}"
                  + ("" if not out["criticalSamples"] else " — " + "; ".join(out["criticalSamples"])))
            print(f" {ok[c['retros']]:>4}  retros                {out['retros']} (need {BAR['retros']})"
                  f" · rule audits {out['ruleAudits']}")
            print(f" {ok[c['laneGrades']]:>4}  lane grades           {out['laneGrades']} (need {BAR['laneGrades']})")
            print(f"       open tip positions    {out['openTipPositions']}")
            if out["ready"]:
                print("Next: the Alpaca-paper overnight pass, then docs/PRE-LIVE-PROFILE.md.")
        return 0
    finally:
        await eng.db.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
