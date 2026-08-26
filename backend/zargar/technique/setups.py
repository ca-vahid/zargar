"""Setup construction: breakout/fakeout classification and trade arithmetic.

Implements spec modules T3.3 (breakout vs fakeout), T4 (entry, stop, targets),
and R2 (the reward:risk gate), plus the two-setup taxonomy from spec §8:

* **Setup A — support bounce**: enter *at* the level, no confirmation wait (T4.2).
* **Setup B — breakout / wedge break**: confirmation *required* (T3.3).

That split is how we resolve the book's own contradiction between "don't wait for
visual confirmation" and "wait for the volume spike"; see spec §T4.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Bar
from .candles import classify, is_decisive
from .levels import Level
from .rulebook import DEFAULT_THRESHOLDS, Thresholds
from .structure import Wedge
from .volume import VolumeAssessment

__all__ = [
    "BreakoutVerdict", "Target", "Setup",
    "classify_breakout", "build_ladder", "build_bounce_setup",
    "build_breakout_setup", "risk_reward",
    "stop_buffer", "invalidation_low", "bounce_stop",
]

# T4.4a — the author's own scale-out ladder.
LADDER_TRIMS = (0.30, 0.40, 0.15)
RUNNER_PCT = 0.15
# T4.4 — his worked example is +2/+4/+6 on a $100 entry.
LADDER_PCTS = (0.02, 0.04, 0.06)


@dataclass
class BreakoutVerdict:
    """Whether a move through a level is real (T3.3)."""

    is_breakout: bool
    is_fakeout: bool
    has_volume: bool
    is_decisive: bool
    has_followthrough: bool
    holds_level: bool
    rules: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "isBreakout": self.is_breakout,
            "isFakeout": self.is_fakeout,
            "hasVolume": self.has_volume,
            "isDecisive": self.is_decisive,
            "hasFollowthrough": self.has_followthrough,
            "holdsLevel": self.holds_level,
            "rules": list(self.rules),
            "reasons": list(self.reasons),
        }


@dataclass
class Target:
    price: float
    trim_pct: float
    basis: str

    def to_dict(self) -> dict:
        return {
            "price": round(self.price, 4),
            "trimPct": round(self.trim_pct * 100, 1),
            "basis": self.basis,
        }


@dataclass
class Setup:
    """A complete, checkable trade plan in underlying price terms."""

    symbol: str
    setup_type: str                 # support_bounce | breakout | falling_wedge
    direction: str                  # long | short
    entry: float
    entry_basis: str                # at_level | on_break
    requires_confirmation: bool
    stop: float
    stop_kind: str                  # mental | hard
    stop_reference: str
    targets: list[Target] = field(default_factory=list)
    runner_pct: float = RUNNER_PCT
    risk_reward: float = 0.0            # measured to the R2 gate target (where the position exits)
    risk_reward_tp3: float = 0.0        # the book's figure: to the final target
    level_price: float | None = None
    rules: list[str] = field(default_factory=list)
    no_trade_reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""

    @property
    def valid(self) -> bool:
        return not self.no_trade_reasons

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "setupType": self.setup_type,
            "direction": self.direction,
            "entry": {
                "price": round(self.entry, 4),
                "basis": self.entry_basis,
                "requiresConfirmation": self.requires_confirmation,
            },
            "stop": {
                "price": round(self.stop, 4),
                "kind": self.stop_kind,
                "reference": self.stop_reference,
            },
            "targets": [t.to_dict() for t in self.targets],
            "runnerPct": round(self.runner_pct * 100, 1),
            "riskReward": round(self.risk_reward, 2),
            "riskRewardTp3": round(self.risk_reward_tp3, 2),
            "levelPrice": round(self.level_price, 4) if self.level_price is not None else None,
            "rules": list(self.rules),
            "noTradeReasons": list(self.no_trade_reasons),
            "confidence": round(self.confidence, 3),
            "valid": self.valid,
            "notes": self.notes,
        }


def risk_reward(entry: float, stop: float, target: float) -> float:
    """Reward divided by risk. 0.0 when the stop is at or beyond the entry."""
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    return abs(target - entry) / risk


def gate_target(targets: list[Target], thresholds: Thresholds | None = None) -> Target | None:
    """R2 — the rung the reward:risk gate is measured to (`Thresholds.rr_gate_target`)."""
    if not targets:
        return None
    t = thresholds or DEFAULT_THRESHOLDS
    return targets[min(max(int(t.rr_gate_target), 0), len(targets) - 1)]


def gate_label(thresholds: Thresholds | None = None) -> str:
    t = thresholds or DEFAULT_THRESHOLDS
    return f"TP{min(max(int(t.rr_gate_target), 0), 2) + 1}"


def breakout_anchor(bars: list[Bar], level_price: float, *, thresholds: Thresholds | None = None,
                    lookback: int = 60) -> float | None:
    """T3.1e generalised to any break (T4.3d): the stop belongs under the base
    the break launches from — the most recent swing low BELOW the level, within
    the acceptable stop distance — never a percentage of the level (until
    2026-08-26 breakouts used `level - 0.5 %`, a fixed-percent stop in costume
    that pinned every breakout's R:R near 12). None when nothing under the level
    qualifies; the caller then anchors on the level itself with the usual buffer."""
    from .levels import find_pivots
    t = thresholds or DEFAULT_THRESHOLDS
    floor = level_price * (1 - t.max_stop_pct)
    window = bars[-lookback:] if lookback else list(bars)
    lows = [p.price for p in find_pivots(window, window=t.pivot_window)
            if p.kind == "low" and floor <= p.price < level_price]
    if lows:
        return float(lows[-1])                        # the most recent base
    recent = [b.low for b in window[-(t.pivot_window * 2):] if floor <= b.low < level_price]
    return float(min(recent)) if recent else None


def classify_breakout(
    bars: list[Bar],
    level: Level,
    break_index: int,
    volume: VolumeAssessment,
    *,
    direction: str = "long",
    thresholds: Thresholds | None = None,
) -> BreakoutVerdict:
    """Apply the three-test breakout / three-test fakeout discriminator (T3.3).

    A breakout requires volume confirmation, a decisive candle, and
    follow-through. Any failure makes it a fakeout — the book is emphatic that
    the default assumption on a weak break is that it will fail.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    if not bars or break_index < 0 or break_index >= len(bars):
        return BreakoutVerdict(False, True, False, False, False, False,
                               ["T3.3d"], ["no candle at break index"])

    bar = bars[break_index]
    prior = bars[:break_index]
    rules: list[str] = []
    reasons: list[str] = []

    # 1. Volume confirmation (T3.3a / T3.3d)
    has_volume = volume.is_spike
    if has_volume:
        rules.append("T3.3a")
        rules.append("T2.5")
    else:
        rules.append("T3.3d")
        rules.append("T2.6")
        reasons.append("no volume surge behind the break")

    # 2. Decisive price action (T3.3b / T3.3e)
    decisive, candle_rules = is_decisive(bar, prior, direction=direction, thresholds=t)
    rules.extend(candle_rules)
    if not decisive:
        reasons.append("break candle is not decisive (small body or rejection wick)")

    # The close must actually clear the level, not merely touch it (T3.3b).
    cleared = bar.close > level.price if direction == "long" else bar.close < level.price
    if not cleared:
        decisive = False
        reasons.append("candle did not close beyond the level")

    # 3. Follow-through (T3.3c / T3.3f)
    after = bars[break_index + 1:break_index + 1 + t.followthrough_bars]
    if after:
        if direction == "long":
            continued = sum(1 for b in after if b.close > bar.close)
            held = all(b.close > level.price for b in after)
        else:
            continued = sum(1 for b in after if b.close < bar.close)
            held = all(b.close < level.price for b in after)
        has_follow = continued >= t.followthrough_required
        holds = held
    else:
        # Not enough bars yet — unresolved rather than failed.
        has_follow = False
        holds = cleared

    if has_follow:
        rules.append("T3.3c")
    elif after:
        reasons.append("no follow-through in the next candles")
    if after and not holds:
        rules.append("T3.3f")
        reasons.append("price failed to hold the level it broke")

    # A break that survived its follow-through window but has since faded back
    # through the level is no longer holding AS OF THE LAST BAR — judging only
    # the first N bars let a mid-afternoon break read "holds=True" while the
    # close sat back below the level (COP 2026-08-21, chat 06cad365).
    last_close = bars[-1].close
    faded = last_close < level.price if direction == "long" else last_close > level.price
    if holds and faded:
        holds = False
        rules.append("T3.3f")
        reasons.append(f"price is back {'below' if direction == 'long' else 'above'} the level "
                       f"at the last close ({last_close:.2f})")

    is_breakout = has_volume and decisive and (has_follow or not after) and holds
    return BreakoutVerdict(
        is_breakout=is_breakout,
        is_fakeout=not is_breakout,
        has_volume=has_volume,
        is_decisive=decisive,
        has_followthrough=has_follow,
        holds_level=holds,
        rules=sorted(set(rules)),
        reasons=reasons,
    )


def build_ladder(
    entry: float,
    direction: str,
    *,
    measured_move: float | None = None,
    next_level: float | None = None,
) -> list[Target]:
    """Three scale-out targets per T4.4a (30/40/15, leaving a 15% runner).

    Anchor priority follows the book: a measured pattern move (T3.1f) wins;
    otherwise the next opposing level; otherwise his 2/4/6% ladder.
    """
    sign = 1.0 if direction == "long" else -1.0

    if measured_move and measured_move > 0:
        full = entry + sign * measured_move
        basis = "measured_move"
        prices = [entry + (full - entry) * f for f in (0.4, 0.75, 1.0)]
    elif next_level is not None:
        full = next_level
        basis = "next_resistance" if direction == "long" else "next_support"
        prices = [entry + (full - entry) * f for f in (0.4, 0.75, 1.0)]
    else:
        basis = "pct_ladder"
        prices = [entry * (1 + sign * p) for p in LADDER_PCTS]

    return [Target(price=p, trim_pct=trim, basis=basis)
            for p, trim in zip(prices, LADDER_TRIMS)]


def _confidence(level: Level, volume: VolumeAssessment, extra: float = 0.0) -> float:
    """Heuristic 0-1 confidence from level strength and volume agreement."""
    score = 0.3
    score += min(level.touches, 4) * 0.1          # T1.2
    if "T1.3a" in level.sources:                   # prior-day extreme
        score += 0.1
    if volume.is_spike or volume.is_dryup:
        score += 0.1
    if volume.below_floor:
        score -= 0.3
    return max(0.0, min(1.0, score + extra))


def stop_buffer(anchor_price: float, *, atr_value: float = 0.0,
                thresholds: Thresholds | None = None) -> float:
    """Clearance below the invalidating price: the larger of two touch
    tolerances, the book's 0.5% ($98 support -> watch ~$97.50), and an ATR
    multiple, so it scales with volatility."""
    t = thresholds or DEFAULT_THRESHOLDS
    tol = max(anchor_price * t.level_tolerance_pct, 1e-9)
    return max(tol * 2, anchor_price * t.bounce_stop_pct, atr_value * t.stop_buffer_atr)


def invalidation_low(bars: list[Bar], level_price: float, *,
                     thresholds: Thresholds | None = None) -> float | None:
    """T4.3d — the price that actually invalidates a bounce at `level_price`:
    the lowest recent trade *below* the level but within the acceptable stop
    distance (the chop band / zone floor under the level). None when price has
    never traded below the level in the window — then the level itself is the
    invalidation and the buffer alone applies (the book's $98 example).
    Deeper prints (below `max_stop_pct`) belong to an older regime and are
    ignored — a stop that far away fails R1 anyway."""
    t = thresholds or DEFAULT_THRESHOLDS
    floor = level_price * (1 - t.max_stop_pct)
    lows = [b.low for b in bars if floor <= b.low < level_price]
    return min(lows) if lows else None


def bounce_stop(level_price: float, *, atr_value: float = 0.0,
                thresholds: Thresholds | None = None,
                invalidation: float | None = None) -> float:
    """T4.3a/T4.3d — the mental stop sits just below the price that invalidates
    the idea: the recent low / zone floor beneath the level when the chart shows
    one (`invalidation`), else the level itself. Never a bare percent of price —
    the buffer is only the clearance below that chart anchor."""
    anchor = level_price
    if invalidation is not None and 0 < invalidation < level_price:
        anchor = invalidation
    return anchor - stop_buffer(anchor, atr_value=atr_value, thresholds=thresholds)


def confluences(level: Level, volume: VolumeAssessment, *, higher_tf_agrees: bool | None = None,
                candle_bullish: bool = False) -> list[str]:
    """T4.6 — the agreeing factors behind a setup (the book asks for 2+)."""
    out: list[str] = []
    if "T1.3a" in level.sources:
        out.append("prior-day extreme (T1.3a)")
    if level.touches >= DEFAULT_THRESHOLDS.strong_touches:
        out.append(f"{level.touches} touches (T1.2)")
    if volume.measurable and (volume.is_spike or volume.is_dryup or "T2.3" in volume.rules):
        out.append("volume posture (T2)")
    if higher_tf_agrees:
        out.append("higher timeframe agrees (T3.3g)")
    if candle_bullish:
        out.append("rejection candle (T3.4b)")
    return out


def build_bounce_setup(
    symbol: str,
    bars: list[Bar],
    level: Level,
    volume: VolumeAssessment,
    *,
    next_resistance: Level | None = None,
    atr_value: float = 0.0,
    stop_atr: float | None = None,
    trend_direction: str | None = None,
    thresholds: Thresholds | None = None,
) -> Setup:
    """Setup A — buy the dip into support (spec §8).

    Entry sits *at* the level, not at the current price: T4.1 computes R:R from
    the level, and a price that has already run too far from it fails the R2
    gate rather than being chased. The stop goes below the chart's invalidating
    low (T4.3d), buffered by `stop_atr` (structure-timeframe ATR when the
    caller has one; falls back to `atr_value`).
    """
    t = thresholds or DEFAULT_THRESHOLDS
    entry = level.price
    # T4.3a/T4.3d — mental stop just below the invalidating low, volatility-aware.
    s_atr = stop_atr if stop_atr is not None else atr_value
    inv = invalidation_low(bars, entry, thresholds=t)
    stop = bounce_stop(entry, atr_value=s_atr, thresholds=t, invalidation=inv)
    risk = entry - stop

    targets = build_ladder(
        entry, "long",
        next_level=next_resistance.price if next_resistance else None,
    )
    gt = gate_target(targets, t)
    rr = risk_reward(entry, stop, gt.price) if gt else 0.0
    rr3 = risk_reward(entry, stop, targets[-1].price) if targets else 0.0

    rules = ["T1.2", "T4.1", "T4.2", "T4.3a", "T4.3d", "T4.4a", "T4.4b"]
    rules.extend(level.sources)
    rules.extend(volume.rules)

    no_trade: list[str] = []
    if volume.below_floor:
        no_trade.append("R3.1 volume below 50% of the time-of-day average")
    if not volume.measurable:
        no_trade.append("R3.1 volume could not be measured — no baseline to confirm against")
    if rr < t.min_risk_reward - 1e-9:
        no_trade.append(f"R2 reward:risk {rr:.2f} to {gate_label(t)} is below the {t.min_risk_reward:.1f} minimum")
    if level.touches < t.min_touches:
        no_trade.append(f"T1.2 level has only {level.touches} touch(es)")
    if risk > entry * t.max_stop_pct:
        no_trade.append(f"T4.3a/R1 the stop the chart justifies ({stop:.2f}) is "
                        f"{risk / entry:.1%} away — beyond the {t.max_stop_pct:.1%} cap")
    if trend_direction == "sideways" and atr_value > 0 and risk < t.chop_stop_atr * atr_value:
        no_trade.append(f"R3.2 stop {risk:.2f} sits inside the chop: trigger-timeframe trend is "
                        f"sideways and the stop is under {t.chop_stop_atr:.0f}x its ATR ({atr_value:.2f})")

    # A rejection wick at the level is the book's bullish tell (T3.4b) — a
    # confidence modifier, never a gate (T4.2: do not wait for confirmation).
    extra = 0.0
    labels = classify(bars, -1, thresholds=t)
    bullish_candle = "hammer" in labels or "bullish_engulfing" in labels
    if bullish_candle:
        rules.append("T3.4b")
        extra += 0.1
    conf = confluences(level, volume, candle_bullish=bullish_candle)
    if len(conf) >= 2:
        rules.append("T4.6")

    return Setup(
        symbol=symbol,
        setup_type="support_bounce",
        direction="long",
        entry=entry,
        entry_basis="at_level",
        requires_confirmation=False,
        stop=stop,
        stop_kind="mental",
        stop_reference="below_invalidation_low" if inv is not None else "below_support",
        targets=targets,
        risk_reward=rr,
        risk_reward_tp3=rr3,
        level_price=level.price,
        rules=sorted(set(rules)),
        no_trade_reasons=no_trade,
        confidence=_confidence(level, volume, extra),
        notes="Enter at the level; do not wait for confirmation (T4.2)."
              + (f" Confluence: {'; '.join(conf)}." if conf else ""),
    )


def build_breakout_setup(
    symbol: str,
    bars: list[Bar],
    level: Level,
    verdict: BreakoutVerdict,
    volume: VolumeAssessment,
    *,
    wedge: Wedge | None = None,
    thresholds: Thresholds | None = None,
    atr_value: float = 0.0,
    next_resistance: Level | None = None,
) -> Setup:
    """Setup B — breakout or falling-wedge break (spec §8).

    Confirmation is mandatory here: an unconfirmed break produces a setup carrying
    the fakeout reasons in `no_trade_reasons` rather than a tradeable plan.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    entry = level.price if wedge is None else max(level.price, bars[-1].close)

    if wedge is not None:
        # T3.1e — stop below the lowest point of the wedge, with the same
        # clearance every chart stop gets (never a bare per-mille of price).
        stop = wedge.lowest_price - stop_buffer(wedge.lowest_price, atr_value=atr_value, thresholds=t)
        stop_ref = "wedge_low"
        setup_type = "falling_wedge"
        measured = wedge.widest_height          # T3.1f
    else:
        # T4.3d — under the base the break launches from (most recent swing low
        # below the level), else under the level itself; buffered like a bounce.
        anchor = breakout_anchor(bars, level.price, thresholds=t)
        base = anchor if anchor is not None else level.price
        stop = base - stop_buffer(base, atr_value=atr_value, thresholds=t)
        stop_ref = "below_break_base" if anchor is not None else "below_broken_resistance"
        setup_type = "breakout"
        measured = None

    targets = build_ladder(entry, "long", measured_move=measured,
                           next_level=(next_resistance.price if next_resistance and measured is None else None))
    gt = gate_target(targets, t)
    rr = risk_reward(entry, stop, gt.price) if gt else 0.0
    rr3 = risk_reward(entry, stop, targets[-1].price) if targets else 0.0
    risk = entry - stop

    rules = ["T4.1", "T4.3a", "T4.4a", "T4.4b"]
    rules.extend(level.sources)
    rules.extend(verdict.rules)
    rules.extend(volume.rules)
    if wedge is not None:
        rules.extend(wedge.rules)
        rules.extend(["T3.1d", "T3.1e", "T3.1f"])

    no_trade: list[str] = []
    if verdict.is_fakeout:
        no_trade.extend(f"T3.3 fakeout: {r}" for r in verdict.reasons)
    if volume.below_floor:
        no_trade.append("R3.1 volume below 50% of the time-of-day average")
    if not volume.measurable:
        no_trade.append("R3.1 volume could not be measured — no baseline to confirm against")
    if rr < t.min_risk_reward - 1e-9:
        no_trade.append(f"R2 reward:risk {rr:.2f} to {gate_label(t)} is below the {t.min_risk_reward:.1f} minimum")
    if risk > entry * t.max_stop_pct:
        no_trade.append(f"T4.3a/R1 the stop the chart justifies ({stop:.2f}) is "
                        f"{risk / entry:.1%} away — beyond the {t.max_stop_pct:.1%} cap")

    conf = _confidence(level, volume, 0.15 if verdict.is_breakout else -0.25)

    return Setup(
        symbol=symbol,
        setup_type=setup_type,
        direction="long",
        entry=entry,
        entry_basis="on_break",
        requires_confirmation=True,
        stop=stop,
        stop_kind="mental",
        stop_reference=stop_ref,
        targets=targets,
        risk_reward=rr,
        risk_reward_tp3=rr3,
        level_price=level.price,
        rules=sorted(set(rules)),
        no_trade_reasons=no_trade,
        confidence=conf,
        notes="Breakout entry requires volume and a decisive candle (T3.3).",
    )
