"""Review upgrade boundaries and the actual execution-monitor DTO contract."""
import pytest

from zargar.techniques.options_cartel.execution_review import review_execution_limits
from zargar.techniques.options_cartel.preparation_scope import SETTING

from .test_options_cartel_execution_review import (
    isolated_review_runtime as isolated_review_runtime,  # noqa: PLC0414
)
from .test_options_cartel_execution_review import legacy_arm


async def test_execution_limit_control_receives_the_real_runtime_dto(engine):
    runtime, run_id = await legacy_arm(engine)
    try:
        row = await runtime.repository.load(run_id)
        detail = runtime.detail(run_id)
        # The UI consumes this DTO, not the repository's raw config dictionary.
        assert "execution" not in detail["config"] and "preparation" not in detail["config"]
        assert detail["preparation"] == {"runId": row["config"]["preparation"]["runId"], "workspace": "practice"}
        assert detail["executionSettings"]["contractPolicy"] is None
        assert detail["portfolio"]["kind"] == "sim" and detail["config"]["mode"] == "auto"
        assert detail["status"] == "armed" and detail["phase"] == "waiting"
        assert not detail["submissionReserved"] and not detail["trades"]
        await review_execution_limits(engine, run_id, clock=runtime.clock)
        assert runtime.detail(run_id)["executionSettings"]["contractPolicy"] is not None
    finally:
        await runtime.stop()


async def test_legacy_upgrade_cannot_replace_an_existing_reviewed_policy(engine):
    runtime, run_id = await legacy_arm(engine)
    try:
        await review_execution_limits(engine, run_id, clock=runtime.clock)
        before = await runtime.repository.load(run_id)
        with pytest.raises(ValueError, match="already has reviewed contract limits"):
            await review_execution_limits(engine, run_id, clock=runtime.clock)
        after = await runtime.repository.load(run_id)
        assert after["config"] == before["config"]
        assert after["state"]["configHistory"] == before["state"]["configHistory"]
    finally:
        await runtime.stop()


@pytest.mark.parametrize("change", [{"enabled": False}, {"budget": 250}])
async def test_policy_change_after_outer_review_check_cannot_publish_limits(engine, monkeypatch, change):
    runtime, run_id = await legacy_arm(engine)
    publish = runtime.arm
    before = await runtime.repository.load(run_id)

    async def change_policy_before_lock(*args, **kwargs):
        await engine.settings.set(SETTING, {**engine.settings.get(SETTING), **change})
        return await publish(*args, **kwargs)

    monkeypatch.setattr(runtime, "arm", change_policy_before_lock)
    try:
        with pytest.raises(ValueError, match="Preparation settings changed during execution-limit review"):
            await review_execution_limits(engine, run_id, clock=runtime.clock)
        after = await runtime.repository.load(run_id)
        assert after["config"] == before["config"]
        assert after["status"] == before["status"] and after["state"]["phase"] == "waiting"
        assert not after["state"].get("attemptTag")
    finally:
        await runtime.stop()
