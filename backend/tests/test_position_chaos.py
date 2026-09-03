"""Phase 2b chaos suite — the acceptance gate for the durable position manager
(plan §2.5 + the techniques research A9). The manager ships with this or not
at all.

Share scenarios run through the REAL OrderManager → RiskGate → sim executor.
Option-leg scenarios use a recording fake order layer: the order plumbing for
options is already exercised end-to-end by the arming suite; what the chaos
suite must prove is the MANAGER's behaviour — write-ahead, restore, policy
decisions, watchdog, reconciliation classification, halts and parity."""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from zargar.domain import Bar
from zargar.execution.policies import PolicyState
from zargar.execution.positions import PositionManager
from zargar.execution.simulate import simulate_position
from zargar.marketstructure.sessions import ET, session_bounds

pytestmark = pytest.mark.usefixtures("fresh_db")


def rth_bar(day: str, minute: int, px: float, symbol: str = "AAPL", spread: float = 0.2) -> Bar:
    open_ms, _ = session_bounds(day)
    ts = open_ms + minute * 60_000
    return Bar(symbol=symbol, tf="1m", ts=ts, open=px, high=px + spread, low=px - spread, close=px, volume=5000)


class FakeOrders:
    """Recording order layer for option-leg scenarios. `script` maps call index ->
    status override (default FILLED at the limit/close)."""

    def __init__(self):
        self.placed = []
        self.cancelled = []
        self.script: dict[int, dict] = {}
        self.n = 0

    async def place(self, intent):
        i = self.n
        self.n += 1
        self.placed.append(intent)
        over = self.script.get(i, {})
        if over.get("raise"):
            raise ConnectionError("venue disconnected")
        status = over.get("status", "FILLED")
        px = over.get("price", intent.limit_price or intent.stop_price or 1.0)
        out = {"id": f"o{i}", "status": status, "symbol": intent.symbol,
               "filledQty": intent.qty if status in ("FILLED", "PARTIALLY_FILLED") else 0.0,
               "avgFillPrice": px if status in ("FILLED", "PARTIALLY_FILLED") else None,
               "rejectReason": over.get("reason")}
        return out

    async def cancel(self, order_id):
        self.cancelled.append(order_id)
        return {"id": order_id, "status": "CANCELLED"}


async def make_manager(engine, *, fake_orders: bool):
    pm = PositionManager(engine)
    if fake_orders:
        fo = FakeOrders()
        engine.orders = fo
        return pm, fo
    return pm, None


def spread_spec(pf, *, qty: int = 2) -> dict:
    """A defined-risk put credit spread on AAPL, adopted (fills known)."""
    return {
        "portfolioId": pf, "symbol": "AAPL", "direction": "long", "techniqueId": "premium",
        "tags": ["source:test"], "entry": 100.0, "risk": 1.0, "entryMark": -1.00,
        "overnight": "app_managed", "overnightAck": True, "guardAccepted": True,
        "policy": {"timeframe": "5m", "stop": {"kind": "none", "guard": "defined-risk spread; sized 1%"},
                   "profit_target_pct_of_credit": 60, "dte_close": 7, "time_stop_sessions": 20},
        "legs": [
            {"symbol": "AAPL261016P00095000", "secType": "OPT", "qty": -qty, "avgFill": 2.00, "multiplier": 100},
            {"symbol": "AAPL261016P00090000", "secType": "OPT", "qty": qty, "avgFill": 1.00, "multiplier": 100},
        ],
    }


# ------------------------------------------------------------------ validation gates
async def test_open_refuses_unsafe_specs(engine):
    pm, _ = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    base = spread_spec(pf)
    bad = {**base, "overnightAck": False}
    with pytest.raises(ValueError) as e:
        await pm.adopt(bad)
    assert "acknowledg" in str(e.value)
    bad = {**base, "policy": {**base["policy"], "stop": {"kind": "none"}}}
    with pytest.raises(ValueError) as e:
        await pm.adopt(bad)
    assert "guard" in str(e.value)
    bad = {**base, "overnight": "venue_stop", "overnightAck": False}
    with pytest.raises(ValueError) as e:
        await pm.adopt(bad)
    assert "venue" in str(e.value)


