"""Tips pre-live W1 correctness fixes (2026-10-02 review, docs/techniques/tip/research/2026-10-02-tips-review/PLAN.md):
W1.1 units check, W1.3 contract multiplier, W1.8 shadow-book phantom shorts, W1.10 rule-audit judge errors.
No LLM is ever called: extractions are ExtractionResult fixtures, the judge is a stub."""
import asyncio
import datetime as dt
import json
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from zargar.brokers.base import ExecReport
from zargar.domain import Quote
from zargar.models import Event, Execution, Order
from zargar.options import occ
from zargar.orders import OrderIntent
from zargar.signals.schemas import (ExtractionResult, TradeSignal, entry_price_is_underlying,
                                    underlying_price_checks_ok)
from zargar.signals.verification import verify_signal
from zargar.techniques.tip import rule_audit

from .conftest import make_test_config, wait_for


# ============================================================ W1.1 units check
class _Quotes:
    def __init__(self, **last):
        now = int(time.time() * 1000)
        self.q = {s: Quote(symbol=s, last=p, bid=p - .01, ask=p + .01, bid_size=100, ask_size=100,
                           ts=now) for s, p in last.items()}

    def get(self, s):
        return self.q.get(s)


_SETTINGS = {"verification.max_price_deviation_pct": 3.0, "verification.max_spread_pct": 1.5,
             "verification.min_price": 1.0, "verification.require_actionable": True}


def _msft_extraction(**over) -> ExtractionResult:
    """The 2026-09-28 message "MSFT 505 0dte 1.00 sl .65 tp 1.30" as the extractor read it:
    instrument UNSPECIFIED, the contract's prices in entry/stop/target."""
    kw = dict(ticker="MSFT", direction="long", action="open", instrument="unspecified",
              strike=505.0, expiry=dt.date.today().isoformat(),
              entry_price=1.00, stop_price=0.65, target_price=1.30, target_prices=[1.30],
              entry_type="limit", timeframe="day_trade", thesis_summary="0DTE call",
              evidence_quotes=["MSFT 505 0dte 1.00 sl .65 tp 1.30"],
              confidence="explicit_call", is_actionable=True)
    kw.update(over)
    return ExtractionResult(signals=[TradeSignal(**kw)], source_type="trade_alert")


def _check(res, name):
    return next((c for c in res["checks"] if c["name"] == name), None)


async def test_msft_0dte_premium_target_is_not_judged_against_the_stock():
    sig = _msft_extraction().signals[0]
    res = await verify_signal(sig, _Quotes(MSFT=506.62), _SETTINGS)
    past = _check(res, "not_past_target")
    assert past is None or past["passed"], "506.62 vs a 1.30 premium target parked a real 0DTE BTO"
    dev = _check(res, "price_deviation")
    assert dev is None or dev["passed"], "a 1.00 premium entry was compared with the 506.62 stock"
    assert not res["park"] and res["passed"], res
    assert _check(res, "price_units") and _check(res, "entry_units")


async def test_premium_in_premium_field_and_no_entry_also_skips():
    sig = _msft_extraction(entry_price=None, premium=1.00).signals[0]
    res = await verify_signal(sig, _Quotes(MSFT=506.62), _SETTINGS)
    assert not res["park"] and res["passed"], res


@pytest.mark.parametrize("ticker,live,strike,tgt,stop", [
    ("MU", 180.0, 990.0, 3.0, 1.5),       # strike-bearing, premium-scale (the 09-11 shape)
    ("SPY", 772.0, 775.0, 2.4, 1.1),
    ("NVDA", 185.0, None, 2.5, 1.2),      # no strike at all: still premium-scale vs the stock
])
async def test_other_reported_shapes_are_not_parked(ticker, live, strike, tgt, stop):
    sig = TradeSignal(ticker=ticker, direction="long", instrument="unspecified", strike=strike,
                      target_price=tgt, stop_price=stop, thesis_summary="x", evidence_quotes=["x"],
                      confidence="explicit_call", is_actionable=True)
    res = await verify_signal(sig, _Quotes(**{ticker: live}), _SETTINGS)
    assert not res["park"], res


