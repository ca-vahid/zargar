"""KFIN-01: retros and digests keep truthful per-run accounting through EVERY
outcome — agent-loop usage (per-call tokens / cache tokens / stop reason /
latency / retries) and side-effect receipts survive success, malformed
output, timeout, provider failure and cancellation; a paid response followed
by a failed write still has its usage; a completed note write followed by a
failure still has its receipt; unknown provider usage stays unknown (never
zero); no phantom requests, no duplicate side effects.

Fixtures come from test_tip_analyst_loop (scripted client + engine rig) and
test_tip_knowledge (the context-channel seed for digests)."""
import asyncio
import datetime as dt

import pytest
from sqlalchemy import select

from zargar.domain import new_id
from zargar.models import DiscordMessage, Signal, TipAnalystRun, TipNote
from zargar.techniques.tip import digest, retro

from .conftest import wait_for
from .test_tip_analyst_loop import _Block, _Resp, _Scripted, rig  # noqa: F401 - fixture re-export


class _Hanging(_Scripted):
    """Scripted responses, then every further request hangs until cancelled
    (a wait_for timeout or a task cancel) — never a phantom response."""

    async def create(self, **kw):
        if self._responses:
            return await super().create(**kw)
        self.requests.append([dict(m) if isinstance(m, dict) else m for m in kw["messages"]])
        await asyncio.Event().wait()


class _NoUsage(_Resp):
    def __init__(self, content, stop="end_turn"):
        super().__init__(content, stop=stop)
        self.usage = None


def _save_note(text="Never chase premium more than 7% over the alert (position 1111)."):
    return _Resp([_Block(type="tool_use", id="t1", name="save_note",
                         input={"scope": "rule", "text": text})], usage=(120, 30))


def _grade(grade="good_call"):
    return _Resp([_Block(type="text", text=(
        '{"grade": "%s", "what_worked": "sized right", "what_didnt": "", '
        '"rule_update": null, "confidence": 0.7}' % grade))], usage=(200, 60))


def _position_row():
    return {"id": new_id(), "symbol": "TEST", "tags": ["source:SrcA"],
            "config": {"direction": "long", "entry": 10.0, "risk": 1.0},
            "state": {"realizedPnl": 42.5, "sessionsSeen": ["2026-09-10", "2026-09-11"]},
            "legs": []}


async def _run(eng, run_id) -> TipAnalystRun:
    async with eng.sf() as session:
        return await session.get(TipAnalystRun, run_id)


async def _notes_by_run(eng, run_id) -> list[TipNote]:
    async with eng.sf() as session:
        return (await session.execute(select(TipNote).where(TipNote.run_id == run_id))).scalars().all()


async def _only_run(eng, kind: str) -> TipAnalystRun:
    async with eng.sf() as session:
        rows = (await session.execute(select(TipAnalystRun).where(TipAnalystRun.kind == kind))).scalars().all()
    assert len(rows) == 1, [r.id for r in rows]
    return rows[0]


# --- position retros ------------------------------------------------------------

async def test_retro_multi_turn_success_keeps_usage_and_receipts(rig):
    eng = rig
    client = _Scripted([_save_note(), _grade()])
    out = await retro.retro_position(eng, _position_row(), client=client)
    assert out and out["grade"] == "good_call"
    usage = out["usage"]
    assert usage["calls"] == 2 and usage["in"] == 320 and usage["out"] == 90
    assert usage["stops"] == ["end_turn", "end_turn"] and usage["retries"] == 0
    assert len(usage["perCall"]) == 2 and all(c["latencyMs"] >= 0 for c in usage["perCall"])
    assert usage["perCall"][0]["inputTokens"] == 120 and usage["perCall"][1]["outputTokens"] == 60
    assert usage["perCall"][0]["cacheReadTokens"] == 0 and usage["unknownCalls"] == 0
    assert [r["tool"] for r in out["receipts"]] == ["save_note"]
    row = await _run(eng, out["runId"])
    assert row.status == "done" and row.opinion["usage"]["calls"] == 2
    assert len(await _notes_by_run(eng, out["runId"])) == 1        # written exactly once
    assert len(client.requests) == 2                               # no phantom request


