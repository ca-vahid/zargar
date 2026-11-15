"""Tips source track record from the archive (2026-10-12): every recorded OPENING tip replayed on price history.

Read-only and rule-based: no model judges anything here, so the result cannot be bent by a model that knows what
happened next. Each actionable `open` signal is replayed through `techniques/tip/replay.py` on the UNDERLYING's 1h
bars - the "armed" book (the real plan builder + walk-forward simulator: wait for the level) and the "immediate"
book (buy the tip-time price, the tip's own stop/target else a time exit). Per source and book: the count, hit
rate, mean R after a cost allowance, the same shrunk grade the live source grade uses (`sizing.grade_source`) and
a DATE-CLUSTERED bootstrap interval (tips of one day rise and fall together - a per-tip interval is too narrow).
The analyst's verdict at tip time (take / skip / watch), recorded live, splits the same record.

What this is NOT: fills. Option tips are scored as a move in the underlying (direction only); 1h bars cannot
order a stop and a target inside one bar; an alert the source deleted before we mirrored it is not here (the
record flatters a room that deletes its losers); an unresolved tip (horizon not over) is left out.

Usage (cwd = the runtime's backend/ for .env; PYTHONPATH = the checkout that holds this file):
  python -m zargar.tools.tip_source_replay [--since 2026-08-28] [--cost-pct 0.3] [--json out.json] [--md out.md]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import random
from zoneinfo import ZoneInfo

VERSION = "tip-source-replay-v1"
ET = ZoneInfo("America/New_York")
LOOKBACK_MS = 46 * 86_400_000


def J(v):
    return (json.loads(v) if isinstance(v, str) else v) or {}


def stated_ms(extraction: dict, created_at: dt.datetime) -> int:
    v = extraction.get("statedAt")
    if isinstance(v, (int, float)) and v > 0:
        return int(v if v > 1e11 else v * 1000)
    if isinstance(v, str) and v:
        try:
            d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return int(d.timestamp() * 1000)
        except ValueError:
            pass
    return int(created_at.timestamp() * 1000)


def cost_r(cost_pct: float, entry: float | None, stop: float | None) -> float | None:
    """The round-trip cost allowance (% of the entry price) in R of this plan."""
    if not entry or not stop or abs(entry - stop) <= 0:
        return None
    return (cost_pct / 100.0) * entry / abs(entry - stop)


def clustered_interval(rows: list[tuple[str, float]], *, draws: int = 2000, seed: int = 7) -> tuple[float, float] | None:
    """90% bootstrap interval of the mean, resampling whole ET DAYS. None below 5 days."""
    by_day: dict[str, list[float]] = {}
    for day, r in rows:
        by_day.setdefault(day, []).append(r)
    days = list(by_day)
    if len(days) < 5:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        xs = [x for d in (rng.choice(days) for _ in days) for x in by_day[d]]
        means.append(sum(xs) / len(xs))
    means.sort()
    return round(means[int(0.05 * draws)], 3), round(means[int(0.95 * draws) - 1], 3)


def summarize(rows: list[tuple[str, float]], *, min_n: int, k: float) -> dict:
    from ..techniques.tip.sizing import grade_source
    g = grade_source([r for _d, r in rows], min_n=min_n, k=k, fraction=0.25)
    ci = clustered_interval(rows)
    verdict = "not enough"
    if g["n"] >= min_n and ci is not None:
        verdict = "promising" if ci[0] > 0 else ("negative" if ci[1] < 0 else "no edge shown")
    return {"n": g["n"], "days": len({d for d, _ in rows}), "hitRate": g.get("hitRate"), "meanR": g.get("meanR"),
            "shrunkEdge": g.get("shrunkEdge"), "ci90": ci, "verdict": verdict}


async def run(args) -> dict:
    import asyncpg

    from ..config import get_config
    from ..marketstructure.history import fetch_window
    from ..techniques.tip.replay import replay_tip
    cfg = get_config()
    dsn = str(cfg.database_url).replace("postgresql+asyncpg://", "postgresql://")
    since = dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.timezone.utc)
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction(readonly=True):
            recs = await conn.fetch(
                """select id, source_name, ticker, direction, instrument, entry_price, target_price, stop_price,
                          horizon_sessions, extraction, created_at
                   from signals where is_actionable and action = 'open' and created_at >= $1
                     and not (extraction ? 'experiment') order by created_at""", since)
    finally:
        await conn.close()
    tips, seen = [], set()
    for r in recs:
        ex = J(r["extraction"])
        ms = stated_ms(ex, r["created_at"])
        day = dt.datetime.fromtimestamp(ms / 1000, ET).date().isoformat()
        key = (r["source_name"], r["ticker"], r["direction"], day)
        if key in seen or not r["ticker"] or r["direction"] not in ("long", "short"):
            continue
        seen.add(key)
        tips.append({"id": r["id"], "source": r["source_name"] or "unknown", "symbol": str(r["ticker"]).upper(),
                     "direction": r["direction"], "instrument": r["instrument"], "ms": ms, "day": day,
                     "entry": r["entry_price"], "stop": r["stop_price"], "target": r["target_price"],
                     "horizon": int(r["horizon_sessions"] or 15),
                     "verdict": str((ex.get("analyst") or {}).get("verdict") or "none")})
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    first = {}
    for t in tips:
        first[t["symbol"]] = min(first.get(t["symbol"], t["ms"]), t["ms"])
    cache: dict[str, list] = {}
    sem = asyncio.Semaphore(4)

    async def load(sym: str) -> None:
        async with sem:
            try:
                cache[sym] = await fetch_window(sym, "1h", first[sym] - LOOKBACK_MS, now_ms)
            except Exception:                              # noqa: BLE001 - no history = the tip is unscored
                cache[sym] = []
    first["SPY"] = min(first.values()) if first else now_ms
    await asyncio.gather(*(load(s) for s in first))
    spy = cache.get("SPY") or []

    def spy_pct(ms: int, bars_held: int) -> float | None:
        """SPY's move over the same 1h bars the immediate book held (the market's share of the result)."""
        idx = [i for i, b in enumerate(spy) if b.ts <= ms]
        if not idx:
            return None
        i0 = idx[-1]
        i1 = min(i0 + max(1, bars_held), len(spy) - 1)
        return (float(spy[i1].close) / float(spy[i0].close) - 1.0) * 100.0

    async def cached(symbol, tf, start_ms, end_ms, **_kw):
        bars = [b for b in cache.get(symbol, []) if start_ms <= b.ts <= end_ms]
        if not bars:
            raise RuntimeError("no bars")
        return bars
    out_rows = []
    for t in tips:
        # a stated number far from the underlying's price is a PREMIUM (or a typo), not a level: replaying it as a
        # stop/target books a -99% exit. Such numbers are dropped and counted; the plan then builds from structure.
        past = [b for b in cache.get(t["symbol"], []) if b.ts <= t["ms"]]
        ref0 = float(past[-1].close) if past else None
        for k in ("entry", "stop", "target"):
            if ref0 and t[k] and not (0.5 * ref0 <= float(t[k]) <= 2.0 * ref0):
                t[k] = None
                t["droppedLevels"] = t.get("droppedLevels", 0) + 1
        res = await replay_tip(symbol=t["symbol"], direction=t["direction"], stated_at_ms=t["ms"],
                               tip_entry=t["entry"], tip_stop=t["stop"],
                               tip_targets=([t["target"]] if t["target"] else []), horizon_sessions=t["horizon"],
                               source=t["source"], fetch=cached)
        row = {**t, "ok": bool(res.get("ok")), "note": res.get("note")}
        if res.get("ok"):
            a, im = res["armed"], res["immediate"]
            c = cost_r(args.cost_pct, a.get("entry"), a.get("stop"))
            row["armedFilled"] = bool(a["filled"])
            row["armedResolved"] = bool(a["resolved"])
            row["armedConstructed"] = bool(a.get("constructed"))
            row["armedR"] = (round(float(a["rMultiple"]) - (c or 0.0), 4) if a["filled"] else None)
            resolved = not (im["reason"] == "horizon" and im["barsHeld"] < t["horizon"] * 7)
            net_pct = float(im["pnlPct"]) - args.cost_pct
            mkt = spy_pct(t["ms"], int(im["barsHeld"]))
            sgn = 1.0 if t["direction"] == "long" else -1.0
            row["immResolved"] = resolved
            row["immPct"] = round(net_pct, 3)
            row["immSpyPct"] = (round(mkt, 3) if mkt is not None else None)
            # the immediate book is judged in % of price MINUS the market's move over the same bars: an R against
            # the armed plan's stop is not meaningful (that stop belongs to another entry) and a rising tape
            # otherwise credits every long
            row["immExcessPct"] = (round(net_pct - sgn * mkt, 3) if mkt is not None else None)
        out_rows.append(row)

    def table(pred, label: str) -> dict:
        groups: dict[str, dict[str, list]] = {}
        for r in out_rows:
            if not r["ok"] or not pred(r):
                continue
            for name in (label_of(r, label), "ALL"):
                g = groups.setdefault(name, {"armed": [], "immediate": [], "tips": 0, "armedUnfilled": 0})
                g["tips"] += 1
                if r["armedResolved"] and r["armedFilled"] and r["armedR"] is not None and not r["armedConstructed"]:
                    g["armed"].append((r["day"], r["armedR"]))
                elif r["armedResolved"] and not r["armedFilled"]:
                    g["armedUnfilled"] += 1
                if r["immResolved"] and r["immExcessPct"] is not None:
                    g["immediate"].append((r["day"], r["immExcessPct"]))
        return {name: {"tips": g["tips"], "armedUnfilled": g["armedUnfilled"],
                       "armed": summarize(g["armed"], min_n=args.min_n, k=args.shrink_k),
                       "immediate": summarize(g["immediate"], min_n=args.min_n, k=args.shrink_k)}
                for name, g in sorted(groups.items(), key=lambda kv: -kv[1]["tips"])}

    def label_of(r, label):
        return r[label]
    return {"version": VERSION, "since": args.since, "costPct": args.cost_pct, "minN": args.min_n,
            "shrinkK": args.shrink_k, "signals": len(recs), "tips": len(tips),
            "scored": sum(1 for r in out_rows if r["ok"]),
            "unscored": sum(1 for r in out_rows if not r["ok"]),
            "tipsWithDroppedLevels": sum(1 for r in out_rows if r.get("droppedLevels")),
            "bySource": table(lambda r: True, "source"),
            "byAnalystVerdict": table(lambda r: True, "verdict"),
            "byInstrument": table(lambda r: True, "instrument"),
            "rows": out_rows}


def markdown(rep: dict) -> str:
    def block(title: str, tbl: dict) -> list[str]:
        ls = [f"## {title}", "", "| Group | Tips | Book | Scored | Days | Hit rate | Mean | Shrunk | 90% interval | Verdict |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for name, g in tbl.items():
            for book in ("immediate", "armed"):
                s = g[book]
                ci = f"{s['ci90'][0]:+.2f} to {s['ci90'][1]:+.2f}" if s["ci90"] else "-"
                hr = f"{s['hitRate'] * 100:.0f}%" if s["hitRate"] is not None else "-"
                mr = f"{s['meanR']:+.2f}" if s["meanR"] is not None else "-"
                se = f"{s['shrunkEdge']:+.2f}" if s["shrunkEdge"] is not None else "-"
                ls.append(f"| {name} | {g['tips']} | {book} | {s['n']} | {s['days']} | {hr} | {mr} | {se} | {ci} | {s['verdict']} |")
        return ls + [""]
    head = [f"# Tips source replay ({rep['version']})", "",
            f"Since {rep['since']}; {rep['signals']} opening signals, {rep['tips']} distinct tips "
            f"(one per source, name, side and day), {rep['scored']} scored, {rep['unscored']} without usable history. "
            f"Cost allowance {rep['costPct']}% of the entry price per round trip. A verdict needs {rep['minN']} scored tips "
            "and 5 days. The armed book is in R against the replay plan's stop; the immediate book is in % of price after "
            "cost MINUS SPY's move over the same bars. Results are the underlying's move, not option fills.", ""]
    return "\n".join(head + block("By source", rep["bySource"]) + block("By the analyst's verdict at tip time", rep["byAnalystVerdict"])
                     + block("By stated instrument", rep["byInstrument"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-28")
    ap.add_argument("--cost-pct", type=float, default=0.3)
    ap.add_argument("--min-n", type=int, default=20)
    ap.add_argument("--shrink-k", type=float, default=20.0)
    ap.add_argument("--json")
    ap.add_argument("--md")
    args = ap.parse_args()
    rep = asyncio.run(run(args))
    md = markdown(rep)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md)
    print(md.encode("ascii", "replace").decode())


if __name__ == "__main__":
    main()
