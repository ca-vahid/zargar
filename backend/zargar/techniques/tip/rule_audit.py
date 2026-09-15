"""The analyst's weekly rule audit (NEXT-GAPS A8) + the knowledge audit.

Rules (`tip_notes` scope "rule") only ACCRETE during normal trading; this run
is the consolidation: it reads every live rule plus the recent retros and lane
grades, and returns merges (duplicates -> one refined rule), expiries (no
longer supported by evidence) and contradictions. The LLM only JUDGES — the
apply step is deterministic code (`apply_knowledge_batch`), and it can only:

- add a refined rule and mark the merged ones superseded (never delete),
- mark an evidence-free/stale rule expired (superseded_by="expired:<run8>"),
- FLAG a contradiction for the human (needs_human) — never resolve one.

Since v0.7.63 the desk runs PROPOSE-ONLY by default
(`techniques.tip.knowledge_apply_enabled` False): merges/expiries become
receipts, only the protective flags land.

Scheduling (R63-03/04, v0.7.65): maintenance runs one bounded CYCLE at a
time. A cycle records the eligible scope set (plus the rulebook as the
pseudo-scope "rule") and per-scope progress; every tick audits PENDING work
only, up to `knowledge_audit_max_groups`; a failed scope is retried with
backoff (MAX_GROUP_ATTEMPTS, then set aside visibly) so it can never hold an
untouched scope out; the cycle completes when nothing is pending — and only
a completed cycle advances the maintenance watermark. Off-switch
`techniques.tip.rule_audit_enabled`. Fail-open like every analyst run: an
error changes nothing and is retried on the cycle's terms.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
from typing import Callable, Optional

from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

log = logging.getLogger("zargar.tip.rule_audit")
ET = ZoneInfo("America/New_York")

AUDIT_TIMEOUT_S = 90.0
MIN_RULES = 3          # nothing to consolidate below this — skip silently
MAX_GROUP_ATTEMPTS = 3          # per cycle; then the scope is set aside, visibly
BACKOFF_HOURS = (23, 47, 95)    # after attempt 1, 2, 3 (just under the daily tick)
MAX_TOKENS_CEILING = 8192       # the one doubled retry never exceeds this


class RuleMerge(BaseModel):
    new_rule: str = Field(description="The single refined rule replacing the merged ones "
                                      "— keep the WHY and cite the strongest evidence")
    supersedes: list[str] = Field(description="ids of the rules this replaces (>= 2, or 1 to rewrite)")
    why: str = Field(default="")


class RuleExpiry(BaseModel):
    id: str
    why: str = Field(default="", description="why the evidence no longer supports it")


class RuleContradiction(BaseModel):
    ids: list[str] = Field(description="the 2+ rule ids that pull in opposite directions")
    why: str = Field(default="")


class RuleAuditOpinion(BaseModel):
    merges: list[RuleMerge] = Field(default_factory=list)
    expires: list[RuleExpiry] = Field(default_factory=list)
    contradictions: list[RuleContradiction] = Field(default_factory=list)
    summary: str = Field(default="", description="2-3 sentences on the rulebook's state")


AUDIT_SYSTEM = """You are the tips desk trader auditing YOUR OWN RULEBOOK — the weekly \
consolidation that keeps it sharp. You are handed every live rule (with ids), your \
recent retros and lane grades (the evidence), and the flags below.

Judge the RULEBOOK, not the trades:
- MERGE near-duplicates into ONE refined rule that keeps the why and cites the \
strongest evidence. Merging one rule with itself (supersedes of length 1) means \
"rewrite it better".
- EXPIRE a rule the evidence no longer supports — rules marked [NO EVIDENCE CITED] \
are the first candidates unless a retro clearly backs them.
- A CONTRADICTION (two rules pulling opposite ways) is NOT yours to resolve: list it \
and the human decides. Never merge or expire your way around a real disagreement.
- Fewer, sharper rules beat many vague ones. It is fine to change nothing.

