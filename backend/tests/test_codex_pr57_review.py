"""Remaining execution-authority contracts at PR57; no runtime/network access."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from .test_team2_picker_gates import _runner


async def test_delayed_price_outside_wide_band_must_not_prevent_fresh_check():
    runner, trade, opts = _runner([(287.5, 0.05)], {287.5: (0.20, 0.21)})
    result = await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade)
    assert result is not None, {"quote_requests": opts.reprice.await_count, "errors": trade.errors}


async def test_failed_fresh_quote_must_not_return_delayed_contract_as_eligible():
    runner, trade, opts = _runner([(287.5, 0.60)], None)
    opts.reprice = AsyncMock(side_effect=RuntimeError("quote unavailable"))
    result = await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade)
    assert result is None, {"priced": result.get("priced"), "ask": result.get("ask")}


async def test_warmup_stamp_must_include_fallback_bars(monkeypatch):
    import zargar.marketdata as md
    import zargar.marketstructure.history as history
    from zargar.techniques.team2.runner import Team2Runner
    from zargar.techniques.team2.rules import Team2Rules
    from zargar.techniques.team2.service import Team2Service
    from .test_team2_session import DAY, prev_day_bars
    prior = prev_day_bars()
    monkeypatch.setattr(md, "load_bars", AsyncMock(return_value=[]))
    monkeypatch.setattr(history, "fetch_window", AsyncMock(return_value=prior))
    runner = Team2Runner.__new__(Team2Runner)
    runner.engine = SimpleNamespace(sf=None)
    runner._warm_loaded, runner._warm, runner._bars = set(), {}, {}
    runner.rules = lambda: Team2Rules()
    runner._log = lambda *a, **kw: None
    ap = SimpleNamespace(run_id="probe", symbol="SPY", plan_for=DAY.isoformat(), plan={})
    await runner._load_warmup(ap)
    consumed, rep = Team2Service.warmup_slice(runner._warm[ap.run_id], sessions=12)
    assert consumed
    assert ap.plan["warmup"]["hash"] == rep["hash"], {"stamped_rows": ap.plan["warmup"]["rows"], "consumed_rows": len(consumed)}
