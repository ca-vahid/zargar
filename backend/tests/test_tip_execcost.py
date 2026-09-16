"""TMR-02 (2026-09-16): execution-cost diagnostic - arithmetic with the venue's
fee basis, unknown on unqualified evidence, spread charged once, no side effects."""
from zargar.techniques.tip import execcost as ec


def _q(bid=1.40, ask=1.50, **kw):
    base = {"symbol": "XYZ260918C00100000", "bid": bid, "ask": ask, "bidSize": 12, "askSize": 30, "sourceTs": 1789580000000,
            "receivedTs": 1789580000500, "ageSeconds": 0.8, "source": "opra", "delayed": False,
            "sampledAt": "2026-09-16T14:00:00+00:00", "quoteStatus": "fresh", "eligibility": []}
    base.update(kw)
    return base


def test_option_round_trip_charges_spread_once_and_both_sides_fees():
    r = ec.round_trip(quote=_q(), quote_status="fresh", qty=2, sec_type="OPT", fee_per_contract=0.99, reg_per_contract=0.05)
    assert r["status"] == "known" and r["multiplier"] == 100.0
    assert r["spreadPerUnit"] == 0.1 and r["spread"] == 20.0            # (1.50 - 1.40) x 100 x 2
    assert r["entryFees"] == 2.08 and r["exitFees"] == 2.08              # (0.99 + 0.05) x 2 per side
    assert r["roundTrip"] == 24.16 and r["purchaseValue"] == 300.0 and r["costShareOfPurchase"] == round(24.16 / 300, 4)
    assert r["spreadPctOfAsk"] == round(0.1 / 1.5, 4) and r["bidSize"] == 12 and r["askSize"] == 30
    assert r["feeBasis"] == "per contract per side + regulatory per contract"
    assert "do not subtract it twice" in r["payoffAlreadyAtBid"] and "not expected profit" in r["meaning"]
    assert r["unknown"] == []


def test_shares_use_a_flat_commission_per_order_per_side():
    r = ec.round_trip(quote=_q(bid=100.00, ask=100.04, bidSize=None, askSize=None), quote_status="fresh", qty=50,
                      sec_type="STK", stock_commission=1.0)
    assert r["multiplier"] == 1.0 and r["spread"] == 2.0 and r["entryFees"] == 1.0 and r["exitFees"] == 1.0
    assert r["roundTrip"] == 4.0 and r["purchaseValue"] == 5002.0 and r["unknown"] == ["quotedSize"]
    zero = ec.round_trip(quote=_q(bid=100.00, ask=100.04), quote_status="fresh", qty=50, sec_type="STK")
    assert zero["roundTrip"] == 2.0, "Webull CA shares: $0 commission -> the spread is the whole cost"


def test_unqualified_evidence_is_unknown_never_a_guess():
    for quote, status, why in [
        (None, "missing", "no quote"),
        (_q(), "stale", "quote not qualified (stale)"),
        (_q(eligibility=["delayed chain snapshot"]), "ineligible", "quote not qualified (ineligible): delayed chain snapshot"),
        (_q(bid=1.60, ask=1.50), "fresh", "crossed quote"),
        (_q(bid=0.0, ask=1.50), "fresh", "one-sided or empty quote"),
    ]:
        r = ec.round_trip(quote=quote, quote_status=status, qty=2, sec_type="OPT", fee_per_contract=0.99)
        assert r["status"] == "unknown" and why in r["reasons"][0], (why, r["reasons"])
        assert r["roundTrip"] is None and r["spread"] is None and r["entryFees"] is None and r["costShareOfPurchase"] is None
        assert set(r["unknown"]) >= {"spread", "entryFees", "exitFees", "roundTrip", "purchaseValue", "costShareOfPurchase"}
    r = ec.round_trip(quote=_q(), quote_status="fresh", qty=0, sec_type="OPT")
    assert r["status"] == "unknown" and r["reasons"] == ["no quantity"]


def test_fill_vs_quote_is_one_fill_against_the_decision_quote():
    f = ec.fill_vs_quote(fill_price=1.52, fill_qty=2, limit=1.55, decision_quote=_q(), sec_type="OPT")
    assert f["vsLimit"] == -0.03 and f["vsAsk"] == 0.02 and f["vsAskDollars"] == 4.0 and f["vsMid"] == 0.07
    assert f["quoteMid"] == 1.45 and f["quoteSourceTs"] == 1789580000000 and f["unknown"] == []
    nothing = ec.fill_vs_quote(fill_price=None, fill_qty=0, limit=1.55, decision_quote=_q(), sec_type="OPT")
    assert nothing["unknown"] == ["fill"] and nothing["vsAsk"] is None
    no_quote = ec.fill_vs_quote(fill_price=1.52, fill_qty=2, limit=None, decision_quote={}, sec_type="OPT")
    assert no_quote["vsLimit"] is None and no_quote["unknown"] == ["ask", "mid"]
    sell = ec.fill_vs_quote(fill_price=1.38, fill_qty=1, limit=None, decision_quote=_q(), sec_type="OPT", side="SELL")
    assert sell["vsMid"] == 0.07, "a sell below mid is a worse fill too (positive = worse)"


async def test_diagnose_reads_the_live_quote_and_touches_nothing(rig):
    from .test_tip_geometry_wiring import _quote
    eng = rig
    q = await _quote(eng, "ECXA")
    orders_before = len(await _orders(eng))
    r = ec.diagnose(eng, symbol="ECXA", qty=10, sec_type="STK")
    assert r["symbol"] == "ECXA" and r["qty"] == 10.0 and r["multiplier"] == 1.0
    if r["status"] == "known":
        assert r["bid"] == q.bid and r["ask"] == q.ask and r["roundTrip"] == round((q.ask - q.bid) * 10, 2)
    else:
        assert r["reasons"], "an unknown diagnostic always says why"
    missing = ec.diagnose(eng, symbol="NOSUCHQUOTE", qty=1, sec_type="OPT")
    assert missing["status"] == "unknown" and missing["reasons"] == ["no quote"]
    assert len(await _orders(eng)) == orders_before
    fees = ec.fees_from_settings(eng.settings)
    assert set(fees) == {"feePerContract", "regPerContract", "stockCommission"}


async def _orders(eng):
    from sqlalchemy import select
    from zargar.models import Order
    async with eng.sf() as session:
        return list((await session.execute(select(Order))).scalars().all())


from .test_proposal_readiness import rig  # noqa: E402,F401
