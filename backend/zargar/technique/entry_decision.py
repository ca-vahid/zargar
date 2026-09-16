"""EM deterministic entry decision (`deterministic-entry-v1`, 2026-09-15; DETERMINISTIC-ENTRY-IMPLEMENTATION-PLAN).

The live EM entry decision is made by APPLICATION RULES: the actual `TriggerTracker` transition that fired, the
plan's saved geometry and the effective thresholds. No model, no chart, no I/O, no clock, no settings read here -
the caller freezes everything into an `EntrySnapshot` and `evaluate_entry` is pure and replayable.

`allow` means the SETUP-level rules permit proceeding to the existing order checks (contract pick / bounded quote
refresh / sizing / admission / never-chase / R2 / final guard / RiskGate). It is never an executor bypass and never a
fill. `refuse` is a deterministic refusal with stable reason codes - it is NOT `critic_killed` and no advisory
critic policy can downgrade it. `defer` means a required input is missing (`unknown_required`): nothing is guessed
and no model is asked.

Rule map (v1 formalises the rules already responsible for execution; no new filter):
  plan_current       the plan is armed for this session and the trigger is the saved one (identity + geometry)
  geometry           entry/stop/targets present and on the right side of each other for the direction
  tracker_fired      the tracker's own state machine reached `fired` on a COMPLETED bar (never from a kind label)
  stop_intact        the firing bar did not close through the stop (T4.3d)
  window             the fire happened in an eligible window per the tracker (R6 / C3 gap-day wait)
  gap                gap rules judged (or explicitly unchecked - recorded, kept as today)
  volume             the tracker's measured relative volume for the branch that fired (floor / surge), or the
                     branch that deliberately bypasses it (range break / loose continuation) - recorded honestly
  confirmation       for break families: the branch that fired (normal follow-through, range_break, loose
                     continuation) with the tracker's evidence; bounce/reject: the touch (T4.2: no reclaim needed)
  exhausted          R3.2 false-break cap not reached
Not encoded (recorded `not_evaluated`, diagnostic only): higher-timeframe fakeout, emerging opposing shelf,
momentum divergence, live chop. Retiring the momentum-family model veto is an explicit policy change.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

DECISION_VERSION = "deterministic-entry-v1"
DECISION_MODE = "deterministic"
FAMILIES = ("bounce", "reject", "breakout", "breakdown", "wedge_break")
ENTRY_REQUIRED = "entry_required"
DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class EntryPolicy:
    """Effective policy the caller resolved (settings are read by the caller, never here)."""
    mode: str = DECISION_MODE                 # deterministic | legacy (legacy never reaches evaluate_entry)
    rule_version: str = DECISION_VERSION
    thresholds: dict = field(default_factory=dict)      # the effective threshold snapshot (hashed into the decision)
    enforce_windows: bool = True


@dataclass(frozen=True)
class EntrySnapshot:
    """Everything the decision may look at. Frozen by the caller at the fire attempt."""
    attempt_id: str
    run_id: str
    plan_id: str
    plan_version: str                         # plan identity incl. replacements (parentRunId chain / builtFrom)
    session: str                              # planFor
    plan_status: str                          # armed | paused | ...
    trigger_id: str
    family: str                               # tracker kind
    direction: str                            # long | short
    entry: float | None                       # the SAVED planned entry (geometry is validated against this)
    stop: float | None
    targets: tuple[float, ...]
    observed_entry: float | None = None       # the tracker's fill proxy (break close / touch level) - separate from the saved entry
    candidate_window: str | None = None       # break families: the window the tracker accepted the candidate in
    tracker_status: str = "waiting"           # the tracker's own status at the attempt
    fired_ts: int | None = None               # the completed bar the tracker fired on
    fired_window: str | None = None
    signal_bar: dict | None = None            # the firing bar {ts, open, high, low, close, volume}
    fired_event: dict | None = None           # the tracker's `fired` note (rel, rangeBreak, loose, confirmedAfter)
    tracker_events: tuple[dict, ...] = ()     # the tracker's notes (bounded)
    gap_unchecked: bool = False
    gap_day: bool = False
    failed_breaks: int = 0
    continuation: bool = False                # the trigger was re-aimed by the gap-continuation rule
    received_ts: int | None = None            # when the app received the bar (ms)
    decided_ts: int | None = None             # when the caller froze the snapshot (ms) - NOT read here
    level_provenance: dict | None = None      # saved level facts (touches, sources, builtFromSession)
    optional_context: dict | None = None      # anything not encoded (recorded, never judged)


@dataclass
class EntryCheck:
    name: str
    outcome: str                              # pass | fail | unknown | not_applicable
    authority: str                            # entry_required | diagnostic
    facts: dict = field(default_factory=dict)
    reason_code: str | None = None


@dataclass
class EntryDecision:
    decision_id: str
    attempt_id: str
    verdict: str                              # allow | refuse | defer
    reason_codes: list[str]
    checks: list[EntryCheck]
    confirmation_variant: str                 # touch | normal_followthrough | range_break | loose_continuation | none
    input_hash: str
    decision_mode: str = DECISION_MODE
    decision_version: str = DECISION_VERSION
    rule_version: str = DECISION_VERSION
    thresholds_hash: str = ""
    plan_id: str = ""
    plan_version: str = ""
    trigger_id: str = ""
    trigger_family: str = ""
    signal_bar_start: int | None = None
    signal_bar_close: int | None = None
    source_time: int | None = None
    received_time: int | None = None
    not_encoded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"decisionId": self.decision_id, "fireAttemptId": self.attempt_id, "decisionMode": self.decision_mode,
                "decisionVersion": self.decision_version, "ruleVersion": self.rule_version, "thresholdsHash": self.thresholds_hash,
                "planId": self.plan_id, "planVersion": self.plan_version, "triggerId": self.trigger_id, "triggerFamily": self.trigger_family,
                "confirmationVariant": self.confirmation_variant, "signalBarStart": self.signal_bar_start, "signalBarClose": self.signal_bar_close,
                "sourceTime": self.source_time, "receivedTime": self.received_time, "verdict": self.verdict,
                "reasonCodes": list(self.reason_codes), "inputHash": self.input_hash, "notEncoded": list(self.not_encoded),
                "checks": [{"name": c.name, "outcome": c.outcome, "authority": c.authority, "facts": c.facts, "reasonCode": c.reason_code}
                           for c in self.checks]}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def snapshot_hash(snapshot: EntrySnapshot, policy: EntryPolicy) -> str:
    """Immutable evidence identity: the snapshot's judged inputs plus the effective rule/threshold set."""
    d = {k: v for k, v in snapshot.__dict__.items() if k not in ("decided_ts", "optional_context")}
    d["_policy"] = {"mode": policy.mode, "rule_version": policy.rule_version, "thresholds": policy.thresholds,
                    "enforce_windows": policy.enforce_windows}
    return hashlib.sha256(_canonical(d).encode("utf-8")).hexdigest()


