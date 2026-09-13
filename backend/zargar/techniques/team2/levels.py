"""Team2 level work beyond the shared primitives: targets and the daily level sheet.

- `targets_beyond(bars15m_history, zones, lookback_sessions)` (L3.1): the next resistance
  above the PDH zone = the most recent 15m pivot high above it within the lookback; the next
  support below the PDL zone = the most recent pivot low below it. `None` when the history
  has none (then the target is "open" and the runner rides the EMA).
- `level_sheet(...)` — the one-line-per-symbol plan text the author posts every morning
  (V9): "Main watch … break above and we focus on calls … room up to X".
"""
from __future__ import annotations

from ...domain import Bar
from ...marketstructure.aggregate import bar_session
from ...marketstructure.dailylevels import Zone
from ...marketstructure.levels import find_pivots
from ...marketstructure.sessions import session_date


def targets_beyond(bars15m: list[Bar], zones: dict[str, Zone], *, lookback_sessions: int = 10,
                   pivot_window: int = 2) -> dict[str, float | None]:
    rth = sorted((b for b in bars15m if bar_session(b.ts) == "rth"), key=lambda b: b.ts)
    if not rth:
        return {"above": None, "below": None}
    dates = sorted({session_date(b.ts) for b in rth})
    keep = set(dates[-lookback_sessions:])
    hist = [b for b in rth if session_date(b.ts) in keep and session_date(b.ts) != zones["pdh"].date]
    pdh, pdl = zones["pdh"], zones["pdl"]
    above = below = None
    for p in reversed(find_pivots(hist, window=pivot_window)):
        if above is None and p.kind == "high" and p.price > pdh.top:
            above = p.price
        if below is None and p.kind == "low" and p.price < pdl.bottom:
            below = p.price
        if above is not None and below is not None:
            break
    return {"above": above, "below": below}


def level_ladder(bars15m: list[Bar], zones: dict[str, Zone], *, lookback_sessions: int = 10,
                 pivot_window: int = 2) -> dict[str, list[float]]:
    """F72 (2026-09-09): every structural level the lookback knows, ordered outward, so a target can
    be re-derived against CURRENT PRICE instead of against the zone.

    `targets_beyond` answers "what is the next pivot beyond the PDH/PDL zone" — anchored on the
    zone, and therefore fixed when the plan is built. On a gap that opens straight THROUGH the zone
    that answer is already behind price before the 15m confirmation arrives (SPY 2026-09-09:
    target 764.75, price 763.7). This returns the same pivots, unfiltered by the zone:
    `highs` ascending and `lows` descending, so the first entry beyond a given price in the trade's
    direction is the next structural level from there. Selection is the caller's job, at entry.
    """
    rth = sorted((b for b in bars15m if bar_session(b.ts) == "rth"), key=lambda b: b.ts)
    if not rth:
        return {"highs": [], "lows": []}
    dates = sorted({session_date(b.ts) for b in rth})
    keep = set(dates[-lookback_sessions:])
    hist = [b for b in rth if session_date(b.ts) in keep and session_date(b.ts) != zones["pdh"].date]
    highs = sorted({round(float(p.price), 4) for p in find_pivots(hist, window=pivot_window) if p.kind == "high"})
    lows = sorted({round(float(p.price), 4) for p in find_pivots(hist, window=pivot_window) if p.kind == "low"},
                  reverse=True)
    return {"highs": highs, "lows": lows}


def next_structural_level(ladder: dict[str, list[float]] | None, price: float, direction: str) -> float | None:
    """The first level in `ladder` strictly beyond `price` in the trade's direction, or None."""
    if not ladder:
        return None
    if direction == "long":
        return next((float(x) for x in (ladder.get("highs") or []) if float(x) > price), None)
    return next((float(x) for x in (ladder.get("lows") or []) if float(x) < price), None)


def level_sheet(symbol: str, zones: dict[str, Zone], pmh: float | None, pml: float | None,
                targets: dict[str, float | None], day_type: str | None = None) -> str:
    pdh, pdl = zones["pdh"], zones["pdl"]
    up = f"{targets['above']:.2f}" if targets.get("above") else "open"
    dn = f"{targets['below']:.2f}" if targets.get("below") else "open"
    pm = f" · PM {pml:.2f}–{pmh:.2f}" if pmh is not None and pml is not None else ""
    dt_ = f" · {day_type.replace('_', ' ')} day" if day_type else ""
    return (f"{symbol}: PDH zone {pdh.bottom:.2f}–{pdh.top:.2f} → break above and we focus on calls, room up to {up}; "
            f"PDL zone {pdl.bottom:.2f}–{pdl.top:.2f} → break below and we focus on puts, room down to {dn}{pm}{dt_}")


