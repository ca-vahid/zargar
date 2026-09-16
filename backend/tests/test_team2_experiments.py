"""Parallel Practice experiments (review team's GO, 2026-09-15): per-book rules, per-book counters, one plan per
(symbol, book), experiment books must be Practice books. Isolation: an experiment's settings cannot reach another
book through the shared `techniques.team2.*` settings."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zargar.execution.planrunner import ArmConfig, ArmedPlan, Trade
from zargar.models import Portfolio
from zargar.techniques.team2.rules import (EXPERIMENT_OVERRIDE_KEYS, Team2Rules, experiment_books, rules_for_book,
                                           rules_from_settings)

from .test_codex_team2_data_eod import bar, ms, rig
from .test_team2_runner import _bank, rig as engine_rig  # noqa: F401
from .test_team2_session import DAY, prev_day_bars, trend_day

CONTROL, SIZING, C1 = "book-control", "book-sizing", "book-c1"
EXP = {"enabled": True, "control": CONTROL, "books": [
    {"portfolioId": SIZING, "label": "team2-sizing-cap-2026-09", "role": "sizing", "overrides": {"size_full": 0.5}},
    {"portfolioId": C1, "label": "team2-c1-conjunction-2026-09", "role": "c1", "overrides": {"no_trade_zone": "conjunction"}},
]}


def _settings(exp=EXP, **shared):
    s = {"techniques.team2.experiments": exp}
    s.update(shared)
    return s


# ---------------------------------------------------------------- rules per book
def test_each_book_runs_its_own_override_and_nothing_else_changes():
    s = _settings()
    base = rules_from_settings(s)
    control, sizing, c1 = rules_for_book(s, CONTROL), rules_for_book(s, SIZING), rules_for_book(s, C1)
    assert control == base, "a book without an experiment entry runs the shared baseline exactly"
    assert sizing.size_full == 0.5 and sizing.no_trade_zone == base.no_trade_zone == "pm_range"
    assert c1.no_trade_zone == "conjunction" and c1.size_full == base.size_full == 1.0
    # everything else identical across the three books (C2, room rules, exits, adds, premium selection...)
    for name in ("key_levels", "pm_room_atr", "min_target_atr", "target_exit", "add_on_retest", "max_adds", "target_premium",
                 "premium_floor", "premium_pick", "trim_1_pct", "trim_2_pct", "premium_stop_pct", "max_losses_per_day",
                 "max_concurrent_positions", "size_small", "last_entry_min", "flatten_min"):
        assert getattr(sizing, name) == getattr(c1, name) == getattr(base, name), name
    assert rules_for_book(s, None) == base and rules_for_book(s, "unknown-book") == base


def test_the_shared_settings_stay_the_baseline_and_an_experiment_cannot_reach_another_book():
    s = _settings()
    assert rules_from_settings(s).size_full == 1.0 and rules_from_settings(s).no_trade_zone == "pm_range"
    # change the sizing experiment's override: only the sizing book moves
    s["techniques.team2.experiments"] = {"enabled": True, "control": CONTROL, "books": [
        {"portfolioId": SIZING, "label": "sizing", "role": "sizing", "overrides": {"size_full": 0.25}},
        {"portfolioId": C1, "label": "c1", "role": "c1", "overrides": {"no_trade_zone": "conjunction"}}]}
    assert rules_for_book(s, SIZING).size_full == 0.25
    assert rules_for_book(s, C1).size_full == 1.0 and rules_for_book(s, CONTROL).size_full == 1.0 and rules_from_settings(s).size_full == 1.0
    # disabled: every book runs the baseline, whatever the map says
    s["techniques.team2.experiments"]["enabled"] = False
    assert rules_for_book(s, SIZING) == rules_for_book(s, C1) == rules_from_settings(s)
    assert experiment_books(s) == []


def test_only_the_roles_override_and_a_combined_or_foreign_key_invalidates_the_whole_map():
    """Review of 41ec565: C1 and the sizing cap are never combined in one book, and a foreign key is never silently
    filtered — the map is invalid as a whole, nothing applies, the errors are reported."""
    import pytest as _pt
    assert set(EXPERIMENT_OVERRIDE_KEYS) == {"size_full", "no_trade_zone"}
    combined = _settings({"enabled": True, "control": CONTROL, "books": [
        {"portfolioId": C1, "label": "c1", "role": "c1", "overrides": {"no_trade_zone": "conjunction", "size_full": 0.5}}]})
    with _pt.raises(ValueError, match="never combined"):
        experiment_books(combined)
    assert rules_for_book(combined, C1) == rules_from_settings(combined)
    foreign = _settings({"enabled": True, "control": CONTROL, "books": [
        {"portfolioId": C1, "label": "c1", "role": "c1", "overrides": {"no_trade_zone": "conjunction", "key_levels": "D1"}}]})
    with _pt.raises(ValueError, match="may override exactly"):
        experiment_books(foreign)
    assert rules_for_book(foreign, C1).key_levels == "off" and rules_for_book(foreign, C1).no_trade_zone == "pm_range"


# ---------------------------------------------------------------- counters per book
def _plan(runner, run_id, pid, symbol="SPY"):
    ap = ArmedPlan(run_id=run_id, symbol=symbol, plan_for="2026-09-14", plan={"zones": {"present": True}, "openSource": "rth_open"},
                   config=ArmConfig(portfolio_id=pid, mode="auto", instrument="options", use_critic=False), trackers={}, armed_at=0)
    runner._armed[run_id] = ap
    return ap


def _loser(tid):
    return Trade(trigger_id=tid, kind="scenario_1", direction="long", fired_ts=ms(10, 0), window="team2", entry=100, stop=99, targets=[104],
                 status="closed", filled_qty=2, realized_pnl=-80.0, instrument="options")


def test_loss_counters_and_concurrency_are_per_book():
    runner, _ = rig()
    runner._armed.clear(); runner._loss_tally = {}
    a1, a2, b1 = _plan(runner, "a1", SIZING), _plan(runner, "a2", SIZING, "QQQ"), _plan(runner, "b1", C1)
    a1.trades["x#1"] = _loser("x#1"); a2.trades["y#1"] = _loser("y#1")
    b1.trades["z#1"] = Trade(trigger_id="z#1", kind="scenario_1", direction="long", fired_ts=ms(10, 0), window="team2", entry=100,
                             stop=99, targets=[104], status="open", filled_qty=2, remaining=2, instrument="options")
    day = "2026-09-14"
    assert runner.losses_across_plans(day, SIZING) == 2 and runner.losses_across_plans(day, C1) == 0 and runner.losses_across_plans(day) == 2
    assert runner.losses_basis(day, SIZING) == "book"
    assert runner.open_positions_across_plans(C1) == 1 and runner.open_positions_across_plans(SIZING) == 0 and runner.open_positions_across_plans() == 1


async def test_one_books_loss_cap_and_open_position_never_block_another_books_fire(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner, _ = rig()
    runner._armed.clear(); runner._loss_tally = {}
    a1, b1 = _plan(runner, "a1", SIZING), _plan(runner, "b1", C1)
    a1.trades["x#1"] = _loser("x#1"); a1.trades["x#2"] = _loser("x#2")            # the sizing book is done for the day
    runner._fire_rest = AsyncMock()
    runner.rules = lambda: Team2Rules()                 # the desk-wide cap ON (the reviewer rig turns it off)
    monkeypatch.setattr(module.time, "time", lambda: ms(10, 2) / 1000)
    fire = {"event": "fire", "ts": ms(10, 2), "setup": "scenario_1@09:45", "touch": 1, "spot": 101.0, "target": 104.0, "targetKind": "plan",
            "regime": {"stack": "bull", "atr": 1}, "entryKind": "ema", "why": "fixture", "sizeMult": 1}
    res = SimpleNamespace(setups=[{"id": "scenario_1@09:45", "kind": "scenario_1", "direction": "long", "target": 104.0}])
    await runner._fire_from_event(a1, fire, bar(10, 1), res, halted=False, journal=False)
    assert runner._fire_rest.await_count == 0 and "skip_loss_cap_desk" in [c.args[1] for c in runner._log.call_args_list]
    await runner._fire_from_event(b1, fire, bar(10, 1), res, halted=False, journal=False)
    assert runner._fire_rest.await_count == 1, "the C1 book's fire is not blocked by the sizing book's losses"


# ---------------------------------------------------------------- one plan per (symbol, book)
async def test_nightly_plans_mint_one_labelled_plan_per_book_under_that_books_rules_and_refuse_a_live_book(engine_rig):
    eng, sim = engine_rig
    sizing = Portfolio(id=uuid.uuid4().hex, name="Team2 Sizing 0.5", kind="sim", starting_cash=10_000.0, cash=10_000.0)
    c1 = Portfolio(id=uuid.uuid4().hex, name="Team2 C1 Conjunction", kind="sim", starting_cash=10_000.0, cash=10_000.0)
    live = Portfolio(id=uuid.uuid4().hex, name="Webull", kind="live", starting_cash=10_000.0, cash=10_000.0)
    async with eng.sf() as session:
        session.add_all([sizing, c1, live]); await session.commit()
    for p in (sizing, c1, live):
        eng.positions.register_portfolio(p)
    await eng.settings.set("techniques.team2.default_portfolio", sim["id"], journal=False)
    # a live-kind book anywhere in the map makes the WHOLE map invalid: nothing experimental is minted, the errors are reported
    await eng.settings.set("techniques.team2.experiments", {"enabled": True, "control": sim["id"], "books": [
        {"portfolioId": sizing.id, "label": "team2-sizing-cap-2026-09", "role": "sizing", "overrides": {"size_full": 0.5}},
        {"portfolioId": c1.id, "label": "team2-c1-conjunction-2026-09", "role": "c1", "overrides": {"no_trade_zone": "conjunction"}},
        {"portfolioId": live.id, "label": "never-real-money", "role": "sizing", "overrides": {"size_full": 0.5}}]}, journal=False)
    prev = prev_day_bars(); today, _ = trend_day(prev)
    await _bank(eng, prev)
    bad = await eng.team2.nightly_plans(DAY.isoformat(), arm=False)
    assert [r["portfolioId"] for r in bad["runs"]] == [sim["id"]] and any("never real money" in f for f in bad["failed"]), bad
    # the valid three-book map
    await eng.settings.set("techniques.team2.experiments", {"enabled": True, "control": sim["id"], "books": [
        {"portfolioId": sizing.id, "label": "team2-sizing-cap-2026-09", "role": "sizing", "overrides": {"size_full": 0.5}},
        {"portfolioId": c1.id, "label": "team2-c1-conjunction-2026-09", "role": "c1", "overrides": {"no_trade_zone": "conjunction"}}]}, journal=False)
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    assert len(out["runs"]) == 3 and len(out["armed"]) == 3, out
    assert not out["failed"], out["failed"]
    by_book = {r["portfolioId"]: r for r in out["runs"]}
    assert set(by_book) == {sim["id"], sizing.id, c1.id}
    assert by_book[sim["id"]]["label"] == "" and by_book[sizing.id]["label"] == "team2-sizing-cap-2026-09"
    for pid, r in by_book.items():
        ap = eng.team2_runner.get(r["runId"])
        assert ap is not None and ap.config.portfolio_id == pid
    # the rules stamped on each run are that book's rules; the shared settings are still the baseline
    from sqlalchemy import select
    from zargar.models import TechniqueRun
    async with eng.sf() as session:
        runs = {r.id: r for r in (await session.execute(select(TechniqueRun).where(TechniqueRun.technique == "team2"))).scalars().all()}
    th = {pid: runs[r["runId"]].config["thresholds"] for pid, r in by_book.items()}
    assert th[sizing.id]["size_full"] == 0.5 and th[sizing.id]["no_trade_zone"] == "pm_range"
    assert th[c1.id]["no_trade_zone"] == "conjunction" and th[c1.id]["size_full"] == 1.0
    assert th[sim["id"]]["size_full"] == 1.0 and th[sim["id"]]["no_trade_zone"] == "pm_range"
    assert runs[by_book[c1.id]["runId"]].config["experiment"]["label"] == "team2-c1-conjunction-2026-09"
    assert rules_from_settings(eng.settings).size_full == 1.0 and rules_from_settings(eng.settings).no_trade_zone == "pm_range"
    # a second nightly run for the same session mints nothing new on any book
    again = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    assert again["runs"] == [] and len(again["skipped"]) == 3
