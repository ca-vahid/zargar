"""Runtime-tunable settings, persisted in the DB and editable from the UI.

Flat dot-notation keys over a typed defaults map. Every change is journaled.
"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import bus as topics
from . import events as ev
from .bus import Bus
from .events import Journal
from .models import Setting

# Historical trading.mode values fold into the two-mode model: practice
# (simulated fills, incl. the old dry_run/sim rungs — per-order dry runs are
# a ticket checkbox now) and live (real orders to any connected venue).
MODE_ALIASES = {"dry_run": "practice", "sim": "practice", "paper": "live"}

DEFAULTS: dict[str, Any] = {
    # --- trading / routing -------------------------------------------------
    "trading.mode": "practice",             # practice | live
    "trading.default_portfolio": "",        # filled at seed time
    "trading.default_qty": 10,
    # --- risk gate ---------------------------------------------------------
    "risk.max_position_notional": 1000.0,   # per symbol, $
    "risk.max_position_pct": 10.0,          # per symbol, % of equity
    "risk.max_gross_exposure_pct": 100.0,
    "risk.price_collar_pct": 5.0,           # limit/market sanity vs last quote
    "risk.max_orders_per_minute": 10,
    "risk.stale_quote_seconds": 10,
    "risk.daily_loss_halt_pct": 3.0,
    "risk.allow_short": False,
    "risk.allow_options": True,
    "risk.max_option_premium_pct": 5.0,     # of equity, per trade
    "risk.max_option_premium_notional": 1000.0,  # $ per order (qty x price x 100)
    "risk.max_option_contracts": 10,        # per order
    "risk.max_option_spread_pct": 10.0,     # MKT option orders rejected above this
    "risk.allow_0dte": True,                # the EnhancedMarket method trades 0DTE/weeklies
    "risk.duplicate_window_seconds": 10,
    "risk.require_market_hours": False,     # enforce RTH for live orders
    "risk.halt_allows_exits": True,         # kill switch stops new entries but still lets you CLOSE a position
    # --- signals / automation ------------------------------------------------
    "signals.default_ttl_minutes": 30,
    "signals.default_sizing_pct": 5.0,      # % of equity per proposal
    "verification.max_price_deviation_pct": 3.0,
    "verification.max_spread_pct": 1.5,
    "verification.min_price": 1.0,
    "verification.require_actionable": True,
    # --- integrations ----------------------------------------------------------
    "telegram.enabled": False,
    "snaptrade.enabled": False,
    "snaptrade.sync_minutes": 15,
    "snaptrade.order_poll_seconds": 2.0,
    "snaptrade.reconcile_seconds": 60,
    "snaptrade.allow_brackets": False,
    "snaptrade.options_brokers": ["Webull Canada"],   # verified via options impact 2026-08-21
    # --- options (chain data + ticket) ---------------------------------------
    "options.provider": "cboe",             # cboe (free, ~15-min delayed) | tradier (token)
    "options.enrich_seconds": 5,            # contract bid/ask refresh cadence from the chain
    "feed.exchange_bars": True,             # correct sampled 1m bars with real exchange OHLC/volume from the 1m history
    "options.fee_per_contract": 0.99,       # Webull CA: USD per contract (+ regulatory fees)
    "quotes.yahoo_poll_seconds": 1.0,   # 1=frantic … 10=calm (see ui tick-speed select)
    # --- broker fee schedule (editable estimates; verify via order impact) ----
    "fees.webull_fx_pct": 1.5,          # Webull CA: rate + 1.5% markup on CAD<->USD
    "fees.wealthsimple_fx_pct": 1.5,    # WS: ~1.5% conversion on USD trades in CAD accts
    "fees.default_fx_pct": 1.5,
    # --- UI ----------------------------------------------------------------
    "ui.theme": "light",                    # light | dark (explicit saves win)
    "ui.accent": "#5b8cff",
    "ui.density": "comfortable",            # comfortable | compact
    "ui.default_symbol": "AAPL",
    "ui.chart.tf": "1m",
    "ui.chart.type": "candlestick",         # candlestick | ohlc | line
    "ui.chart.indicators": ["ema20", "vwap"],
    "ui.chart.show_volume": True,
    # --- signal sources registry (list of {name, emails, trust, notes}) -----
    "sources.registry": [],
    # --- LLM (technique pipeline + chat) -----------------------------------
    "llm.model": "claude-opus-5",
    "llm.effort": "high",                   # low | medium | high | xhigh | max
    "llm.thinking_display": "summarized",   # summarized | omitted (raw CoT is never returned)
    "llm.max_tokens": 16000,
    "llm.max_passes": 6,                    # vision pipeline call budget per run
    # --- technique (docs/TECHNIQUE-ENHANCEDMARKET.md section 10 thresholds) ---
    "technique.enabled": True,
    "technique.long_only": True,
    "technique.level_tolerance_pct": 0.15,
    "technique.min_touches": 2,
    "technique.pivot_window": 3,
    "technique.lookback_sessions": 3,
    "technique.volume_spike_mult": 1.5,
    "technique.volume_dryup_mult": 0.7,
    "technique.decisive_body_ratio": 0.6,
    "technique.min_risk_reward": 3.0,
    "technique.default_risk_pct": 1.0,
    "technique.max_risk_pct": 5.0,
    "technique.wedge_min_bars": 8,
    # Structure is read on the book's 30m/1h charts (p. 114); triggers on 1m/5m.
    "technique.structure_tfs": ["1h", "30m"],
    "technique.trigger_tf": "1m",               # trigger / primary timeframe for manual runs, plans, sweeps, arming
    "technique.bounce_stop_pct": 0.5,           # T4.3a/d — % clearance below the invalidating low (plus 0.25 ATR)
    "technique.max_stop_pct": 3.0,              # T4.3a/R1 — widest chart-justified stop, % of entry
    "technique.plan.zone_merge_pct": 1.0,       # levels closer than this % are one zone, not a ladder
    "technique.enforce_session_windows": True,  # R6: outside prime windows = watch only
    "technique.options.enabled": True,
    "technique.emit_proposals": False,      # valid setups -> practice proposals
    "technique.scan.enabled": False,
    "technique.scan.symbols": ["SPY", "QQQ", "TSLA", "NVDA", "AAPL"],
    "technique.scan.interval_minutes": 30,
    "technique.scan.rth_only": True,
    "technique.scan.windows": ["prime_open", "prime_close"],   # R6.1/R6.2 (when enforced)
    "technique.max_runs_per_day": 40,
    "technique.max_concurrent_runs": 8,     # scan-now / bulk analyst-check parallelism (takes effect on restart)
    # --- technique review loop (docs/TECHNIQUE-REVIEW-PLAN.md) -------------
    "technique.outcome.enabled": True,        # score what price did after each run
    "technique.outcome.horizon_bars": 60,     # bars after as_of to walk forward
    "technique.outcome.entry_window_bars": 12,  # bars a bounce entry has to fill
    "technique.outcome.interval_minutes": 30, # scoring loop cadence
    # --- session plans + walk-forward (docs/TECHNIQUE-WALKFORWARD-PLAN.md) ----
    "technique.plan.gap_void_r": 1.0,          # Q13 (ours): gap > 1R voids the plan
    "technique.plan.respect_mult": 3.0,        # Q14 (ours): reversal >= 3x tol = level respected
    "technique.plan.entry_window_bars": 12,    # bars a bounce has to fill after the touch
    "technique.plan.with_vision": True,        # manual plans get the 4-pass read too (sweeps stay deterministic)
    # --- evening automation (technique.sheet.*) --------------------------------
    "technique.sheet.auto": "off",             # off | build (free graded sheet after close) | analyst (build + LLM-check the A's)
    "technique.sheet.build_at": "16:15",       # ET time the auto build fires (45-min window)
    "technique.sheet.symbols": [],             # universe for the auto sheet; empty = technique.walkforward.symbols
    # the book's universe: liquid, optionable US names with tight spreads and real
    # 1m volume — index ETFs, mega-caps, semis, high-beta tech, financials, energy.
    # (CBOE chains are US-only, so no .TO/.V here.)
    "technique.walkforward.symbols": [
        "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "SMH", "TLT", "GLD",
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "NFLX", "AMD",
        "MU", "INTC", "QCOM", "TSM", "ARM", "CRM", "ORCL", "ADBE", "PLTR", "UBER",
        "COIN", "SHOP", "XYZ", "PYPL", "SOFI", "HOOD", "MSTR", "RIVN", "NIO", "BABA",
        "JPM", "BAC", "GS", "C", "WFC", "XOM", "CVX", "OXY", "BA", "DIS",
    ],
    "technique.walkforward.workers": 0,        # CPU workers for a sweep: 0 auto (cpu-1, max 8), 1 = thread only
    "technique.walkforward.concurrency": 12,   # symbols in flight at once (fetch + score)
    "technique.history.concurrency": 6,        # concurrent Yahoo requests (429 back-off is the net; >10 = throttling)
    # --- phase 2: arm plans for live triggers ---------------------------------
    "technique.arm.enabled": True,             # allow arming plans at all
    "technique.arm.use_critic": True,          # run the vision critic on a live trigger (needs key)
    "technique.arm.critic_effort": "low",      # fire-time critic thinking depth — latency is cost here
    "technique.arm.critic_kills_per_day": 3,   # vetoes per trigger before it stays down for the day
    "technique.arm.refire_cooldown_minutes": 10,  # wait after a veto before the same trigger may refire
    "technique.arm.auto_symbols": [],          # plans built + armed at the open for these symbols
    "technique.arm.mode": "proposal",          # default execution mode: alert | proposal | auto
    "technique.arm.instrument": "options",     # the book trades just-OTM weeklies / 0DTE (T5); "shares" is the alternative
    "technique.arm.contracts": 1,              # R5: one contract per trade while the technique is validated
    "technique.arm.max_contracts": 5,          # hard cap per entry (RiskGate has its own caps too)
    "technique.arm.single_contract_exit": "tp2",  # with < 3 contracts the ladder can't split: exit all at this target
    "technique.arm.default_portfolio": "",     # account armed plans trade in (empty = trading.default_portfolio)
    "technique.arm.risk_pct": 0.5,             # R1: % of equity risked per entry
    "technique.arm.max_qty": 100,              # hard cap on shares per entry
    "technique.arm.allow_live_auto": False,    # auto mode on live/paper accounts needs this AND per-arm ack
    "technique.arm.slippage_pct": 0.1,         # entry limit = trigger price * (1 + this %)
    "technique.arm.flatten_minutes_before_close": 5,
    "technique.arm.max_retries": 2,            # transient submit errors only (never risk rejections)
    "technique.arm.stale_seconds": 180,        # no closed bar for this long in-session = stale, no firing
    "technique.arm.max_open_trades": 1,        # positions a single armed plan may hold at once
    "technique.arm.daily_loss_limit": 0.0,     # $ realised loss that flattens + stops a plan for the day (0 = off)
    "technique.arm.quote_exit": True,          # intra-minute safety: exit when the live quote is decisively through the stop
    "technique.arm.quote_exit_excess_r": 0.25,  # "decisively" = beyond the stop by this x planned risk
    "technique.arm.quote_exit_polls": 2,       # consecutive ~2s polls required (one bad tick is not a breach)
    "technique.arm.quote_exit_seconds": 2.0,   # watch cadence; the quote feed itself polls ~3s
    "technique.arm.premium_stop_pct": 50.0,    # options: sell when the premium bleeds this % below what was paid (0 = off)
    "technique.arm.avoid_0dte_after": "15:15", # ET: after this time prefer this-week expiry over 0DTE ("" = never)
    "technique.arm.strike_within_targets": True,  # cap the just-OTM strike at the plan's TP2
    "technique.arm.entry_fallback": "off",     # options entry blocked (spread/IV/no contract): off = skip, shares = buy the stock instead
    "technique.arm.skip_wide_spread": True,    # options: skip the entry when the contract's spread is wide (T5.4)
    "technique.arm.skip_elevated_iv": False,   # options: skip the entry when IV is elevated (T5.3, IV-crush risk)
}


class SettingsService:
    def __init__(self, session_factory: async_sessionmaker, bus: Bus, journal: Journal) -> None:
        self._sf = session_factory
        self._bus = bus
        self._journal = journal
        self._cache: dict[str, Any] = copy.deepcopy(DEFAULTS)

    async def load(self) -> None:
        async with self._sf() as session:
            rows = (await session.execute(select(Setting))).scalars().all()
        merged = copy.deepcopy(DEFAULTS)
        for row in rows:
            if row.key in DEFAULTS or row.key.startswith("system."):
                merged[row.key] = row.value.get("v")
        # one-time migration of pre-v0.3 mode values
        raw_mode = merged.get("trading.mode")
        canon = MODE_ALIASES.get(raw_mode, raw_mode)
        if canon != raw_mode:
            merged["trading.mode"] = canon
            async with self._sf() as session:
                row = await session.get(Setting, "trading.mode")
                if row is not None:
                    row.value = {"v": canon}
                    await session.commit()
            await self._journal.append(ev.SETTING_CHANGED, {
                "key": "trading.mode", "old": raw_mode, "new": canon,
                "note": "migrated to the practice|live model"})
        self._cache = merged

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def all(self) -> dict[str, Any]:
        return {k: v for k, v in self._cache.items() if not k.startswith("system.")}

    async def set(self, key: str, value: Any, *, journal: bool = True) -> None:
        if key not in DEFAULTS and not key.startswith("system."):
            raise KeyError(f"unknown setting: {key}")
        if key == "trading.mode":
            value = MODE_ALIASES.get(value, value)
            if value not in ("practice", "live"):
                raise KeyError(f"trading.mode must be practice or live, got {value!r}")
        expected = DEFAULTS.get(key)
        if expected is not None and value is not None and not key.startswith("system."):
            # light type coercion so "3" from a form works for a numeric setting
            if isinstance(expected, bool):
                value = bool(value)
            elif isinstance(expected, float) and isinstance(value, (int, str)):
                value = float(value)
            elif isinstance(expected, int) and not isinstance(expected, bool) and isinstance(value, (float, str)):
                value = int(float(value))
        async with self._sf() as session:
            row = await session.get(Setting, key)
            if row is None:
                row = Setting(key=key, value={"v": value})
                session.add(row)
            else:
                row.value = {"v": value}
            await session.commit()
        old = self._cache.get(key)
        self._cache[key] = value
        if journal and not key.startswith("system."):
            await self._journal.append(ev.SETTING_CHANGED, {"key": key, "old": old, "new": value})
        self._bus.publish(topics.SYSTEM, {"kind": "setting", "key": key, "value": value})

    async def set_many(self, values: dict[str, Any]) -> None:
        for k, v in values.items():
            await self.set(k, v)
