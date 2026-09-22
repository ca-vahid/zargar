"""Selection study S1 (registration `s1-r4`): lifecycle, session accounting, endpoint and the frozen final sample.

A PURE function of durable records, so it is identical before and after any restart and can be recomputed by anyone:
  - the activation row (`selection_study_activation`, journaled once by the operator tool, pins registration + analysis hash + build),
  - `SettingChanged` rows for `techniques.team2.selection_study` (when collection was enabled),
  - `TechniquePlanRestored` times of Team2 plans (an engine restart restores every armed plan),
  - regular-session minute bars of SPY/QQQ/IWM (provider alpaca) for the outage rule,
  - the NYSE calendar (`market_calendar`: holidays and 13:00 early closes), in America/New_York,
  - the study's own open/close rows, and `selection_study_final` rows.

States: prepared -> collecting -> (stopped_insufficient_coverage | ready_for_final_analysis) -> finalized.

Session statuses, decided WITHOUT looking at any return (first matching rule wins):
  disabled   the collector was off for the whole regular session;
  partial    it was on for only part of the session, or the study was activated during it;
  excluded   on for the whole session, but: a 13:00 early close; an engine restart between 09:30 and 15:45 ET; or a feed outage
             (three or more consecutive regular-session minutes without an alpaca 1m bar for SPY, QQQ or IWM);
  counted    everything else, INCLUDING a session with zero opportunities.
Only `counted` sessions advance the count and only their records enter the sample. Excluded sessions do NOT advance the count.

Endpoint: the CLOSE (16:00 ET) of the 60th counted session, or the close of the 2026-12-18 session, whichever comes first. A
session counts only once its close has passed, so an opening record on the 60th morning cannot unlock the analysis.
Early stop: at the close of the 15th and every later counted session before the endpoint, if overall valid-outcome coverage of the
primary population so far is under 60%, collection is `stopped_insufficient_coverage` (fix, re-register, restart). Coverage only.
Stopping the study never touches a trading book, a setting or a rule; the operator switches the collector off.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from ...marketstructure.market_calendar import is_early_close, session_close_minutes, trading_days
from . import selection_study as ss
from . import selection_study_analysis as an

SETTING_KEY = "techniques.team2.selection_study"
COHORT_KIND = "team2_collection_cohort"   # journal kind for a collection cohort. NOT `selection_study_*`:
                                          # that prefix is swept into the study population, and a cohort must be
                                          # readable beside the population and incapable of entering it.
TARGET_SESSIONS = 60
DEADLINE = dt.date(2026, 12, 18)
EARLY_STOP_FROM = 15
EARLY_STOP_MIN_COVERAGE_PCT = 60.0
OUTAGE_GAP_MIN = 3
RESTART_CUTOFF = (15, 45)
MIN = 60_000
STATES = ("prepared", "collecting", "stopped_insufficient_coverage", "ready_for_final_analysis", "finalized")


def _ms(d: dt.date, h: int, m: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, h, m, tzinfo=ss.ET).timestamp() * 1000)


def session_bounds(d: dt.date) -> tuple[int, int]:
    close = session_close_minutes(d)
    return _ms(d, 9, 30), _ms(d, close // 60, close % 60)


def et_date(ts_ms: int) -> dt.date:
    return dt.datetime.fromtimestamp(int(ts_ms) / 1000, ss.ET).date()


def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)


def sha(x) -> str:
    return hashlib.sha256(_canon(x).encode()).hexdigest()


def activation_of(rows: list[dict]) -> dict | None:
    """The FIRST activation row for THIS registration (study id, registration hash and analysis hash all match)."""
    for r in rows:
        if (r.get("kind") == "selection_study_activation" and r.get("study") == ss.STUDY and r.get("registrationHash") == ss.REGISTRATION_HASH
                and r.get("analysisSha256") == ss.ANALYSIS_SHA256):
            return r
    return None


def enabled_intervals(setting_events: list[tuple[int, object]], until_ms: int) -> list[tuple[int, int]]:
    """[(from, to)] during which the collector was `collect`. Before the first change the value is the default, `off`."""
    out, on_since = [], None
    for ts, new in sorted(setting_events, key=lambda x: int(x[0])):
        on = str(new or "off").lower() == "collect"
        if on and on_since is None:
            on_since = int(ts)
        elif not on and on_since is not None:
            out.append((on_since, int(ts)))
            on_since = None
    if on_since is not None:
        out.append((on_since, int(until_ms)))
    return out


def outage_dates(minute_ts_by_symbol: dict[str, list[int]], dates: list[dt.date]) -> dict[str, str]:
    """{date: reason} for sessions where SPY, QQQ or IWM lacks OUTAGE_GAP_MIN or more consecutive regular-session 1m bars."""
    out = {}
    have = {s: set(int(t) for t in v) for s, v in minute_ts_by_symbol.items()}
    for d in dates:
        o, c = session_bounds(d)
        for s in ("SPY", "QQQ", "IWM"):
            run = worst = 0
            for t in range(o, c, MIN):
                run = run + 1 if t not in have.get(s, set()) else 0
                worst = max(worst, run)
            if worst >= OUTAGE_GAP_MIN:
                out[d.isoformat()] = f"feed outage: {s} missing {worst} consecutive regular-session minutes"
                break
    return out


def classify(d: dt.date, activation_ms: int, intervals: list[tuple[int, int]], restart_ts: list[int], outages: dict[str, str]) -> dict:
    o, c = session_bounds(d)
    covered = sum(max(0, min(b, c) - max(a, o)) for a, b in intervals)
    if covered <= 0:
        return {"date": d.isoformat(), "status": "disabled", "reasons": ["collector off for the whole session"]}
    if activation_ms > o:
        return {"date": d.isoformat(), "status": "partial", "reasons": ["study activated during the session"]}
    if covered < c - o:
        return {"date": d.isoformat(), "status": "partial", "reasons": ["collector on for only part of the session"]}
    reasons = []
    if is_early_close(d):
        reasons.append("13:00 early close")
    cut = _ms(d, *RESTART_CUTOFF)
    hits = sorted(t for t in restart_ts if o <= int(t) <= cut)
    if hits:
        reasons.append(f"engine restart at {dt.datetime.fromtimestamp(hits[0] / 1000, ss.ET):%H:%M:%S} ET")
    if d.isoformat() in outages:
        reasons.append(outages[d.isoformat()])
    return {"date": d.isoformat(), "status": "excluded" if reasons else "counted", "reasons": reasons}


def _coverage_so_far(study_rows: list[dict], counted: set[str]) -> tuple[int, int]:
    rows = [r for r in an.population(study_rows)["primary"] if r.get("date") in counted]
    valid = sum(1 for r in rows if ss.outcome(r, an.FEE_PER_CONTRACT)["primary"] is not None and r.get("complete", True))
    return len(rows), valid


def lifecycle(*, activation_rows: list[dict], setting_events: list[tuple[int, object]], restart_ts: list[int],
              outages: dict[str, str], study_rows: list[dict], now_ms: int, final_rows: list[dict] | None = None,
              target: int = TARGET_SESSIONS, deadline: dt.date = DEADLINE) -> dict:
    act = activation_of(activation_rows)
    base = {"study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH, "analysisSha256": ss.ANALYSIS_SHA256, "targetSessions": target,
            "deadline": deadline.isoformat(), "nowMs": int(now_ms)}
    if act is None:
        return {**base, "state": "prepared", "activation": None, "sessions": [], "countedSessions": 0, "endpointMs": None,
                "endpointReason": None, "stopMs": None, "stopReason": None, "firstEligibleSession": None, "statusCounts": {}}
    a_ms = int(act["activatedAt"])
    intervals = enabled_intervals(setting_events, now_ms)
    days = trading_days(et_date(a_ms), min(et_date(now_ms), deadline)) if et_date(a_ms) <= deadline else []
    sessions, counted, n = [], set(), 0
    endpoint = reason = stop = stop_reason = None
    first_eligible = None
    for d in days:
        o, c = session_bounds(d)
        if c <= a_ms:
            continue
        if first_eligible is None and o >= a_ms:
            first_eligible = d.isoformat()
        if endpoint is not None or stop is not None:
            sessions.append({"date": d.isoformat(), "status": "after_endpoint", "reasons": ["after the endpoint"]})
            continue
        if now_ms < c:
            sessions.append({"date": d.isoformat(), "status": "in_progress" if now_ms >= o else "not_started", "reasons": []})
            continue
        s = classify(d, a_ms, intervals, restart_ts, outages)
        sessions.append(s)
        if s["status"] == "counted":
            n += 1
            counted.add(s["date"])
            s["count"] = n
            if n >= target:
                endpoint, reason = c, f"close of the {target}th counted session ({d.isoformat()})"
            elif n >= EARLY_STOP_FROM:
                opps, valid = _coverage_so_far(study_rows, counted)
                if opps and 100.0 * valid / opps < EARLY_STOP_MIN_COVERAGE_PCT:
                    stop, stop_reason = c, (f"valid-outcome coverage {100.0 * valid / opps:.1f}% < {EARLY_STOP_MIN_COVERAGE_PCT:g}% "
                                            f"after {n} counted sessions")
        if endpoint is None and stop is None and d == deadline:
            endpoint, reason = c, f"deadline: close of the {deadline.isoformat()} session"
    sealed = sealed_of(final_rows or [])
    finals = [sealed] if sealed is not None else []
    if stop is not None:
        state = "stopped_insufficient_coverage"
    elif finals:
        state = "finalized"
    elif endpoint is not None and now_ms >= endpoint:
        state = "ready_for_final_analysis"
    else:
        state = "collecting"
    counts: dict[str, int] = {}
    for s in sessions:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    return {**base, "state": state, "activation": {k: act.get(k) for k in ("activatedAt", "build", "registrationHash", "analysisSha256", "firstEligibleSession")},
            "firstEligibleSession": first_eligible, "sessions": sessions, "countedSessions": n, "countedDates": sorted(counted),
            "statusCounts": counts, "endpointMs": endpoint, "endpointReason": reason, "stopMs": stop, "stopReason": stop_reason,
            "finalRecorded": ({k: sealed[k] for k in ("manifestSha256", "resultSha256", "intact", "eventId")} if sealed else None),
            # the lifecycle is a READ: it never switches the collector off. When the study no longer uses new records and the
            # collector is still on, the operator switches it off (`coverage_view` says so); trading books are never touched.
            "collectorEnabledNow": bool(intervals and intervals[-1][1] >= int(now_ms))}


def cohort_for(date: str, cohorts: list[dict] | None) -> str | None:
    """Which collection cohort a session date falls in. Pure; `None` when none is recorded.

    A cohort is an inclusive date window over the instrument state the study collected under. It
    does not and must not affect counting: `_classify` is the only thing that decides that, and it
    reads the frozen registration's three exclusion rules alone.
    """
    for c in (cohorts or []):
        lo, hi = str(c.get("fromDate") or ""), str(c.get("toDate") or "")
        if (not lo or date >= lo) and (not hi or date <= hi):
            return str(c.get("cohort") or "") or None
    return None


def label_cohorts(life: dict, cohorts: list[dict] | None) -> dict:
    """Stamp each session with its cohort and summarise the counted ones per cohort. Additive: no
    session's `status` is read or changed here."""
    out = dict(life)
    sessions = [{**s, "cohort": cohort_for(s["date"], cohorts)} for s in (life.get("sessions") or [])]
    per: dict[str, int] = {}
    for s in sessions:
        if s["status"] == "counted":
            per[str(s.get("cohort") or "unassigned")] = per.get(str(s.get("cohort") or "unassigned"), 0) + 1
    out["sessions"] = sessions
    out["cohorts"] = list(cohorts or [])
    out["countedByCohort"] = per
    return out


