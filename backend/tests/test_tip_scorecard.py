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
