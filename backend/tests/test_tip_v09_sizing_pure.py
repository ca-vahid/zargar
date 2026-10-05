"""Tips v0.9 V5/V6/V7 (2026-10-05): the pure halves - risk-first share caps, open risk, the source grade + Kelly, the
risk-scale view, the decision-time arithmetic and guards, the desk metrics and the execution-cost decomposition.
No DB, no network, no LLM."""
import datetime as dt

from zargar.domain import Bar
from zargar.techniques.tip import books as B
from zargar.techniques.tip import desk_metrics as DM
from zargar.techniques.tip import entry_context as EC
from zargar.techniques.tip import sizing as SZ
from zargar.tools.tip_exec_costs import fill_cost


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


# ------------------------------------------------------------------ V5.1
def test_risk_binds_when_the_stop_is_wide():
    c = SZ.share_caps(limit=100.0, stop=90.0, direction="long", risk_budget=100.0, notional_budget=3000.0,
                      position_room=5000.0)
    assert c["caps"]["risk"] == 10 and c["caps"]["notional"] == 30 and c["caps"]["positionPct"] == 50
    assert c["qty"] == 10 and c["binding"] == "risk" and c["plannedRisk"] == 100.0


def test_notional_binds_when_the_stop_is_tight_and_budget_is_an_upper_cap():
    c = SZ.share_caps(limit=100.0, stop=99.0, direction="long", risk_budget=100.0, notional_budget=3000.0)
    assert c["caps"]["risk"] == 100 and c["qty"] == 30 and c["binding"] == "notional"
    assert c["plannedRisk"] == 30.0


def test_position_and_name_caps_bind_and_ties_name_risk_first():
    c = SZ.share_caps(limit=50.0, stop=45.0, direction="long", risk_budget=500.0, notional_budget=10_000.0,
                      position_room=2000.0, name_room=1000.0)
    assert c["caps"] == {"risk": 100, "notional": 200, "positionPct": 40, "nameExposure": 20, "guard": None}
    half = SZ.share_caps(limit=50.0, stop=45.0, direction="long", risk_budget=250.0, notional_budget=5_000.0,
                         position_room=2000.0, name_room=1000.0, scale=0.5)
    assert half["caps"]["guard"] == 10 and half["qty"] == 10 and half["binding"] == "guard",         "an enforce guard halves the quantity even when an absolute ceiling binds"
    assert c["qty"] == 20 and c["binding"] == "nameExposure"
    tie = SZ.share_caps(limit=10.0, stop=9.0, direction="long", risk_budget=50.0, notional_budget=500.0)
    assert tie["qty"] == 50 and tie["binding"] == "risk"


def test_no_stop_or_wrong_side_falls_back_to_the_notional_cap_and_says_so():
    a = SZ.share_caps(limit=20.0, stop=None, direction="long", risk_budget=100.0, notional_budget=1000.0)
    assert a["caps"]["risk"] is None and a["qty"] == 50 and a["binding"] == "notional" and "no stop" in a["note"]
    b = SZ.share_caps(limit=20.0, stop=21.0, direction="long", risk_budget=100.0, notional_budget=1000.0)
    assert b["caps"]["risk"] is None and "wrong side" in b["note"]
    s = SZ.share_caps(limit=20.0, stop=22.0, direction="short", risk_budget=100.0, notional_budget=10_000.0)
    assert s["caps"]["risk"] == 50, "a short's stop sits above the entry"


def test_one_share_over_the_risk_budget_gives_zero():
    c = SZ.share_caps(limit=500.0, stop=400.0, direction="long", risk_budget=50.0, notional_budget=1000.0)
    assert c["caps"]["risk"] == 0 and c["qty"] == 0 and c["binding"] == "risk"


def test_open_risk_of_shares_uses_the_live_stop_and_never_goes_negative():
    legs = [{"qty": 100, "avgFill": 20.0, "secType": "STK", "multiplier": 1}]
    assert SZ.position_open_risk(legs, {"policy": {"stop": {"price": 18.0}}}, {}) == 200.0
    assert SZ.position_open_risk(legs, {"policy": {"stop": {"price": 18.0}}},
                                 {"policyState": {"stop": 19.5}}) == 50.0, "a trailed stop shrinks the open risk"
    assert SZ.position_open_risk(legs, {}, {"policyState": {"stop": 21.0}}) == 0.0, "stop above entry = no risk"
    assert SZ.position_open_risk(legs, {"risk": 0.5}, {}) == 50.0, "no stop -> the entry-time distance"
    assert SZ.position_open_risk([{"qty": 0, "avgFill": 20, "secType": "STK"}], {}, {}) == 0.0


