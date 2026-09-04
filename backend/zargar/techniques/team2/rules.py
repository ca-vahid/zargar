"""Team2Rules — every number the Team2 read/plan/simulation code is parameterised by.

A `MarketRules` superset (duck-compatible with the shared library) plus the method's own
knobs. Built ONCE per plan from settings (`rules_from_settings`) and snapshotted into the plan
run's `config.thresholds` so replay/outcome scoring use the numbers the plan was armed with
(BUILDING-A-TECHNIQUE §6). Rule ids in comments refer to `docs/techniques/team2/METHOD.md`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from ...marketstructure.rules import ALL_WINDOWS, MarketRules

SETTINGS_PREFIX = "techniques.team2."


@dataclass
class Team2Rules(MarketRules):
    # --- shared-library fields this method sets differently from EM
    volume_floor_mult: float = 0.0          # the method has no volume rule (C-modules never mention it)
    gap_void_r: float = 0.0                 # no gap-void rule; a gap is a day type (A1), not a void
    stop_on_close: bool = True              # S1: stops on the 2m CLOSE
    windows: tuple[str, ...] = ALL_WINDOWS  # no schedule rule (P2); the entry window below gates instead

    # --- E: EMA system (2m, extended hours on)
    ema_fast: int = 13
    ema_mid: int = 48
    ema_slow: int = 200
    entry_tf_min: int = 2                   # T1: entries on the 2-minute chart
    confirm_tf_min: int = 15                # C1: level breaks confirmed on the 15-minute close
    flag_tf_min: int = 5                    # C5: flags read on the 5-minute chart
    fan_trend_min_atr: float = 0.60         # E4: EMA spread (max−min of the three) in 2m ATRs below which = chop
    atr_period: int = 14

    # --- L/B: levels and bias
    pm_tol_atr: float = 0.25                # Q5/D7: touch tolerance around PMH/PML (2m ATR multiples)
    zone_tol_atr: float = 0.0               # PDH/PDL zones are their own tolerance (L1.2)
    target_lookback_sessions: int = 10      # L3.1: how far back to look for the last pivot beyond PDH/PDL
    range_day_confirmation: bool = True     # B3/A4: scenarios 2/3 need extra confirmation before a fire
    bias_flip_on_15m_close: bool = True     # D10: bias flips only on a 15m close through the zone the other way

    # --- T: entry
    pullback_max_touches: int = 2           # D9/P6: first two EMA13 touches after confirmation, third is watch-only
    pullback_max_bars: int = 8              # A6: a pullback longer than this is a new consolidation, not a dip
    pullback_body_mult: float = 2.0         # A6/F4: a bar with body > k×avg body INTO the EMA is an engulfing entry — skip
    entry_at: str = "both"                  # "ema" (T1) | "level" (T2 retest / T7 base) | "both"
    allow_ema48_entries: bool = True        # E5: the 48 EMA is the second line of defense — a deeper dip that holds
    allow_ema200_flush: bool = True         # T8: range-day trigger = a 2m close through the 200 EMA in the bias direction
    base_bars: int = 3                      # T7: N consecutive 2m bars holding just beyond the level = a "break & base"
    base_tol_atr: float = 1.0               # T7: how far beyond the level a base may sit (2m ATRs)
    trim_cue: str = "premium"               # X1: "premium" (+trim_1_pct) | "new_extreme" (first new HOD/LOD after entry)
    first_entry_min: int = 9 * 60 + 45      # D6: the first 15m close is 09:45
    last_entry_min: int = 15 * 60 + 30      # D6
    flatten_min: int = 15 * 60 + 45         # C3/D-1: everything closed by 15:45 (0DTE)
    early_flag_before_min: int = 10 * 60    # P2: fires before 10:00 tagged `early` (riskier, still taken)

    # --- S/X: stop and exits (premium terms per §7b; price cues per X1-X3)
    stop_candles: int = 1                   # S2: one 2m candle close through the EMA/level
    premium_stop_pct: float = 25.0          # D13/P1: hard cap on the premium loss (author ~20%)
    trim_1_pct: float = 50.0                # X1/V2: first trim at +50% premium
    trim_1_frac: float = 1.0 / 3.0
    trim_2_pct: float = 100.0               # V2: second trim at +100%
    trim_2_frac: float = 1.0 / 3.0
    runner_exit: str = "ema_close"          # X2: runner exits on a 2m close through the EMA13
    target_exit: bool = True                # X3/V11: outright exit when the pre-planned target is touched

    # --- V: expression (0DTE; D3)
    dte_policy: str = "0dte"                # "0dte" | "1dte" (sweep variant)
    target_premium: float = 0.60            # V1/F5: first OTM strike whose ask <= this
    premium_floor: float = 0.20             # never buy below this (the $0.05 lottery)
    strike_step: float = 1.0                # SPY/QQQ/IWM $1 strikes

    # --- Z: sizing (V6/D4) and daily discipline (D14/D-3)
    size_full: float = 1.0
    size_small: float = 0.5
    size_none: float = 0.0
    max_reentries: int = 2                  # A8/T5
    max_losses_per_day: int = 2
    max_concurrent_positions: int = 1       # A12
    shrink_after_win: bool = True           # P7: next-trade risk <= half the day's realised P&L after a win
    avoid_event_days: bool = False          # D-4: macro calendar flag (placeholder source)

    # --- costs (B4)
    fee_per_contract: float = 1.04          # Webull CA 0.99 + ~0.05 regulatory, per side
    slippage_ticks: int = 1                 # pay the ask + 1 tick, sell the bid − 1 tick
    tick: float = 0.01

    def to_dict(self) -> dict:
        d = asdict(self)
        d["windows"] = list(self.windows)
        d["round_number_steps"] = list(self.round_number_steps)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Team2Rules":
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in (d or {}).items() if k in names}
        if "windows" in kw:
            kw["windows"] = tuple(kw["windows"])
        if "round_number_steps" in kw:
            kw["round_number_steps"] = tuple(kw["round_number_steps"])
        return cls(**kw)


# settings key (without prefix) -> rules field; anything not listed is not UI-tunable
SETTINGS_MAP: dict[str, str] = {
    "ema_fast": "ema_fast", "ema_mid": "ema_mid", "ema_slow": "ema_slow",
    "fan_trend_min_atr": "fan_trend_min_atr", "pm_tol_atr": "pm_tol_atr",
    "target_lookback_sessions": "target_lookback_sessions",
    "range_day_confirmation": "range_day_confirmation",
    "pullback_max_touches": "pullback_max_touches", "pullback_max_bars": "pullback_max_bars",
    "pullback_body_mult": "pullback_body_mult", "entry_at": "entry_at",
    "allow_ema48_entries": "allow_ema48_entries", "allow_ema200_flush": "allow_ema200_flush",
    "base_bars": "base_bars", "base_tol_atr": "base_tol_atr", "trim_cue": "trim_cue",
    "first_entry_min": "first_entry_min", "last_entry_min": "last_entry_min", "flatten_min": "flatten_min",
    "premium_stop_pct": "premium_stop_pct", "trim_1_pct": "trim_1_pct", "trim_1_frac": "trim_1_frac",
    "trim_2_pct": "trim_2_pct", "trim_2_frac": "trim_2_frac", "runner_exit": "runner_exit",
    "target_exit": "target_exit", "dte_policy": "dte_policy", "target_premium": "target_premium",
    "premium_floor": "premium_floor", "size_full": "size_full", "size_small": "size_small",
    "max_reentries": "max_reentries", "max_losses_per_day": "max_losses_per_day",
    "max_concurrent_positions": "max_concurrent_positions", "shrink_after_win": "shrink_after_win",
    "avoid_event_days": "avoid_event_days", "fee_per_contract": "fee_per_contract",
}


def _hhmm_to_min(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    hh, mm = str(v).split(":")
    return int(hh) * 60 + int(mm)


def rules_from_settings(settings) -> Team2Rules:
    """Build the rules from `techniques.team2.*` (UI-editable; DEFAULTS in settings_service)."""
    r = Team2Rules()
    for key, fld in SETTINGS_MAP.items():
        v = settings.get(SETTINGS_PREFIX + key, None)
        if v is None:
            continue
        cur = getattr(r, fld)
        try:
            if fld in ("first_entry_min", "last_entry_min", "flatten_min"):
                v = _hhmm_to_min(v)
            elif isinstance(cur, bool):
                v = bool(v)
            elif isinstance(cur, int):
                v = int(v)
            elif isinstance(cur, float):
                v = float(v)
            else:
                v = str(v)
        except (TypeError, ValueError):
            continue
        setattr(r, fld, v)
    fee = settings.get("options.fee_per_contract", None)
    reg = settings.get("sim.reg_fee_per_contract", None)
    if fee is not None and settings.get(SETTINGS_PREFIX + "fee_per_contract", None) is None:
        r.fee_per_contract = float(fee) + float(reg or 0.0)
    return r


__all__ = ["Team2Rules", "rules_from_settings", "SETTINGS_MAP", "SETTINGS_PREFIX"]