async def test_retro_malformed_after_note_write_keeps_receipt_and_usage(rig):
    """A paid response followed by a failure (the final reply is not JSON)
    still has its usage AND the note the tool wrote still has its receipt."""
    eng = rig
    client = _Scripted([_save_note(), _Resp([_Block(type="text", text="no json here")], usage=(90, 10))])
    out = await retro.retro_position(eng, _position_row(), client=client)
    assert out is None
    row = await _only_run(eng, "retro")
    assert row.status == "failed" and "JSON" in (row.error or "")
    assert row.opinion["usage"]["calls"] == 2 and row.opinion["usage"]["in"] == 210
    assert row.opinion["receipts"][0]["tool"] == "save_note"
    assert len(await _notes_by_run(eng, row.id)) == 1
    assert len(client.requests) == 2


async def test_retro_timeout_keeps_paid_calls_and_receipts(rig, monkeypatch):
    eng = rig
    monkeypatch.setattr(retro, "TIMEOUT_S", 0.4)
    client = _Hanging([_save_note()])
    out = await retro.retro_position(eng, _position_row(), client=client)
    assert out is None
    row = await _only_run(eng, "retro")
    assert row.status == "failed" and "timed out" in row.error
    usage = row.opinion["usage"]
    assert usage["calls"] == 1 and usage["in"] == 120                 # the paid call
    assert len(usage["perCall"]) == 2 and usage["perCall"][1].get("error") == "cancelled"
    assert row.opinion["receipts"][0]["tool"] == "save_note"
    assert len(await _notes_by_run(eng, row.id)) == 1
    assert len(client.requests) == 2


