"""INTRA-01/02/03 (2026-09-16): expiration break-even vs an earlier premium sale,
one lot as an exit-plan question, and the cheap recap read before a paid appraisal.
Synthetic evidence is labelled as such; nothing here trades or changes a limit."""
from types import SimpleNamespace as NS

from zargar.techniques.tip import analyst, feasibility, payoff, recap

FEE = 0.99 + 0.05          # per contract per side (Webull CA fee + regulatory)


def test_a_call_sold_before_expiry_can_profit_below_the_expiration_break_even():
    # the GOOGL case: 2-DTE 350 call bought 2.19; expiration break-even 352.19
    be = payoff.break_even(option_type="call", strike=350.0, premium=2.19)
    assert be["expiration"] == 352.19 and "HELD TO EXPIRY" in be["basis"]
    # SYNTHETIC later executable bid 2.50 with the underlying at 349 (below the strike):
    sale = payoff.premium_exit(entry_premium=2.19, exit_premium=2.50, qty=1, fee_per_unit=FEE, evidence="synthetic: labelled test bid")
    assert sale["status"] == "known" and sale["gross"] == 31.0 and sale["fees"] == 2.08 and sale["net"] == 28.92
    assert sale["evidence"].startswith("synthetic") and "not on the expiration break-even" in sale["note"]
    assert 349.0 < 350.0 < be["expiration"], "profit on the sale while the underlying sits below strike AND below the expiration break-even"
    # HELD TO EXPIRY at 349 the same contract is worthless: the expiration break-even applies only then
    assert payoff.expiry_value(option_type="call", strike=350.0, underlying=349.0) == 0.0
    held = payoff.premium_exit(entry_premium=2.19, exit_premium=payoff.expiry_value(option_type="call", strike=350.0, underlying=349.0),
                               qty=1, fee_per_unit=FEE, evidence="held to expiry")
    assert held["net"] == round(-219.0 - 2.08, 2)
    # missing premium evidence -> unknown, never a guess
    unknown = payoff.premium_exit(entry_premium=2.19, exit_premium=None, qty=1, fee_per_unit=FEE)
    assert unknown["status"] == "unknown" and unknown["unknown"] == ["exitPremium"] and unknown["net"] is None
    assert payoff.break_even(option_type="call", strike=None, premium=2.19)["expiration"] is None


def test_preview_prints_the_expiration_break_even_beside_before_expiry_scenarios():
    gains = payoff.unit_gains(vehicle="option", entry_ref=346.03, targets=[349.0], delta=0.356, multiplier=100.0)
    pv = payoff.payoff_preview(qty=1, fractions=[1.0], gains=gains, unit_loss=109.5, fee_per_unit=FEE, vehicle="option",
                               strike=350.0, premium=2.19, option_type="call", dte=2, hold_sessions=1)
    assert pv["breakEven"]["expiration"] == 352.19 and pv["horizon"]["exitAssumption"].startswith("before expiry")
    assert pv["scenarios"]["allTargets"]["net"] > 0, "the delta-linear exit at 349 is a profit even though 349 < 352.19"
    at_expiry = payoff.payoff_preview(qty=1, fractions=[1.0], gains=gains, unit_loss=109.5, vehicle="option",
                                      strike=350.0, premium=2.19, option_type="call", dte=2, hold_sessions=2)
    # I175-03: a hold cap that reaches the expiry is still NOT an expiry exit; only a declared one is
    assert at_expiry["horizon"]["exitAssumption"].startswith("before expiry") and at_expiry["horizon"]["holdCapReachesExpiry"] in (True, False)
    declared = payoff.payoff_preview(qty=1, fractions=[1.0], gains=gains, unit_loss=109.5, vehicle="option",
                                     strike=350.0, premium=2.19, option_type="call", dte=2, hold_sessions=2, exit_at_expiry=True)
    assert declared["horizon"]["exitAssumption"] == "declared: held to expiry"
    shares = payoff.payoff_preview(qty=10, fractions=[1.0], gains=[3.0], unit_loss=1.0, vehicle="shares")
    assert "breakEven" not in shares and "singleLot" not in shares


