"""ED-04 executable-profit capture (`book-snapshot-v3`, 2026-09-19; integrated plan workstream E, candidate review IR-02/IR-03,
revision-2 review R2-01: the ledger is per TRADE INSTANCE from durable order links, never merged by symbol).

Three numbers that were conflated are kept apart for the EM Practice book at one instant:
  realized net        from the EXECUTION LEDGER of the session (fills and commissions) - never from in-memory trade state,
                      so it survives a restart, a disarm and a recorder that started late; prior-session fills are excluded
  displayed (marked)  the book's own mark of what is still held (option mid when there is an ask, else last) - the number
                      the UI shows; reproduced with the SAME rule as `portfolio.PositionKeeper._mark`
  executable, covered what the UNCOMMITTED remainder could be sold for against the covered side of a fresh, identified, venue
                      quote, limited by the displayed size - where that size is spent ONCE per contract/side across the whole
                      book - minus the modeled exit fee. A hypothetical liquidation estimate, never a fill.

Two phases, both PURE: `capture_book` freezes positions + quote evidence synchronously (time-critical); `finalize_book`
attaches the execution ledger AS OF the capture time (done on the recorder's own task, never on a trading path).
`ProfitCaptureObserver` is the bounded non-blocking recorder; `reduce_session` is the offline reducer. Default OFF under
`techniques.enhanced_market.book_snapshot_observe`.

Frozen rules: unknown provenance is UNKNOWN (an absent source is never relabelled); identity, venue quote time, session,
finiteness, side, size and size unit are all validated; pending exit quantity is reserved AND consumes displayed depth;
spread is never deducted twice; a book with ANY position not fully covered, quotes further apart than the skew limit, or
a ledger that is not restored / not consistent with the held quantities is NOT scorable and can never make a peak.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import uuid
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

VERSION = "book-snapshot-v3"
REDUCER_VERSION = "profit-capture-reducer-v3"
MAX_QUOTE_AGE_MS = 10_000
MAX_SKEW_MS = 5_000
ADMISSIBLE_OPTION_SOURCES = ("opra", "ibkr")
INADMISSIBLE_EQUITY_FEEDS = ("feed:YahooQuoteFeed", "feed:SimQuoteFeed")     # no venue bid/ask time or synthetic: never executable evidence
REASONS = ("periodic", "pre_target", "post_target", "pre_stop", "post_stop", "pre_protection", "post_protection",
           "pre_flatten", "post_flatten", "fill", "restore")


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _market_minute(ts_ms: int) -> bool:
    import datetime as _dt
    from zoneinfo import ZoneInfo
    from ..marketstructure.market_calendar import is_trading_day, session_close_minutes
    try:
        t = _dt.datetime.fromtimestamp(int(ts_ms) / 1000.0, ZoneInfo("America/New_York"))
        return bool(is_trading_day(t.date())) and 9 * 60 + 30 <= t.hour * 60 + t.minute < int(session_close_minutes(t.date()))
    except Exception:                                         # noqa: BLE001 - an unsupported date is HELD, not assumed regular
        return False


def mark_of(sec_type: str, quote: dict | None, avg_cost: float | None) -> tuple[float | None, str]:
    """The book's displayed mark (PLATFORM-RULES 22): an option marks at the mid whenever there is an ask (a 0 bid
    included); otherwise the last print; otherwise nothing (`none` - the book itself would fall back to cost)."""
    q = quote or {}
    bid, ask, last = _f(q.get("bid")) or 0.0, _f(q.get("ask")) or 0.0, _f(q.get("last")) or 0.0
    if sec_type == "OPT" and ask > 0 and ask >= bid:
        return (max(bid, 0.0) + ask) / 2.0, "mid"
    if last > 0:
        return last, "last"
    return None, "none"


def quote_problems(q: dict | None, *, symbol: str, is_option: bool, now_ms: int, max_age_ms: int, side: str,
                   allow_sources: tuple = ()) -> list[str]:
    """Why this quote is NOT executable evidence for `symbol` (empty list = admissible). Nothing is inferred: an absent
    source, an absent venue time or an absent size is a problem, never a default."""
    if not q:
        return ["no_quote"]
    out = []
    if str(q.get("symbol") or "").upper() != str(symbol or "").upper():
        out.append("quote_identity_mismatch")
    src = str(q.get("source") or "").strip()
    if not src:
        out.append("source_unknown")
    elif src.startswith("derived:") or q.get("transform"):
        out.append("derived_quote")
    elif src == "chain" or q.get("delayed"):
        out.append("delayed_quote")
    elif src in allow_sources:
        pass
    elif is_option and src not in ADMISSIBLE_OPTION_SOURCES:
        out.append("source_not_admissible")
    elif (not is_option) and src in INADMISSIBLE_EQUITY_FEEDS:
        out.append("source_not_admissible")
    ts = int(q.get("quoteTs") or 0)
    if ts <= 0:
        out.append("venue_quote_time_unknown")
    elif now_ms - ts > max_age_ms:
        out.append("stale_quote")
    elif ts - now_ms > 1000:
        out.append("venue_quote_time_in_future")
    sess = q.get("session")
    if sess not in (None, "", "regular"):
        out.append("outside_regular_session")
    elif ts > 0 and not _market_minute(ts):                 # the exchange calendar decides: holidays, weekends, early closes
        out.append("outside_regular_session")
    if q.get("halted"):
        out.append("halted")
    bid, ask = _f(q.get("bid")), _f(q.get("ask"))
    if (q.get("bid") is not None and bid is None) or (q.get("ask") is not None and ask is None):
        out.append("non_finite_price")
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        out.append("one_sided_book")
    elif ask < bid:
        out.append("crossed_book")
    size = _f(q.get("bidSize" if side == "bid" else "askSize"))
    if size is None or size <= 0:
        out.append("size_unknown")
    if q.get("sizeUnit") != ("contracts" if is_option else "shares"):
        out.append("size_unit_unknown")
    return out


def capture_position(pos: dict, quote: dict | None, *, now_ms: int, exit_fee_per_unit: float, available_size: float | None,
                     max_age_ms: int = MAX_QUOTE_AGE_MS, allow_sources: tuple = ()) -> dict:
    """One held position. `available_size` = the displayed size STILL UNSPENT for this contract/side after the positions
    allocated before it (the book allocates; a position never reads the quote's size itself). Quantities are conserved:
    reserved = remaining - pendingExit is the ONLY sellable part."""
    m = float(pos.get("multiplier") or 1.0)
    remaining = max(0.0, float(pos.get("remaining") or 0.0))
    pending = max(0.0, min(remaining, float(pos.get("pendingExit") or 0.0)))
    reserved = max(0.0, remaining - pending)
    avg = _f(pos.get("avgFill"))
    is_opt = pos.get("instrument") == "options"
    long_side = str(pos.get("positionSide") or "long") == "long"
    side = "bid" if long_side else "ask"
    mark, basis = mark_of("OPT" if is_opt else "STK", quote, avg)
    sign = 1.0 if long_side else -1.0
    displayed = round((mark - avg) * remaining * m * sign, 4) if (mark is not None and avg is not None) else None
    problems = quote_problems(quote, symbol=str(pos.get("symbol") or ""), is_option=is_opt, now_ms=now_ms, max_age_ms=max_age_ms,
                              side=side, allow_sources=allow_sources) if reserved > 0 else []
    q = quote or {}
    px = _f(q.get(side))
    if reserved <= 0:
        covered, status = 0.0, ("pending_only" if pending > 0 else "flat")
    elif problems or avg is None:
        covered, status = 0.0, "unknown"
        if avg is None:
            problems = problems + ["entry_price_unknown"]
    else:
        covered = max(0.0, min(reserved, float(available_size or 0.0)))
        status = "covered" if covered + 1e-9 >= reserved else "partial"
        if status == "partial":
            problems = ["displayed_size_below_book_quantity"]
    gross = round((px - avg) * covered * m * sign, 4) if (covered > 0 and px is not None and avg is not None) else (0.0 if status in ("flat", "pending_only") else None)
    fee = round(float(exit_fee_per_unit) * covered, 4) if covered > 0 else 0.0
    ts = int(q.get("quoteTs") or 0)
    return {
        "runId": pos.get("runId"), "trigger": pos.get("trigger"), "tradeInstance": pos.get("tradeInstance"),
        "symbol": pos.get("symbol"), "underlying": pos.get("underlying"), "direction": pos.get("direction"),
        "instrument": pos.get("instrument"), "multiplier": m, "positionSide": ("long" if long_side else "short"),
        "quantities": {"original": float(pos.get("original") or 0.0), "remaining": remaining, "pendingExit": pending, "reserved": reserved},
        "avgFill": avg,
        "mark": {"basis": basis, "price": (round(mark, 6) if mark is not None else None), "displayedUnrealized": displayed},
        "quote": ({"symbol": q.get("symbol"), "bid": _f(q.get("bid")), "ask": _f(q.get("ask")), "last": _f(q.get("last")),
                   "bidSize": q.get("bidSize"), "askSize": q.get("askSize"), "sizeUnit": q.get("sizeUnit"),
                   "source": q.get("source") or None, "sourceBasis": q.get("sourceBasis") or None,
                   "rawSource": q.get("rawSource") or None, "transform": q.get("transform") or None,
                   "quoteTs": ts or None, "receivedTs": int(q.get("receivedTs") or 0) or None,
                   "ageMs": (now_ms - ts if ts else None), "session": q.get("session") or None}
                  if quote else None),
        "executable": {"side": side, "price": (px if covered > 0 else None), "coveredQty": covered,
                       "uncoveredQty": round(reserved - covered, 6), "grossCovered": gross, "feeModeled": fee,
                       "netCovered": (round(gross - fee, 4) if gross is not None else None),
                       "status": status, "reasons": problems},
    }


def _side_of(p: dict) -> str:
    return "bid" if str(p.get("positionSide") or "long") == "long" else "ask"


def capture_book(*, ids: dict, seq: int, now_ms: int, reason: str, causal: dict | None, cash: float | None,
                 positions: list, quotes: dict, fee_per_contract: float, stock_fee: float = 0.0,
                 max_age_ms: int = MAX_QUOTE_AGE_MS, max_skew_ms: int = MAX_SKEW_MS, allow_sources: tuple = (),
                 ledger: dict | None = None, instance: str | None = None) -> dict:
    """PHASE 1 (synchronous): positions + quote evidence. Displayed depth is allocated ONCE per (symbol, side) across the
    whole book: pending exits on that contract consume depth first (they are already committed to that side), then the
    positions in deterministic order (symbol, tradeInstance, runId, trigger). Without a ledger the record is
    `ledger: pending` and NOT scorable; `finalize_book` completes it. Passing `ledger` finalizes in one call."""
    ordered = sorted(positions or [], key=lambda p: (str(p.get("symbol")), str(p.get("tradeInstance") or ""), str(p.get("runId") or ""), str(p.get("trigger") or "")))
    depth: dict = {}
    for p in ordered:
        key = (p.get("symbol"), _side_of(p))
        if key not in depth:
            size = _f(((quotes or {}).get(p.get("symbol")) or {}).get("bidSize" if key[1] == "bid" else "askSize")) or 0.0
            pend = sum(max(0.0, float(x.get("pendingExit") or 0.0)) for x in ordered if (x.get("symbol"), _side_of(x)) == key)
            depth[key] = {"displayed": size, "pendingReserved": pend, "left": max(0.0, size - pend)}
    rows = []
    for p in ordered:
        d = depth[(p.get("symbol"), _side_of(p))]
        fee = float(fee_per_contract) if p.get("instrument") == "options" else float(stock_fee)
        row = capture_position(p, (quotes or {}).get(p.get("symbol")), now_ms=now_ms, exit_fee_per_unit=fee, available_size=d["left"],
                               max_age_ms=max_age_ms, allow_sources=allow_sources)
        d["left"] = max(0.0, d["left"] - row["executable"]["coveredQty"])
        rows.append(row)
    held = [r for r in rows if r["quantities"]["remaining"] > 0]
    sellable = [r for r in held if r["quantities"]["reserved"] > 0]
    stamps = [r["quote"]["quoteTs"] for r in sellable if r.get("quote") and r["quote"].get("quoteTs")]
    skew = (max(stamps) - min(stamps)) if len(stamps) >= 2 else 0
    reasons = []
    for r in held:
        st = r["executable"]["status"]
        if st in ("unknown", "partial"):
            reasons.append(f"{r.get('symbol')}:{st}:{'+'.join(r['executable']['reasons'])}")
        elif st == "pending_only" or r["quantities"]["pendingExit"] > 0:
            reasons.append(f"{r.get('symbol')}:pending_exit_reserved")
    if skew > max_skew_ms:
        reasons.append(f"quote_time_skew_{skew}ms")
    displayed = [r["mark"]["displayedUnrealized"] for r in held]
    seq = int(seq)
    rec = {
        "version": VERSION, "ids": dict(ids or {}), "seq": seq, "capturedAt": int(now_ms), "reason": reason,
        "captureId": hashlib.sha256(f"{instance or 'no-instance'}:{seq}:{int(now_ms)}".encode()).hexdigest()[:40],
        "recorderInstance": instance, "causal": dict(causal or {}) or None, "cash": _f(cash), "positions": rows,
        "depthAllocation": [{"symbol": k[0], "side": k[1], "displayed": v["displayed"], "pendingReserved": v["pendingReserved"], "unspent": v["left"]} for k, v in depth.items()],
        "book": {"openPositions": len(held), "quoteReasons": reasons, "quoteSkewMs": int(skew),
                 "displayedUnrealized": (round(sum(displayed), 4) if all(d is not None for d in displayed) else None),
                 "coveredPartialNet": round(sum((r["executable"]["netCovered"] or 0.0) for r in held), 4),
                 "note": "executable = hypothetical covered liquidation estimate, not a fill; a partial basket is never a total"},
        "limits": {"maxQuoteAgeMs": int(max_age_ms), "maxSkewMs": int(max_skew_ms)},
        "ledger": {"status": "pending"},
    }
    return _close(rec, ledger)


def _close(rec: dict, ledger: dict | None) -> dict:
    b = rec["book"]
    reasons = list(b.get("quoteReasons") or [])
    led = ledger or {"status": "pending"}
    if led.get("status") != "restored":
        reasons.append(f"ledger_{led.get('status') or 'pending'}")
        reasons += [f"ledger_error:{e}" for e in led.get("errors") or []]
    else:
        open_qty = {k: float(v) for k, v in (led.get("openQty") or {}).items()}
        held_qty: dict = {}
        for r in rec["positions"]:
            if r["quantities"]["remaining"] > 0:
                held_qty[r["symbol"]] = held_qty.get(r["symbol"], 0.0) + r["quantities"]["remaining"]
        for sym in sorted(set(open_qty) | set(held_qty)):
            if abs(open_qty.get(sym, 0.0) - held_qty.get(sym, 0.0)) > 1e-6:
                reasons.append(f"ledger_position_mismatch:{sym}:ledger={open_qty.get(sym, 0.0):g}:held={held_qty.get(sym, 0.0):g}")
        by_inst = {k: float(v) for k, v in (led.get("openByInstance") or {}).items()}
        held_inst: dict = {}
        for r in rec["positions"]:
            if r["quantities"]["remaining"] > 0:
                held_inst[str(r.get("tradeInstance") or "")] = held_inst.get(str(r.get("tradeInstance") or ""), 0.0) + r["quantities"]["remaining"]
        for iid in sorted(set(by_inst) | set(held_inst)):                # the SAME contract held by two trades must agree trade by trade
            if abs(by_inst.get(iid, 0.0) - held_inst.get(iid, 0.0)) > 1e-6:
                reasons.append(f"ledger_trade_mismatch:{iid or 'unknown'}:ledger={by_inst.get(iid, 0.0):g}:held={held_inst.get(iid, 0.0):g}")
    scorable = not reasons
    realized = led.get("realizedNet") if led.get("status") == "restored" else None
    held = [r for r in rec["positions"] if r["quantities"]["remaining"] > 0]
    exe = round(sum(r["executable"]["netCovered"] or 0.0 for r in held), 4) if scorable else None
    disp = b.get("displayedUnrealized")
    b.update({"realizedNet": realized, "feesPaid": (led.get("fees") if realized is not None else None),
              "ledgerCashFlow": (led.get("cashFlow") if realized is not None else None),
              "displayedNet": (round(realized + disp, 4) if (realized is not None and disp is not None) else None),
              "executableNetCovered": exe, "executableTotalNet": (round(realized + exe, 4) if (exe is not None and realized is not None) else None),
              "scorable": scorable, "unscorableReasons": reasons})
    rec["ledger"] = {k: led.get(k) for k in ("status", "asOf", "readAt", "executions", "executionSet", "realizedNet", "fees", "cashFlow", "openQty", "openByInstance",
                                            "closedTrades", "openTrades", "lateObserved", "errors", "window")}
    return rec


def finalize_book(rec: dict, ledger: dict | None) -> dict:
    """PHASE 2: attach the execution ledger AS OF the capture time and settle scorability. Pure; idempotent."""
    return _close(rec, ledger)


# ------------------------------------------------------------------------------------------------ execution ledger
LINK_STAGE_ENTRY = "entry"


def instrument_of(symbol: str, sec_type: str | None) -> tuple[float | None, str | None]:
    """AUTHORITATIVE money multiplier: the ORDER's security type checked against the symbol's OCC identity
    (`options.occ.contract_multiplier`: the standard 100 only for a symbol that parses as a standard contract).
    Missing or conflicting identity = (None, problem) - never a guess from the symbol's length."""
    from ..options.occ import contract_multiplier
    st = str(sec_type or "").upper()
    occ_mult = contract_multiplier(symbol)
    if st == "OPT":
        return (float(occ_mult), None) if occ_mult else (None, f"instrument_conflict:{symbol}:OPT_without_standard_occ_identity")
    if st in ("STK", "ETF"):
        return (1.0, None) if occ_mult is None else (None, f"instrument_conflict:{symbol}:{st}_with_occ_identity")
    return None, f"instrument_unknown:{symbol}:{st or 'no_sec_type'}"


def resolve_links(order_events: list) -> dict:
    """Durable order -> trade-instance linkage from the plan runner's journaled order results
    (`TechniquePlanOrderResult`: {seq, runId, trigger, stage, orderId, entryOrderId?}). The trade instance IS the entry
    order id. An exit is bound by its journaled `entryOrderId` when present (`basis: journaled_entry_order`); an older
    event without it is bound to the latest entry of the SAME run and trigger journaled before it
    (`basis: journal_sequence` - the runner holds one trade per trigger at a time). Anything else has NO link: the
    ledger reports it as unknown attribution and never guesses from the symbol."""
    out: dict = {}
    last_entry: dict = {}
    for e in sorted(order_events or [], key=lambda x: int(x.get("seq") or 0)):
        oid = e.get("orderId")
        if not oid:
            continue
        key = (str(e.get("runId") or ""), str(e.get("trigger") or ""))
        stage = str(e.get("stage") or "")
        if stage in (LINK_STAGE_ENTRY, "entry_reconciled"):
            stage = LINK_STAGE_ENTRY
            last_entry[key] = str(oid)
            out[str(oid)] = {"instance": str(oid), "runId": key[0], "trigger": key[1], "stage": stage, "basis": "entry_order"}
        elif stage.startswith("exit"):
            inst, basis = (str(e["entryOrderId"]), "journaled_entry_order") if e.get("entryOrderId") else (last_entry.get(key), "journal_sequence")
            if inst:
                out[str(oid)] = {"instance": inst, "runId": key[0], "trigger": key[1], "stage": stage, "basis": basis}
    return out


def build_ledger(executions: list, *, window: tuple, as_of_ms: int | None = None, links: dict | None = None,
                 session_supported: bool = True, read_at_ms: int | None = None) -> dict:
    """The session's realized result FROM EXECUTIONS ONLY, per TRADE INSTANCE. `executions` = [{id, orderId, symbol, secType,
    side, qty, price, commission, tsMs (occurrence), observedAtMs? (ingestion)}] of ONE book; `links` = `resolve_links`.
    Rows outside `window` (prior sessions) or that occurred after `as_of_ms` are excluded. Partial fills of ONE entry order
    combine; different entry orders NEVER merge, even in the same contract. An exit belongs to the instance its order is
    linked to. Unlinked executions, an exit whose entry has no fill in the window (a carry-in), an exit beyond its entry's
    quantity, a symbol conflict or an unknown instrument are ERRORS: the ledger is `unreconciled` and nothing is
    attributed by symbol. Aggregate cash and fees are reported either way, so both can be verified independently."""
    lo, hi = int(window[0]), int(window[1])
    rows = sorted((e for e in executions or [] if lo <= int(e["tsMs"]) < hi and (as_of_ms is None or int(e["tsMs"]) <= int(as_of_ms))),
                  key=lambda e: (int(e["tsMs"]), str(e.get("id") or ""), str(e.get("orderId")), str(e.get("side"))))
    links = links or {}
    inst: dict = {}
    errors: list = []
    fees = cash = 0.0
    cash_known = True
    late = []
    for e in rows:
        sym, oid = str(e["symbol"]), str(e.get("orderId"))
        qty, px, fee = float(e["qty"]), float(e["price"]), float(e.get("commission") or 0.0)
        buy = str(e["side"]).upper() == "BUY"
        fees += fee
        m, prob = instrument_of(sym, e.get("secType"))
        if prob:
            errors.append(prob); cash_known = False
            continue
        cash += (-(qty * px * m) - fee) if buy else (qty * px * m - fee)
        obs = e.get("observedAtMs")
        if obs is not None and int(obs) - int(e["tsMs"]) > 60_000:
            late.append({"executionId": e.get("id"), "occurredAt": int(e["tsMs"]), "observedAt": int(obs)})
        ln = links.get(oid)
        if ln is None:
            errors.append(f"unlinked_execution:{oid}")
            continue
        iid = ln["instance"]
        t = inst.get(iid)
        if buy:
            if ln["stage"] != LINK_STAGE_ENTRY:
                errors.append(f"side_stage_conflict:{oid}:BUY_on_{ln['stage']}")
                continue
            if t is None:
                t = inst[iid] = {"tradeInstance": iid, "runId": ln.get("runId"), "trigger": ln.get("trigger"), "symbol": sym, "multiplier": m, "bought": 0.0,
                                 "sold": 0.0, "cost": 0.0, "proceeds": 0.0, "fees": 0.0, "openedTs": int(e["tsMs"]), "lastTs": int(e["tsMs"]),
                                 "orders": [], "linkBasis": set()}
            elif t["symbol"] != sym:
                errors.append(f"symbol_conflict:{iid}:{t['symbol']}!={sym}")
                continue
            t["bought"] += qty; t["cost"] += qty * px * m; t["fees"] += fee
        else:
            if ln["stage"] == LINK_STAGE_ENTRY:
                errors.append(f"side_stage_conflict:{oid}:SELL_on_entry")
                continue
            if t is None:
                errors.append(f"carry_in_or_missing_entry:{iid}:{sym}")
                continue
            if t["symbol"] != sym:
                errors.append(f"symbol_conflict:{iid}:{t['symbol']}!={sym}")
                continue
            if t["bought"] - t["sold"] + 1e-9 < qty:
                errors.append(f"exit_exceeds_entry:{iid}")
                continue
            t["sold"] += qty; t["proceeds"] += qty * px * m; t["fees"] += fee
        t["lastTs"] = int(e["tsMs"]); t["linkBasis"].add(ln.get("basis"))
        if oid not in t["orders"]:
            t["orders"].append(oid)
    closed, open_trades = [], {}
    realized = 0.0
    for iid, t in inst.items():
        avg = t["cost"] / t["bought"] if t["bought"] else 0.0
        gross = t["proceeds"] - avg * t["sold"]
        realized += gross - t["fees"]
        common = {"tradeInstance": iid, "runId": t["runId"], "trigger": t["trigger"], "symbol": t["symbol"], "fees": round(t["fees"], 4),
                  "orders": list(t["orders"]), "linkBasis": sorted(x for x in t["linkBasis"] if x)}
        if t["bought"] - t["sold"] <= 1e-9:
            closed.append({**common, "qty": t["bought"], "gross": round(gross, 4), "net": round(gross - t["fees"], 4), "openedTs": t["openedTs"], "closedTs": t["lastTs"]})
        else:
            open_trades[iid] = {**common, "remaining": round(t["bought"] - t["sold"], 6), "avgCost": round(avg / t["multiplier"], 6), "realizedGross": round(gross, 4)}
    open_qty: dict = {}
    for t in open_trades.values():
        open_qty[t["symbol"]] = round(open_qty.get(t["symbol"], 0.0) + t["remaining"], 6)
    status = "unsupported_session" if not session_supported else ("restored" if not errors else "unreconciled")
    ids = sorted(str(e.get("id") or f"{e.get('orderId')}:{e['tsMs']}:{e['qty']}:{e['price']}") for e in rows)
    return {"status": status, "asOf": as_of_ms, "readAt": read_at_ms, "window": [lo, hi], "executions": len(rows),
            "executionSet": hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:24],
            "realizedNet": round(realized, 4), "fees": round(fees, 4), "cashFlow": (round(cash, 4) if cash_known else None),
            "openQty": open_qty, "openByInstance": {k: v["remaining"] for k, v in open_trades.items()},
            "closedTrades": sorted(closed, key=lambda c: (c["closedTs"], c["tradeInstance"])), "openTrades": open_trades,
            "lateObserved": late, "errors": errors}


