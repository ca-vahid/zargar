"""EM requalification after an early invalidation (`requalification-v1`, 2026-09-18; integrated plan workstream C).

ORDER-FREE research candidate. NVDA 2026-09-18 is the motivating case: both long triggers were invalidated at 09:31 and
price recovered hours later. The answer is NOT to reset the invalidated trigger or to stretch an expiry: it is to ask
whether FRESH structure formed after the invalidation, and to judge that new structure like any other setup.

Frozen definition (v1):
  1. parent    = one source scenario branch whose baseline trigger reached a terminal non-fired state at `invalidatedTs`
                 (invalidated / gap_void / gapped_past / gapped_through / exhausted). The parent tracker is never touched.
  2. structure = the existing causal pivot detector (`marketstructure.levels.find_pivots`, window w) on 1m bars STRICTLY
                 AFTER the invalidation. Long: a pivot LOW, then a later pivot HIGH (short: mirrored). A pivot at bar i is
                 usable only from bar i + w - its confirmation bar. A rebound above the old entry alone is not structure.
  3. candidate = break family on the fresh pivot: entry = the pivot high (long) / low (short); stop = the fresh pivot on
                 the other side minus the production stop buffer; wider than `max_stop_pct` = refused (as production).
                 Confirmation = the production tracker's completed-close break rules (no same-close fill). App-added, and
                 labelled so: none of this is the author's rule.
  4. targets   = the source's underlying targets that lie beyond the entry (author-supplied); none = held (missing
                 evidence). R2 is measured with the production gate target; below the minimum = refused.
  5. window    = the production session windows and the SOURCE expiry. A morning idea is not extended to the close.
  6. limit     = ONE requalified candidate per scenario branch per session (complexity limit, not a frequency claim).
  7. future    = nothing after the candidate's confirmation time may change its eligibility, stop or targets.
"""
from __future__ import annotations

import hashlib
import json

from ..domain import Bar
from ..marketstructure.levels import find_pivots
from .rulebook import DEFAULT_THRESHOLDS, Thresholds
from .setups import risk_reward, stop_buffer

VERSION = "requalification-v1"
TERMINAL_UNFIRED = ("invalidated", "gap_void", "gapped_past", "gapped_through", "exhausted")


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def child_id(parent_scenario_id: str, session: str) -> str:
    """Unique and STABLE: one child per scenario branch per session - a second call can only return the same id."""
    return "rq1-" + _h([VERSION, parent_scenario_id, session])[:20]


def fresh_structure(bars: list, *, direction: str, invalidated_ts: int, window: int) -> dict | None:
    """The first fresh (pivot, pivot) pair formed strictly after the invalidation, with its causal confirmation index.
    `bars` = the session's closed 1m bars seen SO FAR (causal: the caller never passes future bars)."""
    after = [i for i, b in enumerate(bars) if int(b.ts) > int(invalidated_ts)]
    if not after:
        return None
    start = after[0]
    piv = [p for p in find_pivots(bars, window) if p.index >= start and p.index + window < len(bars)]   # confirmed only: i + w must exist
    lo_kind, hi_kind = ("low", "high") if direction != "short" else ("high", "low")
    for a in piv:
        if a.kind != lo_kind:
            continue
        for b in piv:
            if b.kind == hi_kind and b.index > a.index:
                ok = b.price > a.price if direction != "short" else b.price < a.price
                if ok:
                    return {"protect": {"index": a.index, "ts": a.ts, "price": a.price, "kind": a.kind, "confirmedIndex": a.index + window},
                            "break": {"index": b.index, "ts": b.ts, "price": b.price, "kind": b.kind, "confirmedIndex": b.index + window},
                            "formedTs": b.ts, "confirmedIndex": b.index + window, "confirmedTs": int(bars[b.index + window].ts)}
    return None


