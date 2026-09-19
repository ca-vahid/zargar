"""Evaluate the intake review relevance gate (review-gate-v1) on the SAME evidence, before and after.

Two modes, both read-only, both using the production decision (`techniques/tip/review_gate.decide`):

* retrospective (`--since`): every intake review in the window is re-decided against the desk state
  REBUILT from the durable record at the review's own timestamp (open managed tip positions, armed tip
  plan intervals from TechniquePlanArmed/Disarmed, proposals pending or executed that ET session). For
  each review: cost at list price (llm.rates), the management tools it actually called
  (update_exit_plan / close_position / disarm_plan), and whether the gate would have kept it.
* prospective (`--prospective`): the live TipReviewGate decisions (observe mode) joined to what each
  review then did - a skip-decision whose review called a management tool is a FALSE NEGATIVE.

The acceptance line for `enforce` is printed: false negatives must be zero on both.

Usage (from backend/):
  .venv/Scripts/python -m zargar.tools.tip_review_gate_eval --since 2026-09-09
  .venv/Scripts/python -m zargar.tools.tip_review_gate_eval --prospective --since 2026-09-21
"""
from __future__ import annotations

import argparse
import statistics
import math
import hashlib
import asyncio
import collections
import datetime as dt
import json
import re

import asyncpg

from ..techniques.tip import review_gate as rg

MGMT = {"update_exit_plan", "close_position", "disarm_plan"}
_EXT = re.compile(r"Extracted (\d+) signal\(s\) — content type: ([a-z_]+)\.(.*)$", re.S)
_ET = dt.timezone(dt.timedelta(hours=-4))


def J(v):
    return (json.loads(v) if isinstance(v, str) else v) or {}


def ms(t: dt.datetime) -> int:
    return int(t.timestamp() * 1000)


def extract_line(trace) -> tuple[str, list[str]]:
    """(content type, extracted tickers) from the intake run's own extract step."""
    for s in trace or []:
        m = _EXT.match(s.get("text") or "") if s.get("kind") == "extract" else None
        if m:
            body = re.sub(r"Transcribed the image into text first\.", "", m.group(3))
            tk = []
            for part in body.split(";"):
                tok = part.strip().split(" ")
                if tok and tok[0] and re.match(r"^\$?[A-Z][A-Z.]{0,5}$", tok[0].strip("$")):
                    tk.append(tok[0].strip("$").upper())
            return m.group(2), tk
    return "?", []


def usage_usd(op: dict, rate: dict | None) -> tuple[int, int, float | None]:
    u = op.get("usage") or {}
    if isinstance(u, list):
        u = {"in": sum(int(x.get("inputTokens") or 0) for x in u), "out": sum(int(x.get("outputTokens") or 0) for x in u)}
    tin, tout = int(u.get("in") or 0), int(u.get("out") or 0)
    if not rate:
        return tin, tout, None
    return tin, tout, tin / 1e6 * float(rate["in"]) + tout / 1e6 * float(rate["out"])


async def _rates(c) -> dict:
    v = J(await c.fetchval("select value from settings where key = 'llm.rates'"))
    return v["v"] if isinstance(v.get("v"), dict) else v


async def desk_history(c):
    """Interval lists for positions, plans and proposals, rebuilt from the durable record."""
    pos = []
    for r in await c.fetch("select symbol, tags, created_at, state from managed_positions where technique='tip'"):
        tags = J(r["tags"]) if not isinstance(r["tags"], list) else r["tags"]
        src = next((t[7:] for t in tags or [] if str(t).startswith("source:")), "")
        closed = int(J(r["state"]).get("closedMs") or 0) or None
        pos.append(("position", r["symbol"], src, ms(r["created_at"]), closed))
    runs = {r["id"]: (r["symbol"], J(r["config"]).get("source") or (J(r["config"]).get("context") or {}).get("source") or "")
            for r in await c.fetch("select id, symbol, config from technique_runs where technique='tip'")}
    open_at: dict[str, int] = {}
    plans = []
    for e in await c.fetch("select ts, type, payload from events where type in ('TechniquePlanArmed','TechniquePlanDisarmed') order by ts"):
        rid = J(e["payload"]).get("runId")
        if rid not in runs:
            continue
        if e["type"] == "TechniquePlanArmed":
            open_at.setdefault(rid, ms(e["ts"]))
        elif rid in open_at:
            plans.append(("plan", runs[rid][0], runs[rid][1], open_at.pop(rid), ms(e["ts"])))
    plans += [("plan", runs[rid][0], runs[rid][1], t, None) for rid, t in open_at.items()]
    props = []
    for r in await c.fetch("""select pr.symbol, pr.created_at, pr.decided_at, pr.status, s.source_name src
                              from proposals pr left join signals s on s.id = pr.signal_id"""):
        end = ms(r["decided_at"]) if r["decided_at"] else None
        if r["status"] == "executed":
            end = ms(r["created_at"].astimezone(_ET).replace(hour=20, minute=0, second=0, microsecond=0))
        props.append(("proposal", r["symbol"], r["src"] or "", ms(r["created_at"]), end))
    return pos + plans + props


