"""Tips v0.9 V2.2 / V3 / V4 (2026-10-05): the exit policy BY HORIZON - pure functions over the stamped exit plan.

Evidence (R3-horizon-exits.md, R4-external-evidence.md):
- a 3x daily-ATR stop at the SAME dollar risk beat the desk's ~1.15x-ATR stops in every cohort (V3.1);
- winners peak around session 7 and day-1 exits earn ~0R (V2.4: no same-day share plans);
- a 3x-ATR trail kept 51% of +2R runs vs 35% for a bare breakeven; 1/3 at +1R then a trail lifted the hit rate
  44% -> 57% at the same mean (V4.1-V4.4);
- stops checked on a short horizon cost return; judge on the CLOSE, keep an intrabar crash brake only (V3.2).

    short     stop 2x ATR; 1/2 at +1R; rest trails 2x ATR after +1R; time stop 3 sessions; judged on 15m closes
    swing     stop 3x ATR; 1/3 at +1R + breakeven WITH the partial; trail 3x ATR after +1R; time stop 10 sessions
              only while < +0.5R (the stale rule); 15m closes; crash brake 0.5R beyond the stop; promotion to
              extended at +2R by session 5 above the 20-day MA
    extended  stop 3x ATR; 1/3 at +1.5R + breakeven with it; trail 3x ATR after +1R judged on the DAILY close; time
              stop 20 sessions waived while above the 20-day MA; crash brake 0.5R

The analyst's own targets beyond the horizon's first target stay as extra trims, sharing what is left above a 1/3
runner that always rides the trail (V4.4 - no full exit at the last target). Every number is a techniques.tip.*
setting. Options keep their contract protections (premium stop, monetize, dte_close, the contract's hold cap).
"""
from __future__ import annotations

VERSION = "horizon-exits-v1"


def _g(settings, key: str, default: float) -> float:
    try:
        v = settings.get(f"techniques.tip.{key}", default)
        return float(default if v is None else v)
    except (TypeError, ValueError):
        return float(default)


def stop_atr_multiples(horizon: str | None, settings) -> tuple[float, float]:
    """(minimum, default) stop distance in daily ATRs for a horizon (V3.1): a declared stop narrower than the
    minimum is re-placed at the horizon's default; a wider one is kept (never tightened)."""
    h = horizon if horizon in ("short", "swing", "extended") else "swing"
    default = _g(settings, f"horizon_{h}_stop_atr", 2.0 if h == "short" else 3.0)
    minimum = min(_g(settings, "stop_atr_min", 2.0), default)
    return minimum, default


def ladder_spec(horizon: str, settings) -> tuple[float, float]:
    """(first target in R, fraction sold there)."""
    if horizon == "short":
        return _g(settings, "horizon_short_tp_r", 1.0), _g(settings, "horizon_short_tp_fraction", 0.5)
    if horizon == "extended":
        return _g(settings, "horizon_extended_tp_r", 1.5), _g(settings, "horizon_extended_tp_fraction", 1 / 3)
    return _g(settings, "horizon_swing_tp_r", 1.0), _g(settings, "horizon_swing_tp_fraction", 1 / 3)


def horizon_ladder(plan: dict, *, entry_ref: float, direction: str, settings) -> tuple[list[float], list[float]] | None:
    """Pure. The horizon ladder on the plan's FINAL stop: the first target at k R with its fraction, then the
    analyst's targets beyond it as extra trims sharing (1 - runner - first fraction). None = no stop / no R (the
    plan's own ladder stands)."""
    stop = plan.get("underlyingStop")
    h = plan.get("horizon")
    if stop is None or not entry_ref or h not in ("short", "swing", "extended"):
        return None
    sgn = -1.0 if direction == "short" else 1.0
    risk = sgn * (float(entry_ref) - float(stop))
    if risk <= 0:
        return None
    k, frac = ladder_spec(h, settings)
    base = round(float(entry_ref) + sgn * k * risk, 4)
    runner = max(0.0, min(1.0, _g(settings, "horizon_runner_fraction", 1 / 3)))
    frac = max(0.0, min(frac, 1.0 - runner))
    source = plan.get("analystTargets")
    if source is None:
        source = plan.get("targets") or []
    extras = sorted({round(float(t), 4) for t in source if t and sgn * (float(t) - base) > 1e-9},
                    key=lambda t: sgn * t)[:3]
    room = max(0.0, 1.0 - runner - frac)
    fr = [round(frac, 4)] + ([round(room / len(extras), 4)] * len(extras) if extras else [])
    return [base, *extras], fr


