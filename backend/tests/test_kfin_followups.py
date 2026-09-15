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
    # the release snapshot carries the manifest's ownership marker (KF83-02) and, for a
    # rejection, was written in the same transaction as the expiry (KF83-01)
    assert row.needs_human is False and rec.status == "applied" and any(str(r).startswith("resolve:c:") for r in snaps)
    # identical retry: idempotent replay from the receipt
    again = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[rej])
    assert again.get("replay") is True


async def test_release_without_saved_progress_is_recognised_on_retry(app_client):  # noqa: F811
    """KF83-02: a retry recovers ONLY a transition this manifest wrote - the
    release snapshot carries the manifest's ownership marker; a generic
    resolution by somebody else (same reason shape, same revision arithmetic)
    is a stale review and is refused."""
    from zargar.techniques.tip.consolidation import release_marker
    _, eng = app_client
    svc = eng.signals_service
    # (a) a genuine same-manifest retry: standalone release applied, receipt lost, retry recognises it
    b = await svc.add_tip_note("rule", "RULE (orphan family): proposal.", author="analyst:y")
    await svc.flag_tip_notes([b["id"]], needs_human=True)
    async with eng.sf() as session:
        rev = await session.scalar(select(TipNote.revision_no).where(TipNote.id == b["id"]))
    resolve = [{"id": b["id"], "revision": rev}]
    h = payload_hash(resolve=resolve, batches=[], evidence=[])
    first = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[])
    assert first["resolved"][0]["revisionTo"] == rev + 1
    async with eng.sf() as session:
        last = (await session.execute(select(TipNoteRevision.reason).where(TipNoteRevision.note_id == b["id"])
                                      .order_by(TipNoteRevision.known_until.desc()).limit(1))).scalar()
        assert last == release_marker(h), "the release snapshot names the manifest"
        rec = await session.get(TipKnowledgeBatch, f"consolidation:{h}")
        await session.delete(rec)                       # the receipt vanished after the commit
        await session.commit()
    again = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[])
    assert again["resolved"][0].get("recovered") is True and again["resolved"][0]["revisionTo"] == rev + 1
    # (b) somebody else's generic resolution at the same arithmetic is NOT ownership
    c = await svc.add_tip_note("rule", "RULE (other family): proposal.", author="analyst:z")
    await svc.flag_tip_notes([c["id"]], needs_human=True)
    async with eng.sf() as session:
        rev_c = await session.scalar(select(TipNote.revision_no).where(TipNote.id == c["id"]))
    resolve_c = [{"id": c["id"], "revision": rev_c}]
    rej_c = {"batchId": "other-reject", "scope": "rule", "expire": {"ids": [c["id"]], "reason": "x"},
             "expected_revisions": {c["id"]: rev_c}, "author": "review"}
    hc = payload_hash(resolve=resolve_c, batches=[rej_c], evidence=[])
    await svc.flag_tip_notes([c["id"]], needs_human=False)          # an independent user action
    with pytest.raises(ValueError, match="not disputed"):
        await apply_consolidation(eng, manifest_hash=hc, resolve=resolve_c, batches=[rej_c])
    async with eng.sf() as session:
        row = await session.get(TipNote, c["id"])
    assert row.superseded_by is None, "a stale review expired nothing"


async def test_rejection_keeps_the_rule_non_operative_until_the_expiry_commits(app_client, monkeypatch):  # noqa: F811
    """KF83-01: the release of a reviewed REJECTION happens inside the expiry's
    transaction. A failure at the expiry leaves the row disputed (never an
    undisputed live rule); the retry completes ONE rejection; the batch receipt
    is the durable ownership proof a retry recovers from."""
    _, eng = app_client
    svc = eng.signals_service
    a = await svc.add_tip_note("rule", "RULE (kf83 family): proposal.", author="analyst:x")
    await svc.flag_tip_notes([a["id"]], needs_human=True)
    async with eng.sf() as session:
        rev = await session.scalar(select(TipNote.revision_no).where(TipNote.id == a["id"]))
    resolve = [{"id": a["id"], "revision": rev}]
    rej = {"batchId": "kf83-reject", "scope": "rule", "expire": {"ids": [a["id"]], "reason": "reviewed rejection"},
           "expected_revisions": {a["id"]: rev}, "author": "review"}
    h = payload_hash(resolve=resolve, batches=[rej], evidence=[])
    real = svc.apply_knowledge_batch
    calls = {"n": 0}

    async def flaky(*args, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("expiry unavailable")
        return await real(*args, **kw)
    monkeypatch.setattr(svc, "apply_knowledge_batch", flaky)
    with pytest.raises(OSError):
        await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[rej])
    async with eng.sf() as session:
        row = await session.get(TipNote, a["id"])
    assert row.needs_human and row.superseded_by is None and int(row.revision_no) == rev, \
        "a failed expiry leaves the rejected rule disputed (non-operative), untouched"
    out = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[rej])
    assert out["resolved"][0]["viaBatch"] == "kf83-reject" and out["batches"]["kf83-reject"]["kind"] == "expire"
    async with eng.sf() as session:
        row = await session.get(TipNote, a["id"])
        rec = await session.get(TipKnowledgeBatch, "kf83-reject")
    assert row.superseded_by and not row.needs_human and int(row.revision_no) == rev + 2
    assert (rec.applied or {}).get("released", [{}])[0].get("id") == a["id"]
    # the wrapper receipt lost, the batch receipt alone recovers the release: identical retry = recovered, no second mutation
    async with eng.sf() as session:
        wrec = await session.get(TipKnowledgeBatch, f"consolidation:{h}")
        await session.delete(wrec)
        await session.commit()
    again = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, batches=[rej])
    assert again["resolved"][0].get("recovered") is True
    async with eng.sf() as session:
        row = await session.get(TipNote, a["id"])
    assert int(row.revision_no) == rev + 2


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


