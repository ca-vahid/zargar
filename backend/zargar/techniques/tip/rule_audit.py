"""The analyst's weekly rule audit (NEXT-GAPS A8).

Rules (`tip_notes` scope "rule") only ACCRETE during normal trading; this run
is the consolidation: it reads every live rule plus the recent retros and lane
grades, and returns merges (duplicates -> one refined rule), expiries (no
longer supported by evidence) and contradictions. The LLM only JUDGES — the
apply step is deterministic code, and it can only:

- add a refined rule and mark the merged ones superseded (never delete),
- mark an evidence-free/stale rule expired (superseded_by="expired:<run8>"),
- FLAG a contradiction for the human (needs_human) — never resolve one.

Runs with the nightly review on `techniques.tip.rule_audit_day` (default Sat);
off-switch `techniques.tip.rule_audit_enabled`. Fail-open like every analyst
run: an error changes nothing and retries next week.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Optional

from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

log = logging.getLogger("zargar.tip.rule_audit")
ET = ZoneInfo("America/New_York")

AUDIT_TIMEOUT_S = 90.0
MIN_RULES = 3          # nothing to consolidate below this — skip silently


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


async def _judge(client, *, model: str, system: str, header: str, cap: int,
                 max_tokens_ceiling: int = 8192) -> tuple[RuleAuditOpinion, list[dict]]:
    """One audit call, measured (KB-08): returns the parsed opinion and a
    per-call usage list [{inputTokens, outputTokens, stopReason, latencyMs}].
    The first live rule audit returned an EMPTY text (invalid JSON at column
    0): prose likely ran past the 2,000-token cap before the object — so a
    max_tokens stop with no JSON earns ONE retry at double the cap."""
    import asyncio
    from ...research import llm_stats
    calls: list[dict] = []
    text = ""
    for attempt in (1, 2):
        with llm_stats.timed() as _t:
            resp = await asyncio.wait_for(
                client.messages.create(model=model, max_tokens=cap, system=system,
                                       messages=[{"role": "user", "content": header}]),
                timeout=AUDIT_TIMEOUT_S)
        llm_stats.record_response("audit", resp, model=model, latency_ms=_t.ms, retried=attempt > 1)
        u = getattr(resp, "usage", None)
        stop = getattr(resp, "stop_reason", None)
        calls.append({"inputTokens": int(getattr(u, "input_tokens", 0) or 0) if u else None,
                      "outputTokens": int(getattr(u, "output_tokens", 0) or 0) if u else None,
                      "stopReason": str(stop) if stop else None, "latencyMs": round(_t.ms, 1),
                      "maxTokens": cap})
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if "{" in text or str(stop) != "max_tokens" or cap >= max_tokens_ceiling:
            break
        cap = min(cap * 2, max_tokens_ceiling)
    i, j = text.find("{"), text.rfind("}")
    return RuleAuditOpinion.model_validate_json(text[i:j + 1]), calls


def _apply_mode(settings) -> str:
    return "apply" if bool(settings.get("techniques.tip.knowledge_apply_enabled", False)) else "propose"


async def run_rule_audit(eng, *, client=None, report: dict | None = None) -> dict | None:
    """One audit run: read -> judge (LLM) -> apply (deterministic, ONE
    transaction, conflict-locked — KB-02) -> journal. Returns the applied
    summary, or None (disabled / too few rules / failed); `report`, when
    given, receives {status: skipped|failed|done, reason} so the maintenance
    job can tell a failure from a quiet skip (KB-01)."""
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
            tip={"liveRules": len(rules)}))
        await session.commit()

    header = (f"Today (ET): {dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))):%Y-%m-%d}\n"
              f"YOUR LIVE RULES ({len(rules)}):\n{rules_txt}\n\n"
              f"RECENT RETROS:\n{retro_txt}\n\nLANE GRADES:\n{lane_txt}")
    system = AUDIT_SYSTEM + json.dumps(RuleAuditOpinion.model_json_schema(),
                                       separators=(",", ":"))
    calls: list[dict] = []
    try:
        cap = int(s.get("techniques.tip.audit_max_output_tokens", 3000) or 3000)
        op, calls = await _judge(client, model=model, system=system, header=header, cap=cap)
    except Exception as exc:
        log.warning("rule audit failed: %s", exc)
        await _finish(eng, run_id, status="failed",
                      opinion={"error": str(exc)[:300], "usage": calls})   # KB-08: failures keep usage
        rep.update(status="failed", reason=str(exc)[:200])
        return None

    # ---- deterministic apply: validated + transactional (KB-02) ----------------
    from ... import events as ev
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
        return None
    flagged = list(applied.get("flagged") or [])
    payload = {"runId": run_id, **{k: v for k, v in applied.items() if k != "flagged"},
               "flagged": flagged, "summary": op.summary, "usage": calls, "mode": mode}
    rep.update(status="done", reason="")
    await _finish(eng, run_id, status="done",
                  opinion={"verdict": "audit", **payload,
                           "rationale": op.summary or "rulebook audited"})
    log.info("rule audit %s: merged %d, expired %d, flagged %d",
             run_id[:8], applied["merged"], applied["expired"], applied["contradictions"])
    return payload


AUDITABLE_PREFIXES = ("ticker:", "source:")


async def run_knowledge_audit(eng, *, client=None, report: dict | None = None) -> dict | None:
    """KNOWLEDGE plan B4: the weekly audit widened beyond rules. Every
    `ticker:*` / `source:*` / `general` group holding >= MIN_RULES ACTIVE notes
    gets the same judge -> deterministic-apply pass (merge near-duplicates,
    expire the unsupported, flag contradictions for the human). `daily:*` notes
    expire on their own TTL and `experiment:*`/`signal:*` are never audited.
    Same contract as run_rule_audit: fail-open, one run row, journaled."""
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
    # each group's notes are fetched in full; a per-run group budget DEFERS
    # the rest visibly instead of silently sampling the newest 300 rows
    counts = await svc.note_scope_counts(prefixes=AUDITABLE_PREFIXES, include_general=True)
    eligible = sorted(sc for sc, n in counts.items() if n >= MIN_RULES)
    if not eligible:
        rep.update(status="skipped", reason="no eligible groups")
        return None
    max_groups = int(s.get("techniques.tip.knowledge_audit_max_groups", 12) or 12)
    # KB-04: LEAST-RECENTLY-AUDITED first (durable cursor hydrated from the
    # journal, kept in memory between runs) — alphabetical first-N starved
    # every ticker:* group behind the source:* groups forever
    await _hydrate_audit_cursor(eng)
    eligible.sort(key=lambda sc: (_AUDIT_CURSOR.get(sc, ""), sc))
    todo, deferred = eligible[:max_groups], eligible[max_groups:]
    groups: dict[str, list[dict]] = {}
    for sc in todo:
        groups[sc] = await svc.tip_notes([sc], limit=5000)
    mode = _apply_mode(s)

    run_id = new_id()
    async with eng.sf() as session:
        session.add(TipAnalystRun(
            id=run_id, signal_id=None, ticker="NOTES", source="rule-audit",
            status="running", kind="rule_audit", model=model, tools=[],
            tip={"groups": sorted(groups), "notes": sum(len(v) for v in groups.values())}))
        await session.commit()

    import asyncio
    applied = {"groups": 0, "merged": 0, "expired": 0, "contradictions": 0,
               "newNotes": [], "flagged": [], "rejected": [],
               "groupsEligible": len(eligible), "groupsDeferred": deferred,
               "groupsFailed": []}
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
        try:
            cap = int(s.get("techniques.tip.audit_max_output_tokens", 3000) or 3000)
            op, calls = await _judge(
                client, model=model,
                system=AUDIT_SYSTEM + json.dumps(RuleAuditOpinion.model_json_schema(),
                                                 separators=(",", ":")),
                header=header, cap=cap)
            usage_all += [{"scope": scope, **c} for c in calls]
        except Exception as exc:
            log.warning("knowledge audit failed for %s: %s", scope, exc)
            applied["groupsFailed"].append(scope)      # visible, never silent
            usage_all.append({"scope": scope, "error": str(exc)[:160]})
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
            continue
        _AUDIT_CURSOR[scope] = dt.datetime.now(dt.timezone.utc).isoformat()   # progress, durable via journal
        applied["merged"] += got.get("merged", 0)
        applied["expired"] += got.get("expired", 0)
        applied["newNotes"] += got.get("newNotes", [])
        applied["flagged"] += [i for i in got.get("flagged", []) if i not in applied["flagged"]]
        applied["rejected"] += got.get("rejected", [])
        applied["groups"] += 1
    applied["contradictions"] = len(applied["flagged"])
    applied["mode"] = mode
    partial = bool(applied["groupsFailed"] or deferred)
    rep.update(status=("partial" if partial else "done"),
               reason=(f"failed {len(applied['groupsFailed'])}, deferred {len(deferred)}" if partial else ""))

    from ... import events as ev
    payload = {"runId": run_id, "kind": "knowledge", **applied, "usage": usage_all}
    await eng.journal.append(ev.TIP_RULE_AUDITED, payload,
                             aggregate_type="technique_run", aggregate_id=run_id)
    await _finish(eng, run_id, status=("partial" if partial else "done"),   # never 'done' with failed groups
                  opinion={"verdict": "audit", **payload,
                           "rationale": f"knowledge audit over {applied['groups']} scope group(s)"
                                        + (f"; {len(applied['groupsFailed'])} failed, {len(deferred)} deferred" if partial else "")})
    log.info("knowledge audit %s: %d group(s), merged %d, expired %d, flagged %d",
             run_id[:8], applied["groups"], applied["merged"], applied["expired"],
             applied["contradictions"])
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

# scope -> ISO time of its last audited batch (KB-04 progress cursor). Kept in
# memory between runs and hydrated from the journal so a restart never resets
# the traversal order to "alphabetical first N".
_AUDIT_CURSOR: dict[str, str] = {}
_CURSOR_HYDRATED = False


async def _hydrate_audit_cursor(eng) -> None:
    global _CURSOR_HYDRATED
    if _CURSOR_HYDRATED:
        return
    _CURSOR_HYDRATED = True
    try:
        from sqlalchemy import select as _sel
        from ... import events as ev
        from ...models import Event
        async with eng.sf() as session:
            rows = (await session.execute(
                _sel(Event.payload, Event.ts).where(Event.type == ev.TIP_RULE_AUDITED)
                .order_by(Event.id.desc()).limit(2000))).all()
        for payload, ts in rows:
            sc = (payload or {}).get("scope")
            if sc and sc not in _AUDIT_CURSOR:
                _AUDIT_CURSOR[sc] = ts.isoformat()
    except Exception:
        log.debug("audit cursor hydration unavailable (offline?)", exc_info=True)


async def _last_completion(eng) -> dt.datetime | None:
    """The newest journaled maintenance completion — GENUINE completion only
    ('done'); a partial pass never advances the watermark (KB-01)."""
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
    included) — the audit used to be chained inside the weekday-only
    `tip_retro` job, so its Saturday default never ran (zero rule_audit runs
    in the live DB). Policy: run on the configured day, OR as catch-up when
    no completion exists inside CATCHUP_DAYS; every outcome — skipped (not
    due), done, partial (a group failed/deferred), failed — is journaled as
    TipKnowledgeMaintenance so a quiet week is distinguishable from a broken
    one. Once-per-day and restart-safety come from the scheduler's journal
    hydration; batch idempotency (KB-02) protects a retry of an applied
    batch. Paid work: each audit is a TipAnalystRun, so the restart readiness
    door counts it."""
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
    rule_rep: dict = {}
    know_rep: dict = {}
    try:
        payload["ruleAudit"] = await run_rule_audit(eng, client=client, report=rule_rep)
    except Exception as exc:
        rule_rep.update(status="failed", reason=str(exc)[:200])
    try:
        payload["knowledgeAudit"] = await run_knowledge_audit(eng, client=client, report=know_rep)
    except Exception as exc:
        know_rep.update(status="failed", reason=str(exc)[:200])
    payload["ruleAuditStatus"] = rule_rep or {"status": "done"}
    payload["knowledgeAuditStatus"] = know_rep or {"status": "done"}
    payload["applyMode"] = _apply_mode(s)
    statuses = {rule_rep.get("status", "done"), know_rep.get("status", "done")}
    if "failed" in statuses:
        payload["status"] = "failed"
    elif "partial" in statuses:
        payload["status"] = "partial"
    elif statuses == {"skipped"}:
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
