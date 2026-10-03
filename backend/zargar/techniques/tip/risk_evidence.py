"""W1.2 (2026-10-02): the evidence half of the feasibility authority.

The pre-entry geometry gate (`ProposalService._compute_risk_plan`) and the analyst's feasibility tools
(`check_feasibility`, `find_alternatives`) gather their inputs HERE, then call the one pure function
`geometry.fit_expression` (through `plan_risk` on the gate's side). Before this module the analyst sized with its
own inputs - the declared stop instead of the finalized one, a hard 100 multiplier, a delta of any age, the default
book's equity - and 9 of its takes were refused by the gate it had just "passed" (2026-10-02 review, appendix B).

`gather()` is the code that used to live inline in `_compute_risk_plan`, moved verbatim: the reference price, its
freshness evidence, 15-minute bars (not on the synthetic sim feed), the book's risk budget, the contract metadata
and the delta with its per-field age. Evidence problems are RETURNED (typed), never raised.
"""
from __future__ import annotations

import contextlib
import logging

log = logging.getLogger(__name__)


def tip_book_id(eng) -> str | None:
    """The book a tip proposal is minted in - the same resolution `create_from_signal` applies (techniques.tip.
    default_portfolio, the app default, else the first sim book). The analyst's numbers are computed for THIS book."""
    # W6: the PRIMARY bound book (techniques.tip.books); legacy = techniques.tip.default_portfolio
    from . import books as _books
    sims = [p for p in eng.positions.portfolios() if p.get("kind") == "sim" and not p.get("book")]
    b = _books.primary(eng.settings, eng.positions.portfolio, fallback_pid=(sims[0]["id"] if sims else None))
    return b.portfolioId if b is not None else None


def offline_feed(eng) -> bool:
    """The synthetic sim feed (tests / dev): history fetches are skipped, exactly as the gate always has."""
    return type(getattr(eng, "feed", None)).__name__ == "SimQuoteFeed"