async def test_underlying_scale_unspecified_targets_are_still_checked():
    """Control: a stock tip whose target the stock already passed still parks."""
    sig = TradeSignal(ticker="NVDA", direction="long", instrument="unspecified",
                      entry_price=148.0, target_price=145.0, stop_price=140.0, thesis_summary="x",
                      evidence_quotes=["x"], confidence="explicit_call", is_actionable=True)
    res = await verify_signal(sig, _Quotes(NVDA=150.0), _SETTINGS)
    assert _check(res, "not_past_target")["passed"] is False


def test_cold_quote_uses_the_strike_as_the_scale_reference():
    sig = _msft_extraction().signals[0]
    ok, why = underlying_price_checks_ok(sig, None)
    assert not ok and "premium-scale" in why
    assert entry_price_is_underlying(sig, None) is False
    # a premium-scale ENTRY on an explicit call no longer anchors the call's unit heuristic
    call = _msft_extraction(instrument="call", price_domain=None).signals[0]
    ok, _ = underlying_price_checks_ok(call, 506.62)
    assert not ok


# ============================================================ W1.3 contract multiplier
def test_resolve_multiplier_defaults_standard_us_contracts():
    assert occ.resolve_multiplier("INTC261016C00030000") == (100.0, "standard-us-default")
    assert occ.resolve_multiplier("INTC261016C30")[0] == 100.0              # the short spelling
    assert occ.resolve_multiplier("INTC261016C00030000", 100) == (100.0, "stated")
    assert occ.resolve_multiplier("INTC261016C00030000", None, non_standard=True)[0] is None
    assert occ.resolve_multiplier("AAPL1261016C00030000")[0] is None       # adjusted root: positive evidence
    assert occ.resolve_multiplier("NOT-AN-OCC")[0] is None


async def _risk_plan(monkeypatch, vehicle: dict, symbol: str = "INTC261016C00030000"):
    from zargar.approvals.proposals import ProposalService
    from zargar.clock import now_ms
    from zargar.techniques.tip import execcost, geometry
    now = now_ms()
    q = NS(last=30.0, bid=1.19, ask=1.20, source="opra", source_ts=now, ts=now, delayed=False)
    eng = NS(settings={"options.fee_per_contract": .65, "sim.reg_fee_per_contract": .05},
             ensure_symbol=AsyncMock(), quotes=NS(get=lambda s: q),
             positions=NS(equity=AsyncMock(return_value=9000)), feed=type("SimQuoteFeed", (), {})(),
             options=NS(snapshot_cached=lambda s: {"greeks": {"delta": .4}, "asOf": now, "greeksLive": True}))
    seen: dict = {}
    plan = {"targets": [1.8], "fractions": [1.0], "maxHoldSessions": 2}
    rp = NS(qty=1, unitLoss=40., reviewRequired=None, reviewClass=None)

    def plan_risk(**kw):
        seen.update(kw)
        return plan, rp
    monkeypatch.setattr(geometry, "plan_risk", plan_risk)
    monkeypatch.setattr(execcost, "diagnose", lambda *a, **k: {"status": "known"})
    await ProposalService._compute_risk_plan(NS(engine=eng), mode="enforce", underlying="INTC", direction="long",
                                             pid="p", exit_plan=plan, vehicle=vehicle, sec_type="OPT",
                                             symbol=symbol, limit=1.20, qty=1, entry_hint=30.)
    return seen, rp


