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

import datetime as dt
import hashlib
import json
import logging
from typing import Optional

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


async def _judge(client, *, model: str, system: str, header: str, cap: int,
                 max_tokens_ceiling: int = MAX_TOKENS_CEILING) -> tuple[RuleAuditOpinion, list[dict]]:
    """One audit judgement, measured (KB-08): returns the parsed opinion and
    the per-call usage list [{inputTokens, outputTokens, stopReason,
    latencyMs, maxTokens}]. A reply that does not validate earns ONE retry —
    at double the cap when the stop reason was `max_tokens` (the first live
    rule audit came back empty: prose ran past the 2,000-token cap before any
    object), at the same cap otherwise. Every failure raises JudgeError WITH
    the calls made, so a failed audit still records what it paid for."""
    import asyncio
    from ...research import llm_stats
    calls: list[dict] = []
    last_error: str = ""
    for attempt in (1, 2):
        try:
            with llm_stats.timed() as _t:
                resp = await asyncio.wait_for(
                    client.messages.create(model=model, max_tokens=cap, system=system,
                                           messages=[{"role": "user", "content": header}]),
                    timeout=AUDIT_TIMEOUT_S)
        except Exception as exc:                       # timeout / provider error / cancel
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
            if truncated and cap < max_tokens_ceiling:
                cap = min(cap * 2, max_tokens_ceiling)   # bounded repair: ONE doubled retry
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