__all__ = ["targets_beyond", "level_ladder", "next_structural_level", "level_sheet"]


# =====================================================================================================================
# C2 — multi-day key levels (research; `techniques.team2.key_levels = off | D1 | D2 | D3`, default OFF).
# Spec: docs/techniques/team2/notes/research/2026-09-13-c2-key-levels-spec.md (v2). Everything here is causal: a
# level exists only from `availableAt`; the flip state machine advances on 15m closes and is never backdated.
# =====================================================================================================================
import statistics as _stats
from dataclasses import dataclass as _dataclass, field as _field

KEY_LEVEL_DECAY = 0.85
KEY_LEVEL_TOL_ATR = 0.25          # touch tolerance at build time (x atr_build)
KEY_LEVEL_CLUSTER_ATR = 0.5       # MAXIMUM cluster diameter (max member - min member, x atr_build) — a hard bound
KEY_LEVEL_MASK_ATR = 0.5          # mask width against PDH/PDL zones and PMH/PML (x atr_build)
KEY_LEVEL_LONE_MAX_AGE = 3        # a single member / zero-retest pivot older than this many sessions is dropped
KEY_LEVEL_D2_MIN_EPISODES = 3
KEY_LEVEL_D2_MIN_SESSIONS = 2
KEY_LEVEL_D2_AWAY_BARS = 4
KEY_LEVEL_EXPIRE_BEYOND_ATR = 1.0


@_dataclass
class KeyLevel:
    level_id: str
    definition: str
    origin_kind: str            # high | low | pivot_high | pivot_low
    origin_date: str
    available_at: int
    price: float
    role: str                   # support | resistance
    score: float
    reactions: int
    last_reaction_at: int
    members: list = _field(default_factory=list)      # member prices (audit)
    episode_ids: list = _field(default_factory=list)  # de-duplicated reaction/retest ids (audit)
    masked_by: str = "none"

    def to_dict(self) -> dict:
        return {"levelId": self.level_id, "definition": self.definition, "originKind": self.origin_kind,
                "originDate": self.origin_date, "availableAt": self.available_at, "price": round(self.price, 4),
                "role": self.role, "score": round(self.score, 4), "reactions": self.reactions,
                "lastReactionAt": self.last_reaction_at, "members": [round(m, 4) for m in self.members],
                "episodes": [list(e) for e in self.episode_ids], "maskedBy": self.masked_by,
                # runtime flip state (the read advances these; the plan stores the 17:00 values)
                "flips": 0, "flipPending": False, "breakAt": None, "flipConfirmedAt": None, "retired": False}


def _rth_sessions(bars15m: list[Bar], lookback: int, before_date: str) -> tuple[list[str], dict[str, list[Bar]]]:
    rth = sorted((b for b in bars15m if bar_session(b.ts) == "rth" and session_date(b.ts) < before_date), key=lambda b: b.ts)
    by: dict[str, list[Bar]] = {}
    for b in rth:
        by.setdefault(session_date(b.ts), []).append(b)
    dates = sorted(by)[-lookback:]
    return dates, {d: by[d] for d in dates}


def _sessions_ago(dates: list[str], d: str) -> int:
    """1 = the previous completed session, 2 = the one before, ..."""
    return len(dates) - dates.index(d)


def _reaction(bar: Bar, price: float, tol: float, role: str) -> bool:
    """D2 candle predicate. support: the wick's LOW lies inside the band [price - tol, price + tol] (it came down
    into the level, not through it) and the body closed back ABOVE the band; resistance: the wick's HIGH lies inside
    the band and the body closed back BELOW it. Localising the extreme to the band is what keeps one reaction from
    counting at every grid point below it (spec v2 §1 D2)."""
    if role == "support":
        return price - tol <= bar.low <= price + tol and bar.close > price + tol
    return price - tol <= bar.high <= price + tol and bar.close < price - tol


