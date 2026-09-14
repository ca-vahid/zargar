"""FIX-01 reconciliation: share-fallback trades that carried the option's x100 multiplier.

    python -m zargar.tools.em_reconcile_fallback                 # dry run: print + write the manifest JSON
    python -m zargar.tools.em_reconcile_fallback --apply MANIFEST  # apply exactly that manifest (idempotent,
                                                                   # conditional on the row still matching)

The 2026-09-14 review (EX-01) found HPQ run 4d46f318: buy 100 @ 34.77, sell 30 @ 34.803, sell 70 @ 34.6531 -
net -$7.193 - stored as -$719.30 because `Trade.multiplier` stayed 100 after the shares fallback, and the
plan's $397.19 daily-loss limit was reported crossed. The code fix (`planrunner._enter`) sets the final
instrument's multiplier; this tool repairs the persisted projection (`technique_armed.state.trades`) and
appends a `TechniqueTradeCorrected` event per trade - the original events are never edited.

Halt assessment: `haltOld` / `haltNew` say whether the plan's own daily-loss limit would have been crossed
by the stored vs corrected realized P&L. The apply step does NOT resume paused plans; that stays a human
decision (list them from the manifest).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time

from sqlalchemy import select

from ..config import AppConfig
from ..engine import Engine
from ..models import TechniqueArmed
from ..research import events_contract as ev

CORRECTION_KIND = "TechniqueTradeCorrected"


def _state_hash(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _recompute(trade: dict, mult: float) -> float:
    """Realized P&L from the trade's own exit records at `mult` (what on_order_update does live)."""
    avg = float(trade.get("avgFill") or 0)
    total = 0.0
    for e in trade.get("exits") or []:
        fq = float(e.get("filledQty") or 0)
        px = e.get("price")
        if fq > 0 and px is not None:
            total += (float(px) - avg) * fq * mult
    return round(total, 4)


async def build_manifest(eng: Engine) -> dict:
    items = []
    async with eng.sf() as session:
        rows = (await session.execute(select(TechniqueArmed).where(TechniqueArmed.technique == "enhanced_market"))).scalars().all()
        for row in rows:
            st = row.state or {}
            trades = st.get("trades") or {}
            it = trades.items() if isinstance(trades, dict) else ((t.get("triggerId"), t) for t in trades)
            for tid, t in it:
                if t.get("instrument") != "shares" or float(t.get("multiplier") or 1) == 1.0:
                    continue
                old_real = float(t.get("realizedPnl") or 0)
                new_real = _recompute(t, 1.0)
                limit = float((row.config or {}).get("dailyLossLimit") or 0)
                items.append({
                    "runId": row.run_id, "symbol": row.symbol, "planFor": str(row.plan_for), "trigger": tid,
                    "status": row.status, "expectedStateHash": _state_hash(st),
                    "entryOrderId": t.get("entryOrderId"), "exitOrderIds": [e.get("orderId") for e in t.get("exits") or []],
                    "old": {"multiplier": float(t.get("multiplier") or 1), "realizedPnl": old_real},
                    "new": {"multiplier": 1.0, "realizedPnl": new_real},
                    "fills": {"qty": t.get("filledQty"), "avgFill": t.get("avgFill"),
                              "exits": [{"kind": e.get("kind"), "qty": e.get("filledQty"), "price": e.get("price")} for e in t.get("exits") or []]},
                    "commissions": "not modelled in the sim book (0)",
                    "dailyLossLimit": limit,
                    "haltOld": bool(limit and -old_real >= limit), "haltNew": bool(limit and -new_real >= limit),
                    "reason": "FIX-01: shares fallback kept the option multiplier (x100) on a share trade",
                })
    return {"generatedAt": int(time.time() * 1000), "fix": "FIX-01", "items": items,
            "falseHalts": [i["runId"] for i in items if i["haltOld"] and not i["haltNew"]]}


async def apply(eng: Engine, manifest: dict) -> int:
    applied = 0
    async with eng.sf() as session:
        for it in manifest["items"]:
            row = await session.get(TechniqueArmed, it["runId"])
            if row is None:
                print(f"skip {it['runId'][:8]} {it['trigger']}: row gone"); continue
            st = dict(row.state or {})
            if _state_hash(st) != it["expectedStateHash"]:
                # already applied, or changed since the dry run: idempotent by construction
                trades = st.get("trades") or {}
                t = trades.get(it["trigger"]) if isinstance(trades, dict) else None
                if t and float(t.get("multiplier") or 1) == 1.0:
                    print(f"skip {it['runId'][:8]} {it['trigger']}: already corrected"); continue
                print(f"REFUSE {it['runId'][:8]} {it['trigger']}: state changed since the manifest (re-run the dry run)"); continue
            trades = st.get("trades") or {}
            t = trades[it["trigger"]] if isinstance(trades, dict) else next(x for x in trades if x.get("triggerId") == it["trigger"])
            t["multiplier"] = 1.0
            t["realizedPnl"] = it["new"]["realizedPnl"]
            t.setdefault("corrections", []).append({"fix": "FIX-01", "at": int(time.time() * 1000),
                                                    "old": it["old"], "new": it["new"]})
            row.state = st
            await session.commit()
            await eng.journal.append(CORRECTION_KIND, {
                "runId": it["runId"], "symbol": it["symbol"], "trigger": it["trigger"], "fix": "FIX-01",
                "old": it["old"], "new": it["new"], "haltOld": it["haltOld"], "haltNew": it["haltNew"],
                "reason": it["reason"], "manifestGeneratedAt": manifest["generatedAt"]},
                aggregate_type="technique_run", aggregate_id=it["runId"])
            applied += 1
            print(f"applied {it['runId'][:8]} {it['trigger']}: realized {it['old']['realizedPnl']} -> {it['new']['realizedPnl']}")
    return applied


async def run(args) -> int:
    eng = Engine(AppConfig())
    try:
        if args.apply:
            manifest = json.load(open(args.apply, encoding="utf-8"))
            n = await apply(eng, manifest)
            print(f"applied {n} correction(s); paused plans are NOT resumed by this tool: {manifest.get('falseHalts')}")
            return 0
        m = await build_manifest(eng)
        out = args.out or f"em-fix01-manifest-{time.strftime('%Y%m%d-%H%M%S')}.json"
        json.dump(m, open(out, "w", encoding="utf-8"), indent=2)
        print(json.dumps(m, indent=2)[:4000])
        print(f"\n{len(m['items'])} affected trade record(s); false halts: {m['falseHalts']}; manifest -> {out}")
        return 0
    finally:
        await eng.db.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="FIX-01 share-fallback multiplier reconciliation")
    p.add_argument("--apply", help="manifest JSON from a dry run to apply")
    p.add_argument("--out", help="where to write the dry-run manifest")
    return asyncio.run(run(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
