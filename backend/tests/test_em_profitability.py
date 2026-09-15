"""Profitability cohorts (reviewers' P-01..P-03, frozen 2026-09-15 as profitability-cohorts-v1): pure definitions and
the order-free per-session report. No DB, no engine, no network, no orders."""
from zargar.tools.em_profitability import (COHORT_P01, P02_POLICY, VERSION, affordable_qty, cohort_of, confirmation_class,
                                           friction, p02_compare, p02_eligible, payoff_to_tp1, render, room_bin, room_r,
                                           summarize, underlying_proxy)


def test_p01_membership_is_long_bounce_with_saved_next_resistance_target():
    assert VERSION == "profitability-cohorts-v1"
    assert cohort_of("bounce", "long", "next_resistance") == COHORT_P01
    assert cohort_of("bounce", "long", "pct_ladder") is None          # percentage-target bounces are baseline only
    assert cohort_of("reject", "short", "next_support") is None      # other families are never switched off, only not in the cohort
    assert cohort_of("breakout", "long", "next_resistance") is None


def test_strata_definitions_are_deterministic():
    assert confirmation_class(78.40, 78.49, "long") == "anticipated"           # NFLX 09-15: the firing bar closed under the level
    assert confirmation_class(141.2, 141.01, "long") == "observed_reclaim"
    assert confirmation_class(149.5, 149.78, "short") == "observed_reclaim"
    assert confirmation_class(None, 1.0, "long") == "unknown"
    assert room_r(141.01, 140.1661, 142.738, "long") == 2.048 and room_bin(2.048) == "1-3R"
    assert room_bin(0.5) == "<1R" and room_bin(3.0) == ">=3R" and room_bin(-0.2) == "behind" and room_bin(None) == "unknown"
    assert room_r(100.0, 100.0, 101.0, "long") is None


def test_p03_friction_and_payoff_keep_unknowns_unknown():
    f = friction(1.49, 1.36, 2, 100.0, 1.04)                                  # CVNA 09-15: concession 26 + fees 4.16 on 298 premium
    assert f["concession"] == 26.0 and f["fees"] == 4.16 and f["total"] == 30.16 and f["pctOfPremium"] == 0.1012 and f["known"]
    assert friction(1.49, None, 2, 100.0, 1.04)["known"] is False
    assert friction(34.77, 34.70, 100, 1.0, 1.04)["fees"] == 0.0                # shares: no per-contract fee on this book
    assert payoff_to_tp1(0.0, 141.01, 142.738, 1) is None                      # stored delta 0.0 = unknown, never zero payoff
    assert payoff_to_tp1(0.45, 141.01, 142.738, 1) == 77.76
    assert affordable_qty(204.0, 1.46, 50.0) == 2 and affordable_qty(204.0, 4.90, 50.0) == 0


def test_p02_alternative_counts_forgone_profit_on_a_winner_and_stays_unknown_without_evidence():
    assert p02_eligible("options", 2, 5.196) and p02_eligible("options", 1, 3.8)
    assert not p02_eligible("options", 3, 5.0) and not p02_eligible("options", 2, 1.5) and not p02_eligible("shares", 1, 5.0)
    trade = {"filledQty": 2, "avgFill": 1.00, "multiplier": 100.0, "productionRealized": 225.84, "productionPerContract": [112.92, 112.92]}
    # no covered observation -> unknown, never a candle high
    assert p02_compare(trade, [{"rung": "tp1-candidate", "disposition": "observed", "bid": 1.5}], 1.04)["outcome"] == "unknown"
    # a covered executable bid at the TP1 touch: sell ONE at 1.30, keep the other on production (INTC-like big winner)
    r = p02_compare(trade, [{"rung": "tp1-candidate", "disposition": "covered", "bid": 1.30, "observedTs": 5}], 1.04)
    assert r["policy"] == P02_POLICY and r["outcome"] == "compared" and r["soldByAlternative"] == 1
    assert r["alternativeRealized"] == round((1.30 - 1.00) * 100 - 2 * 1.04 + 112.92, 2)
    assert r["delta"] == round(r["alternativeRealized"] - 225.84, 2) and r["delta"] < 0
    assert r["forgoneOnWinner"] == round(112.92 - ((1.30 - 1.00) * 100 - 2 * 1.04), 2)      # profit sacrificed on the big winner
    # one contract: the whole position leaves at the observation
    one = {"filledQty": 1, "avgFill": 2.96, "multiplier": 100.0, "productionRealized": -40.0, "productionPerContract": [-40.0]}
    r1 = p02_compare(one, [{"rung": "tp1-candidate", "disposition": "covered", "bid": 3.40, "observedTs": 9}], 1.04)
    assert r1["soldByAlternative"] == 1 and r1["alternativeRealized"] == round(44.0 - 2.08, 2) and r1["forgoneOnWinner"] == 0.0
    # still open -> partial
    assert p02_compare({**trade, "productionRealized": None}, [{"rung": "tp1-candidate", "disposition": "covered", "bid": 1.3}], 1.04)["outcome"] == "partial"


