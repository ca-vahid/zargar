"""Tips v0.9 V2.1 (2026-10-05): the HORIZON CLASS of a tip, decided at entry from facts observable then.

Evidence: docs/techniques/tip/research/2026-10-04-v09/R3-horizon-exits.md (Q3, recommendation 4; LOW confidence -
the CIs include 0, so every decision is journaled `TipHorizonDecided` and re-graded at V7.1 after 20 sessions).

    short    (<= 3 sessions)  entry chased >= +2% over the prior close, a gap >= +2% at the open, a catalyst/news
                              tip, or a low-ATR name (daily ATR < 2.5% of price)
    extended (20+ sessions)   a down-day entry (<= -2% under the prior close) or a source with a graded multi-week
                              record (`techniques.tip.horizon_extended_sources`)
    swing    (10, default)    everything else

A short flag wins over an extended flag (the conservative read). The analyst may choose a horizon (V2.5): its choice
wins when it is CONSISTENT - never longer than the classifier's ceiling (any short flag caps the ceiling at short) -
else the classifier's label stands and the disagreement is recorded.

`classify` / `resolve` are PURE. `daily_facts` (I/O: daily bars, cached) and `decide` (classify + stamp the exit
plan + journal) are the thin wiring the proposal path, the analyst's feasibility tools and the armed lane share.
"""
from __future__ import annotations

import contextlib
import logging
import time

log = logging.getLogger("zargar.tip.horizon")

VERSION = "horizon-v1"
HORIZONS = ("short", "swing", "extended")
_RANK = {"short": 0, "swing": 1, "extended": 2}
MODES = ("observe", "enforce")


def horizon_mode(settings) -> str:
    m = str(settings.get("techniques.tip.horizon_mode", "enforce") or "enforce").lower()
    return m if m in MODES else "enforce"


def normalize(h) -> str | None:
    h = str(h or "").strip().lower()
    return h if h in HORIZONS else None


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _sources(settings) -> set[str]:
    raw = settings.get("techniques.tip.horizon_extended_sources", "neal")
    parts = raw if isinstance(raw, (list, tuple)) else str(raw or "").replace(";", ",").split(",")
    return {str(p).strip().lower() for p in parts if str(p).strip()}


def classify(*, direction: str, entry: float | None, prior_close: float | None, session_open: float | None,
             atr: float | None, catalyst: str | None, source: str | None, settings) -> dict:
    """Pure. The label, its reason, the flags that fired and the facts (unknown facts are listed, never guessed)."""
    sgn = -1.0 if str(direction) == "short" else 1.0
    chase = float(settings.get("techniques.tip.horizon_chase_pct", 2.0) or 2.0)
    gap_t = float(settings.get("techniques.tip.horizon_gap_pct", 2.0) or 2.0)
    dip = float(settings.get("techniques.tip.horizon_dip_pct", 2.0) or 2.0)
    low_atr = float(settings.get("techniques.tip.horizon_low_atr_pct", 2.5) or 2.5)
    entry, prior_close, session_open, atr = _f(entry), _f(prior_close), _f(session_open), _f(atr)
    facts: dict = {"entry": entry, "priorClose": prior_close, "sessionOpen": session_open, "atrDaily": atr,
                   "catalyst": (str(catalyst).strip() or None) if catalyst else None, "source": source,
                   "direction": direction}
    unknown: list[str] = []
    short_flags: list[str] = []
    ext_flags: list[str] = []
    move = None
    if entry and prior_close:
        move = (entry / prior_close - 1.0) * 100.0
        facts["entryVsPriorClosePct"] = round(move, 2)
        if sgn * move >= chase:
            short_flags.append(f"chased entry {move:+.1f}% vs the prior close (>= {chase:g}%)")
        elif sgn * move <= -dip:
            ext_flags.append(f"{'down' if sgn > 0 else 'up'}-day entry {move:+.1f}% vs the prior close")
    else:
        unknown.append("entry vs prior close")
    if session_open and prior_close:
        gap = (session_open / prior_close - 1.0) * 100.0
        facts["gapPct"] = round(gap, 2)
        if sgn * gap >= gap_t:
            short_flags.append(f"gap {gap:+.1f}% at the open (>= {gap_t:g}%)")
    else:
        unknown.append("gap")
    ref = entry or prior_close
    if atr and ref:
        atr_pct = atr / ref * 100.0
        facts["atrPct"] = round(atr_pct, 2)
        if atr_pct < low_atr:
            short_flags.append(f"low-ATR name ({atr_pct:.1f}% of price < {low_atr:g}%)")
    else:
        unknown.append("ATR")
    if facts["catalyst"]:
        short_flags.append(f"catalyst/news tip ({facts['catalyst'][:60]})")
    if source and str(source).strip().lower() in _sources(settings):
        ext_flags.append(f"source {source} has a graded multi-week record")
    if short_flags:
        label, reason = "short", "; ".join(short_flags)
    elif ext_flags:
        label, reason = "extended", "; ".join(ext_flags)
    else:
        label, reason = "swing", "no short or extended trigger - the default"
    return {"horizon": label, "reason": reason, "shortFlags": short_flags, "extendedFlags": ext_flags,
            "unknown": unknown, "facts": facts, "version": VERSION}


