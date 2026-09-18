"""2026-09-17 EOD review item 1: a breakout's destination must be distinct from, and beyond, the level it broke, and ahead
of the current actionable price — the same rule for the EMA entry and the level entry of one setup. No ATR threshold.

Before/after on the day's own numbers (QQQ pm_break_up@12:15, anchor = target = 716.76, EMA entry line 716.7557, close 716.80):
before this change the EMA entry traded toward 716.76 while the level entry (716.76 == entry) was re-planned to 716.80;
after it both entry kinds are refused with the same reason.
"""
from __future__ import annotations

import datetime as dt
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zargar.marketstructure.aggregate import aggregate
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.scenario import destination_check
from zargar.techniques.team2.session import simulate_session

from .test_codex_team2_data_eod import bar, rig
from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars, zones_of


# ---------------------------------------------------------------- the pure rule
def test_destination_check_names_collisions_and_behind_without_a_distance_threshold():
    # the QQQ day: target IS the source level
    kind, why = destination_check(716.76, 716.76, 716.7557, 716.80, "long", 0.01)
    assert kind == "collision" and "source-target collision" in why and "716.76" in why
    # within one tick of the anchor is the same level
    assert destination_check(716.769, 716.76, 716.70, 716.72, "long")[0] == "collision"
    # behind the anchor in the trade's direction
    assert destination_check(716.50, 716.76, 716.40, 716.45, "long")[0] == "collision"
    assert destination_check(100.20, 100.0, 100.3, 100.25, "short")[0] == "collision"
    # distinct and beyond the anchor but not ahead of the current price: behind (F72), not a collision
    kind, why = destination_check(716.78, 716.76, 716.70, 716.80, "long")
    assert kind == "behind" and "current price 716.80" in why
    # distinct, beyond the anchor, ahead of the entry line and the current price: allowed — 0.02 of room is enough for the rule
    assert destination_check(716.78, 716.76, 716.70, 716.76, "long") == (None, None)
    assert destination_check(99.0, 100.0, 100.0043, 99.96, "short") == (None, None)
    # the allowed no-target shape passes; a non-number is invalid
    assert destination_check(None, 100.0, 99.0, 99.5, "long") == (None, None)
    assert destination_check("x", 100.0, 99.0, 99.5, "long")[0] == "invalid"


# ---------------------------------------------------------------- the runner: EMA and level entries of one setup resolve the same way
@pytest.mark.parametrize("entry_kind,entry_line", [("ema", 716.7557), ("level", 716.76)])
async def test_the_qqq_day_is_refused_for_both_entry_kinds_and_journaled_as_a_collision(monkeypatch, entry_kind, entry_line):
    import zargar.execution.planrunner as shared
    import zargar.techniques.team2.runner as module
    runner, ap = rig()
    now = int(dt.datetime(2026, 9, 14, 13, 10, tzinfo=ET).timestamp() * 1000)
    monkeypatch.setattr(module.time, "time", lambda: now / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: now)
    ap.bar_index = 10
    ap.plan.update({"pmh": 716.76, "pml": 704.192})
    sid = "pm_break_up@12:15"
    e = {"event": "fire", "ts": now, "setup": sid, "touch": 2, "spot": entry_line, "target": 716.76, "targetKind": "plan",
         "entryKind": entry_kind, "sizeMult": .5, "bucket": "small", "why": "retest of the broken PM high",
         "regime": {"stack": "bull", "atr": .3145, "ema13": 716.7557}}
    res = SimpleNamespace(setups=[{"id": sid, "kind": "pm_break_up", "direction": "long", "anchor": 716.76, "target": 716.76}])
    runner.pick_contract = AsyncMock(return_value={"symbol": "QQQ260917C00717000", "ask": .69})
    runner._enter = AsyncMock()
    await runner._fire_from_event(ap, e, bar(13, 9, 716.80), res, halted=False, journal=True)
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == 0 and f"{sid}#2" not in ap.trades
    skipped = [c.args[1] for c in runner.engine.journal.append.await_args_list if c.args[0] == "TechniquePlanTriggerSkipped"]
    assert skipped and skipped[-1]["event"] == "skip_target_collision" and "source-target collision" in skipped[-1]["why"]
    assert skipped[-1]["anchor"] == 716.76 and skipped[-1]["close"] == 716.80
    assert f"{sid}#2" in (ap.plan.get("executionRefused") or [])          # R1: the read's proxy never opens


