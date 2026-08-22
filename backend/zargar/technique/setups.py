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
    risk_reward: float = 0.0
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


def bounce_stop(level_price: float, *, atr_value: float = 0.0,
                thresholds: Thresholds | None = None) -> float:
    """T4.3a/T4.3d — the mental stop sits *just below the level*: the book's own
    example is $98 support -> watch ~$97.50 (0.5%), and it rejects fixed-percent
    stops that ignore the chart. The buffer is the larger of that percent, two
    touch tolerances, and an ATR multiple, so it scales with volatility."""
    t = thresholds or DEFAULT_THRESHOLDS
    tol = max(level_price * t.level_tolerance_pct, 1e-9)
    return level_price - max(tol * 2, level_price * t.bounce_stop_pct, atr_value * t.stop_buffer_atr)


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
    thresholds: Thresholds | None = None,
) -> Setup:
    """Setup A — buy the dip into support (spec §8).

    Entry sits *at* the level, not at the current price: T4.1 computes R:R from
    the level, and a price that has already run too far from it fails the R2
    gate rather than being chased.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    entry = level.price
    # T4.3a/T4.3d — mental stop just below the level, volatility-aware.
    stop = bounce_stop(entry, atr_value=atr_value, thresholds=t)

    targets = build_ladder(
        entry, "long",
        next_level=next_resistance.price if next_resistance else None,
    )
    rr = risk_reward(entry, stop, targets[-1].price) if targets else 0.0

    rules = ["T1.2", "T4.1", "T4.2", "T4.3a", "T4.3d", "T4.4a", "T4.4b"]
    rules.extend(level.sources)
    rules.extend(volume.rules)

    no_trade: list[str] = []
    if volume.below_floor:
        no_trade.append("R3.1 volume below 50% of the time-of-day average")
    if not volume.measurable:
        no_trade.append("R3.1 volume could not be measured — no baseline to confirm against")
    if rr < t.min_risk_reward:
        no_trade.append(f"R2 reward:risk {rr:.2f} is below the {t.min_risk_reward:.1f} minimum")
    if level.touches < t.min_touches:
        no_trade.append(f"T1.2 level has only {level.touches} touch(es)")

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
        stop_reference="below_support",
        targets=targets,
        risk_reward=rr,
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
) -> Setup:
    """Setup B — breakout or falling-wedge break (spec §8).

    Confirmation is mandatory here: an unconfirmed break produces a setup carrying
    the fakeout reasons in `no_trade_reasons` rather than a tradeable plan.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    entry = level.price if wedge is None else max(level.price, bars[-1].close)

    if wedge is not None:
        # T3.1e — stop below the lowest point of the wedge.
        stop = wedge.lowest_price - max(entry * 0.001, 1e-9)
        stop_ref = "wedge_low"
        setup_type = "falling_wedge"
        measured = wedge.widest_height          # T3.1f
    else:
        stop = level.price - max(entry * 0.005, 1e-9)
        stop_ref = "below_broken_resistance"
        setup_type = "breakout"
        measured = None

    targets = build_ladder(entry, "long", measured_move=measured)
    rr = risk_reward(entry, stop, targets[-1].price) if targets else 0.0

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
    if rr < t.min_risk_reward:
        no_trade.append(f"R2 reward:risk {rr:.2f} is below the {t.min_risk_reward:.1f} minimum")

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
        level_price=level.price,
        rules=sorted(set(rules)),
        no_trade_reasons=no_trade,
        confidence=conf,
        notes="Breakout entry requires volume and a decisive candle (T3.3).",
    )
