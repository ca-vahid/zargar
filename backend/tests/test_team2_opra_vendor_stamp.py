"""OPRA clock semantics: the vendor stamp is recorded, and no decision changes.

`source_ts` on an OPRA quote is OUR POLL time. The vendor's own time for the bid/ask used to be
dropped before the Quote was built, so a premium stop's "two distinct observations" could be two
polls of one vendor print, and nobody could tell afterwards. The rule is deliberately NOT changed
here: keying it on the vendor stamp would stop a genuine standing bleed from ever confirming. These
tests pin the evidence and prove the decision is untouched.
"""
from __future__ import annotations

import time

import pytest

from zargar.domain import Quote

from .test_team2_premium_stop_authority import PAID, SYM, desk  # noqa: F401
from .test_team2_runner import rig  # noqa: F401


async def _watch(eng, runner, ap, stamps):
    """Feed the 2 s watch one breached poll per vendor stamp. Poll times always advance, exactly as
    the OPRA pass does; the vendor stamp is whatever the venue sent."""
    eng.quotes.on_quote(Quote(symbol=ap.symbol, bid=569.9, ask=570.1, last=570.0))
    base = int(time.time() * 1000)
    for n, vendor in enumerate(stamps):
        eng.quotes.on_quote(Quote(symbol=SYM, bid=0.20, ask=0.21, last=0.205, ts=base + n,
                                  source="opra", source_ts=base + n, quote_ts=vendor))
        await runner.on_quote_watch()


async def test_the_defect_is_now_visible_one_print_polled_twice_still_confirms(rig, monkeypatch):
    """The rule counts polls, so ONE vendor print seen on two polls confirms today. That is unchanged
    on purpose - and the record now says the two observations were the same print."""
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    await _watch(eng, runner, ap, [1790000000000, 1790000000000, 1790000000000])
    assert calls and calls[-1]["kind"] == "stop", "the decision is unchanged by this patch"
    conf = calls[-1]["authority"]["quote"]["confirmation"]
    assert conf["distinctVendorObservations"] == 1
    assert conf["genuinelyDistinct"] is False, "the record must say it was one print polled twice"


async def test_two_distinct_vendor_prints_are_recorded_as_distinct(rig, monkeypatch):
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    await _watch(eng, runner, ap, [1790000000000, 1790000001000, 1790000002000])
    conf = calls[-1]["authority"]["quote"]["confirmation"]
    assert conf["genuinelyDistinct"] is True and conf["distinctVendorObservations"] >= 2


async def test_a_missing_vendor_stamp_is_unknowable_not_assumed(rig, monkeypatch):
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    await _watch(eng, runner, ap, [0, 0, 0])
    conf = calls[-1]["authority"]["quote"]["confirmation"]
    assert conf["genuinelyDistinct"] is None, "no vendor stamp means we cannot know, and must not say otherwise"


async def test_the_evidence_names_which_clock_each_stamp_came_from(rig, monkeypatch):
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    now = int(time.time() * 1000)
    eng.quotes.on_quote(Quote(symbol=SYM, bid=0.30, ask=0.31, last=0.305, ts=now,
                              source="opra", source_ts=now, quote_ts=now - 4000))
    price, ev = runner.live_premium_basis(tr, now_ms=now)
    assert ev["sourceTimeBasis"] == "poll", "OPRA source_ts is our poll time and must be labelled as such"
    assert ev["vendorTs"] == now - 4000 and ev["vendorAgeS"] == pytest.approx(4.0, abs=0.01)
    assert ev["ageS"] == pytest.approx(0.0, abs=0.01), "the poll age is unchanged and still bounds staleness"


async def test_freshness_still_reads_the_poll_time_not_the_vendor_time(rig, monkeypatch):
    """A quiet contract whose NBBO last changed minutes ago is still CURRENT: its standing quote is
    confirmed by our poll. Judging freshness on the vendor stamp would wrongly blind the stop."""
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    now = int(time.time() * 1000)
    eng.quotes.on_quote(Quote(symbol=SYM, bid=0.30, ask=0.31, last=0.305, ts=now,
                              source="opra", source_ts=now, quote_ts=now - 10 * 60 * 1000))
    price, ev = runner.live_premium_basis(tr, now_ms=now)
    assert ev["usable"] is True and price is not None


def test_the_opra_pass_carries_the_vendor_stamp_and_keeps_poll_time_as_source_ts():
    """The producer change, read from its source: quote_ts is set from the vendor row and source_ts
    is still the poll clock, in both the overlay and the direct quote."""
    import inspect
    from zargar.options import service
    src = inspect.getsource(service)
    assert "src_ts = now" in src, "source_ts must remain our poll time"
    assert 'vendor_qts = int(r.get("quote_ts") or 0)' in src
    assert src.count("quote_ts=vendor_qts") == 2, "both the overlay and the direct quote carry the vendor stamp"
    assert 'last_ts=int(r.get("trade_ts") or 0)' in src