def items_at(hist, t: int) -> list[dict]:
    return [{"kind": k, "symbol": sym, "source": src} for k, sym, src, a, b in hist if a <= t and (b is None or t < b)]


async def retrospective(c, since: str) -> dict:
    rate = (await _rates(c)).get("claude-opus-5")
    hist = await desk_history(c)
    fails = collections.defaultdict(list)
    for s in await c.fetch("""select source_name, created_at, verification from signals
                              where created_at >= $1 and status = 'verification_failed'""",
                           dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc)):
        fails[s["source_name"]].append((s["created_at"], [x.get("name") for x in (J(s["verification"]).get("checks") or [])
                                                          if x.get("passed") is False]))
    runs = await c.fetch("""select id, source, created_at, opinion, trace from tip_analyst_runs
        where kind='intake' and verdict='review' and created_at >= $1 order by created_at""",
                         dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc))
    rows = []
    for r in runs:
        op = J(r["opinion"])
        trace = r["trace"] if isinstance(r["trace"], list) else J(r["trace"])
        ctype, tickers = extract_line(trace)
        outcomes = [{"status": "verification_failed", "failed": f} for (t0, f) in fails.get(r["source"], [])
                    if abs((t0 - r["created_at"]).total_seconds()) < 180]
        d = rg.decide(tickers=tickers, source=r["source"] or "", outcomes=outcomes, items=items_at(hist, ms(r["created_at"])))
        tin, tout, usd = usage_usd(op, rate)
        tools = [t.get("tool") or t.get("name") for t in (op.get("toolsUsed") or [])]
        rows.append({"id": r["id"], "at": r["created_at"], "source": r["source"], "ctype": ctype, "tickers": tickers,
                     "keep": d["review"], "reason": d["reason"], "in": tin, "out": tout, "usd": usd,
                     "mgmt": [t for t in tools if t in MGMT], "notes": tools.count("save_note"),
                     "missedTip": bool(op.get("missedTip")), "watch": bool(op.get("watch")),
                     "mixed": len(set(tickers)) >= 2, "headline": (op.get("rationale") or "")[:140]})
    return {"rows": rows, "rate": rate}


