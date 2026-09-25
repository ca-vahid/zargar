"""EM scorecard (`em-scorecard-v1`, 2026-09-22): the track record, the stop rule and the preregistered tests.

Pure: no database, no engine. Every threshold here was fixed before the data that decides it existed; these tests pin
that the module reports honestly - collecting until the sample is there, never a verdict on a partial reading.
"""
from zargar.technique import em_scorecard as sc

B, X = sc.BASELINE_BOOK, sc.EXPERIMENT_BOOK
OPT = "ORCL260925C00250000"


def _x(i, order, side, qty, price, *, sym="AAA", book=B, ts=None, fee=0.0):
    return {"id": f"x{i}", "order_id": order, "portfolio_id": book, "symbol": sym, "side": side, "qty": qty,
            "price": price, "commission": fee, "ts": ts if ts is not None else i * 1000}


def test_fifo_matching_books_partial_exits_and_leaves_open_lots_out():
    ex = [_x(1, "e1", "BUY", 10, 100.0, fee=1.0), _x(2, "s1", "SELL", 4, 102.0, fee=0.4), _x(3, "s2", "SELL", 6, 99.0, fee=0.6),
          _x(4, "e2", "BUY", 5, 50.0, sym="BBB")]                                   # never closed
    trades, open_lots = sc.match_trades(ex, exit_kind_by_order={"s1": "tp1", "s2": "stop"})
    assert len(trades) == 1 and list(open_lots) == [(B, "BBB")]
    t = trades[0]
    assert [l["kind"] for l in t["legs"]] == ["tp1", "stop"] and t["finalExit"] == "stop" and t["instrument"] == "shares"
    assert abs(t["gross"] - (8.0 - 6.0)) < 1e-9 and abs(t["net"] - (2.0 - 2.0)) < 1e-9


def test_options_carry_the_multiplier_and_a_disputed_fill_is_repriced_beside_never_instead():
    disputed = next(iter(sc.DISPUTED_FILLS))
    fair = sc.DISPUTED_FILLS[disputed]["fairPrice"]
    ex = [{**_x(1, "e1", "BUY", 1, 1.12, sym=OPT), "id": disputed}, _x(2, "s1", "SELL", 1, 2.50, sym=OPT)]
    (t,), _ = sc.match_trades(ex)
    assert t["instrument"] == "option" and abs(t["gross"] - 138.0) < 1e-6, "booked as recorded"
    assert abs(t["fairGross"] - (2.50 - fair) * 100) < 1e-6 and t["disputed"], "and repriced alongside, flagged"


def test_r_is_the_methods_own_planned_risk():
    shares = {"instrument": "shares", "qty": 10, "uEntry": 100.0, "uStop": 99.5, "net": -5.0, "fairNet": -5.0}
    assert sc.planned_risk(shares) == 5.0 and sc.r_of(shares) == -1.0
    opt = {"instrument": "option", "qty": 2, "avgEntry": 1.0, "net": 50.0, "fairNet": 50.0}
    assert sc.planned_risk(opt, premium_stop_pct=50) == 100.0 and sc.r_of(opt, premium_stop_pct=50) == 0.5
    assert sc.r_of({"instrument": "shares", "qty": 1, "uEntry": None, "uStop": 1, "net": 1}) is None, "no stop, no R - never guessed"


def _t(session, r, *, book=B, **kw):
    """A closed shares trade whose R is exactly r (risk 1)."""
    return {"session": session, "book": book, "instrument": "shares", "qty": 1, "uEntry": 10.0, "uStop": 9.0,
            "net": r, "fairNet": r, "fees": 0.0, **kw}


