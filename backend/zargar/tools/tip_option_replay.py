"""Tips option record from the archive (2026-10-12): every recorded OPTION tip priced on the contract's own trades.

The companion of `tip_source_replay` (which scores the underlying's move). Read-only and rule-based: no model judges
anything. Each actionable `open` signal that names a contract (strike + side, expiry stated or identified by the
stated premium) is priced on Alpaca's 1-minute OPTION bars (built from real prints): the entry is the first minute
that STARTS after the tip, and three fixed exit rules run on the same minutes for every tip - so the analyst's
take / skip / watch split measures its SELECTION, not its exits:

  hold      no stop, sold at the close of the tip's horizon (stated sessions, else 3), never past expiry
  bracket   stop -50% / target +100% of the premium, else the same time exit
  scalp     stop -30% / target +30%, flat at the entry day's close

Results are % of the premium paid after a per-share cost allowance (slippage + fees, both legs), which is what a
fixed budget per tip earns. Date-clustered bootstrap intervals, as in the source replay.

What this is NOT: fills. Prints are not quotes (the entry may sit anywhere inside the spread; the allowance stands
in for that); a stop and a target inside one minute are read stop-first; a time exit ON the expiry day settles at
intrinsic value off the underlying's last 1h close; a tip with no print within 30 minutes is unscored; index
options (SPX) are not in the feed; deleted alerts are not here.

Usage (cwd = this checkout's backend/, runtime .env loaded into the environment):
  python -m zargar.tools.tip_option_replay [--since 2026-08-28] [--opt-cost 0.08] [--json out.json] [--md out.md]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import statistics
from zoneinfo import ZoneInfo

from .tip_source_replay import J, clustered_interval, stated_ms

VERSION = "tip-option-replay-v1"
ET = ZoneInfo("America/New_York")
BARS_URL = "https://data.alpaca.markets/v1beta1/options/bars"
MIN = 60_000
ENTRY_WINDOW_MS = 30 * MIN
DEFAULT_HORIZON = 3
VARIANTS = {"hold": (None, None, False), "bracket": (50.0, 100.0, False), "scalp": (30.0, 30.0, True)}


def alpaca_symbol(root: str, expiry: dt.date, right: str, strike: float) -> str:
    return f"{root.replace('.', '')}{expiry:%y%m%d}{right}{int(round(strike * 1000)):08d}"


def parse_day(v) -> dt.date | None:
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def add_sessions(day: dt.date, n: int) -> dt.date:
    """`n` weekdays after `day` (holidays are not skipped: a holiday only makes the window one session short)."""
    d = day
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def et_of(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000, ET)


def in_session(ms: int) -> bool:
    t = et_of(ms)
    return t.weekday() < 5 and dt.time(9, 30) <= t.time() < dt.time(16, 0)


def pick_entry(bars: list[dict], ms: int) -> dict | None:
    """The first minute that starts after the tip: within 30 minutes, or (a tip outside the session) inside the
    first 30 minutes of a session at most four days later."""
    for b in bars:
        if b["ts"] < ms:
            continue
        if b["ts"] - ms <= ENTRY_WINDOW_MS:
            return b
        t = et_of(b["ts"])
        if not in_session(ms) and t.time() < dt.time(10, 0) and (t.date() - et_of(ms).date()).days <= 4:
            return b
        return None
    return None


def run_variant(entry: dict, path: list[dict], *, stop_pct: float | None, target_pct: float | None,
                same_day: bool, settle: float | None) -> tuple[float, str]:
    """(exit price, reason) for one fixed exit rule over the minutes after the entry."""
    px = float(entry["px"])
    stop = px * (1 - stop_pct / 100.0) if stop_pct else None
    target = px * (1 + target_pct / 100.0) if target_pct else None
    day0 = et_of(entry["ts"]).date()
    last = px
    for b in path:
        if same_day and et_of(b["ts"]).date() != day0:
            return last, "day_close"
        if stop is not None and b["l"] <= stop:
            return min(stop, b["o"]), "stop"
        if target is not None and b["h"] >= target:
            return max(target, b["o"]), "target"
        last = b["c"]
    if same_day:
        return last, "day_close"
    if settle is not None:
        return settle, "expiry"
    return last, "horizon"


def summarize(rows: list[tuple[str, float]], *, min_n: int) -> dict:
    xs = [r for _d, r in rows]
    ci = clustered_interval(rows)
    verdict = "not enough"
    if len(xs) >= min_n and ci is not None:
        verdict = "promising" if ci[0] > 0 else ("negative" if ci[1] < 0 else "no edge shown")
    return {"n": len(xs), "days": len({d for d, _ in rows}),
            "hitRate": (round(sum(1 for x in xs if x > 0) / len(xs), 3) if xs else None),
            "meanPct": (round(sum(xs) / len(xs), 2) if xs else None),
            "medianPct": (round(statistics.median(xs), 2) if xs else None), "ci90": ci, "verdict": verdict}


async def run(args) -> dict:
    import asyncpg
    import httpx

    from ..config import get_config
    from ..marketstructure.history import fetch_window
    from ..options import occ as occ_mod
    cfg = get_config()
    if not cfg.alpaca_key_id or not cfg.alpaca_secret:
        raise SystemExit("Alpaca credentials are not configured")
    headers = {"APCA-API-KEY-ID": cfg.alpaca_key_id, "APCA-API-SECRET-KEY": cfg.alpaca_secret}
    dsn = str(cfg.database_url).replace("postgresql+asyncpg://", "postgresql://")
    since = dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.timezone.utc)
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction(readonly=True):
            recs = await conn.fetch(
                """select id, source_name, ticker, direction, instrument, strike, expiry, premium, horizon_sessions,
                          extraction, created_at
                   from signals where is_actionable and action = 'open' and created_at >= $1
                     and not (extraction ? 'experiment') order by created_at""", since)
    finally:
        await conn.close()
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    tips, seen = [], set()
    for r in recs:
        ex = J(r["extraction"])
        an = ex.get("analyst") or {}
        ms = stated_ms(ex, r["created_at"])
        day = et_of(ms).date()
        key = (r["source_name"], r["ticker"], r["direction"], day)
        if key in seen or not r["ticker"]:
            continue
        seen.add(key)
        root = str(r["ticker"]).upper()
        right = {"call": "C", "put": "P"}.get(str(r["instrument"] or ""))
        strike, expiry = r["strike"], parse_day(r["expiry"])
        if not (right and strike and expiry):
            o = occ_mod.parse_loose(an.get("contract"), float(strike) if strike else None)
            if o is not None and o.underlying.replace(".", "") == root.replace(".", "") and not (right and strike):
                right, strike, expiry = o.right, o.strike, o.expiry
            elif o is not None and right == o.right and strike and abs(o.strike - float(strike)) < 1e-6:
                expiry = o.expiry
        tips.append({"id": r["id"], "source": r["source_name"] or "unknown", "symbol": root, "ms": ms,
                     "day": day.isoformat(), "right": right, "strike": (float(strike) if strike else None),
                     "expiry": expiry, "premium": (float(r["premium"]) if r["premium"] else None),
                     "horizon": int(r["horizon_sessions"] or DEFAULT_HORIZON),
                     "verdict": str(an.get("verdict") or "none"), "instrument": r["instrument"]})

    sem = asyncio.Semaphore(4)
    http = httpx.AsyncClient(timeout=60)

    async def bars(sym: str, start_ms: int, end_ms: int) -> list[dict]:
        out, token = [], None
        end_ms = min(end_ms, now_ms - 16 * MIN)
        if end_ms <= start_ms:
            return out
        iso = lambda v: dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        async with sem:
            for _ in range(20):
                params = {"symbols": sym, "timeframe": "1Min", "start": iso(start_ms), "end": iso(end_ms), "limit": 10_000}
                if token:
                    params["page_token"] = token
                for attempt in range(5):
                    resp = await http.get(BARS_URL, params=params, headers=headers)
                    if resp.status_code != 429:
                        break
                    await asyncio.sleep(2 + 2 * attempt)
                if resp.status_code >= 400:
                    raise RuntimeError(f"Alpaca options/bars HTTP {resp.status_code}: {resp.text[:120]}")
                data = resp.json()
                for b in (data.get("bars") or {}).get(sym) or []:
                    ts = int(dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp() * 1000)
                    out.append({"ts": ts, "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]),
                                "c": float(b["c"]), "px": float(b.get("vw") or b["c"]), "v": b.get("v")})
                token = data.get("next_page_token")
                if not token:
                    break
        return out

    under: dict[str, list] = {}

    async def underlying_close(sym: str, day: dt.date) -> float | None:
        if sym not in under:
            try:
                under[sym] = await fetch_window(sym, "1h", int(since.timestamp() * 1000), now_ms)
            except Exception:                              # noqa: BLE001 - no history = no settlement value
                under[sym] = []
        xs = [b for b in under[sym] if et_of(b.ts).date() == day]
        return float(xs[-1].close) if xs else None

    async def score(t: dict) -> dict:
        row = {**t, "expiry": (t["expiry"].isoformat() if t["expiry"] else None), "ok": False}
        if not t["right"] or not t["strike"]:
            return {**row, "note": "no contract named"}
        day = dt.date.fromisoformat(t["day"])
        expiry, inferred = t["expiry"], False
        try:
            if expiry is None:
                if not t["premium"]:
                    return {**row, "note": "no expiry and no premium to identify it"}
                cands = sorted({add_sessions(day, i) for i in range(0, 6)}
                               | {day + dt.timedelta(days=(4 - day.weekday()) % 7 + 7 * w) for w in range(0, 5)})
                best = None
                for c in cands:
                    probe = await bars(alpaca_symbol(t["symbol"], c, t["right"], t["strike"]), t["ms"], t["ms"] + 3 * ENTRY_WINDOW_MS)
                    e = pick_entry(probe, t["ms"])
                    if e is None:
                        continue
                    miss = abs(e["px"] / t["premium"] - 1.0)
                    if miss <= 0.30 and (best is None or miss < best[0]):
                        best = (miss, c)
                if best is None:
                    return {**row, "note": "expiry not identified by the stated premium"}
                expiry, inferred = best[1], True
            if expiry < day:
                return {**row, "note": "stated expiry is before the tip"}
            sym = alpaca_symbol(t["symbol"], expiry, t["right"], t["strike"])
            end_day = min(expiry, add_sessions(day, max(1, t["horizon"]) - 1))
            end_ms = int(dt.datetime.combine(end_day, dt.time(16, 15), ET).timestamp() * 1000)
            series = await bars(sym, t["ms"], end_ms)
        except Exception as e:                              # noqa: BLE001 - a feed error leaves the tip unscored
            return {**row, "note": f"feed error: {str(e)[:80]}"}
        entry = pick_entry(series, t["ms"])
        if entry is None:
            return {**row, "contract": sym, "note": "no print within 30 minutes of the tip"}
        resolved = end_ms <= now_ms - 16 * MIN
        path = [b for b in series if b["ts"] > entry["ts"]]
        settle = None
        if end_day == expiry and resolved:
            s = await underlying_close(t["symbol"], expiry)
            if s is not None:
                settle = max(0.0, (s - t["strike"]) if t["right"] == "C" else (t["strike"] - s))
        px = float(entry["px"])
        row.update({"ok": True, "contract": sym, "expiry": expiry.isoformat(), "expiryInferred": inferred,
                    "entryPx": round(px, 4), "entryDelayS": int((entry["ts"] - t["ms"]) / 1000),
                    "vsStatedPct": (round((px / t["premium"] - 1) * 100, 1) if t["premium"] else None),
                    "resolved": resolved,
                    "mfePct": round((max([b["h"] for b in path], default=px) / px - 1) * 100, 1),
                    "maePct": round((min([b["l"] for b in path], default=px) / px - 1) * 100, 1)})
        for name, (stop_pct, target_pct, same_day) in VARIANTS.items():
            exit_px, reason = run_variant(entry, path, stop_pct=stop_pct, target_pct=target_pct, same_day=same_day,
                                          settle=settle)
            done = resolved or reason in ("stop", "target") or (same_day and et_of(entry["ts"]).date() < et_of(now_ms).date())
            row[name] = {"exitPx": round(exit_px, 4), "reason": reason, "resolved": done,
                         "grossPct": round((exit_px / px - 1) * 100, 2),
                         "netPct": round((exit_px - px - args.opt_cost) / px * 100, 2)}
        return row

    try:
        out_rows = await asyncio.gather(*(score(t) for t in tips))
    finally:
        await http.aclose()

    def table(label) -> dict:
        groups: dict[str, dict] = {}
        for r in out_rows:
            if r["right"] is None and r["instrument"] not in ("call", "put"):
                continue
            for name in (label(r), "ALL"):
                g = groups.setdefault(name, {"tips": 0, "scored": 0, **{v: [] for v in VARIANTS}})
                g["tips"] += 1
                if not r["ok"]:
                    continue
                g["scored"] += 1
                for v in VARIANTS:
                    if r[v]["resolved"]:
                        g[v].append((r["day"], r[v]["netPct"]))
        return {name: {"tips": g["tips"], "scored": g["scored"],
                       **{v: summarize(g[v], min_n=args.min_n) for v in VARIANTS}}
                for name, g in sorted(groups.items(), key=lambda kv: -kv[1]["tips"])}
    notes: dict[str, int] = {}
    for r in out_rows:
        if not r["ok"]:
            n = str(r.get("note") or "").split(":")[0]
            notes[n] = notes.get(n, 0) + 1
    return {"version": VERSION, "since": args.since, "optCost": args.opt_cost, "minN": args.min_n,
            "signals": len(recs), "tips": len(tips), "scored": sum(1 for r in out_rows if r["ok"]),
            "expiryInferred": sum(1 for r in out_rows if r.get("expiryInferred")), "unscored": notes,
            "bySource": table(lambda r: r["source"]), "byAnalystVerdict": table(lambda r: r["verdict"]),
            "bySourceAndVerdict": table(lambda r: f"{r['source']} / {r['verdict']}"), "rows": out_rows}


def markdown(rep: dict) -> str:
    def block(title: str, tbl: dict, floor: int = 0) -> list[str]:
        ls = [f"## {title}", "", "| Group | Option tips | Scored | Rule | Counted | Days | Winners | Mean | Median | 90% interval of the mean | Verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, g in tbl.items():
            if g["scored"] < floor:
                continue
            for v in VARIANTS:
                s = g[v]
                ci = f"{s['ci90'][0]:+.1f}% to {s['ci90'][1]:+.1f}%" if s["ci90"] else "-"
                hr = f"{s['hitRate'] * 100:.0f}%" if s["hitRate"] is not None else "-"
                mean = f"{s['meanPct']:+.1f}%" if s["meanPct"] is not None else "-"
                med = f"{s['medianPct']:+.1f}%" if s["medianPct"] is not None else "-"
                ls.append(f"| {name} | {g['tips']} | {g['scored']} | {v} | {s['n']} | {s['days']} | {hr} | {mean} | {med} | {ci} | {s['verdict']} |")
        return ls + [""]
    un = "; ".join(f"{n} {k}" for k, n in sorted(rep["unscored"].items(), key=lambda kv: -kv[1])) or "none"
    head = [f"# Tips option replay ({rep['version']})", "",
            f"Since {rep['since']}; {rep['signals']} opening signals, {rep['tips']} distinct tips (one per source, name, "
            f"side and day), {rep['scored']} priced on the contract's own 1-minute trade bars "
            f"({rep['expiryInferred']} with the expiry identified by the stated premium). Unscored: {un}. "
            f"Results are % of the premium paid, after ${rep['optCost']:.2f} a share for both legs' slippage and fees. "
            f"A verdict needs {rep['minN']} counted tips and 5 days. Rules: hold = no stop, sold at the horizon's close "
            "(never past expiry); bracket = stop -50% / target +100%; scalp = stop -30% / target +30%, flat at the "
            "day's close. Prints, not fills.", ""]
    return "\n".join(head + block("By the analyst's verdict at tip time", rep["byAnalystVerdict"])
                     + block("By source", rep["bySource"])
                     + block("By source and verdict (8 or more priced)", rep["bySourceAndVerdict"], floor=8))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-28")
    ap.add_argument("--opt-cost", type=float, default=0.08)
    ap.add_argument("--min-n", type=int, default=20)
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
