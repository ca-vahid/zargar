"""Intake-review context cost by component (S21-06, 2026-09-21 review). Read-only; no provider call.

Every captured review request (`reviewManifest` on the run's trace, behind `techniques.tip.review_capture_context`)
is split into its labelled components - the message + per-signal outcomes, the analyst's rulebook, the shared notes, the
source history - and priced at the run's own recorded input rate, so the desk can see WHAT it pays for on every review,
per source and per useful action, before deciding anything about retention or a cheaper route. Tokens are estimated as
characters / 4 (a tokenizer difference, not an invoice); the run's real usage is printed beside the estimate.

    python -m zargar.tools.tip_review_context_cost --since 2026-09-21
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json

MARKERS = [("message", "MESSAGE:"), ("outcomes", "PER-SIGNAL OUTCOMES:"), ("rules", "YOUR TRADING RULES"),
           ("notes", "SHARED NOTES"), ("history", "RECENT MESSAGES FROM THIS SOURCE")]
MGMT = {"update_exit_plan", "close_position", "disarm_plan"}


def split_header(header: str) -> dict[str, int]:
    """Characters per labelled component of one review header; `head` = what precedes the message (date, events)."""
    pos = [(name, header.find(mark)) for name, mark in MARKERS]
    pos = [(n, p) for n, p in pos if p >= 0]
    pos.sort(key=lambda x: x[1])
    out = {"head": pos[0][1] if pos else len(header)}
    for i, (name, p) in enumerate(pos):
        end = pos[i + 1][1] if i + 1 < len(pos) else len(header)
        out[name] = max(0, end - p)
    return out


def action_of(op: dict) -> str:
    tools = [t.get("tool") or t.get("name") for t in ((op or {}).get("toolsUsed") or [])]
    if any(t in MGMT for t in tools):
        return "management"
    if (op or {}).get("missedTip"):
        return "possible entry flagged"
    if "save_note" in tools:
        return "note only"
    return "nothing"


async def collect(conn, since: str) -> list[dict]:
    rows = await conn.fetch("""select r.id, r.source, r.created_at, r.opinion, s->'reviewManifest'->>'header' as header,
                                      s->'reviewManifest'->>'system' as system
                               from tip_analyst_runs r, jsonb_array_elements(r.trace) s
                               where r.kind='intake' and r.created_at >= $1 and s->>'kind'='context' and s ? 'reviewManifest'""",
                            dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc))
    out = []
    for r in rows:
        op = r["opinion"] if isinstance(r["opinion"], dict) else (json.loads(r["opinion"]) if r["opinion"] else {})
        u = (op or {}).get("usage") or {}
        parts = split_header(r["header"] or "")
        out.append({"id": r["id"], "source": r["source"], "at": r["created_at"], "action": action_of(op),
                    "parts": parts, "systemChars": len(r["system"] or ""), "headerChars": len(r["header"] or ""),
                    "calls": int(u.get("calls") or 0), "inTokens": int(u.get("in") or 0), "outTokens": int(u.get("out") or 0),
                    "tools": [t.get("tool") or t.get("name") for t in ((op or {}).get("toolsUsed") or [])]})
    return out


def render(rows: list[dict], since: str, rate_in: float | None) -> str:
    L = [f"# Intake review context cost by component (since {since}; {len(rows)} captured reviews; read-only)\n",
         "Characters per component of the EXACT request each review received (tokens ~ chars/4, an estimate). The rulebook and "
         "shared notes are supplied on every call of a review, so a multi-turn review pays them per turn. Priced at the "
         f"Opus 5 input list rate {('$%.2f/MTok' % rate_in) if rate_in else '(rate card missing - unpriced)'} - an estimate, not an invoice.\n"]
    if not rows:
        return "\n".join(L + ["No captured review requests in the window (capture knob off or no reviews)."])
    comps = ["head", "message", "outcomes", "rules", "notes", "history"]
    tot = {c: sum(r["parts"].get(c, 0) for r in rows) for c in comps}
    hdr = sum(r["headerChars"] for r in rows)
    L.append("| component | avg chars | share of header | est. tokens per review | est. $ per review (per turn) |")
    L.append("|---|---:|---:|---:|---:|")
    for c in comps:
        avg = tot[c] / len(rows)
        usd = (avg / 4 / 1e6 * rate_in) if rate_in else None
        L.append(f"| {c} | {avg:,.0f} | {tot[c] / max(hdr, 1) * 100:.0f}% | {avg / 4:,.0f} | {('$%.3f' % usd) if usd is not None else 'unpriced'} |")
    sys_avg = sum(r["systemChars"] for r in rows) / len(rows)
    L.append(f"\nSystem prompt + schema: {sys_avg:,.0f} chars per call (also per turn). Recorded usage: "
             f"{sum(r['calls'] for r in rows)} calls, {sum(r['inTokens'] for r in rows):,} input tokens across the {len(rows)} reviews "
             f"(mean {sum(r['inTokens'] for r in rows) / len(rows):,.0f} per review, {sum(r['calls'] for r in rows) / len(rows):.1f} turns).")
    L.append("\n## By useful action (what the review actually did)\n")
    L.append("| action | reviews | avg rules chars | avg notes chars | avg input tokens (recorded) | management tools |")
    L.append("|---|---:|---:|---:|---:|---|")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["action"]].append(r)
    for k, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
        L.append(f"| {k} | {len(g)} | {sum(x['parts'].get('rules', 0) for x in g) / len(g):,.0f} | "
                 f"{sum(x['parts'].get('notes', 0) for x in g) / len(g):,.0f} | {sum(x['inTokens'] for x in g) / len(g):,.0f} | "
                 f"{collections.Counter(t for x in g for t in x['tools'] if t in MGMT).most_common(3) or '-'} |")
    L.append("\n## By source\n")
    L.append("| source | reviews | avg header chars | avg rules | avg notes | avg history | management | note only | nothing |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    bys = collections.defaultdict(list)
    for r in rows:
        bys[r["source"] or "?"].append(r)
    for k, g in sorted(bys.items(), key=lambda kv: -len(kv[1])):
        n = len(g)
        L.append(f"| {k} | {n} | {sum(x['headerChars'] for x in g) / n:,.0f} | {sum(x['parts'].get('rules', 0) for x in g) / n:,.0f} | "
                 f"{sum(x['parts'].get('notes', 0) for x in g) / n:,.0f} | {sum(x['parts'].get('history', 0) for x in g) / n:,.0f} | "
                 f"{sum(1 for x in g if x['action'] == 'management')} | {sum(1 for x in g if x['action'] == 'note only')} | "
                 f"{sum(1 for x in g if x['action'] == 'nothing')} |")
    L.append("\nReading: the rulebook and the notes are the same text on every review of every source; a compact treatment "
             "(fewer / pinned rules, notes scoped to the tickers in the message) is the comparison to prepare on these captured "
             "cases - measured against the FULL context on identical inputs, keeping mixed / correction / protective cases, before "
             "anything is changed. No note is deleted and no route is changed by this report.")
    return "\n".join(L)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--since", default="2026-09-21")
    a = ap.parse_args()
    import asyncpg
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        rows = await collect(c, a.since)
        v = await c.fetchval("select value from settings where key = 'llm.rates'")
        rates = (json.loads(v) if isinstance(v, str) else v) or {}
        rates = rates.get("v", rates) if isinstance(rates, dict) else {}
        rate_in = float((rates.get("claude-opus-5") or {}).get("in") or 0) or None
    finally:
        await c.close()
    print(render(rows, a.since, rate_in))


if __name__ == "__main__":
    asyncio.run(main())
