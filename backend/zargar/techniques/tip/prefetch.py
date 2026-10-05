"""W2.4 (2026-10-02): prefetch + seeded context for the Tips analyst.

The analyst spent its first 3-4 turns fetching the quote, the chain, bars, our positions and (in 5% of runs) the
earnings date - ~8-15 s of option-price seconds before it even started judging (2026-10-02 review, appendices B/C).
Before the appraisal starts, these are fetched CONCURRENTLY (asyncio.gather, each bounded by
`techniques.tip.analyst_prefetch_timeout_s`) and seeded into the header as one compact block. The tools stay
available for more (an exact contract, another expiry, deeper bars).

Rules: nothing is invented - a fetch that failed or timed out is labelled as such; the earnings line is ALWAYS
present (a date, "none known", or why it is unknown) so 100% of appraisals carry it; the block is per-run, so it
sits in the message part of the header (after the cached rulebook block - `review_context.stable_first_blocks`
moves the rulebook first) and inside the head a frozen replay keeps verbatim.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

log = logging.getLogger(__name__)

PREFETCH_VERSION = "prefetch-v1"
SEED_MARK = "PREFETCHED MARKET CONTEXT"


def _network_ok(eng) -> bool:
    """History/calendar fetches are network calls; the synthetic sim feed (tests, dev) never makes them - the same
    rule the geometry gate's bar fetch has always followed."""
    from .risk_evidence import offline_feed
    return not offline_feed(eng)


def _chain_ok(eng) -> bool:
    if _network_ok(eng):
        return True
    with contextlib.suppress(Exception):
        return type(eng.options.provider()).__name__ not in ("CboeClient", "TradierClient")   # an injected provider
    return False


async def _bounded(coro, timeout: float):
    t0 = time.perf_counter()
    try:
        return {"ok": True, "value": await asyncio.wait_for(coro, timeout), "ms": round((time.perf_counter() - t0) * 1000)}
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timed out after {timeout:g}s", "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as exc:                            # noqa: BLE001 - a failed fetch is labelled, never fatal
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                "ms": round((time.perf_counter() - t0) * 1000)}


def bars_summary(bars: list) -> dict:
    """A compact read of ~5 sessions of 1h bars: last close, range, a simple ATR, the last session's range."""
    if not bars:
        return {"note": "no bars"}
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]
    trs = []
    for i, b in enumerate(bars):
        pc = float(bars[i - 1].close) if i else float(b.open)
        trs.append(max(float(b.high) - float(b.low), abs(float(b.high) - pc), abs(float(b.low) - pc)))
    atr = sum(trs[-14:]) / max(1, len(trs[-14:]))
    from ...marketstructure.levels import session_key
    last_key = session_key(bars[-1].ts)
    last = [b for b in bars if session_key(b.ts) == last_key]
    return {"tf": "1h", "bars": len(bars), "lastClose": round(float(bars[-1].close), 4),
            "rangeHigh": round(max(highs), 4), "rangeLow": round(min(lows), 4), "atr1h": round(atr, 4),
            "lastSession": {"date": last_key, "high": round(max(float(b.high) for b in last), 4),
                            "low": round(min(float(b.low) for b in last), 4)}}


def _stated_expiry_strike(signal_row) -> tuple[str | None, float | None, str]:
    inst = str(getattr(signal_row, "instrument", "") or "")
    side = "put" if (inst == "put" or getattr(signal_row, "direction", "long") == "short") else "call"
    return (getattr(signal_row, "expiry", None) or None), (getattr(signal_row, "strike", None) or None), side


