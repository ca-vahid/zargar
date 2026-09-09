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


# ---------------------------------------------------------- glide sizing
async def test_glide_budget_full_then_glides_then_floors(rig):
    """2026-09-07: budget = min(budget_per_tip, free cash / reserve_slots) —
    full size early, gliding down as the book fills, minimum expression late,
    refusal only when the book is truly empty."""
    from zargar.signals.sources import resolve_policy
    eng = rig
    svc = eng.proposals
    await eng.settings.set("techniques.tip.budget_per_tip", 2000.0)
    policy = resolve_policy(eng.settings, "GlideSrc")
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    pf = eng.positions.portfolio(pid)

    pf["cash"] = 10_000.0                              # plenty: full budget, no note
    b, note, refuse = await svc._tip_budget(policy, pid)
    assert (b, note, refuse) == (2000.0, None, None)

    pf["cash"] = 4_500.0                               # glide: 4500/3 = 1500
    b, note, refuse = await svc._tip_budget(policy, pid)
    assert b == 1500.0 and refuse is None and "reserve" in note

    pf["cash"] = 900.0                                 # under the floor: min expression
    b, note, refuse = await svc._tip_budget(policy, pid)
    assert b == 500.0 and refuse is None

    pf["cash"] = 300.0                                 # floor bounded by actual cash
    b, note, refuse = await svc._tip_budget(policy, pid)
    assert b == 300.0 and refuse is None

    pf["cash"] = 30.0                                  # truly empty: refuse, on record
    b, note, refuse = await svc._tip_budget(policy, pid)
    assert b == 0.0 and "book full" in refuse

    await eng.settings.set("techniques.tip.reserve_slots", 0)   # 0 = off
    pf["cash"] = 30.0
    b, note, refuse = await svc._tip_budget(policy, pid)
    assert b == 2000.0 and refuse is None
    pf["cash"] = 10_000.0


async def test_source_open_caps_are_enforced_now(rig):
    """max_open_tips and budget_open_max were parsed but enforced NOWHERE —
    the glide helper makes them real (count gate refuses, $ cap shrinks)."""
    from zargar.models import ManagedPositionRow
    from zargar.signals.sources import resolve_policy
    eng = rig
    svc = eng.proposals
    await eng.settings.set("techniques.tip.sources",
                           {"CapSrc": {"max_open_tips": 2, "budget_open_max": 3000.0}})
    policy = resolve_policy(eng.settings, "CapSrc")
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    eng.positions.portfolio(pid)["cash"] = 10_000.0

    async with eng.sf() as session:                     # one open $2,500 position
        session.add(ManagedPositionRow(
            id=new_id(), technique="tip", symbol="AAA", portfolio_id=pid,
            status="open", tags=["source:CapSrc"], config={},
            legs=[{"symbol": "AAA", "secType": "STK", "qty": 25, "avgFill": 100.0}],
            state={}))
        await session.commit()
    b, note, refuse = await svc._tip_budget(policy, pid)
    assert refuse is None and b == 500.0                # 3000 cap - 2500 open = 500 room
    assert "remaining open budget" in note

    async with eng.sf() as session:                     # second open position: count gate
        session.add(ManagedPositionRow(
            id=new_id(), technique="tip", symbol="BBB", portfolio_id=pid,
            status="open", tags=["source:CapSrc"], config={},
            legs=[{"symbol": "BBB", "secType": "STK", "qty": 1, "avgFill": 10.0}],
            state={}))
        await session.commit()
    b, note, refuse = await svc._tip_budget(policy, pid)
    assert b == 0.0 and "max_open_tips" in refuse

    # other sources are unaffected by CapSrc's positions
    other = resolve_policy(eng.settings, "OtherSrc")
    b, note, refuse = await svc._tip_budget(other, pid)
    assert refuse is None and b > 0


