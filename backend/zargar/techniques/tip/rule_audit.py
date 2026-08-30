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

from pydantic import BaseModel, Field

log = logging.getLogger("zargar.tip.rule_audit")

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


async def run_rule_audit(eng, *, client=None) -> dict | None:
    """One audit run: read -> judge (LLM) -> apply (deterministic) -> journal.
    Returns the applied summary, or None (disabled / too few rules / failed)."""
    from ...domain import new_id
    from ...models import Event, TipAnalystRun

    s = eng.settings
    if not bool(s.get("techniques.tip.rule_audit_enabled", True)):
        return None
    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        return None
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    model = str(s.get("techniques.tip.analyst_model") or "") or eng.config.extraction_model

    svc = eng.signals_service
    rules = await svc.tip_notes(["rule"], limit=100)          # live rules only
    if len(rules) < MIN_RULES:
        log.info("rule audit: only %d live rule(s) — nothing to consolidate", len(rules))
        return None

    # evidence pre-pass (A8.4): a rule should cite a position/run/date
    def cited(r: dict) -> bool:
        t = r["text"].lower()
        return any(k in t for k in ("position", "run ", "run:", "20", "retro", "lane", "#"))

    rules_txt = "\n".join(
        f"- [{r['id']}] {r['text']} (by {r['author']}, {(r['createdAt'] or '')[:10]})"
        + ("" if cited(r) else "  [NO EVIDENCE CITED]")
        for r in rules)

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
    try:
        import asyncio
        resp = await asyncio.wait_for(
            client.messages.create(model=model, max_tokens=2000, system=system,
                                   messages=[{"role": "user", "content": header}]),
            timeout=AUDIT_TIMEOUT_S)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        i, j = text.find("{"), text.rfind("}")
        op = RuleAuditOpinion.model_validate_json(text[i:j + 1])
    except Exception as exc:
        log.warning("rule audit failed: %s", exc)
        await _finish(eng, run_id, status="failed", opinion={"error": str(exc)[:300]})
        return None

    # ---- deterministic apply -------------------------------------------------
    from ... import events as ev
    live_ids = {r["id"] for r in rules}
    applied = {"merged": 0, "expired": 0, "contradictions": 0, "newRules": []}
    for m in op.merges:
        ids = [i for i in m.supersedes if i in live_ids]
        if not ids or not m.new_rule.strip():
            continue
        new = await svc.add_tip_note("rule", m.new_rule.strip(),
                                     author=f"rule-audit:{run_id[:8]}", run_id=run_id)
        await svc.supersede_tip_notes(ids, by=new["id"])
        live_ids -= set(ids)
        applied["merged"] += len(ids)
        applied["newRules"].append(new["id"])
    for e in op.expires:
        if e.id in live_ids:
            await svc.supersede_tip_notes([e.id], by=f"expired:{run_id[:8]}")
            live_ids.discard(e.id)
            applied["expired"] += 1
    flagged: list[str] = []
    for c in op.contradictions:
        ids = [i for i in c.ids if i in live_ids]
        if len(ids) >= 2:
            await svc.flag_tip_notes(ids, needs_human=True)
            flagged += ids
    applied["contradictions"] = len(flagged)

    payload = {"runId": run_id, **applied, "flagged": flagged, "summary": op.summary}
    await eng.journal.append(ev.TIP_RULE_AUDITED, payload,
                             aggregate_type="technique_run", aggregate_id=run_id)
    await _finish(eng, run_id, status="done",
                  opinion={"verdict": "audit", **payload,
                           "rationale": op.summary or "rulebook audited"})
    log.info("rule audit %s: merged %d, expired %d, flagged %d",
             run_id[:8], applied["merged"], applied["expired"], applied["contradictions"])
    return payload


AUDITABLE_PREFIXES = ("ticker:", "source:")