async def test_retro_cancellation_persists_then_reraises(rig):
    eng = rig
    client = _Hanging([_save_note()])
    task = asyncio.create_task(retro.retro_position(eng, _position_row(), client=client))
    await wait_for(lambda: len(client.requests) == 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = await _only_run(eng, "retro")
    assert row.status == "failed" and row.error.startswith("cancelled")
    assert row.finished_at is not None
    assert row.opinion["usage"]["calls"] == 1 and row.opinion["usage"]["in"] == 120
    assert row.opinion["receipts"][0]["tool"] == "save_note"
    assert len(await _notes_by_run(eng, row.id)) == 1


async def test_retro_provider_failure_records_attempts_without_phantom_requests(rig):
    eng = rig

    class _Boom(_Scripted):
        async def create(self, **kw):
            self.requests.append(list(kw["messages"]))
            raise RuntimeError("boom (not transient)")

    client = _Boom([])
    out = await retro.retro_position(eng, _position_row(), client=client)
    assert out is None
    row = await _only_run(eng, "retro")
    usage = row.opinion["usage"]
    assert usage["calls"] == 0 and usage["in"] == 0 and len(usage["perCall"]) == 1
    assert "boom" in usage["perCall"][0]["error"] and usage["retries"] == 0
    assert "receipts" not in row.opinion and len(client.requests) == 1


async def test_unknown_provider_usage_stays_unknown(rig):
    eng = rig
    client = _Scripted([_NoUsage([_Block(type="text", text=(
        '{"grade": "bad_call", "what_worked": "", "what_didnt": "late", '
        '"rule_update": null, "confidence": 0.4}'))])])
    out = await retro.retro_position(eng, _position_row(), client=client)
    assert out and out["grade"] == "bad_call"
    usage = out["usage"]
    assert usage["calls"] == 1 and usage["unknownCalls"] == 1 and usage["partial"] is True
    assert usage["perCall"][0]["inputTokens"] is None and usage["perCall"][0]["outputTokens"] is None
    assert usage["inPerCall"] == []                                    # never a fake zero


# --- unfilled retros --------------------------------------------------------------

async def _expired_signal(eng, source="SrcU", ticker="UNF"):
    sid = new_id()
    async with eng.sf() as session:
        session.add(Signal(id=sid, ticker=ticker, direction="long", action="open",
                           source_name=source, status="expired", extraction={},
                           entry_price=12.0, thesis_summary="offline"))
        await session.commit()
    return sid


async def test_unfilled_retro_success_keeps_usage_and_marks_once(rig):
    eng = rig
    sid = await _expired_signal(eng)
    client = _Scripted([_save_note("Source states entries too far away (retro 2026-09-14)."), _grade("bad_call")])
    out = await retro.run_unfilled_retros(eng, client=client)
    assert out["unfilledRetros"] == 1 and out["failed"] == 0 and out["markFailed"] == 0
    row = await _only_run(eng, "retro")
    assert row.status == "done" and row.opinion["usage"]["calls"] == 2
    assert row.opinion["receipts"][0]["tool"] == "save_note"
    async with eng.sf() as session:
        sig = await session.get(Signal, sid)
    assert sig.extraction["unfilledRetro"] == row.id
    assert len(await _notes_by_run(eng, row.id)) == 1


async def test_unfilled_retro_failure_after_note_write_keeps_receipt(rig):
    eng = rig
    sid = await _expired_signal(eng)
    client = _Scripted([_save_note("Source states entries too far away (retro 2026-09-14)."),
                        _Resp([_Block(type="text", text="garbage")], usage=(50, 5))])
    out = await retro.run_unfilled_retros(eng, client=client)
    assert out["unfilledRetros"] == 0 and out["failed"] == 1
    row = await _only_run(eng, "retro")
    assert row.status == "failed" and row.opinion["usage"]["in"] == 170
    assert row.opinion["receipts"][0]["tool"] == "save_note"
    async with eng.sf() as session:
        sig = await session.get(Signal, sid)
    assert "unfilledRetro" not in (sig.extraction or {})              # reviewed again tomorrow
    assert len(await _notes_by_run(eng, row.id)) == 1


async def test_unfilled_retro_cancellation_persists_then_reraises(rig):
    eng = rig
    await _expired_signal(eng)
    client = _Hanging([_save_note("Source states entries too far away (retro 2026-09-14).")])
    task = asyncio.create_task(retro.run_unfilled_retros(eng, client=client))
    await wait_for(lambda: len(client.requests) == 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = await _only_run(eng, "retro")
    assert row.status == "failed" and row.error.startswith("cancelled")
    assert row.opinion["usage"]["calls"] == 1 and row.opinion["receipts"][0]["tool"] == "save_note"


# --- digests ----------------------------------------------------------------------

_DIGEST_JSON = ('{"summary": "Room leaned bullish NVDA all day.", "tickers": ["NVDA"],'
                ' "promotions": [{"scope": "ticker:NVDA", "text": "room treats 180 as a magnet"},'
                ' {"scope": "source:trading-floor", "text": "the room fades open gaps"}]}')


async def _seed_channel(eng):
    await eng.signals_service.discord_set_watch([
        {"channelId": "cf", "kind": "channel", "sourceName": "trading-floor",
         "enabled": True, "botsOnly": False, "mode": "context"}])
    now = dt.datetime.now(dt.timezone.utc)
    async with eng.sf() as session:
        for i in range(3):
            session.add(DiscordMessage(id=f"tf{i}", channel_id="cf", source_name="trading-floor",
                                       author=f"user{i}", text=f"NVDA looking strong {i}", posted_at=now))
        await session.commit()


async def test_digest_success_has_per_call_record_and_receipts(rig):
    eng = rig
    await _seed_channel(eng)
    client = _Scripted([_Resp([_Block(type="text", text=_DIGEST_JSON)], usage=(500, 80))])
    out = await digest.digest_channel(eng, "cf", client=client)
    assert out["verdict"] == "digest" and len(out["promoted"]) == 2
    usage = out["usage"]
    assert usage["calls"] == 1 and usage["in"] == 500 and usage["out"] == 80
    assert usage["perCall"][0]["stopReason"] == "end_turn" and usage["perCall"][0]["latencyMs"] >= 0
    assert [r["scope"] for r in out["receipts"]] == [f"daily:{out['date']}", "ticker:NVDA", "source:trading-floor"]
    row = await _run(eng, out["runId"])
    assert row.status == "done" and len(row.opinion["receipts"]) == 3
    assert len(await _notes_by_run(eng, out["runId"])) == 3


async def test_malformed_digest_keeps_usage_and_writes_nothing(rig):
    eng = rig
    await _seed_channel(eng)
    client = _Scripted([_Resp([_Block(type="text", text="the room was busy")], stop="max_tokens", usage=(400, 2000))])
    with pytest.raises(ValueError, match="no JSON"):
        await digest.digest_channel(eng, "cf", client=client)
    row = await _only_run(eng, "digest")
    assert row.status == "failed" and "max_tokens" in row.error
    assert row.opinion["usage"]["calls"] == 1 and row.opinion["usage"]["in"] == 400
    assert row.opinion["usage"]["stops"] == ["max_tokens"] and row.opinion["noteId"] is None
    assert "receipts" not in row.opinion
    assert await _notes_by_run(eng, row.id) == []


async def test_promotion_write_failure_keeps_daily_note_receipt(rig, monkeypatch):
    eng = rig
    await _seed_channel(eng)
    svc = eng.signals_service
    real = svc.add_tip_note

    async def flaky(scope, text, **kw):
        if scope.startswith("source:"):
            raise OSError("notes storage unavailable")
        return await real(scope, text, **kw)

    monkeypatch.setattr(svc, "add_tip_note", flaky)
    client = _Scripted([_Resp([_Block(type="text", text=_DIGEST_JSON)], usage=(500, 80))])
    with pytest.raises(OSError, match="notes storage unavailable"):
        await digest.digest_channel(eng, "cf", client=client)
    row = await _only_run(eng, "digest")
    assert row.status == "failed" and "saving notes failed" in row.error
    assert row.opinion["usage"]["calls"] == 1 and row.opinion["usage"]["in"] == 500
    receipts = row.opinion["receipts"]
    assert [r["scope"] for r in receipts] == [f"daily:{row.tip['date']}", "ticker:NVDA"]
    assert row.opinion["noteId"] == receipts[0]["noteId"]
    assert [p["scope"] for p in row.opinion["promoted"]] == ["ticker:NVDA"]
    notes = await _notes_by_run(eng, row.id)
    assert {n.scope for n in notes} == {f"daily:{row.tip['date']}", "ticker:NVDA"}   # written once, not retried
    assert len(client.requests) == 1


async def test_digest_cancellation_persists_then_reraises(rig):
    eng = rig
    await _seed_channel(eng)
    client = _Hanging([])
    task = asyncio.create_task(digest.digest_channel(eng, "cf", client=client))
    await wait_for(lambda: len(client.requests) == 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = await _only_run(eng, "digest")
    assert row.status == "failed" and row.error.startswith("cancelled")
    usage = row.opinion["usage"]
    assert usage["calls"] == 0 and usage["perCall"][0]["error"] == "cancelled"
    assert await _notes_by_run(eng, row.id) == []


async def test_digest_timeout_records_the_attempt(rig, monkeypatch):
    eng = rig
    await _seed_channel(eng)
    monkeypatch.setattr(digest, "DIGEST_TIMEOUT_S", 0.3)
    client = _Hanging([])
    with pytest.raises(ValueError, match="timed out"):
        await digest.digest_channel(eng, "cf", client=client)
    row = await _only_run(eng, "digest")
    assert row.status == "failed" and "timed out" in row.error
    assert row.opinion["usage"]["calls"] == 0 and "timed out" in row.opinion["usage"]["perCall"][0]["error"]


async def test_digest_unknown_usage_stays_unknown(rig):
    eng = rig
    await _seed_channel(eng)
    client = _Scripted([_NoUsage([_Block(type="text", text=_DIGEST_JSON)])])
    out = await digest.digest_channel(eng, "cf", client=client)
    usage = out["usage"]
    assert usage["calls"] == 1 and usage["unknownCalls"] == 1 and usage["partial"] is True
    assert usage["perCall"][0]["inputTokens"] is None and usage["in"] == 0 and usage["inPerCall"] == []
