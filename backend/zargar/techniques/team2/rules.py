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
    flag_tf_min: int = 5                    # C5: flags read on the 5-minute chart — NOT WIRED (no flag detector yet; PLAN §3c)
    fan_trend_min_atr: float = 0.60         # E4: EMA spread (max−min of the three) in 2m ATRs below which = chop
    atr_period: int = 14

    # --- L/B: levels and bias
    pm_tol_atr: float = 0.25                # Q5/D7: touch tolerance around PMH/PML (2m ATR multiples)
    zone_tol_atr: float = 0.0               # F27: a scenario needs a 15m close beyond the zone edge by this x ATR (0 = bare close)
    flip_body_ratio: float = 0.0            # F27: body/range a scenario-setting 15m candle must have (0 = any candle)
    target_lookback_sessions: int = 10      # L3.1: how far back to look for the last pivot beyond PDH/PDL
    range_day_confirmation: bool = True     # B3/A4: scenarios 2/3 need extra confirmation before a fire
    bias_flip_on_15m_close: bool = True     # D10: bias flips only on a 15m close through the zone the other way

    # --- T: entry
    pullback_max_touches: int = 2           # D9/P6: first two EMA13 touches after confirmation, third is watch-only
    pullback_max_bars: int = 8              # A6: a pullback longer than this is a new consolidation, not a dip
    pullback_reset_atr: float = 0.5         # F62: a new pullback needs a close this many ATRs off the EMA13 first (0 = every bar)
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
    stop_candles: int = 1                   # S2: consecutive 2m closes through the EMA/level before the candle stop fires (1 = since v0.1; 2 = RESEARCH arm H1, 2026-09-19)
    premium_stop_pct: float = 25.0          # D13/P1: hard cap on the premium loss (author ~20%)
    trim_1_pct: float = 50.0                # X1/V2: first trim at +50% premium
    trim_1_frac: float = 1.0 / 3.0
    trim_2_pct: float = 100.0               # V2: second trim at +100%
    trim_2_frac: float = 1.0 / 3.0
    runner_exit: str = "ema_close"          # X2: runner exits on a 2m close through the EMA13 — the only exit built; knob is informational
    target_exit: bool = True                # X3/V11: outright exit when the pre-planned target is touched
    hod_target: str = "reentry"             # X3b: "off" | "reentry" | "always" — the running HOD/LOD is the target
                                            #   when it is nearer than the planned level ("HOD resistance is the main
                                            #   target for longs until it breaks"); re-entries only by default
    hod_target_min_atr: float = 1.0         # X3b: the HOD/LOD must leave at least this much room (2m ATRs)
    target_replan_gap_only: bool = True     # F81b: the structure fallback applies on gap days only (the author's play is the gap/flip day)
    preopen_target_rederive: bool = True    # F81: at the pre-open/open, a planned target the gap has already run through is
                                            # re-derived from the MORNING's structure (PML/PMH, then the level ladder), the
                                            # author's own practice ("under the PML I have 291.19, then 289.98")
    target_replan: str = "off"              # F72 VARIANT: "off" | "entry" | "structure" (F81b: PM extreme -> ladder -> none). When a planned target is not ahead of
                                            #   the entry (a gap opened THROUGH the zone), re-derive it from the
                                            #   next structural level beyond CURRENT PRICE and re-validate it at
                                            #   the entry gate. "off" = the baseline: refuse the candidate.
                                            #   NOT recoverable by `hod_target="always"` — X3b's `nearer` test only
                                            #   ever pulls a target CLOSER, and a stale one is already closer.
    add_on_retest: bool = True              # X5 trim-and-add: after a trim, a fresh EMA13 hold re-fills the position
    max_adds: int = 1                       # X5: adds per position

    # --- V: expression (0DTE; D3)
    dte_policy: str = "0dte"                # "0dte" | "1dte" (sweep variant)
    target_premium: float = 0.60            # V1/F5: first OTM strike whose ask <= this
    premium_floor: float = 0.20             # never buy below this (the $0.05 lottery)
    premium_pick: str = "closest"           # F36: "closest" to target_premium (model AND live) | "first_under" (legacy)
    chase_cap_mult: float = 1.5             # F14: never pay more than target_premium x this for the contract (live ask)
    max_signal_age_min: int = 3             # R2 (2026-09-14): a fire whose bar close is older than this at DECISION time is stale — journaled, never sent
    key_levels: str = "off"                 # C2 (2026-09-13, research, OFF): off | D1 | D2 | D3 — multi-day key levels as entry levels
    no_trade_zone: str = "pm_range"         # C1 (2026-09-13, DISABLED): "pm_range" (V6 picture) | "conjunction" (B5: none only inside BOTH ranges)
    pm_room_atr: float = 0.0                # C1 obstacle rule (0 = off): refuse a non-pm_break entry inside the PM range whose PM boundary ahead is < this x ATR away (F15's case)
    min_target_atr: float = 0.0             # C3 (0 = off): refuse an entry whose target is nearer than this x ATR (Tue 09-08 QQQ: one strike away, fee-negative)
    strike_step: float = 1.0                # synthetic grid, used ONLY when the plan carries no chain listing (F104)
    quote_candidates: int = 8               # F105/F108: listed OTM contracts (nearest spot first) quoted live before a verdict
    require_fresh_quote: bool = True        # F108: a contract without a live NBBO is not eligible — defer, never fill on the delayed chain
    warmup_sessions: int = 12               # F99: valid prior sessions every path (live, replay, sweep) seeds the EMAs from

    # --- Z: sizing (V6/D4) and daily discipline (D14/D-3)
    size_full: float = 1.0
    size_small: float = 0.5
    size_none: float = 0.0
    max_reentries: int = 2                  # A8/T5
    max_losses_per_day: int = 2
    losses_desk_wide: bool = True           # F29: the loss cap counts SPY+QQQ+IWM together (one book), not per symbol
    max_concurrent_positions: int = 1       # A12
    shrink_after_win: bool = True           # P7: next-trade risk <= half the day's realised P&L after a win
    avoid_event_days: bool = False          # D-4: macro calendar flag (placeholder source)

    # --- costs (B4)
    fee_per_contract: float = 1.04          # Webull CA 0.99 + ~0.05 regulatory, per side
    slippage_ticks: int = 1                 # pay the ask + 1 tick, sell the bid − 1 tick
    tick: float = 0.01
    target_identity_guard: bool = True      # 2026-09-17: a destination must be distinct from the setup's source level (off = the pre-09-17 behaviour)
    target_collision: str = "refuse"        # RESEARCH arm E1 (2026-09-19): "refuse" (the 2026-09-17 rule) | "replan" (re-derive from the next structural level)

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
    "range_day_confirmation": "range_day_confirmation", "zone_tol_atr": "zone_tol_atr", "flip_body_ratio": "flip_body_ratio",
    "pullback_max_touches": "pullback_max_touches", "pullback_max_bars": "pullback_max_bars", "pullback_reset_atr": "pullback_reset_atr",
    "pullback_body_mult": "pullback_body_mult", "entry_at": "entry_at",
    "allow_ema48_entries": "allow_ema48_entries", "allow_ema200_flush": "allow_ema200_flush",
    "base_bars": "base_bars", "base_tol_atr": "base_tol_atr", "trim_cue": "trim_cue",
    "first_entry_min": "first_entry_min", "last_entry_min": "last_entry_min", "flatten_min": "flatten_min",
    "premium_stop_pct": "premium_stop_pct", "trim_1_pct": "trim_1_pct", "trim_1_frac": "trim_1_frac",
    "trim_2_pct": "trim_2_pct", "trim_2_frac": "trim_2_frac", "runner_exit": "runner_exit",
    "target_exit": "target_exit", "hod_target": "hod_target", "hod_target_min_atr": "hod_target_min_atr",
    "target_replan": "target_replan", "preopen_target_rederive": "preopen_target_rederive", "target_replan_gap_only": "target_replan_gap_only",
    "add_on_retest": "add_on_retest", "max_adds": "max_adds",
    "dte_policy": "dte_policy", "target_premium": "target_premium",
    "premium_floor": "premium_floor", "chase_cap_mult": "chase_cap_mult", "premium_pick": "premium_pick",
    "size_full": "size_full", "size_small": "size_small",
    "max_reentries": "max_reentries", "max_losses_per_day": "max_losses_per_day", "losses_desk_wide": "losses_desk_wide",
    "max_concurrent_positions": "max_concurrent_positions", "shrink_after_win": "shrink_after_win",
    "avoid_event_days": "avoid_event_days", "fee_per_contract": "fee_per_contract",
    "quote_candidates": "quote_candidates", "warmup_sessions": "warmup_sessions", "require_fresh_quote": "require_fresh_quote",
    "target_identity_guard": "target_identity_guard",
    "target_identity_guard": "target_identity_guard",
    "no_trade_zone": "no_trade_zone", "pm_room_atr": "pm_room_atr", "min_target_atr": "min_target_atr",
    "key_levels": "key_levels", "max_signal_age_min": "max_signal_age_min",
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


