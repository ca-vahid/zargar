"""P-06 `tp1-reclaim-runner-exit-v1` after the ED closure re-review (2026-09-17 evening): chronological reducer over the trade
instance's confirmed executions and completed bars; strict shared observation validator; dollars option-only; the
runtime observer seeks the first covered quote without consuming eligibility. Pure tests: synthetic bars, exit records,
executions, observations, and a fake runner for the capture semantics. No engine, no database, no orders."""
import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from zargar.tools.em_profitability import (P06_OBSERVATION_LIFETIME_MS, P06_POLICY, never_tp1_diag, runner_protection,
                                           validate_observation)

NY = ZoneInfo("America/New_York")


def _ms(h, m, s=0):
    return int(dt.datetime(2026, 9, 17, h, m, s, tzinfo=NY).timestamp() * 1000)


def _bar(ts, o, h, l, c):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c}


def _ex(order_id, ts, qty, price, commission=0.0, side="SELL"):
    return {"order_id": order_id, "side": side, "qty": qty, "price": price, "commission": commission, "ts": ts}


def _obs(at, bid, covered, *, inst="ENTRY-1", contract="BMNR260925P00023000", bar_ts=None, src_offset=-500, disposition="observed", scorable=True):
    return {"rung": "tp1-reclaim", "tradeInstance": inst, "observedAt": at, "disposition": disposition,
            "contract": {"symbol": contract, "sourceTs": at + src_offset, "bid": bid, "ask": bid + 0.05},
            "signal": {"barTs": bar_ts}, "modeled": {"scorable": scorable, "bid": bid, "coveredQty": covered}}


TP1, ENTRY, STOP = 104.6325, 103.885, 103.3656
CUT = _ms(16, 0)
IDENT = dict(entry_order_id="ENTRY-1", contract_symbol="SCHW", opened_ts=_ms(9, 40), closed_ts=_ms(15, 56, 1))


def _shares_bars():
    bars = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66), _bar(_ms(11, 51), 104.66, 104.7, 104.55, 104.60),
            _bar(_ms(11, 52), 104.60, 104.9, 104.58, 104.85)]
    bars += [_bar(_ms(11, 53) + i * 60000, 104.7, 104.8, 104.6, 104.72) for i in range(250)]
    return bars


# ----------------------------------------------------------------------------------------------- correction 2: chronology
def test_confirmed_trim_then_reclaim_shares_stay_proxy_only_even_with_an_observation():
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "flatten", "orderId": "x-flat", "qty": 33}]
    execs = [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64), _ex("x-flat", _ms(15, 56, 1), 33, 104.7191)]
    obs = [_obs(_ms(11, 52, 2), 104.61, 33, contract="SCHW", bar_ts=_ms(11, 51))]
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, _shares_bars(), CUT, filled_qty=47, multiplier=1.0, instrument="shares", observations=obs, **IDENT)
    assert r["policy"] == P06_POLICY and r["outcome"] == "underlying_proxy_only" and "proxy only" in r["why"]
    assert r["eligibleAt"] == _ms(11, 51, 3) and r["tp1FilledQty"] == 14 and r["remainingAtSignal"] == 33
    assert r["reclaimTs"] == _ms(11, 51) and r["signalTs"] == _ms(11, 52) and r["modeledExitPx"] == 104.60
    assert r["productionRunner"] == {"qty": 33, "vwap": 104.7191, "fees": 0.0, "kinds": ["flatten"]}
    assert r["dollarDelta"] is None and r["dollarScope"].startswith("options only")


