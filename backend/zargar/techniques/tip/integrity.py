"""KB-06 — the execution-integrity pause (built 2026-09-14 on the reviewer's
GO; implementation review before activation).

Design: docs/techniques/tip/reviews/2026-09-13-kb06-execution-integrity-pause.md.
An INCIDENT is a persisted, journaled record that the automated entry path
produced or acted on something the desk cannot trust: a filled trade that
violated geometry/budget, duplicate or unreconciled executions, an exit that
relied on missing or invalid evidence, a repeated pre-entry failure on one
entry path, or an identified shared-component failure. It is opened by
EVIDENCE (structured exit kinds, execution timestamps, journal references),
scoped to what the evidence implicates, honoured by EVERY automated entry
path at final admission, and released only by a cause-specific validation
of the evidence at the incident's current revision — never by a clock, a
restart or a date rollover. A valid, budget-compliant fast loss is a
DIAGNOSTIC, not an incident; ordinary loss limits and every protective exit
are untouched.

Activation knob `techniques.tip.entry_pause_mode`:
    clock      — the pre-existing clock gate (`adoption_killswitch`) alone  (DEFAULT)
    integrity  — open incidents pause automated entries; the clock gate is off
    both       — either pauses
Incidents are DETECTED and RECORDED in every mode (shadow evidence for the
activation decision); they only PAUSE in `integrity` / `both`.
Initial scope: technique `tip` on the Tips Practice book — never another
technique or a live book by default.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import logging

log = logging.getLogger("zargar.tip.integrity")

MODES = ("clock", "integrity", "both")
FAST_STOP_S = 300                    # the "fast loss" boundary (execution timestamps, never row ages)
STOP_KINDS = ("stop", "premium_stop", "quote_stop", "venue_stop", "bleed")
REPEATED_PRE_ENTRY_FAILURES = 3      # same session, same entry path -> incident on that path

# cause -> what must be true to release (validated by `_validate_release`)
CAUSES: dict[str, str] = {
    "geometry_violation_filled": "the position is closed, or its stop/size satisfy the risk budget again (trim confirmed or tight stop in force)",
    "duplicate_execution": "the duplicate is reconciled: one position per fill, executions matched to orders",
    "unreconciled_fill": "the manager's reconciliation drift on the symbol is cleared",
    "evidence_missing": "the missing evidence exists AND proves the trade/exit valid — stale data, invalid geometry or an execution defect turn this into an integrity incident instead",
    "invalid_evidence": "the entry/exit path that used invalid evidence is repaired and a fresh observation confirms it",
    "repeated_pre_entry_failure": "the entry path passed a pre-entry validation again after the session boundary",
    "shared_component": "the identified shared component is confirmed healthy by its owner (explicit note)",
}


def pause_mode(settings) -> str:
    m = str(settings.get("techniques.tip.entry_pause_mode", "clock") or "clock").lower()
    return m if m in MODES else "clock"


def pauses(settings) -> bool:
    return pause_mode(settings) in ("integrity", "both")


def default_scope(eng) -> dict:
    """Tips Practice only (reviewer: begin with Tips Practice, matching
    geometry's scope) — the technique's default book, never a live one."""
    pid = str(eng.settings.get("techniques.tip.default_portfolio", "") or "")
    return {"technique": "tip", "portfolioId": pid or None}


def _scope_matches(scope: dict, *, technique: str, portfolio_id: str | None, entry_path: str | None,
                   symbol: str | None) -> bool:
    if (scope.get("technique") or "tip") != technique:
        return False
    if scope.get("portfolioId") and portfolio_id and scope["portfolioId"] != portfolio_id:
        return False
    if scope.get("entryPath") and entry_path and scope["entryPath"] != entry_path:
        return False
    if scope.get("symbol") and symbol and str(scope["symbol"]).upper() != str(symbol).upper():
        return False
    return True


def _incident_dict(row) -> dict:
    return {"id": row.id, "openedAt": row.opened_at.isoformat() if row.opened_at else None,
            "resolvedAt": row.resolved_at.isoformat() if row.resolved_at else None,
            "status": row.status, "kind": row.kind, "cause": row.cause, "scope": dict(row.scope or {}),
            "evidence": list(row.evidence or []), "releaseCriteria": row.release_criteria,
            "revision": int(row.revision or 1), "resolver": row.resolver,
            "resolution": dict(row.resolution or {}), "why": row.why}


# ---------------------------------------------------------------------------
async def open_incident(eng, *, kind: str, cause: str, scope: dict, evidence: list[dict],
                        why: str) -> dict:
    """Open (or extend) an incident. Idempotent on (cause, scope, primary
    evidence id): a second observation of the same defect appends evidence
    and bumps the revision instead of opening a duplicate. Journaled
    `TipExecutionIncident`. Cancels resting AUTOMATED entries in scope when
    the pause is active (`_cancel_resting_entries`)."""
    from sqlalchemy import select
    from ... import events as ev
    from ...domain import new_id
    from ...models import TipExecutionIncident
    if cause not in CAUSES:
        raise ValueError(f"unknown incident cause {cause!r}")
    if kind not in ("integrity", "hold"):
        raise ValueError("kind must be integrity | hold")
    now = dt.datetime.now(dt.timezone.utc)
    primary = str((evidence[0] if evidence else {}).get("id") or "")
    async with eng.sf() as session:
        open_rows = (await session.execute(select(TipExecutionIncident).where(
            TipExecutionIncident.status == "open", TipExecutionIncident.cause == cause))).scalars().all()
        for r in open_rows:
            same_scope = (r.scope or {}) == (scope or {})
            same_primary = primary and any(str(e.get("id") or "") == primary for e in (r.evidence or []))
            if same_scope and same_primary:
                r.evidence = list(r.evidence or []) + [{**e, "at": now.isoformat()} for e in evidence[1:]] \
                    if len(evidence) > 1 else list(r.evidence or [])
                r.revision = int(r.revision or 1) + 1
                await session.commit()
                out = _incident_dict(r)
                await eng.journal.append(ev.TIP_EXECUTION_INCIDENT, {**out, "action": "extended"},
                                         aggregate_type="incident", aggregate_id=r.id,
                                         portfolio_id=(scope or {}).get("portfolioId"))
                return out
        row = TipExecutionIncident(
            id=new_id(), opened_at=now, status="open", kind=kind, cause=cause, scope=dict(scope or {}),
            evidence=[{**e, "at": e.get("at") or now.isoformat()} for e in evidence],
            release_criteria=CAUSES[cause], revision=1, why=why[:400])
        session.add(row)
        await session.commit()
        out = _incident_dict(row)
    await eng.journal.append(ev.TIP_EXECUTION_INCIDENT, {**out, "action": "opened"},
                             aggregate_type="incident", aggregate_id=out["id"],
                             portfolio_id=(scope or {}).get("portfolioId"))
    log.warning("execution incident %s opened: %s — %s", out["id"][:8], cause, why)
    if pauses(eng.settings):
        with contextlib.suppress(Exception):
            await _cancel_resting_entries(eng, out)
    return out


async def append_evidence(eng, incident_id: str, evidence: dict) -> dict | None:
    from ... import events as ev
    from ...models import TipExecutionIncident
    now = dt.datetime.now(dt.timezone.utc)
    async with eng.sf() as session:
        row = await session.get(TipExecutionIncident, incident_id, with_for_update=True)
        if row is None:
            return None
        row.evidence = list(row.evidence or []) + [{**evidence, "at": now.isoformat()}]
        row.revision = int(row.revision or 1) + 1          # a stale resolution can no longer clear this
        await session.commit()
        out = _incident_dict(row)
    await eng.journal.append(ev.TIP_EXECUTION_INCIDENT, {**out, "action": "evidence"},
                             aggregate_type="incident", aggregate_id=incident_id)
    return out


async def list_incidents(eng, *, status: str | None = "open", limit: int = 100) -> list[dict]:
    from sqlalchemy import select
    from ...models import TipExecutionIncident
    async with eng.sf() as session:
        q = select(TipExecutionIncident).order_by(TipExecutionIncident.opened_at.desc()).limit(limit)
        if status:
            q = q.where(TipExecutionIncident.status == status)
        rows = (await session.execute(q)).scalars().all()
    return [_incident_dict(r) for r in rows]


async def entry_paused(eng, *, portfolio_id: str | None, technique: str = "tip",
                       entry_path: str | None = None, symbol: str | None = None) -> str | None:
    """The reason no NEW automated entry may be placed right now on this
    technique/book/path — the first OPEN incident whose scope matches — or
    None. Answers from the store (persisted: a restart cannot clear it).
    Exits never consult this."""
    try:
        for inc in await list_incidents(eng, status="open"):
            if _scope_matches(inc["scope"], technique=technique, portfolio_id=portfolio_id,
                              entry_path=entry_path, symbol=symbol):
                return (f"execution-integrity {inc['kind']} incident {inc['id'][:8]} "
                        f"({inc['cause']}): {inc['why']} — release: {inc['releaseCriteria']}")
    except Exception:
        log.debug("entry_paused lookup failed", exc_info=True)
    return None


async def admission(eng, *, portfolio_id: str | None, entry_path: str) -> str | None:
    """Final-admission check for the automated entry paths OTHER than the
    tip auto-approval loop (approve(), the stale-quote retry, the armed fire):
    incidents only, and only when the pause mode is active — the clock gate
    stays exactly where it lives today."""
    if not pauses(eng.settings):
        return None
    return await entry_paused(eng, portfolio_id=portfolio_id, entry_path=entry_path)


async def gate_reason(eng, *, portfolio_id: str | None, entry_path: str) -> str | None:
    """What the automated entry paths call: honours the pause MODE — the
    clock gate alone (default), incidents alone, or both."""
    mode = pause_mode(eng.settings)
    if mode in ("integrity", "both"):
        why = await entry_paused(eng, portfolio_id=portfolio_id, entry_path=entry_path)
        if why:
            return why
    if mode in ("clock", "both"):
        from .lifecycle import adoption_killswitch
        return await adoption_killswitch(eng)
    return None


# ---------------------------------------------------------------------------
async def _validate_release(eng, inc: dict, note: str) -> tuple[bool, str]:
    """Cause-specific check of the release criteria against CURRENT state.
    Receiving evidence is not enough: for a proven defect the state itself
    must be repaired."""
    cause = inc["cause"]
    mgr = getattr(eng, "position_manager", None)
    pos_ids = [str(e.get("id")) for e in inc.get("evidence") or [] if e.get("kind") == "position"]
    if cause == "geometry_violation_filled":
        for pid in pos_ids:
            p = mgr.get(pid) if mgr is not None else None
            if p is None:
                continue                                    # closed / gone: repaired by exit
            exc = (p.extras or {}).get("geometryException") or {}
            if exc.get("phase") in ("trim_pending", "reconcile"):
                return False, f"position {pid[:8]} still holds an unresolved geometry exception ({exc.get('phase')})"
        return True, "positions closed or their exceptions resolved"
    if cause == "unreconciled_fill":
        if mgr is not None:
            halted = set(getattr(mgr, "_entry_halted", set()))
            syms = {str(e.get("symbol") or "").upper() for e in inc.get("evidence") or [] if e.get("symbol")}
            still = sorted(syms & halted)
            if still:
                return False, f"reconciliation drift still halts {', '.join(still)}"
        return True, "no reconciliation drift on the incident's symbols"
    if cause == "duplicate_execution":
        if not note or "reconciled" not in note.lower():
            return False, "state the reconciliation (one position per fill) in the resolution note"
        return True, "reconciliation stated"
    if cause == "evidence_missing":
        proofs = [e for e in inc.get("evidence") or [] if e.get("kind") == "proof"]
        if not proofs:
            return False, "no proof evidence appended — receiving nothing is not validation"
        bad = [e for e in proofs if not e.get("valid")]
        if bad:
            return False, "the appended evidence proves a defect, not validity — open an integrity incident instead"
        return True, f"{len(proofs)} proof record(s) validate the trade"
    if cause == "invalid_evidence":
        proofs = [e for e in inc.get("evidence") or [] if e.get("kind") == "proof" and e.get("valid")]
        return (True, "fresh observation recorded") if proofs else (False, "no fresh valid observation appended")
    if cause == "repeated_pre_entry_failure":
        opened = dt.datetime.fromisoformat(inc["openedAt"])
        from ...marketstructure.sessions import ET
        if dt.datetime.now(dt.timezone.utc).astimezone(ET).date() <= opened.astimezone(ET).date():
            return False, "the session boundary has not passed"
        return True, "new session"
    if cause == "shared_component":
        return (True, "owner confirmed") if note and len(note) >= 12 else (False, "the component owner's confirmation note is required")
    return False, "unknown cause"


async def resolve_incident(eng, incident_id: str, *, resolver: str, examined_revision: int,
                           note: str = "") -> dict:
    """Release an incident: the resolver states which REVISION it examined
    (a stale resolution — newer evidence appended since — is refused) and
    the cause-specific validation must pass. Resolving never touches a loss
    halt, and lifting a halt never resolves an incident."""
    from ... import events as ev
    from ...models import TipExecutionIncident
    async with eng.sf() as session:
        row = await session.get(TipExecutionIncident, incident_id, with_for_update=True)
        if row is None:
            raise ValueError("unknown incident")
        if row.status != "open":
            raise ValueError(f"incident is {row.status}")
        if int(row.revision or 1) != int(examined_revision):
            raise ValueError(f"stale resolution: incident is at revision {row.revision}, "
                             f"you examined {examined_revision} — re-read the evidence")
        inc = _incident_dict(row)
    ok, detail = await _validate_release(eng, inc, note)
    if not ok:
        await eng.journal.append(ev.TIP_EXECUTION_INCIDENT,
                                 {**inc, "action": "release_refused", "resolver": resolver, "detail": detail},
                                 aggregate_type="incident", aggregate_id=incident_id)
        raise ValueError(f"release criteria not met: {detail}")
    now = dt.datetime.now(dt.timezone.utc)
    async with eng.sf() as session:
        row = await session.get(TipExecutionIncident, incident_id, with_for_update=True)
        if int(row.revision or 1) != int(examined_revision):
            raise ValueError("incident changed during validation — re-read")
        row.status = "resolved"
        row.resolved_at = now
        row.resolver = resolver[:80]
        row.resolution = {"note": note[:400], "examinedRevision": int(examined_revision),
                          "validated": detail, "at": now.isoformat()}
        await session.commit()
        out = _incident_dict(row)
    await eng.journal.append(ev.TIP_EXECUTION_INCIDENT, {**out, "action": "resolved"},
                             aggregate_type="incident", aggregate_id=incident_id)
    log.info("execution incident %s resolved by %s: %s", incident_id[:8], resolver, detail)
    return out


# ---------------------------------------------------------------------------
# Detection: structured evidence only — exit KINDS and execution timestamps,
# never row ages or substring matching on prose.
def classify_fast_stop(position: dict, *, now_ms: int | None = None) -> dict | None:
    """For a CLOSED tip position: was the exit a fast stop (< FAST_STOP_S from
    the entry fill to the stop exit), and if so does the evidence prove it
    was a valid trade? Returns None when not a fast stop, else
    {verdict: valid | evidence_missing | invalid, why, ...}. Pure."""
    exits = [x for x in (position.get("exits") or []) if x.get("kind") in STOP_KINDS
             and x.get("status") in ("FILLED", "PARTIALLY_FILLED")]
    if not exits:
        return None
    opened_ms = int(position.get("openedMs") or 0)
    first_stop = min(exits, key=lambda x: int(x.get("ts") or 0))
    exit_ms = int(first_stop.get("ts") or 0)
    if not opened_ms or not exit_ms:
        return {"verdict": "evidence_missing", "why": "no execution timestamps on the record",
                "seconds": None, "exitKind": first_stop.get("kind")}
    seconds = (exit_ms - opened_ms) / 1000.0
    if seconds >= FAST_STOP_S:
        return None
    rp = (position.get("extras") or {}).get("riskPlan") or {}
    problems: list[str] = []
    if not rp:
        problems.append("no pre-entry risk plan on the position")
    else:
        if not rp.get("enforced"):
            problems.append("risk plan was not enforced at entry")
        if rp.get("invariantOk") is False:
            return {"verdict": "invalid", "why": "the FILLED position violated qty x unitLoss <= budget",
                    "seconds": seconds, "exitKind": first_stop.get("kind")}
        if rp.get("reviewRequired"):
            return {"verdict": "invalid", "why": f"entered despite review-required geometry: {rp['reviewRequired']}",
                    "seconds": seconds, "exitKind": first_stop.get("kind")}
        q = rp.get("quote") or {}
        if q.get("delayed"):
            return {"verdict": "invalid", "why": "the entry was priced on a delayed quote",
                    "seconds": seconds, "exitKind": first_stop.get("kind")}
    exc = (position.get("extras") or {}).get("geometryException") or {}
    if exc.get("phase") in ("trim_pending", "reconcile"):
        return {"verdict": "invalid", "why": f"stopped with an unresolved geometry exception ({exc['phase']})",
                "seconds": seconds, "exitKind": first_stop.get("kind")}
    if first_stop.get("kind") == "premium_stop" and not first_stop.get("evidence") \
            and "confirmed" not in str(first_stop.get("reason") or ""):
        problems.append("premium stop without a confirmation record")
    if problems:
        return {"verdict": "evidence_missing", "why": "; ".join(problems), "seconds": seconds,
                "exitKind": first_stop.get("kind")}
    return {"verdict": "valid", "why": "final geometry, sizing and quote evidence valid; a clean fast loss",
            "seconds": seconds, "exitKind": first_stop.get("kind")}


async def detect_incidents(eng, *, portfolio_id: str | None = None) -> list[dict]:
    """Scan today's CLOSED tip positions on real books for fast stops and
    classify each ONCE (idempotent via the journal): valid → diagnostic
    `TipFastStopDiagnostic`; evidence missing → `hold` incident; invalid →
    `integrity` incident. Also: open positions with an unresolved geometry
    exception → integrity incident; manager reconciliation halts on tip
    symbols → integrity incident. Returns the incidents opened/extended."""
    from sqlalchemy import select
    from ... import events as ev
    from ...models import Event, ManagedPositionRow
    from zoneinfo import ZoneInfo
    opened: list[dict] = []
    scope_base = default_scope(eng)
    if portfolio_id:
        scope_base = {**scope_base, "portfolioId": portfolio_id}
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
    sod = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        async with eng.sf() as session:
            rows = (await session.execute(select(ManagedPositionRow).where(
                ManagedPositionRow.technique == "tip", ManagedPositionRow.status == "closed",
                ManagedPositionRow.updated_at >= sod))).scalars().all()
            seen = set((await session.execute(
                select(Event.aggregate_id).where(Event.type == ev.TIP_FAST_STOP_DIAGNOSTIC))).scalars().all())
        for r in rows:
            pf = eng.positions.portfolio(r.portfolio_id) or {}
            if pf.get("kind") != "sim" or (scope_base.get("portfolioId") and r.portfolio_id != scope_base["portfolioId"]):
                continue                                    # research/shadow books and other books: never
            if r.id in seen:
                continue
            st = r.state or {}
            position = {"id": r.id, "exits": st.get("exits") or [], "openedMs": st.get("openedMs"),
                        "extras": (r.config or {}).get("extras") or {}}
            verdict = classify_fast_stop(position)
            if verdict is None:
                continue
            payload = {"positionId": r.id, "symbol": r.symbol, "portfolioId": r.portfolio_id, **verdict}
            await eng.journal.append(ev.TIP_FAST_STOP_DIAGNOSTIC, payload, aggregate_type="position",
                                     aggregate_id=r.id, portfolio_id=r.portfolio_id)
            evidence = [{"kind": "position", "id": r.id, "symbol": r.symbol, "note": verdict["why"]}]
            scope = {**scope_base, "portfolioId": r.portfolio_id}
            if verdict["verdict"] == "invalid":
                opened.append(await open_incident(eng, kind="integrity", cause="geometry_violation_filled",
                                                  scope=scope, evidence=evidence,
                                                  why=f"{r.symbol}: {verdict['why']}"))
            elif verdict["verdict"] == "evidence_missing":
                opened.append(await open_incident(eng, kind="hold", cause="evidence_missing", scope=scope,
                                                  evidence=evidence, why=f"{r.symbol}: {verdict['why']}"))
        mgr = getattr(eng, "position_manager", None)
        if mgr is not None:
            for p in list(getattr(mgr, "_pos", {}).values()):
                if p.technique != "tip" or (eng.positions.portfolio(p.portfolio_id) or {}).get("kind") != "sim":
                    continue
                exc = (p.extras or {}).get("geometryException") or {}
                if exc.get("phase") == "reconcile":
                    opened.append(await open_incident(
                        eng, kind="integrity", cause="geometry_violation_filled",
                        scope={**scope_base, "portfolioId": p.portfolio_id},
                        evidence=[{"kind": "position", "id": p.id, "symbol": p.symbol, "note": exc.get("why")}],
                        why=f"{p.symbol}: filled position holds an unresolvable geometry exception"))
                if p.halt_entries or p.symbol.upper() in set(getattr(mgr, "_entry_halted", set())):
                    opened.append(await open_incident(
                        eng, kind="integrity", cause="unreconciled_fill",
                        scope={**scope_base, "portfolioId": p.portfolio_id, "symbol": p.symbol},
                        evidence=[{"kind": "position", "id": p.id, "symbol": p.symbol,
                                   "note": "; ".join(p.attention or []) or "reconciliation drift"}],
                        why=f"{p.symbol}: unexplained reconciliation drift"))
    except Exception:
        log.debug("incident detection failed", exc_info=True)
    return opened


async def record_pre_entry_failure(eng, *, portfolio_id: str | None, entry_path: str, reason: str,
                                   ref: str | None) -> dict | None:
    """Invalid geometry BEFORE entry is refused/reviewed on its own; REPEATED
    systemic failures on one entry path (REPEATED_PRE_ENTRY_FAILURES in a
    session) open an integrity incident for that path. Counted from the
    journal (TipGeometryRepaired pre-entry with reviewRequired), so a restart
    keeps the count."""
    from sqlalchemy import select
    from ... import events as ev
    from ...models import Event
    from zoneinfo import ZoneInfo
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
    sod = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)
    try:
        async with eng.sf() as session:
            rows = (await session.execute(select(Event.payload).where(
                Event.type == ev.TIP_GEOMETRY_REPAIRED, Event.ts >= sod))).scalars().all()
        n = sum(1 for p in rows if (p or {}).get("phase") == "pre-entry" and (p or {}).get("reviewRequired")
                and ((p or {}).get("entryPath") or "proposal") == entry_path)
    except Exception:
        return None
    if n < REPEATED_PRE_ENTRY_FAILURES:
        return None
    return await open_incident(eng, kind="integrity", cause="repeated_pre_entry_failure",
                               scope={**default_scope(eng), **({"portfolioId": portfolio_id} if portfolio_id else {}),
                                      "entryPath": entry_path},
                               evidence=[{"kind": "journal", "id": ref or f"{entry_path}:{now_et:%Y-%m-%d}",
                                          "note": f"{n} review-required pre-entry results today: {reason}"}],
                               why=f"{n} pre-entry validation failures on the {entry_path} path this session")


async def _cancel_resting_entries(eng, incident: dict) -> int:
    """An incident opened after arming still blocks: resting AUTOMATED entry
    orders in scope are cancelled (reduce-only exits are never touched).
    Proposal-path: executed cards whose entry order is still working — the
    adoption task then sees CANCELLED (or adopts a partial, never a
    duplicate). Armed-path: the tip runner's working entry trades."""
    from sqlalchemy import select
    from ... import events as ev
    from ...models import Order, Proposal
    scope = incident.get("scope") or {}
    n = 0
    try:
        async with eng.sf() as session:
            props = (await session.execute(select(Proposal).where(Proposal.status == "executed"))).scalars().all()
            for pr in props:
                ctx = pr.context or {}
                if ctx.get("techniqueId") != "tip" or pr.decided_via not in ("auto", "triage", "recovery"):
                    continue
                if scope.get("portfolioId") and pr.portfolio_id != scope["portfolioId"]:
                    continue
                if not pr.order_id:
                    continue
                o = await session.get(Order, pr.order_id)
                if o is None or o.status not in ("SUBMITTED", "WORKING", "PARTIALLY_FILLED", "PENDING", "NEW"):
                    continue
                with contextlib.suppress(Exception):
                    await eng.orders.cancel(pr.order_id)
                    n += 1
                    await eng.journal.append(ev.TIP_EXECUTION_INCIDENT,
                                             {"id": incident["id"], "action": "cancelled_resting_entry",
                                              "proposalId": pr.id, "orderId": pr.order_id},
                                             aggregate_type="incident", aggregate_id=incident["id"],
                                             portfolio_id=pr.portfolio_id)
    except Exception:
        log.debug("cancel resting proposal entries failed", exc_info=True)
    runner = None
    with contextlib.suppress(Exception):
        runner = eng.plan_runners.get("tip")
    if runner is not None:
        with contextlib.suppress(Exception):
            n += await runner.cancel_working_entries(reason=f"execution incident {incident['id'][:8]}",
                                                    portfolio_id=scope.get("portfolioId"))
    return n
