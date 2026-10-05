"""Tips v0.9 decision-time context (V6, 2026-10-05; plan docs/techniques/tip/research/2026-10-04-v09/PLAN.md §V6).

One deterministic read per symbol per session, seeded into the analyst header (prefetch) and carried on every card
(`context.entryContext`):

- ATR % (daily ATR14 / prior close), relative volume (session-to-date volume vs the 20-day average, with a linear
  time-of-day adjustment), distance to the 20/50-day MA, gap % (today's open vs prior close) and change % (now vs
  prior close), relative strength vs SPY (5/20-session return difference)
- market regime: SPY vs its 200-day MA, SPY 2-year return, SPY 126-session realised volatility, VIX level
- short interest when Yahoo's defaultKeyStatistics has it (shortRatio = days to cover, short % of float); the sector
  (assetProfile) feeds the V5.3 sector cap
- earnings: days to the next known report (the existing calendar)

Rules: bounded fetches (`techniques.tip.entry_context_timeout_s` each, run concurrently), a failed item is labelled
`unavailable` and never invented, nothing here ever blocks a card (the caller treats a missing context as unknown),
the synthetic sim feed makes no network calls (tests inject `OVERRIDE` fetchers). Cached per (symbol, ET session)
for `techniques.tip.entry_context_ttl_s`; the SPY/VIX regime once per session; the profile for 24 h.

V6.2 regime guard and V6.3 chase filter are pure decisions over this read (`regime_decision`, `chase_decision`).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import math
import time
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

CONTEXT_VERSION = "entry-context-v1"
ET = ZoneInfo("America/New_York")
PROFILE_TTL_S = 24 * 3600
REGIME_TTL_S = 1800

# tests (and only tests) inject fetchers: {"daily": async (symbol, calendar_days) -> [Bar], "profile": async
# (symbol) -> {sector, industry, shortRatio, shortPctFloat}, "vix": async () -> float | None,
# "earnings": async (symbol) -> int | None}
OVERRIDE: dict | None = None

_CTX: dict[tuple[str, str], tuple[float, dict]] = {}
_REGIME: dict[str, tuple[float, dict]] = {}
_PROFILE: dict[str, tuple[float, dict]] = {}


def clear_cache() -> None:
    _CTX.clear()
    _REGIME.clear()
    _PROFILE.clear()


# ------------------------------------------------------------------ pure arithmetic
def _session_date(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(int(ts_ms) / 1000, dt.timezone.utc).astimezone(ET).strftime("%Y-%m-%d")


def split_daily(bars: list, today: str) -> tuple[list, object | None]:
    """(completed sessions before `today`, today's bar or None), sorted by time."""
    bars = sorted(bars or [], key=lambda b: int(b.ts))
    done = [b for b in bars if _session_date(b.ts) < today]
    cur = next((b for b in reversed(bars) if _session_date(b.ts) == today), None)
    return done, cur


def atr(bars: list, n: int = 14) -> float | None:
    if len(bars) < 2:
        return None
    trs = []
    for i in range(1, len(bars)):
        pc = float(bars[i - 1].close)
        h, lo = float(bars[i].high), float(bars[i].low)
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    tail = trs[-n:]
    return sum(tail) / len(tail) if tail else None


def sma(values: list[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def ret(closes: list[float], back: int) -> float | None:
    """% return from the value `back` steps before the last one to the last one."""
    if len(closes) <= back or back <= 0:
        return None
    base, end = closes[-1 - back], closes[-1]
    if not base:
        return None
    return (float(end) / float(base) - 1.0) * 100.0


def elapsed_fraction(now_et: dt.datetime) -> float | None:
    """Share of the regular session elapsed (None before the open, 1.0 after the close)."""
    if now_et.weekday() >= 5:
        return 1.0
    m = now_et.hour * 60 + now_et.minute - (9 * 60 + 30)
    if m < 0:
        return None
    return min(1.0, max(m, 1) / 390.0)


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), nd)


def symbol_metrics(done: list, *, last: float | None, prev_close: float | None, day_volume: float | None,
                   today_open: float | None, frac: float | None) -> dict:
    closes = [float(b.close) for b in done]
    pc = prev_close if (prev_close and prev_close > 0) else (closes[-1] if closes else None)
    px = last if (last and last > 0) else pc
    a = atr(done)
    vols = [float(b.volume or 0) for b in done[-20:] if (b.volume or 0) > 0]
    avg_v = (sum(vols) / len(vols)) if len(vols) >= 10 else None
    rvol = rvol_adj = None
    if avg_v and day_volume and day_volume > 0 and frac is not None:
        rvol = day_volume / avg_v
        rvol_adj = rvol / max(frac, 0.05)
    ma20, ma50 = sma(closes, 20), sma(closes, 50)
    return {
        "price": _r(px, 4), "prevClose": _r(pc, 4),
        "atr": _r(a, 4), "atrPct": _r((a / pc * 100.0) if (a and pc) else None),
        "rvol": _r(rvol), "rvolAdj": _r(rvol_adj), "avgVolume20": (int(avg_v) if avg_v else None),
        "ma20": _r(ma20, 4), "ma50": _r(ma50, 4),
        "distMa20Pct": _r(((px / ma20 - 1) * 100.0) if (px and ma20) else None),
        "distMa50Pct": _r(((px / ma50 - 1) * 100.0) if (px and ma50) else None),
        "gapPct": _r(((today_open / pc - 1) * 100.0) if (today_open and pc) else None),
        "changePct": _r(((px / pc - 1) * 100.0) if (px and pc) else None),
        "ret5": _r(ret(closes + ([px] if (last and last > 0) else []), 5)),
        "ret20": _r(ret(closes + ([px] if (last and last > 0) else []), 20)),
        "sessions": len(done),
    }


def regime_metrics(done: list, *, last: float | None, vix: float | None) -> dict:
    closes = [float(b.close) for b in done]
    px = last if (last and last > 0) else (closes[-1] if closes else None)
    series = closes + ([px] if (last and last > 0) else [])     # a live print extends the series; never a duplicate
    ma200 = sma(closes, 200)
    vol = None
    if len(closes) >= 127:
        lr = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - 126, len(closes)) if closes[i - 1] > 0]
        if len(lr) > 2:
            mu = sum(lr) / len(lr)
            vol = math.sqrt(sum((x - mu) ** 2 for x in lr) / (len(lr) - 1)) * math.sqrt(252) * 100.0
    return {
        "spy": _r(px, 2), "spyMa200": _r(ma200, 2),
        "spyAbove200": (None if (px is None or ma200 is None) else bool(px >= ma200)),
        "spy2yPct": _r(ret(series, 504)), "spyVol126Pct": _r(vol), "vix": _r(vix),
        "spyRet5": _r(ret(series, 5)), "spyRet20": _r(ret(series, 20)),
        "sessions": len(done),
    }


