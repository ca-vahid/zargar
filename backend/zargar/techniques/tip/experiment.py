"""Historical-tip experiment harness (KNOWLEDGE plan Phase 2).

Randomly samples mirrored Discord messages from TIPS-mode channels and runs
each through the REAL intake (extraction → verification → replay → historical
analyst appraisal) — out-of-band by construction: every signal is tagged
`extraction.experiment` and forced onto the replayed path (no orders, no books,
no proposals, no arming; proven in tests/test_tip_experiment.py). The batch
review then grades the PROCESS with the rubric (extraction fidelity,
verification, knowledge injection, tool use, verdict-at-tip-time, gaps) — the
outcome evidence the field lacks for chat-stream tips (KNOWLEDGE plan §2.5).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import random

from sqlalchemy import select

from ... import events as ev
from ...domain import new_id
from ...models import DiscordMessage, RawContent, Signal, TipAnalystRun

log = logging.getLogger("zargar.tip.experiment")

RUBRIC = """Review this out-of-band HISTORICAL experiment batch — {n} old Discord messages
run through the live tip pipeline. Grade the PROCESS, not the P&L (hindsight is cheap;
process is what we can fix). For the batch as a whole and per item where notable:
1. EXTRACTION fidelity — ticker/direction/prices/expiry survived intact from the message?
2. VERIFICATION correctness — right status for the content and its age?
3. KNOWLEDGE injection — were the right notes in context? What note SHOULD have existed?
4. TOOL USE — sensible calls, no live-data confusion (these are historical!), no waste?
5. VERDICT quality — reasonable as of tip time, given the replay outcome as evidence?
6. GAPS — anything dropped, mislabeled, or that the pipeline should have flagged.
Answer as plain structured text: a short overall read, then numbered findings (most
important first, each with the signal ids as evidence), then the top 3 concrete fixes."""


def _state(svc) -> dict:
    st = getattr(svc, "_experiments", None)
    if st is None:
        st = {}
        svc._experiments = st
    return st


async def _tips_sources(eng) -> set[str]:
    watch = eng.signals_service.discord_get_watch() or []
    return {str(e.get("sourceName") or "") for e in watch
            if e.get("enabled") and (e.get("mode") or "tips") != "context"}


async def _processed_message_ids(eng) -> set[str]:
    async with eng.sf() as session:
        rows = (await session.execute(
            select(RawContent.meta).where(RawContent.source_type == "experiment")
        )).scalars().all()
    return {str((m or {}).get("discordMessageId")) for m in rows
            if (m or {}).get("discordMessageId")}


async def sample_messages(eng, *, sample: int, seed: int, since: str,
                          channels: list[str] | None = None) -> list[DiscordMessage]:
    """Seeded random sample of mirrored messages from tips-mode channels:
    text-bearing, posted on/after `since`, never processed before. Image-only
    messages are skipped in v1 (a finding candidate, not a silent drop — the
    manifest counts them)."""
    since_dt = dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc) \
        if since else dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
    sources = await _tips_sources(eng)
    async with eng.sf() as session:
        q = select(DiscordMessage).where(DiscordMessage.posted_at >= since_dt)
        if channels:
            q = q.where(DiscordMessage.channel_id.in_([str(c) for c in channels]))
        rows = (await session.execute(q)).scalars().all()
    processed = await _processed_message_ids(eng)
    pool = [m for m in rows
            if (m.source_name or "") in sources
            and (m.text or "").strip()
            and str(m.id) not in processed]
    rnd = random.Random(seed)
    if len(pool) <= sample:
        return sorted(pool, key=lambda m: m.posted_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
    picked = rnd.sample(pool, sample)
    return sorted(picked, key=lambda m: m.posted_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc))


async def run_batch(eng, *, batch: str, sample: int = 20, seed: int = 7,
                    since: str = "", channels: list[str] | None = None) -> dict:
    """Process one batch sequentially (gentle on the LLM + the feed). Progress
    lives on signals_service._experiments[batch]; the manifest is journaled at
    start and finish (TipExperimentBatch)."""
    svc = eng.signals_service
    state = _state(svc)
    if state.get(batch, {}).get("running"):
        raise ValueError(f"batch {batch} is already running")
    msgs = await sample_messages(eng, sample=sample, seed=seed, since=since,
                                 channels=channels)
    manifest = {"batch": batch, "seed": seed, "since": since, "requested": sample,
                "sampled": len(msgs), "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                "items": []}
    state[batch] = {"running": True, "total": len(msgs), "done": 0, "manifest": manifest}
    await eng.journal.append(ev.TIP_EXPERIMENT_BATCH,
                             {"phase": "started", **{k: manifest[k] for k in
                                                     ("batch", "seed", "since", "requested", "sampled")}},
                             aggregate_type="signal", aggregate_id=f"exp-{batch}")
    try:
        for m in msgs:
            item = {"messageId": m.id, "source": m.source_name,
                    "postedAt": m.posted_at.isoformat() if m.posted_at else None}
            try:
                out = await svc.ingest_experiment(m, batch)
                item["contentId"] = out.get("contentId")
                item["intakeRunId"] = out.get("intakeRunId")
                item["signals"] = [
                    {"id": (o.get("signal") or {}).get("id"),
                     "ticker": (o.get("signal") or {}).get("ticker"),
                     "status": (o.get("signal") or {}).get("status")}
                    for o in (out.get("signals") or [])]
                item["error"] = out.get("error")
            except Exception as exc:            # one bad message never kills the batch
                log.exception("experiment item failed (%s)", m.id)
                item["error"] = str(exc)[:300]
            manifest["items"].append(item)
            state[batch]["done"] += 1
    finally:
        state[batch]["running"] = False
        manifest["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        await eng.journal.append(ev.TIP_EXPERIMENT_BATCH,
                                 {"phase": "finished", "batch": batch,
                                  "sampled": manifest["sampled"],
                                  "items": manifest["items"]},
                                 aggregate_type="signal", aggregate_id=f"exp-{batch}")
    return manifest


async def batch_status(eng, batch: str) -> dict:
    """Everything the batch produced, reconstructed from the DB (survives
    restarts): per-signal status/replay/analyst run + live progress if the
    batch is still running in this process."""
    svc = eng.signals_service
    live = _state(svc).get(batch)
    async with eng.sf() as session:
        sig_rows = (await session.execute(
            select(Signal).order_by(Signal.created_at.asc()))).scalars().all()
        content_rows = (await session.execute(
            select(RawContent).where(RawContent.source_type == "experiment")
        )).scalars().all()
    contents = [c for c in content_rows if (c.meta or {}).get("experiment") == batch]
    items = []
    for r in sig_rows:
        x = r.extraction or {}
        if x.get("experiment") != batch:
            continue
        replay = x.get("replay") or {}
        armed_book = (replay.get("armed") or {}) if replay.get("ok") else {}
        items.append({
            "signalId": r.id, "ticker": r.ticker, "source": r.source_name,
            "status": r.status, "statedAt": x.get("statedAt"),
            "replayOk": bool(replay.get("ok")),
            "replayOutcome": armed_book.get("outcome"),
            "replayR": armed_book.get("rMultiple"),
            "analystRunId": (x.get("analyst") or {}).get("runId"),
            "analystVerdict": (x.get("analyst") or {}).get("verdict"),
        })
    return {"batch": batch,
            "running": bool(live and live.get("running")),
            "progress": ({"done": live.get("done"), "total": live.get("total")}
                         if live else None),
            "messagesProcessed": len(contents),
            "signals": items}


async def review_batch(eng, batch: str, *, client=None) -> dict | None:
    """One analyst review run over the whole batch (kind=retro, experiment-
    tagged): the rubric applied to every item's record. The summary is saved as
    a note under scope experiment:<batch> (never injected into live runs) and
    the run is linked from the CLI/UI like any other."""
    from .analyst import _Recorder, _persist_run

    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        return None
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    model = (str(eng.settings.get("techniques.tip.analyst_model") or "")
             or eng.config.extraction_model)

    status = await batch_status(eng, batch)
    if not status["signals"]:
        raise ValueError(f"batch {batch} has no signals to review")

    # each item's full record, compact: tip + checks + replay + the appraisal
    records = []
    async with eng.sf() as session:
        for it in status["signals"]:
            r = await session.get(Signal, it["signalId"])
            if r is None:
                continue
            x = r.extraction or {}
            run_id = (x.get("analyst") or {}).get("runId")
            run = await session.get(TipAnalystRun, run_id) if run_id else None
            records.append({
                "signalId": r.id, "ticker": r.ticker, "source": r.source_name,
                "statedAt": x.get("statedAt"), "status": r.status,
                "tip": (x.get("signal") or {}),
                "failedChecks": [c.get("name") for c in
                                 (r.verification or {}).get("checks", [])
                                 if not c.get("passed")],
                # F1: a failed appraisal leaves its mark — nothing is silent
                **({"analystError": x["analystError"]} if x.get("analystError") else {}),
                # compact: full replay dicts blew the record set past the
                # model's budget on batch b1 (2026-08-30)
                "replay": ({"ok": (x.get("replay") or {}).get("ok"),
                            "armed": (x.get("replay") or {}).get("armed"),
                            "immediate": (x.get("replay") or {}).get("immediate"),
                            "note": (x.get("replay") or {}).get("note")}
                           if x.get("replay") else None),
                "appraisal": ({k: (x.get("analyst") or {}).get(k) for k in
                               ("verdict", "rationale", "contract", "limit_price",
                                "quantity", "confidence")}
                              if x.get("analyst") else None),
                "toolCalls": ([{"tool": t.get("tool"), "ok": not t.get("error")}
                               for t in (run.opinion or {}).get("toolsUsed", [])]
                              if run else None),
            })

    run_id = new_id()
    async with eng.sf() as session:
        session.add(TipAnalystRun(
            id=run_id, signal_id=None, ticker=f"EXP {batch}"[:16],
            source="experiment", status="running", kind="retro", model=model,
            tools=[], tip={"experiment": batch, "items": len(records)}))
        await session.commit()
    rec = _Recorder(eng, run_id)
    rec.step("start", f"Batch review of experiment {batch}: {len(records)} historical "
                      "tip(s) — grading the PROCESS with the rubric.")
    system = ("You are the tips desk trader reviewing your own pipeline's "
              "handling of historical tips. Be specific, cite signal ids, "
              "and never let hindsight grade a decision.")

    async def _ask(recs_json: str) -> tuple[str, str | None]:
        resp = await client.messages.create(
            model=model, max_tokens=10000, system=system,
            messages=[{"role": "user", "content":
                       RUBRIC.format(n=len(records)) + "\n\nBATCH RECORDS:\n" + recs_json}])
        return ("".join(b.text for b in resp.content
                        if getattr(b, "type", "") == "text").strip(),
                getattr(resp, "stop_reason", None))

    try:
        text, stop = await _ask(json.dumps(records, default=str)[:60000])
        if not text:
            # a huge record set can exhaust the budget on thinking alone —
            # retry once with a trimmed set (found on batch b1, 2026-08-30)
            rec.step("note", f"empty response (stop_reason={stop}) — retrying with "
                             "a trimmed record set")
            text, stop = await _ask(json.dumps(records, default=str)[:25000])
        if not text:
            raise RuntimeError(f"review produced no text twice (stop_reason={stop})")
    except Exception as exc:
        rec.step("error", f"Review failed: {exc}")
        await _persist_run(eng, run_id, status="failed", rec=rec, error=str(exc)[:500])
        raise
    rec.step("final", text[:4000], experiment=batch)
    opinion = {"verdict": "review", "summary": text, "experiment": batch,
               "items": len(records), "model": model, "runId": run_id}
    await _persist_run(eng, run_id, status="done", rec=rec, opinion=opinion)
    # the findings note: experiment-scoped so it is NEVER injected into live runs
    try:
        await eng.signals_service.add_tip_note(
            f"experiment:{batch}", text[:2000], author=f"batch-review:{run_id[:8]}",
            run_id=run_id)
    except Exception:
        log.debug("review note save failed", exc_info=True)
    return opinion
