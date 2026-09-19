"""EM preparation comparison (integrated plan B "Required comparison", 2026-09-18). ZERO paid model calls.

    python -m zargar.tools.em_prep_compare --dates 2026-09-15,2026-09-16,2026-09-17,2026-09-18 [--no-yahoo] [--stdout]

On the SAVED promote reads of each session's prepared sheet (identical causal inputs: each plan's own saved thresholds,
bars snapshot and one pre-market reference - see `em_prep_ablation`), compare three SELECTIONS:

  baseline_model   what the model's plan review selected (verdict `setup`) - the live baseline
  deterministic    `em-prep-policy-v1` deterministic eligibility (valid geometry + grade floor), zero model calls
  frozen_exception deterministic + the exception features frozen 2026-09-18 in `em_prep_ablation` (never re-learned here)

Every selection's replay fills then pass through ONE chronological shared book (`capacity-v1`, conventions taken from
the live settings and printed in the manifest): one open position per plan, a slot cap from the per-symbol exposure
limit, and the daily-loss halt in R. Opportunities are NOT summed independently. Replay fills are UNDERLYING walk-forward
fills: there is no historical executable option evidence (quotes, depth, contract, quantity) for unselected plans, so
every replay figure is labelled PROXY-ONLY and is never converted into dollars. Actual dollars exist only for the live
baseline (execution ledger). Model cost comes from `model-costs-v1` (unknown when no dated price is configured).
Exploratory fixtures, not validation: the prospective definitions are frozen in the delivery's collection manifest.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os

import asyncpg

from ..technique import model_costs as mc
from ..technique import preparation_policy as pp
from . import em_prep_ablation as abl
from .em_profit_capture import DISPUTED, EM_BOOK, _ms, execution_net

VERSION = "prep-compare-v1"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "prep-compare")
J = abl.J
CAPACITY = {"version": "capacity-v1", "riskPctPerEntry": 2.0, "dailyLossHaltPct": 3.0, "maxPositionPct": 10.0, "maxGrossExposurePct": 100.0,
            "derivation": "technique.arm.risk_pct / risk.daily_loss_halt_pct / risk.max_position_pct / risk.max_gross_exposure_pct as configured for EM Practice"}


def shared_book(fills: list, cap: dict = CAPACITY) -> dict:
    """Chronological shared-capacity simulation over replay fills [{symbol, runId, trigger, fillIndex, barsHeld, r}].
    Slots = gross exposure / per-symbol exposure; halt = cumulative REALIZED R at or below -(halt% / risk%) stops new
    entries (exits are never blocked); one open position per plan. A fill without a time index is excluded and counted."""
    slots = max(1, int(cap["maxGrossExposurePct"] // cap["maxPositionPct"]))
    halt_r = -(cap["dailyLossHaltPct"] / cap["riskPctPerEntry"])
    timed = sorted((f for f in fills if f.get("fillIndex") is not None), key=lambda f: (int(f["fillIndex"]), str(f["symbol"]), str(f["trigger"])))
    untimed = [f for f in fills if f.get("fillIndex") is None]
    open_, realized, taken, refused = [], 0.0, [], []
    halted_at = None
    for f in timed:
        t = int(f["fillIndex"])
        for o in [o for o in open_ if o["exitIndex"] <= t]:
            realized += float(o["r"] or 0.0); open_.remove(o)
            if halted_at is None and realized <= halt_r:
                halted_at = o["exitIndex"]
        why = None
        if halted_at is not None and t >= halted_at:
            why = "daily_loss_halt"
        elif any(o["runId"] == f["runId"] for o in open_):
            why = "plan_already_open"
        elif len(open_) >= slots:
            why = "no_free_slot"
        if why:
            refused.append({**f, "why": why}); continue
        open_.append({**f, "exitIndex": t + int(f.get("barsHeld") or 0)}); taken.append(f)
    rs = [float(f["r"] or 0.0) for f in taken]
    return {"capacity": {**cap, "slots": slots, "haltAtR": halt_r}, "taken": len(taken), "refused": len(refused), "refusedWhy": _count(r["why"] for r in refused),
            "untimedExcluded": len(untimed), "haltedAtIndex": halted_at, "sumR": round(sum(rs), 3), "winners": sum(1 for x in rs if x > 0),
            "losers": sum(1 for x in rs if x < 0), "worstDrawdownR": round(_drawdown(taken), 3), "independentSumR": round(sum(float(f["r"] or 0) for f in fills), 3),
            "label": "PROXY-ONLY: underlying walk-forward R under capacity-v1; not dollars, not option fills"}


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def _drawdown(taken: list) -> float:
    eq, peak, dd = 0.0, 0.0, 0.0
    for f in sorted(taken, key=lambda f: int(f["fillIndex"]) + int(f.get("barsHeld") or 0)):
        eq += float(f["r"] or 0.0); peak = max(peak, eq); dd = min(dd, eq - peak)
    return dd


def selections(rows: list, runs: dict, policy_det: dict) -> dict:
    """Membership of each saved read in the three selections + the policy records (pure; `runs` = {runId: {plan, analysis}})."""
    out = {"baseline_model": [], "deterministic": [], "frozen_exception": []}
    decisions = {}
    for r in rows:
        x = runs.get(r["runId"]) or {}
        det = pp.decide(symbol=r["symbol"], plan=x.get("plan") or {}, analysis=None, policy=policy_det, origin="batch", run_id=r["runId"])
        base = pp.decide(symbol=r["symbol"], plan=x.get("plan") or {}, analysis=x.get("analysis"), policy={**policy_det, "preparationPolicy": "baseline"}, origin="batch", run_id=r["runId"])
        decisions[r["runId"]] = {"deterministic": det["disposition"], "deterministicTriggers": det["eligibleTriggers"], "baseline": base["disposition"],
                                 "conditionalFixRescued": base["conditionalFix"]["rescued"], "modelReview": base["modelReview"]}
        if base["disposition"] == "eligible":
            out["baseline_model"].append(r["runId"])
        if det["disposition"] == "eligible":
            out["deterministic"].append(r["runId"])
            if r["cohorts"].get("C_exceptions"):
                out["frozen_exception"].append(r["runId"])
    return {"members": out, "decisions": decisions}


def fills_of(rows: list, members: list, decisions: dict, restrict: bool) -> tuple[list, dict]:
    ids = set(members)
    fills, cov = [], {"plans": 0, "scorable": 0, "unknown": 0, "replannedNotRejudged": 0}
    for r in rows:
        if r["runId"] not in ids:
            continue
        cov["plans"] += 1
        if not r["scorable"]:
            cov["unknown"] += 1; continue
        cov["scorable"] += 1
        allowed = set(decisions[r["runId"]]["deterministicTriggers"]) if restrict and not r["preopen"].get("replanApplied") else None
        if restrict and r["preopen"].get("replanApplied"):
            cov["replannedNotRejudged"] += 1
        for f in r["replay"]["fills"]:
            if allowed is not None and f.get("trigger") not in allowed:
                continue
            fills.append({"symbol": r["symbol"], "runId": r["runId"], "trigger": f.get("trigger"), "fillIndex": f.get("fillIndex"), "barsHeld": f.get("barsHeld"),
                          "r": f.get("r"), "outcome": f.get("outcome")})
    return fills, cov


async def _sheet_for(c, date: str) -> str | None:
    """The prepared sheet whose PLANNED session is `date` (`params.planFor`) - a walk-forward row's own `session` is the
    session the plan was BUILT FROM (the evening before), never the session it trades."""
    return await c.fetchval("""select w.sweep_id from technique_walkforward w join technique_sweeps s on s.id = w.sweep_id
                               where w.promoted_run_id is not null and (s.params::jsonb)->>'planFor' = $1
                               group by w.sweep_id order by count(*) desc limit 1""", date)


async def build_day(date: str, *, allow_yahoo: bool, pricing: list) -> dict:
    c = await asyncpg.connect(abl._db_url())
    try:
        await c.execute("set transaction read only")
        sheet = await _sheet_for(c, date)
        if not sheet:
            return {"date": date, "status": "no_prepared_sheet"}
        session = dt.date.fromisoformat(date)
        ex = [dict(r) for r in await c.fetch("""select symbol, side, qty, price, commission, ts from executions where portfolio_id=$1
            and ts >= to_timestamp($2/1000.0) and ts < to_timestamp($3/1000.0) order by ts""", EM_BOOK, _ms(session, 4, 0), _ms(session, 20, 0))]
    finally:
        await c.close()
    d = await abl.run(sheet, date, allow_yahoo=allow_yahoo)
    c = await asyncpg.connect(abl._db_url())
    try:
        await c.execute("set transaction read only")
        ids = [r["runId"] for r in d["rows"]]
        rr = await c.fetch("""select id, status, created_at, llm, usage, result->'plan' p, result->'analysis' a, jsonb_array_length(coalesce(result->'passes','[]'::jsonb)) np
                              from technique_runs where id = any($1::text[])""", ids)
    finally:
        await c.close()
    runs = {r["id"]: {"plan": J(r["p"]), "analysis": J(r["a"])} for r in rr}
    policy_det = {"preparationPolicy": "deterministic", "gradeFloor": "B", "conditionalReviewFix": "report"}
    sel = selections(d["rows"], runs, policy_det)
    out_sel = {}
    for name, members in sel["members"].items():
        fills, cov = fills_of(d["rows"], members, sel["decisions"], restrict=(name != "baseline_model"))
        out_sel[name] = {"coverage": cov, "sharedBook": shared_book(fills), "fills": fills}
    reqs = []
    for r in rr:
        u = J(r["usage"]) or {}
        has = any(int(u.get(k) or 0) for k in mc.TOKEN_KEYS)
        reqs.append({"runId": r["id"], "provider": "anthropic", "model": (J(r["llm"]) or {}).get("model"), "at": r["created_at"].date().isoformat(),
                     "status": ("completed" if has else "interrupted"), "attempts": 1, "usage": (u if has else None), "passes": int(r["np"] or 0)})
    # model-rejected candidates and avoided losers stay in the comparison
    rejected = [r for r in d["rows"] if r["runId"] not in sel["members"]["baseline_model"]]
    rej_fills, _ = fills_of(d["rows"], [r["runId"] for r in rejected], sel["decisions"], restrict=False)
    return {"date": date, "status": "ok", "sheet": sheet, "reads": d["reads"], "barsSources": d["barsSources"], "premarketSources": d["premarketSources"],
            "selections": out_sel, "members": {k: len(v) for k, v in sel["members"].items()},
            "onlyDeterministic": sorted({r["symbol"] for r in d["rows"] if r["runId"] in sel["members"]["deterministic"] and r["runId"] not in sel["members"]["baseline_model"]}),
            "onlyModel": sorted({r["symbol"] for r in d["rows"] if r["runId"] in sel["members"]["baseline_model"] and r["runId"] not in sel["members"]["deterministic"]}),
            "modelRejected": {"plans": len(rejected), "replayFills": len(rej_fills), "avoidedLosers": sum(1 for f in rej_fills if float(f["r"] or 0) < 0),
                              "forgoneWinners": sum(1 for f in rej_fills if float(f["r"] or 0) > 0), "sumR": round(sum(float(f["r"] or 0) for f in rej_fills), 3),
                              "label": "PROXY-ONLY independent replay of the plans the model rejected"},
            "conditionalFixRescued": sorted(r["symbol"] for r in d["rows"] if sel["decisions"][r["runId"]]["conditionalFixRescued"]),
            "baselineLiveFunnel": {k: d["baselineFunnel"][k] for k in ("liveFired", "liveRefusedBeforeOrder", "liveOrders", "liveFilled", "replayFired", "replayFilled")},
            "baselineLiveRows": d["baselineFunnel"]["rows"],
            "baselineActual": execution_net(ex), "disputedEvidence": DISPUTED.get(date, []),
            "modelCost": mc.summarize(reqs, table=pricing), "deterministicModelCalls": 0}


async def _runtime_rates() -> dict:
    """The platform's `llm.rates` card from the settings table (read-only). Empty = cost unknown, never invented."""
    c = await asyncpg.connect(abl._db_url())
    try:
        await c.execute("set transaction read only")
        v = await c.fetchval("select value from settings where key = 'llm.rates'")
        v = J(v)
        return v if isinstance(v, dict) else {}
    except Exception:                                      # noqa: BLE001
        return {}
    finally:
        await c.close()