def compose(sym: dict, regime: dict, profile: dict | None, earnings_days: int | None, *, symbol: str,
            session: str, problems: dict) -> dict:
    rs5 = (sym["ret5"] - regime["spyRet5"]) if (sym.get("ret5") is not None and regime.get("spyRet5") is not None) else None
    rs20 = (sym["ret20"] - regime["spyRet20"]) if (sym.get("ret20") is not None and regime.get("spyRet20") is not None) else None
    prof = profile or {}
    return {"version": CONTEXT_VERSION, "symbol": symbol, "session": session, "status": "ok" if sym.get("sessions") else "partial",
            **{k: v for k, v in sym.items() if k != "sessions"},
            "rs5": _r(rs5), "rs20": _r(rs20),
            "regime": {k: v for k, v in regime.items() if k not in ("spyRet5", "spyRet20", "sessions")},
            **({"sector": prof.get("sector")} if prof.get("sector") else {}),
            **({"shortRatio": _r(prof.get("shortRatio"))} if prof.get("shortRatio") is not None else {}),
            **({"shortPctFloat": _r(prof.get("shortPctFloat"))} if prof.get("shortPctFloat") is not None else {}),
            "daysToEarnings": earnings_days,
            **({"unavailable": problems} if problems else {})}


def header_line(ctx: dict | None) -> str:
    """One compact line for the analyst header ('' when there is nothing)."""
    if not ctx or ctx.get("status") in (None, "off"):
        return ""
    if ctx.get("status") == "offline":
        return "- decision-time context: unavailable (offline feed)\n"

    def f(k, unit="%", sign=True):
        v = ctx.get(k)
        if v is None:
            return "n/a"
        return (f"{v:+g}" if sign else f"{v:g}") + unit
    rg = ctx.get("regime") or {}
    bits = [f"ATR {f('atrPct', '%', False)}", f"RVOL {ctx.get('rvolAdj') if ctx.get('rvolAdj') is not None else 'n/a'}x (time-adj)",
            f"vs MA20 {f('distMa20Pct')}", f"vs MA50 {f('distMa50Pct')}", f"gap {f('gapPct')}", f"now vs prior close {f('changePct')}",
            f"RS vs SPY 5d {f('rs5')} / 20d {f('rs20')}"]
    if ctx.get("shortRatio") is not None:
        bits.append(f"days-to-cover {ctx['shortRatio']:g}")
    if ctx.get("sector"):
        bits.append(f"sector {ctx['sector']}")
    reg = (f"regime: SPY {'above' if rg.get('spyAbove200') else 'below' if rg.get('spyAbove200') is False else 'n/a vs'} its "
           f"200-day MA, 2-yr {rg.get('spy2yPct') if rg.get('spy2yPct') is not None else 'n/a'}%, "
           f"126d vol {rg.get('spyVol126Pct') if rg.get('spyVol126Pct') is not None else 'n/a'}%, "
           f"VIX {rg.get('vix') if rg.get('vix') is not None else 'n/a'}")
    miss = ctx.get("unavailable") or {}
    return ("- decision-time context (deterministic, daily bars): " + " · ".join(bits) + "; " + reg
            + (f" [unavailable: {', '.join(sorted(miss))}]" if miss else "") + "\n")


