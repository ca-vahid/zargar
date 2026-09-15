"""KFIN-02: bounded, resumable audit judgments. A scope's notes are judged in
deterministic note-boundary chunks (complete input manifest, stable chunk
ids = hash of the ordered (id, revision) pairs), per-chunk progress persists
on the cycle row, unfinished chunks resume across a restart, a changed
revision invalidates and re-plans the affected chunk, each chunk is
judged and applied/proposed exactly once, cross-chunk merges stay
propose-only with complete references, and a cancelled second attempt keeps
the first completed call's evidence. Disposable test DB only, no paid calls."""
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from zargar.db import make_engine, make_session_factory
from zargar.models import TipAnalystRun, TipKnowledgeBatch, TipKnowledgeCycle, TipNote
from zargar.signals.service import SignalService
from zargar.techniques.tip import rule_audit

from .conftest import TEST_DB_URL, wait_for


@pytest.fixture
async def eng(fresh_db):
    db = make_engine(TEST_DB_URL)
    e = NS(sf=make_session_factory(db),
           settings={"techniques.tip.knowledge_apply_enabled": False,
                     "techniques.tip.audit_chunk_notes": 2,
                     "techniques.tip.knowledge_audit_max_chunks": 24},
           config=NS(anthropic_api_key="", extraction_model="offline"),
           journal=NS(append=AsyncMock()))
    e.signals_service = SignalService(e, None)
    yield e
    await db.dispose()


class _Judge:
    """Scripted judge: records every request header; answers from a queue
    of (text, usage) or with an empty opinion; hangs when told to."""

    def __init__(self, replies=None, *, hang_after: int | None = None):
        self.headers: list[str] = []
        self.replies = list(replies or [])
        self.hang_after = hang_after
        self.messages = NS(create=self._create)

    async def _create(self, **kw):
        self.headers.append(kw["messages"][0]["content"])
        if self.hang_after is not None and len(self.headers) > self.hang_after:
            await asyncio.Event().wait()
        text, usage = self.replies.pop(0) if self.replies else ("{}", (100, 5))
        return NS(content=[NS(type="text", text=text)],
                  usage=(NS(input_tokens=usage[0], output_tokens=usage[1]) if usage else None),
                  stop_reason="end_turn")


def _ids_in(header: str) -> list[str]:
    import re
    return re.findall(r"\[([0-9a-f]{32})\]", header)


async def _seed(svc, scope: str, n: int) -> list[str]:
    ids = []
    for i in range(n):
        ids.append((await svc.add_tip_note(scope, f"{scope} evidence {i} (retro 2026-09-1{i})",
                                           family_dedupe=False))["id"])
    return sorted(ids)


async def _cycle_row(eng) -> TipKnowledgeCycle:
    async with eng.sf() as session:
        rows = (await session.execute(select(TipKnowledgeCycle))).scalars().all()
    assert len(rows) == 1
    return rows[0]


async def _batches(eng) -> list[TipKnowledgeBatch]:
    async with eng.sf() as session:
        return (await session.execute(select(TipKnowledgeBatch).order_by(TipKnowledgeBatch.created_at))).scalars().all()


def _count_applies(svc) -> list:
    calls: list = []
    real = svc.apply_knowledge_batch

    async def spy(**kw):
        calls.append(kw)
        return await real(**kw)
    svc.apply_knowledge_batch = spy
    return calls


def _restart(eng) -> None:
    """A new process holds no in-memory audit state — it hydrates from the DB."""
    delattr(eng, "_tip_audit_state")


def test_plan_chunks_is_deterministic_and_note_bounded():
    notes = [{"id": f"{i:032x}", "text": "x" * 10, "revisionNo": 1} for i in range(5)]
    a = rule_audit._plan_chunks(list(reversed(notes)), max_notes=2, max_chars=10_000)
    b = rule_audit._plan_chunks(notes, max_notes=2, max_chars=10_000)
    assert [c["chunkId"] for c in a] == [c["chunkId"] for c in b]
    assert [len(c["notes"]) for c in a] == [2, 2, 1]
    assert [[m[0] for m in c["manifest"]] for c in a] == [[n["id"] for n in notes[0:2]],
                                                         [n["id"] for n in notes[2:4]],
                                                         [n["id"] for n in notes[4:5]]]
    notes[1]["revisionNo"] = 2                            # one revision -> only that chunk's id moves
    c = rule_audit._plan_chunks(notes, max_notes=2, max_chars=10_000)
    assert c[0]["chunkId"] != a[0]["chunkId"] and c[1]["chunkId"] == a[1]["chunkId"]
    big = [{"id": f"{i:032x}", "text": "y" * 5000, "revisionNo": 1} for i in range(3)]
    assert [len(x["notes"]) for x in rule_audit._plan_chunks(big, max_notes=40, max_chars=6000)] == [1, 1, 1]


