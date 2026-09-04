"""Platform plan phases 0+1 (docs/TECHNIQUE-PLATFORM-PLAN.md): the shared
market-structure library stands on its own, the old import paths still work,
the technique registry lists EM, and the tracker's schedule is a parameter."""
from __future__ import annotations

import importlib
import subprocess
import sys

from zargar.domain import Bar
from zargar.marketstructure import (
    DEFAULT_MARKET_RULES, SESSION_WINDOWS, MarketRules, TriggerTracker, count_touches, distance_pct, session_bounds,
)
from zargar.techniques import ENHANCED_MARKET, all_techniques, get_technique


def test_library_imports_without_the_technique_package():
    """The library must never depend on a technique: importing it in a fresh
    interpreter must not pull `zargar.technique` in."""
    code = ("import sys, zargar.marketstructure; "
            "print(sorted(k for k in sys.modules if k.startswith('zargar.technique')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]", out


def test_old_import_paths_are_shims_to_the_library():
    for name in ("levels", "volume", "candles", "structure", "history", "outcome"):
        old = importlib.import_module(f"zargar.technique.{name}")
        new = importlib.import_module(f"zargar.marketstructure.{name}")
        # functions and classes must be the SAME objects (module-level state such as
        # `history._sem` is re-created by the library itself and may legitimately differ)
        public = [k for k in vars(new) if not k.startswith("__") and callable(getattr(new, k))]
        assert public, name
        for k in public:
            assert getattr(old, k) is getattr(new, k), (name, k)
    from zargar.technique import rulebook, walkforward
    from zargar.marketstructure import tracker, sessions
    assert walkforward.TriggerTracker is tracker.TriggerTracker
    assert rulebook.session_window is sessions.session_window
    assert rulebook.PRIME_WINDOWS == sessions.PRIME_WINDOWS


def test_em_thresholds_are_duck_compatible_with_market_rules():
    from zargar.technique.rulebook import DEFAULT_THRESHOLDS
    for f in MarketRules.__dataclass_fields__:
        assert hasattr(DEFAULT_THRESHOLDS, f), f
        assert getattr(DEFAULT_THRESHOLDS, f) == getattr(DEFAULT_MARKET_RULES, f), f


def test_registry_lists_enhanced_market():
    # EM stays first (the default); tip + flow joined 2026-08-27 (wave one)
    ids = [t.id for t in all_techniques()]
    assert ids[0] == "enhanced_market"
    assert set(ids) == {"enhanced_market", "tip", "flow", "team2"}   # team2 joined 2026-09-03 (Team2 desk)
    assert get_technique("enhanced_market") is ENHANCED_MARKET
    d = ENHANCED_MARKET.to_dict()
    assert d["label"] == "EM Options" and d["page"] == "technique" and "validation" in d["tabs"]
    assert get_technique("tip").settings_prefix == "techniques.tip."
    assert get_technique("flow").settings_prefix == "techniques.flow."


def test_order_intent_carries_the_technique_id():
    from zargar.execution.exits import reduce_only_exit_intent
    from zargar.orders import OrderIntent
    i = OrderIntent(portfolio_id="p", symbol="AAPL", side="BUY", qty=1, technique_id="enhanced_market")
    assert i.technique_id == "enhanced_market" and i.source == "manual"
    x = reduce_only_exit_intent(portfolio_id="p", symbol="AAPL", sec_type="STK", qty=1, technique_id="tip")
    assert x.technique_id == "tip" and x.reduce_only and x.source == "technique"


def _bar(ts: int, px: float, vol: int = 1000) -> Bar:
    return Bar(symbol="X", tf="1m", ts=ts, open=px, high=px + 0.05, low=px - 0.05, close=px, volume=vol)


def test_tracker_windows_are_a_parameter_not_a_book_rule():
    """The same state machine, two schedules: EM's prime windows keep a mid-day
    touch watch-only; a technique that trades all day may fire on it."""
    trigger = {"id": "b1", "kind": "bounce", "direction": "long", "setupType": "support_bounce",
               "entry": {"price": 100.0, "basis": "at_level"}, "stop": {"price": 99.0, "reference": "below_support"},
               "targets": [{"price": 101.0}, {"price": 102.0}, {"price": 103.0}], "valid": True}
    open_ms = session_bounds("2026-08-27")[0]
    midday = open_ms + 3 * 3600_000                       # 12:30 ET
    bars = [_bar(open_ms, 101.0), _bar(open_ms + 60_000, 101.0)]   # opening bars, no gap, level not touched
    touch = _bar(midday, 100.0)                            # trades into the level at mid-day on real volume

    em = TriggerTracker(trigger, DEFAULT_MARKET_RULES, None, True, True, 101.0)
    for i, b in enumerate(bars):
        em.on_bar(b, i)
    em_status = em.on_bar(touch, len(bars))
    assert em_status != "fired" and em.observed_midday, em_status

    all_day = MarketRules(windows=SESSION_WINDOWS)
    tr = TriggerTracker(trigger, all_day, None, True, True, 101.0)
    for i, b in enumerate(bars):
        tr.on_bar(b, i)
    assert tr._window_ok(midday) and not em._window_ok(midday)


def test_distance_and_touches_helpers():
    assert round(distance_pct(100.0, 101.0), 2) == 1.0
    assert round(distance_pct(100.0, 99.0), 2) == -1.0
    bars = [_bar(1, 100.02), _bar(2, 100.5), _bar(3, 100.03)]
    assert count_touches(bars, 100.0, 0.1, "support") == 2