def render(days: list, manifest: dict) -> str:
    L = ["# EM preparation comparison - baseline model vs deterministic vs frozen exception", "",
         f"`{VERSION}`, generated {manifest['generatedAt']} (retrospective, exploratory - Sep 15-18 are fixtures, not a validation sample). ZERO paid model calls. "
         f"Policy `{pp.VERSION}`; replay engine `{abl.VERSION}`; capacity `{CAPACITY['version']}`: {manifest['capacity']['slots']} slots, new entries stop at "
         f"{manifest['capacity']['haltAtR']}R realized, one open position per plan.", "",
         "**Read this first.** Replay figures are UNDERLYING walk-forward R on saved plans - PROXY-ONLY. No historical option quote, depth, contract or quantity exists "
         "for plans that were not selected live, so no replay figure is dollars and none is an option fill. Actual dollars appear only for the live baseline "
         "(execution ledger, after commissions). A difference between two selections is a proxy difference under `capacity-v1`, not the measured value of the model. "
         "No equivalence or profitability claim follows from replan agreement or from replay R.", ""]
    L += ["## Selections per session (shared-book, chronological)", "",
          "| Session | Selection | Plans | Scored | Unknown | Taken | Refused by capacity | Proxy sum R (shared) | Independent sum R | Winners | Losers | Worst drawdown R |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for d in days:
        if d.get("status") != "ok":
            L.append(f"| {d['date']} | - | {d.get('status')} | | | | | | | | | |"); continue
        for k in ("baseline_model", "deterministic", "frozen_exception"):
            s = d["selections"][k]; b = s["sharedBook"]; cv = s["coverage"]
            L.append(f"| {d['date']} | {k} | {cv['plans']} | {cv['scorable']} | {cv['unknown']} | {b['taken']} | {b['refused']} {b['refusedWhy'] or ''} | {b['sumR']:+.3f} | {b['independentSumR']:+.3f} | {b['winners']} | {b['losers']} | {b['worstDrawdownR']:+.3f} |")
    L += ["", "## Live baseline: funnel and actual dollars", "",
          "| Session | Live fired | Refused before an order | Orders | Filled | Replay fired (A) | Replay filled (A) | Actual net after commissions | Fees | Open at cutoff |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for d in days:
        if d.get("status") != "ok":
            continue
        f, a = d["baselineLiveFunnel"], d["baselineActual"]
        L.append(f"| {d['date']} | {f['liveFired']} | {f['liveRefusedBeforeOrder']} | {f['liveOrders']} | {f['liveFilled']} | {f['replayFired']} | {f['replayFilled']} | {a['net']:+.4f} | {a['fees']:.2f} | {', '.join(a['openAtCutoff']) or '-'} |")
    tot = sum(d["baselineActual"]["net"] for d in days if d.get("status") == "ok")
    L += ["", f"Actual baseline total over the listed sessions: **{tot:+.4f}** after commissions, excluding model cost."]
    for d in days:
        for x in d.get("disputedEvidence") or []:
            L += ["", f"> DISPUTED EVIDENCE {d['date']}: {x}"]
    L += ["", "## What the model rejected (kept in the comparison)", "", "| Session | Rejected plans | Replay fills | Avoided losers | Forgone winners | Proxy sum R | Only deterministic selects | Only the model selects | Conditional-fix rescued |",
          "|---|---:|---:|---:|---:|---:|---|---|---|"]
    for d in days:
        if d.get("status") != "ok":
            continue
        m = d["modelRejected"]
        L.append(f"| {d['date']} | {m['plans']} | {m['replayFills']} | {m['avoidedLosers']} | {m['forgoneWinners']} | {m['sumR']:+.3f} | {', '.join(d['onlyDeterministic'][:14]) or '-'}{' ...' if len(d['onlyDeterministic']) > 14 else ''} | {', '.join(d['onlyModel'][:10]) or '-'} | {', '.join(d['conditionalFixRescued']) or 'none'} |")
    L += ["", "## Model cost of the baseline reads (`model-costs-v1`)", "", "| Session | Requests | Without completion | Input tok | Output tok | Cache read | Cache write | Estimated USD | Unknown requests | Deterministic model calls |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for d in days:
        if d.get("status") != "ok":
            continue
        c = d["modelCost"]; t = c["tokens"]
        L.append(f"| {d['date']} | {c['requests']} | {c['requestsWithoutCompletion']} | {t['input']} | {t['output']} | {t['cacheRead']} | {t['cacheWrite']} | {c['estimated']['usd'] if c['estimated']['usd'] is not None else 'unknown'} | {c['unknown']['requests']} | {d['deterministicModelCalls']} |")
    L += ["", "Prices come from the platform's ONE `llm.rates` setting (shared with the Tips cost tool); a model without a rate there is UNKNOWN - a price is never invented. "
          "`llm.rates` carries no effective date, so an estimate is the CURRENT card applied to past tokens, not an invoice. Invoice-verified, estimated, unknown and "
          "subscription allocation are separate categories. One request row per saved run (per-pass rows exist from this build on: `result.modelRequests`).", "",
          "## Manifest", "", "```json", json.dumps(manifest, indent=1, default=str), "```", "",
          "Reproduce: `python -m zargar.tools.em_prep_compare --dates " + ",".join(d["date"] for d in days) + "` (read-only, zero model calls)."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True); ap.add_argument("--no-yahoo", action="store_true"); ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--pricing", default=None, help="JSON file with an llm.rates card or dated rows (default: the runtime's `llm.rates` setting, read-only)")
    a = ap.parse_args(argv)
    pricing = json.load(open(a.pricing, encoding="utf-8")) if a.pricing else asyncio.run(_runtime_rates())
    dates = [x.strip() for x in a.dates.split(",") if x.strip()]
    days = [asyncio.run(build_day(d, allow_yahoo=not a.no_yahoo, pricing=pricing)) for d in dates]
    slots = max(1, int(CAPACITY["maxGrossExposurePct"] // CAPACITY["maxPositionPct"]))
    manifest = {"version": VERSION, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "policyVersion": pp.VERSION, "reviewVersion": pp.REVIEW_VERSION,
                "replayVersion": abl.VERSION, "gradeFloor": "B", "exceptionFeatures": {"RR_TP3_MIN": abl.RR_TP3_MIN, "MIN_TOUCHES": abl.MIN_TOUCHES, "frozen": "2026-09-18"},
                "capacity": {**CAPACITY, "slots": slots, "haltAtR": -(CAPACITY["dailyLossHaltPct"] / CAPACITY["riskPctPerEntry"])}, "sheets": {d["date"]: d.get("sheet") for d in days},
                "pricingSource": "llm.rates", "pricedModels": sorted(pricing) if isinstance(pricing, dict) else len(pricing), "paidModelCalls": 0, "book": EM_BOOK}
    md = render(days, manifest)
    os.makedirs(OUT_DIR, exist_ok=True)
    name = f"{dates[0]}_{dates[-1]}" if len(dates) > 1 else dates[0]
    json.dump({"manifest": manifest, "days": days}, open(os.path.join(OUT_DIR, f"{name}.json"), "w", encoding="utf-8"), indent=1, default=str)
    open(os.path.join(OUT_DIR, f"{name}.md"), "w", encoding="utf-8", newline="\n").write(md)
    print(md if a.stdout else f"wrote {OUT_DIR}/{name}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
