"""Team2 session plans — the nightly skeleton and its 09:25 completion (PLAN §1, E11).

A plan is DATA the runner and the simulation act on:

    {"technique": "team2", "symbol": "SPY", "date": "2026-09-04", "version": 1,
     "zones": {"pdh": {...}, "pdl": {...}}, "prevSession": "2026-09-03",
     "targets": {"above": 775.29, "below": 756.10},
     "pmh": 767.78, "pml": 763.59, "dayType": "normal", "openPrice": 766.2,
     "sizingAtOpen": "small", "sheet": "SPY: PDH zone … room up to 775.29 …",
     "complete": True, "thresholds": {...Team2Rules...}}

- `build_skeleton(symbol, date, prev_bars_15m)` after the close: zones from the previous
  session's 15m RTH bars, targets from the lookback, no PM data yet (`complete=False`).
- `complete_plan(skeleton, today_bars_1m)` at 09:25 (or whenever the first bars of the day
  exist): PMH/PML, day type, the open (first RTH bar, else last pre-market close), sizing at
  the open, the sheet line. Idempotent; call again at 09:31 to lock the true open.
"""
from __future__ import annotations

import datetime as dt

from ...domain import Bar
from ...marketstructure.aggregate import aggregate, bar_session, filter_session
from ...marketstructure.dailylevels import premarket_range, prior_day_zones
from ...marketstructure.market_calendar import previous_trading_day
from ...marketstructure.sessions import session_date
from .levels import level_ladder, level_sheet, targets_beyond
from .rules import Team2Rules
from .scenario import classify_day, sizing_bucket

PLAN_VERSION = 1