def thresholds_hash(thresholds: dict) -> str:
    return hashlib.sha256(_canonical(thresholds or {}).encode("utf-8")).hexdigest()[:16]


def _num(x) -> float | None:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def evaluate_entry(snapshot: EntrySnapshot, policy: EntryPolicy) -> EntryDecision:
    """Pure: no I/O, model access, settings reads, clock reads or state mutation."""
    checks: list[EntryCheck] = []
    reasons: list[str] = []
    long = snapshot.direction != "short"
    t = policy.thresholds or {}
    variant = "none"

    def req(name: str, ok: bool | None, code: str, **facts) -> None:
        if ok is None:
            checks.append(EntryCheck(name, "unknown", ENTRY_REQUIRED, facts, code))
            reasons.append(code)
        elif ok:
            checks.append(EntryCheck(name, "pass", ENTRY_REQUIRED, facts))
        else:
            checks.append(EntryCheck(name, "fail", ENTRY_REQUIRED, facts, code))
            reasons.append(code)

    # ---- identity and plan currency
    plan_ok = snapshot.plan_status == "armed" and bool(snapshot.run_id) and bool(snapshot.trigger_id)
    req("plan_current", plan_ok, "plan_not_current", planStatus=snapshot.plan_status, session=snapshot.session)
    fam_ok = snapshot.family in FAMILIES
    req("trigger_family", fam_ok, "unsupported_confirmation_variant", family=snapshot.family)
    # ---- geometry
    e, s = _num(snapshot.entry), _num(snapshot.stop)
    tg = [x for x in (_num(v) for v in snapshot.targets) if x is not None]
    if e is None or s is None or not tg:
        req("geometry", None, "geometry_unknown_required", entry=snapshot.entry, stop=snapshot.stop, targets=list(snapshot.targets))
    else:
        # DE-01: the SAVED plan geometry (saved entry / stop / targets) - the observed trigger price is recorded
        # beside it and judged by the existing downstream checks (never-chase, quantity-dependent R2, quotes)
        side_ok = (s < e and all(x > e for x in tg)) if long else (s > e and all(x < e for x in tg))
        req("geometry", side_ok, "geometry_invalid", entry=e, stop=s, targets=tg, direction=snapshot.direction,
            observedEntry=snapshot.observed_entry)
    # ---- the tracker's own transition (never a kind label)
    fired = snapshot.tracker_status == "fired" and snapshot.fired_ts is not None and snapshot.fired_event is not None
    req("tracker_fired", fired, "trigger_not_fired", trackerStatus=snapshot.tracker_status, firedTs=snapshot.fired_ts,
        firedEvent=(snapshot.fired_event or {}).get("event"))
    # ---- stop intact on the firing bar (T4.3d)
    bar = snapshot.signal_bar or {}
    close = _num(bar.get("close"))
    if close is None or s is None:
        req("stop_intact", None, "signal_bar_unknown_required", close=bar.get("close"), stop=snapshot.stop)
    else:
        intact = (close >= s) if long else (close <= s)
        req("stop_intact", intact, "stop_invalidated", close=close, stop=s)
    # ---- window (the tracker already refused out-of-window touches; record the fired window)
    # DE-01: the shared tracker already gated eligibility where the rule says (the touch bar for bounces /
    # rejections, the CANDIDATE bar for break families - the confirmation bar may complete later). The decision
    # records that evidence and adds NO second window gate; an unfired tracker is refused above.
    if snapshot.fired_window is None and fired:
        req("window", None, "window_unknown_required")
    else:
        req("window", bool(fired), "window_ineligible", firedWindow=snapshot.fired_window, candidateWindow=snapshot.candidate_window,
            enforced=policy.enforce_windows, gatedBy=("tracker_candidate" if snapshot.family in ("breakout", "breakdown", "wedge_break") else "tracker_touch"))
    # ---- gap rules: judged on the open or explicitly unchecked (kept as today, recorded)
    checks.append(EntryCheck("gap", "not_applicable" if snapshot.gap_unchecked else "pass", DIAGNOSTIC,
                             {"gapUnchecked": snapshot.gap_unchecked, "gapDay": snapshot.gap_day, "continuation": snapshot.continuation}))
    # ---- family confirmation + volume, from the ACTUAL fired branch
    fe = snapshot.fired_event or {}
    rel = _num(fe.get("rel"))
    if snapshot.family in ("bounce", "reject"):
        variant = "touch"
        floor = _num(t.get("volume_floor_mult"))
        if floor is not None and floor > 0:
            if rel is None:
                req("volume", None, "volume_unknown", branch="touch", floor=floor)
            else:
                req("volume", rel >= floor, "volume_below_floor", rel=rel, floor=floor)
        else:
            checks.append(EntryCheck("volume", "not_applicable", ENTRY_REQUIRED, {"floor": floor}))
        checks.append(EntryCheck("confirmation", "pass" if fired else "fail", ENTRY_REQUIRED,
                                 {"branch": "touch", "note": "T4.2: enter AT the level, no reclaim/reversal candle required (v1 policy)"},
                                 None if fired else "break_not_confirmed"))
    elif snapshot.family in ("breakout", "breakdown", "wedge_break"):
        if fe.get("rangeBreak"):
            variant = "range_break"
            floor = _num(t.get("volume_floor_mult"))
            if floor is not None and floor > 0:
                req("volume", None if rel is None else rel >= floor, "volume_unknown" if rel is None else "volume_below_floor",
                    branch=variant, rel=rel, floor=floor)
            else:
                checks.append(EntryCheck("volume", "not_applicable", ENTRY_REQUIRED, {"branch": variant}))
            checks.append(EntryCheck("confirmation", "pass" if fired else "fail", ENTRY_REQUIRED,
                                     {"branch": variant, "bypassed": ["volume_surge", "decisive_candle", "follow_through"],
                                      "note": "C5 range break fires on the break close (configured shortcut)"}, None if fired else "break_not_confirmed"))
        elif fe.get("loose"):
            variant = "loose_continuation"
            floor = _num(t.get("volume_floor_mult"))
            if floor is not None and floor > 0:
                req("volume", None if rel is None else rel >= floor, "volume_unknown" if rel is None else "volume_below_floor",
                    branch=variant, rel=rel, floor=floor)
            else:
                checks.append(EntryCheck("volume", "not_applicable", ENTRY_REQUIRED, {"branch": variant}))
            checks.append(EntryCheck("confirmation", "pass" if fired else "fail", ENTRY_REQUIRED,
                                     {"branch": variant, "bypassed": ["volume_surge", "decisive_candle", "follow_through"],
                                      "note": "T-13b loose gap continuation fires on the first close through (configured shortcut)"},
                                     None if fired else "break_not_confirmed"))
        else:
            variant = "normal_followthrough"
            confirmed_after = fe.get("confirmedAfter")
            cand = next((ev for ev in reversed(snapshot.tracker_events) if ev.get("event") == "break_candidate"), None)
            cand_rel = _num((cand or {}).get("rel"))
            surge = _num(t.get("volume_spike_mult"))
            if surge is not None and surge > 0:
                if cand_rel is None:
                    req("volume", None, "volume_unknown", branch=variant, surge=surge)
                else:
                    req("volume", cand_rel >= surge, "volume_below_floor", branch=variant, rel=cand_rel, surge=surge)
            else:
                checks.append(EntryCheck("volume", "not_applicable", ENTRY_REQUIRED, {"branch": variant}))
            ok = fired and confirmed_after is not None and cand is not None
            req("confirmation", None if (fired and confirmed_after is None and cand is None) else ok, "break_not_confirmed",
                branch=variant, confirmedAfter=confirmed_after, candidateBar=(cand or {}).get("ts"),
                decisive=(cand is not None), followThroughBars=confirmed_after)
    else:
        checks.append(EntryCheck("confirmation", "fail", ENTRY_REQUIRED, {"family": snapshot.family}, "unsupported_confirmation_variant"))
    # ---- R3.2 false-break exhaustion
    max_fb = _num(t.get("max_false_breaks"))
    if max_fb is not None and max_fb > 0:
        req("exhausted", snapshot.failed_breaks < max_fb, "level_exhausted", failedBreaks=snapshot.failed_breaks, max=max_fb)
    else:
        checks.append(EntryCheck("exhausted", "not_applicable", ENTRY_REQUIRED, {"failedBreaks": snapshot.failed_breaks}))
    # ---- not encoded (diagnostic only, never a gate)
    not_encoded = ["higher_timeframe_fakeout", "opposing_shelf", "momentum_divergence", "live_chop"]
    for n in not_encoded:
        checks.append(EntryCheck(n, "unknown", DIAGNOSTIC, {"note": "not encoded in deterministic-entry-v1; a future rule needs its own version"}))
    if snapshot.level_provenance is not None:
        checks.append(EntryCheck("level_provenance", "pass", DIAGNOSTIC, dict(snapshot.level_provenance)))
    # ---- verdict
    required = [c for c in checks if c.authority == ENTRY_REQUIRED]
    if any(c.outcome == "fail" for c in required):
        verdict = "refuse"
    elif any(c.outcome == "unknown" for c in required):
        verdict = "defer"
        reasons = [r for r in reasons] + (["unknown_required"] if "unknown_required" not in reasons else [])
    else:
        verdict = "allow"
    ih = snapshot_hash(snapshot, policy)
    decision_id = hashlib.sha256((snapshot.attempt_id + ":" + ih).encode("utf-8")).hexdigest()[:32]
    return EntryDecision(decision_id=decision_id, attempt_id=snapshot.attempt_id, verdict=verdict,
                         reason_codes=list(dict.fromkeys(reasons)), checks=checks, confirmation_variant=variant, input_hash=ih,
                         rule_version=policy.rule_version, thresholds_hash=thresholds_hash(policy.thresholds),
                         plan_id=snapshot.plan_id, plan_version=snapshot.plan_version, trigger_id=snapshot.trigger_id,
                         trigger_family=snapshot.family, signal_bar_start=snapshot.fired_ts,
                         signal_bar_close=(snapshot.fired_ts + 60_000 if snapshot.fired_ts is not None else None),
                         source_time=snapshot.fired_ts, received_time=snapshot.received_ts, not_encoded=not_encoded)


