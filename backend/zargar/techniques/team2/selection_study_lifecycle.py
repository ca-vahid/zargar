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
    finals = [r for r in (final_rows or []) if r.get("kind") == "selection_study_final" and r.get("study") == ss.STUDY
              and r.get("registrationHash") == ss.REGISTRATION_HASH]
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
            "finalRecorded": finals[0] if finals else None}


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
    return {"view": "coverage only (no outcome is shown)", "state": life["state"], "study": life["study"], "registrationHash": life["registrationHash"],
            "countedSessions": life["countedSessions"], "targetSessions": life["targetSessions"], "deadline": life["deadline"],
            "statusCounts": life["statusCounts"], "nonCounted": [s for s in life["sessions"] if s["status"] not in ("counted",)],
            "opportunitiesInCountedSessions": opps, "validOutcomes": valid, "coveragePct": (round(100.0 * valid / opps, 1) if opps else None),
            "c1Only": len(pop["c1Only"]), "otherRegistrations": pop["otherRegistrations"], "ignoredCloses": pop["ignoredCloses"],
            "recoveredOpenings": pop["recoveredOpenings"], "collectorHealth": health,
            "byFeature": {f: ss.coverage(rows, f, an.FEE_PER_CONTRACT) for f in an.FEATURE_ORDER}}


def final_sample(life: dict, study_rows: list[dict]) -> tuple[list[dict], dict]:
    """The frozen sample and its manifest. Only rows of THIS registration, of COUNTED sessions, with a signal before the endpoint;
    an observation whose quote is after the endpoint is made invalid ("after endpoint")."""
    if life["state"] not in ("ready_for_final_analysis", "finalized"):
        raise ValueError(f"final analysis refused: study is {life['state']}")
    endpoint = int(life["endpointMs"])
    counted = set(life["countedDates"])
    inc, outside = [], {}
    for r in study_rows:
        if r.get("kind") not in ("selection_study_open", "selection_study_close"):
            continue
        if not an.of_registration(r):
            outside["other registration"] = outside.get("other registration", 0) + 1
            continue
        if r.get("date") not in counted:
            outside["session not counted"] = outside.get("session not counted", 0) + 1
            continue
        if int(r.get("signalTs") or 0) >= endpoint:
            outside["signal after the endpoint"] = outside.get("signal after the endpoint", 0) + 1
            continue
        row = json.loads(_canon(r))
        for o in (row.get("observations") or {}).values():
            if o.get("valid") and int(o.get("quoteTs") or 0) > endpoint:
                o["valid"], o["reason"] = False, "after endpoint"
        inc.append(row)
    inc.sort(key=lambda r: (str(r.get("date")), str(r.get("opportunityId")), str(r.get("kind")), str(r.get("openHash")), _canon(r)))
    manifest = {"study": ss.STUDY, "registrationHash": ss.REGISTRATION_HASH, "analysisSha256": ss.ANALYSIS_SHA256,
                "activation": life["activation"], "window": {"fromMs": int(life["activation"]["activatedAt"]), "endpointMs": endpoint,
                                                             "endpointReason": life["endpointReason"]},
                "countedSessions": life["countedDates"],
                # sessions up to the endpoint only, so a later run (more `after_endpoint` days) reproduces the same manifest
                "nonCountedSessions": [s for s in life["sessions"] if s["status"] in ("disabled", "partial", "excluded")],
                "records": [{"kind": r["kind"], "opportunityId": r.get("opportunityId"), "openHash": r.get("openHash")} for r in inc],
                "rowsOutsideSample": dict(sorted(outside.items())), "inputSha256": sha(inc), "feePerContract": an.FEE_PER_CONTRACT,
                "analysisParameters": {"resamples": an.RESAMPLES, "seed": an.SEED, "familyAlpha": an.FAMILY_ALPHA}}
    return inc, manifest


def finalise(life: dict, study_rows: list[dict]) -> dict:
    """Frozen final analysis: identical inputs give identical manifest, result and hashes. Costs, window, exclusions and the
    registration are taken from the registration and the lifecycle; nothing is a parameter."""
    inc, manifest = final_sample(life, study_rows)
    report = an.analyse(inc, an.FEE_PER_CONTRACT)
    return {"manifest": manifest, "manifestSha256": sha(manifest), "report": report, "resultSha256": sha(report)}


def verify(recorded: dict, life: dict, study_rows: list[dict]) -> dict:
    """Recompute the final analysis and compare it with a recorded one."""
    again = finalise(life, study_rows)
    return {"manifestMatches": again["manifestSha256"] == recorded.get("manifestSha256"),
            "resultMatches": again["resultSha256"] == recorded.get("resultSha256"),
            "manifestSha256": again["manifestSha256"], "resultSha256": again["resultSha256"]}