# --- parallel Practice experiments (2026-09-15, review team's GO; schema per the review of 41ec565) ----------------
# `techniques.team2.experiments` = {"enabled": bool, "control": <portfolioId>,
#                                   "books": [{"portfolioId", "label", "role": "sizing" | "c1", "overrides": {...}}]}
# One rule field per ROLE and nothing else: sizing -> size_full, c1 -> no_trade_zone. A book never carries both.
# The shared `techniques.team2.*` settings remain the baseline the Control and every unlisted book run on. An invalid
# configuration is invalid AS A WHOLE: nothing is applied, nothing is minted for an experiment, and the errors are
# reported (`validate_experiments`) — never silently filtered into a different experiment.
EXPERIMENT_ROLES = {"sizing": "size_full", "c1": "no_trade_zone"}
EXPERIMENT_OVERRIDE_KEYS = tuple(EXPERIMENT_ROLES.values())
_BOOK_KEYS = {"portfolioId", "label", "role", "overrides"}


def _valid_value(role: str, value) -> str | None:
    if role == "sizing":
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "size_full must be a number"
        return None if 0.0 < v < 1.0 else "size_full must be a cap strictly between 0 and 1 (the sizing experiment is 0.5)"
    if role == "c1":
        return None if value == "conjunction" else "no_trade_zone must be 'conjunction' for the C1 experiment"
    return "unknown role"