def test_a_later_partial_tp1_fill_never_moves_eligibility_and_reduces_the_remainder():
    # TP1 order for 14: 5 fill at 11:51:03, the other 9 fill at 11:53:20 (after the reclaim signal at 11:52)
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "flatten", "orderId": "x-flat", "qty": 33}]
    execs = [_ex("x-tp1", _ms(11, 51, 3), 5, 104.64), _ex("x-tp1", _ms(11, 53, 20), 9, 104.70), _ex("x-flat", _ms(15, 56, 1), 33, 104.7191)]
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, _shares_bars(), CUT, filled_qty=47, multiplier=1.0, instrument="shares", **IDENT)
    assert r["eligibleAt"] == _ms(11, 51, 3), "the first TP1 fill opens eligibility; the later partial does not move it"
    assert r["reclaimTs"] == _ms(11, 51) and r["remainingAtSignal"] == 42, "5 sold before the signal; the later 9 are production's"
    assert r["outcome"] == "underlying_proxy_only" and r["productionRunner"]["qty"] == 42 and sorted(r["productionRunner"]["kinds"]) == ["flatten", "tp1"]


def test_intermediate_tp2_trim_then_reclaim_keeps_evaluating():
    # TP1 fills 14 at 11:51:03; TP2 trims 10 at 11:53:04 (bar 11:52 closed above TP1 at 11:53); bar 11:54 closes back below TP1 at 11:55
    bars = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66), _bar(_ms(11, 51), 104.66, 105.3, 104.6, 105.2), _bar(_ms(11, 52), 105.2, 105.3, 105.0, 105.29),
            _bar(_ms(11, 53), 105.29, 105.3, 104.7, 104.80), _bar(_ms(11, 54), 104.80, 104.85, 104.5, 104.55), _bar(_ms(11, 55), 104.55, 104.8, 104.5, 104.70)]
    bars += [_bar(_ms(11, 56) + i * 60000, 104.7, 104.8, 104.6, 104.72) for i in range(250)]
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "tp2", "orderId": "x-tp2", "qty": 10}, {"kind": "flatten", "orderId": "x-flat", "qty": 23}]
    execs = [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64), _ex("x-tp2", _ms(11, 53, 4), 10, 105.29), _ex("x-flat", _ms(15, 56), 23, 104.7191),
             _ex("other-instance", _ms(11, 52, 30), 40, 99.0)]          # a refired trade's execution: not one of this trade's orders
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, bars, CUT, filled_qty=47, multiplier=1.0, instrument="shares", **IDENT)
    assert r["outcome"] == "underlying_proxy_only", r
    assert r["reclaimTs"] == _ms(11, 54) and r["remainingAtSignal"] == 23, "the TP2 trim reduced the remainder and did NOT end the evaluation"
    assert r["modeledExitPx"] == 104.55 and r["productionRunner"] == {"qty": 23, "vwap": 104.7191, "fees": 0.0, "kinds": ["flatten"]}


def test_full_stop_first_ends_the_evaluation_and_a_missing_minute_is_unknown():
    exits = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "stop", "orderId": "x-stop", "qty": 33}]
    bars = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66), _bar(_ms(11, 51), 104.66, 104.7, 103.2, 103.3), _bar(_ms(11, 52), 103.3, 103.4, 103.1, 103.2)]
    execs = [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64), _ex("x-stop", _ms(11, 51, 40), 33, 103.25)]
    r = runner_protection("long", TP1, ENTRY, STOP, exits, execs, bars, CUT, filled_qty=47, multiplier=1.0, instrument="shares", **IDENT)
    assert r["outcome"] == "not_triggered" and "stop" in r["why"]
    gap = [_bar(_ms(11, 50), 104.5, 104.7, 104.45, 104.66), _bar(_ms(11, 53), 104.66, 104.7, 104.55, 104.60)]
    r2 = runner_protection("long", TP1, ENTRY, STOP, exits[:1] + [{"kind": "flatten", "orderId": "x-flat", "qty": 33}],
                           [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64), _ex("x-flat", _ms(15, 56), 33, 104.72)], gap, CUT, filled_qty=47, multiplier=1.0, instrument="shares", **IDENT)
    assert r2["outcome"] == "unknown" and "bar gap" in r2["why"]


