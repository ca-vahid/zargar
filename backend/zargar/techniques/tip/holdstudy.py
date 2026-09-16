"""PROF-03 (2026-09-15, corrected HOLD142-01..03 the same evening): overnight-hold
comparison - RESEARCH ONLY.

Four Tips trades exited in the next session's first minute for -$725.66. Is
carrying overnight worse than a predeclared intraday close, by setup? This
module collects the evidence contemporaneously and compares two arms on the
same positions with the same costs:

- `carry`: what the position actually does (its stops and exits stay exactly
  as they are - nothing here touches a position), measured two ways: the
  OVERNIGHT QUOTE DRIFT to the next session's first qualified bid inside the
  declared opening window, and - separately - the MANAGED outcome when the
  position's own stop/exit closed it before that sample (an endpoint quote is
  never presented as what the strategy earned);
- `intraday_exit`: a PREDECLARED alternative - selling the sampled remaining
  size at the pre-close qualified BID - never a hindsight peak.

Every observation has a durable identity (study version, session, position,
leg, arm): a retry, a restart or a repeated capture is ONE observation, and the
original evidence is never replaced by a later quote. Sampling windows are
part of the protocol: a pre-close observation must fall inside the last
`hold_preclose_window_minutes` before the exchange close of a trading day
(early closes included), and the next-open observation is the first qualified
quote inside `hold_next_open_window_minutes` after 09:30 ET of the EXPECTED
next trading session (exchange calendar). An observation taken outside its
window is recorded as missed - a later day never stands in for it. A missing,
stale or unqualified quote (cohort.qualify_quote: provenance, delayed flag,
genuine source time, session) is INSUFFICIENT evidence, reported, never filled
in. Results are paired net by setup; no blanket rule is derived here.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from ...domain import new_id
from ...marketstructure import market_calendar as _cal
from . import cohort as _cohort

log = logging.getLogger("zargar.tip.holdstudy")

ET = ZoneInfo("America/New_York")
STUDY_VERSION = "holdstudy-v2"      # v2 2026-09-15: windows, identity, fee basis, managed outcome
RTH_OPEN_MIN = 9 * 60 + 30
DEFAULT_PRECLOSE_WINDOW_MIN = 15    # the last N minutes before the exchange close
DEFAULT_NEXT_OPEN_WINDOW_MIN = 15   # the first N minutes after 09:30 ET
DEFAULT_NEXT_OPEN_ATTEMPTS = 40     # in-window retries (20 s apart) for the FIRST qualified quote from 09:30
DEFAULT_PRECLOSE_BEFORE_CLOSE_MIN = 10   # the pre-close job runs this many minutes before the exchange close
NEXT_OPEN_RETRY_S = 20.0


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(x) -> str | None:
    return x.isoformat() if hasattr(x, "isoformat") else (str(x) if x is not None else None)


def session_date(now: dt.datetime | None = None) -> str:
    return (now or _utcnow()).astimezone(ET).date().isoformat()


def _clock(pinned: dt.datetime | None):
    """The clock a collection run reads AFTER every await: the real clock, or
    the pinned instant when a caller supplied `now` (tests, replays)."""
    return (lambda: pinned) if pinned is not None else _utcnow


def _sample_time(quote: dict | None, fallback: dt.datetime) -> dt.datetime:
    """The ACTUAL time a quote observation was taken (its `sampledAt`, stamped
    by the quote store when the sample was read), else the clock after the
    sample. Distinct from `sourceTs` (the venue print) and from the job's start."""
    raw = (quote or {}).get("sampledAt")
    if raw:
        with contextlib.suppress(Exception):
            t = dt.datetime.fromisoformat(str(raw))
            return t if t.tzinfo is not None else t.replace(tzinfo=dt.timezone.utc)
    return fallback


