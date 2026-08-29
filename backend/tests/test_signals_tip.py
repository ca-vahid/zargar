"""Tip technique unit tests — extraction v2 grounding (Discord shorthand),
dedupe keys, verification parking, source policy, and the tip plan builder.
No LLM, no DB: pure functions + canned schemas."""
import time

from zargar.domain import Bar, Quote
from zargar.marketstructure import simulate_plan
from zargar.signals.extraction import ground_signal
from zargar.signals.schemas import TradeSignal
from zargar.signals.service import dedupe_key_for
from zargar.signals.sources import resolve_policy
from zargar.signals.verification import verify_signal
from zargar.techniques.tip import build_tip_plan

NOW_MS = int(time.time() * 1000)


def sig(**kw):
    base = dict(ticker="NVDA", direction="long", action="open",
                entry_price=None, target_price=None, stop_price=None,
                entry_type="unspecified", timeframe="swing", thesis_summary="x",
                evidence_quotes=["NVDA 180c 9/19"], confidence="explicit_call",
                is_actionable=True)
    base.update(kw)
    return TradeSignal(**base)


# --- grounding: Discord shorthand -------------------------------------------------

def test_shorthand_strike_grounds():
    s = sig(instrument="call", strike=180.0, expiry="2026-09-19")
    g = ground_signal(s, "some room chatter NVDA 180c 9/19 🚀🚀")
    assert g["passed"], g["checks"]


def test_shorthand_price_with_dollar_and_comma_grounds():
    s = sig(ticker="BRK.B", entry_price=1250.50,
            evidence_quotes=["BRK.B entry $1,250.50"])
    g = ground_signal(s, "BRK.B entry $1,250.50 looks good")
    assert g["checks"]["entry_evidenced"], g["checks"]


def test_ungrounded_strike_fails():
    s = sig(instrument="call", strike=185.0)   # quote says 180c
    g = ground_signal(s, "NVDA 180c 9/19")
    assert not g["checks"]["strike_evidenced"]
    assert not g["passed"]


def test_target_prices_all_must_ground():
    s = sig(target_prices=[190.0, 200.0],
            evidence_quotes=["NVDA targets 190 then 200"])
    g = ground_signal(s, "NVDA targets 190 then 200")
    assert g["checks"]["target_evidenced"]
    s2 = sig(target_prices=[190.0, 205.0],
             evidence_quotes=["NVDA targets 190 then 200"])
    g2 = ground_signal(s2, "NVDA targets 190 then 200")
    assert not g2["checks"]["target_evidenced"]


# --- dedupe ----------------------------------------------------------------------

def test_dedupe_key_same_tip_same_key():
    a = dedupe_key_for("room-x", sig(instrument="call", strike=180.0, expiry="2026-09-19"))
    b = dedupe_key_for("room-x", sig(instrument="call", strike=180.0, expiry="2026-09-19",
                                     thesis_summary="different words entirely"))
    assert a == b


def test_dedupe_key_differs_by_strike_and_source():
    base = sig(instrument="call", strike=180.0)
    assert dedupe_key_for("room-x", base) != dedupe_key_for("room-y", base)
    assert (dedupe_key_for("room-x", base)
            != dedupe_key_for("room-x", sig(instrument="call", strike=185.0)))


# --- verification parking ---------------------------------------------------------

class FakeQuotes:
    def __init__(self):
        self.quotes = {}

    def set(self, symbol, last, spread=0.02, halted=False):
        self.quotes[symbol] = Quote(
            symbol=symbol, last=last, bid=last - spread / 2, ask=last + spread / 2,
            bid_size=500, ask_size=500, halted=halted, ts=int(time.time() * 1000))

    def get(self, symbol):
        return self.quotes.get(symbol)


class FakeSettings:
    def __init__(self, **overrides):
        self.values = dict(overrides)

    def get(self, key, default=None):
        return self.values.get(key, default)


async def test_price_deviation_parks_not_kills():
    quotes = FakeQuotes()
    quotes.set("NVDA", 190.0)   # far from claimed entry
    s = sig(entry_price=170.0, target_price=200.0, stop_price=165.0,
            evidence_quotes=["NVDA entry 170 target 200 stop 165"])
    v = await verify_signal(s, quotes, FakeSettings(), grounding={"passed": True})
    assert not v["passed"]
    assert v["park"], v["checks"]


async def test_fatal_failure_never_parks():
    quotes = FakeQuotes()
    quotes.set("NVDA", 190.0, halted=True)
    s = sig(entry_price=170.0, target_price=200.0, stop_price=165.0)
    v = await verify_signal(s, quotes, FakeSettings(), grounding={"passed": True})
    assert not v["passed"] and not v["park"]


