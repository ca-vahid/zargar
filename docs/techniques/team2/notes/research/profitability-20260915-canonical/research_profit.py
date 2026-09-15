"""Controlled profitability comparisons on the canonical tape (2026-09-15, other team's GO):
  (1) C1 conjunction vs baseline, (2) sizing map: size_full 0.5 vs baseline (entries/exits identical).
Every metric on the SAME eligible sample (paired symbol-sessions), after-cost $ P&L at the $600/full-unit research
scale through the existing chronological book (one position desk-wide, two losses end the day), drawdown, exposure,
by date / by symbol, remove-best-day, and a worse-fills rerun (slippage_ticks 2 instead of 1)."""
import asyncio, json, os, sys
from collections import defaultdict
from types import SimpleNamespace
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "..", "backend"))   # the repo backend
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from zargar.bus import Bus
from zargar.config import get_config
from zargar.db import make_engine, make_session_factory
from zargar.events import Journal
from zargar.settings_service import SettingsService
from zargar.techniques.team2.service import Team2Service, paired_rows, summarize_rows
from zargar.tools.team2_c2_report import book_sim, classify, by_symbol, UNIT

START, END, SYMS, SPLIT = "2026-08-20", "2026-09-11", ["SPY", "QQQ", "IWM"], "2026-09-08"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comparisons.json")
ARMS = [("baseline", {}), ("C1", {"no_trade_zone": "conjunction"}), ("size_half", {"size_full": 0.5}),
        ("baseline_slip2", {"slippage_ticks": 2}), ("C1_slip2", {"no_trade_zone": "conjunction", "slippage_ticks": 2}),
        ("size_half_slip2", {"size_full": 0.5, "slippage_ticks": 2}),
        ("C1+size_half", {"no_trade_zone": "conjunction", "size_full": 0.5})]     # reported only as context, not a candidate


def book_detail(rows):
    """book_sim plus the exposure and robustness figures the review asked for."""
    b = book_sim(rows)
    trades = sorted([(r["date"], r["symbol"], t) for r in rows for t in (r.get("trades") or [])], key=lambda x: (x[2]["entryTs"], x[1]))
    open_until = 0; losses = defaultdict(int); taken = []
    for d, sym, t in trades:
        if t["entryTs"] < open_until or losses[d] >= 2:
            continue
        pnl = t["pnlPct"] / 100.0 * float(t.get("sizeMult") or 1.0) * UNIT
        taken.append((d, sym, t, pnl)); open_until = t["exitTs"]
        if pnl < 0:
            losses[d] += 1
    wins = [p for *_, p in taken if p > 0]; loss = [p for *_, p in taken if p < 0]
    by_date = b["byDate"]
    best_day = max(by_date, key=by_date.get) if by_date else None
    by_sym = defaultdict(float); by_size = defaultdict(lambda: [0, 0.0])
    for d, sym, t, pnl in taken:
        by_sym[sym] += pnl
        k = "full(1.0)" if float(t.get("sizeMult") or 1.0) >= 0.999 else f"x{float(t.get('sizeMult') or 1.0):.2f}"
        by_size[k][0] += 1; by_size[k][1] += pnl
    return {**b, "grossWins": round(sum(wins), 0), "grossLosses": round(sum(loss), 0),
            "profitFactor": round(sum(wins) / -sum(loss), 2) if loss else None,
            "unitsDeployed": round(sum(float(t.get("sizeMult") or 1.0) for *_, t, _ in taken), 2),
            "fullUnitTrades": sum(1 for *_, t, _ in taken if float(t.get("sizeMult") or 1.0) >= 0.999),
            "premiumAtRiskMax$": round(max((float(t.get("sizeMult") or 1.0) * UNIT for *_, t, _ in taken), default=0), 0),
            "bestDay": best_day, "totalWithoutBestDay": round(b["total"] - by_date.get(best_day, 0), 0) if best_day else b["total"],
            "bySymbol$": {k: round(v, 0) for k, v in sorted(by_sym.items())},
            "bySize": {k: {"trades": v[0], "pnl$": round(v[1], 0)} for k, v in sorted(by_size.items())},
            "earlier$": round(sum(v for k, v in by_date.items() if k < SPLIT), 0),
            "week37$": round(sum(v for k, v in by_date.items() if k >= SPLIT), 0),
            "takenTrades": [{"date": d, "symbol": sym, "setup": t["setup"], "entryKind": t.get("entryKind"), "sizeMult": t.get("sizeMult"),
                             "bucket": t.get("bucket"), "pnlPct": round(t["pnlPct"], 1), "pnl$": round(pnl, 0), "exit": t.get("exitReason", "")[:40]}
                            for d, sym, t, pnl in taken]}


