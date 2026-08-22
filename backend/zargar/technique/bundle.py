"""Run bundle — everything about one run, on disk, in a reviewable shape.

`build_bundle()` joins the run row, its setups / outcomes / reviews / replays,
the chat thread (every pass prompt + response, tool calls + results, the
summary, reviews), the journal events keyed to the run, and the asset list.
`write_bundle()` lays it out as files the `/technique-review` skill (or a human)
reads top-down:

    run.json          run row + config + setups + outcomes + reviews + replays
    facts.json        detector output the model was given
    trace.md          the decision trace, one line per step, with reasons
    transcript.md     each pass: prompt -> thinking -> text -> parsed JSON;
                      tool calls (args, reason, result) for chat-driven runs
    transcript.json   the raw chat messages
    grounding.json    every grounding check
    outcome.json      what price did afterwards (per plan) + path
    journal.json      events for the run (started/completed/outcome/review/...)
    bars/<tf>.json    full bar windows the pipeline saw (from the snapshot)
    bars/after.json   bars after as_of used for scoring
    images/*.png      per-tf charts, the annotated chart, the user's image
    README.md         what each file is + the one-paragraph summary

`zip_bundle()` returns the same tree as a zip for the API.
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import zipfile
from pathlib import Path

from sqlalchemy import select

from ..models import ChatAsset, ChatMessage, ChatThread, Event
from .outcome import describe_outcome
from .rulebook import RULES


def _ts(ms: int | None) -> str:
    if not ms:
        return "—"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


async def build_bundle(svc, run_id: str) -> dict:
    """Gather everything for `run_id` into one JSON-able dict. `svc` is the
    TechniqueService (needs .engine.sf and .chat)."""
    run = await svc.get_run(run_id)
    if run is None:
        raise KeyError(f"run {run_id} not found")
    thread = await svc.chat.get_thread(run["threadId"]) if run.get("threadId") else None
    async with svc.engine.sf() as session:
        events = (await session.execute(
            select(Event).where(Event.aggregate_id == run_id).order_by(Event.id))).scalars().all()
        setup_ids = [s["id"] for s in run.get("setups") or []]
        sev = (await session.execute(
            select(Event).where(Event.aggregate_id.in_(setup_ids)).order_by(Event.id))).scalars().all() \
            if setup_ids else []
        tool_events = (await session.execute(
            select(Event).where(Event.aggregate_id == run["threadId"], Event.type == "ChatToolCalled")
            .order_by(Event.id))).scalars().all() if run.get("threadId") else []
        assets = (await session.execute(
            select(ChatAsset.id, ChatAsset.media_type, ChatAsset.meta, ChatAsset.created_at)
            .where(ChatAsset.thread_id == run["threadId"]))).all() if run.get("threadId") else []
    ev_dicts = [{"id": e.id, "ts": e.ts.isoformat() if e.ts else None, "type": e.type,
                 "aggregateType": e.aggregate_type, "aggregateId": e.aggregate_id, "payload": e.payload}
                for e in sorted(list(events) + list(sev) + list(tool_events), key=lambda x: x.id)]
    parent = await svc.get_run(run["parentRunId"]) if run.get("parentRunId") else None
    return {
        "run": run,
        "thread": thread,
        "events": ev_dicts,
        "assets": [{"id": a.id, "mediaType": a.media_type, "meta": a.meta or {},
                    "createdAt": a.created_at.isoformat() if a.created_at else None} for a in assets],
        "parent": ({k: parent.get(k) for k in ("id", "symbol", "asOf", "verdict", "setupType",
                                                "confidence", "processVersion", "createdAt")}
                   if parent else None),
        "rules": RULES,
        "exportedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# --- renderers ---------------------------------------------------------------------------

def render_trace_md(run: dict) -> str:
    trace = (run.get("result") or {}).get("trace") or []
    L = [f"# Trace — {run.get('symbol')} {run.get('primaryTf')} · run {run.get('id')}", ""]
    if not trace:
        L.append("_No trace recorded (run predates tracing, or it failed before the first step)._")
        return "\n".join(L) + "\n"
    L.append("| # | t (s) | stage | step | reason |")
    L.append("|--:|------:|-------|------|--------|")
    for r in trace:
        reason = str(r.get("reason", "")).replace("|", "\\|").replace("\n", " ")
        L.append(f"| {r.get('seq')} | {r.get('t') if r.get('t') is not None else ''} | {r.get('stage')} "
                 f"| {r.get('step')} | {reason} |")
    L.append("")
    L.append("## Details")
    L.append("")
    for r in trace:
        d = r.get("detail")
        if not d:
            continue
        L.append(f"### {r.get('seq')} · {r.get('stage')} / {r.get('step')}")
        L.append("```json")
        L.append(json.dumps(d, indent=1, default=str))
        L.append("```")
        L.append("")
    return "\n".join(L) + "\n"


def _block_text(b: dict) -> str:
    t = b.get("type")
    if t == "text":
        return b.get("text", "")
    if t == "thinking":
        return "_(thinking)_\n\n" + (b.get("thinking") or "")
    if t == "redacted_thinking":
        return "_(redacted thinking)_"
    if t == "image_ref":
        return f"_(image asset {b.get('assetId')} · {b.get('mediaType') or b.get('bytes', '')})_"
    if t == "tool_use":
        return f"**tool_use** `{b.get('name')}` id `{b.get('id')}`\n```json\n{json.dumps(b.get('input'), indent=1, default=str)}\n```"
    if t == "tool_result":
        c = b.get("content")
        meta = b.get("meta") or {}
        if isinstance(c, list):
            inner = "\n".join(_block_text(x) for x in c)
        else:
            inner = str(c)
        if len(inner) > 6000:
            inner = inner[:6000] + f"\n… ({len(inner) - 6000} more chars)"
        return (f"**tool_result** `{meta.get('name', '')}` for `{b.get('tool_use_id')}`"
                + (" **(error)**" if b.get("is_error") else "")
                + (f" · {meta.get('seconds')}s" if meta.get("seconds") is not None else "")
                + f"\n```\n{inner}\n```")
    return f"_({t} block)_"


def render_transcript_md(bundle: dict) -> str:
    run = bundle["run"]
    thread = bundle.get("thread") or {}
    L = [f"# Transcript — {run.get('symbol')} {run.get('primaryTf')} · run {run.get('id')}", ""]
    L.append(f"Thread `{thread.get('id')}` · {thread.get('messageCount', 0)} messages · "
             f"model {run.get('llm', {}).get('model')} effort {run.get('llm', {}).get('effort')}")
    L.append("")
    for m in thread.get("messages") or []:
        meta = m.get("meta") or {}
        kind = meta.get("kind")
        head = f"## #{m.get('seq')} {m.get('role')}"
        if meta.get("pass"):
            head += f" · pass **{meta['pass']}**"
        if kind:
            head += f" · {kind}"
        if meta.get("usage"):
            u = meta["usage"]
            head += f" · {u.get('input', 0)}↓ {u.get('output', 0)}↑"
        if meta.get("seconds") is not None:
            head += f" · {meta['seconds']}s"
        L.append(head)
        L.append("")
        for b in m.get("blocks") or []:
            L.append(_block_text(b))
            L.append("")
        if meta.get("parsed") is not None:
            L.append("**parsed (structured output):**")
            L.append("```json")
            L.append(json.dumps(meta["parsed"], indent=1, default=str))
            L.append("```")
            L.append("")
    return "\n".join(L) + "\n"


def render_readme(bundle: dict) -> str:
    run = bundle["run"]
    res = run.get("result") or {}
    a = res.get("analysis") or {}
    g = res.get("grounding") or {}
    cfg = run.get("config") or {}
    outs = run.get("outcomes") or []
    revs = run.get("reviews") or []
    L = [f"# Run {run.get('id')} — {run.get('symbol')} {run.get('primaryTf')}", ""]
    L.append(f"- status **{run.get('status')}** · verdict **{run.get('verdict')}**"
             + (f" ({run.get('setupType')})" if run.get("setupType") else "")
             + f" · confidence {run.get('confidence')} · grounded {run.get('grounded')}")
    L.append(f"- as of {_ts(run.get('asOf'))}{' (live)' if not run.get('asOf') else ''} · created {run.get('createdAt')} "
             f"· trigger {run.get('trigger')} · mode {run.get('mode')}")
    L.append(f"- process version `{cfg.get('processVersion')}` · prompt `{cfg.get('promptVersion')}` · "
             f"rulebook `{cfg.get('rulebookVersion')}` · code `{cfg.get('codeVersion')}` · "
             f"model {cfg.get('model')} / {cfg.get('effort')}")
    if run.get("parentRunId"):
        L.append(f"- replay of `{run['parentRunId']}` with overrides {json.dumps(cfg.get('overrides'))}")
    if a:
        if a.get("entry"):
            L.append(f"- plan: entry {a['entry']['price']} ({a['entry'].get('basis')}) · stop {a['stop']['price']} · "
                     f"targets {[t['price'] for t in a.get('targets', [])]} · R:R {a.get('riskReward')}")
        L.append(f"- rules fired: {', '.join(a.get('rulesFired') or [])}")
        if a.get("noTradeReasons"):
            L.append("- no-trade reasons / warnings:")
            for r in a["noTradeReasons"]:
                L.append(f"  - {r}")
    if g:
        failed = [c for c in g.get("checks") or [] if not c.get("passed")]
        L.append(f"- grounding: {'passed' if g.get('passed') else 'FAILED'} "
                 f"({len(g.get('checks') or []) - len(failed)}/{len(g.get('checks') or [])} checks)")
    if outs:
        L.append("- outcome:")
        for o in outs:
            L.append(f"  - {describe_outcome(o)}")
    else:
        L.append("- outcome: not scored yet")
    if revs:
        L.append("- reviews:")
        for r in revs:
            L.append(f"  - {r['createdAt']} {r['reviewer']}: **{r['reviewVerdict']}**"
                     + (f" · root cause {r['rootCauseStage']}" if r.get("rootCauseStage") else "")
                     + (f" · expected {r['expectedVerdict']}" if r.get("expectedVerdict") else "")
                     + (f" — {r['notes'][:200]}" if r.get("notes") else ""))
    else:
        L.append("- reviews: none")
    if run.get("replays"):
        L.append("- replays: " + ", ".join(f"`{c['id']}` ({c.get('verdict')}, {c.get('status')})"
                                          for c in run["replays"]))
    L += ["", "## Files", "",
          "| file | what |", "|---|---|",
          "| `run.json` | run row (+ config/provenance, setups, outcomes, reviews, replays) |",
          "| `facts.json` | deterministic FACTS the model was given (levels, volume, trend, candidates) |",
          "| `trace.md` | decision trace — every step and why, in order |",
          "| `transcript.md` / `transcript.json` | each pass prompt, thinking, text, structured output; tool calls |",
          "| `grounding.json` | every grounding check with detail |",
          "| `outcome.json` | what price did afterwards, per plan, + path summary |",
          "| `journal.json` | events for this run |",
          "| `bars/<tf>.json` | full bar windows the pipeline saw (`[ts, o, h, l, c, v]`) |",
          "| `bars/after.json` | bars after as_of used for outcome scoring |",
          "| `images/` | charts the model saw (`<tf>.png`), `annotated.png`, `user.*` |",
          ""]
    L.append(f"_exported {bundle.get('exportedAt')}_")
    return "\n".join(L) + "\n"


# --- writers ------------------------------------------------------------------------------

def _ext(media_type: str) -> str:
    return {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
            "application/json": "json", "application/gzip": "json.gz"}.get(media_type, "bin")


async def bundle_files(svc, bundle: dict) -> dict[str, bytes]:
    """The bundle as {relative path: bytes}."""
    run = bundle["run"]
    res = run.get("result") or {}
    files: dict[str, bytes] = {}

    def put(name: str, obj) -> None:
        if isinstance(obj, (bytes, bytearray)):
            files[name] = bytes(obj)
        elif isinstance(obj, str):
            files[name] = obj.encode("utf-8")
        else:
            files[name] = json.dumps(obj, indent=1, default=str).encode("utf-8")

    slim_run = {k: v for k, v in run.items() if k not in ("facts", "live")}
    put("run.json", slim_run)
    put("facts.json", run.get("facts") or {})
    put("trace.md", render_trace_md(run))
    put("transcript.md", render_transcript_md(bundle))
    put("transcript.json", (bundle.get("thread") or {}).get("messages") or [])
    put("grounding.json", res.get("grounding") or {})
    put("outcome.json", {"outcomes": run.get("outcomes") or [], "asOf": run.get("asOf"),
                         "symbol": run.get("symbol"), "tf": run.get("primaryTf")})
    put("journal.json", bundle.get("events") or [])
    put("README.md", render_readme(bundle))
    put("rules.json", bundle.get("rules") or {})

    # bars snapshot
    aid = (run.get("config") or {}).get("barsAssetId")
    if aid:
        data = await svc.chat.get_asset_bytes(aid)
        if data:
            try:
                snap = json.loads(gzip.decompress(data).decode("utf-8"))
                for tf, rows in (snap.get("bars") or {}).items():
                    put(f"bars/{tf}.json", rows)
            except Exception:
                put("bars/snapshot.json.gz", data)
    for o in run.get("outcomes") or []:
        if o.get("barsAssetId"):
            data = await svc.chat.get_asset_bytes(o["barsAssetId"])
            if data:
                put("bars/after.json", data)
            break
    # images
    for key, aid in (run.get("images") or {}).items():
        got = await svc.chat.get_asset(aid)
        if not got:
            continue
        data, mt = got
        if key == "bars":
            continue
        put(f"images/{key}.{_ext(mt)}", data)
    # tool-call images from chat runs live in the thread's assets
    for a in bundle.get("assets") or []:
        meta = a.get("meta") or {}
        if meta.get("kind") in ("pass_chart", "annotated", "user_image", "bars_snapshot", "bars_after"):
            continue
        if str(a.get("mediaType", "")).startswith("image/"):
            got = await svc.chat.get_asset(a["id"])
            if got:
                put(f"images/asset_{a['id'][:8]}.{_ext(got[1])}", got[0])
    return files


async def write_bundle(svc, run_id: str, out_dir: str | Path) -> Path:
    bundle = await build_bundle(svc, run_id)
    files = await bundle_files(svc, bundle)
    root = Path(out_dir) / run_id
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


async def zip_bundle(svc, run_id: str) -> bytes:
    bundle = await build_bundle(svc, run_id)
    files = await bundle_files(svc, bundle)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, data in files.items():
            z.writestr(f"{run_id}/{rel}", data)
    return buf.getvalue()