def card_context(ctx: dict | None) -> dict | None:
    """The compact copy carried on the proposal (`context.entryContext`)."""
    if not ctx or ctx.get("status") in (None, "off"):
        return None
    keep = ("version", "status", "session", "price", "prevClose", "atrPct", "rvol", "rvolAdj", "distMa20Pct",
            "distMa50Pct", "gapPct", "changePct", "rs5", "rs20", "sector", "shortRatio", "shortPctFloat",
            "daysToEarnings", "unavailable", "regime")
    return {k: ctx.get(k) for k in keep if ctx.get(k) is not None}


# ------------------------------------------------------------------ V6.2 / V6.3 pure decisions
def _mode(settings, key: str) -> str:
    v = str(settings.get(key, "observe") or "observe").lower()
    return v if v in ("off", "observe", "enforce") else "observe"


def regime_decision(ctx: dict | None, *, direction: str, settings) -> dict:
    """Hostile = SPY 2-year return < 0 AND high volatility (VIX > techniques.tip.regime_vix_max when VIX is known,
    else SPY 126-session realised vol > techniques.tip.regime_vol_max). A momentum entry (a long that is not a dip:
    price at/above its 20-day MA or up on the day) would be halved. Unknown regime never acts."""
    mode = _mode(settings, "techniques.tip.regime_guard")
    rg = (ctx or {}).get("regime") or {}
    vix_max = float(settings.get("techniques.tip.regime_vix_max", 25.0) or 25.0)
    vol_max = float(settings.get("techniques.tip.regime_vol_max", 25.0) or 25.0)
    two = rg.get("spy2yPct")
    if rg.get("vix") is not None:
        high_vol, vol_basis = float(rg["vix"]) > vix_max, f"VIX {rg['vix']} vs {vix_max:g}"
    elif rg.get("spyVol126Pct") is not None:
        high_vol, vol_basis = float(rg["spyVol126Pct"]) > vol_max, f"SPY 126d vol {rg['spyVol126Pct']}% vs {vol_max:g}%"
    else:
        high_vol, vol_basis = None, "volatility unknown"
    hostile = None if (two is None or high_vol is None) else bool(float(two) < 0 and high_vol)
    d20, chg = (ctx or {}).get("distMa20Pct"), (ctx or {}).get("changePct")
    momentum = direction != "short" and not (d20 is not None and d20 < 0 and chg is not None and chg < 0)
    acts = bool(hostile and momentum and mode != "off")
    return {"mode": mode, "hostile": hostile, "momentum": momentum, "spy2yPct": two, "volBasis": vol_basis,
            "would": ("halve" if acts else None), "scale": (0.5 if acts else 1.0), "applied": bool(acts and mode == "enforce")}


