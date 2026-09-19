"""EM Experimental - pre-open verification of the two Practice books (em-experiment-v1). READ-ONLY; zero model calls.

    python -m zargar.tools.em_experiment_check --date 2026-09-21 [--json]

Session, effective risk limits, routing and operating owner, for the baseline (EM Practice) and the experiment
(EM Experimental) side by side. Every value is read from the database and the live settings; nothing is changed.
A per-plan `dailyLossLimit` is checked against the declared rule: 2 x riskPct x the BOOK's equity at arm time
(`PlanRunner._ensure_loss_halt`), so two books with different equity legitimately carry different allowances.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from zoneinfo import ZoneInfo

import asyncpg

NY = ZoneInfo("America/New_York")
BUNDLE_KEYS = ("preparation_policy", "conditional_review_fix", "prep_grade_floor", "first_sale_rr_gate",
               "book_snapshot_observe", "source_candidates_execute", "runner_protection")
TECHNIQUE_WIDE = ("techniques.enhanced_market.first_sale_rr_gate", "techniques.enhanced_market.preparation_policy",
                  "techniques.enhanced_market.book_snapshot_observe", "techniques.enhanced_market.source_candidates_observe",
                  "techniques.enhanced_market.source_scenarios_observe", "techniques.enhanced_market.shadow_exit_observe",
                  "techniques.enhanced_market.shadow_p02_candidate", "techniques.enhanced_market.paused")
LIMIT_KEYS = ("mode", "instrument", "riskPct", "maxQty", "contracts", "maxContracts", "singleContractExit", "maxOpenTrades",
              "entryFallback", "skipWideSpread", "skipElevatedIv", "slippagePct", "flattenMinutesBeforeClose", "allowLive")


def _j(v):
    return v if isinstance(v, (dict, list)) or v is None else json.loads(v)


def _unwrap(v):
    v = _j(v)
    return v["v"] if isinstance(v, dict) and set(v) == {"v"} else v


async def _book(c, pid: str, date: str, label: str) -> dict:
    p = await c.fetchrow("select id, name, kind, cash, starting_cash, archived, quarantined from portfolios where id=$1", pid) if pid else None
    rows = [dict(r) for r in await c.fetch("""select a.run_id, a.symbol, a.status, a.mode, a.config, r.tags, r.trigger, r.config->'promotion' promo
                                              from technique_armed a join technique_runs r on r.id = a.run_id
                                              where a.technique='enhanced_market' and a.portfolio_id=$1 and a.plan_for=$2""", pid, date)] if pid else []
    cfgs = [_j(r["config"]) or {} for r in rows]
    limits = {k: sorted({json.dumps(c0.get(k)) for c0 in cfgs}) for k in LIMIT_KEYS}
    losses = sorted({round(float(c0.get("dailyLossLimit") or 0), 2) for c0 in cfgs})
    eq = await c.fetchval("select equity from equity_points where portfolio_id=$1 order by ts desc limit 1", pid) if pid else None
    risk = sorted({float(c0.get("riskPct") or 0) for c0 in cfgs}) or [None]
    expect = [round(float(eq or (p["cash"] if p else 0)) * r / 100 * 2, 2) for r in risk if r]
    return {"label": label, "portfolio": (dict(p) if p else None), "lastEquityPoint": eq,
            "armedForSession": {"count": len(rows), "byStatus": _count(r["status"] for r in rows), "byMode": _count(r["mode"] for r in rows),
                                "byRunTrigger": _count(r["trigger"] for r in rows), "promoted": _count((_j(r["promo"]) or {}).get("variant") for r in rows if _j(r["promo"]))},
            "openPositions": [dict(r) for r in await c.fetch("select symbol, sec_type, qty, avg_cost from positions where portfolio_id=$1 and qty <> 0", pid)] if pid else [],
            "workingOrders": (await c.fetchval("select count(*) from orders where portfolio_id=$1 and status in ('NEW','SUBMITTED','PARTIALLY_FILLED')", pid) if pid else 0),
            "effectiveLimits": {k: (json.loads(v[0]) if len(v) == 1 else [json.loads(x) for x in v]) for k, v in limits.items()},
            "dailyLossLimits": losses, "dailyLossRule": "2 x riskPct x the book's equity at arm time",
            "dailyLossExpectedNow": expect, "dailyLossMatchesRule": (not losses) or (not expect) or all(abs(l - expect[0]) <= 0.02 for l in losses),
            "experimentTagged": sum(1 for r in rows if any(str(t).startswith("experiment:") for t in (_j(r["tags"]) or []))),
            "perTechniqueLossHaltPct": None}


EXCEPTION_TYPES = ("BookHaltEngaged", "BookPaused", "TechniqueLossHalt", "DailyLossHalt", "TechniqueArmRefused", "OpsQuiesce",
                   "TechniquePlanRestored", "TechniquePlanError")
QUIET = ("TechniquePlanRestored", "OpsQuiesce")            # counted, never listed one by one: a restart journals one per plan


async def exceptions(c, date: str, books: list) -> dict:
    """Operational exceptions of the session, for prompt reporting: anything that stopped, refused or degraded trading in
    either EM book, plus the shared conditions that reach both. Facts only - no judgement, no action."""
    d = dt.date.fromisoformat(date)
    a = dt.datetime(d.year, d.month, d.day, 4, 0, tzinfo=NY)
    b = a + dt.timedelta(hours=16)
    ours = {str(x) for x in books if x}
    rows = [dict(r) for r in await c.fetch("select type, ts, portfolio_id, payload from events where ts >= $1 and ts < $2 and type = any($3::text[]) order by ts", a, b, list(EXCEPTION_TYPES))]
    out: dict = {"window": [a.isoformat(), b.isoformat()], "byType": {}, "items": [], "rateLimit": {}, "recorder": {}, "unscorable": {}}
    for r in rows:
        p = _j(r["payload"]) or {}
        mine = (str(r["portfolio_id"] or "") in ours) or (str(p.get("portfolioId") or "") in ours)
        if r["type"] in ("TechniquePlanError", "TechniquePlanAlert") and not mine:
            continue                                        # another desk's plan noise is not an EM exception
        key = r["type"] + ("" if mine else " (other book)")
        out["byType"][key] = out["byType"].get(key, 0) + 1
        if r["type"] not in QUIET and len(out["items"]) < 40:
            out["items"].append({"at": r["ts"].isoformat(), "type": r["type"], "book": (r["portfolio_id"] or p.get("portfolioId")),
                                 "why": str(p.get("reason") or p.get("error") or p.get("text") or p.get("label") or "")[:180], "ours": mine})
    rl = await c.fetch("select portfolio_id, payload from events where type='RiskCheckFailed' and ts >= $1 and ts < $2", a, b)
    hit = [r["portfolio_id"] for r in rl if any((x.get("name") == "order_rate" and not x.get("passed")) for x in ((_j(r["payload"]) or {}).get("checks") or []))]
    busiest = await c.fetchrow("select date_trunc('minute', created_at) m, count(*) n from orders where created_at >= $1 and created_at < $2 group by 1 order by 2 desc limit 1", a, b)
    out["rateLimit"] = {"orderRateRejections": len(hit), "byBook": _count(hit), "ours": sum(1 for x in hit if str(x) in ours),
                        "busiestMinute": (str(busiest["m"]) if busiest else None), "busiestMinuteOrders": (int(busiest["n"]) if busiest else 0),
                        "capPerMinute": _unwrap(await c.fetchval("select value from settings where key='risk.max_orders_per_minute'"))}
    if await c.fetchval("select to_regclass('public.technique_book_snapshots') is not null"):
        for pid in ours:
            snaps = [_j(r["payload"]) for r in await c.fetch("select payload from technique_book_snapshots where portfolio_id=$1 and session=$2 order by captured_at", pid, date)]
            if not snaps:
                continue
            per: dict = {}
            reasons: dict = {}
            for sn in snaps:
                rec = sn.get("recorder") or {}
                k = sn.get("recorderInstance")
                per[k] = max(per.get(k, 0), int(rec.get("droppedQueueFull", 0)) + int(rec.get("droppedWriteFailed", 0)))
                for why in (sn.get("book") or {}).get("unscorableReasons") or []:
                    reasons[str(why).split(":")[0]] = reasons.get(str(why).split(":")[0], 0) + 1
            out["recorder"][pid] = {"snapshots": len(snaps), "instances": len(per), "drops": sum(per.values())}
            out["unscorable"][pid] = reasons
    out["anythingToReport"] = bool(out["items"] or out["rateLimit"]["orderRateRejections"] or any(v["drops"] for v in out["recorder"].values()))
    return out


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


async def build(date: str, *, with_exceptions: bool = False) -> dict:
    from .em_prep_ablation import _db_url
    c = await asyncpg.connect(_db_url())
    await c.execute("set default_transaction_read_only = on")
    try:
        xp = _unwrap(await c.fetchval("select value from settings where key='techniques.enhanced_market.experiment'")) or {}
        base_id = _unwrap(await c.fetchval("select value from settings where key='techniques.enhanced_market.default_portfolio'")) or ""
        out = {"date": date, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "experiment": {"enabled": bool(xp.get("enabled")), "portfolioId": xp.get("portfolioId"), "version": xp.get("version"), "label": xp.get("label"),
                              "owner": xp.get("owner"), "startedAt": xp.get("startedAt"), "comparisonTs": xp.get("comparisonTs"), "startingEquity": xp.get("startingEquity"),
                              "overrides": {k: (xp.get("overrides") or {}).get(k) for k in BUNDLE_KEYS}},
               "techniqueWide": {k.rsplit(".", 1)[-1]: _unwrap(await c.fetchval("select value from settings where key=$1", k)) for k in TECHNIQUE_WIDE},
               "shared": {"maxOrdersPerMinute": _unwrap(await c.fetchval("select value from settings where key='risk.max_orders_per_minute'")),
                          "dayNotionalPerTechnique": _unwrap(await c.fetchval("select value from settings where key='risk.max_day_notional_per_technique'")),
                          "emLossHaltPct": _unwrap(await c.fetchval("select value from settings where key='techniques.enhanced_market.daily_loss_halt_pct'")),
                          "bookLossHaltPct": _unwrap(await c.fetchval("select value from settings where key='risk.daily_loss_halt_pct'"))},
               "books": [await _book(c, base_id, date, "baseline (EM Practice)"),
                         await _book(c, str(xp.get("portfolioId") or ""), date, "experiment (EM Experimental)")]}
        if with_exceptions:
            out["exceptions"] = await exceptions(c, date, [base_id, str(xp.get("portfolioId") or "")])
        stray = await c.fetchval("""select count(*) from technique_armed a join technique_runs r on r.id=a.run_id
                                    where a.portfolio_id <> $1 and r.tags::text like '%experiment:%' and a.status in ('armed','paused')""", str(xp.get("portfolioId") or ""))
        out["routing"] = {"taggedRunsArmedOutsideTheExperimentalBook": int(stray or 0),
                          "untaggedArmsInsideTheExperimentalBook": int(await c.fetchval("""select count(*) from technique_armed a join technique_runs r on r.id=a.run_id
                                                                                          where a.portfolio_id=$1 and a.status in ('armed','paused') and r.tags::text not like '%experiment:%'""",
                                                                                        str(xp.get("portfolioId") or "")) or 0),
                          "bothBooksAreSim": all((b["portfolio"] or {}).get("kind") == "sim" for b in out["books"] if b["portfolio"])}
    finally:
        await c.close()
    return out


def render(d: dict) -> str:
    L = [f"# EM books - pre-open verification, {d['date']}", "", f"Generated {d['generatedAt']} (read-only).",
         f"Experiment `{d['experiment']['version']}` enabled: **{d['experiment']['enabled']}**; owner: {d['experiment'].get('owner')}", "",
         "| Item | " + " | ".join(b["label"] for b in d["books"]) + " |", "|---|" + "---|" * len(d["books"])]

    def row(label, fn):
        L.append(f"| {label} | " + " | ".join(str(fn(b)) for b in d["books"]) + " |")
    row("Book id", lambda b: (b["portfolio"] or {}).get("id"))
    row("Kind", lambda b: (b["portfolio"] or {}).get("kind"))
    row("Cash", lambda b: (b["portfolio"] or {}).get("cash"))
    row("Last equity point", lambda b: b["lastEquityPoint"])
    row("Armed for the session", lambda b: f"{b['armedForSession']['count']} {b['armedForSession']['byStatus']} {b['armedForSession']['byMode']}")
    row("Plan origins", lambda b: b["armedForSession"]["byRunTrigger"])
    row("Promoted candidates", lambda b: b["armedForSession"]["promoted"] or "none")
    row("Experiment-tagged arms", lambda b: b["experimentTagged"])
    row("Open positions / working orders", lambda b: f"{len(b['openPositions'])} / {b['workingOrders']}")
    for k in LIMIT_KEYS:
        row(f"Limit: {k}", lambda b, k=k: b["effectiveLimits"].get(k))
    row("Daily loss limit per plan", lambda b: b["dailyLossLimits"])
    row("Matches 2 x riskPct x equity", lambda b: b["dailyLossMatchesRule"])
    L += ["", "Technique-wide EM settings (must be unchanged by the experiment): " + json.dumps(d["techniqueWide"], default=str),
          "", "Shared, not per book: " + json.dumps(d["shared"], default=str),
          "", "Routing: " + json.dumps(d["routing"], default=str), ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(NY).date().isoformat())
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--exceptions", action="store_true", help="operational exceptions of the session (halts, pauses, arm refusals, restarts, order-rate rejections, recorder drops)")
    a = ap.parse_args()
    d = asyncio.run(build(a.date, with_exceptions=a.exceptions))
    if a.json:
        print(json.dumps(d, indent=1, default=str))
    else:
        print(render(d))
        if a.exceptions:
            e = d["exceptions"]
            print("\n## Operational exceptions\n")
            print(f"Anything to report: **{e['anythingToReport']}**. By type: {e['byType'] or 'none'}.")
            print(f"Shared order-rate window: {e['rateLimit']['orderRateRejections']} rejections ({e['rateLimit']['ours']} in an EM book); busiest minute "
                  f"{e['rateLimit']['busiestMinute']} with {e['rateLimit']['busiestMinuteOrders']} orders, cap {e['rateLimit']['capPerMinute']}.")
            print(f"Recorder: {e['recorder'] or 'no captures'}; unscorable reasons: {e['unscorable'] or 'none'}.")
            for it in e["items"]:
                print(f"- {it['at']} {it['type']} book={it['book']} ours={it['ours']} {it['why']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