# ------------------------------------------------------------------ restart mid-position
async def test_restart_restores_position_and_venue_stop(engine):
    pm, _ = await make_manager(engine, fake_orders=False)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    sym = engine.config.sim_symbols[0] if getattr(engine.config, "sim_symbols", None) else "AAPL"
    d = await pm.adopt({
        "portfolioId": pf, "symbol": sym, "direction": "long", "techniqueId": "tip",
        "entry": 100.0, "risk": 1.0, "overnight": "venue_stop",
        "policy": {"timeframe": "5m", "stop": {"kind": "fixed", "price": 99.0},
                   "ladder": {"targets": [102.0], "fractions": [1.0]}},
        "legs": [{"symbol": sym, "secType": "STK", "qty": 50, "avgFill": 100.0}],
    })
    pid = d["id"]
    p = pm.get(pid)
    assert p is not None and p.venue_stop_order_id, "a share position held overnight must carry a venue GTC stop"
    stop_id = p.venue_stop_order_id
    await pm.stop()
    # ---- the process dies; a new manager restores from the DB ----
    pm2 = PositionManager(engine)
    n = await pm2.restore()
    assert n == 1
    p2 = pm2.get(pid)
    assert p2 is not None and p2.status == "open"
    assert p2.venue_stop_order_id == stop_id            # the resting stop survived the restart
    assert p2.state.stop == 99.0 and p2.sessions_seen   # policy state and the session ledger too
    await pm2.stop()


async def test_restart_mid_open_flags_attention_and_halts_entries(engine):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    p_dict = await pm.adopt(spread_spec(pf))
    p = pm.get(p_dict["id"])
    p.status = "opening"                                # simulate a crash mid-open
    await pm._persist(p)
    pm2 = PositionManager(engine)
    engine.orders = fo
    await pm2.restore()
    p2 = pm2.get(p.id)
    assert p2.status == "attention" and p2.halt_entries
    with pytest.raises(ValueError) as e:
        await pm2.open({**spread_spec(pf), "legs": [{"symbol": "AAPL", "secType": "STK", "qty": 1, "side": "BUY"}],
                        "overnight": "venue_stop", "overnightAck": False,
                        "policy": {"stop": {"kind": "fixed", "price": 1.0}}})
    assert "halted" in str(e.value)


# ------------------------------------------------------------------ policy decisions on bars
async def test_credit_target_closes_both_legs_together(engine):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    d = await pm.adopt(spread_spec(pf))
    p = pm.get(d["id"])

    class Q:
        def __init__(self, bid, ask):
            self.bid, self.ask, self.last, self.ts = bid, ask, (bid + ask) / 2, pm.now_ms()
    marks = {"AAPL261016P00095000": Q(0.55, 0.65), "AAPL261016P00090000": Q(0.30, 0.34)}
    engine.quotes.get = lambda s: marks.get(s)          # net buy-back = 0.65 - 0.30 = 0.35 -> 65% captured
    await pm.on_minute_bar(p, rth_bar("2026-08-27", 34, 101.0))   # closes the 09:30-09:35 5m bar
    assert any(x["kind"] == "credit_target" for x in p.exits), p.events[-3:]
    legs_ordered = [i.symbol for i in fo.placed]
    assert "AAPL261016P00095000" in legs_ordered and "AAPL261016P00090000" in legs_ordered
    buyback = next(i for i in fo.placed if i.symbol == "AAPL261016P00095000")
    assert buyback.side == "BUY" and buyback.reduce_only            # short leg buys back reduce-only


