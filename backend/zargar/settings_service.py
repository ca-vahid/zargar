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
from .technique.universe import CORE_UNIVERSE

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
    "risk.max_day_notional_per_technique": 0.0,  # $ BUY notional per technique per ET day (0 = off; EM team B3)
    # --- research feeds (nightly jobs on the engine scheduler; research B4/B5) ---
    "execution.min_dte": 1,                     # NEVER hold an option to expiry: platform floor for dte_close (techniques may only raise it)
    "execution.reconcile_at": "09:05",          # daily pre-open reconciliation pass (positions vs the broker)
    "execution.paused": False,                  # per-technique pause: set techniques.<id>.paused (kill switch stays global; exits are never blocked)
    "research.chain_snapshots.enabled": True,   # nightly per-contract OI/IV/volume rows (history is NOT backfillable)
    "research.chain_snapshots.at": "16:30",     # ET
    "research.chain_snapshots.keep_days": 400,  # prune beyond this window (0 = keep forever)
    "research.chain_snapshots.skip_dead": True, # drop rows with 0 volume AND 0 OI (no signal, ~60% of the chain)
    "research.daily_bars.enabled": True,        # tf=1d bars for the universe into the bars table
    "research.daily_bars.at": "20:05",          # ET
    "research.daily_bars.range": "1mo",         # per-night fetch window (idempotent upserts)

    "risk.max_day_notional_per_tag": 0.0,        # $ BUY notional per tag (e.g. source:xyz) per ET day (0 = off)

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
    # --- phone safety ---------------------------------------------------------
    "mobile.exit_only": True,               # a phone may HALT / flatten / exit / approve, but not OPEN a real-account position
    "mobile.public_url": "",                # the origin phones reach the app at (Tailscale HTTPS) — deep links in Telegram
    "mobile.push_subscriptions": [],        # Web Push subscriptions (phones that opted in)
    "mobile.vapid": {},                     # generated VAPID key pair (private PEM + public b64url)
    "mobile.push_kinds": ["alert", "armed", "proposal", "halt"],   # which events push
    # --- signals / automation ------------------------------------------------
    "signals.default_ttl_minutes": 30,
    "signals.default_sizing_pct": 5.0,      # % of equity per proposal
    "verification.max_price_deviation_pct": 3.0,
    "verification.max_spread_pct": 1.5,
    "verification.min_price": 1.0,
    "verification.require_actionable": True,
    # --- tip technique (docs/techniques/tip/PLAN.md; per-source overrides in .sources) ---
    "techniques.tip.entry": "level_touch",   # level_touch | tip_time (tip_time is EARNED per source)
    "techniques.tip.mode": "proposal",       # shadow | alert | proposal | auto (per-source override)
    "techniques.tip.risk_pct": 1.0,
    "techniques.tip.budget_per_tip": 1000.0,
    "techniques.tip.budget_open_max": 5000.0,
    "techniques.tip.dte_min": 10,            # option expression window — never 0DTE
    "techniques.tip.dte_max": 30,
    "techniques.tip.horizon_sessions": 15,   # tip expires unfilled after N sessions
    "techniques.tip.min_conviction": "implied",
    "techniques.tip.max_open_tips": 5,
    "techniques.tip.max_tip_age_hours": 72,  # older content is REPLAYED on history, never traded
    "techniques.tip.quote_wait_seconds": 6.0,  # wait for a cold ticker's first quote before verifying
    "techniques.tip.analyst_enabled": True,  # the tips analyst (LLM + market tools, advisory)
    "techniques.tip.analyst_max_tools": 8,   # tool-call budget per tip
    "techniques.tip.analyst_model": "",      # empty = the extraction model
    "techniques.tip.dedupe_window_hours": 24,
    "techniques.tip.scorecard_min_n": 20,    # verified tips before a source can leave shadow
    "techniques.tip.stop_atr_mult": 1.0,     # ATR stop when the tip states none
    "techniques.tip.target_r": [1.5, 3.0],   # R-multiple targets when the tip states none
    "techniques.tip.instrument": "shares",   # FALLBACK vehicle for non-option tips; option-shaped
    #                                          tips arm as options via the per-tip vehicle rule
    "techniques.tip.touch_tolerance_pct": 0.002,   # level-touch band for tip triggers
    # options tips die at their contract's expiry — never wait for a level past it:
    "techniques.tip.entry_cutoff_dte": 2,    # stop trying to enter when < N calendar days to the tip's expiry
    "techniques.tip.shadow_auto": True,      # the armed-book loop: auto-arm every open tip in shadow each morning
    "techniques.tip.shadow_arm_at": "09:12", # ET, on engine.scheduler (after the 09:05 reconciliation)
    "techniques.tip.trailing_after_r": 1.0,  # managed-position trail activates after +N R
    "techniques.tip.sources": {},            # {name: {entry, mode, risk_pct, budget_per_tip, ...}}
    # --- flow technique (docs/techniques/flow/PLAN.md; context only in v1, no orders) ---
    "techniques.flow.vol_oi_min": 1.25,      # flag: today's volume / open interest
    "techniques.flow.vol_oi_strong": 5.0,
    "techniques.flow.premium_min": 100_000.0,  # $ mid*volume*100 to flag a contract
    "techniques.flow.min_contract_volume": 500,
    "techniques.flow.min_open_interest": 100,
    "techniques.flow.dte_max": 45,
    "techniques.flow.otm_min_pct": 0.0,      # flagged footprint: 0–12% OTM
    "techniques.flow.otm_max_pct": 12.0,
    "techniques.flow.repeat_days": 3,        # same zone flagged N days in the window
    "techniques.flow.repeat_window": 5,
    "techniques.flow.os_ratio_flag": 0.5,    # options volume / stock volume (bearish flag)
    "techniques.flow.scan_top": 60,          # universe cap per nightly scan
    "techniques.flow.scan_at": "16:45",      # ET, on engine.scheduler — after chain_snapshots (16:30)
    "techniques.flow.universe_score_min": 5, # score >= this on 2 of 3 days joins the working universe (provenance "flow")
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
    # --- technique (docs/techniques/enhanced-market/METHOD.md section 10 thresholds) ---
    "technique.enabled": True,
    "technique.long_only": False,               # False = also plan the short side (rejection at resistance / breakdown, puts)
    "technique.level_tolerance_pct": 0.15,
    "technique.min_touches": 2,
    "technique.pivot_window": 3,
    "technique.lookback_sessions": 3,
    "technique.volume_spike_mult": 1.5,
    "technique.volume_dryup_mult": 0.7,
    "technique.volume_floor_mult": 0.5,         # R3.1 — a touch/break on less than this x the time-of-day baseline never fires
    "technique.max_false_breaks": 2,            # R3.2 — failed breaks of one level per session before it is done
    "technique.decisive_body_ratio": 0.6,
    "technique.min_risk_reward": 3.0,
    "technique.rr_gate_target": "auto",         # R2 measured to: auto (where the position actually exits) | tp1 | tp2 | tp3
    "technique.stop_on_close": True,            # T4.3 — exit when a 1m bar CLOSES through the stop (wick = test); quote breach 0.25R beyond still fires
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
    # --- technique review loop (docs/techniques/enhanced-market/REVIEW-PLAN.md) -------------
    "technique.outcome.enabled": True,        # score what price did after each run
    "technique.outcome.horizon_bars": 60,     # bars after as_of to walk forward
    "technique.outcome.entry_window_bars": 12,  # bars a bounce entry has to fill
    "technique.outcome.interval_minutes": 30, # scoring loop cadence
    # --- session plans + walk-forward (docs/techniques/enhanced-market/WALKFORWARD-PLAN.md) ----
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
    "technique.walkforward.symbols": list(CORE_UNIVERSE),   # the core universe (technique/universe.py): big, famous, heavily-traded, most options-liquid first
    "technique.universe.extra": [],           # your own additions — always planned/armable
    "technique.universe.exclude": [],         # never plan these, whatever layer they come from
    "technique.universe.auto_refresh": True,  # add the day's most-active US stocks (Alpaca screener / Yahoo) before the evening sheet
    "technique.universe.auto_top": 40,        # at most this many auto additions
    "technique.universe.min_price": 20.0,     # auto additions need a share price at least this high (thin, low-priced names are not the book's world)
    "technique.universe.resolved": {},        # cache: {date, symbols, provenance, counts, dropped} — read via GET /api/technique/universe

    "technique.walkforward.workers": 0,        # CPU workers for a sweep: 0 auto (cpu-1, max 8), 1 = thread only
    "technique.walkforward.concurrency": 12,   # symbols in flight at once (fetch + score)
    "technique.history.concurrency": 6,        # concurrent Yahoo requests (429 back-off is the net; >10 = throttling)
    # --- phase 2: arm plans for live triggers ---------------------------------
    "technique.arm.enabled": True,             # allow arming plans at all
    "technique.arm.use_critic": True,          # run the vision critic on a live trigger (needs key)
    "technique.arm.critic_effort": "low",      # fire-time critic thinking depth — latency is cost here
    "technique.arm.midday_trading": False,     # R6.3 EXPERIMENT: let armed triggers fire 10:30-14:45 ET
                                               # (fires carry window="midday" so outcomes are separable)
    "technique.arm.critic_kills_per_day": 3,   # vetoes per trigger before it stays down for the day
    "technique.arm.refire_cooldown_minutes": 10,  # wait after a veto before the same trigger may refire
    "technique.arm.auto_symbols": [],          # plans built + armed at the open for these symbols
    "technique.arm.mode": "proposal",          # default execution mode: alert | proposal | auto
    "technique.arm.instrument": "options",     # the book trades just-OTM weeklies / 0DTE (T5); "shares" is the alternative
    "technique.arm.contracts": 0,              # 0 = size by risk % (see risk_pct); 1 = the book's R5 one-contract rule
    "technique.arm.max_contracts": 10,         # hard cap per entry (RiskGate has its own caps too)
    "technique.arm.friday_size_mult": 0.5,     # Fridays (0DTE day for single names): scale the risk-sized contracts
    "technique.arm.preopen_at": "09:25",       # ET: judge armed plans against the pre-market print from this time
    "technique.arm.preopen_replan": True,      # when every trigger would die at the open, re-plan around the pre-market price

    "technique.arm.single_contract_exit": "tp2",  # with < 3 contracts the ladder can't split: exit all at this target
    "technique.arm.default_portfolio": "",     # account armed plans trade in (empty = trading.default_portfolio)
    "technique.arm.risk_pct": 2.0,             # R1: % of equity risked per entry (practice: 2%; the book's live range is 0.5-1%)
    "technique.arm.max_qty": 100,              # hard cap on shares per entry
    "technique.arm.allow_live_auto": False,    # auto mode on live/paper accounts needs this AND per-arm ack
    "technique.arm.slippage_pct": 0.1,         # entry limit = trigger price * (1 + this %)
    "technique.arm.flatten_minutes_before_close": 5,
    "technique.arm.max_retries": 2,            # transient submit errors only (never risk rejections)
    "technique.arm.stale_seconds": 180,        # no closed bar for this long in-session = stale, no firing
    "technique.arm.max_open_trades": 1,        # positions a single armed plan may hold at once
    "technique.arm.daily_loss_limit": 0.0,     # $ realised loss that flattens + stops a plan for the day (0 = off)
    "technique.arm.daily_loss_fallback": 100.0,  # auto mode with no limit and no readable equity: use this $ (0 = refuse to arm)
    "technique.arm.critic_timeout_seconds": 25,  # fire-time critic hard timeout; a timeout fails OPEN with an alert
    "technique.arm.critic_fail_budget": 3,     # critic failures/timeouts per plan per day; the last one pauses the plan
    "feed.exchange_bar_hold_seconds": 5,       # hold a quote-sampled 1m bar this long for the exchange bar (Alpaca) to replace it
    "technique.arm.quote_exit": True,          # intra-minute safety: exit when the live quote is decisively through the stop
    "technique.arm.quote_exit_excess_r": 0.25,  # "decisively" = beyond the stop by this x planned risk
    "technique.arm.quote_exit_polls": 2,       # consecutive ~2s polls required (one bad tick is not a breach)
    "technique.arm.quote_exit_seconds": 2.0,   # watch cadence; the quote feed itself polls ~3s
    "technique.arm.premium_stop_pct": 50.0,    # options: sell when the premium bleeds this % below what was paid (0 = off)
    "technique.arm.avoid_0dte_after": "10:30", # ET: 0DTE only in the morning window; later fires take the next expiry ("" = never)
    "technique.arm.strike_within_targets": True,  # cap the just-OTM strike at the plan's TP2
    "technique.arm.entry_fallback": "off",     # options entry blocked (spread/IV/no contract): off = skip, shares = buy the stock instead
    "technique.arm.skip_wide_spread": True,    # options: skip the entry when the contract's spread is wide (T5.4)
    "technique.arm.skip_elevated_iv": False,   # options: skip the entry when IV is elevated (T5.3, IV-crush risk)
}



