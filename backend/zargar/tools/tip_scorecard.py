"""Tips economic scorecard (tips-scorecard-v1, 2026-09-19): ONE reconciled daily + cumulative view.

Composes the existing measurement - it adds no second ledger:
* trading   = `tip_outcomes.build_census` (the FIFO lot engine: realized after ALLOCATED fees, open lots at cost)
* marking   = `equity_points` (the book's persisted equity/cash; session close = last point before 04:00 ET)
* model cost= `tip_analyst_runs` usage priced with `llm.rates` (`tip_llm_cost.price`), plus the nightly
              stage rollups ONLY for stages that have no run record (extraction, transcription)

Kept APART, never blended: Practice method results; questioned fills (reviewed registry
`docs/techniques/tip/research/questioned-fills.json`); bookkeeping repairs (orders tagged `reconcile:*`, paired
with the oversell they repair); shadow research books (quarantined books listed, never summed).

Every figure carries its basis. Model dollars are list-price ESTIMATES, not an invoice; three coverage classes:
`stamped` (the run recorded the model that consumed the tokens), `run-record` (the run's own model field,
written by the loop that called it - reviews/appraisals/retros before stamping, with the unchanged configuration
cited), `unpriced` (no model or no rate). Partial = cut/cancelled/unknown-billed calls.

Usage (from backend/):
  .venv/Scripts/python -m zargar.tools.tip_scorecard --since 2026-09-08 [--until 2026-09-18] [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import os
import re

import asyncpg

from . import tip_outcomes
from .tip_llm_cost import normalize_usage, price

VERSION = "tips-scorecard-v1"
ET = dt.timezone(dt.timedelta(hours=-4))
OCC = re.compile(r"^([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")
REGISTRY = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "techniques", "tip", "research",
                        "questioned-fills.json")
STAGE_ONLY = ("extraction", "transcribe")      # stages with NO run record: priced from the nightly rollup (partial)


def J(v):
    return (json.loads(v) if isinstance(v, str) else v) or {}


def session_of(ts: dt.datetime) -> dt.date:
    """ET session date: anything before 04:00 ET belongs to the previous session (same anchor as dayStart)."""
    return (ts.astimezone(ET) - dt.timedelta(hours=4)).date()


def mult(symbol: str) -> float:
    return 100.0 if OCC.match(symbol or "") else 1.0


def load_registry(path: str = REGISTRY) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {"fills": []}


def attribute(kind: str, op: dict, *, analyst_model_configured: str | None) -> tuple[str | None, str]:
    """(model, coverage class) for one run's usage. Stamped first; the run's own model field next (the loop that
    called the provider wrote it); else unpriced. Never today's settings for a run that recorded nothing."""
    u = normalize_usage(op.get("usage"))            # a legacy per-call list carries the model on each call
    if u.get("model"):
        return str(u["model"]), "stamped"
    if kind in ("appraise", "retro") and op.get("model"):
        return str(op["model"]), "run-record"
    if kind == "intake" and op.get("verdict") == "review" and op.get("model"):
        # IntakeRun.review() writes `model` = the model its loop called (analyst_model, empty = extraction model)
        return str(op["model"]), "run-record"
    return None, "unpriced"


