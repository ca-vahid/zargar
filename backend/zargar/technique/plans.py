"""Session plans — the book's pre-session routine, as data (spec T1.6, R6).

A plan is built as-of a session boundary (close of N, or anything outside the
regular session) from FACTS alone. It is *not* a trade: it is the map (levels
with provenance and age) plus **conditional triggers** — WATCH a level, IF
price does X inside a prime window with adequate volume, THEN long with this
stop/targets, VOID IF the open gaps past it — and the gap policy that voids the
whole plan. Every clause cites the rule it comes from. Nothing here calls the
model; `service` can run the vision passes on top as an opt-in.

Triggers are scored afterwards by `walkforward.replay_plan` against the next
session's bars, live by `arming.PlanArmer`, and both use the same
`TriggerTracker`, so validation and live behaviour cannot drift apart.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .levels import Level
from .rulebook import (
    DEFAULT_THRESHOLDS,
    PRIME_WINDOWS,
    Thresholds,
    next_session_date,
    session_date,
)
from .setups import bounce_stop, build_ladder, gate_label, gate_target, risk_reward, stop_buffer

MAX_BOUNCE_TRIGGERS = 3
MAX_BREAK_TRIGGERS = 2
# How far below the last close a support may sit and still be planned (a level
# 8% away is not "tomorrow's map").
MAX_LEVEL_DISTANCE_PCT = 0.04


@dataclass
class Condition:
    rule: str
    text: str
    kind: str            # touch | close_through | window | volume | decisive | followthrough

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Trigger:
    id: str
    kind: str                        # bounce | breakout | wedge_break
    direction: str                   # long
    level_price: float
    level: dict
    entry_price: float
    entry_basis: str                 # at_level | on_break
    stop_price: float
    stop_reference: str
    targets: list[dict]
    risk_reward: float               # measured to the R2 gate target (where the position exits)
    conditions: list[Condition]
    void_if: list[str]
    confluences: list[str]
    confidence: float
    rules: list[str]
    valid: bool
    no_trade_reasons: list[str]
    notes: str = ""
    assessment: dict = field(default_factory=dict)   # grade/score/strengths/cautions
    risk_reward_tp3: float = 0.0     # the book's figure: to the final target

    @property
    def risk(self) -> float:
        return max(self.entry_price - self.stop_price, 0.0)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "direction": self.direction,
            "levelPrice": round(self.level_price, 4), "level": self.level,
            "entry": {"price": round(self.entry_price, 4), "basis": self.entry_basis},
            "stop": {"price": round(self.stop_price, 4), "reference": self.stop_reference},
            "targets": self.targets, "riskReward": round(self.risk_reward, 2),
            "riskRewardTp3": round(self.risk_reward_tp3, 2),
            "risk": round(self.risk, 4),
            "conditions": [c.to_dict() for c in self.conditions], "voidIf": list(self.void_if),
            "confluences": list(self.confluences), "confidence": round(self.confidence, 3),
            "rules": sorted(set(self.rules)), "valid": self.valid,
            "noTradeReasons": list(self.no_trade_reasons), "notes": self.notes,
            "assessment": self.assessment,
            "setupType": {"bounce": "support_bounce", "breakout": "breakout",
                          "wedge_break": "falling_wedge"}[self.kind],
        }


@dataclass
class SessionPlan:
    symbol: str
    plan_for: str                     # ET date of the session the plan is for
    built_from_ms: int                # as-of instant
    built_from_session: str           # ET date of the last session consumed
    structure_tfs: list[str]
    trigger_tf: str
    last_close: float
    levels: list[dict]
    context: dict
    triggers: list[Trigger]
    invalidations: list[dict]
    gap_policy: dict
    notes: list[str] = field(default_factory=list)
    bottom_line: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "planFor": self.plan_for, "builtFromMs": self.built_from_ms,
            "builtFromSession": self.built_from_session, "structureTfs": list(self.structure_tfs),
            "triggerTf": self.trigger_tf, "lastClose": self.last_close,
            "levels": self.levels, "context": self.context,
            "triggers": [t.to_dict() for t in self.triggers],
            "invalidations": self.invalidations, "gapPolicy": self.gap_policy,
            "notes": list(self.notes), "bottomLine": self.bottom_line,
            "validTriggers": sum(1 for t in self.triggers if t.valid),
        }


def _level_from_dict(d: dict) -> Level:
    return Level(price=float(d["price"]), kind=d.get("effectiveKind") or d.get("kind") or "support",
                 touches=int(d.get("touches") or 0), sources=list(d.get("sources") or []),
                 touch_ts=list(d.get("touchTs") or []), first_ts=d.get("firstTs"),
                 last_ts=d.get("lastTs"), timeframe=(d.get("timeframes") or ["1m"])[0])


def _age_sessions(first_ts: int | None, as_of_ms: int) -> int | None:
    if not first_ts:
        return None
    return max(0, int((as_of_ms - first_ts) / 86_400_000))


def _window_condition() -> Condition:
    return Condition("R6.1/R6.2", "inside a prime window (09:30-10:30 or 14:45-16:00 ET)", "window")


def _volume_floor_condition(t: Thresholds) -> Condition:
    return Condition("R3.1", f"volume at the trigger bar >= {t.volume_floor_mult:.0%} of the "
                             f"time-of-day baseline", "volume")


def _trigger_confidence(level: Level, confl: list[str], rr: float, valid: bool) -> float:
    c = 0.3 + min(level.touches, 4) * 0.1 + (0.1 if "T1.3a" in level.sources else 0.0)
    c += 0.05 * len(confl)
    if rr >= 4:
        c += 0.05
    if not valid:
        c -= 0.3
    return max(0.0, min(1.0, c))


def assess_trigger(*, kind: str, lv: Level, rep: dict, zone_size: int, rr: float,
                   target_basis: str, risk: float, entry: float, last: float,
                   stop_reference: str, fakeout_level: float, hta: bool | None,
                   valid: bool, t: Thresholds, members_above: int = 0) -> dict:
    """Deterministic validity grade for a plan trigger — the 'how good is this,
    really' the user reads before arming. Every point cites a rule; the grade is
    A (take it seriously) / B (fine, nothing special) / C (technically clears
    the gates, weak). Invalid triggers get no grade — their noTradeReasons are
    the verdict — but strengths/cautions still show what the idea had."""
    strengths: list[str] = []
    cautions: list[str] = []
    score = 30
    if "T1.3a" in lv.sources:
        score += 12
        strengths.append("prior-day extreme — the book's strongest carried level (T1.3a)")
    if lv.touches >= t.strong_touches:
        score += 12
        strengths.append(f"{lv.touches} touches — a proven level (T1.2)")
    elif lv.touches >= t.min_touches:
        score += 6
        strengths.append(f"{lv.touches} touches (T1.2)")
    if len(rep.get("timeframes") or []) >= 2:
        score += 8
        strengths.append("level visible on multiple timeframes")
    if hta:
        score += 10
        strengths.append("higher-timeframe trend is not against it (T3.3g)")
    if zone_size > 1:
        score += 5
        strengths.append(f"a {zone_size}-level zone backs the idea")
    if rr >= t.min_risk_reward and target_basis in ("next_resistance", "next_support", "measured_move"):
        score += 15
        strengths.append(f"reward:risk {rr:.1f} measured to a real obstacle (R2)")
    elif rr >= t.min_risk_reward:
        score += 5
        cautions.append("targets are the book's 2/4/6% ladder — nothing overhead to anchor them, "
                        "so the R:R number is optimistic (T4.4)")
    if stop_reference in ("below_zone_low", "wedge_low", "below_broken_resistance", "below_invalidation_low",
                          "below_break_base"):
        score += 8
        strengths.append("stop sits below the chart structure that invalidates the idea (T4.3d)")
    dist = abs(entry - last) / last if last else 0.0
    if dist > 0.02:
        score -= 5
        cautions.append(f"the level is {dist:.1%} away — price may never reach it")
    tol = max(last * t.level_tolerance_pct, 1e-9)
    if fakeout_level and abs(fakeout_level - entry) <= max(tol * 4, entry * 0.005):
        score -= 15
        cautions.append("the last session's break of this level FAILED (T3.3d–f) — "
                        "demand every confirmation condition before believing a new one")
    if members_above > 0:
        score -= min(20, 5 + 5 * members_above)
        cautions.append(f"price must first break {members_above} zone support(s) above the entry — "
                        "the move that reaches this level argues against bouncing off it (T3.4d)")
    if kind != "bounce":
        cautions.append("fires only on full confirmation: volume surge + decisive candle "
                        "+ follow-through (T3.3a–c)")
    score = max(0, min(100, score))
    grade = ("A" if score >= 75 else "B" if score >= 55 else "C") if valid else None
    if grade == "A" and target_basis == "pct_ladder":
        grade = "B"
        cautions.append("grade capped at B: an A needs targets anchored to a real obstacle, "
                        "not the assumed 2/4/6% ladder")
    return {"grade": grade, "score": score, "strengths": strengths, "cautions": cautions}


def _fires_only_if(tg: Trigger) -> str:
    if tg.kind == "bounce":
        return (f"fires only if price trades down into {tg.entry_price:.2f} inside a prime "
                f"window on adequate volume")
    return (f"fires only if a bar CLOSES above {tg.entry_price:.2f} inside a prime window "
            f"with a volume surge, a decisive candle and follow-through")


def build_bottom_line(triggers: list[Trigger], plan_for: str) -> str:
    """One plain-language sentence: is there anything to do, and how good is it."""
    valid_t = [tg for tg in triggers if tg.valid]
    if not valid_t:
        why = ""
        if triggers:
            first = triggers[0]
            why = f" (nearest idea, {first.id} at {first.level_price:.2f}: {'; '.join(first.no_trade_reasons) or 'rejected'})"
        return (f"Nothing to arm for {plan_for}: no trigger clears the gates{why}. "
                "A valid plan with nothing to do — do not force a trade (p. 117).")
    parts = [f"{tg.id} {tg.kind} at {tg.level_price:.2f} — grade "
             f"{tg.assessment.get('grade') or '?'} — {_fires_only_if(tg)}"
             for tg in valid_t]
    return (f"Nothing to do before the open. {len(valid_t)} of {len(triggers)} trigger(s) "
            f"can arm for {plan_for}: " + "; ".join(parts) + ". None of this is a fill — "
            "a trigger that never meets its conditions simply never fires.")


def _higher_tf_agrees(context: dict, want: str) -> bool | None:
    """Does the highest structure timeframe's trend agree with a long idea?
    (`want` = uptrend for breakouts; for bounces sideways/uptrend both fine)."""
    trends = context.get("trend") or {}
    for tf in ("1h", "30m", "15m"):
        tr = trends.get(tf)
        if tr:
            d = tr.get("direction")
            if want == "uptrend":
                return d == "uptrend"
            return d in ("uptrend", "sideways")
    return None


def build_session_plan(facts: dict, *, thresholds: Thresholds | None = None,
                       structure_tfs: list[str] | tuple[str, ...] = ("1h", "30m"),
                       trigger_tf: str = "1m") -> SessionPlan:
    """Turn FACTS (computed as-of a session boundary) into a SessionPlan.

    Requires `facts` from `analysis.compute_facts` with `primary_tf == trigger_tf`
    and the structure timeframes as context, so `keyLevels` already merges the
    30m/1h structure with the trigger-timeframe detail.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    symbol = facts.get("symbol", "?")
    as_of = int(facts.get("asOf") or 0)
    last = float(facts.get("lastClose") or 0.0)
    ptf = facts.get("primaryTf") or trigger_tf
    atr_v = float((facts.get("atr") or {}).get(ptf) or 0.0)
    tol = max(last * t.level_tolerance_pct, 1e-9)
    plan_for = next_session_date(as_of) if as_of else "?"
    built_session = session_date(int(facts.get("lastTs") or as_of)) if (facts.get("lastTs") or as_of) else "?"

    sess = facts.get("session") or {}
    prev = sess.get("prev") or {}
    today = sess.get("today") or {}
    context = {
        "trend": facts.get("trend") or {},
        "volume": {tf: {k: v.get(k) for k in ("relativeToTimeOfDayAvg", "trend", "priceTrend", "belowFloor",
                                                 "measurable", "baselineSessions")}
                   for tf, v in (facts.get("volume") or {}).items()},
        "wedge": {tf: (w and {k: w.get(k) for k in ("widestHeight", "lowestPrice", "breakoutLevelNow",
                                                     "volumeDeclining")})
                  for tf, w in (facts.get("wedge") or {}).items()},
        "lastSession": {"date": built_session, "open": today.get("open"), "hod": today.get("hod"),
                        "lod": today.get("lod"), "close": last},
        "prevSession": prev,
        "sessionWindowAtBuild": facts.get("sessionWindow"),
        "notes": list(facts.get("notes") or []),
    }

    # --- levels with provenance and age -------------------------------------------
    levels: list[dict] = []
    for lv in facts.get("keyLevels") or []:
        levels.append({
            "price": round(float(lv["price"]), 4), "kind": lv.get("kind"),
            "effectiveKind": lv.get("effectiveKind") or lv.get("kind"),
            "touches": lv.get("touches"), "sources": list(lv.get("sources") or []),
            "timeframes": list(lv.get("timeframes") or []),
            "position": lv.get("position"),
            "distancePct": round((float(lv["price"]) - last) / last * 100, 3) if last else None,
            "ageSessions": _age_sessions(lv.get("firstTs"), as_of),
            "priorDayExtreme": "T1.3a" in (lv.get("sources") or []),
        })
    # Carry the last session's HOD/LOD explicitly (T1.3a) even if the detector
    # did not promote them to levels yet — they become tomorrow's strongest refs.
    for key, kind in (("lod", "support"), ("hod", "resistance")):
        px = today.get(key)
        if px and not any(abs(l["price"] - px) <= tol * 2 for l in levels):
            levels.append({"price": round(float(px), 4), "kind": kind, "effectiveKind": kind,
                           "touches": 1, "sources": ["T1.3a"], "timeframes": [ptf],
                           "position": "above" if px > last else "below",
                           "distancePct": round((px - last) / last * 100, 3) if last else None,
                           "ageSessions": 0, "priorDayExtreme": True, "carried": True})
    levels.sort(key=lambda l: (0 if l["priorDayExtreme"] else 1, -(l["touches"] or 0)))

    # --- triggers ------------------------------------------------------------------
    triggers: list[Trigger] = []
    notes: list[str] = []
    # Levels closer together than this are one zone, not a ladder of separate
    # trades (T4.3d: the zone's floor is what invalidates, not each rung).
    merge_dist = max(tol * 2, last * t.zone_merge_pct)
    # The stop buffer breathes with structure volatility, not 1m bar noise.
    stop_atr = max([float((facts.get("atr") or {}).get(tf) or 0.0) for tf in structure_tfs] + [atr_v])
    trig_trend = ((facts.get("trend") or {}).get(ptf) or {}).get("direction")

    all_resistances = sorted([l for l in levels if l["effectiveKind"] == "resistance"],
                             key=lambda l: l["price"])
    supports_below = sorted([l for l in levels if l["effectiveKind"] == "support" and l["price"] < last],
                            key=lambda l: -l["price"])
    # A failed break of a level last session makes a new attempt suspect (T3.3d-f).
    rb = facts.get("recentBreak") or {}
    fakeout_level = float(rb.get("levelPrice") or 0.0) if rb.get("isFakeout") else 0.0

    def _zones(members: list[dict]) -> list[list[dict]]:
        """Chain-merge adjacent levels into zones. `members` must be sorted from
        nearest to farthest; a level joins the current zone while it is within
        `merge_dist` of the zone's far edge and the zone stays narrower than the
        stop cap."""
        out: list[list[dict]] = []
        for ld in members:
            if out:
                cur = out[-1]
                width_ok = abs(ld["price"] - cur[0]["price"]) <= cur[0]["price"] * t.max_stop_pct
                if abs(cur[-1]["price"] - ld["price"]) <= merge_dist and width_ok:
                    cur.append(ld)
                    continue
            out.append([ld])
        return out

    def _representative(zone: list[dict]) -> dict:
        """The member that carries the zone's STRENGTH (touches first, prior-day
        extreme as tiebreak) — used for confluences and grading. It is NOT the
        entry: a bounce always enters at the zone's TOP member, because that is
        the first touch that can actually be traded. An entry deeper in the zone
        means price broke the members above it to get there, and that context
        argues against the bounce (T3.4d — WDAY 2026-08-24 graded such an entry
        A while a 42-touch shelf sat five members higher)."""
        return max(zone, key=lambda m: (m.get("touches") or 0, bool(m.get("priorDayExtreme"))))

    def _next_resistance_above(price: float, exclude: set[float] = frozenset()) -> dict | None:
        return next((r for r in all_resistances
                     if r["price"] > price + tol and r["price"] not in exclude), None)

    def _break_base(level_price: float) -> float | None:
        """The most recent trigger-tf swing low under `level_price` within the stop
        cap (`facts.swingLows`, T4.3d) — where a failed break would prove itself."""
        floor = level_price * (1 - t.max_stop_pct)
        lows = [float(p["price"]) for p in (facts.get("swingLows") or {}).get(ptf) or []
                if floor <= float(p["price"]) < level_price]
        return lows[-1] if lows else None

    # Bounce triggers — nearest support zones below, within reach.
    n = 0
    for zone in _zones(supports_below):
        if n >= MAX_BOUNCE_TRIGGERS:
            break
        rep = _representative(zone)
        entry = zone[0]["price"]         # the zone's top — the first tradeable touch
        if (last - entry) / last > MAX_LEVEL_DISTANCE_PCT:
            continue
        lv = _level_from_dict({**rep, "effectiveKind": "support"})
        zone_low = min(m["price"] for m in zone)
        # T4.3d — the stop goes below what invalidates the idea: the zone's
        # floor (which includes a carried prior-day LOD) when there is one.
        stop = bounce_stop(entry, atr_value=stop_atr, thresholds=t,
                           invalidation=zone_low if zone_low < entry else None)
        if triggers and entry >= triggers[-1].stop_price:
            notes.append(f"support {entry:.2f} skipped: inside the risk envelope of trigger "
                         f"{triggers[-1].id} (entry above its stop {triggers[-1].stop_price:.2f})")
            continue
        risk = entry - stop
        next_res = _next_resistance_above(entry)
        targets = build_ladder(entry, "long", next_level=(next_res["price"] if next_res else None))
        rr = risk_reward(entry, stop, gate_target(targets, t).price)
        rr3 = risk_reward(entry, stop, targets[-1].price)
        confl = []
        if "T1.3a" in lv.sources:
            confl.append("prior-day extreme (T1.3a)")
        if lv.touches >= t.strong_touches:
            confl.append(f"{lv.touches} touches (T1.2)")
        hta = _higher_tf_agrees(context, "bounce")
        if hta:
            confl.append("higher timeframe not against it (T3.3g)")
        if len(rep.get("timeframes") or []) >= 2:
            confl.append("confluence across timeframes")
        if len(zone) > 1:
            confl.append(f"zone of {len(zone)} levels ({zone_low:.2f}-{zone[0]['price']:.2f})")
        reasons: list[str] = []
        if rr < t.min_risk_reward - 1e-9:
            reasons.append(f"R2 reward:risk {rr:.2f} to {gate_label(t)} below {t.min_risk_reward:.1f}")
        if lv.touches < t.min_touches and "T1.3a" not in lv.sources:
            reasons.append(f"T1.2 only {lv.touches} touch(es)")
        if risk > entry * t.max_stop_pct:
            reasons.append(f"T4.3a/R1 the stop the chart justifies ({stop:.2f}) is "
                           f"{risk / entry:.1%} away — beyond the {t.max_stop_pct:.1%} cap")
        if trig_trend == "sideways" and atr_v > 0 and risk < t.chop_stop_atr * atr_v:
            reasons.append(f"R3.2 stop {risk:.2f} sits inside the chop: {ptf} trend is sideways "
                           f"and the stop is under {t.chop_stop_atr:.0f}x its ATR ({atr_v:.2f})")
        valid = not reasons
        rules = ["T1.2", "T1.6", "T4.1", "T4.2", "T4.3a", "T4.3d", "T4.4a", "R2", "R3.1", "R3.2",
                 "R6.1", "R6.2"] + list(lv.sources)
        if len(confl) >= 2:
            rules.append("T4.6")
        stop_ref = "below_zone_low" if zone_low < entry else "below_support"
        assessment = assess_trigger(kind="bounce", lv=lv, rep=rep, zone_size=len(zone), rr=rr,
                                    target_basis=targets[0].basis, risk=risk, entry=entry,
                                    last=last, stop_reference=stop_ref, fakeout_level=fakeout_level,
                                    hta=hta, valid=valid, t=t,
                                    members_above=sum(1 for m in zone if m["price"] > entry + tol))
        n += 1
        triggers.append(Trigger(
            id=f"b{n}", kind="bounce", direction="long", level_price=entry,
            level={**rep, "zone": {"high": zone[0]["price"], "low": zone_low,
                                   "members": [m["price"] for m in zone]}},
            entry_price=entry, entry_basis="at_level", stop_price=stop,
            stop_reference=stop_ref,
            targets=[tg.to_dict() for tg in targets], risk_reward=rr, risk_reward_tp3=rr3,
            conditions=[
                Condition("T4.1", f"price trades down into {entry:.2f} (+/- {tol:.2f})", "touch"),
                _window_condition(), _volume_floor_condition(t),
            ],
            void_if=[f"session opens below the stop {stop:.2f} (level gapped through)",
                     f"session opens below {entry:.2f} (gapped past the level — do not chase, T4.1)",
                     f"|open - prev close| > {t.gap_void_r:.1f}x risk ({t.gap_void_r * (entry - stop):.2f})"],
            confluences=confl, confidence=_trigger_confidence(lv, confl, rr, valid),
            rules=rules, valid=valid, no_trade_reasons=reasons, assessment=assessment,
            notes="Bounce: enter AT the level, no visual confirmation (T4.2); a hammer / long lower "
                  "wick at the touch raises confidence (T3.4b) but is not required.",
        ))

    # Breakout triggers — nearest resistance zones above the last close. A break
    # must clear the whole zone, so entry is the zone's top; a failed break is
    # back below the zone, so the stop is under its floor.
    resistances_above = [r for r in all_resistances if r["price"] > last + tol]
    m = 0
    for zone in _zones(resistances_above):
        if m >= MAX_BREAK_TRIGGERS:
            break
        rep = _representative(zone)
        zone_top = max(mm["price"] for mm in zone)
        zone_low = min(mm["price"] for mm in zone)
        entry = zone_top
        if (entry - last) / last > MAX_LEVEL_DISTANCE_PCT:
            continue
        lv = _level_from_dict({**rep, "effectiveKind": "resistance"})
        # T4.3d — the stop sits under the base the break launches from: the most
        # recent swing low below the zone (within the stop cap), else the zone's
        # floor. `zone_low - buffer` alone collapsed to `level - 0.5 %` for every
        # single-level zone (T k1 2026-08-26: 25.87 -> 25.7407), a fixed-percent
        # stop in costume that pinned breakout R:R near 12.
        base = _break_base(zone_low)
        anchor = base if base is not None else zone_low
        stop = anchor - stop_buffer(anchor, atr_value=stop_atr, thresholds=t)
        stop_ref = "below_break_base" if base is not None else "below_broken_resistance"
        risk = entry - stop
        member_prices = {mm["price"] for mm in zone}
        next_res = _next_resistance_above(entry, exclude=member_prices)
        targets = build_ladder(entry, "long", next_level=(next_res["price"] if next_res else None))
        rr = risk_reward(entry, stop, gate_target(targets, t).price)
        rr3 = risk_reward(entry, stop, targets[-1].price)
        confl = []
        if "T1.3a" in lv.sources:
            confl.append("prior-day extreme (T1.3a)")
        if lv.touches >= t.strong_touches:
            confl.append(f"{lv.touches} touches (T1.2)")
        hta = _higher_tf_agrees(context, "uptrend")
        if hta:
            confl.append("higher timeframe uptrend (T3.3g)")
        reasons = []
        if rr < t.min_risk_reward - 1e-9:
            reasons.append(f"R2 reward:risk {rr:.2f} to {gate_label(t)} below {t.min_risk_reward:.1f}")
        if risk > entry * t.max_stop_pct:
            reasons.append(f"T4.3a/R1 the stop the chart justifies ({stop:.2f}) is "
                           f"{risk / entry:.1%} away — beyond the {t.max_stop_pct:.1%} cap")
        valid = not reasons
        rules = ["T1.2", "T1.6", "T3.3a", "T3.3b", "T3.3c", "T2.5", "T4.1", "T4.3a", "T4.4a", "R2", "R6.1", "R6.2"] + list(lv.sources)
        if len(confl) >= 2:
            rules.append("T4.6")
        assessment = assess_trigger(kind="breakout", lv=lv, rep=rep, zone_size=len(zone), rr=rr,
                                    target_basis=targets[0].basis, risk=risk, entry=entry,
                                    last=last, stop_reference=stop_ref,
                                    fakeout_level=fakeout_level, hta=hta, valid=valid, t=t)
        m += 1
        triggers.append(Trigger(
            id=f"k{m}", kind="breakout", direction="long", level_price=entry,
            level={**rep, "zone": {"high": zone_top, "low": zone_low,
                                   "members": [mm["price"] for mm in zone]},
                   **({"breakBase": round(base, 4)} if base is not None else {})},
            entry_price=entry, entry_basis="on_break", stop_price=stop,
            stop_reference=stop_ref,
            targets=[tg.to_dict() for tg in targets], risk_reward=rr, risk_reward_tp3=rr3,
            conditions=[
                Condition("T3.3b", f"a bar CLOSES above {entry:.2f}", "close_through"),
                _window_condition(),
                Condition("T3.3a/T2.5", f"volume on the break >= {t.volume_spike_mult:.1f}x baseline", "volume"),
                Condition("T3.3b", "decisive candle (large body, minimal wicks)", "decisive"),
                Condition("T3.3c/T3.3f", f"{t.followthrough_required} of the next {t.followthrough_bars} bars "
                                         f"hold above the level", "followthrough"),
            ],
            void_if=[f"session opens above {entry:.2f} (gapped past — do not chase, T4.1)",
                     f"|open - prev close| > {t.gap_void_r:.1f}x risk ({t.gap_void_r * (entry - stop):.2f})"],
            confluences=confl, confidence=_trigger_confidence(lv, confl, rr, valid),
            rules=rules, valid=valid, no_trade_reasons=reasons, assessment=assessment,
            notes="Breakout: confirmation REQUIRED (volume surge + decisive candle + follow-through); "
                  "any fakeout tell (T3.3d-f) cancels it.",
        ))

    # Wedge break — if the detectors see a falling wedge on the trigger or a structure tf.
    for tf in [ptf] + list(structure_tfs):
        w = (facts.get("wedge") or {}).get(tf)
        if not w:
            continue
        lvl = float(w.get("breakoutLevelNow") or 0)
        if lvl <= 0:
            continue
        w_low = float(w["lowestPrice"])
        stop = w_low - stop_buffer(w_low, atr_value=stop_atr, thresholds=t)
        targets = build_ladder(lvl, "long", measured_move=float(w.get("widestHeight") or 0))
        rr = risk_reward(lvl, stop, gate_target(targets, t).price)
        rr3 = risk_reward(lvl, stop, targets[-1].price)
        reasons = []
        if rr < t.min_risk_reward - 1e-9:
            reasons.append(f"R2 reward:risk {rr:.2f} to {gate_label(t)} below {t.min_risk_reward:.1f}")
        if not w.get("volumeDeclining"):
            reasons.append("T3.1c volume not declining into the wedge")
        valid = not reasons
        wd = {"price": round(lvl, 4), "kind": "resistance", "effectiveKind": "resistance",
              "touches": 2, "sources": ["T3.1"], "timeframes": [tf], "wedge": w}
        w_lv = _level_from_dict(wd)
        w_assessment = assess_trigger(kind="wedge_break", lv=w_lv, rep=wd, zone_size=1, rr=rr,
                                      target_basis=targets[0].basis, risk=lvl - stop, entry=lvl,
                                      last=last, stop_reference="wedge_low",
                                      fakeout_level=fakeout_level,
                                      hta=_higher_tf_agrees(context, "uptrend"), valid=valid, t=t)
        triggers.append(Trigger(
            id=f"w{tf}", kind="wedge_break", direction="long", level_price=lvl, level=wd,
            entry_price=lvl, entry_basis="on_break", stop_price=stop, stop_reference="wedge_low",
            targets=[tg.to_dict() for tg in targets], risk_reward=rr, risk_reward_tp3=rr3,
            conditions=[
                Condition("T3.1d", f"a bar CLOSES above the upper wedge line (~{lvl:.2f} at the close of {built_session})", "close_through"),
                _window_condition(),
                Condition("T3.3a/T2.5", f"volume on the break >= {t.volume_spike_mult:.1f}x baseline", "volume"),
                Condition("T3.3b", "decisive candle", "decisive"),
                Condition("T3.3c", f"{t.followthrough_required} of the next {t.followthrough_bars} bars hold above", "followthrough"),
            ],
            void_if=[f"session opens above {lvl:.2f} (gapped past)",
                     f"|open - prev close| > {t.gap_void_r:.1f}x risk"],
            confluences=(["falling wedge (T3.1)"] + (["volume declining (T3.1c)"] if w.get("volumeDeclining") else [])),
            confidence=0.5 if valid else 0.25, rules=["T3.1a", "T3.1b", "T3.1c", "T3.1d", "T3.1e", "T3.1f", "R6.1", "R6.2"],
            valid=valid, no_trade_reasons=reasons, assessment=w_assessment,
            notes=f"Wedge break on {tf}: stop below the wedge low (T3.1e), target = measured height (T3.1f).",
        ))
        break

    if not triggers:
        notes.append("No level within reach — a valid plan with nothing to do (p. 117: day trading "
                     "doesn't mean trading every day).")

    invalidations = [
        {"rule": "Q13", "text": f"whole plan void if |open - prev close| exceeds {t.gap_void_r:.1f}x a trigger's risk",
         "kind": "gap_void"},
        {"rule": "T4.1", "text": "a trigger whose level was gapped past at the open is not chased", "kind": "gapped_past"},
        {"rule": "T4.3a", "text": "a trigger whose stop was gapped through at the open is void", "kind": "gapped_through"},
        {"rule": "R6.4", "text": "plan expires at the session close; nothing is held overnight", "kind": "expiry"},
    ]
    gap_policy = {"gapVoidR": t.gap_void_r, "respectMult": t.respect_mult,
                  "entryWindowBars": t.plan_entry_window_bars, "primeWindows": list(PRIME_WINDOWS),
                  "extrapolation": "the book is silent on overnight gaps (spec Q11-Q13)"}
    return SessionPlan(symbol=symbol, plan_for=plan_for, built_from_ms=as_of, built_from_session=built_session,
                       structure_tfs=list(structure_tfs), trigger_tf=trigger_tf, last_close=last,
                       levels=levels, context=context, triggers=triggers, invalidations=invalidations,
                       gap_policy=gap_policy, notes=notes,
                       bottom_line=build_bottom_line(triggers, plan_for))


