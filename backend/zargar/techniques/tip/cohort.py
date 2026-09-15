"""Entry-variant COHORT (KFIN-09, 2026-09-14).

Prospective sampling of the FULL eligible idea cohort: every extracted
actionable open/add signal is recorded at its intake decision - proposals,
auto-approvals, analyst declines, blocked/review-gated cards, at-level arms,
skips, shadows, parks, replays and verification failures alike. `TipEntryStudy`
(proposals.py) only ever saw the proposal path; the denominator here is the
idea, not the card.

Each row keeps the times SEPARATE (source post, receipt, decision), the exact
source instrument and the proposed one, the source-stated premium, the
qualified quote at decision with its own freshness + provenance, the gaps, and
the delayed sample's status. A later sample is a LATER observation
(`sampleKind: delayed`) - "unknown at alert" stays unknown and nothing here
labels a later sample as alert-time evidence.

The declared entry variants (immediate / N-minute delay / premium cap) are
SIMULATED per row under identical budget, fee and fill assumptions into
separate result books (`tip_entry_variant_results`, book = variant:<name>).
They never touch a Portfolio, never place an order, never claim a P&L: the
report separates "evidence adequate" from "insufficient" per row and variant.
Everything is inert until `techniques.tip.entry_cohort_enabled` is on.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import math

from sqlalchemy import select

from ... import events as ev
from ...domain import new_id
from ...models import (DiscordMessage, Proposal, Signal, TipEntryCohortRow,
                       TipEntryVariantResult)

log = logging.getLogger("zargar.tip.cohort")

ELIGIBLE_ACTIONS = ("open", "add")
VARIANTS = ("immediate", "delay", "cap")
DISCLAIMER = ("Entry-variant simulation on the eligible idea cohort under identical budget, "
              "fee and fill assumptions. Fills are hypothetical entries only; no profitability "
              "or equivalence claim is made or implied. Rows marked insufficient lack the "
              "evidence the variant needs and are never filled in.")
_missed_grace_factor = 4.0     # a delayed sample later than due + factor x delay is MISSED


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(x) -> str | None:
    return x.isoformat() if hasattr(x, "isoformat") else (str(x) if x is not None else None)


def is_eligible(sig_or_row, experiment: str | None = None) -> bool:
    """Every actionable open/add idea; experiment samples never (they are
    out-of-band evidence, PLATFORM-RULES invariants 12-13)."""
    if experiment is not None:
        return False
    action = str(getattr(sig_or_row, "action", "") or "")
    return bool(getattr(sig_or_row, "is_actionable", False)) and action in ELIGIBLE_ACTIONS


def source_instrument(row) -> dict:
    """The EXACT instrument the source stated; the OCC symbol only when the
    contract is fully stated (strike + expiry + call/put) - never guessed."""
    out = {"ticker": row.ticker, "direction": row.direction,
           "instrument": row.instrument or "unspecified", "strike": row.strike,
           "expiry": row.expiry, "dteHintDays": getattr(row, "dte_hint_days", None),
           "occ": None}
    if (row.instrument in ("call", "put")) and row.strike and row.expiry:
        with contextlib.suppress(Exception):
            from ...options import occ as occ_mod
            out["occ"] = occ_mod.make(row.ticker, row.expiry, "C" if row.instrument == "call" else "P",
                                      float(row.strike)).symbol
    return out


def classify_decision(row, *, status: str, proposal: dict | None, armed: dict | None,
                      appraised: bool) -> tuple[str, str | None]:
    """(decision, reason) from the intake's final state. Every disposition
    lands somewhere - a skip is a decision, so is a blocked card."""
    op = (row.extraction or {}).get("analyst") or {}
    verdict = op.get("verdict")
    rationale = (op.get("rationale") or "")[:300]
    if armed:
        return "armed", f"analyst at-level arm (run {str(armed.get('runId') or '')[:8]})"
    if proposal:
        ctx = proposal.get("context") or {}
        if ctx.get("autoGate"):
            return "blocked", str(ctx["autoGate"])[:300]
        if ctx.get("reviewRequired"):
            return "blocked", f"geometry review required: {ctx['reviewRequired']}"[:300]
        st = str(proposal.get("status") or "pending")
        if st == "rejected":
            return "declined", f"{proposal.get('decidedVia') or 'rejected'}: {rationale}"[:300]
        if st in ("approved", "filled", "submitted"):
            return "auto_approved", f"analyst {verdict}: {rationale}"[:300]
        return "proposed", f"waiting for a human ({st}); analyst {verdict or 'n/a'}"[:300]
    if status == "verified":
        if verdict in ("skip", "watch"):
            return "skipped", f"analyst {verdict}: {rationale}"[:300]
        if verdict is None and appraised:
            return "no_verdict", "appraisal produced no verdict"
        return "skipped", "verified, no proposal (policy mode / conviction / no vehicle)"
    if status in ("shadow", "parked", "replayed", "verification_failed"):
        failed = [c.get("name") for c in (row.verification or {}).get("checks", [])
                  if not c.get("passed")]
        return status, ("; ".join(failed) if failed else None)
    return str(status or "unknown"), None


def _snap_quote(eng, sym: str, *, max_age_s: float, kind: str) -> tuple[dict | None, str]:
    """(quote record, status) for a symbol from the engine's quote store -
    never fetched anew here; freshness judged on the SOURCE print's age."""
    q = eng.quotes.get(sym)
    if q is None:
        return None, "missing"
    now_ms = int(_utcnow().timestamp() * 1000)
    src_ts = int(getattr(q, "source_ts", 0) or 0) or int(getattr(q, "ts", 0) or 0)
    age_s = max(0.0, (now_ms - src_ts) / 1000.0) if src_ts else None
    rec = {"symbol": sym, "bid": q.bid, "ask": q.ask, "last": q.last,
           "source": getattr(q, "source", "") or "feed", "sourceTs": src_ts,
           "ageSeconds": round(age_s, 1) if age_s is not None else None,
           "delayed": bool(getattr(q, "delayed", False)),
           "sampledAt": _iso(_utcnow()), "sampleKind": kind}
    if age_s is None:
        return rec, "stale"
    return rec, ("fresh" if age_s <= max_age_s else "stale")


