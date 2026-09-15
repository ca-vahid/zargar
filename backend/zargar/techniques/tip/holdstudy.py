"""PROF-03 (2026-09-15): overnight-hold comparison - RESEARCH ONLY.

Four Tips trades exited in the next session's first minute for -$725.66. Is
carrying overnight worse than a predeclared intraday close, by setup? This
module collects the evidence contemporaneously and compares two arms on the
same positions with the same costs:

- `carry`: what the position actually does (its stops and exits stay exactly
  as they are - nothing here touches a position), measured against the next
  session's first qualified quote;
- `intraday_exit`: a PREDECLARED alternative - selling at the pre-close
  qualified BID - never a hindsight peak.

Positions that DID exit intraday are snapshotted too, so a sacrificed next-day
winner counts against the intraday arm. A missing, stale or unqualified quote
(cohort.qualify_quote: provenance, delayed flag, genuine source time, session)
is INSUFFICIENT evidence, reported, never filled in. Results are paired net-R
by setup; no blanket rule is derived here.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from ...domain import new_id
from . import cohort as _cohort

log = logging.getLogger("zargar.tip.holdstudy")

ET = ZoneInfo("America/New_York")
STUDY_VERSION = "holdstudy-v1"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(x) -> str | None:
    return x.isoformat() if hasattr(x, "isoformat") else (str(x) if x is not None else None)


def session_date(now: dt.datetime | None = None) -> str:
    return (now or _utcnow()).astimezone(ET).date().isoformat()


def _snap(eng, sym: str, *, is_option: bool, kind: str) -> tuple[dict | None, str]:
    max_age = float(eng.settings.get("techniques.tip.entry_cohort_quote_max_age_seconds", 300.0) or 300.0)
    return _cohort._snap_quote(eng, sym, max_age_s=max_age, kind=kind, is_option=is_option)


def setup_of(row: dict) -> str:
    """The setup bucket a pair is compared within: vehicle x DTE bucket (options)."""
    if row.get("secType") != "OPT":
        return "shares"
    dte = row.get("dteAtSnapshot")
    if dte is None:
        return "option:dte-unknown"
    d = int(dte)
    return "option:lotto(<=3d)" if d <= 3 else ("option:short(<=14d)" if d <= 14 else "option:longer(>14d)")


def compare_row(row: dict, *, fee_per_contract: float = 0.0, stock_commission: float = 0.0) -> dict:
    """Pure: the two arms for one snapshot row. `carry` = the next session's
    first qualified bid; `intraday_exit` = the pre-close qualified bid (or, for
    a position that really exited intraday, its actual exit price). Both net
    of the same costs, in $ and in R (R = the planned stop risk of the whole
    size at the snapshot). Insufficient whenever an arm lacks a qualified quote."""
    qty = float(row.get("qty") or 0)
    mult = float(row.get("multiplier") or (100.0 if row.get("secType") == "OPT" else 1.0))
    entry = float(row.get("entryPrice") or 0)
    fee = (fee_per_contract if row.get("secType") == "OPT" else stock_commission) * qty
    out = {"version": STUDY_VERSION, "id": row.get("id"), "symbol": row.get("symbol"), "legSymbol": row.get("legSymbol"),
           "arm": row.get("arm"), "setup": setup_of(row), "qty": qty, "entryPrice": entry,
           "plannedRisk": row.get("plannedRisk"), "adequate": False, "reason": None}
    pre = row.get("precloseQuote") or {}
    nxt = row.get("nextOpenQuote") or {}
    pre_ok = row.get("precloseStatus") == "fresh" and float(pre.get("bid") or 0) > 0
    nxt_ok = row.get("nextOpenStatus") == "fresh" and float(nxt.get("bid") or 0) > 0
    if row.get("arm") == "intraday_exit":
        exit_px = row.get("exitPrice")
        pre_ok = exit_px is not None and float(exit_px) > 0
        pre_bid = float(exit_px or 0)
    else:
        pre_bid = float(pre.get("bid") or 0)
    if not pre_ok or not nxt_ok:
        out["reason"] = ("no qualified pre-close quote" if not pre_ok else "no qualified next-open quote") + \
            (f" ({row.get('precloseStatus') if not pre_ok else row.get('nextOpenStatus')})")
        return out
    intraday = (pre_bid - entry) * qty * mult - fee
    carry = (float(nxt["bid"]) - entry) * qty * mult - fee
    r = float(row.get("plannedRisk") or 0) or None
    out.update(adequate=True,
               intradayExit={"price": pre_bid, "net": round(intraday, 2), "R": (round(intraday / r, 2) if r else None)},
               carryToNextOpen={"price": float(nxt["bid"]), "net": round(carry, 2), "R": (round(carry / r, 2) if r else None)},
               carryMinusIntraday=round(carry - intraday, 2),
               sacrificedWinner=(row.get("arm") == "intraday_exit" and carry > intraday),
               note="carry is measured at the next session's FIRST qualified bid, not a later peak; "
                    "the position's real stops/exits were untouched")
    return out


def aggregate(results: list[dict]) -> dict:
    """Paired net-R by setup with counts; insufficient rows are counted, never
    dropped silently. No winner is chosen here."""
    by: dict[str, dict] = {}
    for r in results:
        b = by.setdefault(r["setup"], {"n": 0, "insufficient": 0, "carryNet": 0.0, "intradayNet": 0.0,
                                       "carryR": [], "intradayR": [], "sacrificedWinners": 0, "arms": {"carry": 0, "intraday_exit": 0}})
        b["arms"][r.get("arm") or "carry"] = b["arms"].get(r.get("arm") or "carry", 0) + 1
        if not r.get("adequate"):
            b["insufficient"] += 1
            continue
        b["n"] += 1
        b["carryNet"] += r["carryToNextOpen"]["net"]
        b["intradayNet"] += r["intradayExit"]["net"]
        if r["carryToNextOpen"].get("R") is not None:
            b["carryR"].append(r["carryToNextOpen"]["R"])
            b["intradayR"].append(r["intradayExit"]["R"])
        if r.get("sacrificedWinner"):
            b["sacrificedWinners"] += 1
    for b in by.values():
        b["carryNet"] = round(b["carryNet"], 2)
        b["intradayNet"] = round(b["intradayNet"], 2)
        b["meanCarryR"] = round(sum(b["carryR"]) / len(b["carryR"]), 3) if b["carryR"] else None
        b["meanIntradayR"] = round(sum(b["intradayR"]) / len(b["intradayR"]), 3) if b["intradayR"] else None
        b["pairedDiffR"] = (round(b["meanCarryR"] - b["meanIntradayR"], 3)
                            if b["meanCarryR"] is not None and b["meanIntradayR"] is not None else None)
        del b["carryR"], b["intradayR"]
    return {"version": STUDY_VERSION, "setups": by,
            "disclaimer": "paired arithmetic on contemporaneous qualified quotes; small samples, no rule derived"}


# ------------------------------------------------------------------ collection (inside the app)
def _planned_risk(p: dict, leg: dict) -> float | None:
    stop = ((p.get("state") or {}).get("stop")) or (((p.get("policy") or {}).get("stop") or {}).get("price"))
    entry_ref = p.get("entry")
    if stop is None or not entry_ref:
        return None
    dist = (float(entry_ref) - float(stop)) if p.get("direction") != "short" else (float(stop) - float(entry_ref))
    if dist <= 0:
        return None
    qty = abs(float(leg.get("qty") or 0))
    if leg.get("secType") == "OPT":
        # options: the geometry gate's planned risk when it was recorded, else unknown
        rp = ((p.get("extras") or {}).get("riskPlan") or {})
        return float(rp["plannedRisk"]) if rp.get("plannedRisk") else None
    return round(dist * qty, 2)


def _dte(leg_symbol: str, today: dt.date) -> int | None:
    with contextlib.suppress(Exception):
        from ...options import occ as _occ
        o = _occ.parse(leg_symbol)
        if o is not None:
            return (o.expiry - today).days
    return None


async def snapshot_preclose(eng, *, now: dt.datetime | None = None) -> int:
    """Scheduler job `tip_hold_snapshot` (default 15:50 ET): one row per open
    Tips position (arm carry) and per Tips position that exited intraday today
    (arm intraday_exit), with the qualified pre-close quote of the exact leg.
    Places nothing, changes no policy."""
    from ...models import TipHoldSnapshotRow
    if not bool(eng.settings.get("techniques.tip.hold_study_enabled", True)):
        return 0
    now = now or _utcnow()
    sess = session_date(now)
    today = now.astimezone(ET).date()
    mgr = getattr(eng, "position_manager", None)
    if mgr is None:
        return 0
    rows = [p for p in mgr.positions() if (p.get("technique") == "tip")]
    n = 0
    for p in rows:
        legs = [l for l in (p.get("legs") or []) if l.get("secType") in ("OPT", "STK")]
        if not legs:
            continue
        leg = legs[0]
        closed_ms = p.get("closedMs")
        is_open = p.get("status") == "open" and abs(float(leg.get("qty") or 0)) > 0
        exited_today = (p.get("status") == "closed" and closed_ms
                        and dt.datetime.fromtimestamp(int(closed_ms) / 1000, tz=dt.timezone.utc).astimezone(ET).date() == today)
        if not is_open and not exited_today:
            continue
        arm = "carry" if is_open else "intraday_exit"
        sym = str(leg.get("symbol"))
        is_opt = leg.get("secType") == "OPT"
        if is_opt:
            with contextlib.suppress(Exception):
                await eng.options.refresh_now(sym)
        quote, status = _snap(eng, sym, is_option=is_opt, kind="preclose")
        exit_px = None
        exit_qty = None
        if arm == "intraday_exit":
            fills = [x for x in (p.get("exits") or []) if float(x.get("filledQty") or 0) > 0]
            if fills:
                exit_qty = sum(float(x["filledQty"]) for x in fills)
                exit_px = sum(float(x["filledQty"]) * float(x.get("price") or 0) for x in fills) / exit_qty
        policy = p.get("policy") or {}
        row = TipHoldSnapshotRow(
            id=new_id(), position_id=str(p["id"]), session_date=sess, arm=arm,
            symbol=str(p.get("symbol")), leg_symbol=sym, sec_type=str(leg.get("secType")),
            qty=(exit_qty if arm == "intraday_exit" and exit_qty else abs(float(leg.get("qty") or 0))),
            entry_price=float(leg.get("avgFill") or p.get("entry") or 0), direction=str(p.get("direction") or "long"),
            source=next((t.split(":", 1)[1] for t in (p.get("tags") or []) if str(t).startswith("source:")), None),
            horizon={"maxHoldSessions": policy.get("time_stop_sessions"), "sessionsHeld": p.get("sessionsHeld"),
                     "dte": _dte(sym, today) if is_opt else None, "openedMs": p.get("openedMs")},
            exits_policy={"stop": (p.get("state") or {}).get("stop"), "ladder": policy.get("ladder"),
                          "premiumStopPct": ((policy.get("premium_stop") or {}).get("pct") if isinstance(policy.get("premium_stop"), dict) else policy.get("premium_stop"))},
            planned_risk=_planned_risk(p, leg), fees={"perContract": float(eng.settings.get("options.fee_per_contract", 0.0) or 0.0),
                                                     "stockCommission": float(eng.settings.get("sim.stock_commission", 0.0) or 0.0)},
            preclose_quote=quote, preclose_status=status, exit_price=exit_px,
            next_open_quote=None, next_open_status="pending", gaps=([] if status == "fresh" else [f"pre-close quote {status}"]))
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        n += 1
    if n:
        log.info("hold study: %d pre-close snapshot(s) for %s", n, sess)
    return n


async def sample_next_open(eng, *, now: dt.datetime | None = None) -> int:
    """Scheduler job `tip_hold_next_open` (default 09:36 ET): the first
    qualified quote of the new session for every snapshot still pending."""
    from sqlalchemy import select
    from ...models import TipHoldSnapshotRow
    if not bool(eng.settings.get("techniques.tip.hold_study_enabled", True)):
        return 0
    now = now or _utcnow()
    today = session_date(now)
    async with eng.sf() as session:
        rows = (await session.execute(select(TipHoldSnapshotRow).where(
            TipHoldSnapshotRow.next_open_status == "pending", TipHoldSnapshotRow.session_date < today))).scalars().all()
        ids = [r.id for r in rows]
    n = 0
    for rid in ids:
        async with eng.sf() as session:
            r = await session.get(TipHoldSnapshotRow, rid)
            if r is None or r.next_open_status != "pending":
                continue
            sym, is_opt = r.leg_symbol, r.sec_type == "OPT"
        if is_opt:
            with contextlib.suppress(Exception):
                await eng.options.refresh_now(sym)
        quote, status = _snap(eng, sym, is_option=is_opt, kind="next_open")
        async with eng.sf() as session:
            r = await session.get(TipHoldSnapshotRow, rid, with_for_update=True)
            if r is None or r.next_open_status != "pending":
                continue
            r.next_open_quote = quote
            r.next_open_status = status if quote is not None else "missing"
            r.next_open_sampled_at = now
            if status != "fresh":
                r.gaps = list(r.gaps or []) + [f"next-open quote {r.next_open_status}"]
            await session.commit()
        n += 1
    if n:
        log.info("hold study: %d next-open sample(s) taken", n)
    return n


def row_dict(r) -> dict:
    return {"id": r.id, "positionId": r.position_id, "sessionDate": r.session_date, "arm": r.arm,
            "symbol": r.symbol, "legSymbol": r.leg_symbol, "secType": r.sec_type, "qty": r.qty,
            "entryPrice": r.entry_price, "direction": r.direction, "source": r.source, "horizon": r.horizon,
            "dteAtSnapshot": (r.horizon or {}).get("dte"), "exitsPolicy": r.exits_policy, "plannedRisk": r.planned_risk,
            "fees": r.fees, "precloseQuote": r.preclose_quote, "precloseStatus": r.preclose_status,
            "exitPrice": r.exit_price, "nextOpenQuote": r.next_open_quote, "nextOpenStatus": r.next_open_status,
            "nextOpenSampledAt": _iso(r.next_open_sampled_at), "gaps": list(r.gaps or []),
            "multiplier": 100.0 if r.sec_type == "OPT" else 1.0}
