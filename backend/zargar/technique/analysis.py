"""Deterministic pre-pass: bars → FACTS.

Runs every detector over the requested timeframes and packages the result as
one JSON-able dict. The vision passes read it alongside the chart image, the
grounding pass checks the model's numbers against it, and the UI renders it.
Nothing in here calls an LLM.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..domain import Bar
from .candles import classify, metrics
from .history import HistoryError, fetch_recent, interval_available, split_sessions
from .levels import Level, atr, detect_levels, find_pivots, nearest_level, session_key
from .rulebook import DEFAULT_THRESHOLDS, Thresholds, session_window
from .setups import Setup, build_bounce_setup, build_breakout_setup, classify_breakout
from .structure import detect_wedge, read_trend
from .volume import assess_volume, build_profile

# Sessions of history per timeframe: enough for a time-of-day volume baseline
# and prior-day levels, without dragging in months the method ignores.
SESSIONS_FOR_TF = {"1m": 5, "5m": 8, "15m": 12, "30m": 15, "1h": 25, "1d": 120}
# Bars shown to the model / kept in facts for each timeframe.
WINDOW_FOR_TF = {"1m": 240, "5m": 160, "15m": 120, "30m": 120, "1h": 120, "1d": 120}


@dataclass
class AnalysisRequest:
    """`primary_tf` is where the entry/trigger decision is made; `context_tfs`
    are the structure timeframes (the book reads levels/patterns on 30m/1h,
    p. 114) shown first. `structure_tfs` is an alias kept for plan mode."""
    symbol: str
    as_of_ms: int | None = None
    primary_tf: str = "1m"
    context_tfs: tuple[str, ...] = ("1h", "5m")
    thresholds: Thresholds = field(default_factory=lambda: DEFAULT_THRESHOLDS)

    @property
    def structure_tfs(self) -> tuple[str, ...]:
        return tuple(t for t in self.context_tfs if t != self.primary_tf)

    @property
    def trigger_tf(self) -> str:
        return self.primary_tf

    @property
    def timeframes(self) -> list[str]:
        tfs = list(self.context_tfs) + [self.primary_tf]
        seen: list[str] = []
        for t in tfs:
            if t not in seen:
                seen.append(t)
        return seen


async def gather_bars(req: AnalysisRequest) -> tuple[dict[str, list[Bar]], list[str]]:
    """Fetch bars per timeframe ending at `as_of`. Returns (bars_by_tf, notes)."""
    notes: list[str] = []
    out: dict[str, list[Bar]] = {}
    for tf in req.timeframes:
        if not interval_available(tf, req.as_of_ms):
            notes.append(f"{tf} bars are not available that far back; timeframe skipped")
            continue
        try:
            bars = await fetch_recent(req.symbol, tf, sessions=SESSIONS_FOR_TF.get(tf, 5),
                                      as_of_ms=req.as_of_ms)
        except HistoryError as exc:
            notes.append(f"{tf}: {exc}")
            continue
        if req.as_of_ms is not None:
            bars = [b for b in bars if b.ts <= req.as_of_ms]
        if bars:
            out[tf] = bars
        else:
            notes.append(f"no {tf} bars returned")
    return out, notes


def _position(price: float, last: float, tol: float) -> str:
    if abs(price - last) <= tol:
        return "at"
    return "above" if price > last else "below"


def _level_dict(lv: Level, last: float, tol: float) -> dict:
    d = lv.to_dict()
    d["position"] = _position(lv.price, last, tol)
    # A support that now sits overhead behaves as resistance (and vice versa).
    if lv.kind == "support" and d["position"] == "above":
        d["effectiveKind"] = "resistance"
    elif lv.kind == "resistance" and d["position"] == "below":
        d["effectiveKind"] = "support"
    else:
        d["effectiveKind"] = lv.kind
    return d


def _merge_levels(per_tf: dict[str, list[Level]], last: float, tol: float,
                  limit: int = 12) -> list[dict]:
    """Union of levels across timeframes, deduped by proximity, strongest first."""
    pool: list[tuple[Level, str]] = []
    for tf, lvls in per_tf.items():
        pool.extend((lv, tf) for lv in lvls)
    pool.sort(key=lambda p: (0 if "T1.3a" in p[0].sources else 1, -p[0].touches))
    merged: list[dict] = []
    for lv, tf in pool:
        if any(abs(m["price"] - lv.price) <= tol for m in merged):
            # same level seen on another timeframe — record the confluence
            for m in merged:
                if abs(m["price"] - lv.price) <= tol and tf not in m["timeframes"]:
                    m["timeframes"].append(tf)
                    m["touches"] = max(m["touches"], lv.touches)
            continue
        d = _level_dict(lv, last, tol)
        d["timeframes"] = [tf]
        merged.append(d)
        if len(merged) >= limit:
            break
    return merged


def _session_stats(bars: list[Bar]) -> dict:
    by = split_sessions(bars)
    keys = sorted(by)
    out: dict = {"sessions": keys[-3:]}
    if keys:
        today = by[keys[-1]]
        out["today"] = {"open": today[0].open, "hod": max(b.high for b in today),
                        "lod": min(b.low for b in today), "bars": len(today)}
    if len(keys) >= 2:
        prev = by[keys[-2]]
        out["prev"] = {"hod": max(b.high for b in prev), "lod": min(b.low for b in prev),
                       "close": prev[-1].close, "date": keys[-2]}
    return out


def _recent_break(bars: list[Bar], levels: list[Level], vol, t: Thresholds,
                  lookback: int = 12, profile=None) -> tuple[dict | None, Level | None, int | None]:
    """Did a recent bar close through a resistance? Classify it if so — with
    the volume AT THE BREAK BAR (T3.3a), not the window's last bar."""
    if len(bars) < lookback + 2:
        return None, None, None
    res = [lv for lv in levels if lv.kind == "resistance"]
    if not res:
        return None, None, None
    start = len(bars) - lookback
    for i in range(start, len(bars)):
        b, prev = bars[i], bars[i - 1]
        for lv in res:
            if prev.close <= lv.price < b.close:
                vol_at = assess_volume(bars[:i + 1][-40:], profile, thresholds=t) if profile is not None else vol
                verdict = classify_breakout(bars, lv, i, vol_at, thresholds=t)
                d = verdict.to_dict()
                d.update({"levelPrice": round(lv.price, 4), "breakIndex": i,
                          "breakTs": b.ts, "breakClose": b.close})
                return d, lv, i
    return None, None, None


