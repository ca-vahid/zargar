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
    ev = [dict(r) for r in await c.fetch("select type, payload, aggregate_id from events where aggregate_id = any($1::text[]) and ts >= $2 and ts < $3 and type = any($4::text[])", run_ids, a, b,
                                         ["TechniquePlanTriggerFired", "TechniquePlanTriggerSkipped", "TechniquePlanPositionOpened", "TechniquePlanError", "TechniquePlanExit"])] if run_ids else []
    counts: dict = {}
    refusals: dict = {}
    exits: dict = {}
    missing: dict = {}
    for e in ev:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
        p = _j(e["payload"]) or {}
        if e["type"] == "TechniquePlanTriggerSkipped":
            k = str(p.get("stage") or p.get("reason") or "skipped")
            refusals[k] = refusals.get(k, 0) + 1
            disp = str(((p.get("detail") or {}) if isinstance(p.get("detail"), dict) else {}).get("disposition") or "")
            if disp.startswith("deferred") or disp == "policy_error":        # a refusal for MISSING or unreadable evidence, not for the rule
                missing[disp] = missing.get(disp, 0) + 1
        if e["type"] == "TechniquePlanExit":
            exits[str(p.get("kind"))] = exits.get(str(p.get("kind")), 0) + 1
    promoted = [r for r in armed if _j(r["promo"])]
    # per UNDERLYING: what this book armed, entered, exited and refused - the cohort split is built from these
    per_symbol: dict = {}
    for r in armed:
        per_symbol.setdefault(str(r["symbol"]), {"armed": 0, "fired": 0, "filled": 0, "refused": 0, "missingData": 0, "exits": {}, "net": 0.0, "fees": 0.0, "fills": 0})["armed"] += 1
    by_run = {r["run_id"]: str(r["symbol"]) for r in armed}
    for e in ev:
        sym = by_run.get(e.get("aggregate_id") or "")
        if not sym or sym not in per_symbol:
            continue
        p = _j(e["payload"]) or {}
        cell = per_symbol[sym]
        if e["type"] == "TechniquePlanTriggerFired":
            cell["fired"] += 1
        elif e["type"] == "TechniquePlanPositionOpened":
            cell["filled"] += 1
        elif e["type"] == "TechniquePlanTriggerSkipped":
            cell["refused"] += 1
            disp = str(((p.get("detail") or {}) if isinstance(p.get("detail"), dict) else {}).get("disposition") or "")
            if disp.startswith("deferred") or disp == "policy_error":
                cell["missingData"] += 1
        elif e["type"] == "TechniquePlanExit":
            cell["exits"][str(p.get("kind"))] = cell["exits"].get(str(p.get("kind")), 0) + 1
    for sym, row in (exe.get("bySymbol") or {}).items():                  # realized money, mapped from the traded symbol to its UNDERLYING
        under = _underlying(sym)
        cell = per_symbol.setdefault(under, {"armed": 0, "fired": 0, "filled": 0, "refused": 0, "missingData": 0, "exits": {}, "net": 0.0, "fees": 0.0, "fills": 0})
        cell["net"] = round(cell["net"] + float(row.get("net") or 0), 4)
        cell["fees"] = round(cell["fees"] + float(row.get("fees") or 0), 4)
        cell["fills"] += 1
    return {"portfolioId": pid, "execution": exe, "openExposure": [{"symbol": p["symbol"], "qty": p["qty"], "avgCost": p["avg_cost"]} for p in pos], "equity": dd,
            "capture": {k: cap.get(k) for k in ("status", "snapshots", "coverage", "realizedNetFinal", "peakDisplayedNet", "peakExecutableNet", "givebackVsExecutablePeak", "reconciliation")},
            "plans": {"armed": len(armed), "byOrigin": _count(r["trigger"] for r in armed), "promoted": len(promoted),
                      "promotedByVariant": _count((_j(r["promo"]) or {}).get("variant") for r in promoted)},
            "activity": {"fired": counts.get("TechniquePlanTriggerFired", 0), "entriesFilled": counts.get("TechniquePlanPositionOpened", 0),
                         "refusedOrSkipped": counts.get("TechniquePlanTriggerSkipped", 0), "refusalsByStage": refusals, "missingDataRefusals": missing, "misses": counts.get("TechniquePlanError", 0), "exitsByKind": exits},
            "questionableFills": DISPUTED.get(date, []), "perSymbol": per_symbol}


