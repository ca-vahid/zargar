"""Intake review relevance gate (review-gate-v1, 2026-09-19).

The intake REVIEW is the analyst's tool-using pass over a message that produced nothing tradable (a
discarded signal, or a no-ticker follow-up). It is where exits, trims, stop moves and disarms happen -
and, on 2026-09-09..18, 88% of those reviews changed nothing but a note while costing ~$0.68 each
(docs/techniques/tip/research/2026-09-19-economics-review.md).

A review can only MANAGE something the desk holds or waits on. This module decides, from the desk's
live state, whether the message can reach such an item:

* a message WITH tickers is relevant when any of them is an open managed tip position, an armed/paused
  tip plan, or a live proposal (any source - a trim from another room may still be about our position);
* a message WITHOUT tickers ("SL set for 1.45", "1st TP hit", "I'm out") is relevant when ITS SOURCE has
  an open position, an armed plan, or a proposal still pending or executed this session;
* an entry-shaped discard (a signal that did NOT fail `opens_position` - e.g. an implied call) keeps the
  review, so a possible missed entry is still read by the analyst.

`decide` is pure; `desk_items` reads the live state. Modes (`techniques.tip.review_gate`): `off` - no
decision; `observe` (default) - the decision is journaled (`TipReviewGate`) and the review still runs,
so skipped-would-have-managed cases are measured prospectively; `enforce` - an irrelevant message is
recorded and not reviewed. Entries (tradable signals) never pass through here - their appraisal path is
unchanged.
"""
from __future__ import annotations

import datetime as dt
import re

VERSION = "review-gate-v1"
MODES = ("off", "observe", "enforce")
_OCC = re.compile(r"^([A-Z.]{1,6})\d{6}[CP]\d{8}$")
_ET = dt.timezone(dt.timedelta(hours=-4))


def root(symbol: str | None) -> str:
    s = str(symbol or "").upper().strip().lstrip("$")
    m = _OCC.match(s)
    return m.group(1) if m else s


def mode_of(settings) -> str:
    try:
        m = str(settings.get("techniques.tip.review_gate", "observe") or "observe").lower()
    except Exception:                                     # noqa: BLE001
        return "observe"
    return m if m in MODES else "observe"                 # an unknown value never silently skips reviews


def entry_shaped(outcomes: list[dict]) -> bool:
    """A discarded signal that did not fail `opens_position` reads like a possible entry."""
    for o in outcomes or []:
        failed = set(o.get("failed") or [])
        if o.get("status") == "verification_failed" and failed and "opens_position" not in failed:
            return True
    return False


def decide(*, tickers: list[str] | set[str], source: str, outcomes: list[dict], items: list[dict]) -> dict:
    """Pure. `items` = the desk's open items: {kind: position|plan|proposal, symbol, source}.
    Returns {review: bool, reason, matched: [...], tickers: [...]}."""
    tk = sorted({root(t) for t in (tickers or []) if root(t)})
    if entry_shaped(outcomes):
        return {"review": True, "reason": "entry-shaped discard (possible missed entry)", "matched": [], "tickers": tk}
    if tk:
        hit = [i for i in items if root(i.get("symbol")) in tk]
        reason = "a ticker in the message is held, armed or proposed on the desk" if hit else \
                 "no ticker in the message is held, armed or proposed on the desk"
    else:
        hit = [i for i in items if (i.get("source") or "") == (source or "")]
        reason = "the source has an open position, armed plan or live proposal" if hit else \
                 "no ticker and the source has nothing open on the desk"
    return {"review": bool(hit), "reason": reason, "tickers": tk,
            "matched": [{"kind": i.get("kind"), "symbol": root(i.get("symbol")), "source": i.get("source")} for i in hit[:6]]}


