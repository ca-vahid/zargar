"""ED-04 executable-profit capture (`book-snapshot-v1`, 2026-09-18; integrated plan workstream E).

Three numbers that were conflated are kept apart for the EM Practice book at one instant:
  realized net        cash already booked from fills, net of the fees actually paid
  displayed (marked)  the book's own mark of what is still held (option mid when there is an ask, else last) - the
                      number the UI shows; reproduced with the SAME rule as `portfolio.PositionKeeper._mark`
  executable, covered what the UNCOMMITTED remainder could be sold for against the covered side of a fresh, raw,
                      venue quote (bid for a long, ask for a short), limited by the DISPLAYED size, minus the modeled
                      exit fee. It is a hypothetical liquidation estimate, never a fill.

Layout: `capture_book` is PURE (no I/O, no clock, no settings); `ProfitCaptureObserver` is the EM-owned bounded
asynchronous recorder the runner calls SYNCHRONOUSLY (capture + put_nowait; never awaited by a protective path);
`reduce_session` is the offline reducer the report and the API read. Default OFF under
`techniques.enhanced_market.book_snapshot_observe`.

Rules frozen with the record: a stale / delayed / derived / crossed / unknown-size quote is `unknown` (a value, never a
zero); pending exit quantity is reserved and cannot be sold twice; spread is never deducted twice (the covered side is
used directly; the mark keeps its own basis); a book with ANY position not fully covered, or whose quotes are further
apart in time than the skew limit, is not scorable and can never make a high-water mark.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

VERSION = "book-snapshot-v1"
REDUCER_VERSION = "profit-capture-reducer-v1"
MAX_QUOTE_AGE_MS = 10_000
MAX_SKEW_MS = 5_000
REASONS = ("periodic", "pre_target", "post_target", "pre_stop", "post_stop", "pre_protection", "post_protection",
           "pre_flatten", "post_flatten", "fill", "restore")


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


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


def _quote_problems(q: dict | None, now_ms: int, max_age_ms: int, side: str) -> list[str]:
    if not q:
        return ["no_quote"]
    out = []
    src = str(q.get("source") or "")
    if src.startswith("derived:") or q.get("transform"):
        out.append("derived_quote")
    elif src == "chain" or q.get("delayed"):
        out.append("delayed_quote")
    src_ts = int(q.get("sourceTs") or 0)
    if src_ts <= 0:
        out.append("source_time_unknown")
    elif now_ms - src_ts > max_age_ms:
        out.append("stale_quote")
    elif src_ts - now_ms > 1000:
        out.append("source_time_in_future")
    bid, ask = _f(q.get("bid")), _f(q.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        out.append("one_sided_book")
    elif ask < bid:
        out.append("crossed_book")
    size = q.get("bidSize" if side == "bid" else "askSize")
    if size in (None, 0) or (_f(size) or 0) <= 0:
        out.append("size_unknown")
    return out


def capture_position(pos: dict, quote: dict | None, *, now_ms: int, exit_fee_per_unit: float,
                     max_age_ms: int = MAX_QUOTE_AGE_MS) -> dict:
    """One held position. `pos` = {runId, trigger, tradeInstance, symbol (what is held), underlying, direction,
    instrument (shares|options), multiplier, positionSide (long|short), original, remaining, pendingExit, avgFill,
    realizedGross, feesPaid}. Quantities are conserved: reserved = remaining - pendingExit is the ONLY sellable part."""
    m = float(pos.get("multiplier") or 1.0)
    remaining = max(0.0, float(pos.get("remaining") or 0.0))
    pending = max(0.0, min(remaining, float(pos.get("pendingExit") or 0.0)))
    reserved = max(0.0, remaining - pending)
    avg = _f(pos.get("avgFill"))
    sec = "OPT" if pos.get("instrument") == "options" else "STK"
    long_side = str(pos.get("positionSide") or "long") == "long"
    side = "bid" if long_side else "ask"
    mark, basis = mark_of(sec, quote, avg)
    sign = 1.0 if long_side else -1.0
    displayed = round((mark - avg) * remaining * m * sign, 4) if (mark is not None and avg is not None) else None
    problems = _quote_problems(quote, now_ms, max_age_ms, side) if reserved > 0 else []
    q = quote or {}
    px = _f(q.get(side))
    size = _f(q.get("bidSize" if side == "bid" else "askSize")) or 0.0
    if reserved <= 0:
        covered, status = 0.0, ("pending_only" if pending > 0 else "flat")
    elif problems or avg is None:
        covered, status = 0.0, "unknown"
        if avg is None:
            problems = problems + ["entry_price_unknown"]
    else:
        covered = min(reserved, size)
        status = "covered" if covered + 1e-9 >= reserved else "partial"
        if status == "partial":
            problems = ["displayed_size_below_quantity"]
    gross = round((px - avg) * covered * m * sign, 4) if (covered > 0 and px is not None and avg is not None) else (0.0 if status in ("flat", "pending_only") else None)
    fee = round(float(exit_fee_per_unit) * covered, 4) if covered > 0 else 0.0
    src_ts = int(q.get("sourceTs") or 0)
    return {
        "runId": pos.get("runId"), "trigger": pos.get("trigger"), "tradeInstance": pos.get("tradeInstance"),
        "symbol": pos.get("symbol"), "underlying": pos.get("underlying"), "direction": pos.get("direction"),
        "instrument": pos.get("instrument"), "multiplier": m, "positionSide": ("long" if long_side else "short"),
        "quantities": {"original": float(pos.get("original") or 0.0), "remaining": remaining, "pendingExit": pending, "reserved": reserved},
        "avgFill": avg, "realizedGross": round(float(pos.get("realizedGross") or 0.0), 4), "feesPaid": round(float(pos.get("feesPaid") or 0.0), 4),
        "mark": {"basis": basis, "price": (round(mark, 6) if mark is not None else None), "displayedUnrealized": displayed},
        "quote": ({"symbol": pos.get("symbol"), "bid": _f(q.get("bid")), "ask": _f(q.get("ask")), "last": _f(q.get("last")),
                   "bidSize": q.get("bidSize"), "askSize": q.get("askSize"), "source": q.get("source") or None,
                   "rawSource": q.get("rawSource") or None, "transform": q.get("transform") or None,
                   "sourceTs": src_ts or None, "receivedTs": int(q.get("receivedTs") or 0) or None,
                   "ageMs": (now_ms - src_ts if src_ts else None), "session": q.get("session") or None, "feed": q.get("feed") or None}
                  if quote else None),
        "executable": {"side": side, "price": (px if covered > 0 else None), "coveredQty": covered,
                       "uncoveredQty": round(reserved - covered, 6), "grossCovered": gross, "feeModeled": fee,
                       "netCovered": (round(gross - fee, 4) if gross is not None else None),
                       "status": status, "reasons": problems},
    }


def capture_book(*, ids: dict, seq: int, now_ms: int, reason: str, causal: dict | None, cash: float | None,
                 realized_closed_net: float, fees_closed: float, positions: list, quotes: dict,
                 fee_per_contract: float, stock_fee: float = 0.0, max_age_ms: int = MAX_QUOTE_AGE_MS,
                 max_skew_ms: int = MAX_SKEW_MS) -> dict:
    """ONE immutable book observation. `ids` = {portfolioId, session, build, baseline, policy{...}}; `causal` =
    {eventId?, kind, runId, trigger} of the decision the snapshot brackets; `realized_closed_net` = net realized on
    positions already closed this session (their fees in `fees_closed`); open positions carry their own realized part."""
    rows = []
    for p in positions or []:
        fee = float(fee_per_contract) if p.get("instrument") == "options" else float(stock_fee)
        rows.append(capture_position(p, (quotes or {}).get(p.get("symbol")), now_ms=now_ms, exit_fee_per_unit=fee, max_age_ms=max_age_ms))
    held = [r for r in rows if r["quantities"]["remaining"] > 0]
    sellable = [r for r in held if r["quantities"]["reserved"] > 0]
    stamps = [r["quote"]["sourceTs"] for r in sellable if r.get("quote") and r["quote"].get("sourceTs")]
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
    scorable = not reasons
    realized_open = sum(r["realizedGross"] - r["feesPaid"] for r in rows)
    realized_net = round(float(realized_closed_net) + realized_open, 4)
    fees_paid = round(float(fees_closed) + sum(r["feesPaid"] for r in rows), 4)
    displayed = [r["mark"]["displayedUnrealized"] for r in held]
    displayed_total = round(sum(displayed), 4) if all(d is not None for d in displayed) else None
    exe_net = round(sum(r["executable"]["netCovered"] or 0.0 for r in held), 4) if scorable else None
    return {
        "version": VERSION, "ids": dict(ids or {}), "seq": int(seq), "capturedAt": int(now_ms), "reason": reason,
        "causal": dict(causal or {}) or None, "cash": (_f(cash)), "positions": rows,
        "book": {"openPositions": len(held), "realizedNet": realized_net, "feesPaid": fees_paid,
                 "displayedUnrealized": displayed_total,
                 "displayedNet": (round(realized_net + displayed_total, 4) if displayed_total is not None else None),
                 "executableNetCovered": exe_net,
                 "executableTotalNet": (round(realized_net + exe_net, 4) if exe_net is not None else None),
                 "coveredPartialNet": round(sum((r["executable"]["netCovered"] or 0.0) for r in held), 4),
                 "scorable": scorable, "unscorableReasons": reasons, "quoteSkewMs": int(skew),
                 "note": "executable = hypothetical covered liquidation estimate, not a fill; a partial basket is never a total"},
        "limits": {"maxQuoteAgeMs": int(max_age_ms), "maxSkewMs": int(max_skew_ms)},
    }


# ------------------------------------------------------------------------------------------------ bounded recorder
class ProfitCaptureObserver:
    """EM-owned. `snap()` is synchronous and cheap: knob check, pure capture, `put_nowait`. The background task retries a
    failed write up to `retries` times with the record's ORIGINAL timing, then drops it VISIBLY. Nothing on a
    protective path ever awaits this object. Memory is bounded by the queue size; a full queue drops and counts."""

    def __init__(self, *, enabled: Callable[[], bool], collect: Callable[[], dict | None],
                 write: Callable[[dict], Awaitable[None]], clock_ms: Callable[[], int], cadence_s: Callable[[], float],
                 maxsize: int = 256, retries: int = 3, retry_sleep_s: float = 0.5, on_drop: Callable[[str, dict], None] | None = None):
        self._enabled, self._collect, self._write, self._clock, self._cadence = enabled, collect, write, clock_ms, cadence_s
        self._maxsize, self._retries, self._retry_sleep, self._on_drop = int(maxsize), int(retries), float(retry_sleep_s), on_drop
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._seq = 0
        self._last_periodic_ms = 0
        self._restored = False
        self.stats = {"captured": 0, "written": 0, "droppedQueueFull": 0, "droppedWriteFailed": 0, "captureErrors": 0, "retries": 0}

    def snap(self, reason: str, causal: dict | None = None) -> dict | None:
        """Returns the captured record (or None). NEVER raises, never awaits."""
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
                    reason = "restore"                       # the first sample after a (re)start is an explicit gap marker
            self._seq += 1
            rec = capture_book(seq=self._seq, now_ms=now, reason=reason, causal=causal,
                               **inputs)
            rec["recorder"] = dict(self.stats)
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
                for attempt in range(self._retries):
                    try:
                        await self._write(rec)
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
def reduce_session(snapshots: list, *, execution_net: float | None = None, transfers: float = 0.0,
                   p02: list | None = None, p06: list | None = None) -> dict:
    """Offline. `snapshots` = records of ONE book/session in any order. `execution_net` = the execution-backed net of
    the session (fills and commissions) used to reconcile the flat endpoint; `transfers` = deposits/repairs, which are
    never trading gains. Peaks: displayed peaks use any snapshot with a displayed value; the EXECUTABLE peak uses only
    scorable snapshots. Gaps in `seq` and recorder drop counters are surfaced, never smoothed."""
    snaps = sorted((s for s in snapshots or [] if s.get("version") == VERSION), key=lambda s: (int(s.get("capturedAt") or 0), int(s.get("seq") or 0)))
    out: dict[str, Any] = {"version": REDUCER_VERSION, "snapshots": len(snaps)}
    if not snaps:
        out.update({"status": "no_snapshots", "note": "the recorder was off or the book was flat - nothing is inferred",
                    "pairedExits": {"p02": summarize_paired(p02, []), "p06": summarize_paired(p06, [])}})     # the rows exist; their book context is unknown
        return out
    scor = [s for s in snaps if (s.get("book") or {}).get("scorable")]
    disp = [s for s in snaps if (s.get("book") or {}).get("displayedNet") is not None]

    def peak(rows, key):
        if not rows:
            return None
        b = max(rows, key=lambda s: s["book"][key])
        return {"value": b["book"][key], "at": b["capturedAt"], "seq": b["seq"], "reason": b["reason"]}
    last = snaps[-1]
    flat_end = (last.get("book") or {}).get("openPositions") == 0
    final_realized = (last.get("book") or {}).get("realizedNet")
    seqs = [int(s.get("seq") or 0) for s in snaps]
    gaps = []
    for a, b in zip(snaps, snaps[1:]):
        if int(b["seq"]) < int(a["seq"]):
            gaps.append({"at": b["capturedAt"], "kind": "recorder_restart", "from": a["seq"], "to": b["seq"]})
        elif int(b["seq"]) - int(a["seq"]) > 1:
            gaps.append({"at": b["capturedAt"], "kind": "missing_samples", "from": a["seq"], "to": b["seq"], "missing": int(b["seq"]) - int(a["seq"]) - 1})
    drops = max(((s.get("recorder") or {}).get("droppedQueueFull", 0) + (s.get("recorder") or {}).get("droppedWriteFailed", 0)) for s in snaps)
    unsc: dict[str, int] = {}
    for s in snaps:
        for r in (s.get("book") or {}).get("unscorableReasons") or []:
            k = r.split(":")[1] if r.count(":") >= 1 and not r.startswith("quote_time_skew") else ("quote_time_skew" if r.startswith("quote_time_skew") else r)
            unsc[k] = unsc.get(k, 0) + 1
    p_exec, p_disp = peak(scor, "executableTotalNet"), peak(disp, "displayedNet")
    out.update({
        "status": "ok", "first": snaps[0]["capturedAt"], "last": last["capturedAt"], "seqRange": [min(seqs), max(seqs)],
        "coverage": {"scorable": len(scor), "unscorable": len(snaps) - len(scor), "ratio": round(len(scor) / len(snaps), 4),
                     "unscorableReasons": unsc, "gaps": gaps, "recorderDrops": int(drops)},
        "realizedNetFinal": final_realized, "flatAtEnd": flat_end,
        "peakDisplayedNet": p_disp, "peakExecutableNet": p_exec,
        "displayedMinusExecutableAtExecPeak": None,
        "givebackVsExecutablePeak": (round(p_exec["value"] - final_realized, 4) if (p_exec and flat_end and final_realized is not None) else None),
        "givebackVsDisplayedPeak": (round(p_disp["value"] - final_realized, 4) if (p_disp and flat_end and final_realized is not None) else None),
    })
    if p_exec:
        s = next(x for x in snaps if x["seq"] == p_exec["seq"] and x["capturedAt"] == p_exec["at"])
        if s["book"].get("displayedNet") is not None:
            out["displayedMinusExecutableAtExecPeak"] = round(s["book"]["displayedNet"] - s["book"]["executableTotalNet"], 4)
        # attribution by position AT the executable peak: what each position then gave back (or added) by the end
        attr = []
        for r in s["positions"]:
            end = None
            for t in reversed(snaps):
                m = next((x for x in t["positions"] if x.get("tradeInstance") == r.get("tradeInstance")), None)
                if m is not None:
                    end = m
                    break
            at_peak = (r["realizedGross"] - r["feesPaid"]) + (r["executable"]["netCovered"] or 0.0)
            final = (end["realizedGross"] - end["feesPaid"]) if (end and end["quantities"]["remaining"] == 0) else None
            attr.append({"tradeInstance": r.get("tradeInstance"), "symbol": r.get("symbol"), "netAtPeak": round(at_peak, 4),
                         "finalNet": (round(final, 4) if final is not None else None),
                         "giveback": (round(at_peak - final, 4) if final is not None else None),
                         "feesAfterPeak": (round(end["feesPaid"] - r["feesPaid"], 4) if end else None)})
        out["attributionAtExecutablePeak"] = attr
    if execution_net is not None:
        if flat_end and final_realized is not None:
            diff = round(float(final_realized) - float(execution_net), 4)
            out["reconciliation"] = {"executionBackedNet": round(float(execution_net), 4), "snapshotRealizedNet": final_realized,
                                     "transfersExcluded": round(float(transfers), 4), "difference": diff,
                                     "status": ("ok" if abs(diff) <= 0.011 else "error_unexplained_difference")}
        else:
            out["reconciliation"] = {"executionBackedNet": round(float(execution_net), 4), "status": "not_flat_at_last_snapshot",
                                     "note": "the endpoint is not flat in the capture - not reconciled, not assumed"}
    out["pairedExits"] = {"p02": summarize_paired(p02, snaps), "p06": summarize_paired(p06, snaps)}
    return out


def summarize_paired(rows: list | None, snaps: list) -> dict | None:
    """Consumer integration for the P-02 / P-06 reducers' per-trade rows: each paired-exit row is joined to the book
    capture by STRICT trade identity (`tradeInstance` = entry order id) and time; a row whose trade has no snapshot at
    or before its signal keeps `bookContext: None` (unknown) - nothing is reconstructed after the position closed."""
    if rows is None:
        return None
    out = []
    for r in rows:
        inst, at = r.get("tradeInstance") or r.get("entryOrderId"), int(r.get("signalTs") or r.get("observedAt") or 0)
        ctx = None
        for s in reversed(snaps):
            if int(s["capturedAt"]) <= at:
                m = next((x for x in s["positions"] if x.get("tradeInstance") == inst and x["quantities"]["remaining"] > 0), None)
                if m is not None:
                    ctx = {"seq": s["seq"], "capturedAt": s["capturedAt"], "status": m["executable"]["status"],
                           "netCovered": m["executable"]["netCovered"], "displayedUnrealized": m["mark"]["displayedUnrealized"],
                           "bookScorable": s["book"]["scorable"]}
                break
        out.append({"tradeInstance": inst, "policy": r.get("policy"), "outcome": r.get("outcome"), "dollarDelta": r.get("dollarDelta"),
                    "bookContext": ctx})
    return {"rows": out, "withBookContext": sum(1 for x in out if x["bookContext"]), "total": len(out)}