async def trading(conn, since: str, until: dt.date, book: str, registry: dict) -> dict:
    d = await tip_outcomes.build_census(conn, since_text=since, portfolio=book)
    q_exec = {e for f in registry.get("fills", []) if f.get("book") == book for e in f.get("executions", [])}
    repair_orders = {r["id"]: r for r in await conn.fetch(
        "select id, tags from orders where portfolio_id = $1 and source = 'manual'", book)}
    repair_ids = {oid for oid, r in repair_orders.items()
                  if any(str(t).startswith("reconcile:") for t in (J(r["tags"]) if not isinstance(r["tags"], list) else r["tags"]))}
    days: dict = collections.defaultdict(lambda: {"gross": 0.0, "fees": 0.0, "net": 0.0, "q_net": 0.0, "repair": 0.0,
                                                  "closedIdeas": set(), "trades": 0})
    for r in d["realizations"]:
        sd = session_of(r["ts"])
        if sd > until:
            continue
        net = r["gross"] - r["fees"]
        bucket = days[sd]
        if r["sellExec"] in q_exec or r["buyExec"] in q_exec:
            bucket["q_net"] += net
        else:
            bucket["gross"] += r["gross"]; bucket["fees"] += r["fees"]; bucket["net"] += net
        bucket["trades"] += 1
    # a bookkeeping repair = a reconcile-tagged manual order that closes an OVERSELL (a sell with no lot)
    repairs = []
    for e in d["execs"]:
        if e["order_id"] in repair_ids and e["side"] == "BUY":
            over = next((u for u in d["unallocated"] if u["symbol"] == e["symbol"] and abs(u["qty"] - float(e["qty"])) < 1e-9), None)
            if over is not None:
                amt = over["proceeds"] - float(e["qty"]) * float(e["price"]) * mult(e["symbol"]) - over["fee"] - float(e["commission"] or 0)
                repairs.append({"session": session_of(e["ts"]), "symbol": e["symbol"], "qty": float(e["qty"]), "net": amt,
                                "tag": [t for t in (J(repair_orders[e["order_id"]]["tags"]) or []) if str(t).startswith("reconcile:")]})
                days[session_of(e["ts"])]["repair"] += amt
    repaired_syms = {(r["symbol"]) for r in repairs}
    open_lots = [l for l in d["open_lots"] if not (l["idea"] == "__unknown__" and l["symbol"] in repaired_syms
                                                   and l["order_id"] in repair_ids)]
    return {"census": d, "days": days, "repairs": repairs, "open_lots": open_lots, "questionedExecs": q_exec}


async def marks(conn, book: str) -> dict:
    rows = await conn.fetch("select ts, equity, cash from equity_points where portfolio_id = $1 order by ts", book)
    close: dict = {}
    for r in rows:
        sd = session_of(dt.datetime.fromtimestamp(r["ts"] / 1000, dt.timezone.utc))
        close[sd] = (float(r["equity"]), float(r["cash"]), r["ts"])
    start = await conn.fetchval("select starting_cash from portfolios where id = $1", book)
    return {"close": close, "start": float(start or 0)}


async def cash_check(conn, book: str, closes: dict, start: float) -> dict:
    """Cash from executions alone vs the persisted session-close cash: the trading ledger reconciles or it does not."""
    ex = await conn.fetch("select ts, symbol, side, qty, price, commission from executions where portfolio_id = $1 order by ts", book)
    out = {}
    for sd, (_eq, cash, ts) in sorted(closes.items()):
        flows = sum((-1 if e["side"] == "BUY" else 1) * float(e["qty"]) * float(e["price"]) * mult(e["symbol"])
                    - float(e["commission"] or 0) for e in ex if e["ts"].timestamp() * 1000 <= ts)
        out[sd] = {"fromExecutions": start + flows, "persisted": cash, "diff": cash - (start + flows)}
    return out