async def test_multi_leg_partial_close_stays_proportional(engine):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    d = await pm.adopt(spread_spec(pf, qty=2))
    p = pm.get(d["id"])
    engine.quotes.get = lambda s: None
    await pm.close(p.id, fraction=0.5, reason="test partial")
    qtys = {i.symbol: i.qty for i in fo.placed}
    assert qtys.get("AAPL261016P00095000") == 1 and qtys.get("AAPL261016P00090000") == 1
    # fills arrive -> legs reduce, position stays open
    for i, intent in enumerate(fo.placed):
        await pm.on_order_update({"id": f"o{i}", "status": "FILLED", "symbol": intent.symbol,
                                  "filledQty": intent.qty, "avgFillPrice": 1.0})
    assert p.status != "closed" and all(abs(l.qty) == 1 for l in p.open_legs)


async def test_expiry_friday_dte_close_fires(engine):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    soon = (dt.datetime.now(ET).date() + dt.timedelta(days=1)).strftime("%y%m%d")
    spec = spread_spec(pf)
    spec["legs"] = [{"symbol": f"AAPL{soon}C00100000", "secType": "OPT", "qty": 1, "avgFill": 2.0,
                     "multiplier": 100}]
    spec["entryMark"] = 2.0
    d = await pm.adopt(spec)
    p = pm.get(d["id"])
    engine.quotes.get = lambda s: None
    await pm.on_minute_bar(p, rth_bar("2026-08-27", 34, 105.0))     # deep ITM, 1 DTE
    assert any(x["kind"] == "dte" for x in p.exits), "an ITM contract must never reach auto-exercise"


async def test_weekend_and_extended_bars_make_no_decisions(engine):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    d = await pm.adopt(spread_spec(pf))
    p = pm.get(d["id"])
    engine.quotes.get = lambda s: None
    open_ms, _ = session_bounds("2026-08-27")
    pre = Bar(symbol="AAPL", tf="1m", ts=open_ms - 3600_000, open=90, high=90, low=90, close=90, volume=1)
    sat = Bar(symbol="AAPL", tf="1m", ts=open_ms + 3 * 86400_000, open=90, high=90, low=90, close=90, volume=1)
    n_exits = len(p.exits)
    await pm.on_minute_bar(p, pre)
    await pm.on_minute_bar(p, sat)                       # Sunday by ET -> extended
    assert len(p.exits) == n_exits and p.sessions_held() == 0


async def test_time_stop_counts_trading_sessions_across_days(engine):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    spec = spread_spec(pf)
    spec["policy"] = {"timeframe": "5m", "stop": {"kind": "none", "guard": "defined risk"},
                      "time_stop_sessions": 2}
    d = await pm.adopt(spec)
    p = pm.get(d["id"])
    engine.quotes.get = lambda s: None
    for day in ("2026-08-24", "2026-08-25", "2026-08-26"):   # Mon..Wed
        await pm.on_minute_bar(p, rth_bar(day, 34, 100.5))
    assert any(x["kind"] == "time" for x in p.exits), (p.sessions_seen, p.exits)


async def test_restore_and_adopt_resubscribe_the_underlying(engine, monkeypatch):
    """2026-09-02: after a mid-session restart, RKLB's managed position was
    restored but its UNDERLYING went unwatched (last bar 10:59) — the stop
    was blind. Both adopt() and restore() must ensure the underlying + legs."""
    ensured: list[str] = []

    async def fake_ensure(sym):
        ensured.append(sym.upper())
    monkeypatch.setattr(engine, "ensure_symbol", fake_ensure)
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    await pm.adopt(spread_spec(pf, qty=1))
    assert "AAPL" in ensured and any(s.startswith("AAPL2610") for s in ensured)
    ensured.clear()
    pm2 = PositionManager(engine)
    assert await pm2.restore() == 1
    assert "AAPL" in ensured and any(s.startswith("AAPL2610") for s in ensured)


