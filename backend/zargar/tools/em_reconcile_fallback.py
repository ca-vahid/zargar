"""FIX-01 reconciliation: share-fallback trades that carried the option's x100 multiplier.

    python -m zargar.tools.em_reconcile_fallback                       # dry run: print + write the manifest JSON
    python -m zargar.tools.em_reconcile_fallback --apply MANIFEST      # apply exactly that manifest
    python -m zargar.tools.em_reconcile_fallback --apply M --include-live   # also rows still armed/paused (see below)

The 2026-09-14 review (EX-01) found HPQ run 4d46f318: buy 100 @ 34.77, sell 30 @ 34.803, sell 70 @ 34.6531 -
net -$7.193 - stored as -$719.30 because `Trade.multiplier` stayed 100 after the shares fallback, and the
plan's $397.19 daily-loss limit was reported crossed. The code fix (`planrunner._entry_blocked`) sets the
final instrument's multiplier; this tool repairs the persisted projection (`technique_armed.state.trades`)
and appends one `TechniqueTradeCorrected` receipt per trade - the original events are never edited.

Re-review corrections (DA-03/DA-04, 2026-09-14):
  * the manifest is grouped BY PLAN and every reviewed trade of a plan is applied as ONE row transition,
    conditional on the plan's state hash from the dry run;
  * the new state is an independent deep copy assigned to the mapped attribute (the ORM sees the change);
  * the corrected value is recomputed here from the trade's fill records and must match the manifest;
  * the receipt is journaled BEFORE the row is committed - if the audit write fails nothing is committed;
    the receipt carries the manifest's generation stamp so an exact replay is recognised as already applied;
  * both list- and dict-shaped trade projections are supported; a replay reports `already_applied`;
  * the plan aggregate `state.realizedPnl` is recomputed from the corrected trades;
  * rows that are still armed/paused have a live in-memory owner that can overwrite a database repair:
    they are skipped unless `--include-live` is given AND the engine's restart-check says no owner is
    managing them (quiesce first); commissions are read from the trade's exit records when present.
Halt assessment: `haltOld` / `haltNew` apply the plan's own daily-loss limit to the stored vs corrected
realized P&L of the trade (gross of unrealized exposure - stated, not hidden). Apply never resumes plans.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import sys
import time

from sqlalchemy import select

from ..config import AppConfig
from ..engine import Engine
from ..models import TechniqueArmed

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


def _recompute(trade: dict, mult: float) -> tuple[float, float]:
    """Realized P&L from the trade's own exit records at `mult` (what on_order_update does live), and the
    commissions those records carry (0 when the sim book records none)."""
    avg = float(trade.get("avgFill") or 0)
    total = 0.0
    fees = 0.0
    for e in trade.get("exits") or []:
        fq = float(e.get("filledQty") or 0)
        px = e.get("price")
        if fq > 0 and px is not None:
            total += (float(px) - avg) * fq * mult
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
                new_real, fees = _recompute(t, 1.0)
                limit = float((row.config or {}).get("dailyLossLimit") or 0)
                items.append({
                    "runId": row.run_id, "symbol": row.symbol, "planFor": str(row.plan_for), "trigger": tid,
                    "status": row.status, "portfolioId": row.portfolio_id, "technique": row.technique,
                    "expectedStateHash": _state_hash(st),
                    "entryOrderId": t.get("entryOrderId"), "exitOrderIds": [e.get("orderId") for e in t.get("exits") or []],
                    "filled": bool(float(t.get("filledQty") or 0) > 0),
                    "old": {"multiplier": float(t.get("multiplier") or 1), "realizedPnl": old_real},
                    "new": {"multiplier": 1.0, "realizedPnl": new_real},
                    "fills": {"qty": t.get("filledQty"), "avgFill": t.get("avgFill"),
                              "exits": [{"kind": e.get("kind"), "qty": e.get("filledQty"), "price": e.get("price"),
                                         "status": e.get("status")} for e in t.get("exits") or []]},
                    "commissions": fees,
                    "dailyLossLimit": limit,
                    "haltOld": bool(limit and -old_real >= limit), "haltNew": bool(limit and -new_real >= limit),
                    "reason": "FIX-01: shares fallback kept the option multiplier (x100) on a share trade",
                })
    return {"generatedAt": int(time.time() * 1000), "fix": "FIX-01", "items": items,
            "falseHalts": sorted({i["runId"] for i in items if i["haltOld"] and not i["haltNew"]}),
            "liveRows": sorted({i["runId"] for i in items if i["status"] in ("armed", "paused")})}


async def apply(eng: Engine, manifest: dict, *, include_live: bool = False) -> int:
    """Apply a dry-run manifest. Returns the number of trade corrections persisted."""
    by_run: dict[str, list[dict]] = {}
    for it in manifest["items"]:
        by_run.setdefault(it["runId"], []).append(it)
    applied = 0
    stamp = manifest.get("generatedAt")
    async with eng.sf() as session:
        for run_id, items in by_run.items():
            row = await session.get(TechniqueArmed, run_id)
            if row is None:
                print(f"skip {run_id[:8]}: row gone"); continue
            for it in items:
                if it.get("portfolioId") and it["portfolioId"] != getattr(row, "portfolio_id", it["portfolioId"]):
                    print(f"REFUSE {run_id[:8]}: portfolio mismatch"); break
                if it.get("technique") and it["technique"] != getattr(row, "technique", it["technique"]):
                    print(f"REFUSE {run_id[:8]}: technique mismatch"); break
            else:
                pass
            if any(it.get("portfolioId") and it["portfolioId"] != getattr(row, "portfolio_id", it["portfolioId"]) for it in items):
                continue
            if getattr(row, "status", "") in ("armed", "paused") and not include_live:
                print(f"skip {run_id[:8]}: plan is {row.status} (a live owner may overwrite a repair) - re-run with --include-live after quiescing")
                continue
            current = row.state or {}
            new_state = copy.deepcopy(current)            # DA-03: an independent object, assigned below
            targets = {it["trigger"]: it for it in items}
            found = {}
            for tid, t in _trades(new_state):
                if tid in targets:
                    found[tid] = t
            missing = sorted(set(targets) - set(found))
            if missing:
                print(f"REFUSE {run_id[:8]}: trigger(s) {missing} not in the row"); continue
            if all(float(t.get("multiplier") or 1) == 1.0 for t in found.values()) and _state_hash(current) != items[0]["expectedStateHash"]:
                print(f"already_applied {run_id[:8]} {sorted(found)}"); continue
            if _state_hash(current) != items[0]["expectedStateHash"]:
                print(f"REFUSE {run_id[:8]}: state changed since the manifest (re-run the dry run)"); continue
            receipts = []
            for tid, t in found.items():
                it = targets[tid]
                new_real, fees = _recompute(t, 1.0)
                if abs(new_real - float(it["new"]["realizedPnl"])) > 1e-6:
                    print(f"REFUSE {run_id[:8]} {tid}: recomputed {new_real} != manifest {it['new']['realizedPnl']}"); receipts = None; break
                t["multiplier"] = 1.0
                t["realizedPnl"] = new_real
                t.setdefault("corrections", []).append({"fix": "FIX-01", "at": int(time.time() * 1000),
                                                        "manifestGeneratedAt": stamp, "old": it["old"], "new": it["new"]})
                receipts.append((tid, it, new_real, fees))
            if receipts is None:
                continue
            new_state["realizedPnl"] = round(sum(float(t.get("realizedPnl") or 0) for _, t in _trades(new_state)), 4)
            # DA-03: the durable receipt goes FIRST; if the audit write fails nothing is committed
            for tid, it, new_real, fees in receipts:
                await eng.journal.append(CORRECTION_KIND, {
                    "runId": run_id, "symbol": it["symbol"], "trigger": tid, "fix": "FIX-01",
                    "old": it["old"], "new": {"multiplier": 1.0, "realizedPnl": new_real}, "commissions": fees,
                    "haltOld": it["haltOld"], "haltNew": it["haltNew"], "reason": it["reason"],
                    "manifestGeneratedAt": stamp, "expectedStateHash": it["expectedStateHash"],
                    "newStateHash": _state_hash(new_state)},
                    aggregate_type="technique_run", aggregate_id=run_id)
            row.state = new_state
            await session.commit()
            applied += len(receipts)
            print(f"applied {run_id[:8]} {[r[0] for r in receipts]}: plan realized -> {new_state['realizedPnl']}")
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
        print(f"\n{len(m['items'])} affected trade record(s); false halts: {m['falseHalts']}; live rows: {m['liveRows']}; manifest -> {out}")
        return 0
    finally:
        await eng.db.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="FIX-01 share-fallback multiplier reconciliation")
    p.add_argument("--apply", help="manifest JSON from a dry run to apply")
    p.add_argument("--include-live", action="store_true", help="also correct rows that are still armed/paused (quiesce the engine first)")
    p.add_argument("--out", help="where to write the dry-run manifest")
    return asyncio.run(run(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
