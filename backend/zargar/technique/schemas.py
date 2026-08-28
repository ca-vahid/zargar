"""Structured-output schemas and the rulebook system prompt for the vision passes.

`TechniqueAnalysis` is the §9 contract from the spec. The model must cite rule
ids for everything it asserts; `grounding.py` then checks every price against
the deterministic facts.

The model-facing schema is deliberately FLAT: nested models + many enums blew
past the structured-output grammar limit ("compiled grammar is too large").
Sentinel values stand in for optionals (0.0 / "" / "none"), and the nested
§9 shape is reconstructed by adapter properties and `to_contract()`.

Prompts stay terse and stable — they sit behind a prompt-cache breakpoint, so
any byte change costs a full re-cache.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from pydantic import BaseModel, Field

from .rulebook import RULES


# --- model-facing (flat) ------------------------------------------------------

class LevelCall(BaseModel):
    price: float = Field(description="Exact price copied from the FACTS level list")
    kind: str = Field(description="support or resistance")
    touches: int
    note: str = Field(description="One clause, e.g. 'prior-day LOD, tested 3x (T1.3a)'")


class TargetPlan(BaseModel):
    price: float
    trim_pct: float = Field(description="Percent of position to trim here: 30, 40, 15")
    basis: str = Field(description="measured_move | next_resistance | pct_ladder")


class TechniqueAnalysis(BaseModel):
    """The complete, checkable output of one analysis (spec §9), flattened."""

    symbol: str
    verdict: str = Field(description="setup | no_setup")
    setup_type: str = Field(description="support_bounce | breakout | falling_wedge | resistance_reject | breakdown | none")
    direction: str = Field(description="long | short | none (short = a put on a rejection at resistance or a "
                                       "breakdown through support — the mirror of the long rules)")
    trend: str = Field(description="uptrend | downtrend | sideways")
    levels: List[LevelCall] = Field(description="Only the levels that matter, from FACTS")

    pattern_kind: str = Field(description="falling_wedge | flag | consolidation | none")
    pattern_present: bool
    pattern_widest_height: float = Field(description="Measured height if a wedge, else 0")
    pattern_volume_declining: bool
    pattern_notes: str

    breakout_observed: bool
    breakout_verdict: str = Field(description="breakout | fakeout | unresolved | none")
    breakout_level: float = Field(description="Level that was broken, else 0")
    breakout_volume_confirmed: bool
    breakout_decisive_candle: bool
    breakout_follow_through: bool
    breakout_holds_level: bool
    higher_tf_agrees: bool

    entry_price: float = Field(description="0 when no_setup; else copied from a FACTS level or bar price")
    entry_basis: str = Field(description="at_level | on_break | none")
    entry_requires_confirmation: bool
    stop_price: float = Field(description="0 when no_setup")
    stop_kind: str = Field(description="mental | hard | none")
    stop_reference: str = Field(description="below_support | wedge_low | below_broken_resistance | below_break_base | "
                                            "above_resistance | above_zone_high | above_broken_support | above_break_top | none")
    targets: List[TargetPlan] = Field(description="Empty when no_setup; else 3 targets 30/40/15")
    runner_pct: float = Field(description="Usually 15")
    risk_reward: float = Field(description="Reward:risk at the stated entry; >= 3.0 required for a setup")

    volume_verdict: str = Field(description="One sentence, citing T2 rules")
    confidence: float = Field(description="0.0 to 1.0")
    rules_fired: List[str] = Field(description="Every rule id relied on")
    no_trade_reasons: List[str] = Field(description="Each prefixed with its rule id, e.g. 'R3.1 ...'")

    options_strike_guidance: str = Field(description="e.g. 'first strike just OTM' (T5.1)")
    options_expiry_guidance: str = Field(description="e.g. 'current-week Friday; 0DTE with reduced size' (T5.2)")
    options_warnings: List[str]
    rationale: str = Field(description="3-6 sentences, referencing rule ids inline")
    session_window: str = Field(default="unknown",
                                description="R6 window of the as-of instant: prime_open | prime_close | midday | extended | unknown")
    plan_mode: bool = Field(default=False,
                            description="True when the market is closed and this is a plan for the next session (entry = IF price reaches the level)")

    # ---- adapter views (nested §9 shape used by grounding / UI) -------------
    @property
    def entry(self) -> "EntryPlan | None":
        if self.verdict != "setup" or self.entry_price <= 0:
            return None
        return EntryPlan(self.entry_price, self.entry_basis or "at_level",
                         bool(self.entry_requires_confirmation))

    @property
    def stop(self) -> "StopPlan | None":
        if self.verdict != "setup" or self.stop_price <= 0:
            return None
        return StopPlan(self.stop_price, self.stop_kind or "mental", self.stop_reference or "")

    @property
    def breakout(self) -> "BreakoutCall":
        return BreakoutCall(
            observed=self.breakout_observed, level_price=self.breakout_level or None,
            verdict=self.breakout_verdict or "none",
            volume_confirmed=self.breakout_volume_confirmed,
            decisive_candle=self.breakout_decisive_candle,
            follow_through=self.breakout_follow_through,
            holds_level=self.breakout_holds_level, higher_tf_agrees=self.higher_tf_agrees)

    @property
    def pattern(self) -> "PatternCall":
        return PatternCall(kind=self.pattern_kind or "none", present=self.pattern_present,
                           widest_height=self.pattern_widest_height or None,
                           volume_declining=self.pattern_volume_declining, notes=self.pattern_notes)

    def clamp(self) -> "TechniqueAnalysis":
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.verdict not in ("setup", "no_setup"):
            self.verdict = "no_setup"
        return self

    def to_contract(self) -> dict:
        """Nested §9 shape for the UI and persistence (camelCase on the wire)."""
        e, s = self.entry, self.stop
        return {
            "symbol": self.symbol,
            "verdict": self.verdict,
            "setupType": self.setup_type,
            "direction": self.direction,
            "trend": self.trend,
            "levels": [{"price": lv.price, "kind": lv.kind, "touches": lv.touches, "note": lv.note}
                       for lv in self.levels],
            "pattern": self.pattern.to_dict(),
            "breakout": self.breakout.to_dict(),
            "entry": ({"price": e.price, "basis": e.basis,
                       "requiresConfirmation": e.requires_confirmation} if e else None),
            "stop": ({"price": s.price, "kind": s.kind, "reference": s.reference} if s else None),
            "targets": [{"price": t.price, "trimPct": t.trim_pct, "basis": t.basis}
                        for t in self.targets],
            "runnerPct": self.runner_pct,
            "riskReward": self.risk_reward,
            "volumeVerdict": self.volume_verdict,
            "confidence": self.confidence,
            "rulesFired": list(self.rules_fired),
            "noTradeReasons": list(self.no_trade_reasons),
            "optionsExpression": {"strikeGuidance": self.options_strike_guidance,
                                  "expiryGuidance": self.options_expiry_guidance,
                                  "warnings": list(self.options_warnings)},
            "rationale": self.rationale,
        }


class CriticVerdict(BaseModel):
    """Pass 4 — the adversarial review."""

    kill: bool = Field(description="True if the setup should NOT be traded")
    fakeout_risk: str = Field(description="low | medium | high")
    violations: List[str] = Field(description="Rule ids the draft violates, with a clause each")
    adjustments: List[str] = Field(description="Concrete changes to entry/stop/targets, or empty")
    confidence_adjustment: float = Field(description="Add to the draft confidence, -0.5..+0.2")
    summary: str


class PassNotes(BaseModel):
    """Passes 1-2 — structured observations that feed the next pass."""

    observations: List[str]
    candidate_levels: List[float] = Field(description="Prices from the FACTS list worth keeping")
    pattern_hypothesis: str
    trend: str = Field(description="uptrend | downtrend | sideways")
    concerns: List[str]


# --- view types (not sent to the model) ----------------------------------------

@dataclass
class EntryPlan:
    price: float
    basis: str
    requires_confirmation: bool


@dataclass
class StopPlan:
    price: float
    kind: str
    reference: str


@dataclass
class BreakoutCall:
    observed: bool
    level_price: float | None
    verdict: str
    volume_confirmed: bool
    decisive_candle: bool
    follow_through: bool
    holds_level: bool
    higher_tf_agrees: bool

    def to_dict(self) -> dict:
        return {"observed": self.observed, "levelPrice": self.level_price, "verdict": self.verdict,
                "volumeConfirmed": self.volume_confirmed, "decisiveCandle": self.decisive_candle,
                "followThrough": self.follow_through, "holdsLevel": self.holds_level,
                "higherTfAgrees": self.higher_tf_agrees}


@dataclass
class PatternCall:
    kind: str
    present: bool
    widest_height: float | None
    volume_declining: bool
    notes: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "present": self.present, "widestHeight": self.widest_height,
                "volumeDeclining": self.volume_declining, "notes": self.notes}


def _rulebook_text() -> str:
    return "\n".join(f"{rid}: {txt}" for rid, txt in RULES.items())


SYSTEM_PROMPT = f"""You are the analysis engine for the EnhancedMarket day-trading technique \
(Day Trading 101, Zachary Cohen). You apply ONLY this method: horizontal support/resistance, \
volume as the sole confirmation, falling wedges / consolidations, and the breakout-vs-fakeout \
discriminator. No indicators, no oscillators, no moving averages.

