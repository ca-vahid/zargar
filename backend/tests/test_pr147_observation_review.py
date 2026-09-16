"""Actual sample clocks, emitted replay gaps, and additive index migration."""
import datetime as dt
from sqlalchemy import select, text
from zargar.models import TipHoldSnapshotRow
from zargar.techniques.tip import holdstudy as hs, frozen
from zargar.db import make_engine, create_all
from .conftest import TEST_DB_URL
from .test_kfin_followup_boundaries_review import review_engine  # noqa: F401
from .test_prof142_research_boundaries_review import install_position


async def test_preclose_quote_returned_after_window_is_not_qualified(review_engine, monkeypatch):
    eng = review_engine
    install_position(eng, monkeypatch)
    start = dt.datetime(2026, 9, 15, 19, 59, 59, tzinfo=dt.timezone.utc)
    observed = start + dt.timedelta(seconds=3)
    monkeypatch.setattr(hs, "_snap", lambda *a, **kw: ({"bid": 101, "ask": 102, "sampledAt": observed.isoformat(),
        "sourceTs": int(observed.timestamp()*1000)}, "fresh"))
    await hs.snapshot_preclose(eng, now=start)
    async with eng.sf() as session:
        row = (await session.execute(select(TipHoldSnapshotRow))).scalars().one()
    assert row.preclose_status != "fresh", "quote sampled after 16:00 was admitted using the earlier job clock"


async def test_open_quote_returned_after_window_is_not_qualified(review_engine, monkeypatch):
    eng = review_engine
    install_position(eng, monkeypatch)
    await hs.snapshot_preclose(eng, now=dt.datetime(2026, 9, 14, 19, 50, tzinfo=dt.timezone.utc))
    start = dt.datetime(2026, 9, 15, 13, 44, 59, tzinfo=dt.timezone.utc)
    observed = start + dt.timedelta(seconds=3)
    monkeypatch.setattr(hs, "_snap", lambda *a, **kw: ({"bid": 101, "ask": 102, "sampledAt": observed.isoformat(),
        "sourceTs": int(observed.timestamp()*1000)}, "fresh"))
    await hs.sample_next_open(eng, now=start)
    async with eng.sf() as session:
        row = (await session.execute(select(TipHoldSnapshotRow))).scalars().one()
    assert row.next_open_status != "fresh", "quote sampled after 09:45 was admitted using the earlier job clock"


def test_image_gap_in_actual_replay_field_marks_comparison_limited():
    report = {"bundleId": "case", "variant": "current", "verdict": "skip", "noVerdict": False,
        "bundleGaps": ["view_image output is not capturable"], "manifestGaps": [],
        "toolCalls": {"served": 1, "missing": 0}}
    assert frozen.compare([report, {**report, "variant": "compact"}])["coverageLimited"]


async def test_create_all_restores_missing_declared_index_idempotently(fresh_db):
    db = make_engine(TEST_DB_URL)
    try:
        async with db.begin() as c:
            await c.execute(text('DROP INDEX ix_tip_hold_observation_key'))
        await create_all(db)
        await create_all(db)
        async with db.connect() as c:
            definition = await c.scalar(text("SELECT indexdef FROM pg_indexes WHERE indexname='ix_tip_hold_observation_key'"))
        assert 'UNIQUE INDEX' in definition
    finally:
        await db.dispose()
