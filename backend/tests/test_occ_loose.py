"""2026-09-24: the analyst (Opus 5.5) wrote INTC260925C130; the card priced nothing and waited for a human."""
from zargar.options import occ


def test_a_short_contract_spelling_becomes_real_occ():
    assert occ.parse_loose("INTC260925C130").symbol == "INTC260925C00130000"
    assert occ.parse_loose("spy260925p742.5").symbol == "SPY260925P00742500"
    assert occ.parse_loose("INTC260925C00130000").symbol == "INTC260925C00130000"      # strict OCC unchanged


def test_a_string_that_is_not_a_contract_is_refused_not_guessed():
    for bad in ("INTC 130C", "INTC261399C130", "INTC260925X130", "", None, "INTC260925C0"):
        assert occ.parse_loose(bad) is None