def build_skeleton(symbol: str, date: str, prev_bars_15m: list[Bar], rules: Team2Rules,
                   prev_bars_1m: list[Bar] | None = None) -> dict | None:
    """`prev_bars_15m`: 15m bars (RTH; extra sessions are used for targets) ending with the
    previous trading session. Returns None when the previous session has no bars.
    `prev_bars_1m` (optional): the same sessions' 1m bars — C2's `atr_build` (the previous session's 2m ATR(14) at
    its close) is computed from them; without them the 15m bars supply a stated fallback."""
    prev = previous_trading_day(date).isoformat()
    rth = [b for b in prev_bars_15m if bar_session(b.ts) == "rth"]
    prev_day = [b for b in rth if session_date(b.ts) == prev]
    if not prev_day:
        # tolerate a plan built from bars whose last session differs from the calendar (data gap)
        dates = sorted({session_date(b.ts) for b in rth if session_date(b.ts) < date})
        if not dates:
            return None
        prev = dates[-1]
        prev_day = [b for b in rth if session_date(b.ts) == prev]
    zones = prior_day_zones(prev_day)
    if zones is None:
        return None
    targets = targets_beyond(rth, zones, lookback_sessions=rules.target_lookback_sessions)
    # F72: the same pivots, unfiltered by the zone, so `target_replan` can pick the next structural
    # level beyond CURRENT PRICE at entry time. Data only — nothing reads it unless the knob is on.
    ladder = level_ladder(rth, zones, lookback_sessions=rules.target_lookback_sessions)
    key = None
    if str(getattr(rules, "key_levels", "off") or "off").lower() != "off":
        # C2 (research, OFF by default): the nightly key-level set. atr_build = the previous session's 2m RTH ATR(14)
        # at its close (one number, no plan-date data); fallback from the 15m bars when no 1m bars were supplied.
        from ...marketstructure.levels import atr as _atr
        from .levels import key_levels
        prev_2m = ([b for b in aggregate([x for x in prev_bars_1m if session_date(x.ts) == prev], 2) if bar_session(b.ts) == "rth"]
                   if prev_bars_1m else [])
        atr_build = _atr(sorted(prev_2m, key=lambda b: b.ts), 14) if len(prev_2m) >= 15 else 0.0
        prev_close = float(sorted(prev_day, key=lambda b: b.ts)[-1].close)
        if atr_build <= 0:
            # the frozen definition specifies the previous session's 2m ATR(14); without it the case is INSUFFICIENT
            # DATA (reviewers 2026-09-13) — no approximate fallback, no levels, and the sweep row says so
            key = {"definition": str(rules.key_levels).upper(), "atrBuild": 0.0, "atrBuildSource": "none",
                   "insufficientData": "no previous-session 2m RTH bars for atr_build", "prevClose": prev_close,
                   "candidates": [], "above": [], "below": []}
        else:
            key = key_levels(rth, definition=rules.key_levels, atr_build=float(atr_build), prev_close=prev_close, zones=zones,
                             plan_date=date, lookback=rules.target_lookback_sessions)
            key["atrBuildSource"] = "2m"
    return {
        "technique": "team2", "symbol": symbol.upper(), "date": date, "version": PLAN_VERSION,
        "prevSession": prev,
        "zones": {"pdh": zones["pdh"].to_dict(), "pdl": zones["pdl"].to_dict()},
        "targets": {"above": targets["above"], "below": targets["below"]},
        "targetsPlanned": {"above": targets["above"], "below": targets["below"]},   # F81: what 17:00 said, kept
        "preopenTargetRederive": bool(rules.preopen_target_rederive),
        "levelLadder": ladder,
        "keyLevels": key,
        "pmh": None, "pml": None, "dayType": None, "openPrice": None, "sizingAtOpen": None,
        "sheet": level_sheet(symbol.upper(), zones, None, None, targets),
        "complete": False, "thresholds": rules.to_dict(),
        "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def premarket_extrema(today_bars_1m: list[Bar], date: str) -> dict:
    """2026-09-17 (other team's EOD review §5): a derived level names the bar that produced it. SPY's plan froze a PML of
    660.65 while the bank held 757.53 — an exchange CORRECTION of the 07:46 minute had delivered a corrupt low into the
    private tape, and nothing recorded which bar the extreme came from. Every pre-market extreme now carries its source
    bar (ts, OHLCV, provenance) and the hash of every input bar, so a frozen value can be reconciled against the bank
    and against replay without rewriting the decision."""
    import hashlib
    from ...marketstructure.aggregate import bar_session
    pre = sorted([b for b in today_bars_1m if session_date(b.ts) == date and bar_session(b.ts) == "pre"], key=lambda b: b.ts)
    h = hashlib.sha1()
    for b in pre:
        h.update(f"{b.ts}|{b.open}|{b.high}|{b.low}|{b.close}|{b.volume}|{getattr(b, 'source', '') or ''}|{b.provider}\n".encode())
    def ident(b: Bar | None) -> dict | None:
        if b is None:
            return None
        return {"ts": int(b.ts), "open": float(b.open), "high": float(b.high), "low": float(b.low), "close": float(b.close),
                "volume": int(b.volume or 0), "source": getattr(b, "source", "") or "", "provider": b.provider}
    hi = max(pre, key=lambda b: b.high) if pre else None
    lo = min(pre, key=lambda b: b.low) if pre else None
    return {"pmh": ({"value": float(hi.high), "bar": ident(hi)} if hi else None),
            "pml": ({"value": float(lo.low), "bar": ident(lo)} if lo else None),
            "inputs": {"bars": len(pre), "hash": h.hexdigest()[:16], "firstTs": (int(pre[0].ts) if pre else None),
                       "lastTs": (int(pre[-1].ts) if pre else None),
                       "sources": sorted({(getattr(b, "source", "") or "unknown") for b in pre})},
            "computedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def complete_plan(skeleton: dict, today_bars_1m: list[Bar]) -> dict:
    from ...marketstructure.dailylevels import Zone
    plan = dict(skeleton)
    date = plan["date"]
    zones = {k: Zone(k, top=v["top"], bottom=v["bottom"], date=plan["prevSession"], anchor_ts=v.get("anchorTs") or 0)
             for k, v in plan["zones"].items()}
    today = [b for b in today_bars_1m if session_date(b.ts) == date]
    pmh, pml = premarket_range(today, date)
    rth = filter_session(today, "rth")
    if rth:
        open_price = sorted(rth, key=lambda b: b.ts)[0].open
        open_src = "rth_open"
    else:
        pre = filter_session(today, "pre")
        open_price = sorted(pre, key=lambda b: b.ts)[-1].close if pre else None
        open_src = "premarket_last" if pre else None
    plan.update({"pmh": pmh, "pml": pml, "pmExtrema": premarket_extrema(today, date)})
    if plan.get("keyLevels"):
        from .levels import mask_pm
        plan["keyLevels"] = mask_pm(plan["keyLevels"], pmh, pml, stage=("completed" if rth else "provisional"))
    if open_price is not None:
        plan["openPrice"] = float(open_price)
        plan["openSource"] = open_src
        plan["dayType"] = classify_day(float(open_price), zones, pmh, pml)
        plan["sizingAtOpen"] = sizing_bucket(float(open_price), zones, pmh, pml)
        if plan.get("preopenTargetRederive", True):
            plan["targets"], red = rederive_targets(plan, float(open_price), pmh, pml)
            if red:
                plan["targetsRederived"] = red
    plan["sheet"] = level_sheet(plan["symbol"], zones, pmh, pml, plan["targets"], plan.get("dayType"))
    plan["complete"] = pmh is not None and open_price is not None
    plan["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return plan


def rederive_targets(plan: dict, reference: float, pmh: float | None, pml: float | None) -> tuple[dict, dict]:
    """F81 (2026-09-10, user decision after the author's 2026-09-09 IWM day): the plan's targets are fixed at
    17:00 from prior-day pivots beyond the PDH/PDL zones. When the morning's reference price (pre-market
    last at 09:25, the real open at 09:30) has ALREADY run through a target, that target is not a target —
    every pullback would be refused (F72 guard: 18 refusals on 2026-09-09) or exited on its first bar.
    Re-derive it from the morning's structure, the way the author plans ("under the PML I have 291.19,
    then 289.98"): the pre-market extreme on that side if it is still ahead of the reference, else the next
    structural level of the ladder beyond the reference. A target that is still ahead is left alone; a
    side with nothing ahead becomes None (no target: stops, trims and the flatten manage the trade).
    Returns (targets, record) where record is {} when nothing changed."""
    from .levels import next_structural_level
    from .scenario import target_is_ahead
    planned = dict(plan.get("targetsPlanned") or {})
    if not planned:
        # F88 (2026-09-10): plans minted before v0.7.34 carry no `targetsPlanned`, so this used to fall
        # back to `targets` — which an earlier pass of this function has already overwritten. The
        # re-derive then ratchets off its own output: a side re-derived to None on the 09:25 pre-market
        # estimate can never be restored by the 09:30 open, even when the real open leaves a valid level
        # ahead (IWM 2026-09-10: below 290.17 -> none at 09:25, still none after the 288.48 open with the
        # 287.83 PML ahead of it). Recover what 17:00 said from the record the first pass left behind and
        # pin it, so every later pass re-derives from the plan's own inputs.
        planned = dict(plan.get("targets") or {})
        for side, rec in (plan.get("targetsRederived") or {}).items():
            if isinstance(rec, dict) and "was" in rec:
                planned[side] = rec.get("was")
        plan["targetsPlanned"] = dict(planned)
    cur = dict(plan.get("targets") or {})
    out = dict(cur)
    changed: dict = {}
    for side, direction, pm in (("below", "short", pml), ("above", "long", pmh)):
        tgt = planned.get(side)
        if tgt is None or target_is_ahead(float(tgt), reference, direction):
            out[side] = tgt                                  # still a target: keep what 17:00 said
            continue
        cand = None
        if pm is not None and target_is_ahead(float(pm), reference, direction):
            cand, src = float(pm), ("pml" if side == "below" else "pmh")
        else:
            nxt = next_structural_level(plan.get("levelLadder"), reference, direction)
            cand, src = (float(nxt), "ladder") if nxt is not None else (None, "none")
        out[side] = cand
        changed[side] = {"was": round(float(tgt), 4), "now": (round(cand, 4) if cand is not None else None),
                         "source": src, "reference": round(float(reference), 4)}
    return out, changed


def fifteen_from_1m(bars1m: list[Bar]) -> list[Bar]:
    """Convenience for callers holding 1m history: RTH 15m bars."""
    return [b for b in aggregate(bars1m, 15) if bar_session(b.ts) == "rth"]


__all__ = ["build_skeleton", "complete_plan", "fifteen_from_1m", "PLAN_VERSION"]
