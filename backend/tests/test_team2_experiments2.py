"""Parallel experiments — the boundaries from the review of 41ec565: the validated schema, frozen per-plan rules,
sim-only at every arm, transition inventory (old books retired or paused, exposure preserved), forced replan refused
with exposure, and a receipt that cannot be falsely green."""
from __future__ import annotations

import io
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zargar.execution.planrunner import ArmConfig, ArmedPlan, Trade
from zargar.models import Portfolio
from zargar.techniques.team2.rules import (EXPERIMENT_ROLES, Team2Rules, apply_overrides, experiment_books, rules_for_book,
                                           rules_from_settings, validate_experiments)
from zargar.techniques.team2.service import Team2Service

from .test_codex_team2_data_eod import ms, rig
from .test_team2_runner import _bank, rig as engine_rig  # noqa: F401
from .test_team2_session import DAY, prev_day_bars, trend_day

GOOD = {"enabled": True, "control": "ctl", "books": [
    {"portfolioId": "siz", "label": "team2-sizing-cap-2026-09", "role": "sizing", "overrides": {"size_full": 0.5}},
    {"portfolioId": "c1b", "label": "team2-c1-conjunction-2026-09", "role": "c1", "overrides": {"no_trade_zone": "conjunction"}}]}
SIM = {"ctl": {"kind": "sim"}, "siz": {"kind": "sim"}, "c1b": {"kind": "sim"}, "real": {"kind": "live"}, "old": {"kind": "sim", "archived": True}}


def _s(exp):
    return {"techniques.team2.experiments": exp}


# ---------------------------------------------------------------- 1. the schema
def test_a_valid_three_book_map_yields_one_override_per_role_and_nothing_else():
    v = validate_experiments(_s(GOOD), portfolio_lookup=SIM.get)
    assert v["errors"] == [] and v["control"] == "ctl" and {b["role"] for b in v["books"]} == set(EXPERIMENT_ROLES)
    assert rules_for_book(_s(GOOD), "siz").size_full == 0.5 and rules_for_book(_s(GOOD), "siz").no_trade_zone == "pm_range"
    assert rules_for_book(_s(GOOD), "c1b").no_trade_zone == "conjunction" and rules_for_book(_s(GOOD), "c1b").size_full == 1.0
    assert rules_for_book(_s(GOOD), "ctl") == rules_from_settings(_s(GOOD))


@pytest.mark.parametrize("bad, needle", [
    ({**GOOD, "books": [{"portfolioId": "mix", "label": "x", "role": "sizing", "overrides": {"size_full": .5, "no_trade_zone": "conjunction"}}]}, "never combined"),
    ({**GOOD, "books": [{"portfolioId": "real", "label": "", "role": "sizing", "overrides": {"size_full": .5}}]}, "label is required"),
    ({**GOOD, "books": [{"portfolioId": "real", "label": "r", "role": "sizing", "overrides": {"size_full": .5}}]}, "never real money"),
    ({**GOOD, "books": [{"portfolioId": "old", "label": "o", "role": "sizing", "overrides": {"size_full": .5}}]}, "archived"),
    ({**GOOD, "books": [{"portfolioId": "siz", "label": "s", "role": "sizing", "overrides": {"key_levels": "D1"}}]}, "may override exactly"),
    ({**GOOD, "books": [{"portfolioId": "siz", "label": "s", "role": "sizing", "overrides": {"size_full": 1.0}}]}, "strictly between 0 and 1"),
    ({**GOOD, "books": [{"portfolioId": "c1b", "label": "c", "role": "c1", "overrides": {"no_trade_zone": "pm_range"}}]}, "must be 'conjunction'"),
    ({**GOOD, "books": [{"portfolioId": "ctl", "label": "c", "role": "sizing", "overrides": {"size_full": .5}}]}, "control book cannot also be an experiment"),
    ({**GOOD, "books": GOOD["books"] + [dict(GOOD["books"][0], label="dup")]}, "duplicate portfolioId"),
    ({**GOOD, "books": [GOOD["books"][0], dict(GOOD["books"][0], portfolioId="c1b", label="other")]}, "duplicate role"),
    ({**GOOD, "control": ""}, "control portfolioId is required"),
    ({**GOOD, "books": [dict(GOOD["books"][0], extra=1)]}, "unknown keys"),
    ({**GOOD, "books": []}, "non-empty list"),
])
def test_an_invalid_map_is_invalid_as_a_whole_applies_nothing_and_reports(bad, needle):
    v = validate_experiments(_s(bad), portfolio_lookup=SIM.get)
    assert v["errors"] and any(needle in e for e in v["errors"]), v["errors"]
    assert v["books"] == [], "nothing is applied while any error exists"
    if validate_experiments(_s(bad))["errors"]:                  # detectable without the portfolio lookup
        with pytest.raises(ValueError):
            experiment_books(_s(bad))
        assert rules_for_book(_s(bad), "siz") == rules_from_settings(_s(bad)), "an invalid map never reaches a book"


