"""Flow scan math — pure functions over normalized chain rows. No I/O.

Inputs are the provider-normalized rows from `zargar.options.chain` (volume,
open_interest, bid/ask, greeks.mid_iv) plus the underlying spot. The research
grounding (docs/TECHNIQUE-CANDIDATES.md T2): opening activity shows as
volume >> open interest (Barchart's public recipe is Vol/OI >= 1.25); the
informative footprint is near-dated, somewhat-OTM, money-weighted (Hilliard
2025); repeat hits across days with overnight OI confirmation are the
practitioner filter delayed data CAN deliver, because OI updates overnight.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class FlowThresholds:
    vol_oi_min: float = 1.25
    vol_oi_strong: float = 5.0
    premium_min: float = 100_000.0       # mid * volume * 100
    min_contract_volume: int = 500
    min_open_interest: int = 100
    dte_max: int = 45
    otm_min_pct: float = 0.0
    otm_max_pct: float = 12.0
    repeat_days: int = 3
    repeat_window: int = 5
    os_ratio_flag: float = 0.5           # options volume / stock volume

    @classmethod
    def from_settings(cls, settings) -> "FlowThresholds":
        def g(key: str, fallback):
            v = settings.get(f"techniques.flow.{key}", fallback)
            return fallback if v is None else v
        return cls(
            vol_oi_min=float(g("vol_oi_min", 1.25)),
            vol_oi_strong=float(g("vol_oi_strong", 5.0)),
            premium_min=float(g("premium_min", 100_000.0)),
            min_contract_volume=int(g("min_contract_volume", 500)),
            min_open_interest=int(g("min_open_interest", 100)),
            dte_max=int(g("dte_max", 45)),
            otm_min_pct=float(g("otm_min_pct", 0.0)),
            otm_max_pct=float(g("otm_max_pct", 12.0)),
            repeat_days=int(g("repeat_days", 3)),
            repeat_window=int(g("repeat_window", 5)),
            os_ratio_flag=float(g("os_ratio_flag", 0.5)),
        )


def _mid(row: dict) -> float:
    bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return float(row.get("last") or 0) or max(bid, ask)


def _dte(expiry: str, day: str) -> int:
    try:
        return (dt.date.fromisoformat(expiry) - dt.date.fromisoformat(day)).days
    except ValueError:
        return 10_000


def _otm_pct(row: dict, spot: float) -> float:
    """% out of the money; negative = ITM."""
    strike = float(row.get("strike") or 0)
    if spot <= 0 or strike <= 0:
        return 999.0
    if row.get("option_type") == "call":
        return (strike - spot) / spot * 100
    return (spot - strike) / spot * 100


def fmt_occ(contract: str | None) -> str:
    """Unpadded OCC -> human short form: 'TSM260904C00422500' -> '09/04 422.5C'."""
    import re
    m = re.match(r"^([A-Z.]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$", contract or "")
    if not m:
        return contract or "?"
    _, _, mm, dd, cp, k8 = m.groups()
    k = int(k8) / 1000
    return f"{mm}/{dd} {k:g}{cp}"


def spot_from_chain(rows: list[dict]) -> float:
    """Spot derived from the chain itself via put–call parity: at the strike
    where the nearest expiry's call and put mids are closest, spot ≈ strike +
    call_mid − put_mid. The offline fallback when no quote exists (cold boot,
    late scan) — a scan must never score a chain against spot 0 (2026-08-28:
    four boot re-scans overwrote a good day with zero flags because every
    contract 'failed' the OTM window)."""
    by: dict[tuple[str, float], dict[str, float]] = {}
    for r in rows:
        expiry, strike = str(r.get("expiry") or ""), float(r.get("strike") or 0)
        if not expiry or strike <= 0:
            continue
        m = _mid(r)
        if m <= 0:
            continue
        by.setdefault((expiry, strike), {})[str(r.get("option_type"))] = m
    pairs = [(exp, k, v["call"], v["put"])
             for (exp, k), v in by.items() if "call" in v and "put" in v]
    if not pairs:
        return 0.0
    nearest = min(p[0] for p in pairs)
    _, strike, c, p = min((p for p in pairs if p[0] == nearest),
                          key=lambda p: abs(p[2] - p[3]))
    spot = strike + c - p
    return round(spot, 4) if spot > 0 else 0.0


def last_weekday(day: "dt.date") -> "dt.date":
    """The given date, rolled back to Friday when it lands on a weekend — a
    Saturday 'Scan now' should re-read Friday's tape, not create a junk day."""
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def flag_contracts(rows: list[dict], *, spot: float, day: str, t: FlowThresholds) -> list[dict]:
    """The contracts whose day looked like opening accumulation: enough volume
    to mean something, volume >> OI, real money, near-dated, somewhat OTM."""
    out: list[dict] = []
    for r in rows:
        vol = int(r.get("volume") or 0)
        oi = int(r.get("open_interest") or 0)
        if vol < t.min_contract_volume or oi < t.min_open_interest:
            continue
        dte = _dte(r.get("expiry") or "", day)
        if dte < 0 or dte > t.dte_max:
            continue
        otm = _otm_pct(r, spot)
        if otm < t.otm_min_pct or otm > t.otm_max_pct:
            continue
        vol_oi = vol / max(oi, 1)
        if vol_oi < t.vol_oi_min:
            continue
        mid = _mid(r)
        premium = mid * vol * 100
        if premium < t.premium_min:
            continue
        out.append({
            "contract": r.get("symbol"),
            "expiry": r.get("expiry"),
            "optionType": r.get("option_type"),
            "strike": float(r.get("strike") or 0),
            "volume": vol,
            "openInterest": oi,
            "volOi": round(vol_oi, 2),
            "mid": round(mid, 4),
            "premium": round(premium, 0),
            "otmPct": round(otm, 2),
            "dte": dte,
            "strong": vol_oi >= t.vol_oi_strong,
            "iv": (r.get("greeks") or {}).get("mid_iv"),
        })
    out.sort(key=lambda f: -f["premium"])
    return out


