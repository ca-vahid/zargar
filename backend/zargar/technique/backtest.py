"""Backtest harness: replay history and score the deterministic setups.

This answers "does the method, as codified, have an edge on this symbol?"
without spending a cent on vision calls. Each step re-runs the detectors on
bars *up to* the cursor (no look-ahead), emits any newly-valid setup, then
walks forward to see whether the stop or the targets were hit first.

Outcome model (deliberately simple, matching the book's own management):
    bounce  — fills if price trades down to the level within `entry_window`
              bars; otherwise "not_filled".
    break   — fills at the break bar's close (the level was already taken).
    exits   — scale out 30/40/15 at TP1-3, 15% runner closed at the horizon
              end; the stop is fixed (the book's mental stop is a judgement we
              do not simulate). R multiple = realized P&L / initial risk.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..domain import Bar
from .analysis import AnalysisRequest, compute_facts
from .history import fetch_window, split_sessions
from .outcome import simulate_plan
from .rulebook import DEFAULT_THRESHOLDS, PRIME_WINDOWS, Thresholds, session_window


@dataclass
class TradeResult:
    ts: int
    session: str
    setup_type: str
    entry: float
    stop: float
    targets: list[float]
    filled: bool
    fill_ts: int | None
    outcome: str                # not_filled | stopped | tp1 | tp2 | tp3 | horizon
    r_multiple: float
    bars_held: int
    rules: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ts": self.ts, "session": self.session, "setupType": self.setup_type,
            "entry": round(self.entry, 4), "stop": round(self.stop, 4),
            "targets": [round(t, 4) for t in self.targets], "filled": self.filled,
            "fillTs": self.fill_ts, "outcome": self.outcome,
            "rMultiple": round(self.r_multiple, 3), "barsHeld": self.bars_held,
            "rules": list(self.rules), "confidence": round(self.confidence, 3),
        }


def _simulate(bars: list[Bar], start: int, setup: dict, *, entry_window: int,
              horizon: int, thresholds: Thresholds | None = None) -> TradeResult:
    """Score one deterministic setup with the shared walk-forward model
    (`outcome.simulate_plan`) — the same rules score live runs, so backtest
    statistics and per-run outcomes are directly comparable."""
    ts0 = bars[start].ts
    session = time.strftime("%Y-%m-%d", time.gmtime(ts0 / 1000))
    sim = simulate_plan(bars, start, setup, entry_window=entry_window, horizon=horizon,
                        stop_on="close" if (thresholds or DEFAULT_THRESHOLDS).stop_on_close else "low")
    return TradeResult(
        ts=ts0, session=session, setup_type=setup["setupType"], entry=sim["entry"], stop=sim["stop"],
        targets=sim["targets"], filled=sim["filled"], fill_ts=sim["fillTs"], outcome=sim["outcome"],
        r_multiple=sim["rMultiple"], bars_held=sim["barsHeld"], rules=setup.get("rules", []),
        confidence=setup.get("confidence", 0))


async def run_backtest(symbol: str, tf: str, start_ms: int, end_ms: int, *,
                       step_bars: int = 5, entry_window: int = 12, horizon_bars: int = 60,
                       warmup_sessions: int = 3, thresholds: Thresholds | None = None,
                       only_valid: bool = True, max_trades: int = 500,
                       prime_windows_only: bool = True) -> dict:
    """Replay [start,end] at `tf`. Returns summary + per-trade rows.

    `prime_windows_only` (default) takes setups only when the cursor bar sits in
    an R6 prime window (09:30-10:30 / 14:45-16:00 ET) — the book's schedule.
    `False` is the old all-hours behaviour, kept so the difference is visible."""
    t = thresholds or DEFAULT_THRESHOLDS
    # Pull warm-up history before `start` so early cursors have a volume baseline.
    warm_ms = warmup_sessions * 2 * 86400 * 1000
    bars = await fetch_window(symbol, tf, start_ms - warm_ms, end_ms)
    if len(bars) < 50:
        return {"error": "not enough bars", "bars": len(bars), "trades": [], "summary": {}}
    sessions = split_sessions(bars)
    keys = sorted(sessions)
    first_idx = next((i for i, b in enumerate(bars) if b.ts >= start_ms), 0)
    first_idx = max(first_idx, 40)

    trades: list[TradeResult] = []
    seen: dict[tuple, int] = {}       # (type, round(level)) -> last emit index
    req = AnalysisRequest(symbol=symbol, primary_tf=tf, context_tfs=(), thresholds=t)
    cursor = first_idx
    while cursor < len(bars) - 1 and len(trades) < max_trades:
        window = bars[:cursor + 1]
        # limit to the last few sessions for speed; detectors only need that
        sess_keys = sorted(split_sessions(window))
        keep = set(sess_keys[-(warmup_sessions + 1):])
        window = [b for b in window if time.strftime("%Y-%m-%d", time.gmtime(b.ts / 1000)) in keep]
        facts = compute_facts(req, {tf: window})
        cur_window = session_window(bars[cursor].ts)
        if prime_windows_only and cur_window not in PRIME_WINDOWS:
            cursor += step_bars
            continue
        for s in facts.get("candidateSetups") or []:
            if only_valid and not s.get("valid"):
                continue
            key = (s["setupType"], round(float(s["levelPrice"] or s["entry"]["price"]), 2))
            last_emit = seen.get(key)
            if last_emit is not None and cursor - last_emit < horizon_bars:
                continue
            seen[key] = cursor
            tr = _simulate(bars, cursor, s, entry_window=entry_window, horizon=horizon_bars, thresholds=thresholds)
            tr.rules = list(tr.rules) + [f"window:{cur_window}"]
            trades.append(tr)
        cursor += step_bars

    filled = [x for x in trades if x.filled]
    wins = [x for x in filled if x.r_multiple > 0]
    by_type: dict[str, dict] = {}
    for x in filled:
        d = by_type.setdefault(x.setup_type, {"n": 0, "wins": 0, "sumR": 0.0})
        d["n"] += 1
        d["wins"] += 1 if x.r_multiple > 0 else 0
        d["sumR"] += x.r_multiple
    for d in by_type.values():
        d["winRate"] = round(d["wins"] / d["n"], 3) if d["n"] else 0.0
        d["avgR"] = round(d["sumR"] / d["n"], 3) if d["n"] else 0.0
        d["sumR"] = round(d["sumR"], 3)
    by_window: dict[str, dict] = {}
    for x in filled:
        w = next((r.split(":", 1)[1] for r in x.rules if r.startswith("window:")), "?")
        d = by_window.setdefault(w, {"n": 0, "wins": 0, "sumR": 0.0})
        d["n"] += 1
        d["wins"] += 1 if x.r_multiple > 0 else 0
        d["sumR"] += x.r_multiple
    for d in by_window.values():
        d["winRate"] = round(d["wins"] / d["n"], 3) if d["n"] else 0.0
        d["avgR"] = round(d["sumR"] / d["n"], 3) if d["n"] else 0.0
        d["sumR"] = round(d["sumR"], 3)
    summary = {
        "symbol": symbol.upper(), "tf": tf, "from": bars[first_idx].ts, "to": bars[-1].ts,
        "primeWindowsOnly": prime_windows_only, "byWindow": by_window,
        "sessions": len([k for k in keys if sessions[k][0].ts >= start_ms]),
        "setupsEmitted": len(trades), "filled": len(filled), "notFilled": len(trades) - len(filled),
        "winRate": round(len(wins) / len(filled), 3) if filled else 0.0,
        "avgR": round(sum(x.r_multiple for x in filled) / len(filled), 3) if filled else 0.0,
        "totalR": round(sum(x.r_multiple for x in filled), 3),
        "byType": by_type,
        "params": {"stepBars": step_bars, "entryWindow": entry_window, "horizonBars": horizon_bars,
                   "minRR": t.min_risk_reward, "primeWindowsOnly": prime_windows_only},
    }
    return {"summary": summary, "trades": [x.to_dict() for x in trades]}
