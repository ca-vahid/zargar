"""EM preparation ablation (2026-09-17 EOD review, package C step 1): from the SAVED promote reads of one prepared
sheet, compare - with zero paid model calls - which plans (A) the model selected, (B) deterministic eligibility would
have selected and (C) deterministic eligibility plus predeclared exception features would have selected. Every plan
then goes through the SAME pre-open path the live armer applies (judge the saved triggers against the 09:25 ET
pre-market print; when every trigger is dead, rebuild the plan from the saved bars snapshot around that print) and is
replayed through the walk-forward tracker over the planned session's bars. Order-free research: nothing arms, nothing
trades.

    python -m zargar.tools.em_prep_ablation --sheet <sweep id> --date 2026-09-17 [--out DIR] [--no-yahoo]

Identical causal inputs: each plan's own saved thresholds, its saved bars snapshot (facts + volume profile) and one
pre-market reference per symbol - the JOURNALED print for plans the runner judged live (`TechniquePlanPreopen`), the
last Yahoo pre-market 1m close before 09:25 ET for the others (labelled). Session bars come from the runtime `bars`
table (1m, RTH) and, for symbols the engine never streamed, from Yahoo (research fetch, off the trading engine). A
symbol with no session bars or no pre-market print stays UNKNOWN. Live fills and costs are NOT in this report - they
live in the per-session profitability report; every cohort here is replay-based so the comparison is like-for-like.
Book-level competition is reported only as the peak number of simultaneously open replay fills.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import gzip
import json
import os
import re
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg

from ..domain import Bar
from ..marketstructure.outcome import rows_to_bars
from ..marketstructure.sessions import session_bounds
from ..technique import rulebook as _rb
from ..technique.analysis import AnalysisRequest, compute_facts
from ..technique.plans import build_session_plan
from ..technique.walkforward import build_profile, plan_window, replay_plan

VERSION = "prep-ablation-v3"   # ED-03: descriptive replay, baseline funnel reconciliation, evidence-source split
NY = ZoneInfo("America/New_York")
J = lambda v: (json.loads(v) if isinstance(v, str) else v) or {}   # noqa: E731

# ---------------------------------------------------------------- predeclared exception features (frozen 2026-09-18)
RR_TP3_MIN = 3.0            # the model's most frequent veto: "reward:risk to TP3 below 3.0" (our gate measures at TP2)
MIN_TOUCHES = 2             # T1.2: a one-touch / session-extreme-only level is not a proven level
PCT_LADDER_BASES = ("pct_ladder", "pct", "percent", "percentage")
PREOPEN_ET = (9, 25)

VETO_CATEGORIES = [           # (name, class, regex over the model's FIRST no-trade reason) - specific provenance patterns
    # are tested BEFORE the generic R:R pattern, because a "manufactured R:R" veto also contains the words R:R / R2
    ("target_provenance", "specifiable", re.compile(r"manufactured|pct[- ]ladder|percentage ladder|measured move|artefact|nothing overhead", re.I)),
    ("level_provenance", "specifiable", re.compile(r"not in the FACTS|KEY LEVELS|single[- ]touch|one-touch|single touch|single test|single print|T1\.2", re.I)),
    ("level_distance", "specifiable", re.compile(r"\d+(\.\d+)?% (above|below|from|away)|above last close", re.I)),
    ("volume_floor", "already_encoded_at_fire", re.compile(r"R3\.1|volume floor|below the volume|belowFloor", re.I)),
    ("rr_to_tp3", "specifiable", re.compile(r"reward:risk|R:R|\bR2\b", re.I)),
]
TRIGGER_ID = re.compile(r"\b([bkdrw]\d)\b")


def classify_veto(reason: str) -> tuple[str, str]:
    for name, cls, rx in VETO_CATEGORIES:
        if rx.search(reason or ""):
            return name, cls
    return "unstructured", "unstructured"


def _thresholds(cfg: dict) -> _rb.Thresholds:
    names = {f.name for f in dataclasses.fields(_rb.Thresholds)}
    kw = {k: v for k, v in (cfg.get("thresholds") or {}).items() if k in names}
    try:
        return _rb.Thresholds(**kw)
    except Exception:
        return _rb.DEFAULT_THRESHOLDS


def trigger_features(t: dict, plan: dict) -> dict:
    a = t.get("assessment") or {}
    entry = float((t.get("entry") or {}).get("price") or 0); stop = float((t.get("stop") or {}).get("price") or 0)
    tps = [float(x.get("price")) for x in (t.get("targets") or []) if x.get("price") is not None]
    risk = abs(entry - stop)
    rr3 = t.get("riskRewardTp3")
    if rr3 is None and risk > 0 and len(tps) >= 3:
        rr3 = round(abs(tps[2] - entry) / risk, 2)
    lvl = t.get("level") if isinstance(t.get("level"), dict) else {}
    touches = lvl.get("touches")
    bases = [str(x.get("basis") or "") for x in (t.get("targets") or [])]
    anchored = any(b and b not in PCT_LADDER_BASES for b in bases) if bases else None
    last_close = plan.get("referencePrice") or plan.get("lastClose")
    lp = t.get("levelPrice")
    dist = round(abs(float(lp) - float(last_close)) / float(last_close) * 100, 2) if (lp and last_close) else None
    return {"trigger": t.get("id"), "kind": t.get("kind"), "direction": t.get("direction"), "valid": bool(t.get("valid")),
            "grade": a.get("grade"), "score": a.get("score"), "rr": t.get("riskReward"), "rrTp3": rr3, "touches": touches,
            "targetBases": bases, "targetsAnchored": anchored, "levelDistancePct": dist, "entry": entry, "stop": stop, "targets": tps}


def plan_features(plan: dict) -> dict:
    """Deterministic features of a saved plan's best VALID trigger (the arming candidate)."""
    trig = [t for t in (plan.get("triggers") or []) if t.get("valid")]
    best = max(trig, key=lambda t: ((t.get("assessment") or {}).get("score") or 0), default=None)
    return trigger_features(best, plan) if best else {"valid": False}