def test_one_lot_is_judged_on_its_single_exit_plan_not_rejected_for_missing_partials():
    # the source scales out in three rungs; the desk can afford ONE contract
    gains = payoff.unit_gains(vehicle="option", entry_ref=100.0, targets=[102.0, 104.0, 106.0], delta=0.4, multiplier=100.0)
    pv = payoff.payoff_preview(qty=1, fractions=[0.4, 0.3, 0.3], gains=gains, unit_loss=50.0, fee_per_unit=FEE, vehicle="option")
    sl = pv["singleLot"]
    assert sl["declaredRungs"] == 3 and sl["executableRungs"] == 1 and sl["collapsed"] and sl["canCopyPartials"] is False
    assert "judge that single-exit plan on its own net payoff" in sl["note"]
    assert pv["oneLot"]["policy"] == "single exit at the first target" and pv["oneLot"]["net"] == round(80.0 - 2 * FEE, 2)
    assert pv["scenarios"]["tp1ThenStop"]["net"] == pv["oneLot"]["net"]
    # three contracts CAN execute the three rungs
    pv3 = payoff.payoff_preview(qty=3, fractions=[0.4, 0.3, 0.3], gains=gains, unit_loss=50.0, vehicle="option")
    assert pv3["singleLot"]["canCopyPartials"] is True and pv3["singleLot"]["executableRungs"] == 3
    # a one-unit budget failure still refuses - the budget, not the lot size, is the reason
    f = feasibility.feasibility(budget=89.35, unit_loss=109.5, unit_cost=219.0)
    assert f["feasible"] is False and f["qty"] == 0 and "budget" in str(f["reason"]).lower()


def test_prompt_carries_both_rules_and_keeps_the_independent_skip_reasons():
    assert "BREAK-EVEN IS AN EXPIRATION NUMBER" in analyst.SYSTEM and "ONE LOT IS AN EXIT-PLAN QUESTION" in analyst.SYSTEM
    assert "never force a take from this rule" in analyst.SYSTEM
    assert 'Never call one contract "unmanageable" by itself' in analyst.SYSTEM


def _s(ticker, instrument="call", action="open", premium=None, entry=None, strike=None, actionable=True):
    return NS(ticker=ticker, direction="long", action=action, instrument=instrument, strike=strike, expiry=None,
              premium=premium, entry_price=entry, is_actionable=actionable)


def test_recap_read_routes_maps_compact_and_keeps_management_and_new_entries_full():
    # eva's SPX-led 12-branch level map: both sides of SPX plus unrelated names, no stated premiums
    spx_map = [_s("SPX", "call", strike=6600), _s("SPX", "put", strike=6500), _s("SPX", "call", strike=6650), _s("SPX", "put", strike=6450),
               _s("MRNA", "call", strike=160), _s("TSLA", "call", strike=370), _s("TSLA", "put", strike=345), _s("AAPL", "call", strike=340),
               _s("INTC", "shares"), _s("MSFT", "put", strike=490), _s("NVDA", "shares"), _s("AMZN", "call", strike=260)]
    r = recap.classify(spx_map, "FOMC morning map - levels to watch above and below; digest of the week", fan_in_min=3)
    assert r["category"] == "recap" and r["confidence"] >= 0.8 and r["route"] == "compact"
    assert "SPX" in r["features"]["bothSidesSameUnderlying"] and r["features"]["pricedOpens"] == 0
    # a management post on held names must never be routed away from the full read
    mgmt = recap.classify([_s("SLV", "call", action="trim"), _s("MRNA", "shares", action="update_stop"), _s("T", "call", action="close")],
                          "trimming SLV 40%, stop MRNA to 138, closing T here", fan_in_min=3)
    assert mgmt["category"] == "management" and mgmt["route"] == "full"
    # a single priced BTO is the ordinary route
    one = recap.classify([_s("GOOGL", "call", premium=1.95, strike=350)], "BTO GOOGL 350c 1.95 lotto", fan_in_min=3)
    assert one["category"] == "single" and one["route"] == "full"
    # mixed: priced opens beside management -> full
    mixed = recap.classify([_s("A", "call", premium=1.0), _s("B", "call", action="close"), _s("C", "put", premium=2.0)], "adding A, closing B", fan_in_min=3)
    assert mixed["category"] == "mixed" and mixed["route"] == "full"
    # recap-like but with entry cues and priced opens -> not confident -> full
    ambiguous = recap.classify([_s("A", "call", premium=1.0), _s("B", "call", premium=1.5), _s("C", "put", premium=2.0), _s("D", "call")],
                               "update: bought A and B this morning, sending it", fan_in_min=3)
    assert ambiguous["route"] == "full" and ambiguous["category"] in ("new", "mixed")


def test_compact_selection_is_core_rules_relevant_notes_and_a_short_history():
    rules = [{"id": "1", "core": True, "text": "core"}, {"id": "2", "core": False, "text": "new"}, {"id": "3", "core": False, "text": "old"}]
    assert [r["id"] for r in recap.compact_rules(rules)] == ["1"]
    assert [r["id"] for r in recap.compact_rules([{"id": str(i), "core": False, "text": "x"} for i in range(9)])] == ["0", "1", "2", "3", "4"]
    notes = [{"id": "a", "scope": "ticker:SPX"}, {"id": "b", "scope": "source:eva"}, {"id": "c", "scope": "ticker:MSFT"},
             {"id": "d", "scope": "general", "core": True}, {"id": "e", "scope": "daily:2026-09-15"}]
    assert [n["id"] for n in recap.compact_notes(notes, ticker="spx", source="eva")] == ["a", "b", "d"]
    assert recap.trim_history("\n".join(f"l{i}" for i in range(30)), 12).count("\n") == 11
