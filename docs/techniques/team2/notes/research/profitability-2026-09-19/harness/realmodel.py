"""OFFLINE RESEARCH ONLY (v2, 2026-09-19 correction pass). A PremiumModel whose marks are REAL option TRADE PRINTS
(Alpaca 1m option trade bars, disk-cached). These are prints, not quotes and not fills: every number produced with this
model is a SIMULATED EXECUTION ON REAL PRINTS.

Frozen conventions (see 02-input-and-coverage-manifest.md, "Pricing conventions"):

  T            = the read's decision time = the CLOSE of a 2m bar (a multiple of two minutes).
  SELECTION    uses only prints that existed at T: for each ladder strike the CLOSE of the latest option minute that
               ENDED at or before T, no older than SEL_AGE_MIN minutes. A strike with no such print is not eligible.
  EXECUTION    (entry) happens after T: the OPEN of the first option minute with a print in [T, T+EXEC_WINDOW_MIN).
               The order is a limit at the chase cap (target_premium x 1.5), so an execution print above the cap or
               below the premium floor is NO FILL and the entry is refused (time-dependent eligibility). Observation
               time, execution time and both prices are logged for every entry.
  MANAGEMENT   mark at a 2m close = the CLOSE of the latest option minute inside that same 2m bar (age <= 2 minutes).
               Otherwise the mark is UNKNOWN (NaN): the read takes no premium-based decision on that bar.
  DECISION EXITS (candle stop, premium stop, trims, flatten) at T = the OPEN of the first option minute with a print
               in [T, T+EXIT_WINDOW_MIN). None -> UNKNOWN (NaN): the trade is CENSORED, never priced at zero.
  TARGET EXITS the read books a target inside the 2m bar that ends at T. Intraminute order is unknown, so three
               scenarios are produced, never one "fill": `proxy` = VWAP of the option minute in which the underlying
               first touched; `conservative` = a decision exit at T (the bar close); `optimistic` = the HIGH of the
               touch minute. A touch minute without a print falls back to `conservative`.
No price is ever invented, carried beyond its permitted age, or replaced by zero.
"""
import json, sys, math, pathlib, datetime as dt, time as _time
from dataclasses import dataclass
from zargar.techniques.team2 import premium as _p

MIN = 60_000
SEL_AGE_MIN = 2
EXEC_WINDOW_MIN = 2
EXIT_WINDOW_MIN = 5
URL = "https://data.alpaca.markets/v1beta1/options/bars"
NAN = float("nan")
CTX = {"symbol": None, "date": None, "data": None, "headers": None, "und": None, "http": None, "fetched": 0,
       "touch_mode": "proxy", "ladder": 14, "offline": False}
LOG: list[dict] = []          # one row per entry attempt (selected or refused) and per unknown mark
_mem: dict[str, dict] = {}


def occ(sym, date, call, strike):
    d = dt.date.fromisoformat(date)
    return f"{sym}{d:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


def _index(rows):
    return {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}


def _load(symbols):
    need = []
    for o in symbols:
        if o in _mem:
            continue
        p = CTX["data"] / "opt" / f"{o}.json" if CTX["data"] else None
        if p is not None and p.exists():
            _mem[o] = _index(json.loads(p.read_text()))
        else:
            need.append(o)
    if not need:
        return
    if CTX["offline"]:
        raise RuntimeError(f"offline run needs cached contracts: {need[:3]}... ({len(need)})")
    date, got, token = CTX["date"], {o: [] for o in need}, None
    while True:
        q = {"symbols": ",".join(need), "timeframe": "1Min", "start": date + "T13:00:00Z", "end": date + "T21:00:00Z", "limit": 10000}
        if token:
            q["page_token"] = token
        for attempt in range(6):
            r = CTX["http"].get(URL, params=q, headers=CTX["headers"])
            if r.status_code == 429:
                _time.sleep(3 + 3 * attempt)
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


