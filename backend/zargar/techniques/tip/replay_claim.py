"""Atomic, durable processing claim for a manual intake replay (S21-07 rev 2, 2026-09-22).

The first cut committed the attempt counter and then processed with no lock: two concurrent requests could both read
"1 attempt used", both write "2", and both run `process_content` - the same failed message processed twice. The claim
is now taken inside ONE transaction under a per-message advisory lock (the intake's own claim pattern): the row's
status, its attempt budget and any active claim are re-read under the lock, the claim is written before the work, and
it is released (or left to expire) afterwards. A second request during the work gets `in_progress`; a request after a
crash waits out the claim's lease.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import text as sql_text

CLAIM_LEASE_S = 600.0            # a crashed replay frees its message after this long


def _attempts(meta: dict) -> int:
    return int(bool(meta.get("recoveryRetried"))) + int(meta.get("replayCount") or 0)


async def claim_replay(sf, content_id: str, *, reason: str, max_attempts: int, now: dt.datetime | None = None) -> dict:
    """Take the replay claim atomically. Returns {"ok": True, "attempt", "token"} or {"ok": False, "reason", ...}."""
    from ...models import RawContent
    now = now or dt.datetime.now(dt.timezone.utc)
    token = uuid.uuid4().hex
    async with sf() as session:
        await session.execute(sql_text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"tip-replay:{content_id}"})
        row = await session.get(RawContent, content_id, with_for_update=True)
        if row is None:
            return {"ok": False, "reason": "not_found"}
        meta = dict(row.meta or {})
        if row.status != "error":
            return {"ok": False, "reason": "not_error", "status": row.status}
        claim = meta.get("replayClaim") or {}
        if claim.get("at"):
            try:
                age = (now - dt.datetime.fromisoformat(str(claim["at"]))).total_seconds()
            except ValueError:
                age = 0.0
            if age < CLAIM_LEASE_S:
                return {"ok": False, "reason": "in_progress", "claimedAt": claim.get("at"), "leaseS": CLAIM_LEASE_S}
        used = _attempts(meta)
        if used >= max_attempts:
            return {"ok": False, "reason": "budget_exhausted", "attempts": used, "max": max_attempts}
        meta["replayClaim"] = {"token": token, "at": now.isoformat(), "reason": str(reason)[:200]}
        meta["replayCount"] = int(meta.get("replayCount") or 0) + 1        # counted at the claim, never after the work
        meta["replayedAt"] = now.isoformat()
        meta["replayReason"] = str(reason)[:200]
        row.meta = meta
        await session.commit()                                             # claim durable BEFORE any processing
        return {"ok": True, "attempt": used + 1, "max": max_attempts, "token": token}


async def release_replay(sf, content_id: str, token: str, *, outcome: str) -> bool:
    """Clear the claim this token holds and record the outcome; a foreign token never releases someone else's claim."""
    from ...models import RawContent
    async with sf() as session:
        await session.execute(sql_text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"tip-replay:{content_id}"})
        row = await session.get(RawContent, content_id, with_for_update=True)
        if row is None:
            return False
        meta = dict(row.meta or {})
        if (meta.get("replayClaim") or {}).get("token") != token:
            return False
        meta["replayClaim"] = None
        meta["replayOutcome"] = {"token": token, "outcome": str(outcome)[:120],
                                 "at": dt.datetime.now(dt.timezone.utc).isoformat()}
        row.meta = meta
        await session.commit()
        return True