def coverage_view(life: dict, study_rows: list[dict]) -> dict:
    """The ONLY operational view before the endpoint: lifecycle, session accounting, counts and coverage. No outcome value."""
    counted = set(life.get("countedDates") or [])
    pop = an.population(study_rows)
    rows = [r for r in pop["primary"] if r.get("date") in counted]
    opps, valid = len(rows), sum(1 for r in rows if ss.outcome(r, an.FEE_PER_CONTRACT)["primary"] is not None and r.get("complete", True))
    health = {}
    for r in study_rows:
        for k, v in (r.get("studyHealth") or {}).items():
            health[k] = max(int(health.get(k, 0)), int(v or 0))
    action = None
    if life["state"] in ("stopped_insufficient_coverage", "ready_for_final_analysis", "finalized") and life.get("collectorEnabledNow"):
        action = (f"the study is {life['state']} and the collector is still ON: switch {SETTING_KEY} to off (PATCH /api/settings). "
                  "This tool never changes a setting; later records are outside the sample either way; no trading book is affected")
    return {"view": "coverage only (no outcome is shown)", "operatorAction": action, "collectorEnabledNow": life.get("collectorEnabledNow"),
            "state": life["state"], "study": life["study"], "registrationHash": life["registrationHash"],
            "countedSessions": life["countedSessions"], "targetSessions": life["targetSessions"], "deadline": life["deadline"],
            "statusCounts": life["statusCounts"], "nonCounted": [s for s in life["sessions"] if s["status"] not in ("counted",)],
            # collection cohorts: metadata beside the count, never part of it
            "cohorts": life.get("cohorts") or [], "countedByCohort": life.get("countedByCohort") or {},
            "countedSessionsByDate": [{"date": s["date"], "cohort": s.get("cohort")}
                                      for s in life.get("sessions") or [] if s["status"] == "counted"],
            "opportunitiesInCountedSessions": opps, "validOutcomes": valid, "coveragePct": (round(100.0 * valid / opps, 1) if opps else None),
            "c1Only": len(pop["c1Only"]), "otherRegistrations": pop["otherRegistrations"], "ignoredCloses": pop["ignoredCloses"],
            "recoveredOpenings": pop["recoveredOpenings"], "collectorHealth": health,
            "byFeature": {f: ss.coverage(rows, f, an.FEE_PER_CONTRACT) for f in an.FEATURE_ORDER}}


