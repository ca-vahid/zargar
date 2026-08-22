"""OCC symbology: parse/format both spellings, display, DTE, venue conversion."""
import datetime as dt

import pytest

from zargar.options import occ


def test_parse_unpadded_and_padded_are_the_same_contract():
    a = occ.parse("F260828C00014500")
    b = occ.parse("F     260828C00014500")
    assert a == b
    assert a.underlying == "F" and a.right == "C" and a.strike == 14.5
    assert a.expiry == dt.date(2026, 8, 28)
    assert a.symbol == "F260828C00014500"
    assert a.snaptrade == "F     260828C00014500"
    assert len(a.snaptrade) == 21


def test_parse_rejects_non_occ_and_bad_dates():
    assert occ.parse("AAPL") is None
    assert occ.parse("SHOP.TO") is None
    assert occ.parse("") is None
    assert occ.parse(None) is None
    assert occ.parse("F261331C00014500") is None   # month 13
    assert occ.is_occ("SPXW260821C05000000") is True
    assert occ.is_occ("AAPL") is False


def test_normalize_and_venue_roundtrip():
    assert occ.normalize("aapl  251114c00240000") == "AAPL251114C00240000"
    assert occ.normalize("shop.to") == "SHOP.TO"
    assert occ.to_snaptrade("AAPL251114C00240000") == "AAPL  251114C00240000"
    assert occ.from_snaptrade("AAPL  251114C00240000") == "AAPL251114C00240000"
    assert occ.from_snaptrade("not an option") is None
    with pytest.raises(ValueError):
        occ.to_snaptrade("AAPL")


def test_display_dte_and_expiry():
    o = occ.parse("SPY261218P00765500")
    assert o.display() == "SPY 18 Dec 26 765.5 P"
    assert o.short() == "SPY 765.5P 12/18"
    assert o.option_type == "put"
    assert o.dte(dt.date(2026, 12, 18)) == 0
    assert o.dte(dt.date(2026, 12, 17)) == 1
    assert o.is_expired(dt.date(2026, 12, 19)) is True
    assert o.is_expired(dt.date(2026, 12, 18)) is False
    d = o.to_dict(today=dt.date(2026, 12, 1))
    assert d["dte"] == 17 and d["multiplier"] == 100 and d["right"] == "P"


def test_make_builds_canonical_symbol():
    o = occ.make("f", "2026-08-28", "call", 14.5)
    assert o.symbol == "F260828C00014500"
    assert occ.make("TSLA", dt.date(2026, 9, 18), "P", 300).symbol == "TSLA260918P00300000"
    with pytest.raises(ValueError):
        occ.make("F", "2026-08-28", "X", 1)
