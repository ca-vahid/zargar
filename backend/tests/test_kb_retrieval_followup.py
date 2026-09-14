"""Independent KB maintenance boundaries; offline mocks, no database/paid calls."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

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


async def test_bounded_audit_eventually_visits_deferred_groups(monkeypatch):
    """Stable eligible scopes must not starve behind the alphabetic first group."""
    notes = [{"id": str(i), "text": "Independent evidence", "author": "fixture",
              "createdAt": "2026-09-13", "citedCount": 0} for i in range(3)]
    service = NS(
        note_scope_counts=AsyncMock(return_value={"source:A": 3, "source:B": 3}),
        tip_notes=AsyncMock(return_value=notes),
        apply_knowledge_batch=AsyncMock(return_value={}),
    )
    eng = NS(settings={"techniques.tip.knowledge_audit_max_groups": 1},
             config=NS(anthropic_api_key="", extraction_model="offline"),
             signals_service=service, sf=_Session,
             journal=NS(append=AsyncMock()))
    client = NS(messages=NS(create=AsyncMock(return_value=NS(
        content=[NS(type="text", text="{}")], usage=None, stop_reason="end_turn"))))
    monkeypatch.setattr(rule_audit, "_finish", AsyncMock())
    for _ in range(2):
        await rule_audit.run_knowledge_audit(eng, client=client)
    audited = {call.kwargs["scope"] for call in service.apply_knowledge_batch.await_args_list}
    assert audited == {"source:A", "source:B"}, "Deferred groups must make forward progress"


async def test_missing_provider_credentials_are_not_a_completed_maintenance(monkeypatch):
    """A precondition skip must not suppress catch-up as a successful completion."""
    eng = NS(settings={}, config=NS(anthropic_api_key="", extraction_model="offline"),
             journal=NS(append=AsyncMock()))
    monkeypatch.setattr(rule_audit, "_last_completion", AsyncMock(return_value=None))
    monkeypatch.setattr(rule_audit, "audit_due_today", lambda _settings: False)
    result = await rule_audit.run_knowledge_maintenance(eng)
    assert result["ruleAuditStatus"]["reason"] == "no api key"
    assert result["knowledgeAuditStatus"]["reason"] == "no api key"
    assert result["status"] != "done", "No audit ran; do not mark this as a completion"