def validate_experiments(settings, *, portfolio_lookup=None) -> dict:
    """Validate the map. Returns {"enabled", "control", "books": [valid books], "errors": [...]}. When enabled, any
    error means the configuration is INVALID as a whole (callers apply nothing and report). `portfolio_lookup(pid)`
    (a dict with `kind`/`archived`, or None) enables the Practice-only / existence / archived checks."""
    exp = settings.get(SETTINGS_PREFIX + "experiments", None)
    out = {"enabled": False, "control": "", "books": [], "errors": []}
    if exp is None:
        return out
    if not isinstance(exp, dict):
        out["errors"].append("experiments must be an object"); return out
    out["enabled"] = bool(exp.get("enabled", False))
    out["control"] = str(exp.get("control") or "")
    if not out["enabled"]:
        return out
    errors = out["errors"]
    unknown_top = sorted(k for k in exp if k not in ("enabled", "control", "books"))
    if unknown_top:
        errors.append(f"unknown keys {unknown_top}")
    if not out["control"]:
        errors.append("control portfolioId is required while experiments are enabled")
    books = exp.get("books")
    if not isinstance(books, list) or not books:
        errors.append("books must be a non-empty list"); books = []
    seen_pid, seen_role, seen_label = set(), set(), set()
    valid: list[dict] = []
    for i, b in enumerate(books):
        tag = f"books[{i}]"
        if not isinstance(b, dict):
            errors.append(f"{tag}: must be an object"); continue
        unknown = sorted(k for k in b if k not in _BOOK_KEYS)
        if unknown:
            errors.append(f"{tag}: unknown keys {unknown}")
        pid = str(b.get("portfolioId") or ""); label = str(b.get("label") or ""); role = str(b.get("role") or "")
        ov = b.get("overrides")
        if not pid:
            errors.append(f"{tag}: portfolioId is required")
        if not label:
            errors.append(f"{tag}: label is required")
        if role not in EXPERIMENT_ROLES:
            errors.append(f"{tag}: role must be one of {sorted(EXPERIMENT_ROLES)}")
        if not isinstance(ov, dict) or not ov:
            errors.append(f"{tag}: overrides must be a non-empty object")
        else:
            keys = sorted(ov)
            if role in EXPERIMENT_ROLES and keys != [EXPERIMENT_ROLES[role]]:
                errors.append(f"{tag}: role {role} may override exactly {{{EXPERIMENT_ROLES[role]}}}, got {keys}")
            elif role in EXPERIMENT_ROLES:
                why = _valid_value(role, ov[EXPERIMENT_ROLES[role]])
                if why:
                    errors.append(f"{tag}: {why}")
            if set(keys) >= set(EXPERIMENT_OVERRIDE_KEYS):
                errors.append(f"{tag}: C1 and the sizing cap are never combined in one book")
        if pid and pid == out["control"]:
            errors.append(f"{tag}: the control book cannot also be an experiment")
        if pid in seen_pid:
            errors.append(f"{tag}: duplicate portfolioId {pid}")
        if role in seen_role:
            errors.append(f"{tag}: duplicate role {role}")
        if label in seen_label:
            errors.append(f"{tag}: duplicate label {label}")
        seen_pid.add(pid); seen_role.add(role); seen_label.add(label)
        if portfolio_lookup is not None and pid:
            pf = portfolio_lookup(pid)
            if pf is None:
                errors.append(f"{tag}: portfolio {pid} does not exist")
            else:
                if str(pf.get("kind")) != "sim":
                    errors.append(f"{tag}: portfolio {pid} is not a Practice (sim) book — never real money")
                if bool(pf.get("archived")):
                    errors.append(f"{tag}: portfolio {pid} is archived")
        valid.append({"portfolioId": pid, "label": label, "role": role,
                      "overrides": ({EXPERIMENT_ROLES[role]: ov[EXPERIMENT_ROLES[role]]} if role in EXPERIMENT_ROLES and isinstance(ov, dict)
                                    and EXPERIMENT_ROLES[role] in ov else {})})
    if portfolio_lookup is not None and out["control"]:
        pf = portfolio_lookup(out["control"])
        if pf is None:
            errors.append("control portfolio does not exist")
        elif str(pf.get("kind")) != "sim" or bool(pf.get("archived")):
            errors.append("control portfolio must be an unarchived Practice (sim) book")
    out["books"] = valid if not errors else []
    return out


