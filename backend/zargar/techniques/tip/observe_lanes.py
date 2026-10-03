"""Observe-only lanes from the 2026-10-02 review (W2.5, W2.6, W3.5). Each one JOURNALS what it would have done and
never places, blocks, sizes or times an order. Promotion of any lane is a preregistered decision (register:
docs/techniques/tip/research/EXPERIMENT-REGISTER.md) on real fills with date-clustered intervals.

- W3.5 fast lane (`TipFastLaneShadow`): at signal time, before the ~30 s appraisal, a deterministic pre-check says
  whether a clean, priced buy from an earned source would have been entered right away, with the NBBO it would have
  paid. Graded against the analyst's actual decision and fill.
- W2.6 starter lane (`TipStarterShadow`): when the only reason a take cannot be sized is stop width (no quantity fits
  the risk budget), the 1-lot starter that would have been bought and its risk.
- W2.5 second opinion (`TipSecondOpinionCandidate`): a verified buy the analyst SKIPPED on a judgement call
  (geometry / reach / chase / identity) - the candidate set a frozen-replay A/B re-asks with the opposite framing.
"""
from __future__ import annotations

import contextlib
import logging
import re
import time

log = logging.getLogger("zargar.tip.observe")

JUDGEMENT = re.compile(r"\b(reach|geometry|extended|chase|chasing|ran away|counter-?trend|tape|identity|"
                       r"cannot (?:identify|resolve)|no expiry|unresolv)", re.I)


def fast_lane_check(*, sig, verification: dict, earned: bool, quote, source_price: float | None,
                    band: float = 1.15) -> dict:
    """Pure: would the fast lane enter now? -> {would, reasons}."""
    reasons = []
    if str(getattr(sig, "direction", "long")) != "long":
        reasons.append("not a long buy")
    if str(getattr(sig, "action", "open") or "open") not in ("open", "add"):
        reasons.append("not an open")
    if not all(c.get("passed") or not c.get("fatal") for c in (verification or {}).get("checks") or []):
        reasons.append("verification failed")
    if not earned:
        reasons.append("source has not earned auto")
    if not source_price or source_price <= 0:
        reasons.append("no stated price")
    ask = float(getattr(quote, "ask", 0) or 0) if quote is not None else 0.0
    if ask <= 0:
        reasons.append("no live ask")
    elif source_price and ask > source_price * band:
        reasons.append(f"ask {ask:.2f} > {band:g}x the stated {source_price:.2f}")
    return {"would": not reasons, "reasons": reasons, "ask": ask or None}


async def record_fast_lane(eng, row, sig, verification: dict) -> None:
    if not bool(eng.settings.get("techniques.tip.observe_fast_lane", True)):
        return
    try:
        svc = getattr(eng, "signals_service", None)
        trust = await svc.source_trust(row.source_name or "unknown") if svc is not None else {"graded": 0}
        need_n = int(eng.settings.get("techniques.tip.auto_min_graded", 5))
        need_hit = float(eng.settings.get("techniques.tip.auto_min_hit", 0.4))
        explicit = (((eng.settings.get("techniques.tip.sources") or {}).get(row.source_name or "", {}) or {})
                    .get("mode") == "auto")
        earned = explicit or (trust.get("graded", 0) >= need_n and (trust.get("hitRate") or 0) >= need_hit)
        sym = row.ticker.upper()
        stated = sig.entry_price
        q = eng.quotes.get(sym)
        res = fast_lane_check(sig=sig, verification=verification, earned=earned, quote=q, source_price=stated)
        await eng.journal.append("TipFastLaneShadow", {
            "signalId": row.id, "symbol": sym, "source": row.source_name, **res, "statedPrice": stated,
            "bid": float(getattr(q, "bid", 0) or 0) or None if q is not None else None,
            "decidedMs": int(time.time() * 1000)}, aggregate_type="signal", aggregate_id=row.id)
    except Exception:                                      # noqa: BLE001 - observation never breaks intake
        log.debug("fast lane shadow failed", exc_info=True)


async def record_second_opinion_candidate(eng, row, opinion: dict, verification: dict) -> None:
    if not opinion or opinion.get("verdict") != "skip":
        return
    if not all(c.get("passed") for c in (verification or {}).get("checks") or [{"passed": False}]):
        return
    why = str(opinion.get("rationale") or "")
    m = JUDGEMENT.search(why)
    if not m:
        return
    with contextlib.suppress(Exception):
        await eng.journal.append("TipSecondOpinionCandidate", {
            "signalId": row.id, "symbol": row.ticker, "source": row.source_name, "cue": m.group(0),
            "runId": opinion.get("runId"), "rationale": why[:400]}, aggregate_type="signal", aggregate_id=row.id)


async def record_starter(eng, *, signal_id: str, symbol: str, sec_type: str, limit: float, risk_plan, pid: str) -> None:
    if risk_plan is None or "no quantity" not in str(getattr(risk_plan, "reviewRequired", "") or ""):
        return
    with contextlib.suppress(Exception):
        unit = float(getattr(risk_plan, "unitLoss", 0) or 0)
        await eng.journal.append("TipStarterShadow", {
            "signalId": signal_id, "symbol": symbol, "secType": sec_type, "limit": limit, "qty": 1,
            "unitRisk": round(unit, 2), "budget": getattr(risk_plan, "budget", None),
            "overBudgetX": round(unit / float(risk_plan.budget), 2) if getattr(risk_plan, "budget", None) else None,
            "portfolioId": pid}, aggregate_type="signal", aggregate_id=signal_id, portfolio_id=pid)