def test_underlying_proxy_orders_events_and_flags_gaps():
    day = 1_789_479_000_000
    bars = [{"ts": day + i * 60000, "open": 100, "high": 100.5, "low": 99.5, "close": 100.0} for i in range(10)]
    bars[5]["high"] = 102.5
    assert underlying_proxy(bars, day, 100.0, 99.0, 102.0, "long", day + 20 * 60000) == "tp1_first"
    bars[3]["close"] = 98.9
    assert underlying_proxy(bars, day, 100.0, 99.0, 102.0, "long", day + 20 * 60000) == "stop_first"
    gap = [b for b in bars if b["ts"] != day + 2 * 60000]
    assert underlying_proxy(gap, day, 100.0, 99.0, 102.0, "long", day + 20 * 60000) == "unknown (bar gap)"
    assert underlying_proxy(bars[:2], day, 100.0, 99.0, 102.0, "long", day + 20 * 60000) == "unresolved"


def test_report_keeps_baseline_beside_the_cohort_and_lists_removed_and_missed():
    fill = {"symbol": "ORCL", "trigger": "b2", "kind": "bounce", "direction": "long", "cohort": COHORT_P01, "firstTargetBasis": "next_resistance",
            "confirmation": "observed_reclaim", "sourceAligned": False, "closed": True, "netRealized": 40.0, "filledQty": 1.0, "roomBin": "1-3R",
            "paidPremium": 296.0, "entryFees": 1.04, "fees": 2.08, "firstSaleDistanceR": 3.8, "p02Eligible": True,
            "p02": {"policy": P02_POLICY, "quantity": 1, "soldByAlternative": 1, "outcome": "unknown", "why": "no observation", "alternativeRealized": None,
                    "productionRealized": 40.0, "delta": None, "forgoneOnWinner": None},
            "friction": friction(2.96, 2.86, 1, 100.0, 1.04), "contract": {"delta": 0.0}, "intendedEntry": 141.01, "targets": [142.738], "multiplier": 100.0}
    other = {**fill, "symbol": "MSFT", "trigger": "r2", "kind": "reject", "direction": "short", "cohort": None, "firstTargetBasis": "next_support",
             "closed": False, "netRealized": None, "p02Eligible": False, "paidPremium": 545.0}
    refused = {"symbol": "INTU", "trigger": "b1", "kind": "bounce", "direction": "long", "cohort": COHORT_P01, "refusal": "resulting position exceeds cap",
               "underlyingProxy": "tp1_first", "roomBin": "1-3R", "friction": None}
    data = {"date": "2026-09-15", "cutoff": "16:00", "feePerContractSide": 1.04, "trades": [fill, other], "refused": [refused], "sourceLedgerRows": 7}
    s = summarize(data)
    assert s["baseline"]["fills"] == 2 and s["cohort"]["fills"] == 1 and s["baseline"]["open"] == 1 and s["baseline"]["openExposure"] == 546.04
    assert s["removed"][0]["symbol"] == "MSFT" and s["missedWinnersCandidates"][0]["underlyingProxy"] == "tp1_first"
    assert s["unknown"]["p02WithoutObservation"] == 1 and s["p03"][0]["payoffTp1"] is None
    md = render(data, s)
    assert "Baseline (all EM fills)" in md and COHORT_P01 in md and "MSFT r2" in md and "INTU b1" in md and "unknown (no delta)" in md
