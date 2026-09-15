"""Intake liveness: envelopes briefly in flight are not a stall (2026-09-15:
the monitor flapped Stalled/Recovered every two minutes during a busy session
because any pending count at the sample was a stall reason)."""
import datetime as dt
import json

from zargar.techniques.tip import intake_liveness as il

from .test_proposal_readiness import rig  # noqa: F401


def _status(base, pending: int):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    (base / il.STATUS_FILE).write_text(json.dumps({
        "pid": 1, "at": now, "state": "connected", "connectedAt": now, "lastFrameAt": now, "lastMessageAt": now,
        "reconnects": 0, "ledger": {"pending": pending, "dead": 0, "dropped": 0}, "watched": 1}), encoding="utf-8")


async def test_pending_envelopes_stall_only_when_they_persist(rig, tmp_path):  # noqa: F811
    eng = rig
    _status(tmp_path, 3)
    eng._tip_intake_pending_streak = 0
    v = await il.liveness(eng, base=tmp_path)
    assert v["ok"] and v["state"] == "live" and any("in flight" in w for w in v.get("warnings") or []), v
    eng._tip_intake_pending_streak = il.PENDING_STALL_SAMPLES
    v = await il.liveness(eng, base=tmp_path)
    assert not v["ok"] and any("consecutive" in r for r in v["reasons"]), v
    _status(tmp_path, 0)
    v = await il.liveness(eng, base=tmp_path)
    assert v["ok"] and not v["reasons"]