async def test_oversized_scope_completes_through_bounded_chunks(eng):
    svc = eng.signals_service
    ids = await _seed(svc, "ticker:TSLA", 5)
    applies = _count_applies(svc)
    judge = _Judge()
    rep: dict = {}
    out = await rule_audit.run_knowledge_audit(eng, client=judge, report=rep)
    assert rep["status"] == "done" and out["groups"] == 1, rep
    assert len(judge.headers) == 3
    seen = [_ids_in(h) for h in judge.headers]
    assert [len(s) for s in seen] == [2, 2, 1] and sorted(sum(seen, [])) == ids
    assert all(f"CHUNK {i + 1} of 3" in h and "ticker:TSLA" in h for i, h in enumerate(judge.headers))
    # per-chunk usage on the run, each call tied to its chunk
    assert len(out["usage"]) == 3 and all(u["inputTokens"] == 100 and u["chunkId"] for u in out["usage"])
    assert out["chunks"]["ticker:TSLA"] == {"planned": 3, "done": 3, "pending": 0, "failed": 0,
                                           "notes": 5, "overflow": True, "invalidated": 0}
    assert out["cycle"]["overflow"] == ["ticker:TSLA"] and out["cycle"]["status"] == "done"
    # persisted progress: manifest + stable chunk ids + every chunk done, once
    cyc = await _cycle_row(eng)
    prog = cyc.progress["ticker:TSLA"]
    assert prog["status"] == "done" and prog["manifest"]["chunks"] == 3 and prog["manifest"]["overflow"]
    assert [prog["chunks"][cid]["status"] for cid in prog["manifest"]["chunkIds"]] == ["done"] * 3
    assert sum(len(prog["chunks"][cid]["manifest"]) for cid in prog["manifest"]["chunkIds"]) == 5
    receipts = await _batches(eng)
    assert len(receipts) == 3 == len(applies) and len({b.id for b in receipts}) == 3
    assert all(b.status == "proposed" for b in receipts)
    assert {b.id for b in receipts} == {f"{out['runId']}:ticker:TSLA:{cid}" for cid in prog["manifest"]["chunkIds"]}
    async with eng.sf() as session:
        run = await session.get(TipAnalystRun, out["runId"])
    assert run.status == "done" and run.opinion["chunks"]["ticker:TSLA"]["done"] == 3


async def test_interrupted_cycle_resumes_unfinished_chunks_after_restart(eng):
    svc = eng.signals_service
    eng.settings["techniques.tip.knowledge_audit_max_chunks"] = 1
    ids = await _seed(svc, "source:Alpha", 5)
    applies = _count_applies(svc)
    judge = _Judge()
    rep: dict = {}
    await rule_audit.run_knowledge_audit(eng, client=judge, report=rep)
    assert rep["status"] == "partial" and "chunk budget" in rep["reason"], rep
    assert len(judge.headers) == 1 and _ids_in(judge.headers[0]) == ids[:2]
    cyc = await _cycle_row(eng)
    prog = cyc.progress["source:Alpha"]
    assert prog["status"] == "pending" and prog["attempts"] == 0     # progress, not a failure
    assert [prog["chunks"][c]["status"] for c in prog["manifest"]["chunkIds"]] == ["done", "pending", "pending"]
    first_batch = prog["chunks"][prog["manifest"]["chunkIds"][0]]["batchId"]

    _restart(eng)                                                     # in-memory state gone
    rep2: dict = {}
    await rule_audit.run_knowledge_audit(eng, client=judge, report=rep2)
    assert rep2["status"] == "partial"
    assert len(judge.headers) == 2 and _ids_in(judge.headers[1]) == ids[2:4]   # chunk 0 NOT re-judged
    cyc = await _cycle_row(eng)
    prog = cyc.progress["source:Alpha"]
    assert prog["chunks"][prog["manifest"]["chunkIds"][0]]["batchId"] == first_batch  # reused
    assert cyc.status == "open"

    _restart(eng)
    rep3: dict = {}
    out = await rule_audit.run_knowledge_audit(eng, client=judge, report=rep3)
    assert rep3["status"] == "done" and out["cycle"]["status"] == "done", rep3
    assert len(judge.headers) == 3 and _ids_in(judge.headers[2]) == ids[4:]
    cyc = await _cycle_row(eng)
    assert cyc.status == "done" and cyc.progress["source:Alpha"]["status"] == "done"
    # each chunk applied/proposed exactly once across the three runs
    receipts = await _batches(eng)
    assert len(receipts) == 3 == len(applies) and len({b.id for b in receipts}) == 3
    assert sorted(len(json.loads(json.dumps(b.proposal))["expectedRevisions"]) for b in receipts) == [1, 2, 2]