async def _record_failed_group(eng, run_id: str, scope: str, error: str, calls: list[dict]) -> None:
    """R63-03: failed work is journaled explicitly — a receipt row with
    status 'failed' (same id shape as an applied batch) so restarts see the
    attempt and the paid calls behind it."""
    try:
        from ...models import TipKnowledgeBatch
        async with eng.sf() as session:
            session.add(TipKnowledgeBatch(
                id=f"{run_id}:{scope}", run_id=run_id, scope=scope, status="failed",
                payload_hash="", proposal={"error": (error or "")[:300], "usage": calls},
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
    for sc, p in sorted(prog.items()):
        by.setdefault(p.get("status", "pending"), []).append(sc)
    return {"cycleId": cycle["id"], "startedAt": cycle["startedAt"], "status": cycle["status"],
            **by, "discovered": [d["scope"] for d in (cycle.get("discovered") or [])]}


def _revisions_hash(notes: list[dict]) -> str:
    key = json.dumps(sorted((n["id"], int(n.get("revisionNo") or 1)) for n in notes))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


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

    rules_txt = "\n".join(
        f"- [{r['id']}] {r['text']} (by {r['author']}, {(r['createdAt'] or '')[:10]})"
        + ("" if cited(r) else "  [NO EVIDENCE CITED]")
        + ("  [DISPUTED — unresolved by the human; never merge or expire]" if r.get("needsHuman") else "")
        for r in rules)
    expected_revisions = {r["id"]: int(r.get("revisionNo") or 1) for r in rules}

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

    header = (f"Today (ET): {dt.datetime.now(ET):%Y-%m-%d}\n"
              f"YOUR LIVE RULES ({len(rules)}):\n{rules_txt}\n\n"
              f"RECENT RETROS:\n{retro_txt}\n\nLANE GRADES:\n{lane_txt}")
    system = AUDIT_SYSTEM + json.dumps(RuleAuditOpinion.model_json_schema(),
                                       separators=(",", ":"))
    calls: list[dict] = []
    try:
        cap = int(s.get("techniques.tip.audit_max_output_tokens", 3000) or 3000)
        op, calls = await _judge(client, model=model, system=system, header=header, cap=cap)
    except JudgeError as exc:
        calls = exc.calls
        log.warning("rule audit failed: %s", exc)
        await _finish(eng, run_id, status="failed",
                      opinion={"error": str(exc)[:300], "usage": calls})   # KB-08: failures keep usage
        rep.update(status="failed", reason=str(exc)[:200])
        if cycle is not None:
            _mark(cycle, "rule", ok=False, now=now_iso, error=str(exc))
            await _save_cycle(eng, cycle)
        return None

    # ---- deterministic apply: validated + transactional (KB-02) ----------------
    live_ids = {r["id"] for r in rules}
    mode = _apply_mode(s)
    try:
        applied = await svc.apply_knowledge_batch(
            scope="rule", merges=list(op.merges), expires=list(op.expires),
            contradictions=list(op.contradictions),
            author=f"rule-audit:{run_id[:8]}", run_id=run_id, live_ids=live_ids,
            batch_id=f"{run_id}:rule", expected_revisions=expected_revisions, mode=mode)
    except Exception as exc:
        log.warning("rule audit apply aborted (nothing written): %s", exc)
        await _finish(eng, run_id, status="failed",
                      opinion={"error": f"apply aborted: {exc}"[:300], "usage": calls})
        rep.update(status="failed", reason=f"apply aborted: {exc}"[:200])
        if cycle is not None:
            _mark(cycle, "rule", ok=False, now=now_iso, error=f"apply aborted: {exc}")
            await _save_cycle(eng, cycle)
        return None
    flagged = list(applied.get("flagged") or [])
    payload = {"runId": run_id, **{k: v for k, v in applied.items() if k != "flagged"},
               "flagged": flagged, "summary": op.summary, "usage": calls, "mode": mode,
               "cycleId": cycle["id"] if cycle else None}
    rep.update(status="done", reason="")
    if cycle is not None:
        _mark(cycle, "rule", ok=True, now=now_iso, batch_id=f"{run_id}:rule",
              revisions_hash=_revisions_hash(rules))
        await _save_cycle(eng, cycle)
    await _finish(eng, run_id, status="done",
                  opinion={"verdict": "audit", **payload,
                           "rationale": op.summary or "rulebook audited"})
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
               "newNotes": [], "flagged": [], "rejected": [],
               "groupsEligible": len(eligible), "groupsFailed": []}
    usage_all: list[dict] = []
    for scope, notes in groups.items():
        notes_txt = "\n".join(
            f"- [{n['id']}] {n['text']} (by {n['author']}, {(n['createdAt'] or '')[:10]}, "
            f"cited {n.get('citedCount', 0)}x)"
            + ("  [DISPUTED — unresolved by the human; never merge or expire]" if n.get("needsHuman") else "")
            for n in notes)
        expected_revisions = {n["id"]: int(n.get("revisionNo") or 1) for n in notes}
        header = (f"These are the desk's ACTIVE knowledge notes in scope '{scope}' "
                  f"(not trading rules — market/source knowledge):\n{notes_txt}")
        attempt_at = _now_iso()
        try:
            cap = int(s.get("techniques.tip.audit_max_output_tokens", 3000) or 3000)
            op, calls = await _judge(
                client, model=model,
                system=AUDIT_SYSTEM + json.dumps(RuleAuditOpinion.model_json_schema(),
                                                 separators=(",", ":")),
                header=header, cap=cap)
            usage_all += [{"scope": scope, **c} for c in calls]
        except Exception as exc:
            calls = list(getattr(exc, "calls", None) or [])
            usage_all += [{"scope": scope, **c} for c in calls]
            usage_all.append({"scope": scope, "error": str(exc)[:160]})
            log.warning("knowledge audit failed for %s: %s", scope, exc)
            applied["groupsFailed"].append(scope)      # visible, never silent
            _mark(cycle, scope, ok=False, now=attempt_at, error=str(exc))
            await _record_failed_group(eng, run_id, scope, str(exc), calls)
            await _save_cycle(eng, cycle)
            continue
        live_ids = {n["id"] for n in notes}
        try:
            got = await svc.apply_knowledge_batch(
                scope=scope, merges=list(op.merges), expires=list(op.expires),
                contradictions=list(op.contradictions),
                author=f"knowledge-audit:{run_id[:8]}", run_id=run_id,
                live_ids=live_ids, batch_id=f"{run_id}:{scope}",
                expected_revisions=expected_revisions, mode=mode)
        except Exception as exc:
            log.warning("knowledge audit apply aborted for %s: %s", scope, exc)
            applied["groupsFailed"].append(scope)
            usage_all.append({"scope": scope, "error": f"apply aborted: {exc}"[:160]})
            _mark(cycle, scope, ok=False, now=attempt_at, error=f"apply aborted: {exc}")
            await _record_failed_group(eng, run_id, scope, f"apply aborted: {exc}", calls)
            await _save_cycle(eng, cycle)
            continue
        got = got or {}
        _mark(cycle, scope, ok=True, now=attempt_at, batch_id=f"{run_id}:{scope}",
              revisions_hash=_revisions_hash(notes))
        await _save_cycle(eng, cycle)
        applied["merged"] += got.get("merged", 0)
        applied["expired"] += got.get("expired", 0)
        applied["newNotes"] += got.get("newNotes", [])
        applied["flagged"] += [i for i in got.get("flagged", []) if i not in applied["flagged"]]
        applied["rejected"] += got.get("rejected", [])
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
