"""Arming a plan whose last session has already closed is REFUSED at the runner
(PLATFORM-RULES, 2026-09-01): 22 stale runs from a finished analyst batch were
armed after the close and expired on arrival. `execution.arm_expired_plans`
(default off) is the replay/test escape hatch; restore() is never gated."""
import pytest

from .test_technique_walkforward import rig  # noqa: F401 - synthetic market ending days ago


async def test_runner_refuses_a_plan_for_a_closed_session(rig):
    # the rig seeds the escape hatch (its plans are for past days); turn it off
    await rig.eng.settings.set("execution.arm_expired_plans", False, journal=False)
    run = await rig.svc.analyze("TEST", as_of_ms=rig.sessions[rig.close_day][-1].ts, plan=True, wait=True)
    assert run["mode"] == "plan" and run["result"]["plan"]["planFor"] < "2099-01-01"
    with pytest.raises(ValueError, match="session .* is over"):
        await rig.svc.arm_plan(run["id"], {"instrument": "shares"})
    assert run["id"] not in rig.svc.armer._armed          # nothing half-armed left behind
    r = await rig.client.post(f"/api/technique/runs/{run['id']}/arm", json={"instrument": "shares"})
    assert r.status_code == 400 and "session" in r.json()["detail"]
    # the escape hatch (replays, tests) arms it
    await rig.eng.settings.set("execution.arm_expired_plans", True, journal=False)
    armed = await rig.svc.arm_plan(run["id"], {"instrument": "shares"})   # the rig has options off
    assert armed["status"] == "armed"
    await rig.svc.armer.disarm(run["id"], reason="test")