def test_open_risk_of_options_scales_the_planned_risk_else_the_premium():
    legs = [{"qty": 2, "avgFill": 1.5, "secType": "OPT", "multiplier": 100}]
    assert SZ.position_open_risk(legs, {"extras": {"riskPlan": {"plannedRisk": 120.0, "qty": 4}}}, {}) == 60.0
    assert SZ.position_open_risk(legs, {}, {}) == 300.0


def test_open_risk_cap():
    assert SZ.open_risk_refusal(equity=10_000, open_risk=400, this_risk=100, cap_pct=5) is None
    why = SZ.open_risk_refusal(equity=10_000, open_risk=450, this_risk=100, cap_pct=5)
    assert why and "open-risk cap" in why and "$550" in why
    assert SZ.open_risk_refusal(equity=10_000, open_risk=9e9, this_risk=None, cap_pct=5) is None, "unknown risk: not judged"
    assert SZ.open_risk_refusal(equity=10_000, open_risk=9e9, this_risk=1, cap_pct=0) is None, "0 = off"


# ------------------------------------------------------------------ V5.2
def test_grade_is_ungraded_below_the_minimum_and_shrinks_the_edge():
    g = SZ.grade_source([1.0] * 5, min_n=20)
    assert g["status"] == "ungraded" and g["n"] == 5 and g["shrunkEdge"] == round(1.0 * 5 / 25, 4)
    rs = [2.0] * 10 + [-1.0] * 10                                  # mean +0.5R, hit 50%
    g = SZ.grade_source(rs, min_n=20, k=20, fraction=0.25)
    assert g["status"] == "positive" and g["hitRate"] == 0.5 and g["meanR"] == 0.5
    assert g["shrunkEdge"] == 0.25 and g["winMeanR"] == 2.0 and g["lossMeanR"] == -1.0
    # Kelly on R outcomes: shrunk mean / E[R^2] = 0.25 / 2.5 = 10% of equity per 1R; a quarter = 2.5%
    assert g["kellyPct"] == 10.0 and g["fractionalKellyPct"] == 2.5


def test_negative_shrunk_edge_is_watch_only_and_kelly_caps_the_risk():
    neg = SZ.grade_source([-1.0] * 12 + [1.0] * 8, min_n=20)
    assert neg["status"] == "negative"
    d = SZ.kelly_decision(neg, risk_pct=1.0, mode="observe")
    assert d["watchOnly"] and not d["applied"]
    assert SZ.kelly_decision(neg, risk_pct=1.0, mode="enforce")["applied"]
    small = SZ.grade_source([3.0] * 10 + [-2.9] * 10, min_n=20)   # tiny edge, wide outcomes -> small Kelly
    d = SZ.kelly_decision(small, risk_pct=1.0, mode="enforce")
    assert d["applied"] and 0 < d["scale"] < 1 and d["riskPct"] == small["fractionalKellyPct"]
    big = SZ.grade_source([2.0] * 10 + [-1.0] * 10, min_n=20)
    assert SZ.kelly_decision(big, risk_pct=1.0, mode="enforce")["scale"] == 1.0, "never above the book's risk %"
    assert SZ.kelly_decision(big, risk_pct=1.0, mode="off")["scale"] == 1.0
    assert SZ.kelly_decision(SZ.grade_source([1.0], min_n=20), risk_pct=1.0, mode="enforce")["applied"] is False


def test_risk_scale_applies_only_to_the_risk_budget_keys():
    base = S({"techniques.tip.risk_pct": 1.0, "techniques.tip.risk_budget_per_tip": 80.0,
              "techniques.tip.budget_per_tip": 1000.0})
    with B.scale_risk(0.5):
        v = B.BookSettings(base)
        assert v.get("techniques.tip.risk_pct") == 0.5 and v.get("techniques.tip.risk_budget_per_tip") == 40.0
        assert v.get("techniques.tip.budget_per_tip") == 1000.0
        assert B.risk_scale() == 0.5
    assert B.risk_scale() == 1.0 and B.BookSettings(base).get("techniques.tip.risk_pct") == 1.0
    with B.scale_risk(7):
        assert B.risk_scale() == 1.0, "never scales up"
    b = B._parse_one({"portfolioId": "x", "maxOpenRiskPct": 7})
    assert B.knob(b, "maxOpenRiskPct", S({}), 5.0) == 7 and B.knob(None, "maxOpenRiskPct", S({}), 5.0) == 5.0