Reply with ONLY one JSON object matching this schema — no prose, no markdown fences:
"""


class JudgeError(Exception):
    """A judge call that produced no usable opinion — carries the PAID call
    records made so far (R63-05: usage is evidence even when the reply was
    unusable)."""

    def __init__(self, message: str, calls: list[dict]):
        super().__init__(message)
        self.calls = list(calls)


class JudgeCancelled(asyncio.CancelledError):
    """Cancellation (shutdown/restart) mid-judgement — still a CancelledError
    for the event loop, but it carries the call records made before the
    cancel (KFIN-02: a cancelled second attempt preserves the first completed
    call's evidence)."""

    def __init__(self, calls: list[dict]):
        super().__init__("judge cancelled")
        self.calls = list(calls)


async def _judge(client, *, model: str, system: str, header: str, cap: int,
                 max_tokens_ceiling: int = MAX_TOKENS_CEILING) -> tuple[RuleAuditOpinion, list[dict]]:
    """One audit judgement, measured (KB-08): returns the parsed opinion and
    the per-call usage list [{inputTokens, outputTokens, stopReason,
    latencyMs, maxTokens}]. A reply that does not validate earns ONE retry —
    at double the cap when the stop reason was `max_tokens` (the first live
    rule audit came back empty: prose ran past the 2,000-token cap before any
    object), at the same cap otherwise. EVERY request — the first included —
    is clamped to `max_tokens_ceiling` (KFIN-02: a configured 20,000 cap once
    reached the provider ahead of the retry logic). Every failure raises
    JudgeError WITH the calls made, so a failed audit still records what it
    paid for; a cancellation raises JudgeCancelled with the same records."""
    from ...research import llm_stats
    calls: list[dict] = []
    last_error: str = ""
    ceiling = max(1, int(max_tokens_ceiling))
    cap = min(max(1, int(cap)), ceiling)
    for attempt in (1, 2):
        try:
            with llm_stats.timed() as _t:
                resp = await asyncio.wait_for(
                    client.messages.create(model=model, max_tokens=cap, system=system,
                                           messages=[{"role": "user", "content": header}]),
                    timeout=AUDIT_TIMEOUT_S)
        except asyncio.CancelledError as exc:          # shutdown/restart mid-call
            calls.append({"attempt": attempt, "maxTokens": cap, "error": "cancelled"})
            raise JudgeCancelled(calls) from exc
        except Exception as exc:                       # timeout / provider error
            calls.append({"attempt": attempt, "maxTokens": cap, "error": str(exc)[:160]})
            raise JudgeError(f"judge call failed: {exc}", calls) from exc
        llm_stats.record_response("audit", resp, model=model, latency_ms=_t.ms, retried=attempt > 1)
        u = getattr(resp, "usage", None)
        stop = getattr(resp, "stop_reason", None)
        calls.append({"attempt": attempt,
                      "inputTokens": int(getattr(u, "input_tokens", 0) or 0) if u else None,
                      "outputTokens": int(getattr(u, "output_tokens", 0) or 0) if u else None,
                      "stopReason": str(stop) if stop else None, "latencyMs": round(_t.ms, 1),
                      "maxTokens": cap})
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        i, j = text.find("{"), text.rfind("}")
        try:
            return RuleAuditOpinion.model_validate_json(text[i:j + 1]), calls
        except Exception as exc:
            truncated = str(stop) == "max_tokens"
            last_error = ("truncated at max_tokens, no complete JSON object" if truncated
                          else f"invalid JSON: {str(exc)[:120]}")
            calls[-1]["parseError"] = last_error
            if attempt == 2:
                break
            if truncated and cap < ceiling:
                cap = min(cap * 2, ceiling)              # bounded repair: ONE doubled retry
    raise JudgeError(last_error or "no usable judgement", calls)


def _apply_mode(settings) -> str:
    return "apply" if bool(settings.get("techniques.tip.knowledge_apply_enabled", False)) else "propose"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Cycle + per-scope progress (R63-03/04). The in-memory state lives ON the
# engine (one per process/engine, test rigs get their own) and is persisted
# in `tip_knowledge_cycles` (the cycle) and `tip_knowledge_batches` receipts
# (one per attempted scope, status failed|proposed|applied). The module
# names below are kept for reviewer fixtures that patch them; decisions are
# made from the engine-held state.
_AUDIT_CURSOR: dict = {}
_CURSOR_HYDRATED = False


def _state(eng) -> dict:
    st = getattr(eng, "_tip_audit_state", None)
    if st is None:
        st = {"hydrated": False, "cycle": None, "scopes": {}}
        try:
            setattr(eng, "_tip_audit_state", st)
        except Exception:
            pass
    return st


async def _hydrate(eng) -> dict:
    """Load the open cycle + per-scope attempt/success history once per
    engine; unavailable storage (offline rigs) just means an empty state."""
    st = _state(eng)
    if st["hydrated"]:
        return st
    st["hydrated"] = True
    try:
        from sqlalchemy import select as _sel
        from ...models import TipKnowledgeBatch, TipKnowledgeCycle
        async with eng.sf() as session:
            row = (await session.execute(
                _sel(TipKnowledgeCycle).where(TipKnowledgeCycle.status == "open")
                .order_by(TipKnowledgeCycle.started_at.desc()).limit(1))).scalars().first()
            if row is not None:
                st["cycle"] = {"id": row.id, "startedAt": row.started_at.isoformat(),
                               "status": row.status, "completedAt": None,
                               "eligible": dict(row.eligible or {}),
                               "progress": dict(row.progress or {}),
                               "discovered": list(row.discovered or [])}
            receipts = (await session.execute(
                _sel(TipKnowledgeBatch.scope, TipKnowledgeBatch.status, TipKnowledgeBatch.created_at)
                .order_by(TipKnowledgeBatch.created_at.asc()).limit(5000))).all()
        for scope, status, ts in receipts:
            cur = st["scopes"].setdefault(scope, {"attempt": None, "success": None, "failures": 0})
            cur["attempt"] = ts.isoformat()
            if status == "failed":
                cur["failures"] += 1
            else:
                cur["success"] = ts.isoformat()
                cur["failures"] = 0
    except Exception:
        log.debug("audit state hydration unavailable (offline?)", exc_info=True)
    return st


async def _save_cycle(eng, cycle: dict) -> None:
    try:
        from ...models import TipKnowledgeCycle
        async with eng.sf() as session:
            await session.merge(TipKnowledgeCycle(
                id=cycle["id"], started_at=dt.datetime.fromisoformat(cycle["startedAt"]),
                completed_at=(dt.datetime.fromisoformat(cycle["completedAt"])
                              if cycle.get("completedAt") else None),
                status=cycle["status"], eligible=cycle["eligible"],
                progress=cycle["progress"], discovered=cycle.get("discovered") or []))
            await session.commit()
    except Exception:
        log.debug("cycle persistence unavailable (offline?)", exc_info=True)


async def _record_failed_group(eng, run_id: str, scope: str, error: str, calls: list[dict],
                               *, batch_id: str | None = None, chunk: dict | None = None) -> None:
    """R63-03: failed work is journaled explicitly — a receipt row with
    status 'failed' (same id shape as an applied batch) so restarts see the
    attempt and the paid calls behind it. With chunks (KFIN-02) the receipt
    is per chunk and names the chunk's input manifest."""
    try:
        from ...models import TipKnowledgeBatch
        async with eng.sf() as session:
            session.add(TipKnowledgeBatch(
                id=batch_id or f"{run_id}:{scope}", run_id=run_id, scope=scope[:160],
                status="failed", payload_hash="",
                proposal={"error": (error or "")[:300], "usage": calls,
                          **({"chunk": chunk} if chunk else {})},
                applied={}))
            await session.commit()
    except Exception:
        log.debug("failed-group receipt unavailable (offline?)", exc_info=True)


def _reconcile_cycle(cycle: dict, eligible: dict[str, int], now: str) -> None:
    """Eligibility can change mid-cycle: a scope reaching the floor joins the
    cycle as explicit follow-up work (`discovered`); a scope falling below it
    is dropped from pending. Neither makes completion impossible."""
    prog = cycle["progress"]
    for sc, n in eligible.items():
        if sc not in cycle["eligible"]:
            cycle["eligible"][sc] = {"notes": int(n), "addedAt": now}
            if prog:
                cycle.setdefault("discovered", []).append({"scope": sc, "at": now})
        p = prog.get(sc)
        if p is None:
            prog[sc] = {"status": "pending", "attempts": 0, "lastAttempt": None,
                        "retryAfter": None, "batchId": None, "error": None}
        elif p["status"] == "dropped":
            p["status"] = "pending"
    for sc, p in prog.items():
        if sc != "rule" and sc not in eligible and p["status"] == "pending":
            p["status"] = "dropped"


async def _cycle_for(eng, eligible: dict[str, int]) -> dict:
    """The open cycle (reconciled with today's eligibility) or a new one."""
    from ...domain import new_id
    st = await _hydrate(eng)
    cycle = st.get("cycle")
    now = _now_iso()
    if cycle is None or cycle.get("status") != "open":
        cycle = {"id": new_id(), "startedAt": now, "status": "open", "completedAt": None,
                 "eligible": {}, "progress": {}, "discovered": []}
        st["cycle"] = cycle
    _reconcile_cycle(cycle, eligible, now)
    return cycle


def _pending_scopes(cycle: dict, now: str) -> tuple[list[str], list[str]]:
    """(ready, in_backoff): pending group scopes ordered untouched-first, then
    oldest attempt — a repeatedly failing scope can never starve an
    untouched one (R63-03)."""
    ready, backoff = [], []
    for sc, p in cycle["progress"].items():
        if sc == "rule" or p.get("status") != "pending":
            continue
        if p.get("retryAfter") and p["retryAfter"] > now:
            backoff.append(sc)
        else:
            ready.append(sc)
    ready.sort(key=lambda sc: (int(cycle["progress"][sc].get("attempts") or 0),
                               cycle["progress"][sc].get("lastAttempt") or "", sc))
    return ready, sorted(backoff)


def _mark(cycle: dict, scope: str, *, ok: bool, now: str, error: str | None = None,
          batch_id: str | None = None, revisions_hash: str | None = None) -> None:
    p = cycle["progress"].setdefault(scope, {"status": "pending", "attempts": 0, "lastAttempt": None,
                                             "retryAfter": None, "batchId": None, "error": None})
    p["attempts"] = int(p.get("attempts") or 0) + 1
    p["lastAttempt"] = now
    if ok:
        p.update(status="done", retryAfter=None, batchId=batch_id, error=None,
                 revisionsHash=revisions_hash)
        return
    p["error"] = (error or "")[:200]
    if p["attempts"] >= MAX_GROUP_ATTEMPTS:
        p.update(status="failed", retryAfter=None)      # set aside for this cycle, visibly
    else:
        hours = BACKOFF_HOURS[min(p["attempts"] - 1, len(BACKOFF_HOURS) - 1)]
        p["retryAfter"] = (dt.datetime.fromisoformat(now) + dt.timedelta(hours=hours)).isoformat()


def _cycle_summary(cycle: dict) -> dict:
    prog = cycle.get("progress") or {}
    by: dict[str, list[str]] = {"done": [], "pending": [], "failed": [], "dropped": []}
    chunks: dict[str, dict] = {}
    for sc, p in sorted(prog.items()):
        by.setdefault(p.get("status", "pending"), []).append(sc)
        if p.get("chunks"):
            chunks[sc] = _chunk_summary(p)             # visible overflow + per-chunk progress
    return {"cycleId": cycle["id"], "startedAt": cycle["startedAt"], "status": cycle["status"],
            **by, "discovered": [d["scope"] for d in (cycle.get("discovered") or [])],
            "chunks": chunks,
            "overflow": sorted(sc for sc, c in chunks.items() if c.get("overflow"))}


def _revisions_hash(notes: list[dict]) -> str:
    key = json.dumps(sorted((n["id"], int(n.get("revisionNo") or 1)) for n in notes))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Bounded, resumable judgments (KFIN-02). A scope's notes are split into
# deterministic NOTE-BOUNDARY chunks (ordered by note id; a chunk closes at
# `audit_chunk_notes` notes or `audit_chunk_chars` characters), each with a
# complete input manifest [(note id, revision)] and a stable chunk id = the
# hash of that ordered manifest. Progress is persisted per chunk on the
# cycle's `progress[scope]` (tip_knowledge_cycles.progress), so a restart
# resumes the unfinished chunks; a note added / removed / revised changes
# the affected chunk's id, which invalidates (visibly) and re-plans it
# instead of reusing a stale judgment. Each chunk is judged and
# applied/proposed ONCE (batch id per chunk). A merge/expiry/contradiction
# that reaches across chunks is never applied: it is recorded as a separate
# propose-only batch carrying the referenced ids, their revisions and their
# owning chunks.
CHUNK_NOTES_DEFAULT = 40
CHUNK_CHARS_DEFAULT = 60_000
MAX_CHUNKS_PER_RUN_DEFAULT = 24


def _chunk_settings(s) -> tuple[int, int, int]:
    def _int(key: str, default: int) -> int:
        try:
            v = int(s.get(key, default) or default)
        except Exception:
            v = default
        return max(1, v)
    return (_int("techniques.tip.audit_chunk_notes", CHUNK_NOTES_DEFAULT),
            _int("techniques.tip.audit_chunk_chars", CHUNK_CHARS_DEFAULT),
            _int("techniques.tip.knowledge_audit_max_chunks", MAX_CHUNKS_PER_RUN_DEFAULT))


def _plan_chunks(notes: list[dict], *, max_notes: int, max_chars: int) -> list[dict]:
    """Deterministic note-boundary chunks: [{chunkId, index, notes, manifest,
    chars}]. Same notes at the same revisions -> the same chunk ids; a
    single note larger than `max_chars` gets a chunk of its own."""
    ordered = sorted(notes, key=lambda n: str(n.get("id")))
    groups: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    for n in ordered:
        size = len(str(n.get("text") or "")) + 96          # id/author/date framing
        if cur and (len(cur) >= max_notes or cur_chars + size > max_chars):
            groups.append(cur)
            cur, cur_chars = [], 0
        cur.append(n)
        cur_chars += size
    if cur:
        groups.append(cur)
    return [{"chunkId": _revisions_hash(g), "index": i, "notes": g,
             "manifest": [[n["id"], int(n.get("revisionNo") or 1)] for n in g],
             "chars": sum(len(str(n.get("text") or "")) for n in g)}
            for i, g in enumerate(groups)]


def _batch_id(run_id: str, scope: str, chunk_id: str, n_chunks: int) -> str:
    """One batch per chunk. A scope that fits in one chunk keeps the
    historical `<run>:<scope>` id shape."""
    return f"{run_id}:{scope}" if n_chunks <= 1 else f"{run_id}:{scope}:{chunk_id}"


def _split_cross_chunk(op: RuleAuditOpinion, chunk_ids: set[str],
                       scope_revisions: dict[str, int], owner: dict[str, str]) -> tuple[dict, dict]:
    """Partition a chunk's judgment: `local` references only this chunk's
    notes (applied per mode); `cross` references a note LIVE in the scope but
    outside the chunk (proposal only, with complete references). An id that
    is live nowhere stays local so apply rejects it whole, on the record."""
    local = {"merges": [], "expires": [], "contradictions": []}
    cross = {"merges": [], "expires": [], "contradictions": [], "refs": []}

    def _route(kind: str, item, ids: list[str], **extra) -> None:
        outside = [i for i in ids if i not in chunk_ids]
        if outside and all(i in scope_revisions for i in ids):
            cross[kind].append(item)
            cross["refs"].append({"kind": kind[:-1] if kind != "contradictions" else "contradiction",
                                  "ids": list(ids),
                                  "revisions": {i: scope_revisions[i] for i in ids},
                                  "chunks": {i: owner.get(i) for i in ids},
                                  "outsideChunk": outside, **extra})
        else:
            local[kind].append(item)

    for m in op.merges:
        _route("merges", m, list(m.supersedes or []), text=m.new_rule, why=m.why)
    for e in op.expires:
        _route("expires", e, [e.id], why=e.why)
    for c in op.contradictions:
        _route("contradictions", c, list(c.ids or []), why=c.why)
    return local, cross


def _merge_applied(applied: dict, got: dict) -> None:
    got = got or {}
    applied["merged"] += int(got.get("merged", 0) or 0)
    applied["expired"] += int(got.get("expired", 0) or 0)
    applied["proposedMerges"] = int(applied.get("proposedMerges", 0)) + int(got.get("proposedMerges", 0) or 0)
    applied["proposedExpires"] = int(applied.get("proposedExpires", 0)) + int(got.get("proposedExpires", 0) or 0)
    applied.setdefault("newRules", []).extend(got.get("newRules", []) or [])
    applied.setdefault("newNotes", []).extend(got.get("newNotes", []) or [])
    for i in got.get("flagged", []) or []:
        if i not in applied.setdefault("flagged", []):
            applied["flagged"].append(i)
    applied.setdefault("rejected", []).extend(got.get("rejected", []) or [])
    if got.get("alreadyApplied"):
        applied["alreadyApplied"] = True


def _chunk_summary(prog: dict) -> dict:
    chunks = prog.get("chunks") or {}
    by = {"done": 0, "pending": 0, "failed": 0}
    for e in chunks.values():
        by[e.get("status") if e.get("status") in by else "pending"] += 1
    m = prog.get("manifest") or {}
    return {"planned": len(chunks), **by, "notes": m.get("notes"),
            "overflow": bool(m.get("overflow")), "invalidated": len(prog.get("invalidated") or [])}


async def _audit_scope(eng, client, *, model: str, scope: str, notes: list[dict], system: str,
                       header_for: Callable[[list[dict], int, int], str], prog: dict,
                       save, run_id: str, mode: str, cap: int, budget: dict, author: str,
                       usage_all: list[dict], applied: dict, chunk_cfg: tuple[int, int, int]) -> str:
    """Judge one scope through bounded chunks, resuming what an earlier run
    already finished. Returns 'done' (every chunk done), 'failed' (a chunk
    failed this visit — the scope backs off on the cycle's terms, done chunks
    stay done) or 'deferred' (the run's chunk budget ran out — pending chunks
    are visible and resume next tick). Cancellation persists the chunk's
    state (with the calls already paid for) and propagates as
    JudgeCancelled."""
    svc = eng.signals_service
    max_notes, max_chars, _ = chunk_cfg
    chunks = _plan_chunks(notes, max_notes=max_notes, max_chars=max_chars)
    now = _now_iso()
    known = dict(prog.get("chunks") or {})
    planned = {c["chunkId"] for c in chunks}
    invalidated = list(prog.get("invalidated") or [])
    for cid, entry in known.items():
        if cid not in planned:
            invalidated.append({"chunkId": cid, "index": entry.get("index"),
                                "status": entry.get("status"), "batchId": entry.get("batchId"),
                                "at": now, "reason": "inputs changed (note added/removed/revised)"})
    prog["invalidated"] = invalidated[-50:]
    prog["chunks"] = {
        c["chunkId"]: {**(known.get(c["chunkId"]) or {"status": "pending", "attempts": 0,
                                                       "batchId": None, "error": None, "at": None}),
                       "index": c["index"], "notes": len(c["notes"]), "chars": c["chars"],
                       "manifest": c["manifest"]}
        for c in chunks}
    prog["manifest"] = {"revisionsHash": _revisions_hash(notes), "notes": len(notes),
                        "chunks": len(chunks), "chunkNotes": max_notes, "chunkChars": max_chars,
                        "chunkIds": [c["chunkId"] for c in chunks], "plannedAt": now,
                        "overflow": len(chunks) > 1}
    scope_revisions = {n["id"]: int(n.get("revisionNo") or 1) for n in notes}
    owner = {n["id"]: c["chunkId"] for c in chunks for n in c["notes"]}
    failed_any = deferred = False
    for c in chunks:
        cid = c["chunkId"]
        entry = prog["chunks"][cid]
        if entry.get("status") == "done":
            continue                                   # judged + applied/proposed once already
        if budget["chunks"] <= 0:
            deferred = True
            break
        budget["chunks"] -= 1
        bid = _batch_id(run_id, scope, cid, len(chunks))
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        entry["at"] = now
        chunk_meta = {"chunkId": cid, "index": c["index"], "of": len(chunks),
                      "notes": len(c["notes"]), "manifest": c["manifest"]}

        async def _fail(error: str, calls: list[dict]) -> None:
            usage_all.append({"scope": scope, "chunkId": cid, "error": error[:160]})
            entry.update(status="failed", error=error[:200], batchId=None)
            await _record_failed_group(eng, run_id, scope, error, calls, batch_id=bid, chunk=chunk_meta)
            if save is not None:
                await save()

        try:
            op, calls = await _judge(client, model=model, system=system,
                                     header=header_for(c["notes"], c["index"], len(chunks)), cap=cap)
        except asyncio.CancelledError as exc:
            calls = list(getattr(exc, "calls", None) or [])
            usage_all.extend({"scope": scope, "chunkId": cid, **x} for x in calls)
            await _fail("cancelled (shutdown/restart)", calls)
            raise
        except Exception as exc:
            calls = list(getattr(exc, "calls", None) or [])
            usage_all.extend({"scope": scope, "chunkId": cid, **x} for x in calls)
            log.warning("knowledge audit failed for %s chunk %s: %s", scope, cid, exc)
            await _fail(str(exc), calls)
            failed_any = True
            continue
        usage_all.extend({"scope": scope, "chunkId": cid, **x} for x in calls)
        chunk_ids = {n["id"] for n in c["notes"]}
        local, cross = _split_cross_chunk(op, chunk_ids, scope_revisions, owner)
        try:
            got = await svc.apply_knowledge_batch(
                scope=scope, merges=list(local["merges"]), expires=list(local["expires"]),
                contradictions=list(local["contradictions"]), author=author, run_id=run_id,
                live_ids=chunk_ids, batch_id=bid,
                expected_revisions={i: scope_revisions[i] for i in chunk_ids}, mode=mode)
            xgot = None
            if cross["refs"]:
                # never applied, whatever the mode: the judge saw only this
                # chunk; the human sees the complete references
                xgot = await svc.apply_knowledge_batch(
                    scope=scope, merges=list(cross["merges"]), expires=list(cross["expires"]),
                    contradictions=list(cross["contradictions"]), author=author, run_id=run_id,
                    live_ids=set(scope_revisions), batch_id=f"{bid}:xchunk",
                    expected_revisions=dict(scope_revisions), mode="propose")
        except Exception as exc:
            log.warning("knowledge audit apply aborted for %s chunk %s: %s", scope, cid, exc)
            await _fail(f"apply aborted: {exc}", calls)
            failed_any = True
            continue
        entry.update(status="done", batchId=bid, error=None, summary=(op.summary or "")[:300])
        _merge_applied(applied, got or {})
        if cross["refs"]:
            xrec = {"scope": scope, "chunkId": cid, "batchId": f"{bid}:xchunk",
                    "refs": cross["refs"], "mode": "propose",
                    "proposedMerges": int((xgot or {}).get("proposedMerges", 0) or 0),
                    "proposedExpires": int((xgot or {}).get("proposedExpires", 0) or 0),
                    "flagged": list((xgot or {}).get("flagged", []) or []),
                    "rejected": list((xgot or {}).get("rejected", []) or [])}
            entry["crossChunk"] = xrec
            applied.setdefault("crossChunk", []).append(xrec)
            for i in xrec["flagged"]:
                if i not in applied.setdefault("flagged", []):
                    applied["flagged"].append(i)
        if save is not None:
            await save()
    if failed_any:
        return "failed"
    if deferred:
        return "deferred"
    return "done"


AUDITABLE_PREFIXES = ("ticker:", "source:")


async def _eligible_groups(eng) -> dict[str, int]:
    counts = await eng.signals_service.note_scope_counts(prefixes=AUDITABLE_PREFIXES, include_general=True)
    return {sc: int(n) for sc, n in counts.items() if int(n) >= MIN_RULES}


# ---------------------------------------------------------------------------
async def run_rule_audit(eng, *, client=None, report: dict | None = None,
                         cycle: dict | None = None) -> dict | None:
    """One rulebook audit: read -> judge (LLM) -> apply (deterministic, ONE
    transaction, conflict-locked — KB-02; propose-only by default) -> journal.
    Returns the applied summary, or None (disabled / too few rules / failed /
    already covered this cycle); `report`, when given, receives {status:
    skipped|failed|done, reason} so the maintenance job can tell a failure
    from a quiet skip (KB-01). With a `cycle`, the rulebook is the
    pseudo-scope "rule": audited once per cycle, retried with backoff."""
    from ...domain import new_id
    from ...models import Event, TipAnalystRun

    rep = report if report is not None else {}
    s = eng.settings
    if not bool(s.get("techniques.tip.rule_audit_enabled", True)):
        rep.update(status="skipped", reason="disabled")
        return None
    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        rep.update(status="skipped", reason="no api key")
        return None
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    model = str(s.get("techniques.tip.analyst_model") or "") or eng.config.extraction_model

    svc = eng.signals_service
    rules = await svc.tip_notes(["rule"], limit=5000)         # EVERY live rule (KB-04)
    if len(rules) < MIN_RULES:
        log.info("rule audit: only %d live rule(s) — nothing to consolidate", len(rules))
        rep.update(status="skipped", reason=f"{len(rules)} live rules")
        return None
    now_iso = _now_iso()
    if cycle is not None:
        cycle["eligible"].setdefault("rule", {"notes": len(rules), "addedAt": now_iso})
        p = cycle["progress"].setdefault("rule", {"status": "pending", "attempts": 0, "lastAttempt": None,
                                                  "retryAfter": None, "batchId": None, "error": None})
        if p["status"] == "done":
            rep.update(status="skipped", reason="rulebook audited this cycle")
            return None
        if p["status"] == "failed":
            rep.update(status="skipped", reason=f"rulebook audit set aside this cycle after {p['attempts']} failure(s)")
            return None
        if p.get("retryAfter") and p["retryAfter"] > now_iso:
            rep.update(status="skipped", reason=f"rulebook retry after {p['retryAfter'][:16]}")
            return None

    # evidence pre-pass (A8.4): a rule should cite a position/run/date
    def cited(r: dict) -> bool:
        t = r["text"].lower()
        return any(k in t for k in ("position", "run ", "run:", "20", "retro", "lane", "#"))

    def rules_text(subset: list[dict]) -> str:
        return "\n".join(
            f"- [{r['id']}] {r['text']} (by {r['author']}, {(r['createdAt'] or '')[:10]})"
            + ("" if cited(r) else "  [NO EVIDENCE CITED]")
            + ("  [DISPUTED — unresolved by the human; never merge or expire]" if r.get("needsHuman") else "")
            for r in subset)

    # the evidence: recent retros + lane grades
    from sqlalchemy import select as _sel
    async with eng.sf() as session:
        retros = (await session.execute(
            _sel(TipAnalystRun).where(TipAnalystRun.kind == "retro",
                                      TipAnalystRun.status == "done")
            .order_by(TipAnalystRun.created_at.desc()).limit(10))).scalars().all()
        lanes = (await session.execute(
            _sel(Event.payload).where(Event.type == "TipLaneGraded")
            .order_by(Event.id.desc()).limit(15))).scalars().all()
    retro_txt = "\n".join(
        f"- {r.ticker}: {((r.opinion or {}).get('grade') or '?')} — "
        f"{((r.opinion or {}).get('whatDidnt') or (r.opinion or {}).get('whatWorked') or '')[:160]}"
        for r in retros) or "(no retros yet)"
    lane_txt = "\n".join(
        f"- {(p or {}).get('ticker')}: chose {(p or {}).get('lane')} -> {(p or {}).get('verdict')}"
        for p in lanes) or "(no lane grades yet)"

    run_id = new_id()
    async with eng.sf() as session:
        session.add(TipAnalystRun(
            id=run_id, signal_id=None, ticker="RULES", source="rule-audit",
            status="running", kind="rule_audit", model=model, tools=[],
            tip={"liveRules": len(rules), "cycleId": cycle["id"] if cycle else None}))
        await session.commit()

    def header_for(subset: list[dict], index: int, of: int) -> str:
        part = ("" if of <= 1 else
                f" — CHUNK {index + 1} of {of}: you see only these {len(subset)} rules; "
                "judge them on their own, never reference a rule you cannot see")
        return (f"Today (ET): {dt.datetime.now(ET):%Y-%m-%d}\n"
                f"YOUR LIVE RULES ({len(rules)}{part}):\n{rules_text(subset)}\n\n"
                f"RECENT RETROS:\n{retro_txt}\n\nLANE GRADES:\n{lane_txt}")

    system = AUDIT_SYSTEM + json.dumps(RuleAuditOpinion.model_json_schema(),
                                       separators=(",", ":"))
    cap = int(s.get("techniques.tip.audit_max_output_tokens", 3000) or 3000)
    chunk_cfg = _chunk_settings(s)
    mode = _apply_mode(s)
    # ---- judge (bounded chunks, resumable) + deterministic apply (KB-02) ------
    prog = (cycle["progress"].setdefault("rule", {"status": "pending", "attempts": 0, "lastAttempt": None,
                                                  "retryAfter": None, "batchId": None, "error": None})
            if cycle is not None else {})
    save = (lambda: _save_cycle(eng, cycle)) if cycle is not None else None
    usage_all: list[dict] = []
    applied: dict = {"merged": 0, "expired": 0, "contradictions": 0, "newRules": [],
                     "newNotes": [], "flagged": [], "rejected": [], "mode": mode,
                     "proposedMerges": 0, "proposedExpires": 0, "crossChunk": []}
    budget = {"chunks": chunk_cfg[2]}
    try:
        outcome = await _audit_scope(
            eng, client, model=model, scope="rule", notes=rules, system=system,
            header_for=header_for, prog=prog, save=save, run_id=run_id, mode=mode, cap=cap,
            budget=budget, author=f"rule-audit:{run_id[:8]}", usage_all=usage_all,
            applied=applied, chunk_cfg=chunk_cfg)
    except asyncio.CancelledError:
        # terminal on the record first (usage kept), then propagate
        await _finish(eng, run_id, status="failed",
                      opinion={"error": "cancelled: shutdown/restart", "usage": usage_all,
                               "chunks": _chunk_summary(prog)})
        rep.update(status="failed", reason="cancelled")
        raise
    chunks = _chunk_summary(prog)
    if outcome == "failed":
        err = "; ".join(e.get("error") or "" for e in (prog.get("chunks") or {}).values()
                        if e.get("status") == "failed") or "judge failed"
        log.warning("rule audit failed: %s", err)
        await _finish(eng, run_id, status="failed",
                      opinion={"error": err[:300], "usage": usage_all, "chunks": chunks})   # KB-08: failures keep usage
        rep.update(status="failed", reason=err[:200])
        if cycle is not None:
            _mark(cycle, "rule", ok=False, now=now_iso, error=err)
            await _save_cycle(eng, cycle)
        return None
    if outcome == "deferred":
        pending = chunks["pending"]
        await _finish(eng, run_id, status="partial",
                      opinion={"verdict": "audit", "usage": usage_all, "chunks": chunks,
                               "rationale": f"rulebook audit: {pending} chunk(s) deferred to the next tick"})
        rep.update(status="partial", reason=f"rulebook: {pending} chunk(s) deferred (chunk budget)")
        if cycle is not None:
            prog["lastAttempt"] = now_iso              # progress, not an attempt
            await _save_cycle(eng, cycle)
        return None
    applied["contradictions"] = len(applied["flagged"])
    summary = " ".join(e.get("summary") or "" for e in sorted(
        (prog.get("chunks") or {}).values(), key=lambda e: e.get("index") or 0)).strip()
    flagged = list(applied.get("flagged") or [])
    payload = {"runId": run_id, **{k: v for k, v in applied.items() if k != "flagged"},
               "flagged": flagged, "summary": summary, "usage": usage_all, "mode": mode,
               "chunks": chunks, "cycleId": cycle["id"] if cycle else None}
    rep.update(status="done", reason="")
    if cycle is not None:
        _mark(cycle, "rule", ok=True, now=now_iso,
              batch_id=(prog.get("chunks") or {}).get(prog["manifest"]["chunkIds"][-1], {}).get("batchId"),
              revisions_hash=_revisions_hash(rules))
        await _save_cycle(eng, cycle)
    await _finish(eng, run_id, status="done",
                  opinion={"verdict": "audit", **payload,
                           "rationale": summary or "rulebook audited"})
    log.info("rule audit %s: merged %d, expired %d, flagged %d (%s)",
             run_id[:8], applied["merged"], applied["expired"], applied["contradictions"], mode)
    return payload


async def run_knowledge_audit(eng, *, client=None, report: dict | None = None,
                              cycle: dict | None = None) -> dict | None:
    """KNOWLEDGE plan B4: the weekly audit widened beyond rules. Every
    `ticker:*` / `source:*` / `general` group holding >= MIN_RULES ACTIVE notes
    gets the same judge -> deterministic-apply pass (merge near-duplicates,
    expire the unsupported, flag contradictions for the human). `daily:*` notes
    expire on their own TTL and `experiment:*`/`signal:*` are never audited.
    Same contract as run_rule_audit: fail-open, one run row, journaled.

    R63-03/04: work is drawn from the CYCLE's pending scopes only (untouched
    first, then oldest attempt; a scope in retry backoff waits), at most
    `knowledge_audit_max_groups` per run. The report is `done` when the
    cycle has no pending work left, `partial` while it does."""
    from ...domain import new_id
    from ...models import TipAnalystRun

    rep = report if report is not None else {}
    s = eng.settings
    if not bool(s.get("techniques.tip.rule_audit_enabled", True)):
        rep.update(status="skipped", reason="disabled")
        return None
    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        rep.update(status="skipped", reason="no api key")
        return None
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    model = str(s.get("techniques.tip.analyst_model") or "") or eng.config.extraction_model

    svc = eng.signals_service
    # COMPLETE traversal (KB-04): eligible groups come from a whole-store count,
    # each group's notes are fetched in full; the cycle bounds the paid work
    eligible = await _eligible_groups(eng)
    if not eligible and cycle is None:
        rep.update(status="skipped", reason="no eligible groups")
        return None
    now_iso = _now_iso()
    if cycle is None:
        cycle = await _cycle_for(eng, eligible)
    else:
        _reconcile_cycle(cycle, eligible, now_iso)
    max_groups = int(s.get("techniques.tip.knowledge_audit_max_groups", 12) or 12)
    ready, backoff = _pending_scopes(cycle, now_iso)
    todo = ready[:max_groups]
    from ... import events as ev
    mode = _apply_mode(s)
    if not todo:
        rule_pending = cycle["progress"].get("rule", {}).get("status") == "pending"
        complete = not backoff and not rule_pending
        if complete and cycle["status"] == "open":
            cycle["status"] = "done"
            cycle["completedAt"] = now_iso
        await _save_cycle(eng, cycle)
        payload = {"kind": "knowledge", "groups": 0, "mode": mode, "usage": [],
                   "cycle": _cycle_summary(cycle), "groupsBackoff": backoff}
        if complete:
            rep.update(status="done", reason="cycle complete — nothing pending")
        else:
            rep.update(status="partial", reason=(f"{len(backoff)} group(s) in retry backoff"
                                                 if backoff else "rulebook audit pending"))
        await eng.journal.append(ev.TIP_RULE_AUDITED, payload,
                                 aggregate_type="technique", aggregate_id="tip")
        return payload
    groups: dict[str, list[dict]] = {}
    for sc in todo:
        groups[sc] = await svc.tip_notes([sc], limit=5000)

    run_id = new_id()
    async with eng.sf() as session:
        session.add(TipAnalystRun(
            id=run_id, signal_id=None, ticker="NOTES", source="rule-audit",
            status="running", kind="rule_audit", model=model, tools=[],
            tip={"groups": sorted(groups), "notes": sum(len(v) for v in groups.values()),
                 "cycleId": cycle["id"]}))
        await session.commit()

    applied = {"groups": 0, "merged": 0, "expired": 0, "contradictions": 0,
               "newRules": [], "newNotes": [], "flagged": [], "rejected": [],
               "proposedMerges": 0, "proposedExpires": 0, "crossChunk": [],
               "groupsEligible": len(eligible), "groupsFailed": [], "groupsChunkDeferred": [],
               "chunks": {}}
    usage_all: list[dict] = []
    cap = int(s.get("techniques.tip.audit_max_output_tokens", 3000) or 3000)
    chunk_cfg = _chunk_settings(s)
    budget = {"chunks": chunk_cfg[2]}                     # paid calls per run, across scopes
    system = AUDIT_SYSTEM + json.dumps(RuleAuditOpinion.model_json_schema(), separators=(",", ":"))

    def _header_for(scope: str):
        def header_for(subset: list[dict], index: int, of: int) -> str:
            notes_txt = "\n".join(
                f"- [{n['id']}] {n['text']} (by {n['author']}, {(n['createdAt'] or '')[:10]}, "
                f"cited {n.get('citedCount', 0)}x)"
                + ("  [DISPUTED — unresolved by the human; never merge or expire]" if n.get("needsHuman") else "")
                for n in subset)
            part = ("" if of <= 1 else
                    f" — CHUNK {index + 1} of {of}: you see only these {len(subset)} notes; "
                    "judge them on their own, never reference a note you cannot see")
            return (f"These are the desk's ACTIVE knowledge notes in scope '{scope}'{part} "
                    f"(not trading rules — market/source knowledge):\n{notes_txt}")
        return header_for

    for scope, notes in groups.items():
        if budget["chunks"] <= 0:
            applied["groupsChunkDeferred"].append(scope)  # untouched this run — visible
            continue
        attempt_at = _now_iso()
        prog = cycle["progress"].setdefault(scope, {"status": "pending", "attempts": 0, "lastAttempt": None,
                                                    "retryAfter": None, "batchId": None, "error": None})
        try:
            outcome = await _audit_scope(
                eng, client, model=model, scope=scope, notes=notes, system=system,
                header_for=_header_for(scope), prog=prog, save=lambda: _save_cycle(eng, cycle),
                run_id=run_id, mode=mode, cap=cap, budget=budget,
                author=f"knowledge-audit:{run_id[:8]}", usage_all=usage_all, applied=applied,
                chunk_cfg=chunk_cfg)
        except asyncio.CancelledError:
            applied["chunks"][scope] = _chunk_summary(prog)
            await _finish(eng, run_id, status="failed",
                          opinion={"error": "cancelled: shutdown/restart", "usage": usage_all,
                                   "chunks": applied["chunks"]})
            rep.update(status="failed", reason="cancelled")
            raise
        applied["chunks"][scope] = _chunk_summary(prog)
        if outcome == "failed":
            err = "; ".join(e.get("error") or "" for e in (prog.get("chunks") or {}).values()
                            if e.get("status") == "failed") or "judge failed"
            applied["groupsFailed"].append(scope)      # visible, never silent
            _mark(cycle, scope, ok=False, now=attempt_at, error=err)
            await _save_cycle(eng, cycle)
            continue
        if outcome == "deferred":
            applied["groupsChunkDeferred"].append(scope)
            prog["lastAttempt"] = attempt_at            # progress made, not an attempt
            await _save_cycle(eng, cycle)
            continue
        _mark(cycle, scope, ok=True, now=attempt_at,
              batch_id=(prog.get("chunks") or {}).get(prog["manifest"]["chunkIds"][-1], {}).get("batchId"),
              revisions_hash=_revisions_hash(notes))
        await _save_cycle(eng, cycle)
        applied["groups"] += 1
    applied["contradictions"] = len(applied["flagged"])
    applied["mode"] = mode

    end_iso = _now_iso()
    ready2, backoff2 = _pending_scopes(cycle, end_iso)
    rule_pending = cycle["progress"].get("rule", {}).get("status") == "pending"
    complete = not ready2 and not backoff2 and not rule_pending
    if complete and cycle["status"] == "open":
        cycle["status"] = "done"
        cycle["completedAt"] = end_iso
    await _save_cycle(eng, cycle)
    applied["groupsDeferred"] = ready2
    applied["groupsBackoff"] = backoff2
    applied["groupsGivenUp"] = [sc for sc, p in cycle["progress"].items()
                                if sc != "rule" and p.get("status") == "failed"]
    partial = not complete
    if partial:
        bits = []
        if applied["groupsFailed"]:
            bits.append(f"failed {len(applied['groupsFailed'])}")
        if applied["groupsChunkDeferred"]:
            bits.append(f"chunk budget held {len(applied['groupsChunkDeferred'])}")
        if ready2:
            bits.append(f"deferred {len(ready2)}")
        if backoff2:
            bits.append(f"in backoff {len(backoff2)}")
        if rule_pending:
            bits.append("rulebook pending")
        rep.update(status="partial", reason=", ".join(bits) or "cycle open")
    else:
        rep.update(status="done", reason=("cycle complete"
                                          + (f"; {len(applied['groupsGivenUp'])} set aside" if applied["groupsGivenUp"] else "")))

    payload = {"runId": run_id, "kind": "knowledge", **applied, "usage": usage_all,
               "cycle": _cycle_summary(cycle)}
    await eng.journal.append(ev.TIP_RULE_AUDITED, payload,
                             aggregate_type="technique_run", aggregate_id=run_id)
    await _finish(eng, run_id, status=("partial" if applied["groupsFailed"] else "done"),   # the RUN's own outcome
                  opinion={"verdict": "audit", **payload,
                           "rationale": f"knowledge audit over {applied['groups']} scope group(s)"
                                        + (f"; {len(applied['groupsFailed'])} failed" if applied["groupsFailed"] else "")
                                        + ("; cycle complete" if complete else f"; {len(ready2) + len(backoff2)} pending")})
    log.info("knowledge audit %s: %d group(s), merged %d, expired %d, flagged %d; cycle %s",
             run_id[:8], applied["groups"], applied["merged"], applied["expired"],
             applied["contradictions"], "complete" if complete else "open")
    return payload


async def _finish(eng, run_id: str, *, status: str, opinion: dict) -> None:
    from ...models import TipAnalystRun
    import contextlib
    with contextlib.suppress(Exception):
        async with eng.sf() as session:
            row = await session.get(TipAnalystRun, run_id)
            if row is not None:
                row.status = status
                row.opinion = opinion
                row.finished_at = dt.datetime.now(dt.timezone.utc)      # EOD-08: terminal rows carry their end
                row.trace = list(row.trace or []) + [
                    {"seq": len(row.trace or []), "kind": "final",
                     "text": opinion.get("summary") or opinion.get("error") or status,
                     "at": dt.datetime.now(dt.timezone.utc).isoformat()}]
                await session.commit()


def audit_due_today(settings) -> bool:
    """The configured ET weekday (default Sat) — America/New_York, not a
    fixed UTC offset (KB-01)."""
    want = str(settings.get("techniques.tip.rule_audit_day", "Sat"))[:3].lower()
    return dt.datetime.now(ET).strftime("%a").lower() == want


CATCHUP_DAYS = 8       # a missed Saturday runs on the next tick-able day


async def _last_completion(eng) -> dt.datetime | None:
    """The newest journaled maintenance completion — GENUINE completion only
    ('done' = the cycle covered everything); a partial pass never advances
    the watermark (KB-01, R63-04)."""
    try:
        from sqlalchemy import select as _sel
        from ... import events as ev
        from ...models import Event
        async with eng.sf() as session:
            rows = (await session.execute(
                _sel(Event.payload, Event.ts).where(Event.type == ev.TIP_KNOWLEDGE_MAINTENANCE)
                .order_by(Event.id.desc()).limit(60))).all()
        for payload, ts in rows:
            if (payload or {}).get("status") == "done":
                return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    except Exception:
        log.debug("maintenance completion lookup failed", exc_info=True)
    return None


async def run_knowledge_maintenance(eng, *, client=None, force: bool = False) -> dict:
    """KB-01: knowledge maintenance on its OWN daily schedule (weekends
    included). Policy: run on the configured day, OR as catch-up while the
    current CYCLE is not complete (no genuine completion inside
    CATCHUP_DAYS); every outcome — skipped (not due / precondition), done
    (cycle complete), partial (pending work remains), failed — is journaled
    as TipKnowledgeMaintenance so a quiet week is distinguishable from a
    broken one. Batch idempotency (KB-02) protects a retry of an applied
    batch; the cycle (R63-04) bounds the paid work: each scope and the
    rulebook are audited at most MAX_GROUP_ATTEMPTS times per cycle."""
    from ... import events as ev
    s = eng.settings
    now = dt.datetime.now(ET)
    day = now.strftime("%Y-%m-%d")
    due = audit_due_today(s)
    last = await _last_completion(eng)
    overdue = last is None or (now.astimezone(dt.timezone.utc) - last).days >= CATCHUP_DAYS
    payload: dict = {"date": day, "due": due, "overdue": overdue,
                     "lastCompletion": last.isoformat() if last else None, "catchupDays": CATCHUP_DAYS}
    if not (due or overdue or force):
        payload["status"] = "skipped"
        payload["reason"] = "not due"
        try:
            await eng.journal.append(ev.TIP_KNOWLEDGE_MAINTENANCE, payload,
                                     aggregate_type="technique", aggregate_id="tip")
        except Exception:
            log.debug("maintenance journal failed", exc_info=True)
        return payload
    cycle: dict | None = None
    try:
        cycle = await _cycle_for(eng, await _eligible_groups(eng))
    except Exception:
        log.debug("cycle unavailable for this tick", exc_info=True)
    rule_rep: dict = {}
    know_rep: dict = {}
    try:
        payload["ruleAudit"] = await run_rule_audit(eng, client=client, report=rule_rep, cycle=cycle)
    except Exception as exc:
        rule_rep.update(status="failed", reason=str(exc)[:200])
    try:
        payload["knowledgeAudit"] = await run_knowledge_audit(eng, client=client, report=know_rep, cycle=cycle)
    except Exception as exc:
        know_rep.update(status="failed", reason=str(exc)[:200])
    if cycle is not None:
        await _save_cycle(eng, cycle)
        payload["cycle"] = _cycle_summary(cycle)
    payload["ruleAuditStatus"] = rule_rep or {"status": "done"}
    payload["knowledgeAuditStatus"] = know_rep or {"status": "done"}
    payload["applyMode"] = _apply_mode(s)
    statuses = {rule_rep.get("status", "done"), know_rep.get("status", "done")}
    if "failed" in statuses:
        payload["status"] = "failed"
    elif "partial" in statuses:
        payload["status"] = "partial"
    elif statuses == {"skipped"} and not (cycle and cycle.get("status") == "done"):
        # precondition unavailable (no key / disabled / nothing eligible):
        # NOT a completion — catch-up stays armed (KB-01)
        payload["status"] = "skipped"
        payload["reason"] = "; ".join(sorted({rule_rep.get("reason", ""), know_rep.get("reason", "")} - {""}))
    else:
        payload["status"] = "done"
    try:
        await eng.journal.append(ev.TIP_KNOWLEDGE_MAINTENANCE, payload,
                                 aggregate_type="technique", aggregate_id="tip")
    except Exception:
        log.debug("maintenance journal failed", exc_info=True)
    log.info("knowledge maintenance %s: %s", day, payload["status"])
    return payload
