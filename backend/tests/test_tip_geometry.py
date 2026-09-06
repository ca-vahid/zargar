"""Adoption-geometry gate + per-tip premium cap + rule-family dedupe
(2026-09-04: the analyst's nine-strike rule made deterministic)."""
import datetime as dt

import pytest

from zargar.domain import Bar, new_id
from zargar.engine import Engine
from zargar.signals.service import SignalService, attach_signal_layer
from zargar.techniques.tip.lifecycle import check_exit_geometry

from .conftest import make_test_config


def _bars(entry: float, *, rng: float = 1.0, low: float | None = None, n: int = 60):
    """Flat tape around `entry` with true range ~rng; optional deeper swing low."""
    out = []
    for i in range(n):
        lo = entry - rng / 2
        hi = entry + rng / 2
        if low is not None and i == n // 2:
            lo = low
        out.append(Bar(symbol="X", tf="15m", ts=i * 900_000,
                       open=entry, high=hi, low=lo, close=entry))
    return out


class _Settings:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, key, default=None):
        return self.kv.get(key, default)


def test_wrong_side_targets_dropped():
    plan = {"targets": [98.0, 105.0], "fractions": [0.5, 0.5], "underlyingStop": 95.0}
    out, repairs = check_exit_geometry(plan, direction="long", entry_ref=100.0,
                                       bars=_bars(100.0), settings=_Settings())
    assert out["targets"] == [105.0]
    assert out["fractions"] == [0.5]
    assert any("wrong side" in r for r in repairs)


def test_penny_target_dropped():
    # ATR ~1 → tp floor ~0.5; a +0.10 target is spread donation (HOOD 2026-09-02)
    plan = {"targets": [100.10, 103.0], "fractions": [0.5, 0.5], "underlyingStop": 95.0}
    out, repairs = check_exit_geometry(plan, direction="long", entry_ref=100.0,
                                       bars=_bars(100.0), settings=_Settings())
    assert out["targets"] == [103.0]
    assert any("noise floor" in r for r in repairs)


def test_wrong_side_stop_replaced():
    # MU 2026-09-03: long adopted with the stop ABOVE entry — fired instantly
    plan = {"targets": [105.0], "fractions": [1.0], "underlyingStop": 100.5}
    out, repairs = check_exit_geometry(plan, direction="long", entry_ref=100.0,
                                       bars=_bars(100.0), settings=_Settings())
    assert out["underlyingStop"] < 100.0
    assert any("re-placed stop" in r and "wrong side" in r for r in repairs)


def test_stop_inside_structure_widened():
    # stop clears the % floor but sits ABOVE the swing low (MU ninth strike)
    bars = _bars(100.0, rng=0.4, low=97.0)
    plan = {"targets": [105.0], "fractions": [1.0], "underlyingStop": 98.5}
    out, repairs = check_exit_geometry(plan, direction="long", entry_ref=100.0,
                                       bars=bars, settings=_Settings())
    assert out["underlyingStop"] < 97.0          # below the swing low minus buffer
    assert any("re-placed stop" in r for r in repairs)


def test_short_mirror():
    plan = {"targets": [103.0, 95.0], "fractions": [0.5, 0.5], "underlyingStop": 99.0}
    out, repairs = check_exit_geometry(plan, direction="short", entry_ref=100.0,
                                       bars=_bars(100.0), settings=_Settings())
    assert out["targets"] == [95.0]
    assert out["underlyingStop"] > 100.0


def test_valid_plan_untouched():
    plan = {"targets": [103.0, 106.0], "fractions": [0.5, 0.5], "underlyingStop": 96.0}
    out, repairs = check_exit_geometry(plan, direction="long", entry_ref=100.0,
                                       bars=_bars(100.0), settings=_Settings())
    assert repairs == []
    assert out["targets"] == [103.0, 106.0] and out["underlyingStop"] == 96.0


def test_stopless_option_plan_passes():
    out, repairs = check_exit_geometry({"targets": [110.0]}, direction="long",
                                       entry_ref=100.0, bars=_bars(100.0),
                                       settings=_Settings())
    assert repairs == [] and out.get("underlyingStop") is None


# ---------------------------------------------------------- rule families
def test_rule_family_extraction():
    fam = SignalService._rule_family
    assert fam("RULE (adoption geometry — NINTH strike, MU): ...") == "adoption geometry"
    assert fam("RULE (adoption geometry check — reject any managed plan): x") == "adoption geometry"
    assert fam("RULE (extends the watchlist rule): ...") is None       # no family claim
    assert fam("RULE (new, sits beside the fill-band rule): ...") is None
    assert fam("RULE (stop placement): ...") == "stop placement"       # a real family
    assert fam("plain note, no rule prefix") is None


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def test_new_rule_supersedes_family(rig):
    svc = rig.signals_service
    a = await svc.add_tip_note("rule", "RULE (adoption geometry — FIRST strike): sign-check levels.")
    b = await svc.add_tip_note("rule", "RULE (adoption geometry — SECOND strike): sign + width.")
    c = await svc.add_tip_note("rule", "RULE (lotto tape filter): unrelated family.")
    from zargar.models import TipNote
    async with rig.sf() as session:
        ra = await session.get(TipNote, a["id"])
        rc = await session.get(TipNote, c["id"])
    assert ra.superseded_by == b["id"]           # same family: auto-superseded
    assert rc.superseded_by is None              # other families untouched


# ---------------------------------------------------------- premium cap
async def test_premium_cap_sizes_down(rig):
    svc = rig.proposals
    # BBAI shape: $0.51 contract, budget $5,000 → 25 via contracts cap; the
    # $750 premium cap cuts it to 14; a $9.00 contract still buys 1
    assert svc._cap_premium(25, 0.51) == 14
    assert svc._cap_premium(3, 9.0) == 1
    await rig.settings.set("techniques.tip.max_premium_per_tip", 0)
    assert svc._cap_premium(25, 0.51) == 25      # 0 = off
