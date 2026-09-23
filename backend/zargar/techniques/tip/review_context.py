"""Compact intake-review context (ADV-04, 2026-09-23). Pure text transform; the live review and the frozen comparison
use the same function, so what is measured is what would run.

An intake review mostly reconciles an update against the book (close / trim / stop moves) or flags a possible entry.
The FULL header hands it the whole self-maintained rulebook (~42k chars, 68% of the request) and up to a dozen long
shared notes (~22k chars) on every turn. The compact treatment keeps every rule's HEADLINE (its first clause - the
family and the principle), drops the non-operative pending-proposal block to titles, and keeps only the notes scoped
to a ticker in the message, to the message's source, or the few most recent general notes, each trimmed.

Nothing is invented: every kept line is a verbatim prefix of the original.
"""
from __future__ import annotations

import re

RULES_MARK = "YOUR TRADING RULES"
PENDING_MARK = "PENDING RULE PROPOSALS"
NOTES_MARK = "SHARED NOTES"
HISTORY_MARK = "RECENT MESSAGES FROM THIS SOURCE"
RULE_HEAD_CHARS = 260
NOTE_CHARS = 420
MAX_GENERAL_NOTES = 3


def _headline(line: str, limit: int) -> str:
    """The rule's first clause: up to the first ': ' after the family label, bounded by `limit`."""
    body = line.rstrip()
    cut = body.find("): ")
    if cut == -1:
        cut = body.find(": ")
    end = min(len(body), limit) if cut == -1 else min(len(body), max(cut + 2, 0) + 140, limit)
    return body[:end] + (" …" if end < len(body) else "")


def _section(header: str, start: str, ends: list[str]) -> tuple[int, int] | None:
    i = header.find(start)
    if i == -1:
        return None
    j = min([k for k in (header.find(e, i + len(start)) for e in ends) if k != -1], default=len(header))
    return i, j


def compact_review_header(header: str, *, tickers: list[str] | None = None, source: str | None = None,
                          notes_only: bool = False) -> str:
    """`notes_only` (2026-09-23, cost lever 2): keep the rulebook AND the pending proposals verbatim and trim only the
    shared notes - the full compact form (rule headlines) lost a disarm and changed a close in the ADV-04 comparison."""
    tick = {str(t).upper() for t in (tickers or []) if t}
    out = header
    # 1. rules -> headlines (operative block)
    sec = None if notes_only else _section(out, RULES_MARK, [PENDING_MARK, NOTES_MARK, HISTORY_MARK])
    if sec:
        i, j = sec
        lines = out[i:j].split("\n")
        kept = [lines[0]] + [(_headline(ln, RULE_HEAD_CHARS) if ln.startswith("- ") else ln) for ln in lines[1:]]
        kept.insert(1, "(compact: each rule's headline; the full text is unchanged in the rulebook)")
        out = out[:i] + "\n".join(kept) + out[j:]
    # 2. pending proposals -> titles only
    sec = None if notes_only else _section(out, PENDING_MARK, [NOTES_MARK, HISTORY_MARK])
    if sec:
        i, j = sec
        lines = out[i:j].split("\n")
        kept = [lines[0]] + [(_headline(ln, 140) if ln.startswith("- ") else ln) for ln in lines[1:]]
        out = out[:i] + "\n".join(kept) + out[j:]
    # 3. notes -> ticker / source scoped, a few general, each trimmed
    sec = _section(out, NOTES_MARK, [HISTORY_MARK])
    if sec:
        i, j = sec
        lines = out[i:j].split("\n")
        head, body = lines[0], [ln for ln in lines[1:] if ln.startswith("- ")]
        rest = [ln for ln in lines[1:] if not ln.startswith("- ")]
        keep, general = [], 0
        for ln in body:
            m = re.match(r"- \[([^\]]+)\]", ln)
            scope = (m.group(1) if m else "").strip()
            fam, _, ent = scope.partition(":")
            relevant = ((fam == "ticker" and ent.upper() in tick) or (fam == "source" and source and ent == source)
                        or any(re.search(rf"\b{re.escape(t)}\b", ln) for t in tick))
            if not relevant and fam == "general" and general < MAX_GENERAL_NOTES:
                general += 1
                relevant = True
            if relevant:
                keep.append(ln[:NOTE_CHARS] + (" …" if len(ln) > NOTE_CHARS else ""))
        note = f"(compact: {len(keep)} of {len(body)} notes - scoped to the message's tickers/source + {MAX_GENERAL_NOTES} recent general)"
        out = out[:i] + "\n".join([head, note] + keep + [r for r in rest if r.strip()]) + "\n\n" + out[j:]
    return out


def tickers_in(message: str, outcomes: list[dict] | None = None) -> list[str]:
    """Tickers named in the message ($ABC or bare caps 2-5 letters followed by a strike/expiry cue) plus outcome tickers."""
    found = {m.group(1) for m in re.finditer(r"\$([A-Z]{1,6})\b", message or "")}
    for o in outcomes or []:
        if o.get("ticker"):
            found.add(str(o["ticker"]).upper())
    return sorted(found)
