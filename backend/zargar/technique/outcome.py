"""Outcome scoring — what price actually did after a run.

A review needs the *facts of the matter* next to the verdict: did the entry
fill, did the stop or the targets hit first, how much R was realised, how far
did price move for/against the plan. `simulate_plan` is the single walk-forward
model shared with the backtester (`backtest.py`), so live runs and replays are
scored by exactly the same rules:

    bounce  — fills if price trades down to the entry within `entry_window`
              bars after `start`; otherwise "not_filled".
    break   — fills at the start bar's close (the level was already taken).
    exits   — scale out 30/40/15 at TP1-3, the 15% runner closes at the
              horizon; the stop is fixed. If a bar straddles both the stop and
              a target the stop wins (conservative). R = realised P&L / risk.

MFE/MAE (max favourable / adverse excursion, in R) are reported too, because
"stopped out then ran to TP3" and "never went your way" are different lessons.

For `no_setup` runs the deterministic candidate the pipeline declined is
scored as well (plan_source="candidate") so missed trades are measurable.
"""
from __future__ import annotations

import datetime as dt
import json
import time

from ..domain import Bar
from .history import INTERVAL_SECONDS, MAX_LOOKBACK, fetch_window
from .setups import LADDER_TRIMS, RUNNER_PCT

PATH_OFFSETS = (5, 15, 30, 60)


def plan_from_contract(contract: dict | None) -> dict | None:
    """Analysis contract (`TechniqueAnalysis.to_contract()`) -> scorable plan."""
    if not contract or contract.get("verdict") != "setup":
        return None
    e, s = contract.get("entry"), contract.get("stop")
    if not e or not s or not contract.get("targets"):
        return None
    return {
        "setupType": contract.get("setupType") or "none",
        "entry": {"price": float(e["price"]), "basis": e.get("basis", "at_level")},
        "stop": {"price": float(s["price"])},
        "targets": [{"price": float(t["price"])} for t in contract["targets"] if t.get("price")],
        "riskReward": contract.get("riskReward"),
    }


def plan_from_candidate(cand: dict | None) -> dict | None:
    """facts.candidateSetups[i] -> scorable plan."""
    if not cand:
        return None
    e, s = cand.get("entry"), cand.get("stop")
    if not e or not s or not cand.get("targets"):
        return None
    try:
        return {
            "setupType": cand.get("setupType") or "none",
            "entry": {"price": float(e["price"]), "basis": e.get("basis", "at_level")},
            "stop": {"price": float(s["price"])},
            "targets": [{"price": float(t["price"])} for t in cand["targets"] if t.get("price") is not None],
            "riskReward": cand.get("riskReward"),
            "valid": cand.get("valid"),
        }
    except (KeyError, TypeError, ValueError):
        return None


def same_plan(a: dict | None, b: dict | None, tol: float = 1e-6) -> bool:
    if not a or not b:
        return False
    return (abs(a["entry"]["price"] - b["entry"]["price"]) <= tol
            and abs(a["stop"]["price"] - b["stop"]["price"]) <= tol)


