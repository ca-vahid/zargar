"""EM preparation policy (`em-prep-policy-v1`, 2026-09-18; integrated plan workstream B). Pure.

WHICH saved next-session plans become eligible to arm - decided by ONE owner, with a rules record for every candidate,
whichever path produced it (evening batch, morning ingestion, pre-open re-plan). Distinct from `fire_decision_mode`
(the live entry decision): this is preparation.

  baseline        today's behaviour, unchanged: the model's plan review selects (verdict `setup`). DEFAULT.
  deterministic   proposed: existing valid geometry + the documented grade floor + deterministic preparation rules.
                  ZERO model calls. An absent model review is recorded as ABSENT - neither an old approval nor a veto.

Conditional-plan review semantics (`conditional-review-v1`), built for BOTH modes: "the breakout has not happened yet"
is not a reason to reject a plan whose trigger is BY CONSTRUCTION a condition for the next session. Such a reason is
classified and discarded; every other objection is kept (invalid geometry, unavailable targets, provenance, source
conflicts). Reasons are per trigger: a reason naming k1 never vetoes k2; only an explicit plan-level reason reaches
every trigger. Discarding one bad reason never approves a plan - the trigger then stands or falls on the rules.
Under `baseline` the fix is REPORT-ONLY by default (`conditional_review_fix=report`): rescued triggers are listed, not
armed - arming them is a separate activation decision.

Nothing here reads settings, a clock, a database or a model. Callers freeze the inputs.
"""
from __future__ import annotations

import hashlib
import json
import re

VERSION = "em-prep-policy-v1"
REVIEW_VERSION = "conditional-review-v1"
MODES = ("baseline", "deterministic")
FIX_MODES = ("off", "report", "apply")
GRADES = ("A", "B", "C", "D")
SETTING_MODE = "techniques.enhanced_market.preparation_policy"
SETTING_FLOOR = "techniques.enhanced_market.prep_grade_floor"
SETTING_FIX = "techniques.enhanced_market.conditional_review_fix"
SETTING_AUDIT = "techniques.enhanced_market.prep_audit_quota_pct"

_TRIGGER_ID = re.compile(r"(?<![A-Za-z0-9_])(e_)?([bkrdw]\d{1,2})(?![A-Za-z0-9])")
_NOT_YET = re.compile(
    r"(has|have|had)(\s+not|n't)\s+(yet\s+)?(been\s+)?(broken|happened|triggered|occurred|confirmed|closed (above|below)|reclaimed|reached|touched|tested|observed|printed)"
    r"|no (breakout|breakdown|break|bounce|rejection|touch|retest|confirmation)( there| here| at it)? (has |yet|so far)"
    r"|not yet (been )?(broken|triggered|confirmed|happened|reached|tested|reclaimed|observed)"
    r"|still (below|under|beneath|above|trading (below|under|above)) (the |this |that )?(level|resistance|support|trigger|entry|zone|high|low)"
    r"|price (is|remains|sits) (still )?(below|under|beneath|above) (the |this )?(trigger|level|resistance|support|entry)"
    r"|(awaiting|waiting for|needs to|must first) (a |the )?(break|breakout|breakdown|close (above|below)|confirm|confirmation|reclaim|touch|retest)"
    r"|yet to (break|trigger|confirm|happen|reach|reclaim)", re.I)
_TIMING = re.compile(r"R6\.[34]|outside the (prime|session) window|market is closed|as-of instant", re.I)
_HEADER = re.compile(r"^\s*(e_)?[bkrdw]\d{1,2}\s+[a-z_]+\s*@\s*[\d.,]+\s*(?:[\u2014\-:]+\s*)?", re.I)
_LABEL = re.compile(r"^\s*(REJECTED|not tradeable|not tradable)[^:]{0,40}:\s*", re.I)
_CLAUSE = re.compile(r";|\s\u2014\s|(?<=[a-z0-9\)])\.\s+(?=[A-Z])")


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def effective(get) -> dict:
    """The effective policy from a settings getter - surfaced on preparation, preflight, board and arm snapshots."""
    mode = str(get(SETTING_MODE, "baseline") or "baseline").strip().lower()
    fix = str(get(SETTING_FIX, "report") or "report").strip().lower()
    floor = str(get(SETTING_FLOOR, "B") or "B").strip().upper()
    try:
        quota = max(0.0, min(100.0, float(get(SETTING_AUDIT, 0.0) or 0.0)))
    except (TypeError, ValueError):
        quota = 0.0
    return {"preparationPolicy": (mode if mode in MODES else "baseline"), "preparationPolicyVersion": VERSION,
            "conditionalReviewFix": (fix if fix in FIX_MODES else "report"), "conditionalReviewVersion": REVIEW_VERSION,
            "gradeFloor": (floor if floor in GRADES else "B"), "auditQuotaPct": quota,
            "invalidSetting": (None if mode in MODES else mode)}


