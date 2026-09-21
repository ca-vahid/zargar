"""Selection study S1: the FROZEN analysis (registration `s1-r4`). Written, tested and hash-pinned BEFORE any observation exists:
its sha256 is part of the registration (`selection_study.ANALYSIS_SHA256`), so any edit is a visible new registration.

Pure: journal payloads in, a report out. No database, no settings, no network, no clock. Deterministic for a given input.
Rules: 07-selection-study-spec.md, "Analysis".
"""
from __future__ import annotations

import random

from . import selection_study as ss

FAMILY_ALPHA = 0.05
RESAMPLES = 10_000
SEED = 20260919
MIN_VALID_PER_SIDE = 60
MIN_SESSIONS_PER_SIDE = 20
MIN_COVERAGE_PCT = 80.0
MAX_COVERAGE_GAP_PTS = 15.0
DROP_BEST_SESSIONS = 3
FEATURE_ORDER = ("flag", "levelOrigin", "wait", "first15", "scenario4", "room")
FEE_PER_CONTRACT = 1.04                  # the registered cost; the final analysis takes no other value


def of_registration(row: dict) -> bool:
    return row.get("study") == ss.STUDY and row.get("registrationHash") == ss.REGISTRATION_HASH


def population(journal_rows: list[dict], *, excluded_sessions: set[str] | None = None) -> dict:
    """Journal payloads (in journal order) -> one row per opportunity. `c1Only` opportunities and rows of sessions that are not
    counted are set apart and COUNTED; rows of any other registration are counted and never analysed."""
    mine = [r for r in journal_rows if of_registration(r)]
    opens = [r for r in mine if r.get("kind") == "selection_study_open"]
    closes = [r for r in mine if r.get("kind") == "selection_study_close"]
    rows = ss.collapse(opens, closes)
    rows.sort(key=lambda r: (str(r.get("date")), int(r.get("signalTs") or 0), str(r.get("opportunityId"))))
    excluded = set(excluded_sessions or ())
    primary = [r for r in rows if not r.get("c1Only") and r.get("date") not in excluded]
    return {"all": rows, "primary": primary, "c1Only": [r for r in rows if r.get("c1Only")],
            "excludedSessionRows": [r for r in rows if r.get("date") in excluded],
            "otherRegistrations": sum(1 for r in journal_rows if str(r.get("kind", "")).startswith("selection_study_")
                                      and r.get("kind") not in ("selection_study_activation", "selection_study_final") and not of_registration(r)),
            "ignoredCloses": sum(int(r.get("ignoredCloses") or 0) for r in rows),
            "recoveredOpenings": sum(1 for r in rows if r.get("openingRecovered"))}


def _mean(v):
    return sum(v) / len(v) if v else float("nan")


def _sides(rows: list[dict], feature: str, fee: float):
    fav, rest, cov, sec = {}, {}, {"fav": [0, 0], "rest": [0, 0]}, {"fav": {}, "rest": {}}
    want = ss.FAVOURED[feature]
    for r in rows:
        val = str(((r.get("features") or {}).get(feature) or {}).get("value") or ss.UNKNOWN)
        if val == ss.UNKNOWN:
            continue
        side, key = (fav, "fav") if val == want else (rest, "rest")
        cov[key][0] += 1
        o = ss.outcome(r, fee)
        if o["primary"] is not None and r.get("complete", True):
            cov[key][1] += 1
            side.setdefault(str(r["date"]), []).append(float(o["primary"]))
        for k, v in (o.get("secondary") or {}).items():
            sec[key].setdefault(k, []).append(float(v))
    return fav, rest, cov, sec


def _d(fav: dict, rest: dict, days) -> float:
    a = [x for k in days for x in fav.get(k, [])]
    b = [x for k in days for x in rest.get(k, [])]
    return _mean(a) - _mean(b) if a and b else float("nan")