async def test_redelivered_bar_and_slow_fill_never_double_exit(engine):
    """2026-08-31 live finding: the ~5s exchange-corrected 1m bar re-closed the
    5m window while the time-stop's exit order was still unfilled — a second
    full-size SELL flipped +4 calls into a naked -4 short. Same-minute
    re-decides are dropped, and in-flight exits suppress overlapping qty."""
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    spec = spread_spec(pf, qty=4)
    spec["policy"] = {"timeframe": "5m", "stop": {"kind": "none", "guard": "defined risk"},
                      "time_stop_sessions": 1}
    d = await pm.adopt(spec)
    p = pm.get(d["id"])
    engine.quotes.get = lambda s: None
    fo.script = {i: {"status": "SUBMITTED"} for i in range(20)}   # venue is slow: nothing fills
    for day in ("2026-08-24", "2026-08-25"):
        await pm.on_minute_bar(p, rth_bar(day, 34, 100.5))
    first = len(fo.placed)
    assert first >= 1 and any(x["kind"] == "time" for x in p.exits)
    # the exchange-corrected duplicate of the same closing minute arrives seconds later
    await pm.on_minute_bar(p, rth_bar("2026-08-25", 34, 100.6))
    assert len(fo.placed) == first, "a re-delivered minute must not re-run the policy"
    # …and even a direct racing close submits nothing while those exits are in flight
    await pm.close(p.id, fraction=1.0, reason="racing path", kind="time")
    assert len(fo.placed) == first, "in-flight exits suppress overlapping exit qty"
    assert any(e["event"] == "exit_skip" for e in p.events)
    # a forced stop still supersedes: the resting exits are cancelled, not stacked
    await pm.close(p.id, fraction=1.0, reason="crash brake", kind="stop", force_market=True)
    assert fo.cancelled, "force_market cancels the resting exits first"
    assert len(fo.placed) > first, "the stop itself still goes out"


# ------------------------------------------------------------------ watchdog + stale quotes
async def test_failed_exit_watchdog_retries_then_alerts(engine):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    d = await pm.adopt(spread_spec(pf, qty=1))
    p = pm.get(d["id"])
    engine.quotes.get = lambda s: None
    fo.script = {i: {"status": "REJECTED", "reason": "venue says no"} for i in range(20)}
    await pm.close(p.id, fraction=1.0, reason="test")
    assert p.exits[-1]["status"] == "REJECTED"
    t = [pm._now()]
    pm._now = lambda: t[0]
    retries = 0
    for _ in range(8):
        t[0] += 31.0
        before = fo.n
        await pm._watch_once()
        retries += 1 if fo.n > before else 0
    assert retries == 5, "the watchdog retries exactly 5 times, then hands it to a person"
    assert any("needs a person" in e.get("text", "") for e in p.events if e["event"] == "alert")


async def test_stale_monday_quote_makes_no_crash_brake_decision(engine):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    spec = spread_spec(pf, qty=1)
    spec["policy"] = {"timeframe": "5m", "stop": {"kind": "fixed", "price": 99.0}}
    d = await pm.adopt(spec)
    p = pm.get(d["id"])

    class StaleQ:
        bid = ask = 0.0
        last = 90.0                                      # WAY through the stop…
        ts = 0                                           # …but three days old
    engine.quotes.get = lambda s: StaleQ()
    n = len(fo.placed)
    for _ in range(4):
        await pm._watch_once()
    assert len(fo.placed) == n, "a stale quote must never fire the crash brake"


