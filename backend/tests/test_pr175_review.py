"""Minimal reasoning/route boundaries, pure and unpaid."""
from zargar.techniques.tip import recap, payoff


def test_map_with_fresh_priced_entry_stays_full():
    signals = [
        {"ticker": "AAPL", "instrument": "call", "action": "open"},
        {"ticker": "AAPL", "instrument": "put", "action": "open"},
        {"ticker": "MSFT", "instrument": "shares", "action": "open"},
        {"ticker": "NVDA", "instrument": "call", "action": "open", "premium": 1.0, "is_actionable": True},
        {"ticker": "TSLA", "instrument": "shares", "action": "open"},
    ]
    result = recap.classify(signals, "Morning map and levels. BTO NVDA calls at 1.00.")
    assert result["route"] == "full", result


def test_partial_copy_claim_uses_executable_rungs():
    result = payoff.payoff_preview(qty=3, fractions=[0.8, 0.1, 0.1], gains=[10,20,30], unit_loss=5)
    assert result["ladder"]["units"] == [2,1,0]
    assert result["singleLot"]["canCopyPartials"] is False, result["singleLot"]


def test_maximum_hold_cap_does_not_declare_an_expiry_exit():
    result = payoff.payoff_preview(qty=1, fractions=[1], gains=[10], unit_loss=5,
        strike=350, premium=2.19, option_type="call", dte=2, hold_sessions=5)
    assert result["horizon"]["exitAssumption"] != "at expiry", "a maximum hold cap does not override earlier target/stop exits"