async def desk_items(eng, *, now: dt.datetime | None = None) -> tuple[list[dict], list[str]]:
    """The desk's open items from the live engine: managed tip positions (every book the manager holds),
    armed/paused tip plans, and proposals pending or executed in this ET session. Returns (items, errors):
    a non-empty `errors` means the picture is INCOMPLETE and the caller must review (never skip on a
    partial read)."""
    items: list[dict] = []
    errors: list[str] = []
    # ECON-03 (2026-09-19): an ABSENT or NOT-YET-RESTORED component is an incomplete picture, never "nothing open".
    # None does not mean empty: only a component that answered is authoritative, so a missing one keeps the review.
    mgr = getattr(eng, "position_manager", None)
    if mgr is None:
        errors.append("positions: position manager absent")
    else:
        try:
            for p in mgr.positions(status="open"):
                if p.get("technique") != "tip":
                    continue
                src = next((t[7:] for t in (p.get("tags") or []) if str(t).startswith("source:")), "")
                items.append({"kind": "position", "symbol": p.get("symbol"), "source": src})
        except Exception as exc:                          # noqa: BLE001
            errors.append(f"positions: {type(exc).__name__}")
    runner = getattr(eng, "tip_runner", None)
    if runner is None:
        errors.append("plans: tip runner absent")
    elif not getattr(runner, "restore_complete", False):
        errors.append("plans: tip runner restore not complete")
    else:
        try:
            for ap in list(getattr(runner, "_armed", {}).values()):
                if getattr(ap, "status", "") not in ("armed", "paused"):
                    continue
                plan = getattr(ap, "plan", {}) or {}
                src = (plan.get("context") or {}).get("source") or plan.get("source") or ""
                items.append({"kind": "plan", "symbol": getattr(ap, "symbol", ""), "source": src})
        except Exception as exc:                          # noqa: BLE001
            errors.append(f"plans: {type(exc).__name__}")
    try:
        from sqlalchemy import or_, select
        from ...models import Proposal, Signal
        now = now or dt.datetime.now(dt.timezone.utc)
        session_start = now.astimezone(_ET).replace(hour=4, minute=0, second=0, microsecond=0)
        async with eng.sf() as session:
            rows = (await session.execute(
                select(Proposal.symbol, Proposal.status, Signal.source_name)
                .join(Signal, Signal.id == Proposal.signal_id, isouter=True)
                .where(or_(Proposal.status.in_(("pending", "approved")),
                           (Proposal.status == "executed") & (Proposal.created_at >= session_start))))).all()
        for sym, _st, src in rows:
            items.append({"kind": "proposal", "symbol": sym, "source": src or ""})
    except Exception as exc:                              # noqa: BLE001
        errors.append(f"proposals: {type(exc).__name__}")
    return items, errors


# ---- ADV-05 (2026-09-23): per-source review budget -----------------------------------------------------------------
def source_budget(settings, source: str) -> float | None:
    """The source's daily intake-review budget in list-price USD (`techniques.tip.review_source_budgets`, a map with an
    optional "*" default). None / 0 = no cap. Only ever applied to messages the gate already judged irrelevant to the
    desk - a message about anything we hold, arm or propose is always reviewed."""
    try:
        m = settings.get("techniques.tip.review_source_budgets", {}) or {}
    except Exception:
        return None
    if not isinstance(m, dict):
        return None
    v = m.get(source, m.get("*"))
    try:
        v = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    return v if v and v > 0 else None


def over_budget(spent_usd: float | None, cap_usd: float | None) -> bool:
    """Pure: a known spend at or above a set cap. Unknown spend never trips the cap (fail-open to reviewing)."""
    return cap_usd is not None and spent_usd is not None and spent_usd >= cap_usd


async def source_spend_today(eng, source: str) -> float | None:
    """Priced intake-review spend for `source` since 04:00 ET today, at the llm.rates card (an estimate)."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    from sqlalchemy import text as _t
    et = ZoneInfo("America/New_York")
    now = _dt.datetime.now(et)
    start = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if now < start:
        start -= _dt.timedelta(days=1)
    try:
        rates = eng.settings.get("llm.rates", {}) or {}
        rate = (rates.get("v", rates) if isinstance(rates, dict) else {}).get("claude-opus-5") or {}
        async with eng.sf() as session:
            row = (await session.execute(_t(
                "select coalesce(sum((opinion->'usage'->>'in')::numeric),0), coalesce(sum((opinion->'usage'->>'out')::numeric),0) "
                "from tip_analyst_runs where kind='intake' and source = :s and created_at >= :t"), {"s": source, "t": start})).first()
        return float(row[0]) / 1e6 * float(rate.get("in", 5.0)) + float(row[1]) / 1e6 * float(rate.get("out", 25.0))
    except Exception:                                     # noqa: BLE001 - unknown spend never skips a review
        return None
