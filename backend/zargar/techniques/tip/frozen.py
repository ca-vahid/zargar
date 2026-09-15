"""Frozen knowledge comparison (KFIN-09, 2026-09-14).

An appraisal is replayed against an IMMUTABLE case bundle - the message, the
tool outputs the original run saw, the rule/note set with ids + revisions,
model + settings and the exact context manifest - under two or more KNOWLEDGE
VARIANTS (the current set verbatim, a compact core-only set, a no-knowledge
control). Every replay is isolated by construction:

* no engine is involved in a replay - the only inputs are the bundle and an
  LLM client; a tool call is served from the bundle's recorded outputs or
  refused ("missing"), never fetched today;
* `save_note` is captured on the report as a PROPOSED note and never written;
* nothing reaches tip_notes, orders, proposals, books or plans - the only rows
  a replay may add are `tip_frozen_replays` (evidence).

The report says what changed (decision, contract, protections), what the
model grounded on, whether it produced a verdict at all, latency and tokens.
It never claims a variant is better: that is a separate, reviewed verdict.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time

from sqlalchemy import select

from ... import events as ev
from ...domain import new_id
from ...models import RawContent, Signal, TipAnalystRun, TipFrozenBundle, TipFrozenReplay

log = logging.getLogger("zargar.tip.frozen")

BUNDLE_VERSION = 1
MISSING = ("(unavailable in the frozen bundle - not persisted at run time; "
           "a frozen replay never fetches today's data)")
VARIANTS = ("current", "core_only", "no_knowledge", "compact")
COMPACT_HISTORY_LINES = 12      # PROF-05: the compact context keeps the newest N history lines
# settings a run's behaviour depends on - captured verbatim on the bundle
SETTINGS_KEYS = (
    "techniques.tip.analyst_model", "techniques.tip.analyst_max_tools",
    "techniques.tip.analyst_max_output_tokens", "techniques.tip.analyst_max_rules",
    "techniques.tip.analyst_notes_max", "techniques.tip.budget_per_tip",
    "techniques.tip.max_premium_per_tip", "techniques.tip.max_contracts_per_tip",
    "techniques.tip.lotto_max_dte", "techniques.tip.lotto_budget",
)
_RULES_MARK = "YOUR TRADING RULES (self-maintained — follow them):\n"   # the analyst's exact text
_RULES_MARK_LEGACY = "YOUR TRADING RULES (self-maintained - follow them):\n"
_NOTES_MARK = "\nSHARED NOTES (desk knowledge from earlier runs):\n"
_HISTORY_MARK = "\nTHIS SOURCE'S LAST ~3 DAYS"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def _iso(x) -> str | None:
    if x is None:
        return None
    return x.isoformat() if hasattr(x, "isoformat") else str(x)


# ------------------------------------------------------------------ manifest
def manifest_from_components(*, header: str, system: str, today_line: str,
                             rules_text: str, notes_text: str, history_text: str,
                             lotto_line: str, verification: dict, tip: dict, policy,
                             siblings=None, historical_note=None) -> dict:
    """The EXACT context of one live appraisal, kept as components so a
    frozen replay rebuilds the header verbatim and can swap ONE block
    (rules / notes) for a knowledge variant. Called by the analyst behind
    `techniques.tip.frozen_capture_context`."""
    return {
        "version": BUNDLE_VERSION, "exact": True,
        "header": header, "headerSha": _sha(header),
        "system": system, "systemSha": _sha(system),
        "todayLine": today_line, "rulesText": rules_text, "notesText": notes_text,
        "historyText": history_text, "lottoLine": lotto_line,
        "verification": {"passed": verification.get("passed"),
                         "park": verification.get("park"),
                         "shadow_only": verification.get("shadow_only"),
                         "failedChecks": [c.get("name") for c in verification.get("checks", [])
                                          if not c.get("passed")]},
        "tip": tip,
        "policy": {"budgetPerTip": getattr(policy, "budget_per_tip", None),
                   "dteMin": getattr(policy, "dte_min", None),
                   "dteMax": getattr(policy, "dte_max", None)},
        "siblings": list(siblings) if siblings else None,
        "historicalNote": historical_note,
    }


def format_rules(rules: list[dict]) -> str:
    """The analyst's own rulebook block, formatted exactly as `_rules_text`
    formats it (order preserved = oldest first as supplied)."""
    if not rules:
        from .analyst import STARTER_RULES
        return STARTER_RULES
    return "\n".join(
        ("- [PENDING REVIEW — proposed or disputed, NOT operative policy: do not apply it as a rule] "
         if r.get("disputed") else "- ")
        + f"{r['text']} ({(r.get('createdAt') or '')[:10]})"
        for r in rules)


def format_notes(notes: list[dict]) -> str:
    return "\n".join(
        f"- N{i + 1} [{n.get('scope')}] {n.get('text')} ({(n.get('createdAt') or '')[:10]}, {n.get('author')})"
        for i, n in enumerate(notes)) or "(none yet)"


def trim_history(text: str | None, lines: int) -> str:
    """The newest N lines of a history block (the block is newest first)."""
    if not text:
        return text or ""
    rows = str(text).split("\n")
    return "\n".join(rows[:max(1, int(lines))])


def _rebuild_header(manifest: dict, *, rules_text: str, notes_text: str,
                    history_lines: int | None = None) -> tuple[str, list[str]]:
    """The run's header with the rules and notes blocks replaced. An EXACT
    manifest is sliced at its markers (verbatim otherwise); a reconstructed
    one is assembled from the bundle's components with every unknown block
    left explicitly missing."""
    gaps: list[str] = []
    if manifest.get("exact") and manifest.get("header"):
        h = str(manifest["header"])
        mark = _RULES_MARK if _RULES_MARK in h else _RULES_MARK_LEGACY
        i = h.find(mark)
        j = h.find(_NOTES_MARK, i if i >= 0 else 0)
        k = h.find(_HISTORY_MARK, j if j >= 0 else 0)
        if i < 0 or j < 0 or k < 0:
            gaps.append("header markers not found - rules/notes blocks could not be swapped")
            return h, gaps
        tail = h[k:]
        if history_lines is not None:
            # PROF-05: the history block starts after its marker line
            nl = tail.find("\n", 1)                    # the marker line may begin with a newline
            if nl >= 0:
                tail = tail[:nl + 1] + trim_history(tail[nl + 1:], history_lines)
        return (h[:i + len(mark)] + rules_text + _NOTES_MARK + notes_text + tail), gaps
    tip = manifest.get("tip") or {}
    ver = manifest.get("verification") or {}
    pol = manifest.get("policy") or {}
    budget = pol.get("budgetPerTip")
    today = manifest.get("todayLine") or "Today (ET): (unknown - run time not captured)"
    header = (f"{today}\n"
              f"Per-tip budget: ${float(budget):,.0f} · option DTE window "
              f"{pol.get('dteMin')}-{pol.get('dteMax')} (tip's own contract may override)\n"
              if budget is not None else f"{today}\nPer-tip budget: {MISSING}\n")
    if manifest.get("lottoLine"):
        header += str(manifest["lottoLine"])
    header += (f"TIP: {json.dumps(tip)}\n"
               f"VERIFICATION: {json.dumps({k: ver.get(k) for k in ('passed', 'park', 'shadow_only')})} "
               f"failed checks: {ver.get('failedChecks') or []}\n"
               + _RULES_MARK + rules_text
               + _NOTES_MARK + notes_text
               + "\nTHIS SOURCE'S LAST ~3 DAYS (their channel, mirrored, newest first — the "
                 "backstory this tip arrived in: earlier OPENs, trims, exits, mood. Read it "
                 "before judging; search_messages digs deeper/older):\n"
               + (trim_history(str(manifest.get("historyText")), history_lines)
                  if history_lines is not None and manifest.get("historyText") else str(manifest.get("historyText") or MISSING)))
    if manifest.get("siblings"):
        header = ("THIS MESSAGE HAS SEVERAL BRANCHES and is appraised ONCE, on this one: "
                  + "; ".join(manifest["siblings"]) + ". Judge the MESSAGE (is it a map, a "
                  "digest, a real open?) - your verdict is inherited by every branch; a 'take' "
                  "applies to THIS branch only. Save at most one note about the message as a whole.\n\n"
                  + header)
    if manifest.get("historicalNote"):
        header = str(manifest["historicalNote"]) + "\n\n" + header
    gaps.append("context manifest reconstructed from components (not captured verbatim)")
    if not manifest.get("historyText"):
        gaps.append("source history block missing (not persisted at run time)")
    return header, gaps


# ------------------------------------------------------------------- capture
async def build_bundle(sf, *, run_id: str | None = None, signal_id: str | None = None,
                       settings=None) -> dict:
    """Assemble the case bundle from what the DB already holds. Pure read;
    nothing is fetched from a feed or a provider. `settings` (optional) adds
    the current values of the run-relevant knobs; the bundle records which
    keys were unavailable."""
    if not run_id and not signal_id:
        raise ValueError("run_id or signal_id is required")
    async with sf() as session:
        run = None
        if run_id:
            run = await session.get(TipAnalystRun, run_id)
            if run is None:
                raise ValueError(f"analyst run {run_id} not found")
            signal_id = signal_id or run.signal_id
        sig = await session.get(Signal, signal_id) if signal_id else None
        if sig is None:
            raise ValueError(f"signal {signal_id} not found")
        if run is None:
            run_id = ((sig.extraction or {}).get("analyst") or {}).get("runId")
            run = await session.get(TipAnalystRun, run_id) if run_id else None
            if run is None:
                # the newest appraisal of this signal
                run = (await session.execute(
                    select(TipAnalystRun).where(TipAnalystRun.signal_id == sig.id)
                    .order_by(TipAnalystRun.created_at.desc()).limit(1))).scalars().first()
        content = await session.get(RawContent, sig.raw_content_id) if sig.raw_content_id else None

    gaps: list[str] = []
    x = sig.extraction or {}
    trace = list(run.trace or []) if run else []
    start = next((s for s in trace if s.get("kind") == "start"), {}) or {}
    rule_step = next((s for s in trace if s.get("kind") == "note" and s.get("ruleIds")), None)
    ctx_step = next((s for s in trace if s.get("kind") == "context" and s.get("contextManifest")), None)

    # tool outputs the run saw, in order, keyed on the exact call
    tool_outputs: list[dict] = []
    pending: list[dict] = []
    for s in trace:
        if s.get("kind") == "tool_call":
            pending.append({"tool": s.get("tool"), "args": s.get("args") or {}})
        elif s.get("kind") == "tool_result" and pending:
            call = pending.pop(0)
            res = s.get("result")
            if isinstance(res, dict) and res.get("image"):
                res = {"error": "image content is not captured in a frozen bundle (stub only)"}
                gaps.append(f"view_image output not capturable ({call['args']})")
            tool_outputs.append({**call, "result": res})
    if pending:
        gaps.append(f"{len(pending)} tool call(s) without a recorded result")

    if rule_step:
        rules = [{"id": r.get("id"), "text": r.get("text"), "disputed": bool(r.get("disputed")),
                  "core": r.get("core"), "createdAt": r.get("createdAt")}
                 for r in (rule_step.get("rules") or [])]
        rev = rule_step.get("revisionNos") or []
        for i, r in enumerate(rules):
            r["revisionNo"] = rev[i] if i < len(rev) else None
        knowledge = {"rules": rules, "rulesHash": rule_step.get("rulesHash"),
                     "selection": rule_step.get("selection"), "starterRules": False}
        if any(r.get("core") is None for r in rules):
            gaps.append("rule snapshot predates the core flag - core_only variant unavailable")
    else:
        knowledge = {"rules": [], "rulesHash": None, "selection": None,
                     "starterRules": True}
        if run is not None and start.get("rules"):
            gaps.append("rule snapshot missing from the trace")
    notes = [{"id": n.get("id"), "scope": n.get("scope"), "text": n.get("text"),
              "author": n.get("author"), "createdAt": n.get("createdAt"),
              "core": bool(n.get("core")), "revisionNo": n.get("revisionNo")}
             for n in (start.get("notes") or [])]
    knowledge["notes"] = notes

    settings_snap: dict = {}
    if settings is not None:
        for k in SETTINGS_KEYS:
            try:
                settings_snap[k] = settings.get(k)
            except Exception:
                settings_snap[k] = None
    else:
        gaps.append("settings not captured (no settings service supplied)")

    if ctx_step:
        manifest = dict(ctx_step["contextManifest"])
    else:
        created = getattr(run, "created_at", None)
        today_line = (f"Today (ET): {(created - dt.timedelta(hours=4)):%Y-%m-%d %H:%M}"
                      if created else None)
        manifest = {"version": BUNDLE_VERSION, "exact": False, "header": None,
                    "system": None, "systemSha": None,
                    "todayLine": today_line, "historyText": None, "lottoLine": None,
                    "verification": {"passed": (sig.verification or {}).get("passed"),
                                     "park": (sig.verification or {}).get("park"),
                                     "shadow_only": (sig.verification or {}).get("shadow_only"),
                                     "failedChecks": [c.get("name") for c in
                                                      (sig.verification or {}).get("checks", [])
                                                      if not c.get("passed")]},
                    "tip": start.get("tip") or {},
                    "policy": {"budgetPerTip": (x.get("policy") or {}).get("budget_per_tip"),
                               "dteMin": (x.get("policy") or {}).get("dte_min"),
                               "dteMax": (x.get("policy") or {}).get("dte_max")},
                    "siblings": None, "historicalNote": None}
        gaps.append("context manifest not captured verbatim (techniques.tip.frozen_capture_context "
                    "was off) - reconstructed; source history + system prompt missing")

    op = (run.opinion or {}) if run else {}
    bundle = {
        "version": BUNDLE_VERSION,
        "signal": {"id": sig.id, "ticker": sig.ticker, "direction": sig.direction,
                   "action": sig.action, "instrument": sig.instrument, "strike": sig.strike,
                   "premium": sig.premium, "expiry": sig.expiry, "source": sig.source_name,
                   "status": sig.status, "statedAt": x.get("statedAt"),
                   "extracted": x.get("signal") or {}},
        "message": ({"contentId": content.id, "text": content.body_text, "subject": content.subject,
                     "sourceType": content.source_type, "receivedAt": _iso(content.received_at),
                     "meta": {k: v for k, v in (content.meta or {}).items()
                              if k in ("messageId", "postedAt", "channelId", "author", "images")}}
                    if content else None),
        "run": ({"id": run.id, "model": run.model, "kind": run.kind, "createdAt": _iso(run.created_at),
                 "status": run.status, "verdict": run.verdict,
                 "opinion": {k: op.get(k) for k in
                             ("verdict", "contract", "contract_label", "limit_price", "quantity",
                              "confidence", "entry_mode", "entry_level", "used_notes",
                              "exit_targets", "exit_fractions", "underlying_stop",
                              "premium_stop_pct", "max_hold_sessions", "rationale")},
                 "usage": op.get("usage"), "tools": list(run.tools or [])}
                if run else None),
        "toolOutputs": tool_outputs,
        "knowledge": knowledge,
        "settings": settings_snap,
        "manifest": manifest,
        "gaps": gaps,
    }
    if content is None:
        gaps.append("raw content missing (message text unavailable)")
    if run is None:
        gaps.append("no analyst run for this signal - replay has no baseline decision")
    bundle["contentHash"] = _sha(_canonical({k: v for k, v in bundle.items() if k != "gaps"}))
    bundle["id"] = "fb-" + bundle["contentHash"][:16]
    return bundle


async def capture_bundle(sf, *, run_id: str | None = None, signal_id: str | None = None,
                         settings=None, journal=None) -> dict:
    """Build + persist the bundle (insert-only, keyed by content hash: an
    unchanged case re-captured returns the existing row). Returns the bundle
    dict with `id`, `contentHash` and `existing`."""
    bundle = await build_bundle(sf, run_id=run_id, signal_id=signal_id, settings=settings)
    async with sf() as session:
        row = await session.get(TipFrozenBundle, bundle["id"])
        if row is None:
            session.add(TipFrozenBundle(id=bundle["id"], signal_id=bundle["signal"]["id"],
                                        run_id=(bundle.get("run") or {}).get("id"),
                                        content_hash=bundle["contentHash"], bundle=bundle))
            await session.commit()
            existing = False
        else:
            existing = True
    if journal is not None and not existing:
        try:
            await journal.append(ev.TIP_FROZEN_BUNDLE,
                                 {"bundleId": bundle["id"], "signalId": bundle["signal"]["id"],
                                  "runId": (bundle.get("run") or {}).get("id"),
                                  "contentHash": bundle["contentHash"], "gaps": bundle["gaps"],
                                  "toolOutputs": len(bundle["toolOutputs"]),
                                  "rules": len(bundle["knowledge"]["rules"]),
                                  "notes": len(bundle["knowledge"]["notes"])},
                                 aggregate_type="signal", aggregate_id=bundle["signal"]["id"])
        except Exception:
            log.debug("bundle journal failed", exc_info=True)
    return {**bundle, "existing": existing}


async def load_bundle(sf, bundle_id: str) -> dict:
    async with sf() as session:
        row = await session.get(TipFrozenBundle, bundle_id)
    if row is None:
        raise ValueError(f"bundle {bundle_id} not found")
    return dict(row.bundle or {})


# ------------------------------------------------------------------ variants
def variant_knowledge(bundle: dict, variant: str) -> dict:
    """The rules/notes blocks one variant supplies, plus the manifest of what
    was kept/dropped. `available=False` when the bundle cannot express it."""
    k = bundle.get("knowledge") or {}
    rules = list(k.get("rules") or [])
    notes = list(k.get("notes") or [])
    man = bundle.get("manifest") or {}
    if variant == "current":
        rules_text = (man.get("rulesText") if man.get("exact") and man.get("rulesText")
                      else format_rules(rules))
        notes_text = (man.get("notesText") if man.get("exact") and man.get("notesText")
                      else format_notes(notes))
        return {"variant": variant, "available": True, "rulesText": rules_text,
                "notesText": notes_text, "ruleIds": [r.get("id") for r in rules],
                "noteIds": [n.get("id") for n in notes], "rulesSupplied": len(rules),
                "notesSupplied": len(notes), "dropped": 0,
                "rulesHash": k.get("rulesHash"), "starterRules": bool(k.get("starterRules"))}
    if variant == "core_only":
        if rules and any(r.get("core") is None for r in rules):
            return {"variant": variant, "available": False,
                    "reason": "bundle's rule snapshot carries no core flags"}
        core_r = [r for r in rules if r.get("core")]
        core_n = [n for n in notes if n.get("core")]
        return {"variant": variant, "available": True,
                "rulesText": format_rules(core_r), "notesText": format_notes(core_n),
                "ruleIds": [r.get("id") for r in core_r], "noteIds": [n.get("id") for n in core_n],
                "rulesSupplied": len(core_r), "notesSupplied": len(core_n),
                "dropped": (len(rules) - len(core_r)) + (len(notes) - len(core_n)),
                "rulesHash": _sha(_canonical([r.get("id") for r in core_r]))[:12],
                "starterRules": not core_r,
                **({"degenerate": "no core rules in the bundle - starter rules supplied"}
                   if not core_r else {})}
    if variant == "compact":
        # PROF-05 (2026-09-15): the CORE (mandatory) rules plus the notes that
        # are RELEVANT to this tip - its ticker, its source, and core notes -
        # with the source history trimmed to the newest lines; everything
        # else the full context supplied is dropped and counted
        if rules and any(r.get("core") is None for r in rules):
            return {"variant": variant, "available": False,
                    "reason": "bundle's rule snapshot carries no core flags"}
        tip = (bundle.get("run") or {}).get("tip") or (bundle.get("manifest") or {}).get("tip") or {}
        ticker = str(tip.get("ticker") or "").upper()
        source = str(tip.get("source") or "")
        core_r = [r for r in rules if r.get("core")]
        keep_n = [n for n in notes if n.get("core") or str(n.get("scope") or "") in (f"ticker:{ticker}", f"source:{source}")]
        return {"variant": variant, "available": True,
                "rulesText": format_rules(core_r), "notesText": format_notes(keep_n),
                "ruleIds": [r.get("id") for r in core_r], "noteIds": [n.get("id") for n in keep_n],
                "rulesSupplied": len(core_r), "notesSupplied": len(keep_n),
                "dropped": (len(rules) - len(core_r)) + (len(notes) - len(keep_n)),
                "rulesHash": _sha(_canonical([r.get("id") for r in core_r]))[:12],
                "starterRules": not core_r, "historyLines": COMPACT_HISTORY_LINES,
                "selection": {"rules": "core only", "notes": f"core + ticker:{ticker} + source:{source}",
                              "history": f"newest {COMPACT_HISTORY_LINES} lines"},
                **({"degenerate": "no core rules in the bundle - starter rules supplied"}
                   if not core_r else {})}
    if variant == "no_knowledge":
        return {"variant": variant, "available": True,
                "rulesText": format_rules([]), "notesText": format_notes([]),
                "ruleIds": [], "noteIds": [], "rulesSupplied": 0, "notesSupplied": 0,
                "dropped": len(rules) + len(notes), "rulesHash": None, "starterRules": True}
    return {"variant": variant, "available": False, "reason": f"unknown variant {variant!r}"}


# -------------------------------------------------------------------- replay
def _call_key(tool: str, args: dict) -> str:
    return f"{tool}|{_canonical(args or {})}"


class _Served:
    """Serves tool calls from the bundle - never from a feed."""

    def __init__(self, bundle: dict):
        self.outputs: dict[str, list] = {}
        for t in bundle.get("toolOutputs") or []:
            self.outputs.setdefault(_call_key(t["tool"], t.get("args") or {}), []).append(t["result"])
        self.served: list[dict] = []
        self.missing: list[dict] = []
        self.proposed_notes: list[dict] = []

    def call(self, tool: str, args: dict) -> dict:
        if tool == "save_note":
            self.proposed_notes.append({"scope": args.get("scope"), "text": args.get("text")})
            return {"saved": True, "frozen": True,
                    "note": "captured on the frozen report as a PROPOSED note - not written"}
        key = _call_key(tool, args)
        bucket = self.outputs.get(key)
        if bucket:
            out = bucket.pop(0) if len(bucket) > 1 else bucket[0]
            self.served.append({"tool": tool, "args": args})
            return out if isinstance(out, dict) else {"result": out}
        self.missing.append({"tool": tool, "args": args})
        return {"error": f"frozen replay - {tool} was not called with these arguments in the "
                         "original run, so its output is not in the bundle; the input stays "
                         "missing (a frozen replay never fetches today's data)"}


def _protections(op) -> dict:
    return {"targets": bool(getattr(op, "exit_targets", None)),
            "underlyingStop": getattr(op, "underlying_stop", None) is not None,
            "premiumStop": getattr(op, "premium_stop_pct", None) is not None,
            "holdCap": getattr(op, "max_hold_sessions", None) is not None}


def _report_hash(report: dict) -> str:
    keep = {k: report.get(k) for k in
            ("bundleId", "variant", "headerSha", "systemSha", "verdict", "contract", "limitPrice",
             "quantity", "confidence", "entryMode", "usedNotes", "protections", "noVerdict",
             "toolCalls", "proposedNotes", "knowledge", "decisionChanged", "error")}
    return _sha(_canonical(keep))


async def replay(bundle: dict, *, variant: str, client, model: str | None = None,
                 max_tools: int | None = None, max_tokens: int | None = None) -> dict:
    """One isolated replay. Inputs: the bundle and an LLM client - nothing
    else. Returns the report (never raises for a model failure: a no-verdict
    is a measured outcome)."""
    from .analyst import SYSTEM, TOOLS, AnalystOpinion, _parse_opinion

    kv = variant_knowledge(bundle, variant)
    base = {"bundleId": bundle.get("id"), "variant": variant, "at": _iso(dt.datetime.now(dt.timezone.utc)),
            "baseline": {"verdict": ((bundle.get("run") or {}).get("opinion") or {}).get("verdict"),
                         "contract": ((bundle.get("run") or {}).get("opinion") or {}).get("contract"),
                         "runId": (bundle.get("run") or {}).get("id")},
            "bundleGaps": list(bundle.get("gaps") or [])}
    if not kv.get("available"):
        rep = {**base, "skipped": True, "reason": kv.get("reason"), "noVerdict": True,
               "knowledge": kv, "toolCalls": {"served": 0, "missing": 0}, "proposedNotes": []}
        rep["reportHash"] = _report_hash(rep)
        return rep

    man = bundle.get("manifest") or {}
    settings = bundle.get("settings") or {}
    header, header_gaps = _rebuild_header(man, rules_text=kv["rulesText"], notes_text=kv["notesText"],
                                          history_lines=kv.get("historyLines"))
    if man.get("exact") and man.get("system"):
        system = str(man["system"])
        system_gap = None
    else:
        system = SYSTEM + json.dumps(AnalystOpinion.model_json_schema(), separators=(",", ":"))
        system_gap = "system prompt not captured - the CURRENT prompt was used"
    model = model or (bundle.get("run") or {}).get("model") or str(settings.get("techniques.tip.analyst_model") or "")
    if not model:
        rep = {**base, "skipped": True, "reason": "no model on the bundle and none given",
               "noVerdict": True, "knowledge": kv, "toolCalls": {"served": 0, "missing": 0},
               "proposedNotes": []}
        rep["reportHash"] = _report_hash(rep)
        return rep
    max_tools = int(max_tools if max_tools is not None else (settings.get("techniques.tip.analyst_max_tools") or 8))
    max_tokens = int(max_tokens if max_tokens is not None else (settings.get("techniques.tip.analyst_max_output_tokens") or 3000))

    served = _Served(bundle)
    messages: list = [{"role": "user", "content": header}]
    usage = {"in": 0, "out": 0, "calls": 0, "stops": [], "cacheRead": 0, "cacheCreation": 0}
    tools_used = 0
    text: str | None = None
    error: str | None = None
    t0 = time.perf_counter()
    try:
        for _ in range(max_tools + 2):
            resp = await client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                                messages=messages, tools=TOOLS)
            usage["calls"] += 1
            usage["stops"].append(str(getattr(resp, "stop_reason", None)))
            u = getattr(resp, "usage", None)
            if u is not None:
                usage["in"] += int(getattr(u, "input_tokens", 0) or 0)
                usage["out"] += int(getattr(u, "output_tokens", 0) or 0)
                # PROF-05: effective billed usage includes the cache side
                usage["cacheRead"] += int(getattr(u, "cache_read_input_tokens", 0) or 0)
                usage["cacheCreation"] += int(getattr(u, "cache_creation_input_tokens", 0) or 0)
            calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            think = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            if not calls:
                text = think
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for c in calls:
                args = dict(c.input)
                if tools_used >= max_tools:
                    out = {"error": "tool budget exhausted - answer now"}
                else:
                    out = served.call(c.name, args)
                    tools_used += 1
                results.append({"type": "tool_result", "tool_use_id": c.id,
                                "content": json.dumps(out, default=str)[:6000]})
            messages.append({"role": "user", "content": results})
            if tools_used >= max_tools:
                messages.append({"role": "user", "content":
                                 "Tool budget exhausted. Reply with ONLY the JSON "
                                 "opinion object now - request no more tools."})
    except Exception as exc:                     # a provider failure is an outcome
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
    latency_ms = (time.perf_counter() - t0) * 1000.0

    opinion = None
    if text is not None and error is None:
        try:
            opinion = _parse_opinion(text)
        except ValueError as exc:
            error = f"no parseable opinion: {exc}"
    baseline_verdict = base["baseline"]["verdict"]
    rep = {
        **base,
        "model": model, "headerSha": _sha(header), "systemSha": _sha(system),
        "headerMatchesOriginal": bool(man.get("exact") and man.get("headerSha") == _sha(header)),
        "manifestGaps": header_gaps + ([system_gap] if system_gap else []),
        "knowledge": {k: v for k, v in kv.items() if k not in ("rulesText", "notesText")},
        "verdict": opinion.verdict if opinion else None,
        "contract": opinion.contract if opinion else None,
        "limitPrice": opinion.limit_price if opinion else None,
        "quantity": opinion.quantity if opinion else None,
        "confidence": opinion.confidence if opinion else None,
        "entryMode": getattr(opinion, "entry_mode", None) if opinion else None,
        "usedNotes": list(opinion.used_notes or []) if opinion else [],
        "protections": _protections(opinion) if opinion else None,
        "rationale": (opinion.rationale[:600] if opinion and opinion.rationale else None),
        "noVerdict": opinion is None,
        "error": error,
        "decisionChanged": (opinion is not None and baseline_verdict is not None
                            and opinion.verdict != baseline_verdict),
        "latencyMs": round(latency_ms, 1),
        "tokens": {"in": usage["in"], "out": usage["out"], "calls": usage["calls"],
                   "stops": usage["stops"], "cacheRead": usage["cacheRead"], "cacheCreation": usage["cacheCreation"],
                   "effectiveInput": usage["in"] + usage["cacheRead"] + usage["cacheCreation"]},
        "headerChars": len(header),
        "toolCalls": {"served": len(served.served), "missing": len(served.missing),
                      "servedCalls": served.served, "missingCalls": served.missing},
        "proposedNotes": served.proposed_notes,     # captured, NEVER written
    }
    rep["reportHash"] = _report_hash(rep)
    return rep


async def persist_replay(sf, report: dict, *, journal=None) -> str:
    """Insert-only evidence row for one replay report."""
    rid = new_id()
    async with sf() as session:
        session.add(TipFrozenReplay(id=rid, bundle_id=str(report.get("bundleId") or ""),
                                    variant=str(report.get("variant") or "")[:32],
                                    report_hash=str(report.get("reportHash") or ""), report=report))
        await session.commit()
    if journal is not None:
        try:
            await journal.append(ev.TIP_FROZEN_REPLAY,
                                 {"replayId": rid, "bundleId": report.get("bundleId"),
                                  "variant": report.get("variant"), "verdict": report.get("verdict"),
                                  "noVerdict": report.get("noVerdict"),
                                  "decisionChanged": report.get("decisionChanged"),
                                  "toolCalls": {k: report.get("toolCalls", {}).get(k) for k in ("served", "missing")},
                                  "proposedNotes": len(report.get("proposedNotes") or []),
                                  "reportHash": report.get("reportHash")},
                                 aggregate_type="signal",
                                 aggregate_id=str(((report.get("baseline") or {}).get("runId")) or report.get("bundleId")))
        except Exception:
            log.debug("replay journal failed", exc_info=True)
    return rid


def compare(reports: list[dict]) -> dict:
    """Side-by-side of the variants' reports for ONE bundle. Counts and
    differences only - no ranking, no 'better'."""
    by_variant: dict[str, list[dict]] = {}
    for r in reports:
        by_variant.setdefault(str(r.get("variant")), []).append(r)
    rows = {}
    for v, rs in by_variant.items():
        n = len(rs)
        verdicts = [r.get("verdict") for r in rs]
        rows[v] = {
            "runs": n,
            "verdicts": verdicts,
            "noVerdictRate": (sum(1 for r in rs if r.get("noVerdict")) / n) if n else None,
            "decisionChangedVsBaseline": sum(1 for r in rs if r.get("decisionChanged")),
            "protectionsPresent": [r.get("protections") for r in rs],
            "grounding": {"usedNotes": [r.get("usedNotes") for r in rs],
                          "rulesSupplied": [(r.get("knowledge") or {}).get("rulesSupplied") for r in rs],
                          "notesSupplied": [(r.get("knowledge") or {}).get("notesSupplied") for r in rs]},
            "toolCalls": {"served": sum((r.get("toolCalls") or {}).get("served", 0) for r in rs),
                          "missing": sum((r.get("toolCalls") or {}).get("missing", 0) for r in rs)},
            "proposedNotes": sum(len(r.get("proposedNotes") or []) for r in rs),
            "latencyMs": [r.get("latencyMs") for r in rs],
            "tokens": [r.get("tokens") for r in rs],
            "headerChars": [r.get("headerChars") for r in rs],
            "contracts": [r.get("contract") for r in rs],
            "stops": [((r.get("protections") or {}).get("underlyingStop"), (r.get("protections") or {}).get("premiumStop")) for r in rs],
            "quantities": [r.get("quantity") for r in rs],
            "skipped": [r.get("reason") for r in rs if r.get("skipped")],
            "reportHashes": [r.get("reportHash") for r in rs],
        }
    baseline = next(((r.get("baseline") or {}) for r in reports), {})
    verdict_sets = {v: sorted({str(x) for x in d["verdicts"]}) for v, d in rows.items()}
    return {"bundleId": next((r.get("bundleId") for r in reports), None),
            "baseline": baseline, "variants": rows,
            "decisionDiffers": len({tuple(s) for s in verdict_sets.values()}) > 1,
            "evidence": ("adequate" if reports and not any(r.get("skipped") for r in reports)
                         and all(not r.get("noVerdict") for r in reports) else "insufficient"),
            "disclaimer": ("Counts and differences on ONE frozen case under isolated replays. "
                           "No profitability, quality or equivalence claim is made or implied; "
                           "promotion of any variant is a separate reviewed verdict.")}