def _sessions(n, start=23):
    import datetime as dt
    d0 = dt.date(2026, 9, start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def test_the_stop_rule_collects_then_trips_or_passes_and_ignores_what_motivated_it():
    early = [_t("2026-09-18", -5.0)]                                              # before countFrom: never counted
    few = [_t(s, -1.0) for s in _sessions(5)]
    v = sc.stop_rule(early + few)
    assert v["verdict"] == "collecting" and v["evaluableSessions"] == 5
    losing = [_t(s, r) for s, r in zip(_sessions(20), [-1.0, 0.5] * 10)]
    v = sc.stop_rule(losing)
    assert v["verdict"] == "tripped" and v["summary"]["sumR"] == -5.0 and v["upperMeanR"] < 0.10
    winning = [_t(s, r) for s, r in zip(_sessions(20), [2.0, -1.0] * 10)]
    assert sc.stop_rule(winning)["verdict"] == "passing"
    noisy = [_t(s, r) for s, r in zip(_sessions(20), [-3.0, 2.9] * 10)]          # cum <= 0 but too noisy to rule out an edge
    v = sc.stop_rule(noisy)
    assert v["summary"]["sumR"] <= 0 and v["upperMeanR"] >= 0.10 and v["verdict"] == "passing"
    assert sc.stop_rule(losing, book=X)["evaluableSessions"] == 0, "judged per book"


def test_the_bootstrap_is_seeded_and_resamples_sessions():
    ts = [_t(s, r) for s, r in zip(_sessions(10), [0.3, -0.8, 1.2, -1.0, 0.1, -0.4, 2.0, -1.0, -1.0, 0.5])]
    assert sc.upper_mean_r(ts) == sc.upper_mean_r(ts)
    assert sc.upper_mean_r(ts[:1]) is None, "one session is no interval"


def test_impaired_book_sessions_are_kept_but_never_evaluated():
    s, book = next(iter(sc.IMPAIRED))
    assert not sc.evaluable({"session": s, "book": book})
    assert sc.evaluable({"session": s, "book": B}), "impairment is per book: the baseline traded normally that day"


def test_tests_stay_collecting_below_their_threshold_and_never_call_a_reading_a_verdict():
    base = [_t(s, -1.0, direction="long", window="prime_open", trigger="b1", underlying="AAA") for s in _sessions(5)]
    rows = {r["id"]: r for r in sc.run_tests(base)}
    assert rows["midday"]["status"] == "decided" and "OFF" in rows["midday"]["decision"]
    assert rows["rules_vs_model"]["status"] == "decided", "superseded by the 2026-09-23 decision"
    assert rows["shares_fallback"]["status"] == "decided" and "OFF" in rows["shares_fallback"]["decision"]
    for tid in ("short_puts_prime", "stop_vs_volatility", "one_touch_levels", "break_vs_level"):
        assert rows[tid]["status"] == "collecting" and rows[tid]["readingIsVerdict"] is False, tid
    shorts = [_t(s, -0.5, direction="short", window=w, trigger=f"r{i}", underlying=f"S{i}")
              for i, (s, w) in enumerate(zip(_sessions(25) * 1, ["prime_open", "prime_close", "midday"] * 9))]
    rows = {r["id"]: r for r in sc.run_tests(shorts)}
    assert rows["short_puts_prime"]["n"] == 17 and rows["short_puts_prime"]["status"] == "collecting", "midday shorts are not in the prime test"


def test_ready_needs_the_full_sample_and_the_copy_of_a_trade_counts_once():
    trades = []
    for i, s in enumerate(_sessions(20)):
        for book in (B, X):                                                       # the same decision in both books
            trades.append(_t(s, -1.0, book=book, direction="long", trigger="b1", underlying=f"U{i}"))
    rows = {r["id"]: r for r in sc.run_tests(trades)}
    assert rows["one_touch_levels"]["status"] == "collecting" and rows["shares_fallback"]["status"] == "decided"
    breaks = [_t(sess, -1.0, kind="breakout", trigger=f"k{i}", underlying=f"B{i}") for i, sess in enumerate(_sessions(30, start=24))]
    rows = {r["id"]: r for r in sc.run_tests(breaks)}
    assert rows["break_vs_level"]["status"] == "ready" and rows["break_vs_level"]["reading"]["breakMeanR"] == -1.0


def test_the_report_renders_every_decided_test_even_without_a_threshold_field():
    """2026-09-24 close: rules_vs_model was closed without a 'threshold' key and render() crashed (KeyError), so the close
    check reported 'stop rule: unknown'. Every decided row must render."""
    from zargar.tools.em_scorecard import render
    d = {"version": sc.VERSION, "generatedAt": "x", "allBooks": sc.summary([]), "allBooksCorrected": sc.summary([]), "deduplicated": sc.summary([]),
         "books": {}, "stopRule": sc.stop_rule([]), "tests": sc.run_tests([]), "premiumStopPct": 50.0,
         "friction": {"fees": 0, "entrySpread": 0, "entrySpreadTrades": 0, "exitSpread": None, "exitSpreadTrades": 0, "optionGross": 0},
         "impaired": {}, "disputed": [], "trades": 0, "openLots": 0}
    text = render(d)
    assert "rules_vs_model" in text and "STOP-RULE: collecting" in text