def test_cancelled_trim_pending_ordinary_exit_and_open_runner_are_explicit():
    bars = _shares_bars()
    cancelled = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14, "status": "CANCELLED", "filledQty": 0.0}, {"kind": "flatten", "orderId": "x-flat", "qty": 47}]
    r = runner_protection("long", TP1, ENTRY, STOP, cancelled, [_ex("x-flat", _ms(15, 56, 1), 47, 104.7191)], bars, CUT, filled_qty=47, multiplier=1.0, instrument="shares", **IDENT)
    assert r["outcome"] == "not_eligible" and "never filled" in r["why"]
    # a working ordinary exit (no fill, not cancelled) leaves the runner partial - a later sale is never assumed
    working = [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "tp2", "orderId": "x-tp2", "qty": 33, "status": "SUBMITTED", "ts": _ms(13, 0)}]
    r2 = runner_protection("long", TP1, ENTRY, STOP, working, [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64)], bars, CUT, filled_qty=47, multiplier=1.0, instrument="shares", **IDENT)
    assert r2["outcome"] == "partial" and "working" in r2["why"]
    # executions AFTER the cutoff are ignored: the flatten at 15:56 is invisible to a 15:00 cutoff -> partial
    r3 = runner_protection("long", TP1, ENTRY, STOP, [{"kind": "tp1", "orderId": "x-tp1", "qty": 14}, {"kind": "flatten", "orderId": "x-flat", "qty": 33}],
                           [_ex("x-tp1", _ms(11, 51, 3), 14, 104.64), _ex("x-flat", _ms(15, 56, 1), 33, 104.7191)], bars, _ms(15, 0),
                           filled_qty=47, multiplier=1.0, instrument="shares", **IDENT)
    assert r3["outcome"] == "partial"


# ----------------------------------------------------------------------------------------------- correction 3: validator
OPT = dict(filled_qty=4, multiplier=100.0, instrument="options", avg_fill=0.86, entry_fee_per_unit=1.04, fee_side=1.04,
           entry_order_id="ENTRY-1", contract_symbol="BMNR260925P00023000", opened_ts=_ms(9, 31), closed_ts=_ms(9, 53, 26))
OTP1, OENTRY, OSTOP = 23.3548, 23.5906, 23.7501


def _opt_bars():
    bars = [_bar(_ms(9, 31), 23.6, 23.62, 23.3, 23.34), _bar(_ms(9, 32), 23.35, 23.6, 23.33, 23.55), _bar(_ms(9, 33), 23.54, 23.7, 23.5, 23.65)]
    return bars + [_bar(_ms(9, 34) + i * 60000, 23.65, 23.85, 23.6, 23.80) for i in range(30)]


OEXITS = [{"kind": "tp1", "orderId": "o-tp1", "qty": 1}, {"kind": "stop", "orderId": "o-stop", "qty": 3}]
OEXECS = [_ex("o-tp1", _ms(9, 32, 1), 1, 0.80, 1.04), _ex("o-stop", _ms(9, 53, 26), 3, 0.60, 3.12)]
SIGNAL_BAR = _ms(9, 32)      # the 09:32 bar closed 23.55 > TP1 -> signal at 09:33


def test_options_earliest_strictly_valid_observation_wins_over_a_later_more_favourable_one():
    obs = [_obs(_ms(9, 33, 40), 0.90, 3, bar_ts=SIGNAL_BAR),      # later and more favourable - must NOT be chosen
           _obs(_ms(9, 33, 2), 0.78, 3, bar_ts=SIGNAL_BAR)]
    r = runner_protection("short", OTP1, OENTRY, OSTOP, OEXITS, OEXECS, _opt_bars(), CUT, observations=obs, **OPT)
    assert r["outcome"] == "compared" and r["modeledExitPx"] == 0.78 and r["modeledExitTs"] == _ms(9, 33, 2)
    alt = 3 * ((0.78 - 0.86) * 100 - 1.04 - 1.04); prod = 3 * ((0.60 - 0.86) * 100 - 1.04) - 3.12
    assert r["alternativeRealized"] == round(alt, 2) and r["productionRealized"] == round(prod, 2) and r["dollarDelta"] == round(alt - prod, 2)


