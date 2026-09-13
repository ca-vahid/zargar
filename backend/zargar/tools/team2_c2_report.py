"""C2 paired development report (spec v2 §3–§4, accepted by the other team 2026-09-13).

    cd backend
    .venv/bin/python -m zargar.tools.team2_c2_report --start 2026-08-20 --end 2026-09-11 [--symbols SPY,QQQ,IWM]
        [--definitions D1,D2,D3] [--out docs/techniques/team2/notes/research/c2-dev-report.json]

Runs the baseline and each definition IN-PROCESS on the banked (canonical, post-C6) tape, restricts EVERY reported
metric — trade counts, model sums, the chronological book simulation, drawdown, exposure, by-date/by-symbol tables,
the funnel — to the symbol-sessions eligible in every sweep (`Team2Service.paired_rows`), publishes the excluded
cells with reasons, classifies matched trades as new / displaced / changed-exit / lost, and applies the predeclared
acceptance gates (§4). The validation window (2026-09-14 → 2026-10-09) is SEALED: any requested date inside or after
it is refused unless `--validation-read --after 2026-10-09` is given explicitly (the one preregistered read).

Research tooling only: it changes no setting, arms nothing, writes nothing to the runtime DB except the dataset
version record every sweep already writes.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from collections import defaultdict
from types import SimpleNamespace

VALIDATION_START, VALIDATION_END = "2026-09-14", "2026-10-09"
UNIT = 600.0                     # $ per FULL-size position — a labelled scale, not the Practice book's sizing
GATE_BOOK_MIN_GAIN = 300.0       # §4.1
GATE_DD_MULT = 1.25              # §4.2
GATE_MIN_CHANGED = 6             # §4.3
GATE_SIMPLER_MARGIN = 600.0      # §4 verdict rule


def trade_key(sym: str, d: str, t: dict) -> tuple:
    return (sym, d, str(t.get("setup") or ""), str(t.get("entryTs") or ""), str(t.get("entryKind") or ""))


def trades_of(rows: list[dict]) -> dict:
    return {trade_key(r["symbol"], r["date"], t): t for r in rows for t in (r.get("trades") or [])}


def classify(base_rows: list[dict], var_rows: list[dict]) -> dict:
    """Matched trades (spec §5): shared unchanged, changed-exit (same entry, different exit/pnl), displaced (same
    setup kind + date + symbol, different entry), new, lost."""
    a, b = trades_of(base_rows), trades_of(var_rows)
    shared = [k for k in b if k in a]
    unchanged = [k for k in shared if round(a[k]["pnlPct"], 2) == round(b[k]["pnlPct"], 2) and a[k].get("exitTs") == b[k].get("exitTs")]
    changed_exit = [k for k in shared if k not in unchanged]
    only_b = [k for k in b if k not in a]
    only_a = [k for k in a if k not in b]
    def fam(k):
        return (k[0], k[1], k[2].split("@")[0])
    fams_a = {fam(k) for k in only_a}
    displaced = [k for k in only_b if fam(k) in fams_a]
    new = [k for k in only_b if k not in displaced]
    lost = [k for k in only_a if fam(k) not in {fam(k2) for k2 in displaced}]
    def rows_for(keys, src):
        return [{"symbol": k[0], "date": k[1], "setup": k[2], "entryTs": k[3], "kind": k[4], "pnlPct": src[k]["pnlPct"],
                 "bucket": src[k].get("bucket"), "keyLevel": src[k].get("keyLevel")} for k in keys]
    return {"unchanged": len(unchanged),
            "changedExit": [{**r, "pnlPctBefore": a[k]["pnlPct"]} for r, k in zip(rows_for(changed_exit, b), changed_exit)],
            "displaced": rows_for(displaced, b), "new": rows_for(new, b), "lost": rows_for(lost, a),
            "sums": {"changedExit": round(sum(b[k]["pnlPct"] - a[k]["pnlPct"] for k in changed_exit), 1),
                     "displaced": round(sum(b[k]["pnlPct"] for k in displaced), 1),
                     "new": round(sum(b[k]["pnlPct"] for k in new), 1), "lost": round(sum(a[k]["pnlPct"] for k in lost), 1)}}


def book_sim(rows: list[dict], unit: float = UNIT) -> dict:
    """Chronological across symbols: one open position at a time desk-wide, two losses end the day, $ = pnl% x sizeMult x unit."""
    trades = sorted([(r["date"], r["symbol"], t) for r in rows for t in (r.get("trades") or [])],
                    key=lambda x: (x[2]["entryTs"], x[1]))
    open_until = 0; losses = defaultdict(int); day_pnl = defaultdict(float); taken = 0; skip_c = skip_l = 0
    equity = peak = mdd = 0.0; minutes = 0
    for d, sym, t in trades:
        if t["entryTs"] < open_until:
            skip_c += 1; continue
        if losses[d] >= 2:
            skip_l += 1; continue
        pnl = t["pnlPct"] / 100.0 * float(t.get("sizeMult") or 1.0) * unit
        taken += 1; open_until = t["exitTs"]; day_pnl[d] += pnl; minutes += max(0, (t["exitTs"] - t["entryTs"]) // 60_000)
        if pnl < 0:
            losses[d] += 1
        equity += pnl; peak = max(peak, equity); mdd = min(mdd, equity - peak)
    return {"taken": taken, "skippedConcurrent": skip_c, "skippedLossCap": skip_l, "total": round(equity, 0),
            "maxDrawdown": round(mdd, 0), "worstDay": round(min(day_pnl.values()), 0) if day_pnl else 0.0,
            "bestDay": round(max(day_pnl.values()), 0) if day_pnl else 0.0, "minutesInMarket": minutes,
            "byDate": {k: round(v, 0) for k, v in sorted(day_pnl.items())}}


def by_symbol(rows: list[dict]) -> dict:
    out: dict = defaultdict(lambda: {"trades": 0, "pnlPctSum": 0.0})
    for r in rows:
        for t in r.get("trades") or []:
            out[r["symbol"]]["trades"] += 1; out[r["symbol"]]["pnlPctSum"] += t["pnlPct"]
    return {k: {"trades": v["trades"], "pnlPctSum": round(v["pnlPctSum"], 1)} for k, v in sorted(out.items())}


def funnel(rows: list[dict]) -> dict:
    tot: dict = defaultdict(int)
    for r in rows:
        for k, v in (r.get("keyLevels") or {}).items():
            if isinstance(v, int) and not isinstance(v, bool):
                tot[k] += v
    return dict(tot)


def gates(base: dict, var: dict, changed_entries: int, changed_cells_positive: int, changed_cells: int) -> dict:
    """§4 acceptance gates on one period."""
    g1 = var["book"]["total"] >= base["book"]["total"] + GATE_BOOK_MIN_GAIN and var["model"]["pnlPctSum"] >= base["model"]["pnlPctSum"]
    g2 = var["book"]["maxDrawdown"] >= base["book"]["maxDrawdown"] * GATE_DD_MULT and var["book"]["worstDay"] >= base["book"]["worstDay"] * GATE_DD_MULT
    g3 = changed_entries >= GATE_MIN_CHANGED
    g4 = changed_cells == 0 or changed_cells_positive * 2 >= changed_cells
    return {"g1_book_and_model": g1, "g2_drawdown": g2, "g3_exposure": g3, "g4_breadth": g4,
            "qualifies": g1 and g2 and g3 and g4, "insufficientExposure": not g3}


def seal_check(start: str, end: str, validation_read: bool, after: str | None) -> None:
    if end >= VALIDATION_START:
        if not validation_read:
            raise SystemExit(f"refused: {end} touches the sealed validation window {VALIDATION_START}..{VALIDATION_END}; "
                             f"development ends {dt.date.fromisoformat(VALIDATION_START) - dt.timedelta(days=1)}")
        today = dt.date.today().isoformat()
        if not after or today <= VALIDATION_END or after != VALIDATION_END:
            raise SystemExit(f"refused: the validation read is preregistered for after {VALIDATION_END} (pass --after {VALIDATION_END}); today is {today}")


async def run(args) -> dict:
    from ..bus import Bus
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..events import Journal
    from ..settings_service import SettingsService
    from ..techniques.team2.service import Team2Service, paired_rows, summarize_rows
    cfg = get_config(); eng = make_engine(cfg.database_url); sf = make_session_factory(eng); bus = Bus()
    settings = SettingsService(sf, bus, Journal(sf, bus)); await settings.load()
    svc = Team2Service(SimpleNamespace(settings=settings, sf=sf), None)
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    defs = [d.strip().upper() for d in args.definitions.split(",")]
    sweeps = {"baseline": await svc.sweep(args.start, args.end, symbols=symbols)}
    for d in defs:
        sweeps[d] = await svc.sweep(args.start, args.end, symbols=symbols, overrides={"key_levels": d})
    hashes = {k: v.get("datasetVersion") for k, v in sweeps.items()}
    if len(set(hashes.values())) != 1:
        raise SystemExit(f"refused: the sweeps did not consume one dataset: {hashes}")
    names = list(sweeps)
    aligned, dropped = paired_rows(*[sweeps[n] for n in names])
    rows_by = dict(zip(names, aligned))
    report = {"start": args.start, "end": args.end, "symbols": symbols, "datasetVersion": hashes["baseline"],
              "codeVersion": sweeps["baseline"]["summary"].get("codeVersion"), "unitDollars": UNIT,
              "commonSample": {"symbolSessions": len(rows_by["baseline"]), "dropped": dropped},
              "variants": {}}
    base_rows = rows_by["baseline"]
    base = {"model": summarize_rows(base_rows), "book": book_sim(base_rows), "bySymbol": by_symbol(base_rows)}
    report["variants"]["baseline"] = base
    for d in defs:
        rows = rows_by[d]
        cls = classify(base_rows, rows)
        changed_keys = {(r["symbol"], r["date"]) for r in cls["new"] + cls["displaced"] + cls["changedExit"] + cls["lost"]}
        cell_delta = defaultdict(float)
        for r in cls["new"] + cls["displaced"]:
            cell_delta[(r["symbol"], r["date"])] += r["pnlPct"]
        for r in cls["changedExit"]:
            cell_delta[(r["symbol"], r["date"])] += r["pnlPct"] - r["pnlPctBefore"]
        for r in cls["lost"]:
            cell_delta[(r["symbol"], r["date"])] -= r["pnlPct"]
        var = {"model": summarize_rows(rows), "book": book_sim(rows), "bySymbol": by_symbol(rows), "matched": cls,
               "funnel": funnel(rows), "changedCells": sorted([list(k) for k in changed_keys])}
        var["gates"] = gates(base, var, len(cls["new"]) + len(cls["displaced"]),
                             sum(1 for v in cell_delta.values() if v > 0), len(cell_delta))
        report["variants"][d] = var
    # verdict rule (§4): simplest qualifying wins unless a more complex one beats it by the margin at book level
    quals = [d for d in defs if report["variants"][d]["gates"]["qualifies"]]
    pick = None
    for d in quals:
        if pick is None or report["variants"][d]["book"]["total"] >= report["variants"][pick]["book"]["total"] + GATE_SIMPLER_MARGIN:
            pick = d
    report["developmentCandidate"] = pick
    report["note"] = ("development period only; the validation window is sealed and read once after " + VALIDATION_END
                      if not args.validation_read else "PREREGISTERED VALIDATION READ")
    await eng.dispose()
    return report


def print_report(rep: dict) -> None:
    print(f"C2 paired report {rep['start']} -> {rep['end']}  dataset {str(rep['datasetVersion'])[:12]}  code {rep['codeVersion']}")
    cs = rep["commonSample"]
    print(f"  common eligible symbol-sessions: {cs['symbolSessions']}   dropped: {len(cs['dropped'])}")
    for d in cs["dropped"]:
        print(f"    - {d['symbol']} {d['date']}: {'; '.join(d['reasons'])}")
    b = rep["variants"]["baseline"]
    print(f"  baseline: trades {b['model']['trades']} wr {b['model']['winRate']} sum {b['model']['pnlPctSum']} | book ${b['book']['total']:.0f} "
          f"mdd ${b['book']['maxDrawdown']:.0f} worst ${b['book']['worstDay']:.0f} minutes {b['book']['minutesInMarket']}")
    for k, v in rep["variants"].items():
        if k == "baseline":
            continue
        m = v["matched"]; g = v["gates"]
        print(f"  {k}: trades {v['model']['trades']} wr {v['model']['winRate']} sum {v['model']['pnlPctSum']} | book ${v['book']['total']:.0f} "
              f"mdd ${v['book']['maxDrawdown']:.0f} worst ${v['book']['worstDay']:.0f} minutes {v['book']['minutesInMarket']}")
        print(f"      matched: unchanged {m['unchanged']}  new {len(m['new'])} ({m['sums']['new']})  displaced {len(m['displaced'])} "
              f"({m['sums']['displaced']})  changed-exit {len(m['changedExit'])} ({m['sums']['changedExit']})  lost {len(m['lost'])} ({m['sums']['lost']})")
        print(f"      funnel: {v['funnel']}")
        print(f"      gates: {g}")
    print(f"  development candidate: {rep['developmentCandidate']}   ({rep['note']})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="C2 paired development report (research tooling)")
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--symbols", default="SPY,QQQ,IWM"); ap.add_argument("--definitions", default="D1,D2,D3")
    ap.add_argument("--out", default=None)
    ap.add_argument("--validation-read", action="store_true", help="the ONE preregistered validation read (after the window)")
    ap.add_argument("--after", default=None)
    args = ap.parse_args(argv)
    seal_check(args.start, args.end, args.validation_read, args.after)
    rep = asyncio.run(run(args))
    print_report(rep)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
        print("  written", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
