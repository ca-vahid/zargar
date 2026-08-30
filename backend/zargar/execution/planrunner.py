"""PlanRunner — the shared runtime that turns a session plan into managed money.

Platform plan phase 2 (2026-08-27): this is `technique/arming.py`'s PlanArmer with
the EnhancedMarket opinions taken out and replaced by hooks (`rules`, `load_plan`,
`judge_fire`, `record_fire`, `emit_proposal`, `pick_contract`, `size_multiplier`,
`preopen*`, `arm_today`). Everything risky stays here and is identical for every
technique:

    armed plan ──1m bars──▶ TriggerTracker (marketstructure; the walk-forward's object)
        ▼
    fire ──▶ judge_fire (hook) ──▶ record_fire (hook) ──▶ execution mode:
        alert     : record + journal only
        proposal  : emit_proposal (hook; user approves; RiskGate on approval)
        auto      : entry order via OrderManager.place() (RiskGate inside), then the
                    position is managed on closed bars — ladder trims, stop, flatten
                    before the close — through the reduce-only exit path

Write-ahead and journaled against the plan run: arm / pause / resume / disarm,
every skipped touch and why, every order intent and result, every fill, exit,
error and retry. State is persisted (`technique_armed`) so a restart re-arms
today's and future plans; the live-persisted record beats any replay. No new
order path exists: every order goes through `OrderManager.place()` →
`RiskGate.evaluate()`, and the kill switch is honoured before any submission.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from .. import bus as topics
from .. import events as ev
from ..domain import Bar, new_id  # noqa: F401
from ..marketstructure.rules import DEFAULT_MARKET_RULES, MarketRules
from ..marketstructure.sessions import (
    ET,
    PRIME_WINDOWS,
    next_session_date,
    session_bounds,
    session_date,
    session_window,
)
from ..marketstructure.tracker import TriggerTracker, score_trigger
from ..marketstructure.volume import build_profile
from ..models import TechniqueArmed
from .book import EXIT_LADDER, EXIT_REPRICE_BARS
from .exits import (
    plan_exit,
    premium_stop_breach,
    quote_stop_breach,
    reduce_only_exit_intent,
    stale_working_exit,
)
from .listener import SessionListener

log = logging.getLogger("zargar.execution.planrunner")

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
    premium_budget: float = 0.0      # options: cap contracts so premium*100*n <= this $ (tip budgets); 0 = off
    skip_wide_spread: bool = True    # options: skip the entry if T5.4 warns the contract spread is wide
    skip_elevated_iv: bool = False   # options: skip the entry if T5.3 warns IV is elevated (IV-crush risk)
    # When the options entry is blocked (wide spread / elevated IV / no
    # contract): "off" = skip the trade (old behaviour), "shares" = express the
    # same level trade in the underlying instead (SNOW 2026-08-25 lost +1.89R
    # to a 16.5% spread skip). Changeable after arming.
    entry_fallback: str = "off"

    def to_dict(self) -> dict:
        return {"portfolioId": self.portfolio_id, "mode": self.mode, "instrument": self.instrument,
                "contracts": self.contracts, "maxContracts": self.max_contracts,
                "singleContractExit": self.single_contract_exit, "riskPct": self.risk_pct,
                "maxQty": self.max_qty, "qty": self.qty, "useCritic": self.use_critic,
                "allowLive": self.allow_live, "flattenMinutesBeforeClose": self.flatten_minutes_before_close,
                "slippagePct": self.slippage_pct, "maxRetries": self.max_retries,
                "maxOpenTrades": self.max_open_trades, "dailyLossLimit": self.daily_loss_limit,
                "premiumBudget": self.premium_budget,
                "skipWideSpread": self.skip_wide_spread, "skipElevatedIv": self.skip_elevated_iv,
                "entryFallback": self.entry_fallback}

    @classmethod
    def from_dict(cls, d: dict) -> "ArmConfig":
        return cls(portfolio_id=str(d.get("portfolioId") or d.get("portfolio_id") or ""),
                   mode=str(d.get("mode") or "proposal"),
                   instrument=str(d.get("instrument") or "options"),
                   contracts=(int(d["contracts"]) if d.get("contracts") not in (None, "", 0, "0") else
                              (None if "contracts" in d else 1)),
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
                   premium_budget=float(d.get("premiumBudget", d.get("premium_budget", 0.0)) or 0.0),
                   skip_wide_spread=bool(d.get("skipWideSpread", d.get("skip_wide_spread", True))),
                   skip_elevated_iv=bool(d.get("skipElevatedIv", d.get("skip_elevated_iv", False))),
                   entry_fallback=str(d.get("entryFallback", d.get("entry_fallback", "off")) or "off"))


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
    contract_attempted: bool = False     # the chain was consulted for this trade (pick before the critic, A8)
    order_symbol: str | None = None      # what was actually bought (OCC symbol for options)
    multiplier: float = 1.0              # 100 for options
    single_exit: str = "tp2"             # options with < 3 contracts: exit everything at this target
    direction: str = "long"              # long (call) | short (put) — the underlying idea's side
    # a durable-position handoff has claimed this trade's fill (ARM-GAPS B5):
    # the session exit machinery must not touch it while the adopt is in flight
    handoff_pending: bool = False

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
        return {"triggerId": self.trigger_id, "kind": self.kind, "direction": self.direction,
                "firedTs": self.fired_ts, "window": self.window,
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
    critic_kills: dict[str, int] = field(default_factory=dict)   # per-trigger veto count (re-arm cap)
    critic_failures: int = 0            # critic errors/timeouts today (fail-open budget, A8)
    fire_tasks: dict = field(default_factory=dict)   # in-flight fire -> critic -> order chains, by trigger
    gap_seed: str = ""                  # late arm: where the opening bars came from (A1)
    preopen_done: bool = False          # the 09:25 pre-open check ran for this plan today (Q5)
    refire_at: dict[str, int] = field(default_factory=dict)      # per-trigger cooldown after a veto (ms)
    # prior-session 1m bars from the run's snapshot: the fire-time FACTS need a
    # volume baseline (live engine bars are today-only -> baselineSessions=0,
    # PM 2026-08-26 fired with volume the critic could not verify either way)
    baseline_bars: list = field(default_factory=list)
    stop_reason: str = ""               # why the plan stopped firing (loss halt, etc.)
    scorecard: dict | None = None       # execution review vs the walk-forward replay (after close)
    replay_ts: int | None = None        # while seeding historical bars: stamp events with the BAR's time
    technique: str = "generic"          # registry id of the technique that armed it
    # multi-day plans (ARM-GAPS A): a plan whose horizon spans sessions STAYS
    # ARMED at the close and rolls in place — plan_for advances, trackers
    # rebuild, sessions_used counts. Single-session plans (all of EM) keep
    # horizon_sessions=1 and expire exactly as before.
    horizon_sessions: int = 1           # total sessions the plan may watch
    sessions_used: int = 0              # completed (or missed-while-down) sessions
    expires_session: str = ""           # last session date the plan may still fire ("" = plan_for)
    risk_warning: str = ""              # arm-time cap preflight (ARM-GAPS E3) — shown on the card

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
            if t.status == "failed" and t.filled_qty <= 0:
                probs.append(f"{t.trigger_id}: fire produced nothing — {t.reason or 'failed'}")
        if self.stale and any(t.remaining > 0 for t in self.trades.values()):
            probs.append("bar data is stale while a position is open")
        if self.config.mode == "auto" and float(self.config.daily_loss_limit or 0) <= 0 \
                and self.status in ("armed", "paused"):
            probs.append("auto mode with NO loss halt — set dailyLossLimit (the account's equity could not be read)")
        return probs

    def to_dict(self, *, portfolio: dict | None = None, quote=None, now_ms: int | None = None) -> dict:
        now_ms = now_ms or int(time.time() * 1000)
        last = float(quote.last) if quote is not None and quote.last > 0 else None
        prime_now = session_window(now_ms)
        trig = []
        grades: list[str] = []
        for tid, tr in self.trackers.items():
            a = tr.trigger.get("assessment") or {}
            if a.get("grade"):
                grades.append(str(a["grade"]))
            d = {"id": tid, "label": tr.trigger.get("label") or None,   # None → the UI words it (kind @ price), never the raw id
                 "kind": tr.kind, "status": tr.status, "entry": tr.entry, "stop": tr.stop,
                 "targets": [t["price"] for t in tr.trigger.get("targets") or []],
                 "riskReward": tr.trigger.get("riskReward"), "firedTs": tr.fired_ts, "firedWindow": tr.fired_window,
                 "observedMidday": len(tr.observed_midday), "skipped": tr.skipped[-3:],
                 "gapUnchecked": tr.gap_unchecked, "failedBreaks": tr.failed_breaks,
                 "grade": a.get("grade"), "gradeScore": a.get("score"),
                 "conditions": tr.trigger.get("conditions"), "setupId": self.setup_ids.get(tid),
                 # the day view annotates the level before the session exists: which side
                 # the trade is on, and how well-worn the level is (touches / age)
                 "direction": getattr(tr, "direction", None) or tr.trigger.get("direction") or "long",
                 "levelTouches": (tr.trigger.get("level") or {}).get("touches"),
                 "levelAge": (tr.trigger.get("level") or {}).get("ageSessions")}
            if last:
                d["distancePct"] = round((tr.entry - last) / last * 100, 3)
                d["distance"] = round(tr.entry - last, 4)
            # "can it fire right now" — the trigger's OWN windows (a tip fires in
            # any RTH window; EM's prime clock is EM's rule — ARM-GAPS E1), or
            # the window gate being off
            trig_windows = getattr(tr.thresholds, "windows", None) or PRIME_WINDOWS
            d["windowOpenNow"] = (prime_now in trig_windows) or not tr.enforce_windows
            trig.append(d)
        open_trades = [t for t in self.trades.values() if t.open]
        return {
            "runId": self.run_id, "technique": self.technique, "symbol": self.symbol, "planFor": self.plan_for,
            "horizonSessions": self.horizon_sessions, "sessionsUsed": self.sessions_used,
            "expiresSession": self.expires_session or self.plan_for,
            "sessionDay": min(self.sessions_used + 1, max(1, self.horizon_sessions)),
            "riskWarning": self.risk_warning or None,
            "status": self.status,
            # best deterministic grade among the watched triggers — kept visible so
            # grade-vs-outcome calibration (TRADING-RULES 1.2) stays in front of us
            "grade": (min(grades) if grades else None),
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
        def _label(tid: str) -> str:
            # the plan's own label, else the PRICE names the level — run-internal
            # trigger ids look like noise on screen (user 2026-08-30)
            tr = self.trackers.get(tid)
            lbl = tr.trigger.get("label") if tr is not None else None
            return lbl or (f"the {tr.entry:.2f} level" if tr is not None else tid)

        opens = [t for t in self.trades.values() if t.open]
        if opens:
            t = opens[0]
            return f"in trade {_label(t.trigger_id)}: {t.remaining:g} left, stop {t.stop:.2f}, next target " \
                   f"{t.targets[t.trims_done]:.2f}" if t.trims_done < len(t.targets) else f"in trade {_label(t.trigger_id)}: runner {t.remaining:g}"
        waiting = [tid for tid, tr in self.trackers.items() if tr.status in ("waiting", "observed")]
        if not waiting:
            return "nothing left to watch"
        nearest = None
        if last:
            nearest = min(((abs(self.trackers[t].entry - last) / last * 100, t) for t in waiting), default=None)
        # honest label: judged against the PLAN'S OWN windows (a tip can fire
        # mid-day; EM's prime clock is EM's rule) — and with the gate off
        # a "midday" summary must not claim watching-only either
        gate_off = any(not self.trackers[t].enforce_windows for t in waiting)
        plan_windows = next((getattr(self.trackers[t].thresholds, "windows", None)
                             for t in waiting), None) or PRIME_WINDOWS
        w = ("window open — can fire" if window_now in plan_windows
             else f"{window_now}: can fire (window gate off)" if gate_off
             else f"{window_now}: watching only")
        return (f"watching {len(waiting)} trigger(s) · nearest {_label(nearest[1])} {nearest[0]:.2f}% away · {w}"
                if nearest else f"watching {len(waiting)} trigger(s) · {w}")



def _et_day_start_ms(now_ms: int) -> int:
    """Epoch ms of midnight America/New_York for the given instant."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    d = dt.datetime.fromtimestamp(now_ms / 1000, tz=et)
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)