def compute_facts(req: AnalysisRequest, bars_by_tf: dict[str, list[Bar]],
                  notes: list[str] | None = None) -> dict:
    """Run all detectors and package FACTS for the prompt, grounding, and UI."""
    t = req.thresholds
    primary = req.primary_tf if req.primary_tf in bars_by_tf else (
        next(iter(bars_by_tf)) if bars_by_tf else req.primary_tf)
    facts: dict = {
        "symbol": req.symbol.upper(),
        "asOf": req.as_of_ms or int(time.time() * 1000),
        "primaryTf": primary,
        "requestedPrimaryTf": req.primary_tf,
        "notes": list(notes or []),
        "timeframes": {},
        "levels": {},
        "trend": {},
        "volume": {},
        "wedge": {},
        "lastCandles": {},
        "bars": {},
    }
    if not bars_by_tf:
        facts["notes"].append("no bars available for any timeframe")
        return facts

    pbars = bars_by_tf[primary]
    last = pbars[-1].close
    facts["lastClose"] = last
    facts["lastTs"] = pbars[-1].ts
    # R6 — where in the book's schedule the as-of instant sits (ET).
    facts["sessionWindow"] = session_window(int(facts["asOf"]))
    facts["atr"] = {}
    tol = max(last * t.level_tolerance_pct * 2, 1e-6)

    per_tf_levels: dict[str, list[Level]] = {}
    for tf, bars in bars_by_tf.items():
        win = WINDOW_FOR_TF.get(tf, 150)
        facts["timeframes"][tf] = {"bars": len(bars), "from": bars[0].ts, "to": bars[-1].ts,
                                   "window": min(win, len(bars))}
        sessions = split_sessions(bars)
        keys = sorted(sessions)
        prior = sessions[keys[-2]] if len(keys) >= 2 else None
        lvls = detect_levels(bars, thresholds=t, prior_session_bars=prior, timeframe=tf)
        per_tf_levels[tf] = lvls
        facts["levels"][tf] = [_level_dict(lv, last, tol) for lv in lvls[:10]]

        tr = read_trend(bars[-win:], thresholds=t)
        facts["trend"][tf] = tr.to_dict()
        facts["atr"][tf] = round(atr(bars[-win:]), 4)
        # recent swing lows — the bases a break launches from (breakout stops, T4.3d)
        facts.setdefault("swingLows", {})[tf] = [
            {"price": round(p.price, 4), "ts": p.ts}
            for p in find_pivots(bars[-60:], window=t.pivot_window) if p.kind == "low"][-8:]

        today_key = keys[-1] if keys else None
        prof = build_profile(bars, exclude_session=today_key)
        va = assess_volume(bars[-40:], prof, thresholds=t)
        vd = va.to_dict()
        vd["baselineSessions"] = prof.sessions
        facts["volume"][tf] = vd

        w = detect_wedge(bars[-min(80, len(bars)):], thresholds=t)
        if w is not None:
            wd = w.to_dict()
            off = len(bars) - min(80, len(bars))
            wd["startTs"] = bars[off + w.start_index].ts
            wd["endTs"] = bars[off + w.end_index].ts
            wd["breakoutLevelNow"] = round(w.breakout_level(w.end_index), 4)
            facts["wedge"][tf] = wd
        else:
            facts["wedge"][tf] = None

        cands = []
        for i in range(max(0, len(bars) - 5), len(bars)):
            m = metrics(bars[i]).to_dict()
            m["labels"] = classify(bars, i, thresholds=t)
            m["o"], m["h"], m["l"], m["c"], m["v"] = (bars[i].open, bars[i].high, bars[i].low,
                                                     bars[i].close, bars[i].volume)
            cands.append(m)
        facts["lastCandles"][tf] = cands
        facts["bars"][tf] = [b.to_row() for b in bars[-win:]]

    facts["keyLevels"] = _merge_levels(per_tf_levels, last, tol)
    facts["session"] = _session_stats(pbars)
    sess = facts["session"]
    if sess.get("today") and sess.get("prev") and sess["prev"].get("close"):
        pc = sess["prev"]["close"]
        facts["gap"] = {"open": sess["today"]["open"], "prevClose": pc,
                        "pct": round((sess["today"]["open"] - pc) / pc * 100, 3)}

    # --- candidate setups (deterministic) ---------------------------------
    plevels = per_tf_levels.get(primary, [])
    pprof = build_profile(pbars, exclude_session=session_key(pbars[-1].ts))
    pvol = assess_volume(pbars[-40:], pprof, thresholds=t)
    sup = nearest_level(plevels, last, "support", side="below")
    res_above = nearest_level(plevels, last, "resistance", side="above")
    candidates: list[dict] = []
    if sup is not None:
        # Stop buffer scales with the widest timeframe's ATR (structure, not
        # trigger noise); the chop guard compares against the trigger tf's own.
        stop_atr = max((float(v or 0.0) for v in facts["atr"].values()), default=0.0)
        ptrend = (facts.get("trend") or {}).get(primary) or {}
        s: Setup = build_bounce_setup(facts["symbol"], pbars, sup, pvol,
                                      next_resistance=res_above,
                                      atr_value=float(facts["atr"].get(primary) or 0.0),
                                      stop_atr=stop_atr,
                                      trend_direction=ptrend.get("direction"), thresholds=t)
        d = s.to_dict()
        d["distanceFromEntryPct"] = round((last - s.entry) / s.entry * 100, 3)
        candidates.append(d)

    brk, brk_level, brk_idx = _recent_break(pbars, plevels, pvol, t, profile=pprof)
    facts["recentBreak"] = brk
    if brk is not None and brk_level is not None and brk_idx is not None:
        vol_at_break = assess_volume(pbars[:brk_idx + 1][-40:], pprof, thresholds=t)
        verdict = classify_breakout(pbars, brk_level, brk_idx, vol_at_break, thresholds=t)
        wobj = detect_wedge(pbars[-min(80, len(pbars)):], thresholds=t)
        s2 = build_breakout_setup(facts["symbol"], pbars, brk_level, verdict, vol_at_break,
                                  wedge=wobj, thresholds=t,
                                  atr_value=max((float(v or 0.0) for v in facts["atr"].values()), default=0.0),
                                  next_resistance=nearest_level(plevels, brk_level.price * (1 + t.level_tolerance_pct),
                                                                "resistance", side="above"))
        candidates.append(s2.to_dict())
    facts["candidateSetups"] = candidates
    return facts