def _journal_order(rows: list[dict]) -> list[dict]:
    """JOURNAL order: by `_eventId` (the loader's events.id) when present; rows without one keep their given order (stable).
    The first-opening / first-close rules are decided in THIS order, before anything is canonicalised for hashing."""
    return sorted(rows, key=lambda r: (r.get("_eventId") is None, int(r.get("_eventId") or 0)))


_TRANSPORT = ("_eventId", "selectedOpening", "selectedClose", "openings", "ignoredCloses")   # identities and counts: listed, not hashed


def _select(rows: list[dict]) -> list[dict]:
    """The evidence the analysis sees, decided in JOURNAL order before any canonicalisation: every opening (they say which books
    examined the opportunity) and, per opportunity, only the FIRST close that carries the owning opening's hash (the owner = the
    first opening that is not a `duplicateOf`); an opportunity without any opening keeps its first close (recovered opening).
    Later or foreign closes are dropped here and counted in the diagnostics, so they can never change the sample or its hashes."""
    opens = [r for r in rows if r.get("kind") == "selection_study_open"]
    owner: dict[str, str] = {}
    for r in opens:
        oid = str(r.get("opportunityId"))
        if oid not in owner and not r.get("duplicateOf"):
            owner[oid] = str(r.get("openHash"))
    for r in opens:
        owner.setdefault(str(r.get("opportunityId")), str(r.get("openHash")))
    chosen: dict[str, dict] = {}
    for r in rows:
        if r.get("kind") != "selection_study_close":
            continue
        oid = str(r.get("opportunityId"))
        if oid in chosen:
            continue
        if oid not in owner or str(r.get("openHash")) == owner[oid]:
            chosen[oid] = r
    keep = {id(c) for c in chosen.values()}
    return [r for r in rows if r.get("kind") == "selection_study_open" or id(r) in keep]


