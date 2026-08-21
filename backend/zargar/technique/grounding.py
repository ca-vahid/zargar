"""Grounding: verify every number in a TechniqueAnalysis against FACTS.

Same discipline as `signals/extraction.py::ground_signal` — the model proposes,
deterministic code disposes. A price is grounded only if it corresponds to
something real: a detected level, an actual bar extreme, or an arithmetic
derivation (measured move, pct ladder) from a grounded anchor.
"""
from __future__ import annotations

from .rulebook import RULES, DEFAULT_THRESHOLDS, Thresholds
from .schemas import TechniqueAnalysis
from .setups import LADDER_PCTS, risk_reward


def _tolerance(price: float, facts: dict, t: Thresholds) -> float:
    last = float(facts.get("lastClose") or price or 1.0)
    # Use the wider of pct tolerance and a fraction of the recent bar range.
    rows = (facts.get("bars") or {}).get(facts.get("primaryTf"), [])[-30:]
    rng = 0.0
    if rows:
        rng = sum(r[2] - r[3] for r in rows) / len(rows)
    return max(last * t.level_tolerance_pct * 2, rng * 0.35, 0.01)


def _anchor_prices(facts: dict) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for lv in facts.get("keyLevels") or []:
        out.append((float(lv["price"]), "level"))
    for tf, lvls in (facts.get("levels") or {}).items():
        for lv in lvls:
            out.append((float(lv["price"]), f"level:{tf}"))
    sess = facts.get("session") or {}
    for k in ("prev", "today"):
        blk = sess.get(k) or {}
        for kk in ("hod", "lod", "open", "close"):
            if kk in blk:
                out.append((float(blk[kk]), f"session:{k}.{kk}"))
    for tf, rows in (facts.get("bars") or {}).items():
        for r in rows[-200:]:
            out.append((float(r[2]), f"bar:{tf}.high"))
            out.append((float(r[3]), f"bar:{tf}.low"))
            out.append((float(r[4]), f"bar:{tf}.close"))
    for tf, w in (facts.get("wedge") or {}).items():
        if w:
            out.append((float(w["lowestPrice"]), f"wedge:{tf}.low"))
            out.append((float(w["breakoutLevelNow"]), f"wedge:{tf}.break"))
    return out


def _nearest(price: float, anchors: list[tuple[float, str]]) -> tuple[float, str]:
    best = min(anchors, key=lambda a: abs(a[0] - price)) if anchors else (price, "none")
    return abs(best[0] - price), best[1]


