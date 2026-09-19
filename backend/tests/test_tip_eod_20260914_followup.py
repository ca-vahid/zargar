"""EOD 2026-09-14 follow-ups the reviewer's files do not cover: intake liveness
(EOD-01), the research quarantine flag (EOD-09), the staged model rule's
rendering (EOD-03) and the typed review class on the journal (EOD-02)."""
import datetime as dt
import json
from pathlib import Path

from zargar.techniques.tip import intake_liveness as il

from .test_tip_knowledge import app_client  # noqa: F401


def _status(tmp_path: Path, *, at: dt.datetime, frame: dt.datetime, state="connected", pending=0):
    (tmp_path / il.STATUS_FILE).write_text(json.dumps({
        "pid": 1, "at": at.isoformat(), "state": state, "connectedAt": at.isoformat(),
        "lastFrameAt": frame.isoformat(), "lastDispatchAt": frame.isoformat(), "lastMessageAt": None,
        "seenCount": 3, "reconnects": 0, "idleReconnects": 0, "recovering": False,
        "ledger": {"pending": pending, "dead": 0, "dropped": 0}, "watched": 2, "channels": {}}), encoding="utf-8")


async def test_liveness_distinguishes_a_live_pipe_from_a_stuck_one(app_client, tmp_path):  # noqa: F811
    client, eng = app_client
    now = dt.datetime.now(dt.timezone.utc)
    # (1) no status file at all: unknown, not ok
    v = await il.liveness(eng, base=tmp_path, now=now)
    assert v["ok"] is False and v["state"] == "unknown"
    # (2) fresh status, recent frame: live
    _status(tmp_path, at=now, frame=now - dt.timedelta(seconds=5))
    v = await il.liveness(eng, base=tmp_path, now=now)
    assert v["ok"] is True and v["state"] == "live", v["reasons"]
    # (3) fresh status but NO frame for 6 minutes on a "connected" socket: stuck pipe
    _status(tmp_path, at=now, frame=now - dt.timedelta(minutes=6))
    v = await il.liveness(eng, base=tmp_path, now=now)
    assert v["ok"] is False and any("stuck pipe" in r for r in v["reasons"])
    # (4) the status file itself is stale: the gateway process is gone or hung
    _status(tmp_path, at=now - dt.timedelta(minutes=10), frame=now - dt.timedelta(minutes=10))
    v = await il.liveness(eng, base=tmp_path, now=now)
    assert v["ok"] is False and any("hung or gone" in r for r in v["reasons"])
    # (5) pending envelopes never hide behind a live socket - but one sighting is a claim in flight, not a stall
    # (bd7bf658, 2026-09-18: "envelopes briefly in flight are not a stall"): it WARNS, and only a pending count that
    # persists through PENDING_STALL_SAMPLES consecutive monitor samples is a stall
    _status(tmp_path, at=now, frame=now, pending=3)
    eng._tip_intake_pending_streak = 0
    v = await il.liveness(eng, base=tmp_path, now=now)
    assert v["ok"] is True and any("in flight" in w for w in v["warnings"])
    eng._tip_intake_pending_streak = il.PENDING_STALL_SAMPLES
    v = await il.liveness(eng, base=tmp_path, now=now)
    assert v["ok"] is False and any("pending delivery" in r for r in v["reasons"])
    # the API route exists (reads the runtime cwd; here there is no file -> unknown, still 200)
    r = await client.get("/api/tip/intake/liveness")
    assert r.status_code == 200 and "reasons" in r.json()


async def test_quarantined_shadow_book_is_not_evidence(app_client):  # noqa: F811
    client, eng = app_client
    from zargar.models import Portfolio
    from zargar.domain import new_id
    row = Portfolio(id=new_id(), name="Shadow: TestSrc", kind="shadow", starting_cash=1e5, cash=1e5,
                    source_name="TestSrc", book="immediate")
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    eng.positions.register_portfolio(row)
    r = await client.post(f"/api/portfolios/{row.id}/quarantine", json={"on": True, "note": "APLD runaway 2026-09-14"})
    assert r.status_code == 200 and r.json()["quarantined"] is True
    assert (eng.positions.portfolio(row.id) or {}).get("quarantined") is True
    listed = {p["id"]: p for p in (await client.get("/api/portfolios")).json()}
    assert listed[row.id]["quarantined"] is True and listed[row.id]["quarantineNote"] == "APLD runaway 2026-09-14"
    # source trust ignores the quarantined immediate book (lane b empty)
    trust = await eng.signals_service.source_trust("TestSrc")
    lane_b = trust.get("shadow") or trust.get("immediate") or {}
    assert not any(v for v in (lane_b.values() if isinstance(lane_b, dict) else []) if isinstance(v, (int, float)) and v)
    # it survives a reload of the portfolio table
    await eng.positions.load()
    assert (eng.positions.portfolio(row.id) or {}).get("quarantined") is True
    r = await client.post(f"/api/portfolios/{row.id}/quarantine", json={"on": False})
    assert r.status_code == 200 and r.json()["quarantined"] is False


async def test_staged_model_rule_is_rendered_as_pending_not_policy(app_client):  # noqa: F811
    _, eng = app_client
    from zargar.techniques.tip.analyst import _rules_text, _run_tool
    svc = eng.signals_service
    await eng.settings.set("techniques.tip.knowledge_apply_enabled", False, journal=False)
    live = await svc.add_tip_note("rule", "RULE (fill band): never pay more than 1.15x the source's fill.", author="user")
    out = await _run_tool(eng, "save_note", {"scope": "rule", "text": "RULE (fill band): 1.5x is fine now."},
                          {"ticker": "X", "source": "s", "run_id": "retro-1", "stage": "retro"})
    assert out.get("saved") and "PROPOSED" in (out.get("status") or "")
    rules = {n["id"]: n for n in await svc.tip_notes(["rule"], limit=50)}
    assert rules[live["id"]]["supersededBy"] is None, "a staged proposal never supersedes the live family member"
    assert rules[out["id"]]["needsHuman"] is True
    text, _n, _snap = await _rules_text(eng)
    assert "PENDING REVIEW" in text and "1.5x is fine now" in text and "never pay more than 1.15x" in text
