"""The nav's registry marks a switched-off technique as retired (2026-10-05, Team2 retired)."""
from __future__ import annotations

import httpx

from zargar.api.app import create_app

from .test_team2_runner import rig  # noqa: F401


async def test_a_disabled_technique_is_listed_as_retired_and_nothing_else_is(rig):
    eng, _ = rig
    transport = httpx.ASGITransport(app=create_app(eng.config, eng))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        before = {t["id"]: t for t in (await client.get("/api/techniques")).json()}
        assert before["team2"]["retired"] is False and not any(t["retired"] for t in before.values())
        await eng.settings.set("techniques.team2.enabled", False)
        after = {t["id"]: t for t in (await client.get("/api/techniques")).json()}
        assert after["team2"]["retired"] is True
        assert [i for i, t in after.items() if t["retired"]] == ["team2"]
        assert after["enhanced_market"]["retired"] is False, "a technique without the key is never retired"