def feature_test(rows: list[dict], feature: str, fee: float, *, resamples: int = RESAMPLES, seed: int = SEED) -> dict:
    fav, rest, cov, sec = _sides(rows, feature, fee)
    days = sorted(set(fav) | set(rest))
    nf, nr = sum(len(v) for v in fav.values()), sum(len(v) for v in rest.values())
    unknown = sum(1 for r in rows if str(((r.get("features") or {}).get(feature) or {}).get("value") or ss.UNKNOWN) == ss.UNKNOWN)
    covf = 100.0 * cov["fav"][1] / cov["fav"][0] if cov["fav"][0] else 0.0
    covr = 100.0 * cov["rest"][1] / cov["rest"][0] if cov["rest"][0] else 0.0
    out = {"feature": feature, "favoured": ss.FAVOURED[feature], "nFavoured": nf, "nRest": nr, "sessionsFavoured": len(fav), "sessionsRest": len(rest),
           "opportunitiesFavoured": cov["fav"][0], "opportunitiesRest": cov["rest"][0], "coverageFavouredPct": round(covf, 1),
           "coverageRestPct": round(covr, 1), "unknownFeature": unknown, "d": None, "ci95": None, "p": None, "favouredMean": None,
           "restMean": None, "dWithoutBestSessions": None, "judgeable": False, "whyNotJudgeable": [],
           # descriptive only, never tested (registration: secondaryTested = false)
           "secondaryDescriptive": {side: {k: round(_mean(v), 3) for k, v in sorted(sec[side].items())} for side in ("fav", "rest")}}
    why = out["whyNotJudgeable"]
    if nf < MIN_VALID_PER_SIDE or nr < MIN_VALID_PER_SIDE:
        why.append(f"fewer than {MIN_VALID_PER_SIDE} valid outcomes on a side ({nf} / {nr})")
    if len(fav) < MIN_SESSIONS_PER_SIDE or len(rest) < MIN_SESSIONS_PER_SIDE:
        why.append(f"fewer than {MIN_SESSIONS_PER_SIDE} sessions on a side ({len(fav)} / {len(rest)})")
    if covf < MIN_COVERAGE_PCT or covr < MIN_COVERAGE_PCT:
        why.append(f"coverage under {MIN_COVERAGE_PCT:g}% on a side ({covf:.1f} / {covr:.1f})")
    if abs(covf - covr) > MAX_COVERAGE_GAP_PTS:
        why.append(f"coverage differs by more than {MAX_COVERAGE_GAP_PTS:g} points between the sides")
    if nf == 0 or nr == 0:
        return out
    d = _d(fav, rest, days)
    rng = random.Random(f"{seed}:{feature}")
    boots = []
    for _ in range(resamples):                          # whole SESSIONS are resampled: within-session dependence is preserved
        x = _d(fav, rest, rng.choices(days, k=len(days)))
        if x == x:
            boots.append(x)
    boots.sort()
    lo, hi = boots[int(0.025 * len(boots))], boots[min(len(boots) - 1, int(0.975 * len(boots)))]
    p = min(1.0, 2.0 * min(sum(b <= 0 for b in boots), sum(b >= 0 for b in boots)) / len(boots))
    contrib = {k: sum(fav.get(k, [])) / nf - sum(rest.get(k, [])) / nr for k in days}
    keep = [k for k in days if k not in set(sorted(days, key=lambda k: (-contrib[k], k))[:DROP_BEST_SESSIONS])]
    out.update(d=round(d, 3), ci95=[round(lo, 3), round(hi, 3)], p=max(p, 1.0 / len(boots)),
               favouredMean=round(_mean([x for v in fav.values() for x in v]), 3), restMean=round(_mean([x for v in rest.values() for x in v]), 3),
               dWithoutBestSessions=round(_d(fav, rest, keep), 3), judgeable=not why)
    return out


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values (monotone). Ties are ordered by the frozen feature order."""
    order = sorted(pvalues, key=lambda k: (pvalues[k], FEATURE_ORDER.index(k) if k in FEATURE_ORDER else 99, k))
    m, out, running = len(order), {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (m - i) * pvalues[k]))
        out[k] = running
    return out


def family_pvalues(tests: list[dict]) -> dict[str, float]:
    """The frozen Holm FAMILY is all six primary tests. A feature that is not judgeable (or has no p) enters the family with
    p = 1: it cannot pass, and it still counts in the family size, so dropping a feature never loosens the others."""
    return {t["feature"]: (float(t["p"]) if t["judgeable"] and t["p"] is not None else 1.0) for t in tests}


def verdict(t: dict, p_holm: float | None) -> tuple[str, list[str]]:
    if not t["judgeable"]:
        return "insufficient evidence", list(t["whyNotJudgeable"])
    fails = []
    if p_holm is None or p_holm >= FAMILY_ALPHA:
        fails.append("Holm-adjusted p is not below 0.05")
    if not (t["d"] > 0 and t["ci95"][0] > 0):
        fails.append("the improvement is not positive with its interval above zero")
    if not t["favouredMean"] > 0:
        fails.append("the favoured bucket's own mean is not above zero after costs")
    if not t["dWithoutBestSessions"] > 0:
        fails.append("the sign does not survive removing the three most favourable sessions")
    return ("pass", []) if not fails else ("fail", fails)


def choose(tests: list[dict]) -> str | None:
    """Exactly ONE passing feature goes forward: smallest Holm p, then the larger lower bound of d, then the feature order."""
    passers = [t for t in tests if t.get("verdict") == "pass"]
    if not passers:
        return None
    passers.sort(key=lambda t: (t["pHolm"], -t["ci95"][0], FEATURE_ORDER.index(t["feature"])))
    return passers[0]["feature"]


def analyse(journal_rows: list[dict], fee_per_contract: float = FEE_PER_CONTRACT, *, excluded_sessions: set[str] | None = None,
            resamples: int = RESAMPLES, seed: int = SEED) -> dict:
    pop = population(journal_rows, excluded_sessions=excluded_sessions)
    rows = pop["primary"]
    tests = [feature_test(rows, f, fee_per_contract, resamples=resamples, seed=seed) for f in FEATURE_ORDER]
    adj = holm(family_pvalues(tests))
    for t in tests:
        t["pHolm"] = adj.get(t["feature"])
        t["verdict"], t["reasons"] = verdict(t, t["pHolm"])
    chosen = choose(tests)
    return {"study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH, "opportunities": len(pop["all"]), "primaryPopulation": len(rows),
            "c1Only": len(pop["c1Only"]), "excludedSessionRows": len(pop["excludedSessionRows"]), "otherRegistrations": pop["otherRegistrations"],
            "ignoredCloses": pop["ignoredCloses"], "recoveredOpenings": pop["recoveredOpenings"], "sessions": len({r["date"] for r in rows}),
            "coverage": {f: ss.coverage(rows, f, fee_per_contract) for f in FEATURE_ORDER}, "tests": tests,
            "studyOutcome": ("at least one pass" if chosen else "none"), "featureCarriedForward": chosen,
            "parameters": {"familyAlpha": FAMILY_ALPHA, "family": list(FEATURE_ORDER), "resamples": resamples, "seed": seed,
                           "minValidPerSide": MIN_VALID_PER_SIDE, "minSessionsPerSide": MIN_SESSIONS_PER_SIDE, "minCoveragePct": MIN_COVERAGE_PCT,
                           "maxCoverageGapPts": MAX_COVERAGE_GAP_PTS, "winsorPct": ss.WINSOR_PCT, "feePerContract": fee_per_contract}}