def test_a_disabled_or_absent_map_applies_nothing_without_errors():
    assert validate_experiments(_s({**GOOD, "enabled": False}))["books"] == [] and validate_experiments(_s({**GOOD, "enabled": False}))["errors"] == []
    assert validate_experiments({})["enabled"] is False and experiment_books({}) == []
    assert apply_overrides(Team2Rules(), {"size_full": .5, "no_trade_zone": "conjunction"}) == Team2Rules(), "a combined stamp is never applied either"


# ---------------------------------------------------------------- 2. frozen per-plan rules + sim-only arm
def test_the_plans_stamped_override_is_frozen_the_live_map_cannot_flip_an_armed_book():
    runner, _ = rig()
    runner.rules = lambda: Team2Rules()
    ap = ArmedPlan(run_id="siz-1", symbol="SPY", plan_for="2026-09-16", trackers={}, armed_at=0,
                   plan={"zones": {}, "experiment": {"label": "team2-sizing-cap-2026-09", "role": "sizing", "portfolioId": "siz", "overrides": {"size_full": 0.5}}},
                   config=ArmConfig(portfolio_id="siz", mode="auto", instrument="options", use_critic=False))
    runner.engine.settings = _s({**GOOD, "enabled": False})              # the map is DISABLED / edited underneath
    assert runner.rules_for(ap).size_full == 0.5, "the armed sizing book keeps its stamped rules"
    runner.engine.settings = _s({**GOOD, "books": [dict(GOOD["books"][0], overrides={"size_full": 0.25})]})
    assert runner.rules_for(ap).size_full == 0.5, "editing the map does not reach the armed plan"
    bare = ArmedPlan(run_id="ctl-1", symbol="SPY", plan_for="2026-09-16", trackers={}, armed_at=0, plan={"zones": {}},
                     config=ArmConfig(portfolio_id="ctl", mode="auto", instrument="options", use_critic=False))
    assert runner.rules_for(bare) == Team2Rules()


async def test_an_experiment_plan_can_only_be_armed_on_its_own_practice_book(monkeypatch):
    runner, _ = rig()
    plan = {"experiment": {"label": "team2-sizing-cap-2026-09", "role": "sizing", "portfolioId": "siz", "overrides": {"size_full": 0.5}}}
    runner.load_plan = AsyncMock(return_value={"id": "r1", "symbol": "SPY", "result": {"plan": plan}, "config": {}})
    runner.engine.positions = SimpleNamespace(portfolio=lambda pid: SIM.get(pid))
    from zargar.execution import planrunner as shared
    called = []
    monkeypatch.setattr(shared.PlanRunner, "arm", AsyncMock(side_effect=lambda *a, **k: called.append((a, k)) or {"ok": True}))
    with pytest.raises(ValueError, match="never real money"):
        await runner.arm("r1", {"mode": "auto", "portfolioId": "real"})
    with pytest.raises(ValueError, match="minted for book siz"):
        await runner.arm("r1", {"mode": "auto", "portfolioId": "c1b"})
    with pytest.raises(ValueError, match="never real money"):
        await runner.arm("r1", {"mode": "auto", "portfolioId": "old"}, restored=True)
    assert called == []
    await runner.arm("r1", {"mode": "auto", "portfolioId": "siz"})
    assert len(called) == 1 and called[0][0][1]["portfolioId"] == "siz"