def exception_pass(f: dict) -> tuple[bool, list[str]]:
    """Cohort C's predeclared deterministic exception features; an UNKNOWN feature never fails a plan (stated)."""
    fails = []
    if f.get("rrTp3") is not None and f["rrTp3"] < RR_TP3_MIN: fails.append("rr_to_tp3")
    if f.get("touches") is not None and f["touches"] < MIN_TOUCHES: fails.append("level_provenance")
    if f.get("targetsAnchored") is False: fails.append("target_provenance")
    return (not fails), fails


def preopen_judgement(plan: dict, premarket: float, t: _rb.Thresholds) -> dict:
    """Mirror of `PlanArmer.preopen_check` (FIX-04 predicates) over the plan's VALID triggers - judgement only."""
    prev = float(plan.get("referencePrice") or plan.get("lastClose") or 0)
    rows = []; alive = 0
    for tg in plan.get("triggers") or []:
        if not tg.get("valid"):
            continue
        entry = float(tg["entry"]["price"]); stop = float(tg["stop"]["price"]); risk = abs(entry - stop)
        short = tg.get("direction") == "short"; last = premarket; verdict = "ok"
        if tg.get("kind") in ("bounce", "reject"):
            through = (last > stop) if short else (last < stop)
            past = (last >= entry) if short else (last <= entry)
            verdict = "gapped_through" if through else ("gapped_past" if past else "ok")
        else:
            if (last < entry) if short else (last > entry):
                verdict = "gapped_past"
        if verdict == "ok" and prev and risk > 0 and abs(last - prev) > t.gap_void_r * risk:
            verdict = "gap_void"
        alive += verdict == "ok"
        rows.append({"trigger": tg["id"], "kind": tg["kind"], "verdict": verdict})
    pct = ((premarket - prev) / prev * 100) if prev else 0.0
    return {"rows": rows, "reference": prev, "gapPct": round(pct, 3), "replan": bool(rows) and alive == 0}