async def prefetch(eng, signal_row, *, timeout_s: float | None = None) -> dict:
    """Fetch the five context items concurrently. Returns {version, ticker, items:{quote, chain, bars, positions,
    earnings}, ms} - every item {ok, value|error}; never raises."""
    from .analyst import _compact_chain, _our_positions, _run_tool
    sym = str(getattr(signal_row, "ticker", "") or "").upper()
    t = float(timeout_s if timeout_s is not None else
              eng.settings.get("techniques.tip.analyst_prefetch_timeout_s", 6.0) or 6.0)
    exp, strike, side = _stated_expiry_strike(signal_row)
    t0 = time.perf_counter()

    async def quote():
        return await _run_tool(eng, "get_quote", {"symbol": sym}, ctx={})

    async def chain():
        if not exp:
            return {"note": "the tip states no expiry - fetch a chain with get_expiries/get_chain if needed"}
        if not _chain_ok(eng):
            return {"note": "chain not prefetched (offline feed)"}
        ch = await eng.options.chain(sym, str(exp))
        slim = _compact_chain(ch, want=float(strike) if strike else None)
        # a slice around the stated strike: the five nearest, one side only (the tip's side)
        rows = sorted(slim.get("strikes") or [], key=lambda r: abs(float(r["strike"]) - float(strike or slim.get("spot") or 0)))[:5]
        rows = sorted(rows, key=lambda r: float(r["strike"]))
        return {"expiry": slim.get("expiry"), "dte": slim.get("dte"), "spot": slim.get("spot"),
                "side": side, "strikes": [{"strike": r["strike"], **(r.get(side) or {})} for r in rows],
                "strikesTotal": slim.get("strikesTotal"), "delayed": ch.get("delayed")}

    async def bars():
        if not _network_ok(eng):
            return {"note": "bars not prefetched (offline feed)"}
        from ...marketstructure.history import fetch_recent
        return bars_summary(await fetch_recent(sym, "1h", sessions=5))

    async def positions():
        return _our_positions(eng, sym)

    async def earnings():
        cal = getattr(eng, "calendar", None)
        if cal is None:
            return {"daysToEarnings": None, "status": "unknown", "why": "calendar not available"}
        if not _network_ok(eng):
            return {"daysToEarnings": None, "status": "unknown", "why": "calendar not fetched (offline feed)"}
        days = await cal.days_to_earnings(sym)
        return {"daysToEarnings": days, "status": ("none known" if days is None else "known"),
                "note": "dates are advisory, not confirmed"}

    async def context():
        # v0.9 V6.1 (2026-10-05): the deterministic decision-time read (cached per symbol per session; the proposal
        # path reuses it). Its own fetches are bounded; offline feeds return status "offline"
        from . import entry_context as _ec
        return await _ec.get(eng, sym)

    names = ("quote", "chain", "bars", "positions", "earnings", "context")
    got = await asyncio.gather(*(_bounded(f(), t) for f in (quote, chain, bars, positions, earnings, context)))
    items = dict(zip(names, got))
    if not items["earnings"]["ok"]:
        items["earnings"] = {"ok": True, "value": {"daysToEarnings": None, "status": "unknown",
                                                   "why": items["earnings"].get("error")}}
    return {"version": PREFETCH_VERSION, "ticker": sym, "items": items,
            "ms": round((time.perf_counter() - t0) * 1000), "timeoutS": t}


def _line(v) -> str:
    return json.dumps(v, default=str, separators=(",", ":"))[:1500]


def seed_block(pre: dict, *, fetched_at: str) -> str:
    """The compact header block. Ends with a newline; never empty when `pre` exists."""
    it = pre.get("items") or {}

    def val(k):
        x = it.get(k) or {}
        return x.get("value") if x.get("ok") else {"unavailable": x.get("error") or "not fetched"}
    e = val("earnings") or {}
    if e.get("status") == "known":
        earn = f"in {e.get('daysToEarnings')} day(s) (advisory, not confirmed)"
    elif e.get("status") == "none known":
        earn = "no upcoming date known (advisory)"
    else:
        earn = f"unknown - {e.get('why') or e.get('unavailable') or 'not fetched'}"
    ctx_line = ""
    with contextlib.suppress(Exception):
        from . import entry_context as _ec
        _cv = val("context")
        ctx_line = _ec.header_line(_cv) if (isinstance(_cv, dict) and _cv.get("version")) else ""
    return (f"{SEED_MARK} for {pre.get('ticker')} (prefetched {fetched_at}, concurrently, before this appraisal; "
            "the tools stay available - re-fetch before pricing if minutes have passed):\n"
            f"- earnings: {earn}\n"
            + ctx_line +
            f"- quote: {_line(val('quote'))}\n"
            f"- chain slice (stated expiry/strike): {_line(val('chain'))}\n"
            f"- bars summary: {_line(val('bars'))}\n"
            f"- our positions in {pre.get('ticker')}: {_line(val('positions'))}\n")


def record(pre: dict) -> dict:
    """What rides the opinion: which items arrived, the earnings value and the timing."""
    it = pre.get("items") or {}
    e = ((it.get("earnings") or {}).get("value") or {})
    return {"version": pre.get("version"), "ms": pre.get("ms"),
            "fetched": [k for k, v in it.items() if v.get("ok") and not ((v.get("value") or {}).get("note"))],
            "failed": {k: v.get("error") for k, v in it.items() if not v.get("ok")},
            "earnings": {"status": e.get("status"), "daysToEarnings": e.get("daysToEarnings"),
                         **({"why": e.get("why")} if e.get("why") else {})}}
