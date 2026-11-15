"""Scout agent tools - the NUMBERS the agent reads (PLAN section 9). Pure: daily bars in, dicts and text out.

The agent never sees a chart image. Code reads the chart (trend, averages, ranges, levels, volume, relative
strength against SPY) and hands the model those numbers as plain lines, each one quotable: a proposal's
evidence must quote a tool result verbatim, so every line here is written once and never reformatted.

Bars are the shared `Bar` objects (ts ms, open/high/low/close/volume), oldest first or in any order.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Sequence

from .form4 import ET

TOOLS_VERSION = "scout-agent-tools-v1"


def _day(b) -> str:
    return dt.datetime.fromtimestamp(b.ts / 1000, ET).date().isoformat()


def _sorted(bars: Sequence | None) -> list:
    return sorted(bars or [], key=lambda x: x.ts)


def _sma(xs: Sequence[float], n: int, end: int | None = None) -> float | None:
    end = len(xs) if end is None else end
    return sum(xs[end - n:end]) / n if end >= n else None


def _ret(xs: Sequence[float], n: int) -> float | None:
    return xs[-1] / xs[-1 - n] - 1.0 if len(xs) > n and xs[-1 - n] > 0 else None


def atr(bars: Sequence, n: int = 14) -> float | None:
    b = _sorted(bars)
    if len(b) < n + 1:
        return None
    trs = [max(float(x.high) - float(x.low), abs(float(x.high) - float(p.close)), abs(float(x.low) - float(p.close)))
           for p, x in zip(b[-n - 1:-1], b[-n:])]
    return sum(trs) / n


def rsi(closes: Sequence[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def levels(bars: Sequence, *, lookback: int = 120, wing: int = 3, merge_atr: float = 0.5) -> list[dict]:
    """Swing highs/lows (a bar whose high/low is the extreme of `wing` bars each side) over the last `lookback`
    sessions, merged when closer than `merge_atr` x ATR. Each level: price, kind (support/resistance relative
    to the last close), touches, last touch date."""
    b = _sorted(bars)[-lookback:]
    a = atr(b) or 0.0
    if len(b) < 2 * wing + 1:
        return []
    raw: list[tuple[float, str]] = []
    for i in range(wing, len(b) - wing):
        hi, lo = float(b[i].high), float(b[i].low)
        win = b[i - wing:i + wing + 1]
        if hi >= max(float(x.high) for x in win):
            raw.append((hi, _day(b[i])))
        if lo <= min(float(x.low) for x in win):
            raw.append((lo, _day(b[i])))
    raw.sort()
    merged: list[dict] = []
    for px, d in raw:
        if merged and a > 0 and px - merged[-1]["hi"] <= merge_atr * a:
            m = merged[-1]
            m["prices"].append(px)
            m["hi"] = px
            m["last"] = max(m["last"], d)
        else:
            merged.append({"prices": [px], "hi": px, "last": d})
    last = float(b[-1].close)
    out = []
    for m in merged:
        p = sum(m["prices"]) / len(m["prices"])
        out.append({"price": round(p, 2), "kind": "support" if p < last else "resistance",
                    "touches": len(m["prices"]), "lastTouch": m["last"],
                    "distPct": round((p / last - 1.0) * 100, 2) if last > 0 else None})
    return out


def chart_read(bars: Sequence, bench: Sequence | None = None) -> dict:
    """Everything a chart reader would take from a daily chart, as numbers. {} when history is too short."""
    b = _sorted(bars)
    if len(b) < 30:
        return {}
    c = [float(x.close) for x in b]
    last = c[-1]
    a = atr(b)
    s20, s50, s200 = _sma(c, 20), _sma(c, 50), _sma(c, 200)
    s50_prev = _sma(c, 50, len(c) - 10)
    vol = [float(x.volume or 0) for x in b]
    v20 = _sma(vol, 20)
    hi20, lo20 = max(float(x.high) for x in b[-20:]), min(float(x.low) for x in b[-20:])
    hi55, lo55 = max(float(x.high) for x in b[-55:]), min(float(x.low) for x in b[-55:])
    yr = b[-252:]
    hi52, lo52 = max(float(x.high) for x in yr), min(float(x.low) for x in yr)
    if s50 and s200:
        trend = ("uptrend" if last > s50 > s200 else "downtrend" if last < s50 < s200
                 else "above both averages, 50 below 200" if last > s50 and last > s200
                 else "below both averages, 50 above 200" if last < s50 and last < s200 else "mixed")
    elif s50:
        trend = "above the 50-day average" if last > s50 else "below the 50-day average"
    else:
        trend = "unknown"
    bc = [float(x.close) for x in _sorted(bench)] if bench else []
    lv = levels(b)
    sup = sorted((x for x in lv if x["kind"] == "support"), key=lambda x: -x["price"])[:3]
    res = sorted((x for x in lv if x["kind"] == "resistance"), key=lambda x: x["price"])[:3]
    prev = float(b[-2].close)
    out = {
        "lastDate": _day(b[-1]), "last": round(last, 2), "sessions": len(b), "trend": trend,
        "sma20": s20, "sma50": s50, "sma200": s200,
        "sma50Slope10dPct": ((s50 / s50_prev - 1.0) * 100) if s50 and s50_prev else None,
        "atr14": a, "atrPct": (a / last * 100) if a and last > 0 else None,
        "ret": {k: _ret(c, n) for k, n in (("5d", 5), ("20d", 20), ("60d", 60), ("120d", 120))},
        "spy": {k: _ret(bc, n) for k, n in (("5d", 5), ("20d", 20), ("60d", 60), ("120d", 120))} if bc else {},
        "rsi14": rsi(c),
        "hi20": hi20, "lo20": lo20, "hi55": hi55, "lo55": lo55, "hi52": hi52, "lo52": lo52,
        "volRatio1d": (vol[-1] / v20) if v20 else None,
        "volRatio5d": ((_sma(vol, 5) or 0) / v20) if v20 else None,
        "advUsd20": sum(float(x.close) * float(x.volume or 0) for x in b[-20:]) / 20,
        "gapPct": ((float(b[-1].open) / prev - 1.0) * 100) if prev > 0 else None,
        "support": sup, "resistance": res,
        "recent": [{"d": _day(x), "o": round(float(x.open), 2), "h": round(float(x.high), 2),
                    "l": round(float(x.low), 2), "c": round(float(x.close), 2), "v": int(float(x.volume or 0))}
                   for x in b[-10:]],
    }
    rs = {}
    for k in ("20d", "60d", "120d"):
        r, s = out["ret"].get(k), out["spy"].get(k)
        rs[k] = (r - s) if r is not None and s is not None else None
    out["vsSpy"] = rs
    return out


def _p(x: float | None, d: int = 1, signed: bool = True) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.{d}f}%" if signed else f"{x * 100:.{d}f}%"


def _n(x: float | None, d: int = 2) -> str:
    return "n/a" if x is None else f"{x:,.{d}f}"


def render_chart(ticker: str, r: dict) -> str:
    """The chart read as quotable lines."""
    if not r:
        return f"{ticker}: not enough daily history for a chart read (fewer than 30 sessions)."
    lines = [
        f"{ticker} daily chart as of {r['lastDate']} close ({r['sessions']} sessions)",
        f"last close: {_n(r['last'])}",
        f"trend: {r['trend']}",
        f"20-day average: {_n(r['sma20'])}; 50-day: {_n(r['sma50'])}; 200-day: {_n(r['sma200'])}",
        f"50-day average slope over 10 sessions: {_n(r['sma50Slope10dPct'])}%",
        f"ATR(14): {_n(r['atr14'])} ({_n(r['atrPct'])}% of price)",
        f"returns: 5d {_p(r['ret']['5d'])}, 20d {_p(r['ret']['20d'])}, 60d {_p(r['ret']['60d'])}, 120d {_p(r['ret']['120d'])}",
        f"vs SPY: 20d {_p(r['vsSpy']['20d'])}, 60d {_p(r['vsSpy']['60d'])}, 120d {_p(r['vsSpy']['120d'])}",
        f"RSI(14): {_n(r['rsi14'], 1)}",
        f"20-day range: {_n(r['lo20'])} - {_n(r['hi20'])}; 55-day range: {_n(r['lo55'])} - {_n(r['hi55'])}; "
        f"52-week range: {_n(r['lo52'])} - {_n(r['hi52'])}",
        f"volume: last session {_n(r['volRatio1d'])}x its 20-day average; last 5 sessions {_n(r['volRatio5d'])}x",
        f"average daily dollar volume (20d): ${_n(r['advUsd20'] / 1e6, 1)}M",
        f"last session gap at the open: {_n(r['gapPct'])}%",
    ]
    for x in r["support"]:
        lines.append(f"support {x['price']:.2f} ({x['distPct']:+.2f}% away, {x['touches']} touch(es), last {x['lastTouch']})")
    for x in r["resistance"]:
        lines.append(f"resistance {x['price']:.2f} ({x['distPct']:+.2f}% away, {x['touches']} touch(es), last {x['lastTouch']})")
    if not r["support"]:
        lines.append("support: no swing low below the last close in 120 sessions")
    if not r["resistance"]:
        lines.append("resistance: no swing high above the last close in 120 sessions")
    lines.append("last 10 sessions (date open high low close volume):")
    for x in r["recent"]:
        lines.append(f"  {x['d']} {x['o']:.2f} {x['h']:.2f} {x['l']:.2f} {x['c']:.2f} {x['v']:,}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- the idea screen
def screen(reads: dict[str, dict], *, min_price: float = 5.0, min_adv_usd: float = 5e6, top: int = 25) -> list[dict]:
    """Rank a universe of chart reads for LONG swing ideas. Code-computed, deterministic:
    score = 0.5 x pct-rank(60d vs SPY) + 0.3 x pct-rank(20d vs SPY) + 0.2 x pct-rank(5-day volume ratio),
    over names that pass price and liquidity and trade above their 50-day average. Flags say why a name is
    interesting (breakout near the 55-day high, pullback to the 20-day average in an uptrend, volume surge)."""
    rows = []
    for t, r in reads.items():
        if not r or r.get("last", 0) < min_price or (r.get("advUsd20") or 0) < min_adv_usd:
            continue
        if not r.get("sma50") or r["last"] <= r["sma50"]:
            continue
        rows.append((t, r))
    if not rows:
        return []

    def prank(vals: list[float | None]) -> list[float]:
        idx = sorted((v, i) for i, v in enumerate(vals) if v is not None)
        out = [0.0] * len(vals)
        n = len(idx)
        for k, (_, i) in enumerate(idx):
            out[i] = (k + 1) / n if n else 0.0
        return out

    r60 = prank([r["vsSpy"].get("60d") for _, r in rows])
    r20 = prank([r["vsSpy"].get("20d") for _, r in rows])
    rv = prank([r.get("volRatio5d") for _, r in rows])
    out = []
    for k, (t, r) in enumerate(rows):
        flags = []
        a = r.get("atr14") or 0
        if r["hi55"] and r["last"] >= 0.99 * r["hi55"]:
            flags.append("near 55-day high")
        if r["trend"] == "uptrend" and r["sma20"] and a and abs(r["last"] - r["sma20"]) <= a:
            flags.append("pullback to 20-day average in uptrend")
        if (r.get("volRatio1d") or 0) >= 2.0:
            flags.append("volume surge")
        if (r.get("rsi14") or 0) >= 75:
            flags.append("RSI above 75 (extended)")
        out.append({"ticker": t, "score": round(0.5 * r60[k] + 0.3 * r20[k] + 0.2 * rv[k], 4),
                    "last": r["last"], "trend": r["trend"], "vsSpy20": r["vsSpy"].get("20d"),
                    "vsSpy60": r["vsSpy"].get("60d"), "atrPct": r.get("atrPct"), "rsi14": r.get("rsi14"),
                    "volRatio5d": r.get("volRatio5d"), "advUsd20": r.get("advUsd20"), "flags": flags})
    out.sort(key=lambda x: (-x["score"], x["ticker"]))
    return out[:top]


def render_screen(rows: list[dict], extra: list[dict] | None = None, *, universe: int = 0) -> str:
    lines = [f"momentum / relative-strength screen over {universe} liquid US names (long ideas only; "
             f"price >= $5, 20-day dollar volume >= $5M, above the 50-day average); rank, ticker, score, "
             f"60d and 20d return vs SPY, ATR %, RSI, 5-day volume ratio, flags:"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r['ticker']} score {r['score']:.3f} | 60d vs SPY {_p(r['vsSpy60'])} | 20d vs SPY "
                     f"{_p(r['vsSpy20'])} | ATR {_n(r['atrPct'])}% | RSI {_n(r['rsi14'], 1)} | vol5d "
                     f"{_n(r['volRatio5d'])}x | {', '.join(r['flags']) or 'no flags'}")
    if not rows:
        lines.append("(no name passed the screen today)")
    if extra:
        lines.append("Scout event candidates for today (insider-purchase clusters / earnings reactions that "
                     "passed Scout's gates):")
        for x in extra:
            lines.append(f"- {x['ticker']}: {x['what']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- options: expected move
def expected_move(*, spot: float | None, straddle_mid: float | None, dte: int | None, iv30: float | None) -> dict:
    """The options market's expected move: the at-the-money straddle mid as % of spot to that expiry, and the
    30-day implied volatility scaled to 1 and 10 sessions (iv x sqrt(n/252))."""
    out: dict = {"spot": spot, "dte": dte, "iv30": iv30}
    out["straddlePct"] = (straddle_mid / spot * 100) if spot and straddle_mid else None
    iv = iv30 / 100.0 if iv30 and iv30 > 3 else iv30          # providers send 0.35 or 35
    out["move1dPct"] = iv * math.sqrt(1 / 252) * 100 if iv else None
    out["move10dPct"] = iv * math.sqrt(10 / 252) * 100 if iv else None
    return out


def render_options(ticker: str, em: dict, *, expiry: str | None, provider: str | None) -> str:
    if not em.get("spot"):
        return f"{ticker}: no option chain (not listed on the provider, or the request failed)."
    iv = em.get("iv30")
    ivs = "n/a" if iv is None else (f"{iv:.1f}%" if iv > 3 else f"{iv * 100:.1f}%")
    return "\n".join([
        f"{ticker} options ({provider or 'provider'}, delayed) spot {em['spot']:.2f}",
        f"30-day implied volatility: {ivs}",
        f"implied 1-session move: {_n(em['move1dPct'])}%; implied 10-session move: {_n(em['move10dPct'])}%",
        f"at-the-money straddle to {expiry or 'n/a'} ({em.get('dte')} days): {_n(em['straddlePct'])}% of spot",
    ])
