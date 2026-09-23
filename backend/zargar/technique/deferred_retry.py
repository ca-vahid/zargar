"""One bounded re-evaluation of an entry the admission gate could not decide (`deferral-retry-v1`).

PROPOSED POLICY, DEFAULT OFF. The frozen behaviour it sits beside is this: a first-sale
`deferred_missing_evidence` marks the trade `skipped` and the trigger never fires again. On
2026-09-21 all nine deferred experimental triggers - IREN, ON, NBIS, SMH, AVGO, AMGN, MRVL, APP and
QQQ - ended their session there. The word "deferred" promised a later look that the code never took.
That mismatch is the finding; this module is the separately disclosed proposal, not a silent repair.

What a retry may and may not do. It re-runs the SAME setup through the SAME production path, so
every gate - contract pick, option admission, sizing, day budget, no-chase, R2, first-sale again and
the final dispatch guard - runs exactly as it did the first time. It does not relax anything, does
not remember the earlier price, and does not create a second position.

The window is counted in BARS, from the bar the trigger fired on. That matters: the fault that
caused these deferrals was a wrong host clock, and a bar count cannot be stretched by a wrong clock
the way a wall-clock deadline can. A setup that was invalidated, stopped, expired or already
submitted is never revived.
"""
from __future__ import annotations

VERSION = "deferral-retry-v1"

# The dispositions this policy treats as "undecided, may look again". A refusal on the METHOD's own
# terms (`refused`) is a decision and is never retried.
RETRYABLE = ("deferred_missing_evidence", "deferred_error")
# A trade that has reached any of these has either been sent or is beyond recall.
SENT_OR_DONE = ("submitting", "working", "open", "closed", "cancelled", "failed", "proposal")


def normalize_mode(raw) -> str:
    """`off` (frozen behaviour) | `bounded` (one retry). Anything else is off: an unreadable policy
    must never invent a second entry attempt."""
    m = str(raw or "off").strip().lower()
    return m if m in ("off", "bounded") else "off"


def eligible(trade, tracker, *, bar_index: int, window_bars: int, retried: set | None = None,
             plan_status: str = "armed", halted: bool = False) -> tuple[bool, str]:
    """Pure: may this deferred trade be re-evaluated on the bar that just closed?

    Returns (allowed, why). `why` always explains the decision, including when it is yes, because
    the journal entry for a second attempt has to say what justified it.
    """
    tid = getattr(trade, "trigger_id", "")
    if halted:
        return False, "trading is halted for this book"
    if plan_status not in ("armed", "fired"):
        return False, f"the plan is {plan_status}, not armed"
    if getattr(trade, "status", "") != "skipped":
        st = getattr(trade, "status", "")
        return False, (f"the trade is {st} - already sent or resolved" if st in SENT_OR_DONE
                       else f"the trade is {st}, not a skipped attempt")
    if float(getattr(trade, "filled_qty", 0) or 0) > 0 or getattr(trade, "entry_order_id", None):
        return False, "an order already exists for this trade - a retry would double the position"
    disp = ((getattr(trade, "timing", None) or {}).get("firstSale") or {}).get("disposition")
    if disp not in RETRYABLE:
        return False, f"disposition {disp!r} is a decision, not an undecided attempt"
    if retried and tid in retried:
        return False, "this trigger has already used its one retry"
    fired_at = getattr(trade, "fire_bar_index", None)
    if fired_at is None:
        # Without the fire's own bar index there is no clock-proof window. Refuse rather than fall
        # back to wall time: the whole point of this policy is that a wrong clock cannot extend it.
        return False, "no fire bar index (restored trade) - cannot bound the window without a clock"
    elapsed = int(bar_index) - int(fired_at)
    if elapsed > int(window_bars):
        return False, f"the original entry window has elapsed ({elapsed} > {window_bars} bars) - T4.1, no chase"
    tstatus = str(getattr(tracker, "status", "") or "")
    if tstatus not in ("fired", "waiting", "armed"):
        return False, f"the setup is {tstatus} - invalidated, expired or already taken"
    return True, f"undecided on {disp} {elapsed} bar(s) ago, inside the original {window_bars}-bar window"


def record(trade, tracker, *, allowed: bool, why: str, bar_index: int, window_bars: int) -> dict:
    """The journalled account of a retry decision - taken or declined."""
    return {"version": VERSION, "trigger": getattr(trade, "trigger_id", ""), "retried": bool(allowed), "why": why,
            "disposition": ((getattr(trade, "timing", None) or {}).get("firstSale") or {}).get("disposition"),
            "firedBarIndex": getattr(trade, "fire_bar_index", None), "barIndex": int(bar_index),
            "windowBars": int(window_bars), "trackerStatus": str(getattr(tracker, "status", "") or ""),
            "note": "one bounded re-evaluation through the unchanged production path; no gate is relaxed"}