def _evidence(r: dict) -> dict:
    """A selected row's content for hashing, without transport fields (the identities are listed separately)."""
    return {k: v for k, v in r.items() if k not in _TRANSPORT}


def final_sample(life: dict, study_rows: list[dict]) -> tuple[list[dict], dict]:
    """The frozen sample and its manifest. Only rows of THIS registration, of COUNTED sessions, with a signal before the endpoint,
    in JOURNAL order; an observation whose quote is after the endpoint is made invalid ("after endpoint"). The manifest hashes the
    SELECTED evidence (one row per opportunity: first opening, first close bound to it) and lists the selected identities; nothing
    outside the window enters it, so rows that arrive later outside the window cannot change it."""
    if life["state"] not in ("ready_for_final_analysis", "finalized"):
        raise ValueError(f"final analysis refused: study is {life['state']}")
    endpoint = int(life["endpointMs"])
    counted = set(life["countedDates"])
    inc = []
    for r in _journal_order(study_rows):
        if r.get("kind") not in ("selection_study_open", "selection_study_close") or not an.of_registration(r):
            continue
        if r.get("date") not in counted or int(r.get("signalTs") or 0) >= endpoint:
            continue
        row = json.loads(_canon(r))
        for o in (row.get("observations") or {}).values():
            if o.get("valid") and int(o.get("quoteTs") or 0) > endpoint:
                o["valid"], o["reason"] = False, "after endpoint"
        inc.append(row)
    inc = _select(inc)                                    # every opening + the ONE close bound to the owning opening, journal order
    selected = an.population(inc)["all"]                  # collapse, then a canonical (date, signal, id) order
    sessions = [s for s in life["sessions"] if s["status"] in ("counted", "excluded", "partial", "disabled")]
    manifest = {"study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH, "analysisSha256": ss.ANALYSIS_SHA256,
                "activation": life["activation"], "window": {"fromMs": int(life["activation"]["activatedAt"]), "endpointMs": endpoint,
                                                             "endpointReason": life["endpointReason"]},
                "countedSessions": life["countedDates"],
                "sessionClassification": sessions,       # the eligibility decision, with its evidence (reasons), frozen here
                "selectedRecords": [{"opportunityId": r.get("opportunityId"), "openHash": r.get("openHash"),
                                     "openingEventId": r.get("selectedOpening"), "closeEventId": r.get("selectedClose"),
                                     "complete": bool(r.get("complete")), "c1Only": bool(r.get("c1Only"))} for r in selected],
                "selectedEvidenceSha256": sha([_evidence(r) for r in selected]), "feePerContract": an.FEE_PER_CONTRACT,
                "analysisParameters": {"resamples": an.RESAMPLES, "seed": an.SEED, "familyAlpha": an.FAMILY_ALPHA}}
    return inc, manifest