def test_reviewer_reproduction_wrong_identity_or_contract_or_after_cutoff_never_compares():
    good = dict(bid=0.90, covered=3, bar_ts=SIGNAL_BAR)
    bad = [_obs(_ms(9, 33, 2), inst="OTHER_ENTRY", **good), _obs(_ms(9, 33, 2), contract="WRONG_CONTRACT", **good),
           _obs(_ms(16, 39), **good),                                            # after the cutoff / position close
           {**_obs(_ms(9, 33, 2), **good), "tradeInstance": None},               # missing identity
           {**_obs(_ms(9, 33, 2), **good), "signal": {}},                        # missing signal identity
           _obs(_ms(9, 33, 2), bid=0.90, covered=3, bar_ts=_ms(9, 31)),           # a different signal bar
           _obs(_ms(9, 33, 2), bid=0.90, covered=3, bar_ts=SIGNAL_BAR, src_offset=+3000),   # quote time after the observation: out of order
           _obs(_ms(9, 32, 30), **good),                                         # before the signal
           _obs(_ms(9, 33, 2), bid=0.90, covered=1, bar_ts=SIGNAL_BAR),           # partial coverage
           _obs(_ms(9, 33, 2), bid=0.90, covered=3, bar_ts=SIGNAL_BAR, disposition="pending_exit"),
           _obs(_ms(9, 33, 2), bid=0.90, covered=3, bar_ts=SIGNAL_BAR, scorable=False),
           _obs(_ms(9, 33) + P06_OBSERVATION_LIFETIME_MS + 1000, **good)]        # beyond the lifetime
    r = runner_protection("short", OTP1, OENTRY, OSTOP, OEXITS, OEXECS, _opt_bars(), CUT, observations=bad, **OPT)
    assert r["outcome"] == "underlying_proxy_only" and r["dollarDelta"] is None
    assert len(r["observationsRejected"]) == len(bad)
    reasons = " | ".join(x["why"] for x in r["observationsRejected"])
    for needle in ("trade instance", "contract", "after the cutoff", "signal identity", "out of order", "before the signal", "coverage", "disposition", "unscorable"):
        assert needle in reasons, needle
    # the strict validator alone: a missing entry-order id on the reducer side is a failure too
    ok, why, _, _ = validate_observation(_obs(_ms(9, 33, 2), **good), rung="tp1-reclaim", entry_order_id=None, contract_symbol="BMNR260925P00023000",
                                         signal_bar_ts=SIGNAL_BAR, signal_ts=_ms(9, 33), remaining=3, cutoff_ms=CUT)
    assert not ok and "trade instance" in why


def test_options_without_a_valid_observation_are_an_underlying_proxy_against_the_underlying():
    r = runner_protection("short", OTP1, OENTRY, OSTOP, OEXITS, OEXECS, _opt_bars(), CUT, **OPT)
    assert r["outcome"] == "underlying_proxy_only" and r["remainingAtSignal"] == 3 and r["signalTs"] == _ms(9, 33)
    assert r["modeledExitPx"] == 23.54 and r["productionRunner"]["vwap"] == 0.6 and r["productionRunner"]["underlyingRef"] == 23.80
    assert r["underlyingDeltaR"] == round((23.80 - 23.54) / (OSTOP - OENTRY), 3)


# ----------------------------------------------------------------------------------------------- correction 1: observer
def _fake_runner(quotes: dict):
    from zargar.execution.planrunner import PlanRunner
    fake = SimpleNamespace(engine=SimpleNamespace(quotes=SimpleNamespace(get=lambda sym: quotes.get(sym))),
                           rt=lambda key, default=None: default, _log=lambda *a, **k: None,
                           _shadow_enabled=lambda ap: True)
    # the real production-rung helpers, bound to the fake (they read only ap.config / tr)
    fake._full_exit_rung = lambda ap, tr, qty: PlanRunner._full_exit_rung(fake, ap, tr, qty)
    fake._production_exit_qty = lambda ap, tr, idx, label: PlanRunner._production_exit_qty(fake, ap, tr, idx, label)
    fake._shadow_capture_rung = lambda *a, **k: PlanRunner._shadow_capture_rung(fake, *a, **k)
    fake.__dict__.setdefault("_shadow_seen", set()); fake.__dict__.setdefault("_shadow_pending", set())
    fake._now_ms = lambda: _ms(9, 33, 1)                       # the signal-time sample is judged at 09:33:01 ET, not the wall clock
    return fake, PlanRunner