def resolve(classified: dict, analyst_horizon=None, analyst_reason: str | None = None) -> dict:
    """Pure. The analyst's horizon wins when consistent (never longer than the ceiling the classifier allows: any
    short flag caps it at short); else the classifier's label, recorded as a disagreement."""
    cls = classified.get("horizon") or "swing"
    ah = normalize(analyst_horizon)
    ceiling = "short" if classified.get("shortFlags") else "extended"
    if ah is None:
        return {"horizon": cls, "source": "classifier", "reason": classified.get("reason"),
                "classifier": cls, "analyst": None, "consistent": None}
    if _RANK[ah] <= _RANK[ceiling]:
        return {"horizon": ah, "source": "analyst",
                "reason": (analyst_reason or f"analyst chose {ah}") + (f" (classifier: {cls})" if ah != cls else ""),
                "classifier": cls, "analyst": ah, "consistent": True}
    return {"horizon": cls, "source": "classifier",
            "reason": (f"{classified.get('reason')} - the analyst's {ah} is inconsistent with it "
                       f"(ceiling {ceiling})"),
            "classifier": cls, "analyst": ah, "consistent": False}


# ---------------------------------------------------------------------------------------------- wiring (I/O)
async def daily_facts(eng, symbol: str) -> dict:
    """Daily ATR14, the prior close, today's open and the 20-day MA from daily bars (60 days), cached ~10 minutes per
    symbol. {} on the synthetic sim feed or any failure - the classifier then lists the facts as unknown."""
    sym = str(symbol or "").upper()
    if not sym:
        return {}
    cache: dict = eng.__dict__.setdefault("_tip_daily_facts", {})
    hit = cache.get(sym)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    out: dict = {}
    if type(getattr(eng, "feed", None)).__name__ != "SimQuoteFeed":
        with contextlib.suppress(Exception):
            from ...clock import now_ms as _now_ms
            from ...marketstructure.history import fetch_window
            from ...marketstructure.levels import atr as _atr
            from ...marketstructure.sessions import session_date
            now = int(_now_ms())
            bars = await fetch_window(sym, "1d", now - 60 * 86_400_000, now)
            today = session_date(now)
            done = [b for b in (bars or []) if session_date(b.ts) < today]
            cur = [b for b in (bars or []) if session_date(b.ts) == today]
            if done:
                out["priorClose"] = float(done[-1].close)
                a = _atr(done[-15:])
                if a > 0:
                    out["atrDaily"] = round(a, 4)
                if len(done) >= 20:
                    out["ma20"] = round(sum(b.close for b in done[-20:]) / 20.0, 4)
            if cur:
                out["sessionOpen"] = float(cur[0].open)
    if "priorClose" not in out:
        with contextlib.suppress(Exception):
            q = eng.quotes.get(sym)
            if q is not None and getattr(q, "prev_close", 0):
                out["priorClose"] = float(q.prev_close)
    if len(cache) > 400:
        cache.clear()
    cache[sym] = (time.time(), out)
    return out