def outside_diagnostics(life: dict, study_rows: list[dict]) -> dict:
    """Rows of this and other registrations that are NOT in the sample, by reason. Reported beside the manifest, never inside it."""
    endpoint = int(life["endpointMs"]) if life.get("endpointMs") is not None else None
    counted = set(life.get("countedDates") or [])
    out: dict[str, int] = {}
    for r in study_rows:
        if r.get("kind") not in ("selection_study_open", "selection_study_close"):
            continue
        why = ("other registration" if not an.of_registration(r) else "session not counted" if r.get("date") not in counted
               else "signal after the endpoint" if endpoint is not None and int(r.get("signalTs") or 0) >= endpoint else None)
        if why:
            out[why] = out.get(why, 0) + 1
    return dict(sorted(out.items()))


def _finite(x):
    import math
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_finite(v) for v in x]
    return x


def finalise(life: dict, study_rows: list[dict]) -> dict:
    """Frozen final analysis from the durable inputs: the same inputs give the same manifest, result and hashes, in any transport
    order. Costs, window, exclusions and the registration come from the registration and the lifecycle; nothing is a parameter."""
    inc, manifest = final_sample(life, study_rows)
    report = _finite(an.analyse(inc, an.FEE_PER_CONTRACT))   # JSON-safe: a non-finite number becomes null before hashing
    return {"manifest": manifest, "manifestSha256": sha(manifest), "report": report, "resultSha256": sha(report),
            "diagnostics": {"rowsOutsideSample": outside_diagnostics(life, study_rows), **inside_diagnostics(life, study_rows)}}


def inside_diagnostics(life: dict, study_rows: list[dict]) -> dict:
    """Counts about the in-window journal that are NOT evidence: closes that were not selected, recovered openings, repeated openings."""
    endpoint, counted = int(life["endpointMs"]), set(life["countedDates"])
    rows = [r for r in _journal_order(study_rows) if r.get("kind") in ("selection_study_open", "selection_study_close") and an.of_registration(r)
            and r.get("date") in counted and int(r.get("signalTs") or 0) < endpoint]
    pop = an.population(rows)
    return {"closesNotSelected": pop["ignoredCloses"], "recoveredOpenings": pop["recoveredOpenings"],
            "opportunitiesWithRepeatedOpenings": sum(1 for r in pop["all"] if int(r.get("openings") or 1) > 1)}


def seal_payload(fin: dict) -> dict:
    """The ONE journal row that seals the study: the full manifest and result with their hashes. The first such row wins forever."""
    return {"kind": "selection_study_final", "study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH,
            "manifestSha256": fin["manifestSha256"], "resultSha256": fin["resultSha256"], "manifest": fin["manifest"], "report": fin["report"]}


def sealed_of(final_rows: list[dict]) -> dict | None:
    """The FIRST final row of this registration (journal order), with an integrity check of its embedded manifest and result."""
    for r in _journal_order(final_rows or []):
        if r.get("kind") == "selection_study_final" and r.get("study") == ss.STUDY and r.get("registrationHash") == ss.REGISTRATION_HASH:
            intact = (isinstance(r.get("manifest"), dict) and isinstance(r.get("report"), dict)
                      and sha(r["manifest"]) == r.get("manifestSha256") and sha(r["report"]) == r.get("resultSha256"))
            return {"manifest": r.get("manifest"), "manifestSha256": r.get("manifestSha256"), "report": r.get("report"),
                    "resultSha256": r.get("resultSha256"), "intact": intact, "eventId": r.get("_eventId")}
    return None