@dataclass
class FireJudgement:
    """What the technique's judge said about a fire."""
    verdict: str = "setup"            # "setup" = go; anything else = killed (trigger re-armed, capped)
    confidence: float = 1.0
    critic: dict | None = None        # {kill, summary, violations, ...} when a critic ran
    contract: dict | None = None      # the technique's analysis contract (what a proposal is built from)
    trace: list = field(default_factory=list)
    stop: bool = False                # the fire must stop here (e.g. the critic budget is exhausted)
    extra: Any = None                 # technique-private payload (EM: the TechniqueAnalysis)


class PlanRunner(SessionListener):
    """Generic session-plan runner on the shared execution listener: the live loops
    (1m bars, order updates, heartbeat, quote watch) and the order-id index come
    from `SessionListener`; the technique supplies its opinions through the hooks
    at the bottom of this class; exits are the shared reduce-only path."""

    def __init__(self, engine, *, name: str = "plan-runner") -> None:
        super().__init__(engine, name=name)
        self._armed: dict[str, ArmedPlan] = {}
        # (run_id, trigger_id[, "~prem"]) -> consecutive quote polls seen in breach
        self._quote_breaches: dict[tuple[str, str], int] = {}
        # (run_id, trigger_id) -> (last retry ts, attempts) for the failed-exit watchdog
        self._exit_retries: dict[tuple[str, str], tuple[float, int]] = {}
        self._auto_done: set[tuple[str, str]] = set()
        # per-hook observability (EM team #6): "which hook, how often, how slow"
        # is a query, not a hunt — surfaced on the armed summary as `hookStats`
        self._hook_stats: dict[str, dict] = {}
        # conditional entries (ARM-PLAN P4): trailing closes per run for the
        # EMA/holds guards, and once-per-session dormant journaling
        self._guard_closes: dict[str, list[float]] = {}
        self._guard_noted: set[tuple[str, str, str]] = set()


    # ---------------------------------------------------------------- runtime settings
    _RT_MISSING = object()

    def rt(self, key: str, default=None):
        """Runtime setting with per-technique override (phase 3, spec §8.4):
        `techniques.<TECHNIQUE_ID>.<key>` beats `execution.<key>` (the platform
        default; the old `technique.arm.<key>` names are deprecated aliases the
        settings service migrates and redirects)."""
        s = self.engine.settings
        v = s.get(f"techniques.{self.TECHNIQUE_ID}.{key}", self._RT_MISSING)
        if v is not self._RT_MISSING and v is not None:
            return v
        return s.get(f"execution.{key}", default)

    # ---------------------------------------------------------------- listener hooks
    async def on_minute_bar(self, symbol, bar) -> None:
        for ap in [a for a in self._armed.values() if a.symbol == symbol and a.status in ("armed", "paused")]:
            await self._on_bar(ap, bar, journal=True)

    async def on_order(self, order: dict) -> None:
        await self.on_order_update(order)

    # ------------------------------------------------------------- quote stop watch
    def quote_watch_seconds(self) -> float:
        try:
            return max(0.05, float(self.rt("quote_exit_seconds", 2.0)))
        except (TypeError, ValueError):
            return 2.0

    async def on_quote_watch(self) -> None:
        """Between bar closes, exit an open trade whose *underlying* quote is
        decisively through the stop (`execution.exits.quote_stop_breach`) for
        `execution.quote_exit_polls` consecutive polls (one bad tick is not a
        breach). Safety only: this path can only sell what is already open —
        reduce-only, same `_exit` machinery, journaled with its own reason."""
        s = self.engine.settings
        if not bool(self.rt("quote_exit", True)):
            return
        try:
            excess = float(self.rt("quote_exit_excess_r", 0.25))
            need = max(1, int(self.rt("quote_exit_polls", 2)))
        except (TypeError, ValueError):
            excess, need = 0.25, 2
        max_age = int(self.rt("stale_seconds", 180))
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
            prem_pct = float(self.rt("premium_stop_pct", 50.0) or 0)
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
                        if miss == 30:       # ~1 minute of consecutive misses at 2s
                            await self._alert(ap, f"{tr.trigger_id}: no live quote for the option "
                                              f"{tr.order_symbol} for ~1 min while holding — the premium stop "
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
                reason = quote_stop_breach(tr, last, excess_r=excess, direction=tr.direction) if (last is not None and fresh) else None
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
            # each runner restores ONLY its own technique's rows — with two
            # runners live, an unfiltered restore would re-arm the other
            # technique's plans through the wrong hooks (found building tip)
            rows = (await session.execute(select(TechniqueArmed).where(
                TechniqueArmed.status.in_(("armed", "paused")),
                TechniqueArmed.technique == self.TECHNIQUE_ID))).scalars().all()
        n = 0
        now_ms = int(time.time() * 1000)
        # the session a boot-rolled PAST plan should target: today while today's
        # session can still trade, else the next session (a weekend/evening
        # restart must not strand a plan on a non-session date). Plans for today
        # or a future session restore unchanged.
        _td = dt.date.fromisoformat(today)
        target = today if (_td.weekday() < 5 and now_ms < session_bounds(today)[1]) \
            else next_session_date(now_ms)
        for row in rows:
            state = dict(row.state or {})
            # the COLUMN is authoritative (both are written by _persist; the
            # column is also what tests/ops hand-edit) — the state's copy only
            # backfills rows persisted before rolls existed
            plan_for = str(row.plan_for or state.get("planFor") or "")
            expires = str(state.get("expiresSession") or "") or plan_for
            if plan_for < today:
                if expires >= target:
                    # multi-day plan whose horizon is still live: BOOT-ROLL it
                    # forward (ARM-GAPS A4) — sessions missed while the app was
                    # down count against the horizon; trackers rebuild fresh
                    # (arm() seeds today's bars incl. the opening-bar fetch),
                    # only consumed rungs carry over
                    missed = _weekday_sessions_between(plan_for, target)
                    state["planFor"] = target
                    state["sessionsUsed"] = int(state.get("sessionsUsed") or 0) + missed
                    state["trackers"] = {tid: t for tid, t in (state.get("trackers") or {}).items()
                                         if t.get("status") == "fired"}
                    try:
                        await self.arm(row.run_id, ArmConfig.from_dict(row.config or {}), restored=True,
                                       paused=(row.status == "paused"), prior_state=state)
                        n += 1
                        ap = self._armed.get(row.run_id)
                        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ROLLED, {
                            "runId": row.run_id, "symbol": row.symbol, "from": plan_for, "to": target,
                            "bootRoll": True, "missedSessions": missed,
                            "sessionsUsed": (ap.sessions_used if ap else None),
                            "horizonSessions": (ap.horizon_sessions if ap else None)},
                            aggregate_type="technique_run", aggregate_id=row.run_id)
                    except Exception as exc:
                        log.warning("boot-roll re-arm %s failed: %s", row.run_id, exc)
                    continue
                # horizon passed while the app was down: expire SCORED — with a
                # stop reason and the journal trail, never a silent status write
                async with self.engine.sf() as session:
                    r2 = await session.get(TechniqueArmed, row.run_id)
                    if r2 is not None:
                        r2.status = "expired"
                        st2 = dict(r2.state or {})
                        st2["stopReason"] = "horizon passed while the app was down"
                        r2.state = st2
                        await session.commit()
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_DISARMED, {
                    "runId": row.run_id, "symbol": row.symbol,
                    "reason": "expired on restore — the plan's last session passed while the app was down",
                    "planFor": plan_for, "expiresSession": expires},
                    aggregate_type="technique_run", aggregate_id=row.run_id)
                with contextlib.suppress(Exception):
                    await self.on_plan_expired_offline(row)
                continue
            try:
                await self.arm(row.run_id, ArmConfig.from_dict(row.config or {}), restored=True,
                               paused=(row.status == "paused"), prior_state=row.state or {})
                n += 1
            except Exception as exc:
                log.warning("re-arm %s failed: %s", row.run_id, exc)
        return n

    # ---------------------------------------------------------------- queries
    @property
    def armer(self):
        # duck-type for the per-technique service registry (`engine.techniques`):
        # scoped routes call `svc.armer.*`, and a runner IS its own armer
        return self

    def armed(self, *, slim: bool = False) -> list[dict]:
        out = [self._snapshot(a) for a in self._armed.values()]
        if slim:
            # phones: the list without the per-plan event log / back-compat copies
            for d in out:
                d["events"] = []
                d["fired"] = []
        return out

    # what a phone's "Now" screen needs, in reading order: is anything wrong ->
    # am I in a trade -> what happened today -> what is still waiting -> P&L
    TIMELINE_KINDS = frozenset({
        "armed", "adopted", "fired", "entry_submit", "entry_working", "entry_rejected", "fire_error",
        "critic_killed", "critic_error", "position_open", "position_closed", "exit_submit", "exit_fill",
        "exit_failed", "exit_retry", "manual_exit", "loss_halt", "paused", "resumed", "disarmed",
        "skipped", "premium_stop", "quote_stop", "proposal", "contract_skipped", "kill_cap",
        "cooldown_skip", "halt_skip", "max_open_skip", "stale", "preopen_check", "entry_fallback",
        "entry_cancelled", "fire_cancelled", "rearmed_after_kill", "option_pick_failed",
    })

    def summary(self) -> dict:
        now_ms = int(time.time() * 1000)
        day_start = _et_day_start_ms(now_ms)
        window_now = session_window(now_ms)
        # "can anything fire now" judged against THIS technique's own windows
        # (a tip fires any RTH window; EM's prime clock is EM's — ARM-GAPS E1)
        my_windows = getattr(self.rules(), "windows", None) or PRIME_WINDOWS
        attention: list[dict] = []
        in_trade: list[dict] = []
        watching: list[dict] = []
        timeline: list[dict] = []
        stopped: list[dict] = []
        realized = 0.0
        unrealized = 0.0
        loss_limit = 0.0
        counts = {"armed": 0, "paused": 0, "inTrade": 0, "attention": 0, "watching": 0}
        for ap in self._armed.values():
            port = self.engine.positions.portfolio(ap.config.portfolio_id) or {}
            q = self.engine.quotes.get(ap.symbol)
            last = float(q.last) if q is not None and q.last and q.last > 0 else None
            base = {
                "runId": ap.run_id, "symbol": ap.symbol, "status": ap.status,
                "grade": ap.to_dict(portfolio=port, quote=q, now_ms=now_ms).get("grade"),
                "mode": ap.config.mode, "instrument": ap.config.instrument,
                "workspace": port.get("kind"), "account": port.get("name"),
                "stale": ap.stale, "lastPrice": last,
                "technique": ap.technique,
                "sessionDay": min(ap.sessions_used + 1, max(1, ap.horizon_sessions)),
                "horizonSessions": ap.horizon_sessions,
            }
            if ap.status == "armed":
                counts["armed"] += 1
            elif ap.status == "paused":
                counts["paused"] += 1
            realized += sum(t.realized_pnl for t in ap.trades.values())
            loss_limit += float(ap.config.daily_loss_limit or 0)
            reasons = ap._attention_reasons()
            if reasons:
                attention.append({**base, "reasons": reasons,
                                  "hasPosition": any(t.remaining > 0 for t in ap.trades.values())})
            for t in ap.trades.values():
                if not t.open:
                    continue
                unreal = self._trade_unrealized(ap, t)
                unrealized += unreal
                risk = max((t.avg_fill or t.entry) - t.stop, 1e-9) * max(t.remaining, 1e-9) * t.multiplier
                nxt = t.targets[t.trims_done] if t.trims_done < len(t.targets) else None
                in_trade.append({
                    **base, "triggerId": t.trigger_id, "kind": t.kind, "direction": t.direction,
                    "remaining": t.remaining, "filledQty": t.filled_qty, "entry": t.avg_fill or t.entry,
                    "stop": t.stop, "nextTarget": nxt, "targets": list(t.targets), "trimsDone": t.trims_done,
                    "unrealizedPnl": round(unreal, 2),
                    "unrealizedR": (round(unreal / risk, 2) if risk > 0 else None),
                    "firedTs": t.fired_ts, "window": t.window, "orderSymbol": t.order_symbol,
                    "contract": ({k: (t.contract or {}).get(k) for k in ("symbol", "strike", "expiry", "right", "bid", "ask")}
                                 if t.contract else None),
                    "multiplier": t.multiplier,
                    "tradeStatus": t.status, "realizedPnl": round(t.realized_pnl, 2),
                })
            if ap.status in ("armed", "paused"):
                waiting = [(tid, tr) for tid, tr in ap.trackers.items() if tr.status in ("waiting", "observed")]
                if waiting:
                    nearest = None
                    if last:
                        nearest = min(waiting, key=lambda x: abs(x[1].entry - last))
                    else:
                        nearest = waiting[0]
                    tid, tr = nearest
                    watching.append({
                        **base, "triggers": len(waiting),
                        # what would be bought: fixed contracts/qty, else risk-%% sizing
                        "size": {"contracts": ap.config.contracts, "riskPct": ap.config.risk_pct,
                                 "qty": ap.config.qty},
                        "nearest": {"id": tid, "label": tr.trigger.get("label") or None,
                                    "kind": tr.kind, "entry": tr.entry, "stop": tr.stop,
                                    "direction": tr.direction,
                                    "targets": [tg["price"] for tg in (tr.trigger.get("targets") or [])],
                                    "distancePct": (round((tr.entry - last) / last * 100, 3) if last else None)},
                        "window": window_now, "windowOpenNow": window_now in my_windows,
                        "summary": ap._summary(window_now, last),
                    })
            if ap.stop_reason:
                stopped.append({**base, "reason": ap.stop_reason, "at": None})
            for e in ap.events:
                if e.get("event") in self.TIMELINE_KINDS and int(e.get("ts") or 0) >= day_start:
                    timeline.append({"ts": e.get("ts"), "runId": ap.run_id, "symbol": ap.symbol,
                                     "kind": e.get("event"), "text": e.get("text") or "",
                                     "pnl": e.get("pnl") or e.get("realizedPnl")})
        timeline.sort(key=lambda x: -(x["ts"] or 0))
        counts["inTrade"] = len(in_trade)
        counts["attention"] = len(attention)
        counts["watching"] = len(watching)
        rank = {"attn": 0, "trade": 1}
        watching.sort(key=lambda w: (w["stale"], abs(w["nearest"]["distancePct"] or 999)))
        _ = rank
        used = (-(realized + unrealized) / loss_limit * 100) if loss_limit > 0 else None
        return {
            "asOf": now_ms, "window": window_now, "windowOpenNow": window_now in my_windows,
            "haltEngaged": bool(self.engine.halt.engaged),
            "workspace": str(self.engine.settings.get("trading.mode", "practice")),
            "counts": counts,
            "attention": attention, "inTrade": in_trade, "timeline": timeline[:100],
            "watching": watching, "stoppedToday": stopped,
            "hookStats": self.hook_stats(),
            "pnl": {"realized": round(realized, 2), "unrealized": round(unrealized, 2),
                    "lossLimit": round(loss_limit, 2),
                    "lossLimitUsedPct": (round(max(0.0, used), 1) if used is not None else None)},
        }

    def get(self, run_id: str) -> ArmedPlan | None:
        return self._armed.get(run_id)

    def detail(self, run_id: str) -> dict | None:
        ap = self._armed.get(run_id)
        return self._snapshot(ap) if ap else None

    def _snapshot(self, ap: ArmedPlan) -> dict:
        d = ap.to_dict(portfolio=self.engine.positions.portfolio(ap.config.portfolio_id),
                       quote=self.engine.quotes.get(ap.symbol))
        # so the card can stop claiming "critic on" for a technique with no
        # reviewer (ARM-GAPS F1) — useCritic is then inert by construction
        d["reviewerAvailable"] = bool(self.reviewer_available())
        return d

    # ---------------------------------------------------------------- config validation
    def validate_config(self, cfg: ArmConfig, *, explicit_portfolio: bool = True) -> dict:
        s = self.engine.settings
        if cfg.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if cfg.entry_fallback not in ("off", "shares"):
            raise ValueError("entryFallback must be 'off' or 'shares'")
        pid = cfg.portfolio_id or str(self.rt("default_portfolio", "")) or str(s.get("trading.default_portfolio", ""))
        portfolio = self.engine.positions.portfolio(pid) if pid else None
        sims = [p for p in self.engine.positions.portfolios() if p["kind"] == "sim"]
        # Workspace safety: a DEFAULTED account must match the trading mode — in
        # practice, an implicit arm never lands on a live/paper account (the user
        # bulk-armed 10 plans in the Practice workspace and got Webull). An
        # explicitly chosen live account is still honoured.
        if (portfolio is not None and not explicit_portfolio
                and portfolio["kind"] in ("live", "paper")
                and str(s.get("trading.mode", "practice")) != "live"):
            portfolio = sims[0] if sims else None
        if portfolio is None:
            if cfg.mode == "alert" and sims:
                portfolio = sims[0]
            else:
                raise ValueError("portfolio (account) is required — pick the account this plan trades in")
        cfg.portfolio_id = portfolio["id"]
        if cfg.mode == "auto" and portfolio["kind"] in ("live", "paper"):
            if not bool(self.rt("allow_live_auto", False)):
                raise ValueError("auto execution on a live/paper account is disabled "
                                 "(execution.allow_live_auto)")
            if not cfg.allow_live:
                raise ValueError("auto execution on a live/paper account needs the explicit acknowledgement (allowLive)")
            if str(s.get("trading.mode", "practice")) != "live":
                raise ValueError("trading.mode is 'practice' — live accounts are blocked; switch to live first")
        max_risk = float(self.rt("max_risk_pct", s.get("technique.max_risk_pct", 5.0)))
        if cfg.risk_pct <= 0 or cfg.risk_pct > max_risk:
            raise ValueError(f"riskPct must be in (0, {max_risk:g}] (R1)")
        if cfg.max_qty <= 0:
            raise ValueError("maxQty must be > 0")
        if cfg.instrument not in ("options", "shares"):
            raise ValueError("instrument must be 'options' or 'shares'")
        if cfg.instrument == "options":
            if cfg.contracts is not None and cfg.contracts < 1:
                raise ValueError("contracts must be >= 1 (or empty to size by risk %)")
            if cfg.max_contracts < 1:
                raise ValueError("maxContracts must be >= 1")
            if cfg.mode in ("auto", "proposal") and not bool(
                    self.rt("options_enabled", s.get("technique.options.enabled", True))):
                raise ValueError("options are disabled for this technique "
                                 "(options_enabled) — switch the instrument to shares")
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
                  paused: bool = False, prior_state: dict | None = None) -> dict:
        if not bool(self.rt("enabled", True)):
            raise RuntimeError("execution.enabled is off (the runner is disabled)")
        if bool(self.rt("paused", False)):
            raise RuntimeError(f"technique {self.TECHNIQUE_ID!r} is paused "
                               f"(techniques.{self.TECHNIQUE_ID}.paused) — resume it before arming new plans")
        if run_id in self._armed:
            return self._snapshot(self._armed[run_id])
        run = await self.load_plan(run_id)          # hook: the technique's run record (result.plan)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        plan = (run.get("result") or {}).get("plan")
        if run.get("mode") != "plan" or not plan:
            raise ValueError("only plan runs (mode=plan) can be armed")
        s = self.engine.settings
        cfg = config if isinstance(config, ArmConfig) else ArmConfig.from_dict({
            "portfolioId": str(self.rt("default_portfolio", "")) or str(s.get("trading.default_portfolio", "")),
            "mode": str(self.rt("mode", "proposal")), "riskPct": self.rt("risk_pct", 0.5),
            "maxQty": self.rt("max_qty", 100), "useCritic": self.rt("use_critic", True),
            "flattenMinutesBeforeClose": self.rt("flatten_minutes_before_close", 5),
            "slippagePct": self.rt("slippage_pct", 0.1), "maxRetries": self.rt("max_retries", 2),
            "instrument": self.rt("instrument", "options"), "contracts": self.rt("contracts", 1),
            "maxContracts": self.rt("max_contracts", 5),
            "singleContractExit": self.rt("single_contract_exit", "tp2"),
            "maxOpenTrades": self.rt("max_open_trades", 1),
            "dailyLossLimit": self.rt("daily_loss_limit", 0.0),
            "skipWideSpread": self.rt("skip_wide_spread", True),
            "skipElevatedIv": self.rt("skip_elevated_iv", False),
            "entryFallback": self.rt("entry_fallback", "off"),
            **(config or {})})
        explicit_pid = (bool(config.portfolio_id) if isinstance(config, ArmConfig)
                        else bool((config or {}).get("portfolioId") or (config or {}).get("portfolio_id")))
        portfolio = self.validate_config(cfg, explicit_portfolio=explicit_pid)
        symbol = run["symbol"]
        # tip-scoped override first (ARM-GAPS E1); the legacy EM name stays the
        # fallback so existing EM configs keep working unchanged
        enforce = bool(self.rt("enforce_session_windows",
                               s.get("technique.enforce_session_windows", True)))
        t = self.rules()                               # hook: the technique's MarketRules
        profile = None
        baseline_bars: list = []
        with contextlib.suppress(Exception):
            baseline_bars = list(await self.load_baseline_bars(run_id, str(plan.get("triggerTf") or "1m")) or [])
            if baseline_bars:
                profile = build_profile(baseline_bars)
        ref_px = float(plan.get("referencePrice") or plan.get("lastClose") or 0) or None
        trackers = {tg["id"]: TriggerTracker(tg, t, profile, enforce, True, ref_px)
                    for tg in plan.get("triggers") or [] if tg.get("valid")}
        ap = ArmedPlan(run_id=run_id, symbol=symbol, plan=plan, plan_for=plan.get("planFor") or "",
                       config=cfg, trackers=trackers, armed_at=time.time(), technique=self.TECHNIQUE_ID,
                       status="paused" if paused else "armed", baseline_bars=baseline_bars)
        # multi-day horizon (ARM-GAPS A1): the technique says how many sessions
        # this plan may watch and the last session it may still fire in
        try:
            h, exp = await self._hook("plan_horizon", self.plan_horizon(run, plan))
            ap.horizon_sessions = max(1, int(h or 1))
            ap.expires_session = str(exp or "") or ap.plan_for
        except Exception:
            log.exception("plan_horizon hook failed — treating as single-session")
            ap.horizon_sessions, ap.expires_session = 1, ap.plan_for
        if restored and prior_state:
            # a rolled plan's CURRENT session lives in the state, not the plan
            # doc — but a roll only ever moves FORWARD (never let a stale state
            # rewind a plan below the day it was built for)
            ap.sessions_used = int(prior_state.get("sessionsUsed") or 0)
            if prior_state.get("planFor") and str(prior_state["planFor"]) > ap.plan_for:
                ap.plan_for = str(prior_state["planFor"])
            if prior_state.get("expiresSession"):
                ap.expires_session = str(prior_state["expiresSession"])
            if prior_state.get("riskWarning"):
                ap.risk_warning = str(prior_state["riskWarning"])
        self._armed[run_id] = ap
        with contextlib.suppress(Exception):
            await self.engine.ensure_symbol(symbol)
        seeded = 0
        try:
            todays = [b for b in self.engine.bars.bars(symbol, "1m", limit=2000, include_forming=False)
                      if session_date(b.ts) == ap.plan_for]
            todays = await self._complete_opening_bars(ap, todays)
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
            # The seed replay above re-ran today's (corrected) bars, which can
            # CONTRADICT what actually happened live — e.g. GOLD 2026-08-25:
            # live gap-voided b2 at 09:31, but the replay's clean history fired
            # it at 09:44 as a phantom "alert" trade. The live-persisted record
            # is authoritative: apply it over any replay conclusion, and drop
            # trades the replay minted that the live plan never had.
            ap.critic_kills = {str(k): int(v) for k, v in ((prior_state or {}).get("criticKills") or {}).items()}
            ap.critic_failures = int((prior_state or {}).get("criticFailures") or 0)
            ap.refire_at = {str(k): int(v) for k, v in ((prior_state or {}).get("refireAt") or {}).items()}
            prior_trackers = (prior_state or {}).get("trackers") or {}
            for ptid, pst in prior_trackers.items():
                trk = trackers.get(ptid)
                if trk is None or not pst.get("status"):
                    continue
                if trk.status != pst["status"]:
                    self._log(ap, "replay_divergence",
                              f"{ptid}: live record was '{pst['status']}' but the replay said '{trk.status}' — "
                              "keeping the live record", trigger=ptid)
                trk.status = pst["status"]
                trk.fired_ts = pst.get("firedTs")
                trk.fired_window = pst.get("firedWindow")
                # gap_unchecked is the REPLAY's own verdict (did it see the 09:30 bar?) —
                # never inherit an older restart's value, which may itself be the artifact
                trk.failed_breaks = max(trk.failed_breaks, int(pst.get("failedBreaks") or 0))
                if pst["status"] not in ("fired",):
                    trk.fill_price = None
            if prior_state is not None:
                live_tids = {t.get("triggerId") for t in (prior_state.get("trades") or [])}
                for ptid in [k for k, t in list(ap.trades.items())
                             if k not in live_tids and t.status == "alert"]:
                    ap.trades.pop(ptid, None)
                    self._log(ap, "phantom_dropped",
                              f"{ptid}: replay-minted alert trade removed (live plan never fired it)", trigger=ptid)
            with contextlib.suppress(Exception):
                await self._restore_trades(ap, state=prior_state)
        await self._persist(ap)
        try:
            await self._ensure_loss_halt(ap, cfg, restored=restored)
        except ValueError:
            self._armed.pop(run_id, None)
            ap.status = "disarmed"
            await self._persist(ap)
            raise
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

    async def _complete_opening_bars(self, ap: ArmedPlan, todays: list[Bar]) -> list[Bar]:
        """A1 — a plan armed (or restored) AFTER the open must replay the session
        from its 09:30 bar: the open-gap rules are judged on the opening bar only,
        and the in-memory aggregator knows nothing from before the process started
        (2026-08-26: a 09:50 reboot "gap-voided" 22 triggers against the 09:50
        print). Fetch the missing opening bars from history (Alpaca-first) and
        merge them in front; the live buffer wins on overlap. If history has
        nothing, the trackers run with `gap_unchecked` rather than guess."""
        from ..brokers.sim import SimQuoteFeed
        open_ms, close_ms = session_bounds(ap.plan_for)
        now_ms = int(time.time() * 1000)
        if now_ms <= open_ms + 60_000 or ap.plan_for != session_date(now_ms):
            return todays
        # "have the open" means the 09:30 bar itself is present — a buffer that
        # starts with pre-market bars and jumps to 09:50 (the process ran in
        # pre-market, rebooted, came back) does NOT have it
        if any(open_ms <= b.ts <= open_ms + 60_000 for b in todays):
            return todays
        if isinstance(self.engine.feed, SimQuoteFeed):
            return todays
        hist: list[Bar] = []
        try:
            from ..marketstructure.history import fetch_session
            tf = str(ap.plan.get("triggerTf") or "1m")
            hist = [b for b in await fetch_session(ap.symbol, tf, ap.plan_for)
                    if open_ms <= b.ts < min(now_ms, close_ms)]
        except Exception as exc:
            log.warning("opening bars for %s could not be fetched: %s", ap.symbol, exc)
        if not hist:
            ap.gap_seed = "unavailable"
            self._log(ap, "opening_bars_missing",
                      "armed after the open and history has no opening bars — the overnight gap rules "
                      "cannot be judged (triggers run with gap_unchecked)")
            return todays
        have = {b.ts: b for b in hist}
        have.update({b.ts: b for b in todays})            # the live buffer wins on overlap
        merged = [have[k] for k in sorted(have)]
        added = len(merged) - len(todays)
        ap.gap_seed = f"history:{added}"
        self._log(ap, "opening_bars_seeded",
                  f"armed after the open — {added} opening bar(s) from history replayed first so the gap "
                  f"rules see the 09:30 bar", added=added)
        return merged

    async def _ensure_loss_halt(self, ap: ArmedPlan, cfg: ArmConfig, *, restored: bool = False) -> None:
        """A2 — auto mode always carries a loss halt. Derived from equity (2 x the
        per-trade risk); when equity cannot be read, the fixed fallback is used and
        it is said LOUDLY — 36/37 plans armed for 2026-08-26 had none because a log
        line was the only witness. Fallback 0 = refuse to arm rather than arm
        unprotected (a restored plan is kept, with a critical alert)."""
        if cfg.mode != "auto" or float(cfg.daily_loss_limit or 0) > 0:
            return
        eq = 0.0
        for attempt in range(2):
            with contextlib.suppress(Exception):
                eq = float(await self.engine.positions.equity(cfg.portfolio_id))
            if eq > 0:
                break
            await asyncio.sleep(0.5)
        if eq > 0:
            cfg.daily_loss_limit = round(eq * cfg.risk_pct / 100 * 2, 2)
            self._log(ap, "loss_halt_default",
                      f"auto mode with no loss halt set — defaulted to ${cfg.daily_loss_limit:,.0f} "
                      f"(2 \u00d7 the per-trade risk of {cfg.risk_pct}% on ${eq:,.0f})")
            return
        fallback = float(self.rt("daily_loss_fallback", 100.0) or 0)
        if fallback <= 0:
            if restored:
                await self._alert(ap, "auto mode with NO loss halt: the account's equity could not be read and "
                                  "execution.daily_loss_fallback is 0 — trading unprotected; set dailyLossLimit",
                                  level="critical", stage="loss_halt")
                return
            raise ValueError("auto mode needs a loss halt: the account's equity could not be read and "
                             "execution.daily_loss_fallback is 0 — set dailyLossLimit explicitly")
        cfg.daily_loss_limit = fallback
        await self._alert(ap, f"the account's equity could not be read — loss halt set to the fixed fallback "
                          f"${fallback:,.0f} (execution.daily_loss_fallback), not 2 x the per-trade risk",
                          level="warning", stage="loss_halt")

    async def wait_fires(self, run_id: str | None = None) -> None:
        """Await in-flight fire -> critic -> order chains (tests, manual replays, disarm)."""
        aps = [self._armed[run_id]] if run_id and run_id in self._armed else list(self._armed.values())
        tasks = [t for ap in aps for t in list(ap.fire_tasks.values())]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def set_mode(self, run_id: str, mode: str | None = None, *, allow_live: bool = False,
                       entry_fallback: str | None = None) -> dict:
        """Change an armed plan's execution mode and/or entry fallback in place.
        Runs the same gates as arming: auto on a live/paper account still needs
        allow_live_auto + trading.mode=live + the explicit acknowledgement."""
        ap = self._armed.get(run_id)
        if ap is None:
            raise KeyError("not armed")
        mode = mode or ap.config.mode
        if mode == ap.config.mode and (entry_fallback is None or entry_fallback == ap.config.entry_fallback):
            return self._snapshot(ap)
        old = ap.config.mode
        cfg = ArmConfig.from_dict({**ap.config.to_dict(), "mode": mode,
                                   "entryFallback": (entry_fallback if entry_fallback is not None
                                                     else ap.config.entry_fallback),
                                   "allowLive": allow_live or ap.config.allow_live})
        self.validate_config(cfg)                      # gates (mode, live-auto, options capability)
        await self._ensure_loss_halt(ap, cfg)
        ap.config = cfg
        changes = []
        if cfg.mode != old:
            changes.append(f"execution mode {old} -> {cfg.mode}")
        if entry_fallback is not None:
            changes.append(f"entry fallback -> {cfg.entry_fallback}")
        self._log(ap, "mode_changed", "; ".join(changes) or f"execution mode {old} -> {cfg.mode}")
        await self._persist(ap)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_MODE_CHANGED,
                                         {"runId": run_id, "symbol": ap.symbol, "from": old, "to": cfg.mode},
                                         aggregate_type="technique_run", aggregate_id=run_id,
                                         portfolio_id=cfg.portfolio_id)
        self._publish(ap, "mode_changed")
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
        # an in-flight fire chain must not race the disarm: mark the plan first
        # (the chain refuses to send once the plan is no longer armed), then let
        # it finish — never cancel mid-order (the write-ahead intent would dangle)
        ap.status = "disarmed"
        await self.wait_fires(run_id)
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
        run = await self.load_plan(run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        plan = (run.get("result") or {}).get("plan") or {}
        s = self.engine.settings
        cfg = config if isinstance(config, ArmConfig) else ArmConfig.from_dict({
            "portfolioId": str(self.rt("default_portfolio", "")) or str(s.get("trading.default_portfolio", "")),
            "mode": str(self.rt("mode", "proposal")),
            "instrument": self.rt("instrument", "options"), **(config or {})})
        # config validation (account, live gate, options capability)
        gate_ok, gate_msg = True, ""
        try:
            portfolio = self.validate_config(
                cfg, explicit_portfolio=bool((config or {}).get("portfolioId") or (config or {}).get("portfolio_id")))
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
                                 qty=qty, order_type="LMT", limit_price=round(entry, 2), dry_run=True, source="technique", technique_id=self.TECHNIQUE_ID)
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
        enabled = bool(self.rt("options_enabled", s.get("technique.options.enabled", True)))
        checks.append({"name": "options_enabled", "passed": enabled,
                       "detail": "" if enabled else "options are disabled for this technique"})
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

    async def _restore_trades(self, ap: ArmedPlan, state: dict | None = None) -> None:
        """After a restart, rebuild the Trade objects and the order-id index from
        the persisted projection so an open position keeps being managed and its
        fills still find their trade (instead of being orphaned).

        `state` must be the row state captured BEFORE seeding: the seed replay
        persists as it goes, so re-reading the row here can resurrect phantom
        trades the replay itself just minted (GOLD 2026-08-25)."""
        if state is None:
            async with self.engine.sf() as session:
                row = await session.get(TechniqueArmed, ap.run_id)
            state = (row.state if row else None) or {}
        rebuilt = 0
        for td in state.get("trades") or []:
            tid = td.get("triggerId")
            if not tid:
                continue
            tr = Trade(
                trigger_id=tid, kind=td.get("kind") or "", direction=td.get("direction") or "long",
                fired_ts=int(td.get("firedTs") or 0),
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

    def _trade_unrealized(self, ap: ArmedPlan, t: Trade) -> float:
        """One trade marked at the option's bid / the underlying's last; 0 when
        there is no quote (never guessed)."""
        if t.remaining <= 0 or not t.avg_fill:
            return 0.0
        if t.instrument == "options" and t.order_symbol:
            q = self.engine.quotes.get(t.order_symbol)
            px = float(q.bid) if q is not None and q.bid and q.bid > 0 else None
        else:
            q = self.engine.quotes.get(ap.symbol)
            px = float(q.last) if q is not None and q.last and q.last > 0 else None
        if px is None:
            return 0.0
        return (px - float(t.avg_fill)) * t.remaining * t.multiplier

    def _unrealized(self, ap: ArmedPlan) -> float:
        """Marked at the option's bid / the underlying's last — what a sell-now
        would roughly realize. 0 when no quote is available (never guessed)."""
        return sum(self._trade_unrealized(ap, t) for t in ap.trades.values())

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
                from ..approvals.telegram import open_keyboard
                from ..push import public_url
                await tg.send(f"\u26a0 {ap.symbol} armed plan: {text}",
                              open_keyboard(public_url(self.engine.settings), f"/armed/{ap.run_id}"))

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

    # ---------------------------------------------------------------- persistence / audit
    async def _persist(self, ap: ArmedPlan) -> None:
        try:
            async with self.engine.sf() as session:
                row = await session.get(TechniqueArmed, ap.run_id)
                state = {"trackers": {tid: {"status": tr.status, "firedTs": tr.fired_ts, "firedWindow": tr.fired_window,
                                            "skipped": tr.skipped[-5:], "observedMidday": len(tr.observed_midday),
                                            "gapUnchecked": tr.gap_unchecked, "failedBreaks": tr.failed_breaks}
                                      for tid, tr in ap.trackers.items()},
                         "trades": [t.to_dict() for t in ap.trades.values()],
                         "events": ap.events[-200:], "barsSeen": ap.bar_index, "lastBarTs": ap.last_bar_ts,
                         "realizedPnl": round(sum(t.realized_pnl for t in ap.trades.values()), 2),
                         "criticKills": ap.critic_kills, "refireAt": ap.refire_at,
                         "criticFailures": ap.critic_failures, "gapSeed": ap.gap_seed,
                         "stopReason": ap.stop_reason, "scorecard": ap.scorecard,
                         # multi-day roll bookkeeping (ARM-GAPS A): the CURRENT
                         # session and horizon survive a restart via the state
                         "planFor": ap.plan_for, "horizonSessions": ap.horizon_sessions,
                         "sessionsUsed": ap.sessions_used, "expiresSession": ap.expires_session,
                         "riskWarning": ap.risk_warning}
                if row is None:
                    row = TechniqueArmed(run_id=ap.run_id, symbol=ap.symbol, plan_for=ap.plan_for,
                                         portfolio_id=ap.config.portfolio_id, mode=ap.config.mode,
                                         config=ap.config.to_dict(), status=ap.status, state=state,
                                         technique=self.TECHNIQUE_ID)
                    session.add(row)
                else:
                    row.status = ap.status
                    row.config = ap.config.to_dict()
                    row.portfolio_id = ap.config.portfolio_id
                    row.mode = ap.config.mode
                    row.plan_for = ap.plan_for          # rolls advance the session (ARM-GAPS A2)
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
        await self.wait_fires(run_id)
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
                if idx - tr.fire_bar_index > self.rules().plan_entry_window_bars:
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
        # 2) triggers — never evaluated on pre/after-market bars (R6.5: after-hours
        #    volume is misleading signal; exits above and expiry below still run)
        in_session = session_window(bar.ts) != "extended"
        open_or_working = sum(1 for t in ap.trades.values() if t.status in ("fired", "submitting", "working", "open"))
        # R6.3 experiment (technique.arm.midday_trading): fires allowed outside the
        # prime windows — LIVE ARMER ONLY. Sweeps/backtests/plans build their own
        # trackers and never read this, so the deterministic record stays R6-true
        # and the execution scorecard's live-vs-replay diff becomes the experiment's
        # own counterfactual. The in_session gate above still blocks pre/after-market.
        want_enforce = self.entry_windows_enforced()      # hook (EM: R6 windows unless the mid-day experiment is on)
        # guard bookkeeping (ARM-PLAN P4): trailing closes for EMA/holds guards,
        # live-only state (a restart just re-warms the window)
        closes = self._guard_closes.setdefault(ap.run_id, [])
        closes.append(float(bar.close))
        del closes[:-120]
        for tid, tr in (ap.trackers.items() if in_session else ()):
            if tr.enforce_windows != want_enforce:
                tr.enforce_windows = want_enforce
            if tr.status in tr.TERMINAL:
                continue
            trig_dict = next((t for t in (ap.plan.get("triggers") or [])
                              if t.get("id") == tid), {})
            guards = trig_dict.get("guards") or []
            if guards:
                from ..marketstructure.guards import evaluate_guards
                ok, reasons = evaluate_guards(
                    guards, direction=str(trig_dict.get("direction") or "long"),
                    bar=bar, closes=closes, quote_of=self.engine.quotes.get)
                if not ok:
                    # dormant: the trigger never sees this bar; journal once/session
                    key = (ap.run_id, tid, session_date(bar.ts))
                    if key not in self._guard_noted:
                        self._guard_noted.add(key)
                        self._log(ap, "guarded", f"{tid}: dormant — {'; '.join(reasons)}",
                                  trigger=tid)
                        if journal:
                            await self.engine.journal.append(
                                ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED,
                                {"runId": ap.run_id, "symbol": ap.symbol, "trigger": tid,
                                 "event": "guarded", "ts": bar.ts,
                                 "reason": "; ".join(reasons)},
                                aggregate_type="technique_run", aggregate_id=ap.run_id)
                    continue
            before = tr.status
            n_obs, n_skip = len(tr.observed_midday), len(tr.skipped)
            if trig_dict.get("kind") == "timed":
                # timed entry (ARM-PLAN P4): no level to track — the guards
                # (time_at et al.) opening IS the signal; enter at this close
                tr.entry = float(bar.close)
                trig_dict.setdefault("entry", {})["price"] = float(bar.close)
                tr.fired_index, tr.fired_ts, tr.fill_price = idx, bar.ts, float(bar.close)
                st = tr.status = "fired"
            else:
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
                # a multi-day plan gapped past/through its level: loud, not silent
                # (ARM-GAPS A6) — the trigger revives at the roll for a retest
                if journal and st != before and self._multi_day(ap) \
                        and st in ("gapped_past", "gapped_through", "gap_void"):
                    await self._alert(ap, f"{tid}: {ap.symbol} opened {st.replace('_', ' ')} the "
                                      f"{tr.entry:.2f} level — not chasing; the plan stays armed and "
                                      f"watches for a retest (rolls to the next session at the close)",
                                      level="warning", stage="gap_roll")
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
                if ap.refire_at.get(tid) and bar.ts < ap.refire_at[tid]:
                    # cooling down after a critic veto: the SAME squeeze re-firing
                    # every bar burned all three critic calls in 3 minutes (PM
                    # 2026-08-26) — a later, distinct touch is the point of re-arming
                    tr.status = "observed"
                    tr.fired_index = tr.fired_ts = tr.fired_window = tr.fill_price = None
                    left = max(1, round((ap.refire_at[tid] - bar.ts) / 60_000))
                    self._log(ap, "cooldown_skip",
                              f"{tid}: conditions met but cooling down after a veto — {left}m left", trigger=tid)
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
                if journal:
                    self._spawn_fire(ap, tid, tr, bar, idx)      # off the bar loop (A8): exits never wait
                else:
                    await self._fire(ap, tid, tr, bar, idx, journal=False)
                if ap.trades.get(tid) and ap.trades[tid].status in ("fired", "working", "open", "submitting"):
                    open_or_working += 1
        # 3) end of session
        if bar.ts >= close_ms - 60_000:
            await self._end_session(ap, journal=journal, reason="session closed")
        elif journal:
            await self._persist(ap)


    async def _end_session(self, ap: ArmedPlan, *, journal: bool, reason: str = "session closed") -> None:
        """Session close for a plan: a multi-day plan with sessions left ROLLS in
        place (stays armed — ARM-GAPS A2); otherwise expire, write the execution
        scorecard, finish the trackers and disarm — one implementation for the
        bar-driven close AND the clock-driven close (the 15:59 bar may simply
        never arrive: on 2026-08-26 a feed outage meant the scorecards never
        wrote). Idempotent."""
        if ap.status in ("expired", "disarmed") and ap.run_id not in self._armed:
            return
        if self._should_roll(ap):
            if journal:
                await self._roll_session(ap)
            # seed replay (journal=False): leave the plan armed — the live close
            # already rolled it, or the 16:05 heartbeat clock will
            return
        ap.status = "expired"
        if journal and ap.scorecard is None:
            ap.scorecard = self._score_execution(ap)     # score BEFORE finish() (it mutates trackers)
            if ap.scorecard:
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_SCORED, {
                    "runId": ap.run_id, "symbol": ap.symbol, **ap.scorecard},
                    aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
        for tr in ap.trackers.values():
            tr.finish()
        if journal:
            await self.disarm(ap.run_id, reason=reason)
            # the plan expired at the close with no roll left: the technique may
            # expire its upstream record (the tip's signal — "the level never
            # came"). Base hook is a no-op; a rolled plan never reaches here.
            with contextlib.suppress(Exception):
                await self._hook("on_plan_horizon_expired", self.on_plan_horizon_expired(ap))

    # ---------------------------------------------------------------- multi-day roll
    # Tracker statuses that get a fresh chance next session. Terminal-for-good:
    # `invalidated` (price closed through the stop before entry — the thesis is
    # broken) and a consumed fire (the rung was played). Gap verdicts and
    # exhaustion are judgements about ONE session's open/price action.
    _REVIVABLE = frozenset({"waiting", "observed", "gap_void", "gapped_past",
                            "gapped_through", "exhausted"})

    def _multi_day(self, ap: ArmedPlan) -> bool:
        return (ap.expires_session or ap.plan_for) > ap.plan_for

    def _next_session_after(self, plan_for: str) -> str:
        return next_session_date(session_bounds(plan_for)[1] + 60_000)

    def _trigger_revivable(self, ap: ArmedPlan, tid: str, tr: TriggerTracker) -> bool:
        if tr.status in self._REVIVABLE:
            return True
        if tr.status == "fired":
            trade = ap.trades.get(tid)
            # fired but never filled (entry window elapsed / rejected / failed dry):
            # the level gets a fresh chance; a fill (or a handed-off trade, which
            # was popped from ap.trades) consumed the rung
            return trade is not None and trade.filled_qty <= 0 \
                and trade.status in ("cancelled", "failed", "alert", "proposal")
        return False

    def _should_roll(self, ap: ArmedPlan) -> bool:
        if not self._multi_day(ap) or ap.status not in ("armed", "paused"):
            return False
        nxt = self._next_session_after(ap.plan_for)
        if nxt > (ap.expires_session or ap.plan_for):
            return False
        return any(self._trigger_revivable(ap, tid, tr) for tid, tr in ap.trackers.items())

    async def _roll_session(self, ap: ArmedPlan) -> None:
        """Advance a multi-day plan to its next session IN PLACE (ARM-GAPS A2):
        cancel resting entries, flatten anything session-scoped still open,
        rebuild the trackers fresh (next open gets a real 09:30 judgement via
        the live bars / `_complete_opening_bars` on a restore), count the
        session, keep the run id and the audit trail."""
        old = ap.plan_for
        nxt = self._next_session_after(old)
        consumed: dict[str, str] = {}
        for tid, tr in ap.trackers.items():
            if not self._trigger_revivable(ap, tid, tr):
                consumed[tid] = tr.status if tr.status in tr.TERMINAL or tr.status == "fired" \
                    else "exhausted"
        for tr_ in ap.trades.values():
            if tr_.status == "working" and tr_.entry_order_id:
                with contextlib.suppress(Exception):
                    await self.engine.orders.cancel(tr_.entry_order_id)
                tr_.status = "cancelled"
                tr_.reason = "session ended unfilled — the level gets a fresh chance next session"
                self._log(ap, "entry_cancelled", f"{tr_.trigger_id}: {tr_.reason}", trigger=tr_.trigger_id)
            elif tr_.status == "open" and tr_.remaining > 0:
                # still session-scoped at the close (no handoff claimed it):
                # session-scoped stays session-scoped — never held overnight
                await self._exit(ap, tr_, "flatten", tr_.remaining, journal=True, force_market=True,
                                 reason="session-scoped position at the roll — flattened, not held overnight")
        ap.sessions_used += 1
        ap.plan_for = nxt
        ap.bar_index = 0
        ap.last_bar_ts = None
        ap.stale = ap.stale_noted = False
        ap.preopen_done = False
        ap.gap_seed = ""
        ap.critic_failures = 0
        ap.critic_kills = {}
        ap.refire_at = {}
        self._guard_closes.pop(ap.run_id, None)
        enforce = bool(self.engine.settings.get("technique.enforce_session_windows", True))
        rules = self.rules()
        profile = None
        with contextlib.suppress(Exception):
            if ap.baseline_bars:
                profile = build_profile(ap.baseline_bars)
        q = self.engine.quotes.get(ap.symbol)
        ref_px = (float(q.last) if q is not None and q.last and q.last > 0 else None) \
            or float(ap.plan.get("referencePrice") or ap.plan.get("lastClose") or 0) or None
        ap.trackers = {tg["id"]: TriggerTracker(tg, rules, profile, enforce, True, ref_px)
                       for tg in ap.plan.get("triggers") or [] if tg.get("valid")}
        for tid, st in consumed.items():
            if tid in ap.trackers:
                ap.trackers[tid].status = st
        self._log(ap, "rolled",
                  f"session {old} closed — rolled to {nxt} "
                  f"(day {ap.sessions_used + 1} of {ap.horizon_sessions}, "
                  f"last session {ap.expires_session or nxt})")
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_ROLLED, {
            "runId": ap.run_id, "symbol": ap.symbol, "from": old, "to": nxt,
            "sessionsUsed": ap.sessions_used, "horizonSessions": ap.horizon_sessions,
            "expiresSession": ap.expires_session,
            "consumed": consumed,
            "realizedPnl": round(sum(t.realized_pnl for t in ap.trades.values()), 2)},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
        await self._persist(ap)
        self._publish(ap, "rolled")

    # ---------------------------------------------------------------- fire -> execute
    def _mint_trade(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, bar: Bar, idx: int) -> Trade:
        window = session_window(bar.ts)
        cfg = ap.config
        trade = Trade(trigger_id=tid, kind=tr.kind, direction=tr.direction, fired_ts=bar.ts, window=window,
                      entry=float(tr.fill_price or tr.entry),
                      stop=tr.stop, targets=[float(t["price"]) for t in tr.trigger.get("targets") or []][:3],
                      fire_bar_index=idx, last_price=bar.close, instrument=cfg.instrument,
                      multiplier=100.0 if cfg.instrument == "options" else 1.0)
        ap.trades[tid] = trade
        self._log(ap, "fired", f"{tid} {tr.kind} fired at {trade.entry:.2f} ({window})", trigger=tid, window=window)
        return trade

    def _spawn_fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, bar: Bar, idx: int) -> None:
        """A8 — the fire -> critic -> contract -> order chain runs OFF the serial bar
        loop: a slow model must never delay another plan's stop. The trade is
        minted synchronously (so the plan's open-position count sees it at once);
        the chain re-checks the plan is still armed before anything is sent."""
        trade = self._mint_trade(ap, tid, tr, bar, idx)
        task = asyncio.create_task(self._fire_rest(ap, tid, tr, bar, idx, trade, journal=True),
                                   name=f"fire-{ap.symbol}-{tid}")
        ap.fire_tasks[tid] = task

        def _done(t: asyncio.Task, *, tid=tid, ap=ap, trade=trade) -> None:
            ap.fire_tasks.pop(tid, None)
            if t.cancelled():
                if trade.status == "fired":
                    trade.status, trade.reason = "cancelled", "fire chain cancelled before the order was sent"
                return
            exc = t.exception()
            if exc is not None:
                log.error("fire chain failed for %s %s: %s", ap.symbol, tid, exc)
                if trade.status in ("fired", "submitting"):
                    trade.status, trade.reason = "failed", f"fire failed: {exc}"
                    trade.errors.append(str(exc))
                self._log(ap, "fire_error", f"{tid}: {exc}", trigger=tid)
        task.add_done_callback(_done)

    async def _fire(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, bar: Bar, idx: int, *, journal: bool) -> None:
        trade = self._mint_trade(ap, tid, tr, bar, idx)
        await self._fire_rest(ap, tid, tr, bar, idx, trade, journal=journal)

    async def _critic_failed(self, ap: ArmedPlan, tid: str, trade: Trade, msg: str) -> bool:
        """A8 — a critic error/timeout FAILS OPEN (a model outage must not silently
        stop data collection) but never silently: a loud alert each time, and a
        per-day budget — the failure that exhausts it sends nothing and pauses the
        plan. Returns True when this fire must stop here."""
        s = self.engine.settings
        ap.critic_failures += 1
        budget = max(1, int(self.rt("critic_fail_budget", 3) or 3))
        self._log(ap, "critic_error", f"{tid}: critic failed ({msg}) — {ap.critic_failures}/{budget} today", trigger=tid)
        if ap.critic_failures >= budget:
            trade.status = "critic_unavailable"
            trade.reason = f"critic failed {ap.critic_failures}x today ({msg}) — plan paused, nothing sent"
            await self._alert(ap, f"{tid}: {trade.reason} (execution.critic_fail_budget)",
                              level="critical", stage="critic")
            with contextlib.suppress(Exception):
                await self.pause(ap.run_id)
            return True
        await self._alert(ap, f"{tid}: critic failed ({msg}) — continuing WITHOUT the critic "
                          f"({ap.critic_failures}/{budget} failures today)", level="warning", stage="critic")
        return False

    async def _fire_rest(self, ap: ArmedPlan, tid: str, tr: TriggerTracker, bar: Bar, idx: int, trade: Trade,
                         *, journal: bool) -> None:
        window, cfg = trade.window, ap.config
        # A8 — pick the contract BEFORE the judge, so it judges the vehicle
        # (spread / IV / delta / DTE) and not just the chart; the order path reuses it
        if journal and cfg.instrument == "options" and cfg.mode in ("proposal", "auto"):
            with contextlib.suppress(Exception):
                await self._hook("pick_contract", self.pick_contract(ap, trade))
        # the technique's deterministic read of the fire (hook, no I/O), then its
        # optional reviewer (hook) — the RUNNER owns the timeout, the fail-open
        # budget, pause-on-exhaust, the veto cooldown, the kill cap and re-arming
        j = await self._hook("analyze_fire", self.analyze_fire(ap, tid, tr, trade))
        if journal and cfg.use_critic and self.reviewer_available():
            timeout = float(self.rt("critic_timeout_seconds", 25) or 0)
            try:
                coro = self.review_fire(ap, tid, tr, trade, j)
                verdict, confidence, critic = await self._hook(
                    "review_fire", asyncio.wait_for(coro, timeout) if timeout > 0 else coro)
                j.verdict, j.confidence, j.critic = verdict, float(confidence), critic
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                msg = (f"timed out after {timeout:.0f}s" if isinstance(exc, asyncio.TimeoutError) else str(exc))
                log.warning("fire review failed: %s", msg)
                j.trace.append({"stage": "critic", "step": "error", "reason": msg})
                if await self._critic_failed(ap, tid, trade, msg):
                    await self._persist(ap)
                    self._publish(ap, "critic_unavailable")
                    return
        critic = j.critic
        trade.critic = critic and {k: critic.get(k) for k in ("kill", "summary", "violations")}
        # the technique's own record of the fire (EM: the setup row), always, so the run shows what fired
        if journal:
            try:
                await self._hook("record_fire", self.record_fire(ap, tid, tr, trade, j))
            except Exception:
                log.exception("recording fired setup failed")
        if journal:
            await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_FIRED, {
                "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "kind": tr.kind, "window": window,
                "middayExperiment": window == "midday",
                "fill": tr.fill_price, "entry": tr.entry, "stop": tr.stop, "targets": trade.targets,
                "verdictAfterCritic": j.verdict, "confidence": round(float(j.confidence), 3), "critic": trade.critic,
                "setupId": trade.setup_id, "mode": cfg.mode, "portfolioId": cfg.portfolio_id, "trace": j.trace},
                aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
        if j.verdict != "setup":
            trade.status = "critic_killed"
            trade.reason = (critic or {}).get("summary") or "critic killed"
            self._log(ap, "critic_killed", f"{tid}: {trade.reason}", trigger=tid)
            # A veto is an opinion about THIS moment, not the level: like the
            # paused/halt skips, the trigger goes back to watching so a later,
            # distinct touch can fire again (fresh critic, fresh data) — capped
            # so a stubborn disagreement doesn't burn critic calls all day.
            s = self.engine.settings
            cap = max(1, int(self.rt("critic_kills_per_day", 3)))
            cool = max(0, int(self.rt("refire_cooldown_minutes", 10)))
            ap.critic_kills[tid] = ap.critic_kills.get(tid, 0) + 1
            if ap.critic_kills[tid] < cap:
                tr.status = "observed"
                tr.fired_index = tr.fired_ts = tr.fired_window = tr.fill_price = None
                if cool:
                    ap.refire_at[tid] = int(time.time() * 1000) + cool * 60_000
                self._log(ap, "rearmed_after_kill",
                          f"{tid}: back to watching — a later touch can refire after a {cool}m cooldown "
                          f"(veto {ap.critic_kills[tid]}/{cap})", trigger=tid)
            else:
                self._log(ap, "kill_cap", f"{tid}: vetoed {ap.critic_kills[tid]} times — staying down for the day",
                          trigger=tid)
            await self._persist(ap)
            self._publish(ap, "critic_killed")
            return
        # the chain ran off the bar loop: the plan may have been disarmed meanwhile
        if journal and (self._armed.get(ap.run_id) is not ap or ap.status != "armed"):
            trade.status = "cancelled"
            trade.reason = f"plan {ap.status} before the order was sent"
            self._log(ap, "fire_cancelled", f"{tid}: {trade.reason}", trigger=tid)
            await self._persist(ap)
            self._publish(ap, "fired")
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
                    contract = trade.contract if trade.contract_attempted else await self._hook("pick_contract", self.pick_contract(ap, trade))
                    if contract is None:
                        trade.status = "failed"
                        trade.reason = "no option contract available (see errors)"
                if trade.status != "failed":
                    pid = await self._hook("emit_proposal", self.emit_proposal(
                        ap, trade, j, contract,
                        contracts=(await self._size_contracts(ap, trade, contract) if contract else None)))
            except Exception as exc:
                log.exception("proposal emission failed")
                trade.errors.append(f"proposal: {exc}")
            trade.proposal_id = pid
            if trade.status != "failed":
                trade.status = "proposal" if pid else "failed"
                trade.reason = ("proposal created — approve it in Signals" if pid else "no proposal could be created")
            self._log(ap, "proposal" if pid else "proposal_failed", f"{tid}: {trade.reason}", trigger=tid, proposalId=pid)
            if not pid:
                # a proposal-mode fire that produced NOTHING is a failure a person
                # must see (ARM-GAPS A5/F4) — the plan waited days for this touch
                await self._alert(ap, f"{tid}: the trigger fired but {trade.reason}"
                                  + (f" ({'; '.join(trade.errors[-2:])})" if trade.errors else ""),
                                  stage="proposal")
        else:
            await self._enter(ap, trade, tr, journal=journal)
        await self._persist(ap)
        self._publish(ap, "fired")
        if journal:
            with contextlib.suppress(Exception):
                await self.after_fire(ap, tid, tr, trade, j, bar)   # hook (EM: chat thread note)

    def _trigger_fraction(self, ap: ArmedPlan, trade: Trade) -> float:
        """This trigger's share of the plan's total size (scale-in plans,
        ARM-PLAN P3). Single-trigger plans (all of EM) carry no sizeFraction
        and size exactly as before."""
        for t in (ap.plan.get("triggers") or []):
            if t.get("id") == trade.trigger_id:
                f = t.get("sizeFraction")
                if f:
                    return max(0.05, min(1.0, float(f)))
                break
        return 1.0

    async def _size(self, ap: ArmedPlan, trade: Trade) -> float:
        cfg = ap.config
        if cfg.qty:
            return float(min(cfg.qty, cfg.max_qty))
        equity = await self.engine.positions.equity(cfg.portfolio_id)
        per_share = max(trade.entry - trade.stop, 0.01)
        qty = int(max(0, equity * cfg.risk_pct / 100 / per_share))
        return float(min(qty, cfg.max_qty))

    async def _size_contracts(self, ap: ArmedPlan, trade: Trade, contract: dict) -> int:
        """R1 on the instrument we actually trade. Fixed `contracts` wins (R5 one-
        contract rule while learning); otherwise size by risk: the dollars at risk
        per contract are what the premium stop can lose (`premium_stop_pct` of the
        premium, or the whole premium when that stop is off), contracts = equity x
        risk% / that. Fridays are scaled by `technique.arm.friday_size_mult`, 0DTE
        by a further half (T5.2 "reduced size"), then capped by `max_contracts`."""
        cfg = ap.config
        s = self.engine.settings
        if cfg.contracts:
            return int(max(1, min(cfg.contracts, cfg.max_contracts)))
        premium = float(contract.get("ask") or contract.get("mid") or 0) * 100.0
        if premium <= 0:
            return 1
        prem_stop = float(self.rt("premium_stop_pct", 50.0) or 0)
        risk_per = premium * (prem_stop / 100.0 if 0 < prem_stop < 100 else 1.0)
        equity = await self.engine.positions.equity(cfg.portfolio_id)
        raw = equity * cfg.risk_pct / 100 / max(risk_per, 1e-9)
        mult, why = self.size_multiplier(contract)        # hook (EM: Friday x0.5, 0DTE x0.5)
        n = int(raw * mult)
        if cfg.premium_budget > 0:
            # per-plan dollar budget (tip technique): never spend more premium than
            # the budget allows. Floors at 1 — a single contract slightly over
            # budget is accepted (the RiskGate premium caps still backstop) and
            # warned, rather than silently skipping the tip.
            afford = int(cfg.premium_budget // max(premium, 1e-9))
            if afford < 1:
                why.append(f"premium ${premium:,.0f} exceeds the ${cfg.premium_budget:,.0f} budget — 1 contract anyway")
            n = min(n, max(1, afford))
            why.append(f"budget ${cfg.premium_budget:,.0f}")
        n = int(max(1, min(n, cfg.max_contracts)))
        self._log(ap, "sized",
                  f"{trade.trigger_id}: {n} contract(s) — ${equity * cfg.risk_pct / 100:,.0f} at risk "
                  f"({cfg.risk_pct:g}% of ${equity:,.0f}) / ${risk_per:,.0f} per contract"
                  + (f" ({prem_stop:g}% premium stop on ${premium:,.0f})" if 0 < prem_stop < 100 else "")
                  + (", " + ", ".join(why) if why else "") + f", cap {cfg.max_contracts}",
                  trigger=trade.trigger_id, contracts=n)
        return n

    async def _enter(self, ap: ArmedPlan, trade: Trade, tr: TriggerTracker, *, journal: bool) -> None:
        """Auto mode: place the entry order (write-ahead: intent journaled first;
        OrderManager journals the risk verdict and routing). Options: buy the
        just-OTM contract at the ask (the book buys the ask on a break, p. 31);
        shares: limit at the trigger price + slippage."""
        from ..orders import OrderIntent
        cfg = ap.config
        use_options = cfg.instrument == "options"
        if trade.direction == "short" and not use_options:
            # the short side is expressed with puts only — no share shorting (margin,
            # locate, R1 on a borrowed position: none of that is in the book's method)
            trade.status = "skipped"
            trade.reason = "short setups trade puts only — this plan is armed for shares"
            self._log(ap, "skipped", f"{trade.trigger_id}: {trade.reason}", trigger=trade.trigger_id)
            return
        contract = None
        if use_options:
            contract = trade.contract if trade.contract_attempted else await self._hook("pick_contract", self.pick_contract(ap, trade))
            # T5.3/T5.4 liquidity/IV gates
            blocked = None
            if contract is not None:
                warnings = [str(w) for w in (contract.get("warnings") or [])]
                if cfg.skip_wide_spread and any("T5.4 wide spread" in w for w in warnings):
                    blocked = next(w for w in warnings if "T5.4 wide spread" in w)
                elif cfg.skip_elevated_iv and any("T5.3 elevated IV" in w for w in warnings):
                    blocked = next(w for w in warnings if "T5.3 elevated IV" in w)
            if contract is not None and blocked is None:
                # Premium risk caps are checked HERE, not only at the RiskGate:
                # a high-priced underlying (GS ~$21/contract) would otherwise
                # fire, get rejected, and take no trade at all — with the
                # fallback enabled the plan expresses the level in shares.
                s = self.engine.settings
                n_est = await self._size_contracts(ap, trade, contract)
                est = float(contract.get("ask") or contract.get("mid") or 0.0) * 100.0 * max(1, n_est)
                cap = float(s.get("risk.max_option_premium_notional", 0.0) or 0.0)
                pct_cap = float(s.get("risk.max_option_premium_pct", 0.0) or 0.0)
                pf = self.engine.positions.portfolio(cfg.portfolio_id) or {}
                eq = float(pf.get("equity") or pf.get("cash") or 0.0)
                if est > 0 and cap and est > cap:
                    blocked = f"premium ≈${est:,.0f} exceeds the ${cap:,.0f} per-order cap (risk.max_option_premium_notional)"
                elif est > 0 and pct_cap and eq and est > eq * pct_cap / 100.0:
                    blocked = (f"premium ≈${est:,.0f} is over {pct_cap:g}% of the account's ${eq:,.0f} equity "
                               f"(risk.max_option_premium_pct)")
            if contract is None or blocked:
                why = blocked or (trade.errors[-1] if trade.errors else "no contract available")
                if cfg.entry_fallback == "shares" and trade.direction != "short":
                    # Express the same level trade in the underlying instead of
                    # skipping — the edge is the level, the option is only the
                    # vehicle (per-arm choice, changeable after arming). Never for
                    # a short (puts only).
                    use_options = False
                    trade.instrument = "shares"
                    trade.contract = None
                    trade.order_symbol = None
                    self._log(ap, "entry_fallback",
                              f"{trade.trigger_id}: options unavailable ({why}) — taking shares instead",
                              trigger=trade.trigger_id)
                elif contract is None:
                    trade.status = "failed"
                    trade.reason = "no option contract available — nothing sent"
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": trade.trigger_id, "stage": "entry",
                        "error": trade.errors[-1] if trade.errors else "no contract"},
                        aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=cfg.portfolio_id)
                    # a fire that dies at the touch must be SEEN (ARM-GAPS F4)
                    await self._alert(ap, f"{trade.trigger_id}: the trigger fired but no option "
                                      f"contract was available and the shares fallback is off — "
                                      f"nothing was sent", stage="entry")
                    return
                else:
                    trade.status = "skipped"
                    trade.reason = f"contract skipped ({blocked})"
                    self._log(ap, "contract_skipped", f"{trade.trigger_id}: {trade.reason}", trigger=trade.trigger_id)
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": trade.trigger_id, "event": "contract_quality",
                        "reason": trade.reason}, aggregate_type="technique_run", aggregate_id=ap.run_id)
                    return
        frac = self._trigger_fraction(ap, trade)      # scale-in plans (ARM-PLAN P3)
        if use_options:
            qty = float(await self._size_contracts(ap, trade, contract))
            if frac < 1.0:
                qty = float(max(1, int(qty * frac)))
            limit = round(float(contract.get("ask") or contract.get("mid") or 0), 2)
            if limit <= 0:
                trade.status = "failed"
                trade.reason = "contract has no ask price"
                return
            cap = None
            with contextlib.suppress(Exception):
                cap = await self._hook("entry_limit_cap", self.entry_limit_cap(ap, trade, contract))
            if cap and limit > float(cap):
                # never chase (ARM-GAPS C1): rest at the trader's price — T4.1
                # cancels an unfilled entry, and a multi-day plan rolls the level
                self._log(ap, "entry_capped",
                          f"{trade.trigger_id}: ask {limit:.2f} is above the never-chase cap "
                          f"{float(cap):.2f} — resting the entry at the cap", trigger=trade.trigger_id)
                limit = round(float(cap), 2)
            order_symbol, sec_type = contract["symbol"], "OPT"
        else:
            qty = await self._size(ap, trade)
            if frac < 1.0:
                qty = float(max(1, int(qty * frac))) if qty >= 1 else qty
            if cfg.premium_budget > 0 and trade.entry > 0:
                # the plan's dollar budget survives the shares fallback
                # (ARM-GAPS B4): a tip whose option was unbuyable must not become
                # a risk-%-sized share position several times its budget
                afford = int(cfg.premium_budget // max(trade.entry, 0.01))
                if afford < 1:
                    trade.status = "skipped"
                    trade.reason = (f"the ${cfg.premium_budget:,.0f} plan budget cannot buy one share "
                                    f"at {trade.entry:.2f} — not sent")
                    self._log(ap, "skipped", f"{trade.trigger_id}: {trade.reason}", trigger=trade.trigger_id)
                    return
                if qty > afford:
                    self._log(ap, "sized",
                              f"{trade.trigger_id}: shares capped {qty:g} -> {afford} by the "
                              f"${cfg.premium_budget:,.0f} plan budget", trigger=trade.trigger_id)
                    qty = float(afford)
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
                             qty=qty, order_type="LMT", limit_price=limit, tif="DAY", source="technique", technique_id=self.TECHNIQUE_ID)
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
        if tr.handoff_pending:
            # the durable manager is claiming this fill (ARM-GAPS B5): no session
            # exit may race the adopt — the handoff either pops the trade or
            # clears the flag on failure, and the flatten resumes next bar
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
                             ladder=EXIT_LADDER, single_exit=ap.config.single_contract_exit,
                             stop_on="close" if self.rules().stop_on_close else "low",
                             direction=tr.direction)
        if decision is None:
            # a single-contract position may need to advance its trim counter without an order
            hit = ((bar.low <= tr.targets[tr.trims_done]) if tr.direction == "short"
                   else (bar.high >= tr.targets[tr.trims_done])) if tr.trims_done < len(tr.targets) else False
            if hit and tr.instrument == "options" and tr.filled_qty < 3:
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
                                         qty=qty, bid=bid, force_market=force_market, source="technique", technique_id=self.TECHNIQUE_ID)
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


    async def _run_preopen(self, ap: ArmedPlan) -> None:
        """The pre-open judgement, orchestrated (and journaled) by the runner: the
        technique's `preopen_check` hook says keep | replan(reference); a replan asks
        `build_replacement_plan` for a fresh run and this method swaps the plans.
        Hooks stay judgement-only — every journal entry and alert happens here, so
        the event shapes are the same for every technique."""
        q = self.engine.quotes.get(ap.symbol)
        now_ms = int(time.time() * 1000)
        last = float(q.last) if q is not None and q.last and q.last > 0 else 0.0
        fresh = q is not None and (now_ms - q.ts) <= 15 * 60_000
        if last <= 0 or not fresh:
            self._log(ap, "preopen_check", "no fresh pre-market print — nothing to judge before the open")
            return
        v = await self._hook("preopen_check", self.preopen_check(ap, last))
        if not v:
            return
        rows, prev, pct = v.get("rows") or [], float(v.get("reference") or 0), float(v.get("gapPct") or 0)
        summary = ", ".join(f"{r['trigger']} {r['verdict']}" for r in rows) or "no live triggers"
        self._log(ap, "preopen_check",
                  f"pre-market {last:.2f} vs {prev:.2f} ({pct:+.2f}%): {summary}", rows=rows, premarket=last)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_PREOPEN, {
            "runId": ap.run_id, "symbol": ap.symbol, "planFor": ap.plan_for, "premarket": last,
            "reference": prev, "gapPct": round(pct, 3), "triggers": rows, "replan": bool(v.get("replan"))},
            aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
        if not v.get("replan"):
            return
        # every trigger would die at the open: ask the technique for a plan around the actual price
        try:
            run = await self._hook("build_replacement_plan", self.build_replacement_plan(ap, reference_price=last))
        except Exception as exc:
            await self._alert(ap, f"pre-open re-plan failed ({exc}) — keeping the evening plan", level="warning",
                              stage="preopen")
            return
        new_plan = ((run or {}).get("result") or {}).get("plan") or {}
        n_valid = int(new_plan.get("validTriggers") or 0)
        if not run or run.get("status") != "done" or n_valid <= 0:
            self._log(ap, "preopen_replan_empty",
                      f"re-plan at {last:.2f} found no tradeable level — keeping the evening plan "
                      f"(its triggers will void at the open)", runId=(run or {}).get("id"))
            return
        cfg = ap.config
        old_id = ap.run_id
        await self.disarm(old_id, reason=f"pre-open re-plan: pre-market {last:.2f} ({pct:+.2f}%) killed every trigger")
        try:
            await self.arm(run["id"], ArmConfig.from_dict(cfg.to_dict()))
        except Exception as exc:
            await self._alert(ap, f"pre-open re-plan built {run.get('id', '?')[:8]} but arming it failed: {exc}",
                              level="critical", stage="preopen")
            return
        new_ap = self._armed.get(run["id"])
        if new_ap is not None:
            new_ap.preopen_done = True
            self._log(new_ap, "preopen_replanned",
                      f"replaces {old_id[:8]}: {n_valid} trigger(s) around the pre-market price {last:.2f}",
                      parentRunId=old_id)
        await self.engine.journal.append(ev.TECHNIQUE_PLAN_REPLANNED, {
            "runId": run["id"], "parentRunId": old_id, "symbol": ap.symbol, "planFor": ap.plan_for,
            "premarket": last, "reference": prev, "gapPct": round(pct, 3), "validTriggers": n_valid},
            aggregate_type="technique_run", aggregate_id=run["id"], portfolio_id=cfg.portfolio_id)
        self.engine.bus.publish(topics.TECHNIQUE, {
            "kind": "alert", "level": "info",
            "text": f"{ap.symbol}: pre-open re-plan — {n_valid} trigger(s) around {last:.2f} ({pct:+.2f}% vs close)",
            "runId": run["id"], "symbol": ap.symbol})

    async def on_heartbeat(self) -> None:
        """Auto-arm configured symbols at the open; mark stale plans; publish a
        heartbeat snapshot every minute so the dashboard's numbers stay live.
        Runs on the shared SessionListener heartbeat (every 60 s)."""
        s = self.engine.settings
        stale_s = int(self.rt("stale_seconds", 180))
        now = dt.datetime.now(ET)
        now_ms = int(time.time() * 1000)
        in_session = now.weekday() < 5 and (9 * 60 + 30) <= now.hour * 60 + now.minute < 16 * 60
        if now.weekday() < 5 and self.preopen_due(now):     # hook (EM: 09:25 pre-market judgement / re-plan)
            for ap in list(self._armed.values()):
                if ap.plan_for == now.strftime("%Y-%m-%d") and ap.status == "armed" and not ap.preopen_done:
                    ap.preopen_done = True
                    try:
                        await self._run_preopen(ap)
                    except Exception:
                        log.exception("pre-open check failed for %s", ap.symbol)
        # Daily hook-stats roll-up (EM team #6): after the close, journal per-hook
        # latency/error counters so "which hook, how often, how slow" is a query
        if (now.weekday() < 5 and now.hour * 60 + now.minute >= 16 * 60 + 5
                and self._hook_stats and getattr(self, "_hook_stats_day", "") != now.strftime("%Y-%m-%d")):
            self._hook_stats_day = now.strftime("%Y-%m-%d")
            with contextlib.suppress(Exception):
                await self.engine.journal.append(ev.TECHNIQUE_HOOK_STATS, {
                    "technique": self.TECHNIQUE_ID, "date": self._hook_stats_day, "hooks": self.hook_stats()})
            self._hook_stats.clear()
        # Clock-driven close (2026-08-27, EM team): expiry and the scorecard must not
        # depend on the 15:59 bar arriving — a feed outage at the close would
        # otherwise leave plans armed and unscored (08-26). 16:05 ET, by the clock.
        if now.weekday() < 5 and now.hour * 60 + now.minute >= 16 * 60 + 5:
            today_str = now.strftime("%Y-%m-%d")
            for ap in list(self._armed.values()):
                if ap.plan_for == today_str and ap.status in ("armed", "paused"):
                    self._log(ap, "session_closed_clock",
                              "16:05 ET and the closing bar never arrived — closing by the clock")
                    try:
                        await self._end_session(ap, journal=True,
                                                reason="session closed (clock — no closing bar seen)")
                    except Exception:
                        log.exception("clock-driven close failed for %s", ap.symbol)
        for ap in list(self._armed.values()):
            if in_session and ap.plan_for == now.strftime("%Y-%m-%d") and ap.last_bar_ts \
                    and now_ms - ap.last_bar_ts > stale_s * 1000 and not ap.stale:
                ap.stale = True
                self._log(ap, "stale", f"no closed bar for {stale_s}s — triggers idle until bars resume; "
                                       "exits keep working on quotes")
                if any(t.remaining > 0 for t in ap.trades.values()):
                    await self._alert(ap, f"data went stale while holding a position — exits keep working "
                                      f"on quotes, but watch it (no closed bar for {stale_s}s)",
                                      level="warning", stage="stale_data")
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_ERROR, {
                    "runId": ap.run_id, "symbol": ap.symbol, "stage": "data", "error": "stale bars",
                    "lastBarTs": ap.last_bar_ts}, aggregate_type="technique_run", aggregate_id=ap.run_id)
            if ap.status in ("armed", "paused"):
                self._publish(ap, "heartbeat")
        syms = [] if bool(self.rt("paused", False)) else [str(x).upper() for x in self.rt("auto_symbols", [])]
        if syms and bool(self.rt("enabled", True)):
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



    async def _hook(self, name: str, coro):
        """Await a technique hook with per-hook latency / error accounting."""
        st = self._hook_stats.setdefault(name, {"calls": 0, "errors": 0, "totalMs": 0.0, "maxMs": 0.0})
        st["calls"] += 1
        t0 = time.perf_counter()
        try:
            return await coro
        except BaseException:
            st["errors"] += 1
            raise
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
            st["totalMs"] = round(st["totalMs"] + ms, 1)
            st["maxMs"] = round(max(st["maxMs"], ms), 1)

    def hook_stats(self) -> dict:
        return {k: dict(v) for k, v in self._hook_stats.items()}

    # ================================================================ technique hooks
    # A technique subclass overrides these; every default is the "no opinion" path.
    TECHNIQUE_ID = "generic"          # registry id stamped on plans and order intents

    def rules(self) -> MarketRules:
        """The MarketRules the trackers and exits read (EM: rulebook thresholds from settings)."""
        return DEFAULT_MARKET_RULES

    async def load_plan(self, run_id: str) -> dict | None:
        """The run record to arm: a dict with `symbol`, `mode == "plan"` and `result.plan`
        (levels + triggers as data)."""
        raise NotImplementedError("this runner has no plan source")

    async def load_baseline_bars(self, run_id: str, tf: str) -> list:
        """Prior-session bars for the trigger timeframe (the volume baseline); [] = none."""
        return []

    def entry_windows_enforced(self) -> bool:
        """Whether the trackers enforce their `rules().windows` for entries right now."""
        return bool(self.engine.settings.get("technique.enforce_session_windows", True))

    async def analyze_fire(self, ap: "ArmedPlan", tid: str, tr: TriggerTracker, trade: "Trade") -> "FireJudgement":
        """The technique's deterministic read of the fire — no I/O, no model.
        Default: the trigger fired, so it is a setup."""
        return FireJudgement()

    def reviewer_available(self) -> bool:
        """Does this technique have a fire-time reviewer (EM: the vision critic) right now?"""
        return False

    async def review_fire(self, ap: "ArmedPlan", tid: str, tr: TriggerTracker, trade: "Trade",
                          judgement: "FireJudgement") -> tuple[str, float, dict | None]:
        """The reviewer: returns (verdict, confidence, critic dict|None). May raise or
        take too long — the runner owns the timeout, the fail-open budget and the
        veto machinery; this hook must not journal."""
        return judgement.verdict, judgement.confidence, None

    async def record_fire(self, ap: "ArmedPlan", tid: str, tr: TriggerTracker, trade: "Trade",
                          judgement: "FireJudgement") -> None:
        """Persist the technique's own record of the fire (EM: the setup row -> trade.setup_id)."""
        return None

    async def emit_proposal(self, ap: "ArmedPlan", trade: "Trade", judgement: "FireJudgement",
                            contract: dict | None, *, contracts: int | None) -> str | None:
        """Proposal mode: create the proposal the user approves; return its id (None = could not)."""
        return None

    async def after_fire(self, ap: "ArmedPlan", tid: str, tr: TriggerTracker, trade: "Trade",
                         judgement: "FireJudgement", bar: Bar) -> None:
        """Best-effort notification after the fire chain settled (EM: chat thread note)."""
        return None

    async def pick_contract(self, ap: "ArmedPlan", trade: "Trade") -> dict | None:
        """Expression policy for options: choose the contract (fills trade.contract /
        order_symbol). Default: no contract -> shares fallback or skip."""
        trade.contract_attempted = True
        return None

    def size_multiplier(self, contract: dict) -> tuple[float, list[str]]:
        """Policy multipliers on the risk-based contract count, with reasons."""
        return 1.0, []

    async def entry_limit_cap(self, ap: "ArmedPlan", trade: "Trade", contract: dict) -> float | None:
        """The most an auto entry may pay for the contract (ARM-GAPS C1) —
        None = uncapped. The tip runner caps at the analyst's limit / the tip's
        stated premium × (1 + max_chase_pct)."""
        return None

    def preopen_due(self, now: dt.datetime) -> bool:
        """Is it time for the technique's pre-open judgement (EM: 09:25 ET)?"""
        return False

    async def preopen_check(self, ap: "ArmedPlan", premarket: float) -> dict | None:
        """Judge the plan against the pre-market print. Returns
        {"rows": [...], "reference": prev_close, "gapPct": float, "replan": bool}
        or None when there is nothing to judge. Judgement only — the runner logs,
        journals and orchestrates any replacement."""
        return None

    async def build_replacement_plan(self, ap: "ArmedPlan", *, reference_price: float) -> dict | None:
        """Build a fresh plan run around the actual price (returns the run record,
        or None). Called only when `preopen_check` said replan."""
        return None

    async def arm_today(self, symbol: str, config: dict | None = None, *, with_vision: bool | None = None) -> dict:
        """Build and arm today's plan for a symbol on demand (auto-arm at the open)."""
        raise RuntimeError("this runner does not build plans on demand")

    async def plan_horizon(self, run: dict, plan: dict) -> tuple[int, str | None]:
        """How many sessions this plan may watch, and the LAST session date it may
        still fire in (ARM-GAPS A1). Default: single-session (all of EM)."""
        return 1, None

    async def on_plan_horizon_expired(self, ap: "ArmedPlan") -> None:
        """A multi-day plan expired with its horizon spent and the level never
        filled — the technique may expire its own upstream record (the tip's
        signal). Called after the scored expire."""
        return None

    async def on_plan_expired_offline(self, row) -> None:
        """restore() expired a persisted plan whose horizon passed while the app
        was down (row = the TechniqueArmed row). Same purpose as
        `on_plan_horizon_expired`, for a plan that never re-armed."""
        return None


def _weekday_sessions_between(a: str, b: str) -> int:
    """Weekday sessions in [a, b): how many sessions a plan armed for `a` has
    completed or missed by the time `b` is the current session."""
    try:
        d = dt.date.fromisoformat(a)
        end = dt.date.fromisoformat(b)
    except ValueError:
        return 0
    n = 0
    while d < end:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n