def _db_url() -> str:
    url = os.environ.get("ZARGAR_DATABASE_URL")
    if not url:
        for p in (Path("C:/Cursor/zargar/backend/.env"), Path(".env")):
            if p.exists():
                m = re.search(r"^ZARGAR_DATABASE_URL=(.+)$", p.read_text(encoding="utf-8"), re.M)
                if m: url = m.group(1).strip().strip('"'); break
    if not url:
        raise SystemExit("ZARGAR_DATABASE_URL is not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _session_bars(c, symbol: str, date: str, *, allow_yahoo: bool) -> tuple[list[Bar], str]:
    o, cl = session_bounds(date)
    rows = await c.fetch("select ts, open, high, low, close, volume from bars where symbol=$1 and tf='1m' and ts >= $2 and ts < $3 order by ts", symbol, o, cl)
    if len(rows) >= 300:
        return [Bar(symbol=symbol, tf="1m", ts=int(r["ts"]), open=float(r["open"]), high=float(r["high"]), low=float(r["low"]), close=float(r["close"]), volume=float(r["volume"] or 0), source="stored") for r in rows], "stored"
    if not allow_yahoo:
        return [], "none"
    try:
        from ..marketstructure.history import fetch_session
        bars = await fetch_session(symbol, "1m", date)
        return (bars, "yahoo") if len(bars) >= 300 else ([], "none")
    except Exception as exc:   # research fetch: a failure is an unknown, never a fabricated bar
        return [], f"none ({str(exc)[:60]})"


async def _premarket_yahoo(symbol: str, date: str) -> float | None:
    try:
        from ..marketstructure.history import fetch_extended_session
        y, m, d = (int(x) for x in date.split("-"))
        cutoff = int(dt.datetime(y, m, d, PREOPEN_ET[0], PREOPEN_ET[1], tzinfo=NY).timestamp() * 1000)
        bars = [b for b in await fetch_extended_session(symbol, "1m", date) if b.ts < cutoff]
        return float(bars[-1].close) if bars else None
    except Exception:
        return None


def _replay_summary(rep: dict, bars: list[Bar] | None = None) -> dict:
    idx = {b.ts: i for i, b in enumerate(bars or [])}
    trig = [t for t in rep.get("triggers") or [] if t.get("valid")]
    fired = [t for t in trig if t.get("status") == "fired" and t.get("sim")]
    sims = [t["sim"] for t in fired]
    filled = [s for s in sims if s.get("filled")]
    return {"validTriggers": len(trig), "fired": len(fired), "filled": len(filled),
            "outcomes": dict(Counter(str(s.get("outcome")) for s in filled)),
            "sumR": round(sum(float(s.get("rMultiple") or 0) for s in filled), 3),
            "statuses": dict(Counter(str(t.get("status")) for t in trig)),
            "fills": [{"trigger": t["id"], "kind": t.get("kind"), "fillIndex": (s.get("fillIndex") if s.get("fillIndex") is not None else idx.get(t.get("firedTs"))), "barsHeld": s.get("barsHeld"), "outcome": s.get("outcome"), "r": s.get("rMultiple")} for t, s in zip(fired, sims) if s.get("filled")]}


def _cohort_stats(rows: list[dict]) -> dict:
    known = [r for r in rows if r["scorable"]]
    fills = [f for r in known for f in r["replay"]["fills"]]
    rs = [float(f["r"] or 0) for f in fills]
    outcomes = Counter(str(f["outcome"]) for f in fills)
    spans = [(f["fillIndex"], f["fillIndex"] + int(f["barsHeld"] or 0)) for f in fills if f.get("fillIndex") is not None]
    peak = max((sum(1 for a, b in spans if a <= i <= b) for i in range(0, 391)), default=0)
    return {"plans": len(rows), "scorable": len(known), "unknown": len(rows) - len(known),
            "replanned": sum(1 for r in known if r["preopen"].get("replanApplied")),
            "fired": sum(r["replay"]["fired"] for r in known), "filled": len(fills), "outcomes": dict(outcomes),
            "winners": sum(1 for x in rs if x > 0), "losers": sum(1 for x in rs if x < 0),
            "sumR": round(sum(rs), 3), "meanR": (round(sum(rs) / len(rs), 3) if rs else None),
            "peakSimultaneousOpen": peak, "sharedBookModel": "none - independent per-plan replays; capital, slots and order competition are NOT modeled (unscorable here)",
            "premarketSources": dict(Counter(r["preopen"]["premarketSource"] for r in rows)),
            "readTokens": {k: sum(int((r["usage"] or {}).get(k) or 0) for r in rows) for k in ("input", "output", "cacheRead", "cacheWrite")}}


async def run(sheet: str, date: str, *, allow_yahoo: bool) -> dict:
    c = await asyncpg.connect(_db_url())
    try:
        await c.execute("set statement_timeout = 30000")
        wf = await c.fetch("select symbol, session, promoted_run_id from technique_walkforward where sweep_id=$1 and promoted_run_id is not null", sheet)
        ids = [r["promoted_run_id"] for r in wf]
        runs = await c.fetch("select id, symbol, result, config, usage, created_at from technique_runs where id = any($1::text[])", ids)
        o_ms, _ = session_bounds(date)
        pre_ev = await c.fetch("""select payload->>'symbol' sym, payload->>'runId' run_id, (payload->>'premarket')::float pm, (payload->>'replan')::bool rp
                                  from events where type='TechniquePlanPreopen' and ts >= to_timestamp($1/1000.0) - interval '30 minutes' and ts < to_timestamp($1/1000.0) + interval '5 minutes'""", o_ms)
        live_pm = {r["sym"]: (r["pm"], r["rp"]) for r in pre_ev}
        live_disarmed = {r["s"] for r in await c.fetch("""select payload->>'symbol' s from events where type='TechniquePlanDisarmed' and payload->>'reason' like 'pre-open re-plan%'
                                                         and ts >= to_timestamp($1/1000.0) - interval '30 minutes' and ts < to_timestamp($1/1000.0) + interval '5 minutes'""", o_ms)}
        out_rows = []; bars_cache: dict[str, tuple[list[Bar], str]] = {}; pm_cache: dict[str, tuple[float | None, str]] = {}
        for r in sorted(runs, key=lambda x: x["symbol"]):
            sym = r["symbol"]; res = J(r["result"]); cfg = J(r["config"]); plan = res.get("plan") or {}; an = res.get("analysis") or {}
            t = _thresholds(cfg)
            feats = plan_features(plan)
            reason0 = (an.get("noTradeReasons") or [""])[0]
            veto_cat, veto_cls = classify_veto(reason0) if an.get("verdict") != "setup" else (None, None)
            named = None
            if veto_cat:
                m = TRIGGER_ID.search(reason0)
                nt = next((x for x in (plan.get("triggers") or []) if m and x.get("id") == m.group(1)), None)
                named = trigger_features(nt, plan) if nt else None
            # ---- pre-market reference: journaled when the runner judged this symbol live, Yahoo otherwise
            if sym not in pm_cache:
                if sym in live_pm and live_pm[sym][0]:
                    pm_cache[sym] = (float(live_pm[sym][0]), "journal")
                else:
                    v = await _premarket_yahoo(sym, date) if allow_yahoo else None
                    pm_cache[sym] = (v, "yahoo" if v else "none")
            premarket, pm_src = pm_cache[sym]
            if sym not in bars_cache:
                bars_cache[sym] = await _session_bars(c, sym, date, allow_yahoo=allow_yahoo)
            sbars, bsrc = bars_cache[sym]
            # ---- saved bars snapshot -> facts / profile (identical causal inputs)
            by_tf: dict[str, list[Bar]] = {}
            aid = cfg.get("barsAssetId")
            if aid:
                blob = await c.fetchval("select data from chat_assets where id=$1", aid)
                if blob:
                    snap = json.loads(gzip.decompress(blob).decode("utf-8"))
                    by_tf = {tf: rows_to_bars(sym, tf, rows) for tf, rows in (snap.get("bars") or {}).items()}
            ttf = plan.get("triggerTf") or "1m"; stfs = tuple(plan.get("structureTfs") or ("1h", "30m"))
            built_ms = int(plan.get("builtFromMs") or session_bounds(plan.get("builtFromSession") or date)[1])
            preopen = {"premarket": premarket, "premarketSource": pm_src, "replanApplied": False, "liveReplanned": sym in live_disarmed,
                       "liveJudged": sym in live_pm}
            traded_plan = plan
            if premarket and plan.get("triggers"):
                jd = preopen_judgement(plan, premarket, t)
                preopen.update({"gapPct": jd["gapPct"], "verdicts": {x["trigger"]: x["verdict"] for x in jd["rows"]}, "replanWanted": jd["replan"]})
                if jd["replan"] and by_tf:
                    try:
                        req = AnalysisRequest(symbol=sym, as_of_ms=built_ms, primary_tf=ttf, context_tfs=stfs, thresholds=t)
                        facts = compute_facts(req, by_tf, [])
                        new_plan = build_session_plan(facts, thresholds=t, structure_tfs=list(stfs), trigger_tf=ttf, reference_price=premarket).to_dict()
                        if int(new_plan.get("validTriggers") or 0) > 0:
                            traded_plan = new_plan; preopen["replanApplied"] = True
                            preopen["replanTriggers"] = [{"id": x["id"], "kind": x["kind"], "level": x.get("levelPrice")} for x in new_plan.get("triggers") or [] if x.get("valid")]
                        else:
                            preopen["replanEmpty"] = True
                    except Exception as exc:
                        preopen["replanError"] = str(exc)[:120]
            replay = {"validTriggers": 0, "fired": 0, "filled": 0, "outcomes": {}, "sumR": 0.0, "statuses": {}, "fills": []}
            scorable = bool(sbars) and bool(premarket) and bool(traded_plan.get("triggers"))
            if scorable:
                prof = None
                if by_tf:
                    try:
                        prof = build_profile(plan_window(by_tf, built_ms).get(ttf) or [])
                    except Exception:
                        prof = None
                replay = _replay_summary(replay_plan(traded_plan, sbars, thresholds=t, profile=prof), sbars)
            ok, fails = exception_pass(feats)
            grade_ab = bool(feats.get("valid")) and (feats.get("grade") in ("A", "B"))
            out_rows.append({"symbol": sym, "runId": r["id"], "verdict": an.get("verdict"), "confidence": an.get("confidence"),
                             "vetoReason": reason0[:220] if veto_cat else None, "vetoCategory": veto_cat, "vetoClass": veto_cls,
                             "vetoNamedTrigger": named, "features": feats, "exceptionPass": ok, "exceptionFails": fails,
                             "cohorts": {"A_model": an.get("verdict") == "setup", "B_valid": bool(feats.get("valid")), "B_gradeB": grade_ab, "C_exceptions": grade_ab and ok},
                             "barsSource": bsrc, "scorable": scorable, "preopen": preopen, "replay": replay, "usage": J(r["usage"])})
        cohorts = {k: _cohort_stats([x for x in out_rows if x["cohorts"][k]]) for k in ("A_model", "B_valid", "B_gradeB", "C_exceptions")}
        # ED-03: reconcile the A replay with the ACTUAL live funnel of the same symbols from the immutable journal
        live = await c.fetch("""select e.payload->>'symbol' sym, e.type, coalesce(e.payload->>'reason','') reason, e.payload->>'trigger' trig
                                from events e join technique_runs r on r.id = e.aggregate_id
                                where r.technique='enhanced_market' and e.ts >= to_timestamp($1/1000.0) and e.ts < to_timestamp($1/1000.0) + interval '7 hours'
                                and e.type in ('TechniquePlanTriggerFired','TechniquePlanTriggerSkipped','TechniquePlanOrderResult','TechniquePlanPositionOpened')""", o_ms)
        funnel: dict[str, dict] = {}
        for e in live:
            f = funnel.setdefault(e["sym"], {"fired": 0, "refusedBeforeOrder": 0, "orders": 0, "filled": 0, "refusals": []})
            if e["type"] == "TechniquePlanTriggerFired": f["fired"] += 1
            elif e["type"] == "TechniquePlanTriggerSkipped" and (e["reason"].startswith("contract skipped") or "budget" in e["reason"]):
                f["refusedBeforeOrder"] += 1; f["refusals"].append(e["reason"][:60])
            elif e["type"] == "TechniquePlanOrderResult": f["orders"] += 1
            elif e["type"] == "TechniquePlanPositionOpened": f["filled"] += 1
        a_syms = [x["symbol"] for x in out_rows if x["cohorts"]["A_model"]]
        recon = []
        for x in out_rows:
            if not x["cohorts"]["A_model"]: continue
            lf = funnel.get(x["symbol"], {"fired": 0, "refusedBeforeOrder": 0, "orders": 0, "filled": 0, "refusals": []})
            if lf["fired"] or x["replay"]["fired"]:
                recon.append({"symbol": x["symbol"], "liveFired": lf["fired"], "liveRefusedBeforeOrder": lf["refusedBeforeOrder"], "liveOrders": lf["orders"],
                              "liveFilled": lf["filled"], "liveRefusals": lf["refusals"], "replayFired": x["replay"]["fired"], "replayFilled": x["replay"]["filled"],
                              "replayOutcomes": x["replay"]["outcomes"]})
        baseline = {"liveFired": sum(funnel.get(sy, {}).get("fired", 0) for sy in a_syms), "liveRefusedBeforeOrder": sum(funnel.get(sy, {}).get("refusedBeforeOrder", 0) for sy in a_syms),
                    "liveOrders": sum(funnel.get(sy, {}).get("orders", 0) for sy in a_syms), "liveFilled": sum(funnel.get(sy, {}).get("filled", 0) for sy in a_syms),
                    "replayFired": cohorts["A_model"]["fired"], "replayFilled": cohorts["A_model"]["filled"], "rows": recon,
                    "note": "the replay fills every fired trigger on the underlying: no contract selection, spread or budget refusal, entry timeout, shares fallback, sizing or slot competition - live filled counts are therefore lower by construction"}
        vetoes = [x for x in out_rows if x["vetoCategory"]]
        veto_table = Counter((x["vetoCategory"], x["vetoClass"]) for x in vetoes)
        agree = Counter()
        for x in vetoes:
            f = x["vetoNamedTrigger"] or x["features"]
            cat = x["vetoCategory"]
            if cat == "rr_to_tp3": agree[(cat, f.get("rrTp3") is not None and f["rrTp3"] < RR_TP3_MIN, "named" if x["vetoNamedTrigger"] else "best")] += 1
            elif cat == "level_provenance": agree[(cat, f.get("touches") is not None and f["touches"] < MIN_TOUCHES, "named" if x["vetoNamedTrigger"] else "best")] += 1
            elif cat == "target_provenance": agree[(cat, f.get("targetsAnchored") is False, "named" if x["vetoNamedTrigger"] else "best")] += 1
        named_valid = sum(1 for x in vetoes if x["vetoNamedTrigger"] and x["vetoNamedTrigger"].get("valid"))
        named_invalid = sum(1 for x in vetoes if x["vetoNamedTrigger"] and not x["vetoNamedTrigger"].get("valid"))
        newly = [x for x in out_rows if x["verdict"] != "setup" and x["cohorts"]["C_exceptions"]]
        excluded = [x for x in out_rows if x["verdict"] == "setup" and not x["cohorts"]["C_exceptions"]]
        fidelity = Counter()
        for x in out_rows:
            if x["preopen"].get("liveJudged"):
                fidelity[("live replanned" if x["preopen"]["liveReplanned"] else "live kept", "offline replanned" if x["preopen"]["replanApplied"] else "offline kept")] += 1
        return {"version": VERSION, "sheet": sheet, "date": date, "generatedAt": dt.datetime.now(NY).isoformat(timespec="seconds"),
                "features": {"RR_TP3_MIN": RR_TP3_MIN, "MIN_TOUCHES": MIN_TOUCHES, "pctLadderBases": list(PCT_LADDER_BASES)},
                "reads": len(out_rows), "barsSources": dict(Counter(x["barsSource"].split(" (")[0] for x in out_rows)),
                "premarketSources": dict(Counter(x["preopen"]["premarketSource"] for x in out_rows)),
                "preopenFidelity": [{"live": k[0], "offline": k[1], "n": n} for k, n in fidelity.items()],
                "cohorts": cohorts, "baselineFunnel": baseline,
                "vetoCategories": [{"category": k[0], "class": k[1], "n": n} for k, n in veto_table.most_common()],
                "vetoNamedTrigger": {"namedValid": named_valid, "namedInvalid": named_invalid, "unnamed": len(vetoes) - named_valid - named_invalid},
                "vetoFeatureAgreement": [{"category": k[0], "featureReproducesVeto": k[1], "against": k[2], "n": n} for k, n in sorted(agree.items(), key=lambda kv: (kv[0][0], not kv[0][1]))],
                "newlyEligibleC": [{"symbol": x["symbol"], "grade": x["features"].get("grade"), "kind": x["features"].get("kind"), "rrTp3": x["features"].get("rrTp3"), "vetoCategory": x["vetoCategory"],
                                    "replanned": x["preopen"].get("replanApplied"), "replay": {k: x["replay"][k] for k in ("fired", "filled", "outcomes", "sumR")}, "scorable": x["scorable"]} for x in newly],
                "modelSetupsFailingC": [{"symbol": x["symbol"], "fails": x["exceptionFails"], "rrTp3": x["features"].get("rrTp3"), "touches": x["features"].get("touches"),
                                         "replay": {k: x["replay"][k] for k in ("fired", "filled", "outcomes", "sumR")}} for x in excluded],
                "rows": out_rows}
    finally:
        await c.close()


def render(d: dict) -> str:
    L = [f"# EM preparation ablation - {d['date']} (sheet `{d['sheet'][:8]}`, {d['version']}, generated {d['generatedAt']})", "",
         "Order-free replay of every SAVED promote read of the sheet: each plan is judged against the 09:25 ET pre-market print exactly as the live "
         "armer judges it (rebuilt from its saved bars snapshot around that print when every trigger is dead), then replayed through the walk-forward "
         "tracker over the session's bars with its own saved thresholds and volume profile. ZERO paid model calls. Live fills and costs are NOT here "
         "(see `research/profitability/<date>.md`); every cohort is replay-based so the comparison is like-for-like. Unknown stays unknown: a plan "
         "without session bars or a pre-market print is counted, not scored.", "",
         f"Reads: {d['reads']} | session bars: {d['barsSources']} | pre-market print: {d['premarketSources']}", "",
         "Pre-open fidelity (plans the runner judged live vs this offline mirror): " + "; ".join(f"{x['live']} / {x['offline']}: {x['n']}" for x in d["preopenFidelity"]), "",
         "## Cohorts (replay-based)", "",
         "| cohort | plans | scored | replanned | fired | filled | winners | losers | sum R | mean R | outcomes | peak open | read tokens (in/out/cacheRead) |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|"]
    names = {"A_model": "A model-selected (verdict setup)", "B_valid": "B any deterministic valid trigger", "B_gradeB": "B grade A/B valid trigger",
             "C_exceptions": f"C = B grade A/B + exceptions (R:R to TP3 >= {RR_TP3_MIN}, level touches >= {MIN_TOUCHES}, anchored targets)"}
    for k, s in d["cohorts"].items():
        tk = s["readTokens"]
        L.append(f"| {names[k]} | {s['plans']} | {s['scorable']} | {s['replanned']} | {s['fired']} | {s['filled']} | {s['winners']} | {s['losers']} | {s['sumR']} | {s['meanR']} | {s['outcomes']} | {s['peakSimultaneousOpen']} | {tk['input']:,}/{tk['output']:,}/{tk['cacheRead']:,} |")
    L += ["", "Read tokens are the recorded usage of the model reads that produced each cohort's plans; cohorts B and C need NONE of them "
          "(the plan is built before the model). Tokens are usage categories, not an invoice, and proxy R is never converted into a token-dollar return.", "",
          "**What the cohort rows are (ED-03):** independently simulated UNDERLYING trades per plan - no option selection, no executable fills, no fees, "
          "no shared capital / slot / order competition (unmodeled, hence unscorable as economics). A difference between two cohort rows is an "
          "'underlying independent-replay cohort difference under these assumptions', not the measured economic value of the model or of a policy. "
          "Pre-market evidence per cohort: " + "; ".join(f"{k}: {v['premarketSources']}" for k, v in d["cohorts"].items()) + ".", "",
          "## Baseline funnel reconciliation (cohort A symbols: live journal vs this replay)", "",
          f"Live: fired {d['baselineFunnel']['liveFired']}, refused before an order {d['baselineFunnel']['liveRefusedBeforeOrder']}, orders {d['baselineFunnel']['liveOrders']}, "
          f"positions opened {d['baselineFunnel']['liveFilled']} | Replay: fired {d['baselineFunnel']['replayFired']}, filled {d['baselineFunnel']['replayFilled']}. {d['baselineFunnel']['note']}", "",
          "| symbol | live fired | live refused pre-order | live orders | live filled | replay fired | replay filled | replay outcomes | live refusal |", "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for r in d["baselineFunnel"]["rows"]:
        L.append(f"| {r['symbol']} | {r['liveFired']} | {r['liveRefusedBeforeOrder']} | {r['liveOrders']} | {r['liveFilled']} | {r['replayFired']} | {r['replayFilled']} | {r['replayOutcomes']} | {'; '.join(r['liveRefusals'])[:70]} |")
    L += ["",
          "## What the model vetoed (first no-trade reason, classified)", "", "| category | class | n |", "|---|---|---:|"]
    for v in d["vetoCategories"]: L.append(f"| {v['category']} | {v['class']} | {v['n']} |")
    nt = d["vetoNamedTrigger"]
    L += ["", f"The veto names a specific trigger in {nt['namedValid'] + nt['namedInvalid']} of the rejections; in {nt['namedInvalid']} the named trigger is one the "
          f"plan itself already marks INVALID (the model argued about an idea the deterministic builder had already declined) and in {nt['namedValid']} it is a valid trigger.", "",
          "Does the deterministic feature reproduce the veto, measured on the trigger the model named (else the best valid one)?", "",
          "| category | feature reproduces the veto | measured on | n |", "|---|---|---|---:|"]
    for v in d["vetoFeatureAgreement"]: L.append(f"| {v['category']} | {'yes' if v['featureReproducesVeto'] else 'NO'} | {v['against']} | {v['n']} |")
    L += ["", f"## Newly eligible under C (model said no_setup, C says eligible): {len(d['newlyEligibleC'])}", "",
          "| symbol | grade | kind | R:R to TP3 | model veto category | replanned | replay fired/filled | outcomes | sum R |", "|---|---|---|---:|---|---|---|---|---:|"]
    for x in d["newlyEligibleC"]:
        L.append(f"| {x['symbol']} | {x['grade']} | {x['kind']} | {x['rrTp3']} | {x['vetoCategory']} | {'yes' if x['replanned'] else 'no'} | {x['replay']['fired']}/{x['replay']['filled']}{'' if x['scorable'] else ' (unknown)'} | {x['replay']['outcomes']} | {x['replay']['sumR']} |")
    L += ["", f"## Model setups that C would have EXCLUDED: {len(d['modelSetupsFailingC'])}", "", "| symbol | failing features | R:R to TP3 | touches | replay fired/filled | outcomes | sum R |", "|---|---|---:|---:|---|---|---:|"]
    for x in d["modelSetupsFailingC"]:
        L.append(f"| {x['symbol']} | {', '.join(x['fails'])} | {x['rrTp3']} | {x['touches']} | {x['replay']['fired']}/{x['replay']['filled']} | {x['replay']['outcomes']} | {x['replay']['sumR']} |")
    L += ["", "## What could be wrong", "",
          "- Replay outcomes are underlying-based R from the walk-forward simulator (bar-close stops, 0.25R brake, 30/40/15 ladder): no option premium, "
          "no contract liquidity, no sizing, no daily budget, no slot competition - the same limits as every sweep. Filled counts are not tradeable counts.",
          "- The offline pre-open mirror uses the JOURNALED pre-market print where the runner judged the plan live and the last Yahoo pre-market 1m close "
          "before 09:25 ET otherwise; the live runner used a quote at that instant. The fidelity line above says how often the mirror's replan decision "
          "matched the live one on the plans that were judged live.",
          "- Exception features are frozen guesses at what the model's prose encodes; an unknown feature (missing touches / target basis) never fails a plan, "
          "which biases C toward inclusion. Read the agreement table before trusting C.",
          "- Symbols without stored bars were fetched from Yahoo for research; a symbol still without bars or a print is unknown, never a non-fill.",
          "- A feature that reproduces a veto reproduces that veto's stated reason, not the model's whole-plan eligibility decision.",
          "- One session, and the exception features were written after reading this session's vetoes: scoring them on the same session is exploratory "
          "by construction. Future sessions must be prospective or held out. Nothing here is a verdict on the model's selection value."]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True); ap.add_argument("--date", required=True)
    ap.add_argument("--out", default="../docs/techniques/enhanced-market/research/prep-ablation")
    ap.add_argument("--no-yahoo", action="store_true", help="never fetch research bars; symbols without stored bars stay unknown")
    a = ap.parse_args()
    d = asyncio.run(run(a.sheet, a.date, allow_yahoo=not a.no_yahoo))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.date}.json").write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
    (out / f"{a.date}.md").write_text(render(d), encoding="utf-8")
    print(render(d).split("## Newly eligible")[0])
    print("written", out / f"{a.date}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