async def _posted_at(eng, content) -> dt.datetime | None:
    meta = (getattr(content, "meta", None) or {})
    mid = meta.get("messageId")
    if mid:
        async with eng.sf() as session:
            m = await session.get(DiscordMessage, str(mid))
        if m is not None and m.posted_at:
            return m.posted_at
    posted = meta.get("postedAt")
    if posted:
        with contextlib.suppress(ValueError, TypeError):
            d = dt.datetime.fromisoformat(str(posted))
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    return None


def _row_dict(r: TipEntryCohortRow) -> dict:
    return {"id": r.id, "signalId": r.signal_id, "contentId": r.content_id, "source": r.source,
            "ticker": r.ticker, "action": r.action, "decisionKind": r.decision_kind,
            "postedAt": _iso(r.posted_at), "receivedAt": _iso(r.received_at),
            "decidedAt": _iso(r.decided_at), "decision": r.decision,
            "decisionReason": r.decision_reason, "sourceInstrument": r.source_instrument,
            "proposedInstrument": r.proposed_instrument, "sourcePremium": r.source_premium,
            "quoteSymbol": r.quote_symbol, "quoteAtDecision": r.quote_at_decision,
            "quoteStatus": r.quote_status, "delayedSample": r.delayed_sample,
            "delayedStatus": r.delayed_status, "delayedDueAt": _iso(r.delayed_due_at),
            "gaps": list(r.gaps or [])}