async def test_short_ordering_mirror():
    quotes = FakeQuotes()
    quotes.set("NVDA", 170.0)
    s = sig(direction="short", instrument="put", entry_price=170.0,
            target_price=160.0, stop_price=175.0,
            evidence_quotes=["NVDA puts entry 170 target 160 stop 175"])
    v = await verify_signal(s, quotes, FakeSettings(), grounding={"passed": True})
    assert v["passed"], v["checks"]
    bad = sig(direction="short", entry_price=170.0, target_price=180.0, stop_price=160.0)
    v2 = await verify_signal(bad, quotes, FakeSettings(), grounding={"passed": True})
    ordering = next(c for c in v2["checks"] if c["name"] == "price_ordering")
    assert not ordering["passed"]


# --- source policy ---------------------------------------------------------------

def test_policy_defaults_and_overrides():
    s = FakeSettings(**{
        "techniques.tip.risk_pct": 1.0,
        "techniques.tip.sources": {
            "room-x": {"entry": "tip_time", "mode": "shadow", "risk_pct": 0.5},
        },
    })
    unknown = resolve_policy(s, "somebody-new")
    assert unknown.entry == "level_touch" and unknown.mode == "proposal"
    earned = resolve_policy(s, "room-x")
    assert earned.entry == "tip_time" and earned.mode == "shadow"
    assert earned.risk_pct == 0.5
    assert earned.dte_min == 10 and earned.dte_max == 30   # platform defaults survive


def test_policy_rejects_junk_modes():
    s = FakeSettings(**{"techniques.tip.sources": {"x": {"entry": "yolo", "mode": "warp"}}})
    p = resolve_policy(s, "x")
    assert p.entry == "level_touch" and p.mode == "proposal"


# --- expiry-aware waiting (options tips die at expiry) ---------------------------

def test_wait_window_capped_by_contract_expiry():
    import datetime as dt

    from zargar.techniques.tip.horizon import effective_wait_sessions, tip_expiry
    today = dt.date(2026, 8, 27)                      # a Thursday
    # "NVDA 180c 9/4" — expiry next Friday, cutoff 2d => last entry day Sep 2 (Wed)
    exp = tip_expiry("2026-09-04", None, today)
    wait = effective_wait_sessions(policy_horizon=10, tip_horizon=None,
                                   expiry=exp, today=today, entry_cutoff_dte=2)
    assert wait == 4                                   # Fri 28, Mon 31, Tue 1, Wed 2
    # expiring tomorrow: cutoff has passed — too late, don't chase theta
    exp2 = tip_expiry("2026-08-28", None, today)
    assert effective_wait_sessions(policy_horizon=10, tip_horizon=None,
                                   expiry=exp2, today=today, entry_cutoff_dte=2) == 0


def test_wait_window_from_dte_hint_and_policy():
    import datetime as dt

    from zargar.techniques.tip.horizon import effective_wait_sessions, tip_expiry
    today = dt.date(2026, 8, 27)
    # "weeklies" hint ~5 days from receipt; cutoff 2 => last entry Sun Aug 30,
    # so only Friday the 28th remains as a session to wait in
    exp = tip_expiry(None, 5, today)
    assert exp == dt.date(2026, 9, 1)
    wait = effective_wait_sessions(policy_horizon=10, tip_horizon=None,
                                   expiry=exp, today=today, entry_cutoff_dte=2)
    assert wait == 1                                   # Fri 28 only
    # no expiry info at all: the policy/tip horizon rules
    assert effective_wait_sessions(policy_horizon=10, tip_horizon=4, expiry=None,
                                   today=today, entry_cutoff_dte=2) == 4


def test_hold_cap_is_the_thesis_expiry():
    import datetime as dt

    from zargar.techniques.tip.horizon import hold_sessions_cap
    today = dt.date(2026, 8, 27)
    assert hold_sessions_cap(expiry=dt.date(2026, 9, 4), today=today, fallback=10) == 6
    assert hold_sessions_cap(expiry=None, today=today, fallback=10) == 10
    assert hold_sessions_cap(expiry=dt.date(2026, 8, 27), today=today, fallback=10) == 1


# --- the tip plan builder --------------------------------------------------------

def bars_with_support(symbol="NVDA", tf="5m", support=100.0, n=60):
    """Oscillating bars that touch `support` several times and close above it."""
    out = []
    ts = NOW_MS - n * 300_000
    for i in range(n):
        lo = support if i % 7 == 0 else support + 0.8
        close = support + 1.5 + (i % 5) * 0.3
        out.append(Bar(symbol=symbol, tf=tf, ts=ts + i * 300_000,
                       open=close - 0.2, high=close + 0.6, low=lo, close=close,
                       volume=10_000))
    return out