def confirm_oi(prev_flags: list[dict], today_oi: dict[str, int], *, ratio: float = 0.5) -> list[dict]:
    """Yesterday's flags whose open interest rose overnight by at least
    `ratio` x the flagged volume — the volume really was opening positions.
    This is the disambiguation retail flow feeds cannot give (no open/close
    tags on public prints); OI can, one day late."""
    confirmed = []
    for f in prev_flags:
        oi_now = today_oi.get(f.get("contract") or "")
        if oi_now is None:
            continue
        delta = oi_now - int(f.get("openInterest") or 0)
        if delta >= ratio * int(f.get("volume") or 0) > 0:
            confirmed.append({**f, "oiDelta": delta, "oiConfirmed": True})
    return confirmed


def repeat_counts(flag_days: dict[str, list[str]], *, window_days: list[str]) -> dict[str, int]:
    """contract -> number of distinct days flagged inside the window
    (window_days = the last N session dates, newest last)."""
    win = set(window_days)
    return {c: len(set(days) & win) for c, days in flag_days.items() if set(days) & win}


def aggregate_symbol(rows: list[dict], *, stock_volume: int | None) -> dict:
    call_vol = sum(int(r.get("volume") or 0) for r in rows if r.get("option_type") == "call")
    put_vol = sum(int(r.get("volume") or 0) for r in rows if r.get("option_type") == "put")
    call_prem = sum(_mid(r) * int(r.get("volume") or 0) * 100 for r in rows if r.get("option_type") == "call")
    put_prem = sum(_mid(r) * int(r.get("volume") or 0) * 100 for r in rows if r.get("option_type") == "put")
    total = call_vol + put_vol
    # O/S: options volume in SHARE-equivalents (x100) over stock volume (Johnson-So)
    os_ratio = (total * 100 / stock_volume) if stock_volume else None
    return {
        "callVolume": call_vol, "putVolume": put_vol, "totalVolume": total,
        "pcVolumeRatio": round(put_vol / call_vol, 3) if call_vol else None,
        "callPremium": round(call_prem, 0), "putPremium": round(put_prem, 0),
        "osRatio": round(os_ratio, 4) if os_ratio is not None else None,
    }


def build_read(symbol: str, day: str, *, flags: list[dict], confirmed: list[dict],
               repeats: dict[str, int], agg: dict, t: FlowThresholds,
               spot: float | None = None) -> dict:
    """The day's verdict for one symbol: a transparent additive score with a
    plain-language reason per point, and a directional lean from where the
    flagged premium sits. Context, not a trade."""
    score = 0.0
    reasons: list[str] = []
    call_prem = sum(f["premium"] for f in flags if f["optionType"] == "call")
    put_prem = sum(f["premium"] for f in flags if f["optionType"] == "put")
    if flags:
        score += min(len(flags), 3)
        reasons.append(f"{len(flags)} contract(s) with opening-style volume "
                       f"(Vol/OI >= {t.vol_oi_min:g}, premium >= ${t.premium_min:,.0f})")
    strong = [f for f in flags if f["strong"]]
    if strong:
        score += 1
        reasons.append(f"{len(strong)} at Vol/OI >= {t.vol_oi_strong:g} (aggressive)")
    if confirmed:
        score += 2 * min(len(confirmed), 2)
        reasons.append(f"{len(confirmed)} of yesterday's flags OI-confirmed overnight "
                       "(the volume really opened positions)")
    hot = {c: n for c, n in repeats.items() if n >= t.repeat_days}
    if hot:
        score += 3
        reasons.append(f"repeat accumulation: {len(hot)} contract(s) flagged on "
                       f">= {t.repeat_days} of the last {t.repeat_window} sessions")
    os_ratio = agg.get("osRatio")
    bear_os = os_ratio is not None and os_ratio >= t.os_ratio_flag
    if bear_os:
        reasons.append(f"high options/stock volume ratio ({os_ratio:g}) — historically a "
                       "bearish flag (Johnson-So)")
    if call_prem > 2 * put_prem and call_prem > 0:
        lean = "bull"
    elif put_prem > 2 * call_prem and put_prem > 0:
        lean = "bear"
    elif call_prem or put_prem:
        lean = "mixed"
    else:
        lean = "none"
    if bear_os and lean == "bull":
        lean = "mixed"
        reasons.append("call flow against a bearish O/S ratio — treated as mixed")
    return {
        "symbol": symbol.upper(), "day": day, "score": round(score, 1), "lean": lean,
        "spot": spot, "reasons": reasons, "flags": flags[:10], "confirmed": confirmed[:10],
        "repeatHits": hot, "aggregates": agg,
    }


def context_line(read: dict | None) -> str | None:
    """One plain-language sentence for another technique's context (Tip
    verification, EM reads). None when there is nothing worth saying."""
    if not read or not read.get("score"):
        return None
    lean = {"bull": "call accumulation", "bear": "put accumulation",
            "mixed": "two-sided flow", "none": "flow"}.get(read.get("lean") or "none")
    top = (read.get("flags") or [{}])[0]
    detail = ""
    if top.get("contract"):
        detail = (f"; largest: {top['contract']} ${top['premium']:,.0f} "
                  f"at Vol/OI {top['volOi']:g}")
    return (f"Options flow {read['day']}: {lean}, score {read['score']:g}"
            f" — {read['reasons'][0] if read.get('reasons') else ''}{detail}")