def preclose_job_time(d: dt.date | str, *, before_close_minutes: int = DEFAULT_PRECLOSE_BEFORE_CLOSE_MIN) -> str:
    """When the pre-close job should run on a given date, relative to the
    EXCHANGE close (early closes included): "15:50" on a normal day, "12:50"
    on a 13:00 close. Non-trading days get the normal time (the job then
    records nothing / a miss by the window rule)."""
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    close_min = int(_cal.session_close_minutes(d)) if _cal.is_trading_day(d) else int(_cal.RTH_CLOSE_MIN)
    m = max(0, close_min - int(before_close_minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def next_open_job_time() -> str:
    """The next-open job starts AT the opening window's start (09:30 ET) and
    searches inside it - the protocol is the first qualified quote from 09:30."""
    return f"{RTH_OPEN_MIN // 60:02d}:{RTH_OPEN_MIN % 60:02d}"


def _event_label(eng, now, sess) -> dict | None:
    """TMR-01: the verified event label on the observation (event-day sessions stay distinguishable)."""
    try:
        from . import events as _evc
        c = _evc.context_for(eng, now=now, session=sess)
        return {k: c.get(k) for k in ("status", "coverage", "label")}
    except Exception:                                   # noqa: BLE001
        return None


def _knob(eng, key: str, default):
    try:
        v = eng.settings.get(key, default)
    except Exception:
        v = default
    return default if v is None else v


def _snap(eng, sym: str, *, is_option: bool, kind: str) -> tuple[dict | None, str]:
    max_age = float(_knob(eng, "techniques.tip.entry_cohort_quote_max_age_seconds", 300.0) or 300.0)
    return _cohort._snap_quote(eng, sym, max_age_s=max_age, kind=kind, is_option=is_option)


# ------------------------------------------------------------------ protocol windows (pure)
def observation_key(session: str, position_id: str, leg_symbol: str, arm: str, *, version: str = STUDY_VERSION) -> str:
    """The durable identity of ONE observation: study version, session, position
    (holding episode), leg and arm. Two captures of the same identity are the
    same observation."""
    return f"{version}|{session}|{position_id}|{leg_symbol}|{arm}"


def preclose_window(session: str, *, minutes: int = DEFAULT_PRECLOSE_WINDOW_MIN) -> dict | None:
    """[close - N min, close) of a trading day in ET, early closes included;
    None when the date is not a trading day."""
    d = dt.date.fromisoformat(session)
    if not _cal.is_trading_day(d):
        return None
    close_min = int(_cal.session_close_minutes(d))
    end = dt.datetime.combine(d, dt.time(0, 0), tzinfo=ET) + dt.timedelta(minutes=close_min)
    start = end - dt.timedelta(minutes=int(minutes))
    return {"kind": "preclose", "sessionDate": session, "start": start.isoformat(), "end": end.isoformat(),
            "closeMinutes": close_min, "earlyClose": bool(_cal.is_early_close(d))}


def expected_next_session(session: str) -> str:
    """The exchange calendar's next trading day after the snapshot session."""
    return _cal.next_trading_day(dt.date.fromisoformat(session)).isoformat()


def next_open_window(expected: str, *, minutes: int = DEFAULT_NEXT_OPEN_WINDOW_MIN) -> dict:
    """[09:30, 09:30 + N min] ET of the expected next trading session."""
    d = dt.date.fromisoformat(expected)
    start = dt.datetime.combine(d, dt.time(0, 0), tzinfo=ET) + dt.timedelta(minutes=RTH_OPEN_MIN)
    end = start + dt.timedelta(minutes=int(minutes))
    return {"kind": "next_open", "sessionDate": expected, "start": start.isoformat(), "end": end.isoformat()}


def judge_window(now: dt.datetime, window: dict | None) -> str:
    """'early' | 'inside' | 'late' | 'none' (not a trading day)."""
    if window is None:
        return "none"
    start = dt.datetime.fromisoformat(window["start"])
    end = dt.datetime.fromisoformat(window["end"])
    if now < start:
        return "early"
    if now >= end:
        return "late"
    return "inside"


def setup_of(row: dict) -> str:
    """The setup bucket a pair is compared within: vehicle x DTE bucket (options)."""
    if row.get("secType") != "OPT":
        return "shares"
    dte = row.get("dteAtSnapshot")
    if dte is None:
        return "option:dte-unknown"
    d = int(dte)
    return "option:lotto(<=3d)" if d <= 3 else ("option:short(<=14d)" if d <= 14 else "option:longer(>14d)")


# ------------------------------------------------------------------ comparison (pure)
def _costs(row: dict, *, fee_per_contract: float, stock_commission: float, reg_per_contract: float) -> dict:
    """Allocated ENTRY fee plus the EXIT cost of the sampled size. Options: a
    per-contract fee (+ regulatory charge) on each side. Shares: a flat
    per-order commission on each side; the entry order's commission is
    allocated pro rata to the sampled remainder when the entry size is known,
    otherwise counted in full and flagged. Unknown inputs stay visible."""
    qty = float(row.get("qty") or 0)
    notes: list[str] = []
    if row.get("secType") == "OPT":
        unit = float(fee_per_contract) + float(reg_per_contract)
        entry = unit * qty
        exit_ = unit * qty
        basis = "per contract per side"
        if not reg_per_contract:
            notes.append("regulatory per-contract charges not supplied (0)")
    else:
        entry_qty = float(row.get("entryQty") or 0)
        if entry_qty > 0 and qty > 0:
            entry = float(stock_commission) * min(1.0, qty / entry_qty)
        else:
            entry = float(stock_commission)
            if stock_commission:
                notes.append("entry size unknown: entry commission counted in full")
        exit_ = float(stock_commission)
        basis = "per order per side"
        notes.append("sell-side regulatory charges (SEC/FINRA) not modelled")
    return {"entry": round(entry, 4), "exit": round(exit_, 4), "total": round(entry + exit_, 4), "basis": basis,
            "notes": notes}


def _risk_for_sample(row: dict) -> tuple[float | None, str]:
    """The stop risk of the SAMPLED size: plannedRisk scaled from the size it was
    planned for (plannedRiskQty) to the sampled quantity."""
    planned = float(row.get("plannedRisk") or 0) or None
    if planned is None:
        return None, "no planned risk"
    qty = float(row.get("qty") or 0)
    basis_qty = float(row.get("plannedRiskQty") or 0)
    if basis_qty > 0 and qty > 0:
        return round(planned * qty / basis_qty, 4), "planned risk scaled to the sampled size"
    return planned, "legacy row: planned risk not rebased to the sampled size"


def compare_row(row: dict, *, fee_per_contract: float = 0.0, stock_commission: float = 0.0,
                reg_per_contract: float = 0.0) -> dict:
    """Pure: the two arms for one snapshot row, net of the allocated entry fee
    and the exit cost, in $ and in R (R = the stop risk of the sampled size).

    `intradayExit`   = selling the sampled size at the pre-close qualified bid (or,
                       for a position that really exited intraday, its actual exit).
    `carryToNextOpen` = the OVERNIGHT QUOTE DRIFT: the same size valued at the next
                       session's first qualified bid inside the opening window. It is
                       a quote comparison, not what the managed strategy earned.
    `managedCarry`   = what the strategy actually did when its own stop/exit closed
                       the position before the next-open sample (known only then).
    Insufficient whenever an arm lacks a qualified quote in its window."""
    qty = float(row.get("qty") or 0)
    mult = float(row.get("multiplier") or (100.0 if row.get("secType") == "OPT" else 1.0))
    entry = float(row.get("entryPrice") or 0)
    costs = _costs(row, fee_per_contract=fee_per_contract, stock_commission=stock_commission,
                   reg_per_contract=reg_per_contract)
    fee = costs["total"]
    risk, risk_basis = _risk_for_sample(row)
    out = {"version": STUDY_VERSION, "id": row.get("id"), "positionId": row.get("positionId"),
           "bookKind": row.get("bookKind"), "symbol": row.get("symbol"), "legSymbol": row.get("legSymbol"), "arm": row.get("arm"), "setup": setup_of(row), "qty": qty, "entryPrice": entry,
           "plannedRisk": row.get("plannedRisk"), "riskForSample": risk, "riskBasis": risk_basis, "costs": costs,
           "adequate": False, "reason": None,
           "meaning": {"carryToNextOpen": "overnight quote drift (next-open bid), not the strategy's realized result",
                       "intradayExit": "predeclared pre-close liquidation of the sampled size",
                       "managedCarry": "the strategy's own exit when it closed before the next-open sample"}}
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

    def _net(px: float) -> float:
        return (px - entry) * qty * mult - fee

    intraday = _net(pre_bid)
    carry = _net(float(nxt["bid"]))
    r_of = (lambda x: round(x / risk, 2)) if risk else (lambda x: None)
    managed = None
    co = row.get("carryOutcome") or {}
    if row.get("arm") == "carry" and co.get("closedBeforeSample") and co.get("exitPrice"):
        m_net = _net(float(co["exitPrice"]))
        managed = {"known": True, "price": float(co["exitPrice"]), "net": round(m_net, 2), "R": r_of(m_net),
                   "closedAt": co.get("closedAt"), "reason": co.get("reason")}
    elif row.get("arm") == "carry":
        managed = {"known": False, "note": "still open at the next-open sample - the strategy's result is not yet known"}
    out.update(adequate=True,
               intradayExit={"price": pre_bid, "net": round(intraday, 2), "R": r_of(intraday)},
               carryToNextOpen={"price": float(nxt["bid"]), "net": round(carry, 2), "R": r_of(carry)},
               carryMinusIntraday=round(carry - intraday, 2),
               managedCarry=managed,
               sacrificedWinner=(row.get("arm") == "intraday_exit" and carry > intraday),
               note="carry is the next session's FIRST qualified bid inside the opening window (quote drift), "
                    "never a later peak; the position's real stops/exits were untouched")
    return out


def aggregate(results: list[dict]) -> dict:
    """Paired net by setup with counts; insufficient rows are counted, never
    dropped silently. Position-session observations are what is counted here
    (one position can appear on several sessions) - not independent trade
    ideas. No winner is chosen here."""
    by: dict[str, dict] = {}
    for r in results:
        b = by.setdefault(r["setup"], {"n": 0, "insufficient": 0, "carryNet": 0.0, "intradayNet": 0.0,
                                       "carryR": [], "intradayR": [], "sacrificedWinners": 0,
                                       "managedKnown": 0, "managedNet": 0.0,
                                       "positions": set(), "arms": {"carry": 0, "intraday_exit": 0}})
        b["arms"][r.get("arm") or "carry"] = b["arms"].get(r.get("arm") or "carry", 0) + 1
        bk = r.get("bookKind") or "unknown"
        b.setdefault("books", {})[bk] = b.get("books", {}).get(bk, 0) + 1
        if r.get("positionId"):
            b["positions"].add(r["positionId"])
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
        m = r.get("managedCarry") or {}
        if m.get("known"):
            b["managedKnown"] += 1
            b["managedNet"] += m["net"]
    for b in by.values():
        b["carryNet"] = round(b["carryNet"], 2)
        b["intradayNet"] = round(b["intradayNet"], 2)
        b["managedNet"] = round(b["managedNet"], 2)
        b["meanCarryR"] = round(sum(b["carryR"]) / len(b["carryR"]), 3) if b["carryR"] else None
        b["meanIntradayR"] = round(sum(b["intradayR"]) / len(b["intradayR"]), 3) if b["intradayR"] else None
        b["pairedDiffR"] = (round(b["meanCarryR"] - b["meanIntradayR"], 3)
                            if b["meanCarryR"] is not None and b["meanIntradayR"] is not None else None)
        b["distinctPositions"] = len(b["positions"])
        del b["carryR"], b["intradayR"], b["positions"]
    from .experiments_register import identity as _xid
    return {"version": STUDY_VERSION, "setups": by, "experiment": _xid("overnight-hold"),
            "unit": "position-session observations (a position held several nights is counted once per session)",
            "disclaimer": "paired arithmetic on contemporaneous qualified quotes inside declared windows; "
                          "carry is quote drift unless managedCarry is known; small samples, no rule derived"}


# ------------------------------------------------------------------ collection (inside the app)
def _planned_risk(p: dict, leg: dict) -> tuple[float | None, float | None]:
    """(planned stop risk, the size it was planned for). Shares: stop distance x
    the leg's current size. Options: the geometry gate's planned risk for its
    plan quantity, else unknown."""
    stop = ((p.get("state") or {}).get("stop")) or (((p.get("policy") or {}).get("stop") or {}).get("price"))
    entry_ref = p.get("entry")
    qty = abs(float(leg.get("qty") or 0))
    if leg.get("secType") == "OPT":
        rp = ((p.get("extras") or {}).get("riskPlan") or {})
        if rp.get("plannedRisk"):
            basis = float(rp.get("planQty") or 0) or (qty + _exited_qty(p, leg))
            return float(rp["plannedRisk"]), (basis or None)
        return None, None
    if stop is None or not entry_ref:
        return None, None
    dist = (float(entry_ref) - float(stop)) if p.get("direction") != "short" else (float(stop) - float(entry_ref))
    if dist <= 0:
        return None, None
    return round(dist * qty, 2), qty


def _exited_qty(p: dict, leg: dict) -> float:
    return sum(float(x.get("filledQty") or 0) for x in (p.get("exits") or [])
               if (x.get("leg") in (None, leg.get("symbol"))))


def _dte(leg_symbol: str, today: dt.date) -> int | None:
    with contextlib.suppress(Exception):
        from ...options import occ as _occ
        o = _occ.parse(leg_symbol)
        if o is not None:
            return (o.expiry - today).days
    return None


async def _insert_once(eng, row) -> bool:
    """Insert unless an observation with the same identity already exists
    (checked first, and enforced by the unique index for a concurrent writer).
    The original observation is never replaced."""
    from sqlalchemy import select
    from ...models import TipHoldSnapshotRow
    async with eng.sf() as session:
        dup = (await session.execute(select(TipHoldSnapshotRow.id).where(
            TipHoldSnapshotRow.observation_key == row.observation_key))).scalar_one_or_none()
        if dup is not None:
            return False
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
    return True


async def snapshot_preclose(eng, *, now: dt.datetime | None = None) -> int:
    """Scheduler job `tip_hold_snapshot` (default 15:50 ET): one observation per
    open Tips position leg (arm carry) and per Tips position that exited
    intraday today (arm intraday_exit), with the qualified pre-close quote of
    the exact leg - ONLY inside the pre-close window of a trading day. Too
    early: nothing is recorded (the timely run will). After the close, or on a
    non-trading day (an after-close boot's catch-up): the observation is
    recorded as MISSED without a quote - never back-labeled pre-close.
    Idempotent per observation identity. Places nothing, changes no policy.
    Returns the number of NEW rows."""
    from ...models import TipHoldSnapshotRow
    if not bool(_knob(eng, "techniques.tip.hold_study_enabled", True)):
        return 0
    clock = _clock(now)
    now = now or _utcnow()
    now_et = now.astimezone(ET)
    sess = now_et.date().isoformat()
    today = now_et.date()
    window = preclose_window(sess, minutes=int(_knob(eng, "techniques.tip.hold_preclose_window_minutes",
                                                      DEFAULT_PRECLOSE_WINDOW_MIN)))
    verdict = judge_window(now, window)
    if verdict == "early":
        log.info("hold study: %s is before the pre-close window %s - nothing recorded", now_et.strftime("%H:%M"),
                 window and window["start"][11:16])
        return 0
    mgr = getattr(eng, "position_manager", None)
    if mgr is None:
        return 0
    rows = [p for p in mgr.positions() if (p.get("technique") == "tip")]
    # 2026-09-16 (first v2 capture): a CLOSED position leaves manager memory, so the
    # intraday_exit arm must read today's closes from the durable record - otherwise
    # the arm never observes anything (T, SLV, GOOGL exits were missed on 09-16)
    seen = {str(p.get("id")) for p in rows}
    try:
        from sqlalchemy import select
        from ...models import ManagedPositionRow
        day_start_ms = int(dt.datetime.combine(today, dt.time(0, 0), tzinfo=ET).timestamp() * 1000)
        async with eng.sf() as session:
            closed = (await session.execute(select(ManagedPositionRow).where(
                ManagedPositionRow.technique == "tip", ManagedPositionRow.status == "closed",
                ManagedPositionRow.created_at >= now - dt.timedelta(days=45)))).scalars().all()
        for r in closed:
            cm = (r.state or {}).get("closedMs")
            if str(r.id) in seen or not cm or int(cm) < day_start_ms:
                continue
            with contextlib.suppress(Exception):
                rows.append(mgr._from_row(r).to_dict())
    except Exception:                                   # noqa: BLE001 - the carry arm still records
        log.debug("hold study: closed-position read failed", exc_info=True)
    n = 0
    tol = float(_knob(eng, "techniques.tip.entry_cohort_quote_max_age_seconds", 300.0) or 300.0)
    fees = {"perContract": float(_knob(eng, "options.fee_per_contract", 0.0) or 0.0),
            "regPerContract": float(_knob(eng, "sim.reg_fee_per_contract", 0.0) or 0.0),
            "stockCommission": float(_knob(eng, "sim.stock_commission", 0.0) or 0.0),
            "basis": "options: per contract per side; shares: per order per side"}
    for p in rows:
        legs = [l for l in (p.get("legs") or []) if l.get("secType") in ("OPT", "STK")]
        if not legs:
            continue
        closed_ms = p.get("closedMs")
        is_open = p.get("status") == "open" and any(abs(float(l.get("qty") or 0)) > 0 for l in legs)
        exited_today = (p.get("status") == "closed" and closed_ms
                        and dt.datetime.fromtimestamp(int(closed_ms) / 1000, tz=dt.timezone.utc).astimezone(ET).date() == today)
        if not is_open and not exited_today:
            continue
        arm = "carry" if is_open else "intraday_exit"
        policy = p.get("policy") or {}
        for leg in legs:
            if is_open and abs(float(leg.get("qty") or 0)) <= 0:
                continue
            sym = str(leg.get("symbol"))
            is_opt = leg.get("secType") == "OPT"
            key = observation_key(sess, str(p["id"]), sym, arm)
            observed_at = now
            if verdict == "inside":
                # R147-01: the clock is re-read for THIS row (earlier rows, option
                # refreshes and retries take time) and the ACTUAL sample time -
                # the quote's own sampledAt, read after the await - must lie inside
                # the window; the job's start time admits nothing by itself
                t_row = clock()
                if judge_window(t_row, window) != "inside":
                    quote, status = None, "late"
                    observed_at = t_row
                    gaps = [f"pre-close window ended before this row was sampled (row reached at "
                            f"{t_row.astimezone(ET).strftime('%H:%M:%S')} ET, job started "
                            f"{now_et.strftime('%H:%M:%S')} ET) - late, not protocol-qualified"]
                else:
                    if is_opt:
                        with contextlib.suppress(Exception):
                            await eng.options.refresh_now(sym)
                    quote, status = _snap(eng, sym, is_option=is_opt, kind="preclose")
                    observed_at = _sample_time(quote, clock())
                    if status == "fresh" and judge_window(observed_at, window) != "inside":
                        status = "late"
                        gaps = [f"quote sampled at {observed_at.astimezone(ET).strftime('%H:%M:%S')} ET, outside the "
                                f"pre-close window {window['start'][11:16]}-{window['end'][11:16]} ET (job started "
                                f"{now_et.strftime('%H:%M:%S')} ET) - late, not protocol-qualified"]
                    else:
                        gaps = [] if status == "fresh" else [f"pre-close quote {status}"]
            else:
                quote, status = None, "outside_window"
                gaps = [("pre-close window elapsed" if verdict == "late" else "not a trading day")
                        + f": observed {now_et.strftime('%Y-%m-%d %H:%M')} ET, window "
                        + (f"{window['start'][11:16]}-{window['end'][11:16]} ET" if window else "none")
                        + " - observation MISSED, not back-labeled"]
            exit_px = exit_qty = None
            if arm == "intraday_exit":
                fills = [x for x in (p.get("exits") or []) if float(x.get("filledQty") or 0) > 0
                         and (x.get("leg") in (None, sym))]
                if fills:
                    exit_qty = sum(float(x["filledQty"]) for x in fills)
                    exit_px = sum(float(x["filledQty"]) * float(x.get("price") or 0) for x in fills) / exit_qty
            planned, planned_qty = _planned_risk(p, leg)
            remaining = abs(float(leg.get("qty") or 0))
            entry_qty = remaining + _exited_qty(p, leg)
            book = {}
            with contextlib.suppress(Exception):
                book = eng.positions.portfolio(str(p.get("portfolioId"))) or {}
            row = TipHoldSnapshotRow(
                id=new_id(), observation_key=key, study_version=STUDY_VERSION,
                position_id=str(p["id"]), session_date=sess, arm=arm,
                portfolio_id=str(p.get("portfolioId") or "") or None, book_kind=str(book.get("kind") or "") or None,
                symbol=str(p.get("symbol")), leg_symbol=sym, sec_type=str(leg.get("secType")),
                qty=(exit_qty if arm == "intraday_exit" and exit_qty else remaining),
                entry_qty=(entry_qty or None),
                entry_price=float(leg.get("avgFill") or p.get("entry") or 0), direction=str(p.get("direction") or "long"),
                source=next((t.split(":", 1)[1] for t in (p.get("tags") or []) if str(t).startswith("source:")), None),
                horizon={"maxHoldSessions": policy.get("time_stop_sessions"), "sessionsHeld": p.get("sessionsHeld"),
                         "dte": _dte(sym, today) if is_opt else None, "openedMs": p.get("openedMs")},
                exits_policy={"stop": (p.get("state") or {}).get("stop"), "ladder": policy.get("ladder"),
                              "premiumStopPct": ((policy.get("premium_stop") or {}).get("pct") if isinstance(policy.get("premium_stop"), dict) else policy.get("premium_stop"))},
                planned_risk=planned, planned_risk_qty=planned_qty, fees=fees,
                observed_at=observed_at,
                window={**(window or {"kind": "preclose", "sessionDate": sess, "start": None, "end": None}),
                        "verdict": (judge_window(observed_at, window) if window else verdict),
                        "event": _event_label(eng, now, sess),
                        "jobStartedAt": _iso(now), "observedAt": _iso(observed_at),
                        "sampledAt": (quote or {}).get("sampledAt"),
                        "sourceTs": (quote or {}).get("sourceTs"), "toleranceS": tol},
                expected_next_session=expected_next_session(sess),
                preclose_quote=quote, preclose_status=status, exit_price=exit_px,
                next_open_quote=None, next_open_status="pending", gaps=gaps)
            if await _insert_once(eng, row):
                n += 1
    if n:
        log.info("hold study: %d pre-close observation(s) for %s (%s)", n, sess, verdict)
    return n


async def _managed_outcome(eng, position_id: str, since: dt.datetime | None, until: dt.datetime) -> dict:
    """What the position's OWN management did between the snapshot and the
    next-open sample: closed before the sample (with the exits' price) or
    still open. Read from the durable record; never inferred from a quote."""
    from ...models import ManagedPositionRow
    try:
        async with eng.sf() as session:
            row = await session.get(ManagedPositionRow, position_id)
    except Exception:
        return {"known": False, "reason": "position record unreadable"}
    if row is None:
        return {"known": False, "reason": "position record not found"}
    state = row.state or {}
    since_ms = int(since.timestamp() * 1000) if since else 0
    until_ms = int(until.timestamp() * 1000)
    fills = [x for x in (state.get("exits") or []) if float(x.get("filledQty") or 0) > 0
             and since_ms <= int(x.get("ts") or 0) <= until_ms and x.get("price")]
    closed_ms = state.get("closedMs")
    closed_before = row.status == "closed" and closed_ms and int(closed_ms) <= until_ms
    out = {"known": True, "status": row.status, "closedBeforeSample": bool(closed_before),
           "exitsBetween": [{"ts": x.get("ts"), "qty": x.get("filledQty"), "price": x.get("price"),
                             "kind": x.get("kind"), "reason": x.get("reason")} for x in fills]}
    if closed_before:
        if fills:
            q = sum(float(x["filledQty"]) for x in fills)
            out["exitPrice"] = round(sum(float(x["filledQty"]) * float(x["price"]) for x in fills) / q, 6)
            out["exitQty"] = q
            out["reason"] = fills[-1].get("reason")
        out["closedAt"] = _iso(dt.datetime.fromtimestamp(int(closed_ms) / 1000, tz=dt.timezone.utc))
    return out


async def sample_next_open(eng, *, now: dt.datetime | None = None) -> int:
    """Scheduler job `tip_hold_next_open` (default 09:36 ET): for every pending
    observation whose EXPECTED next trading session (exchange calendar) is
    today, the FIRST qualified quote inside the opening window - retried inside
    the window, recorded terminally (with the attempts) when none qualifies. A
    pending observation whose expected session has already passed is MISSED:
    a later day never replaces it. Before the expected session or before
    09:30, nothing happens. Returns the number of observations settled."""
    from sqlalchemy import select
    from ...models import TipHoldSnapshotRow
    if not bool(_knob(eng, "techniques.tip.hold_study_enabled", True)):
        return 0
    pinned = now is not None
    clock = _clock(now)
    now = now or _utcnow()
    today = session_date(now)
    win_min = int(_knob(eng, "techniques.tip.hold_next_open_window_minutes", DEFAULT_NEXT_OPEN_WINDOW_MIN))
    max_attempts = 1 if pinned else int(_knob(eng, "techniques.tip.hold_next_open_attempts", DEFAULT_NEXT_OPEN_ATTEMPTS))
    async with eng.sf() as session:
        rows = (await session.execute(select(TipHoldSnapshotRow).where(
            TipHoldSnapshotRow.next_open_status == "pending", TipHoldSnapshotRow.session_date < today))).scalars().all()
        todo = [(r.id, r.session_date, r.expected_next_session or expected_next_session(r.session_date)) for r in rows]
    n = 0
    for rid, sess, expected in todo:
        window = next_open_window(expected, minutes=win_min)
        sampled_at = now
        if today < expected:
            continue                                   # not yet the expected session
        if today > expected:
            status, quote, attempts = "missed", None, 0
            gap = (f"next-open window for the expected session {expected} elapsed: observed {today} - "
                   f"observation MISSED, a later day never replaces it")
        else:
            verdict = judge_window(now, window)
            if verdict == "early":
                continue
            if verdict == "late":
                status, quote, attempts = "missed", None, 0
                gap = (f"next-open window {window['start'][11:16]}-{window['end'][11:16]} ET elapsed: observed "
                       f"{now.astimezone(ET).strftime('%H:%M')} ET - observation MISSED")
            else:
                async with eng.sf() as session:
                    r = await session.get(TipHoldSnapshotRow, rid)
                    if r is None or r.next_open_status != "pending":
                        continue
                    sym, is_opt = r.leg_symbol, r.sec_type == "OPT"
                attempts = 0
                quote, status = None, "missing"
                sampled_at = clock()
                while True:
                    # R147-01: every attempt re-reads the clock before sampling and
                    # judges the quote's ACTUAL sample time against the window
                    if judge_window(clock(), window) != "inside":
                        if attempts == 0:
                            status, quote, sampled_at = "missed", None, clock()
                        break
                    attempts += 1
                    if is_opt:
                        with contextlib.suppress(Exception):
                            await eng.options.refresh_now(sym)
                    quote, status = _snap(eng, sym, is_option=is_opt, kind="next_open")
                    sampled_at = _sample_time(quote, clock())
                    if status == "fresh":
                        if judge_window(sampled_at, window) != "inside":
                            status = "late"
                        break
                    if attempts >= max_attempts:
                        break
                    await asyncio.sleep(NEXT_OPEN_RETRY_S)
                if status == "fresh":
                    gap = None
                elif status == "late":
                    gap = (f"qualified quote sampled at {sampled_at.astimezone(ET).strftime('%H:%M:%S')} ET, outside the "
                           f"opening window {window['start'][11:16]}-{window['end'][11:16]} ET (job started "
                           f"{now.astimezone(ET).strftime('%H:%M:%S')} ET) - late, not protocol-qualified")
                elif status == "missed":
                    gap = (f"opening window ended before this row was sampled (reached at "
                           f"{sampled_at.astimezone(ET).strftime('%H:%M:%S')} ET) - observation MISSED")
                else:
                    gap = f"no qualified next-open quote inside the window after {attempts} attempt(s): {status}"
        async with eng.sf() as session:
            r = await session.get(TipHoldSnapshotRow, rid, with_for_update=True)
            if r is None or r.next_open_status != "pending":
                continue                               # settled by a concurrent run: the original stands
            r.next_open_quote = quote
            r.next_open_status = status if (quote is not None or status in ("missed", "late")) else "missing"
            r.next_open_sampled_at = sampled_at
            r.next_open_window = {**window, "jobStartedAt": _iso(now), "observedAt": _iso(sampled_at),
                                  "sampledAt": (quote or {}).get("sampledAt"), "attempts": attempts,
                                  "sourceTs": (quote or {}).get("sourceTs")}
            if gap:
                r.gaps = list(r.gaps or []) + [gap]
            if r.arm == "carry":
                r.carry_outcome = await _managed_outcome(eng, r.position_id, r.observed_at or r.created_at, sampled_at)
            await session.commit()
        n += 1
    if n:
        log.info("hold study: %d next-open observation(s) settled", n)
    return n


async def requalify_legacy(eng_or_sf, *, now: dt.datetime | None = None) -> int:
    """One-shot repair for rows captured before the window protocol (v1): a
    pre-close observation whose capture time lies outside its session's
    pre-close window is re-labeled `outside_window` whatever its quote label
    was (a miss, never evidence; never upgraded), its
    identity key and expected next session filled in. Returns rows changed."""
    from sqlalchemy import select
    from ...models import TipHoldSnapshotRow
    sf = getattr(eng_or_sf, "sf", eng_or_sf)
    changed = 0
    async with sf() as session:
        rows = (await session.execute(select(TipHoldSnapshotRow))).scalars().all()
        for r in rows:
            touched = False
            if not r.observation_key:
                r.observation_key = observation_key(r.session_date, r.position_id, r.leg_symbol, r.arm,
                                                    version=r.study_version or "holdstudy-v1")
                touched = True
            if not r.expected_next_session:
                r.expected_next_session = expected_next_session(r.session_date)
                touched = True
            observed = r.observed_at or r.created_at
            if r.preclose_status != "outside_window" and observed is not None:
                w = preclose_window(r.session_date)
                v = judge_window(observed, w)
                if v != "inside":
                    # whatever the quote's own label was, an observation outside the
                    # window is a MISSED observation (never upgraded, never evidence)
                    r.preclose_status = "outside_window"
                    r.window = {**(w or {"kind": "preclose", "sessionDate": r.session_date}), "verdict": v,
                                "observedAt": _iso(observed), "requalified": _iso(now or _utcnow())}
                    r.gaps = list(r.gaps or []) + [f"re-qualified: captured {observed.astimezone(ET).strftime('%H:%M')} ET "
                                                   f"outside the pre-close window - not pre-close evidence"]
                    touched = True
            changed += 1 if touched else 0
        await session.commit()
    return changed


def row_dict(r) -> dict:
    return {"id": r.id, "observationKey": r.observation_key, "studyVersion": r.study_version,
            "positionId": r.position_id, "sessionDate": r.session_date, "arm": r.arm,
            "portfolioId": r.portfolio_id, "bookKind": r.book_kind,
            "symbol": r.symbol, "legSymbol": r.leg_symbol, "secType": r.sec_type, "qty": r.qty, "entryQty": r.entry_qty,
            "entryPrice": r.entry_price, "direction": r.direction, "source": r.source, "horizon": r.horizon,
            "dteAtSnapshot": (r.horizon or {}).get("dte"), "exitsPolicy": r.exits_policy,
            "plannedRisk": r.planned_risk, "plannedRiskQty": r.planned_risk_qty,
            "fees": r.fees, "observedAt": _iso(r.observed_at), "window": r.window,
            "expectedNextSession": r.expected_next_session, "nextOpenWindow": r.next_open_window,
            "precloseQuote": r.preclose_quote, "precloseStatus": r.preclose_status,
            "exitPrice": r.exit_price, "nextOpenQuote": r.next_open_quote, "nextOpenStatus": r.next_open_status,
            "nextOpenSampledAt": _iso(r.next_open_sampled_at), "carryOutcome": r.carry_outcome,
            "gaps": list(r.gaps or []), "multiplier": 100.0 if r.sec_type == "OPT" else 1.0}