def applies_on_book(eng, pid: str | None) -> bool:
    """The horizon EXIT policy runs where the Tips Practice policy runs (`policy_kind` == sim: Practice books and an
    IBKR book under `techniques.tip.live_parity`). Elsewhere the label is recorded only."""
    try:
        from ...approvals.proposals import policy_kind
        pf = eng.positions.portfolio(pid) or {} if pid else {}
        return policy_kind(eng.settings, pf) == "sim"
    except Exception:
        return False


def atr_stop_scope(eng, pid: str | None) -> bool:
    """V3.1's ATR stop re-sizes the trade, so it applies only where the pre-entry geometry gate SIZES from the stop
    (enforce on a Practice-policy book) - a post-fill widen without a resize would multiply the dollar risk."""
    if str(eng.settings.get("techniques.tip.stop_atr_mode", "enforce") or "enforce").lower() != "enforce":
        return False
    try:
        from . import geometry as _geo
        if _geo.gate_mode(eng.settings) != "enforce":
            return False
    except Exception:
        return False
    return applies_on_book(eng, pid)


def stamp(plan: dict, *, decision: dict, classified: dict, atr: float | None, applied: bool,
          atr_stop: bool) -> dict:
    """Pure: the exit plan with its horizon carried (V2.1)."""
    out = dict(plan or {})
    out.update({"horizon": decision["horizon"], "horizonReason": decision.get("reason"),
                "horizonSource": decision.get("source"), "horizonClassifier": classified.get("horizon"),
                "horizonVersion": VERSION, "horizonApplied": bool(applied)})
    if decision.get("analyst"):
        out["horizonAnalyst"] = decision["analyst"]
    if atr and atr > 0:
        out["atrDaily"] = round(float(atr), 4)
    out["atrStop"] = bool(atr_stop and atr and atr > 0)
    return out


async def decide(eng, *, plan: dict, symbol: str, direction: str, entry_ref: float | None, catalyst: str | None,
                 source: str | None, analyst: dict | None, pid: str | None, where: str,
                 signal_id: str | None = None, atr_stop: bool | None = None, journal: bool = True) -> dict:
    """Classify, resolve against the analyst, stamp the plan, journal `TipHorizonDecided`. Never raises: a failure
    leaves the plan unlabelled (the legacy exit policy) and is logged."""
    try:
        s = eng.settings
        facts = await daily_facts(eng, symbol)
        cls = classify(direction=direction, entry=entry_ref, prior_close=facts.get("priorClose"),
                       session_open=facts.get("sessionOpen"), atr=facts.get("atrDaily"), catalyst=catalyst,
                       source=source, settings=s)
        if facts.get("ma20") is not None:
            cls["facts"]["ma20"] = facts["ma20"]
        a = analyst or {}
        dec = resolve(cls, a.get("horizon"), a.get("horizon_reason"))
        lotto = bool((plan or {}).get("lotto"))
        if lotto:
            dec = {**dec, "horizon": "short", "source": "lotto", "reason": "lotto lane (0-3 DTE) - its own exits"}
        mode = horizon_mode(s)
        applied = mode == "enforce" and not lotto and applies_on_book(eng, pid)
        stop_ok = atr_stop_scope(eng, pid) if atr_stop is None else bool(atr_stop)
        out = stamp(plan, decision=dec, classified=cls, atr=facts.get("atrDaily"), applied=applied,
                    atr_stop=(stop_ok and not lotto))
        if journal:
            with contextlib.suppress(Exception):
                await eng.journal.append("TipHorizonDecided", {
                    "signalId": signal_id, "symbol": str(symbol or "").upper(), "where": where, "mode": mode,
                    "horizon": dec["horizon"], "reason": dec.get("reason"), "decidedBy": dec.get("source"),
                    "classifier": cls["horizon"], "classifierReason": cls["reason"], "analyst": dec.get("analyst"),
                    "consistent": dec.get("consistent"), "applied": applied, "atrStop": out["atrStop"],
                    "shortFlags": cls["shortFlags"], "extendedFlags": cls["extendedFlags"],
                    "unknown": cls["unknown"], "facts": cls["facts"], "version": VERSION},
                    aggregate_type="signal", aggregate_id=signal_id or str(symbol or "tip"),
                    **({"portfolio_id": pid} if pid else {}))
        return out
    except Exception:                                      # noqa: BLE001 - the legacy policy is the fallback
        log.exception("horizon decision failed for %s", symbol)
        return dict(plan or {})
