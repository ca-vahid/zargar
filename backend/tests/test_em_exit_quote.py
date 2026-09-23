"""exit-quote-v1 (2026-09-22): EM journals the quote each exit was DECIDED on, after the exit order exists.

Why: until now the exit side of every option round trip's spread was an estimate - the quote at the decision was never
kept. The record is pure observation: it is read before the exit and written after the order is placed, so a protective
exit never waits on it, and a failure to capture it never blocks the exit.
"""
from sqlalchemy import select

from zargar.domain import Bar
from zargar.models import Event, Order

from .conftest import wait_for
from .test_em_experiment import _launch, _open, _trade
from .test_technique_arming import _plan_run, _quote, rig  # noqa: F401  (rig is a fixture)


async def _stop_out(rig, run, pid):
    _armed, bars, b1, i = await _open(rig, run, pid)
    stop = b1["stop"]
    await _quote(rig, stop - 0.02)
    await rig.svc.armer.on_bar(run["id"], Bar(symbol="TEST", tf="1m", ts=bars[i].ts, open=b1["entry"], high=b1["entry"],
                                              low=stop - 0.05, close=stop - 0.02, volume=1000))
    await _quote(rig, stop - 0.02)
    await wait_for(lambda: _trade(rig, run["id"]).get("status") == "closed", timeout=5)
    return b1


async def _exit_quotes(rig):
    async with rig.eng.sf() as s:
        return [e.payload for e in (await s.execute(select(Event).where(Event.type == "TechniqueExitQuote"))).scalars().all()]


async def test_a_stop_exit_journals_the_quote_it_was_decided_on_bound_to_the_exit_order(rig):
    await _launch(rig)
    run = await _plan_run(rig)
    b1 = await _stop_out(rig, run, rig.sim["id"])
    (rec,) = await wait_for(lambda: _exit_quotes(rig), timeout=5)             # written off the exit path, so it lands after
    async with rig.eng.sf() as s:
        sell = (await s.execute(select(Order).where(Order.portfolio_id == rig.sim["id"], Order.side == "SELL"))).scalars().one()
    assert rec["version"] == "exit-quote-v1" and rec["runId"] == run["id"] and rec["kind"] == "stop"
    assert rec["exitOrderId"] == str(sell.id) and rec["exitOrderIds"] == [str(sell.id)], "bound to the order it priced"
    assert rec["symbol"] == "TEST" and rec["instrument"] == "shares" and rec["trigger"] == b1["id"]
    assert rec["bid"] is not None and rec["ask"] is not None and rec["bid"] <= b1["stop"], "the quote the stop saw, not a later one"


async def test_capture_off_writes_nothing(rig):
    await _launch(rig)
    await rig.eng.settings.set("techniques.enhanced_market.exit_quote_capture", False, journal=False)
    run = await _plan_run(rig)
    await _stop_out(rig, run, rig.sim["id"])
    assert "_eq_recorder" not in rig.svc.armer.__dict__ and await _exit_quotes(rig) == [], "nothing was even queued"


async def test_a_capture_failure_never_blocks_the_exit(rig, monkeypatch):
    await _launch(rig)

    def boom(*a, **k):
        raise RuntimeError("quote cache unavailable")
    monkeypatch.setattr(type(rig.svc.armer), "_exit_quote_snapshot", boom)
    run = await _plan_run(rig)
    await _stop_out(rig, run, rig.sim["id"])                                     # closes: the exit did not wait on the record
    assert "_eq_recorder" not in rig.svc.armer.__dict__ and await _exit_quotes(rig) == [], "nothing was even queued"