def _underlying(symbol: str) -> str:
    from ..options.occ import parse
    o = parse(symbol)
    return (o.underlying if o else str(symbol)).upper()


def cohorts(books: dict) -> dict:
    """Split the session by symbol class: symbols BOTH books armed, and each book's own. A difference inside the common
    cohort is the closest thing to a like-for-like comparison; the other two cohorts are trades one book never had."""
    b, x = (books.get("baseline") or {}).get("perSymbol") or {}, (books.get("experiment") or {}).get("perSymbol") or {}
    both = sorted(set(b) & set(x))
    out = {}
    for name, syms, side in (("common", both, None), ("baselineOnly", sorted(set(b) - set(x)), "baseline"), ("experimentOnly", sorted(set(x) - set(b)), "experiment")):
        cell = {"symbols": len(syms), "names": syms[:40]}
        for label, src in (("baseline", b), ("experiment", x)):
            if side and side != label:
                cell[label] = None
                continue
            rows = [src[s] for s in syms if s in src]
            cell[label] = {"armed": sum(r["armed"] for r in rows), "fired": sum(r["fired"] for r in rows), "filled": sum(r["filled"] for r in rows),
                           "refused": sum(r["refused"] for r in rows), "missingDataRefusals": sum(r["missingData"] for r in rows),
                           "netAfterFees": round(sum(r["net"] for r in rows), 4), "fees": round(sum(r["fees"] for r in rows), 4),
                           "exits": _merge(r["exits"] for r in rows)}
        out[name] = cell
    return out


def _merge(dicts) -> dict:
    out: dict = {}
    for d in dicts:
        for k, v in (d or {}).items():
            out[k] = out.get(k, 0) + v
    return out