async def test_intc_take_without_vehicle_multiplier_prices_at_100(monkeypatch):
    seen, rp = await _risk_plan(monkeypatch, vehicle={"kind": "option"})      # no multiplier, no optionType
    assert seen["multiplier"] == 100.0 and seen["option_type"] == "call"
    assert seen["quote_meta"]["multiplierSource"] == "standard-us-default"
    assert "multiplier unknown" not in str(rp.reviewRequired or "")


async def test_non_standard_deliverable_is_still_refused(monkeypatch):
    _seen, rp = await _risk_plan(monkeypatch, vehicle={"kind": "option", "optionType": "call",
                                                        "deliverable": 50})
    assert "contract multiplier unknown" in str(rp.reviewRequired)


# ============================================================ W1.10 rule-audit judge errors
def _ok_resp():
    return NS(content=[NS(type="text", text=json.dumps({"summary": "ok"}))], usage=None, stop_reason="end_turn")


class _Overloaded(Exception):
    status_code = 529


async def test_empty_timeout_is_described_and_retried(monkeypatch):
    monkeypatch.setattr(rule_audit, "TRANSIENT_BACKOFF_S", (0.0, 0.0))
    create = AsyncMock(side_effect=[asyncio.TimeoutError(), _Overloaded("Overloaded"), _ok_resp()])
    op, calls = await rule_audit._judge(NS(messages=NS(create=create)), model="m", system="s", header="h", cap=500)
    assert op.summary == "ok" and create.await_count == 3
    errs = [c for c in calls if c.get("error")]
    assert [c["errorType"] for c in errs] == ["TimeoutError", "_Overloaded"]
    assert all(c["error"].strip() for c in errs) and all(c["transient"] for c in errs)
    assert calls[-1].get("transientRetries") == 2


async def test_persistent_transient_failure_is_bounded_and_never_empty(monkeypatch):
    monkeypatch.setattr(rule_audit, "TRANSIENT_BACKOFF_S", (0.0, 0.0))
    create = AsyncMock(side_effect=asyncio.TimeoutError())
    with pytest.raises(rule_audit.JudgeError) as ei:
        await rule_audit._judge(NS(messages=NS(create=create)), model="m", system="s", header="h", cap=500)
    assert create.await_count == 3                               # 1 + 2 bounded retries
    msg = str(ei.value)
    assert msg.startswith("judge call failed: TimeoutError") and msg != "judge call failed: "
    assert len(ei.value.calls) == 3


async def test_non_transient_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(rule_audit, "TRANSIENT_BACKOFF_S", (0.0, 0.0))
    create = AsyncMock(side_effect=ValueError(""))
    with pytest.raises(rule_audit.JudgeError) as ei:
        await rule_audit._judge(NS(messages=NS(create=create)), model="m", system="s", header="h", cap=500)
    assert create.await_count == 1 and "ValueError" in str(ei.value)


def test_batch_wait_timeout_is_not_retried_in_call():
    assert rule_audit.is_transient_error(TimeoutError("batch x did not end"), batched=True) is False
    assert rule_audit.is_transient_error(TimeoutError(), batched=False) is True


# ============================================================ W1.8 shadow phantom shorts
@pytest.fixture
async def rig(fresh_db):
    from zargar.engine import Engine
    from zargar.signals.service import attach_signal_layer
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def _events(eng, kind):
    async with eng.sf() as session:
        return (await session.execute(select(Event).where(Event.type == kind))).scalars().all()


async def _execs(eng, pid, side="SELL"):
    async with eng.sf() as session:
        return (await session.execute(select(Execution).where(
            Execution.portfolio_id == pid, Execution.side == side))).scalars().all()


async def test_shadow_sell_with_nothing_held_books_nothing(rig):
    eng = rig
    shadow = await eng.signals_service.shadow_portfolio("PhantomSrc", "immediate")
    await eng.ensure_symbol("AAPL")
    await wait_for(lambda: eng.quotes.get("AAPL") is not None)
    out = await eng.orders.place(OrderIntent(portfolio_id=shadow["id"], symbol="AAPL", side="SELL",
                                             qty=11, order_type="MKT", reduce_only=True, source="auto"))
    assert out["status"] == "REJECTED_RISK" and "no lot" in out["rejectReason"]
    assert await _events(eng, "ShadowSellRefused")
    assert not await _execs(eng, shadow["id"])
    assert eng.positions.position_qty(shadow["id"], "AAPL") == 0