async def model_cost(conn, since: dt.datetime, until: dt.date, rates: dict) -> dict:
    cfg_changes = await conn.fetchval(
        "select count(*) from events where type='SettingChanged' and payload->>'key' in ('techniques.tip.analyst_model')")
    runs = await conn.fetch("""select kind, source, created_at, opinion, verdict, status from tip_analyst_runs
                               where created_at >= $1 and coalesce(tip->>'experiment','') = ''""", since)
    per = collections.defaultdict(lambda: {"usd": 0.0, "runs": 0, "in": 0, "out": 0, "unpricedRuns": 0,
                                           "unpricedIn": 0, "partialRuns": 0, "unknownCalls": 0, "classes": collections.Counter()})
    by_source = collections.defaultdict(float)
    for r in runs:
        sd = session_of(r["created_at"])
        if sd > until:
            continue
        op = J(r["opinion"])
        if r["verdict"] and "verdict" not in op:
            op["verdict"] = r["verdict"]
        u = normalize_usage(op.get("usage"))
        if not u.get("in") and not u.get("out"):
            continue
        model, cls = attribute(r["kind"], op, analyst_model_configured=None)
        stage = "intake-review" if r["kind"] == "intake" and r["verdict"] == "review" else r["kind"]
        b = per[(sd, stage)]
        b["runs"] += 1; b["in"] += int(u.get("in") or 0); b["out"] += int(u.get("out") or 0)
        b["classes"][cls] += 1
        b["partialRuns"] += 1 if u.get("partial") else 0
        b["unknownCalls"] += int(u.get("unknownCalls") or 0)
        rate = rates.get(model) if model else None
        p = price({"in": u.get("in") or 0, "out": u.get("out") or 0, "cacheRead": u.get("cacheRead") or 0,
                   "cacheWrite": u.get("cacheWrite") or 0}, rate)
        if p.get("priced"):
            b["usd"] += p["usd"]
            if r["kind"] in ("appraise", "retro", "intake"):
                by_source[(sd, r["source"] or "unknown")] += p["usd"]
        else:
            b["unpricedRuns"] += 1; b["unpricedIn"] += int(u.get("in") or 0)
    # stages with no run record: the nightly rollup (partial coverage; a restart loses in-memory counts)
    stage_rows = await conn.fetch("""select payload from events where type='TechniqueHookStats'
                                     and payload->>'technique' = 'tip' and payload ? 'llm'""")
    stage_days = collections.defaultdict(dict)
    for s in stage_rows:
        p = J(s["payload"])
        try:
            sd = dt.date.fromisoformat(p.get("date"))
        except (TypeError, ValueError):
            continue
        if sd < since.date() or sd > until:
            continue
        for st in STAGE_ONLY:
            row = (p.get("llm") or {}).get(st)
            if not row:
                continue
            agg = stage_days[sd].setdefault(st, {"in": 0, "out": 0, "requests": 0, "models": collections.Counter()})
            agg["in"] += int(row.get("inputTokens") or 0); agg["out"] += int(row.get("outputTokens") or 0)
            agg["requests"] += int(row.get("requests") or 0)
            agg["models"].update(row.get("models") or {})
    for sd, stages in stage_days.items():
        for st, agg in stages.items():
            model = agg["models"].most_common(1)[0][0] if len(agg["models"]) == 1 else None
            b = per[(sd, st)]
            b["runs"] += agg["requests"]; b["in"] += agg["in"]; b["out"] += agg["out"]
            p = price({"in": agg["in"], "out": agg["out"]}, rates.get(model) if model else None)
            if p.get("priced"):
                b["usd"] += p["usd"]; b["classes"]["rollup-partial"] += 1
            else:
                b["unpricedRuns"] += 1; b["unpricedIn"] += agg["in"]
    return {"per": per, "bySource": by_source, "analystModelChanges": int(cfg_changes or 0)}


async def build(conn, *, since: str, until: dt.date, book: str) -> dict:
    registry = load_registry()
    rates_raw = J(await conn.fetchval("select value from settings where key='llm.rates'"))
    rates = rates_raw["v"] if isinstance(rates_raw.get("v"), dict) else rates_raw
    t = await trading(conn, since, until, book, registry)
    m = await marks(conn, book)
    cash = await cash_check(conn, book, m["close"], m["start"])
    since_dt = dt.datetime.combine(dt.date.fromisoformat(since), dt.time(4, 0), tzinfo=ET)
    mc = await model_cost(conn, since_dt, until, rates)
    shadows = []
    for pf in await conn.fetch("select id, name, quarantined, book from portfolios where kind='shadow' and archived is not true order by name"):
        sd = await tip_outcomes.build_census(conn, since_text=since, portfolio=pf["id"], kinds=("shadow",))
        net = sum(r["gross"] - r["fees"] for r in sd["realizations"] if session_of(r["ts"]) <= until)
        shadows.append({"book": pf["name"], "quarantined": bool(pf["quarantined"]), "kind": pf["book"],
                        "realizedNet": net, "closedMatches": len(sd["realizations"]),
                        "openLots": len(sd["open_lots"]), "unallocated": len(sd["unallocated"])})
    return {"version": VERSION, "since": since, "until": until.isoformat(), "book": book, "trading": t, "marks": m,
            "cash": cash, "model": mc, "shadows": shadows, "registry": registry}