async def test_premium_watch_takes_lotto_profit_on_the_quote_loop(engine):
    """2026-09-02 GOOGL 0DTE 340C: the contract went +230% and back inside one
    15m bar while the analyst's UNDERLYING ladder (341.5) never printed. A
    `premium_watch` policy judges the premium ladder / stop every quote tick:
    +100% -> sell half, then the rest floors at the entry premium; a second
    tick at the same level does not double-sell while the exit is in flight."""
    from zargar.domain import Quote, now_ms
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    occ = "GOOGL260902C00340000"
    d = await pm.adopt({
        "portfolioId": pf, "symbol": "GOOGL", "direction": "long", "techniqueId": "tip",
        "entry": 338.7, "risk": 16.9, "entryMark": 0.13,
        "overnight": "app_managed", "overnightAck": True, "guardAccepted": True,
        "policy": {"timeframe": "15m", "stop": {"kind": "none", "guard": "premium stop"},
                   "ladder": {"targets": [341.5], "fractions": [1.0]},
                   "premium_stop_pct": 50, "premium_watch": True,
                   "premium_ladder": {"gains_pct": [100, 200], "fractions": [0.5, 0.5]}},
        "legs": [{"symbol": occ, "secType": "OPT", "qty": 20, "avgFill": 0.13, "multiplier": 100}],
    })
    p = pm.get(d["id"])
    quotes = {"GOOGL": Quote(symbol="GOOGL", bid=338.0, ask=338.1, last=338.05, ts=now_ms()),
              occ: Quote(symbol=occ, bid=0.2, ask=0.22, last=0.21, ts=now_ms())}
    engine.quotes.get = lambda s: quotes.get(s)
    await pm._watch_once()
    assert not fo.placed, "+60% is under the first rung"
    quotes[occ] = Quote(symbol=occ, bid=0.27, ask=0.29, last=0.28, ts=now_ms())   # +108%
    await pm._watch_once()
    assert len(fo.placed) == 1 and fo.placed[0].qty == 10 and fo.placed[0].side == "SELL"
    assert p.state.premium_trims_done == 1 and p.state.premium_floor == 0.13
    # exit is filled by the fake layer synchronously; the same level again = no second rung
    await pm._watch_once()
    assert len(fo.placed) == 1
    # the remainder is floored at entry: a give-back to 0.13 closes it, not -50%
    quotes[occ] = Quote(symbol=occ, bid=0.12, ask=0.14, last=0.13, ts=now_ms())
    await pm._watch_once()
    assert len(fo.placed) == 2 and fo.placed[1].qty == 10
    assert any("floor" in str(e) for e in p.events)


async def test_monetize_take_and_ratchet_floor_on_the_quote_loop(engine):
    """2026-09-04 (research decision): swing options run the monetize campaign —
    at +100% sell half (the debit is recouped), ratchet floors under the rest,
    judged every quote tick. The RKLB shape (+X% and all the way back) banks the
    gain instead of round-tripping."""
    from zargar.domain import Quote, now_ms
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    occ = "RKLB261016C00070000"
    d = await pm.adopt({
        "portfolioId": pf, "symbol": "RKLB", "direction": "long", "techniqueId": "tip",
        "entry": 63.15, "risk": 3.35, "entryMark": 3.55,
        "overnight": "app_managed", "overnightAck": True, "guardAccepted": True,
        "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": 59.8},
                   "ladder": {"targets": [67.5, 71.0, 75.0], "fractions": [0.4, 0.35, 0.25]},
                   "premium_stop_pct": 55, "premium_watch": True,
                   "monetize": {"take_at_pct": 100, "take_fraction": 0.5,
                                "floors": [[50, 15], [100, 50], [200, 120]]}},
        "legs": [{"symbol": occ, "secType": "OPT", "qty": 13, "avgFill": 3.55, "multiplier": 100}],
    })
    p = pm.get(d["id"])
    quotes = {"RKLB": Quote(symbol="RKLB", bid=64.0, ask=64.1, last=64.05, ts=now_ms()),
              occ: Quote(symbol=occ, bid=4.2, ask=4.4, last=4.3, ts=now_ms())}
    engine.quotes.get = lambda s: quotes.get(s)
    await pm._watch_once()                                     # +18%: nothing yet
    assert not fo.placed
    quotes[occ] = Quote(symbol=occ, bid=7.3, ask=7.6, last=7.45, ts=now_ms())   # +105%
    await pm._watch_once()
    assert len(fo.placed) == 1 and fo.placed[0].side == "SELL" and fo.placed[0].qty == 6
    assert p.state.premium_take_done and p.state.premium_floor == 3.55
    assert p.state.premium_floor_gain == 50.0                  # the +100 rung locked +50
    quotes[occ] = Quote(symbol=occ, bid=4.9, ask=5.2, last=5.0, ts=now_ms())    # +38% < floor
    await pm._watch_once()
    assert len(fo.placed) == 2 and fo.placed[1].qty == 7       # the rest banked at the floor
    assert any("ratchet floor" in str(e) for e in p.events)