async def run_knowledge_audit(eng, *, client=None) -> dict | None:
    """KNOWLEDGE plan B4: the weekly audit widened beyond rules. Every
    `ticker:*` / `source:*` / `general` group holding >= MIN_RULES ACTIVE notes
    gets the same judge -> deterministic-apply pass (merge near-duplicates,
    expire the unsupported, flag contradictions for the human). `daily:*` notes
    expire on their own TTL and `experiment:*`/`signal:*` are never audited.
    Same contract as run_rule_audit: fail-open, one run row, journaled."""
    from ...domain import new_id
    from ...models import TipAnalystRun

    s = eng.settings
    if not bool(s.get("techniques.tip.rule_audit_enabled", True)):
        return None
    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        return None
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    model = str(s.get("techniques.tip.analyst_model") or "") or eng.config.extraction_model

    svc = eng.signals_service
    all_notes = await svc.tip_notes(limit=300)     # active only (expired/superseded filtered)
    groups: dict[str, list[dict]] = {}
    for n in all_notes:
        sc = n["scope"]
        if sc == "general" or sc.startswith(AUDITABLE_PREFIXES):
            groups.setdefault(sc, []).append(n)
    groups = {k: v for k, v in groups.items() if len(v) >= MIN_RULES}
    if not groups:
        return None

    run_id = new_id()
    async with eng.sf() as session:
        session.add(TipAnalystRun(
            id=run_id, signal_id=None, ticker="NOTES", source="rule-audit",
            status="running", kind="rule_audit", model=model, tools=[],
            tip={"groups": sorted(groups), "notes": sum(len(v) for v in groups.values())}))
        await session.commit()

    import asyncio
    applied = {"groups": 0, "merged": 0, "expired": 0, "contradictions": 0,
               "newNotes": [], "flagged": []}
    for scope, notes in sorted(groups.items()):
        notes_txt = "\n".join(
            f"- [{n['id']}] {n['text']} (by {n['author']}, {(n['createdAt'] or '')[:10]}, "
            f"cited {n.get('citedCount', 0)}x)"
            for n in notes)
        header = (f"These are the desk's ACTIVE knowledge notes in scope '{scope}' "
                  f"(not trading rules — market/source knowledge):\n{notes_txt}")
        try:
            resp = await asyncio.wait_for(
                client.messages.create(model=model, max_tokens=1500,
                                       system=AUDIT_SYSTEM + json.dumps(
                                           RuleAuditOpinion.model_json_schema(),
                                           separators=(",", ":")),
                                       messages=[{"role": "user", "content": header}]),
                timeout=AUDIT_TIMEOUT_S)
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            i, j = text.find("{"), text.rfind("}")
            op = RuleAuditOpinion.model_validate_json(text[i:j + 1])
        except Exception as exc:
            log.warning("knowledge audit failed for %s: %s", scope, exc)
            continue
        live_ids = {n["id"] for n in notes}
        for m in op.merges:
            ids = [i for i in m.supersedes if i in live_ids]
            if not ids or not m.new_rule.strip():
                continue
            new = await svc.add_tip_note(scope, m.new_rule.strip(),
                                         author=f"knowledge-audit:{run_id[:8]}",
                                         run_id=run_id)
            await svc.supersede_tip_notes(ids, by=new["id"])
            live_ids -= set(ids)
            applied["merged"] += len(ids)
            applied["newNotes"].append(new["id"])
        for e in op.expires:
            if e.id in live_ids:
                await svc.supersede_tip_notes([e.id], by=f"expired:{run_id[:8]}")
                live_ids.discard(e.id)
                applied["expired"] += 1
        for c in op.contradictions:
            ids = [i for i in c.ids if i in live_ids]
            if len(ids) >= 2:
                await svc.flag_tip_notes(ids, needs_human=True)
                applied["flagged"] += ids
        applied["groups"] += 1
    applied["contradictions"] = len(applied["flagged"])

    from ... import events as ev
    payload = {"runId": run_id, "kind": "knowledge", **applied}
    await eng.journal.append(ev.TIP_RULE_AUDITED, payload,
                             aggregate_type="technique_run", aggregate_id=run_id)
    await _finish(eng, run_id, status="done",
                  opinion={"verdict": "audit", **payload,
                           "rationale": f"knowledge audit over {applied['groups']} scope group(s)"})
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
    """Runs with the nightly review only on the configured ET weekday."""
    want = str(settings.get("techniques.tip.rule_audit_day", "Sat"))[:3].lower()
    now_et = dt.datetime.now(dt.timezone(dt.timedelta(hours=-4)))
    return now_et.strftime("%a").lower() == want
