"""Pre-refusal opportunity audit — what the desk saw before contract selection.

The selection study starts at contract selection, so a candidate refused on structure never reaches
it. On 2026-09-21 that hid the entire story: the study recorded zero primary opportunities while two
breakouts were being refused all morning because each had been handed its own source level as its
destination.

This is an ORDER-FREE, read-only audit over durable journal records. It starts no collector, changes
no setting, sends nothing and is not part of the frozen S1 population. Run it after the close.

Counting rule, learned the hard way on both desks: the unit is the PHYSICAL CANDIDATE, not the
refusal row. One SPY setup refused on eleven bars across three books is one candidate, not eleven
and not thirty-three. Identity is (date, symbol, setupId) — book-independent by construction, so the
same contact seen by three books deduplicates to one and two distinct contacts never collide.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict

AUDIT_VERSION = "opportunity-audit-v1"

# events that describe a candidate's life before an order exists
SETUP_EVENTS = ("scenario", "pm_break", "key_level_break", "setup_target_resolved", "setup_target_refused")
REFUSAL_EVENTS = ("skip_target_collision", "skip_no_trade_zone", "skip_target_behind", "skip_target_near",
                  "skip_engulfing", "skip_range_confirmation", "skip_no_contract", "skip_reentries",
                  "skip_last_entry", "skip_loss_cap", "skip_loss_cap_desk", "skip_pm_room",
                  "max_open_skip", "halt_skip", "paused_skip", "stale_signal_skip",
                  "backdated_signal_skip", "entry_gate_refused", "add_no_room")
PRICED_EVENTS = ("contract_picked", "contract_skipped", "fired")


def _candidate_key(date: str, symbol: str, setup_id: str) -> str:
    return f"{date}:{symbol}:{setup_id}"


async def collect(sf, day: str) -> dict:
    """Read one session's pre-order record and fold it into candidates."""
    from sqlalchemy import select
    from ..models import Event
    import datetime as _dt
    d = _dt.date.fromisoformat(day)
    lo = _dt.datetime.combine(d, _dt.time(0, 0), _dt.timezone.utc)
    hi = lo + _dt.timedelta(days=1)
    async with sf() as s:
        rows = (await s.execute(select(Event).where(Event.ts >= lo, Event.ts <= hi).order_by(Event.id))).scalars().all()
    return fold([(int(r.ts.timestamp() * 1000), r.type, dict(r.payload or {})) for r in rows], day)


def fold(rows: list[tuple], day: str) -> dict:
    """Pure: (tsMs, eventType, payload) rows -> deduplicated candidates. No I/O, so the counting
    rule can be tested directly rather than through a database."""
    runs: dict[str, dict] = {}           # runId -> {symbol, book}
    for ts_ms, etype, p in rows:
        rid = p.get("runId")
        if rid and etype in ("TechniquePlanArmed", "TechniquePlanRestored"):
            runs[rid] = {"symbol": p.get("symbol"), "book": p.get("portfolioId") or (p.get("config") or {}).get("portfolioId")}

    cands: dict[str, dict] = {}
    for ts_ms, etype, p in rows:
        ev, rid = str(p.get("event") or ""), p.get("runId")
        sym = p.get("symbol") or (runs.get(rid) or {}).get("symbol")
        book = (runs.get(rid) or {}).get("book")
        setup = p.get("setup") or p.get("trigger") or p.get("scenario")
        if not (sym and setup) or not (ev in SETUP_EVENTS or ev in REFUSAL_EVENTS or ev in PRICED_EVENTS):
            continue
        setup = str(setup).split("#")[0]                    # a touch is not a new candidate
        key = _candidate_key(day, sym, setup)
        c = cands.setdefault(key, {
            "id": key, "date": day, "symbol": sym, "setupId": setup, "direction": None,
            "source": None, "confirmedTs": None, "targetCandidates": None, "resolvedTarget": None,
            "firstSeenTs": ts_ms, "books": {}, "priced": False,
            "refusalChain": [], "actionableEvidence": None, "revisions": 0,
        })
        c["revisions"] += 1
        if ev in SETUP_EVENTS:
            c["confirmedTs"] = c["confirmedTs"] or ts_ms
            for src, dst in (("level", "source"), ("anchor", "source"), ("source", "source")):
                if p.get(src) is not None and c["source"] is None:
                    c["source"] = p.get(src)
            if p.get("record"):                              # setup-target-v1 resolution, when it ran
                c["targetCandidates"] = p["record"].get("ladder")
                c["resolvedTarget"] = p["record"].get("target")
        if ev in PRICED_EVENTS:
            c["priced"] = True
        if ev in REFUSAL_EVENTS:
            b = str(book or "?")[:8]
            c["books"].setdefault(b, {"refusals": [], "admitted": False})
            if ev not in [x["event"] for x in c["refusalChain"]]:
                c["refusalChain"].append({"event": ev, "firstTs": ts_ms,
                                          "reason": str(p.get("reason") or "")[:200]})
            bl = c["books"][b]["refusals"]
            if ev not in bl:
                bl.append(ev)
        if ev == "fired" or etype == "TechniquePlanTriggerFired":
            c["books"].setdefault(str(book or "?")[:8], {"refusals": [], "admitted": False})["admitted"] = True

    # a candidate the desk actually traded is admitted somewhere
    for ts_ms, etype, p in rows:
        if etype != "TechniquePlanTriggerFired":
            continue
        sym = p.get("symbol")
        setup = str(p.get("setupId") or p.get("trigger") or "").split("#")[0]
        key = _candidate_key(day, sym, setup)
        if key in cands:
            b = str((runs.get(p.get("runId")) or {}).get("book") or "?")[:8]
            cands[key]["books"].setdefault(b, {"refusals": [], "admitted": False})["admitted"] = True
            cands[key]["priced"] = True
    return cands


def summarise(cands: dict) -> dict:
    by_reason: dict[str, int] = defaultdict(int)
    never_priced, admitted, refused_everywhere = [], [], []
    for c in cands.values():
        if any(b["admitted"] for b in c["books"].values()):
            admitted.append(c["id"])
        elif c["refusalChain"]:
            refused_everywhere.append(c["id"])
            by_reason[c["refusalChain"][0]["event"]] += 1
        if not c["priced"]:
            never_priced.append(c["id"])
    return {
        "version": AUDIT_VERSION,
        "candidates": len(cands),
        "admittedSomewhere": len(admitted),
        "refusedEverywhere": len(refused_everywhere),
        "neverPriced": len(never_priced),
        "firstRefusalByReason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
        "note": ("counts are PHYSICAL CANDIDATES deduplicated across books, revisions and repeated bars - "
                 "never refusal rows; option evidence is unknown for anything never priced"),
    }


async def _amain(a) -> int:
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    eng = make_engine(get_config().database_url)
    try:
        sf = make_session_factory(eng)
        cands = await collect(sf, a.date)
    finally:
        await eng.dispose()
    out = {"summary": summarise(cands), "candidates": sorted(cands.values(), key=lambda c: (c["symbol"], c["setupId"]))}
    if a.summary_only:
        out.pop("candidates")
    print(json.dumps(out, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Order-free pre-refusal opportunity audit (read-only).")
    ap.add_argument("date", help="session date, YYYY-MM-DD")
    ap.add_argument("--summary-only", action="store_true")
    return asyncio.run(_amain(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
