"""Research timing and cohort boundaries; no model or trading calls."""
import datetime as dt
from types import SimpleNamespace as NS
from sqlalchemy import select
from zargar.models import TipHoldSnapshotRow
from zargar.techniques.tip import holdstudy as hs
from .test_kfin_followup_boundaries_review import review_engine  # noqa: F401


def install_position(eng, monkeypatch):
    eng.position_manager = NS(positions=lambda: [{
        "id": "position", "portfolioId": "practice", "technique": "tip", "status": "open",
        "symbol": "XYZ", "entry": 100, "direction": "long", "state": {"stop": 95},
        "legs": [{"symbol": "XYZ", "secType": "STK", "qty": 10, "avgFill": 100}],
        "policy": {"stop": {"price": 95}, "time_stop_sessions": 5}, "tags": []}])
    monkeypatch.setattr(hs, "_snap", lambda *a, **kw: ({"bid": 101, "ask": 102}, "fresh"))


async def test_after_close_boot_does_not_create_qualified_preclose_evidence(review_engine, monkeypatch):
    eng = review_engine
    install_position(eng, monkeypatch)
    await hs.snapshot_preclose(eng, now=dt.datetime(2026, 9, 15, 22, tzinfo=dt.timezone.utc))
    async with eng.sf() as session:
        rows = (await session.execute(select(TipHoldSnapshotRow))).scalars().all()
    assert all(r.preclose_status != "fresh" for r in rows), "18:00 ET observation was labeled qualified pre-close evidence"


async def test_missed_next_session_cannot_be_replaced_by_a_later_day(review_engine, monkeypatch):
    eng = review_engine
    install_position(eng, monkeypatch)
    await hs.snapshot_preclose(eng, now=dt.datetime(2026, 9, 14, 19, 50, tzinfo=dt.timezone.utc))
    await hs.sample_next_open(eng, now=dt.datetime(2026, 9, 17, 13, 36, tzinfo=dt.timezone.utc))
    async with eng.sf() as session:
        rows = (await session.execute(select(TipHoldSnapshotRow))).scalars().all()
    assert all(r.next_open_status != "fresh" for r in rows), "Thursday replaced Tuesday's missing next-open observation"


async def test_replayed_preclose_capture_is_one_observation(review_engine, monkeypatch):
    eng = review_engine
    install_position(eng, monkeypatch)
    when = dt.datetime(2026, 9, 15, 19, 50, tzinfo=dt.timezone.utc)
    await hs.snapshot_preclose(eng, now=when)
    await hs.snapshot_preclose(eng, now=when)
    async with eng.sf() as session:
        rows = (await session.execute(select(TipHoldSnapshotRow))).scalars().all()
    assert len(rows) == 1, "repeated capture double-counts the same position/session"


def test_hold_net_includes_entry_and_exit_fees():
    r = hs.compare_row({"id": "r", "arm": "carry", "symbol": "XYZ", "secType": "OPT", "qty": 2,
        "entryPrice": 1.5, "multiplier": 100, "plannedRisk": 150,
        "precloseQuote": {"bid": 1.4}, "precloseStatus": "fresh",
        "nextOpenQuote": {"bid": 1.8}, "nextOpenStatus": "fresh"}, fee_per_contract=1)
    assert r["intradayExit"]["net"] == -24 and r["carryToNextOpen"]["net"] == 56