def candidate_key(symbol: str, plan: dict) -> str:
    """Identity of a CANDIDATE, independent of the path that produced it: symbol + session + the trigger geometry.
    The same plan reached through batch, ingestion and the pre-open re-plan has ONE key - it can be armed once."""
    trig = sorted((str(t.get("kind")), str(t.get("direction") or ""), round(float(t.get("levelPrice") or (t.get("entry") or {}).get("price") or 0), 4),
                   round(float((t.get("stop") or {}).get("price") if isinstance(t.get("stop"), dict) else (t.get("stop") or 0)), 4))
                  for t in (plan or {}).get("triggers") or [] if t.get("valid"))
    return _h({"symbol": str(symbol).upper(), "planFor": (plan or {}).get("planFor"), "triggers": trig})[:32]


def causal_input_key(*, symbol: str, session: str, as_of, bars_hash: str | None, source_hashes=None, adjusted_data_id: str | None = None,
                     thresholds_hash: str | None, grade_policy: str, policy_version: str = VERSION, model: str | None = None,
                     prompt_version: str | None = None, horizon: str | None = None) -> str:
    """Identity of a preparation DECISION's causal inputs. Symbol/date alone is never identity: any changed bar set,
    source revision, adjustment, threshold, grade policy, model/prompt (when a model is involved) or horizon is a new key."""
    return _h({"symbol": str(symbol).upper(), "session": session, "asOf": as_of, "bars": bars_hash, "sources": sorted(source_hashes or []),
               "adjusted": adjusted_data_id, "thresholds": thresholds_hash, "grade": grade_policy, "policy": policy_version,
               "model": model, "prompt": prompt_version, "horizon": horizon})


# ------------------------------------------------------------------------------------ conditional-review-v1
def split_clauses(text: str) -> list[str]:
    """A model reason is often several objections in one sentence. Strip the `k1 breakout @ 220.24 - REJECTED:` header and
    split on `;`, an em dash and sentence ends, so a logically invalid clause never drags a real objection out with it."""
    t = _LABEL.sub("", _HEADER.sub("", str(text or "").strip()))
    return [c.strip() for c in _CLAUSE.split(t) if c and len(c.strip()) >= 8]


def classify_clause(text: str) -> str:
    t = str(text or "")
    if _NOT_YET.search(t):
        return "not_yet_triggered"
    if _TIMING.search(t):
        return "session_timing"
    return "substantive"


def classify_reason(text: str) -> str:
    """`substantive` when ANY clause is a real objection; `not_yet_triggered` / `session_timing` only when EVERY clause is."""
    classes = [classify_clause(c) for c in split_clauses(text)] or [classify_clause(text)]
    if any(c == "substantive" for c in classes):
        return "substantive"
    return "not_yet_triggered" if "not_yet_triggered" in classes else "session_timing"


def review_semantics(no_trade_reasons, trigger_ids) -> dict:
    """Split the model's reasons by the trigger they NAME. Returns {triggers: {id: {...}}, planLevel: [...]}.
    modelVeto per trigger: `substantive` (at least one kept reason reaches it), `invalid_only` (every reason reaching it
    was discarded), `none` (no reason reaches it)."""
    ids = [str(i) for i in trigger_ids or []]
    per = {i: [] for i in ids}
    plan_level = []
    for raw in no_trade_reasons or []:
        text = str(raw or "").strip()
        if not text:
            continue
        named = []
        lead = _TRIGGER_ID.match(text)
        if lead and ((lead.group(1) or "") + lead.group(2)) in per:
            named = [(lead.group(1) or "") + lead.group(2)]          # a reason that OPENS with a trigger id is about that trigger only
        else:
            for m in _TRIGGER_ID.finditer(text):
                tid = (m.group(1) or "") + m.group(2)
                if tid in per and tid not in named:
                    named.append(tid)
        clauses = split_clauses(text)
        row = {"text": text[:400], "class": classify_reason(text),
               "discardedClauses": [c[:200] for c in clauses if classify_clause(c) != "substantive"],
               "keptClauses": [c[:200] for c in clauses if classify_clause(c) == "substantive"]}
        if named:
            for tid in named:
                per[tid].append({**row, "scope": "trigger"})
        else:
            plan_level.append({**row, "scope": "plan"})
    out = {}
    for tid in ids:
        reach = per[tid] + plan_level
        kept = [r for r in reach if r["class"] == "substantive"]
        out[tid] = {"reasons": reach, "kept": kept, "discarded": [r for r in reach if r["class"] != "substantive"],
                    "modelVeto": ("substantive" if kept else ("invalid_only" if reach else "none"))}
    return {"version": REVIEW_VERSION, "triggers": out, "planLevel": plan_level}