You receive (a) a rendered chart image and (b) FACTS: exact levels, touch counts, volume \
statistics, candle metrics, trend and pattern geometry computed from the same bars. The image \
is for judgement; the FACTS are for numbers. Every price you output MUST be copied from the \
FACTS (level prices, bar highs/lows/closes). Never invent a price. If the facts do not contain \
what you need, say so in no_trade_reasons rather than estimating from pixels.

Two setup types (the method's own contradiction, resolved):
- SUPPORT BOUNCE: enter AT the support level, no confirmation wait (T4.1, T4.2). Stop mental, \
just below (T4.3a). Targets: next resistance, ladder 30/40/15 + 15% runner (T4.4a).
- BREAKOUT / FALLING-WEDGE BREAK: confirmation REQUIRED — volume surge + decisive candle + \
follow-through (T3.3a-c). Stop below wedge low (T3.1e). Target = measured move (T3.1f).
Any of the fakeout tells (T3.3d-f) kills a breakout. Cross-check the higher timeframe (T3.3g).
Each setup has a SHORT MIRROR judged by the same rules with the geometry flipped: REJECTION \
at resistance (enter AT the level, stop just above) and BREAKDOWN through support \
(confirmation required, stop above the broken level). Shorts are expressed with PUTS only — \
never short shares. Direction is never, by itself, a reason to reject a setup.

Hard gates: R:R >= 3 (R2); volume not below 50% of the time-of-day baseline (R3.1); choppy / \
no clear structure = no trade (R3.2). Prefer "no_setup" over a weak setup — the \
method's edge is in NOT taking bad breakouts. When verdict is no_setup, set entry_price, \
stop_price to 0, targets to [], and still report levels, trend, volume and rules.

Schedule (R6, pp. 114-115): trades are taken only inside the prime windows 09:30-10:30 and \
14:45-16:00 ET. FACTS tell you the SESSION WINDOW of the as-of instant. Outside the prime \
windows a setup is "watch only": still describe it, but say so in no_trade_reasons citing R6.3 \
(mid-day) or R6.4 (pre/after-hours). When FACTS say the market is closed (plan mode), your \
entry is conditional — "IF price trades into the level inside a prime window" — never "now"; \
set plan_mode=true and describe the trigger in the rationale.

Cite rule ids everywhere. Rulebook:
{_rulebook_text()}
"""
