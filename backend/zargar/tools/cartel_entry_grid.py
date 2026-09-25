"""Read-only entry-rule grid over every recorded Cartel pre-open candidate pool; never places orders.

For each session, the latest completed pre-open preparation of each named Practice book supplies the
frozen long candidate pool (the same lineage as ``cartel_historical_lab``). Native SIP 1m history is
fetched once per symbol (baselines use only sessions completed before the candidate's daily cutoff;
outcomes use the minutes AFTER the signal). Each candidate-day is read under a predeclared grid:

* breakout, 15m and 5m candles, volume multiple 1.0 / 1.2 / 1.5, gap policy none / retest_v1
* pivot_30m (Sean's pullback entry: break of the first green 30-minute pivot off the 8/21 EMAs) and
  undercut_reclaim, 5m and 15m, from the method lab's frozen definitions

Outcome of a signal (declared before running): entry at the confirmation close, protective stop at the
signal's stop, exit at the first of stop (a 1m low through it; the open if it gapped through) or first
target (a 1m high through it; the open if it gapped through) within ``HORIZON_SESSIONS`` sessions, else
the last close. Reported in R of the signal's own risk, gross and after a 2 bp per-side share cost.
Options are NOT modeled: no historical option quotes exist for these candidates. Exploratory: the grid
was chosen after seeing some sessions; it is not a held-out test.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path

import httpx

from ..marketstructure.market_calendar import next_trading_day
from ..marketstructure.sessions import ET, session_bounds
from ..techniques.options_cartel.automatic_plans import PreparationPolicy
from ..techniques.options_cartel.entry import read_entry
from ..techniques.options_cartel.method_lab import build_specs, freeze_candidates
from ..techniques.options_cartel.prepare import build_volume_baseline
from ..techniques.options_cartel.profitability_research import candidate_from_analysis, make_plan
from ..techniques.options_cartel.shadow_entries import ShadowEntrySpec, read_shadow_entry
from .cartel_historical_lab import choose_preparations, legacy_analysis, load, native_history

HORIZON_SESSIONS = 5
COST_BPS = 2.0
VOLUMES = (1.0, 1.2, 1.5)


def variants():
    """The predeclared grid: (name, kind, timeframe, volume multiple, gap policy)."""
    out = []
    for tf in (15, 5):
        for vol in VOLUMES:
            for gap in ("none", "retest_v1"):
                out.append((f"breakout_{tf}m_v{vol:g}_{'gap' if gap != 'none' else 'nogap'}", "breakout", tf, vol, gap))
    for model in ("pivot_30m", "undercut_reclaim"):
        for tf in (5, 15):
            out.append((f"{model}_{tf}m", model, tf, 1.5, "none"))
    return out


def outcome(signal, targets, minutes, *, horizon_end, direction="long"):
    """Pure: first of stop / first target after the signal, else the last close before ``horizon_end``."""
    sign = 1 if direction == "long" else -1
    entry, stop, target = signal["referencePrice"], signal["stop"], targets[0]
    risk = (entry-stop)*sign
    if risk <= 0:
        return None
    after = [b for b in minutes if signal["at"] <= b.ts < horizon_end]
    if not after:
        return {"exit": "no_data", "r": None}
    for b in after:
        if (b.low-stop)*sign <= 0 if sign == 1 else (b.high-stop)*sign >= 0:
            price = b.open if (b.open-stop)*sign < 0 else stop
            kind = "stop"
        elif (b.high-target)*sign >= 0 if sign == 1 else (b.low-target)*sign <= 0:
            price = b.open if (b.open-target)*sign > 0 else target
            kind = "target"
        else:
            continue
        gross = (price-entry)*sign/risk
        return {"exit": kind, "at": b.ts, "price": price, "r": gross, "rNet": gross-(entry+price)*COST_BPS/1e4/risk}
    price = after[-1].close
    gross = (price-entry)*sign/risk
    return {"exit": "time", "at": after[-1].ts, "price": price, "r": gross, "rNet": gross-(entry+price)*COST_BPS/1e4/risk}


def horizon_close(day):
    d = dt.date.fromisoformat(day)
    for _ in range(HORIZON_SESSIONS-1):
        d = next_trading_day(d)
    return session_bounds(d.isoformat())[1]


def evaluate(candidate, day, history, minutes, frozen_at):
    opened, closed = session_bounds(day)
    matrices = {str(tf): build_volume_baseline(history, candidate["symbol"], tf, candidate["sourceAt"], require_exchange=True)
                for tf in (5, 15)}
    specs = build_specs(candidate, day, matrices, frozen_at)
    day_minutes = [b for b in minutes if opened <= b.ts < closed]
    end = horizon_close(day)
    rows = []
    for name, kind, tf, vol, gap in variants():
        if kind == "breakout":
            policy = {**candidate["entryPolicy"], "timeframe_minutes": tf, "volume_multiple": vol, "gap_policy": gap}
            plan = make_plan({**candidate, "entryPolicy": policy}, day, matrices[str(tf)])
            read = read_entry(plan, day_minutes, closed-1, entry_after=opened)
            targets = list(plan.targets)
        else:
            key = f"{kind}_5m_v1"
            if key not in specs:
                continue
            raw = {**specs[key]}
            if tf == 15:
                raw.update(id=raw["id"]+":15m", confirmation_minutes=15, volume_baseline=matrices["15"]["baselines"])
            spec = ShadowEntrySpec.model_validate(raw)
            read = read_shadow_entry(spec, day_minutes, closed-1, entry_after=opened)
            targets = list(spec.targets)
        signal = read.get("signal")
        row = {"variant": name, "status": read["status"], "signalAt": signal["at"] if signal else None}
        if signal:
            row.update(entry=signal["referencePrice"], stop=signal["stop"], volumeRatio=signal.get("volumeRatio"),
                       outcome=outcome(signal, targets, minutes, horizon_end=end))
        rows.append(row)
    sign = 1 if candidate.get("direction", "long") == "long" else -1
    touch = next((b.ts for b in day_minutes if ((b.high if sign == 1 else b.low)-candidate["trigger"])*sign >= 0), None)
    return {"symbol": candidate["symbol"], "session": day, "setup": candidate["setup"], "trigger": candidate["trigger"],
            "touchedAt": touch, "absentMinutes": (closed-opened)//60_000-len(day_minutes),
            "minuteCount": len(day_minutes), "baselineSlots": {tf: len(m["baselines"]) for tf, m in matrices.items()}, "rows": rows}


def summarize(results):
    per = defaultdict(lambda: {"candidateDays": 0, "signals": 0, "targets": 0, "stops": 0, "time": 0, "rNet": []})
    for res in results:
        for row in res["rows"]:
            s = per[row["variant"]]
            s["candidateDays"] += 1
            if row.get("signalAt"):
                s["signals"] += 1
                o = row.get("outcome") or {}
                if o.get("r") is not None:
                    s[{"target": "targets", "stop": "stops", "time": "time"}[o["exit"]]] += 1
                    s["rNet"].append(o["rNet"])
    table = []
    for name, *_ in variants():
        s = per.get(name)
        if not s:
            continue
        r = s.pop("rNet")
        table.append({"variant": name, **s, "tradesScored": len(r), "totalRNet": round(sum(r), 3),
                      "avgRNet": round(statistics.mean(r), 3) if r else None,
                      "winRate": round(sum(x > 0 for x in r)/len(r), 3) if r else None})
    return table


async def run(args):
    import asyncpg
    from ..config import AppConfig
    cfg = AppConfig(_env_file=args.env_file)
    client = httpx.AsyncClient(headers={"APCA-API-KEY-ID": cfg.alpaca_key_id, "APCA-API-SECRET-KEY": cfg.alpaca_secret}, timeout=30)
    conn = await asyncpg.connect(os.environ["CARTEL_AUDIT_DATABASE_URL"], server_settings={"default_transaction_read_only": "on"})
    pools, errors = [], []
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            for portfolio in args.portfolio:
                preps = await conn.fetch("select id,status,created_at,config,result from technique_runs where technique='options_cartel' "
                    "and mode='preparation' and config->>'workspace'='practice' and config->>'portfolioId'=$1 "
                    "and config->>'session'>=$2 and config->>'session'<=$3 order by created_at,id", portfolio, args.start, args.end)
                for day, prep in sorted(choose_preparations(preps).items()):
                    pcfg, res = load(prep["config"]), load(prep["result"])
                    policy = PreparationPolicy.model_validate(pcfg["policy"])
                    opened = session_bounds(day)[0]
                    # Only rows that passed the automatic review can become candidates; loading the ~3,000
                    # screened-out analyses per preparation costs >1 GB on the host and changes nothing.
                    cited = [r["analysisId"] for r in res.get("rows", []) if r.get("analysisId") and r.get("status") not in ("filtered", "prefiltered")]
                    saved = await conn.fetch("select id,symbol,config,result,created_at from technique_runs where technique='options_cartel' "
                        "and mode='analysis' and id=any($1::text[]) and created_at<to_timestamp($2::double precision/1000) "
                        "order by created_at,id", cited, opened)
                    by_symbol = {}
                    for r in saved:
                        if r["symbol"] not in by_symbol or r["id"] in cited:
                            by_symbol[r["symbol"]] = r
                    candidates = []
                    for r in by_symbol.values():
                        body = load(r["config"])
                        if body.get("inputs", {}).get("direction") != "long":
                            continue
                        try:
                            c = candidate_from_analysis({"runId": r["id"], "symbol": r["symbol"], "config": body,
                                                         "result": legacy_analysis(load(r["result"]))}, policy, "primary")
                            if c:
                                candidates.append(c)
                        except (ValueError, KeyError, TypeError) as exc:
                            errors.append({"session": day, "symbol": r["symbol"], "reason": str(exc)[:160]})
                    if not candidates:
                        pools.append((day, portfolio, int(res["finishedAt"]), []))
                        continue
                    frozen = freeze_candidates(candidates, at=int(res["finishedAt"]), day=day, cap=100)
                    pools.append((day, portfolio, int(res["finishedAt"]), frozen["candidates"]))
                    print(json.dumps({"session": day, "portfolio": portfolio[:8], "candidates": len(frozen["candidates"])}), flush=True)
    finally:
        await conn.close()
    by_symbol = defaultdict(list)
    for day, portfolio, frozen_at, cands in pools:
        for c in cands:
            by_symbol[c["symbol"]].append((day, frozen_at, c))
    results = []
    try:
        for symbol, items in sorted(by_symbol.items()):
            first = min(d for d, _, _ in items)
            start = int(dt.datetime.combine(dt.date.fromisoformat(first)-dt.timedelta(days=45), dt.time(), dt.timezone.utc).timestamp()*1000)
            end = min(int(dt.datetime.now(dt.timezone.utc).timestamp()*1000), max(horizon_close(d) for d, _, _ in items))
            try:
                minutes, manifest = await native_history(client, symbol, start, end)
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({"symbol": symbol, "reason": f"history: {type(exc).__name__}"})
                continue
            if not manifest.get("complete"):
                errors.append({"symbol": symbol, "reason": "incomplete native pagination"})
                continue
            for day, frozen_at, c in items:
                try:
                    results.append(evaluate(c, day, minutes, minutes, frozen_at))
                except (ValueError, KeyError, TypeError) as exc:
                    errors.append({"session": day, "symbol": symbol, "reason": str(exc)[:160]})
            del minutes
    finally:
        await client.aclose()
    report = {"version": "cartel-entry-grid-v1", "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
              "start": args.start, "end": args.end, "portfolios": args.portfolio, "horizonSessions": HORIZON_SESSIONS,
              "costBpsPerSide": COST_BPS, "summary": summarize(results), "candidateDays": len(results), "results": results,
              "errors": errors, "placesOrders": False,
              "limitations": ["Underlying R only; option P&L is not modeled (no historical option quotes).",
                              "Retrospective native minutes, not receipt-time evidence; data refusals may differ from live.",
                              "Candidate pools are the saved pre-open long pools; the screen was not re-run under new rules.",
                              "Exploratory grid on a small sample; not a held-out test. Signals within one session are correlated."]}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    for row in report["summary"]:
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--portfolio", action="append", required=True)
    p.add_argument("--env-file", required=True)
    p.add_argument("--output", required=True)
    asyncio.run(run(p.parse_args()))