def experiment_books(settings) -> list[dict]:
    """The enabled, VALID experiment books (role, label, the one override). Raises ValueError when the enabled map is
    invalid — an invalid configuration applies nothing anywhere."""
    v = validate_experiments(settings)
    if v["enabled"] and v["errors"]:
        raise ValueError("invalid techniques.team2.experiments: " + "; ".join(v["errors"]))
    return v["books"]


def experiment_for(settings, portfolio_id: str | None) -> dict | None:
    if not portfolio_id:
        return None
    try:
        return next((b for b in experiment_books(settings) if b["portfolioId"] == str(portfolio_id)), None)
    except ValueError:
        return None


def apply_overrides(base: Team2Rules, overrides: dict | None) -> Team2Rules:
    """The baseline plus WHITELISTED overrides (the frozen per-plan snapshot uses this — never the live map)."""
    ov = {k: v for k, v in (overrides or {}).items() if k in EXPERIMENT_OVERRIDE_KEYS}
    if not ov or set(ov) >= set(EXPERIMENT_OVERRIDE_KEYS):
        return base
    return Team2Rules.from_dict({**base.to_dict(), **ov})


def rules_for_book(settings, portfolio_id: str | None) -> Team2Rules:
    """The rules a NEW plan on this book is minted under: the shared baseline plus the book's validated override.
    A book without a (valid) experiment entry runs the baseline exactly."""
    base = rules_from_settings(settings)
    b = experiment_for(settings, portfolio_id)
    return apply_overrides(base, b["overrides"]) if b else base
