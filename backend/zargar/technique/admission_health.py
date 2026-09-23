"""Systemic admission failure detection for EnhancedMarket (`admission-health-v1`, 2026-09-21).

On 2026-09-21 the experimental book fired thirteen times, deferred nine of them on
`venue_time_in_future`, placed no order all session, and NOTHING said so until a person went
looking. Each individual refusal was correct and unremarkable; only their SHAPE - many symbols,
one cause, no submissions - showed that the desk was not trading. This module recognises that
shape and hands it to the runner's existing alert path.

Design commitments, so this can never become a trading rule by accident:

* It is an ALARM, never a gate. Nothing here admits, refuses, retries, sizes or prices anything.
  The detector is pure and the caller decides only whether to shout.
* Thresholds are FROZEN and named (`THRESHOLDS`). They are tuned to catch a desk that has stopped
  trading, not to comment on an ordinary refusal: a stop that worked, a rule that said no, or a
  single missing quote must never page anyone.
* It reports what a person needs to act: how many, which symbols, when it started and last
  happened, the representative clock offsets, which book and which build.
* It de-duplicates, and it says when the condition RECOVERS, because an alarm nobody can clear is
  an alarm people learn to ignore.
"""
from __future__ import annotations

import time

VERSION = "admission-health-v1"

# Frozen 2026-09-21. Either condition raises the same alarm.
THRESHOLDS = {
    # A systemic evidence fault hits every symbol at once, so two DIFFERENT symbols failing for the
    # same reason in five minutes is already a pattern - one symbol could just be a thin quote.
    "distinctSymbolsWithinWindow": 2,
    "windowSeconds": 300,
    # A slower failure still has to be caught: three eligible attempts that produced no order at all
    # means the desk is armed and silent, whatever the spacing.
    "attemptsWithNoSubmission": 3,
    # One alarm per book per cause per half hour. Repeats update the counts instead of paging again.
    "cooldownSeconds": 1800,
}

# Dispositions that mean "the gate could not decide", as opposed to the method deciding not to trade.
UNDECIDED = ("deferred_missing_evidence", "deferred_error", "policy_error")


def _problems(rec: dict) -> list[str]:
    v = ((rec.get("underlying") or {}).get("validated") or {})
    return [str(p) for p in (v.get("problems") or [])]


def _offset_ms(rec: dict) -> float | None:
    """How far the evidence's venue time sits from this host's clock, in ms, positive = future.

    The record carries its own host timestamp and the venue's, so the gap is measurable per record
    without asking any clock a second time."""
    ev = ((rec.get("underlying") or {}).get("evidence") or {})
    host = int(rec.get("ts") or 0)
    stamps = [int(ev.get(k) or 0) for k in ("quoteTs", "lastTs")]
    stamps = [s for s in stamps if s > 0]
    if not host or not stamps:
        return None
    return float(max(stamps) - host)


class AdmissionWatch:
    """Bounded, in-memory. One per runner; state is cheap and rebuilt on restart (the journal keeps
    the durable record). Never raises into the caller: a broken alarm must not stop trading."""

    def __init__(self, *, thresholds: dict | None = None) -> None:
        self.t = {**THRESHOLDS, **(thresholds or {})}
        self._events: list[dict] = []          # recent undecided attempts (bounded)
        self._alarmed: dict[str, dict] = {}    # (book, cause) -> last alarm
        self._submitted: set[str] = set()      # books that have admitted at least one entry this run

    # ---- observation -------------------------------------------------------------------------
    def observe(self, rec: dict, *, book: str, symbol: str, disposition: str, build: str = "",
                now_ms: int | None = None) -> dict | None:
        """Feed ONE first-sale record. Returns an alarm dict when this record completes a pattern,
        else None. An admitted entry clears the book's silence."""
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if disposition not in UNDECIDED:
            if disposition == "passed":
                self._submitted.add(book)
                return self._recover(book, now)
            return None                                    # an ordinary refusal is the method working
        probs = _problems(rec)
        cause = probs[0] if probs else "unknown_evidence_problem"
        self._events.append({"at": now, "book": book, "symbol": str(symbol).upper(), "cause": cause,
                             "disposition": disposition, "offsetMs": _offset_ms(rec), "build": build})
        if len(self._events) > 500:
            self._events = self._events[-250:]
        return self._judge(book, cause, now)

    def _judge(self, book: str, cause: str, now: int) -> dict | None:
        win = int(self.t["windowSeconds"]) * 1000
        same = [e for e in self._events if e["book"] == book and e["cause"] == cause]
        recent = [e for e in same if now - e["at"] <= win]
        distinct_recent = {e["symbol"] for e in recent}
        distinct_all = {e["symbol"] for e in same}
        hit = (len(distinct_recent) >= int(self.t["distinctSymbolsWithinWindow"])
               or (book not in self._submitted and len(same) >= int(self.t["attemptsWithNoSubmission"])))
        if not hit:
            return None
        key = f"{book}:{cause}"
        prev = self._alarmed.get(key)
        if prev and now - int(prev["at"]) < int(self.t["cooldownSeconds"]) * 1000:
            prev["count"] = len(same)                      # keep counting quietly; do not page again
            prev["lastAt"] = same[-1]["at"]
            return None
        offs = [e["offsetMs"] for e in same if e["offsetMs"] is not None]
        alarm = {
            "version": VERSION, "kind": "systemic_admission_failure", "book": book, "cause": cause,
            "at": now, "count": len(same), "distinctSymbols": sorted(distinct_all)[:12],
            "firstAt": same[0]["at"], "lastAt": same[-1]["at"],
            "noSubmissionInBook": book not in self._submitted,
            "offsetsMs": ({"min": round(min(offs), 1), "max": round(max(offs), 1),
                           "representative": round(sorted(offs)[len(offs) // 2], 1)} if offs else None),
            "build": next((e["build"] for e in reversed(same) if e["build"]), ""),
            "thresholds": dict(self.t),
            "text": self._text(cause, len(same), sorted(distinct_all), offs, book not in self._submitted),
            "isGate": False,
        }
        self._alarmed[key] = {"at": now, "count": len(same), "lastAt": same[-1]["at"], "recovered": False}
        return alarm

    def _recover(self, book: str, now: int) -> dict | None:
        """The first admitted entry after an alarm closes it - once, and only for what was alarmed."""
        out = None
        for key, a in list(self._alarmed.items()):
            if key.startswith(f"{book}:") and not a.get("recovered"):
                a["recovered"] = True
                out = {"version": VERSION, "kind": "systemic_admission_recovered", "book": book,
                       "cause": key.split(":", 1)[1], "at": now, "count": a.get("count"),
                       "text": f"admission recovered in book {book[:8]}: an entry passed the gate after "
                               f"{a.get('count')} undecided attempt(s) on {key.split(':', 1)[1]}",
                       "isGate": False}
        return out

    @staticmethod
    def _text(cause: str, count: int, symbols: list[str], offs: list[float], silent: bool) -> str:
        who = ", ".join(symbols[:6]) + ("..." if len(symbols) > 6 else "")
        s = (f"admission is refusing every entry: {count} attempt(s) across {len(symbols)} symbol(s) ({who}) "
             f"undecided on {cause}")
        if offs:
            rep = sorted(offs)[len(offs) // 2]
            s += f"; venue evidence reads {rep / 1000:.1f}s from this host's clock"
            if cause == "venue_time_in_future":
                s += " - check host clock synchronization, the gate is correct to refuse"
        if silent:
            s += "; NO order has been submitted in this book"
        return s