def analysis_from_trigger(trigger: dict, symbol: str, *, session_window: str = "unknown",
                          confidence: float | None = None):
    """A `TechniqueAnalysis` (the pipeline's contract) for a fired trigger, so the
    live path can reuse `_persist_setup` / the critic / proposals unchanged."""
    from .schemas import TechniqueAnalysis
    lv = trigger.get("level") or {}
    targets = trigger.get("targets") or []
    trims = (30.0, 40.0, 15.0)
    base = dict(
        symbol=symbol, verdict="setup", setup_type=trigger.get("setupType") or "support_bounce",
        direction="long", trend="sideways",
        levels=[{"price": float(trigger["levelPrice"]), "kind": lv.get("effectiveKind") or lv.get("kind") or "support",
                 "touches": int(lv.get("touches") or 1), "note": ",".join(lv.get("sources") or [])}],
        pattern_kind="falling_wedge" if trigger.get("kind") == "wedge_break" else "none",
        pattern_present=trigger.get("kind") == "wedge_break",
        pattern_widest_height=float(((lv.get("wedge") or {}).get("widestHeight")) or 0.0),
        pattern_volume_declining=bool((lv.get("wedge") or {}).get("volumeDeclining")), pattern_notes="",
        breakout_observed=trigger.get("kind") != "bounce", breakout_verdict="breakout" if trigger.get("kind") != "bounce" else "none",
        breakout_level=float(trigger["levelPrice"]) if trigger.get("kind") != "bounce" else 0.0,
        breakout_volume_confirmed=trigger.get("kind") != "bounce", breakout_decisive_candle=trigger.get("kind") != "bounce",
        breakout_follow_through=trigger.get("kind") != "bounce", breakout_holds_level=trigger.get("kind") != "bounce",
        higher_tf_agrees=any("higher timeframe" in c for c in (trigger.get("confluences") or [])),
        entry_price=float(trigger["entry"]["price"]), entry_basis=trigger["entry"].get("basis", "at_level"),
        entry_requires_confirmation=trigger.get("kind") != "bounce",
        stop_price=float(trigger["stop"]["price"]), stop_kind="mental",
        stop_reference=trigger["stop"].get("reference", "below_support"),
        targets=[{"price": float(tg["price"]), "trim_pct": float(tg.get("trimPct") or trims[i] if i < 3 else 15.0),
                  "basis": tg.get("basis", "next_resistance")} for i, tg in enumerate(targets[:3])],
        runner_pct=15.0, risk_reward=float(trigger.get("riskReward") or 0.0),
        volume_verdict="judged at the trigger bar (T2.9)",
        confidence=float(confidence if confidence is not None else trigger.get("confidence") or 0.5),
        rules_fired=list(trigger.get("rules") or []), no_trade_reasons=list(trigger.get("noTradeReasons") or []),
        options_strike_guidance="first strike just OTM (T5.1)", options_expiry_guidance="current-week Friday; 0DTE with reduced size (T5.2)",
        options_warnings=[], rationale=f"Planned {trigger.get('kind')} trigger {trigger.get('id')} fired: "
                                       + "; ".join(c.get("text", "") for c in (trigger.get("conditions") or [])),
        session_window=session_window, plan_mode=False)
    return TechniqueAnalysis.model_validate(base)