def _episodes(bars: list[Bar], price: float, tol: float, role: str, *, start_index: int = 0) -> list[tuple]:
    """Reaction episodes at `price` in `role`: consecutive reacting bars are ONE episode; a new one needs
    KEY_LEVEL_D2_AWAY_BARS consecutive closed bars fully outside the band, or a session boundary.
    Returns [(episode_id, extreme_price, ts_of_first_bar)] with episode_id = (sessionDate, index of the first bar)."""
    out: list[tuple] = []
    in_episode = False
    away = KEY_LEVEL_D2_AWAY_BARS      # start "away enough"
    last_sess = None
    for i in range(start_index, len(bars)):
        b = bars[i]
        sess = session_date(b.ts)
        if sess != last_sess:
            away = KEY_LEVEL_D2_AWAY_BARS
            in_episode = False
            last_sess = sess
        if _reaction(b, price, tol, role):
            if not in_episode and away >= KEY_LEVEL_D2_AWAY_BARS:
                out.append(((sess, i), b.low if role == "support" else b.high, b.ts))
                in_episode = True
            elif in_episode:
                pass                                   # lingering: the same episode
            away = 0
            continue
        in_episode = False
        outside = b.low > price + tol or b.high < price - tol
        away = away + 1 if outside else 0
    return out


def _cluster(cands: list[dict], width: float) -> list[dict]:
    """Sort by price, walk upward; a candidate joins the current cluster only if the cluster's DIAMETER with it
    (max member - min member) stays <= `width`. A running-median test does not bound a cluster (the reviewers'
    fixture chained 2.5 ATR at a 0.5 ATR radius, 2026-09-13); the diameter test does. Deterministic, no chaining.
    Episode ids are de-duplicated on merge."""
    out: list[dict] = []
    for c in sorted(cands, key=lambda x: x["price"]):
        if out and (max(out[-1]["members"] + [c["price"]]) - min(out[-1]["members"] + [c["price"]])) <= width:
            cl = out[-1]
            cl["members"].append(c["price"])
            cl["episode_ids"] |= set(c.get("episode_ids") or [])
            cl["kinds"].append(c["kind"])
            cl["dates"].append(c["origin_date"])
            cl["available"].append(c["available_at"])
            cl["last"].append(c["last_reaction_at"])
            cl["extremes"].extend(c.get("extremes") or [c["price"]])
        else:
            out.append({"members": [c["price"]], "episode_ids": set(c.get("episode_ids") or []), "kinds": [c["kind"]],
                        "dates": [c["origin_date"]], "available": [c["available_at"]], "last": [c["last_reaction_at"]],
                        "extremes": list(c.get("extremes") or [c["price"]])})
    return out


def _d1_candidates(dates: list[str], by: dict[str, list[Bar]]) -> list[dict]:
    out = []
    for d in dates:
        bars = by[d]
        hi = max(bars, key=lambda b: b.high); lo = min(bars, key=lambda b: b.low)
        close_ts = bars[-1].ts + 15 * 60_000
        out.append({"price": hi.high, "kind": "high", "origin_date": d, "available_at": close_ts, "last_reaction_at": hi.ts,
                    "episode_ids": [(d, "high")]})
        out.append({"price": lo.low, "kind": "low", "origin_date": d, "available_at": close_ts, "last_reaction_at": lo.ts,
                    "episode_ids": [(d, "low")]})
    return out