def ground_analysis(analysis: TechniqueAnalysis, facts: dict,
                    *, thresholds: Thresholds | None = None) -> dict:
    """Return {"passed", "checks": [...], "corrections": [...]}.

    `corrections` are human-readable hints handed back to the model on retry.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    checks: list[dict] = []
    corrections: list[str] = []
    anchors = _anchor_prices(facts)
    last = float(facts.get("lastClose") or 0.0)

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    # 1. rule ids exist
    bad_rules = [r for r in analysis.rules_fired if r not in RULES]
    check("rule_ids_valid", not bad_rules, f"unknown: {bad_rules}" if bad_rules else "")
    if bad_rules:
        corrections.append(f"Unknown rule ids {bad_rules}; use only ids from the rulebook.")

    # 2. every level the model names is a real level
    for lv in analysis.levels:
        tol = _tolerance(lv.price, facts, t)
        d, src = _nearest(lv.price, [a for a in anchors if a[1].startswith("level")])
        ok = d <= tol
        check(f"level_{lv.price:.2f}_grounded", ok,
              f"nearest {src} Δ{d:.3f} tol {tol:.3f}")
        if not ok:
            corrections.append(f"Level {lv.price:.2f} is not in the FACTS level list; "
                               f"pick the exact price of a listed level.")

    if analysis.verdict == "no_setup":
        check("no_setup_has_reasons", bool(analysis.no_trade_reasons),
              "no_setup must carry no_trade_reasons")
        passed = all(c["passed"] for c in checks)
        return {"passed": passed, "checks": checks, "corrections": corrections}

    # --- setup path ---------------------------------------------------------
    check("entry_present", analysis.entry is not None)
    check("stop_present", analysis.stop is not None)
    check("targets_present", len(analysis.targets) >= 1)
    if analysis.entry is None or analysis.stop is None or not analysis.targets:
        corrections.append("A setup verdict requires entry, stop, and at least one target.")
        return {"passed": False, "checks": checks, "corrections": corrections}

    e, s = analysis.entry.price, analysis.stop.price
    tol_e = _tolerance(e, facts, t)

    # entry must sit on a level or a bar price
    d, src = _nearest(e, anchors)
    check("entry_grounded", d <= tol_e, f"nearest {src} Δ{d:.3f} tol {tol_e:.3f}")
    if d > tol_e:
        corrections.append(f"Entry {e:.2f} does not correspond to any level or bar price in FACTS.")

    # stop: below entry for long; within a sane band below a grounded anchor
    check("stop_below_entry", s < e if analysis.direction == "long" else s > e)
    d_s, src_s = _nearest(s, anchors)
    stop_band = max(tol_e * 3, e * 0.01)
    check("stop_near_anchor", d_s <= stop_band, f"nearest {src_s} Δ{d_s:.3f} band {stop_band:.3f}")
    if d_s > stop_band:
        corrections.append(f"Stop {s:.2f} is far from any level/bar price; place it just beyond "
                           f"the invalidating level (T4.3a/T3.1e).")

    # targets: each grounded by level/bar, measured move, or pct ladder
    wedge_h = None
    for w in (facts.get("wedge") or {}).values():
        if w:
            wedge_h = float(w["widestHeight"])
    ladder = {round(e * (1 + p), 4) for p in LADDER_PCTS}
    ordered = True
    prev = e
    for i, tg in enumerate(analysis.targets):
        p = tg.price
        tol_t = _tolerance(p, facts, t)
        d_t, src_t = _nearest(p, anchors)
        ok = d_t <= tol_t
        why = f"nearest {src_t} Δ{d_t:.3f}"
        if not ok and tg.basis == "measured_move" and wedge_h:
            full = e + wedge_h
            ok = abs(p - full) <= tol_t or any(abs(p - (e + (full - e) * f)) <= tol_t
                                               for f in (0.4, 0.75, 1.0))
            why = f"measured move from {e:.2f}+{wedge_h:.2f}"
        if not ok and tg.basis == "pct_ladder":
            ok = any(abs(p - q) <= tol_t for q in ladder)
            why = "2/4/6% ladder"
        if not ok and tg.basis in ("next_resistance", "next_support"):
            # build_ladder() places TP1-3 at 40/75/100% of the way to the next
            # opposing level — those intermediate points are legitimate targets.
            opp = [a for a in anchors if a[1].startswith("level") and
                   ((a[0] > e) if analysis.direction == "long" else (a[0] < e))]
            for lvp, _src in opp:
                if any(abs(p - (e + (lvp - e) * f)) <= tol_t for f in (0.4, 0.75, 1.0)):
                    ok = True
                    why = f"ladder fraction toward level {lvp:.2f}"
                    break
        check(f"target{i + 1}_{p:.2f}_grounded", ok, why)
        if not ok:
            corrections.append(f"Target {p:.2f} is not a level, bar price, measured move, or "
                               f"ladder step; re-anchor it.")
        if (analysis.direction == "long" and p <= prev) or (analysis.direction == "short" and p >= prev):
            ordered = False
        prev = p
    check("targets_ordered", ordered, "targets must step away from entry")

    # R:R recomputed from the numbers, must match and clear R2
    rr = risk_reward(e, s, analysis.targets[-1].price)
    check("rr_matches", abs(rr - analysis.risk_reward) <= max(0.25, rr * 0.15),
          f"computed {rr:.2f} reported {analysis.risk_reward:.2f}")
    check("rr_meets_R2", rr >= t.min_risk_reward, f"{rr:.2f} vs {t.min_risk_reward}")
    if rr < t.min_risk_reward:
        corrections.append(f"R:R is {rr:.2f} (< {t.min_risk_reward}); either find a better entry/stop "
                           f"or return no_setup citing R2.")

    # volume floor is a hard gate
    vol = (facts.get("volume") or {}).get(facts.get("primaryTf")) or {}
    check("volume_not_below_floor", not vol.get("belowFloor"), str(vol.get("note", "")))
    if vol.get("belowFloor"):
        corrections.append("Volume is below the 50% floor (R3.1); a setup is not permitted.")

    # breakout setups need a confirmed break
    if analysis.setup_type in ("breakout", "falling_wedge"):
        bk = analysis.breakout
        confirmed = bk.observed and bk.verdict == "breakout"
        check("breakout_confirmed", confirmed, f"verdict={bk.verdict}")
        if not confirmed:
            corrections.append("Breakout-type setups require an observed, confirmed breakout "
                               "(T3.3a-c); otherwise use no_setup or a support bounce.")
        check("entry_requires_confirmation", analysis.entry.requires_confirmation,
              "breakout entries must be marked requires_confirmation")
    if analysis.setup_type == "support_bounce":
        check("bounce_enters_at_level", analysis.entry.basis == "at_level")
        # entry must be at/near current price zone to be actionable, else T4.1 expired
        if last:
            drift = (last - e) / e * 100
            check("bounce_not_chased", drift <= 1.0, f"price is {drift:.2f}% above the level")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "corrections": corrections}