async def record_idea(eng, *, row, content, status: str, proposal: dict | None = None,
                      armed: dict | None = None, experiment: str | None = None,
                      appraised: bool = False, kind: str = "intake") -> dict | None:
    """Record one eligible idea at its decision. Returns the row dict, or None
    when the idea is not eligible / the cohort is off. Never raises into the
    intake (callers wrap it); never places anything."""
    s = eng.settings
    if not bool(s.get("techniques.tip.entry_cohort_enabled", False)):
        return None
    if not is_eligible(row, experiment):
        return None
    async with eng.sf() as session:               # the freshest state of the signal
        db = await session.get(Signal, row.id)
        if db is not None:
            row = db
        if content is None and row.raw_content_id:
            from ...models import RawContent
            content = await session.get(RawContent, row.raw_content_id)
        if proposal and proposal.get("id"):
            p = await session.get(Proposal, proposal["id"])
            if p is not None:
                from ...approvals.proposals import proposal_dict
                proposal = proposal_dict(p)
    decision, reason = classify_decision(row, status=status, proposal=proposal, armed=armed,
                                         appraised=appraised)
    gaps: list[str] = []
    src = source_instrument(row)
    if row.instrument in ("call", "put", "either", "unspecified") and not src["occ"]:
        gaps.append("no exact source contract (strike/expiry/right not all stated)")
    proposed = None
    if proposal:
        ctx = proposal.get("context") or {}
        proposed = {"kind": "proposal", "proposalId": proposal.get("id"),
                    "symbol": proposal.get("symbol"), "secType": proposal.get("secType"),
                    "limit": proposal.get("limitPrice"), "qty": proposal.get("qty"),
                    "vehicle": ctx.get("vehicle"), "status": proposal.get("status")}
    elif armed:
        proposed = {"kind": "arm", "armedRunId": armed.get("runId"),
                    "entryLevel": ((row.extraction or {}).get("analyst") or {}).get("entry_level")}
    premium = row.premium
    if premium is None:
        gaps.append("no source-stated premium")
    posted_at = await _posted_at(eng, content)
    if posted_at is None:
        gaps.append("source post time unknown (no mirrored message)")
    received_at = getattr(content, "received_at", None)
    # the symbol the variants would price: the proposed contract, else the
    # source's exact contract, else the shares
    sym = None
    if proposed and proposed.get("kind") == "proposal" and proposed.get("symbol"):
        sym = str(proposed["symbol"])
    elif src["occ"]:
        sym = src["occ"]
    elif (row.instrument or "unspecified") in ("shares", "unspecified") and not src["strike"]:
        sym = row.ticker
    max_age = float(s.get("techniques.tip.entry_cohort_quote_max_age_seconds", 300.0) or 300.0)
    quote, qstatus = (None, "missing")
    if sym:
        quote, qstatus = _snap_quote(eng, sym, max_age_s=max_age, kind="decision")
        if quote is None and sym != row.ticker:
            with contextlib.suppress(Exception):     # best-effort ONE observation
                await asyncio.wait_for(eng.options.refresh_now(sym), timeout=5.0)
            quote, qstatus = _snap_quote(eng, sym, max_age_s=max_age, kind="decision")
    else:
        gaps.append("no priceable instrument at decision")
    if quote is None:
        gaps.append("no quote at decision")
    elif qstatus == "stale":
        gaps.append(f"decision quote stale ({quote.get('ageSeconds')}s > {max_age:g}s)")
    delay_min = float(s.get("techniques.tip.entry_cohort_delay_minutes", 3.0) or 3.0)
    now = _utcnow()
    delayed_status = "pending" if sym else "unknown"
    due = now + dt.timedelta(minutes=delay_min) if sym else None
    cid = new_id()
    crow = TipEntryCohortRow(
        id=cid, signal_id=row.id, content_id=getattr(content, "id", None),
        source=row.source_name, ticker=row.ticker, action=row.action, decision_kind=kind,
        posted_at=posted_at, received_at=received_at, decided_at=now,
        decision=decision, decision_reason=reason, source_instrument=src,
        proposed_instrument=proposed, source_premium=premium, quote_symbol=sym,
        quote_at_decision=quote, quote_status=qstatus, delayed_sample=None,
        delayed_status=delayed_status, delayed_due_at=due, gaps=gaps)
    async with eng.sf() as session:
        session.add(crow)
        await session.commit()
    # journal the DECISION record - quotes are never journaled (hard rule)
    with contextlib.suppress(Exception):
        await eng.journal.append(ev.TIP_ENTRY_COHORT,
                                 {"cohortId": cid, "signalId": row.id, "decision": decision,
                                  "decisionKind": kind, "reason": reason,
                                  "quoteSymbol": sym, "quoteStatus": qstatus,
                                  "delayedStatus": delayed_status, "gaps": gaps,
                                  "postedAt": _iso(posted_at), "receivedAt": _iso(received_at),
                                  "decidedAt": _iso(now)},
                                 aggregate_type="signal", aggregate_id=row.id)
    if sym and due is not None:
        task = asyncio.create_task(_delayed_sample(eng, cid, sym, due),
                                   name=f"tip-cohort-delay-{cid[:8]}")
        tasks = getattr(eng, "_tip_cohort_tasks", None)
        if tasks is None:
            tasks = eng._tip_cohort_tasks = set()
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    return _row_dict(crow)


async def _delayed_sample(eng, cohort_id: str, sym: str, due: dt.datetime) -> None:
    wait = (due - _utcnow()).total_seconds()
    if wait > 0:
        await asyncio.sleep(wait)
    with contextlib.suppress(Exception):
        await sample_one(eng, cohort_id)