# ------------------------------------------------------------------ V6
def _daily(n: int, *, start=100.0, step=0.5, vol=1_000_000, end_day=dt.date(2026, 10, 2)) -> list:
    out, day = [], end_day
    days = []
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= dt.timedelta(days=1)
    for i, d in enumerate(reversed(days)):
        c = start + step * i
        ts = int(dt.datetime(d.year, d.month, d.day, 13, 30, tzinfo=dt.timezone.utc).timestamp() * 1000)
        out.append(Bar(symbol="X", tf="1d", ts=ts, open=c - 0.2, high=c + 1.0, low=c - 1.0, close=c, volume=vol))
    return out


def test_symbol_metrics_atr_rvol_mas_gap_and_returns():
    bars = _daily(60)
    done, cur = EC.split_daily(bars, "2026-10-05")
    assert len(done) == 60 and cur is None
    last = done[-1].close
    m = EC.symbol_metrics(done, last=last * 1.03, prev_close=None, day_volume=500_000, today_open=last * 1.01, frac=0.25)
    assert m["prevClose"] == round(last, 4) and m["changePct"] == 3.0 and m["gapPct"] == 1.0
    assert m["atr"] == 2.0 and m["atrPct"] == round(2.0 / last * 100, 2)
    assert m["rvol"] == 0.5 and m["rvolAdj"] == 2.0, "half the average volume a quarter into the session = 2x pace"
    assert m["distMa20Pct"] > 0 and m["distMa50Pct"] > m["distMa20Pct"]
    assert m["ret5"] is not None and m["ret20"] is not None
    assert EC.symbol_metrics([], last=None, prev_close=None, day_volume=None, today_open=None, frac=None)["atr"] is None


def test_regime_metrics_and_hostile_regime_decision():
    up = _daily(540, start=300.0, step=0.4)
    rg = EC.regime_metrics(up, last=None, vix=18.0)
    assert rg["spyAbove200"] is True and rg["spy2yPct"] > 0 and rg["vix"] == 18.0 and rg["spyVol126Pct"] is not None
    down = _daily(540, start=600.0, step=-0.4)
    hostile = {"regime": EC.regime_metrics(down, last=None, vix=31.0), "distMa20Pct": 2.0, "changePct": 1.0}
    assert hostile["regime"]["spy2yPct"] < 0
    d = EC.regime_decision(hostile, direction="long", settings=S({}))
    assert d["hostile"] and d["momentum"] and d["would"] == "halve" and d["scale"] == 0.5 and not d["applied"]
    assert EC.regime_decision(hostile, direction="long", settings=S({"techniques.tip.regime_guard": "enforce"}))["applied"]
    calm = {"regime": {**hostile["regime"], "vix": 15.0}}
    assert EC.regime_decision(calm, direction="long", settings=S({}))["hostile"] is False
    dip = {**hostile, "distMa20Pct": -3.0, "changePct": -1.5}
    assert EC.regime_decision(dip, direction="long", settings=S({}))["would"] is None, "a dip entry is not momentum"
    assert EC.regime_decision({}, direction="long", settings=S({}))["hostile"] is None, "unknown never acts"
    novix = {"regime": {**hostile["regime"], "vix": None, "spyVol126Pct": 40.0}, "distMa20Pct": 1.0, "changePct": 1.0}
    assert EC.regime_decision(novix, direction="long", settings=S({}))["hostile"] is True


def test_chase_filter():
    ctx = {"prevClose": 100.0, "price": 102.5}
    d = EC.chase_decision(ctx, direction="long", entry_price=None, settings=S({}))
    assert d["chased"] and d["entryVsPrevClosePct"] == 2.5 and d["would"] and not d["applied"] and d["maxHoldSessions"] == 3
    e = EC.chase_decision(ctx, direction="long", entry_price=None, settings=S({"techniques.tip.chase_filter": "enforce"}))
    assert e["applied"] and e["scale"] == 0.5 and e["horizon"] == "short"
    assert EC.chase_decision({"prevClose": 100.0, "price": 101.0}, direction="long", entry_price=None,
                             settings=S({}))["chased"] is False
    assert EC.chase_decision({"prevClose": 100.0, "price": 97.0}, direction="short", entry_price=None,
                             settings=S({}))["chased"] is True
    assert EC.chase_decision({}, direction="long", entry_price=None, settings=S({}))["chased"] is None
    off = EC.chase_decision(ctx, direction="long", entry_price=None, settings=S({"techniques.tip.chase_filter": "off"}))
    assert off["chased"] and off["would"] is None


