"""ED-04 report command (integrated plan E): realized / displayed / covered-executable profit for the EM Practice book.

    python -m zargar.tools.em_profit_capture report --date 2026-09-18 [--stdout]

READ-ONLY (one read-only transaction). Reads `technique_book_snapshots` (the ED-04 recorder, default OFF), the
execution ledger (`executions`) for the execution-backed net, the persisted equity samples as a labelled DISPLAYED
series, and - when present - the per-trade P-02 / P-06 rows of `research/profitability/<date>.json` for the consumer
join. When the recorder did not run (every session before its activation) the executable section says so: nothing is
reconstructed from marks, bars or hindsight. Output: `research/profit-capture/<date>.{md,json}`.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

from ..technique.profit_capture import instrument_of, reduce_session

NY = ZoneInfo("America/New_York")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EM_BOOK = "045d8c35b3f149628ea001ae90a58edb"
OUT_DIR = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "profit-capture")
PROFITABILITY_DIR = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "profitability")
DISPUTED = {"2026-09-17": ["ORCL: the 09-17 simulated fill is questioned by the 09-17 review (E17-01 derived-quote producer); "
                           "the execution ledger is reported as booked and flagged - no replacement price is invented"]}


def _ms(d: dt.date, hh: int, mm: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).timestamp() * 1000)


def execution_net(rows: list) -> dict:
    """Execution-backed session result from raw fills: sells - buys - commissions, per held symbol and in total. A symbol
    whose bought and sold quantities differ is OPEN at the cutoff and is excluded from the flat total (listed)."""
    per: dict[str, dict] = {}
    unknown: list = []
    for r in rows:
        sym = r["symbol"]
        m, prob = instrument_of(sym, r.get("sec_type") or r.get("secType"))
        if prob:                                              # unknown / conflicting instrument identity: never priced by the symbol's shape
            unknown.append(prob)
            continue
        p = per.setdefault(sym, {"buyQty": 0.0, "sellQty": 0.0, "cash": 0.0, "fees": 0.0, "multiplier": m})
        amt = float(r["qty"]) * float(r["price"]) * m
        if str(r["side"]).upper() == "BUY":
            p["buyQty"] += float(r["qty"]); p["cash"] -= amt
        else:
            p["sellQty"] += float(r["qty"]); p["cash"] += amt
        p["fees"] += float(r["commission"] or 0.0)
    flat = {k: v for k, v in per.items() if abs(v["buyQty"] - v["sellQty"]) < 1e-9}
    open_ = sorted(k for k in per if k not in flat)
    return {"net": round(sum(v["cash"] - v["fees"] for v in flat.values()), 4), "fees": round(sum(v["fees"] for v in flat.values()), 4),
            "bySymbol": {k: {"net": round(v["cash"] - v["fees"], 4), "fees": round(v["fees"], 4), "qty": v["buyQty"]} for k, v in sorted(flat.items())},
            "openAtCutoff": open_, "fills": len(rows), "unknownInstrument": sorted(set(unknown)),
            "complete": not unknown}


async def build(date: str) -> dict:
    import asyncpg
    from .. import config as _config
    session = dt.date.fromisoformat(date)
    t0, t1 = _ms(session, 4, 0), _ms(session, 20, 0)
    url = _config.AppConfig().database_url.replace("postgresql+asyncpg://", "postgresql://")
    c = await asyncpg.connect(url)
    await c.execute("set default_transaction_read_only = on")
    try:
        ex = [dict(r) for r in await c.fetch("""select e.id, e.order_id, e.symbol, e.side, e.qty, e.price, e.commission, e.ts, o.sec_type
            from executions e join orders o on o.id = e.order_id
            where e.portfolio_id=$1 and e.ts >= to_timestamp($2/1000.0) and e.ts < to_timestamp($3/1000.0) order by e.ts, e.id""", EM_BOOK, t0, t1)]
        eq = [dict(r) for r in await c.fetch("""select ts, equity, cash from equity_points where portfolio_id=$1 and ts >= $2 and ts < $3 order by ts""",
                                             EM_BOOK, _ms(session, 9, 30), _ms(session, 16, 0))]
        has_table = await c.fetchval("select to_regclass('public.technique_book_snapshots') is not null")
        snaps = []
        if has_table:
            rows = await c.fetch("""select payload from technique_book_snapshots where portfolio_id=$1 and session=$2 order by captured_at, seq""", EM_BOOK, date)
            snaps = [(r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"])) for r in rows]
        build_sha = next((((x.get('ids') or {}).get('build')) for x in snaps if (x.get('ids') or {}).get('build')), None)   # recorded by the capture itself
    finally:
        await c.close()
    p02 = p06 = None
    pj = os.path.join(PROFITABILITY_DIR, f"{date}.json")
    if os.path.exists(pj):
        d = json.load(open(pj, encoding="utf-8"))
        trades = d.get("trades") or []
        p06 = [{"tradeInstance": t.get("entryOrderId"), "policy": (t.get("p06") or {}).get("policy"), "signalTs": (t.get("p06") or {}).get("signalTs"),
                "outcome": (t.get("p06") or {}).get("outcome"), "dollarDelta": (t.get("p06") or {}).get("dollarDelta")} for t in trades if t.get("p06")]
        p02 = [{"tradeInstance": t.get("entryOrderId"), "policy": "small-position-exit-v1", "signalTs": (t.get("p02") or {}).get("observedAt"),
                "outcome": (t.get("p02") or {}).get("outcome"), "dollarDelta": (t.get("p02") or {}).get("delta")} for t in trades if t.get("p02")]
    exe = execution_net(ex)
    final = [{"id": r["id"], "orderId": r["order_id"], "symbol": r["symbol"], "secType": r["sec_type"], "side": r["side"], "qty": float(r["qty"]),
              "price": float(r["price"]), "commission": float(r["commission"] or 0.0), "tsMs": int(r["ts"].timestamp() * 1000)} for r in ex]
    red = reduce_session(snaps, execution_net=(exe["net"] if exe["complete"] else None), execution_fees=(exe["fees"] if exe["complete"] else None),
                         p02=p02, p06=p06, final_executions=final)
    sampled = None
    if eq:
        hi = max(eq, key=lambda r: r["equity"]); first = eq[0]
        sampled = {"samples": len(eq), "first": {"ts": first["ts"], "equity": first["equity"]}, "peak": {"ts": hi["ts"], "equity": hi["equity"]},
                   "last": {"ts": eq[-1]["ts"], "equity": eq[-1]["equity"]}, "peakMinusFirst": round(hi["equity"] - first["equity"], 4),
                   "basis": "persisted 30 s equity samples on the book's MARKS (option mid / share last) - displayed, not executable; samples can miss peaks"}
    return {"date": date, "book": EM_BOOK, "asOf": dt.datetime.now(dt.timezone.utc).isoformat(), "engineBuildAtSession": build_sha,
            "recorder": {"tablePresent": bool(has_table), "snapshots": len(snaps)}, "execution": exe, "displayedSampledEquity": sampled,
            "capture": red, "disputedEvidence": DISPUTED.get(date, []),
            "retrospective": "generated after the session; not knowledge that was available on the trading day"}


def render(d: dict) -> str:
    e, c, L = d["execution"], d["capture"], []
    L += [f"# EM executable-profit report - {d['date']}", "",
          f"Generated {d['asOf']} (retrospective; not knowledge available on the trading day). Book `{d['book']}`. Engine build recorded by the capture: `{d.get('engineBuildAtSession') or 'not recorded (no capture)'}`. "
          f"Reducer `{c.get('version')}`. Read-only.", "",
          "## 1. Realized (execution ledger - exact)", "",
          f"Net after commissions **{e['net']:+.4f}** on {e['fills']} fills; commissions {e['fees']:.2f}." + (f" OPEN at the cutoff (excluded): {', '.join(e['openAtCutoff'])}." if e["openAtCutoff"] else ""), "",
          "| Held symbol | Qty | Net | Fees |", "|---|---:|---:|---:|"]
    L += [f"| {k} | {v['qty']:g} | {v['net']:+.4f} | {v['fees']:.2f} |" for k, v in e["bySymbol"].items()] or ["| - | - | - | - |"]
    for x in d["disputedEvidence"]:
        L += ["", f"> DISPUTED EVIDENCE: {x}"]
    s = d["displayedSampledEquity"]
    L += ["", "## 2. Displayed (marks) - labelled, never executable", ""]
    L += ([f"{s['samples']} equity samples in the regular session: first {s['first']['equity']:.4f}, sampled peak {s['peak']['equity']:.4f} "
           f"({s['peakMinusFirst']:+.4f} vs first), last {s['last']['equity']:.4f}. Basis: {s['basis']}."] if s else ["No equity samples in the session window."])
    L += ["", "## 3. Covered executable liquidation estimate (ED-04 `book-snapshot-v1`)", ""]
    if c.get("status") != "ok":
        L += [f"**Unavailable: {c.get('status')}.** Recorder table present: {d['recorder']['tablePresent']}; snapshots for this session: {d['recorder']['snapshots']}. "
              "The ED-04 recorder did not run in this session (it is built default OFF and was not deployed), so no executable peak, giveback or coverage "
              "figure exists. Nothing is reconstructed from marks, candles or hindsight: the value is UNKNOWN, not zero."]
    else:
        cov = c["coverage"]
        L += [f"Snapshots {c['snapshots']} (scorable {cov['scorable']}, unscorable {cov['unscorable']}, ratio {cov['ratio']}); recorder drops {cov['recorderDrops']}; gaps {len(cov['gaps'])}.", "",
              "| Measure | Value | At |", "|---|---:|---|",
              f"| Realized net (final snapshot) | {c.get('realizedNetFinal')} | flat at end: {c.get('flatAtEnd')} |",
              f"| Peak displayed net | {(c.get('peakDisplayedNet') or {}).get('value')} | {(c.get('peakDisplayedNet') or {}).get('at')} |",
              f"| Peak executable net (scorable only) | {(c.get('peakExecutableNet') or {}).get('value')} | {(c.get('peakExecutableNet') or {}).get('at')} |",
              f"| Giveback vs executable peak | {c.get('givebackVsExecutablePeak')} | hypothetical estimate, not a fill |",
              f"| Displayed minus executable at that peak | {c.get('displayedMinusExecutableAtExecPeak')} | spread and depth haircut |",
              "", f"Unscorable reasons: {cov['unscorableReasons'] or 'none'}.", "",
              f"Reconciliation to the execution ledger: **{(c.get('reconciliation') or {}).get('status')}** (difference {(c.get('reconciliation') or {}).get('difference')})."]
        if c.get("attributionAtExecutablePeak"):
            L += ["", "| Position | Net at the executable peak | Final net | Giveback | Fees after the peak |", "|---|---:|---:|---:|---:|"]
            L += [f"| {a['symbol']} ({a['tradeInstance']}) | {a['netAtPeak']} | {a['finalNet']} | {a['giveback']} | {a['feesAfterPeak']} |" for a in c["attributionAtExecutablePeak"]]
    pe = c.get("pairedExits") or {}
    L += ["", "## 4. Paired-exit consumers (P-02 / P-06) joined to the book capture", ""]
    for k in ("p02", "p06"):
        v = pe.get(k)
        L += [f"- {k.upper()}: " + ("no per-trade rows for this session" if v is None else f"{v['total']} rows, {v['withBookContext']} with book context (strict trade identity and time; the rest stay unknown)")]
    L += ["", "Reproduce: `python -m zargar.tools.em_profit_capture report --date " + d["date"] + "` (read-only)."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("--date", required=True); r.add_argument("--stdout", action="store_true")
    a = ap.parse_args(argv)
    data = asyncio.run(build(a.date)); md = render(data)
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(data, open(os.path.join(OUT_DIR, f"{a.date}.json"), "w", encoding="utf-8"), indent=1, default=str)
    open(os.path.join(OUT_DIR, f"{a.date}.md"), "w", encoding="utf-8", newline="\n").write(md)
    print(md if a.stdout else f"wrote {OUT_DIR}/{a.date}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