# --- platform settings scoping (phase 3; spec: platform plan §8.4, decisions 2026-08-27) ----
# Canonical names for every key the shared runner (`execution/planrunner.py`) reads live
# under `execution.*`; the old `technique.arm.*` names stay as DEPRECATED ALIASES —
# `get`/`set` redirect transparently and a stored legacy value is migrated once with
# `SettingChanged` journal continuity. A technique overrides a runtime key with
# `techniques.<id>.<key>` (resolved by `PlanRunner.rt()`): techniques.<id>.<key>
# -> execution.<key>. EM-policy keys are NOT platform keys and are excluded:
# `technique.arm.midday_trading` by explicit decision (EM-only, forever), plus the
# keys only EM's hooks read (pre-open, critic effort, strike caps, Friday/0DTE sizing).
_ALIAS_EXCLUDE = {
    "technique.arm.midday_trading",       # decision 2026-08-27: EM-only, never a platform key
    "technique.arm.critic_effort",        # EM's reviewer prompt policy
    "technique.arm.preopen_at",           # EM's 09:25 judgement
    "technique.arm.preopen_replan",
    "technique.arm.strike_within_targets",  # EM's T5 expression policy
    "technique.arm.avoid_0dte_after",
    "technique.arm.friday_size_mult",     # EM's T5.2 sizing policy
}
ALIASES: dict[str, str] = {
    k: "execution." + k[len("technique.arm."):]
    for k in list(DEFAULTS)
    if k.startswith("technique.arm.") and k not in _ALIAS_EXCLUDE
}
for _legacy, _canon in ALIASES.items():
    DEFAULTS.setdefault(_canon, copy.deepcopy(DEFAULTS[_legacy]))


