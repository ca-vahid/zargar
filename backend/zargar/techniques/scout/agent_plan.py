"""Scout agent - the code checks between a model's proposal and a research-book entry (PLAN section 9). Pure.

The model proposes; code decides whether the proposal can trade:
  * grounding  - every evidence item quotes a tool result of THIS run verbatim (whitespace-collapsed,
                 case-insensitive); fewer than `min_evidence` grounded items -> refused `ungrounded`
  * geometry   - long only (shares; never a short), stop below the entry reference by 0.5..4 ATR,
                 first target >= `min_r1` R, targets ascending, limit entries at or below the last close
  * eligibility- the ticker was chart-read in this run, price and liquidity floors, not already held or
                 proposed today in the lane's book
  * calendar   - the horizon (3..20 sessions) is cut to end before a known earnings date; < 3 left -> refused
Sizing happens at the fill (desk._enter): qty = risk % of book equity / (fill - stop), capped by a share of
equity and by cash. The model never sizes a position and never places an order.

The comparison lanes' plans are built here too, from the agent's geometry in ATR units (random twin) or a
fixed default (screen lane), so the lanes differ ONLY in what was picked.
"""
from __future__ import annotations

import hashlib
import math
import random as _random
import re
from dataclasses import dataclass, field

PLAN_VERSION = "scout-agent-plan-v1"
_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    return _WS.sub(" ", str(s or "")).strip().lower()


@dataclass(frozen=True)
class Limits:
    min_price: float = 5.0
    min_adv_usd: float = 5e6
    min_stop_atr: float = 0.5
    max_stop_atr: float = 4.0
    min_r1: float = 1.5
    min_horizon: int = 3
    max_horizon: int = 20
    max_proposals: int = 3
    min_evidence: int = 2
    min_quote_chars: int = 8
    max_limit_above_last_pct: float = 0.0       # a limit entry may not sit above the last close


@dataclass
class Checked:
    ok: bool
    ticker: str
    reasons: list[str] = field(default_factory=list)       # why refused (empty when ok)
    notes: list[str] = field(default_factory=list)         # adjustments made (horizon cut, targets dropped)
    plan: dict | None = None
    evidence: list[dict] = field(default_factory=list)     # grounded
    dropped_evidence: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "ticker": self.ticker, "reasons": self.reasons, "notes": self.notes,
                "plan": self.plan, "evidence": self.evidence, "droppedEvidence": self.dropped_evidence}


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def ground(evidence, results: dict[str, str], *, min_chars: int = 8) -> tuple[list[dict], list[dict]]:
    """Split evidence items into (grounded, dropped). `results` = result id -> the tool result text."""
    kept, dropped = [], []
    for e in evidence if isinstance(evidence, list) else []:
        if not isinstance(e, dict):
            dropped.append({"item": e, "why": "not an object"})
            continue
        rid = str(e.get("result_id") or e.get("resultId") or "").strip().upper()
        q = str(e.get("quote") or "")
        item = {"resultId": rid, "quote": q, "point": str(e.get("point") or "")[:400]}
        if rid not in results:
            dropped.append({**item, "why": f"no tool result {rid or '(none)'} in this run"})
        elif len(norm(q)) < min_chars:
            dropped.append({**item, "why": f"quote shorter than {min_chars} characters"})
        elif norm(q) not in norm(results[rid]):
            dropped.append({**item, "why": "quote not found verbatim in that result"})
        else:
            kept.append(item)
    return kept, dropped


def sessions_until(today: str, date: str, session_days: list[str]) -> int | None:
    """Trading sessions from `today` (exclusive) to `date` (inclusive) over a list of future session dates."""
    if date <= today:
        return None
    n = sum(1 for d in session_days if today < d <= date)
    return n


