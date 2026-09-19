"""first-sale-v1 retrospective report (integrated plan D): what R each EM entry offered where it would FIRST be sold, at
the quantity actually sent - rebuilt from the immutable order-intent journal. READ-ONLY, zero model calls.

    python -m zargar.tools.em_first_sale report --dates 2026-09-15,2026-09-16,2026-09-17,2026-09-18 [--stdout]

Historical limits, stated per row: the underlying's live price at admission was never captured (`unknown`, never
inferred); the only CONTEMPORANEOUS contract evidence is the picked contract's own row in the intent (alternatives were
not stored before this build - from this build on the first-sale record carries the near-money rows of the chain already
in hand). `wouldRefuse` = what `enforce` would have done; nothing here changes a fill, a rule or a threshold.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os

from ..technique import first_sale as fs
from .em_profit_capture import EM_BOOK, _ms, execution_net

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "first-sale")
J = lambda v: (json.loads(v) if isinstance(v, str) else v) or {}   # noqa: E731


async def build(date: str) -> dict:
    import asyncpg
    from .. import config as _config
    d = dt.date.fromisoformat(date)
    c = await asyncpg.connect(_config.AppConfig().database_url.replace("postgresql+asyncpg://", "postgresql://"))
    await c.execute("set transaction read only")
    try:
        evs = await c.fetch("""select e.ts, e.aggregate_id rid, e.payload p, r.config cfg, r.result->'plan' plan from events e join technique_runs r on r.id = e.aggregate_id
            where e.type='TechniquePlanOrderIntent' and r.technique='enhanced_market' and e.portfolio_id=$1 and e.ts >= to_timestamp($2/1000.0) and e.ts < to_timestamp($3/1000.0) order by e.ts""",
                            EM_BOOK, _ms(d, 4, 0), _ms(d, 20, 0))
        ex = [dict(r) for r in await c.fetch("""select symbol, side, qty, price, commission from executions where portfolio_id=$1 and ts >= to_timestamp($2/1000.0)
            and ts < to_timestamp($3/1000.0)""", EM_BOOK, _ms(d, 4, 0), _ms(d, 20, 0))]
    finally:
        await c.close()
    net = execution_net(ex)
    rows = []
    for e in evs:
        p, cfg, plan = J(e["p"]), J(e["cfg"]), J(e["plan"])
        if str(p.get("side")) != "BUY":
            continue
        trig = next((t for t in plan.get("triggers") or [] if t.get("id") == p.get("trigger")), {})
        contract = p.get("contract") or None
        inst = "options" if p.get("secType") == "OPT" else "shares"
        th = (cfg.get("thresholds") or {})
        rec = fs.build_record(stage="retrospective", symbol=p.get("symbol"), run_id=e["rid"], trigger_id=p.get("trigger"), family=str(trig.get("kind") or ""),
                              direction=str(trig.get("direction") or ("short" if trig.get("kind") in ("reject", "breakdown") else "long")), session=date,
                              plan_entry=(trig.get("entry") or {}).get("price"), runner_entry=p.get("entry"), stop=p.get("stop"), targets=p.get("targets") or [],
                              underlier_evidence=None, instrument=inst, qty=p.get("qty"), multiplier=(100.0 if inst == "options" else 1.0), limit_price=p.get("limitPrice"),
                              single_exit="tp2", pinned_gate_target=str((cfg.get("settings") or {}).get("technique.rr_gate_target") or "auto"), pin_source=("run_config" if cfg else "unresolved"),
                              min_rr=float(th.get("min_risk_reward") or 3.0), contract=contract,
                              option_quote=({"bid": contract.get("bid"), "ask": contract.get("ask"), "source": contract.get("priced")} if contract else None),
                              fee_per_contract=1.04, stock_commission=0.0, affordable_qty=p.get("qty"),
                              plan_gate={"targetIndex": th.get("rr_gate_target"), "rr": trig.get("riskReward"), "rrTp3": trig.get("riskRewardTp3"), "min": th.get("min_risk_reward")},
                              mode="retrospective", now_ms=int(e["ts"].timestamp() * 1000))
        held = (contract or {}).get("symbol") or p.get("symbol")
        g = rec["gate"]
        raw, _prob = (fs.r_raw(direction=rec["direction"], entry=p.get("entry"), stop=p.get("stop"), target=rec["underlying"]["targets"][g["rungIndex"]])
                      if g["rungIndex"] is not None else (None, None))
        rows.append({"ts": e["ts"].isoformat(), "record": rec, "heldSymbol": held, "actualNet": (net["bySymbol"].get(held) or {}).get("net"),
                     "rRunnerEntryRaw": raw, "belowMinAtRunnerEntry": (raw is not None and raw < g["minRiskReward"]),
                     "v2Disposition": fs.decide(rec, "enforce")["disposition"]})
    return {"date": date, "rows": rows, "executionNet": net["net"], "asOf": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def render(days: list) -> str:
    L = ["# EM first-sale R at the final quantity - retrospective (`first-sale-v2`)", "",
         f"Generated {days[0]['asOf']} from the immutable order-intent journal; retrospective, read-only. **The validated executable underlying price at admission was never "
         "captured before this build**, so under `first-sale-v2` EVERY historical row is `unknown` for admission and `enforce` would have DEFERRED it - that column is the honest "
         "answer, not a back-test. `R at the runner's entry` is the geometry-only number (unrounded): the exact admission number only if the underlying had not moved. "
         "`Actual net` is the execution ledger's result for the held symbol.", "",
         "| Session | Time (UTC) | Symbol | Trigger | Vehicle | Qty | Gate target | First production sale | R at the runner's entry | Min | Plan-time R (rung) | Below min at the runner's entry | v2 admission (no evidence captured) | Actual net |",
         "|---|---|---|---|---|---:|---|---|---:|---:|---|---|---|---:|"]
    n = below = 0
    for d in days:
        for r in d["rows"]:
            g, v, f = r["record"]["gate"], r["record"]["vehicle"], r["record"]["firstSale"]
            pt = g.get("planTime") or {}
            n += 1
            below += 1 if r["belowMinAtRunnerEntry"] else 0
            raw = r["rRunnerEntryRaw"]
            raw_s = f"{raw:.4f}" if raw is not None else "unknown"
            L.append(f"| {d['date']} | {r['ts'][11:19]} | {r['record']['symbol']} | {r['record']['trigger']} | {v['instrument']} | {v['quantity']:g} | {g['rung']} | {f['rung']} | "
                     f"{raw_s} | {g['minRiskReward']:g} | {pt.get('rr')} (TP{(pt.get('targetIndex') or 0) + 1}) | "
                     f"{'yes' if r['belowMinAtRunnerEntry'] else 'no'} | {r['v2Disposition'].replace('_', ' ')} | {r['actualNet'] if r['actualNet'] is not None else 'no fill or open'} |")
    L += ["", f"Entries: {n}. Below the minimum on the runner's entry alone: {below}. Admission under v2 is unknown for all {n} (no validated underlying evidence exists for them); "
          "forward observation is the only way to learn how often the live executable bound changes the verdict.", "",
          "Four sessions of fixtures. This shows what the geometry said; it does not establish that enforcing the gate is profitable, and one avoided loser is not a reason to enforce. "
          "Observation first; enforcement is a separate decision.", "",
          "Reproduce: `python -m zargar.tools.em_first_sale report --dates " + ",".join(d["date"] for d in days) + "`."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("--dates", required=True); r.add_argument("--stdout", action="store_true")
    a = ap.parse_args(argv)
    dates = [x.strip() for x in a.dates.split(",") if x.strip()]
    days = [asyncio.run(build(d)) for d in dates]
    md = render(days)
    os.makedirs(OUT_DIR, exist_ok=True)
    name = f"{dates[0]}_{dates[-1]}" if len(dates) > 1 else dates[0]
    json.dump(days, open(os.path.join(OUT_DIR, f"{name}.json"), "w", encoding="utf-8"), indent=1, default=str)
    open(os.path.join(OUT_DIR, f"{name}.md"), "w", encoding="utf-8", newline="\n").write(md)
    print(md if a.stdout else f"wrote {OUT_DIR}/{name}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