def snapshot_from_tracker(*, attempt_id: str, run_id: str, plan: dict, plan_status: str, trigger_id: str, tracker,
                          signal_bar: dict | None, received_ts: int | None, decided_ts: int | None) -> EntrySnapshot:
    """Freeze the ACTUAL tracker transition into a snapshot (called by the runner hook; no I/O). `tracker` is a
    `TriggerTracker`; its `events` notes carry the branch that fired (rel / rangeBreak / loose / confirmedAfter)."""
    trig = tracker.trigger or {}
    fired_event = next((ev for ev in reversed(tracker.events) if ev.get("event") == "fired"), None)
    lv = trig.get("level") if isinstance(trig.get("level"), dict) else {}
    return EntrySnapshot(
        attempt_id=attempt_id, run_id=run_id, plan_id=run_id,
        plan_version=str((plan or {}).get("builtFromMs") or (plan or {}).get("builtFromSession") or "") + ":" + str((plan or {}).get("parentRunId") or ""),
        session=str((plan or {}).get("planFor") or ""), plan_status=plan_status, trigger_id=trigger_id, family=tracker.kind,
        direction=tracker.direction, entry=_num(tracker.entry), stop=_num(tracker.stop), observed_entry=_num(tracker.fill_price),
        candidate_window=next((ev.get("window") for ev in reversed(tracker.events) if ev.get("event") == "break_candidate"), None),
        targets=tuple(x for x in (_num(t.get("price")) for t in (trig.get("targets") or [])) if x is not None),
        tracker_status=tracker.status, fired_ts=tracker.fired_ts, fired_window=tracker.fired_window, signal_bar=signal_bar,
        fired_event=fired_event, tracker_events=tuple(tracker.events[-12:]), gap_unchecked=bool(tracker.gap_unchecked),
        gap_day=bool(getattr(tracker, "gap_day", False)), failed_breaks=int(tracker.failed_breaks or 0),
        continuation=bool(trig.get("continuation")), received_ts=received_ts, decided_ts=decided_ts,
        level_provenance={"touches": lv.get("touches"), "sources": lv.get("sources"), "builtFromSession": (plan or {}).get("builtFromSession"),
                          "basis": [t.get("basis") for t in (trig.get("targets") or [])]})