def chase_decision(ctx: dict | None, *, direction: str, entry_price: float | None, settings) -> dict:
    """A chased entry: >= techniques.tip.chase_threshold_pct above the prior close (mirrored for a short). Would use
    the SHORT horizon (time box <= 3 sessions) and half size (R3: such entries fade after ~3 sessions)."""
    mode = _mode(settings, "techniques.tip.chase_filter")
    thr = float(settings.get("techniques.tip.chase_threshold_pct", 2.0) or 2.0)
    pc = (ctx or {}).get("prevClose")
    px = entry_price if (entry_price and entry_price > 0) else (ctx or {}).get("price")
    if not pc or not px:
        return {"mode": mode, "chased": None, "entryVsPrevClosePct": None, "would": None, "scale": 1.0, "applied": False}
    pct = (float(px) / float(pc) - 1.0) * 100.0
    chased = (pct >= thr) if direction != "short" else (pct <= -thr)
    acts = bool(chased and mode != "off")
    return {"mode": mode, "chased": bool(chased), "entryVsPrevClosePct": round(pct, 2), "thresholdPct": thr,
            "would": ("short horizon + half size" if acts else None), "horizon": ("short" if acts else None),
            "maxHoldSessions": (3 if acts else None), "scale": (0.5 if acts else 1.0),
            "applied": bool(acts and mode == "enforce")}


# ------------------------------------------------------------------ fetchers
def _offline(eng) -> bool:
    with contextlib.suppress(Exception):
        from .risk_evidence import offline_feed
        return offline_feed(eng)
    return False


async def _net_daily(symbol: str, calendar_days: int) -> list:
    from ...marketstructure.history import fetch_window
    end = int(time.time() * 1000)
    return await fetch_window(symbol, "1d", end - int(calendar_days) * 86400 * 1000, end)


async def _net_profile(eng, symbol: str) -> dict:
    cal = getattr(eng, "calendar", None)
    if cal is None or not hasattr(cal, "quote_summary"):
        return {}
    qs = await cal.quote_summary(symbol, ("assetProfile", "defaultKeyStatistics"))
    ap = qs.get("assetProfile") or {}
    ks = qs.get("defaultKeyStatistics") or {}

    def raw(d, k):
        v = d.get(k)
        return v.get("raw") if isinstance(v, dict) else (v if isinstance(v, (int, float)) else None)
    spf = raw(ks, "shortPercentOfFloat")
    return {"sector": ap.get("sector") or None, "industry": ap.get("industry") or None,
            "shortRatio": raw(ks, "shortRatio"), "shortPctFloat": (spf * 100.0 if spf is not None else None)}


async def _net_vix() -> float | None:
    bars = await _net_daily("^VIX", 10)
    return float(sorted(bars, key=lambda b: int(b.ts))[-1].close) if bars else None


async def _bounded(coro, timeout: float):
    try:
        return True, await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError:
        return False, f"timed out after {timeout:g}s"
    except Exception as exc:                            # noqa: BLE001 - labelled, never fatal
        return False, f"{type(exc).__name__}: {str(exc)[:100]}"


def _fetchers(eng) -> dict | None:
    if OVERRIDE is not None:
        return OVERRIDE
    if _offline(eng):
        return None

    async def earnings(sym):
        cal = getattr(eng, "calendar", None)
        return await cal.days_to_earnings(sym) if cal is not None else None
    return {"daily": _net_daily, "profile": lambda sym: _net_profile(eng, sym), "vix": _net_vix, "earnings": earnings}