async def sample_one(eng, cohort_id: str, *, now: dt.datetime | None = None) -> dict | None:
    """Take the configured LATER sample for one pending row (idempotent: a
    row that is no longer pending is left alone). Labeled `delayed`; a
    sample far past its due time is MISSED, never back-labeled."""
    now = now or _utcnow()
    s = eng.settings
    max_age = float(s.get("techniques.tip.entry_cohort_quote_max_age_seconds", 300.0) or 300.0)
    delay_min = float(s.get("techniques.tip.entry_cohort_delay_minutes", 3.0) or 3.0)
    async with eng.sf() as session:
        r = await session.get(TipEntryCohortRow, cohort_id)
        if r is None or r.delayed_status != "pending" or not r.quote_symbol:
            return _row_dict(r) if r else None
        if r.delayed_due_at and now < r.delayed_due_at:
            return _row_dict(r)
        gaps = list(r.gaps or [])
        if r.delayed_due_at and (now - r.delayed_due_at).total_seconds() > _missed_grace_factor * delay_min * 60:
            r.delayed_status = "missed"
            gaps.append("delayed sample missed (process was not running at the due time)")
            r.gaps = gaps
            await session.commit()
            return _row_dict(r)
        sym = r.quote_symbol
    quote, qstatus = _snap_quote(eng, sym, max_age_s=max_age, kind="delayed")
    if quote is None and sym != (r.ticker if r else sym):
        with contextlib.suppress(Exception):
            await asyncio.wait_for(eng.options.refresh_now(sym), timeout=5.0)
        quote, qstatus = _snap_quote(eng, sym, max_age_s=max_age, kind="delayed")
    async with eng.sf() as session:
        r = await session.get(TipEntryCohortRow, cohort_id)
        if r is None or r.delayed_status != "pending":
            return _row_dict(r) if r else None
        gaps = list(r.gaps or [])
        if quote is None:
            r.delayed_status = "missed"
            gaps.append("delayed sample: no quote")
        else:
            r.delayed_sample = {**quote, "quoteStatus": qstatus,
                                "measuredFrom": "decision", "note": "a LATER observation, never alert-time evidence"}
            r.delayed_status = "sampled"
            if qstatus == "stale":
                gaps.append(f"delayed sample stale ({quote.get('ageSeconds')}s)")
        r.gaps = gaps
        await session.commit()
        return _row_dict(r)


async def sample_due(eng, *, now: dt.datetime | None = None) -> int:
    """Catch-up for pending rows whose due time has passed (a restart loses
    the in-process timer; the row stays visibly pending until this runs)."""
    now = now or _utcnow()
    async with eng.sf() as session:
        ids = (await session.execute(
            select(TipEntryCohortRow.id).where(TipEntryCohortRow.delayed_status == "pending",
                                               TipEntryCohortRow.delayed_due_at <= now))).scalars().all()
    n = 0
    for cid in ids:
        with contextlib.suppress(Exception):
            await sample_one(eng, cid, now=now)
            n += 1
    return n


# ------------------------------------------------------------------ variants
def assumptions(settings) -> dict:
    """The ONE set of budget / fee / fill assumptions every variant uses."""
    budget = float(settings.get("techniques.tip.budget_per_tip", 1000.0) or 0)
    prem_cap = float(settings.get("techniques.tip.max_premium_per_tip", 750.0) or 0)
    return {
        "optionBudget": min(budget, prem_cap) if prem_cap > 0 else budget,
        "sharesBudget": budget,
        "maxContracts": int(settings.get("techniques.tip.max_contracts_per_tip", 25) or 25),
        "feePerContract": float(settings.get("options.fee_per_contract", 0.0) or 0)
                          + float(settings.get("sim.reg_fee_per_contract", 0.0) or 0),
        "stockCommission": float(settings.get("sim.stock_commission", 0.0) or 0),
        "fill": "buy at the sample's ask (marketable limit), whole units, no partial fills, no slippage beyond the ask",
        "delayMinutes": float(settings.get("techniques.tip.entry_cohort_delay_minutes", 3.0) or 3.0),
        "premiumCap": float(settings.get("techniques.tip.entry_cohort_premium_cap", 1.05) or 1.05),
        "quoteMaxAgeSeconds": float(settings.get("techniques.tip.entry_cohort_quote_max_age_seconds", 300.0) or 300.0),
    }