def build_child(*, parent: dict, bars: list, thresholds: Thresholds | None = None, atr_value: float = 0.0, existing_children=None) -> dict:
    """`parent` = {scenarioId, symbol, direction, session, invalidatedTs, invalidatedStatus, sourceTargets, expiresTs,
    oldEntry}. Returns the child record: disposition requalification_eligible | waiting | held_for_missing_evidence |
    refused | expired - always order-free (`origin = scenario:<id>`)."""
    t = thresholds or DEFAULT_THRESHOLDS
    cid = child_id(parent["scenarioId"], parent["session"])
    base = {"version": VERSION, "childId": cid, "parentScenarioId": parent["scenarioId"], "origin": f"scenario:{parent['scenarioId']}", "orderFree": True,
            "symbol": parent.get("symbol"), "direction": parent.get("direction"), "session": parent.get("session"),
            "parentState": {"status": parent.get("invalidatedStatus"), "invalidatedTs": parent.get("invalidatedTs"), "untouched": True}}
    if cid in set(existing_children or []):
        return {**base, "disposition": "refused", "reason": "one_requalified_candidate_per_branch_per_session"}
    if parent.get("invalidatedStatus") not in TERMINAL_UNFIRED:
        return {**base, "disposition": "refused", "reason": "parent_not_invalidated"}
    direction = "short" if parent.get("direction") == "short" else "long"
    w = int(getattr(t, "pivot_window", 3) or 3)
    st = fresh_structure(bars, direction=direction, invalidated_ts=int(parent["invalidatedTs"]), window=w)
    if st is None:
        last_ts = int(bars[-1].ts) if bars else 0
        expired = parent.get("expiresTs") and last_ts >= int(parent["expiresTs"])
        return {**base, "disposition": ("expired" if expired else "waiting"),
                "reason": "no fresh confirmed pivot structure after the invalidation (a rebound through the old entry is not structure)"}
    if parent.get("expiresTs") and int(st["confirmedTs"]) >= int(parent["expiresTs"]):
        return {**base, "disposition": "expired", "reason": "fresh structure confirmed only after the source expiry - the source horizon is not extended",
                "structure": st}
    entry = float(st["break"]["price"])
    anchor = float(st["protect"]["price"])
    buf = stop_buffer(anchor, atr_value=atr_value, thresholds=t)
    stop = round(anchor - buf if direction == "long" else anchor + buf, 4)
    risk_pct = abs(entry - stop) / entry if entry else 1.0
    targets = sorted([float(x) for x in (parent.get("sourceTargets") or []) if (float(x) > entry if direction == "long" else float(x) < entry)], reverse=(direction == "short"))
    rec = {**base, "structure": st,
           "differsFromParent": {"oldEntry": parent.get("oldEntry"), "newEntry": entry, "why": "entry and stop come from pivots formed AFTER the invalidation; the parent level is not reused"},
           "geometry": {"entry": entry, "stop": stop, "stopProvenance": f"fresh pivot {st['protect']['kind']} {anchor:g} - production stop buffer {buf:.4f} (app-derived)",
                        "targets": targets, "targetProvenance": ("author-supplied underlying targets beyond the new entry" if targets else None)},
           "confirmation": {"family": ("breakout" if direction == "long" else "breakdown"), "rule": "production tracker completed-close break rules (app-added; not the author's rule)",
                            "sameCloseFill": False},
           "eligibleFromTs": st["confirmedTs"], "expiresTs": parent.get("expiresTs")}
    if risk_pct > float(t.max_stop_pct):
        return {**rec, "disposition": "refused", "reason": f"stop {risk_pct:.2%} of entry is wider than the {float(t.max_stop_pct):.1%} cap (production rule)"}
    if not targets:
        return {**rec, "disposition": "held_for_missing_evidence", "reason": "no author target lies beyond the fresh entry - target provenance unknown, none invented"}
    gate = targets[min(max(int(t.rr_gate_target), 0), len(targets) - 1)]
    rr = round(risk_reward(entry, stop, gate), 3)
    rec["gate"] = {"riskReward": rr, "min": float(t.min_risk_reward), "gateTarget": gate}
    if rr + 1e-9 < float(t.min_risk_reward):
        return {**rec, "disposition": "refused", "reason": f"R2 {rr} to {gate:g} is below {float(t.min_risk_reward):g} (named outcome; the threshold is not lowered)"}
    return {**rec, "disposition": "requalification_eligible", "reason": None,
            "trigger": {"id": cid, "kind": rec["confirmation"]["family"], "direction": direction, "levelPrice": entry, "valid": True, "riskReward": rr,
                        "entry": {"price": entry, "basis": "on_break"}, "stop": {"price": stop, "reference": "fresh pivot"},
                        "targets": [{"price": x, "basis": "author"} for x in targets], "setupType": "requalification", "origin": f"scenario:{parent['scenarioId']}"}}


def bars_upto(bars: list, ts: int) -> list:
    """Causal slice: only bars that had CLOSED by `ts` (1m bars: start + 60 s)."""
    return [b for b in bars if int(b.ts) + 60_000 <= int(ts)]
