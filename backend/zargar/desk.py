"""The morning desk surface (POST-SOAK-BUILD-PLAN Phase 1).

The user is three time zones behind the market: the open is 06:30 local. This
module owns the three technique-agnostic jobs that make mornings safe:

- `roll_watchdog` (09:00 ET): every registered plan runner sweeps for plans the
  close missed (`PlanRunner.roll_stale`) — a restart inside the close window can
  skip both the bar-driven close and the 16:05 clock.
- `soak_nightly` (17:30 ET): the practice-soak scorecard, persisted for free via
  the scheduler's `ScheduledJobRan` journal row.
- `morning_report` (08:25 ET): ONE composed answer to "what needs me" — pushed
  (web push + Telegram) and served at GET /api/desk/morning for the Dashboard.

Everything composes from existing state; this module writes nothing but journal
rows. Times are settings (`desk.*`) so they stay UI-editable and journaled.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .models import Event, RawContent, Signal

ET = ZoneInfo("America/New_York")
log = logging.getLogger("zargar.desk")


def _prev_close_utc(now: dt.datetime | None = None) -> dt.datetime:
    """The most recent 16:00 ET before now — 'overnight' starts there."""
    now_et = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et <= close:
        close -= dt.timedelta(days=1)
    while close.weekday() >= 5:                    # weekend: back to Friday
        close -= dt.timedelta(days=1)
    return close.astimezone(dt.timezone.utc)


class DeskService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.last_report: dict | None = None       # served instantly after compose

    # ------------------------------------------------------------- watchdog
    async def roll_watchdog(self) -> dict:
        out: list[dict] = []
        for tid, runner in (getattr(self.engine, "plan_runners", None) or {}).items():
            try:
                out.extend(await runner.roll_stale())
            except Exception:
                log.exception("roll watchdog failed for %s", tid)
        if out:
            log.warning("roll watchdog acted on %d plan(s): %s", len(out),
                        ", ".join(f"{x['symbol']}({'rolled' if x['rolled'] else x['status']})"
                                  for x in out))
        return {"acted": len(out), "plans": out}

    # ------------------------------------------------------------- soak
    async def soak_nightly(self) -> dict:
        from .tools.soak_report import collect
        out = await collect(self.engine, 30)
        # persistence is the scheduler's ScheduledJobRan row (result payload)
        return out

    async def _latest_job_result(self, job: str) -> dict | None:
        from .scheduler import SCHEDULED_JOB_RAN
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Event.payload).where(Event.type == SCHEDULED_JOB_RAN)
                .order_by(Event.ts.desc()).limit(100))).scalars().all()
        for p in rows:
            if (p or {}).get("job") == job:
                return p.get("result") if isinstance(p.get("result"), dict) else None
        return None

    # ------------------------------------------------------------- composer
    async def morning_report(self) -> dict:
        eng = self.engine
        since = _prev_close_utc()
        now = dt.datetime.now(dt.timezone.utc)

        # -- needs you: pending proposals (fail-closed ones called out) --------
        pending = []
        if getattr(eng, "proposals", None) is not None:
            try:
                pending = await eng.proposals.list_pending()
            except Exception:
                log.exception("morning: proposals unavailable")
        from .signals.sources import resolve_policy
        analyst_on = bool(eng.settings.get("techniques.tip.analyst_enabled", True))
        needs_props = []
        for p in pending:
            ctx = p.get("context") or {}
            src = ctx.get("sourceName")
            verdict = (ctx.get("analyst") or {}).get("verdict")
            fail_closed = (analyst_on and not verdict
                           and resolve_policy(eng.settings, src).mode == "auto")
            needs_props.append({
                "id": p.get("id"), "symbol": p.get("symbol"), "source": src,
                "qty": p.get("qty"), "limitPrice": p.get("limitPrice"),
                "expiresAt": p.get("expiresAt"),
                "verdict": verdict,
                "failClosed": fail_closed,
                "why": ("the analyst produced no verdict — auto-approve failed CLOSED"
                        if fail_closed else
                        f"analyst said {verdict}" if verdict else "awaiting your call"),
            })

        # -- needs you: plans flagged / needing attention ----------------------
        attention = []
        armed_by_technique: dict[str, dict] = {}
        for tid, runner in (getattr(eng, "plan_runners", None) or {}).items():
            counts = {"armed": 0, "paused": 0, "inTrade": 0}
            for ap in list(getattr(runner, "_armed", {}).values()):
                if ap.status == "armed":
                    counts["armed"] += 1
                elif ap.status == "paused":
                    counts["paused"] += 1
                if any(t.remaining > 0 for t in ap.trades.values()):
                    counts["inTrade"] += 1
                try:
                    reasons = ap._attention_reasons()
                except Exception:
                    reasons = []
                if reasons:
                    attention.append({"runId": ap.run_id, "symbol": ap.symbol,
                                      "technique": tid, "reasons": reasons})
            armed_by_technique[tid] = counts

        # -- follow-up flags journaled overnight (a "close"/"update_stop" from
        #    the source against a still-waiting plan) --------------------------
        # a run is "still waiting" only if some runner holds it armed/paused —
        # follow-up flags for plans since disarmed are history, not homework
        live_runs: set[str] = set()
        for runner in (getattr(eng, "plan_runners", None) or {}).values():
            for ap in getattr(runner, "_armed", {}).values():
                if ap.status in ("armed", "paused"):
                    live_runs.add(ap.run_id)
        async with eng.sf() as session:
            follow = (await session.execute(
                select(Event.payload).where(
                    Event.type == "TechniquePlanError", Event.ts >= since))).scalars().all()
            seen_runs: dict[str, dict] = {}
            for p in follow:
                if not str((p or {}).get("error", "")).startswith("source follow-up"):
                    continue
                rid = str((p or {}).get("runId") or "")
                if rid and rid not in live_runs:
                    continue                     # already disarmed — not homework
                # one row per plan, latest note wins (eva reposts stop updates)
                seen_runs[rid or f"?{len(seen_runs)}"] = {
                    "symbol": (p or {}).get("symbol"),
                    "note": str((p or {}).get("error"))[:160], "runId": rid or None}
            follow_ups = list(seen_runs.values())
            rolls = (await session.execute(
                select(Event.payload).where(
                    Event.type == "TechniquePlanRolled", Event.ts >= since))).scalars().all()
            overnight_rows = (await session.execute(
                select(Signal).where(Signal.created_at >= since)
                .order_by(Signal.created_at.asc()))).scalars().all()
            from .signals.service import experiment_tag
            overnight = [{"ticker": r.ticker, "source": r.source_name,
                          "status": r.status, "action": r.action,
                          "at": r.created_at.isoformat() if r.created_at else None,
                          "id": r.id}
                         for r in overnight_rows
                         if experiment_tag(r.extraction) is None]   # research batches are not tips
            from sqlalchemy import func
            err_content = int((await session.execute(
                select(func.count()).select_from(RawContent)
                .where(RawContent.status == "error"))).scalar_one())

        report = {
            "date": now.astimezone(ET).strftime("%Y-%m-%d"),
            "generatedAt": now.isoformat(),
            "needsYou": {
                "pendingProposals": needs_props,
                "failClosedCount": sum(1 for x in needs_props if x["failClosed"]),
                "attention": attention,
                "followUps": follow_ups,
            },
            "overnight": {"tips": overnight,
                          "counts": _count_by(overnight, "status")},
            "today": {
                "armedByTechnique": armed_by_technique,
                "rolled": [{"symbol": (p or {}).get("symbol"),
                            "to": (p or {}).get("to"),
                            "runId": (p or {}).get("runId")} for p in rolls],
                "rollWatchdog": await self._latest_job_result("roll_watchdog"),
            },
            "soak": await self._latest_job_result("soak_nightly"),
            "intake": {
                "errorContent": err_content,
                # since-boot resilience tally (POST-SOAK 4.4)
                **(getattr(getattr(eng, "signals_service", None), "counters", None) or {}),
                "analystApiRetries": _analyst_retries(),
            },
        }
        self.last_report = report
        return report

    # ------------------------------------------------------------- ledger
    async def ledger(self, days: int = 30) -> dict:
        """The plain-language money view (user 2026-09-01: 'what was bought,
        what was sold, how much gain each time'). REAL books only (sim/live/
        paper) — research books never. Round trips are FIFO-paired per
        (book, symbol) from executions; book corrections (PortfolioAdjusted)
        appear as their own rows so the ledger reconciles to the dollar."""
        from sqlalchemy import select

        from .models import Event, Execution, Order
        eng = self.engine
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        # follow the workspace, like the Dashboard headline: practice = sim
        # books; live = the real accounts (research/shadow books never)
        live_ws = str(eng.settings.get("trading.mode", "practice")) == "live"
        kinds = ("live", "paper") if live_ws else ("sim",)
        real = {p["id"]: p for p in eng.positions.portfolios()
                if p["kind"] in kinds}
        async with eng.sf() as session:
            rows = (await session.execute(
                select(Execution, Order.technique, Order.source, Order.tags)
                .join(Order, Order.id == Execution.order_id)
                .where(Execution.portfolio_id.in_(list(real)))
                .order_by(Execution.ts.asc()))).all()
            adj_rows = (await session.execute(
                select(Event).where(Event.type == "PortfolioAdjusted",
                                    Event.ts >= cutoff))).scalars().all()

        def label(tech, src, tags):
            tip_src = next((str(t).split(":", 1)[1] for t in (tags or [])
                            if str(t).startswith("source:")), None)
            if tech == "tip" or tip_src:
                return f"tip · {tip_src}" if tip_src else "tip"
            if tech:
                return tech.replace("enhanced_market", "EM Options")
            return {"signal": "approved tip", "auto": "auto", "technique": "technique"}.get(src, src)

        trips: list[dict] = []
        open_lots: dict[tuple, list[dict]] = {}
        for e, tech, src, tags in rows:
            mult = 100.0 if len(e.symbol) > 10 else 1.0
            lots = open_lots.setdefault((e.portfolio_id, e.symbol), [])
            qty, px = float(e.qty), float(e.price)
            sgn = 1.0 if e.side == "BUY" else -1.0
            while qty > 1e-9 and lots and lots[0]["sgn"] != sgn:
                lot = lots[0]
                take = min(qty, lot["qty"])
                gain = (px - lot["px"]) * take * mult * lot["sgn"]
                trips.append({
                    "symbol": e.symbol, "secType": ("OPT" if mult > 1 else "STK"),
                    "qty": take, "portfolio": real[e.portfolio_id]["name"],
                    "inPrice": lot["px"], "outPrice": px,
                    "inAt": lot["ts"].isoformat(), "outAt": e.ts.isoformat(),
                    "cost": round(lot["px"] * take * mult, 2),
                    "gain": round(gain, 2),
                    "short": lot["sgn"] < 0,
                    "label": lot["label"],
                    "day": e.ts.astimezone(ET).strftime("%Y-%m-%d"),
                })
                lot["qty"] -= take
                qty -= take
                if lot["qty"] <= 1e-9:
                    lots.pop(0)
            if qty > 1e-9:
                lots.append({"sgn": sgn, "qty": qty, "px": px, "ts": e.ts,
                             "label": label(tech, src, tags)})

        open_positions = []
        for (pid, sym), lots in open_lots.items():
            for lot in lots:
                mult = 100.0 if len(sym) > 10 else 1.0
                q = eng.quotes.get(sym)
                mark = float(q.last) if q is not None and q.last and q.last > 0 else None
                open_positions.append({
                    "symbol": sym, "qty": lot["qty"] * lot["sgn"],
                    "portfolio": real[pid]["name"],
                    "inPrice": lot["px"], "inAt": lot["ts"].isoformat(),
                    "cost": round(lot["px"] * lot["qty"] * mult, 2),
                    "mark": mark,
                    "unrealized": (round((mark - lot["px"]) * lot["qty"] * mult * lot["sgn"], 2)
                                   if mark else None),
                    "label": lot["label"],
                })

        adjustments = [{
            "day": a.ts.astimezone(ET).strftime("%Y-%m-%d"), "at": a.ts.isoformat(),
            "amount": round(float((a.payload or {}).get("cashDelta") or 0), 2),
            "reason": str((a.payload or {}).get("reason") or "book correction")[:200],
        } for a in adj_rows]

        window_trips = [t for t in trips
                        if dt.datetime.fromisoformat(t["outAt"]) >= cutoff]
        day_keys = sorted({t["day"] for t in window_trips}
                          | {a["day"] for a in adjustments}, reverse=True)
        days_out = [{
            "date": d,
            "realized": round(sum(t["gain"] for t in window_trips if t["day"] == d)
                              + sum(a["amount"] for a in adjustments if a["day"] == d), 2),
            "trips": [t for t in window_trips if t["day"] == d],
            "adjustments": [a for a in adjustments if a["day"] == d],
        } for d in day_keys]

        equity = 0.0
        for pid in real:
            with contextlib.suppress(Exception):
                equity += float(await eng.positions.equity(pid) or 0)
        return {
            "asOf": dt.datetime.now(dt.timezone.utc).isoformat(),
            "windowDays": days,
            "total": round(equity, 2),
            "startingCash": round(sum(float(p.get("startingCash") or 0)
                                      for p in real.values()), 2),
            "realized": round(sum(t["gain"] for t in window_trips)
                              + sum(a["amount"] for a in adjustments), 2),
            "openValue": round(sum(x["cost"] for x in open_positions), 2),
            "days": days_out,
            "open": open_positions,
        }

    # ------------------------------------------------------------- delivery
    async def morning_send(self) -> dict:
        """Compose + deliver the short form (push + Telegram). The long form is
        the Dashboard card reading GET /api/desk/morning."""
        r = await self.morning_report()
        ny = r["needsYou"]
        lines = []
        if ny["pendingProposals"]:
            fc = ny["failClosedCount"]
            lines.append(f"{len(ny['pendingProposals'])} proposal(s) waiting"
                         + (f" — {fc} fail-closed (analyst gave no verdict)" if fc else ""))
        if ny["followUps"]:
            lines.append(f"{len(ny['followUps'])} plan(s) flagged by source follow-ups")
        if ny["attention"]:
            lines.append(f"{len(ny['attention'])} plan(s) need attention")
        if not lines:
            lines.append("nothing needs you")
        armed = sum(c.get("armed", 0) for c in r["today"]["armedByTechnique"].values())
        tips_n = len(r["overnight"]["tips"])
        body = (" · ".join(lines)
                + f"\nOvernight: {tips_n} tip(s). Today: {armed} plan(s) armed"
                + (f", {len(r['today']['rolled'])} rolled" if r["today"]["rolled"] else "")
                + ".")
        title = f"Zargar morning — {r['date']}"
        sent = {"push": False, "telegram": False}
        push = getattr(self.engine, "push", None)
        if push is not None:
            try:
                await push.send(title, body, url="/dashboard", tag="desk-morning")
                sent["push"] = True
            except Exception:
                log.exception("morning push failed")
        tg = getattr(self.engine, "telegram", None)
        if tg is not None:
            try:
                from .approvals.telegram import open_keyboard
                from .push import public_url
                await tg.send(f"☀ {title}\n{body}",
                              open_keyboard(public_url(self.engine.settings), "/dashboard"))
                sent["telegram"] = True
            except Exception:
                log.exception("morning telegram failed")
        return {"sent": sent, "title": title, "body": body,
                "needsYou": len(ny["pendingProposals"]) + len(ny["attention"]) + len(ny["followUps"])}

    async def morning_send_scheduled(self) -> dict:
        """The scheduler's entry: 'runs late rather than never' is right for the
        watchdog and the soak, but an EVENING deploy must not fire a 'morning'
        push (found live 2026-08-31: registering after 08:25 pushed at night).
        Past the cutoff we compose only — the Dashboard card stays fresh."""
        now_et = dt.datetime.now(ET)
        cutoff = str(self.engine.settings.get("desk.morning_push_until", "10:30"))
        try:
            hh, mm = (int(x) for x in cutoff.split(":"))
        except ValueError:
            hh, mm = 10, 30
        if now_et.hour * 60 + now_et.minute > hh * 60 + mm:
            r = await self.morning_report()
            ny = r["needsYou"]
            return {"sent": {"push": False, "telegram": False}, "skippedLate": True,
                    "needsYou": (len(ny["pendingProposals"]) + len(ny["attention"])
                                 + len(ny["followUps"]))}
        return await self.morning_send()


def _analyst_retries() -> int:
    try:
        from .techniques.tip.analyst import API_RETRIES
        return int(API_RETRIES["n"])
    except Exception:  # pragma: no cover - counter is best-effort telemetry
        return 0


def _count_by(rows: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        out[str(r.get(key))] = out.get(str(r.get(key)), 0) + 1
    return out


def attach_desk(engine) -> DeskService:
    """Wire the desk jobs into the engine scheduler (idempotent)."""
    desk = DeskService(engine)
    engine.desk = desk
    s = engine.settings
    engine.scheduler.register("roll_watchdog", str(s.get("desk.roll_watchdog_at", "09:00")),
                              desk.roll_watchdog)
    engine.scheduler.register("soak_nightly", str(s.get("desk.soak_at", "17:30")),
                              desk.soak_nightly)
    if bool(s.get("desk.morning_push", True)):
        engine.scheduler.register("morning_report", str(s.get("desk.morning_at", "08:25")),
                                  desk.morning_send_scheduled)
    return desk
