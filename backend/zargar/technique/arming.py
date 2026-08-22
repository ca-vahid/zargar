"""Phase 2 — arm a session plan for live triggers, with execution (walk-forward plan §9).

The book's "set alerts above and below key levels" (p. 117), done by the
machine — and, when the user asks for it, traded by the machine:

    armed plan ──1m bars──▶ TriggerTracker (same object the walk-forward uses)
        │ fires only inside the R6 prime windows; mid-day touches are logged
        ▼
    fire ──▶ optional vision critic ──▶ setup row ──▶ execution mode:
        alert     : setup + journal only
        proposal  : practice proposal (user approves; RiskGate on approval)
        auto      : entry order now via OrderManager.place() (RiskGate inside),
                    then the position is *managed* on bars: 30/40/15 trims at
                    the targets, stop, and a flatten before the close
                    (day trader — nothing held overnight)

Everything is write-ahead and journaled against the plan run: arm / pause /
resume / disarm, every touch that was skipped and why, every order intent and
its result, every fill, every exit, every error and retry. The armed state is
persisted (`technique_armed`) so a restart re-arms today's plans and the
dashboard can always say what it is watching, what it wants to do, and what
happened. No new order path exists: every order goes through
`OrderManager.place()` → `RiskGate.evaluate()`, and the kill switch is honoured
before any submission.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from .. import bus as topics
from .. import events as ev
from ..domain import Bar, new_id
from ..models import TechniqueArmed, TechniqueSetup
from .analysis import facts_for_prompt
from .plans import analysis_from_trigger
from .rulebook import ET, PRIME_WINDOWS, session_bounds, session_date, session_window
from .setups import LADDER_TRIMS
from .volume import build_profile
from .walkforward import TriggerTracker

log = logging.getLogger("zargar.technique.arming")

MODES = ("alert", "proposal", "auto")
TRANSIENT_ERRORS = ("timeout", "connection", "temporarily", "rate limit", "503", "502", "unavailable")


@dataclass
class ArmConfig:
    portfolio_id: str
    mode: str = "proposal"           # alert | proposal | auto
    risk_pct: float = 0.5            # % of equity risked per trade (R1: 0.5-1 %)
    max_qty: float = 100.0           # hard cap on shares per entry
    qty: float | None = None         # fixed size instead of risk sizing
    use_critic: bool = True
    allow_live: bool = False         # explicit acknowledgement for auto mode on a live portfolio
    flatten_minutes_before_close: int = 5
    slippage_pct: float = 0.1        # entry limit = trigger price * (1 + slippage)
    max_retries: int = 2

    def to_dict(self) -> dict:
        return {"portfolioId": self.portfolio_id, "mode": self.mode, "riskPct": self.risk_pct,
                "maxQty": self.max_qty, "qty": self.qty, "useCritic": self.use_critic,
                "allowLive": self.allow_live, "flattenMinutesBeforeClose": self.flatten_minutes_before_close,
                "slippagePct": self.slippage_pct, "maxRetries": self.max_retries}

    @classmethod
    def from_dict(cls, d: dict) -> "ArmConfig":
        return cls(portfolio_id=str(d.get("portfolioId") or d.get("portfolio_id") or ""),
                   mode=str(d.get("mode") or "proposal"),
                   risk_pct=float(d.get("riskPct", d.get("risk_pct", 0.5)) or 0.5),
                   max_qty=float(d.get("maxQty", d.get("max_qty", 100)) or 100),
                   qty=(float(d["qty"]) if d.get("qty") else None),
                   use_critic=bool(d.get("useCritic", d.get("use_critic", True))),
                   allow_live=bool(d.get("allowLive", d.get("allow_live", False))),
                   flatten_minutes_before_close=int(d.get("flattenMinutesBeforeClose", d.get("flatten_minutes_before_close", 5)) or 5),
                   slippage_pct=float(d.get("slippagePct", d.get("slippage_pct", 0.1)) or 0.1),
                   max_retries=int(d.get("maxRetries", d.get("max_retries", 2)) or 2))


@dataclass
class Trade:
    """One fired trigger's execution lifecycle (auto mode), or the record of
    what alert/proposal mode did."""
    trigger_id: str
    kind: str
    fired_ts: int
    window: str
    entry: float
    stop: float
    targets: list[float]
    status: str = "fired"       # fired | critic_killed | alert | proposal | submitting | working | open |
    #                             closed | cancelled | failed | skipped
    reason: str = ""
    setup_id: str | None = None
    proposal_id: str | None = None
    entry_order_id: str | None = None
    limit_price: float | None = None
    qty: float = 0.0
    filled_qty: float = 0.0
    avg_fill: float | None = None
    remaining: float = 0.0
    trims_done: int = 0
    exit_order_ids: list[str] = field(default_factory=list)
    exits: list[dict] = field(default_factory=list)     # {kind: tp1|tp2|tp3|stop|flatten|disarm, qty, orderId, price?}
    realized_pnl: float = 0.0
    last_price: float | None = None
    errors: list[str] = field(default_factory=list)
    retries: int = 0
    opened_ts: int | None = None
    closed_ts: int | None = None
    fire_bar_index: int | None = None
    critic: dict | None = None

    @property
    def open(self) -> bool:
        return self.status in ("working", "open")

    def to_dict(self) -> dict:
        risk = max(self.entry - self.stop, 1e-9)
        unreal = ((self.last_price - (self.avg_fill or self.entry)) * self.remaining
                  if self.last_price is not None and self.remaining > 0 and self.avg_fill else 0.0)
        return {"triggerId": self.trigger_id, "kind": self.kind, "firedTs": self.fired_ts, "window": self.window,
                "entry": self.entry, "stop": self.stop, "targets": self.targets, "status": self.status,
                "reason": self.reason, "setupId": self.setup_id, "proposalId": self.proposal_id,
                "entryOrderId": self.entry_order_id, "limitPrice": self.limit_price, "qty": self.qty,
                "filledQty": self.filled_qty, "avgFill": self.avg_fill, "remaining": self.remaining,
                "trimsDone": self.trims_done, "exits": list(self.exits), "realizedPnl": round(self.realized_pnl, 2),
                "unrealizedPnl": round(unreal, 2), "realizedR": round(self.realized_pnl / (risk * self.filled_qty), 3)
                if self.filled_qty else None, "lastPrice": self.last_price, "errors": list(self.errors),
                "retries": self.retries, "openedTs": self.opened_ts, "closedTs": self.closed_ts,
                "critic": self.critic}


@dataclass
class ArmedPlan:
    run_id: str
    symbol: str
    plan: dict
    plan_for: str
    config: ArmConfig
    trackers: dict[str, TriggerTracker]
    armed_at: float
    status: str = "armed"               # armed | paused | expired | disarmed
    bar_index: int = 0
    last_bar_ts: int | None = None
    trades: dict[str, Trade] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    stale: bool = False
    stale_noted: bool = False
    setup_ids: dict[str, str] = field(default_factory=dict)

    def to_dict(self, *, portfolio: dict | None = None, quote=None, now_ms: int | None = None) -> dict:
        now_ms = now_ms or int(time.time() * 1000)
        last = float(quote.last) if quote is not None and quote.last > 0 else None
        prime_now = session_window(now_ms)
        trig = []
        for tid, tr in self.trackers.items():
            d = {"id": tid, "kind": tr.kind, "status": tr.status, "entry": tr.entry, "stop": tr.stop,
                 "targets": [t["price"] for t in tr.trigger.get("targets") or []],
                 "riskReward": tr.trigger.get("riskReward"), "firedTs": tr.fired_ts, "firedWindow": tr.fired_window,
                 "observedMidday": len(tr.observed_midday), "skipped": tr.skipped[-3:],
                 "conditions": tr.trigger.get("conditions"), "setupId": self.setup_ids.get(tid)}
            if last:
                d["distancePct"] = round((tr.entry - last) / last * 100, 3)
                d["distance"] = round(tr.entry - last, 4)
            d["windowOpenNow"] = prime_now in PRIME_WINDOWS
            trig.append(d)
        open_trades = [t for t in self.trades.values() if t.open]
        return {
            "runId": self.run_id, "symbol": self.symbol, "planFor": self.plan_for, "status": self.status,
            "config": self.config.to_dict(),
            "portfolio": ({k: portfolio.get(k) for k in ("id", "name", "kind", "venue", "baseCurrency")} if portfolio else
                          {"id": self.config.portfolio_id}),
            "armedAt": dt.datetime.fromtimestamp(self.armed_at, dt.timezone.utc).isoformat(),
            "barsSeen": self.bar_index, "lastBarTs": self.last_bar_ts,
            "barAgeSeconds": (round((now_ms - self.last_bar_ts) / 1000) if self.last_bar_ts else None),
            "stale": self.stale, "sessionWindowNow": prime_now, "lastPrice": last,
            "quoteAgeSeconds": (round((now_ms - quote.ts) / 1000) if quote is not None else None),
            "triggers": trig,
            "trades": [t.to_dict() for t in self.trades.values()],
            "openPositions": len(open_trades),
            "realizedPnl": round(sum(t.realized_pnl for t in self.trades.values()), 2),
            "fired": [t.to_dict() for t in self.trades.values()],   # back-compat for the rail
            "events": self.events[-40:],
            "summary": self._summary(prime_now, last),
        }

    def _summary(self, window_now: str, last: float | None) -> str:
        if self.status == "paused":
            return "paused — watching, not firing"
        if self.status in ("expired", "disarmed"):
            return self.status
        if self.stale:
            return "STALE DATA — not firing until bars resume"
        opens = [t for t in self.trades.values() if t.open]
        if opens:
            t = opens[0]
            return f"in trade {t.trigger_id}: {t.remaining:g} left, stop {t.stop:.2f}, next target " \
                   f"{t.targets[t.trims_done]:.2f}" if t.trims_done < len(t.targets) else f"in trade {t.trigger_id}: runner {t.remaining:g}"
        waiting = [tid for tid, tr in self.trackers.items() if tr.status in ("waiting", "observed")]
        if not waiting:
            return "nothing left to watch"
        nearest = None
        if last:
            nearest = min(((abs(self.trackers[t].entry - last) / last * 100, t) for t in waiting), default=None)
        w = "prime window open" if window_now in PRIME_WINDOWS else f"{window_now}: watching only"
        return (f"watching {len(waiting)} trigger(s) · nearest {nearest[1]} {nearest[0]:.2f}% away · {w}"
                if nearest else f"watching {len(waiting)} trigger(s) · {w}")


class PlanArmer:
    def __init__(self, engine, technique) -> None:
        self.engine = engine
        self.technique = technique
        self._armed: dict[str, ArmedPlan] = {}
        self._task: asyncio.Task | None = None
        self._orders_task: asyncio.Task | None = None
        self._auto_task: asyncio.Task | None = None
        self._auto_done: set[tuple[str, str]] = set()
        self._order_index: dict[str, tuple[str, str]] = {}   # order id -> (run_id, trigger id)

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._bar_loop(), name="technique-armer")
        if self._orders_task is None:
            self._orders_task = asyncio.create_task(self._orders_loop(), name="technique-armer-orders")
        if self._auto_task is None:
            self._auto_task = asyncio.create_task(self._auto_loop(), name="technique-armer-auto")

    async def stop(self) -> None:
        for name in ("_task", "_orders_task", "_auto_task"):
            t = getattr(self, name)
            if t:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
                setattr(self, name, None)

    async def restore(self) -> int:
        """Re-arm today's persisted plans after a restart (armed/paused only)."""
        today = session_date(int(time.time() * 1000))
        async with self.engine.sf() as session:
            rows = (await session.execute(select(TechniqueArmed).where(
                TechniqueArmed.status.in_(("armed", "paused"))))).scalars().all()
        n = 0
        for row in rows:
            if row.plan_for != today:
                async with self.engine.sf() as session:
                    r2 = await session.get(TechniqueArmed, row.run_id)
                    if r2 is not None:
                        r2.status = "expired"
                        await session.commit()
                continue
            try:
                await self.arm(row.run_id, ArmConfig.from_dict(row.config or {}), restored=True,
                               paused=(row.status == "paused"))
                n += 1
            except Exception as exc:
                log.warning("re-arm %s failed: %s", row.run_id, exc)
        return n

    # ---------------------------------------------------------------- queries
    def armed(self) -> list[dict]:
        return [self._snapshot(a) for a in self._armed.values()]

    def get(self, run_id: str) -> ArmedPlan | None:
        return self._armed.get(run_id)

    def detail(self, run_id: str) -> dict | None:
        ap = self._armed.get(run_id)
        return self._snapshot(ap) if ap else None

    def _snapshot(self, ap: ArmedPlan) -> dict:
        return ap.to_dict(portfolio=self.engine.positions.portfolio(ap.config.portfolio_id),
                          quote=self.engine.quotes.get(ap.symbol))

    # ---------------------------------------------------------------- config validation
    def validate_config(self, cfg: ArmConfig) -> dict:
        s = self.engine.settings
        if cfg.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        pid = cfg.portfolio_id or str(s.get("technique.arm.default_portfolio", "")) or str(s.get("trading.default_portfolio", ""))
        portfolio = self.engine.positions.portfolio(pid) if pid else None
        if portfolio is None:
            sims = [p for p in self.engine.positions.portfolios() if p["kind"] == "sim"]
            if cfg.mode == "alert" and sims:
                portfolio = sims[0]
            else:
                raise ValueError("portfolio (account) is required — pick the account this plan trades in")
        cfg.portfolio_id = portfolio["id"]
        if cfg.mode == "auto" and portfolio["kind"] in ("live", "paper"):
            if not bool(s.get("technique.arm.allow_live_auto", False)):
                raise ValueError("auto execution on a live/paper account is disabled "
                                 "(technique.arm.allow_live_auto)")
            if not cfg.allow_live:
                raise ValueError("auto execution on a live/paper account needs the explicit acknowledgement (allowLive)")
            if str(s.get("trading.mode", "practice")) != "live":
                raise ValueError("trading.mode is 'practice' — live accounts are blocked; switch to live first")
        if cfg.risk_pct <= 0 or cfg.risk_pct > float(s.get("technique.max_risk_pct", 5.0)):
            raise ValueError(f"riskPct must be in (0, {s.get('technique.max_risk_pct', 5.0)}] (R1)")
        if cfg.max_qty <= 0:
            raise ValueError("maxQty must be > 0")
        return portfolio

    # ---------------------------------------------------------------- arm / disarm
    async def arm(self, run_id: str, config: ArmConfig | dict | None = None, *, restored: bool = False,
                  paused: bool = False) -> dict:
        if not bool(self.engine.settings.get("technique.arm.enabled", True)):
            raise RuntimeError("technique.arm.enabled is off")
        if run_id in self._armed:
            return self._snapshot(self._armed[run_id])
        run = await self.technique.get_run(run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        plan = (run.get("result") or {}).get("plan")
        if run.get("mode") != "plan" or not plan:
            raise ValueError("only plan runs (mode=plan) can be armed")
        s = self.engine.settings
        cfg = config if isinstance(config, ArmConfig) else ArmConfig.from_dict({
            "portfolioId": str(s.get("technique.arm.default_portfolio", "")) or str(s.get("trading.default_portfolio", "")),
            "mode": str(s.get("technique.arm.mode", "proposal")), "riskPct": s.get("technique.arm.risk_pct", 0.5),
            "maxQty": s.get("technique.arm.max_qty", 100), "useCritic": s.get("technique.arm.use_critic", True),
            "flattenMinutesBeforeClose": s.get("technique.arm.flatten_minutes_before_close", 5),
            "slippagePct": s.get("technique.arm.slippage_pct", 0.1), "maxRetries": s.get("technique.arm.max_retries", 2),
            **(config or {})})
        portfolio = self.validate_config(cfg)
        symbol = run["symbol"]
        enforce = bool(s.get("technique.enforce_session_windows", True))
        t = self.technique.thresholds()
        profile = None
        with contextlib.suppress(Exception):
            snap = await self.technique.load_bars_snapshot(run_id)
            if snap and snap.get(plan.get("triggerTf") or "1m"):
                profile = build_profile(snap[plan.get("triggerTf") or "1m"])
        trackers = {tg["id"]: TriggerTracker(tg, t, profile, enforce, True, float(plan.get("lastClose") or 0) or None)
                    for tg in plan.get("triggers") or [] if tg.get("valid")}
        ap = ArmedPlan(run_id=run_id, symbol=symbol, plan=plan, plan_for=plan.get("planFor") or "",
                       config=cfg, trackers=trackers, armed_at=time.time(),
                       status="paused" if paused else "armed")
        self._armed[run_id] = ap
        with contextlib.suppress(Exception):
            await self.engine.ensure_symbol(symbol)
        seeded = 0
        try:
            todays = [b for b in self.engine.bars.bars(symbol, "1m", limit=2000, include_forming=False)
                      if session_date(b.ts) == ap.plan_for]
            for b in todays:
                await self._on_bar(ap, b, journal=False)
                seeded += 1
        except Exception:
            log.exception("seeding armed plan failed")
        await self._persist(ap)
        self._log(ap, "armed" if not restored else "restored", f"{cfg.mode} mode on {portfolio['name']} ({portfolio['kind']})",
                  seededBars=seeded)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ARMED, {
            "runId": run_id, "symbol": symbol, "planFor": ap.plan_for, "triggers": list(trackers),
            "seededBars": seeded, "enforceWindows": enforce, "config": cfg.to_dict(),
            "portfolio": {k: portfolio.get(k) for k in ("id", "name", "kind", "venue")}, "restored": restored},
            aggregate_type="technique_run", aggregate_id=run_id, portfolio_id=cfg.portfolio_id)
        self.start()
        self._publish(ap, "armed")
        return self._snapshot(ap)

    async def pause(self, run_id: str) -> dict:
        ap = self._armed.get(run_id)
        if ap is None:
            raise KeyError("not armed")
        if ap.status == "armed":
            ap.status = "paused"
            self._log(ap, "paused", "no new fires; open positions keep being managed")
            await self._persist(ap)
            await self.engine.journal.append(ev.TECHNIQUE_PLAN_PAUSED, {"runId": run_id, "symbol": ap.symbol},
                                             aggregate_type="technique_run", aggregate_id=run_id)
            self._publish(ap, "paused")
        return self._snapshot(ap)

    async def resume(self, run_id: str) -> dict:
        ap = self._armed.get(run_id)
        if ap is None:
            raise KeyError("not armed")
        if ap.status == "paused":
            ap.status = "armed"
            self._log(ap, "resumed", "firing enabled again")
            await self._persist(ap)
            await self.engine.journal.append(ev.TECHNIQUE_PLAN_RESUMED, {"runId": run_id, "symbol": ap.symbol},
                                             aggregate_type="technique_run", aggregate_id=run_id)
            self._publish(ap, "resumed")
        return self._snapshot(ap)

    async def disarm(self, run_id: str, *, reason: str = "manual", flatten: bool = False) -> bool:
        ap = self._armed.get(run_id)
        if ap is None:
            return False
        # cancel working entries; optionally flatten open positions
        for tr in ap.trades.values():
            if tr.status == "working" and tr.entry_order_id:
                with contextlib.suppress(Exception):
                    await self.engine.orders.cancel(tr.entry_order_id)
                tr.status = "cancelled"
                tr.reason = f"disarmed ({reason})"
                self._log(ap, "entry_cancelled", f"{tr.trigger_id}: working entry cancelled on disarm")
            elif tr.status == "open" and flatten and tr.remaining > 0:
                await self._exit(ap, tr, "disarm", tr.remaining, journal=True)
        ap.status = "disarmed"
        self._armed.pop(run_id, None)
        await self._persist(ap)
        self._log(ap, "disarmed", reason)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_DISARMED, {
            "runId": run_id, "symbol": ap.symbol, "reason": reason, "flatten": flatten,
            "fired": len(ap.trades), "openLeft": sum(1 for t in ap.trades.values() if t.open),
            "statuses": {tid: tr.status for tid, tr in ap.trackers.items()}},
            aggregate_type="technique_run", aggregate_id=run_id, portfolio_id=ap.config.portfolio_id)
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "disarmed", "runId": run_id, "reason": reason,
                                                   "armed": self._snapshot(ap)})
        return True

    async def stop_all(self, *, flatten: bool = False, reason: str = "stop all") -> int:
        n = 0
        for rid in list(self._armed):
            if await self.disarm(rid, reason=reason, flatten=flatten):
                n += 1
        return n

    async def arm_today(self, symbol: str, config: dict | None = None, *, with_vision: bool | None = None) -> dict:
        """Build today's plan (as of just before the open) and arm it."""
        today = session_date(int(time.time() * 1000))
        open_ms, _ = session_bounds(today)
        run = await self.technique.analyze(symbol, as_of_ms=open_ms - 1000, trigger="arm", plan=True,
                                           with_vision=with_vision, wait=True)
        if run.get("status") != "done":
            raise RuntimeError(f"plan build failed: {run.get('error')}")
        return await self.arm(run["id"], config)

    # ---------------------------------------------------------------- persistence / audit
    async def _persist(self, ap: ArmedPlan) -> None:
        try:
            async with self.engine.sf() as session:
                row = await session.get(TechniqueArmed, ap.run_id)
                state = {"trackers": {tid: {"status": tr.status, "firedTs": tr.fired_ts, "firedWindow": tr.fired_window,
                                            "skipped": tr.skipped[-5:], "observedMidday": len(tr.observed_midday)}
                                      for tid, tr in ap.trackers.items()},
                         "trades": [t.to_dict() for t in ap.trades.values()],
                         "events": ap.events[-60:], "barsSeen": ap.bar_index, "lastBarTs": ap.last_bar_ts,
                         "realizedPnl": round(sum(t.realized_pnl for t in ap.trades.values()), 2)}
                if row is None:
                    row = TechniqueArmed(run_id=ap.run_id, symbol=ap.symbol, plan_for=ap.plan_for,
                                         portfolio_id=ap.config.portfolio_id, mode=ap.config.mode,
                                         config=ap.config.to_dict(), status=ap.status, state=state)
                    session.add(row)
                else:
                    row.status = ap.status
                    row.config = ap.config.to_dict()
                    row.portfolio_id = ap.config.portfolio_id
                    row.mode = ap.config.mode
                    row.state = state
                    row.updated_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
        except Exception:
            log.exception("persisting armed plan failed")

    def _log(self, ap: ArmedPlan, what: str, text: str, **detail) -> dict:
        rec = {"ts": int(time.time() * 1000), "event": what, "text": text, **detail}
        ap.events.append(rec)
        if len(ap.events) > 400:
            del ap.events[:-400]
        return rec

    async def audit(self, run_id: str, *, limit: int = 200) -> list[dict]:
        """Journal events for this plan run (arm/fire/orders/exits/errors), newest last."""
        from ..models import Event
        async with self.engine.sf() as session:
            rows = (await session.execute(select(Event).where(Event.aggregate_id == run_id)
                                          .order_by(Event.id.desc()).limit(limit))).scalars().all()
        out = [{"id": e.id, "ts": e.ts.isoformat() if e.ts else None, "type": e.type, "payload": e.payload}
               for e in rows]
        # orders raised by this plan carry their own aggregate; pull them in too
        oids = [oid for oid, (rid, _) in self._order_index.items() if rid == run_id]
        if oids:
            async with self.engine.sf() as session:
                orows = (await session.execute(select(Event).where(Event.aggregate_id.in_(oids))
                                               .order_by(Event.id.desc()).limit(limit))).scalars().all()
            out += [{"id": e.id, "ts": e.ts.isoformat() if e.ts else None, "type": e.type, "payload": e.payload,
                     "orderId": e.aggregate_id} for e in orows]
        out.sort(key=lambda x: x["id"])
        return out

    # ---------------------------------------------------------------- bar / order loops
    async def _bar_loop(self) -> None:
        async with self.engine.bus.subscription(topics.BARS) as q:
            while True:
                msg = await q.get()
                try:
                    if msg.get("tf") != "1m":
                        continue
                    bar: Bar = msg.get("bar")
                    sym = msg.get("symbol")
                    for ap in [a for a in self._armed.values() if a.symbol == sym and a.status in ("armed", "paused")]:
                        await self._on_bar(ap, bar, journal=True)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("armed plan bar handling failed")

    async def _orders_loop(self) -> None:
        async with self.engine.bus.subscription(topics.ORDERS) as q:
            while True:
                msg = await q.get()
                try:
                    await self.on_order_update(msg)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("armed plan order handling failed")

    async def on_order_update(self, o: dict) -> None:
        key = self._order_index.get(o.get("id"))
        if not key:
            return
        run_id, tid = key
        ap = self._armed.get(run_id)
        if ap is None:
            return
        tr = ap.trades.get(tid)
        if tr is None:
            return
        status = o.get("status")
        if o["id"] == tr.entry_order_id:
            if status in ("FILLED", "PARTIALLY_FILLED"):
                new_filled = float(o.get("filledQty") or 0)
                if new_filled > tr.filled_qty:
                    tr.filled_qty = new_filled
                    tr.avg_fill = o.get("avgFillPrice")
                    tr.remaining = tr.filled_qty - sum(float(x.get("filledQty") or 0) for x in tr.exits)
                    if tr.status != "open":
                        tr.status = "open"
                        tr.opened_ts = int(time.time() * 1000)
                        self._log(ap, "position_open", f"{tid}: filled {tr.filled_qty:g} @ {tr.avg_fill}",
                                  trigger=tid, qty=tr.filled_qty, avgFill=tr.avg_fill)
                        await self.engine.journal.append(ev.TECHNIQUE_PLAN_POSITION_OPENED, {
                            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "orderId": o["id"],
                            "qty": tr.filled_qty, "avgFill": tr.avg_fill, "stop": tr.stop, "targets": tr.targets},
                            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
                    await self._persist(ap)
                    self._publish(ap, "position_open")
            elif status in ("REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED") and tr.status in ("submitting", "working"):
                if tr.filled_qty > 0:
                    tr.status = "open"           # partial then cancel: manage what we have
                else:
                    tr.status = "cancelled" if status in ("CANCELLED", "EXPIRED") else "failed"
                    tr.reason = o.get("rejectReason") or status
                    self._log(ap, "entry_" + status.lower(), f"{tid}: entry {status} {tr.reason}", trigger=tid)
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "stage": "entry", "status": status,
                        "reason": tr.reason, "orderId": o["id"]},
                        aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
                await self._persist(ap)
                self._publish(ap, "entry_" + status.lower())
        elif o["id"] in tr.exit_order_ids:
            x = next((e for e in tr.exits if e.get("orderId") == o["id"]), None)
            if x is None:
                return
            if status in ("FILLED", "PARTIALLY_FILLED"):
                fq = float(o.get("filledQty") or 0)
                prev = float(x.get("filledQty") or 0)
                if fq > prev:
                    x["filledQty"] = fq
                    x["price"] = o.get("avgFillPrice")
                    if tr.avg_fill and x.get("price") is not None:
                        tr.realized_pnl += (float(x["price"]) - float(tr.avg_fill)) * (fq - prev)
                    tr.remaining = max(0.0, tr.filled_qty - sum(float(e.get("filledQty") or 0) for e in tr.exits))
                    self._log(ap, "exit_fill", f"{tid}: {x['kind']} filled {fq:g} @ {x.get('price')}, {tr.remaining:g} left",
                              trigger=tid, kind=x["kind"], qty=fq, price=x.get("price"))
                    if tr.remaining <= 1e-9 and tr.status != "closed":
                        tr.status = "closed"
                        tr.closed_ts = int(time.time() * 1000)
                        self._log(ap, "position_closed", f"{tid}: closed, realized {tr.realized_pnl:+.2f}",
                                  trigger=tid, realizedPnl=round(tr.realized_pnl, 2))
                        await self.engine.journal.append(ev.TECHNIQUE_PLAN_POSITION_CLOSED, {
                            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "realizedPnl": round(tr.realized_pnl, 2),
                            "exits": tr.exits, "avgFill": tr.avg_fill, "qty": tr.filled_qty},
                            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
                    await self._persist(ap)
                    self._publish(ap, "exit_fill")
            elif status in ("REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED"):
                x["status"] = status
                x["error"] = o.get("rejectReason")
                tr.errors.append(f"exit {x['kind']} {status}: {o.get('rejectReason') or ''}")
                self._log(ap, "exit_failed", f"{tid}: exit {x['kind']} {status} {o.get('rejectReason') or ''}", trigger=tid)
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                    "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "stage": f"exit:{x['kind']}",
                    "status": status, "reason": o.get("rejectReason"), "orderId": o["id"]},
                    aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
                await self._persist(ap)
                self._publish(ap, "exit_failed")

    async def on_bar(self, run_id: str, bar: Bar) -> dict | None:
        """Feed one closed bar by hand (tests / replays)."""
        ap = self._armed.get(run_id)
        if ap is None:
            return None
        await self._on_bar(ap, bar, journal=True)
        return self._snapshot(ap)

    async def _on_bar(self, ap: ArmedPlan, bar: Bar, *, journal: bool) -> None:
        if session_date(bar.ts) != ap.plan_for:
            return
        if ap.last_bar_ts is not None and bar.ts <= ap.last_bar_ts:
            return
        ap.last_bar_ts = bar.ts
        ap.stale = False
        idx = ap.bar_index
        ap.bar_index += 1
        _, close_ms = session_bounds(ap.plan_for)
        halted = bool(getattr(self.engine.halt, "engaged", False))
        # 1) manage open positions first (exits never wait on anything)
        for tr in ap.trades.values():
            if tr.status == "open" and tr.remaining > 0:
                tr.last_price = bar.close
                await self._manage(ap, tr, bar, close_ms, journal=journal)
            elif tr.status == "working" and tr.fire_bar_index is not None and tr.entry_order_id:
                # entry not filled within the entry window -> cancel (T4.1: do not chase)
                if idx - tr.fire_bar_index > self.technique.thresholds().plan_entry_window_bars:
                    with contextlib.suppress(Exception):
                        await self.engine.orders.cancel(tr.entry_order_id)
                    tr.status = "cancelled"
                    tr.reason = "entry window elapsed without a fill (T4.1: not chased)"
                    self._log(ap, "entry_cancelled", f"{tr.trigger_id}: {tr.reason}", trigger=tr.trigger_id)
                    if journal:
                        await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tr.trigger_id,
                            "event": "entry_window_elapsed", "reason": tr.reason},
                            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
        # 2) triggers
        for tid, tr in ap.trackers.items():
            if tr.status in ("fired", "gapped_past", "gapped_through", "gap_void", "expired"):
                continue
            before = tr.status
            n_obs, n_skip = len(tr.observed_midday), len(tr.skipped)
            st = tr.on_bar(bar, idx)
            changed = st != before or len(tr.observed_midday) != n_obs or len(tr.skipped) != n_skip
            if changed and st != "fired":
                what = st if st != before else ("observed_midday" if len(tr.observed_midday) != n_obs else "skipped")
                reason = (tr.skipped[-1]["reason"] if what == "skipped" and tr.skipped else what)
                self._log(ap, what, f"{tid}: {reason}", trigger=tid, window=session_window(bar.ts), close=bar.close)
                if journal:
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": what, "ts": bar.ts,
                        "window": session_window(bar.ts), "close": bar.close, "reason": reason},
                        aggregate_type="technique_run", aggregate_id=ap.run_id)
                    self._publish(ap, what)
            if st == "fired" and before != "fired":
                if ap.status == "paused":
                    tr.status = "observed"           # keep watching; a paused plan never fires
                    tr.fired_index = tr.fired_ts = tr.fired_window = tr.fill_price = None
                    self._log(ap, "paused_skip", f"{tid}: conditions met but the plan is paused", trigger=tid)
                    if journal:
                        await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "paused", "ts": bar.ts},
                            aggregate_type="technique_run", aggregate_id=ap.run_id)
                    continue
                if halted:
                    tr.status = "observed"
                    tr.fired_index = tr.fired_ts = tr.fired_window = tr.fill_price = None
                    self._log(ap, "halt_skip", f"{tid}: conditions met but the kill switch is engaged", trigger=tid)
                    if journal:
                        await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "halt", "ts": bar.ts},
                            aggregate_type="technique_run", aggregate_id=ap.run_id)
                    continue
                await self._fire(ap, tid, tr, bar, idx, journal=journal)
        # 3) end of session
        if bar.ts >= close_ms - 60_000:
            ap.status = "expired"
            for tr in ap.trackers.values():
                tr.finish()
            if journal:
                await self.disarm(ap.run_id, reason="session closed")
        elif journal:
            await self._persist(ap)

    # ---------------------------------------------------------------- fire -> execute
    async def _fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, bar: Bar, idx: int, *, journal: bool) -> None:
        window = session_window(bar.ts)
        cfg = ap.config
        trade = Trade(trigger_id=tid, kind=tr.kind, fired_ts=bar.ts, window=window, entry=float(tr.fill_price or tr.entry),
                      stop=tr.stop, targets=[float(t["price"]) for t in tr.trigger.get("targets") or []][:3],
                      fire_bar_index=idx, last_price=bar.close)
        ap.trades[tid] = trade
        self._log(ap, "fired", f"{tid} {tr.kind} fired at {trade.entry:.2f} ({window})", trigger=tid, window=window)
        a = analysis_from_trigger(tr.trigger, ap.symbol, session_window=window)
        critic = None
        llm = self.technique.llm_config()
        trace: list[dict] = []
        if cfg.use_critic and llm.available and journal:
            try:
                from .analysis import AnalysisRequest, compute_facts
                from .render import render_chart
                from .vision import VisionPipeline
                bars = self.engine.bars.bars(ap.symbol, "1m", limit=600, include_forming=False)
                req = AnalysisRequest(symbol=ap.symbol, primary_tf="1m", context_tfs=(), thresholds=self.technique.thresholds())
                facts = compute_facts(req, {"1m": bars}, []) if bars else {}
                png = render_chart(bars[-240:], title=f"{ap.symbol} 1m", tf="1m") if bars else None
                vp = VisionPipeline(self.technique._get_client(), llm, thresholds=self.technique.thresholds(),
                                    max_passes=2, trace=trace)
                critic = await vp.run_critic(a, {"1m": png} if png else {}, facts_for_prompt(facts) if facts else "")
            except Exception as exc:
                log.warning("live critic failed: %s", exc)
                trace.append({"stage": "critic", "step": "error", "reason": str(exc)})
                self._log(ap, "critic_error", f"{tid}: critic failed ({exc}); continuing without it", trigger=tid)
        trade.critic = critic and {k: critic.get(k) for k in ("kill", "summary", "violations")}
        contract = a.to_contract()
        # setup row (always, so the run shows what fired)
        if journal:
            try:
                await self.technique._persist_setup(ap.run_id, ap.symbol, a, contract, None, grounded=True)
                setups = (await self.technique.get_run(ap.run_id) or {}).get("setups") or []
                if setups:
                    trade.setup_id = setups[-1]["id"]
                    ap.setup_ids[tid] = trade.setup_id
            except Exception:
                log.exception("persisting fired setup failed")
        if journal:
            await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_FIRED, {
                "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "kind": tr.kind, "window": window,
                "fill": tr.fill_price, "entry": tr.entry, "stop": tr.stop, "targets": trade.targets,
                "verdictAfterCritic": a.verdict, "confidence": round(a.confidence, 3), "critic": trade.critic,
                "setupId": trade.setup_id, "mode": cfg.mode, "portfolioId": cfg.portfolio_id, "trace": trace},
                aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        if a.verdict != "setup":
            trade.status = "critic_killed"
            trade.reason = (critic or {}).get("summary") or "critic killed"
            self._log(ap, "critic_killed", f"{tid}: {trade.reason}", trigger=tid)
            await self._persist(ap)
            self._publish(ap, "critic_killed")
            return
        # execution mode
        if cfg.mode == "alert" or not journal:
            trade.status = "alert"
            trade.reason = "alert mode: setup recorded, nothing sent"
        elif cfg.mode == "proposal":
            pid = None
            try:
                setup_row = await self._setup_row(trade.setup_id)
                if setup_row is not None:
                    pid = await self.technique._emit_proposal(setup_row, a, portfolio_id=cfg.portfolio_id,
                                                              risk_pct=cfg.risk_pct, max_qty=cfg.max_qty,
                                                              fixed_qty=cfg.qty)
            except Exception as exc:
                log.exception("proposal emission failed")
                trade.errors.append(f"proposal: {exc}")
            trade.proposal_id = pid
            trade.status = "proposal" if pid else "failed"
            trade.reason = "practice proposal created — approve it in Signals" if pid else "no proposal could be created"
            self._log(ap, "proposal" if pid else "proposal_failed", f"{tid}: {trade.reason}", trigger=tid, proposalId=pid)
        else:
            await self._enter(ap, trade, tr, journal=journal)
        await self._persist(ap)
        self._publish(ap, "fired")
        if journal and self.technique.chat:
            run = await self.technique.get_run(ap.run_id)
            if run and run.get("threadId"):
                with contextlib.suppress(Exception):
                    await self.technique.chat.append_message(
                        run["threadId"], "assistant",
                        [{"type": "text", "text": (
                            f"**Trigger {tid} fired** at {dt.datetime.fromtimestamp(bar.ts / 1000, ET):%H:%M} ET "
                            f"({window}) — {tr.kind} at {trade.entry:.2f}, stop {tr.stop:.2f}; mode {cfg.mode}: {trade.status}"
                            + (f" — {trade.reason}" if trade.reason else "")
                            + (f"; critic: {'KILLED' if a.verdict != 'setup' else 'survived'} — {critic.get('summary')}"
                               if critic else ""))}],
                        {"kind": "plan_trigger", "runId": ap.run_id, "trigger": tid}, run_id=ap.run_id)

    async def _setup_row(self, setup_id: str | None):
        if not setup_id:
            return None
        async with self.engine.sf() as session:
            return await session.get(TechniqueSetup, setup_id)

    async def _size(self, ap: ArmedPlan, trade: Trade) -> float:
        cfg = ap.config
        if cfg.qty:
            return float(min(cfg.qty, cfg.max_qty))
        equity = await self.engine.positions.equity(cfg.portfolio_id)
        per_share = max(trade.entry - trade.stop, 0.01)
        qty = int(max(0, equity * cfg.risk_pct / 100 / per_share))
        return float(min(qty, cfg.max_qty))

    async def _enter(self, ap: ArmedPlan, trade: Trade, tr: TriggerTracker, *, journal: bool) -> None:
        """Auto mode: place the entry order (write-ahead: intent journaled first;
        OrderManager journals the risk verdict and routing)."""
        from ..orders import OrderIntent
        cfg = ap.config
        qty = await self._size(ap, trade)
        if qty < 1:
            trade.status = "skipped"
            trade.reason = "size rounds to 0 shares at this risk % — not sent"
            self._log(ap, "skipped", f"{trade.trigger_id}: {trade.reason}", trigger=trade.trigger_id)
            return
        limit = round(trade.entry * (1 + cfg.slippage_pct / 100), 2)
        trade.qty = qty
        trade.limit_price = limit
        trade.status = "submitting"
        intent = OrderIntent(portfolio_id=cfg.portfolio_id, symbol=ap.symbol, side="BUY", qty=qty,
                             order_type="LMT", limit_price=limit, tif="DAY", source="technique")
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ORDER_INTENT, {
            "runId": ap.run_id, "symbol": ap.symbol, "trigger": trade.trigger_id, "side": "BUY", "qty": qty,
            "limitPrice": limit, "entry": trade.entry, "stop": trade.stop, "targets": trade.targets,
            "portfolioId": cfg.portfolio_id, "riskPct": cfg.risk_pct},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        self._log(ap, "entry_submit", f"{trade.trigger_id}: BUY {qty:g} LMT {limit:.2f}", trigger=trade.trigger_id)
        result = await self._place_with_retry(ap, trade, intent, stage="entry")
        if result is None:
            return
        trade.entry_order_id = result.get("id")
        if trade.entry_order_id:
            self._order_index[trade.entry_order_id] = (ap.run_id, trade.trigger_id)
        status = result.get("status")
        if status in ("REJECTED_RISK", "REJECTED"):
            trade.status = "failed"
            trade.reason = result.get("rejectReason") or status
            trade.errors.append(trade.reason)
            self._log(ap, "entry_rejected", f"{trade.trigger_id}: {trade.reason}", trigger=trade.trigger_id)
            await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                "runId": ap.run_id, "symbol": ap.symbol, "trigger": trade.trigger_id, "stage": "entry",
                "status": status, "reason": trade.reason, "orderId": trade.entry_order_id},
                aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        elif status in ("FILLED", "PARTIALLY_FILLED"):
            await self.on_order_update(result)
        else:
            trade.status = "working"
            self._log(ap, "entry_working", f"{trade.trigger_id}: order {trade.entry_order_id[:8]} {status}",
                      trigger=trade.trigger_id, orderId=trade.entry_order_id)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ORDER_RESULT, {
            "runId": ap.run_id, "symbol": ap.symbol, "trigger": trade.trigger_id, "stage": "entry",
            "orderId": trade.entry_order_id, "status": status, "reason": result.get("rejectReason")},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)

    async def _place_with_retry(self, ap: ArmedPlan, trade: Trade, intent, *, stage: str) -> dict | None:
        """Submit through OrderManager; retry only transient transport errors
        (never a risk rejection), journaling every attempt."""
        cfg = ap.config
        attempt = 0
        while True:
            try:
                return await self.engine.orders.place(intent)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                transient = any(k in msg.lower() for k in TRANSIENT_ERRORS)
                trade.errors.append(f"{stage}: {msg}")
                attempt += 1
                trade.retries = attempt
                self._log(ap, f"{stage}_error", f"{trade.trigger_id}: {msg}" + (" — retrying" if transient and attempt <= cfg.max_retries else ""),
                          trigger=trade.trigger_id, attempt=attempt)
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                    "runId": ap.run_id, "symbol": ap.symbol, "trigger": trade.trigger_id, "stage": stage,
                    "error": msg, "attempt": attempt, "retrying": transient and attempt <= cfg.max_retries},
                    aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
                if transient and attempt <= cfg.max_retries:
                    await asyncio.sleep(min(2.0 * attempt, 5.0))
                    continue
                if stage == "entry":
                    trade.status = "failed"
                    trade.reason = msg
                await self._persist(ap)
                self._publish(ap, f"{stage}_error")
                return None

    async def _manage(self, ap: ArmedPlan, tr: Trade, bar: Bar, close_ms: int, *, journal: bool) -> None:
        """Exits on closed bars: stop first (conservative), then the 30/40/15
        ladder, then a flatten before the close. One exit per bar per trade."""
        if not journal:
            return
        pending = any(e.get("status") in (None, "SUBMITTED", "ACCEPTED", "working") and not e.get("filledQty")
                      for e in tr.exits if e.get("orderId"))
        if pending:
            return                                  # wait for the working exit to resolve
        flatten_at = close_ms - ap.config.flatten_minutes_before_close * 60_000
        if bar.low <= tr.stop:
            await self._exit(ap, tr, "stop", tr.remaining, journal=True)
            return
        if bar.ts >= flatten_at:
            await self._exit(ap, tr, "flatten", tr.remaining, journal=True)
            return
        if tr.trims_done < len(tr.targets) and bar.high >= tr.targets[tr.trims_done]:
            k = tr.trims_done
            share = LADDER_TRIMS[k] if k < len(LADDER_TRIMS) else 1.0
            qty = float(int(round(tr.filled_qty * share)))
            qty = min(qty, tr.remaining)
            if k == len(tr.targets) - 1 and tr.remaining - qty < 1:
                qty = tr.remaining          # no fractional runner left behind
            if qty >= 1:
                await self._exit(ap, tr, f"tp{k + 1}", qty, journal=True)
            tr.trims_done += 1

    async def _exit(self, ap: ArmedPlan, tr: Trade, kind: str, qty: float, *, journal: bool) -> None:
        from ..orders import OrderIntent
        qty = float(int(qty))
        if qty < 1 or tr.remaining <= 0:
            return
        cfg = ap.config
        intent = OrderIntent(portfolio_id=cfg.portfolio_id, symbol=ap.symbol, side="SELL", qty=qty,
                             order_type="MKT", tif="DAY", source="technique")
        rec = {"kind": kind, "qty": qty, "orderId": None, "status": None, "filledQty": 0.0, "price": None,
               "ts": int(time.time() * 1000)}
        tr.exits.append(rec)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_EXIT, {
            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tr.trigger_id, "kind": kind, "qty": qty,
            "remainingBefore": tr.remaining, "stop": tr.stop, "targets": tr.targets},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        self._log(ap, "exit_submit", f"{tr.trigger_id}: {kind} SELL {qty:g} MKT", trigger=tr.trigger_id, kind=kind)
        result = await self._place_with_retry(ap, tr, intent, stage=f"exit:{kind}")
        if result is None:
            rec["status"] = "ERROR"
            return
        rec["orderId"] = result.get("id")
        rec["status"] = result.get("status")
        if rec["orderId"]:
            tr.exit_order_ids.append(rec["orderId"])
            self._order_index[rec["orderId"]] = (ap.run_id, tr.trigger_id)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ORDER_RESULT, {
            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tr.trigger_id, "stage": f"exit:{kind}",
            "orderId": rec["orderId"], "status": rec["status"], "reason": result.get("rejectReason")},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        if rec["status"] in ("REJECTED", "REJECTED_RISK"):
            rec["error"] = result.get("rejectReason")
            tr.errors.append(f"exit {kind}: {rec['error']}")
            self._log(ap, "exit_failed", f"{tr.trigger_id}: {kind} rejected — {rec['error']}", trigger=tr.trigger_id)
        elif rec["status"] in ("FILLED", "PARTIALLY_FILLED"):
            await self.on_order_update(result)
        await self._persist(ap)
        self._publish(ap, "exit_submit")

    # ---------------------------------------------------------------- housekeeping
    def _publish(self, ap: ArmedPlan, what: str) -> None:
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "armed", "event": what, "armed": self._snapshot(ap)})

    async def _auto_loop(self) -> None:
        """Auto-arm configured symbols at the open; mark stale plans; publish a
        heartbeat snapshot every minute so the dashboard's numbers stay live."""
        await asyncio.sleep(20)
        while True:
            try:
                s = self.engine.settings
                stale_s = int(s.get("technique.arm.stale_seconds", 180))
                now = dt.datetime.now(ET)
                now_ms = int(time.time() * 1000)
                in_session = now.weekday() < 5 and (9 * 60 + 30) <= now.hour * 60 + now.minute < 16 * 60
                for ap in list(self._armed.values()):
                    if in_session and ap.plan_for == now.strftime("%Y-%m-%d") and ap.last_bar_ts \
                            and now_ms - ap.last_bar_ts > stale_s * 1000 and not ap.stale:
                        ap.stale = True
                        self._log(ap, "stale", f"no closed bar for {stale_s}s — not firing until data resumes")
                        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                            "runId": ap.run_id, "symbol": ap.symbol, "stage": "data", "error": "stale bars",
                            "lastBarTs": ap.last_bar_ts}, aggregate_type="technique_run", aggregate_id=ap.run_id)
                    if ap.status in ("armed", "paused"):
                        self._publish(ap, "heartbeat")
                syms = [str(x).upper() for x in s.get("technique.arm.auto_symbols", [])]
                if syms and bool(s.get("technique.arm.enabled", True)):
                    today = now.strftime("%Y-%m-%d")
                    if now.weekday() < 5 and (9 * 60 + 20) <= now.hour * 60 + now.minute < 16 * 60:
                        for sym in syms:
                            if (sym, today) in self._auto_done or any(a.symbol == sym and a.plan_for == today
                                                                      for a in self._armed.values()):
                                continue
                            self._auto_done.add((sym, today))
                            try:
                                await self.arm_today(sym)
                            except Exception as exc:
                                log.warning("auto-arm %s failed: %s", sym, exc)
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("armer housekeeping error")
                await asyncio.sleep(60)