def report_retro(res: dict, since: str) -> None:
    rows = res["rows"]
    usd = lambda xs: sum(x["usd"] or 0.0 for x in xs)
    keep = [x for x in rows if x["keep"]]; skip = [x for x in rows if not x["keep"]]
    fn = [x for x in skip if x["mgmt"]]
    print(f"# Intake review gate - retrospective, reviews since {since}\n")
    print(f"Cost at llm.rates list price (an ESTIMATE, not an invoice); rate card {'present' if res['rate'] else 'MISSING - cost unpriced'}.\n")
    print("| | reviews | est. cost | with a management tool | note only | missed-tip flag |")
    print("|---|---:|---:|---:|---:|---:|")
    for label, xs in (("all (before)", rows), ("kept by the gate (after)", keep), ("skipped by the gate", skip)):
        print(f"| {label} | {len(xs)} | ${usd(xs):,.2f} | {sum(1 for x in xs if x['mgmt'])} | "
              f"{sum(1 for x in xs if not x['mgmt'] and x['notes'])} | {sum(1 for x in xs if x['missedTip'])} |")
    print(f"\n**False negatives (skipped reviews that called a management tool): {len(fn)}**")
    for x in fn:
        print(f"- {x['at']:%Y-%m-%d %H:%M} {x['source']} {x['ctype']} tickers={x['tickers']} tools={x['mgmt']}")
    # ECON-03: management tools are not the only thing a review can be worth - these skipped classes need a HUMAN read
    print("\nSkipped reviews by what else they carried (for human review - a tool count alone does not prove no value):")
    print(f"- possible new entry flagged (missed-tip text): {sum(1 for x in skip if x['missedTip'])}")
    print(f"- deferred action (non-empty watch list): {sum(1 for x in skip if x['watch'])}")
    print(f"- mixed message (two or more tickers): {sum(1 for x in skip if x['mixed'])}")
    print(f"- note written: {sum(1 for x in skip if x['notes'])} (historical receipt absence does not prove a note has no future value)")
    for x in [x for x in skip if x["missedTip"] or x["watch"]][:12]:
        print(f"  - {x['at']:%m-%d %H:%M} {x['source']} {x['tickers']} missedTip={x['missedTip']} watch={x['watch']} | {x['headline']}")
    print("\n| content type | reviews | est. cost | kept | management |")
    print("|---|---:|---:|---:|---:|")
    by = collections.defaultdict(list)
    for x in rows:
        by[x["ctype"]].append(x)
    for k, xs in sorted(by.items(), key=lambda kv: -usd(kv[1])):
        print(f"| {k} | {len(xs)} | ${usd(xs):,.2f} | {sum(1 for x in xs if x['keep'])} | {sum(1 for x in xs if x['mgmt'])} |")
    # cost by message category x what the review actually DID (one row per review, its most useful action)
    def action(x):
        return ("management (exit plan / close / disarm)" if x["mgmt"] else "possible missed entry flagged" if x["missedTip"]
                else "note only" if x["notes"] else "nothing")
    print("\n| content type | useful action | reviews | est. cost | of which the gate would skip |")
    print("|---|---|---:|---:|---:|")
    cross = collections.defaultdict(list)
    for x in rows:
        cross[(x["ctype"], action(x))].append(x)
    for (ct, act), xs in sorted(cross.items(), key=lambda kv: -usd(kv[1])):
        sk = [x for x in xs if not x["keep"]]
        print(f"| {ct} | {act} | {len(xs)} | ${usd(xs):,.2f} | {len(sk)} (${usd(sk):,.2f}) |")
    print("\n| source | reviews | est. cost | kept | management |")
    print("|---|---:|---:|---:|---:|")
    by = collections.defaultdict(list)
    for x in rows:
        by[x["source"]].append(x)
    for k, xs in sorted(by.items(), key=lambda kv: -usd(kv[1])):
        print(f"| {k} | {len(xs)} | ${usd(xs):,.2f} | {sum(1 for x in xs if x['keep'])} | {sum(1 for x in xs if x['mgmt'])} |")
    print("\nAPPROXIMATE reconstruction: the desk state at each review is REBUILT from managed positions, arm/disarm "
          "events and proposals - not the live state the gate will read; a plan whose arm or disarm event is missing, or a "
          "signal-to-source join that is absent, is invisible here. Treat the zero as necessary, not sufficient.")
    print("\nLimits: desk state is rebuilt from positions, arm/disarm events and proposals; extracted tickers come "
          "from the intake run's own extract line (up to 8 listed). A missed-tip flag is advisory text no process "
          "consumes. Reviews before 2026-09-09 carry no usage and are excluded.")