# ---------------------------------------------------------------- 3. transitions
def _svc(settings, armed, portfolios=SIM):
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))))

    class Ctx:
        async def __aenter__(self): return session
        async def __aexit__(self, *a): return False
    paused: dict = {}
    halt = SimpleNamespace(book_paused=lambda pid: paused.get(pid))
    engine = SimpleNamespace(settings=settings, sf=Ctx, positions=SimpleNamespace(portfolio=lambda pid: portfolios.get(pid)), halt=halt)
    engine.pause_book = AsyncMock(side_effect=lambda pid, reason, **kw: paused.__setitem__(pid, {"reason": reason, **kw}) or paused[pid])
    runner = SimpleNamespace(_armed=armed, arm=AsyncMock(return_value={}))
    runner.disarm = AsyncMock(side_effect=lambda run_id, **kw: armed.pop(run_id, None) is not None)
    svc = Team2Service(engine, runner)
    svc.mint_plan_run = AsyncMock(side_effect=lambda sym, date, **kw: {"runId": f"new-{sym}-{(kw.get('experiment') or {}).get('role', 'control')}", "symbol": sym, "plan": {}})
    return svc, engine, runner


def _old_plan(run_id, pid, symbol="SPY", exposure=False):
    ap = ArmedPlan(run_id=run_id, symbol=symbol, plan_for="2026-09-16", trackers={}, armed_at=0, plan={},
                   config=ArmConfig(portfolio_id=pid, mode="auto", instrument="options", use_critic=False))
    if exposure:
        ap.trades["x#1"] = Trade(trigger_id="x#1", kind="scenario_1", direction="long", fired_ts=ms(10, 0), window="team2", entry=100, stop=99,
                                 targets=[104], status="open", filled_qty=2, remaining=2, instrument="options")
    return ap


async def test_old_book_plans_are_inventoried_and_block_experiment_minting_without_force():
    settings = {"techniques.team2.symbols": ["SPY"], "techniques.team2.default_portfolio": "ctl", **_s(GOOD)}
    old = _old_plan("old-1", "practice-old")
    svc, engine, runner = _svc(settings, {"old-1": old}, {**SIM, "practice-old": {"kind": "sim"}})
    out = await svc.nightly_plans("2026-09-16", arm=False)
    assert out["outsideBooks"] == [{"runId": "old-1", "symbol": "SPY", "portfolioId": "practice-old", "exposure": False}]
    assert [r["portfolioId"] for r in out["runs"]] == ["ctl"], "only the control is minted until the old book is dealt with"
    assert any("other books" in f for f in out["failed"])
    runner.disarm.assert_not_awaited(); engine.pause_book.assert_not_awaited()


async def test_force_retires_an_old_plan_without_exposure_and_pauses_the_book_that_has_it():
    settings = {"techniques.team2.symbols": ["SPY"], "techniques.team2.default_portfolio": "ctl", **_s(GOOD)}
    flat, held = _old_plan("old-flat", "practice-old"), _old_plan("old-held", "practice-held", exposure=True)
    svc, engine, runner = _svc(settings, {"old-flat": flat, "old-held": held}, {**SIM, "practice-old": {"kind": "sim"}, "practice-held": {"kind": "sim"}})
    out = await svc.nightly_plans("2026-09-16", arm=False, force=True)
    runner.disarm.assert_awaited_once()
    assert runner.disarm.await_args.args[0] == "old-flat" and runner.disarm.await_args.kwargs["flatten"] is False
    engine.pause_book.assert_awaited_once()
    assert engine.pause_book.await_args.args[0] == "practice-held" and engine.pause_book.await_args.kwargs["label"] == "team2-transition"
    assert sorted(r["portfolioId"] for r in out["runs"]) == ["c1b", "ctl", "siz"], "all three books minted after the transition"
    assert [o["runId"] for o in out["retiredOutside"]] == ["old-flat"] and [o["runId"] for o in out["pausedOutside"]] == ["old-held"]


async def test_a_forced_replan_never_removes_the_manager_of_an_open_trade():
    settings = {"techniques.team2.symbols": ["SPY"], "techniques.team2.default_portfolio": "ctl", **_s({**GOOD, "enabled": False})}
    held = _old_plan("ctl-held", "ctl", exposure=True)
    svc, engine, runner = _svc(settings, {"ctl-held": held})
    out = await svc.nightly_plans("2026-09-16", arm=False, force=True)
    runner.disarm.assert_not_awaited()
    assert out["runs"] == [] and any("unresolved exposure" in f for f in out["failed"])


