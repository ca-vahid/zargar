"""EM source-conditioned candidates (`source-continuation-v1`, 2026-09-18; integrated plan workstream C). ORDER-FREE.

Two separately identified research variants that consume workstream A's scenarios and workstream B's policy record:

  source_continuation   the author's OWN branch (symbol, direction, level, family), evaluated with app geometry taken
                        from the saved deterministic plan's trigger that the matcher calls `aligned`. No aligned trigger
                        = no app geometry = held (nothing is invented). An aligned trigger our gates rejected (AMD 2.97R)
                        stays a NAMED refusal with a cost/benefit diagnostic - the threshold is never lowered.
  requalification       `requalification-v1` (see requalification.py): fresh structure after an early invalidation.

Every candidate carries `origin = scenario:<id>`: `PlanRunner.arm` refuses that origin (the Delivery B order-free
boundary), so no API, ingestion, reuse or restore path can arm one. The evaluator owns its OWN `TriggerTracker`
instances - the baseline tracker state is never reset, reused or overwritten; baseline outcomes are reported in parallel.

State is a pure function of (candidate definition, closed bars so far): persistence stores the definition and the last
bar consumed; resume re-derives the state from the session's bars, so a restart can neither skip nor double-count.

UI dispositions: waiting | triggered | invalidated | requalification_eligible | held_for_missing_evidence | refused | expired.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from zoneinfo import ZoneInfo

from ..marketstructure.tracker import TriggerTracker, score_trigger
from . import requalification as rq
from .rulebook import DEFAULT_THRESHOLDS, Thresholds

VERSION = "source-continuation-v1"
DISPOSITIONS = ("waiting", "triggered", "invalidated", "requalification_eligible", "held_for_missing_evidence", "refused", "expired")
NY = ZoneInfo("America/New_York")
MORNING_EXPIRY_ET = (11, 30)          # `source-morning-expiry-v1`: a morning-rundown idea with no stated horizon ends at 11:30 ET


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def candidate_id(scenario_id: str, session: str) -> str:
    return "sc1-" + _h([VERSION, scenario_id, session])[:20]


def source_expiry_ts(session: str, horizon: str | None) -> tuple[int | None, str]:
    """When the SOURCE idea stops being actionable in-session (app convention, labelled). `swing` ideas are out of scope
    for the intraday evaluator; an unstated or `open` horizon ends at 11:30 ET; `0dte` lasts the session."""
    d = dt.date.fromisoformat(session)
    if horizon == "swing":
        return None, "swing: not evaluated intraday (separately declared horizon required)"
    hh, mm = (16, 0) if horizon == "0dte" else MORNING_EXPIRY_ET
    return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).timestamp() * 1000), ("source-session-expiry-v1" if horizon == "0dte" else "source-morning-expiry-v1")


def build_candidate(*, scenario: dict, payload: dict, match: dict | None, plan: dict | None, policy_record: dict | None, session: str) -> dict:
    """ONE source-continuation candidate for ONE scenario branch. Pure; chooses nothing from later outcomes."""
    sid = scenario["scenarioId"]
    sup, app, sym = scenario["authorSupplied"], scenario["appDerived"], (scenario.get("symbol") or {})
    expires, exp_der = source_expiry_ts(session, app.get("horizon"))
    base = {"version": VERSION, "variant": "source_continuation", "candidateId": candidate_id(sid, session), "scenarioId": sid, "pairId": scenario.get("pairId"),
            "origin": f"scenario:{sid}", "orderFree": True, "session": session, "symbol": sym.get("resolved"), "direction": sup.get("direction"),
            "author": (payload.get("author") or {}).get("displayName"), "noteId": (payload.get("note") or {}).get("id"),
            "source": {"condition": sup.get("condition"), "level": app.get("level"), "family": app.get("family"), "targets": app.get("underlyingTargets"),
                       "stop": None, "usableAt": (scenario.get("correction") or {}).get("usableAt") or (payload.get("times") or {}).get("usableAt"),
                       "stance": scenario.get("stance")},
            "expiresTs": expires, "expiryDerivation": exp_der,
            "policy": ({"mode": policy_record.get("mode"), "version": policy_record.get("version"), "disposition": policy_record.get("disposition"),
                        "eligibleTriggers": policy_record.get("eligibleTriggers")} if policy_record else None)}
    if scenario.get("disposition") != "candidate_source" or not sym.get("resolved"):
        return {**base, "disposition": "held_for_missing_evidence", "reason": "source held for resolution: " + "; ".join(scenario.get("heldReasons") or [sym.get("status") or "unresolved"])}
    if expires is None:
        return {**base, "disposition": "held_for_missing_evidence", "reason": exp_der}
    aligned = [r for r in (match or {}).get("triggers") or [] if r.get("verdict") == "aligned"]
    if not aligned:
        why = "no app geometry: the saved plan has no trigger on the author's side at his level" + ("" if app.get("level") else " (the author gave no numeric level)")
        return {**base, "disposition": "held_for_missing_evidence", "reason": why, "matchOverall": (match or {}).get("overall")}
    pick = next((r for r in aligned if r.get("valid")), aligned[0])
    trig = next((copy.deepcopy(t) for t in (plan or {}).get("triggers") or [] if t.get("id") == pick["trigger"]), None)
    if trig is None:
        return {**base, "disposition": "held_for_missing_evidence", "reason": "aligned trigger not found in the saved plan"}
    geometry = {"planTrigger": pick["trigger"], "entry": (trig.get("entry") or {}).get("price"), "stop": (trig.get("stop") or {}).get("price"),
                "targets": [x.get("price") if isinstance(x, dict) else x for x in trig.get("targets") or []], "riskReward": trig.get("riskReward"),
                "provenance": "app-derived: the saved deterministic plan's trigger at the author's level (the author gave no stop)"}
    if not trig.get("valid"):
        return {**base, "disposition": "refused", "geometry": geometry, "namedBaselineOutcome": True,
                "reason": "our gates rejected the aligned trigger: " + "; ".join((trig.get("noTradeReasons") or ["not tradeable"])[:2])[:240], "trigger": trig}
    if policy_record and pick["trigger"] not in (policy_record.get("eligibleTriggers") or []) and policy_record.get("mode") == "deterministic":
        return {**base, "disposition": "refused", "geometry": geometry, "reason": "the preparation policy does not make this trigger eligible", "trigger": trig}
    trig["origin"] = f"scenario:{sid}"
    return {**base, "disposition": "waiting", "geometry": geometry, "trigger": trig, "reason": None}


def evaluate(candidate: dict, bars: list, *, thresholds: Thresholds | None = None, profile=None, prev_close: float | None = None,
             upto_ts: int | None = None) -> dict:
    """Causal evaluation with the candidate's OWN tracker. Only bars CLOSED by `upto_ts` (default: all given) and
    before the source expiry are fed. The proxy outcome (what the underlying did afterwards) is reported apart and
    never feeds back into the disposition."""
    out = {**candidate}
    trig = candidate.get("trigger")
    if candidate.get("disposition") not in ("waiting", "requalification_eligible") or not trig:
        return out
    t = thresholds or DEFAULT_THRESHOLDS
    usable = _ms(candidate.get("source", {}).get("usableAt")) if candidate.get("variant") == "source_continuation" else candidate.get("eligibleFromTs")
    exp = candidate.get("expiresTs")
    tracker = TriggerTracker(copy.deepcopy(trig), t, profile, True, True, prev_close)
    born = int(candidate.get("eligibleFromTs") or 0) if candidate.get("variant") == "requalification" else 0
    if born:
        out["gapRule"] = "not applicable: the structure was born after the open (the tracker runs gap_unchecked, as production does for a late start); the parent's gap verdict stands"
    if born:
        bars = [b for b in bars if int(b.ts) > born]        # a requalified candidate never sees bars from before its own confirmation;
    fed = 0                                                 # the tracker indexes its OWN bar list, so the slice is what it and the scorer get
    for i, b in enumerate(bars):
        closed = int(b.ts) + 60_000
        if upto_ts is not None and closed > int(upto_ts):
            break
        if exp is not None and int(b.ts) >= int(exp):
            break
        tracker.on_bar(b, i)
        fed += 1
        if tracker.status == "fired":
            if usable is not None and closed <= int(usable):
                # the condition completed BEFORE the source was usable to the app: not a source-informed entry
                out.update({"disposition": "expired", "reason": "the condition completed before the source became usable to the app", "firedTs": tracker.fired_ts})
                return out
            break
        if tracker.status in TriggerTracker.TERMINAL:
            break
    out["barsConsumed"] = fed
    out["lastBarTs"] = int(bars[fed - 1].ts) if fed else None
    out["trackerEvents"] = list(tracker.events[-8:]); out["skipped"] = list(tracker.skipped[-6:])
    if tracker.status == "fired":
        out.update({"disposition": "triggered", "firedTs": tracker.fired_ts, "firedWindow": tracker.fired_window, "fillProxy": tracker.fill_price,
                    "pricingGates": pricing_gates(candidate, None)})
        scored = score_trigger(tracker, bars, thresholds=t)
        out["outcomeProxy"] = {**(scored.get("sim") or {}), "evidenceClass": "underlying_walkforward_proxy",
                               "note": "what the UNDERLYING did afterwards - not an option fill, not dollars; never feeds the disposition"}
    elif tracker.status in TriggerTracker.TERMINAL:
        out.update({"disposition": "invalidated", "reason": f"tracker: {tracker.status}", "invalidatedStatus": tracker.status,
                    "invalidatedTs": (tracker.events[-1].get("ts") if tracker.events else out["lastBarTs"])})
    elif exp is not None and bars and (upto_ts is None or int(upto_ts) >= int(exp)) and int(bars[-1].ts) + 60_000 >= int(exp):
        out.update({"disposition": "expired", "reason": "source expiry reached without the condition"})
    return out


def pricing_gates(candidate: dict, quotes: dict | None) -> dict:
    """The executable-pricing stage. Order-free research never fetches a chain: without a contemporaneous cached quote
    the contract / spread / sizing / budget gates are UNKNOWN - they are not assumed to pass."""
    q = (quotes or {}).get(candidate.get("symbol"))
    return {"stage": "executable_pricing", "underlierQuote": ("present" if q else "unknown"),
            "contract": "unknown (no chain fetch on the research path)", "spread": "unknown", "sizing": "unknown", "budget": "unknown",
            "noChase": "applied by the tracker (completed-bar rules)", "note": "a triggered candidate is NOT an executable entry"}


def requalify(*, scenario: dict, payload: dict, baseline_trigger_state: dict, bars: list, session: str, thresholds: Thresholds | None = None,
              existing_children=None, upto_ts: int | None = None) -> dict:
    """Variant 2. `baseline_trigger_state` = {status, ts, entry} of the PARENT's invalidated baseline trigger (read-only)."""
    app = scenario["appDerived"]
    expires, exp_der = source_expiry_ts(session, app.get("horizon"))
    seen = rq.bars_upto(bars, upto_ts) if upto_ts is not None else list(bars)
    parent = {"scenarioId": scenario["scenarioId"], "symbol": (scenario.get("symbol") or {}).get("resolved"), "direction": scenario["authorSupplied"].get("direction"),
              "session": session, "invalidatedTs": baseline_trigger_state.get("ts"), "invalidatedStatus": baseline_trigger_state.get("status"),
              "sourceTargets": app.get("underlyingTargets"), "expiresTs": expires, "oldEntry": baseline_trigger_state.get("entry")}
    child = rq.build_child(parent=parent, bars=seen, thresholds=thresholds, existing_children=existing_children)
    return {**child, "variant": "requalification", "expiryDerivation": exp_der, "candidateId": child["childId"],
            "author": (payload.get("author") or {}).get("displayName"), "noteId": (payload.get("note") or {}).get("id")}