def simulate_plan(bars: list[Bar], start: int, plan: dict, *, entry_window: int = 12,
                  horizon: int = 60, stop_on: str = "close", breach_r: float = 0.25) -> dict:
    """Walk `bars` forward from index `start` (the bar the decision was made on)
    and score `plan`. Returns a plain dict (see keys below). `bars` must be
    sorted by ts and include the start bar; bars after `start` are the future.

    Keys: filled, fillTs, fillIndex, outcome (not_filled|stopped|tp1|tp2|tp3|
    horizon), rMultiple, mfeR, maeR, barsHeld, barsAvailable, resolved (the
    outcome can no longer change with more bars), hits [ts per target hit].

    `stop_on` mirrors the live exit rule (`execution.exits.plan_exit`): "close" =
    stopped when a bar closes through the stop, filled at that close; "low" = the
    old touch rule, filled at the stop. Either way a bar whose LOW is `breach_r`
    beyond the stop is the intra-minute quote brake firing (filled there) — the
    same disaster exit the live quote watch takes. Change one, change both.
    """
    entry = float(plan["entry"]["price"])
    stop = float(plan["stop"]["price"])
    targets = [float(t["price"]) for t in plan["targets"]]
    trims = list(LADDER_TRIMS[:len(targets)])
    short = (plan.get("direction") == "short")
    sgn = -1.0 if short else 1.0                  # P&L per unit = sgn * (price - entry)
    risk = (stop - entry) if short else (entry - stop)   # distance to the stop, positive when sane
    avail = max(0, len(bars) - 1 - start)
    base = {"entry": entry, "stop": stop, "targets": targets, "setupType": plan.get("setupType"),
            "barsAvailable": avail, "horizon": horizon, "entryWindow": entry_window}
    if risk <= 0 or not targets:
        return {**base, "filled": False, "fillTs": None, "fillIndex": None, "outcome": "not_filled",
                "rMultiple": 0.0, "mfeR": 0.0, "maeR": 0.0, "barsHeld": 0, "resolved": True,
                "hits": [], "note": "invalid plan (stop above entry or no targets)"}

    # --- fill ------------------------------------------------------------------
    if plan["entry"].get("basis") == "on_break":
        fill_i = start
    else:
        fill_i = None
        last_i = min(len(bars) - 1, start + entry_window)
        for i in range(start + 1, last_i + 1):
            if (bars[i].high >= entry) if short else (bars[i].low <= entry):
                fill_i = i
                break
        if fill_i is None:
            window_done = (len(bars) - 1) >= start + entry_window
            return {**base, "filled": False, "fillTs": None, "fillIndex": None, "outcome": "not_filled",
                    "rMultiple": 0.0, "mfeR": 0.0, "maeR": 0.0, "barsHeld": 0,
                    "resolved": window_done, "hits": [],
                    "note": ("price never traded down to the entry within the window" if window_done
                             else "entry window still open")}

    # --- walk forward --------------------------------------------------------------
    remaining = 1.0
    realized = 0.0
    hit = 0
    hits: list[int] = []
    outcome = "horizon"
    resolved = False
    end_i = min(len(bars) - 1, fill_i + horizon)
    mfe = 0.0
    mae = 0.0
    i = fill_i + 1
    last_i = fill_i
    while i <= end_i and remaining > 1e-9:
        b = bars[i]
        last_i = i
        mfe = max(mfe, sgn * (b.low if short else b.high) * 1.0 - sgn * entry) if False else \
            max(mfe, (entry - b.low) if short else (b.high - entry))
        mae = max(mae, (b.high - entry) if short else (entry - b.low))
        brake = stop + breach_r * risk if short else stop - breach_r * risk
        if (b.high >= brake) if short else (b.low <= brake):    # crash through: the quote brake
            realized += remaining * sgn * (brake - entry)
            remaining = 0.0
            outcome = "stopped" if hit == 0 else f"tp{hit}"
            resolved = True
            break
        ref = b.close if stop_on == "close" else (b.high if short else b.low)
        if (ref >= stop) if short else (ref <= stop):
            realized += remaining * sgn * ((b.close if stop_on == "close" else stop) - entry)
            remaining = 0.0
            outcome = "stopped" if hit == 0 else f"tp{hit}"
            resolved = True
            break
        while hit < len(targets) and ((b.low <= targets[hit]) if short else (b.high >= targets[hit])):
            part = trims[hit] if hit < len(trims) else remaining
            part = min(part, remaining)
            realized += part * sgn * (targets[hit] - entry)
            remaining -= part
            hit += 1
            hits.append(b.ts)
        i += 1
    if remaining > 1e-9:
        last = bars[last_i]
        realized += remaining * sgn * (last.close - entry)
        if hit > 0:
            outcome = f"tp{hit}"
        # horizon reached only if we actually had that many bars
        resolved = (fill_i + horizon) <= (len(bars) - 1)
    r_mult = realized / risk
    return {**base, "filled": True, "fillTs": bars[fill_i].ts, "fillIndex": fill_i, "outcome": outcome,
            "rMultiple": round(r_mult, 4), "mfeR": round(mfe / risk, 4), "maeR": round(mae / risk, 4),
            "barsHeld": last_i - fill_i, "resolved": resolved, "hits": hits,
            "note": "" if resolved else "horizon not reached yet"}


