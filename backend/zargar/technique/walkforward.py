"""Walk-forward validation of session plans (spec §6 of the walk-forward plan).

    for each session N: plan = build_session_plan(as_of = close of N)
                        replay(plan, bars of N+1)        # bar by bar, no look-ahead

`TriggerTracker` evaluates one trigger incrementally — the same object scores a
plan against historical bars here and watches live bars in `arming.py`, so
validation and live behaviour cannot drift apart. Fills and exits go through
`outcome.simulate_plan` (the backtester's and the outcome loop's scorer).

Two metric families are kept apart on purpose:
  * level quality  — did price *respect* each planned level? (no trades needed)
  * trigger quality — trigger rate, fill rate, win rate, R, per kind / window / tf
Each rule that is ours (R6 gating, gap rules) is also evaluated *without* itself
(counterfactuals) so its value is measured, not assumed.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from ..domain import Bar
from .analysis import SESSIONS_FOR_TF, AnalysisRequest, compute_facts
from .candles import is_decisive
from .history import fetch_window
from .levels import session_key
from .outcome import simulate_plan
from .plans import SessionPlan, build_session_plan
from .rulebook import (
    DEFAULT_THRESHOLDS,
    PRIME_WINDOWS,
    Thresholds,
    session_bounds,
    session_date,
    session_window,
)
from .volume import VolumeProfile, build_profile, relative_volume

# A claim verdict needs at least this many fires (or tested levels) on each side.
MIN_CLAIM_FIRES = 5
MIN_CLAIM_TESTED = 20

# --- level respect / TriggerTracker / score_trigger ------------------------------
# Moved to the shared library (platform plan phase 1, 2026-08-27): one state
# machine for live, plan and sweep, parameterised by MarketRules.
from ..marketstructure.tracker import TriggerTracker, level_respect, score_trigger  # noqa: E402,F401

def replay_plan(plan: dict, bars: list[Bar], *, thresholds: Thresholds | None = None,
                profile: VolumeProfile | None = None, include_invalid: bool = False) -> dict:
    """Replay one session against a plan. Returns per-trigger results (with
    counterfactuals) plus level respect and a summary."""
    t = thresholds or DEFAULT_THRESHOLDS
    prev_close = float(plan.get("referencePrice") or plan.get("lastClose") or 0) or None
    out_triggers: list[dict] = []
    if not bars:
        return {"session": plan.get("planFor"), "bars": 0, "triggers": [], "levels": [],
                "summary": {"note": "no bars for the planned session (holiday / no data)"}}
    open_px = bars[0].open
    gap_pct = round((open_px - prev_close) / prev_close * 100, 3) if prev_close else None
    for tg in plan.get("triggers") or []:
        if not tg.get("valid") and not include_invalid:
            out_triggers.append({"id": tg["id"], "kind": tg["kind"], "valid": False,
                                 "status": "not_tradeable", "reasons": tg.get("noTradeReasons")})
            continue
        variants = {
            "base": TriggerTracker(tg, t, profile, True, True, prev_close),
            "noWindowGate": TriggerTracker(tg, t, profile, False, True, prev_close),
            "noGapRules": TriggerTracker(tg, t, profile, True, False, prev_close),
        }
        for i, b in enumerate(bars):
            for v in variants.values():
                v.on_bar(b, i)
        scored = {k: score_trigger(v, bars, thresholds=t) for k, v in variants.items()}
        base = scored["base"]
        out_triggers.append({
            # validity comes from the PLAN side: an includeInvalid replay must not
            # relabel a no-trade trigger as tradeable (it cost the 08-27 gate audit
            # two wrong tallies)
            "id": tg["id"], "kind": tg["kind"], "valid": bool(tg.get("valid")), "levelPrice": tg["levelPrice"],
            "entry": tg["entry"]["price"], "stop": tg["stop"]["price"], "riskReward": tg["riskReward"],
            "confluences": tg.get("confluences"), "confidence": tg.get("confidence"),
            **base,
            "counterfactual": {"noWindowGate": scored["noWindowGate"], "noGapRules": scored["noGapRules"]},
        })
    levels = level_respect(plan.get("levels") or [], bars, thresholds=t)
    fired = [x for x in out_triggers if x.get("status") == "fired"]
    sims = [x["sim"] for x in fired if x.get("sim")]
    summary = {
        "gapPct": gap_pct, "open": open_px, "close": bars[-1].close,
        "triggers": len([x for x in out_triggers if x.get("valid")]),
        "fired": len(fired),
        "wins": sum(1 for s in sims if (s.get("rMultiple") or 0) > 0),
        "sumR": round(sum(s.get("rMultiple") or 0 for s in sims), 4),
        "levelsRespected": sum(1 for l in levels if l["status"] == "respected"),
        "levelsBroken": sum(1 for l in levels if l["status"] in ("broken", "flipped")),
        "levelsFlipped": sum(1 for l in levels if l["status"] == "flipped"),
        "levelsUntested": sum(1 for l in levels if l["status"] == "untested"),
        "statuses": {x.get("status"): 1 for x in out_triggers},
    }
    return {"session": plan.get("planFor"), "bars": len(bars), "triggers": out_triggers, "levels": levels,
            "summary": summary}


# --- sweep ----------------------------------------------------------------------------


def _by_session(bars: list[Bar]) -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = defaultdict(list)
    for b in bars:
        out[session_date(b.ts)].append(b)
    return dict(out)


def sweep_window_ms(start: str, end: str, *, warmup_sessions: int = 6, tfs: tuple[str, ...] = ()) -> tuple[int, int]:
    """[from, to] in ms that a sweep over plan days [start, end] needs: enough
    history before `start` for the deepest timeframe window `analyze()` would use
    (`SESSIONS_FOR_TF`, sized like `history.fetch_recent`), and the session AFTER
    `end` (a week covers any holiday run) because the last plan is scored on it."""
    o_ms, _ = session_bounds(start)
    _, e_ms = session_bounds(end)
    sessions = max([warmup_sessions] + [SESSIONS_FOR_TF.get(tf, 5) for tf in tfs])
    cal_days = max(2, int(sessions * 1.6) + 2)
    return o_ms - cal_days * 86_400_000, e_ms + 7 * 86_400_000


def plan_window(bars_by_tf: dict[str, list[Bar]], close_ms: int) -> dict[str, list[Bar]]:
    """Exactly the bars a live `analyze()` at `close_ms` would see: per timeframe,
    the last `SESSIONS_FOR_TF[tf]` sessions ending at the close (what
    `gather_bars` -> `fetch_recent` returns). Validation and the promoted plan run
    must be built from the same window or their plans drift apart."""
    out: dict[str, list[Bar]] = {}
    for tf, bars in bars_by_tf.items():
        upto = [b for b in bars if b.ts <= close_ms]
        if not upto:
            continue
        keys: list[str] = []
        for b in upto:
            k = session_key(b.ts)
            if not keys or keys[-1] != k:
                keys.append(k)
        keep = set(keys[-SESSIONS_FOR_TF.get(tf, 5):])
        out[tf] = [b for b in upto if session_key(b.ts) in keep]
    return out


async def fetch_symbol_bars(symbol: str, start: str, end: str, *, structure_tfs: list[str], trigger_tf: str,
                            warmup_sessions: int = 6,
                            bars_override: dict[str, list[Bar]] | None = None) -> dict[str, list[Bar]]:
    """The I/O half of a sweep: every timeframe's bars for one symbol (the
    structure tfs fetch concurrently; `history._sem` bounds Yahoo traffic)."""
    tfs = list(structure_tfs) + [trigger_tf]
    lo, hi = sweep_window_ms(start, end, warmup_sessions=warmup_sessions, tfs=tuple(tfs))

    async def one(tf: str) -> list[Bar]:
        if bars_override and tf in bars_override:
            return list(bars_override[tf])
        return await fetch_window(symbol, tf, lo, hi)

    got = await asyncio.gather(*(one(tf) for tf in tfs))
    return dict(zip(tfs, got))


def compute_symbol_rows(symbol: str, start: str, end: str, *, structure_tfs: list[str], trigger_tf: str,
                        thresholds: Thresholds, bars_by_tf: dict[str, list[Bar]], warmup_sessions: int = 6,
                        include_invalid: bool = False, progress=None) -> list[dict]:
    """The CPU half: walk [start, end] for one symbol — one row per (plan session
    N, scored on N+1). Pure and picklable, so a sweep can farm symbols out to a
    process pool; `progress(symbol, day, n_rows)` (sync) is optional."""
    trig = bars_by_tf.get(trigger_tf) or []
    if not trig:
        return [{"symbol": symbol, "session": None, "error": f"no {trigger_tf} bars"}]
    sessions = _by_session(trig)
    keys = sorted(sessions)
    rows: list[dict] = []
    for i, day in enumerate(keys):
        if day < start or day > end or i + 1 >= len(keys):
            continue
        nxt = keys[i + 1]
        as_of = session_bounds(day)[1]          # 16:00 ET of N: outside the session, plan mode
        window = plan_window(bars_by_tf, as_of)  # == what `analyze()` at that close would fetch
        if not window.get(trigger_tf):
            continue
        req = AnalysisRequest(symbol=symbol, as_of_ms=as_of, primary_tf=trigger_tf,
                              context_tfs=tuple(structure_tfs), thresholds=thresholds)
        facts = compute_facts(req, window, [])
        plan = build_session_plan(facts, thresholds=thresholds, structure_tfs=structure_tfs,
                                  trigger_tf=trigger_tf).to_dict()
        next_bars = sessions[nxt]
        # same relative-volume baseline the promoted run's scorecard uses (its 1m snapshot)
        prof = build_profile(window[trigger_tf])
        rep = replay_plan(plan, next_bars, thresholds=thresholds, profile=prof, include_invalid=include_invalid)
        rows.append({"symbol": symbol, "session": day, "planFor": nxt, "plan": _slim_plan(plan), "result": rep})
        if progress:
            progress(symbol, day, len(rows))
    return rows


async def run_symbol(symbol: str, start: str, end: str, *, structure_tfs: list[str], trigger_tf: str,
                     thresholds: Thresholds, warmup_sessions: int = 6, include_invalid: bool = False,
                     bars_override: dict[str, list[Bar]] | None = None) -> list[dict]:
    """fetch + compute for one symbol, inline (CLI / tests / replays). The sweep
    service runs the two halves separately so many symbols overlap."""
    bars_by_tf = await fetch_symbol_bars(symbol, start, end, structure_tfs=structure_tfs, trigger_tf=trigger_tf,
                                         warmup_sessions=warmup_sessions, bars_override=bars_override)
    return compute_symbol_rows(symbol, start, end, structure_tfs=structure_tfs, trigger_tf=trigger_tf,
                               thresholds=thresholds, bars_by_tf=bars_by_tf, warmup_sessions=warmup_sessions,
                               include_invalid=include_invalid)


def _slim_plan(plan: dict) -> dict:
    return {k: plan.get(k) for k in ("symbol", "planFor", "builtFromSession", "structureTfs", "triggerTf",
                                     "lastClose", "levels", "triggers", "validTriggers", "invalidations",
                                     "context", "gapPolicy")}


def last_completed_session(now_ms: int | None = None) -> str:
    """ET date of the most recent regular session whose close is behind us
    (weekends skipped; holidays are not modelled — they simply have no bars)."""
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000) if now_ms is None else int(now_ms)
    day = session_date(now_ms)
    y, m, d = (int(x) for x in day.split("-"))
    cur = dt.date(y, m, d)
    if cur.weekday() >= 5 or now_ms < session_bounds(day)[1]:
        cur -= dt.timedelta(days=1)
        while cur.weekday() >= 5:
            cur -= dt.timedelta(days=1)
    return cur.strftime("%Y-%m-%d")


def compute_symbol_plan(symbol: str, day: str, *, structure_tfs: list[str], trigger_tf: str,
                        thresholds: Thresholds, bars_by_tf: dict[str, list[Bar]]) -> dict:
    """The plan a live analyse at `day`'s close builds — no replay (the session it
    is for has not happened yet). Same window + builder as `compute_symbol_rows`,
    so a plan sheet row and a later validation row are the same plan."""
    as_of = session_bounds(day)[1]
    window = plan_window(bars_by_tf, as_of)
    if not window.get(trigger_tf):
        return {"symbol": symbol, "session": None, "error": f"no {trigger_tf} bars"}
    req = AnalysisRequest(symbol=symbol, as_of_ms=as_of, primary_tf=trigger_tf,
                          context_tfs=tuple(structure_tfs), thresholds=thresholds)
    facts = compute_facts(req, window, [])
    plan = build_session_plan(facts, thresholds=thresholds, structure_tfs=structure_tfs,
                              trigger_tf=trigger_tf).to_dict()
    return {"symbol": symbol, "session": day, "planFor": plan.get("planFor"), "plan": _slim_plan(plan),
            "result": {"pending": True, "planFor": plan.get("planFor")}}


def score_pending_row(plan: dict, bars_by_tf: dict[str, list[Bar]], *, trigger_tf: str, thresholds: Thresholds,
                      include_invalid: bool = False) -> dict | None:
    """Replay a plan-sheet row once its session has bars; None while it has not
    (or the session is still running — a partial replay would be misleading)."""
    plan_for = plan.get("planFor")
    if not plan_for:
        return None
    trig = bars_by_tf.get(trigger_tf) or []
    nxt = [b for b in trig if session_date(b.ts) == plan_for]
    if not nxt:
        return None
    _, close_ms = session_bounds(plan_for)
    if nxt[-1].ts < close_ms - 3 * 60_000:
        return None
    as_of = session_bounds(plan.get("builtFromSession") or plan_for)[1]
    prof = build_profile(plan_window(bars_by_tf, as_of).get(trigger_tf) or [])
    return replay_plan(plan, nxt, thresholds=thresholds, profile=prof, include_invalid=include_invalid)


def aggregate(rows: list[dict]) -> dict:
    """Roll sweep rows up into the two metric families + claim checks (§6.4)."""
    lv_by_source: dict[str, dict] = defaultdict(lambda: {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0})
    lv_by_touch: dict[str, dict] = defaultdict(lambda: {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0})
    lv_by_tf: dict[str, dict] = defaultdict(lambda: {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0})
    lv_pd: dict[str, dict] = {"priorDay": {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0},
                              "other": {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0}}
    trig_by_kind: dict[str, dict] = defaultdict(lambda: {"planned": 0, "fired": 0, "wins": 0, "sumR": 0.0,
                                                         "gappedPast": 0, "gappedThrough": 0, "gapVoid": 0,
                                                         "observedMidday": 0, "notTriggered": 0, "mfeR": 0.0, "maeR": 0.0})
    trig_by_window: dict[str, dict] = defaultdict(lambda: {"fired": 0, "wins": 0, "sumR": 0.0})
    cf = {"base": {"fired": 0, "wins": 0, "sumR": 0.0}, "noWindowGate": {"fired": 0, "wins": 0, "sumR": 0.0},
          "noGapRules": {"fired": 0, "wins": 0, "sumR": 0.0}}
    midday_fires = {"fired": 0, "wins": 0, "sumR": 0.0}
    by_rr_gate: dict[str, dict] = defaultdict(lambda: {"fired": 0, "wins": 0, "sumR": 0.0})
    sessions = 0
    symbols = set()
    for r in rows:
        res = r.get("result") or {}
        if not res.get("bars"):
            continue
        sessions += 1
        symbols.add(r.get("symbol"))
        for l in res.get("levels") or []:
            for src in (l.get("sources") or ["?"]):
                d = lv_by_source[src]; d["n"] += 1; d[l["status"]] += 1
            tb = "1" if (l.get("touchesPlanned") or 0) <= 1 else "2" if l["touchesPlanned"] == 2 else "3+"
            d = lv_by_touch[tb]; d["n"] += 1; d[l["status"]] += 1
            for tf in (l.get("timeframes") or ["?"]):
                d = lv_by_tf[tf]; d["n"] += 1; d[l["status"]] += 1
            d = lv_pd["priorDay" if l.get("priorDayExtreme") else "other"]; d["n"] += 1; d[l["status"]] += 1
        for tg in res.get("triggers") or []:
            if not tg.get("valid"):
                continue
            k = trig_by_kind[tg["kind"]]
            k["planned"] += 1
            st = tg.get("status")
            if st == "fired":
                s = tg.get("sim") or {}
                rr = s.get("rMultiple") or 0.0
                k["fired"] += 1; k["sumR"] += rr; k["wins"] += 1 if rr > 0 else 0
                k["mfeR"] += s.get("mfeR") or 0.0; k["maeR"] += s.get("maeR") or 0.0
                w = trig_by_window[tg.get("firedWindow") or "?"]
                w["fired"] += 1; w["sumR"] += rr; w["wins"] += 1 if rr > 0 else 0
                cf["base"]["fired"] += 1; cf["base"]["sumR"] += rr; cf["base"]["wins"] += 1 if rr > 0 else 0
                gate = "rr>=4" if (tg.get("riskReward") or 0) >= 4 else "rr3-4"
                g = by_rr_gate[gate]; g["fired"] += 1; g["sumR"] += rr; g["wins"] += 1 if rr > 0 else 0
            elif st == "gapped_past":
                k["gappedPast"] += 1
            elif st == "gapped_through":
                k["gappedThrough"] += 1
            elif st == "gap_void":
                k["gapVoid"] += 1
            elif st == "observed":
                k["observedMidday"] += 1
            else:
                k["notTriggered"] += 1
            for name in ("noWindowGate", "noGapRules"):
                c = (tg.get("counterfactual") or {}).get(name) or {}
                if c.get("status") == "fired":
                    rr = (c.get("sim") or {}).get("rMultiple") or 0.0
                    cf[name]["fired"] += 1; cf[name]["sumR"] += rr; cf[name]["wins"] += 1 if rr > 0 else 0
                    if name == "noWindowGate" and c.get("firedWindow") == "midday":
                        midday_fires["fired"] += 1; midday_fires["sumR"] += rr; midday_fires["wins"] += 1 if rr > 0 else 0

    def rate(d, num, den):
        return round(d[num] / d[den], 3) if d.get(den) else None

    def finish_lv(m):
        return {k: {**v, "respectRate": rate(v, "respected", "n"),
                    "testedRespectRate": (round(v["respected"] / (v["n"] - v["untested"]), 3)
                                          if (v["n"] - v["untested"]) else None)} for k, v in m.items()}

    def finish_tr(m):
        out = {}
        for k, v in m.items():
            out[k] = {**{kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()},
                      "winRate": rate(v, "wins", "fired"),
                      "avgR": round(v["sumR"] / v["fired"], 3) if v.get("fired") else None,
                      "triggerRate": rate(v, "fired", "planned") if "planned" in v else None}
        return out

    trig_kind = finish_tr(trig_by_kind)
    windows = finish_tr(trig_by_window)
    cfo = finish_tr(cf)
    pd_ = finish_lv(lv_pd)
    touch = finish_lv(lv_by_touch)

    # claim grid (§6.4) — only what the data can say: below MIN_CLAIM_FIRES fires (or
    # MIN_CLAIM_TESTED tested levels) on either side a verdict is noise, so it stays
    # "insufficient" rather than pass/fail on two trades
    claims = []
    def enough(*ns):
        return all((n or 0) >= MIN_CLAIM_FIRES for n in ns)
    def tested(d):
        return (d.get("n") or 0) - (d.get("untested") or 0)
    def claim(name, rule, metric, ok, detail):
        claims.append({"claim": name, "rule": rule, "metric": metric,
                       "verdict": ("pass" if ok else "fail") if ok is not None else "insufficient", "detail": detail})
    a, b = pd_["priorDay"].get("testedRespectRate"), pd_["other"].get("testedRespectRate")
    ok_pd = a is not None and b is not None and tested(pd_["priorDay"]) >= MIN_CLAIM_TESTED and tested(pd_["other"]) >= MIN_CLAIM_TESTED
    claim("Prior-day HOD/LOD are the strongest levels", "T1.3a", "tested respect rate prior-day vs other",
          (a > b) if ok_pd else None, {"priorDay": a, "other": b, "testedPriorDay": tested(pd_["priorDay"]), "testedOther": tested(pd_["other"])})
    t2, t3 = touch.get("2", {}).get("testedRespectRate"), touch.get("3+", {}).get("testedRespectRate")
    ok_t = t2 is not None and t3 is not None and tested(touch.get("2", {})) >= MIN_CLAIM_TESTED and tested(touch.get("3+", {})) >= MIN_CLAIM_TESTED
    claim("More touches = stronger level", "T1.2", "tested respect rate 3+ vs 2",
          (t3 >= t2) if ok_t else None, {"2": t2, "3+": t3, "tested2": tested(touch.get("2", {})), "tested3+": tested(touch.get("3+", {}))})
    po, pc, md = windows.get("prime_open", {}), windows.get("prime_close", {}), midday_fires
    prime_r = ((po.get("sumR") or 0) + (pc.get("sumR") or 0)) / max(1, (po.get("fired") or 0) + (pc.get("fired") or 0)) \
        if ((po.get("fired") or 0) + (pc.get("fired") or 0)) else None
    mid_r = (md["sumR"] / md["fired"]) if md["fired"] else None
    claim("Prime windows beat mid-day", "R6.1-R6.3", "avg R prime vs mid-day (counterfactual fires)",
          (prime_r > mid_r) if (prime_r is not None and mid_r is not None
                                and enough((po.get("fired") or 0) + (pc.get("fired") or 0), md["fired"])) else None,
          {"primeAvgR": round(prime_r, 3) if prime_r is not None else None, "middayAvgR": round(mid_r, 3) if mid_r is not None else None,
           "primeFired": (po.get("fired") or 0) + (pc.get("fired") or 0), "middayFired": md["fired"]})
    base_r = cfo["base"].get("avgR"); ng = cfo["noGapRules"].get("avgR")
    claim("Gap rules help (ours)", "Q11-Q13", "avg R with vs without gap rules",
          (base_r >= ng) if (base_r is not None and ng is not None and enough(cfo["base"].get("fired"), cfo["noGapRules"].get("fired"))) else None,
          {"with": base_r, "without": ng, "firedWith": cfo["base"].get("fired"), "firedWithout": cfo["noGapRules"].get("fired")})
    g3, g4 = by_rr_gate.get("rr3-4", {}), by_rr_gate.get("rr>=4", {})
    claim("R:R >= 3 gate is not dominated by a stricter one", "R2", "avg R for 3-4 vs >=4",
          None if not enough(g3.get("fired"), g4.get("fired")) else (g3["sumR"] / g3["fired"] >= 0.5 * (g4["sumR"] / g4["fired"])),
          {"rr3-4": finish_tr({"x": g3})["x"] if g3 else None, "rr>=4": finish_tr({"x": g4})["x"] if g4 else None})
    bk = trig_kind.get("breakout", {}); bo = trig_kind.get("bounce", {})
    claim("Confirmed breakouts are worth taking", "T3.3a-c", "breakout win rate / avg R",
          (bk.get("avgR") or 0) > 0 if enough(bk.get("fired")) else None, {"breakout": bk})
    claim("Bounce at the level works", "T4.1/T4.2", "bounce win rate / avg R",
          (bo.get("avgR") or 0) > 0 if enough(bo.get("fired")) else None, {"bounce": bo})

    total_fired = cfo["base"]["fired"]
    return {
        "sessions": sessions, "symbols": sorted(s for s in symbols if s),
        "levels": {"bySource": finish_lv(lv_by_source), "byTouches": touch, "byTimeframe": finish_lv(lv_by_tf),
                   "priorDayVsOther": pd_},
        "triggers": {"byKind": trig_kind, "byWindow": windows, "counterfactual": cfo,
                     "middayFiresWithoutGate": finish_tr({"midday": midday_fires})["midday"],
                     "byRrGate": finish_tr(by_rr_gate)},
        "claims": claims,
        "sample": {"fired": total_fired, "target": 100,
                   "note": "the book asks for >= 100 trades before trusting a result (p. 72)"},
    }
