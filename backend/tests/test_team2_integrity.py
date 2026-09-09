"""Read integrity + execution semantics (Codex review 2026-09-08, TRADING-RULES F49/F50/F51/F61/F62):
- an IV update can never rewrite a past signal (the read's sigma is locked per plan and stamped);
- acted-on read events are recognised by fingerprint, so a moved input can neither re-fire nor skip one;
- the day type is finalized on the real 09:30 open with the 09:25 estimate kept as a snapshot;
- the plan target sells on the first FRESH underlying print, once, reduce-only;
- a pullback is an episode (departure + return) and only a PRICED pullback spends the allowance."""
from __future__ import annotations

import math

import pytest

from zargar.domain import Quote
from zargar.execution.planrunner import Trade
from zargar.marketdata import persist_bars
from zargar.marketstructure import aggregate, filter_session
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.session import simulate_session

from .test_team2_runner import rig  # noqa: F401
from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars, trend_day, zones_of

PREV = prev_day_bars()
TOP = zones_of(PREV)["pdh"].top


def _run(price_fn, **rule_kw):
    rules = make_rules(**rule_kw)
    today = path_1m(DAY, (4, 0), (20, 0), price_fn)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules), today)
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV)


# ---------------------------------------------------------------- F62 / F61 (pure read)
def drift_day(i):
    """Break, one clean dip to the EMA13, then 40 minutes sitting ON the EMA (a drift, not pullbacks), then up."""
    m = 4 * 60 + i
    if m < 9 * 60 + 30:
        return 566 + 2.0 * (i / 330)
    x = m - 9 * 60 - 30
    if x < 15:
        return 568.5 + (TOP + 1.5 - 568.5) * (x / 14)
    if x < 30:
        return TOP + 1.5 - 1.2 * ((x - 15) / 15)          # the real pullback
    if x < 70:
        return TOP + 0.3 + 0.03 * math.sin(x)              # sits on the EMA band for 40 minutes
    if x < 150:
        return TOP + 0.3 + 4.0 * ((x - 70) / 80)
    return TOP + 4.3 - 2.0 * ((x - 150) / 240)


def test_a_drift_on_the_ema_is_one_pullback_not_many():
    # floor above 1.5 x target: no strike can ever be picked, so nothing fires and nothing spends — the
    # pullback counters alone tell the story (the loss cap would otherwise end the day after two fires)
    res = _run(drift_day, entry_at="ema", allow_ema48_entries=False, pullback_body_mult=100, target_premium=0.10,
               premium_floor=0.20)
    s = [x for x in res.setups if x["kind"] == "scenario_1"][0]
    off = _run(drift_day, entry_at="ema", allow_ema48_entries=False, pullback_body_mult=100, target_premium=0.10,
               premium_floor=0.20, pullback_reset_atr=0)
    s_off = [x for x in off.setups if x["kind"] == "scenario_1"][0]
    assert s["pullbacks"] < s_off["pullbacks"]                                    # the reset collapses the drift
    assert s_off["pullbacks"] >= 3 * s["pullbacks"]                               # 4 episodes vs 16 bar-contacts on this day
    assert any(e["event"] == "same_pullback" for e in res.events)


def test_a_plumbing_refusal_does_not_spend_the_allowance():
    # a premium band no strike can satisfy (floor above 1.5 x target) -> every attempt is refused as skip_no_contract
    res = _run(drift_day, entry_at="ema", allow_ema48_entries=False, pullback_body_mult=100,
               target_premium=0.10, premium_floor=0.20)
    s = [x for x in res.setups if x["kind"] == "scenario_1"][0]
    assert any(e["event"] == "skip_no_contract" for e in res.events)
    assert s["opportunities"] >= 1 and s["touches"] == 0 and s["attempts"] == 0   # counted, not spent
    assert not [e for e in res.events if e["event"] == "late_touch"]             # nothing burned the D9 budget


def test_only_priced_pullbacks_spend_and_the_counters_nest():
    today, _ = trend_day(PREV)
    rules = make_rules()
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules), today)
    res = simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV)
    for s in res.setups:
        assert s["pullbacks"] >= s["opportunities"] >= s["touches"] >= s["attempts"] == s["entries"]
    t = res.trades[0]
    assert any(x.get("fillAssumption") == "target_touch_intrabar" for x in t["exits"]) or all(
        "target" not in x["reason"] for x in t["exits"])


# ---------------------------------------------------------------- F51 + fingerprints (runner)
async def _armed(eng):
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    return eng.team2_runner, eng.team2_runner.get(out["armed"][0]), filter_session(today, "rth")