def _d2_candidates(dates: list[str], by: dict[str, list[Bar]], atr_build: float) -> list[dict]:
    bars = [b for d in dates for b in by[d]]
    step = KEY_LEVEL_TOL_ATR * atr_build
    tol = step
    lo = min(b.low for b in bars); hi = max(b.high for b in bars)
    origin = (lo // step) * step
    out = []
    p = origin
    while p <= hi + step:
        for role in ("support", "resistance"):
            eps = _episodes(bars, p, tol, role)
            sessions = {e[0][0] for e in eps}
            if len(eps) >= KEY_LEVEL_D2_MIN_EPISODES and len(sessions) >= KEY_LEVEL_D2_MIN_SESSIONS:
                newest = max(eps, key=lambda e: e[2])
                out.append({"price": float(p), "kind": "low" if role == "support" else "high",
                            "origin_date": newest[0][0], "available_at": by[newest[0][0]][-1].ts + 15 * 60_000,
                            "last_reaction_at": newest[2], "episode_ids": [e[0] for e in eps],
                            "extremes": [e[1] for e in eps]})
        p += step
    return out


def _d3_candidates(dates: list[str], by: dict[str, list[Bar]], atr_build: float, prev_session: str) -> list[dict]:
    bars = [b for d in dates for b in by[d]]
    tol = KEY_LEVEL_TOL_ATR * atr_build
    prev = by.get(prev_session) or []
    prev_hi = max((b.high for b in prev), default=None); prev_lo = min((b.low for b in prev), default=None)
    out = []
    for p in find_pivots(bars, window=2):
        d = session_date(p.ts)
        if d == prev_session and (p.price == prev_hi or p.price == prev_lo):
            continue                                    # the previous session's extremes are the PDH/PDL zones
        avail_i = p.index + 2
        available_at = bars[avail_i].ts + 15 * 60_000
        role = "resistance" if p.kind == "high" else "support"
        eps = _episodes(bars, p.price, tol, role, start_index=avail_i + 1)
        out.append({"price": float(p.price), "kind": "pivot_" + p.kind, "origin_date": d, "available_at": available_at,
                    "last_reaction_at": max([e[2] for e in eps], default=p.ts), "episode_ids": [e[0] for e in eps],
                    "retests": len(eps)})
    return out


def _expired(level_price: float, origin_kind: str, dates: list[str], by: dict[str, list[Bar]], atr_build: float) -> bool:
    """Two consecutive completed sessions closed THROUGH the level by > 1.0 atr_build (below a low-born level, above a
    high-born one) without any wick into its band: the level was traversed and never reacted — it is in the way, not a
    level. Judged on the level's ORIGIN side, so a support price merely moved away from (still above it) is kept."""
    if len(dates) < 2:
        return False
    tol = KEY_LEVEL_TOL_ATR * atr_build
    low_born = origin_kind in ("low", "pivot_low")
    for d in dates[-2:]:
        bars = by[d]
        close = bars[-1].close
        beyond = (close < level_price - KEY_LEVEL_EXPIRE_BEYOND_ATR * atr_build) if low_born else                  (close > level_price + KEY_LEVEL_EXPIRE_BEYOND_ATR * atr_build)
        touched = any(b.low <= level_price + tol and b.high >= level_price - tol for b in bars)
        if not beyond or touched:
            return False
    return True


def key_levels(bars15m: list[Bar], *, definition: str, atr_build: float, prev_close: float, zones: dict[str, Zone],
               plan_date: str, lookback: int = 10, cap: int = 3) -> dict:
    """The nightly key-level set for one definition (D1 | D2 | D3), masked against the PDH/PDL zones, ranked and
    capped per side. Returns {"definition", "atrBuild", "candidates": [...all, with maskedBy...], "above": [...],
    "below": [...]} — all levels as dicts (`KeyLevel.to_dict`)."""
    definition = str(definition).upper()
    dates, by = _rth_sessions(bars15m, lookback, plan_date)
    if not dates or atr_build <= 0:
        return {"definition": definition, "atrBuild": atr_build, "candidates": [], "above": [], "below": []}
    prev_session = dates[-1]
    if definition == "D1":
        raw = _d1_candidates(dates, by)
    elif definition == "D2":
        raw = _d2_candidates(dates, by, atr_build)
    elif definition == "D3":
        raw = _d3_candidates(dates, by, atr_build, prev_session)
    else:
        raise ValueError(f"unknown key-level definition {definition!r}")
    width = KEY_LEVEL_CLUSTER_ATR * atr_build
    levels: list[KeyLevel] = []
    for cl in _cluster(raw, width):
        members = cl["members"]
        if definition == "D2":
            price = float(_stats.median(cl["extremes"]))
            reactions = len(cl["episode_ids"])
            origin = max(cl["dates"])
            score = reactions * KEY_LEVEL_DECAY ** (_sessions_ago(dates, origin) - 1)
        elif definition == "D3":
            price = float(_stats.median(members))
            retests = len(cl["episode_ids"])
            origin = min(cl["dates"])                                   # a cluster of pivots is as old as its first pivot
            if retests == 0 and _sessions_ago(dates, origin) > KEY_LEVEL_LONE_MAX_AGE:
                continue
            reactions = 1 + retests
            score = reactions * KEY_LEVEL_DECAY ** (_sessions_ago(dates, origin) - 1)
        else:
            price = float(_stats.median(members))
            reactions = len(members)
            origin = max(cl["dates"])
            if reactions == 1 and _sessions_ago(dates, origin) > KEY_LEVEL_LONE_MAX_AGE:
                continue
            score = reactions * KEY_LEVEL_DECAY ** (_sessions_ago(dates, origin) - 1)
        if abs(price - prev_close) <= KEY_LEVEL_TOL_ATR * atr_build:
            continue                                                    # a level AT the close has no role
        role = "support" if price < prev_close else "resistance"
        kind = cl["kinds"][0] if len(set(cl["kinds"])) == 1 else ("high" if role == "resistance" else "low")
        if _expired(price, kind, dates, by, atr_build):
            continue
        lid = f"{bars15m[0].symbol}:{definition}:{origin}:{kind}:{price:.4f}"
        lv = KeyLevel(level_id=lid, definition=definition, origin_kind=kind, origin_date=origin,
                      available_at=max(cl["available"]), price=price, role=role, score=score, reactions=reactions,
                      last_reaction_at=max(cl["last"]), members=members, episode_ids=sorted(cl["episode_ids"], key=str))
        # 17:00 mask against the PDH/PDL zones (the zones keep their semantics; the candidate record keeps the reason)
        for zk in ("pdh", "pdl"):
            z = zones[zk]
            if z.bottom - KEY_LEVEL_MASK_ATR * atr_build <= price <= z.top + KEY_LEVEL_MASK_ATR * atr_build:
                lv.masked_by = zk
                break
        levels.append(lv)
    above = [lv for lv in levels if lv.role == "resistance" and lv.masked_by == "none"]
    below = [lv for lv in levels if lv.role == "support" and lv.masked_by == "none"]
    above.sort(key=lambda lv: (-lv.score, -lv.last_reaction_at, abs(lv.price - prev_close), -lv.price))
    below.sort(key=lambda lv: (-lv.score, -lv.last_reaction_at, abs(lv.price - prev_close), lv.price))
    return {"definition": definition, "atrBuild": round(atr_build, 6), "prevClose": round(prev_close, 4),
            "candidates": [lv.to_dict() for lv in levels],
            "above": [lv.to_dict() for lv in above[:cap]], "below": [lv.to_dict() for lv in below[:cap]]}


def mask_pm(kl: dict | None, pmh: float | None, pml: float | None, *, stage: str) -> dict | None:
    """09:25 (provisional) / 09:30 (completed) mask against the PM levels. Re-applied on each call from the level's
    build-time state, so a level masked provisionally and freed on the completed range is free. No refill."""
    if not kl or pmh is None or pml is None:
        return kl
    width = KEY_LEVEL_MASK_ATR * float(kl.get("atrBuild") or 0)
    out = dict(kl); masks = []
    for side in ("above", "below"):
        rows = []
        for lv in kl.get(side, []):
            lv = dict(lv)
            if lv.get("maskedBy") in ("pmh", "pml"):
                lv["maskedBy"] = "none"
            for tag, ref in (("pmh", pmh), ("pml", pml)):
                if abs(float(lv["price"]) - float(ref)) <= width:
                    lv["maskedBy"] = tag
                    masks.append({"levelId": lv["levelId"], "maskedBy": tag, "stage": stage})
                    break
            rows.append(lv)
        out[side] = rows
    out["pmMasks"] = masks
    out["pmMaskStage"] = stage
    return out


def advance_flip(level: dict, bar15m: Bar) -> str | None:
    """The flip state machine on one 15m close. Returns "break" | "confirm" | "reject" | "retire" | None and mutates
    the level dict (role, flips, flipPending, breakAt, flipConfirmedAt, retired)."""
    if level.get("retired"):
        return None
    price = float(level["price"]); role = level["role"]
    through = bar15m.close < price if role == "support" else bar15m.close > price
    if level.get("flipPending"):
        if through:
            level["flipPending"] = False
            level["flipConfirmedAt"] = bar15m.ts + 15 * 60_000
            level["role"] = "resistance" if role == "support" else "support"
            level["flips"] = int(level.get("flips") or 0) + 1
            if level["flips"] >= 2:
                level["retired"] = True
                return "retire"
            return "confirm"
        level["flipPending"] = False
        return "reject"
    if through:
        level["flipPending"] = True
        level["breakAt"] = bar15m.ts + 15 * 60_000
        return "break"
    return None


def active_key_levels(kl: dict | None) -> list[dict]:
    """Levels that may act: unmasked, not retired, not pending a flip."""
    if not kl:
        return []
    return [lv for side in ("above", "below") for lv in kl.get(side, [])
            if lv.get("maskedBy", "none") == "none" and not lv.get("retired") and not lv.get("flipPending")]


def ladder_with_key_levels(ladder: dict | None, kl: dict | None) -> dict:
    """The L3 ladder plus the active key levels as extra rungs (C2 package part iii)."""
    highs = set(float(x) for x in (ladder or {}).get("highs") or [])
    lows = set(float(x) for x in (ladder or {}).get("lows") or [])
    for lv in active_key_levels(kl):
        (highs if lv["role"] == "resistance" else lows).add(float(lv["price"]))
    return {"highs": sorted(highs), "lows": sorted(lows, reverse=True)}


__all__ += ["KeyLevel", "key_levels", "mask_pm", "advance_flip", "active_key_levels", "ladder_with_key_levels"]