async def prospective(c, since: str) -> None:
    ev = await c.fetch("""select ts, payload from events where type='TipReviewGate' and ts >= $1 order by ts""",
                       dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc))
    rate = (await _rates(c)).get("claude-opus-5")
    ids = [J(e["payload"]).get("intakeRunId") for e in ev]
    runs = {r["id"]: J(r["opinion"]) for r in await c.fetch(
        "select id, opinion from tip_analyst_runs where id = any($1::varchar[])", [i for i in ids if i])}
    cnt = collections.Counter(); fn = []; cost = collections.defaultdict(float); other = []; incomplete = 0
    sessions = set()
    for e in ev:
        p = J(e["payload"]); op = runs.get(p.get("intakeRunId")) or {}
        tools = [t.get("tool") or t.get("name") for t in (op.get("toolsUsed") or [])]
        _i, _o, usd = usage_usd(op, rate)
        key = (p.get("mode"), p.get("decision"), bool(p.get("applied")))
        cnt[key] += 1; cost[key] += usd or 0.0
        sessions.add((e["ts"].astimezone(_ET) - dt.timedelta(hours=4)).date())
        incomplete += 1 if p.get("readErrors") else 0
        if p.get("decision") == "skip" and any(t in MGMT for t in tools):
            fn.append((e["ts"], p.get("source"), p.get("tickers"), [t for t in tools if t in MGMT]))
        elif p.get("decision") == "skip" and (op.get("missedTip") or op.get("watch") or len(p.get("tickers") or []) >= 2):
            other.append((e["ts"], p.get("source"), p.get("tickers"), bool(op.get("missedTip")), bool(op.get("watch")),
                          (op.get("rationale") or "")[:140]))
    print(f"# Intake review gate - prospective decisions since {since}\n")
    print(f"Coverage: {len(ev)} decision(s) over {len(sessions)} accounting session(s) ({', '.join(str(d) for d in sorted(sessions)) or 'none'}); "
          f"{incomplete} decided with an incomplete desk read (always reviewed).\n")
    print("| mode | decision | skipped for real | messages | est. review cost |")
    print("|---|---|---|---:|---:|")
    for k, n in sorted(cnt.items()):
        print(f"| {k[0]} | {k[1]} | {k[2]} | {n} | ${cost[k]:,.2f} |")
    print(f"\n**False negatives (observe skip-decisions whose review managed something): {len(fn)}**")
    for f in fn:
        print(f"- {f[0]:%Y-%m-%d %H:%M} {f[1]} {f[2]} {f[3]}")
    print(f"\nSkip-decisions that carried something else worth a human read (possible new entry, deferred action, mixed "
          f"message): {len(other)}")
    for o in other[:20]:
        print(f"- {o[0]:%Y-%m-%d %H:%M} {o[1]} {o[2]} missedTip={o[3]} watch={o[4]} | {o[5]}")
    print("\nThis is a REVIEW checkpoint, not an activation rule: zero management false negatives here AND in the retrospective "
          "replay are necessary; a human also reads the list above (corrections, new entries, mixed messages, useful deferred "
          "actions). A few clean sessions are not statistical proof that no harmful exclusion exists.")


# ---- model-cost alternatives: the frozen-evaluation PLAN and its budget (no provider call is made here) ----
# Candidate list prices per MTok (Anthropic published list, read 2026-09-19; cache read ~0.1x input, 5-minute cache
# write ~1.25x input). They live HERE, not in `llm.rates`: a candidate is not a production model. Re-verify the card
# on the day a paid evaluation is approved - the budget below is recomputed from whatever is passed.
CANDIDATE_RATES = {"claude-sonnet-5": {"in": 2.0, "out": 10.0, "cacheRead": 0.2, "cacheWrite": 2.5},
                   "claude-haiku-4-5": {"in": 1.0, "out": 5.0, "cacheRead": 0.1, "cacheWrite": 1.25}}
QUOTAS = (("management", 20), ("missed_entry_flag", 10), ("correction", 8), ("mixed_multi_ticker", 6), ("note_only", 16))
MARGIN = 1.30          # tokenizer differences, an extra tool turn, one retry
_CORR = re.compile(r"correct|typo|meant|edit(ed)?\b|revis|update to (my|the)", re.I)


def stratum(x: dict) -> str:
    return ("management" if x["mgmt"] else "missed_entry_flag" if x["missedTip"] else
            "correction" if _CORR.search(x.get("headline") or "") else "mixed_multi_ticker" if x["mixed"] else "note_only")


def model_plan(res: dict, *, captured: set) -> dict:
    """Stratified case quotas + an estimate-based dollar guard. `captured` = review runs that carry an exact request manifest -
    ONLY those are replayable; the historical rows size the budget and show how rare the hard strata are."""
    rows = [r for r in res["rows"] if r["in"]]
    days = max(1, len({x["at"].date() for x in rows}))
    by = collections.defaultdict(list)
    for r in rows:
        by[stratum(r)].append(r)
    strata, total = [], {m: 0.0 for m in CANDIDATE_RATES}
    for name, quota in QUOTAS:
        g = sorted(by.get(name, []), key=lambda x: hashlib.sha256(x["id"].encode()).hexdigest())
        med_in = int(statistics.median(x["in"] for x in g)) if g else 0
        med_out = int(statistics.median(x["out"] for x in g)) if g else 0
        cost = {m: round(quota * (med_in / 1e6 * rt["in"] + med_out / 1e6 * rt["out"]) * MARGIN, 2) for m, rt in CANDIDATE_RATES.items()}
        for m in total:
            total[m] += cost[m]
        strata.append({"stratum": name, "history": len(g), "perDay": round(len(g) / days, 1), "quota": quota,
                       "capturedNow": sum(1 for x in g if x["id"] in captured), "medianIn": med_in, "medianOut": med_out,
                       "cost": cost, "opusUsd": round(quota * (statistics.mean(x["usd"] for x in g) if g else 0), 2)})
    cap = math.ceil(sum(total.values()) / 5.0) * 5.0
    return {"strata": strata, "totals": {m: round(v, 2) for m, v in total.items()}, "capUsd": cap,
            "capturedReviews": len(captured), "historyReviews": len(rows)}


