"""EM Experimental - daily comparison of the two Practice books (em-experiment-v1). READ-ONLY; zero model calls.

    python -m zargar.tools.em_experiment_report report --date 2026-09-21 [--stdout]

Baseline (EM Practice) beside the experiment (EM Experimental), same session, same clock: net realized after fees, open
exposure, marked vs covered-executable P&L, drawdown, trades / refusals / misses, model cost estimate, source alignment and
data coverage. Questionable fills are listed apart and never netted away. The experiment is the INTEGRATED BUNDLE: a
difference between the books cannot by itself say which change caused it. Unknown stays unknown."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

import asyncpg

from ..technique import model_costs as mc
from ..technique.profit_capture import reduce_session
from .em_profit_capture import DISPUTED, execution_net

NY = ZoneInfo("America/New_York")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "experiment")


def _j(v):
    return v if isinstance(v, (dict, list)) or v is None else json.loads(v)


def _unwrap(v):
    v = _j(v)
    return v["v"] if isinstance(v, dict) and set(v) == {"v"} else v


async def _book(c, pid: str, date: str, a: dt.datetime, b: dt.datetime) -> dict:
    ex = [dict(r) for r in await c.fetch("""select e.id, e.order_id, e.symbol, e.side, e.qty, e.price, e.commission, e.ts, o.sec_type from executions e
                                            join orders o on o.id = e.order_id where e.portfolio_id=$1 and e.ts >= $2 and e.ts < $3 order by e.ts, e.id""", pid, a, b)]
    exe = execution_net(ex)
    pos = [dict(r) for r in await c.fetch("select symbol, sec_type, qty, avg_cost from positions where portfolio_id=$1 and qty <> 0", pid)]
    eq = [dict(r) for r in await c.fetch("select ts, equity from equity_points where portfolio_id=$1 and ts >= $2 and ts < $3 order by ts",
                                         pid, int(a.timestamp() * 1000), int(b.timestamp() * 1000))]
    dd = None
    if eq:
        peak, worst = eq[0]["equity"], 0.0
        for r in eq:
            peak = max(peak, r["equity"]); worst = min(worst, r["equity"] - peak)
        dd = {"maxDrawdown": round(worst, 2), "first": eq[0]["equity"], "last": eq[-1]["equity"], "markedChange": round(eq[-1]["equity"] - eq[0]["equity"], 2), "samples": len(eq)}
    snaps = []
    if await c.fetchval("select to_regclass('public.technique_book_snapshots') is not null"):
        snaps = [_j(r["payload"]) for r in await c.fetch("select payload from technique_book_snapshots where portfolio_id=$1 and session=$2 order by captured_at, seq", pid, date)]
    final = [{"id": r["id"], "orderId": r["order_id"], "symbol": r["symbol"], "secType": r["sec_type"], "side": r["side"], "qty": float(r["qty"]), "price": float(r["price"]),
              "commission": float(r["commission"] or 0.0), "tsMs": int(r["ts"].timestamp() * 1000)} for r in ex]
    cap = reduce_session(snaps, execution_net=(exe["net"] if exe["complete"] else None), execution_fees=(exe["fees"] if exe["complete"] else None), final_executions=final)
    armed = [dict(r) for r in await c.fetch("select a.run_id, a.symbol, a.status, r.trigger, r.tags, r.config->'promotion' promo from technique_armed a join technique_runs r on r.id=a.run_id "
                                            "where a.technique='enhanced_market' and a.portfolio_id=$1 and a.plan_for=$2", pid, date)]
    run_ids = [r["run_id"] for r in armed]
    ev = [dict(r) for r in await c.fetch("select type, payload from events where aggregate_id = any($1::text[]) and ts >= $2 and ts < $3 and type = any($4::text[])", run_ids, a, b,
                                         ["TechniquePlanTriggerFired", "TechniquePlanTriggerSkipped", "TechniquePlanPositionOpened", "TechniquePlanError", "TechniquePlanExit"])] if run_ids else []
    counts: dict = {}
    refusals: dict = {}
    exits: dict = {}
    for e in ev:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
        p = _j(e["payload"]) or {}
        if e["type"] == "TechniquePlanTriggerSkipped":
            k = str(p.get("stage") or p.get("reason") or "skipped")
            refusals[k] = refusals.get(k, 0) + 1
        if e["type"] == "TechniquePlanExit":
            exits[str(p.get("kind"))] = exits.get(str(p.get("kind")), 0) + 1
    promoted = [r for r in armed if _j(r["promo"])]
    return {"portfolioId": pid, "execution": exe, "openExposure": [{"symbol": p["symbol"], "qty": p["qty"], "avgCost": p["avg_cost"]} for p in pos], "equity": dd,
            "capture": {k: cap.get(k) for k in ("status", "snapshots", "coverage", "realizedNetFinal", "peakDisplayedNet", "peakExecutableNet", "givebackVsExecutablePeak", "reconciliation")},
            "plans": {"armed": len(armed), "byOrigin": _count(r["trigger"] for r in armed), "promoted": len(promoted),
                      "promotedByVariant": _count((_j(r["promo"]) or {}).get("variant") for r in promoted)},
            "activity": {"fired": counts.get("TechniquePlanTriggerFired", 0), "entriesFilled": counts.get("TechniquePlanPositionOpened", 0),
                         "refusedOrSkipped": counts.get("TechniquePlanTriggerSkipped", 0), "refusalsByStage": refusals, "misses": counts.get("TechniquePlanError", 0), "exitsByKind": exits},
            "questionableFills": DISPUTED.get(date, [])}


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


async def build(date: str) -> dict:
    from .em_prep_ablation import _db_url
    c = await asyncpg.connect(_db_url())
    await c.execute("set default_transaction_read_only = on")
    try:
        d = dt.date.fromisoformat(date)
        a = dt.datetime(d.year, d.month, d.day, 4, 0, tzinfo=NY); b = a + dt.timedelta(hours=16)
        xp = _unwrap(await c.fetchval("select value from settings where key='techniques.enhanced_market.experiment'")) or {}
        base = _unwrap(await c.fetchval("select value from settings where key='techniques.enhanced_market.default_portfolio'")) or ""
        rates = _unwrap(await c.fetchval("select value from settings where key='llm.rates'")) or {}
        out = {"date": date, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "experiment": xp, "books": {}}
        for name, pid in (("baseline", base), ("experiment", str(xp.get("portfolioId") or ""))):
            out["books"][name] = await _book(c, pid, date, a, b) if pid else None
        runs = await c.fetch("""select id, created_at, status, llm, usage, result, trigger from technique_runs where technique='enhanced_market'
                                and created_at >= $1 and created_at < $2 and result->'plan'->>'planFor' like $3""", a - dt.timedelta(hours=44), b, date + "%")
        rows = [{"id": r["id"], "created_at": r["created_at"].date().isoformat(), "status": r["status"], "llm": _j(r["llm"]) or {}, "usage": _j(r["usage"]) or {},
                 "result": _j(r["result"]) or {}} for r in runs if r["trigger"] != "experiment"]
        out["modelCost"] = {"baseline": mc.summarize(mc.requests_from_runs(rows), table=(rates if isinstance(rates, dict) else {})),
                            "experiment": {"modelCalls": 0, "note": "deterministic preparation and promotion: zero model calls by construction"}}
    finally:
        await c.close()
    return out


def render(d: dict) -> str:
    L = [f"# EM Experimental vs baseline - {d['date']}", "",
         f"Generated {d['generatedAt']} (read-only, zero model calls). Experiment `{(d['experiment'] or {}).get('version')}` on book `{(d['experiment'] or {}).get('portfolioId')}`; "
         "overrides: " + json.dumps((d["experiment"] or {}).get("overrides") or {}, sort_keys=True) + ".", "",
         "**The experiment is the integrated bundle.** A difference between the books cannot by itself identify which change caused it. Simulated money; unknown stays unknown.", "",
         "| Measure | Baseline (EM Practice) | Experiment (EM Experimental) |", "|---|---|---|"]
    b, x = d["books"].get("baseline") or {}, d["books"].get("experiment") or {}

    def g(book, *path, default="unknown"):
        v = book
        for k in path:
            v = (v or {}).get(k) if isinstance(v, dict) else None
        return default if v is None else v
    rows = (("Net realized after fees (flat symbols)", ("execution", "net")), ("Fees", ("execution", "fees")), ("Fills", ("execution", "fills")),
            ("Open at the cutoff", ("execution", "openAtCutoff")), ("Marked equity change (30 s samples)", ("equity", "markedChange")), ("Max drawdown (marked)", ("equity", "maxDrawdown")),
            ("Executable peak (covered, scorable only)", ("capture", "peakExecutableNet", "value")), ("Displayed (marked) peak", ("capture", "peakDisplayedNet", "value")),
            ("Giveback vs the executable peak", ("capture", "givebackVsExecutablePeak")), ("Capture coverage (scorable / snapshots)", ("capture", "coverage", "ratio")),
            ("Capture status", ("capture", "status")), ("Plans armed", ("plans", "armed")), ("Plans by origin", ("plans", "byOrigin")),
            ("Promoted source / requalified plans", ("plans", "promotedByVariant")), ("Triggers fired", ("activity", "fired")), ("Entries filled", ("activity", "entriesFilled")),
            ("Refused or skipped", ("activity", "refusalsByStage")), ("Misses (entry errors)", ("activity", "misses")), ("Exits by kind", ("activity", "exitsByKind")))
    for label, path in rows:
        L.append(f"| {label} | {g(b, *path)} | {g(x, *path)} |")
    mcb = (d.get("modelCost") or {}).get("baseline") or {}
    L += ["", f"Model cost of preparing the baseline: estimated {g(mcb, 'estimated', 'usd')} USD at the current price card (an estimate, not an invoice; never subtracted from trading results); "
              f"invoice-verified {g(mcb, 'invoiceVerified', 'usd')}; unknown requests {g(mcb, 'unknown', 'requests')}. Experiment: 0 model calls.", ""]
    q = (b.get("questionableFills") or []) + (x.get("questionableFills") or [])
    L += ["## Questionable fills (shown apart, never netted away)", ""] + ([f"- {i}" for i in q] or ["- none recorded for this session"])
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("--date", required=True); r.add_argument("--stdout", action="store_true")
    a = ap.parse_args()
    d = asyncio.run(build(a.date))
    md = render(d)
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(d, open(os.path.join(OUT_DIR, f"{a.date}.json"), "w", encoding="utf-8"), indent=1, default=str)
    open(os.path.join(OUT_DIR, f"{a.date}.md"), "w", encoding="utf-8", newline="\n").write(md)
    print(md if a.stdout else f"wrote {OUT_DIR}/{a.date}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