def exclusion_diagnostic(name: str, trigger: dict, bars: list, *, thresholds: Thresholds | None = None, profile=None, prev_close: float | None = None,
                         relax: str | None = None) -> dict:
    """Cost AND benefit of a named baseline exclusion (MU volume skip, AMD 2.97R), hindsight-labelled. `relax` =
    `volume` replays the same trigger with the volume floor off; None replays the rejected geometry as-is. Diagnostic
    only: it never changes a threshold and is never a selection feature."""
    import dataclasses
    t = thresholds or DEFAULT_THRESHOLDS
    if relax == "volume":
        over = {k: 0.0 for k in ("volume_spike_mult", "volume_floor_mult") if hasattr(t, k)}
        t = dataclasses.replace(t, **over) if over else t
    tr = TriggerTracker({**copy.deepcopy(trigger), "valid": True}, t, profile, True, True, prev_close)
    for i, b in enumerate(bars):
        tr.on_bar(b, i)
        if tr.status in TriggerTracker.TERMINAL:
            break
    sc = score_trigger(tr, bars, thresholds=t)
    sim = sc.get("sim") or {}
    return {"exclusion": name, "relaxed": relax, "status": sc.get("status"), "firedTs": sc.get("firedTs"), "outcome": sim.get("outcome"), "rMultiple": sim.get("rMultiple"),
            "benefitOfExclusion": (abs(sim["rMultiple"]) if (sim.get("rMultiple") or 0) < 0 else 0.0) if sim else None,
            "costOfExclusion": (sim["rMultiple"] if (sim.get("rMultiple") or 0) > 0 else 0.0) if sim else None,
            "label": "HINDSIGHT diagnostic on the underlying; a single path; never grounds for loosening the production gate"}


