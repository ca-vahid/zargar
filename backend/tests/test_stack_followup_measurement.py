"""Corrected-stack crash/acknowledgment boundaries — measurement half.

Codex follow-up review 2026-09-09 (test_stack_followup.py), split per owning
branch: A4 lives here on the measurement PR (zargar.research.llm_stats exists
only from this branch); A1–A3 live in test_stack_followup.py on the gateway
PR. The test body is verbatim from the reviewer's file."""
from types import SimpleNamespace as NS

import pytest

from zargar.research import llm_stats


@pytest.fixture(autouse=True)
def clean_pending(monkeypatch):
    # pending frozen batches are module-global like _ACC — isolate them too
    monkeypatch.setattr(llm_stats, "_PENDING", {})


async def test_ambiguous_flush_reuses_same_batch_identity(monkeypatch):
    monkeypatch.setattr(llm_stats, "_ACC", {})
    llm_stats.record("extraction", input_tokens=10)
    committed = []

    async def append(kind, payload):
        committed.append(payload)
        if len(committed) == 1:
            raise RuntimeError("commit succeeded but acknowledgment was lost")

    eng = NS(journal=NS(append=append))
    assert await llm_stats.flush(eng) == 0
    assert await llm_stats.flush(eng) == 1
    assert committed[0]["batchId"] == committed[1]["batchId"], committed
