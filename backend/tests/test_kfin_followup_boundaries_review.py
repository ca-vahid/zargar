"""Independent follow-up boundaries. Disposable Codex DB only."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from zargar.db import make_engine, make_session_factory
from zargar.models import TipNote
from zargar.signals.service import SignalService
from zargar.techniques.tip.consolidation import apply_consolidation, payload_hash
from .conftest import TEST_DB_URL
from zargar.techniques.tip import cohort
import datetime as dt


@pytest.fixture
async def review_engine(fresh_db):
    db = make_engine(TEST_DB_URL)
    eng = NS(sf=make_session_factory(db), settings={"techniques.tip.knowledge_apply_enabled": False},
             journal=NS(append=AsyncMock()))
    eng.signals_service = SignalService(eng, None)
    yield eng
    await db.dispose()


async def setup_rejection(eng):
    note = await eng.signals_service.add_tip_note("rule", "Unapproved risk policy.",
                                                author="analyst:fixture", staged=True)
    resolve = [{"id": note["id"], "revision": note["revisionNo"]}]
    batches = [{"batchId": "review-boundary-rejection", "scope": "rule",
                "expected_revisions": {note["id"]: note["revisionNo"]},
                "expire": {"ids": [note["id"]], "reason": "rejected"}}]
    return note, dict(manifest_hash=payload_hash(resolve=resolve, batches=batches, evidence=[]),
                      resolve=resolve, batches=batches)


async def test_failed_expiry_never_activates_rejected_proposal(review_engine, monkeypatch):
    eng = review_engine
    note, payload = await setup_rejection(eng)
    monkeypatch.setattr(eng.signals_service, "apply_knowledge_batch", AsyncMock(side_effect=OSError("expiry unavailable")))
    with pytest.raises(OSError):
        await apply_consolidation(eng, **payload)
    async with eng.sf() as session:
        row = await session.get(TipNote, note["id"])
        assert row.needs_human or row.superseded_by, "rejected proposal became undisputed live policy before expiry committed"


async def test_unrelated_resolution_is_not_manifest_ownership(review_engine):
    eng = review_engine
    note, payload = await setup_rejection(eng)
    # A separate user action has the same generic resolve revision reason.
    await eng.signals_service.flag_tip_notes([note["id"]], needs_human=False)
    with pytest.raises(ValueError):
        await apply_consolidation(eng, **payload)


async def test_notification_failure_still_finishes_and_replays(review_engine):
    eng = review_engine
    note, payload = await setup_rejection(eng)
    async def fail_notification(kind, body, **kwargs):
        if body.get("resolved"):
            raise OSError("notification unavailable")
    eng.journal.append = AsyncMock(side_effect=fail_notification)
    await apply_consolidation(eng, **payload)
    assert (await apply_consolidation(eng, **payload))["replay"]
    async with eng.sf() as session:
        assert (await session.get(TipNote, note["id"])).superseded_by


async def test_twelve_minute_recovery_is_not_three_minute_evidence(review_engine, monkeypatch):
    from zargar.models import TipEntryCohortRow
    eng = review_engine
    now = dt.datetime.now(dt.timezone.utc)
    row = TipEntryCohortRow(id="late-review", signal_id="late-review-signal", ticker="AAPL",
                           action="open", decision="declined", decision_kind="intake", quote_symbol="AAPL",
                           decided_at=now - dt.timedelta(minutes=12),
                           delayed_due_at=now - dt.timedelta(minutes=9), delayed_status="pending", gaps=[])
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    monkeypatch.setattr(cohort, "_snap_quote", lambda *a, **kw: ({"ask": 100, "bid": 99,
                        "sampledAt": now.isoformat(), "ageSeconds": 0}, "fresh"))
    result = await cohort.sample_one(eng, row.id, now=now)
    variant = cohort.simulate_variants(result, cohort.assumptions(eng.settings), variants=("delay",))[0]
    assert not variant["adequate"], "12-minute observation counted as adequate for the 3-minute variant"


def test_delayed_chain_quote_is_not_eligible_execution_evidence():
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    q = NS(bid=1, ask=1.1, last=1.05, source="chain", source_ts=now, ts=now, delayed=True)
    eng = NS(quotes={"AAPL261016C00100000": q})
    sample, status = cohort._snap_quote(eng, "AAPL261016C00100000", max_age_s=300, kind="decision")
    row = {"id": "chain", "ticker": "AAPL", "quoteSymbol": "AAPL261016C00100000",
           "quoteAtDecision": sample, "quoteStatus": status}
    variant = cohort.simulate_variants(row, cohort.assumptions({}), variants=("immediate",))[0]
    assert not variant["adequate"], "delayed chain quote is treated as executable comparison evidence"