FIRE_MODE_ALIASES = {"legacy_blocking": "legacy", "critic": "legacy", "llm": "legacy"}


def normalize_fire_mode(raw) -> str:
    """The ONE normaliser for `fire_decision_mode` (runner, preview, UI): strip/lower, legacy aliases -> legacy;
    anything else is `invalid:<raw>` (the runner refuses on it, never a silent fallback)."""
    mode = str(raw if raw is not None else "deterministic").strip().lower() or "deterministic"
    mode = FIRE_MODE_ALIASES.get(mode, mode)
    return mode if mode in ("deterministic", "legacy") else f"invalid:{raw}"


def policy_from_thresholds(thresholds, *, enforce_windows: bool = True, mode: str = DECISION_MODE) -> EntryPolicy:
    """The effective EM thresholds as a plain dict (only the keys the v1 rules read, so the hash is stable)."""
    keys = ("volume_floor_mult", "volume_spike_mult", "followthrough_bars", "followthrough_required", "max_false_breaks",
            "level_tolerance_pct", "gap_void_r", "gap_day_pct", "gap_day_wait_minutes", "range_break", "gap_continuation_confirm",
            "gap_through_continuation", "gap_day_continuation", "windows",
            # DE-01 / DR-03: the confirmation inputs that create the evidence (decisive candle, range break)
            "decisive_body_ratio", "decisive_size_mult", "max_breakout_wick_ratio", "range_break_bars", "range_break_max_range_mult")
    snap = {}
    for k in keys:
        v = getattr(thresholds, k, None) if not isinstance(thresholds, dict) else thresholds.get(k)
        if v is not None:
            snap[k] = list(v) if isinstance(v, (tuple, list, set)) else v
    return EntryPolicy(mode=mode, rule_version=DECISION_VERSION, thresholds=snap, enforce_windows=enforce_windows)