async def test_a_distinct_destination_beyond_the_anchor_still_enters(monkeypatch):
    import zargar.execution.planrunner as shared
    import zargar.techniques.team2.runner as module
    runner, ap = rig()
    now = int(dt.datetime(2026, 9, 14, 13, 10, tzinfo=ET).timestamp() * 1000)
    monkeypatch.setattr(module.time, "time", lambda: now / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: now)
    ap.bar_index = 10
    sid = "pm_break_up@12:15"
    e = {"event": "fire", "ts": now, "setup": sid, "touch": 2, "spot": 716.7557, "target": 718.00, "targetKind": "plan",
         "entryKind": "ema", "sizeMult": .5, "bucket": "small", "why": "retest", "regime": {"stack": "bull", "atr": .3145}}
    res = SimpleNamespace(setups=[{"id": sid, "kind": "pm_break_up", "direction": "long", "anchor": 716.76, "target": 718.00}])
    runner.pick_contract = AsyncMock(return_value={"symbol": "QQQ260917C00717000", "ask": .69})
    runner._enter = AsyncMock()
    await runner._fire_from_event(ap, e, bar(13, 9, 716.80), res, halted=False, journal=True)
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == 1 and ap.trades[f"{sid}#2"].targets == [718.0]


def test_resolve_fire_target_judges_the_actionable_price_and_the_anchor():
    runner, ap = rig()
    setup = {"anchor": 716.76}
    # collision: refused with the collision wording, whatever the entry kind
    t, why = runner.resolve_fire_target({"target": 716.76}, setup, 716.7557, "long", actionable=716.80, anchor=716.76)
    assert t is None and "source-target collision" in why
    # distinct target but the current price already ran through it: behind
    t, why = runner.resolve_fire_target({"target": 716.78}, setup, 716.70, "long", actionable=716.80, anchor=716.76)
    assert t is None and "current price 716.80" in why and "collision" not in why
    # valid
    assert runner.resolve_fire_target({"target": 718.0}, setup, 716.70, "long", actionable=716.80, anchor=716.76) == (718.0, None)
    # the read's no-target shape (F81b) is still allowed
    assert runner.resolve_fire_target({"target": None, "targetKind": "none"}, {"target": 716.76, "anchor": 716.76}, 716.70, "long",
                                      actionable=716.80, anchor=716.76) == (None, None)


# ---------------------------------------------------------------- the read: a PM-break whose target is its own level never fires
def _collision_day():
    """Gap-up day built so the pre-open F81 re-derivation sets the above-target to the PM high, and the first 15m bar
    then closes above that PM high: the pm_break_up setup's destination is its own anchor."""
    prev = prev_day_bars()
    z = zones_of(prev)
    top = z["pdh"].top
    pmh = top + 3.0                                     # pre-market high, above the zone

    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:                              # pre-market: climb to the PM high at 08:30, ease back a little
            if m <= 8 * 60 + 30:
                return top + 0.5 + (pmh - top - 0.5) * ((m - 240) / (270))
            return pmh - 0.6
        x = m - 9 * 60 - 30
        if x < 15:                                       # first 15m bar pushes through the PM high and closes above it
            return pmh - 0.4 + 0.9 * (x / 14)
        if x < 40:                                       # pullback to the EMA13 above the PM high, then a rally
            return pmh + 0.5 - 0.35 * ((x - 15) / 25)
        if x < 120:
            return pmh + 0.15 + 3.0 * ((x - 40) / 80)
        return pmh + 3.0 + 0.05 * math.sin(i / 3)
    today = path_1m(DAY, (4, 0), (20, 0), f)
    return prev, today, z, pmh