@pytest.mark.parametrize("has_exposure", [False, True])
async def test_an_unconfirmed_transition_blocks_experiment_minting_and_keeps_exposure_managed(has_exposure):
    settings = {"techniques.team2.symbols": ["SPY"], "techniques.team2.default_portfolio": "ctl", **_s(GOOD)}
    old = _old_plan("old-1", "practice-old", exposure=has_exposure)
    svc, engine, runner = _svc(settings, {"old-1": old}, {**SIM, "practice-old": {"kind": "sim"}})
    if has_exposure:
        engine.pause_book = AsyncMock(return_value=None)                    # returned no record: unconfirmed
    else:
        runner.disarm = AsyncMock(return_value=False)                       # false result: unconfirmed
    out = await svc.nightly_plans("2026-09-16", arm=False, force=True)
    assert [r["portfolioId"] for r in out["runs"]] == ["ctl"] and out["transitionFailed"]
    assert any("transition NOT confirmed" in f for f in out["failed"])
    assert "old-1" in runner._armed, "the old plan keeps managing its book"
    assert "pausedOutside" not in out and "retiredOutside" not in out


async def test_a_failed_forced_replacement_never_leaves_two_plans():
    settings = {"techniques.team2.symbols": ["SPY"], "techniques.team2.default_portfolio": "ctl", **_s({**GOOD, "enabled": False})}
    flat = _old_plan("ctl-flat", "ctl")
    svc, engine, runner = _svc(settings, {"ctl-flat": flat})
    runner.disarm = AsyncMock(side_effect=RuntimeError("disarm failed"))
    out = await svc.nightly_plans("2026-09-16", arm=False, force=True)
    assert out["runs"] == [] and any("replacement of plan ctl-flat failed" in f for f in out["failed"]) and "replaced" not in out


async def test_the_control_must_be_the_default_book_before_experiment_plans_are_minted():
    settings = {"techniques.team2.symbols": ["SPY"], "techniques.team2.default_portfolio": "practice-old", **_s(GOOD)}
    svc, engine, runner = _svc(settings, {}, {**SIM, "practice-old": {"kind": "sim"}})
    out = await svc.nightly_plans("2026-09-16", arm=False)
    assert [r["portfolioId"] for r in out["runs"]] == ["practice-old"] and any("is not the default book" in f for f in out["failed"])


async def test_the_real_engine_mints_stamped_plans_and_a_restart_keeps_the_book_and_rule_identity(engine_rig):
    eng, sim = engine_rig
    sizing = Portfolio(id=uuid.uuid4().hex, name="Team2 Sizing 0.5", kind="sim", starting_cash=10_000.0, cash=10_000.0)
    c1 = Portfolio(id=uuid.uuid4().hex, name="Team2 C1", kind="sim", starting_cash=10_000.0, cash=10_000.0)
    async with eng.sf() as session:
        session.add_all([sizing, c1]); await session.commit()
    for p in (sizing, c1):
        eng.positions.register_portfolio(p)
    await eng.settings.set("techniques.team2.default_portfolio", sim["id"], journal=False)
    await eng.settings.set("techniques.team2.experiments", {"enabled": True, "control": sim["id"], "books": [
        {"portfolioId": sizing.id, "label": "team2-sizing-cap-2026-09", "role": "sizing", "overrides": {"size_full": 0.5}},
        {"portfolioId": c1.id, "label": "team2-c1-conjunction-2026-09", "role": "c1", "overrides": {"no_trade_zone": "conjunction"}}]}, journal=False)
    prev = prev_day_bars(); trend_day(prev); await _bank(eng, prev)
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    assert len(out["armed"]) == 3 and not out["failed"], out
    siz_run = next(r["runId"] for r in out["runs"] if r["portfolioId"] == sizing.id)
    ap = eng.team2_runner.get(siz_run)
    assert ap.plan["experiment"]["role"] == "sizing" and eng.team2_runner.rules_for(ap).size_full == 0.5
    # disable the map underneath: the armed plan keeps its rules
    await eng.settings.set("techniques.team2.experiments", {"enabled": False, "control": sim["id"], "books": []}, journal=False)
    assert eng.team2_runner.rules_for(ap).size_full == 0.5
    # a restart: the plan comes back on the same book with the same stamped rules
    state = eng.team2_runner._armed.pop(siz_run)
    await eng.team2_runner.arm(siz_run, ArmConfig(portfolio_id=sizing.id, mode="alert", instrument="options", use_critic=False), restored=True, prior_state={})
    ap2 = eng.team2_runner.get(siz_run)
    assert ap2.config.portfolio_id == sizing.id and ap2.plan["experiment"]["label"] == "team2-sizing-cap-2026-09" and eng.team2_runner.rules_for(ap2).size_full == 0.5
    with pytest.raises(ValueError):
        await eng.team2_runner.arm(siz_run, ArmConfig(portfolio_id=c1.id, mode="alert", instrument="options", use_critic=False))