async def test_rollup_banks_a_credit_and_keeps_convexity(engine):
    """2026-09-04: a deep-ITM winner (delta 0.82, mostly intrinsic) rolls to the
    ~0.35-delta strike when the credit beats the original debit — cash banked >
    cost, upside retained, premium campaign restarts on the new contract. A
    failed replacement buy leaves us FLAT AND PAID, never in limbo."""
    from zargar.domain import Quote, now_ms
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    cur, new = "NVDA261016C00200000", "NVDA261016C00250000"

    class StubOpts:
        def __init__(self):
            self.rows = [
                {"symbol": new, "expiry": "2026-10-16", "option_type": "call", "strike": 250.0,
                 "greeks": {"delta": 0.36, "mid_iv": 0.5}},
                {"symbol": "NVDA261016C00230000", "expiry": "2026-10-16", "option_type": "call",
                 "strike": 230.0, "greeks": {"delta": 0.52, "mid_iv": 0.5}},
            ]
            self.snaps = {cur: {"greeks": {"delta": 0.82, "mid_iv": 0.55}}}
        def snapshot_cached(self, sym):
            return self.snaps.get(sym)
        def provider(self):
            outer = self
            class P:
                async def all_rows(self, underlying):
                    return outer.rows
            return P()
        async def track(self, sym):
            return None
        async def stop(self):
            return None
    engine.options = StubOpts()
    d = await pm.adopt({
        "portfolioId": pf, "symbol": "NVDA", "direction": "long", "techniqueId": "tip",
        "entry": 195.0, "risk": 8.0, "entryMark": 4.00,
        "overnight": "app_managed", "overnightAck": True, "guardAccepted": True,
        "policy": {"timeframe": "15m", "stop": {"kind": "none", "guard": "premium campaign"},
                   "premium_stop_pct": 55, "premium_watch": True,
                   "monetize": {"take_at_pct": 100, "take_fraction": 0.5},
                   "rollup": {"enabled": True, "delta": 0.75, "target_delta": 0.35,
                              "max": 2, "max_spread_pct": 10.0}},
        "legs": [{"symbol": cur, "secType": "OPT", "qty": 4, "avgFill": 4.00, "multiplier": 100}],
    })
    p = pm.get(d["id"])
    quotes = {"NVDA": Quote(symbol="NVDA", bid=254.0, ask=254.2, last=254.1, ts=now_ms()),
              cur: Quote(symbol=cur, bid=55.0, ask=55.8, last=55.4, ts=now_ms()),
              new: Quote(symbol=new, bid=11.8, ask=12.2, last=12.0, ts=now_ms())}
    engine.quotes.get = lambda s: quotes.get(s)
    assert await pm._maybe_rollup(p) is True
    # SELL the old at its bid, BUY the new at its ask — through the order layer
    assert [(i.symbol, i.side) for i in fo.placed] == [(cur, "SELL"), (new, "BUY")]
    assert p.status == "open" and p.open_legs[0].symbol == new and p.open_legs[0].qty == 4
    assert p.entry_mark == 12.2 and p.state.rolls_done == 1 and not p.state.premium_take_done
    assert p.realized_pnl > 4.00 * 4 * 100          # banked more than the trade ever cost
    # a second roll with a too-small credit is refused (candidate ask too dear)
    quotes[new] = Quote(symbol=new, bid=12.5, ask=13.0, last=12.7, ts=now_ms())
    engine.options.snaps[new] = {"greeks": {"delta": 0.80, "mid_iv": 0.5}}
    engine.options.rows = [{"symbol": "NVDA261016C00300000", "expiry": "2026-10-16",
                            "option_type": "call", "strike": 300.0,
                            "greeks": {"delta": 0.35, "mid_iv": 0.5}}]
    quotes["NVDA261016C00300000"] = Quote(symbol="NVDA261016C00300000", bid=2.0, ask=2.2,
                                          last=2.1, ts=now_ms())
    # credit 12.5 - 2.2 = 10.3 < the NEW debit 12.2 -> refused
    assert await pm._maybe_rollup(p) is False


