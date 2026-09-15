"""PROF-02 report: closed Tips positions - the declared ladder in integer
units, the arithmetic scenarios of the plan they carried, and the realized
round trip reconciled from actual fills (excess exits reported separately).

    python -m zargar.tools.tip_payoff_report [--since 2026-09-08] [--json out.json]

Arithmetic and reconciliation only: no profit claim from target arithmetic,
no retrospective peaks. Read-only.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json

from sqlalchemy import select

from ..config import AppConfig
from ..db import make_engine, make_session_factory
from ..models import Execution, ManagedPositionRow
from ..techniques.tip import payoff as po


def _since(s: str) -> dt.datetime | None:
    if not s:
        return None
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def direction_of(cfg: dict) -> str:
    return str((cfg or {}).get("direction") or "long")


def analyse_row(row: ManagedPositionRow, execs: dict[str, list[dict]] | None = None) -> dict:
    """`execs`: order id -> executions from the venue ledger; when present they are the
    reconciliation truth (RKT: the venue stop's 148-share fill never reached the manager's record)."""
    cfg = row.config or {}
    st = row.state or {}
    policy = cfg.get("policy") or {}
    legs = row.legs or []
    leg = legs[0] if legs else {}
    mult = float(leg.get("multiplier") or 1.0)
    exits = [x for x in (st.get("exits") or []) if float(x.get("filledQty") or 0) > 0]
    entry_qty = sum(float(x.get("filledQty") or 0) for x in exits) + abs(float(leg.get("qty") or 0))
    entry_price = float(leg.get("avgFill") or cfg.get("entry") or 0)
    fills = [{"qty": x.get("filledQty"), "price": x.get("price"), "kind": x.get("kind")} for x in exits]
    source = "manager record"
    if execs:
        entry_oid = leg.get("entryOrderId")
        exit_oids = [x.get("orderId") for x in (st.get("exits") or []) if x.get("orderId")]
        vso = st.get("venueStopOrderId")
        if vso and vso not in exit_oids:
            exit_oids.append(vso)
        ent = execs.get(entry_oid) or []
        if ent:
            entry_qty = sum(float(e["qty"]) for e in ent)
            entry_price = sum(float(e["qty"]) * float(e["price"]) for e in ent) / entry_qty
        ex_fills = [e for oid in exit_oids for e in (execs.get(oid) or [])]
        # the ledger truth for this book+symbol: every opposite-side execution after
        # the entry (a venue stop whose id the manager lost, RKT 2026-09-15, is here)
        book_key = f"{row.portfolio_id}|{row.symbol}"
        entry_ts = min((e["ts"] for e in ent), default="")
        seen = {(e["orderId"], e["ts"]) for e in ex_fills}
        for e in (execs.get(book_key) or []):
            if e["orderId"] == entry_oid or e["ts"] <= entry_ts:
                continue
            if (direction_of(cfg) == "long" and e.get("side") == "SELL") or (direction_of(cfg) == "short" and e.get("side") == "BUY"):
                if (e["orderId"], e["ts"]) not in seen:
                    ex_fills.append({**e, "ledger": True})
        if ex_fills:
            kinds = {x.get("orderId"): x.get("kind") for x in (st.get("exits") or [])}
            kinds[vso] = "venue_stop"
            fills = [{"qty": e["qty"], "price": e["price"], "kind": kinds.get(e["orderId"]) or ("ledger exit" if e.get("ledger") else None)}
                     for e in sorted(ex_fills, key=lambda e: e["ts"])]
            source = "venue executions"
    direction = str(cfg.get("direction") or "long")
    ladder = (policy.get("ladder") or {})
    targets = [float(t) for t in (ladder.get("targets") or [])]
    fractions = [float(f) for f in (ladder.get("fractions") or [])]
    stop = ((policy.get("stop") or {}).get("price"))
    entry_ref = float(cfg.get("entry") or entry_price or 0)
    unit_loss = None
    if stop is not None and entry_ref:
        dist = (entry_ref - float(stop)) if direction != "short" else (float(stop) - entry_ref)
        if dist > 0:
            unit_loss = round(dist * mult, 4) if leg.get("secType") == "STK" else None
    gains = po.unit_gains(vehicle=("shares" if leg.get("secType") == "STK" else "option"), entry_ref=entry_ref,
                          targets=targets, direction=direction, delta=None, multiplier=mult)
    preview = po.payoff_preview(qty=int(entry_qty), fractions=fractions, gains=gains, unit_loss=unit_loss,
                                vehicle=("shares" if leg.get("secType") == "STK" else "option"))
    realized = po.realized_from_fills(entry_qty=entry_qty, entry_price=entry_price, fills=fills,
                                      multiplier=mult, direction=direction)
    realized["source"] = source
    return {"id": row.id, "symbol": row.symbol, "status": row.status, "secType": leg.get("secType"),
            "entryQty": entry_qty, "entryPrice": entry_price, "stop": stop, "targets": targets, "fractions": fractions,
            "ladder": preview["ladder"], "scenarios": preview.get("scenarios"), "oneLot": preview.get("oneLot"),
            "realized": realized, "closeReason": st.get("closeReason")}


async def report(sf, *, since: dt.datetime | None) -> list[dict]:
    async with sf() as session:
        q = select(ManagedPositionRow).where(ManagedPositionRow.technique == "tip",
                                             ManagedPositionRow.status == "closed").order_by(ManagedPositionRow.created_at.desc())
        if since:
            q = q.where(ManagedPositionRow.created_at >= since)
        rows = (await session.execute(q)).scalars().all()
        oids: set[str] = set()
        for r in rows:
            for leg in (r.legs or []):
                if leg.get("entryOrderId"):
                    oids.add(str(leg["entryOrderId"]))
            for x in ((r.state or {}).get("exits") or []):
                if x.get("orderId"):
                    oids.add(str(x["orderId"]))
            if (r.state or {}).get("venueStopOrderId"):
                oids.add(str(r.state["venueStopOrderId"]))
        execs: dict[str, list[dict]] = {}
        keys = {(r.portfolio_id, r.symbol) for r in rows}
        if oids or keys:
            from sqlalchemy import or_, and_
            cond = [Execution.order_id.in_(list(oids))] if oids else []
            cond += [and_(Execution.portfolio_id == pid_, Execution.symbol == sym_) for pid_, sym_ in keys]
            erows = (await session.execute(select(Execution).where(or_(*cond)))).scalars().all()
            for e in erows:
                rec = {"orderId": str(e.order_id), "qty": float(e.qty), "price": float(e.price), "side": str(e.side),
                       "ts": e.ts.isoformat() if e.ts else ""}
                execs.setdefault(str(e.order_id), []).append(rec)
                execs.setdefault(f"{e.portfolio_id}|{e.symbol}", []).append(rec)
    return [analyse_row(r, execs) for r in rows]


def _table(rows: list[dict]) -> str:
    lines = ["| position | qty | ladder units | executable | realized (fills) | excess units | tp1-then-stop (est.) | all targets (est.) |",
             "|---|---:|---|---|---:|---:|---:|---:|"]
    for r in rows:
        sc = r.get("scenarios") or {}
        lines.append(f"| {r['symbol']} {r['secType']} | {r['entryQty']:g} | {r['ladder']['units']} +{r['ladder']['runner']} | "
                     f"{'yes' if r['ladder']['executable'] else 'NO'} | {r['realized']['realized']} | {r['realized']['excessUnits']} | "
                     f"{(sc.get('tp1ThenStop') or {}).get('net', 'n/a')} | {(sc.get('allTargets') or {}).get('net', 'n/a')} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    cfg = AppConfig()
    db = make_engine(cfg.database_url)
    sf = make_session_factory(db)

    async def run():
        try:
            rows = await report(sf, since=_since(a.since))
        finally:
            await db.dispose()
        print(_table(rows))
        print(f"\n{len(rows)} closed Tips position(s). Estimates are arithmetic on the declared plan (shares only get a "
              "stop-distance unit loss here; options need the entry delta) - no claim that targets are reached.")
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, indent=2, default=str)
            print("written:", a.json)
    asyncio.run(run())


if __name__ == "__main__":
    main()