@pytest.mark.parametrize("collision", [True, False])
def test_read_refuses_a_pm_break_whose_destination_is_its_own_level(collision):
    prev, today, z, pmh = _collision_day()
    rules = make_rules()
    plan = build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules)
    # the planned above-target lies below where the day opens, so F81 re-derives it to the PM high (the QQQ shape)…
    plan["targetsPlanned"]["above"] = z["pdh"].top + 0.2
    plan["targets"]["above"] = z["pdh"].top + 0.2
    if not collision:
        # …unless the planned target already sits beyond the PM high: nothing to re-derive, the destination is distinct
        plan["targetsPlanned"]["above"] = round(pmh + 2.5, 2)
        plan["targets"]["above"] = round(pmh + 2.5, 2)
    done = complete_plan(plan, today)
    assert done["dayType"] == "gap_up"
    pm_hi = done["pmh"]
    res = simulate_session(done, today, rules, sigma=0.20, warmup_1m=prev).to_dict()
    pm_setups = [s for s in res["setups"] if s["kind"] == "pm_break_up"]
    assert pm_setups, [s["kind"] for s in res["setups"]]
    setup = pm_setups[0]
    fires = [e for e in res["events"] if e["event"] == "fire" and e["setup"] == setup["id"]]
    notes = [e for e in res["events"] if e["event"] == "skip_target_collision" and e.get("setup") == setup["id"]]
    if collision:
        assert done["targets"]["above"] == pm_hi and setup["target"] == pm_hi == setup["anchor"]
        assert not fires and notes and "source-target collision" in notes[0]["why"]
        assert notes[0]["anchor"] == notes[0]["target"] == round(pm_hi, 4)
    else:
        assert setup["target"] > setup["anchor"] and not notes
        assert fires, "a distinct destination beyond the broken level still lets the pullback fire"


# ---------------------------------------------------------------- PR204 review: the actionable price is the FRESH quote, judged again at the order boundary
def _live(px, now):
    return SimpleNamespace(get=lambda _: SimpleNamespace(last=px, bid=px - .01, ask=px + .01, ts=now, source_ts=now, source="alpaca"))


@pytest.mark.parametrize("direction,live_spot,entries", [("long", 100.4, 1), ("long", 101.1, 0), ("short", 99.6, 1), ("short", 98.9, 0)])
async def test_the_fresh_quote_decides_the_room_at_the_fire_long_and_short(monkeypatch, direction, live_spot, entries):
    import zargar.execution.planrunner as shared
    import zargar.techniques.team2.runner as module
    runner, ap = rig()
    now = int(dt.datetime(2026, 9, 14, 13, 10, tzinfo=ET).timestamp() * 1000)
    monkeypatch.setattr(module.time, "time", lambda: now / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: now)
    ap.bar_index = 10
    runner.engine.quotes = _live(live_spot, now)
    up = direction == "long"
    sid = "pm_break_up@12:15" if up else "pm_break_down@12:15"
    e = {"event": "fire", "ts": now, "setup": sid, "touch": 1, "spot": 100.1 if up else 99.9, "target": 101.0 if up else 99.0,
         "targetKind": "plan", "entryKind": "ema", "sizeMult": .5, "bucket": "small", "why": "valid closed-bar signal",
         "regime": {"stack": "bull" if up else "bear", "atr": .3}}
    res = SimpleNamespace(setups=[{"id": sid, "kind": sid.split("@")[0], "direction": direction, "anchor": 100.0, "target": e["target"]}])
    runner.pick_contract = AsyncMock(return_value={"symbol": "TEST", "ask": .5})
    runner._enter = AsyncMock()
    await runner._fire_from_event(ap, e, bar(13, 9, 100.3 if up else 99.7), res, halted=False, journal=True)
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == entries
    if not entries:
        skipped = [c.args[1] for c in runner.engine.journal.append.await_args_list if c.args[0] == "TechniquePlanTriggerSkipped"][-1]
        assert skipped["event"] == "skip_target_behind" and skipped["actionableSource"] == "mid" and skipped["actionable"] == live_spot
        assert skipped["actionableTs"] == now and skipped["actionableAgeMs"] == 0