async def test_delayed_sample_timing_and_provenance_eligibility(app_client, monkeypatch):  # noqa: F811
    """KF83-03/04: a timely recovery is the delay variant's evidence, a late
    one is a diagnostic, a delayed chain quote / no source time / a crossed
    quote is never executable evidence, and a qualified OPRA observation is."""
    _, eng = app_client
    from zargar.domain import new_id
    from zargar.models import TipEntryCohortRow
    now = dt.datetime.now(dt.timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    opra = {"symbol": "X260101C00100000", "bid": 1.0, "ask": 1.1, "last": 1.05, "source": "opra", "sourceTs": now_ms - 2000,
            "ageSeconds": 2.0, "delayed": False, "quoteStatus": "fresh"}
    a = cohort.assumptions(eng.settings)
    # (04) provenance
    st, why = cohort.qualify_quote({**opra, "source": "chain", "delayed": True}, is_option=True, max_age_s=300, now_ms=now_ms, check_session=False)
    assert st == "ineligible" and any("chain" in w for w in why) and any("delayed" in w for w in why)
    st, why = cohort.qualify_quote({**opra, "sourceTs": 0}, is_option=True, max_age_s=300, now_ms=now_ms, check_session=False)
    assert st == "ineligible" and any("source time" in w for w in why)
    st, _ = cohort.qualify_quote({**opra, "sourceTs": now_ms + 60_000}, is_option=True, max_age_s=300, now_ms=now_ms, check_session=False)
    assert st == "ineligible"
    st, _ = cohort.qualify_quote({**opra, "bid": 1.2}, is_option=True, max_age_s=300, now_ms=now_ms, check_session=False)
    assert st == "ineligible"
    st, _ = cohort.qualify_quote(opra, is_option=True, max_age_s=300, now_ms=now_ms, check_session=False)
    assert st == "fresh"
    row_ok = {"id": "r", "ticker": "X", "quoteSymbol": opra["symbol"], "quoteAtDecision": opra, "quoteStatus": "fresh"}
    assert cohort.simulate_variants(row_ok, a, variants=("immediate",))[0]["adequate"] is True
    row_bad = {**row_ok, "quoteAtDecision": {**opra, "source": "chain", "delayed": True}, "quoteStatus": "fresh"}
    assert cohort.simulate_variants(row_bad, a, variants=("immediate",))[0]["adequate"] is False, "a stored label is re-judged"
    # (03) timing: timely = sampled/eligible, late = diagnostic
    await eng.settings.set("techniques.tip.entry_cohort_enabled", True, journal=False)
    monkeypatch.setattr(cohort, "_snap_quote", lambda *ar, **kw: ({**opra, "sampleKind": "delayed"}, "fresh"))
    timely = TipEntryCohortRow(id=new_id(), signal_id=new_id(), ticker="X", action="open", decision="declined",
                               decision_kind="intake", quote_symbol=opra["symbol"], delayed_status="pending",
                               delayed_due_at=now - dt.timedelta(seconds=20), gaps=[])
    late = TipEntryCohortRow(id=new_id(), signal_id=new_id(), ticker="X", action="open", decision="declined",
                             decision_kind="intake", quote_symbol=opra["symbol"], delayed_status="pending",
                             delayed_due_at=now - dt.timedelta(minutes=9), gaps=[])
    async with eng.sf() as session:
        session.add(timely)
        session.add(late)
        await session.commit()
    r1 = await cohort.sample_one(eng, timely.id)
    r2 = await cohort.sample_one(eng, late.id)
    assert r1["delayedStatus"] == "sampled" and r1["delayedSample"]["eligible"] is True
    assert r2["delayedStatus"] == "late" and r2["delayedSample"]["eligible"] is False and r2["delayedSample"]["latenessSeconds"] > 60
    v1 = cohort.simulate_variants(r1, a, variants=("delay",))[0]
    v2 = cohort.simulate_variants(r2, a, variants=("delay",))[0]
    assert v1["adequate"] is True and v2["adequate"] is False and "diagnostic" in v2["reason"]
    # a finalized row is left alone by a racing second call
    again = await cohort.sample_one(eng, late.id)
    assert again["delayedStatus"] == "late"