def _technique_override_canonical(key: str) -> str | None:
    """`techniques.<id>.<suffix>` is a valid per-technique override iff
    `execution.<suffix>` is a known runtime key; returns that canonical key."""
    parts = key.split(".", 2)
    if len(parts) == 3 and parts[0] == "techniques" and parts[1]:
        canon = "execution." + parts[2]
        if canon in DEFAULTS:
            return canon
    return None


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
        by_key = {row.key: row for row in rows}
        for row in rows:
            if row.key in DEFAULTS or row.key.startswith("system.") \
                    or _technique_override_canonical(row.key) is not None:
                merged[row.key] = row.value.get("v")
        # one-time migration of stored legacy runtime keys to their canonical
        # execution.* names (phase 3): the canonical row wins if both exist
        migrated: list[tuple[str, str, Any]] = []
        for legacy, canon in ALIASES.items():
            if legacy in by_key and canon not in by_key:
                v = by_key[legacy].value.get("v")
                merged[canon] = v
                migrated.append((legacy, canon, v))
        if migrated:
            async with self._sf() as session:
                for _legacy, canon, v in migrated:
                    session.add(Setting(key=canon, value={"v": v}))
                await session.commit()
            for legacy, canon, v in migrated:
                await self._journal.append(ev.SETTING_CHANGED, {
                    "key": canon, "old": DEFAULTS.get(canon), "new": v,
                    "note": f"migrated from the deprecated name {legacy} (platform plan phase 3)"})
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
        return self._cache.get(ALIASES.get(key, key), default)

    def all(self) -> dict[str, Any]:
        out = {k: v for k, v in self._cache.items() if not k.startswith("system.")}
        # deprecated aliases mirror their canonical value so the existing UI keeps
        # showing (and editing) the truth during the migration window
        for legacy, canon in ALIASES.items():
            if canon in out:
                out[legacy] = out[canon]
        return out

    async def set(self, key: str, value: Any, *, journal: bool = True, broadcast: bool = True) -> None:
        """`broadcast=False` keeps the change off the `system` bus topic (which every
        WS client receives) — use it for secrets."""
        alias_of = None
        if key in ALIASES:
            alias_of, key = key, ALIASES[key]      # deprecated name: write the canonical key
        if key not in DEFAULTS and not key.startswith("system.") \
                and _technique_override_canonical(key) is None:
            raise KeyError(f"unknown setting: {key}")
        if key == "trading.mode":
            value = MODE_ALIASES.get(value, value)
            if value not in ("practice", "live"):
                raise KeyError(f"trading.mode must be practice or live, got {value!r}")
        expected = DEFAULTS.get(key)
        if expected is None:
            ov = _technique_override_canonical(key)
            if ov is not None:
                expected = DEFAULTS.get(ov)
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
            payload = {"key": key, "old": old, "new": value}
            if alias_of:
                payload["aliasOf"] = alias_of      # journal continuity: edits via the old name stay findable
            await self._journal.append(ev.SETTING_CHANGED, payload)
        if broadcast:
            self._bus.publish(topics.SYSTEM, {"kind": "setting", "key": key, "value": value})

    async def set_many(self, values: dict[str, Any]) -> None:
        for k, v in values.items():
            await self.set(k, v)