async def test_changed_revision_invalidates_and_replans_the_affected_chunk(eng):
    svc = eng.signals_service
    eng.settings["techniques.tip.knowledge_audit_max_chunks"] = 1
    ids = await _seed(svc, "source:Beta", 4)
    applies = _count_applies(svc)
    judge = _Judge()
    await rule_audit.run_knowledge_audit(eng, client=judge)
    cyc = await _cycle_row(eng)
    prog = cyc.progress["source:Beta"]
    old_chunk0 = prog["manifest"]["chunkIds"][0]
    assert prog["chunks"][old_chunk0]["status"] == "done"
    # a human edits a note the finished chunk judged -> its revision moves
    await svc.update_tip_note(ids[0], text="REVISED by the human after the judgment (retro 2026-09-14)")

    rep: dict = {}
    await rule_audit.run_knowledge_audit(eng, client=judge, report=rep)
    assert rep["status"] == "partial"
    assert len(judge.headers) == 2 and "REVISED by the human" in judge.headers[1]   # re-judged, not reused
    assert _ids_in(judge.headers[1]) == ids[:2]
    cyc = await _cycle_row(eng)
    prog = cyc.progress["source:Beta"]
    new_chunk0 = prog["manifest"]["chunkIds"][0]
    assert new_chunk0 != old_chunk0 and old_chunk0 not in prog["chunks"]
    assert prog["invalidated"][0]["chunkId"] == old_chunk0 and "revised" in prog["invalidated"][0]["reason"]
    assert prog["chunks"][new_chunk0]["status"] == "done" and prog["chunks"][new_chunk0]["manifest"][0] == [ids[0], 2]
    assert prog["manifest"]["chunkIds"][1] in prog["chunks"]                     # the untouched chunk kept its id

    out = await rule_audit.run_knowledge_audit(eng, client=judge, report=rep)
    assert rep["status"] == "done" and len(judge.headers) == 3
    assert len(await _batches(eng)) == 3 == len(applies)
    assert out["chunks"]["source:Beta"]["invalidated"] == 1