def incremental_without_best(base, var):
    """The variant's advantage with the date that contributes MOST to the advantage removed."""
    diff = {d: var["byDate"].get(d, 0) - base["byDate"].get(d, 0) for d in set(base["byDate"]) | set(var["byDate"])}
    if not diff:
        return None
    best = max(diff, key=diff.get)
    return {"bestIncrementalDate": best, "itsContribution": round(diff[best], 0),
            "advantageWithoutIt": round(var["total"] - base["total"] - diff[best], 0)}


async def main():
    cfg = get_config(); eng = make_engine(cfg.database_url); sf = make_session_factory(eng); bus = Bus()
    settings = SettingsService(sf, bus, Journal(sf, bus)); await settings.load()
    svc = Team2Service(SimpleNamespace(settings=settings, sf=sf), None)
    sweeps = {}
    for label, ov in ARMS:
        sweeps[label] = await svc.sweep(START, END, symbols=SYMS, overrides=ov or None)
        print(f"swept {label}: dataset {sweeps[label]['datasetVersion'][:16]} rows {len(sweeps[label]['rows'])} trades {sweeps[label]['summary']['trades']}", flush=True)
    labels = [a[0] for a in ARMS]
    aligned, dropped = paired_rows(*[sweeps[l] for l in labels])
    rows = dict(zip(labels, aligned))
    print(f"\nELIGIBLE SAMPLE: {len(aligned[0])} symbol-sessions common to all arms; dropped {len(dropped)}: {dropped[:6]}")
    res = {"sample": {"start": START, "end": END, "symbols": SYMS, "eligibleCells": len(aligned[0]), "dropped": dropped,
                      "datasetVersion": sweeps["baseline"]["datasetVersion"], "unit$": UNIT, "split": SPLIT},
           "arms": {}}
    for l in labels:
        m = summarize_rows(rows[l]); b = book_detail(rows[l])
        res["arms"][l] = {"overrides": dict(ARMS[labels.index(l)][1]), "model": {**m, "bySymbol": by_symbol(rows[l])}, "book": b}
        print(f"\n== {l:16s} model trades={m['trades']} wr={m['winRate']} pnl%={m['pnlPctSum']} | BOOK taken={b['taken']} total=${b['total']} "
              f"PF={b['profitFactor']} mdd=${b['maxDrawdown']} worst=${b['worstDay']} best={b['bestDay']}(${b['byDate'].get(b['bestDay'],0)}) "
              f"noBest=${b['totalWithoutBestDay']} earlier=${b['earlier$']} wk37=${b['week37$']} min={b['minutesInMarket']} units={b['unitsDeployed']} "
              f"fullTrades={b['fullUnitTrades']} maxRisk=${b['premiumAtRiskMax$']}")
        print(f"   by symbol $ {b['bySymbol$']} | by size {b['bySize']}")
        print(f"   by date $ {b['byDate']}")
    for var, base in (("C1", "baseline"), ("size_half", "baseline"), ("C1_slip2", "baseline_slip2"), ("size_half_slip2", "baseline_slip2"), ("C1+size_half", "baseline")):
        c = classify(rows[base], rows[var]); bb, vb = res["arms"][base]["book"], res["arms"][var]["book"]
        inc = incremental_without_best(bb, vb)
        res["arms"][var]["vsBase"] = {"base": base, "bookDelta$": round(vb["total"] - bb["total"], 0), "mddDelta$": round(vb["maxDrawdown"] - bb["maxDrawdown"], 0),
                                      "matched": {k: (v if isinstance(v, (int, float)) else len(v)) for k, v in c.items() if k != "sums"}, "sums": c["sums"],
                                      "incremental": inc}
        print(f"\n-- {var} vs {base}: book {vb['total']-bb['total']:+.0f}$ (mdd {vb['maxDrawdown']-bb['maxDrawdown']:+.0f}$) | matched: unchanged={c['unchanged']} "
              f"changedExit={len(c['changedExit'])} displaced={len(c['displaced'])} new={len(c['new'])} lost={len(c['lost'])} sums={c['sums']} | {inc}")
    json.dump(res, open(OUT, "w"), indent=1, default=str)
    print("\nwritten", OUT)


asyncio.run(main())