# ------------------------------------------------------------------------------------------- the decision
def _grade_ok(grade, floor: str) -> str:
    g = str(grade or "").upper()
    if g not in GRADES:
        return "unknown"
    return "pass" if GRADES.index(g) <= GRADES.index(floor) else "fail"


def _trigger_rules(t: dict, floor: str) -> list:
    tg = t.get("targets") or []
    stop = t.get("stop")
    stop_px = (stop or {}).get("price") if isinstance(stop, dict) else stop
    reasons = list(t.get("noTradeReasons") or [])
    return [
        {"name": "geometry_valid", "outcome": ("pass" if t.get("valid") else "fail"), "detail": ("; ".join(reasons[:2])[:240] if not t.get("valid") else None)},
        {"name": "stop_present", "outcome": ("pass" if stop_px else "fail"), "detail": None},
        {"name": "targets_available", "outcome": ("pass" if tg else "fail"), "detail": None},
        {"name": "grade_floor", "outcome": _grade_ok((t.get("assessment") or {}).get("grade"), floor),
         "detail": f"grade {(t.get('assessment') or {}).get('grade')} vs floor {floor}"},
    ]


def decide(*, symbol: str, plan: dict, analysis: dict | None, policy: dict, origin: str, source_hold: list | None = None,
           run_id: str | None = None, input_key: str | None = None) -> dict:
    """ONE eligibility decision for one candidate. `analysis` = the saved model review ({verdict, no_trade_reasons}) or
    None when no model reviewed the plan. `origin` = batch | ingest | preopen_replan | manual. `source_hold` = reasons the
    SOURCE data is ambiguous (held for resolution, never sent as a trade candidate)."""
    mode, floor, fix = policy.get("preparationPolicy", "baseline"), policy.get("gradeFloor", "B"), policy.get("conditionalReviewFix", "report")
    trig = list((plan or {}).get("triggers") or [])
    ids = [str(t.get("id")) for t in trig]
    review_state = "absent" if not analysis or not analysis.get("verdict") else str(analysis.get("verdict"))
    sem = review_semantics((analysis or {}).get("no_trade_reasons") or (analysis or {}).get("noTradeReasons") or [], ids) if review_state != "absent" else None
    rows, rescued = [], []
    for t in trig:
        tid = str(t.get("id"))
        rules = _trigger_rules(t, floor)
        rules_ok = all(c["outcome"] == "pass" for c in rules)
        unknown = [c["name"] for c in rules if c["outcome"] == "unknown"]
        model = (sem or {}).get("triggers", {}).get(tid) if sem else None
        if mode == "deterministic":
            eligible, basis = rules_ok, "rules"
        elif review_state == "setup":
            eligible, basis = bool(t.get("valid")), "model_setup"                    # baseline arms the reviewed plan's valid triggers
        elif review_state == "no_setup":
            eligible, basis = False, "model_no_setup"
            if model and model["modelVeto"] in ("invalid_only", "none") and t.get("valid"):
                if rules_ok:
                    rescued.append(tid)
                    basis = "model_reason_invalid__rules_pass"
                    eligible = (fix == "apply")
                else:
                    basis = "model_reason_invalid__rules_fail"                       # one bad reason removed is NOT an approval
        else:
            eligible, basis = False, "baseline_requires_model_review"
        rows.append({"id": tid, "kind": t.get("kind"), "direction": t.get("direction"), "level": t.get("levelPrice"), "eligible": bool(eligible), "basis": basis,
                     "rules": rules, "unknownRules": unknown,
                     "modelReview": ({"veto": model["modelVeto"], "kept": model["kept"], "discarded": model["discarded"]} if model else None)})
    held = list(source_hold or [])
    any_eligible = any(r["eligible"] for r in rows)
    if held:
        disposition = "held_for_resolution"
    elif not trig:
        disposition = "refused"
    else:
        disposition = "eligible" if any_eligible else "refused"
    rec = {"version": VERSION, "reviewVersion": REVIEW_VERSION, "mode": mode, "owner": "em-preparation-policy", "origin": origin, "runId": run_id,
           "symbol": str(symbol).upper(), "planFor": (plan or {}).get("planFor"), "candidateKey": candidate_key(symbol, plan), "inputKey": input_key,
           "modelReview": review_state, "modelCalls": (0 if mode == "deterministic" else None), "gradeFloor": floor,
           "disposition": disposition, "eligibleTriggers": [r["id"] for r in rows if r["eligible"]] if not held else [],
           "triggers": rows, "sourceHold": held,
           "conditionalFix": {"mode": fix, "rescued": rescued, "applied": bool(rescued) and fix == "apply"},
           "planLevelModelReasons": (sem or {}).get("planLevel") if sem else None}
    rec["explanation"] = explain(rec)
    rec["decisionHash"] = _h({k: rec[k] for k in ("version", "mode", "candidateKey", "disposition", "eligibleTriggers", "gradeFloor", "modelReview")})
    return rec