def _fill(sample: dict, *, is_option: bool, a: dict) -> dict:
    ask = float(sample.get("ask") or 0)
    if ask <= 0:
        return {"filled": False, "reason": "sample has no ask"}
    if is_option:
        qty = min(a["maxContracts"], int(math.floor(a["optionBudget"] / (ask * 100))))
        if qty < 1:
            return {"filled": False, "reason": "no contract fits the budget at the ask"}
        return {"filled": True, "price": ask, "qty": qty, "cost": round(ask * qty * 100, 2),
                "fees": round(a["feePerContract"] * qty, 2)}
    qty = int(math.floor(a["sharesBudget"] / ask))
    if qty < 1:
        return {"filled": False, "reason": "no share fits the budget at the ask"}
    return {"filled": True, "price": ask, "qty": qty, "cost": round(ask * qty, 2),
            "fees": round(a["stockCommission"], 2)}


def simulate_variants(row: dict, a: dict, *, variants=VARIANTS) -> list[dict]:
    """Pure: one result per variant for one cohort row dict. `adequate`
    means the variant had the evidence it needs; `fill` is a hypothetical
    entry (or None). Nothing is marked-to-market here."""
    is_option = bool((row.get("quoteSymbol") or "") != (row.get("ticker") or "")) and bool(row.get("quoteSymbol"))
    q = row.get("quoteAtDecision")
    d = row.get("delayedSample")
    out = []
    for v in variants:
        res = {"variant": v, "book": f"variant:{v}", "cohortId": row.get("id"),
               "signalId": row.get("signalId"), "decision": row.get("decision"),
               "adequate": False, "reason": None, "sampleKind": None, "fill": None,
               "assumptions": {k: a[k] for k in ("optionBudget", "sharesBudget", "maxContracts",
                                                 "feePerContract", "stockCommission", "fill")}}
        if not row.get("quoteSymbol"):
            res["reason"] = "no priceable instrument"
        elif v == "immediate":
            if q is None:
                res["reason"] = "no quote at decision"
            elif row.get("quoteStatus") != "fresh":
                res["reason"] = f"decision quote {row.get('quoteStatus')} (age {q.get('ageSeconds')}s)"
            else:
                res.update(adequate=True, sampleKind="decision", fill=_fill(q, is_option=is_option, a=a))
        elif v == "delay":
            res["assumptions"]["delayMinutes"] = a["delayMinutes"]
            st = row.get("delayedStatus")
            if st == "pending":
                res["reason"] = "delayed sample pending"
            elif st != "sampled" or d is None:
                res["reason"] = f"delayed sample {st}"
            elif d.get("quoteStatus") != "fresh":
                res["reason"] = f"delayed sample {d.get('quoteStatus')} (age {d.get('ageSeconds')}s)"
            else:
                res.update(adequate=True, sampleKind="delayed", fill=_fill(d, is_option=is_option, a=a))
        elif v == "cap":
            res["assumptions"]["premiumCap"] = a["premiumCap"]
            prem = row.get("sourcePremium")
            if not is_option:
                res["reason"] = "cap variant applies to option ideas only"
            elif prem is None:
                res["reason"] = "no source-stated premium"
            elif q is None:
                res["reason"] = "no quote at decision"
            elif row.get("quoteStatus") != "fresh":
                res["reason"] = f"decision quote {row.get('quoteStatus')} (age {q.get('ageSeconds')}s)"
            else:
                ask = float(q.get("ask") or 0)
                limit = round(float(prem) * a["premiumCap"], 4)
                res["adequate"] = True
                res["sampleKind"] = "decision"
                if ask <= 0:
                    res["fill"] = {"filled": False, "reason": "sample has no ask"}
                elif ask > limit:
                    res["fill"] = {"filled": False, "reason": f"ask {ask:g} above cap {limit:g} "
                                                              f"({a['premiumCap']:g}x stated {float(prem):g})"}
                else:
                    res["fill"] = _fill(q, is_option=True, a=a)
                    res["fill"]["capLimit"] = limit
        else:
            res["reason"] = f"unknown variant {v}"
        out.append(res)
    return out