def test_level_touch_long_plan():
    bars = bars_with_support()
    plan = build_tip_plan(symbol="nvda", direction="long", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, source="room-x",
                          signal_id="sig123", thesis="going up")
    assert plan.symbol == "NVDA"
    [t] = plan.triggers
    # level_touch rides the tracker's touch-fire mechanics (bounce/reject)
    assert t.kind == "bounce" and t.direction == "long" and t.valid
    # the UI shows WHO tipped, never the raw id ("tip-71796b9b3378", 2026-08-29)
    assert t.id == "tip-sig123" and t.label == "room-x tip"
    assert t.to_dict()["label"] == "room-x tip"
    assert t.entry_basis == "at_level"
    assert t.entry_price <= 102.5 * 1.001
    assert t.stop_price < t.entry_price
    assert all(tgt["price"] > t.entry_price for tgt in t.targets)
    assert plan.gap_policy["policy"] == "ignore"
    assert plan.context["source"] == "room-x" and plan.context["signalId"] == "sig123"


def test_tip_entry_price_wins_when_on_right_side():
    bars = bars_with_support()
    plan = build_tip_plan(symbol="NVDA", direction="long", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, tip_entry=101.0, tip_stop=99.0,
                          tip_targets=[105.0, 110.0])
    [t] = plan.triggers
    assert t.entry_price == 101.0 and t.stop_price == 99.0
    assert [x["price"] for x in t.targets] == [105.0, 110.0]


def test_breakout_tip_level_honoured():
    # "watch $22 for a breakout" with price at 20.5 (2026-08-28, PeloSwing BOIL):
    # the stated level is ABOVE price — it must become a breakout trigger at the
    # tip's own level, never a substitute dip-buy at a support below
    bars = bars_with_support()
    plan = build_tip_plan(symbol="BOIL", direction="long", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, tip_entry=106.0,
                          source="PeloSwing", thesis="wedge breakout")
    [t] = plan.triggers
    assert t.kind == "breakout" and t.direction == "long" and t.valid
    assert t.entry_price == 106.0                # the tip's level, verbatim
    assert t.entry_basis == "on_break"           # fires on the close through
    assert t.stop_price < 106.0
    assert all(tgt["price"] > 106.0 for tgt in t.targets)
    assert "breakout entry from the tip itself" in t.notes


def test_breakdown_tip_level_honoured():
    bars = bars_with_support()
    plan = build_tip_plan(symbol="XYZ", direction="short", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, tip_entry=99.0)
    [t] = plan.triggers
    assert t.kind == "breakdown" and t.entry_price == 99.0
    assert t.entry_basis == "on_break"
    assert t.stop_price > 99.0                   # short mirror
    assert all(tgt["price"] < 99.0 for tgt in t.targets)


async def test_replay_breakout_fills_on_close_through():
    # the replay emulates the tracker for breakout tips: fill on the first
    # CLOSE through the level, or honestly report "never filled"
    from zargar.techniques.tip.replay import replay_tip
    HOUR = 3_600_000
    now = NOW_MS

    def mk_bars(crosses: bool) -> list[Bar]:
        out = []
        n = 400
        for i in range(n):
            frac = i / n
            if frac < 0.6:
                c = 100.0 + (i % 4) * 0.2            # coil below the level
            else:
                c = (107.0 + (frac - 0.6) * 20) if crosses else 104.0
            out.append(Bar(symbol="T", tf="1h", ts=now - (n - i) * HOUR,
                           open=c, high=c + 0.5, low=c - 0.5, close=c, volume=1000))
        return out

    async def fetch_cross(sym, tf, s, e):
        return mk_bars(True)

    async def fetch_flat(sym, tf, s, e):
        return mk_bars(False)

    stated = now - 300 * HOUR                        # inside the bar span, before the cross
    out = await replay_tip(symbol="T", direction="long", stated_at_ms=stated,
                           tip_entry=106.0, horizon_sessions=40, fetch=fetch_cross)
    assert out["ok"] and out["armed"]["filled"]
    assert out["armed"]["entry"] == 106.0            # the tip's level, not a dip-buy

    out2 = await replay_tip(symbol="T", direction="long", stated_at_ms=stated,
                            tip_entry=106.0, horizon_sessions=40, fetch=fetch_flat)
    assert out2["ok"] and not out2["armed"]["filled"]
    assert out2["armed"]["outcome"] == "not_filled"  # never crossed — says so


