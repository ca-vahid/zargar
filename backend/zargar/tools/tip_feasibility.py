"""PROF-01 replay: re-judge recent TAKE cards at their CONTEMPORANEOUS stored
evidence and budget - feasible quantity or an honest no-trade - plus the
labelled shares alternative at equal risk where the tip carried a stop.

    python -m zargar.tools.tip_feasibility replay [--since 2026-09-14] [--json out.json]

Reads the proposals' persisted risk plan (unit loss, budget, quote/greek
provenance) and signal prices. It never fetches today's market, never places
anything and never changes a card. Chain alternatives need the chain at the
time, which the cards did not store - reported as unavailable, not invented.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json

from sqlalchemy import select

from ..config import AppConfig
from ..db import make_engine, make_session_factory
from ..models import Proposal
from ..techniques.tip import feasibility as fz


def _since(s: str) -> dt.datetime | None:
    if not s:
        return None
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


async def replay(sf, *, since: dt.datetime | None) -> list[dict]:
    async with sf() as session:
        q = select(Proposal).order_by(Proposal.created_at.desc())
        if since:
            q = q.where(Proposal.created_at >= since)
        rows = (await session.execute(q)).scalars().all()
    out = []
    for p in rows:
        ctx = p.context or {}
        if ctx.get("techniqueId") != "tip" or (ctx.get("analyst") or {}).get("verdict") != "take":
            continue
        rp = ctx.get("riskPlan") or {}
        prices = ctx.get("signalPrices") or {}
        sizing = ctx.get("sizing") or {}
        vehicle = ctx.get("vehicle") or {}
        budget = float(rp.get("budget") or 0)
        unit = rp.get("unitLoss")
        mult = float(rp.get("multiplier") or (100.0 if p.sec_type == "OPT" else 1.0))
        unit_cost = (float(p.limit_price) * mult) if p.limit_price else None
        f = fz.feasibility(budget=budget, unit_loss=unit, unit_cost=unit_cost, allocation_limit=sizing.get("budget"))
        direction = "short" if (p.sec_type == "OPT" and vehicle.get("optionType") == "put") else "long"
        entry = prices.get("entry") or (rp.get("entryRef") if rp.get("entryRef") else None)
        stop = rp.get("finalStop") or prices.get("stop")
        alt = fz.share_alternative(entry=entry, stop=stop, direction=direction, budget=budget,
                                   allocation_limit=sizing.get("budget")) if p.sec_type == "OPT" else None
        out.append({
            "proposalId": p.id, "createdAt": p.created_at.isoformat() if p.created_at else None,
            "symbol": p.symbol, "secType": p.sec_type, "display": vehicle.get("display") or p.symbol,
            "status": p.status, "requestedQty": p.qty, "limit": p.limit_price,
            "unitLoss": unit, "unitLossBasis": rp.get("unitLossBasis"), "budget": budget,
            "budgetSource": rp.get("budgetSource"), "quote": rp.get("quote"),
            "greeks": {k: v for k, v in (rp.get("greeks") or {}).items() if k != "text"},
            "reviewClass": rp.get("reviewClass"),
            "feasibility": f,
            "verdict": ("feasible" if f.get("feasible") else ("no-trade (honest): " + str(f.get("reason")))
                        if f.get("feasible") is not None else "no estimate (review)"),
            "sharesAlternative": alt,
            "chainAlternatives": "unavailable - the chain at the time was not stored; not invented",
        })
    return out


def _table(rows: list[dict]) -> str:
    lines = ["| card | when | unit risk | budget | fits | verdict | shares alt (qty @ risk) |", "|---|---|---:|---:|---:|---|---|"]
    for r in rows:
        f = r["feasibility"]
        alt = r.get("sharesAlternative")
        lines.append(f"| {r['display']} | {str(r['createdAt'])[:16]} | {r['unitLoss'] if r['unitLoss'] is not None else 'n/a'} | "
                     f"{r['budget']:.2f} | {f.get('qty') if f.get('qty') is not None else 'n/a'} | {r['verdict']} | "
                     f"{(str(alt['qty']) + ' @ $' + str(alt['plannedRisk'])) if alt else '-'} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["replay"])
    ap.add_argument("--since", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    cfg = AppConfig()
    db = make_engine(cfg.database_url)
    sf = make_session_factory(db)

    async def run():
        try:
            rows = await replay(sf, since=_since(a.since))
        finally:
            await db.dispose()
        print(_table(rows))
        print(f"\n{len(rows)} TAKE card(s); feasible {sum(1 for r in rows if r['feasibility'].get('feasible'))}, "
              f"no-trade {sum(1 for r in rows if r['feasibility'].get('feasible') is False)}, "
              f"no estimate {sum(1 for r in rows if r['feasibility'].get('feasible') is None)}")
        print("Contemporaneous stored evidence only; alternatives are labelled research comparisons, never substitutions.")
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, indent=2, default=str)
            print("written:", a.json)
    asyncio.run(run())


if __name__ == "__main__":
    main()
