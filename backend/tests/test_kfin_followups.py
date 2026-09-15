"""Review follow-ups after the KFIN packet (2026-09-15): consolidation retry
safety, delayed-sample recovery, attachment coverage on the signal."""
import datetime as dt

import pytest
from sqlalchemy import select

from zargar.models import TipKnowledgeBatch, TipNote, TipNoteRevision
from zargar.techniques.tip import cohort
from zargar.techniques.tip.consolidation import apply_consolidation, payload_hash

from .test_tip_knowledge import app_client  # noqa: F401


async def test_release_commits_with_progress_and_retries_after_a_failed_notification(app_client, monkeypatch):  # noqa: F811
    """The reproduced defect: the dispute release committed, the notification
    raised, the wrapper progress was never saved and the identical retry then
    failed with 'not disputed'. Now the transition and the progress commit
    together; the journal is best-effort; the retry recognises the release."""
    _, eng = app_client
    svc = eng.signals_service
    await eng.settings.set("techniques.tip.knowledge_apply_enabled", False, journal=False)
    a = await svc.add_tip_note("rule", "RULE (retry family): proposal.", author="analyst:x")
    await svc.flag_tip_notes([a["id"]], needs_human=True)
    async with eng.sf() as session:
        rev = await session.scalar(select(TipNote.revision_no).where(TipNote.id == a["id"]))
    resolve = [{"id": a["id"], "revision": rev}]
    rej = {"batchId": "retry-reject", "scope": "rule", "expire": {"ids": [a["id"]], "reason": "reviewed rejection"},
           "expected_revisions": {a["id"]: rev}, "author": "review"}
    h = payload_hash(resolve=resolve, batches=[rej], evidence=[])
    real_append = eng.journal.append
    calls = {"n": 0}

    async def flaky_append(kind, payload, **kw):
        if kind == "TipRuleAudited" and (payload or {}).get("resolved") and calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("journal down")
        return await real_append(kind, payload, **kw)
    monkeypatch.setattr(eng.journal, "append", flaky_append)
    # first attempt: the release commits, the notification fails, the apply continues
    out = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[rej])
    assert out["resolved"][0]["revisionTo"] == rev + 1 and out["batches"]["retry-reject"]["kind"] == "expire"
    async with eng.sf() as session:
        row = await session.get(TipNote, a["id"])
        rec = await session.get(TipKnowledgeBatch, f"consolidation:{h}")
        snaps = (await session.execute(select(TipNoteRevision.reason).where(TipNoteRevision.note_id == a["id"]))).scalars().all()
    assert row.needs_human is False and rec.status == "applied" and "resolve" in snaps
    # identical retry: idempotent replay from the receipt
    again = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[rej])
    assert again.get("replay") is True


async def test_release_without_saved_progress_is_recognised_on_retry(app_client):  # noqa: F811
    """Even if the receipt row vanished after a committed release, the retry
    validates the row as 'released by this manifest' (reviewed revision + 1
    with a resolve snapshot) instead of refusing it as 'not disputed'."""
    _, eng = app_client
    svc = eng.signals_service
    b = await svc.add_tip_note("rule", "RULE (orphan family): proposal.", author="analyst:y")
    await svc.flag_tip_notes([b["id"]], needs_human=True)
    async with eng.sf() as session:
        rev = await session.scalar(select(TipNote.revision_no).where(TipNote.id == b["id"]))
    resolve = [{"id": b["id"], "revision": rev}]
    rej = {"batchId": "orphan-reject", "scope": "rule", "expire": {"ids": [b["id"]], "reason": "reviewed rejection"},
           "expected_revisions": {b["id"]: rev}, "author": "review"}
    h = payload_hash(resolve=resolve, batches=[rej], evidence=[])
    # simulate the old failure shape: the release committed (resolve snapshot), no receipt at all
    await svc.flag_tip_notes([b["id"]], needs_human=False)
    out = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[rej])
    assert out["resolved"][0].get("recovered") is True and out["resolved"][0]["revisionTo"] == rev + 1
    assert out["batches"]["orphan-reject"]["expired"][0]["id"] == b["id"]
    # a rule released by SOMEONE ELSE at a different revision is still refused
    c = await svc.add_tip_note("rule", "RULE (other family): proposal.", author="analyst:z")
    await svc.flag_tip_notes([c["id"]], needs_human=True)
    await svc.flag_tip_notes([c["id"]], needs_human=False)
    await svc.flag_tip_notes([c["id"]], needs_human=True)
    await svc.flag_tip_notes([c["id"]], needs_human=False)          # two transitions past the reviewed revision
    resolve_c = [{"id": c["id"], "revision": 1}]
    rej_c = {"batchId": "other-reject", "scope": "rule", "expire": {"ids": [c["id"]], "reason": "x"},
             "expected_revisions": {c["id"]: 1}, "author": "review"}
    hc = payload_hash(resolve=resolve_c, batches=[rej_c], evidence=[])
    with pytest.raises(ValueError, match="not disputed"):
        await apply_consolidation(eng, manifest_hash=hc, resolve=resolve_c, batches=[rej_c])


async def test_delayed_samples_are_recovered_after_a_restart(app_client):  # noqa: F811
    """A pending row whose due time passed while the process was down is
    picked up by the recovery pass (the in-process timer is gone); one far
    past its grace is MISSED, never back-labeled."""
    _, eng = app_client
    from zargar.domain import new_id
    from zargar.models import TipEntryCohortRow
    await eng.settings.set("techniques.tip.entry_cohort_enabled", True, journal=False)
    now = dt.datetime.now(dt.timezone.utc)
    due_recent = now - dt.timedelta(seconds=30)
    due_old = now - dt.timedelta(hours=3)
    rows = []
    for due in (due_recent, due_old):
        r = TipEntryCohortRow(id=new_id(), signal_id=new_id(), ticker="AAPL", action="open", decision="declined", decision_kind="intake",
                              quote_symbol="AAPL", delayed_status="pending", delayed_due_at=due, gaps=[])
        rows.append(r)
    async with eng.sf() as session:
        for r in rows:
            session.add(r)
        await session.commit()
    await eng.ensure_symbol("AAPL")
    n = await cohort.sample_due(eng)
    assert n == 2
    async with eng.sf() as session:
        recent = await session.get(TipEntryCohortRow, rows[0].id)
        old = await session.get(TipEntryCohortRow, rows[1].id)
    assert recent.delayed_status in ("sampled", "missed") and recent.delayed_status != "pending"
    assert old.delayed_status == "missed" and any("missed" in g for g in old.gaps)
    # the loop is wired into the engine's background tasks
    assert any(t.get_name() == "tip-cohort-recovery" for t in eng._tasks)