# ---------------------------------------------------------------- 4. the receipt
def _receipt_rig(monkeypatch, tmp_path, values, portfolios, armed, runs, health, ops):
    import urllib.request
    import zargar.config as config
    import zargar.db as db
    import zargar.settings_service as settings_module

    class Settings:
        def __init__(self, *a): pass
        async def load(self): pass
        def get(self, k, d=None): return values.get(k, d)
    results = [SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: portfolios)),
               SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: armed)),
               SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: runs))]
    session = SimpleNamespace(execute=AsyncMock(side_effect=results))

    class Ctx:
        async def __aenter__(self): return session
        async def __aexit__(self, *a): return False
    monkeypatch.setattr(config, "get_config", lambda: SimpleNamespace(database_url="unused"))
    monkeypatch.setattr(db, "make_engine", lambda _: SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr(db, "make_session_factory", lambda _: Ctx)
    monkeypatch.setattr(settings_module, "SettingsService", Settings)
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, **kw: io.BytesIO(json.dumps(health if url.endswith("/health") else ops).encode()))
    return tmp_path / "receipt.json"


def _pf(pid, name, cash=10000.0, start=10000.0, kind="sim", archived=False):
    return SimpleNamespace(id=pid, name=name, kind=kind, cash=cash, starting_cash=start, archived=archived)


def _armed(run_id, sym, pid):
    return SimpleNamespace(run_id=run_id, symbol=sym, portfolio_id=pid, status="armed")


def _run(run_id, role, overrides, version="0.7.94", code_version=None):
    """A run the way `mint_plan_run` stamps it: `codeVersion` = the strategy schema id, `appVersion` = the release."""
    from zargar.techniques.team2.service import CODE_VERSION
    exp = {"role": role, "overrides": overrides, "label": f"team2-{role}"} if role else None
    th = {**Team2Rules().to_dict(), **overrides}
    return SimpleNamespace(id=run_id, result={"plan": ({"experiment": exp} if exp else {})},
                           config={"codeVersion": code_version or CODE_VERSION, "appVersion": version, "build": "fixture", "thresholds": th,
                                   **({"experiment": exp} if exp else {})})


FULL = {"techniques.team2.symbols": ["SPY"], "techniques.team2.default_portfolio": "ctl", "system.halt": {},
        "techniques.team2.experiments": {"enabled": True, "control": "ctl", "books": GOOD["books"]}}
PFS = [_pf("ctl", "Team2 Control"), _pf("siz", "Team2 Sizing 0.5"), _pf("c1b", "Team2 C1")]
ARMED = [_armed("r-ctl", "SPY", "ctl"), _armed("r-siz", "SPY", "siz"), _armed("r-c1", "SPY", "c1b")]
RUNS = [_run("r-ctl", None, {}), _run("r-siz", "sizing", {"size_full": 0.5}), _run("r-c1", "c1", {"no_trade_zone": "conjunction"})]


async def test_the_receipt_is_ready_only_with_complete_evidence_and_c6(monkeypatch, tmp_path):
    from zargar.tools import team2_receipt
    target = _receipt_rig(monkeypatch, tmp_path, FULL, PFS, ARMED, RUNS, {"ok": True, "version": "0.7.94", "build": "abc"}, {"pausedBooks": []})
    monkeypatch.setattr(team2_receipt, "c6_status", lambda: {"satisfied": True, "evidence": {"reviewedBy": "review team", "date": "2026-09-16", "datasetVersion": "x", "reference": "note"}})
    await team2_receipt.main(SimpleNamespace(date="2026-09-16", out=str(target)))
    r = json.loads(target.read_text(encoding="utf-8"))
    assert r["activation"].startswith("READY") and r["blockers"] == [] and r["state"] == "ENABLED"
    assert all(b["stampOk"] for b in r["books"])


