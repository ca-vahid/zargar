"""Armed-plan persistence throttle (2026-10-05, loop saturation; EM review conditions):
a bar that changes ONLY the bar counters skips the write, anything else writes on that bar,
the floor still writes, non-bar callers always write, and the persisted row is exactly the
in-memory state minus the counters - what restore() reads."""
import datetime as dt
import json

from sqlalchemy import select

from zargar.execution import planrunner as pr
from zargar.execution.planrunner import Trade
from zargar.models import TechniqueArmed
from zargar.technique.rulebook import ET

from .test_technique_walkforward import rig  # noqa: F401

MIN = 60_000


async def _row_state(rig, run_id):
    async with rig.eng.sf() as session:
        row = (await session.execute(select(TechniqueArmed).where(TechniqueArmed.run_id == run_id))).scalar_one()
        return dict(row.state or {}), row.updated_at


def _body(state):
    return json.dumps({k: v for k, v in state.items() if k not in ("barsSeen", "lastBarTs")},
                      sort_keys=True, default=str)


async def test_quiet_bars_skip_the_write_and_changes_write_on_their_bar(rig, monkeypatch):
    run = await rig.svc.analyze("TEST", as_of_ms=rig.sessions[rig.close_day][-1].ts, plan=True, wait=True)
    armed = await rig.svc.arm_plan(run["id"], {"instrument": "shares"})
    assert armed["status"] == "armed"
    armer = rig.svc.armer
    ap = armer._armed[run["id"]]
    clock = [1000.0]
    monkeypatch.setattr(pr.time, "monotonic", lambda: clock[0])

    await armer._persist(ap)                                   # an ordinary (non-bar) write: always
    first, _ = await _row_state(rig, ap.run_id)
    base_seen = first.get("barsSeen")

    # 1) only the counters move -> no write
    ap.bar_index = (ap.bar_index or 0) + 3
    ap.last_bar_ts = (ap.last_bar_ts or 0) + 3 * MIN
    clock[0] += 60
    await armer._persist(ap, bar_tick=True)
    st, _ = await _row_state(rig, ap.run_id)
    assert st.get("barsSeen") == base_seen

    # 2) an event (a decision) writes on that bar
    armer._log(ap, "test", "a decision on this bar")
    clock[0] += 60
    await armer._persist(ap, bar_tick=True)
    st, _ = await _row_state(rig, ap.run_id)
    assert st.get("barsSeen") == ap.bar_index
    assert st["events"][-1]["event"] == "test"

    # 3) an opened trade writes on that bar, and the row is the in-memory state minus counters
    day = dt.date.fromisoformat(ap.plan_for)
    ts = int(dt.datetime(day.year, day.month, day.day, 10, 0, tzinfo=ET).timestamp() * 1000)
    ap.trades["r1"] = Trade(trigger_id="r1", kind="bounce", fired_ts=ts, window="am", entry=100.0, stop=99.4,
                            targets=[101.0, 101.5, 102.0], status="open", instrument="shares")
    ap.bar_index += 1
    clock[0] += 60
    await armer._persist(ap, bar_tick=True)
    st, _ = await _row_state(rig, ap.run_id)
    assert [t["triggerId"] if "triggerId" in t else t.get("trigger_id") for t in st["trades"]] == ["r1"]
    assert st["trades"][0]["stop"] == 99.4

    # 4) a per-bar mark on the open trade (its dict changes) writes too
    before = st["trades"][0]
    ap.trades["r1"].stop = 99.8
    ap.bar_index += 1
    clock[0] += 60
    await armer._persist(ap, bar_tick=True)
    st, _ = await _row_state(rig, ap.run_id)
    assert st["trades"][0]["stop"] == 99.8 and st["trades"][0] != before

    # 5) quiet again -> skipped; the stored row still equals memory minus the counters
    ap.bar_index += 1
    clock[0] += 60
    await armer._persist(ap, bar_tick=True)
    st, _ = await _row_state(rig, ap.run_id)
    assert st.get("barsSeen") == ap.bar_index - 1
    mem = json.loads(armer._persist_seen[ap.run_id][0])[0]
    assert _body(st) == json.dumps(mem, sort_keys=True, default=str)

    # 6) the floor: after persist_floor_seconds a quiet bar writes the counters
    clock[0] += 301
    await armer._persist(ap, bar_tick=True)
    st, _ = await _row_state(rig, ap.run_id)
    assert st.get("barsSeen") == ap.bar_index

    # 7) floor 0 = write every bar (rollback knob)
    await rig.eng.settings.set("execution.persist_floor_seconds", 0, journal=False)
    ap.bar_index += 1
    clock[0] += 1
    await armer._persist(ap, bar_tick=True)
    st, _ = await _row_state(rig, ap.run_id)
    assert st.get("barsSeen") == ap.bar_index
    await rig.eng.settings.set("execution.persist_floor_seconds", 300, journal=False)

    # 8) a non-bar caller (disarm/close/roll paths) always writes, even when quiet
    ap.bar_index += 1
    clock[0] += 1
    await armer._persist(ap)
    st, _ = await _row_state(rig, ap.run_id)
    assert st.get("barsSeen") == ap.bar_index

    # 9) a status change writes on the bar (disarm writes its final record)
    await armer.disarm(run["id"], reason="test")
    async with rig.eng.sf() as session:
        row = (await session.execute(select(TechniqueArmed).where(TechniqueArmed.run_id == run["id"]))).scalar_one()
        assert row.status != "armed"