def report_model_plan(plan: dict, since: str) -> None:
    print(f"# Cheaper intake-review processing - frozen evaluation plan and budget (history since {since})\n")
    print("No provider call was made to produce this plan. Candidates are evaluated on the EXACT captured request of real "
          "reviews (`review_frozen.py`): tools are served from the case, a management tool is recorded as a proposed action and "
          "never executed. Production keeps its model whatever the result.\n")
    print("| case type | in history | per day | quota | captured now | median in / out tokens | Sonnet 5 | Haiku 4.5 | same cases on Opus 5 (recorded mean) |")
    print("|---|---:|---:|---:|---:|---|---:|---:|---:|")
    for x in plan["strata"]:
        print(f"| {x['stratum']} | {x['history']} | {x['perDay']} | {x['quota']} | {x['capturedNow']} | {x['medianIn']:,} / {x['medianOut']:,} | "
              f"${x['cost']['claude-sonnet-5']:,.2f} | ${x['cost']['claude-haiku-4-5']:,.2f} | ${x['opusUsd']:,.2f} |")
    t = plan["totals"]
    print(f"\n**Budget: ${plan['capUsd']:,.0f} estimate-based spending guard, not a guaranteed maximum** - actual billing can "
          f"exceed a reservation; the guard refuses the NEXT attempt once recorded spend plus the next reservation would pass "
          f"${plan['capUsd']:,.0f}, so the final bill can end above it by at most one attempt's overrun, which is recorded "
          f"(`review_frozen.SuiteBudget`: ONE durable ledger across both models, every case, turn, retry and separate invocation; each attempt is reserved BEFORE it is sent at request chars / 3 input + the full max_tokens output x 1.25, settled from the provider's usage, and left charged at its reservation when billing is unknown; SDK retries disabled; the guard cannot be raised by a later run) = "
          f"Sonnet 5 ${t['claude-sonnet-5']:,.2f} + Haiku 4.5 ${t['claude-haiku-4-5']:,.2f}, one pass per model, including a "
          f"{int(round((MARGIN - 1) * 100))}% margin. No repeat passes inside this budget.")
    print(f"\nReplayable today: {plan['capturedReviews']} captured review(s) of {plan['historyReviews']} in history. A review before "
          "capture was switched on kept its tool results but not its request, so it cannot be replayed faithfully; the quotas fill "
          "from reviews captured prospectively. At the per-day rates above the rare case types (management, missed-entry, correction) "
          "set the calendar, not the budget.")
    print("\nComparison (safeguards rev 2): the actual INSTRUCTION is compared - target, stop levels, targets, fractions, sale "
          "fraction, hold cap; a changed level is a disagreement. A read is served only for the exact tool + arguments the case "
          "recorded; anything else stays MISSING and makes the case INCONCLUSIVE - never an equivalence pass. Limitation that "
          "remains: the guard is estimate-based - reservations use request characters / 3 and list prices, not the provider's tokenizer or invoice; the total stays within the guard only while no single attempt bills more than 1.25x its reservation.")
    print("\nAcceptance to even DISCUSS a change (not an activation rule): zero missed management actions, zero invalid replies on "
          "the management and correction cases, missed-entry flags matched, and every disagreement read by a human. One pass is "
          "not a measure of run-to-run variance.")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--since", default="2026-09-09")
    ap.add_argument("--prospective", action="store_true")
    ap.add_argument("--model-plan", action="store_true", help="frozen-evaluation case quotas + budget for cheaper review models (no provider call)")
    a = ap.parse_args()
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        if a.model_plan:
            cap = {r["id"] for r in await c.fetch("""select id from tip_analyst_runs where kind='intake' and verdict='review'
                                                     and trace::text like '%reviewManifest%'""")}
            report_model_plan(model_plan(await retrospective(c, a.since), captured=cap), a.since)
        elif a.prospective:
            await prospective(c, a.since)
        else:
            report_retro(await retrospective(c, a.since), a.since)
    finally:
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