async def gather(eng, *, underlying: str, sec_type: str, symbol: str, vehicle: dict | None, limit: float,
                 entry_hint: float | None, pid: str | None, cache: dict | None = None) -> dict:
    """Everything the risk arithmetic needs, with typed evidence problems. `cache` (optional, caller-held) shares
    the underlying's bars and the book equity across several contracts of one appraisal (find_alternatives)."""
    from ...clock import now_ms as _now_ms
    from . import geometry as _geo
    s = eng.settings
    cache = cache if cache is not None else {}
    now = int(_now_ms())
    quote_meta: dict = {"limit": float(limit)}
    problems: list[tuple[str, str]] = []      # (readiness code, detail)
    q_max_age = float(s.get("techniques.tip.geometry_quote_max_age_seconds", 300.0) or 300.0)

    def _age_s(q) -> float | None:
        ts = getattr(q, "source_ts", None) or getattr(q, "ts", None)
        try:
            return max(0.0, (now - int(ts)) / 1000.0) if ts else None
        except (TypeError, ValueError):
            return None

    if sec_type == "STK":
        # G91-02: the maximum admissible entry is the BUY limit — size there
        if not limit or float(limit) <= 0:
            raise ValueError("no executable limit for a share entry")
        entry_ref = float(limit)
        quote_meta["entryRefBasis"] = "limit"
        # EOD-06: the share plan carries the SAME quote-freshness evidence the
        # incident classifier requires (source, age, delayed)
        sq = None
        with contextlib.suppress(Exception):
            sq = eng.quotes.get(underlying)
        if sq is not None:
            age = _age_s(sq)
            quote_meta.update({"source": getattr(sq, "source", None), "ageS": age,
                               "delayed": bool(getattr(sq, "delayed", False)),
                               "underlyingDelayed": bool(getattr(sq, "delayed", False))})
            if bool(getattr(sq, "delayed", False)):
                problems.append(("quote_delayed", "share reference quote is delayed"))
            elif age is not None and age > q_max_age:
                problems.append(("quote_stale", f"share reference quote is {age:.0f}s old (max {q_max_age:.0f}s)"))
    else:
        await eng.ensure_symbol(underlying)
        uq = eng.quotes.get(underlying)
        entry_ref = float(uq.last) if uq is not None and getattr(uq, "last", 0) and uq.last > 0 else None
        quote_meta["entryRefBasis"] = "underlying-last"
        if entry_ref is None:
            problems.append(("quote_missing", "no live underlying reference quote"))
            entry_ref = float(entry_hint) if entry_hint else 0.0
        else:
            age = _age_s(uq)
            quote_meta.update({"underlyingSource": getattr(uq, "source", None),
                               "underlyingAgeS": age, "underlyingDelayed": bool(getattr(uq, "delayed", False))})
            if bool(getattr(uq, "delayed", False)):
                problems.append(("quote_delayed", "underlying reference quote is delayed"))
            elif age is None:
                problems.append(("quote_stale", "underlying reference quote age unknown"))
            elif age > q_max_age:
                problems.append(("quote_stale", f"underlying reference quote is {age:.0f}s old (max {q_max_age:.0f}s)"))
    key = ("bars", underlying)
    if key in cache:
        bars = cache[key]
    else:
        bars = []
        if not offline_feed(eng):
            try:
                from ...marketstructure.history import fetch_window
                bars = await fetch_window(underlying, "15m", now - 7 * 86_400_000, now)
            except Exception:
                log.debug("pre-entry geometry: no bars for %s", underlying)
        cache[key] = bars
    ekey = ("equity", pid)
    if ekey in cache:
        equity = cache[ekey]
    else:
        equity = None
        with contextlib.suppress(Exception):
            equity = float(await eng.positions.equity(pid) or 0) or None
        cache[ekey] = equity
    from . import books as _books
    budget, budget_source = _geo.risk_budget(_books.BookSettings(s), equity)   # W6: per-book riskPct
    delta = None
    greeks_meta: dict = {}
    multiplier = 1.0
    option_type = None
    currency = str((vehicle or {}).get("currency") or "USD")
    if sec_type == "OPT":
        # W1.3: a missing multiplier on a standard US contract is the standard 100; only a positively
        # non-standard deliverable is refused
        from ...options import occ as _occ_res
        v = vehicle or {}
        deliverable = v.get("deliverable")
        non_std = bool(v.get("nonStandard") or v.get("adjusted")
                       or (deliverable not in (None, "", 100, 100.0, "100")))
        res_mult, mult_src = _occ_res.resolve_multiplier(symbol, v.get("multiplier"), non_standard=non_std)
        quote_meta["multiplierSource"] = mult_src
        if res_mult is None:
            problems.append(("contract_metadata", f"contract multiplier unknown ({mult_src})"))
            multiplier = 0.0
        else:
            multiplier = float(res_mult)
        option_type = v.get("optionType")
        if option_type not in ("call", "put"):
            _po = _occ_res.parse_loose(symbol)
            if _po is not None:
                option_type = _po.option_type
        if option_type not in ("call", "put"):
            problems.append(("contract_metadata", "option type unknown"))
        snap = None
        with contextlib.suppress(Exception):
            snap = eng.options.snapshot_cached(symbol)
        g = (snap or {}).get("greeks") or {}
        g_max_age = float(s.get("techniques.tip.geometry_greeks_max_age_seconds", 900.0) or 900.0)
        if g.get("delta") is None:
            greeks_meta = {"reason": "missing delta — no estimate invented"}
        else:
            field_ts = ((snap or {}).get("greeksFieldAsOf") or {}).get("delta") or (snap or {}).get("asOf")
            try:
                g_age = max(0.0, (now - int(field_ts)) / 1000.0) if field_ts else None
            except (TypeError, ValueError):
                g_age = None
            greeks_meta = {"source": "live" if (snap or {}).get("greeksLive") else "chain",
                           "asOf": field_ts, "ageS": g_age}
            if g_age is None:
                greeks_meta["reason"] = "delta age unknown — no estimate invented"
            elif g_age > g_max_age:
                greeks_meta["reason"] = f"delta is {g_age:.0f}s old (max {g_max_age:.0f}s) — no estimate invented"
            else:
                delta = float(g["delta"])
        oq = eng.quotes.get(symbol)
        if oq is not None:
            quote_meta.update({"source": getattr(oq, "source", None), "ageS": _age_s(oq),
                               "delayed": bool(getattr(oq, "delayed", False))})
            if bool(getattr(oq, "delayed", False)):
                problems.append(("quote_delayed", "contract quote is delayed"))
    return {"entryRef": entry_ref, "quoteMeta": quote_meta, "problems": problems, "bars": bars,
            "equity": equity, "budget": budget, "budgetSource": budget_source, "delta": delta,
            "greeksMeta": greeks_meta, "multiplier": multiplier, "optionType": option_type, "currency": currency,
            "now": now}