async def test_rollup_failed_buy_leaves_us_flat_and_paid(engine):
    from zargar.domain import Quote, now_ms
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    cur, new = "AMD261016C00150000", "AMD261016C00190000"

    class StubOpts:
        def snapshot_cached(self, sym):
            return {"greeks": {"delta": 0.85, "mid_iv": 0.5}} if sym == cur else None
        def provider(self):
            class P:
                async def all_rows(self, underlying):
                    return [{"symbol": new, "expiry": "2026-10-16", "option_type": "call",
                             "strike": 190.0, "greeks": {"delta": 0.34, "mid_iv": 0.5}}]
            return P()
        async def track(self, sym):
            return None
        async def stop(self):
            return None
    engine.options = StubOpts()
    d = await pm.adopt({
        "portfolioId": pf, "symbol": "AMD", "direction": "long", "techniqueId": "tip",
        "entry": 148.0, "risk": 6.0, "entryMark": 3.00,
        "overnight": "app_managed", "overnightAck": True, "guardAccepted": True,
        "policy": {"timeframe": "15m", "stop": {"kind": "none", "guard": "premium campaign"},
                   "premium_watch": True,
                   "rollup": {"enabled": True, "delta": 0.75, "target_delta": 0.35, "max": 2}},
        "legs": [{"symbol": cur, "secType": "OPT", "qty": 2, "avgFill": 3.00, "multiplier": 100}],
    })
    p = pm.get(d["id"])
    quotes = {"AMD": Quote(symbol="AMD", bid=189.0, ask=189.2, last=189.1, ts=now_ms()),
              cur: Quote(symbol=cur, bid=40.0, ask=40.6, last=40.3, ts=now_ms()),
              new: Quote(symbol=new, bid=8.0, ask=8.3, last=8.1, ts=now_ms())}
    engine.quotes.get = lambda s: quotes.get(s)
    fo.script[1] = {"status": "REJECTED_RISK", "reason": "test: refuse the buy"}
    assert await pm._maybe_rollup(p) is True
    assert p.status == "closed" and not p.open_legs
    assert p.realized_pnl > 3.00 * 2 * 100          # flat AND paid


async def test_halt_does_not_trap_the_exit(engine):
    """Kill switch on -> a reduce-only close still routes (the REAL gate)."""
    pm, _ = await make_manager(engine, fake_orders=False)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    sym = engine.config.sim_symbols[0] if getattr(engine.config, "sim_symbols", None) else "AAPL"
    d = await pm.adopt({
        "portfolioId": pf, "symbol": sym, "direction": "long", "techniqueId": "tip",
        "entry": 100.0, "risk": 1.0, "overnight": "day_only",
        "policy": {"timeframe": "5m", "stop": {"kind": "fixed", "price": 99.0}},
        "legs": [{"symbol": sym, "secType": "STK", "qty": 10, "avgFill": 100.0}],
    })
    engine.halt.engage("chaos test")
    try:
        await pm.close(d["id"], fraction=1.0, reason="halted exit test")
        p = pm.get(d["id"])
        rec = p.exits[-1]
        assert rec["status"] not in ("REJECTED_RISK",), rec
    finally:
        engine.halt.release()


# ------------------------------------------------------------------ reconciliation
async def test_reconcile_classifies_assignment_and_expiry(engine, monkeypatch):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    yday = (dt.datetime.now(ET).date() - dt.timedelta(days=1)).strftime("%y%m%d")
    spec = spread_spec(pf)
    spec["legs"] = [
        {"symbol": f"AAPL{yday}P00105000", "secType": "OPT", "qty": -1, "avgFill": 2.0, "multiplier": 100},
        {"symbol": f"AAPL{yday}P00090000", "secType": "OPT", "qty": 1, "avgFill": 0.5, "multiplier": 100},
    ]
    d = await pm.adopt(spec)
    p = pm.get(d["id"])

    class Q:
        bid = ask = 0.0
        last = 100.0                                     # 90P OTM (worthless), 105P ITM (assigned)
        def __init__(self):
            self.ts = pm.now_ms()
    engine.quotes.get = lambda s: Q()
    monkeypatch.setattr(engine.positions, "positions_list",
                        lambda pid=None: [{"symbol": "AAPL", "qty": 100.0}])
    report = await pm.reconcile()
    whats = " | ".join(x["what"] for x in report["explained"])
    assert "assigned" in whats and "expired worthless" in whats
    assert report["unexplained"] == []
    stk = [l for l in p.legs if l.sec_type == "STK"]
    assert stk and stk[0].qty == 100 and stk[0].origin == "assignment" and stk[0].avg_fill == 105.0