async def _drive_until_fire(runner, ap, rth) -> int:
    """Feed bars until the runner's first `fired` event; return how many bars were fed."""
    for i, b in enumerate(rth):
        await runner.on_bar(ap.run_id, b)
        if any(e["event"] == "fired" for e in ap.events):
            return i + 1
    raise AssertionError("the trend day never fired")


async def test_iv_is_locked_per_session_and_a_later_iv_cannot_rewrite_or_duplicate_events(rig):
    eng, sim = rig
    runner, ap, rth = await _armed(eng)
    await eng.team2.preopen_complete()
    half = await _drive_until_fire(runner, ap, rth)
    snap = ap.plan.get("sigma")
    assert snap and snap["value"] > 0 and snap["source"] in ("chain_atm", "vix_proxy") and snap["lockedAt"]
    fired_before = [e for e in ap.events if e["event"] == "fired"]
    events_before = list((runner._last_sim[ap.run_id] or {}).get("events") or [])
    # the IV proxy moves a lot after the lock: the read must keep the locked value
    runner._sigma_cache[ap.symbol] = (snap["lockedAt"][:10], 0.95)
    assert await runner._session_sigma(ap) == pytest.approx(snap["value"])
    for b in rth[half:]:
        await runner.on_bar(ap.run_id, b)
    events_after = list((runner._last_sim[ap.run_id] or {}).get("events") or [])
    assert events_after[:len(events_before)] == events_before                    # history intact
    fired_after = [e for e in ap.events if e["event"] == "fired"]
    ids = [e.get("trigger") for e in fired_after]
    assert len(ids) == len(set(ids))                                             # no duplicate fires
    assert len(fired_before) == 1 and len(fired_after) >= 1
    assert not [e for e in ap.events if e["event"] == "read_rewritten"]          # nothing moved under the read
    # the stamped run carries the same sigma (point-in-time provenance for replay)
    rd = await eng.team2.replay(ap.run_id)
    assert (rd.get("result") or {}).get("summary", {}).get("sigma") == pytest.approx(snap["value"], abs=1e-3)


async def test_a_moved_input_is_reported_and_never_re_fires(rig):
    eng, sim = rig
    runner, ap, rth = await _armed(eng)
    await eng.team2.preopen_complete()
    n = await _drive_until_fire(runner, ap, rth)
    fired_ids = [e.get("trigger") for e in ap.events if e["event"] == "fired"]
    # an IV change alone does NOT change what fired: the fire's identity (bar, setup, touch) is IV-free
    ap.plan["sigma"]["value"] = 0.95
    await runner.on_bar(ap.run_id, rth[n]); await runner.on_bar(ap.run_id, rth[n + 1])
    assert not [e for e in ap.events if e["event"] == "read_rewritten"]
    # now an input that DOES move the read's history: the PDH zone jumps 50 points, so the scenario that
    # confirmed at 09:45 (and the fire it produced) no longer exist in the recomputed read
    for z in ap.plan["zones"].values():
        z["top"] += 50; z["bottom"] += 50
    for b in rth[n + 2:]:
        await runner.on_bar(ap.run_id, b)
    rewritten = [e for e in ap.events if e["event"] == "read_rewritten"]
    assert len(rewritten) == 1 and rewritten[0]["count"] >= 2                    # said once, with the count
    ids = [e.get("trigger") for e in ap.events if e["event"] == "fired"]
    assert ids[: len(fired_ids)] == fired_ids and len(ids) == len(set(ids))      # the earlier fire stands once; a genuinely NEW
    assert all(i not in fired_ids for i in ids[len(fired_ids):])                 # event under the moved read still acts


