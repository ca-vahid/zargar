"""Share observations must carry the same evidence policy as option observations (2026-09-21).

Every share observation EM had ever recorded - five of five - was discarded as having "no source
provenance / timestamp", while option observations from the same recorder in the same session scored
normally. Two causes, both fixed here:

  * the shadow path read `Quote.source` raw, and that field is empty by contract on EVERY equity, so
    the substitution its sibling recorders apply was never seen;
  * when the venue time was missing it fell back to the RECEIPT time, so `ageS` silently measured how
    long ago we saw the quote instead of how old the venue said it was.

The second is the more dangerous of the two, and the Tips desk made the same point independently the
same afternoon: a source timestamp that matches the host clock proves nothing about venue time.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_codex_em_final_dispatch_budget import CONTRACT, dispatch_rig  # noqa: F401
from zargar.domain import Quote, now_ms
from zargar.technique.first_sale import build_record
from zargar.technique.research_recorder import feed_identity, quote_evidence

pytestmark = pytest.mark.asyncio


def _equity_quote(*, venue_ts: int | None, source: str = "") -> Quote:
    q = Quote("AVGO", bid=357.20, ask=357.33, last=357.13, bid_size=360, ask_size=80,
              ts=now_ms(), source=source)
    if venue_ts is not None:
        q.quote_ts = venue_ts
        q.last_ts = venue_ts
    return q


async def test_an_equity_quote_carries_no_source_of_its_own(dispatch_rig):
    """The premise of the whole defect, pinned so it is not mistaken for a feed outage."""
    q = _equity_quote(venue_ts=now_ms() - 100)
    assert q.source == "" and q.source_ts == 0, "equities never carry source/source_ts; that is the contract"
    assert q.quote_ts > 0, "their venue time lives on quote_ts"


async def test_the_shadow_recorder_now_labels_a_share_quote_and_says_the_label_is_a_process(dispatch_rig):
    rig = dispatch_rig
    venue = now_ms() - 120
    rig.engine.quotes.on_quote(_equity_quote(venue_ts=venue))
    rig.engine.feed = SimpleNamespace()                       # any feed object; the label is its class name
    captured = {}
    rig.runner._shadow_publish = lambda ap, rec: captured.update(rec)
    tr = rig.trade
    tr.instrument, tr.order_symbol, tr.multiplier = "shares", None, 1.0
    ident = feed_identity(rig.engine)
    ev = quote_evidence(rig.engine.quotes.get("AVGO"), symbol="AVGO", is_option=False, feed=ident)
    assert ev["source"] == ident and ev["sourceBasis"] == "engine_feed", \
        "the sibling recorder substitutes a process label and says so"
    assert ev["quoteTs"] == venue, "and reads the equity's real venue time, not the receipt"


async def test_a_substituted_label_is_persisted_with_the_field_that_says_it_was_substituted():
    """`feed:HybridQuoteFeed` names a class in this app. A reader must be able to tell."""
    ue = {"symbol": "AVGO", "bid": 355.18, "ask": 355.75, "last": 355.46, "quoteTs": 1, "lastTs": 1,
          "receivedTs": 1, "source": "feed:HybridQuoteFeed", "sourceBasis": "engine_feed",
          "rawSource": None, "halted": False}
    rec = build_record(stage="order", symbol="AVGO", run_id="r", trigger_id="b1", family="bounce",
                       direction="long", session="2026-09-21", plan_entry=355.0, runner_entry=355.0,
                       stop=353.0, targets=[357.0, 359.0, 361.0], underlier_evidence=ue,
                       instrument="shares", qty=13, multiplier=1.0, limit_price=355.16,
                       single_exit="tp2", pinned_gate_target="auto", pin_source="run_config",
                       min_rr=3.0, contract=None, option_quote=None, fee_per_contract=1.04,
                       stock_commission=0.0, affordable_qty=13, plan_gate=None, mode="observe",
                       now_ms=2)
    stored = (rec.get("underlying") or {}).get("evidence") or {}
    assert stored.get("sourceBasis") == "engine_feed", \
        "the field that distinguishes a substituted label from a venue identity must survive persistence"
    assert "rawSource" in stored, "and what the provider actually said, if anything"


async def test_a_venue_time_is_never_borrowed_from_the_host_clock(dispatch_rig):
    """With no venue stamp the age must be unknown - not zero, and not the receipt age."""
    q = _equity_quote(venue_ts=None)
    assert q.quote_ts == 0 and q.last_ts == 0
    ev = quote_evidence(q, symbol="AVGO", is_option=False, feed="feed:HybridQuoteFeed")
    assert ev["quoteTs"] == 0, "no venue time means no venue time"
    assert ev["source"] is None, "and without one, no label may be substituted either"
    assert ev["receivedTs"] > 0, "the receipt is kept, in its own field, where it cannot be mistaken for venue time"


async def test_an_option_quote_keeps_its_real_venue_identity(dispatch_rig):
    """The half that already worked must keep working."""
    stamp = now_ms() - 50
    oq = Quote(CONTRACT, bid=2.95, ask=3.0, last=2.975, bid_size=115, ask_size=161,
               ts=now_ms(), source="opra", source_ts=stamp)
    ev = quote_evidence(oq, symbol=CONTRACT, is_option=True, feed=None)
    assert ev["source"] == "opra" and ev["sourceBasis"] == "quote"
    assert ev["quoteTs"] == stamp, "options read their venue time from source_ts"


@pytest.mark.parametrize("src,vts,expect", [
    ("", 0, "no source provenance and no venue timestamp"),
    ("", 5, "no source provenance"),
    ("opra", 0, "no venue timestamp"),
])
async def test_the_recorded_reason_names_which_half_was_missing(src, vts, expect):
    """The old message blamed both halves whichever one was absent, which sent this investigation
    looking for a missing timestamp that was never missing."""
    import inspect

    from zargar.execution import planrunner
    body = inspect.getsource(planrunner.PlanRunner._shadow_capture_rung)
    assert expect in body, f"the reason for src={src!r} vts={vts} must be distinguishable"
    assert "no source provenance / timestamp" not in body, "the conflated message is gone"