@pytest.mark.parametrize("mutate, needle", [
    (lambda k: k.update(health={"ok": False}), "not healthy"),
    (lambda k: k.update(health={"ok": True, "version": "0.7.90"}), "predates the reviewed"),
    (lambda k: k.update(armed=ARMED[:2]), "no armed plan"),
    (lambda k: k.update(armed=ARMED + [_armed("r-old", "SPY", "practice-old")], portfolios=PFS + [_pf("practice-old", "Team2 Practice")]), "fourth book"),
    (lambda k: k.update(portfolios=[_pf("ctl", "Team2 Control", cash=9934.16)] + PFS[1:]), "fresh starting balance"),
    (lambda k: k.update(ops={"pausedBooks": ["siz"]}), "is paused"),
    (lambda k: k.update(runs=[RUNS[0], _run("r-siz", "sizing", {"size_full": 1.0}), RUNS[2]]), "is stamped"),
    (lambda k: k.update(runs=[RUNS[0], _run("r-siz", "sizing", {"size_full": 0.5}, version="0.7.93"), RUNS[2]]), "minted by release"),
    (lambda k: k.update(runs=[RUNS[0], _run("r-siz", "sizing", {"size_full": 0.5}, code_version="team2-0.0"), RUNS[2]]), "strategy schema"),
    (lambda k: k.update(armed=ARMED + [_armed("r-siz-dup", "SPY", "siz")], runs=RUNS + [_run("r-siz-dup", "sizing", {"size_full": 0.5})]), "duplicate armed plans"),
    (lambda k: k.update(values={**FULL, "techniques.team2.default_portfolio": "practice-old"}), "is not the default book"),
    (lambda k: k.update(values={**FULL, "techniques.team2.experiments": {"enabled": True, "control": "ctl", "books": GOOD["books"][:1]}}), "both experiment roles"),
])
async def test_missing_evidence_is_a_blocker_never_a_pass(monkeypatch, tmp_path, mutate, needle):
    from zargar.tools import team2_receipt
    kw = dict(values=FULL, portfolios=PFS, armed=ARMED, runs=RUNS, health={"ok": True, "version": "0.7.94", "build": "abc"}, ops={"pausedBooks": []})
    mutate(kw)
    target = _receipt_rig(monkeypatch, tmp_path, **kw)
    monkeypatch.setattr(team2_receipt, "c6_status", lambda: {"satisfied": True, "evidence": {"reviewedBy": "r", "date": "d", "datasetVersion": "x", "reference": "n"}})
    await team2_receipt.main(SimpleNamespace(date="2026-09-16", out=str(target)))
    r = json.loads(target.read_text(encoding="utf-8"))
    assert r["activation"].startswith("NOT READY") and any(needle in b for b in r["blockers"]), r["blockers"]


async def test_readonly_settings_load_never_writes_or_journals_any_migration():
    from zargar.bus import Bus
    from zargar.settings_service import SettingsService
    rows = [SimpleNamespace(key="trading.mode", value={"v": "sim"}), SimpleNamespace(key="technique.arm.mode", value={"v": "auto"})]
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))),
                              get=AsyncMock(return_value=rows[0]), add=lambda *a: None, commit=AsyncMock())

    class Ctx:
        async def __aenter__(self): return session
        async def __aexit__(self, *a): return False
    journal = SimpleNamespace(append=AsyncMock())
    st = SettingsService(Ctx, Bus(), journal); st.readonly = True
    await st.load()
    assert st.get("trading.mode") == "practice"
    session.commit.assert_not_awaited(); journal.append.assert_not_awaited()
    assert rows[0].value == {"v": "sim"}


async def test_a_disabled_map_is_prepared_never_ready_and_c6_needs_a_record(monkeypatch, tmp_path):
    from zargar.tools import team2_receipt
    values = {**FULL, "techniques.team2.experiments": {**FULL["techniques.team2.experiments"], "enabled": False}}
    target = _receipt_rig(monkeypatch, tmp_path, values, PFS, [], [], {"ok": True, "version": "0.7.94", "build": "abc"}, {"pausedBooks": []})
    monkeypatch.setattr(team2_receipt, "C6_EVIDENCE", tmp_path / "missing.json")
    await team2_receipt.main(SimpleNamespace(date="2026-09-16", out=str(target)))
    r = json.loads(target.read_text(encoding="utf-8"))
    assert r["state"].startswith("PREPARED") and r["activation"].startswith("NOT READY") and any("C6" in b for b in r["blockers"])
    (tmp_path / "c6.json").write_text("C6 satisfied", encoding="utf-8")                  # prose is not evidence
    monkeypatch.setattr(team2_receipt, "C6_EVIDENCE", tmp_path / "c6.json")
    assert team2_receipt.c6_status()["satisfied"] is False
    (tmp_path / "c6.json").write_text(json.dumps({"satisfied": True, "reviewedBy": "review team", "date": "2026-09-16", "datasetVersion": "abc", "reference": "note"}), encoding="utf-8")
    assert team2_receipt.c6_status()["satisfied"] is True
