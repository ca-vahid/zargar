"""E17-03 (2026-09-17): Tips OPERATING cost, reported apart from trading P&L.

Reads the usage every analyst-family run persisted (`tip_analyst_runs.opinion.usage`: in/out/
cacheRead/cacheWrite tokens, calls, unknownCalls, partial) plus the nightly `TechniqueHookStats.llm`
stage rollup, groups by day x kind x model, and prices it ONLY when `llm.rates` names the model.
No rate -> "UNPRICED": the report never infers a dollar bill. Cancelled / cut calls with unknown
billing are counted apart (`unknownCalls`, `partialRuns`) so a total is always labelled as a lower
bound when they exist. Read-only.

    python -m zargar.tools.tip_llm_cost --since 2026-09-17 [--until 2026-09-17] [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from zoneinfo import ZoneInfo

from sqlalchemy import select, text as sql_text

from ..config import AppConfig
from ..db import make_engine, make_session_factory
from ..models import TipAnalystRun

ET = ZoneInfo("America/New_York")


def price(tokens: dict, rate: dict | None) -> dict:
    """Pure: dollars for one bucket of tokens under one rate card ($ per million tokens).
    Returns {"usd": None, "priced": False} when the model has no rate - never a guess."""
    if not rate:
        return {"usd": None, "priced": False, "note": "unpriced: no rate for this model in llm.rates"}
    usd = 0.0
    for key, rk in (("in", "in"), ("out", "out"), ("cacheRead", "cacheRead"), ("cacheWrite", "cacheWrite")):
        n = float(tokens.get(key) or 0)
        r = rate.get(rk)
        if n and r is None:
            return {"usd": None, "priced": False, "note": f"unpriced: rate card lacks '{rk}'"}
        usd += n / 1_000_000.0 * float(r or 0)
    return {"usd": round(usd, 4), "priced": True}


def rollup(runs: list[dict], rates: dict) -> dict:
    """Pure: group per-run usage by day x kind x model; price when possible; label lower bounds."""
    groups: dict[tuple, dict] = {}
    for r in runs:
        u = r.get("usage") or {}
        key = (r["day"], r["kind"], r.get("model") or "unknown-model")
        g = groups.setdefault(key, {"day": key[0], "kind": key[1], "model": key[2], "runs": 0, "calls": 0,
                                    "in": 0, "out": 0, "cacheRead": 0, "cacheWrite": 0,
                                    "unknownCalls": 0, "partialRuns": 0, "runsWithoutUsage": 0, "failed": 0})
        g["runs"] += 1
        if r.get("status") == "failed":
            g["failed"] += 1
        if not u:
            g["runsWithoutUsage"] += 1
            continue
        for k in ("calls", "in", "out", "cacheRead", "cacheWrite", "unknownCalls"):
            g[k] += int(u.get(k) or 0)
        if u.get("partial"):
            g["partialRuns"] += 1
    out = []
    for g in groups.values():
        p = price(g, rates.get(g["model"]) if g["model"] else None)
        g.update(p)
        g["lowerBound"] = bool(g["unknownCalls"] or g["partialRuns"] or g["runsWithoutUsage"])
        out.append(g)
    out.sort(key=lambda x: (x["day"], x["kind"], x["model"]))
    total_priced = sum(x["usd"] for x in out if x.get("priced"))
    return {"groups": out, "totalPricedUsd": round(total_priced, 4),
            "unpricedGroups": sum(1 for x in out if not x.get("priced")),
            "lowerBound": any(x["lowerBound"] for x in out),
            "note": "operating cost of the Tips desk's model calls - reported APART from trading P&L; "
                    "unpriced groups have no rate in llm.rates; lowerBound = cut/cancelled calls or runs without usage exist"}


async def load_runs(sf, *, since: str, until: str) -> list[dict]:
    start = dt.datetime.combine(dt.date.fromisoformat(since), dt.time(0, 0), tzinfo=ET)
    end = dt.datetime.combine(dt.date.fromisoformat(until), dt.time(23, 59, 59), tzinfo=ET)
    async with sf() as session:
        rows = (await session.execute(select(TipAnalystRun).where(
            TipAnalystRun.created_at >= start, TipAnalystRun.created_at <= end))).scalars().all()
    out = []
    for r in rows:
        op = r.opinion or {}
        out.append({"id": r.id, "kind": r.kind or "appraise", "status": r.status,
                    "day": r.created_at.astimezone(ET).strftime("%Y-%m-%d") if r.created_at else since,
                    "model": op.get("model") or (op.get("usage") or {}).get("model"),
                    "usage": op.get("usage") or {}})
    return out


async def load_rates(sf) -> dict:
    async with sf() as session:
        row = (await session.execute(sql_text("select value from settings where key = 'llm.rates'"))).first()
    if not row:
        return {}
    v = row[0]
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return {}
    if isinstance(v, dict) and "v" in v and isinstance(v["v"], dict):
        v = v["v"]
    return v if isinstance(v, dict) else {}


async def load_stage_rollup(sf, *, since: str, until: str) -> list[dict]:
    """The nightly TechniqueHookStats.llm rows (per stage: requests, tokens, stops, models)."""
    async with sf() as session:
        rows = (await session.execute(sql_text(
            "select payload from events where type = 'TechniqueHookStats' and payload->>'technique' = 'tip' "
            "and payload ? 'llm' and payload->>'date' between :a and :b order by ts"), {"a": since, "b": until})).all()
    return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    until = a.until or a.since
    cfg = AppConfig()
    db = make_engine(cfg.database_url)
    sf = make_session_factory(db)

    async def run():
        try:
            runs = await load_runs(sf, since=a.since, until=until)
            rates = await load_rates(sf)
            stages = await load_stage_rollup(sf, since=a.since, until=until)
        finally:
            await db.dispose()
        rep = rollup(runs, rates)
        print(f"Tips model usage {a.since}..{until} - {len(runs)} run(s); rates for: {sorted(rates) or 'NONE (all unpriced)'}")
        print("| day | kind | model | runs | calls | in | out | cacheRead | cacheWrite | unknownCalls | partialRuns | noUsage | failed | USD |")
        print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for g in rep["groups"]:
            usd = f"{g['usd']:.2f}" if g.get("priced") else "unpriced"
            print(f"| {g['day']} | {g['kind']} | {g['model']} | {g['runs']} | {g['calls']} | {g['in']} | {g['out']} | {g['cacheRead']} | "
                  f"{g['cacheWrite']} | {g['unknownCalls']} | {g['partialRuns']} | {g['runsWithoutUsage']} | {g['failed']} | {usd} |")
        print(f"\npriced total USD {rep['totalPricedUsd']:.2f} ({rep['unpricedGroups']} unpriced group(s)); "
              f"lower bound: {rep['lowerBound']}. {rep['note']}")
        if stages:
            print(f"\nnightly stage rollups (TechniqueHookStats.llm): {len(stages)} row(s)")
            for p in stages:
                for stage, st in (p.get("llm") or {}).items():
                    print(f"  {p.get('date')} {stage}: requests={st.get('requests')} retries={st.get('retries')} in={st.get('inputTokens')} "
                          f"out={st.get('outputTokens')} models={st.get('models')} stops={st.get('stops')}")
        else:
            print("\nno nightly TechniqueHookStats.llm rollup in range yet (the tip_llm_stats job flushes at 17:40 ET)")
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump({"runs": runs, "rates": rates, "rollup": rep, "stages": stages}, fh, indent=1, default=str)
            print("written:", a.json)
    asyncio.run(run())


if __name__ == "__main__":
    main()
