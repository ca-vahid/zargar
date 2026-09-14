"""Offline knowledge-boundary regressions; no provider or database access."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from zargar.techniques.tip import rule_audit


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    def add(self, _row):
        pass

    async def commit(self):
        pass


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(rule_audit, "_AUDIT_CURSOR", {})
    monkeypatch.setattr(rule_audit, "_CURSOR_HYDRATED", True)
    monkeypatch.setattr(rule_audit, "_finish", AsyncMock())
    notes = [{"id": str(i), "text": "Evidence", "author": "fixture", "createdAt": "2026-09-13",
              "revisionNo": 1} for i in range(3)]
    service = NS(note_scope_counts=AsyncMock(return_value={"source:A": 3, "source:B": 3}),
                 tip_notes=AsyncMock(return_value=notes),
                 apply_knowledge_batch=AsyncMock(return_value={}))
    return NS(settings={"techniques.tip.knowledge_audit_max_groups": 1},
              config=NS(anthropic_api_key="", extraction_model="offline"),
              signals_service=service, sf=_Session, journal=NS(append=AsyncMock()))


async def test_failed_scope_does_not_starve_untouched_scope(engine, monkeypatch):
    seen = []

    async def judge(_client, **kwargs):
        seen.append(kwargs["header"])
        if "source:A" in kwargs["header"]:
            raise ValueError("Repeatable model failure")
        return rule_audit.RuleAuditOpinion(), []

    monkeypatch.setattr(rule_audit, "_judge", judge)
    for _ in range(2):
        await rule_audit.run_knowledge_audit(engine, client=object())
    assert any("source:B" in header for header in seen), "Failed A cannot hold B out forever"


async def test_completed_bounded_cycle_can_advance_completion(engine, monkeypatch):
    monkeypatch.setattr(rule_audit, "_judge", AsyncMock(return_value=(rule_audit.RuleAuditOpinion(), [])))
    statuses = []
    for _ in range(2):
        report = {}
        await rule_audit.run_knowledge_audit(engine, client=object(), report=report)
        statuses.append(report["status"])
    assert "done" in statuses, "A complete cycle must not remain permanently partial with propose-only notes"


async def test_invalid_audit_json_keeps_paid_call_usage(engine):
    engine.signals_service.note_scope_counts.return_value = {"source:A": 3}
    client = NS(messages=NS(create=AsyncMock(return_value=NS(
        content=[NS(type="text", text="{\"merges\": [")],
        usage=NS(input_tokens=777, output_tokens=3000), stop_reason="max_tokens"))))
    result = await rule_audit.run_knowledge_audit(engine, client=client)
    assert sum(call.get("inputTokens", 0) or 0 for call in result["usage"]) >= 777, (
        "The failed audit burned 777 input tokens; its run must retain that usage"
    )