def drift(sealed: dict, life: dict, study_rows: list[dict]) -> dict:
    """What a recomputation from TODAY's records would give, compared with the seal. Reported, never applied."""
    try:
        again = finalise(life, study_rows)
    except ValueError as exc:
        return {"recomputable": False, "why": str(exc)}
    sm, am = sealed.get("manifest") or {}, again["manifest"]
    ss_, as_ = {s["date"]: s["status"] for s in sm.get("sessionClassification") or []}, {s["date"]: s["status"] for s in am["sessionClassification"]}
    sr = {(x["opportunityId"], x["openHash"], x.get("closeEventId")) for x in sm.get("selectedRecords") or []}
    ar = {(x["opportunityId"], x["openHash"], x.get("closeEventId")) for x in am["selectedRecords"]}
    return {"recomputable": True, "manifestWouldChange": again["manifestSha256"] != sealed.get("manifestSha256"),
            "resultWouldChange": again["resultSha256"] != sealed.get("resultSha256"),
            "sessionsReclassified": sorted({d for d in set(ss_) | set(as_) if ss_.get(d) != as_.get(d)}),
            "recordsOnlyInSeal": len(sr - ar), "recordsOnlyInRecomputation": len(ar - sr)}


def resolve_final(life: dict, study_rows: list[dict], final_rows: list[dict]) -> dict:
    """The authoritative final answer: the SEALED artifact when one exists (with drift reported beside it), else a computation
    that is not yet sealed."""
    sealed = sealed_of(final_rows)
    if sealed is not None:
        return {"sealed": True, "artifact": sealed, "drift": drift(sealed, life, study_rows)}
    fin = finalise(life, study_rows)
    return {"sealed": False, "artifact": fin, "drift": None}


def artifact_integrity(recorded: dict) -> dict:
    """Hash the ACTUAL saved payloads and compare them with their declared hashes. An edited or missing manifest or report fails
    here, whatever the declared values say; the computed hashes are what every later comparison uses."""
    problems, computed = [], {}
    for key, hkey in (("manifest", "manifestSha256"), ("report", "resultSha256")):
        payload, declared = recorded.get(key), recorded.get(hkey)
        if not isinstance(payload, dict) or not payload:
            problems.append(f"{key} payload is missing")
        else:
            computed[hkey] = sha(payload)
        if not isinstance(declared, str) or not declared:
            problems.append(f"declared {hkey} is missing")
        elif hkey in computed and computed[hkey] != declared:
            problems.append(f"the saved {key} does not hash to its declared {hkey}")
    return {"intact": not problems, "problems": problems,
            "manifestSha256": computed.get("manifestSha256"), "resultSha256": computed.get("resultSha256"),
            "declaredManifestSha256": recorded.get("manifestSha256"), "declaredResultSha256": recorded.get("resultSha256")}


def verify(recorded: dict, life: dict, study_rows: list[dict], final_rows: list[dict] | None = None) -> dict:
    """Verify a recorded artifact: (1) its own payloads must hash to their declared values, (2) it must BE the sealed artifact when
    a seal exists, and (3) separately, whether a recomputation from today's records would differ (drift). A valid sealed result with
    later drift stays valid; an edited or missing payload never does."""
    sealed = sealed_of(final_rows or [])
    again = finalise(life, study_rows)
    rec = artifact_integrity(recorded)
    out = {"recordedIntact": rec["intact"], "problems": rec["problems"], "recorded": rec,
           "matchesSeal": (None if sealed is None else bool(rec["intact"] and sealed["intact"]
                                                            and rec["manifestSha256"] == sealed["manifestSha256"]
                                                            and rec["resultSha256"] == sealed["resultSha256"])),
           "sealIntact": None if sealed is None else sealed["intact"],
           "manifestMatches": bool(rec["intact"] and again["manifestSha256"] == rec["manifestSha256"]),
           "resultMatches": bool(rec["intact"] and again["resultSha256"] == rec["resultSha256"]),
           "manifestSha256": again["manifestSha256"], "resultSha256": again["resultSha256"]}
    out["valid"] = bool(rec["intact"] and (out["matchesSeal"] is not False))
    if sealed is not None:
        out["drift"] = drift(sealed, life, study_rows)
    return out