def execution_set(executions: list, *, window: tuple, as_of_ms: int) -> str:
    """The identity of the executions a ledger as of `as_of_ms` SHOULD contain - the reducer compares it with what each
    capture actually saw, so a fill discovered later REVISES with provenance instead of silently rewriting history."""
    return build_ledger(executions, window=window, as_of_ms=as_of_ms, links={})["executionSet"]


# ------------------------------------------------------------------------------------------------ bounded recorder
class ProfitCaptureObserver:
    """EM-owned. `snap()` is synchronous and cheap: knob check, pure capture, `put_nowait`. The recorder task then attaches
    the execution ledger (`finalize`, off every trading path) and writes IDEMPOTENTLY: the record's `captureId` is stable
    across retries, so an ambiguous acknowledgement can never insert a second observation. Each observer instance has its
    own id - a restart is a distinct identity and an explicit gap. Nothing on a protective path awaits this object."""

    def __init__(self, *, enabled: Callable[[], bool], collect: Callable[[], dict | None],
                 write: Callable[[dict], Awaitable[None]], clock_ms: Callable[[], int], cadence_s: Callable[[], float],
                 finalize: Callable[[dict], Awaitable[dict]] | None = None,
                 maxsize: int = 256, retries: int = 3, retry_sleep_s: float = 0.5, on_drop: Callable[[str, dict], None] | None = None):
        self._enabled, self._collect, self._write, self._clock, self._cadence = enabled, collect, write, clock_ms, cadence_s
        self._finalize = finalize
        self._maxsize, self._retries, self._retry_sleep, self._on_drop = int(maxsize), int(retries), float(retry_sleep_s), on_drop
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._seq = 0
        self._last_periodic_ms = 0
        self._restored = False
        self.instance = uuid.uuid4().hex
        self.stats = {"captured": 0, "written": 0, "droppedQueueFull": 0, "droppedWriteFailed": 0, "captureErrors": 0, "retries": 0, "finalizeErrors": 0}

    def snap(self, reason: str, causal: dict | None = None) -> dict | None:
        """Returns the captured (phase 1) record or None. NEVER raises, never awaits."""
        try:
            if not self._enabled():
                return None
            now = int(self._clock())
            if reason == "periodic":
                if now - self._last_periodic_ms < max(1.0, float(self._cadence())) * 1000.0:
                    return None
                self._last_periodic_ms = now
            inputs = self._collect()
            if not inputs or (reason == "periodic" and not inputs.get("positions")):
                return None                                  # a flat book records nothing periodic; EVENT snapshots (a closing fill) always land
            if not self._restored:
                self._restored = True
                if reason == "periodic":
                    reason = "restore"                       # the first sample of an observer instance is an explicit gap marker
            self._seq += 1
            rec = capture_book(seq=self._seq, now_ms=now, reason=reason, causal=causal, instance=self.instance, **inputs)
            rec["recorder"] = {**self.stats, "instance": self.instance}
            self.stats["captured"] += 1
            self._put(rec)
            return rec
        except Exception:                                    # noqa: BLE001 - research must never disturb the runner
            self.stats["captureErrors"] += 1
            log.exception("book snapshot capture failed")
            return None

    def _put(self, rec: dict) -> None:
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._maxsize)
        try:
            self._queue.put_nowait(rec)
        except asyncio.QueueFull:
            self.stats["droppedQueueFull"] += 1
            if self._on_drop:
                self._on_drop("queue_full", rec)
            return
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._drain(), name="em-book-snapshot-recorder")

    async def _drain(self) -> None:
        q = self._queue
        while True:
            rec = await q.get()
            try:
                if self._finalize is not None:
                    try:
                        rec = await self._finalize(rec)      # execution ledger as of the capture time - off every trading path
                    except Exception:                        # noqa: BLE001 - still written: ledger error = unscorable, visibly
                        self.stats["finalizeErrors"] += 1
                        rec = finalize_book(rec, {"status": "error"})
                for attempt in range(self._retries):
                    try:
                        await self._write(rec)               # idempotent by rec["captureId"]
                        self.stats["written"] += 1
                        break
                    except Exception as exc:                 # noqa: BLE001
                        if attempt == self._retries - 1:
                            self.stats["droppedWriteFailed"] += 1
                            if self._on_drop:
                                self._on_drop(f"write_failed:{type(exc).__name__}", rec)
                        else:
                            self.stats["retries"] += 1
                            await asyncio.sleep(self._retry_sleep)
            finally:
                q.task_done()

    async def wait_idle(self) -> None:
        if self._queue is not None:
            await self._queue.join()