async def test_a_target_crossed_during_the_awaited_work_is_refused_at_the_order_boundary(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner, ap = rig()
    now = int(dt.datetime(2026, 9, 14, 13, 10, tzinfo=ET).timestamp() * 1000)
    monkeypatch.setattr(module.time, "time", lambda: now / 1000)
    runner.engine.quotes = _live(100.4, now)
    trade = __import__("zargar.execution.planrunner", fromlist=["Trade"]).Trade(
        trigger_id="pm_break_up@12:15#1", kind="pm_break_up", fired_ts=now, window="team2", entry=100.1, stop=99.8, targets=[101.0],
        setup_id="pm_break_up@12:15", instrument="options", multiplier=100.0, direction="long")
    ap.trades[trade.trigger_id] = trade
    # the time gate refuses first on this synthetic date; take it out of the way so the target gate is what is exercised
    monkeypatch.setattr(runner, "_entry_time_refusal", lambda ap_, stage: None)
    assert await runner.entry_gate(ap, trade, "order") is None and runner.entry_guard_predicate(ap, trade) is None
    # the quote pick / review / sizing took time and the price ran to the target: no entry, at the order stage, on a retry and at submit
    runner.engine.quotes = _live(101.05, now)
    for stage in ("order", "retry"):
        why = await runner.entry_gate(ap, trade, stage)
        assert why and f"order boundary ({stage})" in why and "current price 101.05" in why and "reached the target" in why and "(mid, 0s old)" in why
    assert "order boundary (submit)" in (runner.entry_guard_predicate(ap, trade) or "")
    assert trade.targets == [101.0]                                           # never rewritten to let the order through
    # a stale quote is not evidence: the time gate and the venue decide (no refusal from this gate)
    runner.engine.quotes = _live(101.05, now - 600_000)
    assert await runner.entry_gate(ap, trade, "order") is None
    # the read's no-target shape and the pre-order stage are untouched
    trade.targets = []
    runner.engine.quotes = _live(101.05, now)
    assert await runner.entry_gate(ap, trade, "order") is None and await runner.entry_gate(ap, trade, "pre_order") is None


# ---------------------------------------------------------------- PR204 round 2: the price's own time decides its freshness
def test_fresh_underlying_binds_the_age_to_the_field_it_uses(monkeypatch):
    import zargar.techniques.team2.runner as module
    from zargar.domain import Quote
    runner, ap = rig()
    now = int(dt.datetime(2026, 9, 14, 13, 10, tzinfo=ET).timestamp() * 1000)
    monkeypatch.setattr(module.time, "time", lambda: now / 1000)
    store = {}
    runner.engine.quotes = SimpleNamespace(get=lambda _: store.get("q"))
    # a fresh print: the last, aged by its own trade time — the receipt time is irrelevant
    store["q"] = Quote(symbol="SPY", bid=100.38, ask=100.42, last=100.4, ts=now - 900_000, last_ts=now - 2_000, quote_ts=now - 1_000)
    assert runner._fresh_underlying(ap) == (100.4, "last") and runner._actionable_evidence()["ageMs"] == 2_000
    # a ten-minute-old print re-emitted under a NEW bid/ask: the print is not fresh, the quote midpoint is
    store["q"] = Quote(symbol="SPY", bid=101.10, ask=101.12, last=100.4, ts=now, last_ts=now - 600_000, quote_ts=now)
    assert runner._fresh_underlying(ap) == (101.11, "mid") and runner._actionable_evidence()["source"] == "mid"
    # the options NBBO convention: `source_ts` is bid/ask evidence when `quote_ts` is not carried
    store["q"] = SimpleNamespace(last=100.4, bid=101.10, ask=101.12, ts=now, source_ts=now - 3_000)
    assert runner._fresh_underlying(ap) == (101.11, "mid")
    # old print AND old quote: unavailable, never the receipt time
    store["q"] = Quote(symbol="SPY", bid=101.10, ask=101.12, last=100.4, ts=now, last_ts=now - 600_000, quote_ts=now - 600_000)
    assert runner._fresh_underlying(ap) == (None, "stale price")
    # a crossed quote is not evidence for the midpoint
    store["q"] = Quote(symbol="SPY", bid=101.20, ask=101.12, last=100.4, ts=now, last_ts=now - 600_000, quote_ts=now)
    assert runner._fresh_underlying(ap)[0] is None
    # zero / missing times are no time at all
    store["q"] = Quote(symbol="SPY", bid=101.10, ask=101.12, last=100.4, ts=0)
    assert runner._fresh_underlying(ap) == (None, "no price time")
    store["q"] = SimpleNamespace(last=100.4, ts=now)
    assert runner._fresh_underlying(ap) == (None, "no price time")
    store["q"] = SimpleNamespace(last=0.0, bid=0.0, ask=0.0, ts=now)
    assert runner._fresh_underlying(ap) == (None, "no price")
    # a time from the future is not fresh either
    store["q"] = Quote(symbol="SPY", last=100.4, ts=now, last_ts=now + 60_000)
    assert runner._fresh_underlying(ap)[0] is None


def test_alpaca_bars_and_prints_stamp_the_time_of_the_price_they_set(monkeypatch):
    import zargar.brokers.alpaca as feed_module
    from zargar.brokers.alpaca import AlpacaQuoteFeed
    now = int(dt.datetime(2026, 9, 14, 13, 10, tzinfo=ET).timestamp() * 1000)
    monkeypatch.setattr(feed_module, "now_ms", lambda: now)
    emitted = []
    feed = AlpacaQuoteFeed(emitted.append, "", "", on_bars=lambda bars: None)
    iso = lambda t: dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).isoformat()
    # a completed bar sets last to its close, timed at the bar's close
    feed.handle({"T": "b", "S": "SPY", "t": iso(now - 120_000), "o": 100.0, "h": 100.5, "l": 99.9, "c": 100.3, "v": 1000})
    feed.handle({"T": "q", "S": "SPY", "bp": 100.28, "ap": 100.32, "bs": 1, "as": 1, "t": iso(now - 500)})
    q = emitted[-1]
    assert q.last == 100.3 and q.last_ts == now - 60_000 and q.quote_ts == now - 500 and q.ts == now
    # a later bid/ask message keeps the print's own time; only the quote time moves
    feed._st("SPY")["emit_ms"] = 0
    feed.handle({"T": "q", "S": "SPY", "bp": 101.10, "ap": 101.12, "bs": 1, "as": 1, "t": iso(now)})
    q2 = emitted[-1]
    assert q2.last == 100.3 and q2.last_ts == now - 60_000 and q2.quote_ts == now
    # an eligible print moves last and its time together
    feed._st("SPY")["emit_ms"] = 0
    feed.handle({"T": "t", "S": "SPY", "p": 101.11, "s": 100, "t": iso(now)})
    q3 = emitted[-1]
    assert q3.last == 101.11 and q3.last_ts == now