def observed_px(o, T, max_age_min=SEL_AGE_MIN):
    """Latest print that EXISTED at T: close of an option minute that ended at or before T. -> (price, print_minute_ts) | (None, None)"""
    b = _mem[o]
    t0 = (T // MIN) * MIN
    for k in range(1, max_age_min + 1):
        r = b.get(t0 - k * MIN)
        if r:
            return float(r["c"]), t0 - k * MIN
    return None, None


def exec_px(o, T, window_min):
    """First print AFTER the decision: open of the first option minute with a print in [T, T+window). -> (price, ts) | (None, None)"""
    b = _mem[o]
    t0 = (T // MIN) * MIN
    for k in range(window_min):
        r = b.get(t0 + k * MIN)
        if r:
            return float(r["o"]), t0 + k * MIN
    return None, None


def bar_mark(o, bar_open_ts):
    """Management mark for the 2m bar [t, t+2m): the latest print INSIDE it. Older prints are not carried."""
    b = _mem[o]
    for t in (bar_open_ts + MIN, bar_open_ts):
        r = b.get(t)
        if r:
            return float(r["c"])
    return None


def touch_px(o, T, target, long, mode):
    u, b = CTX["und"], _mem[o]
    for t0 in (T - 2 * MIN, T - MIN):
        r = u.get(t0)
        if r and ((r["h"] >= target) if long else (r["l"] <= target)):
            ob = b.get(t0)
            if ob is None:
                return None
            return float(ob["h"] if mode == "optimistic" else ob["vw"])
    return None


@dataclass
class RealPremiumModel(_p.PremiumModel):
    def mark(self, spot, strike, ts_ms, *, call, expiry=None):
        o = occ(CTX["symbol"], CTX["date"], call, strike)
        _load([o])
        fr = sys._getframe(1)
        if fr.f_code.co_name == "close_fraction":
            reason = str(fr.f_locals.get("reason") or "")
            px = None
            if "touched" in reason and CTX["touch_mode"] != "conservative":
                px = touch_px(o, ts_ms, float(spot), call, CTX["touch_mode"])
            if px is None:
                px, _ = exec_px(o, ts_ms, EXIT_WINDOW_MIN)
            if px is None:
                LOG.append({"kind": "exit_unknown", "symbol": CTX["symbol"], "date": CTX["date"], "occ": o, "ts": ts_ms, "reason": reason[:60]})
                return NAN
            return px
        px = bar_mark(o, ts_ms)                      # management: called with the 2m bar's OPEN ts
        if px is None:
            LOG.append({"kind": "mark_unknown", "symbol": CTX["symbol"], "date": CTX["date"], "occ": o, "ts": ts_ms})
            return NAN
        return px

    def buy(self, mark):
        return _p.Fill(premium=NAN, fee_per_contract=self.fee_per_contract) if isinstance(mark, float) and math.isnan(mark) else super().buy(mark)

    def sell(self, mark):
        return _p.Fill(premium=NAN, fee_per_contract=self.fee_per_contract) if isinstance(mark, float) and math.isnan(mark) else super().sell(mark)

    def pick_strike(self, spot, ts_ms, direction, *, target_premium, premium_floor, step=1.0, expiry=None,
                    max_steps=40, mode="closest", strikes=None):
        call = direction == "long"
        ladder = _p.otm_ladder(spot, call, step=step, strikes=strikes, max_steps=CTX.get("ladder", 14))
        _load([occ(CTX["symbol"], CTX["date"], call, k) for k in ladder])
        cap = target_premium * _p.MAX_OVER_TARGET
        cands, unseen = [], 0
        for k in ladder:
            m, mts = observed_px(occ(CTX["symbol"], CTX["date"], call, k), ts_ms)
            if m is None:
                unseen += 1
                continue
            if premium_floor <= m <= cap:
                cands.append((k, m, mts))
        row = {"kind": "entry", "symbol": CTX["symbol"], "date": CTX["date"], "T": ts_ms, "direction": direction,
               "ladder": len(ladder), "unobserved": unseen, "candidates": len(cands)}
        if not cands:
            LOG.append({**row, "outcome": "no_observed_contract_in_band"})
            return None
        k, m, mts = min(cands, key=lambda x: (abs(x[1] - target_premium), x[1]))
        o = occ(CTX["symbol"], CTX["date"], call, k)
        px, xts = exec_px(o, ts_ms, EXEC_WINDOW_MIN)
        row.update(strike=k, occ=o, observedPx=m, observationTs=mts, observedAgeMin=(ts_ms // MIN * MIN - mts) // MIN)
        if px is None:
            LOG.append({**row, "outcome": "no_execution_print"})
            return None
        row.update(execPx=px, executionTs=xts, execLagMin=(xts - ts_ms // MIN * MIN) // MIN)
        if px > cap + 1e-9:
            LOG.append({**row, "outcome": "refused_above_chase_cap"})
            return None
        if px < premium_floor - 1e-9:
            LOG.append({**row, "outcome": "refused_below_floor"})
            return None
        LOG.append({**row, "outcome": "filled"})
        return (k, px)

    def nearest_otm(self, spot, ts_ms, direction, *, step=1.0, expiry=None, strikes=None):
        call = direction == "long"
        first = next(iter(_p.otm_ladder(spot, call, step=step, strikes=strikes, max_steps=1)), None)
        if first is None:
            return None
        o = occ(CTX["symbol"], CTX["date"], call, first)
        _load([o])
        m, _ = observed_px(o, ts_ms)
        return None if m is None else (first, m)
