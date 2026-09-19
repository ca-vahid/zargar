"""tips-scorecard-v1 + census reuse: session anchor, cost attribution classes, questioned/repair separation, and the
census' armed-plan owner resolution. All database access is faked."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.tools import tip_outcomes, tip_scorecard as sc

UTC = dt.timezone.utc


def test_session_anchor_is_04_00_et():
    assert sc.session_of(dt.datetime(2026, 9, 18, 7, 59, tzinfo=UTC)) == dt.date(2026, 9, 17)   # 03:59 ET
    assert sc.session_of(dt.datetime(2026, 9, 18, 8, 0, tzinfo=UTC)) == dt.date(2026, 9, 18)    # 04:00 ET


def test_cost_attribution_classes_never_infer_from_settings():
    assert sc.attribute("intake", {"usage": {"in": 5, "model": "m-stamped"}}, analyst_model_configured=None) == ("m-stamped", "stamped")
    # a legacy per-call list (rule audit) carries the model on each call -> stamped
    assert sc.attribute("rule_audit", {"usage": [{"inputTokens": 3, "model": "m1"}]}, analyst_model_configured=None) == ("m1", "stamped")
    # a review run's own model field (written by its loop) -> run-record
    assert sc.attribute("intake", {"usage": {"in": 5}, "verdict": "review", "model": "m2"}, analyst_model_configured=None) == ("m2", "run-record")
    # an intake extraction record's model field is the EXTRACTOR identity and prices nothing
    assert sc.attribute("intake", {"usage": {"in": 5}, "model": "m3"}, analyst_model_configured=None) == (None, "unpriced")
    assert sc.attribute("digest", {"usage": {"in": 5}}, analyst_model_configured="m4") == (None, "unpriced")


def _census(realizations, unallocated=(), open_lots=(), execs=()):
    return {"realizations": list(realizations), "unallocated": list(unallocated), "open_lots": list(open_lots),
            "execs": list(execs), "orders": [], "rows": [], "ownerByOrder": {}}


async def test_questioned_and_repair_are_reported_apart(monkeypatch):
    t = dt.datetime(2026, 9, 17, 14, 5, tzinfo=UTC)
    real = [
        {"ts": t, "idea": "a", "book": "B", "symbol": "X", "qty": 1, "gross": 100.0, "fees": 2.0,
         "sellExec": "s1", "buyExec": "b1", "sellOrder": "", "buyOrder": ""},
        {"ts": t, "idea": "q", "book": "B", "symbol": "Y", "qty": 1, "gross": 50.0, "fees": 2.0,
         "sellExec": "s2", "buyExec": "QBUY", "sellOrder": "", "buyOrder": ""},
    ]
    repair_exec = {"order_id": "R1", "side": "BUY", "symbol": "Z", "qty": 10, "price": 11.0, "commission": 0,
                   "ts": dt.datetime(2026, 9, 15, 15, 54, tzinfo=UTC)}
    unalloc = [{"exec": "sx", "symbol": "Z", "book": "B", "qty": 10, "proceeds": 100.0, "fee": 0.0, "reason": "oversold"}]
    lots = [{"idea": "__unknown__", "symbol": "Z", "order_id": "R1", "qty": 10, "px": 11.0, "fee_unit": 0, "ts": repair_exec["ts"]}]
    monkeypatch.setattr(tip_outcomes, "build_census", AsyncMock(return_value=_census(real, unalloc, lots, [repair_exec])))

    class Conn:
        async def fetch(self, q, *a):
            return [{"id": "R1", "tags": ["reconcile:z-oversell"]}] if "source = 'manual'" in q else []
    reg = {"fills": [{"book": "B", "executions": ["QBUY"]}]}
    out = await sc.trading(Conn(), "2026-09-08", dt.date(2026, 9, 18), "B", reg)
    d17, d15 = out["days"][dt.date(2026, 9, 17)], out["days"][dt.date(2026, 9, 15)]
    assert d17["net"] == 98.0 and d17["q_net"] == 48.0            # method and questioned never blended
    assert d15["repair"] == -10.0                                  # 10 x (10.0 proceeds/unit - 11.0 buy) = -10
    assert out["open_lots"] == []                                  # the repair lot is not a live position


async def test_census_resolves_an_armed_plan_fill_to_its_signal():
    stamp = dt.datetime(2026, 9, 16, 19, 17, tzinfo=UTC)
    sig = {"id": "idea-a", "source_name": "S", "status": "proposed", "created_at": stamp - dt.timedelta(hours=2), "extraction": {}}
    order = {"id": "plan-buy", "signal_id": None, "symbol": "X", "side": "BUY", "filled_qty": 1, "limit_price": 5,
             "avg_fill_price": 5, "status": "FILLED", "portfolio_id": "tips", "source": "technique"}
    execs = [{"id": "e1", "order_id": "plan-buy", "portfolio_id": "tips", "symbol": "X", "side": "BUY", "qty": 1,
              "price": 5, "commission": 1, "ts": stamp},
             {"id": "e2", "order_id": "sell", "portfolio_id": "tips", "symbol": "X", "side": "SELL", "qty": 1,
              "price": 6, "commission": 1, "ts": stamp + dt.timedelta(minutes=5)}]

    class Conn:
        async def fetch(self, q, *a):
            if "FROM signals" in q:
                return [sig]
            if "FROM orders" in q:
                return [order]
            if "FROM executions" in q:
                return execs
            if "TechniquePlanOrderResult" in q:
                return [{"oid": "plan-buy", "sid": "idea-a"}, {"oid": "other", "sid": "outside-window"}]
            return []

        async def fetchrow(self, q, *a):
            return {"value": '{"v":"tips"}'}
    d = await tip_outcomes.build_census(Conn(), since_text="2026-09-08", portfolio="tips")
    assert d["ownerByOrder"]["plan-buy"] == "idea-a" and "other" not in d["ownerByOrder"]
    row = next(r for r in d["rows"] if r["id"] == "idea-a")
    assert row["disp"] == "filled-closed" and abs(row["realized"] - (-1.0)) < 1e-9   # shares: (6 - 5) x 1 - 2 fees; before: unknown-owner


def test_entry_horizons_score_keeps_missing_missing():
    from zargar.tools import tip_entry_horizons as eh
    ET = eh.ET
    t0 = dt.datetime(2026, 9, 17, 10, 45, tzinfo=ET)
    prints = [(dt.datetime(2026, 9, 17, 11, 20, tzinfo=ET), 1.70),          # +35 min
              (dt.datetime(2026, 9, 17, 15, 59, tzinfo=ET), 1.37),          # session close
              (dt.datetime(2026, 9, 18, 15, 59, tzinfo=ET), 0.69)]          # next close
    s = eh.score(t0, 1.59, prints)
    assert (s["p30"], s["pclose"], s["pnext"]) == (1.70, 1.37, 0.69)
    thin = eh.score(t0, 1.59, [(dt.datetime(2026, 9, 17, 12, 30, tzinfo=ET), 1.5)])   # no print in +30..45, none late
    assert thin["p30"] is None and thin["pclose"] is None and thin["pnext"] is None and thin["missing"] is False
    assert eh.score(t0, 1.59, None)["missing"] is True
    assert eh.next_session(dt.date(2026, 9, 18)) == dt.date(2026, 9, 21)                # Friday -> Monday


def test_entry_horizons_v2_calendar_windows_and_start_eligibility():
    from zargar.tools import tip_entry_horizons as eh
    ET = eh.ET
    # early close (day after Thanksgiving 2026-11-27, 13:00 ET): the close window is 12:30-13:00, never 15:30
    t0 = dt.datetime(2026, 11, 27, 10, 0, tzinfo=ET)
    s = eh.score(t0, 1.0, [(dt.datetime(2026, 11, 27, 12, 45, tzinfo=ET), 1.2), (dt.datetime(2026, 11, 27, 15, 30, tzinfo=ET), 9.9)])
    assert s["pclose"] == 1.2 and s["pcloseAt"].startswith("2026-11-27T12:45")
    # next close = the final 30 minutes of the NEXT TRADING day (Monday 11-30), not Saturday and not a morning print
    s2 = eh.score(t0, 1.0, [(dt.datetime(2026, 11, 30, 9, 31, tzinfo=ET), 0.5), (dt.datetime(2026, 11, 30, 15, 45, tzinfo=ET), 0.8)])
    assert s2["pnext"] == 0.8
    # a decision sampled outside the regular session has no executable start: nothing is scored
    pre = eh.score(dt.datetime(2026, 9, 17, 9, 23, tzinfo=ET), 1.0, [(dt.datetime(2026, 9, 17, 15, 59, tzinfo=ET), 2.0)])
    assert pre["inSession"] is False and pre["pclose"] is None
    # starting-quote eligibility reuses the executable-evidence rule
    sampled = dt.datetime(2026, 9, 17, 14, 45, 34, tzinfo=dt.timezone.utc)          # 10:45:34 ET
    ms = int(sampled.timestamp() * 1000)
    good = {"atDecision": {"ask": 1.59, "bid": 1.55, "source": "opra", "delayed": False, "sourceTs": ms - 2000}}
    assert eh.start_eligibility(good, sampled) == (True, [])
    for bad in ({"ask": 1.59, "bid": 1.55, "source": "chain", "delayed": True, "sourceTs": ms - 2000},      # delayed chain
                {"ask": 1.59, "bid": 1.55, "source": "opra", "delayed": False, "sourceTs": ms - 120_000},  # stale
                {"ask": 1.59, "bid": 1.70, "source": "opra", "delayed": False, "sourceTs": ms - 2000},     # crossed
                {"ask": 1.59, "bid": 1.55, "source": "opra", "delayed": False}):                            # no source time
        ok, why = eh.start_eligibility({"atDecision": bad}, sampled)
        assert ok is False and why


def test_render_prints_marked_and_realized_after_cost_separately_with_open_pnl():
    """ECON-01: a day with open P&L - marked change (+39.04) and realized (-11.18) differ, and BOTH after-cost
    figures are printed with the primary one labelled; the mark's actual timestamp is shown, not '16:00'."""
    import collections
    day = dt.date(2026, 9, 18)
    mark_ts = int(dt.datetime(2026, 9, 19, 7, 59, tzinfo=UTC).timestamp() * 1000)          # 03:59 ET next day
    prev_ts = int(dt.datetime(2026, 9, 18, 7, 59, tzinfo=UTC).timestamp() * 1000)
    per = collections.defaultdict(lambda: {"usd": 0.0, "runs": 0, "in": 0, "out": 0, "unpricedRuns": 0, "unpricedIn": 0,
                                           "partialRuns": 0, "unknownCalls": 0, "classes": collections.Counter()})
    per[(day, "intake-review")]["usd"] = 81.61
    res = {"version": sc.VERSION, "since": "2026-09-18", "until": "2026-09-18", "book": "B", "preIntervalExecutions": 40,
           "trading": {"days": {day: {"net": -11.18, "fees": 4.16, "q_net": 0.0, "repair": 0.0}}, "repairs": [],
                       "open_lots": [{"qty": 2, "px": 0.34, "symbol": "AAL261016C00014000", "fee_unit": 1.04, "ts": dt.datetime(2026, 9, 18, 14, tzinfo=UTC)}],
                       "census": {"unallocated": [], "rows": [], "realizations": [], "execs": [], "orders": [], "ownerByOrder": {}},
                       "questionedExecs": set()},
           "marks": {"start": 10000.0, "close": {dt.date(2026, 9, 17): (8925.42, 6679.92, prev_ts), day: (8964.46, 6758.70, mark_ts)}},
           "cash": {}, "model": {"per": per, "bySource": {}, "analystModelChanges": 0}, "shadows": [], "registry": {"fills": []}}
    out = sc.render(res)
    row = next(l for l in out.splitlines() if l.startswith("| 2026-09-18 |"))
    assert "+39.04" in row and "**-42.57**" in row and "-92.79" in row          # 39.04 - 81.61 and -11.18 - 81.61
    assert "09-19 03:59" in row and "MARKED after model cost (primary)" in out
    assert "Interval baseline: 8,925.42 = the 2026-09-17 accounting-day mark" in out
    assert "Equity identity:** not printed" in out                               # the report starts after inception
