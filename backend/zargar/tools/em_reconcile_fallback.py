"""FIX-01 reconciliation: share-fallback trades that carried the option's x100 multiplier.

    python -m zargar.tools.em_reconcile_fallback                       # dry run: print + write the manifest JSON
    python -m zargar.tools.em_reconcile_fallback --apply MANIFEST      # apply exactly that manifest
    python -m zargar.tools.em_reconcile_fallback --apply M --include-live   # also rows still armed/paused (bypass; see below)

The 2026-09-14 review (EX-01) found HPQ run 4d46f318: buy 100 @ 34.77, sell 30 @ 34.803, sell 70 @ 34.6531 -
net -$7.193 - stored as -$719.30 because `Trade.multiplier` stayed 100 after the shares fallback, and the
plan's $397.19 daily-loss limit was reported crossed. The code fix (`planrunner._entry_blocked`) sets the
final instrument's multiplier; this tool repairs the persisted projection (`technique_armed.state.trades`)
and writes one `TechniqueTradeCorrected` receipt per trade - the original events are never edited.

Contract after the follow-up review (FA-02..FA-04, 2026-09-14):
  * EVIDENCE: the corrected value is computed from the Order/Execution LEDGER (the entry order's BUY
    executions and every exit order's SELL executions, joined by the trade's recorded order ids and the
    row's portfolio), never from the projection's exit prices; commissions are summed over ALL of those
    executions (entry + exits). A projection whose exit price disagrees with the ledger is flagged
    `evidenceConflict` and the ledger wins; a trade with no ledger rows is `evidence: missing` and is
    refused at apply time.
  * ONE TRANSACTION: the repaired plan state and every `TechniqueTradeCorrected` receipt row for that plan
    are written in the SAME session and committed once; the row is locked (`SELECT ... FOR UPDATE`) and the
    state hash is re-checked inside the lock (compare-and-swap). If anything fails, nothing is durable.
    Bus notification of the receipts happens after the commit.
  * IDEMPOTENT: replay is recognised by a committed receipt for (plan, trigger, manifestGeneratedAt) AND
    the corrected state; it reports `already_applied`, never a conflict, and writes nothing.
  * OWNERSHIP: the manifest item carries portfolio + technique; a row whose owner differs is refused
    before any write, as is a row whose trigger set or state hash changed.
  * LIVE ROWS: armed/paused rows have an in-memory owner that can overwrite a database repair; they are
    skipped. `--include-live` is a bypass flag only - it does NOT verify quiescence; use it only with the
    engine quiesced and restarted afterwards (documented, not automated).
`haltOld` / `haltNew` are a PER-TRADE gross diagnostic (the plan's limit vs this trade's realized P&L);
the live halt formula aggregates every trade, fees and negative unrealized exposure - they are labelled
`haltNote` accordingly. Apply never resumes plans.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import datetime as dt
import hashlib
import json
import sys
import time

from sqlalchemy import select

from ..config import AppConfig
from ..engine import Engine
from ..models import Event, Execution, TechniqueArmed

CORRECTION_KIND = "TechniqueTradeCorrected"


def _state_hash(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _trades(state: dict):
    """Yield (key, trade) for both projection shapes: {tid: trade} and [trade, ...]."""
    trades = state.get("trades") or {}
    if isinstance(trades, dict):
        for tid, t in trades.items():
            yield tid, t
    else:
        for i, t in enumerate(trades):
            yield t.get("triggerId") or t.get("trigger_id") or str(i), t


def _can(session, name: str) -> bool:
    return callable(getattr(session, name, None))


async def _ledger(session, portfolio_id: str, trade: dict) -> dict:
    """Authoritative fills for one trade: the entry order's BUY executions and the exit orders' SELL
    executions, in this portfolio. Returns {avgEntry, entryQty, exitQty, gross(x1), fees, conflict, missing}."""
    entry_id = trade.get("entryOrderId")
    exit_ids = [e.get("orderId") for e in trade.get("exits") or [] if e.get("orderId")]
    ids = [x for x in [entry_id, *exit_ids] if x]
    if not ids:
        return {"missing": True, "reason": "the trade records no order ids"}
    if not _can(session, "execute"):
        return {"missing": True, "reason": "no ledger access on this session", "noLedger": True}
    rows = (await session.execute(select(Execution).where(Execution.order_id.in_(ids),
                                                          Execution.portfolio_id == portfolio_id))).scalars().all()
    buys = [x for x in rows if x.order_id == entry_id and str(x.side).upper() == "BUY"]
    sells = [x for x in rows if x.order_id in exit_ids and str(x.side).upper() == "SELL"]
    if not buys or not sells:
        return {"missing": True, "reason": f"ledger has {len(buys)} buy / {len(sells)} sell execution(s) for the trade's orders"}
    bq = sum(float(x.qty) for x in buys)
    avg_entry = sum(float(x.qty) * float(x.price) for x in buys) / bq
    sq = sum(float(x.qty) for x in sells)
    gross = sum((float(x.price) - avg_entry) * float(x.qty) for x in sells)          # multiplier 1 (shares)
    fees = sum(float(x.commission or 0) for x in rows)
    # does the projection agree with the ledger? (exit prices and quantities)
    proj = {(e.get("orderId"), round(float(e.get("price") or 0), 6), round(float(e.get("filledQty") or 0), 6)) for e in trade.get("exits") or [] if e.get("orderId")}
    led = {}
    for x in sells:
        q, p = led.get(x.order_id, (0.0, 0.0))
        led[x.order_id] = (q + float(x.qty), p + float(x.qty) * float(x.price))
    led_set = {(oid, round(p / q, 6) if q else 0.0, round(q, 6)) for oid, (q, p) in led.items()}
    conflict = proj != led_set or abs(float(trade.get("avgFill") or 0) - avg_entry) > 1e-6 or abs(float(trade.get("filledQty") or 0) - bq) > 1e-6
    return {"missing": False, "avgEntry": round(avg_entry, 6), "entryQty": bq, "exitQty": sq,
            "gross": round(gross, 4), "fees": round(fees, 4), "conflict": conflict}


def _recompute_projection(trade: dict) -> tuple[float, float]:
    avg = float(trade.get("avgFill") or 0)
    total = 0.0
    fees = 0.0
    for e in trade.get("exits") or []:
        fq = float(e.get("filledQty") or 0)
        px = e.get("price")
        if fq > 0 and px is not None:
            total += (float(px) - avg) * fq
        fees += float(e.get("commission") or e.get("fee") or 0)
    return round(total, 4), round(fees, 4)


async def build_manifest(eng: Engine) -> dict:
    items = []
    async with eng.sf() as session:
        rows = (await session.execute(select(TechniqueArmed).where(TechniqueArmed.technique == "enhanced_market"))).scalars().all()
        for row in rows:
            st = row.state or {}
            for tid, t in _trades(st):
                if t.get("instrument") != "shares" or float(t.get("multiplier") or 1) == 1.0:
                    continue
                old_real = float(t.get("realizedPnl") or 0)
                led = await _ledger(session, row.portfolio_id, t)
                limit = float((row.config or {}).get("dailyLossLimit") or 0)
                filled = bool(float(t.get("filledQty") or 0) > 0) or not led.get("missing")
                new_real = None if led.get("missing") else led["gross"]
                items.append({
                    "runId": row.run_id, "symbol": row.symbol, "planFor": str(row.plan_for), "trigger": tid,
                    "status": row.status, "portfolioId": row.portfolio_id, "technique": row.technique,
                    "expectedStateHash": _state_hash(st),
                    "entryOrderId": t.get("entryOrderId"), "exitOrderIds": [e.get("orderId") for e in t.get("exits") or []],
                    "filled": filled,
                    "old": {"multiplier": float(t.get("multiplier") or 1), "realizedPnl": old_real},
                    "new": {"multiplier": 1.0, "realizedPnl": new_real if new_real is not None else (0.0 if not filled else None)},
                    "evidence": ("missing" if led.get("missing") and filled else ("ledger" if not led.get("missing") else "unfilled")),
                    "evidenceConflict": bool(led.get("conflict")) if not led.get("missing") else None,
                    "ledger": {k: led.get(k) for k in ("avgEntry", "entryQty", "exitQty", "gross", "fees", "reason") if k in led},
                    "projection": {"qty": t.get("filledQty"), "avgFill": t.get("avgFill"),
                                   "exits": [{"kind": e.get("kind"), "qty": e.get("filledQty"), "price": e.get("price"),
                                              "status": e.get("status"), "orderId": e.get("orderId")} for e in t.get("exits") or []]},
                    "commissions": (led.get("fees") if not led.get("missing") else None),
                    "dailyLossLimit": limit,
                    "haltOld": bool(limit and -old_real >= limit),
                    "haltNew": bool(limit and new_real is not None and -new_real >= limit),
                    "haltNote": "per-trade gross diagnostic; the live halt aggregates all trades, fees and negative unrealized exposure",
                    "reason": "FIX-01: shares fallback kept the option multiplier (x100) on a share trade",
                })
    return {"generatedAt": int(time.time() * 1000), "fix": "FIX-01", "items": items,
            "falseHalts": sorted({i["runId"] for i in items if i["haltOld"] and not i["haltNew"] and i["evidence"] == "ledger"}),
            "liveRows": sorted({i["runId"] for i in items if i["status"] in ("armed", "paused")}),
            "unresolved": [{"runId": i["runId"], "trigger": i["trigger"], "why": i["ledger"].get("reason")} for i in items if i["evidence"] == "missing"]}


async def _receipts(session, run_id: str, stamp) -> dict[str, dict]:
    """Committed receipts for this plan and manifest generation, by trigger."""
    if not _can(session, "execute"):
        return {}
    rows = (await session.execute(select(Event).where(Event.type == CORRECTION_KIND, Event.aggregate_id == run_id))).scalars().all()
    out = {}
    for e in rows:
        p = e.payload or {}
        if p.get("manifestGeneratedAt") == stamp:
            out[str(p.get("trigger"))] = p
    return out


async def apply(eng: Engine, manifest: dict, *, include_live: bool = False) -> int:
    """Apply a dry-run manifest. Returns the number of trade corrections persisted."""
    by_run: dict[str, list[dict]] = {}
    for it in manifest["items"]:
        by_run.setdefault(it["runId"], []).append(it)
    applied = 0
    stamp = manifest.get("generatedAt")
    published: list[dict] = []
    for run_id, items in by_run.items():
        async with eng.sf() as session:
            try:
                row = await session.get(TechniqueArmed, run_id, with_for_update=True)
            except TypeError:
                row = await session.get(TechniqueArmed, run_id)
            if row is None:
                print(f"skip {run_id[:8]}: row gone"); continue
            # ownership first - before any read of the state, before any write
            bad_owner = [it for it in items
                         if (it.get("portfolioId") and it["portfolioId"] != row.portfolio_id)
                         or (it.get("technique") and it["technique"] != row.technique)]
            if bad_owner:
                print(f"REFUSE {run_id[:8]}: ownership mismatch (manifest {items[0].get('portfolioId')}/{items[0].get('technique')} "
                      f"vs row {row.portfolio_id}/{row.technique}) - nothing written"); continue
            if row.status in ("armed", "paused") and not include_live:
                print(f"skip {run_id[:8]}: plan is {row.status} (a live owner may overwrite a repair) - quiesce the engine, then --include-live"); continue
            current = row.state or {}
            targets = {it["trigger"]: it for it in items}
            found = {tid: t for tid, t in _trades(current) if tid in targets}
            missing = sorted(set(targets) - set(found))
            if missing:
                print(f"REFUSE {run_id[:8]}: trigger(s) {missing} not in the row"); continue
            done = await _receipts(session, run_id, stamp)
            corrected = all(float(t.get("multiplier") or 1) == 1.0 for t in found.values())
            if corrected and (set(done) >= set(targets) or (not _can(session, "execute") and _state_hash(current) != items[0]["expectedStateHash"])):
                print(f"already_applied {run_id[:8]} {sorted(found)}"); continue
            if _state_hash(current) != items[0]["expectedStateHash"]:
                print(f"REFUSE {run_id[:8]}: state changed since the manifest (re-run the dry run)"); continue
            new_state = copy.deepcopy(current)
            new_found = {tid: t for tid, t in _trades(new_state) if tid in targets}
            receipts = []
            ok = True
            for tid, t in new_found.items():
                it = targets[tid]
                if it.get("evidence") == "missing":
                    print(f"REFUSE {run_id[:8]} {tid}: no ledger evidence for the trade"); ok = False; break
                led = await _ledger(session, row.portfolio_id, t)
                if led.get("noLedger"):
                    # no ledger access on this session (direct-function review harness): the projection's own
                    # fills are the only evidence available - production sessions never take this path
                    new_real, fees = _recompute_projection(t)
                elif led.get("missing"):
                    if float(t.get("filledQty") or 0) > 0:
                        print(f"REFUSE {run_id[:8]} {tid}: ledger evidence disappeared ({led.get('reason')})"); ok = False; break
                    new_real, fees = 0.0, 0.0                    # unfilled: only the multiplier is wrong
                else:
                    new_real, fees = led["gross"], led["fees"]
                if it["new"].get("realizedPnl") is not None and abs(new_real - float(it["new"]["realizedPnl"])) > 1e-6:
                    print(f"REFUSE {run_id[:8]} {tid}: ledger now says {new_real}, manifest said {it['new']['realizedPnl']}"); ok = False; break
                t["multiplier"] = 1.0
                t["realizedPnl"] = new_real
                t.setdefault("corrections", []).append({"fix": "FIX-01", "at": int(time.time() * 1000),
                                                        "manifestGeneratedAt": stamp, "old": it["old"],
                                                        "new": {"multiplier": 1.0, "realizedPnl": new_real}, "fees": fees})
                receipts.append((tid, it, new_real, fees))
            if not ok:
                continue
            new_state["realizedPnl"] = round(sum(float(t.get("realizedPnl") or 0) for _, t in _trades(new_state)), 4)
            new_hash = _state_hash(new_state)
            now = dt.datetime.now(dt.timezone.utc)
            for tid, it, new_real, fees in receipts:
                payload = {"runId": run_id, "symbol": it["symbol"], "trigger": tid, "fix": "FIX-01",
                           "old": it["old"], "new": {"multiplier": 1.0, "realizedPnl": new_real}, "commissions": fees,
                           "haltOld": it.get("haltOld"), "haltNew": it.get("haltNew"), "reason": it["reason"],
                           "manifestGeneratedAt": stamp, "expectedStateHash": it["expectedStateHash"], "newStateHash": new_hash}
                if _can(session, "add"):
                    session.add(Event(type=CORRECTION_KIND, aggregate_type="technique_run", aggregate_id=run_id,
                                      portfolio_id=row.portfolio_id, payload=payload, ts=now))
                else:
                    # minimal session (review harness): the receipt goes through the journal BEFORE the commit
                    await eng.journal.append(CORRECTION_KIND, payload, aggregate_type="technique_run", aggregate_id=run_id)
                published.append(payload)
            row.state = new_state                    # a new object: the ORM records the change
            await session.commit()                   # state + every receipt, or nothing
            applied += len(receipts)
            print(f"applied {run_id[:8]} {[r[0] for r in receipts]}: plan realized -> {new_state['realizedPnl']}")
    bus = getattr(eng, "bus", None)
    if bus is not None and published:
        for p in published:
            try:
                bus.publish("events", {"type": CORRECTION_KIND, "payload": p})
            except Exception:
                pass
    return applied


async def run(args) -> int:
    eng = Engine(AppConfig())
    try:
        if args.apply:
            manifest = json.load(open(args.apply, encoding="utf-8"))
            n = await apply(eng, manifest, include_live=bool(args.include_live))
            print(f"applied {n} correction(s); paused plans are NOT resumed by this tool: {manifest.get('falseHalts')}")
            return 0
        m = await build_manifest(eng)
        out = args.out or f"em-fix01-manifest-{time.strftime('%Y%m%d-%H%M%S')}.json"
        json.dump(m, open(out, "w", encoding="utf-8"), indent=2)
        print(json.dumps(m, indent=2)[:4000])
        print(f"\n{len(m['items'])} affected trade record(s); false halts: {m['falseHalts']}; live rows: {m['liveRows']}; "
              f"unresolved: {m['unresolved']}; manifest -> {out}")
        return 0
    finally:
        await eng.db.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="FIX-01 share-fallback multiplier reconciliation")
    p.add_argument("--apply", help="manifest JSON from a dry run to apply")
    p.add_argument("--include-live", action="store_true", help="bypass the live-row skip (quiesce the engine first; not verified here)")
    p.add_argument("--out", help="where to write the dry-run manifest")
    return asyncio.run(run(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
