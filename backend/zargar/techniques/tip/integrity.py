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


async def list_incidents(eng, *, status: str | None = "open", limit: int | None = 100) -> list[dict]:
    """Incidents newest first. `limit=None` = COMPLETE (the admission path
    must see every open incident, never a recent slice — I93-01)."""
    from sqlalchemy import select
    from ...models import TipExecutionIncident
    async with eng.sf() as session:
        q = select(TipExecutionIncident).order_by(TipExecutionIncident.opened_at.desc())
        if status:
            q = q.where(TipExecutionIncident.status == status)
        if limit:
            q = q.limit(int(limit))
        rows = (await session.execute(q)).scalars().all()
    return [_incident_dict(r) for r in rows]


async def entry_paused(eng, *, portfolio_id: str | None, technique: str = "tip",
                       entry_path: str | None = None, symbol: str | None = None) -> str | None:
    """The reason no NEW automated entry may be placed right now on this
    technique/book/path — the first OPEN incident whose scope matches — or
    None. Answers from the store (persisted: a restart cannot clear it) over
    the COMPLETE set of open incidents. An unavailable store is a refusal
    (I93-01: fail closed — 'unknown' is never 'no incidents'). Exits never
    consult this."""
    try:
        incidents = await list_incidents(eng, status="open", limit=None)
    except Exception as exc:
        log.warning("incident store unavailable — automated entries refused: %s", exc)
        return f"execution-integrity state unavailable ({type(exc).__name__}) — automated entry refused"
    for inc in incidents:
        if _scope_matches(inc["scope"], technique=technique, portfolio_id=portfolio_id,
                          entry_path=entry_path, symbol=symbol):
            return (f"execution-integrity {inc['kind']} incident {inc['id'][:8]} "
                    f"({inc['cause']}): {inc['why']} — release: {inc['releaseCriteria']}")
    return None