def path_summary(bars_after: list[Bar], ref_price: float) -> dict:
    """High/low/close at fixed offsets after the decision bar, absolute and in
    % of `ref_price` — a quick "where did it go" independent of any plan."""
    out: dict = {}
    for n in PATH_OFFSETS:
        if len(bars_after) < n:
            continue
        seg = bars_after[:n]
        hi = max(b.high for b in seg)
        lo = min(b.low for b in seg)
        cl = seg[-1].close
        out[f"+{n}"] = {"high": hi, "low": lo, "close": cl,
                        "highPct": round((hi - ref_price) / ref_price * 100, 3) if ref_price else None,
                        "lowPct": round((lo - ref_price) / ref_price * 100, 3) if ref_price else None,
                        "closePct": round((cl - ref_price) / ref_price * 100, 3) if ref_price else None}
    out["bars"] = len(bars_after)
    return out


def horizon_still_fetchable(tf: str, as_of_ms: int) -> bool:
    """Yahoo serves each interval only so far back; after that the outcome is
    unscorable (unless the bars were captured earlier)."""
    return (time.time() - as_of_ms / 1000) < MAX_LOOKBACK.get(tf, 0) - 3600


async def fetch_after(symbol: str, tf: str, as_of_ms: int, *, horizon: int, entry_window: int,
                      max_days: int = 10) -> list[Bar]:
    """Bars strictly after `as_of_ms`, enough to cover entry window + horizon
    (calendar-padded so overnight gaps and weekends do not starve it)."""
    need = horizon + entry_window + 2
    span_s = need * INTERVAL_SECONDS.get(tf, 60)
    # intraday bars only occur ~6.5h/day; pad generously and clip by count
    if tf in ("1m", "5m", "15m", "1h"):
        days = min(max_days, max(1, span_s // (6.5 * 3600) + 2))
        end_ms = min(int(time.time() * 1000), as_of_ms + int(days * 86400 * 1000))
    else:
        end_ms = min(int(time.time() * 1000), as_of_ms + need * 86400 * 1000 * 2)
    bars = await fetch_window(symbol, tf, as_of_ms - INTERVAL_SECONDS.get(tf, 60) * 1000, end_ms)
    return [b for b in bars if b.ts > as_of_ms][:need]


def bars_to_rows(bars: list[Bar]) -> list[list]:
    return [b.to_row() for b in bars]


def rows_to_bars(symbol: str, tf: str, rows: list[list]) -> list[Bar]:
    return [Bar(symbol=symbol, tf=tf, ts=int(r[0]), open=float(r[1]), high=float(r[2]),
                low=float(r[3]), close=float(r[4]), volume=int(r[5] or 0)) for r in rows]


def outcome_dict(o) -> dict:
    return {
        "id": o.id, "runId": o.run_id, "setupId": o.setup_id, "planSource": o.plan_source,
        "status": o.status, "horizonBars": o.horizon_bars, "plan": o.plan or {},
        "outcome": o.outcome, "rMultiple": o.r_multiple, "mfeR": o.mfe_r, "maeR": o.mae_r,
        "barsHeld": o.bars_held, "barsAfter": o.bars_after, "path": o.path or {},
        "barsAssetId": o.bars_asset_id, "note": o.note,
        "scoredAt": o.scored_at.isoformat() if o.scored_at else None,
        "createdAt": o.created_at.isoformat() if o.created_at else None,
    }


def describe_outcome(o: dict) -> str:
    """One line for summaries / the bundle."""
    src = o.get("planSource")
    st = o.get("status")
    if st == "unscorable":
        return f"{src}: unscorable — {o.get('note') or ''}".strip()
    if st == "pending":
        return f"{src}: pending"
    oc = o.get("outcome")
    r = o.get("rMultiple")
    bits = [f"{src}: {oc}"]
    if oc != "not_filled" and r is not None:
        bits.append(f"R {r:+.2f}")
        if o.get("mfeR") is not None:
            bits.append(f"MFE {o['mfeR']:.2f}R / MAE {o['maeR']:.2f}R")
        if o.get("barsHeld") is not None:
            bits.append(f"{o['barsHeld']} bars")
    if st == "partial":
        bits.append("(partial — more bars to come)")
    return " · ".join(bits)


def json_dumps(obj) -> str:
    return json.dumps(obj, default=_default)


def _default(o):
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    return str(o)