async def profile(eng, symbol: str, *, timeout_s: float | None = None) -> dict:
    """Sector + short-interest profile, cached 24 h; {} when unknown."""
    sym = str(symbol or "").upper()
    hit = _PROFILE.get(sym)
    if hit and time.time() - hit[0] < PROFILE_TTL_S:
        return hit[1]
    fx = _fetchers(eng)
    if fx is None or not sym:
        return {}
    t = float(timeout_s if timeout_s is not None else eng.settings.get("techniques.tip.entry_context_timeout_s", 4.0) or 4.0)
    ok, val = await _bounded(fx["profile"](sym), t)
    out = val if (ok and isinstance(val, dict)) else {}
    if ok:
        _PROFILE[sym] = (time.time(), out)
    return out


async def sector_of(eng, symbol: str) -> str | None:
    return (await profile(eng, symbol)).get("sector") or None


async def _regime(eng, fx: dict, session: str, t: float) -> tuple[dict, dict]:
    hit = _REGIME.get(session)
    if hit and time.time() - hit[0] < REGIME_TTL_S:
        return hit[1], {}
    (ok_s, spy), (ok_v, vix) = await asyncio.gather(_bounded(fx["daily"]("SPY", 780), t), _bounded(fx["vix"](), t))
    problems = {}
    if not ok_s:
        problems["spy"] = spy
    if not ok_v:
        problems["vix"] = vix
    done, _cur = split_daily(spy if ok_s else [], session)
    q = None
    with contextlib.suppress(Exception):
        q = eng.quotes.get("SPY")
    last = (float(q.last) if (q is not None and q.last and q.last > 0) else None)
    reg = regime_metrics(done, last=last, vix=(vix if ok_v else None))
    if ok_s and done:
        _REGIME[session] = (time.time(), reg)
    return reg, problems


async def get(eng, symbol: str, *, timeout_s: float | None = None, now: dt.datetime | None = None) -> dict:
    """The decision-time context for `symbol` (never raises; status off | offline | ok | partial)."""
    s = eng.settings
    if not bool(s.get("techniques.tip.entry_context", True)):
        return {"version": CONTEXT_VERSION, "status": "off"}
    sym = str(symbol or "").upper()
    now_et = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    session = now_et.strftime("%Y-%m-%d")
    ttl = float(s.get("techniques.tip.entry_context_ttl_s", 600) or 600)
    hit = _CTX.get((sym, session))
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    fx = _fetchers(eng)
    if fx is None:
        return {"version": CONTEXT_VERSION, "status": "offline", "symbol": sym}
    t = float(timeout_s if timeout_s is not None else s.get("techniques.tip.entry_context_timeout_s", 4.0) or 4.0)
    try:
        (ok_d, daily), (reg, reg_problems), prof, (ok_e, earn) = await asyncio.gather(
            _bounded(fx["daily"](sym, 110), t), _regime(eng, fx, session, t), profile(eng, sym, timeout_s=t),
            _bounded(fx["earnings"](sym), t) if fx.get("earnings") else _done((True, None)))
    except Exception as exc:                            # noqa: BLE001 - the context never fails a card
        log.debug("entry context failed for %s: %s", sym, exc)
        return {"version": CONTEXT_VERSION, "status": "unavailable", "symbol": sym, "why": str(exc)[:120]}
    problems = dict(reg_problems)
    if not ok_d:
        problems["daily"] = daily
    if not ok_e:
        problems["earnings"] = earn
    done, cur = split_daily(daily if ok_d else [], session)
    q = None
    with contextlib.suppress(Exception):
        q = eng.quotes.get(sym)
    last = prev = vol = None
    if q is not None:
        last = float(q.reg_price) if (getattr(q, "reg_price", 0) or 0) > 0 and getattr(q, "session", "") == "regular" else float(q.last or 0) or None
        prev = float(q.prev_close or 0) or None
        vol = float(q.volume or 0) or None
    if vol is None and cur is not None:
        vol = float(cur.volume or 0) or None
    if last is None and cur is not None:
        last = float(cur.close)
    sm = symbol_metrics(done, last=last, prev_close=prev, day_volume=vol,
                        today_open=(float(cur.open) if cur is not None else None), frac=elapsed_fraction(now_et))
    ctx = compose(sm, reg, prof, (earn if ok_e else None), symbol=sym, session=session, problems=problems)
    if ok_d and done:
        _CTX[(sym, session)] = (time.time(), ctx)
    return ctx


async def _done(v):
    return v
