"""Option trade prints -> sweeps (FLOW-CONFIRMATION-PLAN, phase 0).

The author's trigger is a burst of buyer-initiated option volume, many times
the contract's open interest, in a near-the-money strike minutes after the
open ("sweeps started lifting the $360 calls ... 122,038 contracts against
6,742 open interest"). This module turns raw prints into that signal:

  fetch_option_trades()  Alpaca options trades (REST, paged) for one contract
  classify_tick()        per-minute totals with a TICK-TEST buy estimate - our
                         plan has no historical option quotes, so an uptick
                         (or a repeat at the last price, half-weighted) is
                         counted as buyer-initiated; the live detector uses
                         the real NBBO instead and records which method it used
  detect_sweeps()        pure: the first minute a rolling window qualifies

Calibration (2026-09-08, TSLA $360C 2026-08-31, the author's +240% trade):
cumulative volume crossed 3x open interest at 09:40 and 5.3x at 09:45; the
biggest 5-minute window (09:45-09:49) carried 18,159 contracts, 8,445 of them
tick-test buys; he entered at 09:49. GPRO $1C the same day: 32,651 contracts on
2,733 open interest, biggest window 5,199 / 2,561 buys at 14:21. The defaults
below fire on both at the right minute and on nothing quiet.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

TRADES_URL = "https://data.alpaca.markets/v1beta1/options/trades"
ET = dt.timezone(dt.timedelta(hours=-4))       # prints are stamped UTC; minutes are bucketed in ET
MIN = 60_000


@dataclass(frozen=True)
class SweepRules:
    window_minutes: int = 5
    min_window_buys: int = 250                # absolute floor: thin names never qualify on a handful of prints
    window_buys_vs_oi: float = 0.25           # the window's buys vs open interest
    min_cumulative: int = 1000                # absolute floor on session volume
    cumulative_vs_oi: float = 3.0             # session volume vs open interest ("many times the OI")
    cooldown_minutes: int = 10                # one sweep per contract per cooldown
    assumed_oi: int = 2000                    # when open interest is unknown (no snapshot row), judge against this - never against 1
    burst_vs_baseline: float = 3.0            # the window's buys vs the contract's own prior 30-min pace (NVDA 0DTE puts
    #                                           printed 500k contracts on 2026-09-04: every 10 minutes looked like a sweep
    #                                           against OI; against its own pace only the real bursts do)
    baseline_minutes: int = 30
    min_baseline_minutes: int = 15            # inside the first 15 minutes the pace test is skipped (the open IS the burst)
    max_per_day: int = 3                      # after three sweeps a contract is simply busy, not swept


@dataclass
class MinuteFlow:
    ts: int                                    # minute start, epoch ms
    contracts: int = 0
    buys: int = 0                              # buyer-initiated (tick test or NBBO)
    prints: int = 0
    big_prints: int = 0                        # prints of 100+ contracts
    notional: float = 0.0                      # contracts x price x 100
    method: str = "tick"


@dataclass
class Sweep:
    occ: str
    ts: int                                    # the minute the window qualified
    window_contracts: int
    window_buys: int
    cumulative: int
    oi: int
    vol_oi: float                              # cumulative / max(oi, 1)
    big_prints: int
    notional: float
    method: str = "tick"

    def to_dict(self) -> dict:
        return {"occ": self.occ, "ts": self.ts, "windowContracts": self.window_contracts,
                "windowBuys": self.window_buys, "cumulative": self.cumulative, "oi": self.oi,
                "volOi": round(self.vol_oi, 2), "bigPrints": self.big_prints,
                "notional": round(self.notional, 0), "method": self.method}


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def fetch_option_trades(occ: str, start_ms: int, end_ms: int, *, key: str, secret: str,
                              http: httpx.AsyncClient | None = None, max_pages: int = 40) -> list[dict]:
    """Raw prints for one contract in [start, end]: {"t": iso, "p": price, "s": size, "x": exchange, "c": cond}."""
    own = http is None
    http = http or httpx.AsyncClient(timeout=60)
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    out: list[dict] = []
    token = None
    try:
        for _ in range(max_pages):
            params = {"symbols": occ, "start": _iso(start_ms), "end": _iso(end_ms), "limit": 10_000}
            if token:
                params["page_token"] = token
            r = await http.get(TRADES_URL, params=params, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"Alpaca options/trades HTTP {r.status_code}: {r.text[:120]}")
            data = r.json()
            out.extend((data.get("trades") or {}).get(occ) or [])
            token = data.get("next_page_token")
            if not token:
                break
    finally:
        if own:
            await http.aclose()
    return out


def _print_ms(iso: str) -> int:
    s = iso.replace("Z", "+00:00")
    if "." in s:                                   # nanosecond stamps: keep 6 digits for fromisoformat
        head, tail = s.split(".", 1)
        frac, tz = tail[:-6], tail[-6:]
        s = f"{head}.{frac[:6]:0<6}{tz}"
    return int(dt.datetime.fromisoformat(s).timestamp() * 1000)


def classify_tick(trades: list[dict]) -> list[MinuteFlow]:
    """Per-minute flow with a tick-test buy estimate. An uptick counts as a buy,
    a print at the last price counts half, a downtick counts as a sell. Prints
    must be in time order (Alpaca returns them that way)."""
    by: dict[int, MinuteFlow] = {}
    last: float | None = None
    for t in trades:
        ts = _print_ms(str(t["t"]))
        m = (ts // MIN) * MIN
        f = by.get(m) or by.setdefault(m, MinuteFlow(ts=m))
        p, s = float(t["p"]), int(t.get("s") or 0)
        f.contracts += s
        f.prints += 1
        f.notional += s * p * 100.0
        if s >= 100:
            f.big_prints += 1
        if last is not None:
            if p > last:
                f.buys += s
            elif p == last:
                f.buys += s // 2
        last = p
    return [by[k] for k in sorted(by)]


def classify_nbbo(prints: list[tuple[int, float, int, float, float]]) -> list[MinuteFlow]:
    """Live path: prints as (ts_ms, price, size, bid, ask) with the NBBO at print
    time. At or above the ask (within a tick) = buy; at or below the bid = sell."""
    by: dict[int, MinuteFlow] = {}
    for ts, p, s, bid, ask in prints:
        m = (ts // MIN) * MIN
        f = by.get(m) or by.setdefault(m, MinuteFlow(ts=m, method="nbbo"))
        f.contracts += s
        f.prints += 1
        f.notional += s * p * 100.0
        if s >= 100:
            f.big_prints += 1
        tick = 0.01 if p >= 3 else 0.005
        if ask > 0 and p >= ask - tick:
            f.buys += s
        elif bid > 0 and p <= bid + tick:
            pass
        else:
            f.buys += s // 2
    return [by[k] for k in sorted(by)]


def detect_sweeps(occ: str, minutes: list[MinuteFlow], oi: int, rules: SweepRules = SweepRules()) -> list[Sweep]:
    """The minute(s) at which a rolling window of buyer-initiated volume, on top
    of a session that has already traded a multiple of the open interest,
    qualifies as a sweep. Pure; minutes must be sorted."""
    out: list[Sweep] = []
    oi_eff = int(oi) if oi and int(oi) > 0 else rules.assumed_oi
    cumulative = 0
    last_fire = None
    win_ms = rules.window_minutes * MIN
    for i, f in enumerate(minutes):
        cumulative += f.contracts
        lo = f.ts - win_ms + MIN
        window = [g for g in minutes[: i + 1] if g.ts >= lo]
        w_buys = sum(g.buys for g in window)
        w_all = sum(g.contracts for g in window)
        if w_buys < max(rules.min_window_buys, rules.window_buys_vs_oi * oi_eff):
            continue
        if cumulative < max(rules.min_cumulative, rules.cumulative_vs_oi * oi_eff):
            continue
        if last_fire is not None and f.ts - last_fire < rules.cooldown_minutes * MIN:
            continue
        # pace: the window must be a burst against the contract's own recent tape
        base_lo = f.ts - rules.baseline_minutes * MIN
        base = [g for g in minutes[:i] if base_lo <= g.ts < lo]
        if i >= rules.min_baseline_minutes and base:       # the first minutes of the session ARE the burst
            span_min = max(1, (lo - max(base_lo, base[0].ts)) // MIN)
            pace = sum(g.buys for g in base) / span_min * rules.window_minutes
            if w_buys < rules.burst_vs_baseline * max(pace, 1.0):
                continue
        if len(out) >= rules.max_per_day:
            break
        last_fire = f.ts
        out.append(Sweep(occ=occ, ts=f.ts, window_contracts=w_all, window_buys=w_buys, cumulative=cumulative,
                         oi=int(oi or 0), vol_oi=cumulative / oi_eff, big_prints=sum(g.big_prints for g in window),
                         notional=sum(g.notional for g in window), method=minutes[0].method if minutes else "tick"))
    return out


def et_minute(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000, ET).strftime("%H:%M")