def facts_for_prompt(facts: dict, *, max_bars: int = 60) -> str:
    """Compact, readable rendering of FACTS for the model. Stable ordering."""
    L: list[str] = []
    L.append(f"SYMBOL {facts.get('symbol')}  asOf={facts.get('asOf')}  "
             f"lastClose={facts.get('lastClose')}  primaryTf={facts.get('primaryTf')}")
    if facts.get("sessionWindow"):
        sw = facts["sessionWindow"]
        L.append(f"SESSION WINDOW (R6): {sw}" + (" — prime, tradeable" if sw in ("prime_open", "prime_close")
                                                 else " — outside the prime windows: watch only (R6.3/R6.4)"))
    if facts.get("gap"):
        g = facts["gap"]
        L.append(f"GAP AT OPEN: {g['pct']:+.2f}% (open {g['open']:.2f} vs prev close {g['prevClose']:.2f})")
    for n in facts.get("notes") or []:
        L.append(f"NOTE: {n}")
    sess = facts.get("session") or {}
    if sess.get("prev"):
        p = sess["prev"]
        L.append(f"PREV SESSION {p['date']}: HOD={p['hod']:.2f} LOD={p['lod']:.2f} close={p['close']:.2f}")
    if sess.get("today"):
        td = sess["today"]
        L.append(f"TODAY: open={td['open']:.2f} HOD={td['hod']:.2f} LOD={td['lod']:.2f} bars={td['bars']}")
    L.append("KEY LEVELS (merged across timeframes; price kind touches position sources tfs):")
    for lv in facts.get("keyLevels") or []:
        L.append(f"  {lv['price']:.2f} {lv['effectiveKind']:<10} x{lv['touches']} {lv['position']:<5} "
                 f"{','.join(lv['sources'])} [{','.join(lv['timeframes'])}]")
    for tf, tr in (facts.get("trend") or {}).items():
        L.append(f"TREND {tf}: {tr['direction']} (HH={tr['higherHighs']} HL={tr['higherLows']} "
                 f"LH={tr['lowerHighs']} LL={tr['lowerLows']})")
    for tf, v in (facts.get("volume") or {}).items():
        L.append(f"VOLUME {tf}: rel={v['relativeToTimeOfDayAvg']}x trend={v['trend']} "
                 f"price={v['priceTrend']} spike={v['isSpike']} dryup={v['isDryup']} "
                 f"belowFloor={v['belowFloor']} measurable={v['measurable']} "
                 f"baselineSessions={v.get('baselineSessions')} rules={','.join(v['rules'])}")
    for tf, w in (facts.get("wedge") or {}).items():
        if w:
            L.append(f"WEDGE {tf}: falling_wedge widest={w['widestHeight']:.2f} low={w['lowestPrice']:.2f} "
                     f"breakLevelNow={w['breakoutLevelNow']:.2f} volDeclining={w['volumeDeclining']} "
                     f"rules={','.join(w['rules'])}")
        else:
            L.append(f"WEDGE {tf}: none")
    rb = facts.get("recentBreak")
    if rb:
        L.append(f"RECENT BREAK of {rb['levelPrice']:.2f}: breakout={rb['isBreakout']} "
                 f"volume={rb['hasVolume']} decisive={rb['isDecisive']} follow={rb['hasFollowthrough']} "
                 f"holds={rb['holdsLevel']} reasons={rb['reasons']}")
    else:
        L.append("RECENT BREAK: none")
    ptf = facts.get("primaryTf")
    for c in (facts.get("lastCandles") or {}).get(ptf, [])[-3:]:
        L.append(f"CANDLE {ptf} ts={c['ts']} o={c['o']:.2f} h={c['h']:.2f} l={c['l']:.2f} c={c['c']:.2f} "
                 f"v={c['v']} body={c['bodyRatio']} upW={c['upperWickRatio']} loW={c['lowerWickRatio']} "
                 f"{','.join(c['labels']) or '-'}")
    L.append("CANDIDATE SETUPS (deterministic, pre-judgement):")
    for s in facts.get("candidateSetups") or []:
        L.append(f"  {s['setupType']}: entry={s['entry']['price']:.2f} stop={s['stop']['price']:.2f} "
                 f"targets={[t['price'] for t in s['targets']]} RR={s['riskReward']} "
                 f"valid={s['valid']} noTrade={s['noTradeReasons']} conf={s['confidence']}")
    rows = (facts.get("bars") or {}).get(ptf, [])[-max_bars:]
    L.append(f"LAST {len(rows)} BARS {ptf} [ts,o,h,l,c,v]:")
    for r in rows:
        L.append(f"  {r[0]},{r[1]:.2f},{r[2]:.2f},{r[3]:.2f},{r[4]:.2f},{r[5]}")
    return "\n".join(L)