def incident_identity_record(inc: dict) -> dict:
    """The identity a person acknowledges (A86-01): id, revision and the
    evidence content - any appended evidence or a different incident set is
    a different identity."""
    import hashlib
    import json
    ev_hash = hashlib.sha256(json.dumps(inc.get("evidence") or [], sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return {"id": str(inc.get("id")), "revision": int(inc.get("revision") or 1), "evidenceHash": ev_hash,
            "kind": inc.get("kind"), "cause": inc.get("cause")}


async def applicable_incidents(eng, *, portfolio_id: str | None, technique: str = "tip",
                               entry_path: str | None = None, symbol: str | None = None) -> list[dict]:
    """ALL open incidents whose scope applies (complete set, sorted by id) as
    identity records - the structured companion of `entry_paused` (which
    reports the first one in prose). Raises when the store is unavailable."""
    incidents = await list_incidents(eng, status="open", limit=None)
    out = [incident_identity_record(inc) for inc in incidents
           if _scope_matches(inc["scope"], technique=technique, portfolio_id=portfolio_id,
                             entry_path=entry_path, symbol=symbol)]
    return sorted(out, key=lambda x: x["id"])


async def admission(eng, *, portfolio_id: str | None, entry_path: str,
                    symbol: str | None = None, detect: bool = True) -> str | None:
    """The ONE final-admission boundary for every automated entry path
    (proposal auto-approval, approve(via=auto), the stale-quote retry, the
    armed fire and EVERY transport retry of it): runs detection first (a
    defect that just happened pauses this very entry), then answers from
    the complete incident set; fails closed when either is unavailable.
    Only active when the pause mode includes incidents — the clock gate stays
    exactly where it lives today."""
    if not pauses(eng.settings):
        return None
    if detect:
        try:
            await detect_incidents(eng, portfolio_id=portfolio_id, strict=True)
        except Exception as exc:
            return f"execution-integrity detection unavailable ({type(exc).__name__}) — automated entry refused"
    return await entry_paused(eng, portfolio_id=portfolio_id, entry_path=entry_path, symbol=symbol)


async def gate_reason(eng, *, portfolio_id: str | None, entry_path: str) -> str | None:
    """What the automated entry paths call: honours the pause MODE — the
    clock gate alone (default), incidents alone, or both."""
    mode = pause_mode(eng.settings)
    if mode in ("integrity", "both"):
        why = await admission(eng, portfolio_id=portfolio_id, entry_path=entry_path)
        if why:
            return why
    if mode in ("clock", "both"):
        from .lifecycle import adoption_killswitch
        return await adoption_killswitch(eng)
    return None


# ---------------------------------------------------------------------------
def _incident_symbols(inc: dict) -> set[str]:
    out = {str((inc.get("scope") or {}).get("symbol") or "").upper()}
    for e in inc.get("evidence") or []:
        if e.get("symbol"):
            out.add(str(e["symbol"]).upper())
    return {x for x in out if x}


async def _incident_order_ids(eng, inc: dict) -> set[str] | None:
    """The order ids that belong to the incident's positions (entry legs and
    exits). None when the positions cannot be loaded (unknown, not empty)."""
    sf = getattr(eng, "sf", None)
    pos_ids = [str(e.get("id")) for e in inc.get("evidence") or [] if e.get("kind") == "position"]
    if sf is None or not pos_ids:
        return None
    ids: set[str] = set()
    try:
        from ...models import ManagedPositionRow
        async with sf() as session:
            for pid in pos_ids:
                row = await session.get(ManagedPositionRow, pid)
                for l in (getattr(row, "legs", None) or []):
                    if isinstance(l, dict) and l.get("entryOrderId"):
                        ids.add(str(l["entryOrderId"]))
                for x in ((getattr(row, "state", None) or {}).get("exits") or []):
                    if isinstance(x, dict) and x.get("orderId"):
                        ids.add(str(x["orderId"]))
    except Exception:
        return None
    return ids


async def _resolve_proof(eng, e: dict, inc: dict | None = None) -> tuple[bool | None, str]:
    ok, detail, _meta = await _resolve_proof_meta(eng, e, inc)
    return ok, detail


async def _resolve_proof_meta(eng, e: dict, inc: dict | None = None) -> tuple[bool | None, str, dict]:
    """A proof reference resolves to an ACTUAL record BOUND to the incident
    (C95-06) or it is nothing: an API-supplied boolean is not validation, and
    a record's mere existence is not either. Supported refs:
    `execution:<id>` — must be in the incident's book, for one of the
    incident's symbols and belong to one of the incident's positions' orders
    (entry legs or exits); `event:<id>` — a journal row of a kind that carries
    structured validity, for one of the incident's positions/proposals;
    `position:<id>` — one of the incident's own positions whose plan is
    enforced and inside its invariant. Returns (valid|None, detail)."""
    inc = inc or {}
    scope = inc.get("scope") or {}
    ref = str(e.get("ref") or e.get("id") or "")
    sf = getattr(eng, "sf", None)
    if not ref or ":" not in ref or sf is None:
        return None, f"unresolvable proof reference {ref!r}", {}
    kind, _, ident = ref.partition(":")
    symbols = _incident_symbols(inc)
    pos_ids = {str(x.get("id")) for x in inc.get("evidence") or [] if x.get("kind") == "position"}
    try:
        from ...models import Event, Execution, ManagedPositionRow
        async with sf() as session:
            if kind == "execution":
                row = await session.get(Execution, ident)
                if row is None:
                    return None, f"execution {ident} does not exist", {}
                meta = {"kind": "execution", "ts": row.ts, "orderId": str(row.order_id), "symbol": str(row.symbol)}
                if scope.get("portfolioId") and str(row.portfolio_id) != str(scope["portfolioId"]):
                    return None, f"execution {ident} is in book {row.portfolio_id}, not the incident's — unrelated", meta
                order_ids = await _incident_order_ids(eng, inc)
                if order_ids is None:
                    return None, f"execution {ident}: the incident's positions could not be loaded", meta
                # EOD-06: the binding is the EXACT leg/order/book relationship — an
                # execution on one of the incident's positions' own orders (entry
                # legs or exits) is bound even when its symbol is the option
                # CONTRACT and the incident is scoped by the UNDERLYING; a symbol
                # match alone never binds
                if str(row.order_id) in order_ids:
                    return True, f"execution {ident} {row.side} {row.qty:g} @ {row.price} at {row.ts.isoformat()}", meta
                if symbols and str(row.symbol).upper() not in symbols:
                    return None, f"execution {ident} is for {row.symbol}, not {', '.join(sorted(symbols))} — unrelated", meta
                return None, f"execution {ident} belongs to order {row.order_id}, not one of the incident's positions — unrelated", meta
            if kind == "event":
                row = await session.get(Event, int(ident))
                if row is None:
                    return None, f"journal event {ident} does not exist", {}
                p = row.payload or {}
                meta = {"kind": "event", "ts": row.ts, "type": row.type, "payload": p}
                if scope.get("portfolioId") and row.portfolio_id and str(row.portfolio_id) != str(scope["portfolioId"]):
                    return None, f"journal event {ident} is in another book — unrelated", meta
                if row.type == "TipGeometryRepaired":
                    # a REPAIRED-PATH record: bound by book + the incident's underlying(s)
                    under = str(p.get("underlying") or "").upper()
                    if symbols and under not in symbols:
                        return None, f"journal event {ident} is about {under or '?'}, not the incident's symbol — unrelated", meta
                    if not scope.get("portfolioId") and not p.get("portfolioId"):
                        pass
                    q = p.get("quote") or {}
                    ok = bool(p.get("enforced")) and not p.get("reviewRequired") and not q.get("delayed") \
                        and not q.get("underlyingDelayed")
                    return ok, (f"event {ident}: {'enforced pre-entry plan without review' if ok else 'pre-entry record not a clean repaired path'}"), {**meta, "repairedPath": ok}
                bound = (str(p.get("positionId") or "") in pos_ids
                         or str(p.get("proposalId") or "") in {str(x.get("id")) for x in inc.get("evidence") or [] if x.get("kind") == "proposal"})
                if not bound:
                    return None, f"journal event {ident} is not about one of the incident's positions/proposals — unrelated", meta
                if row.type == "TipFastStopDiagnostic":
                    return (p.get("verdict") == "valid"), f"event {ident}: diagnostic verdict {p.get('verdict')}", {**meta, "observation": True}
                if row.type == "ManagedPositionExit" and p.get("confirmation"):
                    return bool((p.get("confirmation") or {}).get("confirmed")), f"event {ident}: exit confirmation record", {**meta, "observation": True}
                return None, f"journal event {ident} ({row.type}) carries no structured validity", meta
            if kind == "position":
                if pos_ids and ident not in pos_ids:
                    return None, f"position {ident} is not one of the incident's positions — unrelated", {}
                row = await session.get(ManagedPositionRow, ident)
                if row is None:
                    return None, f"position {ident} does not exist", {}
                meta = {"kind": "position", "ts": getattr(row, "updated_at", None)}
                if scope.get("portfolioId") and str(row.portfolio_id) != str(scope["portfolioId"]):
                    return None, f"position {ident} is in another book — unrelated", meta
                rp = ((row.config or {}).get("extras") or {}).get("riskPlan") or {}
                if not rp:
                    return None, f"position {ident} has no risk plan", meta
                ok = bool(rp.get("enforced")) and rp.get("invariantOk") is True and not rp.get("reviewRequired") \
                    and not (rp.get("quote") or {}).get("delayed")
                return ok, f"position {ident}: enforced={rp.get('enforced')} invariantOk={rp.get('invariantOk')}", meta
    except Exception as exc:
        return None, f"proof {ref} could not be resolved: {exc}", {}
    return None, f"unknown proof kind {kind!r}", {}


async def _validate_release(eng, inc: dict, note: str) -> tuple[bool, str]:
    """Cause-specific check of the release criteria against CURRENT state at
    the examined revision (I93-03): referenced evidence must resolve to actual
    records; an unavailable manager/store is UNKNOWN, and unknown is never
    repaired; the calendar alone never releases; a human override is a
    separate, labeled path (`resolve_incident(..., override=True)`)."""
    cause = inc["cause"]
    mgr = getattr(eng, "position_manager", None)
    pos_ids = [str(e.get("id")) for e in inc.get("evidence") or [] if e.get("kind") == "position"]
    proofs = [e for e in inc.get("evidence") or [] if e.get("kind") == "proof"]

    resolved: list[tuple] = []

    async def resolved_proofs() -> tuple[list[str], list[str], list[str]]:
        good, bad, unknown = [], [], []
        resolved.clear()
        for e in proofs:
            ok, detail, meta = await _resolve_proof_meta(eng, e, inc)
            resolved.append((ok, detail, meta))
            (good if ok else bad if ok is False else unknown).append(detail)
        return good, bad, unknown

    def _opened() -> dt.datetime | None:
        try:
            t = dt.datetime.fromisoformat(inc["openedAt"])
            return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
        except Exception:
            return None

    if cause == "geometry_violation_filled":
        if mgr is None:
            return False, "position manager unavailable — repair cannot be verified (unknown is not repaired)"
        sf = getattr(eng, "sf", None)
        for pid in pos_ids:
            p = mgr.get(pid)
            if p is None:
                # not in memory: verify it is CLOSED on the record, never assume
                if sf is None:
                    return False, f"position {pid[:8]} state unknown"
                try:
                    from ...models import ManagedPositionRow
                    async with sf() as session:
                        row = await session.get(ManagedPositionRow, pid)
                except Exception as exc:
                    return False, f"position {pid[:8]} state unavailable: {exc}"
                if row is None or row.status != "closed":
                    return False, f"position {pid[:8]} is {getattr(row, 'status', 'missing')} — not repaired"
                continue
            exc = (p.extras or {}).get("geometryException") or {}
            if exc.get("phase") in ("trim_pending", "reconcile"):
                return False, f"position {pid[:8]} still holds an unresolved geometry exception ({exc.get('phase')})"
            rp = (p.extras or {}).get("riskPlan") or {}
            if exc.get("phase") == "kept_tight" or exc.get("phase") == "widened":
                continue                                    # a resolved exception: the tight/admissible stop is in force
            if not (rp.get("enforced") and rp.get("invariantOk") is True):
                return False, f"position {pid[:8]} still violates its risk plan"
        return True, "every referenced position is closed or back inside its risk plan"
    if cause == "unreconciled_fill":
        if mgr is None:
            return False, "position manager unavailable — drift cannot be verified"
        halted = set(getattr(mgr, "_entry_halted", set()))
        syms = {str(e.get("symbol") or "").upper() for e in inc.get("evidence") or [] if e.get("symbol")}
        still = sorted(syms & halted)
        if still:
            return False, f"reconciliation drift still halts {', '.join(still)}"
        for pid in pos_ids:
            p = mgr.get(pid)
            if p is not None and p.halt_entries:
                return False, f"position {pid[:8]} still flags reconciliation drift"
        return True, "no reconciliation drift on the incident's symbols"
    if cause == "duplicate_execution":
        # verified against the executions table: no order with fills beyond its quantity
        sf = getattr(eng, "sf", None)
        order_ids = [str(e.get("id")) for e in inc.get("evidence") or [] if e.get("kind") == "order"]
        if sf is None or not order_ids:
            return False, "duplicate cannot be verified without the order records"
        try:
            from sqlalchemy import func, select
            from ...models import Execution, Order
            async with sf() as session:
                for oid in order_ids:
                    o = await session.get(Order, oid)
                    filled = float((await session.execute(
                        select(func.coalesce(func.sum(Execution.qty), 0.0)).where(Execution.order_id == oid))).scalar() or 0)
                    if o is None or filled > float(o.qty) + 1e-9:
                        return False, f"order {oid[:8]} still shows {filled:g} filled against {getattr(o, 'qty', '?')} requested"
        except Exception as exc:
            return False, f"execution records unavailable: {exc}"
        return True, "executions match their orders"
    if cause == "evidence_missing":
        if not proofs:
            return False, "no proof evidence appended — receiving nothing is not validation"
        good, bad, unknown = await resolved_proofs()
        if bad:
            return False, "the appended evidence proves a defect, not validity — open an integrity incident instead: " + "; ".join(bad)
        if not good:
            return False, "proof references do not resolve to records: " + "; ".join(unknown or ["none valid"])
        # unresolvable references never count; they are reported, not fatal, once a real record validates
        return True, (f"{len(good)} resolved proof record(s) validate the trade: " + "; ".join(good)
                      + (f" (ignored {len(unknown)} unresolvable reference(s))" if unknown else ""))
    if cause == "invalid_evidence":
        # an INVALID-QUOTE / invalid-evidence incident releases only when the
        # entry/exit path is proven REPAIRED (a clean enforced pre-entry record
        # for this book + symbol, AFTER the incident opened) AND a qualifying
        # FRESH observation exists (an execution or confirmed exit record bound
        # to the incident's positions, AFTER the incident opened). An earlier
        # fill — even of the correct position — predates the defect and proves
        # nothing about the repair.
        good, bad, unknown = await resolved_proofs()
        if bad:
            return False, "the appended evidence itself shows a defect: " + "; ".join(bad)
        opened = _opened()
        if opened is None:
            return False, "the incident has no usable opening time"
        repaired = [d for ok, d, m in resolved if ok and m.get("repairedPath") and m.get("ts") and m["ts"] > opened]
        stale_repairs = [d for ok, d, m in resolved if ok and m.get("repairedPath") and m.get("ts") and m["ts"] <= opened]
        fresh = [d for ok, d, m in resolved if ok and (m.get("kind") == "execution" or m.get("observation"))
                 and m.get("ts") and m["ts"] > opened]
        stale = [d for ok, d, m in resolved if ok and (m.get("kind") == "execution" or m.get("observation"))
                 and m.get("ts") and m["ts"] <= opened]
        if not repaired:
            return False, ("no repaired-path record after the incident opened"
                           + (f" (a record predating it does not count: {'; '.join(stale_repairs)})" if stale_repairs else "")
                           + (f"; unresolved: {'; '.join(unknown)}" if unknown else ""))
        if not fresh:
            return False, ("no qualifying fresh observation after the incident opened"
                           + (f" — an earlier fill predates the defect: {'; '.join(stale)}" if stale else ""))
        return True, "repaired path: " + "; ".join(repaired) + " | fresh observation: " + "; ".join(fresh)
    if cause == "repeated_pre_entry_failure":
        # the calendar never releases on its own: a SUCCESSFUL pre-entry
        # validation on this path must be on the journal AFTER the incident opened
        sf = getattr(eng, "sf", None)
        if sf is None:
            return False, "journal unavailable — no successful revalidation can be verified"
        try:
            from sqlalchemy import select
            from ...models import Event
            opened = dt.datetime.fromisoformat(inc["openedAt"])
            path = (inc.get("scope") or {}).get("entryPath") or "proposal"
            async with sf() as session:
                q = select(Event.payload).where(Event.type == "TipGeometryRepaired", Event.ts > opened)
                if (inc.get("scope") or {}).get("portfolioId"):
                    q = q.where(Event.portfolio_id == str(inc["scope"]["portfolioId"]))
                rows = (await session.execute(q)).scalars().all()
        except Exception as exc:
            return False, f"journal unavailable: {exc}"
        ok = [p for p in rows if (p or {}).get("phase") in ("pre-entry", "submit") and (p or {}).get("enforced")
              and not (p or {}).get("reviewRequired") and ((p or {}).get("entryPath") or "proposal") == path]
        if not ok:
            return False, "no successful pre-entry validation on this path since the incident opened"
        return True, f"{len(ok)} successful pre-entry validation(s) since the incident opened"
    if cause == "shared_component":
        good, bad, unknown = await resolved_proofs()
        if bad:
            return False, "the component's evidence still shows a defect"
        if good:
            return True, "component health resolved from records: " + "; ".join(good)
        return False, "a shared-component incident releases on resolved health evidence or a labeled override"
    return False, "unknown cause"


async def resolve_incident(eng, incident_id: str, *, resolver: str, examined_revision: int,
                           note: str = "", override: bool = False) -> dict:
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
    if not ok and override:
        # a HUMAN override is honest about what it is: not a verified repair
        if not note or len(note.strip()) < 20:
            raise ValueError("an override needs a substantive note (>= 20 chars) stating why the desk accepts the risk")
        ok, detail = True, f"OVERRIDE by {resolver} (validation said: {detail})"
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
                          "validated": detail, "override": bool(override and detail.startswith("OVERRIDE")),
                          "at": now.isoformat()}
        await session.commit()
        out = _incident_dict(row)
    await eng.journal.append(ev.TIP_EXECUTION_INCIDENT, {**out, "action": "resolved"},
                             aggregate_type="incident", aggregate_id=incident_id)
    log.info("execution incident %s resolved by %s: %s", incident_id[:8], resolver, detail)
    return out


# ---------------------------------------------------------------------------
# Detection: structured evidence only — exit KINDS and execution timestamps,
# never row ages or substring matching on prose.
def _risk_plan_evidence(rp: dict) -> tuple[str, str]:
    """(status, why) of a position's pre-entry risk plan as EVIDENCE:
    'valid' needs enforced + invariantOk True + no review + a non-delayed
    quote record; anything less is 'missing'; a recorded violation is
    'invalid'. A bare {enforced: true} proves nothing (I93-02)."""
    if not rp:
        return "missing", "no pre-entry risk plan on the position"
    if rp.get("invariantOk") is False:
        return "invalid", "the FILLED position violated qty x unitLoss <= budget"
    if rp.get("reviewRequired"):
        return "invalid", f"entered despite review-required geometry: {rp['reviewRequired']}"
    q = rp.get("quote") or {}
    if q.get("delayed") is True or q.get("underlyingDelayed") is True:
        return "invalid", "the entry was priced on a delayed quote"
    missing = []
    if not rp.get("enforced"):
        missing.append("risk plan was not enforced at entry")
    if rp.get("invariantOk") is not True:
        missing.append("no budget invariant on the record")
    if "delayed" not in q:
        missing.append("no quote-freshness record on the plan")
    if missing:
        return "missing", "; ".join(missing)
    return "valid", "enforced plan, budget invariant and quote freshness on the record"


def _exit_evidence(x: dict) -> tuple[str, str]:
    """A premium stop is proven only by a STRUCTURED confirmation record on
    the exit (`confirmation: {confirmed: true, observations: [...]}`); prose is
    not evidence (I93-02: 'NOT confirmed; missing observation' passed the old
    substring test)."""
    if x.get("kind") != "premium_stop":
        return "valid", "underlying/venue stop"
    conf = x.get("confirmation")
    if isinstance(conf, dict) and conf.get("confirmed") is True and len(conf.get("observations") or []) >= 2:
        return "valid", "premium stop with a two-observation confirmation record"
    if isinstance(conf, dict) and conf.get("confirmed") is False:
        return "invalid", "premium stop exited WITHOUT confirmation"
    return "missing", "premium stop without a structured confirmation record"


def classify_fast_stop(position: dict, *, now_ms: int | None = None,
                       entry_fill_ms: int | None = None, exit_fill_ms: int | None = None) -> dict | None:
    """For a CLOSED tip position: classify a STOP exit from structured
    evidence. Timing uses ACTUAL fill timestamps when the caller resolved
    them from the executions table (`entry_fill_ms` / `exit_fill_ms`); the
    record's `openedMs` (adoption) and the exit's `filledTs` are the fallback,
    and an unknown timing is reported as unknown, never assumed fast or slow.
    A proven violation is `invalid` at any speed (its significance is
    independent of elapsed time); a slow stop with valid evidence is None
    (nothing to classify); a fast stop is `valid` only when the plan, budget,
    quote and exit evidence are all on the record. Pure."""
    exits = [x for x in (position.get("exits") or []) if x.get("kind") in STOP_KINDS
             and x.get("status") in ("FILLED", "PARTIALLY_FILLED")]
    if not exits:
        return None
    first_stop = min(exits, key=lambda x: int(x.get("filledTs") or x.get("ts") or 0))
    kind = first_stop.get("kind")
    rp = (position.get("extras") or {}).get("riskPlan") or {}
    plan_status, plan_why = _risk_plan_evidence(rp)
    exit_status, exit_why = _exit_evidence(first_stop)
    exc = (position.get("extras") or {}).get("geometryException") or {}
    if exc.get("phase") in ("trim_pending", "reconcile"):
        plan_status, plan_why = "invalid", f"stopped with an unresolved geometry exception ({exc['phase']})"
    opened = int(entry_fill_ms or 0) or None
    closed = int(exit_fill_ms or 0) or None
    timing = "fills"
    if opened is None or closed is None:
        opened = opened or int(position.get("openedMs") or 0) or None
        closed = closed or int(first_stop.get("filledTs") or 0) or None
        timing = "record"
    seconds = ((closed - opened) / 1000.0) if (opened and closed) else None
    fast = (seconds is not None and seconds < FAST_STOP_S)
    base = {"seconds": seconds, "exitKind": kind, "timing": timing if seconds is not None else "unknown"}
    if plan_status == "invalid" or exit_status == "invalid":
        why = plan_why if plan_status == "invalid" else exit_why
        defect = ("quote" if "delayed quote" in why else "exit-evidence" if exit_status == "invalid" else "geometry")
        return {"verdict": "invalid", "why": why, "defect": defect, **base}
    if seconds is None:
        return {"verdict": "evidence_missing", "why": "no execution timestamps on the record", **base}
    if not fast:
        return None
    problems = [w for st, w in ((plan_status, plan_why), (exit_status, exit_why)) if st == "missing"]
    if problems:
        return {"verdict": "evidence_missing", "why": "; ".join(problems), **base}
    return {"verdict": "valid", "why": "final geometry, sizing, quote and exit evidence valid; a clean fast loss", **base}


async def _fill_times(eng, position_row) -> tuple[int | None, int | None]:
    """ACTUAL entry / first-stop fill times from the executions table
    (I93-02): the entry legs' order ids and the stop exit's order id."""
    try:
        from sqlalchemy import select
        from ...models import Execution
        legs = position_row.legs or []
        st = position_row.state or {}
        entry_ids = [l.get("entryOrderId") for l in legs if l.get("entryOrderId")]
        stops = [x for x in (st.get("exits") or []) if x.get("kind") in STOP_KINDS
                 and x.get("status") in ("FILLED", "PARTIALLY_FILLED") and x.get("orderId")]
        stop_ids = [x["orderId"] for x in stops]
        if not entry_ids or not stop_ids:
            return None, None
        async with eng.sf() as session:
            e_rows = (await session.execute(select(Execution.ts).where(Execution.order_id.in_(entry_ids)))).scalars().all()
            x_rows = (await session.execute(select(Execution.ts).where(Execution.order_id.in_(stop_ids)))).scalars().all()
        if not e_rows or not x_rows:
            return None, None
        first_entry = min(e_rows)
        first_stop = min(x_rows)
        return int(first_entry.timestamp() * 1000), int(first_stop.timestamp() * 1000)
    except Exception:
        return None, None


async def detect_incidents(eng, *, portfolio_id: str | None = None, strict: bool = False) -> list[dict]:
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
            entry_ms, exit_ms = await _fill_times(eng, r)
            verdict = classify_fast_stop(position, entry_fill_ms=entry_ms, exit_fill_ms=exit_ms)
            if verdict is None:
                continue
            payload = {"positionId": r.id, "symbol": r.symbol, "portfolioId": r.portfolio_id, **verdict}
            evidence = [{"kind": "position", "id": r.id, "symbol": r.symbol, "note": verdict["why"]}]
            scope = {**scope_base, "portfolioId": r.portfolio_id}
            # C95-07: a classification that REQUIRES an incident is finished only
            # once that incident exists — the diagnostic receipt (which makes the
            # position "seen") is written after the incident, carrying its id, so a
            # failed incident write is retried on the next detection
            inc = None
            if verdict["verdict"] == "invalid":
                cause = ("invalid_evidence" if verdict.get("defect") in ("quote", "exit-evidence")
                         else "geometry_violation_filled")
                inc = await open_incident(eng, kind="integrity", cause=cause,
                                          scope=scope, evidence=evidence, why=f"{r.symbol}: {verdict['why']}")
            elif verdict["verdict"] == "evidence_missing":
                inc = await open_incident(eng, kind="hold", cause="evidence_missing", scope=scope,
                                          evidence=evidence, why=f"{r.symbol}: {verdict['why']}")
            if inc is not None:
                opened.append(inc)
                payload["incidentId"] = (inc or {}).get("id")
            await eng.journal.append(ev.TIP_FAST_STOP_DIAGNOSTIC, payload, aggregate_type="position",
                                     aggregate_id=r.id, portfolio_id=r.portfolio_id)
        # duplicate executions: an entry order filled beyond its quantity (I93-02)
        dup = await _duplicate_executions(eng, [r for r in rows], scope_base.get("portfolioId"))
        for oid, sym, pid_, filled, requested in dup:
            opened.append(await open_incident(
                eng, kind="integrity", cause="duplicate_execution",
                scope={**scope_base, "portfolioId": pid_, "symbol": sym},
                evidence=[{"kind": "order", "id": oid, "symbol": sym,
                           "note": f"{filled:g} filled against {requested:g} requested"}],
                why=f"{sym}: order {oid[:8]} shows duplicate executions"))
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
        if strict:
            raise                                   # admission fails CLOSED on an unavailable store
        log.debug("incident detection failed", exc_info=True)
    return opened


async def _duplicate_executions(eng, rows, portfolio_id: str | None) -> list[tuple]:
    """Entry orders of today's closed positions (and every open tip position)
    whose executions sum past the order's quantity."""
    out: list[tuple] = []
    try:
        from sqlalchemy import func, select
        from ...models import Execution, Order
        order_ids: set[str] = set()
        for r in rows:
            for l in (r.legs or []):
                if l.get("entryOrderId"):
                    order_ids.add(str(l["entryOrderId"]))
        mgr = getattr(eng, "position_manager", None)
        for p in list(getattr(mgr, "_pos", {}).values()) if mgr is not None else []:
            if p.technique == "tip":
                for l in p.legs:
                    if getattr(l, "entry_order_id", None):
                        order_ids.add(str(l.entry_order_id))
        if not order_ids:
            return out
        async with eng.sf() as session:
            sums = (await session.execute(
                select(Execution.order_id, func.sum(Execution.qty)).where(Execution.order_id.in_(sorted(order_ids)))
                .group_by(Execution.order_id))).all()
            for oid, filled in sums:
                o = await session.get(Order, oid)
                if o is None or (portfolio_id and o.portfolio_id != portfolio_id):
                    continue
                if float(filled or 0) > float(o.qty) + 1e-9:
                    out.append((oid, o.symbol, o.portfolio_id, float(filled), float(o.qty)))
    except Exception:
        log.debug("duplicate-execution scan failed", exc_info=True)
    return out


_CARD_INTRINSIC_REVIEW = ("no quantity satisfies", "risk budget", "no stop", "spread vehicle",
                          "human decision only", "wrong side", "penny")
# what the producers actually write when EVIDENCE could not be obtained (EOD-02: the
# review's real outputs are "no risk estimate: missing delta — no estimate invented",
# "delta is 901s old (max 900s)", "underlying reference quote is 301s old (max 300s)")
_SYSTEMIC_REVIEW = ("unavailable", "exception", "provider", "delayed", "stale", "no fresh", "missing delta",
                    "no quote", "quote missing", "quote age unknown", "multiplier unknown", "error",
                    "timeout", "bars", "s old", "old (max", "no live underlying")


def systemic_pre_entry_reason(reason: str | None, review_class: str | None = None) -> bool:
    """Does a review-gated pre-entry result point at a FAILING PATH (evidence
    could not be produced: bars/quote/greeks/provider/exception) rather than
    at the card itself (the budget fits no unit, the plan has no stop, an
    unsupported vehicle)? Only the former counts toward
    `repeated_pre_entry_failure` — 2026-09-14, first enforce session: three
    analyst-skipped option cards whose whole debit exceeded the $88 budget
    opened a (duplicated) incident and paused the Practice proposal path.
    The TYPED class on the plan (`reviewClass`: evidence | budget | plan)
    decides when present; the text match is the fallback for older journal
    rows, and it checks the evidence vocabulary FIRST (the producer's
    "no risk estimate:" prefix wraps both kinds — EOD-02 false negative)."""
    if review_class in ("evidence", "budget", "plan"):
        return review_class == "evidence"
    r = str(reason or "").lower()
    if not r:
        return False
    if any(k in r for k in _SYSTEMIC_REVIEW):
        return True
    return False


async def record_pre_entry_failure(eng, *, portfolio_id: str | None, entry_path: str, reason: str,
                                   ref: str | None, review_class: str | None = None) -> dict | None:
    """Invalid geometry BEFORE entry is refused/reviewed on its own; REPEATED
    SYSTEMIC failures on one entry path (REPEATED_PRE_ENTRY_FAILURES in a
    session) open ONE integrity incident for that path (later failures extend
    it). Counted from the journal (TipGeometryRepaired pre-entry with a
    systemic reviewRequired), so a restart keeps the count."""
    if not systemic_pre_entry_reason(reason, review_class):
        return None
    from sqlalchemy import select
    from ... import events as ev
    from ...models import Event
    from zoneinfo import ZoneInfo
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
    sod = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)
    try:
        async with eng.sf() as session:
            q = select(Event.payload).where(Event.type == ev.TIP_GEOMETRY_REPAIRED, Event.ts >= sod)
            if portfolio_id:
                q = q.where(Event.portfolio_id == str(portfolio_id))     # EOD-02: book B never trips book A
            rows = (await session.execute(q)).scalars().all()
        n = sum(1 for p in rows if (p or {}).get("phase") == "pre-entry"
                and systemic_pre_entry_reason((p or {}).get("reviewRequired"), (p or {}).get("reviewClass"))
                and ((p or {}).get("entryPath") or "proposal") == entry_path)
    except Exception:
        return None
    if n < REPEATED_PRE_ENTRY_FAILURES:
        return None
    # ONE incident per path/book/session: the primary evidence id is the
    # session key, so `open_incident`'s idempotency EXTENDS the open incident
    # with this failure instead of opening a duplicate.
    session_key = f"{entry_path}:{portfolio_id or '-'}:{now_et:%Y-%m-%d}"
    evidence = [{"kind": "journal", "id": session_key,
                 "note": f"{n} systemic review-required pre-entry results today on the {entry_path} path"}]
    if ref:
        evidence.append({"kind": "journal", "id": ref, "note": f"pre-entry failure #{n}: {reason}"})
    return await open_incident(eng, kind="integrity", cause="repeated_pre_entry_failure",
                               scope={**default_scope(eng), **({"portfolioId": portfolio_id} if portfolio_id else {}),
                                      "entryPath": entry_path},
                               evidence=evidence,
                               why=f"{n} systemic pre-entry validation failures on the {entry_path} path this session")