# ---------------------------------------------------------- retro cursor
async def test_retro_reaches_position_51(rig):
    """Codex audit 2026-09-08 finding 5: 'oldest 50 then filter reviewed'
    starved newer closures once 50 tagged rows sat older than them. The keyset
    cursor filters eligibility before the cap and reports the real backlog."""
    import datetime as _dt

    from zargar.models import ManagedPositionRow
    from zargar.techniques.tip.retro import run_tip_retros
    eng = rig
    await eng.settings.set("techniques.tip.retro_enabled", True)
    old = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=5)
    async with eng.sf() as session:
        for i in range(55):                       # 55 already-reviewed, OLD rows
            session.add(ManagedPositionRow(
                id=new_id(), technique="tip", symbol=f"T{i:02d}", portfolio_id="p1",
                status="closed", tags=["retro-done"], config={}, legs=[],
                state={}, created_at=old, updated_at=old))
        session.add(ManagedPositionRow(              # position 56: NEW, unreviewed
            id="pos-51", technique="tip", symbol="NEWP", portfolio_id="p1",
            status="closed", tags=["source:S"],
            config={"direction": "long", "entry": 10.0, "risk": 1.0, "policy": {}},
            legs=[{"symbol": "NEWP", "secType": "STK", "qty": 0, "avgFill": 10.0}],
            state={"realizedPnl": 5.0, "exits": [], "events": []}))
        await session.commit()

    class _NoLLM:                                  # count eligibility only
        pass
    out = await run_tip_retros(eng, client=None, limit=0)   # limit 0: census only
    assert out["backlog"] == 1, out
    assert out["oldestUnreviewedAgeDays"] is not None


# ---------------------------------------------------------- session brake
async def test_adoption_killswitch_reads_persisted_reason_and_skips_shadow(rig):
    """2026-09-08: the brake read state.closeReason, which was never persisted
    (dormant); it also counted SHADOW-book deaths (GME research noise). Now:
    a real-book stop-out < 5 min pauses autos; shadow deaths never do."""
    from zargar.models import ManagedPositionRow
    from zargar.techniques.tip.lifecycle import adoption_killswitch
    eng = rig
    sim_pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    shadow = await eng.signals_service.shadow_portfolio("BrakeSrc", "immediate")

    async def add_closed(pid: str, sym: str):
        async with eng.sf() as session:
            session.add(ManagedPositionRow(
                id=new_id(), technique="tip", symbol=sym, portfolio_id=pid,
                status="closed", tags=["source:BrakeSrc"], config={}, legs=[],
                state={"closeReason": "venue-side GTC stop", "realizedPnl": -5.0}))
            await session.commit()

    assert await adoption_killswitch(eng) is None          # clean day
    await add_closed(shadow["id"], "GME")                  # research noise
    assert await adoption_killswitch(eng) is None
    await add_closed(sim_pid, "AAA")                       # real book: brake
    reason = await adoption_killswitch(eng)
    assert reason and "AAA" in reason and "paused" in reason


def test_close_reason_rides_to_dict():
    """The Managed dataclass now carries close_reason (the brake reads the
    persisted state.closeReason — it was never written before 2026-09-08)."""
    from zargar.execution.positions import Managed
    p = Managed(id="x", portfolio_id="p", symbol="T", direction="long",
                technique="tip", policy={}, legs=[], entry=100.0, risk=1.0)
    p.close_reason = "bar closed through the stop"
    assert p.to_dict().get("closeReason") == "bar closed through the stop"


# ---------------------------------------------------------- premium cap
async def test_premium_cap_sizes_down(rig):
    svc = rig.proposals
    # BBAI shape: $0.51 contract, budget $5,000 → 25 via contracts cap; the
    # $750 premium cap cuts it to 14; a $9.00 contract still buys 1
    assert svc._cap_premium(25, 0.51) == 14
    assert svc._cap_premium(3, 9.0) == 1
    await rig.settings.set("techniques.tip.max_premium_per_tip", 0)
    assert svc._cap_premium(25, 0.51) == 25      # 0 = off