def exit_policy(books: dict) -> dict:
    """Where the two books EXITED differently on the same symbol. The experiment's P-06 (`runner_protect`) is the policy
    difference by construction; everything else is the production ladder, which both books share."""
    b, x = (books.get("baseline") or {}).get("perSymbol") or {}, (books.get("experiment") or {}).get("perSymbol") or {}
    rows = []
    for sym in sorted(set(b) & set(x)):
        eb, ex = b[sym].get("exits") or {}, x[sym].get("exits") or {}
        if eb != ex:
            rows.append({"symbol": sym, "baselineExits": eb, "experimentExits": ex,
                         "p06": int(ex.get("runner_protect") or 0), "sameKinds": sorted(set(eb) & set(ex))})
    p06 = {"experiment": sum(int((v.get("exits") or {}).get("runner_protect") or 0) for v in x.values()),
           "baseline": sum(int((v.get("exits") or {}).get("runner_protect") or 0) for v in b.values())}
    return {"p06RunnerProtectExits": p06, "differingSymbols": rows,
            "note": "P-06 executes only in the experimental book; the baseline keeps the production ladder and records P-06 as an observation"}


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
                                and created_at >= $1 and created_at < $2 and result->'plan'->>'planFor' like $3""", a - dt.timedelta(hours=96), b, date + "%")   # a Monday plan is reviewed over the weekend
        rows = [{"id": r["id"], "created_at": r["created_at"].date().isoformat(), "status": r["status"], "llm": _j(r["llm"]) or {}, "usage": _j(r["usage"]) or {},
                 "result": _j(r["result"]) or {}} for r in runs if r["trigger"] != "experiment"]
        # shared order-rate window (ONE per engine, all desks): rejections and the busiest submission minute of the session
        rl = await c.fetch("""select portfolio_id, payload from events where type='RiskCheckFailed' and ts >= $1 and ts < $2""", a, b)
        rate = [r["portfolio_id"] for r in rl if any((x.get("name") == "order_rate" and not x.get("passed")) for x in ((_j(r["payload"]) or {}).get("checks") or []))]
        busiest = await c.fetchrow("""select date_trunc('minute', created_at) m, count(*) n from orders where created_at >= $1 and created_at < $2 group by 1 order by 2 desc limit 1""", a, b)
        cap = _unwrap(await c.fetchval("select value from settings where key='risk.max_orders_per_minute'"))
        out["sharedRateLimit"] = {"orderRateRejections": len(rate), "byBook": _count(rate), "busiestMinute": (str(busiest["m"]) if busiest else None),
                                  "busiestMinuteOrders": (int(busiest["n"]) if busiest else 0), "capPerMinute": cap}
        out["cohorts"] = cohorts(out["books"])
        out["exitPolicy"] = exit_policy(out["books"])
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
            ("Refused or skipped", ("activity", "refusalsByStage")), ("Of which MISSING-DATA refusals", ("activity", "missingDataRefusals")),
            ("Misses (entry errors)", ("activity", "misses")), ("Exits by kind (P-06 = runner_protect)", ("activity", "exitsByKind")),
            ("Capture unscorable reasons", ("capture", "coverage", "unscorableReasons")))
    for label, path in rows:
        L.append(f"| {label} | {g(b, *path)} | {g(x, *path)} |")
    L += ["", "## Trades by cohort (trading money only - model cost is separate, below)", "",
          "| Cohort | Symbols | Book | Armed | Fired | Filled | Refused | of which missing data | Net after fees | Fees | Exits |", "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for name, label in (("common", "Common symbols (both books armed)"), ("baselineOnly", "Baseline only"), ("experimentOnly", "Experiment only")):
        cell = (d.get("cohorts") or {}).get(name) or {}
        for who in ("baseline", "experiment"):
            v = cell.get(who)
            if v is None:
                continue
            L.append(f"| {label} | {cell.get('symbols')} | {who} | {v['armed']} | {v['fired']} | {v['filled']} | {v['refused']} | {v['missingDataRefusals']} | "
                     f"{v['netAfterFees']} | {v['fees']} | {v['exits'] or '-'} |")
    ep = d.get("exitPolicy") or {}
    L += ["", "## Exit-policy differences", "",
          f"P-06 `runner_protect` exits: experiment {ep.get('p06RunnerProtectExits', {}).get('experiment')}, baseline {ep.get('p06RunnerProtectExits', {}).get('baseline')} "
          f"({ep.get('note')}).", ""]
    if ep.get("differingSymbols"):
        L += ["| Symbol | Baseline exits | Experiment exits | P-06 exits |", "|---|---|---|---:|"]
        L += [f"| {r['symbol']} | {r['baselineExits'] or '-'} | {r['experimentExits'] or '-'} | {r['p06']} |" for r in ep["differingSymbols"][:40]]
    else:
        L += ["No common symbol exited differently in the two books this session."]
    L += [""]
    mcb = (d.get("modelCost") or {}).get("baseline") or {}
    L += ["", "## Model cost (kept apart from trading P&L, never netted into it)", "",
          f"Model cost of preparing the baseline: estimated {g(mcb, 'estimated', 'usd')} USD at the current price card (an estimate, not an invoice; never subtracted from trading results); "
              f"invoice-verified {g(mcb, 'invoiceVerified', 'usd')}; unknown requests {g(mcb, 'unknown', 'requests')}. Experiment: 0 model calls.", ""]
    rl = d.get("sharedRateLimit") or {}
    L += ["## Shared order-rate window (all desks, one engine)", "",
          f"order_rate rejections this session: {rl.get('orderRateRejections')} {rl.get('byBook') or ''}; busiest submission minute {rl.get('busiestMinute')} with "
          f"{rl.get('busiestMinuteOrders')} orders against a cap of {rl.get('capPerMinute')} per minute.", ""]
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
