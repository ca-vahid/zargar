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
from ..execution import SessionListener
from ..execution.book import EXIT_LADDER, EXIT_REPRICE_BARS
from ..execution.exits import (
    plan_exit,
    premium_stop_breach,
    quote_stop_breach,
    reduce_only_exit_intent,
    stale_working_exit,
)
from ..models import TechniqueArmed, TechniqueSetup
from .analysis import facts_for_prompt
from .plans import analysis_from_trigger
from .rulebook import ET, PRIME_WINDOWS, session_bounds, session_date, session_window
from .volume import build_profile
from .walkforward import TriggerTracker, score_trigger

log = logging.getLogger("zargar.technique.arming")

MODES = ("alert", "proposal", "auto")
TRANSIENT_ERRORS = ("timeout", "connection", "temporarily", "rate limit", "503", "502", "unavailable")


@dataclass
class ArmConfig:
    portfolio_id: str
    mode: str = "proposal"           # alert | proposal | auto
    instrument: str = "options"      # options (the book: just-OTM weekly / 0DTE, T5) | shares
    contracts: int | None = 1        # options: fixed contracts (R5 one-contract rule); None = size by risk %
    max_contracts: int = 5           # options: hard cap per entry
    single_contract_exit: str = "tp2"  # options with < 3 contracts: exit everything at this target
    risk_pct: float = 0.5            # % of equity risked per trade (R1: 0.5-1 %, 5 % hard cap)
    max_qty: float = 100.0           # shares: hard cap per entry
    qty: float | None = None         # shares: fixed size instead of risk sizing
    use_critic: bool = True
    allow_live: bool = False         # explicit acknowledgement for auto mode on a live portfolio
    flatten_minutes_before_close: int = 5
    slippage_pct: float = 0.1        # shares: entry limit = trigger price * (1 + slippage)
    max_retries: int = 2
    max_open_trades: int = 1         # how many positions this plan may hold at once (R5 spirit)
    daily_loss_limit: float = 0.0    # $ realised loss that stops the plan (flatten + disarm); 0 = off
    skip_wide_spread: bool = True    # options: skip the entry if T5.4 warns the contract spread is wide
    skip_elevated_iv: bool = False   # options: skip the entry if T5.3 warns IV is elevated (IV-crush risk)

    def to_dict(self) -> dict:
        return {"portfolioId": self.portfolio_id, "mode": self.mode, "instrument": self.instrument,
                "contracts": self.contracts, "maxContracts": self.max_contracts,
                "singleContractExit": self.single_contract_exit, "riskPct": self.risk_pct,
                "maxQty": self.max_qty, "qty": self.qty, "useCritic": self.use_critic,
                "allowLive": self.allow_live, "flattenMinutesBeforeClose": self.flatten_minutes_before_close,
                "slippagePct": self.slippage_pct, "maxRetries": self.max_retries,
                "maxOpenTrades": self.max_open_trades, "dailyLossLimit": self.daily_loss_limit,
                "skipWideSpread": self.skip_wide_spread, "skipElevatedIv": self.skip_elevated_iv}

    @classmethod
    def from_dict(cls, d: dict) -> "ArmConfig":
        return cls(portfolio_id=str(d.get("portfolioId") or d.get("portfolio_id") or ""),
                   mode=str(d.get("mode") or "proposal"),
                   instrument=str(d.get("instrument") or "options"),
                   contracts=(int(d["contracts"]) if d.get("contracts") not in (None, "", 0) else
                              (None if "contracts" in d and d.get("contracts") in (None, "") else 1)),
                   max_contracts=int(d.get("maxContracts", d.get("max_contracts", 5)) or 5),
                   single_contract_exit=str(d.get("singleContractExit", d.get("single_contract_exit", "tp2")) or "tp2"),
                   risk_pct=float(d.get("riskPct", d.get("risk_pct", 0.5)) or 0.5),
                   max_qty=float(d.get("maxQty", d.get("max_qty", 100)) or 100),
                   qty=(float(d["qty"]) if d.get("qty") else None),
                   use_critic=bool(d.get("useCritic", d.get("use_critic", True))),
                   allow_live=bool(d.get("allowLive", d.get("allow_live", False))),
                   flatten_minutes_before_close=int(d.get("flattenMinutesBeforeClose", d.get("flatten_minutes_before_close", 5)) or 5),
                   slippage_pct=float(d.get("slippagePct", d.get("slippage_pct", 0.1)) or 0.1),
                   max_retries=int(d.get("maxRetries", d.get("max_retries", 2)) or 2),
                   max_open_trades=int(d.get("maxOpenTrades", d.get("max_open_trades", 1)) or 1),
                   daily_loss_limit=float(d.get("dailyLossLimit", d.get("daily_loss_limit", 0.0)) or 0.0),
                   skip_wide_spread=bool(d.get("skipWideSpread", d.get("skip_wide_spread", True))),
                   skip_elevated_iv=bool(d.get("skipElevatedIv", d.get("skip_elevated_iv", False))))


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
    instrument: str = "shares"           # shares | options
    contract: dict | None = None         # options: the picked contract (OCC symbol, strike, expiry, bid/ask, ...)
    order_symbol: str | None = None      # what was actually bought (OCC symbol for options)
    multiplier: float = 1.0              # 100 for options
    single_exit: str = "tp2"             # options with < 3 contracts: exit everything at this target

    @property
    def open(self) -> bool:
        return self.status in ("working", "open")

    @property
    def sec_type(self) -> str:
        """What the shared exit planner reads to pick LMT-at-bid vs MKT."""
        return "OPT" if self.instrument == "options" else "STK"

    @property
    def pending_exit_qty(self) -> float:
        """Shares/contracts already committed to a working (un-resolved) exit —
        never send another exit for these (avoids overselling)."""
        total = 0.0
        for e in self.exits:
            st = e.get("status")
            if st in ("REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED", "ERROR", "FILLED"):
                continue
            total += float(e.get("qty") or 0) - float(e.get("filledQty") or 0)
        return max(0.0, total)

    def to_dict(self) -> dict:
        risk = max(self.entry - self.stop, 1e-9)
        if self.instrument == "options":
            # unrealised in $ from the contract's own quote is not tracked here; show premium at risk
            unreal = 0.0
        else:
            unreal = ((self.last_price - (self.avg_fill or self.entry)) * self.remaining
                      if self.last_price is not None and self.remaining > 0 and self.avg_fill else 0.0)
        return {"triggerId": self.trigger_id, "kind": self.kind, "firedTs": self.fired_ts, "window": self.window,
                "instrument": self.instrument, "contract": self.contract, "orderSymbol": self.order_symbol,
                "multiplier": self.multiplier,
                "entry": self.entry, "stop": self.stop, "targets": self.targets, "status": self.status,
                "reason": self.reason, "setupId": self.setup_id, "proposalId": self.proposal_id,
                "entryOrderId": self.entry_order_id, "limitPrice": self.limit_price, "qty": self.qty,
                "filledQty": self.filled_qty, "avgFill": self.avg_fill, "remaining": self.remaining,
                "trimsDone": self.trims_done, "exits": list(self.exits), "realizedPnl": round(self.realized_pnl, 2),
                "unrealizedPnl": round(unreal, 2),
                "realizedR": (round(self.realized_pnl / (risk * self.filled_qty), 3)
                              if self.filled_qty and self.instrument != "options" else None),
                "premiumPaid": (round((self.avg_fill or 0) * self.filled_qty * self.multiplier, 2)
                                if self.instrument == "options" and self.filled_qty else None),
                "lastPrice": self.last_price, "errors": list(self.errors),
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
    stop_reason: str = ""               # why the plan stopped firing (loss halt, etc.)
    scorecard: dict | None = None       # execution review vs the walk-forward replay (after close)
    replay_ts: int | None = None        # while seeding historical bars: stamp events with the BAR's time

    def _attention_reasons(self) -> list[str]:
        """Human sentences for anything that needs a person: a failed exit with the
        position still open, an entry that half-filled then errored, stale data
        while holding. Empty list = all clear."""
        probs: list[str] = []
        for t in self.trades.values():
            last_exit = t.exits[-1] if t.exits else None
            if t.remaining > 0 and last_exit and last_exit.get("status") in ("ERROR", "REJECTED", "REJECTED_RISK"):
                probs.append(f"{t.trigger_id}: exit {last_exit.get('kind')} failed — {t.remaining:g} still held")
            if t.status == "failed" and t.filled_qty > 0 and t.remaining > 0:
                probs.append(f"{t.trigger_id}: entry errored after a partial fill — {t.remaining:g} held unmanaged")
        if self.stale and any(t.remaining > 0 for t in self.trades.values()):
            probs.append("bar data is stale while a position is open")
        return probs

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
            "stopReason": self.stop_reason, "scorecard": self.scorecard,
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
            "needsAttention": (lambda probs: bool(probs))(self._attention_reasons()),
            "attentionReasons": self._attention_reasons(),
            "fired": [t.to_dict() for t in self.trades.values()],   # back-compat for the rail
            "events": self.events[-200:],   # a full session of touches/skips fits in the day panel
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


class PlanArmer(SessionListener):
    """Arms EnhancedMarket session plans on the shared execution listener. The
    live loops (1m bars, order updates, heartbeat) and the order-id index come
    from `SessionListener`; this class supplies the technique-specific hooks —
    trigger evaluation, the critic, contract picking, sizing — and the exit
    management is the shared reduce-only path in `execution.exits`."""

    def __init__(self, engine, technique) -> None:
        super().__init__(engine, name="technique-armer")
        self.technique = technique
        self._armed: dict[str, ArmedPlan] = {}
        # (run_id, trigger_id[, "~prem"]) -> consecutive quote polls seen in breach
        self._quote_breaches: dict[tuple[str, str], int] = {}
        # (run_id, trigger_id) -> (last retry ts, attempts) for the failed-exit watchdog
        self._exit_retries: dict[tuple[str, str], tuple[float, int]] = {}
        self._auto_done: set[tuple[str, str]] = set()

    # ---------------------------------------------------------------- listener hooks
    async def on_minute_bar(self, symbol, bar) -> None:
        for ap in [a for a in self._armed.values() if a.symbol == symbol and a.status in ("armed", "paused")]:
            await self._on_bar(ap, bar, journal=True)

    async def on_order(self, order: dict) -> None:
        await self.on_order_update(order)

    # ------------------------------------------------------------- quote stop watch
    def quote_watch_seconds(self) -> float:
        try:
            return max(0.05, float(self.engine.settings.get("technique.arm.quote_exit_seconds", 2.0)))
        except (TypeError, ValueError):
            return 2.0

    async def on_quote_watch(self) -> None:
        """Between bar closes, exit an open trade whose *underlying* quote is
        decisively through the stop (`execution.exits.quote_stop_breach`) for
        `technique.arm.quote_exit_polls` consecutive polls (one bad tick is not a
        breach). Safety only: this path can only sell what is already open —
        reduce-only, same `_exit` machinery, journaled with its own reason."""
        s = self.engine.settings
        if not bool(s.get("technique.arm.quote_exit", True)):
            return
        try:
            excess = float(s.get("technique.arm.quote_exit_excess_r", 0.25))
            need = max(1, int(s.get("technique.arm.quote_exit_polls", 2)))
        except (TypeError, ValueError):
            excess, need = 0.25, 2
        max_age = int(s.get("technique.arm.stale_seconds", 180))
        now_ms = int(time.time() * 1000)
        for ap in list(self._armed.values()):
            if ap.status not in ("armed", "paused"):
                continue
            open_trades = [t for t in ap.trades.values() if t.status == "open" and t.remaining > 0]
            if not open_trades:
                continue
            q = self.engine.quotes.get(ap.symbol)
            last = float(q.last) if q is not None and q.last and q.last > 0 else None
            fresh = q is not None and (now_ms - q.ts) <= max_age * 1000
            prem_pct = float(s.get("technique.arm.premium_stop_pct", 50.0) or 0)
            for tr in open_trades:
                # 1) failed-exit watchdog: a position whose exit errored must never
                #    sit un-managed — retry at market every 30s (5 tries), alert once
                last_exit = tr.exits[-1] if tr.exits else None
                if (last_exit and last_exit.get("status") in ("ERROR", "REJECTED", "REJECTED_RISK")
                        and tr.pending_exit_qty <= 1e-9):
                    rkey = (ap.run_id, tr.trigger_id)
                    ts0, attempts = self._exit_retries.get(rkey, (0.0, 0))
                    if attempts < 5 and time.time() - ts0 >= 30.0:
                        self._exit_retries[rkey] = (time.time(), attempts + 1)
                        if attempts == 0:
                            await self._alert(ap, f"{tr.trigger_id}: exit {last_exit.get('kind')} failed "
                                              f"({last_exit.get('error') or last_exit.get('status')}) — "
                                              f"watchdog retrying at market", stage="exit_watchdog")
                        self._log(ap, "exit_retry", f"{tr.trigger_id}: watchdog retry {attempts + 1}/5",
                                  trigger=tr.trigger_id)
                        await self._exit(ap, tr, "stop", tr.remaining, journal=True, force_market=True,
                                         reason=f"watchdog retry {attempts + 1} after failed exit")
                        continue
                    if attempts >= 5 and time.time() - ts0 < 31.0:
                        await self._alert(ap, f"{tr.trigger_id}: exit still failing after 5 retries — "
                                          f"position needs manual attention (Sell now / broker app)",
                                          stage="exit_watchdog")
                        self._exit_retries[rkey] = (time.time() + 1e9, attempts)   # alert once
                        continue
                # 2) premium stop (options): the contract's own price bled too far
                if tr.instrument == "options" and prem_pct > 0 and tr.order_symbol:
                    oq = self.engine.quotes.get(tr.order_symbol)
                    fresh_o = oq is not None and (now_ms - oq.ts) <= max_age * 1000
                    # a fresh quote with no bid means nobody is paying anything — that
                    # IS the worst bleed, not a data gap; only a missing/stale quote is
                    obid = (float(oq.bid) if oq is not None and oq.bid and oq.bid > 0
                            else (0.0 if fresh_o else None))
                    nkey = (ap.run_id, tr.trigger_id + "~noq")
                    if obid is None:
                        miss = self._quote_breaches.get(nkey, 0) + 1
                        self._quote_breaches[nkey] = miss
                        if miss == 150:      # ~5 minutes of consecutive misses at 2s
                            await self._alert(ap, f"{tr.trigger_id}: no live quote for the option "
                                              f"{tr.order_symbol} for ~5 min while holding — the premium stop "
                                              f"is blind; underlying stops still work", level="warning",
                                              stage="option_quote_gap")
                    else:
                        self._quote_breaches.pop(nkey, None)
                    preason = premium_stop_breach(tr, obid, stop_pct=prem_pct)
                    pkey = (ap.run_id, tr.trigger_id + "~prem")
                    if preason is None:
                        self._quote_breaches.pop(pkey, None)
                    else:
                        pn = self._quote_breaches.get(pkey, 0) + 1
                        self._quote_breaches[pkey] = pn
                        if pn >= need:
                            self._quote_breaches.pop(pkey, None)
                            self._log(ap, "premium_stop", f"{tr.trigger_id}: {preason}", trigger=tr.trigger_id)
                            await self._alert(ap, f"{tr.trigger_id}: {preason} — selling at market",
                                              level="warning", stage="premium_stop")
                            await self._exit(ap, tr, "stop", tr.remaining, journal=True, force_market=True,
                                             reason=preason)
                            continue
                # 3) underlying decisively through the stop
                key = (ap.run_id, tr.trigger_id)
                reason = quote_stop_breach(tr, last, excess_r=excess) if (last is not None and fresh) else None
                if reason is None:
                    self._quote_breaches.pop(key, None)
                    continue
                n = self._quote_breaches.get(key, 0) + 1
                self._quote_breaches[key] = n
                if n < need:
                    continue
                self._quote_breaches.pop(key, None)
                self._log(ap, "quote_stop", f"{tr.trigger_id}: {reason} (poll {n}/{need})", trigger=tr.trigger_id)
                await self._exit(ap, tr, "stop", tr.remaining, journal=True, force_market=True,
                                 reason=f"intra-minute quote breach: {reason}")

    async def restore(self) -> int:
        """Re-arm persisted plans after a restart (armed/paused only). A plan for
        today OR a coming session is re-armed — arming Sunday evening for Monday
        must survive a restart; only plans whose session has passed expire."""
        today = session_date(int(time.time() * 1000))
        async with self.engine.sf() as session:
            rows = (await session.execute(select(TechniqueArmed).where(
                TechniqueArmed.status.in_(("armed", "paused"))))).scalars().all()
        n = 0
        for row in rows:
            if (row.plan_for or "") < today:
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
        if cfg.instrument not in ("options", "shares"):
            raise ValueError("instrument must be 'options' or 'shares'")
        if cfg.instrument == "options":
            if cfg.contracts is not None and cfg.contracts < 1:
                raise ValueError("contracts must be >= 1 (or empty to size by risk %)")
            if cfg.max_contracts < 1:
                raise ValueError("maxContracts must be >= 1")
            if cfg.mode in ("auto", "proposal") and not bool(s.get("technique.options.enabled", True)):
                raise ValueError("technique.options.enabled is off — switch the instrument to shares")
            ok, why = self.options_capability(portfolio)
            if cfg.mode == "auto" and not ok:
                raise ValueError(f"this account cannot trade options here: {why}")
        return portfolio

    def options_capability(self, portfolio: dict) -> tuple[bool, str]:
        """Can option orders be routed for this account?"""
        kind, venue = portfolio.get("kind"), portfolio.get("venue")
        if kind in ("sim", "shadow"):
            return True, "simulated fills from the delayed chain"
        if venue == "snaptrade":
            opts = getattr(self.engine, "options", None)
            if opts is None:
                return False, "options service not attached"
            return opts.allows_options(portfolio["id"])
        if venue == "ibkr":
            ib = getattr(self.engine, "ibkr", None)
            return (bool(ib is not None and getattr(ib, "connected", False)),
                    "IBKR gateway connected" if (ib is not None and getattr(ib, "connected", False)) else "IBKR gateway not connected")
        return False, "unknown venue"

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
            "instrument": s.get("technique.arm.instrument", "options"), "contracts": s.get("technique.arm.contracts", 1),
            "maxContracts": s.get("technique.arm.max_contracts", 5),
            "singleContractExit": s.get("technique.arm.single_contract_exit", "tp2"),
            "maxOpenTrades": s.get("technique.arm.max_open_trades", 1),
            "dailyLossLimit": s.get("technique.arm.daily_loss_limit", 0.0),
            "skipWideSpread": s.get("technique.arm.skip_wide_spread", True),
            "skipElevatedIv": s.get("technique.arm.skip_elevated_iv", False),
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
                # Events from replayed history carry the bar's time, not "now" —
                # a 13:03 restart must not relabel the 09:41 refusals.
                ap.replay_ts = b.ts
                await self._on_bar(ap, b, journal=False)
                seeded += 1
        except Exception:
            log.exception("seeding armed plan failed")
        finally:
            ap.replay_ts = None
        if restored:
            with contextlib.suppress(Exception):
                await self._restore_trades(ap)
        await self._persist(ap)
        if cfg.mode == "auto" and float(cfg.daily_loss_limit or 0) <= 0 and not restored:
            eq = 0.0
            with contextlib.suppress(Exception):
                eq = float(await self.engine.positions.equity(cfg.portfolio_id))
            if eq <= 0:
                log.warning("loss-halt derivation skipped for %s: equity unavailable — arming with NO loss halt",
                            run_id)
            if eq > 0:
                cfg.daily_loss_limit = round(eq * cfg.risk_pct / 100 * 2, 2)
                self._log(ap, "loss_halt_default",
                          f"auto mode with no loss halt set — defaulted to ${cfg.daily_loss_limit:,.0f} "
                          f"(2 \u00d7 the per-trade risk of {cfg.risk_pct}% on ${eq:,.0f})")
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
                # cancel any working exit first so the flatten and a stale limit
                # can't both fill (overselling), then sell the rest at market
                for e in tr.exits:
                    if e.get("orderId") and e.get("status") not in ("FILLED", "REJECTED", "REJECTED_RISK",
                                                                     "CANCELLED", "EXPIRED", "ERROR"):
                        with contextlib.suppress(Exception):
                            await self.engine.orders.cancel(e["orderId"])
                        e["status"] = "CANCELLED"
                await self._exit(ap, tr, "disarm", tr.remaining, journal=True, force_market=True)
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

    async def preflight(self, run_id: str, config: ArmConfig | dict | None = None) -> dict:
        """Dry-run the best trigger's entry so the Arm dialog can say — before you
        arm — whether the order would actually pass the risk gate on this account,
        and what it would buy. Costs nothing (no order is placed, no option chain
        is fetched: options are estimated from the trigger price)."""
        run = await self.technique.get_run(run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        plan = (run.get("result") or {}).get("plan") or {}
        s = self.engine.settings
        cfg = config if isinstance(config, ArmConfig) else ArmConfig.from_dict({
            "portfolioId": str(s.get("technique.arm.default_portfolio", "")) or str(s.get("trading.default_portfolio", "")),
            "mode": str(s.get("technique.arm.mode", "proposal")),
            "instrument": s.get("technique.arm.instrument", "options"), **(config or {})})
        # config validation (account, live gate, options capability)
        gate_ok, gate_msg = True, ""
        try:
            portfolio = self.validate_config(cfg)
        except ValueError as exc:
            return {"ok": False, "blocked": str(exc), "checks": [], "size": None}
        symbol = run["symbol"]
        valids = [t for t in (plan.get("triggers") or []) if t.get("valid")]
        best = min(valids, key=lambda t: -(t.get("confidence") or 0)) if valids else None
        if best is None:
            return {"ok": True, "note": "no tradeable trigger in this plan — nothing would fire", "checks": [], "size": None}
        entry = float(best["entry"]["price"])
        stop = float(best["stop"]["price"])
        equity = await self.engine.positions.equity(cfg.portfolio_id)
        from ..orders import OrderIntent
        if cfg.instrument == "shares":
            per_share = max(entry - stop, 0.01)
            qty = float(min(int(max(0, equity * cfg.risk_pct / 100 / per_share)), cfg.max_qty)) if not cfg.qty \
                else float(min(cfg.qty, cfg.max_qty))
            if qty < 1:
                return {"ok": False, "blocked": "position sizes to 0 shares at this risk % / equity", "checks": [],
                        "size": {"shares": 0}}
            intent = OrderIntent(portfolio_id=cfg.portfolio_id, symbol=symbol, sec_type="STK", side="BUY",
                                 qty=qty, order_type="LMT", limit_price=round(entry, 2), dry_run=True, source="technique")
            try:
                res = await self.engine.orders.place(intent)
            except Exception as exc:
                return {"ok": False, "blocked": f"{type(exc).__name__}: {exc}", "checks": [], "size": {"shares": qty}}
            checks = (res.get("risk") or {}).get("checks") or []
            ok = res.get("status") != "REJECTED_RISK"
            return {"ok": ok, "instrument": "shares", "size": {"shares": qty, "entry": entry, "notional": round(qty * entry, 2)},
                    "checks": checks, "account": {"name": portfolio.get("name"), "kind": portfolio.get("kind")},
                    "trigger": best.get("id"), "note": ""}
        # options: estimate (the exact OCC contract is chosen at fire time)
        checks = []
        opt_ok, opt_why = self.options_capability(portfolio)
        checks.append({"name": "options_supported", "passed": opt_ok, "detail": "" if opt_ok else opt_why})
        enabled = bool(s.get("technique.options.enabled", True))
        checks.append({"name": "options_enabled", "passed": enabled,
                       "detail": "" if enabled else "technique.options.enabled is off"})
        n = int(cfg.contracts or 1)
        est_premium = round(max(0.02, entry * 0.02), 2)          # rough: ~2% of spot as a weekly ATM premium
        est_notional = round(est_premium * 100 * n, 2)
        cap = float(s.get("risk.max_option_premium_notional", 1000.0))
        checks.append({"name": "premium_cap_estimate", "passed": est_notional <= cap,
                       "detail": f"≈${est_notional:,.0f} vs per-order cap ${cap:,.0f}" if est_notional > cap else ""})
        pct_cap = float(s.get("risk.max_option_premium_pct", 5.0))
        pct_ok = equity <= 0 or est_notional <= equity * pct_cap / 100
        checks.append({"name": "premium_pct_estimate", "passed": pct_ok,
                       "detail": f"≈${est_notional:,.0f} exceeds {pct_cap:.0f}% of ${equity:,.0f}" if not pct_ok else ""})
        ok = all(c["passed"] for c in checks)
        return {"ok": ok, "instrument": "options",
                "size": {"contracts": n, "estPremium": est_premium, "estNotional": est_notional},
                "checks": checks, "account": {"name": portfolio.get("name"), "kind": portfolio.get("kind")},
                "trigger": best.get("id"),
                "note": "Estimate only — the exact contract (just-OTM call, this Friday/0DTE) and its real premium are chosen when the trigger fires."}

    async def _restore_trades(self, ap: ArmedPlan) -> None:
        """After a restart, rebuild the Trade objects and the order-id index from
        the persisted projection so an open position keeps being managed and its
        fills still find their trade (instead of being orphaned)."""
        async with self.engine.sf() as session:
            row = await session.get(TechniqueArmed, ap.run_id)
        state = (row.state if row else None) or {}
        rebuilt = 0
        for td in state.get("trades") or []:
            tid = td.get("triggerId")
            if not tid:
                continue
            tr = Trade(
                trigger_id=tid, kind=td.get("kind") or "", fired_ts=int(td.get("firedTs") or 0),
                window=td.get("window") or "", entry=float(td.get("entry") or 0), stop=float(td.get("stop") or 0),
                targets=[float(x) for x in (td.get("targets") or [])], status=td.get("status") or "open",
                reason=td.get("reason") or "", setup_id=td.get("setupId"), proposal_id=td.get("proposalId"),
                entry_order_id=td.get("entryOrderId"), limit_price=td.get("limitPrice"),
                qty=float(td.get("qty") or 0), filled_qty=float(td.get("filledQty") or 0),
                avg_fill=td.get("avgFill"), remaining=float(td.get("remaining") or 0),
                trims_done=int(td.get("trimsDone") or 0), exits=list(td.get("exits") or []),
                exit_order_ids=[e.get("orderId") for e in (td.get("exits") or []) if e.get("orderId")],
                realized_pnl=float(td.get("realizedPnl") or 0), instrument=td.get("instrument") or "shares",
                contract=td.get("contract"), order_symbol=td.get("orderSymbol"),
                multiplier=float(td.get("multiplier") or 1.0), opened_ts=td.get("openedTs"),
                closed_ts=td.get("closedTs"), fire_bar_index=None)
            tr.single_exit = ap.config.single_contract_exit
            ap.trades[tid] = tr
            # re-index working entry/exit orders so their updates route back here
            if tr.entry_order_id and tr.status in ("working", "submitting", "open"):
                self.register_order(tr.entry_order_id, (ap.run_id, tid))
            for oid in tr.exit_order_ids:
                self.register_order(oid, (ap.run_id, tid))
            if tid in ap.trackers and tr.status not in ("cancelled", "failed", "skipped"):
                ap.trackers[tid].status = "fired"     # already acted on; don't re-fire live
            rebuilt += 1
        if rebuilt:
            self._log(ap, "restored_trades", f"re-attached {rebuilt} trade(s) after restart", trades=rebuilt)

    def _score_execution(self, ap: ArmedPlan) -> dict | None:
        """After the close, compare what the armer actually did to what the
        deterministic walk-forward replay of the same session says *should* have
        happened — the same check the Validation tab runs, now applied to a live
        run. Answers: did we fire when the model would have? did our fill/exit
        line up? This is the record you review the plan by."""
        try:
            bars = [b for b in self.engine.bars.bars(ap.symbol, "1m", limit=2000, include_forming=False)
                    if session_date(b.ts) == ap.plan_for]
        except Exception:
            bars = []
        if not bars and ap.trackers:
            # bars fed straight to the trackers (tests / replays don't go through the aggregator)
            fed = getattr(next(iter(ap.trackers.values())), "_bars", None) or []
            bars = [b for b in fed if session_date(b.ts) == ap.plan_for]
        if not bars:
            return None
        rows = []
        theo_fires = actual_fires = matched = 0
        theo_sum_r = 0.0
        for tid, tracker in ap.trackers.items():
            theo = score_trigger(tracker, bars)
            sim = theo.get("sim") or {}
            tr = ap.trades.get(tid)
            theo_fired = theo.get("status") == "fired"
            actual_fired = bool(tr and tr.status in ("open", "closed") or (tr and tr.filled_qty > 0))
            if theo_fired:
                theo_fires += 1
                theo_sum_r += float(sim.get("rMultiple") or 0)
            if actual_fired:
                actual_fires += 1
            if theo_fired and actual_fired:
                matched += 1
            notes = []
            if theo_fired and not actual_fired:
                notes.append("model would have fired here but the live plan did not (check volume/critic/gates)")
            if actual_fired and not theo_fired:
                notes.append("the live plan fired but the deterministic replay would not have")
            entry_slip = None
            if tr and tr.avg_fill and theo.get("fillPrice") and tr.instrument != "options":
                entry_slip = round(float(tr.avg_fill) - float(theo["fillPrice"]), 4)
            rows.append({
                "trigger": tid, "kind": tracker.kind,
                "theoretical": {"status": theo.get("status"), "firedTs": theo.get("firedTs"),
                                "fill": theo.get("fillPrice"), "outcome": sim.get("outcome"),
                                "rMultiple": sim.get("rMultiple"), "mfeR": sim.get("mfeR"), "maeR": sim.get("maeR")},
                "actual": (None if tr is None else {
                    "status": tr.status, "firedTs": tr.fired_ts, "instrument": tr.instrument,
                    "avgFill": tr.avg_fill, "premiumPaid": (round((tr.avg_fill or 0) * tr.filled_qty * tr.multiplier, 2)
                                                            if tr.instrument == "options" and tr.filled_qty else None),
                    "realizedPnl": round(tr.realized_pnl, 2), "exits": [e.get("kind") for e in tr.exits],
                    "reason": tr.reason}),
                "match": theo_fired == actual_fired, "entrySlippage": entry_slip, "notes": notes,
            })
        return {
            "planFor": ap.plan_for, "symbol": ap.symbol,
            "theoreticalFires": theo_fires, "actualFires": actual_fires, "matched": matched,
            "theoreticalSumR": round(theo_sum_r, 3),
            "realizedPnl": round(sum(t.realized_pnl for t in ap.trades.values()), 2),
            "rows": rows,
        }

    def _unrealized(self, ap: ArmedPlan) -> float:
        """Marked at the option's bid / the underlying's last — what a sell-now
        would roughly realize. 0 when no quote is available (never guessed)."""
        total = 0.0
        for t in ap.trades.values():
            if t.remaining <= 0 or not t.avg_fill:
                continue
            if t.instrument == "options" and t.order_symbol:
                q = self.engine.quotes.get(t.order_symbol)
                px = float(q.bid) if q is not None and q.bid and q.bid > 0 else None
            else:
                q = self.engine.quotes.get(ap.symbol)
                px = float(q.last) if q is not None and q.last and q.last > 0 else None
            if px is not None:
                total += (px - float(t.avg_fill)) * t.remaining * t.multiplier
        return total

    async def _maybe_loss_halt(self, ap: ArmedPlan) -> bool:
        """The plan's "certain loss halt": once the day's loss — realised PLUS the
        open positions marked at the bid (theta bleed counts) — crosses the dollar
        limit, flatten everything and stop the plan. Returns True if it fired."""
        limit = float(ap.config.daily_loss_limit or 0)
        if limit <= 0 or ap.status not in ("armed", "paused"):
            return False
        realized = sum(t.realized_pnl for t in ap.trades.values())
        unreal = self._unrealized(ap)
        total = realized + min(0.0, unreal)     # open gains do not license bigger losses
        if total > -limit:
            return False
        ap.stop_reason = (f"loss halt: realised {realized:.2f} + open {unreal:.2f} marked at bid "
                          f"crossed -{limit:.2f}")
        self._log(ap, "loss_halt", ap.stop_reason)
        await self._alert(ap, ap.stop_reason, stage="loss_halt")
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
            "runId": ap.run_id, "symbol": ap.symbol, "stage": "loss_halt", "error": ap.stop_reason,
            "realizedPnl": round(realized, 2), "limit": limit},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
        await self.disarm(ap.run_id, reason="loss halt", flatten=True)
        return True

    async def _alert(self, ap: ArmedPlan, text: str, *, level: str = "critical", stage: str = "alert") -> None:
        """One call = every channel: the plan's live log, the append-only journal,
        a WS toast for the UI (crosses workspaces), and Telegram when configured.
        Alerting must never break trading — every channel is best-effort."""
        self._log(ap, "alert", text)
        with contextlib.suppress(Exception):
            await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                "runId": ap.run_id, "symbol": ap.symbol, "stage": stage, "error": text, "level": level},
                aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
        with contextlib.suppress(Exception):
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "alert", "level": level, "text": f"{ap.symbol}: {text}",
                                                       "runId": ap.run_id, "symbol": ap.symbol})
        tg = getattr(self.engine, "telegram", None)
        if tg is not None:
            with contextlib.suppress(Exception):
                await tg.send(f"\u26a0 {ap.symbol} armed plan: {text}")

    async def flatten_trade(self, run_id: str, trigger_id: str | None = None) -> dict | None:
        """Recourse button: sell what a trade (or every open trade of the plan)
        still holds, at market, right now. Reduce-only — nothing else changes."""
        ap = self._armed.get(run_id)
        if ap is None:
            return None
        targets = [t for t in ap.trades.values()
                   if t.remaining > 0 and (trigger_id is None or t.trigger_id == trigger_id)]
        for tr in targets:
            self._log(ap, "manual_exit", f"{tr.trigger_id}: sell-now pressed — selling {tr.remaining:g} at market",
                      trigger=tr.trigger_id)
            await self._exit(ap, tr, "stop", tr.remaining, journal=True, force_market=True,
                             reason="manual sell-now from the Armed dashboard")
        await self._persist(ap)
        self._publish(ap, "manual_exit")
        return self._snapshot(ap)

    async def stop_all(self, *, flatten: bool = False, reason: str = "stop all") -> int:
        n = 0
        for rid in list(self._armed):
            if await self.disarm(rid, reason=reason, flatten=flatten):
                n += 1
        return n

    async def adopt_order(self, run_id: str, *, key: str, underlying: dict, order: dict,
                          instrument: str = "shares", order_symbol: str | None = None,
                          multiplier: float = 1.0) -> bool:
        """Take over a position opened elsewhere (an approved technique proposal)
        and manage its exits — stop, ladder, flatten — like an auto trade. Returns
        False if the plan is no longer armed (then the user manages it by hand)."""
        ap = self._armed.get(run_id)
        if ap is None:
            return False
        targets = [float(t.get("price") if isinstance(t, dict) else t) for t in (underlying.get("targets") or [])][:3]
        tr = Trade(trigger_id=key, kind="proposal", fired_ts=int(time.time() * 1000),
                   window=session_window(int(time.time() * 1000)), entry=float(underlying.get("entry") or 0),
                   stop=float(underlying.get("stop") or 0), targets=targets, instrument=instrument,
                   order_symbol=order_symbol or (order.get("symbol") if instrument == "options" else ap.symbol),
                   multiplier=multiplier, status="working", entry_order_id=order.get("id"),
                   qty=float(order.get("qty") or 0), limit_price=order.get("limitPrice"))
        tr.single_exit = ap.config.single_contract_exit
        ap.trades[key] = tr
        if order.get("id"):
            self.register_order(order["id"], (run_id, key))
        self._log(ap, "adopted", f"{key}: managing an approved proposal ({instrument}) order {str(order.get('id'))[:8]}",
                  trigger=key)
        if order.get("status") in ("FILLED", "PARTIALLY_FILLED"):
            await self.on_order_update(order)
        await self._persist(ap)
        self._publish(ap, "adopted")
        return True

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
                         "events": ap.events[-200:], "barsSeen": ap.bar_index, "lastBarTs": ap.last_bar_ts,
                         "realizedPnl": round(sum(t.realized_pnl for t in ap.trades.values()), 2),
                         "stopReason": ap.stop_reason, "scorecard": ap.scorecard}
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
        rec = {"ts": ap.replay_ts or int(time.time() * 1000), "event": what, "text": text, **detail}
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

    # ---------------------------------------------------------------- order updates
    async def on_order_update(self, o: dict) -> None:
        key = self.owner_of(o.get("id"))
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
                        tr.realized_pnl += (float(x["price"]) - float(tr.avg_fill)) * (fq - prev) * tr.multiplier
                    tr.remaining = max(0.0, tr.filled_qty - sum(float(e.get("filledQty") or 0) for e in tr.exits))
                    self._log(ap, "exit_fill", f"{tid}: {x['kind']} filled {fq:g} @ {x.get('price')}, {tr.remaining:g} left",
                              trigger=tid, kind=x["kind"], qty=fq, price=x.get("price"))
                    if tr.remaining <= 1e-9 and tr.status != "closed":
                        tr.status = "closed"
                        tr.closed_ts = int(time.time() * 1000)
                        for k in [k for k in self._quote_breaches if k[0] == ap.run_id and k[1].startswith(tid)]:
                            self._quote_breaches.pop(k, None)
                        self._exit_retries.pop((ap.run_id, tid), None)
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
        # 1b) loss halt: if this plan's realised loss has crossed its limit, flatten
        #     what's open and stop it for the day (the user's "certain loss halt")
        if journal and await self._maybe_loss_halt(ap):
            return
        # 2) triggers
        open_or_working = sum(1 for t in ap.trades.values() if t.status in ("working", "open"))
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
                if ap.config.mode == "auto" and open_or_working >= max(1, ap.config.max_open_trades):
                    tr.status = "observed"
                    tr.fired_index = tr.fired_ts = tr.fired_window = tr.fill_price = None
                    self._log(ap, "max_open_skip",
                              f"{tid}: fired but already holding {open_or_working} (max {ap.config.max_open_trades})", trigger=tid)
                    if journal:
                        await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "max_open_trades",
                            "open": open_or_working, "max": ap.config.max_open_trades, "ts": bar.ts},
                            aggregate_type="technique_run", aggregate_id=ap.run_id)
                    continue
                await self._fire(ap, tid, tr, bar, idx, journal=journal)
                if ap.trades.get(tid) and ap.trades[tid].status in ("working", "open", "submitting"):
                    open_or_working += 1
        # 3) end of session
        if bar.ts >= close_ms - 60_000:
            ap.status = "expired"
            if journal:
                ap.scorecard = self._score_execution(ap)     # score BEFORE finish() (it mutates trackers)
                if ap.scorecard:
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_SCORED, {
                        "runId": ap.run_id, "symbol": ap.symbol, **ap.scorecard},
                        aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
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
                      fire_bar_index=idx, last_price=bar.close, instrument=cfg.instrument,
                      multiplier=100.0 if cfg.instrument == "options" else 1.0)
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
                # give the critic the whole live picture, not just the draft: which
                # R6 window we are in, the plan's other triggers, and — for options —
                # the contract it would buy (spread / IV / delta warnings)
                live_ctx = [f"LIVE CONTEXT — trigger {tid} fired at {trade.entry:.2f} in the {window} window."]
                others = [f"{t2}: {trk.kind} @ {trk.entry:.2f} ({trk.status})"
                          for t2, trk in ap.trackers.items() if t2 != tid]
                if others:
                    live_ctx.append("Other triggers in this plan: " + "; ".join(others) + ".")
                if cfg.instrument == "options" and trade.contract:
                    c = trade.contract
                    live_ctx.append(
                        f"Contract to buy (T5): {c.get('display') or c.get('symbol')} — bid/ask "
                        f"{c.get('bid')}/{c.get('ask')}, IV {c.get('iv')}, delta {c.get('delta')}, "
                        f"DTE {c.get('dte')}."
                        + (" WARNINGS: " + "; ".join(c.get("warnings") or []) if c.get("warnings") else ""))
                facts_ctx = (facts_for_prompt(facts) + "\n\n" + "\n".join(live_ctx)) if facts else "\n".join(live_ctx)
                critic = await vp.run_critic(a, {"1m": png} if png else {}, facts_ctx)
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
                contract = None
                if cfg.instrument == "options":
                    contract = await self._pick_contract(ap, trade)
                    if contract is None:
                        trade.status = "failed"
                        trade.reason = "no option contract available (see errors)"
                setup_row = await self._setup_row(trade.setup_id)
                if setup_row is not None and trade.status != "failed":
                    pid = await self.technique._emit_proposal(
                        setup_row, a, portfolio_id=cfg.portfolio_id, risk_pct=cfg.risk_pct, max_qty=cfg.max_qty,
                        fixed_qty=cfg.qty, contract=contract, managed=True,
                        contracts=(await self._size_contracts(ap, trade, contract) if contract else None))
            except Exception as exc:
                log.exception("proposal emission failed")
                trade.errors.append(f"proposal: {exc}")
            trade.proposal_id = pid
            if trade.status != "failed":
                trade.status = "proposal" if pid else "failed"
                trade.reason = ("proposal created — approve it in Signals" if pid else "no proposal could be created")
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

    async def _pick_contract(self, ap: ArmedPlan, trade: Trade) -> dict | None:
        """T5: the just-OTM call, current-week Friday / 0DTE, from the live chain."""
        s = self.engine.settings
        max_strike = None
        if bool(s.get("technique.arm.strike_within_targets", True)) and trade.targets:
            max_strike = float(trade.targets[1] if len(trade.targets) >= 2 else trade.targets[0])
        avoid_0dte = False
        cutoff = str(s.get("technique.arm.avoid_0dte_after", "15:15") or "")
        if cutoff:
            with contextlib.suppress(ValueError):
                hh, mm = (int(x) for x in cutoff.split(":"))
                now = dt.datetime.now(ET)
                avoid_0dte = (now.hour * 60 + now.minute) >= hh * 60 + mm
        try:
            pick = await self.technique.option_pick(ap.symbol, "long", spot=float(trade.last_price or trade.entry),
                                                    max_strike=max_strike, avoid_0dte=avoid_0dte)
        except Exception as exc:
            trade.errors.append(f"option chain: {exc}")
            self._log(ap, "option_pick_failed", f"{trade.trigger_id}: option chain error {exc}", trigger=trade.trigger_id)
            return None
        if not pick or not pick.get("available") or not pick.get("symbol"):
            why = (pick or {}).get("error") or "no contract just OTM"
            trade.errors.append(f"option pick: {why}")
            self._log(ap, "option_pick_failed", f"{trade.trigger_id}: {why}", trigger=trade.trigger_id)
            return None
        trade.contract = {k: pick.get(k) for k in ("symbol", "display", "underlying", "expiry", "strike", "optionType",
                                                    "bid", "ask", "mid", "spreadPct", "delta", "theta", "iv", "dte",
                                                    "is0dte", "openInterest", "volume", "warnings", "provider")}
        trade.order_symbol = pick["symbol"]
        self._log(ap, "option_picked", f"{trade.trigger_id}: {pick.get('display') or pick['symbol']} "
                  f"bid/ask {pick.get('bid')}/{pick.get('ask')}" + (f"; warnings: {'; '.join(pick.get('warnings') or [])}"
                                                                    if pick.get("warnings") else ""),
                  trigger=trade.trigger_id, contract=trade.contract)
        with contextlib.suppress(Exception):
            if getattr(self.engine, "options", None) is not None:
                await self.engine.options.track(pick["symbol"])
        return trade.contract

    async def _size_contracts(self, ap: ArmedPlan, trade: Trade, contract: dict) -> int:
        cfg = ap.config
        if cfg.contracts:
            return int(max(1, min(cfg.contracts, cfg.max_contracts)))
        premium = float(contract.get("ask") or contract.get("mid") or 0) * 100.0
        if premium <= 0:
            return 1
        equity = await self.engine.positions.equity(cfg.portfolio_id)
        n = int(equity * cfg.risk_pct / 100 / premium)
        if contract.get("is0dte") and n > 1:
            n = max(1, n // 2)                 # T5.2: 0DTE trades use reduced size
            self._log(ap, "sized", f"{trade.trigger_id}: 0DTE — risk-sized contracts halved to {n}",
                      trigger=trade.trigger_id)
        return int(max(1, min(n, cfg.max_contracts)))

    async def _enter(self, ap: ArmedPlan, trade: Trade, tr: TriggerTracker, *, journal: bool) -> None:
        """Auto mode: place the entry order (write-ahead: intent journaled first;
        OrderManager journals the risk verdict and routing). Options: buy the
        just-OTM contract at the ask (the book buys the ask on a break, p. 31);
        shares: limit at the trigger price + slippage."""
        from ..orders import OrderIntent
        cfg = ap.config
        if cfg.instrument == "options":
            contract = await self._pick_contract(ap, trade)
            if contract is None:
                trade.status = "failed"
                trade.reason = "no option contract available — nothing sent"
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                    "runId": ap.run_id, "symbol": ap.symbol, "trigger": trade.trigger_id, "stage": "entry",
                    "error": trade.errors[-1] if trade.errors else "no contract"},
                    aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
                return
            # T5.3/T5.4 liquidity/IV gates — skip the entry when configured to
            warnings = [str(w) for w in (contract.get("warnings") or [])]
            blocked = None
            if cfg.skip_wide_spread and any("T5.4 wide spread" in w for w in warnings):
                blocked = next(w for w in warnings if "T5.4 wide spread" in w)
            elif cfg.skip_elevated_iv and any("T5.3 elevated IV" in w for w in warnings):
                blocked = next(w for w in warnings if "T5.3 elevated IV" in w)
            if blocked:
                trade.status = "skipped"
                trade.reason = f"contract skipped ({blocked})"
                self._log(ap, "contract_skipped", f"{trade.trigger_id}: {trade.reason}", trigger=trade.trigger_id)
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                    "runId": ap.run_id, "symbol": ap.symbol, "trigger": trade.trigger_id, "event": "contract_quality",
                    "reason": trade.reason}, aggregate_type="technique_run", aggregate_id=ap.run_id)
                return
            qty = float(await self._size_contracts(ap, trade, contract))
            limit = round(float(contract.get("ask") or contract.get("mid") or 0), 2)
            if limit <= 0:
                trade.status = "failed"
                trade.reason = "contract has no ask price"
                return
            order_symbol, sec_type = contract["symbol"], "OPT"
        else:
            qty = await self._size(ap, trade)
            if qty < 1:
                trade.status = "skipped"
                trade.reason = "size rounds to 0 shares at this risk % — not sent"
                self._log(ap, "skipped", f"{trade.trigger_id}: {trade.reason}", trigger=trade.trigger_id)
                return
            limit = round(trade.entry * (1 + cfg.slippage_pct / 100), 2)
            order_symbol, sec_type = ap.symbol, "STK"
            trade.order_symbol = ap.symbol
        trade.qty = qty
        trade.limit_price = limit
        trade.status = "submitting"
        intent = OrderIntent(portfolio_id=cfg.portfolio_id, symbol=order_symbol, sec_type=sec_type, side="BUY",
                             qty=qty, order_type="LMT", limit_price=limit, tif="DAY", source="technique")
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ORDER_INTENT, {
            "runId": ap.run_id, "symbol": ap.symbol, "orderSymbol": order_symbol, "secType": sec_type,
            "trigger": trade.trigger_id, "side": "BUY", "qty": qty, "limitPrice": limit, "entry": trade.entry,
            "stop": trade.stop, "targets": trade.targets, "portfolioId": cfg.portfolio_id, "riskPct": cfg.risk_pct,
            "contract": trade.contract},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        self._log(ap, "entry_submit", f"{trade.trigger_id}: BUY {qty:g} {'contract(s) ' + (trade.contract or {}).get('display', order_symbol) if sec_type == 'OPT' else 'sh'} LMT {limit:.2f}",
                  trigger=trade.trigger_id)
        result = await self._place_with_retry(ap, trade, intent, stage="entry")
        if result is None:
            return
        trade.entry_order_id = result.get("id")
        if trade.entry_order_id:
            self.register_order(trade.entry_order_id, (ap.run_id, trade.trigger_id))
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
        """Exits on closed bars, via the shared reduce-only exit path
        (`execution.exits`): stop first, then the 30/40/15 ladder, then a flatten
        before the close — one exit per bar. A working exit that has not filled
        within a couple of bars (a stale bid in a falling market) is cancelled and
        re-sent at market so a stop can never sit un-filled while the trade bleeds."""
        if not journal:
            return
        tr.single_exit = ap.config.single_contract_exit
        # 1) re-price a stuck working exit before deciding anything new
        idx = ap.bar_index - 1
        stale = stale_working_exit(tr, idx, reprice_bars=EXIT_REPRICE_BARS)
        if stale is not None:
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(stale["orderId"])
            stale["status"] = "CANCELLED"
            self._log(ap, "exit_reprice", f"{tr.trigger_id}: {stale['kind']} not filled in {EXIT_REPRICE_BARS} bars — re-sending at market",
                      trigger=tr.trigger_id, kind=stale["kind"])
            await self._exit(ap, tr, stale["kind"], float(stale.get("qty") or tr.remaining), journal=True, force_market=True)
            return
        decision = plan_exit(tr, bar, close_ms=close_ms,
                             flatten_minutes=ap.config.flatten_minutes_before_close,
                             ladder=EXIT_LADDER, single_exit=ap.config.single_contract_exit)
        if decision is None:
            # a single-contract position may need to advance its trim counter without an order
            if (tr.trims_done < len(tr.targets) and bar.high >= tr.targets[tr.trims_done]
                    and tr.instrument == "options" and tr.filled_qty < 3):
                tr.trims_done += 1
            return
        tr.trims_done = decision.new_trims_done
        if decision.qty >= 1:
            await self._exit(ap, tr, decision.kind, decision.qty, journal=True, reason=decision.reason)

    async def _exit(self, ap: ArmedPlan, tr: Trade, kind: str, qty: float, *, journal: bool,
                    force_market: bool = False, reason: str = "") -> None:
        qty = float(int(qty))
        if qty < 1 or tr.remaining <= 0:
            return
        # never commit more than what is still un-exited (avoid overselling)
        available = tr.remaining - tr.pending_exit_qty
        qty = min(qty, available)
        if qty < 1:
            return
        cfg = ap.config
        bid = None
        if tr.instrument == "options" and tr.order_symbol:
            q = self.engine.quotes.get(tr.order_symbol)
            bid = float(q.bid) if q is not None and q.bid > 0 else None
        symbol = tr.order_symbol if tr.instrument == "options" and tr.order_symbol else ap.symbol
        intent = reduce_only_exit_intent(portfolio_id=cfg.portfolio_id, symbol=symbol, sec_type=tr.sec_type,
                                         qty=qty, bid=bid, force_market=force_market, source="technique")
        rec = {"kind": kind, "qty": qty, "orderId": None, "status": None, "filledQty": 0.0, "price": None,
               "ts": int(time.time() * 1000), "barIndex": ap.bar_index - 1}
        tr.exits.append(rec)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_EXIT, {
            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tr.trigger_id, "kind": kind, "qty": qty,
            "remainingBefore": tr.remaining, "stop": tr.stop, "targets": tr.targets, "reduceOnly": True,
            "orderType": intent.order_type, "reason": reason},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        self._log(ap, "exit_submit", f"{tr.trigger_id}: {kind} SELL {qty:g} {intent.order_type} (reduce-only)",
                  trigger=tr.trigger_id, kind=kind)
        result = await self._place_with_retry(ap, tr, intent, stage=f"exit:{kind}")
        if result is None:
            rec["status"] = "ERROR"
            return
        rec["orderId"] = result.get("id")
        rec["status"] = result.get("status")
        if rec["orderId"]:
            tr.exit_order_ids.append(rec["orderId"])
            self.register_order(rec["orderId"], (ap.run_id, tr.trigger_id))
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ORDER_RESULT, {
            "runId": ap.run_id, "symbol": ap.symbol, "trigger": tr.trigger_id, "stage": f"exit:{kind}",
            "orderId": rec["orderId"], "status": rec["status"], "reason": result.get("rejectReason")},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        if rec["status"] in ("REJECTED", "REJECTED_RISK"):
            rec["error"] = result.get("rejectReason")
            tr.errors.append(f"exit {kind}: {rec['error']}")
            self._log(ap, "exit_failed", f"{tr.trigger_id}: {kind} rejected — {rec['error']}", trigger=tr.trigger_id)
            await self._alert(ap, f"{tr.trigger_id}: exit {kind} REJECTED — {rec['error']} "
                              f"(position still open; watchdog will retry)", stage="exit_failed")
        elif rec["status"] in ("FILLED", "PARTIALLY_FILLED"):
            await self.on_order_update(result)
        await self._persist(ap)
        self._publish(ap, "exit_submit")

    # ---------------------------------------------------------------- housekeeping
    def _publish(self, ap: ArmedPlan, what: str) -> None:
        self.engine.bus.publish(topics.TECHNIQUE, {"kind": "armed", "event": what, "armed": self._snapshot(ap)})

    async def on_heartbeat(self) -> None:
        """Auto-arm configured symbols at the open; mark stale plans; publish a
        heartbeat snapshot every minute so the dashboard's numbers stay live.
        Runs on the shared SessionListener heartbeat (every 60 s)."""
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
                if any(t.remaining > 0 for t in ap.trades.values()):
                    await self._alert(ap, f"data went stale while holding a position — exits keep working "
                                      f"on quotes, but watch it (no closed bar for {stale_s}s)",
                                      level="warning", stage="stale_data")
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
