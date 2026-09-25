"""EM scorecard - the track record, the stop rule and the preregistered tests (read-only, zero model calls).

    python -m zargar.tools.em_scorecard                 # everything to date
    python -m zargar.tools.em_scorecard --json
    python -m zargar.tools.em_scorecard --out <file.md> # also written by the close check each weekday

The last two lines of the text output are machine-readable for the session checks:
    STOP-RULE: collecting|passing|tripped
    TESTS-READY: <comma-separated ids or none>

It changes nothing. It never stops a book, flips a setting or retunes a threshold: it reports whether a question the
desk fixed in advance is still collecting, ready to decide, or already decided. See `technique/em_scorecard.py`.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import statistics as st

from ..technique import em_scorecard as sc

NY = dt.timezone(dt.timedelta(hours=-4))          # sessions in this record are all EDT; the label is the ET date
ARCHIVED_SHARED_BOOK = "ff3c29d46d07415c94573429b482ea2f"
EM_BOOKS = {sc.BASELINE_BOOK: "EM Practice", sc.EXPERIMENT_BOOK: "EM Experimental",
            ARCHIVED_SHARED_BOOK: "Practice (archived, shared)"}


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


def _ms(x) -> int:
    return int(x.timestamp() * 1000) if hasattr(x, "timestamp") else int(x)


def _session(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, NY).date().isoformat()


async def load(c) -> dict:
    """Everything the scorecard needs, read once. EM trades are identified by the plan's own events, not by book, so
    the old shared book contributes only the orders EM itself placed there."""
    armed = {r["run_id"]: dict(r) for r in await c.fetch(
        "select run_id, symbol, portfolio_id, plan_for from technique_armed where technique='enhanced_market'")}
    runs = list(armed)
    ev = [dict(r) for r in await c.fetch(
        "select type, ts, aggregate_id, payload from events where aggregate_id = any($1::text[]) and type = any($2::text[])",
        runs, ["TechniquePlanPositionOpened", "TechniquePlanPositionClosed", "TechniquePlanTriggerFired",
               "TechniquePlanOrderIntent", "TechniquePlanExit", "TechniqueExitQuote"])]
    for e in ev:
        e["payload"] = _j(e["payload"]) or {}
        e["ms"] = _ms(e["ts"])
    entry_orders = {str(e["payload"].get("orderId")): e for e in ev if e["type"] == "TechniquePlanPositionOpened"}
    exit_kind = {}
    for e in ev:
        if e["type"] == "TechniquePlanPositionClosed":
            for x in e["payload"].get("exits") or []:
                exit_kind[str(x.get("orderId"))] = x.get("kind")
        elif e["type"] == "TechniquePlanExit" and e["payload"].get("orderId"):
            exit_kind.setdefault(str(e["payload"]["orderId"]), e["payload"].get("kind"))
    em_orders = set(entry_orders) | set(exit_kind)
    ex = [dict(r) for r in await c.fetch(
        "select id, order_id, portfolio_id, symbol, side, qty, price, commission, ts from executions "
        "where order_id = any($1::text[])", list(em_orders))]
    for x in ex:
        x["ts"] = _ms(x["ts"])
    plans = {}
    for r in await c.fetch("select id, result->'plan'->'triggers' trig from technique_runs where id = any($1::text[])", runs):
        plans[r["id"]] = {str(t.get("id")): t for t in (_j(r["trig"]) or [])}
    rates = {"premiumStopPct": 50.0}
    for k in ("techniques.enhanced_market.premium_stop_pct", "technique.arm.premium_stop_pct"):
        v = _j(await c.fetchval("select value from settings where key=$1", k))
        v = v.get("v") if isinstance(v, dict) and "v" in v else v
        if v not in (None, ""):
            rates["premiumStopPct"] = float(v)
            break
    return {"armed": armed, "events": ev, "entryOrders": entry_orders, "exitKind": exit_kind, "executions": ex,
            "plans": plans, "rates": rates}


async def enrich(c, data: dict, trades: list) -> None:
    """Attach what the preregistered tests need to each closed trade: the trigger it came from, its window and side,
    the level's touch count, the stop against the stock's own recent range, and what price did after a stop."""
    fired = {}
    intents = {}
    exit_quotes = {}
    for e in data["events"]:
        if e["type"] == "TechniquePlanTriggerFired":
            fired.setdefault(e["aggregate_id"], []).append(e)
        elif e["type"] == "TechniquePlanOrderIntent":
            intents.setdefault(e["aggregate_id"], []).append(e)
        elif e["type"] == "TechniqueExitQuote":
            exit_quotes[str(e["payload"].get("exitOrderId") or "")] = e["payload"]
    for t in trades:
        op = data["entryOrders"].get(str(t["entryOrder"]))
        run = op["aggregate_id"] if op else None
        f = [e for e in fired.get(run, []) if e["ms"] <= t["entryTs"] + 5000]
        f = f[-1]["payload"] if f else {}
        it = [e for e in intents.get(run, []) if e["ms"] <= t["entryTs"] + 5000]
        it = it[-1]["payload"] if it else {}
        kind = f.get("kind")
        trig = str(f.get("trigger") or "")
        level = ((data["plans"].get(run) or {}).get(trig) or {}).get("level") or {}
        t.update({"run": run, "session": _session(t["entryTs"]), "kind": kind, "trigger": trig or None,
                  "direction": ("short" if kind in ("reject", "breakdown") else "long" if kind else None),
                  "window": f.get("window"), "uEntry": f.get("entry"), "uStop": f.get("stop"),
                  "targets": f.get("targets"), "underlying": f.get("symbol") or (data["armed"].get(run) or {}).get("symbol"),
                  "levelTouches": level.get("touches"), "entryQuote": (it.get("contract") or None)})
        # friction on the entry: the fill against the mid of the contract quote the order was priced on
        q = t["entryQuote"] or {}
        if t["instrument"] == "option" and q.get("bid") and q.get("ask"):
            mid = (float(q["bid"]) + float(q["ask"])) / 2
            t["entrySpreadCost"] = round((t["avgEntry"] - mid) * t["qty"] * 100, 2)
        # friction on the exit: the fill against the mid of the quote captured AT the exit decision
        costs = []
        for leg in t["legs"]:
            eq = exit_quotes.get(str(leg["order"]))
            if t["instrument"] == "option" and eq and eq.get("bid") and eq.get("ask"):
                mid = (float(eq["bid"]) + float(eq["ask"])) / 2
                costs.append((mid - leg["price"]) * leg["qty"] * 100)
        t["exitSpreadCost"] = round(sum(costs), 2) if costs else None
    # the stop against the stock's own movement, and what happened after the stop
    for t in trades:
        if t.get("uEntry") is None or t.get("uStop") is None or not t.get("underlying"):
            continue
        e, s = float(t["uEntry"]), float(t["uStop"])
        bars = [dict(r) for r in await c.fetch(
            "select ts, high, low from bars where symbol=$1 and tf='1m' and ts >= $2 and ts < $3 order by ts",
            t["underlying"], t["entryTs"] - 31 * 60_000, t["entryTs"])]
        ranges = [float(b["high"]) - float(b["low"]) for b in bars[-30:]]
        if len(ranges) >= 10 and st.mean(ranges) > 0:
            t["stopOverRange"] = round(abs(e - s) / st.mean(ranges), 2)
        if t.get("finalExit") == "stop" and t.get("targets"):
            tp1 = float(t["targets"][0])
            close_ms = int(dt.datetime.fromisoformat(f"{t['session']}T16:00:00").replace(tzinfo=NY).timestamp() * 1000)
            after = [dict(r) for r in await c.fetch(
                "select high, low from bars where symbol=$1 and tf='1m' and ts >= $2 and ts < $3",
                t["underlying"], t["legs"][-1]["ts"], close_ms)]
            short = t.get("direction") == "short"
            t["laterReachedTp1"] = any((float(b["low"]) <= tp1) if short else (float(b["high"]) >= tp1) for b in after)


async def build() -> dict:
    import asyncpg
    url = os.environ.get("ZARGAR_DATABASE_URL") or ""
    c = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await c.execute("set default_transaction_read_only = on")
        data = await load(c)
        trades, open_lots = sc.match_trades(data["executions"], exit_kind_by_order=data["exitKind"])
        await enrich(c, data, trades)
        psp = data["rates"]["premiumStopPct"]
        books = {}
        for pid, name in EM_BOOKS.items():
            mine = [t for t in trades if t["book"] == pid]
            if mine:
                books[name] = {"all": sc.summary(mine, premium_stop_pct=psp),
                               "disputedCorrected": sc.summary(mine, fair=True, premium_stop_pct=psp)}
        allb = sc.summary(trades, premium_stop_pct=psp)
        dd = sc.dedupe(trades)
        friction = {
            "fees": round(sum(float(t["fees"]) for t in trades), 2),
            "entrySpread": round(sum(t.get("entrySpreadCost") or 0 for t in trades), 2),
            "entrySpreadTrades": sum(1 for t in trades if t.get("entrySpreadCost") is not None),
            "exitSpread": (round(sum(t["exitSpreadCost"] for t in trades if t.get("exitSpreadCost") is not None), 2)
                           if any(t.get("exitSpreadCost") is not None for t in trades) else None),
            "exitSpreadTrades": sum(1 for t in trades if t.get("exitSpreadCost") is not None),
            "optionGross": round(sum(float(t["gross"]) for t in trades if t["instrument"] == "option"), 2)}
        return {"version": sc.VERSION, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "premiumStopPct": psp, "trades": len(trades), "openLots": len(open_lots),
                "allBooks": allb, "allBooksCorrected": sc.summary(trades, fair=True, premium_stop_pct=psp),
                "deduplicated": sc.summary(dd, premium_stop_pct=psp), "books": books,
                "stopRule": sc.stop_rule(trades, premium_stop_pct=psp),
                "tests": sc.run_tests(trades, premium_stop_pct=psp),
                "friction": friction, "impaired": {f"{k[0]} {EM_BOOKS.get(k[1], k[1])}": v for k, v in sc.IMPAIRED.items()},
                "disputed": [d["why"] for d in sc.DISPUTED_FILLS.values()]}
    finally:
        await c.close()


def _n(v, fmt="{:+.2f}"):
    return "unknown" if v is None else fmt.format(v)


def render(d: dict) -> str:
    a, ac, rule = d["allBooks"], d["allBooksCorrected"], d["stopRule"]
    L = [f"# EM scorecard ({d['version']})", "", f"Generated {d['generatedAt']}. Read-only; changes nothing.", "",
         "## Track record", "",
         "| | Trades | Net after fees | Win rate | Profit factor | Sum R | Mean R |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    def row(label, s):
        return (f"| {label} | {s['trades']} | {_n(s['net'])} | {_n(s['winRate'], '{:.0%}')} | "
                f"{_n(s['profitFactor'], '{:.2f}')} | {_n(s['sumR'])} | {_n(s['meanR'], '{:+.3f}')} |")
    L.append(row("All EM books", a))
    L.append(row("All, disputed fills at a fair price", ac))
    L.append(row("De-duplicated (a copied trade counted once)", d["deduplicated"]))
    for name, b in d["books"].items():
        L.append(row(name, b["all"]))
    L += ["", f"R is the method's own risk unit: the entry-to-stop distance for shares, the {d['premiumStopPct']:g}% "
              "premium stop for options - what each trade planned to lose, so it is not fitted to outcomes.", "",
          "## The stop rule", "",
          f"**{rule['verdict'].upper()}** - {rule['why']}.", "",
          f"Adopted {rule['rule']['adopted']}, counted from {rule['rule']['countFrom']}: after "
          f"{rule['rule']['minEvaluableSessions']} evaluable sessions, if cumulative R is at or below "
          f"{rule['rule']['maxCumulativeR']:g} and the optimistic average trade is below "
          f"{rule['rule']['upperMeanRBelow']:+.2f}R, {rule['rule']['action']}. It decides {rule['rule']['decides']}; "
          "the rule reports, a person acts.", "",
          "## Preregistered tests", "",
          "| Test | Question | Registered | Threshold | Now | Status | Reading (not a verdict until ready) |",
          "|---|---|---|---|---:|---|---|"]
    for t in d["tests"]:
        if t.get("status") == "decided":
            L.append(f"| {t['id']} | {t['question']} | {t['registered']} | {t.get('threshold') or (str(t.get('minSessions') or t.get('minTrades') or '') + ' (superseded)')} | - | **decided** | {t['decision']} |")
        else:
            L.append(f"| {t['id']} | {t['question']} | {t['registered']} | {t['need']} from {t['countFrom']} | "
                     f"{t['n']} | {t['status']} | {json.dumps(t['reading'], default=str)[:220]} |")
    f = d["friction"]
    L += ["", "## Friction", "",
          f"Fees {f['fees']}. Entry-side option spread {f['entrySpread']} across {f['entrySpreadTrades']} trades. "
          f"Exit-side option spread {_n(f['exitSpread'])} across {f['exitSpreadTrades']} trades "
          "(measured only from 2026-09-23, when the exit quote began to be recorded). Option gross "
          f"{f['optionGross']}.", "",
          "## Kept, but not believed", ""]
    L += [f"- impaired: {k} - {v}" for k, v in d["impaired"].items()]
    L += [f"- disputed fill: {x}" for x in d["disputed"]]
    ready = [t["id"] for t in d["tests"] if t.get("status") == "ready"]
    L += ["", f"STOP-RULE: {rule['verdict']}", f"TESTS-READY: {','.join(ready) or 'none'}"]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="EM scorecard: track record, stop rule and preregistered tests (read-only)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="also write the rendered markdown here")
    a = ap.parse_args()
    d = asyncio.run(build())
    text = json.dumps(d, indent=1, default=str) if a.json else render(d)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(render(d) + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