async def test_cancelled_second_attempt_preserves_first_call_evidence(eng):
    svc = eng.signals_service
    eng.settings["techniques.tip.audit_chunk_notes"] = 40
    ids = await _seed(svc, "ticker:NVDA", 3)
    judge = _Judge([('{"merges": [', (777, 3000))], hang_after=1)   # attempt 1 malformed, attempt 2 hangs
    task = asyncio.create_task(rule_audit.run_knowledge_audit(eng, client=judge))
    await wait_for(lambda: len(judge.headers) == 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    receipts = await _batches(eng)
    assert len(receipts) == 1 and receipts[0].status == "failed"
    usage = receipts[0].proposal["usage"]
    assert usage[0]["inputTokens"] == 777 and usage[0]["attempt"] == 1        # the paid first attempt
    assert usage[1]["attempt"] == 2 and usage[1]["error"] == "cancelled"
    assert receipts[0].proposal["chunk"]["manifest"] == [[i, 1] for i in ids]
    async with eng.sf() as session:
        runs = (await session.execute(select(TipAnalystRun))).scalars().all()
    assert len(runs) == 1 and runs[0].status == "failed" and runs[0].error is None
    assert runs[0].opinion["error"].startswith("cancelled")
    assert any(u.get("inputTokens") == 777 for u in runs[0].opinion["usage"])
    cyc = await _cycle_row(eng)
    prog = cyc.progress["ticker:NVDA"]
    chunk = prog["chunks"][prog["manifest"]["chunkIds"][0]]
    assert chunk["status"] == "failed" and "cancelled" in chunk["error"]
    assert prog["attempts"] == 0 and prog["status"] == "pending"              # a restart is not a strike
    # the next tick judges the chunk again — once — and completes the cycle
    good = _Judge()
    rep: dict = {}
    out = await rule_audit.run_knowledge_audit(eng, client=good, report=rep)
    assert rep["status"] == "done" and len(good.headers) == 1 and out["groups"] == 1
    assert len(await _batches(eng)) == 2                                     # failed receipt + the proposal


async def test_cross_chunk_merge_stays_a_proposal_with_complete_references(eng):
    svc = eng.signals_service
    eng.settings["techniques.tip.knowledge_apply_enabled"] = True       # apply mode: in-chunk merges land
    ids = await _seed(svc, "ticker:AMD", 4)
    chunk0, chunk1 = ids[:2], ids[2:]
    replies = [
        (json.dumps({"merges": [{"supersedes": [chunk0[0], chunk1[0]], "new_rule": "cross-chunk merge (retro 2026-09-14)",
                                 "why": "looks alike"}], "summary": "c0"}), (100, 5)),
        (json.dumps({"merges": [{"supersedes": chunk1, "new_rule": "in-chunk merge (retro 2026-09-14)"}],
                     "summary": "c1"}), (100, 5)),
    ]
    out = await rule_audit.run_knowledge_audit(eng, client=_Judge(replies))
    assert out["mode"] == "apply" and out["merged"] == 2 and len(out["newNotes"]) == 1   # only the in-chunk merge
    async with eng.sf() as session:
        rows = {i: await session.get(TipNote, i) for i in ids}
    assert rows[chunk0[0]].superseded_by is None and rows[chunk1[0]].superseded_by is not None
    assert rows[chunk1[1]].superseded_by == rows[chunk1[0]].superseded_by
    x = out["crossChunk"]
    assert len(x) == 1 and x[0]["mode"] == "propose" and x[0]["proposedMerges"] == 1
    ref = x[0]["refs"][0]
    assert ref["kind"] == "merge" and ref["ids"] == [chunk0[0], chunk1[0]]
    assert ref["revisions"] == {chunk0[0]: 1, chunk1[0]: 1} and ref["outsideChunk"] == [chunk1[0]]
    assert len(set(ref["chunks"].values())) == 2 and ref["text"].startswith("cross-chunk")
    receipts = {b.id: b for b in await _batches(eng)}
    xb = receipts[x[0]["batchId"]]
    assert xb.id.endswith(":xchunk") and xb.status == "proposed"
    assert xb.proposal["merges"][0]["supersedes"] == [chunk0[0], chunk1[0]]
    assert set(xb.proposal["expectedRevisions"]) == set(ids)               # the whole scope's manifest
    assert sum(1 for b in receipts.values() if b.status == "applied") == 2
    cyc = await _cycle_row(eng)
    prog = cyc.progress["ticker:AMD"]
    assert prog["chunks"][prog["manifest"]["chunkIds"][0]]["crossChunk"]["batchId"] == xb.id


async def test_rulebook_audit_resumes_its_chunks_too(eng):
    """The rulebook pseudo-scope uses the same bounded judgments: a chunk
    budget of one leaves the rest pending (visible), the next tick finishes."""
    svc = eng.signals_service
    eng.settings["techniques.tip.knowledge_audit_max_chunks"] = 1
    ids = await _seed(svc, "rule", 3)
    judge = _Judge()
    cycle = await rule_audit._cycle_for(eng, {})
    rep: dict = {}
    out = await rule_audit.run_rule_audit(eng, client=judge, report=rep, cycle=cycle)
    assert out is None and rep["status"] == "partial" and "deferred" in rep["reason"], rep
    assert _ids_in(judge.headers[0]) == ids[:2] and "CHUNK 1 of 2" in judge.headers[0]
    assert cycle["progress"]["rule"]["status"] == "pending"
    rep2: dict = {}
    out = await rule_audit.run_rule_audit(eng, client=judge, report=rep2, cycle=cycle)
    assert rep2["status"] == "done" and out["chunks"] == {"planned": 2, "done": 2, "pending": 0,
                                                          "failed": 0, "notes": 3, "overflow": True,
                                                          "invalidated": 0}
    assert len(judge.headers) == 2 and _ids_in(judge.headers[1]) == ids[2:]
    assert cycle["progress"]["rule"]["status"] == "done"
    assert len(await _batches(eng)) == 2