def explain(rec: dict) -> str:
    """Human-readable, generated from the rule record - no prose model."""
    parts = [f"{rec['symbol']} for {rec.get('planFor')}: {rec['disposition'].replace('_', ' ')} under `{rec['mode']}` ({rec['origin']}; model review {rec['modelReview']})."]
    if rec.get("sourceHold"):
        parts.append("Held: " + "; ".join(rec["sourceHold"]) + ".")
    for r in rec.get("triggers") or []:
        failed = [c["name"] + (f" ({c['detail']})" if c.get("detail") else "") for c in r["rules"] if c["outcome"] != "pass"]
        line = f"{r['id']} {r.get('kind')}: " + ("eligible" if r["eligible"] else "not eligible") + f" [{r['basis']}]"
        if failed:
            line += " - rules not passed: " + ", ".join(failed)
        mr = r.get("modelReview")
        if mr and mr.get("discarded"):
            line += f" - {len(mr['discarded'])} model reason(s) discarded as {sorted({d['class'] for d in mr['discarded']})}"
        if mr and mr.get("kept"):
            line += f" - model objection kept: {mr['kept'][0]['text'][:120]}"
        parts.append(line)
    cf = rec.get("conditionalFix") or {}
    if cf.get("rescued"):
        parts.append(f"Conditional-review fix ({cf['mode']}): {', '.join(cf['rescued'])} rescued" + (" and eligible." if cf.get("applied") else " - REPORTED ONLY, not eligible under this setting."))
    return " ".join(parts)


def select(decisions: list, *, already_armed_keys=None) -> dict:
    """ONE arm list from every path's decisions: a candidate key is armed at most once (first eligible decision wins;
    later duplicates are reported as `duplicate_of`), and a key already armed is never armed again."""
    armed = set(already_armed_keys or [])
    arm, skipped = [], []
    for d in decisions or []:
        k = d.get("candidateKey")
        if d.get("disposition") != "eligible":
            skipped.append({"runId": d.get("runId"), "symbol": d.get("symbol"), "why": d.get("disposition")})
        elif k in armed:
            skipped.append({"runId": d.get("runId"), "symbol": d.get("symbol"), "why": "duplicate_of_armed_candidate", "candidateKey": k})
        else:
            armed.add(k)
            arm.append({"runId": d.get("runId"), "symbol": d.get("symbol"), "candidateKey": k, "origin": d.get("origin"), "triggers": d.get("eligibleTriggers")})
    return {"version": VERSION, "arm": arm, "skipped": skipped}


# ------------------------------------------------------------------------------------------ audit sampler
def audit_sampled(*, session: str, candidate: str, input_key: str | None, policy_version: str = VERSION, quota_pct: float = 0.0) -> bool:
    """Deterministic audit sample: a stable hash of (session, candidate, inputs, policy) against the quota. Default quota
    0 = zero paid calls. Evidence only - a sampled audit never gains execution authority, fast or slow, pass or fail."""
    q = max(0.0, min(100.0, float(quota_pct or 0.0)))
    if q <= 0:
        return False
    bucket = int(_h([session, candidate, input_key, policy_version])[:8], 16) % 10_000
    return bucket < int(round(q * 100))


# ------------------------------------------------------------------------------------------- batch resume
def plan_batch(items: list, ledger: dict) -> dict:
    """Resume a batch without duplicate reviews or arms. `items` = [{inputKey, symbol, ...}]; `ledger` = {inputKey:
    {status: done|failed|running, attempts, retryable}}. Done work is reused; only FAILED retryable reads run again; a
    changed input has a new key and therefore runs."""
    run, reuse, skip = [], [], []
    for it in items or []:
        led = (ledger or {}).get(it.get("inputKey"))
        if led is None:
            run.append(it)
        elif led.get("status") == "done":
            reuse.append(it)
        elif led.get("status") == "failed" and led.get("retryable", True) and int(led.get("attempts") or 0) < 3:
            run.append({**it, "retryOf": led.get("attempts")})
        else:
            skip.append({**it, "why": f"{led.get('status')} (attempts {led.get('attempts')})"})
    return {"run": run, "reuse": reuse, "skip": skip}