def _ms(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T", 1))
        return int((d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp() * 1000)
    except ValueError:
        return None


def table_row(c: dict, baseline: dict | None = None) -> dict:
    """The source -> candidate -> gate row the report and the UI show."""
    g = c.get("geometry") or {}
    return {"candidateId": c.get("candidateId"), "variant": c.get("variant"), "author": c.get("author"), "symbol": c.get("symbol"), "direction": c.get("direction"),
            "condition": (c.get("source") or {}).get("condition"), "sourceLevel": (c.get("source") or {}).get("level"), "entry": g.get("entry"), "stop": g.get("stop"),
            "targets": g.get("targets"), "disposition": c.get("disposition"), "reason": c.get("reason"), "firedTs": c.get("firedTs"),
            "outcomeProxy": (c.get("outcomeProxy") or {}).get("outcome"), "rProxy": (c.get("outcomeProxy") or {}).get("rMultiple"),
            "baseline": baseline, "orderFree": True, "origin": c.get("origin")}


def evaluate_session(*, payloads: list, plans_by_symbol: dict, bars_by_symbol: dict, baseline_by_symbol: dict | None, session: str,
                     upto_ts: int | None = None, thresholds_by_symbol: dict | None = None, profiles_by_symbol: dict | None = None,
                     policy_by_run: dict | None = None, prev_close_by_symbol: dict | None = None) -> list:
    """The ONE evaluator the forward loop and the replay tool share. Pure: scenarios (A) + saved plans + the policy records
    (B) + closed bars -> candidates of both variants with their dispositions. `plans_by_symbol[sym]` = [{runId, createdAt,
    trigger(origin), plan}], newest last; `baseline_by_symbol[sym]` = [{trigger, direction, status, ts, entry}] of the
    BASELINE trackers (read-only). Missing bars = the candidate stays `waiting` with `barsCoverage: none` - never guessed."""
    from . import source_scenarios as _ss
    out = []
    for payload in payloads or []:
        for sc in payload.get("scenarios") or []:
            sym = (sc.get("symbol") or {}).get("resolved")
            plans = (plans_by_symbol or {}).get(sym) or []
            best_plan, best_match = None, None
            for p in plans:
                m = _ss.match_plan(sc, payload, p.get("plan") or {}, plan_built_at=p.get("createdAt"), plan_origin=p.get("trigger"))
                if best_match is None or (m["alignedTrigger"] and not best_match["alignedTrigger"]):
                    best_plan, best_match = p, m
            pol = (policy_by_run or {}).get((best_plan or {}).get("runId"))
            cand = build_candidate(scenario=sc, payload=payload, match=best_match, plan=(best_plan or {}).get("plan"), policy_record=pol, session=session)
            cand["planRunId"] = (best_plan or {}).get("runId"); cand["matchOverall"] = (best_match or {}).get("overall")
            bars = (bars_by_symbol or {}).get(sym) or []
            th = (thresholds_by_symbol or {}).get(sym); prof = (profiles_by_symbol or {}).get(sym); pc = (prev_close_by_symbol or {}).get(sym)
            if cand["disposition"] == "waiting":
                if bars:
                    cand = evaluate(cand, bars, thresholds=th, profile=prof, prev_close=pc, upto_ts=upto_ts)
                else:
                    cand["barsCoverage"] = "none"
            base = [b for b in ((baseline_by_symbol or {}).get(sym) or []) if b.get("direction") == sc["authorSupplied"].get("direction")]
            cand["baseline"] = base
            out.append(cand)
            dead = next((b for b in sorted(base, key=lambda b: int(b.get("ts") or 0)) if b.get("status") in rq.TERMINAL_UNFIRED), None)
            if sym and dead is not None and sc.get("disposition") == "candidate_source":
                if bars:
                    child = requalify(scenario=sc, payload=payload, baseline_trigger_state=dead, bars=bars, session=session, thresholds=th, upto_ts=upto_ts)
                    if child.get("disposition") == "requalification_eligible":
                        ev = evaluate({**child, "source": {}}, bars, thresholds=th, profile=prof, prev_close=None, upto_ts=upto_ts)
                        child = {**child, **{k: ev[k] for k in ("disposition", "firedTs", "fillProxy", "outcomeProxy", "pricingGates", "reason", "barsConsumed") if k in ev}}
                        if child["disposition"] == "requalification_eligible" and ev.get("disposition") == "requalification_eligible":
                            child["disposition"] = "requalification_eligible"          # confirmed structure, break not (yet) triggered
                else:
                    child = {"version": rq.VERSION, "variant": "requalification", "candidateId": rq.child_id(sc["scenarioId"], session), "parentScenarioId": sc["scenarioId"],
                             "origin": f"scenario:{sc['scenarioId']}", "orderFree": True, "symbol": sym, "direction": sc["authorSupplied"].get("direction"),
                             "disposition": "waiting", "barsCoverage": "none", "reason": "no session bars - unknown, not assumed"}
                child["baseline"] = base
                out.append(child)
    return out