async def compute_results(eng_or_sf, settings, *, since: dt.datetime | None = None,
                          variants=VARIANTS) -> list[dict]:
    """Simulate every variant for every cohort row and store the results in
    their separate books (deterministic ids, recomputable)."""
    sf = getattr(eng_or_sf, "sf", eng_or_sf)
    a = assumptions(settings)
    async with sf() as session:
        q = select(TipEntryCohortRow).order_by(TipEntryCohortRow.decided_at.asc())
        if since is not None:
            q = q.where(TipEntryCohortRow.decided_at >= since)
        rows = (await session.execute(q)).scalars().all()
        results = []
        for r in rows:
            for res in simulate_variants(_row_dict(r), a, variants=variants):
                rid = f"{r.id}:{res['variant']}"
                await session.merge(TipEntryVariantResult(
                    id=rid, cohort_id=r.id, variant=res["variant"], book=res["book"],
                    adequate=bool(res["adequate"]), result=res, computed_at=_utcnow()))
                results.append({**res, "id": rid})
        await session.commit()
    return results


async def cohort_report(eng_or_sf, settings, *, since: dt.datetime | None = None,
                        variants=VARIANTS, recompute: bool = True) -> dict:
    """The denominator (every eligible idea by decision), each variant's
    adequate/insufficient/filled counts, and the per-row detail. Separates
    evidence-adequate rows from insufficient ones; never a P&L."""
    sf = getattr(eng_or_sf, "sf", eng_or_sf)
    if recompute:
        await compute_results(eng_or_sf, settings, since=since, variants=variants)
    async with sf() as session:
        q = select(TipEntryCohortRow).order_by(TipEntryCohortRow.decided_at.asc())
        if since is not None:
            q = q.where(TipEntryCohortRow.decided_at >= since)
        rows = [_row_dict(r) for r in (await session.execute(q)).scalars().all()]
        ids = [r["id"] for r in rows]
        res_rows = ((await session.execute(
            select(TipEntryVariantResult).where(TipEntryVariantResult.cohort_id.in_(ids))))
                    .scalars().all()) if ids else []
    by_decision: dict[str, int] = {}
    for r in rows:
        by_decision[r["decision"]] = by_decision.get(r["decision"], 0) + 1
    per_variant: dict[str, dict] = {}
    for x in res_rows:
        v = per_variant.setdefault(x.variant, {"book": x.book, "rows": 0, "adequate": 0,
                                               "insufficient": 0, "filled": 0, "noFill": 0,
                                               "insufficientReasons": {}})
        v["rows"] += 1
        if x.adequate:
            v["adequate"] += 1
            if (x.result.get("fill") or {}).get("filled"):
                v["filled"] += 1
            else:
                v["noFill"] += 1
        else:
            v["insufficient"] += 1
            why = str(x.result.get("reason") or "?")
            v["insufficientReasons"][why] = v["insufficientReasons"].get(why, 0) + 1
    return {
        "since": _iso(since), "generatedAt": _iso(_utcnow()),
        "denominator": {"ideas": len(rows), "byDecision": by_decision,
                        "quoteStatus": {k: sum(1 for r in rows if r["quoteStatus"] == k)
                                        for k in ("fresh", "stale", "missing")},
                        "delayedStatus": {k: sum(1 for r in rows if r["delayedStatus"] == k)
                                          for k in ("pending", "sampled", "missed", "unknown")},
                        "postTimeKnown": sum(1 for r in rows if r["postedAt"]),
                        "sourcePremiumKnown": sum(1 for r in rows if r["sourcePremium"] is not None)},
        "assumptions": assumptions(settings),
        "variants": per_variant,
        "evidence": {"adequateRows": sum(1 for x in res_rows if x.adequate),
                     "insufficientRows": sum(1 for x in res_rows if not x.adequate)},
        "rows": rows,
        "results": [{**x.result, "id": x.id} for x in res_rows],
        "disclaimer": DISCLAIMER,
    }


async def recovery_loop(eng, *, first_delay_s: float = 30.0, interval_s: float = 60.0) -> None:
    """Startup + periodic catch-up for pending delayed samples (review follow-up
    2026-09-15: `sample_due` had no caller, so a restart left samples pending
    for ever). Runs inside the app; a sample past its grace is MISSED, never
    back-labeled."""
    await asyncio.sleep(first_delay_s)
    while True:
        try:
            if bool(eng.settings.get("techniques.tip.entry_cohort_enabled", False)):
                n = await sample_due(eng)
                if n:
                    log.info("entry cohort: %d delayed sample(s) recovered", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("entry cohort delayed-sample recovery failed")
        await asyncio.sleep(interval_s)

