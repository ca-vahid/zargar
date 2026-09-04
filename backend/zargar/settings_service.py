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
    "execution.exit_inflight_ttl_seconds": 900, # an unfilled exit order older than this stops suppressing new exits (zombie guard)
    # --- the morning desk surface (POST-SOAK Phase 1) ---
    "desk.morning_at": "08:25",             # ET; the one-glance morning report (push + Telegram + Dashboard)
    "desk.morning_push": True,              # off = compose on demand only (GET /api/desk/morning)
    "desk.morning_push_until": "10:30",     # ET; past this a late (re)deploy composes without pushing
    "desk.roll_watchdog_at": "09:00",       # ET; rolls any plan the close missed (restart inside the close window)
    "desk.soak_at": "17:30",                # ET; nightly practice-soak scorecard (journaled, feeds the morning report)
    "signals.recovery_interval_seconds": 900,  # cold-park re-verify + error-content retry sweep cadence
    "execution.paused": False,                  # per-technique pause: set techniques.<id>.paused (kill switch stays global; exits are never blocked)
    "execution.arm_expired_plans": False,       # refuse arming a plan whose last session already closed (replays/tests set True; techniques.<id>.arm_expired_plans overrides)
    "research.chain_snapshots.enabled": True,   # nightly per-contract OI/IV/volume rows (history is NOT backfillable)
    "research.chain_snapshots.at": "16:30",     # ET
    "research.chain_snapshots.keep_days": 400,  # prune beyond this window (0 = keep forever)
    "research.chain_snapshots.skip_dead": True, # drop rows with 0 volume AND 0 OI (no signal, ~60% of the chain)
    "research.daily_bars.enabled": True,        # tf=1d bars for the universe into the bars table
    "research.daily_bars.at": "20:05",          # ET
    "research.daily_bars.range": "1mo",         # per-night fetch window (idempotent upserts)
    # --- extended-hours 1m bars + volatility indices (2026-09-03, Team2 desk; PLAN §3c B1/B2) ---
    "research.ext_bars.enabled": True,          # bank 04:00-20:00 ET 1m bars nightly (Yahoo keeps only ~20 days; a sweep needs more)
    "research.ext_bars.at": "20:10",            # ET, after the post-market closes
    "research.ext_bars.symbols": ["SPY", "QQQ", "IWM"],  # the Team2 universe; other techniques may add theirs
    "research.ext_bars.backfill_days": 20,      # calendar days to (re)fetch each night — idempotent upserts
    "research.vix.enabled": True,               # daily ^VIX / ^VIX1D closes into the bars table (tf=1d) — the IV proxy for the 0DTE premium scorer
    "research.vix.symbols": ["^VIX", "^VIX1D", "^VIX9D"],
    "research.macro_events": [],                # MANUAL macro calendar (FOMC/CPI/NFP...): [{date, name, kind, time}] — research/macro_calendar.py (placeholder source)

    "risk.max_day_notional_per_tag": 0.0,        # $ BUY notional per tag (e.g. source:xyz) per ET day (0 = off)

    "risk.stale_quote_seconds": 10,
    "risk.daily_loss_halt_pct": 3.0,
    "risk.daily_loss_halt_scope": "portfolio",   # portfolio (halt only the losing book) | global (the old switch)
    "execution.daily_loss_halt_pct": 0.0,        # per-TECHNIQUE day loss (% of the book) that pauses its plans; techniques.<id>.* overrides; 0 = off
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
    # --- Team2 technique (2026-09-03; docs/techniques/team2/PLAN.md D1-D14) --------------------------
    "techniques.team2.enabled": True,
    "techniques.team2.symbols": ["SPY", "QQQ", "IWM"],   # D2: fixed universe, no scan
    "techniques.team2.mode": "alert",                # alert | proposal | auto (earned the same way EM earned it)
    "techniques.team2.plan_at": "17:00",             # ET nightly skeleton (PDH/PDL zones, targets)
    "techniques.team2.preopen_at": "09:25",          # ET completion (PMH/PML, day type, sizing bucket)
    "techniques.team2.zero_dte": {                   # D3/E6: the per-technique 0DTE policy RiskGate enforces
        "enabled": True, "last_entry_et": "15:30", "flatten_et": "15:45", "max_contracts": 10, "premium_cap": 1000.0},
    "techniques.team2.dte_policy": "0dte",           # 0dte | 1dte (sweep variant)
    "techniques.team2.target_premium": 0.60,         # V1/F5: first OTM strike whose ask <= this
    "techniques.team2.premium_floor": 0.20,
    "techniques.team2.sigma_source": "vix1d",        # IV proxy for the premium model: vix1d | vix | chain
    "techniques.team2.fan_trend_min_atr": 0.60,      # E4 chop/trend threshold (EMA spread in 2m ATRs)
    "techniques.team2.pm_tol_atr": 0.25,             # D7 touch tolerance
    "techniques.team2.target_lookback_sessions": 10, # L3.1
    "techniques.team2.range_day_confirmation": True, # B3/A4
    "techniques.team2.pullback_max_touches": 2,      # D9
    "techniques.team2.pullback_max_bars": 8,         # A6
    "techniques.team2.pullback_body_mult": 2.0,      # A6/F4 engulfing filter
    "techniques.team2.entry_at": "both",             # ema | level | both (T1 pullbacks, T2 retests + T7 bases)
    "techniques.team2.allow_ema48_entries": True,    # E5 second line of defense
    "techniques.team2.allow_ema200_flush": True,     # T8 range-day trigger: 2m close through the 200 EMA
    "techniques.team2.base_bars": 3,                 # T7 break & base
    "techniques.team2.base_tol_atr": 1.0,
    "techniques.team2.trim_cue": "premium",          # premium | new_extreme (X1 "new high/low of day")
    "techniques.team2.chase_cap_mult": 1.5,          # F14: entry limit <= target_premium x this (the premium band)
    "techniques.team2.hod_target": "reentry",        # off | reentry | always (X3b running HOD/LOD as the target)
    "techniques.team2.hod_target_min_atr": 1.0,
    "techniques.team2.add_on_retest": True,          # X5 trim-and-add
    "techniques.team2.max_adds": 1,
    "techniques.team2.first_entry_min": "09:45",     # D6 (first 15m close)
    "techniques.team2.last_entry_min": "15:30",
    "techniques.team2.flatten_min": "15:45",         # C3
    "techniques.team2.premium_stop_pct": 25.0,       # D13/P1
    "techniques.team2.trim_1_pct": 50.0,             # V2
    "techniques.team2.trim_1_frac": 0.3333,
    "techniques.team2.trim_2_pct": 100.0,
    "techniques.team2.trim_2_frac": 0.3333,
    "techniques.team2.runner_exit": "ema_close",     # X2
    "techniques.team2.target_exit": True,            # X3/V11
    "techniques.team2.size_full": 1.0,               # V6/D4 buckets
    "techniques.team2.size_small": 0.5,
    "techniques.team2.max_reentries": 2,             # A8
    "techniques.team2.max_losses_per_day": 2,        # D-3
    "techniques.team2.max_concurrent_positions": 1,  # A12
    "techniques.team2.shrink_after_win": True,       # P7/D14
    "techniques.team2.avoid_event_days": False,      # D-4 (macro calendar placeholder)
    "techniques.team2.budget_per_trade": 2000.0,     # $ premium per full-size entry (user 2026-09-04: 500 -> 2000)
    "techniques.team2.risk_pct": 6.0,                # % of equity at risk per entry: 2000 x the 25% premium stop = $500 on the $8.5k practice book
    "techniques.team2.max_risk_pct": 6.0,            # Team2's own R1 cap (resolves via rt(); the shared default is 5)
    "techniques.team2.daily_loss_halt_pct": 10.0,    # Team2 pauses its own plans on a book after losing 10% of it today (~2 full stops)
    "techniques.team2.allow_live_auto": False,
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
    "techniques.tip.discord.watch": [],      # allowlist of DMs/channels the gateway monitors (UI-managed)
    "techniques.tip.analyst_enabled": True,  # the tips analyst (LLM + market tools, advisory)
    "techniques.tip.analyst_max_tools": 8,   # tool-call budget per tip
    "techniques.tip.analyst_model": "",      # empty = the extraction model
    "techniques.tip.analyst_notes_max": 12,  # shared-knowledge notes handed to each run
    "techniques.tip.review_enabled": True,   # analyst reviews non-tradable updates vs our positions
    "techniques.tip.allow_live_auto": False, # auto mode may self-approve into a LIVE portfolio
    "techniques.tip.max_contracts_per_tip": 25,  # hard cap on option qty per proposal — budget sizing on lotto premium is nonsense (277 × $0.09, 2026-08-31)
    # --- the lotto lane (0–3 DTE tips; user decision 2026-09-01) ---
    "techniques.tip.fan_in_min": 3,             # a message with >= N signals is appraised ONCE (siblings inherit the verdict)
    "techniques.tip.lotto_enabled": True,
    "techniques.tip.lotto_max_dte": 3,          # a stated contract expiring within N days is a lotto
    "techniques.tip.lotto_budget": 1500.0,      # $ per lotto tip (separate from budget_per_tip)
    "techniques.tip.lotto_flatten_et": "15:45", # expiry-day mandatory flatten (never hold through the close)
    "techniques.tip.lotto_premium_targets": "100,200",   # lotto profit-taking on the CONTRACT: +N% rungs (quote-tick judged)
    "techniques.tip.lotto_premium_fractions": "0.5,0.5", # fraction of the original size sold at each rung; rest floors at entry
    "techniques.tip.monetize_enabled": True,     # swing options: house-money take + ratchet floors on the CONTRACT (research 2026-09-04)
    "techniques.tip.monetize_take_at": 100.0,    # sell monetize_take_fraction when the premium is up N% (recoups the debit at 100/0.5)
    "techniques.tip.monetize_take_fraction": 0.5,
    "techniques.tip.monetize_floors": "50:15,100:50,200:120",  # peak-gain%:locked-floor% rungs; +100/+100 beyond; theta/IV tighten in code
    "techniques.tip.rollup_enabled": True,       # deep-ITM winner rolls to ~0.35 delta for a credit >= the debit (max 2)
    "techniques.tip.rollup_delta": 0.75,         # roll trigger: |delta| at/above this (or extrinsic <= 10% of premium)
    "techniques.tip.rollup_target_delta": 0.35,  # the strike the roll buys
    "techniques.tip.rollup_max": 2,              # rolls per position
    "techniques.tip.rollup_max_spread_pct": 10.0,  # skip illiquid legs (bid/ask spread % of mid, either leg)
    "techniques.tip.bleed_exit_enabled": True,   # exit an option bleeding bleed_exit_pct with the stock inside bleed_band_pct of entry (BBAI 09-04)
    "techniques.tip.bleed_exit_pct": 35.0,
    "techniques.tip.bleed_band_pct": 3.0,
    "techniques.tip.unattended": True,           # practice decides itself: analyst skip/watch DECLINES the card (recorded), promoted takes trade; live always waits for the human
    "techniques.tip.triage_at": "09:33",         # morning triage: re-appraise anything still pending against the live open
    "techniques.tip.auto_min_graded": 5,     # earned auto: closed tip positions a source needs before the platform-default auto self-approves
    "techniques.tip.auto_min_hit": 0.4,      # earned auto: minimum hit rate on those closed positions (explicit per-source auto bypasses both)
    "techniques.tip.retro_enabled": True,    # nightly analyst retro on closed tip positions
    "techniques.tip.retro_at": "17:10",      # ET, engine scheduler
    "techniques.tip.analyst_manage_enabled": True,  # analyst may adjust/trim OPEN tip positions (exit-only)
    "techniques.tip.mirror_max_messages": 50000,    # discord message mirror cap (oldest pruned; raised for 90d onboarding + context channels, 2026-08-30)
    "techniques.tip.note_ttl_daily_days": 14,       # daily:* digest notes expire after this (query-time)
    "techniques.tip.note_ttl_scoped_days": 90,      # ticker:*/source:* notes; citation in a live run refreshes
    "techniques.tip.digest_enabled": False,         # nightly context-channel digests (turn on once the digest-now prompt is trusted)
    "techniques.tip.dedupe_window_hours": 24,
    "techniques.tip.scorecard_min_n": 20,    # verified tips before a source can leave shadow
    "techniques.tip.stop_atr_mult": 1.0,     # ATR stop when the tip states none
    "techniques.tip.target_r": [1.5, 3.0],   # R-multiple targets when the tip states none
    "techniques.tip.instrument": "shares",   # FALLBACK vehicle for non-option tips; option-shaped
    #                                          tips arm as options via the per-tip vehicle rule
    "techniques.tip.touch_tolerance_pct": 0.002,   # level-touch band for tip triggers
    # options tips die at their contract's expiry — never wait for a level past it:
    "techniques.tip.entry_cutoff_dte": 2,    # stop trying to enter when < N calendar days to the tip's expiry
    # never-chase (ARM-GAPS C1): an armed fire pays at most the analyst's limit /
    # the tip's stated premium × (1 + this %) — above it the entry rests at the cap
    "techniques.tip.max_chase_pct": 10.0,
    # re-posted tips (ARM-GAPS D6): annotate the waiting plan; optionally extend
    # its horizon window / queue a fresh appraisal (only when a plan is live)
    "techniques.tip.seen_again_extends": False,
    "techniques.tip.seen_again_reappraise": True,
    # tip-scoped runner knobs (ARM-GAPS E1) — these win over the EM-named
    # legacy keys for TIP plans; EM keeps reading its own technique.* names
    "techniques.tip.enforce_session_windows": True,
    "techniques.tip.options_enabled": True,
    "techniques.tip.max_risk_pct": 5.0,
    # a tip entry FILL (auto mode) tells the phone via Telegram too (ARM-GAPS F5)
    "techniques.tip.telegram_fills": True,
    # the weekly rule audit (NEXT-GAPS A8): consolidate/expire the analyst's
    # rules; contradictions surface to the human, never self-resolved
    "techniques.tip.rule_audit_enabled": True,
    "techniques.tip.rule_audit_day": "Sat",   # ET weekday (Mon..Sun), runs with the nightly review
    # native multi-leg spreads (NEXT-GAPS M): SnapTrade ACCOUNT ids verified to
    # accept a legs-array order (Webull CA probes clean; Wealthsimple is 1156).
    # Empty = leg-sequencing everywhere except the simulator.
    "options.mleg_accounts": [],
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
    "techniques.flow.dte_min": 3,        # FL2: 0-2 DTE prints are expiry-board noise, never flagged
    "techniques.flow.dte_max": 45,
    "techniques.flow.premium_unit": 1_000_000.0,  # FL2: $ of flagged premium per score point (cap 3)
    # FL4: OFF until the thresholds earn it — when True, a confirmed high-score
    # read sent to Tips carries explicit_call conviction instead of implied
    "techniques.flow.calibrated": False,
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
    "options.provider": "cboe",             # chain browser/greeks/OI: cboe (free, ~15-min delayed) | tradier (token)
    "options.quotes_source": "alpaca",      # tracked-contract bid/ask/last: alpaca (real-time OPRA, Algo Trader Plus) | chain (delayed row)
    "options.enrich_seconds": 2,            # contract quote refresh cadence (OPRA batch call; was 5 on the delayed chain)
    "feed.exchange_bars": True,             # correct sampled 1m bars with real exchange OHLC/volume from the 1m history
    "options.fee_per_contract": 0.99,       # Webull CA: USD per contract (+ regulatory fees)
    "sim.reg_fee_per_contract": 0.05,       # practice fills: regulatory/exchange fees per contract on top (OCC/ORF/FINRA ≈ $0.05)
    "sim.stock_commission": 0.0,            # practice fills: flat commission per share trade — Webull CA charges $0 (audited 2026-09-01)
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
    # --- EM method ingestion (docs/techniques/enhanced-market/INGESTION-PLAN.md) - EM-ONLY.
    # The shared read-only Discord gateway forwards these channels to EM's inbox; the
    # em_ingest worker transcribes videos; extraction + board check are automatic;
    # ARMING IS HUMAN unless auto_arm is turned on. Never read by any other technique.
    "techniques.enhanced_market.discord.channels": [
        {"channelId": "1126325195301462117", "label": "em-alerts"},     # the pre-trading setups video + his alerts
        {"channelId": "1126364741779062974", "label": "watchlists"},    # morning board posts
    ],
    "techniques.enhanced_market.ingest.enabled": True,
    "techniques.enhanced_market.ingest.auto_transcribe": True,
    "techniques.enhanced_market.ingest.auto_extract": True,
    "techniques.enhanced_market.ingest.auto_plan_board": True,   # deterministic plan runs on the board's symbols (no LLM)
    "techniques.enhanced_market.ingest.auto_arm": False,         # proposes only; a human arms
    "techniques.enhanced_market.ingest.auto_arm_min_grade": "B",   # auto-arm only plans graded this or better (A > B > C)
    "techniques.enhanced_market.ingest.board_max_symbols": 12,
    "techniques.enhanced_market.ingest.transcribe_max_attempts": 5,
    "techniques.enhanced_market.ingest.live_recheck_seconds": 60,   # a still-live broadcast is re-probed this often (no attempt spent)
    "techniques.enhanced_market.ingest.live_max_wait_minutes": 45,  # then take whatever replay exists (partial) rather than wait forever
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
