"""Context-channel digests (KNOWLEDGE plan Phase 4 / C2-C3).

A context channel (e.g. trading-floor) is mirrored but never auto-tipped; its
value is distilled here instead: one run per channel-day reads the mirrored
messages and writes ONE `daily:YYYY-MM-DD` note (14d TTL — today's chatter is
short-lived by design) plus at most a handful of PROMOTED durable nuggets into
`ticker:`/`source:` scopes with provenance. FinMem's layering, applied to chat:
the noise dies in two weeks, the structure survives.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select

from ...domain import new_id
from ...models import DiscordMessage, TipAnalystRun

log = logging.getLogger("zargar.tip.digest")

ET = ZoneInfo("America/New_York")
DIGEST_TIMEOUT_S = 180
MAX_PROMOTIONS = 5

SYSTEM = """You are the tips desk's analyst distilling ONE day of a general trading chat
channel into desk knowledge. Two outputs:
1. summary — the day in 3-8 tight sentences: tickers discussed (with the room's lean),
recurring themes, notable calls/exits people described, overall mood. Skip pleasantries
and memes. This becomes a note that EXPIRES in 14 days — it may be dated.
2. promotions — 0-{maxp} DURABLE nuggets worth keeping beyond the day: a structural read
on a ticker ("room notes NVDA 180 acted as a magnet all week"), a poster's persistent
habit, a recurring setup. Each goes to scope "ticker:SYM" or "source:<channel>". Only
promote what would still be useful in a month; when in doubt, don't.
Reply with ONLY one JSON object matching this schema — no prose, no markdown fences:
"""


class Promotion(BaseModel):
    scope: str = Field(description='"ticker:SYM" or "source:<name>"')
    text: str


class DigestOpinion(BaseModel):
    summary: str
    tickers: list[str] = Field(default_factory=list)
    promotions: list[Promotion] = Field(default_factory=list)


def _day_bounds_et(date_str: str | None) -> tuple[dt.datetime, dt.datetime, str]:
    day = (dt.datetime.now(ET).date() if not date_str
           else dt.date.fromisoformat(date_str))
    start = dt.datetime.combine(day, dt.time(0, 0), tzinfo=ET)
    return (start.astimezone(dt.timezone.utc),
            (start + dt.timedelta(days=1)).astimezone(dt.timezone.utc),
            day.isoformat())


async def _prepare(eng, channel_id: str, date: str | None):
    """(source, day, messages) for one channel-day; ValueError when empty."""
    watch = {str(e.get("channelId")): e
             for e in (eng.signals_service.discord_get_watch() or [])}
    entry = watch.get(str(channel_id)) or {}
    source = entry.get("sourceName") or f"channel:{channel_id}"
    start, end, day = _day_bounds_et(date)
    async with eng.sf() as session:
        msgs = (await session.execute(
            select(DiscordMessage)
            .where(DiscordMessage.channel_id == str(channel_id),
                   DiscordMessage.posted_at >= start,
                   DiscordMessage.posted_at < end)
            .order_by(DiscordMessage.posted_at.asc()).limit(600))).scalars().all()
    msgs = [m for m in msgs if (m.text or "").strip()]
    if not msgs:
        raise ValueError(f"no mirrored messages for {source} on {day}")
    return source, day, msgs


def _client_and_model(eng, client):
    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        return None, None
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    model = (str(eng.settings.get("techniques.tip.analyst_model") or "")
             or eng.config.extraction_model)
    return client, model


async def _run(eng, run_id: str, *, source: str, day: str, msgs, client, model) -> dict:
    """One digest run, accounted through every outcome (KFIN-01): the single
    provider call is a `perCall` record on the run's `usage` (tokens, cache
    tokens, stop reason, latency; unknown provider usage stays None), each
    note write leaves a receipt the moment it lands, and a failure or
    cancellation ANYWHERE — the call, the parse, the daily note, a promotion
    — persists the run as failed WITH the usage and the receipts gathered so
    far before propagating. No write is retried."""
    import contextlib as _ctx
    import time as _time

    from ...research import llm_stats
    from .analyst import _Recorder, _persist_run, _usage_new, _usage_record

    rec = _Recorder(eng, run_id)
    rec.step("start", f"Digesting {source} for {day}: {len(msgs)} message(s).")
    transcript = "\n".join(
        f"[{(m.posted_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc)).astimezone(ET):%H:%M}] "
        f"{m.author}: {m.text}"
        for m in msgs)[:60000]
    header = (f"CHANNEL: {source} · DATE: {day} (ET)\n"
              f"TRANSCRIPT ({len(msgs)} messages):\n{transcript}")
    system = (SYSTEM.replace("{maxp}", str(MAX_PROMOTIONS))
              + json.dumps(DigestOpinion.model_json_schema(), separators=(",", ":")))
    usage = _usage_new()
    receipts: list[dict] = []
    partial: dict = {"noteId": None, "promoted": []}

    def _meta() -> dict:
        return {"usage": usage, **partial,
                **({"receipts": list(receipts)} if receipts else {})}

    async def _terminal_failure(error: str, *, cancelled: bool = False) -> None:
        rec.step("error", ("Cancelled (shutdown/restart) — reconciled as failed."
                           if cancelled else f"Digest failed: {error}"))
        if cancelled:
            with _ctx.suppress(Exception):
                await _persist_run(eng, run_id, status="failed", rec=rec,
                                   error="cancelled: shutdown/restart", opinion=_meta())
        else:
            await _persist_run(eng, run_id, status="failed", rec=rec,
                               error=error[:500], opinion=_meta())

    # ---- the paid call ------------------------------------------------------
    _t0 = _time.perf_counter()
    try:
        try:
            resp = await asyncio.wait_for(
                client.messages.create(model=model, max_tokens=2000, system=system,
                                       messages=[{"role": "user", "content": header}]),
                timeout=DIGEST_TIMEOUT_S)
        except asyncio.CancelledError:
            _usage_record(usage, None, latency_ms=(_time.perf_counter() - _t0) * 1000.0,
                          error="cancelled")
            raise
        except TimeoutError:
            _usage_record(usage, None, latency_ms=(_time.perf_counter() - _t0) * 1000.0,
                          error=f"timed out after {DIGEST_TIMEOUT_S}s")
            raise ValueError(f"digest call timed out after {DIGEST_TIMEOUT_S}s") from None
        except Exception as exc:
            _usage_record(usage, None, latency_ms=(_time.perf_counter() - _t0) * 1000.0,
                          error=f"{type(exc).__name__}: {exc}")
            raise
        latency_ms = (_time.perf_counter() - _t0) * 1000.0
        _usage_record(usage, resp, latency_ms=latency_ms)
        with _ctx.suppress(Exception):
            llm_stats.record_response("digest", resp, model=model, latency_ms=latency_ms)
        if getattr(resp, "stop_reason", "") == "max_tokens":
            rec.step("note", "Reply hit the output-token limit (stop=max_tokens) — "
                             "recorded; the answer may be truncated.")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        i, j = text.find("{"), text.rfind("}")
        if i == -1 or j <= i:
            raise ValueError("no JSON object in the digest reply"
                             + (" (truncated at max_tokens)"
                                if getattr(resp, "stop_reason", "") == "max_tokens" else ""))
        op = DigestOpinion.model_validate_json(text[i:j + 1])
    except asyncio.CancelledError:
        await _terminal_failure("cancelled", cancelled=True)
        raise
    except Exception as exc:
        await _terminal_failure(str(exc))
        raise

    # ---- the side effects: each one receipted the moment it lands -----------
    svc = eng.signals_service
    now_iso = lambda: dt.datetime.now(dt.timezone.utc).isoformat()   # noqa: E731
    try:
        note = await svc.add_tip_note(
            f"daily:{day}", f"[{source}] {op.summary.strip()}"[:2000],
            author=f"digest:{run_id[:8]}", run_id=run_id)
        partial["noteId"] = note["id"]
        receipt = {"tool": "save_note", "scope": f"daily:{day}", "noteId": note["id"],
                   "at": now_iso()}
        receipts.append(receipt)
        rec.step("receipt", f"side effect: daily note {note['id'][:8]} saved", **receipt)
        for p in op.promotions[:MAX_PROMOTIONS]:
            scope = (p.scope or "").strip()
            if not scope.startswith(("ticker:", "source:")) or not p.text.strip():
                continue                      # promotions may only land in durable scopes
            pn = await svc.add_tip_note(scope[:160],
                                        f"{p.text.strip()} (from {source} {day})"[:2000],
                                        author=f"digest:{run_id[:8]}", run_id=run_id)
            partial["promoted"].append({"id": pn["id"], "scope": scope})
            receipt = {"tool": "save_note", "scope": scope, "noteId": pn["id"], "at": now_iso()}
            receipts.append(receipt)
            rec.step("receipt", f"side effect: promotion {pn['id'][:8]} saved to {scope}",
                     **receipt)
    except asyncio.CancelledError:
        await _terminal_failure("cancelled", cancelled=True)
        raise
    except Exception as exc:
        # a completed write keeps its receipt; the failed one is not retried
        await _terminal_failure(f"saving notes failed: {exc}")
        raise
    promoted = partial["promoted"]
    rec.step("final", f"Digest saved (note {note['id'][:8]}) — "
                      f"{len(promoted)} nugget(s) promoted to durable scopes. "
                      f"Tickers: {', '.join(op.tickers[:12]) or '—'}.",
             noteId=note["id"], promoted=promoted)
    opinion = {"verdict": "digest", "summary": op.summary, "tickers": op.tickers,
               "noteId": note["id"], "promoted": promoted, "date": day,
               "channelId": None, "runId": run_id, "usage": usage, "receipts": list(receipts)}
    await _persist_run(eng, run_id, status="done", rec=rec, opinion=opinion)
    return opinion


async def _create_run_row(eng, channel_id: str, source: str, day: str,
                          n_msgs: int, model: str) -> str:
    run_id = new_id()
    async with eng.sf() as session:
        session.add(TipAnalystRun(
            id=run_id, signal_id=None, ticker="DIGEST"[:16], source=source,
            status="running", kind="digest", model=model, tools=[],
            tip={"channelId": str(channel_id), "date": day, "messages": n_msgs}))
        await session.commit()
    return run_id


async def digest_channel(eng, channel_id: str, *, date: str | None = None,
                         client=None) -> dict | None:
    """Digest one context channel's ET day, synchronously (nightly + tests).
    ValueError when the channel-day has no mirrored messages."""
    client, model = _client_and_model(eng, client)
    if client is None:
        return None
    source, day, msgs = await _prepare(eng, channel_id, date)
    run_id = await _create_run_row(eng, channel_id, source, day, len(msgs), model)
    out = await _run(eng, run_id, source=source, day=day, msgs=msgs,
                     client=client, model=model)
    out["channelId"] = str(channel_id)
    return out


async def start_digest(eng, channel_id: str, *, date: str | None = None,
                       client=None) -> dict:
    """The digest-now button: validate + create the (streaming) run row, then
    finish in the background. Returns {runId, date, messages} immediately."""
    client, model = _client_and_model(eng, client)
    if client is None:
        raise ValueError("no analyst client configured")
    source, day, msgs = await _prepare(eng, channel_id, date)
    run_id = await _create_run_row(eng, channel_id, source, day, len(msgs), model)

    async def _bg():
        try:
            await _run(eng, run_id, source=source, day=day, msgs=msgs,
                       client=client, model=model)
        except Exception:
            log.exception("digest run %s failed", run_id[:8])

    asyncio.create_task(_bg(), name=f"tip-digest-{run_id[:8]}")
    return {"runId": run_id, "date": day, "messages": len(msgs), "source": source}


async def digest_all_context_channels(eng, *, client=None) -> list[dict]:
    """Nightly pass (gated by techniques.tip.digest_enabled): digest today for
    every enabled context channel. Fail-open per channel."""
    out: list[dict] = []
    for e in (eng.signals_service.discord_get_watch() or []):
        if not e.get("enabled") or (e.get("mode") or "tips") != "context":
            continue
        try:
            op = await digest_channel(eng, str(e.get("channelId")), client=client)
            if op:
                out.append(op)
        except ValueError as exc:          # quiet channel today — not an error
            log.info("digest skipped: %s", exc)
        except Exception:
            log.exception("digest failed for %s", e.get("sourceName"))
    return out
