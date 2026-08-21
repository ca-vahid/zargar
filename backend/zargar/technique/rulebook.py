"""Rule identifiers and tunable thresholds for the EnhancedMarket technique.

Every rule id here maps 1:1 to a numbered rule in
`docs/TECHNIQUE-ENHANCEDMARKET.md`. Detection code, LLM prompts, and journal
events all cite these ids so a setup can always be explained after the fact.

Thresholds marked "gap" are places where the book gives no number (spec §10).
They live in `settings_service.DEFAULTS` under `technique.*` so they are
UI-editable and journaled on change, per the project's settings convention.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Rule catalogue --------------------------------------------------------
# id -> short human-readable statement. Kept terse: this text is injected into
# the system prompt and rendered in the UI next to each fired rule.

RULES: dict[str, str] = {
    # T1 — Support & resistance
    "T1.1": "Support stalls declines; resistance stalls advances.",
    "T1.2": "A level needs >=2 touches to be real; 3+ is strong.",
    "T1.3a": "Prior-day HOD/LOD levels are the strongest.",
    "T1.3b": "Previous day's support/resistance carries into today.",
    "T1.3c": "Intraday swing highs/lows with >=2 touches are levels.",
    "T1.3d": "Round numbers act as levels on their own.",
    "T1.5": "Trendlines: <=45 degrees, consistent anchoring, >=3 touches.",
    # T2 — Volume
    "T2.1": "Rising price + rising volume confirms the trend.",
    "T2.2": "Rising price + falling volume is bearish divergence.",
    "T2.3": "Falling price + falling volume means selling is exhausting.",
    "T2.4": "A volume spike after a long trend can mark a climax reversal.",
    "T2.5": "A breakout with a volume surge is genuine.",
    "T2.6": "A breakout on low volume is a fakeout warning.",
    "T2.7": "Large volume on small price movement signals institutional activity.",
    "T2.8": "Low volume in consolidation precedes a significant move.",
    "T2.9": "Volume is always judged against a time-of-day baseline.",
    # T3 — Patterns
    "T3.1a": "Falling wedge: lower highs and lower lows.",
    "T3.1b": "Falling wedge: converging lines, upper steeper than lower.",
    "T3.1c": "Falling wedge: volume decreases as it forms.",
    "T3.1d": "Falling wedge entry: decisive break above the upper trendline.",
    "T3.1e": "Falling wedge stop: below the lowest point of the wedge.",
    "T3.1f": "Falling wedge target: widest height projected from the breakout.",
    "T3.2": "Consolidation gives a tight stop and a high-probability entry.",
    "T3.3a": "True breakout: volume tapers into the level, then surges.",
    "T3.3b": "True breakout: large candle closing clearly beyond, minimal wicks.",
    "T3.3c": "True breakout: follow-through in the next few candles.",
    "T3.3d": "Fakeout: no volume behind the move.",
    "T3.3e": "Fakeout: quick reversal, long wick, closes back inside.",
    "T3.3f": "Fakeout: fails to hold the level it broke.",
    "T3.3g": "A lower-timeframe breakout may be a higher-timeframe fakeout.",
    "T3.4a": "Close near the high = buyers control; near the low = sellers.",
    "T3.4b": "Long wicks are rejection; lower wick bullish, upper bearish.",
    "T3.4c": "Dominant-colour candles grow larger in a strong trend.",
    "T3.4d": "Context overrides the individual candle.",
    "T3.5a": "Uptrend = higher highs and higher lows.",
    "T3.5b": "Downtrend = lower highs and lower lows.",
    # T4 — Entry / stop / targets
    "T4.1": "Enter at the level; compute R:R from the level, never chase.",
    "T4.2": "Do not wait for visual confirmation on a bounce entry.",
    "T4.3a": "Stop is mental, referenced just beyond the invalidating level.",
    "T4.3b": "On a stop touch, judge the reaction before exiting.",
    "T4.3c": "Averaging down requires a hard stop, not a mental one.",
    "T4.4a": "Scale out 30/40/15 with a 15% runner.",
    "T4.4b": "Never exit on P&L; exit on the chart.",
    "T4.5": "Average down only with a catalyst, with the trend, at support, preplanned.",
    # T5 — Options
    "T5.1": "Trade strikes just out of the money.",
    "T5.2": "Weeklies to current-week Friday; 0DTE with reduced size.",
    "T5.3": "Do not buy elevated IV — IV crush loses money on a correct call.",
    "T5.4": "Avoid wide spreads, inflated premium, high theta / low delta.",
    # R — Risk
    "R1": "Risk 0.5-1% per trade; 5% is the hard ceiling; never full-port.",
    "R2": "Require R:R >= 3.0.",
    "R3.1": "No trade when volume is below 50% of average.",
    "R3.2": "No trade in choppy action or after >2 false breakouts in the first hour.",
    "R3.3": "No trade on poor contract conditions.",
    "R3.4": "No trade on holidays, FOMC days, or major economic releases.",
    "R5": "One contract per trade while the technique is being validated.",
}


def rule(rid: str) -> str:
    """Text for a rule id. Raises on unknown ids so typos fail loudly."""
    return RULES[rid]


@dataclass(frozen=True)
class Thresholds:
    """Tunable numbers. Defaults are the spec §10 proposals (Q1-Q10)."""

    # Q1 — how close counts as a touch, as a fraction of price
    level_tolerance_pct: float = 0.0015
    # Q1b — alternative ATR-relative tolerance; the larger of the two wins
    level_tolerance_atr: float = 0.25
    # T1.2 — touches required for a level to be real / strong
    min_touches: int = 2
    strong_touches: int = 3
    # Swing pivot detection: bars either side that must be exceeded
    pivot_window: int = 3
    # Q3 — sessions of history to consider for level detection
    lookback_sessions: int = 3
    # Q4/Q5 — volume spike and dry-up, relative to time-of-day baseline
    volume_spike_mult: float = 1.5
    volume_dryup_mult: float = 0.7
    # R3.1 — no-trade floor
    volume_floor_mult: float = 0.5
    # Q6 — decisive candle: body share of range, and size vs recent average
    decisive_body_ratio: float = 0.60
    decisive_size_mult: float = 1.5
    # T3.3b — "minimal wicks": max share of range in the leading wick
    max_breakout_wick_ratio: float = 0.25
    # Q7 — follow-through: N of the next M bars continue
    followthrough_bars: int = 3
    followthrough_required: int = 2
    # Q8 — wedge minimums
    wedge_min_bars: int = 8
    wedge_min_touches: int = 2
    # T1.5 — trendline slope ceiling (45 degrees, as price-fraction per bar)
    max_trendline_slope_pct: float = 0.01
    # R2 — minimum acceptable reward:risk
    min_risk_reward: float = 3.0
    # R1 — position risk
    default_risk_pct: float = 1.0
    max_risk_pct: float = 5.0
    # T3.4b — long wick threshold, as share of candle range
    long_wick_ratio: float = 0.5
    # Round-number detection: treat multiples of these as psychological levels
    round_number_steps: tuple[float, ...] = (1.0, 5.0, 10.0, 50.0, 100.0)


DEFAULT_THRESHOLDS = Thresholds()


# Settings keys mirrored into settings_service.DEFAULTS so the UI can edit them.
SETTINGS_PREFIX = "technique."

def settings_defaults() -> dict[str, float | int | bool | str]:
    """Dot-key defaults to merge into `settings_service.DEFAULTS`."""
    t = DEFAULT_THRESHOLDS
    return {
        "technique.enabled": True,
        "technique.long_only": True,               # spec Q10
        "technique.level_tolerance_pct": t.level_tolerance_pct * 100,
        "technique.min_touches": t.min_touches,
        "technique.pivot_window": t.pivot_window,
        "technique.lookback_sessions": t.lookback_sessions,
        "technique.volume_spike_mult": t.volume_spike_mult,
        "technique.volume_dryup_mult": t.volume_dryup_mult,
        "technique.decisive_body_ratio": t.decisive_body_ratio,
        "technique.min_risk_reward": t.min_risk_reward,
        "technique.default_risk_pct": t.default_risk_pct,
        "technique.max_risk_pct": t.max_risk_pct,
        "technique.wedge_min_bars": t.wedge_min_bars,
    }


def thresholds_from_settings(get) -> Thresholds:
    """Build a Thresholds from a settings getter, falling back to defaults.

    `get` is `settings_service.get`-shaped: `get(key, default)`.
    """
    d = DEFAULT_THRESHOLDS
    return Thresholds(
        level_tolerance_pct=float(get("technique.level_tolerance_pct",
                                      d.level_tolerance_pct * 100)) / 100,
        level_tolerance_atr=d.level_tolerance_atr,
        min_touches=int(get("technique.min_touches", d.min_touches)),
        strong_touches=d.strong_touches,
        pivot_window=int(get("technique.pivot_window", d.pivot_window)),
        lookback_sessions=int(get("technique.lookback_sessions", d.lookback_sessions)),
        volume_spike_mult=float(get("technique.volume_spike_mult", d.volume_spike_mult)),
        volume_dryup_mult=float(get("technique.volume_dryup_mult", d.volume_dryup_mult)),
        volume_floor_mult=d.volume_floor_mult,
        decisive_body_ratio=float(get("technique.decisive_body_ratio", d.decisive_body_ratio)),
        decisive_size_mult=d.decisive_size_mult,
        max_breakout_wick_ratio=d.max_breakout_wick_ratio,
        followthrough_bars=d.followthrough_bars,
        followthrough_required=d.followthrough_required,
        wedge_min_bars=int(get("technique.wedge_min_bars", d.wedge_min_bars)),
        wedge_min_touches=d.wedge_min_touches,
        max_trendline_slope_pct=d.max_trendline_slope_pct,
        min_risk_reward=float(get("technique.min_risk_reward", d.min_risk_reward)),
        default_risk_pct=float(get("technique.default_risk_pct", d.default_risk_pct)),
        max_risk_pct=float(get("technique.max_risk_pct", d.max_risk_pct)),
        long_wick_ratio=d.long_wick_ratio,
        round_number_steps=d.round_number_steps,
    )
