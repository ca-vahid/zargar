"""2026-09-23: outcome starvation. The loop scored the 25 NEWEST runs; ~300 plan runs a night for a session that had not
started took every slot, and nothing after 2026-09-18 was ever scored. Future-session plans are now skipped and finished
sessions are scored oldest first; a run that keeps failing is set aside after 3 attempts."""
import datetime as dt

from zargar.models import TechniqueRun
from zargar.domain import new_id

from .test_technique_arming import rig  # noqa: F401  (rig is a fixture)


def _run(plan_for: str, created: dt.datetime) -> TechniqueRun:
    return TechniqueRun(id=new_id(), symbol="TEST", technique="enhanced_market", trigger="experiment", status="done", mode="plan",
                        as_of=int((created - dt.timedelta(hours=1)).timestamp() * 1000), created_at=created,
                        result={"plan": {"planFor": plan_for, "triggers": []}}, config={}, facts={})


async def test_future_sessions_are_skipped_and_finished_ones_scored_oldest_first(rig, monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    past_old = _run((now - dt.timedelta(days=6)).date().isoformat(), now - dt.timedelta(days=7))
    past_new = _run((now - dt.timedelta(days=3)).date().isoformat(), now - dt.timedelta(days=4))
    future = [_run((now + dt.timedelta(days=5)).date().isoformat(), now - dt.timedelta(minutes=30 + i)) for i in range(5)]
    async with rig.eng.sf() as s:
        s.add_all([past_old, past_new, *future])
        await s.commit()
    seen = []

    async def fake_score(rid, **kw):
        seen.append(rid)
        return []
    monkeypatch.setattr(rig.svc, "score_run", fake_score)
    out = await rig.svc.score_pending(limit=2)
    assert seen == [past_old.id, past_new.id], "oldest finished session first; the future-session plans never take a slot"
    assert not set(seen) & {f.id for f in future}
    assert out["failed"] == []


async def test_a_run_that_keeps_failing_is_set_aside(rig, monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    broken = _run((now - dt.timedelta(days=6)).date().isoformat(), now - dt.timedelta(days=7))
    good = _run((now - dt.timedelta(days=3)).date().isoformat(), now - dt.timedelta(days=4))
    async with rig.eng.sf() as s:
        s.add_all([broken, good])
        await s.commit()
    calls = []

    async def fake_score(rid, **kw):
        calls.append(rid)
        if rid == broken.id:
            raise RuntimeError("bars unavailable")
        return []
    monkeypatch.setattr(rig.svc, "score_run", fake_score)
    for _ in range(3):
        await rig.svc.score_pending(limit=1)
    assert calls == [broken.id] * 3, "the broken run is at the head for its three attempts"
    await rig.svc.score_pending(limit=1)
    assert calls[-1] == good.id, "then it is set aside and the queue moves on"