def check(p: dict, *, chart: dict | None, results: dict[str, str], held: set[str], proposed: set[str],
          earnings: list[str] | None, today: str, sessions_ahead: list[str], lim: Limits = Limits()) -> Checked:
    """One proposal -> Checked. `chart` = agent_tools.chart_read of the ticker in this run (None = never read);
    `sessions_ahead` = the next trading session dates after today (for the horizon / earnings cut)."""
    t = re.sub(r"[^A-Z0-9.\-]", "", str(p.get("ticker") or "").upper())[:12]
    c = Checked(ok=False, ticker=t)
    if not t:
        c.reasons.append("no ticker")
        return c
    kept, dropped = ground(p.get("evidence"), results, min_chars=lim.min_quote_chars)
    c.evidence, c.dropped_evidence = kept, dropped
    if not chart:
        c.reasons.append("no chart read of this ticker in this run (call chart first)")
        return c
    last, a = _f(chart.get("last")), _f(chart.get("atr14"))
    if not last or not a or a <= 0:
        c.reasons.append("chart read has no price or ATR")
        return c
    if last < lim.min_price:
        c.reasons.append(f"price {last:.2f} below ${lim.min_price:g}")
    if (_f(chart.get("advUsd20")) or 0) < lim.min_adv_usd:
        c.reasons.append(f"20-day dollar volume below ${lim.min_adv_usd / 1e6:g}M")
    if t in held:
        c.reasons.append("already held in this book")
    if t in proposed:
        c.reasons.append("already proposed today")
    side = str(p.get("side") or "long").lower()
    if side != "long":
        c.reasons.append("long only: the research book buys shares and never shorts")
    entry = p.get("entry") if isinstance(p.get("entry"), dict) else {}
    kind = str(entry.get("kind") or "now").lower()
    limit = _f(entry.get("limit_price") if "limit_price" in entry else entry.get("limitPrice"))
    if kind not in ("now", "limit"):
        c.reasons.append(f"entry kind '{kind}' (now | limit)")
        kind = "now"
    if kind == "limit":
        if limit is None or limit <= 0:
            c.reasons.append("limit entry without a limit price")
            limit = None
        elif limit > last * (1 + lim.max_limit_above_last_pct / 100.0):
            c.reasons.append(f"limit {limit:.2f} above the last close {last:.2f} (a limit buy waits for a lower price)")
    ref = limit if (kind == "limit" and limit) else last
    stop = _f(p.get("stop"))
    if stop is None or stop <= 0:
        c.reasons.append("no stop")
    elif stop >= ref:
        c.reasons.append(f"stop {stop:.2f} not below the entry {ref:.2f}")
    else:
        d_atr = (ref - stop) / a
        if d_atr < lim.min_stop_atr:
            c.reasons.append(f"stop {d_atr:.2f} ATR from the entry (min {lim.min_stop_atr:g}: inside normal noise)")
        elif d_atr > lim.max_stop_atr:
            c.reasons.append(f"stop {d_atr:.2f} ATR from the entry (max {lim.max_stop_atr:g})")
    raw_t = p.get("targets") if isinstance(p.get("targets"), list) else []
    targets = [v for v in (_f(x) for x in raw_t) if v is not None][:2]
    if not targets:
        c.reasons.append("no target")
    elif any(b <= a_ for a_, b in zip(targets, targets[1:])):
        c.reasons.append("targets not ascending")
    elif stop is not None and stop < ref:
        r1 = (targets[0] - ref) / (ref - stop)
        if r1 < lim.min_r1:
            c.reasons.append(f"first target is {r1:.2f}R (min {lim.min_r1:g}R)")
    try:
        horizon = int(p.get("horizon_sessions") or p.get("horizonSessions") or 0)
    except (TypeError, ValueError):
        horizon = 0
    if not lim.min_horizon <= horizon <= lim.max_horizon:
        c.reasons.append(f"horizon {horizon} sessions (allowed {lim.min_horizon}-{lim.max_horizon})")
    else:
        fut = sorted(d for d in (earnings or []) if d > today)
        if fut:
            n = sessions_until(today, fut[0], sessions_ahead)
            # the entry session is today (session 1); earnings on session k -> hold at most k - 1 sessions
            if n is not None:
                cap = n                       # sessions after today before the report day, plus today
                if cap < horizon:
                    if cap < lim.min_horizon:
                        c.reasons.append(f"earnings on {fut[0]}: only {cap} session(s) before it")
                    else:
                        c.notes.append(f"horizon cut {horizon} -> {cap} sessions (earnings on {fut[0]})")
                        horizon = cap
    try:
        conviction = int(p.get("conviction") or 0)
    except (TypeError, ValueError):
        conviction = 0
    if not 1 <= conviction <= 5:
        c.reasons.append("conviction must be 1-5")
    if len(kept) < lim.min_evidence:
        c.reasons.append(f"ungrounded: {len(kept)} evidence item(s) quote a tool result verbatim "
                         f"(min {lim.min_evidence})")
    if c.reasons:
        return c
    risk = ref - stop
    c.ok = True
    c.plan = {"version": PLAN_VERSION, "entry": {"kind": kind, "limit": limit, "ref": round(ref, 4)},
              "stop": round(stop, 2), "targets": [round(x, 2) for x in targets],
              "targetsR": [round((x - ref) / risk, 3) for x in targets], "stopAtr": round(risk / a, 3),
              "limitAtr": round((last - limit) / a, 3) if kind == "limit" and limit else 0.0,
              "atrAtProposal": round(a, 4), "lastAtProposal": last, "horizon": horizon,
              "conviction": conviction, "thesis": str(p.get("thesis") or "")[:2000],
              "invalidation": str(p.get("invalidation") or "")[:600]}
    return c