def _trade(remaining=3.0):
    from zargar.execution.planrunner import Trade
    tr = Trade(trigger_id="r1", kind="reject", fired_ts=_ms(9, 31), window="prime_open", entry=OENTRY, stop=OSTOP, targets=[OTP1, 23.1486, 23.0012],
               status="open", entry_order_id="ENTRY-1", filled_qty=4.0, remaining=remaining, instrument="options", direction="short",
               contract={"symbol": "BMNR260925P00023000"}, order_symbol="BMNR260925P00023000", multiplier=100.0, opened_ts=_ms(9, 31, 3))
    tr.exits.append({"kind": "tp1", "orderId": "o-tp1", "qty": 1, "filledQty": 1.0, "status": "FILLED"})
    return tr


def _quote(sym, bid, ask, bid_size, ts, *, source="opra", src_ts=None):
    return SimpleNamespace(symbol=sym, bid=bid, ask=ask, last=ask, bid_size=bid_size, ask_size=50, ts=ts, source=source, source_ts=(src_ts if src_ts is not None else ts - 500), delayed=False, mid=(bid + ask) / 2)


def test_observer_stale_first_sample_is_raw_and_a_later_fresh_quote_supplies_the_covered_observation():
    now = _ms(9, 33, 1)
    quotes = {"BMNR": _quote("BMNR", 23.53, 23.55, 100, now), "BMNR260925P00023000": _quote("BMNR260925P00023000", 0.78, 0.83, 40, now, src_ts=now - 30_000)}   # contract quote 30 s old = stale
    fake, PR = _fake_runner(quotes)
    ap = SimpleNamespace(run_id="RUN", symbol="BMNR", config=SimpleNamespace(portfolio_id="p", single_contract_exit="tp2"))
    tr = _trade()
    bar = SimpleNamespace(ts=SIGNAL_BAR, close=23.55, open=23.35, high=23.6, low=23.33)
    out = PR._reclaim_signal(fake, ap, tr, bar)
    assert tr.reclaim_signal and tr.reclaim_signal["barTs"] == SIGNAL_BAR and tr.reclaim_signal["signalTs"] == _ms(9, 33)
    assert len(out) == 1 and out[0]["rung"] == "tp1-reclaim" and out[0]["modeled"]["scorable"] is False and out[0]["_key"][-1] == "tp1-reclaim-raw"
    assert out[0]["signal"]["barTs"] == SIGNAL_BAR
    fake._shadow_seen.add(out[0]["_key"]); fake._shadow_pending.discard(out[0]["_key"])      # the raw write succeeded
    # a second call on the bar does nothing: the signal is set once
    assert PR._reclaim_signal(fake, ap, tr, bar) == []
    # the quote watch: a fresh, covered contract quote 12 s later supplies the covered observation (own key)
    later = now + 12_000
    quotes["BMNR260925P00023000"] = _quote("BMNR260925P00023000", 0.79, 0.84, 40, later)
    quotes["BMNR"] = _quote("BMNR", 23.56, 23.58, 100, later)
    out2 = PR._shadow_capture(fake, ap, [tr], quotes["BMNR"], later, 0.25)
    rec = [p for p in out2 if p["rung"] == "tp1-reclaim"]
    assert len(rec) == 1 and rec[0]["modeled"]["scorable"] is True and rec[0]["modeled"]["coveredQty"] == 3 and rec[0]["_key"][-1] == "tp1-reclaim"
    assert rec[0]["signal"]["barTs"] == SIGNAL_BAR and rec[0]["tradeInstance"] == "ENTRY-1"
    fake._shadow_seen.add(rec[0]["_key"]); fake._shadow_pending.discard(rec[0]["_key"])
    # once covered, later (even better) quotes are not captured for this rung
    quotes["BMNR260925P00023000"] = _quote("BMNR260925P00023000", 0.95, 1.00, 40, later + 5000)
    out3 = PR._shadow_capture(fake, ap, [tr], quotes["BMNR"], later + 5000, 0.25)
    assert [p for p in out3 if p["rung"] == "tp1-reclaim"] == []