async def _cancel_resting_entries(eng, incident: dict) -> int:
    """An incident opened after arming still blocks: resting AUTOMATED entry
    orders IN SCOPE are cancelled (reduce-only exits are never touched) with
    the SAME scope semantics as admission (I93-04): a proposal-path incident
    never touches armed entries and vice versa; a symbol scope narrows both.
    Every cancellation is verified at the order afterwards — a fill that won
    the race is journaled (its adoption path manages it), never assumed
    cancelled."""
    from sqlalchemy import select
    from ... import events as ev
    from ...models import Order, Proposal
    scope = incident.get("scope") or {}
    path = scope.get("entryPath")
    sym_scope = str(scope.get("symbol") or "").upper() or None
    n = 0
    if path in (None, "proposal", "retry"):
        try:
            async with eng.sf() as session:
                props = (await session.execute(select(Proposal).where(Proposal.status == "executed"))).scalars().all()
                todo = []
                for pr in props:
                    ctx = pr.context or {}
                    if ctx.get("techniqueId") != "tip" or pr.decided_via not in ("auto", "triage", "recovery"):
                        continue
                    if not _scope_matches(scope, technique="tip", portfolio_id=pr.portfolio_id,
                                          entry_path=path, symbol=pr.symbol):
                        continue
                    if sym_scope and str(pr.symbol).upper() != sym_scope \
                            and str((ctx.get("vehicle") or {}).get("underlying") or "").upper() != sym_scope:
                        continue
                    if not pr.order_id:
                        continue
                    o = await session.get(Order, pr.order_id)
                    if o is None or o.status not in ("SUBMITTED", "WORKING", "PARTIALLY_FILLED", "PENDING", "NEW"):
                        continue
                    todo.append((pr.id, pr.order_id, pr.portfolio_id))
            for prop_id, order_id, pid in todo:
                outcome = "cancel_requested"
                try:
                    await eng.orders.cancel(order_id)
                except Exception as exc:
                    outcome = f"cancel_failed: {str(exc)[:80]}"
                status = None
                with contextlib.suppress(Exception):
                    async with eng.sf() as session:
                        o = await session.get(Order, order_id)
                        status = o.status if o is not None else None
                if status in ("FILLED", "PARTIALLY_FILLED"):
                    outcome = "filled_before_cancel"        # the adoption path manages the fill
                elif status == "CANCELLED":
                    outcome = "cancelled"
                    n += 1
                with contextlib.suppress(Exception):
                    await eng.journal.append(ev.TIP_EXECUTION_INCIDENT,
                                             {"id": incident["id"], "action": "cancelled_resting_entry",
                                              "proposalId": prop_id, "orderId": order_id, "outcome": outcome,
                                              "orderStatus": status},
                                             aggregate_type="incident", aggregate_id=incident["id"],
                                             portfolio_id=pid)
        except Exception:
            log.debug("cancel resting proposal entries failed", exc_info=True)
    if path in (None, "arm"):
        runner = None
        with contextlib.suppress(Exception):
            runner = eng.plan_runners.get("tip")
        if runner is not None:
            with contextlib.suppress(Exception):
                n += await runner.cancel_working_entries(reason=f"execution incident {incident['id'][:8]}",
                                                        portfolio_id=scope.get("portfolioId"), symbol=sym_scope)
    return n