def test_header_line_and_card_context():
    done = _daily(60)
    sm = EC.symbol_metrics(done, last=done[-1].close, prev_close=None, day_volume=1_000_000, today_open=None, frac=1.0)
    rg = EC.regime_metrics(_daily(540, start=300.0, step=0.4), last=None, vix=None)
    ctx = EC.compose(sm, rg, {"sector": "Technology", "shortRatio": 6.2}, 12, symbol="X", session="2026-10-05",
                     problems={"vix": "timed out"})
    line = EC.header_line(ctx)
    assert line.startswith("- decision-time context") and "ATR" in line and "days-to-cover 6.2" in line
    assert "sector Technology" in line and "unavailable: vix" in line and line.endswith("\n")
    card = EC.card_context(ctx)
    assert card["sector"] == "Technology" and card["daysToEarnings"] == 12 and "ma20" not in card
    assert EC.header_line({"status": "offline"}).startswith("- decision-time context: unavailable")
    assert EC.header_line(None) == "" and EC.card_context({"status": "off"}) is None


def test_elapsed_fraction():
    et = EC.ET
    assert EC.elapsed_fraction(dt.datetime(2026, 10, 5, 9, 0, tzinfo=et)) is None
    assert EC.elapsed_fraction(dt.datetime(2026, 10, 5, 12, 45, tzinfo=et)) == 0.5
    assert EC.elapsed_fraction(dt.datetime(2026, 10, 5, 17, 0, tzinfo=et)) == 1.0


# ------------------------------------------------------------------ V7
def test_desk_metric_helpers():
    assert DM.mfe_kept(realized_r=1.0, peak_r=2.0) == 0.5
    assert DM.mfe_kept(realized_r=-1.0, peak_r=0.0) is None
    assert DM.noise_stop(direction="long", entry=100, risk=2, highs_after=[101, 102.5], lows_after=[]) is True
    assert DM.noise_stop(direction="long", entry=100, risk=2, highs_after=[101], lows_after=[]) is False
    assert DM.noise_stop(direction="long", entry=100, risk=2, highs_after=[], lows_after=[]) is None
    assert DM.noise_stop(direction="short", entry=100, risk=2, highs_after=[], lows_after=[97.5]) is True
    assert DM.horizon_of({"horizon": "swing"}, []) == "swing"
    assert DM.horizon_of({"extras": {"horizon": {"class": "extended"}}}, []) == "extended"
    assert DM.horizon_of({}, ["source:x", "horizon:short"]) == "short" and DM.horizon_of({}, []) is None
    assert DM.is_stop_exit({"closeReason": "stop 17.00 hit"}) and DM.is_stop_exit({"exits": [{"kind": "venue_stop"}]})
    assert not DM.is_stop_exit({"closeReason": "target", "exits": [{"kind": "ladder"}]})
    line = DM.summary_line({"books": [{"portfolioId": "abcdef12", "name": "P", "openPositions": 3, "utilisationPct": 42.0,
                                        "openRiskPct": 2.5, "openRiskCapPct": 5.0, "mfeKeptMean": 0.4,
                                        "stopOuts": 2, "noiseStopOuts": 1}]})
    assert line == "Tips: P: 3 open, 42% deployed, risk 2.5%/5%, MFE kept 40%, 1/2 noise stops"


def test_fill_cost_decomposition():
    buy = fill_cost(side="BUY", qty=100, price=10.02, multiplier=1, commission=1.0, bid=9.98, ask=10.02, limit=10.05)
    assert buy["spreadPaid"] == 2.0 and buy["slippage"] == 0.0 and buy["vsLimit"] == -3.0 and buy["allIn"] == 3.0
    sell = fill_cost(side="SELL", qty=2, price=1.40, multiplier=100, commission=1.3, bid=1.45, ask=1.55, limit=None)
    assert sell["spreadPaid"] == 20.0 and sell["slippage"] == 10.0
    bid_only = fill_cost(side="SELL", qty=10, price=5.0, multiplier=1, commission=0, bid=5.0, ask=None, limit=None)
    assert bid_only["spreadPaid"] is None and bid_only["slippage"] == 0.0 and bid_only["unknown"]
    none = fill_cost(side="BUY", qty=1, price=5.0, multiplier=1, commission=0.35, bid=None, ask=None, limit=None)
    assert none["spreadPaid"] is None and "decision quote" in none["unknown"] and none["allIn"] == 0.35