def source_setup(res: dict) -> list[dict]:
    """Idea-level economics by source x setup x entry style (method results only; questioned apart)."""
    t = res["trading"]; cen = t["census"]
    until = dt.date.fromisoformat(res["until"])
    q = t["questionedExecs"]
    first_buy_src = {}
    order_src = {o["id"]: o.get("source") for o in cen["orders"]} if cen["orders"] and "source" in cen["orders"][0] else {}
    for e in sorted(cen["execs"], key=lambda e: e["ts"]):
        if e["side"] == "BUY":
            first_buy_src.setdefault(e["order_id"], order_src.get(e["order_id"]))
    per_idea = collections.defaultdict(lambda: {"net": 0.0, "fees": 0.0, "q": 0.0, "path": []})
    for r in sorted(cen["realizations"], key=lambda r: r["ts"]):
        if session_of(r["ts"]) > until:
            continue
        net = r["gross"] - r["fees"]
        a = per_idea[r["idea"]]
        if r["sellExec"] in q or r["buyExec"] in q:
            a["q"] += net
        else:
            a["net"] += net; a["fees"] += r["fees"]
    rows = collections.defaultdict(lambda: {"ideas": 0, "filled": 0, "completed": 0, "partial": 0, "net": 0.0, "fees": 0.0,
                                            "wins": [], "losses": [], "open_cost": 0.0, "q": 0.0, "seq": []})
    buys_by_order = collections.defaultdict(list)
    for e in cen["execs"]:
        if e["side"] == "BUY":
            buys_by_order[e["order_id"]].append(e)
    idea_orders = collections.defaultdict(list)
    for o in cen["orders"]:
        owner = cen["ownerByOrder"].get(o["id"])
        if owner and o["side"] == "BUY":
            idea_orders[owner].append(o)
    for r in cen["rows"]:
        if not r["disp"].startswith("filled"):
            continue
        style = "armed-at-level" if any((o.get("source") or "") == "technique" for o in idea_orders.get(r["id"], [])) else "proposal-now"
        key = (r["source"], r["bucket"], style)
        g = rows[key]; a = per_idea.get(r["id"]) or {"net": 0.0, "fees": 0.0, "q": 0.0}
        g["ideas"] += 1; g["filled"] += 1; g["open_cost"] += r["open_cost"]; g["q"] += a["q"]
        g["net"] += a["net"]; g["fees"] += a["fees"]
        if r["completed"]:
            g["completed"] += 1
            (g["wins"] if a["net"] > 0 else g["losses"]).append(a["net"])
        elif a["net"] or r["open_cost"]:
            g["partial"] += 1 if a["net"] else 0
        g["seq"].append((r["created_at"], a["net"]))
    out = []
    for (src, bkt, style), g in rows.items():
        cum = peak = dd = 0.0
        for _t, v in sorted(g["seq"], key=lambda x: x[0]):
            cum += v; peak = max(peak, cum); dd = min(dd, cum - peak)
        out.append({"source": src, "setup": bkt, "entry": style, **{k: g[k] for k in ("ideas", "completed", "partial", "net", "fees", "open_cost", "q")},
                    "wins": len(g["wins"]), "avgWin": (sum(g["wins"]) / len(g["wins"])) if g["wins"] else None,
                    "losses": len(g["losses"]), "avgLoss": (sum(g["losses"]) / len(g["losses"])) if g["losses"] else None,
                    "maxDrawdown": dd})
    return sorted(out, key=lambda r: r["net"])


