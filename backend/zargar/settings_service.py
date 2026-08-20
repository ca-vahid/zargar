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
    "trading.confirm_before_submit": True,
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
    "risk.duplicate_window_seconds": 10,
    "risk.require_market_hours": False,     # enforce RTH for live orders
    # --- account -------------------------------------------------------------
    "account.regime": "ca",                 # ca | us — tax/day-trade rule set
    "account.day_trade_warnings": True,
    # --- signals / automation ------------------------------------------------
    "signals.default_ttl_minutes": 30,
    "signals.auto_execute_enabled": False,
    "signals.max_auto_notional": 500.0,
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
    "quotes.yahoo_poll_seconds": 3.0,
    # --- UI ----------------------------------------------------------------
    "ui.theme": "light",                    # light | dark (explicit saves win)
    "ui.accent": "#5b8cff",
    "ui.density": "comfortable",            # comfortable | compact
    "ui.default_symbol": "AAPL",
    "ui.chart.tf": "1m",
    "ui.chart.type": "candlestick",         # candlestick | ohlc | line
    "ui.chart.indicators": ["ema20", "vwap"],
    "ui.chart.show_volume": True,
    "ui.quote_flash": True,
    # --- signal sources registry (list of {name, emails, trust, notes}) -----
    "sources.registry": [],
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
