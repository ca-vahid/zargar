"""Volume analysis (spec module T2).

The book treats volume as the only confirmation instrument, and is specific that
it must be judged against a *time-of-day* baseline (T2.9, p. 63) — comparing the
09:35 bar to a flat all-day average would call every open a volume spike.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..domain import Bar
from .rules import DEFAULT_MARKET_RULES as DEFAULT_THRESHOLDS, MarketRules as Thresholds

__all__ = [
    "VolumeProfile", "VolumeAssessment", "build_profile",
    "assess_volume", "relative_volume", "volume_trend",
]


def _minute_of_day(ts_ms: int) -> int:
    dt = datetime.fromtimestamp(ts_ms / 1000, timezone.utc)
    return dt.hour * 60 + dt.minute


def _session(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


@dataclass
class VolumeProfile:
    """Per-minute-of-day average volume, built from prior sessions (T2.9)."""

    by_minute: dict[int, float] = field(default_factory=dict)
    overall: float = 0.0
    sessions: int = 0

    def baseline(self, ts_ms: int) -> float:
        """Expected volume for this time of day, falling back to the overall mean."""
        if not self.by_minute:
            return self.overall
        minute = _minute_of_day(ts_ms)
        if minute in self.by_minute:
            return self.by_minute[minute]
        # Nearest known minute — bar alignment differs across timeframes.
        nearest = min(self.by_minute, key=lambda m: abs(m - minute))
        if abs(nearest - minute) <= 15:
            return self.by_minute[nearest]
        return self.overall


def build_profile(bars: list[Bar], *, exclude_session: str | None = None) -> VolumeProfile:
    """Average volume per minute-of-day across the sessions present in `bars`.

    `exclude_session` drops the session under analysis so today's own volume does
    not contaminate the baseline it is being measured against.
    """
    buckets: dict[int, list[float]] = {}
    sessions: set[str] = set()
    total = 0.0
    count = 0
    for b in bars:
        sess = _session(b.ts)
        if exclude_session and sess == exclude_session:
            continue
        sessions.add(sess)
        buckets.setdefault(_minute_of_day(b.ts), []).append(float(b.volume))
        total += float(b.volume)
        count += 1
    return VolumeProfile(
        by_minute={m: sum(v) / len(v) for m, v in buckets.items() if v},
        overall=(total / count) if count else 0.0,
        sessions=len(sessions),
    )


def relative_volume(bar: Bar, profile: VolumeProfile) -> float:
    """Bar volume as a multiple of its time-of-day baseline. 0.0 if no baseline."""
    base = profile.baseline(bar.ts)
    return (float(bar.volume) / base) if base > 0 else 0.0


def volume_trend(bars: list[Bar]) -> str:
    """Direction of volume across a window: 'rising' | 'falling' | 'flat'.

    Compares the mean of the first and last thirds, which is robust to a single
    outlier bar in a way a first-vs-last comparison is not.
    """
    if len(bars) < 3:
        return "flat"
    third = max(1, len(bars) // 3)
    head = sum(float(b.volume) for b in bars[:third]) / third
    tail = sum(float(b.volume) for b in bars[-third:]) / third
    if head <= 0:
        return "flat"
    change = (tail - head) / head
    if change > 0.15:
        return "rising"
    if change < -0.15:
        return "falling"
    return "flat"


def price_trend(bars: list[Bar]) -> str:
    """Direction of price across a window: 'rising' | 'falling' | 'flat'."""
    if len(bars) < 2:
        return "flat"
    first, last = bars[0].close, bars[-1].close
    if first <= 0:
        return "flat"
    change = (last - first) / first
    if change > 0.001:
        return "rising"
    if change < -0.001:
        return "falling"
    return "flat"


@dataclass
class VolumeAssessment:
    """Verdict on what volume is saying about a window."""

    relative: float                 # reference bar vs time-of-day baseline
    trend: str                      # rising | falling | flat
    price_trend: str
    is_spike: bool
    is_dryup: bool
    below_floor: bool               # R3.1 no-trade condition
    rules: list[str] = field(default_factory=list)
    note: str = ""
    measurable: bool = True         # False when there was no usable volume data
    skipped_forming: bool = False   # True when a partial trailing bar was ignored

    def to_dict(self) -> dict:
        return {
            "relativeToTimeOfDayAvg": round(self.relative, 3),
            "trend": self.trend,
            "priceTrend": self.price_trend,
            "isSpike": self.is_spike,
            "isDryup": self.is_dryup,
            "belowFloor": self.below_floor,
            "measurable": self.measurable,
            "skippedFormingBar": self.skipped_forming,
            "rules": list(self.rules),
            "note": self.note,
        }


def assess_volume(
    bars: list[Bar],
    profile: VolumeProfile,
    *,
    thresholds: Thresholds | None = None,
) -> VolumeAssessment:
    """Apply the T2 rule table to a window of bars.

    Fires the divergence/confirmation rules (T2.1-T2.3), spike and dry-up
    detection (T2.4/T2.8), the institutional-activity tell (T2.7), and the
    R3.1 no-trade floor.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    if not bars:
        return VolumeAssessment(0.0, "flat", "flat", False, False, False,
                                [], "no bars", measurable=False)

    # The trailing bar is often still forming: its volume is partial or zero and
    # comparing it to a full-bar baseline would understate relative volume. Fall
    # back to the last bar that actually traded.
    idx = len(bars) - 1
    skipped = False
    while idx >= 0 and bars[idx].volume <= 0:
        idx -= 1
        skipped = True
    if idx < 0:
        return VolumeAssessment(0.0, volume_trend(bars), price_trend(bars),
                                False, False, False, ["T2.9"],
                                "no volume data in window", measurable=False)

    last = bars[idx]
    rel = relative_volume(last, profile)
    measurable = rel > 0
    vtrend = volume_trend(bars)
    ptrend = price_trend(bars)
    rules: list[str] = ["T2.9"]

    is_spike = measurable and rel >= t.volume_spike_mult
    is_dryup = measurable and rel <= t.volume_dryup_mult
    below_floor = measurable and rel < t.volume_floor_mult

    if ptrend == "rising" and vtrend == "rising":
        rules.append("T2.1")
        note = "Volume is confirming the advance."
    elif ptrend == "rising" and vtrend == "falling":
        rules.append("T2.2")
        note = "Bearish divergence: price up, volume down."
    elif ptrend == "falling" and vtrend == "falling":
        rules.append("T2.3")
        note = "Selling pressure is exhausting."
    elif ptrend == "flat" and is_dryup:
        rules.append("T2.8")
        note = "Quiet consolidation — often precedes a move."
    else:
        note = "No clear volume/price relationship."

    if is_spike:
        rules.append("T2.4")
    # Large volume, small move (T2.7): high relative volume with a tight range.
    rng = last.high - last.low
    window = bars[max(0, idx - 19):idx + 1]
    avg_rng = sum(b.high - b.low for b in window) / len(window)
    if is_spike and avg_rng > 0 and rng < avg_rng * 0.6:
        rules.append("T2.7")
        note = "Heavy volume on a small range — possible institutional activity."
    if below_floor:
        rules.append("R3.1")
        note = "Volume below the no-trade floor."

    if not measurable:
        note = "No volume baseline available — volume rules cannot be applied."

    return VolumeAssessment(
        relative=rel,
        trend=vtrend,
        price_trend=ptrend,
        is_spike=is_spike,
        is_dryup=is_dryup,
        below_floor=below_floor,
        rules=rules,
        note=note,
        measurable=measurable,
        skipped_forming=skipped,
    )