def render(res: dict) -> str:
    L = []
    t, m, mc = res["trading"], res["marks"], res["model"]
    since = dt.date.fromisoformat(res["since"]); until = dt.date.fromisoformat(res["until"])
    sessions = sorted(sd for sd in set(t["days"]) | set(m["close"]) | {k[0] for k in mc["per"]} if since <= sd <= until)
    L.append(f"# Tips economic scorecard ({VERSION}) - {res['since']} .. {res['until']}\n")
    L.append("Tips Practice book only in the trading columns; shadow research books are listed apart and never summed. "
             "Realized = FIFO lots after ALLOCATED fees (the census engine). Marked change = persisted session-close "
             "equity minus the previous close. Model cost = list-price ESTIMATE from `llm.rates` - not an invoice.\n")
    L.append("| session | method realized net | fees in it | questioned net | repairs | close equity | marked change | open (MV - cost) | model cost (priced) | unpriced runs | partial runs | net after model cost |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    prev_eq = m["start"]; cum = collections.Counter()
    for sd in sessions:
        dd = t["days"].get(sd) or {"net": 0.0, "fees": 0.0, "q_net": 0.0, "repair": 0.0}
        eq = m["close"].get(sd)
        chg = (eq[0] - prev_eq) if eq else None
        mv_minus_cost = None
        if eq:
            open_cost = sum(l["qty"] * l["px"] * mult(l["symbol"]) for l in t["open_lots"]
                            if session_of(l["ts"]) <= sd)          # approximate at that close (lots still open today)
            mv_minus_cost = (eq[0] - eq[1]) - open_cost if sd == max(m["close"]) else None
        cost_rows = [v for (d, _st), v in mc["per"].items() if d == sd]
        usd = sum(v["usd"] for v in cost_rows)
        unp = sum(v["unpricedRuns"] for v in cost_rows)
        part = sum(v["partialRuns"] for v in cost_rows)
        trade_total = dd["net"] + dd["q_net"] + dd["repair"]
        L.append(f"| {sd} | {dd['net']:+,.2f} | {dd['fees']:,.2f} | {dd['q_net']:+,.2f} | {dd['repair']:+,.2f} | "
                 f"{(f'{eq[0]:,.2f}' if eq else '-')} | {(f'{chg:+,.2f}' if chg is not None else '-')} | "
                 f"{(f'{mv_minus_cost:+,.2f}' if mv_minus_cost is not None else '')} | {usd:,.2f} | {unp} | {part} | "
                 f"{trade_total - usd:+,.2f} |")
        cum["net"] += dd["net"]; cum["fees"] += dd["fees"]; cum["q"] += dd["q_net"]; cum["rep"] += dd["repair"]
        cum["usd"] += usd; cum["unp"] += unp; cum["part"] += part
        if eq:
            prev_eq = eq[0]
    last = m["close"].get(max(sd for sd in m["close"] if sd <= until)) if m["close"] else None
    L.append(f"| **cumulative** | **{cum['net']:+,.2f}** | {cum['fees']:,.2f} | {cum['q']:+,.2f} | {cum['rep']:+,.2f} | "
             f"{(f'{last[0]:,.2f}' if last else '-')} | **{((last[0] - m['start']) if last else 0):+,.2f}** | | "
             f"**{cum['usd']:,.2f}** | {cum['unp']} | {cum['part']} | **{cum['net'] + cum['q'] + cum['rep'] - cum['usd']:+,.2f}** |")
    # reconciliation
    L.append("\n## Reconciliation\n")
    worst = max((abs(v["diff"]) for v in res["cash"].values()), default=0.0)
    L.append(f"- **Cash from executions vs persisted cash** at every session close: largest difference ${worst:,.2f} "
             f"({'reconciles' if worst < 0.05 else 'DOES NOT reconcile - see rows'}).")
    if last:
        open_cost = sum(l["qty"] * l["px"] * mult(l["symbol"]) for l in t["open_lots"])
        open_fees = sum(l["qty"] * l["fee_unit"] for l in t["open_lots"])
        realized_all = cum["net"] + cum["q"] + cum["rep"]
        unreal = (last[0] - last[1]) - open_cost
        resid = last[0] - (m["start"] + realized_all + unreal - open_fees)
        L.append(f"- **Equity identity at the last close:** start {m['start']:,.2f} + realized (method + questioned + "
                 f"repairs) {realized_all:+,.2f} + open MV-cost {unreal:+,.2f} - entry fees on open lots {open_fees:,.2f} = "
                 f"{m['start'] + realized_all + unreal - open_fees:,.2f} vs persisted {last[0]:,.2f} (residual {resid:+,.2f}).")
    for r in t["repairs"]:
        L.append(f"- **Bookkeeping repair** {r['session']} {r['symbol']} x{r['qty']:g}: {r['net']:+,.2f} ({', '.join(r['tag'])}) - "
                 "reported apart; not a method result.")
    for f in res["registry"].get("fills", []):
        L.append(f"- **Questioned fill** {f['session']} {f['symbol']} ({f['flag']}): kept on the ledger, graded apart - {f['evidence']}.")
    cen = t["census"]
    if cen["unallocated"]:
        rem = [u for u in cen["unallocated"] if u["symbol"] not in {r["symbol"] for r in t["repairs"]}]
        if rem:
            L.append(f"- Unallocated sells not explained by a repair: {len(rem)} (see the census exceptions).")
    # model cost by stage
    L.append("\n## Model operating cost by stage (cumulative, list-price estimate)\n")
    L.append("| stage | runs/requests | input tokens | output tokens | priced $ | stamped | run-record | rollup (partial) | unpriced runs | unpriced input | partial runs | unknown calls |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    st = collections.defaultdict(lambda: {"runs": 0, "in": 0, "out": 0, "usd": 0.0, "c": collections.Counter(),
                                          "ur": 0, "ui": 0, "pr": 0, "uc": 0})
    for (sd, stage), v in mc["per"].items():
        if not (since <= sd <= until):
            continue
        a = st[stage]; a["runs"] += v["runs"]; a["in"] += v["in"]; a["out"] += v["out"]; a["usd"] += v["usd"]
        a["c"].update(v["classes"]); a["ur"] += v["unpricedRuns"]; a["ui"] += v["unpricedIn"]
        a["pr"] += v["partialRuns"]; a["uc"] += v["unknownCalls"]
    for stage, a in sorted(st.items(), key=lambda kv: -kv[1]["usd"]):
        L.append(f"| {stage} | {a['runs']} | {a['in']:,} | {a['out']:,} | {a['usd']:,.2f} | {a['c']['stamped']} | "
                 f"{a['c']['run-record']} | {a['c']['rollup-partial']} | {a['ur']} | {a['ui']:,} | {a['pr']} | {a['uc']} |")
    L.append(f"\nAttribution basis: `stamped` = usage.model recorded by the loop; `run-record` = the run's own model "
             f"field written by the loop that called the provider (journaled changes to techniques.tip.analyst_model in "
             f"the record: {mc['analystModelChanges']}); `rollup (partial)` = nightly stage counters for extraction/"
             "transcription, which have no run record and lose in-memory counts across restarts - a LOWER BOUND. "
             "Digest and rule-audit are desk overhead (no source).")
    # by source
    L.append("\n## Priced model cost by source (appraise + retro + intake reviews)\n")
    srcs = collections.Counter()
    for (sd, src), usd in mc["bySource"].items():
        if since <= sd <= until:
            srcs[src] += usd
    L.append("| source | priced $ |")
    L.append("|---|---:|")
    for src, usd in srcs.most_common():
        L.append(f"| {src} | {usd:,.2f} |")
    # source x setup x entry style
    L.append("\n## Source x setup x entry style - FILLED Practice ideas (method results; questioned apart)\n")
    L.append("| source | setup | entry | filled ideas | completed | partial | net realized | fees | wins (avg) | losses (avg) | max drawdown | open at cost | questioned net |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|")
    for r in source_setup(res):
        L.append(f"| {r['source']} | {r['setup']} | {r['entry']} | {r['ideas']} | {r['completed']} | {r['partial']} | {r['net']:+,.2f} | "
                 f"{r['fees']:,.2f} | {r['wins']}" + (f" ({r['avgWin']:+,.2f})" if r['avgWin'] is not None else "") + f" | {r['losses']}"
                 + (f" ({r['avgLoss']:+,.2f})" if r['avgLoss'] is not None else "") + f" | {r['maxDrawdown']:+,.2f} | {r['open_cost']:,.2f} | {r['q']:+,.2f} |")
    L.append("\nNo cohort above has enough completed ideas to claim an edge; the table ranks where money went, not what will "
             "work. Open exposure is at cost and is not credited to any cohort.")
    # shadow books
    L.append("\n## Shadow research books (never summed with Practice; quarantined books excluded from any judgement)\n")
    L.append("| book | kind | quarantined | realized net (FIFO, research) | matched sells | open lots | unallocated sells |")
    L.append("|---|---|---|---:|---:|---:|---:|")
    for s in res["shadows"]:
        L.append(f"| {s['book']} | {s['kind'] or '-'} | {'YES' if s['quarantined'] else ''} | {s['realizedNet']:+,.2f} | "
                 f"{s['closedMatches']} | {s['openLots']} | {s['unallocated']} |")
    L.append("\nShadow books buy at tip time or at the level with research sizing and no fees model parity; their cash is "
             "not a portfolio. They inform source comparison only.")
    return "\n".join(L) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--since", default="2026-09-08")
    ap.add_argument("--until", default="")
    ap.add_argument("--book", default="", help="Tips Practice book id (default: techniques.tip.default_portfolio)")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    conn = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        book = a.book
        if not book:
            v = J(await conn.fetchval("select value from settings where key='techniques.tip.default_portfolio'"))
            book = v.get("v") if isinstance(v, dict) else v
        until = dt.date.fromisoformat(a.until) if a.until else session_of(dt.datetime.now(dt.timezone.utc))
        res = await build(conn, since=a.since, until=until, book=str(book))
        print(render(res))
        if a.json:
            def plain(v):
                if isinstance(v, dict):
                    return {("|".join(map(str, k)) if isinstance(k, tuple) else str(k)): plain(x) for k, x in v.items()}
                if isinstance(v, (list, tuple, set)):
                    return [plain(x) for x in v]
                return v if isinstance(v, (int, float, str, bool)) or v is None else str(v)
            summary = {k: res[k] for k in ("version", "since", "until", "book", "shadows")}
            summary["days"] = plain(res["trading"]["days"]); summary["repairs"] = plain(res["trading"]["repairs"])
            summary["cash"] = plain(res["cash"]); summary["modelCost"] = plain(res["model"]["per"])
            summary["sourceSetup"] = plain(source_setup(res))
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump(plain(summary), f, indent=1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