def size(*, equity: float, cash: float, fill: float, stop: float, risk_pct: float,
         max_position_pct: float) -> tuple[int, str]:
    """Shares for a fill: risk % of equity over the per-share risk, capped by a share of equity and by cash."""
    per = fill - stop
    if per <= 0:
        return 0, f"fill {fill:.2f} at or below the stop {stop:.2f}"
    by_risk = math.floor(equity * risk_pct / 100.0 / per)
    by_cap = math.floor(equity * max_position_pct / 100.0 / fill)
    by_cash = math.floor(max(cash, 0.0) / fill)
    q = max(0, min(by_risk, by_cap, by_cash))
    which = "risk" if q == by_risk else "position cap" if q == by_cap else "cash"
    return q, f"{q} shares (bound by {which}: risk {by_risk}, cap {by_cap}, cash {by_cash})"


def policy(plan: dict, *, stop: float, targets: list[float]) -> dict:
    """The position manager's exit policy (policies-as-data): fixed stop judged on the daily close, the
    targets as a half/half ladder with the stop to entry on the first trim, a time exit at the horizon."""
    pol = {"timeframe": "1d", "stop": {"kind": "fixed", "price": round(stop, 2)},
           "time_stop_sessions": max(1, int(plan["horizon"]) - 1), "gap_exit": True}
    if targets:
        fr = [1.0] if len(targets) == 1 else [0.5, 0.5]
        pol["ladder"] = {"targets": [round(x, 2) for x in targets], "fractions": fr}
        pol["breakeven_on_trim"] = True
    return pol


def limit_gate(plan: dict | None, ask: float | None) -> tuple[bool, str]:
    """A limit-entry plan enters only when the live ask is at or below its limit."""
    e = (plan or {}).get("entry") or {}
    if e.get("kind") != "limit" or not e.get("limit"):
        return True, ""
    if ask and ask <= float(e["limit"]):
        return True, f"ask {ask:.2f} <= limit {float(e['limit']):.2f}"
    return False, f"level_not_reached: ask {ask if ask else 'n/a'} above the limit {float(e['limit']):.2f}"


def like_plan(plan: dict, chart: dict) -> dict | None:
    """The random twin's plan: the agent pick's geometry in ATR units on the twin's own chart."""
    last, a = _f(chart.get("last")), _f(chart.get("atr14"))
    if not last or not a:
        return None
    kind = plan["entry"]["kind"]
    ref = last - float(plan.get("limitAtr") or 0) * a if kind == "limit" else last
    stop = ref - float(plan["stopAtr"]) * a
    if stop <= 0:
        return None
    targets = [ref + r * (ref - stop) for r in plan["targetsR"]]
    return {**plan, "entry": {"kind": kind, "limit": round(ref, 2) if kind == "limit" else None, "ref": round(ref, 4)},
            "stop": round(stop, 2), "targets": [round(x, 2) for x in targets], "atrAtProposal": round(a, 4),
            "lastAtProposal": last, "thesis": "random twin (same geometry in ATR units)", "invalidation": ""}


def default_plan(chart: dict, *, stop_atr: float = 2.0, targets_r: tuple[float, ...] = (2.0, 3.0),
                 horizon: int = 10) -> dict | None:
    """The screen-only lane's fixed plan: buy now, stop 2 ATR, targets 2R / 3R, 10 sessions."""
    last, a = _f(chart.get("last")), _f(chart.get("atr14"))
    if not last or not a:
        return None
    stop = last - stop_atr * a
    if stop <= 0:
        return None
    return {"version": PLAN_VERSION, "entry": {"kind": "now", "limit": None, "ref": last}, "stop": round(stop, 2),
            "targets": [round(last + r * (last - stop), 2) for r in targets_r], "targetsR": list(targets_r),
            "stopAtr": stop_atr, "limitAtr": 0.0, "atrAtProposal": round(a, 4), "lastAtProposal": last,
            "horizon": horizon, "conviction": None, "thesis": "screen-only lane (fixed plan)", "invalidation": ""}


def seed_of(key: str, attempt: int = 0) -> int:
    return int(hashlib.sha256(f"{key}#{attempt}".encode()).hexdigest()[:16], 16)


def draw_twin(key: str, pool: list[str], exclude: set[str], attempt: int = 0) -> str | None:
    names = sorted({p.upper() for p in pool} - {e.upper() for e in exclude})
    if not names:
        return None
    return _random.Random(seed_of(key, attempt)).choice(names)


def lessons_version(texts: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(texts)).encode()).hexdigest()[:12] if texts else "none"
