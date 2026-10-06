"""2026-10-06: a model wrote "NKE261023C37000" (the $37 call, OCC strike field truncated); the loose parser read a
$37,000 strike. With the underlying price the plausible reading wins; without one the old dollar reading stays."""
from zargar.options.occ import parse_loose


def test_truncated_occ_strike_reads_as_thousandths_near_the_price():
    o = parse_loose("NKE261023C37000", ref_price=36.9)
    assert o is not None and o.strike == 37.0 and o.symbol == "NKE261023C00037000"


def test_dollar_strikes_keep_their_reading():
    assert parse_loose("INTC260925C130", ref_price=128.0).strike == 130.0
    assert parse_loose("SPY260925P742.5", ref_price=740.0).strike == 742.5
    assert parse_loose("NDX261016C20000", ref_price=20100.0).strike == 20000.0


def test_without_a_price_the_old_reading_stays():
    assert parse_loose("NKE261023C37000").strike == 37000.0
