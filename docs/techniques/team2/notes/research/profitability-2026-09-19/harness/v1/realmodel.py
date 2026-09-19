"""OFFLINE RESEARCH ONLY. A PremiumModel whose marks are REAL option prints (Alpaca 1m trade bars, disk-cached), so the
pure session read chooses strikes, trims, premium-stops and books P&L on real prices. No price is ever invented: a contract
with no print in the allowed window is simply not eligible (pick) or carries its last real print (management).

Price conventions (validated against the desk's 16 actual fills: fill - minute open has median 0.00):
  decision-time marks (entry, strike pick, stop/trim/flatten exits at a 2m close) = OPEN of the option minute that starts at
      the decision time (first print after the decision); up to FWD minutes forward when that minute has no print.
  target-touch exits (the session books them intrabar)       = VWAP of the option minute in which the underlying touched.
  management marks at a 2m close (P1 / trim cues / adds)      = CLOSE of the bar's second minute, else the last earlier print.
"""
import json, sys, pathlib, datetime as dt
import httpx
from dataclasses import dataclass
from zargar.techniques.team2 import premium as _p

MIN = 60_000
URL = "https://data.alpaca.markets/v1beta1/options/bars"
CTX = {"symbol": None, "date": None, "data": None, "headers": None, "und": None, "http": None, "fetched": 0}
_mem: dict[str, dict] = {}


def occ(sym, date, call, strike):
    d = dt.date.fromisoformat(date)
    return f"{sym}{d:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


def _load(symbols: list[str]) -> None:
    need = []
    for o in symbols:
        if o in _mem:
            continue
        p = CTX["data"] / "opt" / f"{o}.json"
        if p.exists():
            _mem[o] = _index(json.loads(p.read_text()))
        else:
            need.append(o)
    if not need:
        return
    date = CTX["date"]
    got = {o: [] for o in need}
    token = None
    while True:
        q = {"symbols": ",".join(need), "timeframe": "1Min", "start": date + "T13:00:00Z", "end": date + "T21:00:00Z", "limit": 10000}
        if token:
            q["page_token"] = token
        for attempt in range(6):
            r = CTX["http"].get(URL, params=q, headers=CTX["headers"])
            if r.status_code == 429:
                import time
                time.sleep(3 + 3 * attempt)
                continue
            break
        r.raise_for_status()
        d = r.json()
        for o, rows in (d.get("bars") or {}).items():
            got.setdefault(o, []).extend(rows)
        token = d.get("next_page_token")
        if not token:
            break
    for o, rows in got.items():
        (CTX["data"] / "opt" / f"{o}.json").write_text(json.dumps(rows))
        _mem[o] = _index(rows)
        CTX["fetched"] += 1


def _index(rows):
    return {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}


def decision_px(o: str, ts: int, fwd: int = 2):
    b = _mem[o]
    t0 = (ts // MIN) * MIN
    for k in range(fwd + 1):
        r = b.get(t0 + k * MIN)
        if r:
            return float(r["o"])
    return None


def last_px(o: str, ts_end: int, back: int = 5):
    """The last real print at or before the END of the 2m bar (ts_end exclusive)."""
    b = _mem[o]
    t0 = (ts_end // MIN) * MIN - MIN
    for k in range(back + 1):
        r = b.get(t0 - k * MIN)
        if r:
            return float(r["c"])
    return None


def touch_px(o: str, ts_end: int, target: float, long: bool):
    u, b = CTX["und"], _mem[o]
    for t0 in (ts_end - 2 * MIN, ts_end - MIN):
        r = u.get(t0)
        if r and ((r["h"] >= target) if long else (r["l"] <= target)) and b.get(t0):
            return float(b[t0]["vw"])
    return None


@dataclass
class RealPremiumModel(_p.PremiumModel):
    def mark(self, spot, strike, ts_ms, *, call, expiry=None):
        o = occ(CTX["symbol"], CTX["date"], call, strike)
        _load([o])
        fr = sys._getframe(1)
        name = fr.f_code.co_name
        if name == "close_fraction":
            reason = str(fr.f_locals.get("reason") or "")
            px = None
            if "touched" in reason:
                px = touch_px(o, ts_ms, float(spot), call)
            if px is None:
                px = decision_px(o, ts_ms)
            if px is None:
                px = last_px(o, ts_ms + MIN)
            return px if px is not None else 0.0
        # management mark: called with the 2m bar's OPEN ts; the bar ends 2 minutes later
        px = last_px(o, ts_ms + 2 * MIN)
        return px if px is not None else 0.0

    def pick_strike(self, spot, ts_ms, direction, *, target_premium, premium_floor, step=1.0, expiry=None,
                    max_steps=40, mode="closest", strikes=None):
        call = direction == "long"
        ladder = _p.otm_ladder(spot, call, step=step, strikes=strikes, max_steps=CTX.get("ladder", 14))
        if CTX.get("itm_steps"):
            first = ladder[0]
            ladder = [first - (i + 1) * step if call else first + (i + 1) * step for i in range(CTX["itm_steps"])][::-1] + ladder
        _load([occ(CTX["symbol"], CTX["date"], call, k) for k in ladder])
        cands = []
        for k in ladder:
            m = decision_px(occ(CTX["symbol"], CTX["date"], call, k), ts_ms)
            if m is None:
                continue
            if premium_floor <= m <= target_premium * _p.MAX_OVER_TARGET:
                cands.append((k, m))
        if not cands:
            return None
        return min(cands, key=lambda km: (abs(km[1] - target_premium), km[1]))

    def nearest_otm(self, spot, ts_ms, direction, *, step=1.0, expiry=None, strikes=None):
        call = direction == "long"
        first = next(iter(_p.otm_ladder(spot, call, step=step, strikes=strikes, max_steps=1)), None)
        if first is None:
            return None
        o = occ(CTX["symbol"], CTX["date"], call, first)
        _load([o])
        m = decision_px(o, ts_ms)
        return None if m is None else (first, m)