def with_horizon_ladder(plan: dict, *, entry_ref: float, direction: str, settings) -> dict:
    """The plan with its targets/fractions replaced by the horizon ladder (idempotent: the analyst's own targets are
    kept once under `analystTargets`). Unchanged when the horizon is not applied or the ladder is fixed."""
    if not plan.get("horizonApplied") or plan.get("ladderFixed") or plan.get("lotto"):
        return plan
    if plan.get("horizonLadderStop") is not None and plan.get("underlyingStop") is not None \
            and abs(float(plan["horizonLadderStop"]) - float(plan["underlyingStop"])) < 1e-9:
        return plan          # already built on THIS stop: a re-check never re-prices the ladder off a moving quote
    lad = horizon_ladder(plan, entry_ref=entry_ref, direction=direction, settings=settings)
    if lad is None:
        return plan
    out = dict(plan)
    if "analystTargets" not in out:
        out["analystTargets"] = list(plan.get("targets") or [])
    out["targets"], out["fractions"] = lad
    out["horizonLadderStop"] = float(plan["underlyingStop"])
    return out


def _trail(mult: float, atr: float | None, after_r: float) -> dict:
    if atr and atr > 0:
        return {"mode": "atr", "value": float(mult), "after_r": float(after_r), "atr_abs": round(float(atr), 4)}
    return {"mode": "structure", "after_r": float(after_r)}       # no daily ATR: the structure trail stands


def apply(policy: dict, plan: dict, *, is_option: bool, settings, entry_ref: float | None = None,
          direction: str = "long") -> dict:
    """Pure: the shared policy document reshaped by the plan's horizon. A plan without an APPLIED horizon (observe
    mode, a lotto, a non-Practice book, a legacy plan) returns the policy unchanged."""
    h = plan.get("horizon")
    if not plan.get("horizonApplied") or plan.get("lotto") or h not in ("short", "swing", "extended"):
        return policy
    out = dict(policy)
    out["horizon"] = h
    out["horizonVersion"] = VERSION
    if plan.get("horizonReason"):
        out["horizonReason"] = str(plan["horizonReason"])[:300]
    atr = float(plan.get("atrDaily") or 0) or None
    if atr:
        out["atrDaily"] = atr
    after_r = _g(settings, "horizon_trail_after_r", 1.0)
    brake = _g(settings, "horizon_brake_r", 0.5)
    min_hold = int(_g(settings, "min_share_hold_sessions", 2))
    cap = out.get("time_stop_sessions")                 # options: the contract's hold cap (never outlive it)
    if entry_ref and not plan.get("ladderFixed"):
        # the card's ladder stands while its stop does (the approved plan); a changed stop rebuilds it on the fill
        laddered = with_horizon_ladder(plan, entry_ref=float(entry_ref), direction=direction, settings=settings)
        if laddered is not plan and laddered.get("targets"):
            out["ladder"] = {"targets": list(laddered["targets"]), "fractions": list(laddered["fractions"])}
    for k in ("stale", "breakeven_after_r", "promote", "time_stop_unless_above_ma"):
        out.pop(k, None)
    if h == "short":
        out["timeframe"] = "15m"
        out["trailing"] = _trail(_g(settings, "horizon_short_trail_atr", 2.0), atr, after_r)
        n = int(_g(settings, "horizon_short_sessions", 3))
        out["time_stop_sessions"] = min(int(cap), n) if (is_option and cap) else max(min_hold, n)
        if bool(settings.get("techniques.tip.horizon_short_breakeven", False)):
            out["breakeven_on_trim"] = True
        return out
    out["breakeven_on_trim"] = True
    out["quote_brake_r"] = brake
    out["gap_exit"] = True
    if not is_option:
        out["venue_stop_beyond_r"] = brake
    ma = int(_g(settings, "horizon_extended_ma", 20))
    ext_n = int(_g(settings, "horizon_extended_sessions", 20))
    ext_trail = _trail(_g(settings, "horizon_extended_trail_atr", 3.0), atr, after_r)
    if h == "swing":
        out["timeframe"] = "15m"
        out["trailing"] = _trail(_g(settings, "horizon_swing_trail_atr", 3.0), atr, after_r)
        out["stale"] = {"sessions": int(_g(settings, "horizon_swing_sessions", 10)),
                        "min_r": _g(settings, "horizon_swing_stale_min_r", 0.5)}
        if not is_option:
            out.pop("time_stop_sessions", None)          # the stale rule IS the swing time stop (only below +0.5R)
        overlay: dict = {"timeframe": "1d", "stale": None, "trailing": ext_trail, "horizon": "extended"}
        if not is_option:
            overlay.update({"time_stop_sessions": ext_n, "time_stop_unless_above_ma": ma})
        out["promote"] = {"by_session": int(_g(settings, "horizon_promote_by_session", 5)),
                          "min_r": _g(settings, "horizon_promote_min_r", 2.0),
                          "above_ma": int(_g(settings, "horizon_promote_ma", 20)),
                          "label": "extended", "overlay": overlay}
        return out
    # extended
    out["timeframe"] = "1d"
    out["trailing"] = ext_trail
    if is_option:
        out["time_stop_sessions"] = cap or ext_n
    else:
        out["time_stop_sessions"] = ext_n
        out["time_stop_unless_above_ma"] = ma
    return out
