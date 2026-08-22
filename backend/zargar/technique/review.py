"""Review taxonomy, validation, serialisation and run diffs.

A review records *what the user expected*, *whether the verdict held up* and
*which stage of the pipeline is to blame*. The vocabularies below are shared by
the API, the CLI (`zargar.tools.technique_review`), the UI and the
`/technique-review` skill so the stored data stays queryable.
"""
from __future__ import annotations

REVIEW_VERDICTS: dict[str, str] = {
    "correct": "The verdict and plan were right for what the chart showed (and what followed).",
    "wrong_verdict": "Said setup when there was none, or no_setup when a valid setup was there.",
    "wrong_levels": "Right idea, but the levels it keyed off were not the ones that mattered.",
    "wrong_plan": "Setup was real but entry/stop/targets were mis-placed (chased, stop too tight/wide, R:R off).",
    "late": "Called correctly but after the move had already happened.",
    "data_issue": "Bars/volume/time-of-day data were wrong or missing, so the read could not be right.",
    "unclear": "Cannot tell yet (outcome pending or ambiguous).",
}

ROOT_CAUSE_STAGES: dict[str, str] = {
    "data": "history fetch / as_of window / missing timeframe (technique/history.py, analysis.gather_bars)",
    "detectors": "levels, volume, structure, wedge, candles, candidate setups (levels.py, volume.py, structure.py, setups.py)",
    "facts_prompt": "what FACTS told the model, or how it was phrased (analysis.facts_for_prompt)",
    "pass_context": "PASS 1 read of structure/levels on the context timeframe (vision.py, schemas.PassNotes)",
    "pass_pattern": "PASS 2 pattern / breakout read (vision.py)",
    "pass_entry": "PASS 3 entry decision / plan construction (vision.py, schemas.TechniqueAnalysis, SYSTEM_PROMPT)",
    "critic": "PASS 4 kill/keep decision or confidence adjustment (vision.py, schemas.CriticVerdict)",
    "grounding": "the FACTS verification accepted or rejected wrongly (grounding.py)",
    "options": "contract pick (options.py)",
    "thresholds": "a tunable number in technique.* settings (rulebook.Thresholds)",
    "rulebook": "the method itself as codified disagrees with the book (rulebook.RULES, TECHNIQUE-ENHANCEDMARKET.md)",
    "other": "anything else — say what in notes",
}

REVIEWERS = ("user", "claude")
VERDICTS = ("setup", "no_setup")


def validate_review(*, review_verdict: str, root_cause_stage: str | None, reviewer: str,
                    expected_verdict: str | None) -> None:
    if review_verdict not in REVIEW_VERDICTS:
        raise ValueError(f"review_verdict must be one of {sorted(REVIEW_VERDICTS)}")
    if root_cause_stage is not None and root_cause_stage not in ROOT_CAUSE_STAGES:
        raise ValueError(f"root_cause_stage must be one of {sorted(ROOT_CAUSE_STAGES)}")
    if reviewer not in REVIEWERS:
        raise ValueError(f"reviewer must be one of {REVIEWERS}")
    if expected_verdict is not None and expected_verdict not in VERDICTS:
        raise ValueError(f"expected_verdict must be one of {VERDICTS}")


def review_dict(r) -> dict:
    return {
        "id": r.id, "runId": r.run_id, "reviewer": r.reviewer,
        "expectedVerdict": r.expected_verdict, "expectedSetupType": r.expected_setup_type,
        "expectedPlan": r.expected_plan or {}, "expectationNote": r.expectation_note or "",
        "reviewVerdict": r.review_verdict, "rootCauseStage": r.root_cause_stage,
        "notes": r.notes or "", "actions": r.actions or [],
        "processVersion": r.process_version or {},
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    }


# --- diffs ------------------------------------------------------------------------

def _plan_of(run: dict) -> dict:
    a = ((run.get("result") or {}).get("analysis")) or run.get("analysis") or {}
    return {
        "verdict": a.get("verdict"), "setupType": a.get("setupType"), "trend": a.get("trend"),
        "confidence": a.get("confidence"),
        "entry": (a.get("entry") or {}).get("price"), "stop": (a.get("stop") or {}).get("price"),
        "targets": [t.get("price") for t in (a.get("targets") or [])],
        "riskReward": a.get("riskReward"),
        "levels": [lv.get("price") for lv in (a.get("levels") or [])],
        "rulesFired": sorted(a.get("rulesFired") or []),
        "noTradeReasons": list(a.get("noTradeReasons") or []),
        "grounded": ((run.get("result") or {}).get("grounding") or {}).get("passed"),
    }


def diff_runs(a: dict, b: dict) -> dict:
    """Field-by-field comparison of two run dicts (as returned by get_run):
    the analysis, the process version and the thresholds that differ."""
    pa, pb = _plan_of(a), _plan_of(b)
    changed = {k: {"a": pa[k], "b": pb[k]} for k in pa if pa[k] != pb[k]}
    ca, cb = a.get("config") or {}, b.get("config") or {}
    ta, tb = ca.get("thresholds") or {}, cb.get("thresholds") or {}
    thr = {k: {"a": ta.get(k), "b": tb.get(k)} for k in set(ta) | set(tb) if ta.get(k) != tb.get(k)}
    sa, sb = ca.get("settings") or {}, cb.get("settings") or {}
    st = {k: {"a": sa.get(k), "b": sb.get(k)} for k in set(sa) | set(sb) if sa.get(k) != sb.get(k)}
    ver = {k: {"a": ca.get(k), "b": cb.get(k)}
           for k in ("promptVersion", "rulebookVersion", "codeVersion", "processVersion", "model", "effort")
           if ca.get(k) != cb.get(k)}
    ua, ub = a.get("usage") or {}, b.get("usage") or {}
    return {
        "a": {"id": a.get("id"), "symbol": a.get("symbol"), "asOf": a.get("asOf"),
              "createdAt": a.get("createdAt"), "parentRunId": a.get("parentRunId")},
        "b": {"id": b.get("id"), "symbol": b.get("symbol"), "asOf": b.get("asOf"),
              "createdAt": b.get("createdAt"), "parentRunId": b.get("parentRunId")},
        "sameInputs": a.get("symbol") == b.get("symbol") and a.get("asOf") == b.get("asOf")
                      and a.get("primaryTf") == b.get("primaryTf"),
        "analysis": changed, "thresholds": thr, "settings": st, "versions": ver,
        "usage": {"a": ua, "b": ub},
        "seconds": {"a": (a.get("result") or {}).get("seconds"), "b": (b.get("result") or {}).get("seconds")},
        "plans": {"a": pa, "b": pb},
    }
