"""Completion checks for already-built telemetry and bounded audit helpers."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar import delivery_health
from zargar.domain import Bar
from zargar.techniques.tip import rule_audit


async def test_delivery_writer_retains_other_consumers_without_another_bar(monkeypatch):
    release = asyncio.Event()
    started = asyncio.Event()
    persisted = []

    async def append(_kind, payload):
        started.set()
        await release.wait()
        persisted.append(payload)

    eng = NS(journal=NS(append=append))
    monkeypatch.setattr(delivery_health, "now_ms", lambda: 100_000)
    message = {"bar": Bar("X", "1m", 0, 1, 2, 1, 2), "publishedAt": 99_000}
    delivery_health.observe(eng, "first", message, 0)
    await started.wait()
    delivery_health.observe(eng, "second", message, 0)
    release.set()
    await eng._delivery_health_task
    await asyncio.sleep(0)
    assert {row["consumer"] for row in persisted} == {"first", "second"}, (
        "the second consumer's dirty snapshot vanished when the shared writer was busy")


async def test_first_audit_request_honors_output_ceiling():
    client = NS(messages=NS(create=AsyncMock(return_value=NS(
        content=[NS(type="text", text="{}")], usage=None, stop_reason="end_turn"))))
    await rule_audit._judge(client, model="offline", system="fixture", header="fixture",
                            cap=20_000, max_tokens_ceiling=8192)
    assert client.messages.create.call_args.kwargs["max_tokens"] <= 8192, (
        "the first request exceeded the documented ceiling before retry logic ran")