def plan_summary_text(plan: dict) -> str:
    """Human-readable plan for the run's chat thread / CLI."""
    L = [f"**{plan['symbol']} — session plan for {plan['planFor']}** (built from the {plan['builtFromSession']} close "
         f"{plan['lastClose']:.2f}; structure {', '.join(plan['structureTfs'])}, triggers on {plan['triggerTf']})"]
    lv = plan.get("levels") or []
    if lv:
        L.append("Levels: " + "; ".join(f"{l['price']:.2f} {l['effectiveKind'][0].upper()} x{l['touches']}"
                                        + (" PD" if l.get("priorDayExtreme") else "") for l in lv[:8]))
    for tg in plan.get("triggers") or []:
        a = tg.get("assessment") or {}
        head = (f"{tg['id']} {tg['kind']} @ {tg['levelPrice']:.2f}: "
                + (f"ARMABLE (grade {a.get('grade')})" if tg["valid"] and a.get("grade")
                   else "ARMABLE" if tg["valid"] else "not tradeable"))
        L.append(f"- {head} — IF " + "; ".join(c["text"] for c in tg["conditions"])
                 + f" THEN long {tg['entry']['price']:.2f}, stop {tg['stop']['price']:.2f}, "
                   f"targets {[x['price'] for x in tg['targets']]}, R:R {tg['riskReward']:.2f}"
                 + (f" · {'; '.join(tg['noTradeReasons'])}" if tg["noTradeReasons"] else ""))
    if not plan.get("triggers"):
        L.append("- no triggers within reach")
    if plan.get("bottomLine"):
        L.append(f"Bottom line: {plan['bottomLine']}")
    L.append("Void: " + "; ".join(i["text"] for i in plan.get("invalidations") or []))
    return "\n".join(L)