async def test_the_locked_iv_comes_from_todays_atm_chain_when_it_prices(rig, monkeypatch):
    eng, sim = rig
    runner, ap, rth = await _armed(eng)
    await eng.team2.preopen_complete()
    spot = rth[0].close
    seen: list[tuple] = []

    async def fake_chain(self_, symbol, expiry):
        seen.append((symbol, expiry))
        rows = []
        here = float(eng.quotes.get(symbol).last)          # the sim feed keeps printing SPY: build the chain around what it shows
        for k in (round(here) - 2, round(here) - 1, round(here), round(here) + 1, round(here) + 2):
            for typ, iv in (("call", 0.21 + 0.01 * abs(k - here)), ("put", 0.25 + 0.01 * abs(k - here))):
                rows.append({"symbol": f"SPY{typ[0].upper()}{k}", "option_type": typ, "strike": float(k), "expiry": expiry,
                             "bid": 0.5, "ask": 0.6, "greeks": {"mid_iv": iv}})
        return rows

    monkeypatch.setattr(eng.options.provider().__class__, "chain", fake_chain)
    eng.quotes.on_quote(Quote(symbol=ap.symbol, last=spot, bid=spot - 0.01, ask=spot + 0.01, session="regular"))
    for b in rth[:2]:                                   # the read (and the lock) happens on the first 2m close
        await runner.on_bar(ap.run_id, b)
    snap = ap.plan["sigma"]
    # the sim feed keeps printing SPY, so the strike nearest the spot the snapshot SAW is the ATM one
    assert snap["source"] == "chain_atm" and snap["chainDelayed"] is True and snap["strike"] == round(snap["spot"])
    assert snap["value"] == pytest.approx((0.21 + 0.25) / 2 + 0.01 * abs(snap["strike"] - snap["spot"]), abs=2e-3)   # call+put ATM average
    assert seen and seen[0][0] == "SPY"
    # locked: the chain can move all it likes afterwards
    monkeypatch.setattr(eng.options.provider().__class__, "chain", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    for b in rth[2:6]:
        await runner.on_bar(ap.run_id, b)
    assert ap.plan["sigma"] == snap
    row = await runner.load_plan(ap.run_id)
    assert ((row.get("result") or {}).get("plan") or {}).get("sigma", {}).get("source") == "chain_atm"    # stamped on the run


async def test_the_read_falls_back_to_the_vix_proxy_when_the_chain_has_no_iv(rig):
    eng, sim = rig
    runner, ap, rth = await _armed(eng)
    await eng.team2.preopen_complete()
    for b in rth[:2]:
        await runner.on_bar(ap.run_id, b)
    snap = ap.plan["sigma"]
    assert snap["source"] == "vix_proxy" and snap["value"] == pytest.approx(0.20)   # no VIX bars banked either: the 0.20 floor


# ---------------------------------------------------------------- F49
async def test_day_type_is_finalized_on_the_real_open_and_the_estimate_is_kept(rig):
    eng, sim = rig
    runner, ap, rth = await _armed(eng)
    await eng.team2.preopen_complete()
    assert ap.plan["openSource"] == "premarket_last" and ap.plan["complete"]
    est = ap.plan["openPrice"]
    await runner.on_bar(ap.run_id, rth[0])
    assert ap.plan["openSource"] == "rth_open" and ap.plan["openPrice"] == rth[0].open
    assert ap.plan["preopenSnapshot"]["openPrice"] == est and ap.plan["preopenSnapshot"]["openSource"] == "premarket_last"
    assert any(e["event"] == "open_finalized" for e in ap.events)
    await runner.on_bar(ap.run_id, rth[1])
    assert sum(1 for e in ap.events if e["event"] == "open_finalized") == 1      # once


# ---------------------------------------------------------------- F50
async def test_target_sells_once_on_a_fresh_print_through_it(rig, monkeypatch):
    eng, sim = rig
    runner, ap, rth = await _armed(eng)
    await runner.set_mode(ap.run_id, "auto")
    calls: list[tuple] = []

    async def fake_exit(ap_, t, kind, qty, *, journal, force_market=False, reason=""):
        calls.append((kind, qty, force_market))
        t.exits.append({"kind": kind, "qty": qty, "orderId": "t1", "status": "SUBMITTED", "filledQty": 0.0})
        t.exit_order_ids.append("t1")

    monkeypatch.setattr(runner, "_exit", fake_exit)
    tr = Trade(trigger_id="pm_break_down@09:30#1", kind="pm_break_down", fired_ts=1, window="team2", entry=716.9, stop=717.4,
               targets=[716.34], status="open", setup_id="pm_break_down@09:30", entry_order_id="e", filled_qty=14, remaining=14,
               avg_fill=0.655, instrument="options", order_symbol="QQQ260908P00714000", multiplier=100.0, direction="short")
    ap.trades[tr.trigger_id] = tr
    # not through the target: nothing
    eng.quotes.on_quote(Quote(symbol=ap.symbol, last=716.60, bid=716.59, ask=716.61, session="regular"))
    await runner.on_quote_watch()
    assert not calls
    # through it on a fresh print: one reduce-only limit exit for the remaining size
    eng.quotes.on_quote(Quote(symbol=ap.symbol, last=716.30, bid=716.29, ask=716.31, session="regular"))
    await runner.on_quote_watch()
    assert calls == [("tp3", 14, False)]
    assert any(e["event"] == "target_hit" for e in ap.events)
    # a second poll while the exit is pending does not send another
    await runner.on_quote_watch()
    assert len(calls) == 1
    # a stale print through the target does not sell (freshness is the guard)
    tr.exits.clear(); tr.exit_order_ids.clear(); calls.clear()
    q = Quote(symbol=ap.symbol, last=716.00, bid=715.99, ask=716.01, session="regular")
    q.ts = q.ts - 3_600_000
    eng.quotes.on_quote(q)
    await runner.on_quote_watch()
    assert not calls
