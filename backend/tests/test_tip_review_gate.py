"""review-gate-v1: a message reaches the analyst review only when it can reach something the desk holds, arms
or proposes (or reads like a possible entry). Frozen cases are real 2026-09-09..18 message shapes."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from zargar.signals.service import SignalService as SignalsService
from zargar.techniques.tip import review_gate as rg

MUGG, AB, EVA = "🌟｜muggzone-options", "🌟｜ab", "🌟｜eva"
POS_HOOD = {"kind": "position", "symbol": "HOOD", "source": MUGG}
PLAN_AAOI = {"kind": "plan", "symbol": "AAOI", "source": AB}
PROP_ORCL = {"kind": "proposal", "symbol": "ORCL260925C00160000", "source": MUGG}
DISCARD_MGMT = [{"ticker": "HOOD", "status": "verification_failed", "failed": ["opens_position"]}]


@pytest.mark.parametrize("case, tickers, source, outcomes, items, review", [
    # exit / trim on a HELD position ("TRIIMMING MORE HERE @ 2.10" on the HOOD 120C) -> reviewed
    ("exit on held position", ["HOOD"], MUGG, DISCARD_MGMT, [POS_HOOD], True),
    # the same trim when nothing is held (a room recap) -> not reviewed
    ("trim on unheld ticker", ["HOOD"], MUGG, DISCARD_MGMT, [], False),
    # no-ticker management ("SL set for 1.45") while the source's ORCL proposal executed this session -> reviewed
    ("no-ticker stop move, source has live idea", [], MUGG, [], [PROP_ORCL], True),
    # no-ticker chatter ("CHOP HOUR") from a source with nothing open -> not reviewed
    ("no-ticker chatter, source idle", [], MUGG, [], [], False),
    # another source's position does not make this source's tickerless line relevant
    ("no-ticker, only another source holds", [], EVA, [], [POS_HOOD], False),
    # correction / mass update naming an ARMED plan ("$AAOI 120c (Failed Lotto)") -> reviewed
    ("correction on armed plan", ["APLD", "AAOI"], AB, [], [PLAN_AAOI], True),
    # mixed message: one held ticker among several -> reviewed
    ("mixed message", ["NVDA", "HOOD"], MUGG, DISCARD_MGMT, [POS_HOOD], True),
    # option symbol on the desk matches the underlying ticker in the message
    ("option root match", ["ORCL"], MUGG, [], [PROP_ORCL], True),
    # entry-shaped discard ("im liking META 1dte 665 calls here") -> reviewed even with nothing open
    ("possible missed entry", ["META"], MUGG,
     [{"ticker": "META", "status": "verification_failed", "failed": ["actionable", "explicit_or_implied"]}], [], True),
])
def test_decide_frozen_cases(case, tickers, source, outcomes, items, review):
    d = rg.decide(tickers=tickers, source=source, outcomes=outcomes, items=items)
    assert d["review"] is review, (case, d)
    assert d["reason"]


def test_unknown_mode_is_observe_never_silent_skip():
    assert rg.mode_of({"techniques.tip.review_gate": "enforc"}) == "observe"
    assert rg.mode_of({}) == "observe"
    assert rg.mode_of({"techniques.tip.review_gate": "ENFORCE"}) == "enforce"


def _svc(mode, *, positions=(), fail=False):
    journal = NS(append=AsyncMock())

    class Mgr:
        def positions(self, status=None):
            if fail:
                raise RuntimeError("manager unavailable")
            return list(positions)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **k):
            return NS(all=lambda: [])                  # no live proposals
    # every component present and answering: only then is "nothing matched" an authoritative empty desk
    eng = NS(settings={"techniques.tip.review_gate": mode}, journal=journal, position_manager=Mgr(),
             tip_runner=NS(_armed={}, restore_complete=True), sf=lambda: _Session())
    return NS(engine=eng), journal


def _intake():
    return NS(id="run-1", step=lambda *a, **k: None, finish=AsyncMock())


CONTENT = NS(source_name=MUGG, id="content-1")
OUT = [{"signal": {"ticker": "HOOD", "status": "verification_failed"}}]


async def test_enforce_skips_an_unreachable_message_on_the_record():
    svc, journal = _svc("enforce")
    intake = _intake()
    ok = await SignalsService._review_gate(svc, intake, CONTENT, OUT, DISCARD_MGMT, path="discarded")
    assert ok is False
    intake.finish.assert_awaited_once()
    assert intake.finish.await_args.args[0] == "gated"
    payload = journal.append.await_args.args[1]
    assert payload["decision"] == "skip" and payload["applied"] is True and payload["intakeRunId"] == "run-1"


async def test_enforce_reviews_a_held_ticker():
    svc, journal = _svc("enforce", positions=[{"technique": "tip", "symbol": "HOOD", "tags": [f"source:{MUGG}"]}])
    intake = _intake()
    assert await SignalsService._review_gate(svc, intake, CONTENT, OUT, DISCARD_MGMT, path="discarded") is True
    intake.finish.assert_not_awaited()
    assert journal.append.await_args.args[1]["decision"] == "review"


async def test_observe_records_the_skip_decision_but_still_reviews():
    svc, journal = _svc("observe")
    intake = _intake()
    assert await SignalsService._review_gate(svc, intake, CONTENT, OUT, DISCARD_MGMT, path="discarded") is True
    p = journal.append.await_args.args[1]
    assert p["decision"] == "skip" and p["applied"] is False and p["mode"] == "observe"
    intake.finish.assert_not_awaited()


async def test_off_decides_nothing():
    svc, journal = _svc("off")
    assert await SignalsService._review_gate(svc, _intake(), CONTENT, OUT, DISCARD_MGMT, path="discarded") is True
    journal.append.assert_not_awaited()


async def test_an_incomplete_desk_read_reviews_even_under_enforce():
    svc, journal = _svc("enforce", fail=True)            # the position manager cannot be read
    intake = _intake()
    assert await SignalsService._review_gate(svc, intake, CONTENT, OUT, DISCARD_MGMT, path="discarded") is True
    intake.finish.assert_not_awaited()
    p = journal.append.await_args.args[1]
    assert p["decision"] == "review" and p["readErrors"] == ["positions: RuntimeError"]


async def test_a_failing_decision_never_blocks_the_review():
    svc, _journal = _svc("enforce")
    orig = rg.decide
    try:
        rg.decide = lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        assert await SignalsService._review_gate(svc, _intake(), CONTENT, OUT, DISCARD_MGMT, path="discarded") is True
    finally:
        rg.decide = orig


async def test_a_runner_whose_restore_has_not_completed_keeps_the_review():
    svc, journal = _svc("enforce")
    svc.engine.tip_runner = NS(_armed={}, restore_complete=False)
    assert await SignalsService._review_gate(svc, _intake(), CONTENT, OUT, DISCARD_MGMT, path="discarded") is True
    assert journal.append.await_args.args[1]["readErrors"] == ["plans: tip runner restore not complete"]