async def test_shadow_sell_is_capped_at_the_held_lot(rig):
    eng = rig
    shadow = await eng.signals_service.shadow_portfolio("CapSrc", "immediate")
    await eng.ensure_symbol("AAPL")
    await wait_for(lambda: eng.quotes.get("AAPL") is not None)
    await eng.orders.place(OrderIntent(portfolio_id=shadow["id"], symbol="AAPL", side="BUY",
                                       qty=4, order_type="MKT", source="auto"))
    await wait_for(lambda: eng.positions.position_qty(shadow["id"], "AAPL") == 4, timeout=30)
    out = await eng.orders.place(OrderIntent(portfolio_id=shadow["id"], symbol="AAPL", side="SELL",
                                             qty=6, order_type="MKT", source="auto"))
    assert out["qty"] == 4
    await wait_for(lambda: eng.positions.position_qty(shadow["id"], "AAPL") == 0, timeout=30)
    again = await eng.orders.place(OrderIntent(portfolio_id=shadow["id"], symbol="AAPL", side="SELL",
                                               qty=5, order_type="MKT", source="auto"))
    assert again["status"] == "REJECTED_RISK"
    assert eng.positions.position_qty(shadow["id"], "AAPL") == 0


async def test_dangling_bracket_child_never_shorts_a_shadow_book(rig):
    """The likely leak: a bracket child left resting after the lot was sold another way
    (time-exit sweep / manager exit) fills later. The flat lot cancels its resting sells,
    and a fill that arrives anyway is not booked."""
    from zargar.orders import BracketSpec
    eng = rig
    shadow = await eng.signals_service.shadow_portfolio("BracketSrc", "immediate")
    await eng.ensure_symbol("AAPL")
    await wait_for(lambda: eng.quotes.get("AAPL") is not None)
    px = eng.quotes.get("AAPL").last
    parent = await eng.orders.place(OrderIntent(
        portfolio_id=shadow["id"], symbol="AAPL", side="BUY", qty=4, order_type="MKT", source="auto",
        bracket=BracketSpec(take_profit=round(px * 3, 2), stop_loss=round(px * 0.2, 2))))

    async def children():
        async with eng.sf() as session:
            return (await session.execute(select(Order).where(Order.parent_id == parent["id"]))).scalars().all()
    assert parent["status"] not in ("REJECTED_RISK", "REJECTED"), parent
    await wait_for(lambda: _len_async(children, 2), timeout=30)
    kids = await children()
    # the lot is sold by a non-bracket exit (the immediate book's time sweep)
    await eng.orders.place(OrderIntent(portfolio_id=shadow["id"], symbol="AAPL", side="SELL", qty=4,
                                       order_type="MKT", reduce_only=True, source="auto"))
    await wait_for(lambda: eng.positions.position_qty(shadow["id"], "AAPL") == 0, timeout=30)

    async def all_cancelled():
        return all(k.status == "CANCELLED" for k in await children())
    await wait_for(all_cancelled, timeout=30)
    # a late fill report on a child (venue race) is refused, never booked
    await eng.orders.on_report(ExecReport(kind="fill", order_id=kids[0].id, fill_qty=4,
                                          fill_price=px, exec_id="late-child"))
    assert eng.positions.position_qty(shadow["id"], "AAPL") == 0
    assert len(await _execs(eng, shadow["id"])) == 1
    assert any(e.payload.get("phase") == "fill" for e in await _events(eng, "ShadowSellRefused"))


async def _len_async(fn, n):
    return len(await fn()) >= n
