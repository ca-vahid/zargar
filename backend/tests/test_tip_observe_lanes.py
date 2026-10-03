"""W2.5 / W2.6 / W3.5 observe lanes (2026-10-03): pure checks; they journal and never touch an order."""
from types import SimpleNamespace as NS

from zargar.techniques.tip.observe_lanes import JUDGEMENT, fast_lane_check


def test_fast_lane_check():
    sig = NS(direction="long", action="open")
    ok = {"checks": [{"name": "x", "passed": True}]}
    q = NS(ask=10.5, bid=10.4)
    assert fast_lane_check(sig=sig, verification=ok, earned=True, quote=q, source_price=10.0)["would"] is True
    r = fast_lane_check(sig=sig, verification=ok, earned=True, quote=NS(ask=12.0), source_price=10.0)
    assert not r["would"] and "1.15x" in r["reasons"][0]
    r = fast_lane_check(sig=NS(direction="short", action="open"), verification=ok, earned=False, quote=None,
                        source_price=None)
    assert not r["would"] and len(r["reasons"]) == 4


def test_judgement_cue():
    assert JUDGEMENT.search("setup passes my filters but the reach to target is poor")
    assert JUDGEMENT.search("no expiry stated - contract identity unresolvable")
    assert not JUDGEMENT.search("this is a recap of an earlier trade, not an open")
