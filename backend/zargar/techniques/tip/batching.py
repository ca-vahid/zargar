"""Message Batches for the Tips jobs that can wait (2026-09-23, user decision: batching yes, fewer tool turns no).

The Batch API bills input and output at 50% of list price and returns within minutes (at most 24 h). Only
single-call, non-interactive jobs use it: the nightly channel digests and the knowledge-maintenance judge calls.
Intake reviews, appraisals and retros stay live - they are latency-bound tool loops.

`create()` is a drop-in for `client.messages.create(**kw)`: with batching off it IS that call. With it on, one request
is submitted as a batch, polled until it ends, and its Message returned. A batch that does not end inside
`techniques.tip.batch_timeout_s` is cancelled and a TimeoutError raised, which the callers already treat as a failed
call (their usage records say so). A non-succeeded result raises RuntimeError with the provider's reason.
"""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("zargar.tip.batching")

POLL_S = 20.0


def enabled(settings) -> bool:
    try:
        return bool(settings.get("techniques.tip.batch_jobs", False))
    except Exception:
        return False


def timeout_s(settings, default: float) -> float:
    """The wait a caller should allow: the batch timeout when batching is on, else its own direct-call timeout."""
    if not enabled(settings):
        return default
    try:
        return max(default, float(settings.get("techniques.tip.batch_timeout_s", 3600) or 3600))
    except Exception:
        return max(default, 3600.0)


def jsonable(v):
    """Batch request params are plain JSON: SDK content blocks (a replayed reply) become dicts, None fields dropped."""
    if hasattr(v, "model_dump"):
        return v.model_dump(exclude_none=True)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


async def create(client, settings, *, custom_id: str = "tip-job", poll_s: float = POLL_S, **kw):
    if not enabled(settings) or not hasattr(getattr(client, "messages", None), "batches"):
        return await client.messages.create(**kw)
    limit = timeout_s(settings, 0.0)
    batch = await client.messages.batches.create(requests=[{"custom_id": custom_id[:64], "params": jsonable(kw)}])
    t0 = time.monotonic()
    try:
        while getattr(batch, "processing_status", "") != "ended":
            if time.monotonic() - t0 > limit:
                raise TimeoutError(f"batch {batch.id} did not end within {limit:.0f}s")
            await asyncio.sleep(poll_s)
            batch = await client.messages.batches.retrieve(batch.id)
    except BaseException:
        # cancelled (shutdown) or timed out: stop the batch so nothing is processed - and billed - unseen
        try:
            await client.messages.batches.cancel(batch.id)
        except Exception:
            pass
        raise
    decoder = await client.messages.batches.results(batch.id)
    async for item in decoder:
        res = getattr(item, "result", None)
        if getattr(res, "type", "") == "succeeded":
            return res.message
        err = getattr(res, "error", None)
        raise RuntimeError(f"batch request {getattr(res, 'type', 'unknown')}: {getattr(err, 'message', err)}")
    raise RuntimeError(f"batch {batch.id} ended without a result")
