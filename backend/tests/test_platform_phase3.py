"""Phase 3 (platform plan §8.4): settings scoping — canonical execution.* keys,
deprecated technique.arm.* aliases with journal continuity, per-technique
overrides resolved by PlanRunner.rt(), and the live-re-read run cap."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from zargar.models import Event, Setting
from zargar.settings_service import ALIASES, DEFAULTS
from zargar.technique.service import attach_technique_layer


async def test_legacy_names_are_aliases_with_journal_continuity(engine):
    s = engine.settings
    # write via the deprecated name -> the canonical row is what is stored
    await s.set("technique.arm.premium_stop_pct", 40.0)
    assert s.get("execution.premium_stop_pct") == 40.0
    assert s.get("technique.arm.premium_stop_pct") == 40.0     # old name still reads the truth
    async with engine.sf() as session:
        rows = {r.key for r in (await session.execute(select(Setting))).scalars().all()}
        assert "execution.premium_stop_pct" in rows
        evs = (await session.execute(select(Event).where(Event.type == "SettingChanged")
                                     .order_by(Event.id.desc()))).scalars().all()
    top = evs[0].payload
    assert top["key"] == "execution.premium_stop_pct" and top["aliasOf"] == "technique.arm.premium_stop_pct"
    # the snapshot mirrors the canonical value onto the legacy name for the UI
    assert s.all()["technique.arm.premium_stop_pct"] == 40.0


async def test_stored_legacy_value_migrates_once_on_load(engine):
    async with engine.sf() as session:
        session.add(Setting(key="technique.arm.stale_seconds", value={"v": 240}))
        await session.commit()
    await engine.settings.load()
    assert engine.settings.get("execution.stale_seconds") == 240
    async with engine.sf() as session:
        rows = {r.key for r in (await session.execute(select(Setting))).scalars().all()}
    assert "execution.stale_seconds" in rows


async def test_technique_override_beats_platform_default(engine):
    s = engine.settings
    await attach_technique_layer(engine)
    armer = engine.technique.armer
    assert armer.rt("premium_stop_pct", 50.0) == DEFAULTS["execution.premium_stop_pct"]
    await s.set("execution.premium_stop_pct", 45.0)
    assert armer.rt("premium_stop_pct", 50.0) == 45.0
    await s.set("techniques.enhanced_market.premium_stop_pct", 33.0)
    assert armer.rt("premium_stop_pct", 50.0) == 33.0           # per-technique override wins
    with pytest.raises(KeyError):
        await s.set("techniques.enhanced_market.not_a_runtime_key", 1)


def test_em_policy_keys_are_not_platform_keys():
    for k in ("technique.arm.midday_trading", "technique.arm.friday_size_mult",
              "technique.arm.preopen_at", "technique.arm.avoid_0dte_after",
              "technique.arm.critic_effort", "technique.arm.strike_within_targets",
              "technique.arm.preopen_replan"):
        assert k not in ALIASES, k
        assert k in DEFAULTS, k


async def test_run_cap_is_reread_live(engine):
    await attach_technique_layer(engine)
    svc = engine.technique
    await engine.settings.set("technique.max_concurrent_runs", 3)
    svc._run_sem = None
    # touch the lazy path the way _execute does
    want = max(1, int(engine.settings.get("technique.max_concurrent_runs", 8)))
    assert want == 3
    import asyncio
    svc._run_sem = asyncio.Semaphore(want)
    svc._run_sem_size = want
    await engine.settings.set("technique.max_concurrent_runs", 7)
    want2 = max(1, int(engine.settings.get("technique.max_concurrent_runs", 8)))
    assert want2 == 7 and svc._run_sem_size != want2            # next run rebuilds the semaphore


def test_every_journaled_kind_has_a_contract():
    """Every ev.TECHNIQUE_* constant that the runner or the technique journals is
    registered in the contracts, so a new kind cannot ship shapeless."""
    import re
    from pathlib import Path

    import zargar.events as ev
    from zargar.research.events_contract import CONTRACTS
    root = Path(ev.__file__).parent
    used = set()
    for p in list((root / "technique").glob("*.py")) + list((root / "execution").glob("*.py")):
        used |= set(re.findall(r"ev\.(TECHNIQUE_[A-Z_]+)", p.read_text(encoding="utf-8")))
    for const in used:
        kind = getattr(ev, const)
        assert kind in CONTRACTS, f"{const} ({kind}) journaled but not in the event contracts"


def test_contract_validation_shapes():
    from zargar.research.events_contract import validate
    ok = {"runId": "r", "symbol": "AAPL", "trigger": "b1", "kind": "bounce", "window": "prime_open",
          "entry": 1.0, "stop": 0.9, "mode": "auto", "fill": None}
    assert validate("TechniquePlanTriggerFired", ok) == []
    bad = validate("TechniquePlanTriggerFired", {"runId": "r"})
    assert any("missing required field" in p for p in bad)
    assert validate("TechniqueMadeUpKind", {}) != []       # unregistered Technique kind is a violation
    assert validate("OrderIntentCreated", {}) == []        # non-technique kinds are out of scope


async def test_never_list_and_day_notional_caps(engine):
    """Share shorting is a hard reject; 0DTE is EM-only; per-technique/per-tag
    day-notional caps bind when configured."""
    from zargar.orders import OrderIntent
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")

    # share short: hard reject regardless of the (ignored) risk.allow_short toggle
    await engine.settings.set("risk.allow_short", True)
    r = await engine.orders.place(OrderIntent(portfolio_id=pf["id"], symbol="AAPL", side="SELL",
                                              qty=5, order_type="MKT", source="manual"))
    assert r["status"] == "REJECTED_RISK"
    checks = {c["name"]: c for c in r["risk"]["checks"]}
    assert not checks["short_allowed"]["passed"] and "never" in checks["short_allowed"]["detail"]

    # per-technique day cap: second buy that would cross the cap is rejected
    await engine.settings.set("risk.max_day_notional_per_technique", 1000.0)
    sym = engine.config.sim_symbols[0] if getattr(engine.config, "sim_symbols", None) else "AAPL"
    q = None
    for _ in range(100):
        q = engine.quotes.get(sym)
        if q is not None and q.last > 0:
            break
        import asyncio as _a
        await _a.sleep(0.05)
    assert q is not None and q.last > 0
    qty = max(1, int(600 / q.last))
    i1 = OrderIntent(portfolio_id=pf["id"], symbol=sym, side="BUY", qty=qty, order_type="LMT",
                     limit_price=round(q.last, 2), source="technique", technique_id="tip", tags=["source:x"])
    r1 = await engine.orders.place(i1)
    assert r1["status"] != "REJECTED_RISK", r1.get("rejectReason")
    i2 = i1.model_copy(deep=True)
    i2.qty = qty + 1                       # not a duplicate of i1, still crosses the cap
    r2 = await engine.orders.place(i2)
    assert r2["status"] == "REJECTED_RISK" and "/day cap" in (r2.get("rejectReason") or "")

    # rows carry the identity
    from sqlalchemy import select
    from zargar.models import Order
    async with engine.sf() as session:
        row = (await session.execute(select(Order).where(Order.id == r1["id"]))).scalar_one()
    assert row.technique == "tip" and row.tags == ["source:x"]


async def test_scheduler_runs_and_journals_jobs(engine):
    """A registered job runs once for the day, journals, and a failing job alerts
    without killing the scheduler."""
    import zargar.scheduler as sch
    ran = []

    async def ok():
        ran.append(1)
        return {"n": 1}

    async def boom():
        raise RuntimeError("nope")

    engine.scheduler.register("t_ok", "00:00", ok, weekdays_only=False)
    engine.scheduler.register("t_boom", "00:00", boom, weekdays_only=False)
    await engine.scheduler._tick()
    await engine.scheduler._tick()          # same day: must not run again
    assert ran == [1]
    st = {j["name"]: j for j in engine.scheduler.status()}
    assert st["t_ok"]["runs"] == 1 and st["t_boom"]["failures"] == 1
    from sqlalchemy import select
    from zargar.models import Event
    async with engine.sf() as session:
        kinds = [e.type for e in (await session.execute(
            select(Event).where(Event.type.in_((sch.SCHEDULED_JOB_RAN, sch.SCHEDULED_JOB_FAILED))))).scalars().all()]
    assert sch.SCHEDULED_JOB_RAN in kinds and sch.SCHEDULED_JOB_FAILED in kinds


async def test_chain_snapshot_writes_rows(engine, monkeypatch):
    """The nightly snapshot persists one row per contract and is idempotent."""
    from zargar.research import snapshots as snap

    class FakeProvider:
        async def all_rows(self, sym):
            return [{"symbol": f"{sym}260918C00100000", "underlying": sym, "expiry": "2026-09-18",
                     "option_type": "C", "strike": 100.0, "bid": 1.0, "ask": 1.2, "last": 1.1,
                     "volume": 42, "open_interest": 1337, "greeks": {"mid_iv": 0.33, "delta": 0.5}}]

    class FakeOpts:
        def provider(self):
            return FakeProvider()

        async def stop(self):
            return None

    engine.options = FakeOpts()

    async def uni(_):
        return ["AAPL", "MSFT", "SHOP.TO"]     # the .TO name must be filtered out
    monkeypatch.setattr(snap, "_universe", uni)
    r1 = await snap.snapshot_chains(engine)
    r2 = await snap.snapshot_chains(engine)    # rerun same day: conflict-ignored
    assert r1["rows"] == 2 and r1["symbols"] == 2 and r2["failed"] == 0
    from sqlalchemy import select, func
    from zargar.models import OptionChainSnapshot
    async with engine.sf() as session:
        n = (await session.execute(select(func.count()).select_from(OptionChainSnapshot))).scalar_one()
        row = (await session.execute(select(OptionChainSnapshot).limit(1))).scalars().first()
    assert n == 2 and row.open_interest == 1337 and row.iv == 0.33


async def test_daily_bars_snapshot_persists_1d_rows(engine, monkeypatch):
    from zargar.domain import Bar
    from zargar.research import snapshots as snap

    async def uni(_):
        return ["AAPL"]
    monkeypatch.setattr(snap, "_universe", uni)

    async def fake_fetch(sym, tf="1d", range_="1mo", **kw):
        return [Bar(symbol=sym, tf="1d", ts=1787407800000, open=1, high=2, low=0.5, close=1.5, volume=100)]
    monkeypatch.setattr(engine.feed, "fetch_bars", fake_fetch, raising=False)
    out = await snap.snapshot_daily_bars(engine)
    assert out["rows"] == 1
    from sqlalchemy import select
    from zargar.models import BarRow
    async with engine.sf() as session:
        rows = (await session.execute(select(BarRow).where(BarRow.tf == "1d"))).scalars().all()
    assert len(rows) == 1 and rows[0].symbol == "AAPL"    # 1d rows pass the alignment filter


async def test_calendar_parses_quote_summary(engine, monkeypatch):
    """The calendar record is parsed from quoteSummary and cached; failures come
    back as empty records, never exceptions."""
    import zargar.calendar_service as calmod

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"quoteSummary": {"result": [{"calendarEvents": {
                "earnings": {"earningsDate": [{"raw": 1793538000}]},   # 2026-11-01 ~21:00 UTC
                "exDividendDate": {"raw": 1793019600},
            }}]}}

    calls = []

    async def fake_get(url, params=None, **kw):
        calls.append(url)
        if "getcrumb" in url:
            class C:
                status_code = 200
                text = "abc123"
            return C()
        if "fc.yahoo.com" in url:
            class W:
                status_code = 200
                text = ""
            return W()
        return FakeResp()

    monkeypatch.setattr(engine.calendar._client, "get", fake_get)
    rec = await engine.calendar.get("AAPL")
    assert rec["earnings"] and rec["exDividend"] and rec["source"] == "yahoo"
    n = len(calls)
    rec2 = await engine.calendar.get("AAPL")     # cached: no new HTTP
    assert rec2 is rec and len(calls) == n
    d = await engine.calendar.days_to_earnings("AAPL")
    assert d is None or isinstance(d, int)

    async def boom(url, params=None, **kw):
        raise RuntimeError("offline")
    monkeypatch.setattr(engine.calendar._client, "get", boom)
    rec3 = await engine.calendar.get("MSFT")
    assert rec3["earnings"] == [] and rec3["exDividend"] is None


async def test_per_technique_pause_blocks_new_arms_not_exits(engine):
    """techniques.<id>.paused refuses new arms; the flag never touches the exit
    paths (per-plan pause() is the reversible half; exits stay reduce-only exempt)."""
    import pytest as _pytest

    from zargar.technique.service import attach_technique_layer
    await attach_technique_layer(engine)
    armer = engine.technique.armer
    await engine.settings.set("techniques.enhanced_market.paused", True)
    assert armer.rt("paused", False) is True
    with _pytest.raises(RuntimeError) as ei:
        await armer.arm("no-such-run")
    assert "paused" in str(ei.value)
    await engine.settings.set("techniques.enhanced_market.paused", False)
    with _pytest.raises(KeyError):                    # unpaused: falls through to the run lookup
        await armer.arm("no-such-run")
    assert "enhanced_market" in engine.techniques     # the service registry exists