async def test_reconcile_unexplained_drift_halts_the_symbol(engine, monkeypatch):
    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    d = await pm.adopt(spread_spec(pf))
    p = pm.get(d["id"])
    engine.quotes.get = lambda s: None
    monkeypatch.setattr(engine.positions, "positions_list", lambda pid=None: [])   # broker shows nothing
    report = await pm.reconcile()
    assert report["unexplained"] and p.status == "attention" and pm.entries_halted("AAPL")
    pm.clear_entry_halt("AAPL")
    assert not pm.entries_halted("AAPL")


# ------------------------------------------------------------------ parity: live == simulate
async def test_live_and_simulated_policy_decisions_match(engine):
    policy = {"timeframe": "5m", "stop": {"kind": "fixed", "price": 99.0},
              "ladder": {"targets": [101.0, 102.0], "fractions": [0.5, 0.5]},
              "breakeven_after_r": 1.0, "trailing": {"mode": "pct", "value": 1.0, "after_r": 1.5}}
    path = [100.2, 100.6, 101.2, 101.6, 102.2, 101.8, 101.1, 100.4, 99.9, 99.4]
    bars5 = [Bar(symbol="T", tf="5m", ts=session_bounds("2026-08-27")[0] + (30 + 5 * i) * 60_000,
                 open=px, high=px + 0.3, low=px - 0.3, close=px, volume=1000) for i, px in enumerate(path)]
    sim = simulate_position(policy, bars5, direction="long", entry=100.0, risk=1.0)

    pm, fo = await make_manager(engine, fake_orders=True)
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    d = await pm.adopt({
        "portfolioId": pf, "symbol": "T", "direction": "long", "techniqueId": "tip",
        "entry": 100.0, "risk": 1.0, "overnight": "day_only", "policy": policy,
        "legs": [{"symbol": "T", "secType": "STK", "qty": 100, "avgFill": 100.0}],
    })
    p = pm.get(d["id"])
    engine.quotes.get = lambda s: None
    engine.bars.bars = lambda *a, **k: []               # force the raw-bar path
    live_kinds = []
    for b in bars5:
        one_m = Bar(symbol="T", tf="1m", ts=b.ts + 4 * 60_000, open=b.open, high=b.high, low=b.low,
                    close=b.close, volume=b.volume)
        n0 = len(p.exits)
        await pm.on_minute_bar(p, one_m)
        live_kinds += [x["kind"] for x in p.exits[n0:]]
        # apply the fills so the next bar sees the reduced position
        for i, intent in enumerate(fo.placed[len(fo.cancelled) + 0:]):
            pass
        for i, intent in enumerate(fo.placed):
            oid = f"o{i}"
            if any(x.get("orderId") == oid and not x.get("filledQty") for x in p.exits):
                await pm.on_order_update({"id": oid, "status": "FILLED", "symbol": intent.symbol,
                                          "filledQty": intent.qty, "avgFillPrice": b.close})
    sim_kinds = [x["kind"] for x in sim["exits"]]
    assert live_kinds == sim_kinds, (live_kinds, sim_kinds)
    assert p.state.trims_done == sim["state"]["trimsDone"]
    assert (p.state.stop is None) == (sim["finalStop"] is None)
    if p.state.stop is not None:
        assert abs(p.state.stop - sim["finalStop"]) < 1e-6
