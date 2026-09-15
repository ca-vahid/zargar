"""Restart readiness must include the Tips paid-work rows, not only EM."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.models import TipAnalystRun
from zargar.ops import restart_state

from .test_tip_knowledge import app_client  # noqa: F401


async def test_running_tip_audit_is_visible_to_restart_readiness(app_client):  # noqa: F811
    _, eng = app_client
    eng.technique = NS(status=AsyncMock(return_value={"running": []}))
    async with eng.sf() as session:
        session.add(TipAnalystRun(id="active-tip-audit", ticker="NOTES", source="review",
                                 status="running", kind="rule_audit", model="offline",
                                 tools=[], trace=[], tip={}, opinion={}))
        await session.commit()
    state = await restart_state(eng)
    assert state["inflightRuns"] >= 1, "A running Tips audit disappeared behind the EM-only count"