def test_tip_time_short_plan():
    bars = bars_with_support()
    plan = build_tip_plan(symbol="NVDA", direction="short", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, entry_mode="tip_time",
                          instrument_hint="put")
    [t] = plan.triggers
    assert t.entry_basis == "on_break"           # immediate fill semantics
    assert t.entry_price == 102.5
    assert t.stop_price > t.entry_price          # short mirror
    assert all(tgt["price"] < t.entry_price for tgt in t.targets)
    assert t.valid


def test_wrong_side_tip_stop_falls_back_to_atr():
    bars = bars_with_support()
    plan = build_tip_plan(symbol="NVDA", direction="long", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, tip_entry=101.0,
                          tip_stop=103.0)      # stop above a long entry: nonsense
    [t] = plan.triggers
    assert t.valid
    assert t.stop_price < t.entry_price
    assert t.stop_reference.startswith("atr")


def test_tip_plan_is_simulatable_by_shared_walkforward():
    """The whole point: a tip plan feeds the same simulate_plan as EM."""
    bars = bars_with_support()
    plan = build_tip_plan(symbol="NVDA", direction="long", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, tip_entry=101.0, tip_stop=99.5,
                          tip_targets=[103.0])
    trig = plan.triggers[0].to_dict()
    # future: dips to the entry, then rallies through the target
    future = list(bars)
    ts0 = bars[-1].ts
    path = [(100.9, 101.2), (101.5, 102.2), (102.8, 103.4), (103.5, 104.0)]
    for i, (lo, close) in enumerate(path):
        future.append(Bar(symbol="NVDA", tf="5m", ts=ts0 + (i + 1) * 300_000,
                          open=close - 0.3, high=close + 0.4, low=lo, close=close,
                          volume=9_000))
    out = simulate_plan(future, len(bars) - 1, trig, entry_window=5, horizon=10)
    assert out["filled"]
    assert out["outcome"] in ("tp1", "horizon")
    assert out["rMultiple"] > 0


def test_scale_in_ladder_builds_multi_trigger_plan():
    # ARM-PLAN P3: one trigger per rung, sizeFraction each, ONE shared stop
    # beyond the deepest rung; a rung on the wrong side of price is dropped
    bars = bars_with_support()
    plan = build_tip_plan(symbol="NVDA", direction="long", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, tip_stop=99.0,
                          tip_targets=[105.0, 110.0], signal_id="sigsc1",
                          scale_ins=[{"price": 101.5, "fraction": 0.5},
                                     {"price": 100.5, "fraction": 0.5},
                                     {"price": 103.9, "fraction": 0.5}])  # wrong side: dropped
    assert len(plan.triggers) == 2
    t1, t2 = plan.triggers
    assert (t1.entry_price, t2.entry_price) == (101.5, 100.5)   # nearest rung first
    assert t1.size_fraction == 0.5 and t2.size_fraction == 0.5
    assert t1.stop_price == t2.stop_price == 99.0               # one campaign, one stop
    assert t1.valid and t2.valid
    d = t1.to_dict()
    assert d["sizeFraction"] == 0.5                             # serialized for the armer
    # single-trigger plans stay unchanged on the wire (EM untouched)
    single = build_tip_plan(symbol="NVDA", direction="long", reference_price=102.5,
                            bars=bars, as_of_ms=NOW_MS, tip_entry=101.0)
    assert "sizeFraction" not in single.triggers[0].to_dict()


def test_scale_in_short_side_and_shared_atr_stop():
    bars = bars_with_support()
    plan = build_tip_plan(symbol="NVDA", direction="short", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS,
                          tip_targets=[98.0],
                          scale_ins=[{"price": 103.5, "fraction": 0.4},
                                     {"price": 104.5, "fraction": 0.6}])
    assert len(plan.triggers) == 2
    t1, t2 = plan.triggers
    assert (t1.entry_price, t2.entry_price) == (103.5, 104.5)   # nearest first (short: lower)
    assert t1.kind == "reject" and t2.kind == "reject"
    assert t1.stop_price == t2.stop_price > 104.5               # ATR stop beyond the deepest rung