def test_observer_partial_depth_is_raw_then_sufficient_depth_is_covered_and_pending_exit_blocks_the_signal():
    now = _ms(9, 33, 1)
    quotes = {"BMNR": _quote("BMNR", 23.53, 23.55, 100, now), "BMNR260925P00023000": _quote("BMNR260925P00023000", 0.78, 0.83, 1, now)}   # depth 1 < remaining 3
    fake, PR = _fake_runner(quotes)
    ap = SimpleNamespace(run_id="RUN", symbol="BMNR", config=SimpleNamespace(portfolio_id="p", single_contract_exit="tp2"))
    tr = _trade()
    out = PR._reclaim_signal(fake, ap, tr, SimpleNamespace(ts=SIGNAL_BAR, close=23.55, open=23.35, high=23.6, low=23.33))
    assert out[0]["modeled"]["scorable"] is True and out[0]["modeled"]["coveredQty"] == 1 and out[0]["modeled"]["unresolvedQty"] == 2
    # the observer records what it saw; coverage below the remainder is the REDUCER's rejection (partial coverage case) -
    # the rung's covered key is consumed by a scorable sample, so the reducer must see coverage explicitly
    fake._shadow_seen.add(out[0]["_key"])
    r = runner_protection("short", OTP1, OENTRY, OSTOP, OEXITS, OEXECS, _opt_bars(), CUT, observations=[{**out[0], "observedAt": now}], **OPT)
    assert r["outcome"] == "underlying_proxy_only" and any("coverage" in x["why"] for x in r["observationsRejected"])
    # a working exit blocks the signal entirely (pending-exit precedence)
    tr2 = _trade(); tr2.exits.append({"kind": "tp2", "orderId": "o-tp2", "qty": 1, "filledQty": 0.0, "status": "SUBMITTED"})   # a working exit
    assert tr2.pending_exit_qty == 1.0
    assert PR._reclaim_signal(fake, ap, tr2, SimpleNamespace(ts=SIGNAL_BAR, close=23.55, open=23.35, high=23.6, low=23.33)) == [] and tr2.reclaim_signal is None


def test_never_tp1_diag_is_descriptive_and_skips_filled_trims():
    bars = [_bar(_ms(9, 40) + i * 60000, 258.0, 258.5 + (i == 5) * 1.9, 257.8, 258.2) for i in range(20)]
    d = never_tp1_diag("long", 258.4742, 255.4297, _ms(9, 40), _ms(10, 0), [(0, {"kind": "flatten", "qty": 19})], bars)
    assert d["heldBars"] == 19 and d["mfeR"] == round((260.4 - 258.4742) / (258.4742 - 255.4297), 3)
    assert never_tp1_diag("long", 258.4742, 255.4297, _ms(9, 40), _ms(10, 0), [(0, {"kind": "tp1", "qty": 5})], bars) is None


def test_tp1_reclaim_signal_is_pure_and_side_aware():
    from zargar.execution.exits import tp1_reclaim_signal
    assert tp1_reclaim_signal("long", 104.6325, 104.60) and not tp1_reclaim_signal("long", 104.6325, 104.70)
    assert tp1_reclaim_signal("short", 23.3548, 23.55) and not tp1_reclaim_signal("short", 23.3548, 23.30)
    assert not tp1_reclaim_signal("long", None, 100.0) and not tp1_reclaim_signal("long", 100.0, None)