# --------------------------------------------------------------------------------------------------- offline reducer
def reduce_session(snapshots: list, *, execution_net: float | None = None, execution_fees: float | None = None,
                   transfers: float | None = 0.0, p02: list | None = None, p06: list | None = None,
                   final_executions: list | None = None) -> dict:
    """Offline. `snapshots` = records of ONE book/session in any order. `execution_net` / `execution_fees` = the
    execution-backed session result used to reconcile the flat endpoint; `transfers` = deposits/repairs, never trading
    gains. The EXECUTABLE peak uses only scorable snapshots. Recorder restarts (a new instance), missing sequence numbers
    and drop counters are surfaced. Per-trade attribution reconciles each position at the peak to its CLOSED TRADE in the
    final ledger (executions), never to in-memory state."""
    snaps = sorted((s for s in snapshots or [] if s.get("version") == VERSION), key=lambda s: (int(s.get("capturedAt") or 0), int(s.get("seq") or 0)))
    seen, uniq = set(), []
    for s in snaps:                                           # a duplicate observation (same captureId) counts once
        k = s.get("captureId") or (s.get("recorderInstance"), s.get("seq"), s.get("capturedAt"))
        if k in seen:
            continue
        seen.add(k); uniq.append(s)
    duplicates = len(snaps) - len(uniq)
    snaps = uniq
    out: dict[str, Any] = {"version": REDUCER_VERSION, "snapshots": len(snaps), "duplicatesIgnored": duplicates}
    scopes = sorted({(str((s.get("ids") or {}).get("portfolioId") or ""), str((s.get("ids") or {}).get("session") or "")) for s in snaps})
    if len(scopes) > 1:                                       # one book, one session - a mixed input is refused, never blended
        out.update({"status": "error_mixed_scope", "scopes": [{"portfolioId": a, "session": b} for a, b in scopes],
                    "note": "snapshots of more than one book or session were supplied - nothing is reduced"})
        return out
    policies = {json.dumps((s.get("ids") or {}).get("policy"), sort_keys=True, default=str) for s in snaps}
    out["scope"] = {"portfolioId": scopes[0][0] if scopes else None, "session": scopes[0][1] if scopes else None, "policyVariants": len(policies),
                    "singlePolicy": len(policies) <= 1}
    if not snaps:
        out.update({"status": "no_snapshots", "note": "the recorder was off or the book was flat - nothing is inferred",
                    "pairedExits": {"p02": summarize_paired(p02, []), "p06": summarize_paired(p06, [])}})
        return out
    revisions = []
    if final_executions is not None:                          # capture-as-of vs later reconciliation: a fill discovered later REVISES, with provenance
        for s in snaps:
            led = s.get("ledger") or {}
            if led.get("executionSet") and led.get("window"):
                want = execution_set(final_executions, window=tuple(led["window"]), as_of_ms=int(s["capturedAt"]))
                if want != led["executionSet"]:
                    revisions.append({"captureId": s.get("captureId"), "capturedAt": s["capturedAt"], "seq": s["seq"],
                                      "why": "executions that occurred before this capture were not yet known to the observer (late arrival)"})
    revised = {r["captureId"] for r in revisions}
    scor = [s for s in snaps if (s.get("book") or {}).get("scorable") and s.get("captureId") not in revised]
    disp = [s for s in snaps if (s.get("book") or {}).get("displayedNet") is not None]

    def peak(rows, key):
        if not rows:
            return None
        b = max(rows, key=lambda s: s["book"][key])
        return {"value": b["book"][key], "at": b["capturedAt"], "seq": b["seq"], "reason": b["reason"], "captureId": b.get("captureId")}
    last = snaps[-1]
    flat_end = (last.get("book") or {}).get("openPositions") == 0
    final_realized = (last.get("book") or {}).get("realizedNet")
    gaps = []
    for a, b in zip(snaps, snaps[1:]):
        if a.get("recorderInstance") != b.get("recorderInstance"):
            gaps.append({"at": b["capturedAt"], "kind": "recorder_restart", "from": a["seq"], "to": b["seq"]})
        elif int(b["seq"]) - int(a["seq"]) > 1:
            gaps.append({"at": b["capturedAt"], "kind": "missing_samples", "from": a["seq"], "to": b["seq"], "missing": int(b["seq"]) - int(a["seq"]) - 1})
    per_inst: dict = {}                                       # drop counters restart with the observer: the session total is the SUM of each instance's maximum
    for s in snaps:
        k = s.get("recorderInstance")
        per_inst[k] = max(per_inst.get(k, 0), int((s.get("recorder") or {}).get("droppedQueueFull", 0)) + int((s.get("recorder") or {}).get("droppedWriteFailed", 0)))
    drops = sum(per_inst.values())
    unsc: dict[str, int] = {}
    for s in snaps:
        for r in (s.get("book") or {}).get("unscorableReasons") or []:
            parts = r.split(":")
            k = "quote_time_skew" if r.startswith("quote_time_skew") else (parts[0] if r.startswith("ledger") else (parts[1] if len(parts) > 1 else parts[0]))
            unsc[k] = unsc.get(k, 0) + 1
    p_exec, p_disp = peak(scor, "executableTotalNet"), peak(disp, "displayedNet")
    out.update({
        "status": "ok", "first": snaps[0]["capturedAt"], "last": last["capturedAt"],
        "coverage": {"scorable": len(scor), "unscorable": len(snaps) - len(scor), "ratio": round(len(scor) / len(snaps), 4),
                     "unscorableReasons": unsc, "gaps": gaps, "recorderDrops": int(drops),
                     "recorderInstances": len({s.get("recorderInstance") for s in snaps}), "dropsByInstance": {str(k): v for k, v in per_inst.items()},
                     "revisedByLateExecutions": revisions, "lateObservedExecutions": (last.get("ledger") or {}).get("lateObserved") or []},
        "realizedNetFinal": final_realized, "flatAtEnd": flat_end,
        "peakDisplayedNet": p_disp, "peakExecutableNet": p_exec, "displayedMinusExecutableAtExecPeak": None,
        "givebackVsExecutablePeak": (round(p_exec["value"] - final_realized, 4) if (p_exec and flat_end and final_realized is not None) else None),
        "givebackVsDisplayedPeak": (round(p_disp["value"] - final_realized, 4) if (p_disp and flat_end and final_realized is not None) else None),
    })
    final_closed = {c["tradeInstance"]: c for c in ((last.get("ledger") or {}).get("closedTrades") or [])}
    if p_exec:
        s = next(x for x in snaps if x.get("captureId") == p_exec.get("captureId") and x["seq"] == p_exec["seq"])
        if s["book"].get("displayedNet") is not None:
            out["displayedMinusExecutableAtExecPeak"] = round(s["book"]["displayedNet"] - s["book"]["executableTotalNet"], 4)
        open_at_peak = (s.get("ledger") or {}).get("openTrades") or {}
        attr = []
        for r in s["positions"]:
            lt = open_at_peak.get(r.get("tradeInstance")) or {}
            at_peak = float(lt.get("realizedGross") or 0.0) - float(lt.get("fees") or 0.0) + (r["executable"]["netCovered"] or 0.0)
            fin = final_closed.get(r.get("tradeInstance"))
            attr.append({"tradeInstance": r.get("tradeInstance"), "runId": (fin or lt).get("runId"), "trigger": (fin or lt).get("trigger"),
                         "symbol": r.get("symbol"), "netAtPeak": round(at_peak, 4),
                         "finalNet": (fin["net"] if fin else None), "giveback": (round(at_peak - fin["net"], 4) if fin else None),
                         "feesAfterPeak": (round(fin["fees"] - float(lt.get("fees") or 0.0), 4) if fin else None),
                         "basis": ("executions (closed trade in the final ledger)" if fin else "unknown: the trade is not closed in the final ledger")})
        out["attributionAtExecutablePeak"] = attr
    out["closedTrades"] = list(final_closed.values())
    if execution_net is not None:
        if flat_end and final_realized is not None:
            diff = round(float(final_realized) - float(execution_net), 4)
            fees_paid = (last.get("book") or {}).get("feesPaid")
            fee_diff = (round(float(fees_paid) - float(execution_fees), 4) if (execution_fees is not None and fees_paid is not None) else None)
            trades_sum = round(sum(c["net"] for c in final_closed.values()), 4)
            cash0, cash1 = snaps[0].get("cash"), last.get("cash")
            flow0, flow1 = (snaps[0].get("book") or {}).get("ledgerCashFlow"), (last.get("book") or {}).get("ledgerCashFlow")
            cash_diff = (round((cash1 - cash0) - (flow1 - flow0) - float(transfers), 4) if None not in (cash0, cash1, flow0, flow1, transfers) else None)
            bad = abs(diff) > 0.011 or (fee_diff is not None and abs(fee_diff) > 0.011) or abs(trades_sum - float(final_realized)) > 0.011 \
                or (cash_diff is not None and abs(cash_diff) > 0.011)
            missing = [n for n, v in (("fees", fee_diff), ("cash", cash_diff)) if v is None]
            out["reconciliation"] = {"executionBackedNet": round(float(execution_net), 4), "snapshotRealizedNet": final_realized, "difference": diff,
                                     "feesDifference": fee_diff, "sumOfClosedTrades": trades_sum, "cashMinusLedgerFlow": cash_diff,
                                     "transfersExcluded": (round(float(transfers), 4) if transfers is not None else None), "comparisonsUnavailable": missing,
                                     "status": ("error_unexplained_difference" if bad else ("partial_comparisons_unavailable" if missing else "ok"))}
        else:
            out["reconciliation"] = {"executionBackedNet": round(float(execution_net), 4), "status": "not_flat_at_last_snapshot",
                                     "note": "the endpoint is not flat or the ledger was never restored in the capture - not reconciled, not assumed"}
    out["pairedExits"] = {"p02": summarize_paired(p02, snaps), "p06": summarize_paired(p06, snaps)}
    return out