def test_guards_evaluator_kinds():
    # ARM-PLAN P4: the pure guard evaluator, one case per kind
    from zargar.domain import Bar
    from zargar.marketstructure.guards import evaluate_guards
    mk = lambda ts, close: Bar(symbol="T", tf="1m", ts=ts, open=close, high=close + 0.1,
                               low=close - 0.1, close=close, volume=0)
    import datetime as _dt
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    at = lambda h, m: int(_dt.datetime(2026, 8, 28, h, m, tzinfo=et).timestamp() * 1000)

    closes = [100.0] * 8 + [101.0]
    ok, why = evaluate_guards([{"kind": "ema_reclaim", "period": 8}], direction="long",
                              bar=mk(at(10, 0), 101.0), closes=closes)
    assert ok, why
    ok, why = evaluate_guards([{"kind": "ema_reclaim", "period": 8}], direction="long",
                              bar=mk(at(10, 0), 99.0), closes=[100.0] * 8 + [99.0])
    assert not ok and "ema_reclaim" in why[0]

    ok, _ = evaluate_guards([{"kind": "holds_above", "price": 640, "bars": 3}],
                            direction="long", bar=mk(at(10, 0), 641.0),
                            closes=[641.0, 642.0, 641.5])
    assert ok
    ok, why = evaluate_guards([{"kind": "holds_above", "price": 640, "bars": 3}],
                              direction="long", bar=mk(at(10, 0), 641.0),
                              closes=[639.0, 642.0, 641.0])
    assert not ok

    class _Q:
        last = 645.0
    ok, _ = evaluate_guards([{"kind": "guard_symbol", "symbol": "SPY", "op": ">=", "price": 640}],
                            direction="long", bar=mk(at(10, 0), 100.0), closes=[100.0],
                            quote_of=lambda s: _Q())
    assert ok
    ok, why = evaluate_guards([{"kind": "guard_symbol", "symbol": "SPY", "op": ">=", "price": 640}],
                              direction="long", bar=mk(at(10, 0), 100.0), closes=[100.0],
                              quote_of=None)
    assert not ok and "unsupported" in why[0]       # replay degrade: watch-only

    ok, why = evaluate_guards([{"kind": "time_at", "et": "09:45"}], direction="long",
                              bar=mk(at(9, 40), 100.0), closes=[100.0])
    assert not ok
    ok, _ = evaluate_guards([{"kind": "time_at", "et": "09:45"}], direction="long",
                            bar=mk(at(9, 45), 100.0), closes=[100.0])
    assert ok
    ok, why = evaluate_guards([{"kind": "astrology"}], direction="long",
                              bar=mk(at(10, 0), 100.0), closes=[100.0])
    assert not ok and "unsupported guard" in why[0]


def test_guard_fired_plan_and_simulated_fill():
    # conditions with NO level => a guard-fired ("timed") plan that enters at
    # the close of the first bar where the guards open — live and replay agree
    from zargar.marketstructure.outcome import simulate_plan
    bars = bars_with_support()
    plan = build_tip_plan(symbol="NVDA", direction="long", reference_price=102.5,
                          bars=bars, as_of_ms=NOW_MS, tip_stop=99.0,
                          tip_targets=[106.0, 110.0],
                          guards=[{"kind": "time_at", "et": "09:45"}])
    [t] = plan.triggers
    assert t.kind == "timed" and t.entry_basis == "on_break"
    assert t.guards == [{"kind": "time_at", "et": "09:45"}]
    assert "guards" in t.to_dict()

    # simulate: bars 09:30..: fill lands on the first >= 09:45 bar's close
    import datetime as _dt
    from zoneinfo import ZoneInfo
    from zargar.domain import Bar
    et = ZoneInfo("America/New_York")
    day = _dt.datetime(2026, 8, 28, 9, 30, tzinfo=et)
    sim_bars = []
    for i in range(40):
        ts = int((day + _dt.timedelta(minutes=i)).timestamp() * 1000)
        c = 102.0 + i * 0.2
        sim_bars.append(Bar(symbol="NVDA", tf="1m", ts=ts, open=c, high=c + 0.3,
                            low=c - 0.3, close=c, volume=100))
    out = simulate_plan(sim_bars, 0, t.to_dict(), horizon=39)
    assert out["filled"] and out["fillIndex"] == 15      # the 09:45 bar
    assert out["entry"] == sim_bars[15].close            # entered at that close

    # a guard that never opens => not filled, honestly labelled
    plan2 = build_tip_plan(symbol="NVDA", direction="long", reference_price=102.5,
                           bars=bars, as_of_ms=NOW_MS, tip_stop=99.0,
                           tip_targets=[106.0],
                           guards=[{"kind": "guard_symbol", "symbol": "SPY",
                                    "op": ">=", "price": 640}])
    out2 = simulate_plan(sim_bars, 0, plan2.triggers[0].to_dict(), horizon=39)
    assert not out2["filled"] and "never opened" in out2["note"]