def test_alpaca_keeps_a_missing_venue_time_at_zero_while_bookkeeping_still_runs(monkeypatch):
    """PR #204 r3: a message without `t` yields last_ts / quote_ts = 0 (no price evidence), the receipt time serves only the
    session roll and the volume, and the helper reports the price unavailable; a malformed stamp is treated the same."""
    import zargar.brokers.alpaca as feed_module
    from zargar.brokers.alpaca import AlpacaQuoteFeed, venue_ms
    now = int(dt.datetime(2026, 9, 14, 13, 10, tzinfo=ET).timestamp() * 1000)
    monkeypatch.setattr(feed_module, "now_ms", lambda: now)
    assert venue_ms(None) == 0 and venue_ms("") == 0 and venue_ms("not-a-time") == 0
    assert venue_ms(dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).isoformat()) == now
    emitted = []
    feed = AlpacaQuoteFeed(emitted.append, "", "")
    feed.handle({"T": "t", "S": "SPY", "p": 101.1, "s": 100})                         # no venue time
    q = emitted[-1]
    assert q.last == 101.1 and q.last_ts == 0 and q.ts == now and q.volume >= 100         # bookkeeping ran, evidence absent
    feed._st("SPY")["emit_ms"] = 0
    feed.handle({"T": "q", "S": "SPY", "bp": 101.1, "ap": 101.12, "bs": 1, "as": 1})   # no venue time
    q2 = emitted[-1]
    assert q2.quote_ts == 0 and q2.last_ts == 0
    runner, ap = rig()
    monkeypatch.setattr(__import__("zargar.techniques.team2.runner", fromlist=["time"]).time, "time", lambda: now / 1000)
    runner.engine.quotes = SimpleNamespace(get=lambda _: q2)
    assert runner._fresh_underlying(ap) == (None, "no price time")
    # a malformed stamp is no stamp either
    feed._st("SPY")["emit_ms"] = 0
    feed.handle({"T": "t", "S": "SPY", "p": 101.2, "s": 100, "t": "garbage"})
    assert emitted[-1].last == 101.2 and emitted[-1].last_ts == 0