def summarize_paired(rows: list | None, snaps: list) -> dict | None:
    """Consumer integration for the P-02 / P-06 reducers' per-trade rows: each paired-exit row is joined to the book
    capture by STRICT trade identity (`tradeInstance` = entry order id) and time; a row whose trade has no snapshot at
    or before its signal keeps `bookContext: None` (unknown) - nothing is reconstructed after the position closed."""
    if rows is None:
        return None
    out = []
    known: dict = {}                                          # trade instances VERIFIED by the execution ledger, with their lifecycle
    for s in snaps:
        led = s.get("ledger") or {}
        for c in led.get("closedTrades") or []:
            known[c["tradeInstance"]] = {"openedTs": c.get("openedTs"), "closedTs": c.get("closedTs")}
        for k in (led.get("openTrades") or {}):
            known.setdefault(k, {"openedTs": None, "closedTs": None})
    for r in rows:
        inst, at = r.get("tradeInstance") or r.get("entryOrderId"), int(r.get("signalTs") or r.get("observedAt") or 0)
        ctx = None
        life = known.get(inst)
        verified = life is not None and at > 0 and (life.get("openedTs") is None or at >= int(life["openedTs"])) and (life.get("closedTs") is None or at <= int(life["closedTs"]))
        for s in (reversed(snaps) if verified else []):
            if int(s["capturedAt"]) <= at:
                m = next((x for x in s["positions"] if x.get("tradeInstance") == inst and x["quantities"]["remaining"] > 0), None)
                if m is not None:
                    ctx = {"seq": s["seq"], "capturedAt": s["capturedAt"], "status": m["executable"]["status"],
                           "netCovered": m["executable"]["netCovered"], "displayedUnrealized": m["mark"]["displayedUnrealized"],
                           "bookScorable": s["book"]["scorable"]}
                break
        out.append({"tradeInstance": inst, "policy": r.get("policy"), "outcome": r.get("outcome"), "dollarDelta": r.get("dollarDelta"),
                    "identityVerified": bool(verified), "comparisonClass": r.get("comparisonClass") or ("dollars" if r.get("dollarDelta") is not None else "proxy_only"),
                    "bookContext": ctx})
    return {"rows": out, "withBookContext": sum(1 for x in out if x["bookContext"]), "total": len(out)}
