"""2026-09-21 fix goal: clock health, systemic admission alarms and the bounded deferral retry.

The session these cover: the experimental book fired thirteen times, deferred nine on
`venue_time_in_future`, submitted nothing, and said nothing about it. Three separate faults are
pinned here - a host clock nobody was watching, an alarm that did not exist, and a "deferral" that
was really terminal - and the admission gate itself is pinned UNCHANGED, because it was right.
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_codex_em_final_dispatch_budget import CONTRACT, dispatch_rig  # noqa: F401 - the reviewers' rig, unchanged
from zargar.domain import Quote, now_ms
from zargar.technique import admission_health as ah
from zargar.technique import deferred_retry as dr
from zargar.tools import clock_health as ch

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------------------------
# clock health: the measurement that was missing on 2026-09-21
# --------------------------------------------------------------------------------------------

def _servers(monkeypatch, offsets: dict, *, delay_ms: float = 20.0):
    def fake(host, timeout=3.0):
        if isinstance(offsets[host], Exception):
            raise offsets[host]
        return {"server": host, "offsetMs": offsets[host], "roundTripMs": delay_ms,
                "uncertaintyMs": delay_ms / 2, "stratum": 1}
    monkeypatch.setattr(ch, "ntp_offset", fake)
    return tuple(offsets)


def test_a_quorum_of_servers_that_agree_is_what_makes_the_offset_trustworthy(monkeypatch):
    names = _servers(monkeypatch, {"a": 10510.0, "b": 10520.0, "c": 10530.0})
    d = ch.measure_ntp(names)
    assert d["status"] == "fail" and d["offsetMs"] == 10520.0 and d["agreed"] is True
    assert d["direction"] == "host behind true time", "a positive offset means the HOST is behind"


def test_servers_that_disagree_produce_unknown_not_a_confident_wrong_number(monkeypatch):
    names = _servers(monkeypatch, {"a": 0.0, "b": 9000.0, "c": -4000.0})
    d = ch.measure_ntp(names)
    assert d["status"] == "unknown" and d["agreed"] is False and "disagree" in d["why"]


def test_one_unreachable_server_does_not_stop_the_measurement(monkeypatch):
    names = _servers(monkeypatch, {"a": 120.0, "b": TimeoutError("no answer"), "c": 130.0})
    d = ch.measure_ntp(names)
    assert d["status"] == "ok" and len(d["servers"]) == 2 and len(d["errors"]) == 1


def test_no_server_answers_is_unknown_never_ok(monkeypatch):
    names = _servers(monkeypatch, {"a": TimeoutError("x"), "b": OSError("y")})
    d = ch.measure_ntp(names)
    assert d["status"] == "unknown" and d["offsetMs"] is None


@pytest.mark.parametrize("offset,status", [(50.0, "ok"), (700.0, "warn"), (10520.0, "fail")])
def test_the_thresholds_are_the_gates_own_tolerance(monkeypatch, offset, status):
    names = _servers(monkeypatch, {"a": offset, "b": offset + 5})
    assert ch.measure_ntp(names)["status"] == status


async def test_the_report_says_whether_admission_is_broken_and_never_proposes_loosening_it(monkeypatch):
    names = _servers(monkeypatch, {"a": 10510.0, "b": 10520.0})
    monkeypatch.setattr(ch, "platform_sync", lambda: {"platform": "windows", "service": "Stopped",
                                                      "startType": "Manual", "status": "fail",
                                                      "why": "not synchronized"})
    d = await ch.build(servers=names, with_db=False)
    a = d["admissionImpact"]
    assert d["status"] == "fail"
    assert a["breaksAdmission"] is True and a["gateFutureToleranceMs"] == 1000
    assert round(a["apparentFutureOnFreshQuoteMs"]) == 10520
    assert "must not be loosened" in a["note"]
    text = ch.render(d)
    assert "entries will be refused" in text and "Stopped" in text


async def test_a_healthy_clock_on_an_unsynchronized_host_is_still_a_warning(monkeypatch):
    names = _servers(monkeypatch, {"a": 5.0, "b": 7.0})
    monkeypatch.setattr(ch, "platform_sync", lambda: {"platform": "windows", "service": "Stopped",
                                                      "startType": "Manual", "status": "fail", "why": "x"})
    d = await ch.build(servers=names, with_db=False)
    assert d["status"] == "warn", "right now but drifting again after the next reboot is not ok"


# --------------------------------------------------------------------------------------------
# systemic admission alarm: noticing that the desk is armed and silent
# --------------------------------------------------------------------------------------------

BOOK = "07ef1e867cad4150bc81e072a8fd600a"


def _rec(problem: str = "venue_time_in_future", *, host_ms: int, ahead_ms: int = 9600) -> dict:
    return {"ts": host_ms,
            "underlying": {"evidence": {"quoteTs": host_ms + ahead_ms, "lastTs": host_ms + ahead_ms,
                                        "receivedTs": host_ms, "source": "feed:HybridQuoteFeed"},
                           "validated": {"status": "invalid", "problems": [problem]}}}


def test_two_symbols_one_cause_within_the_window_is_the_alarm():
    w, t0 = ah.AdmissionWatch(), 1_700_000_000_000
    assert w.observe(_rec(host_ms=t0), book=BOOK, symbol="IREN", disposition="deferred_missing_evidence") is None
    alarm = w.observe(_rec(host_ms=t0 + 1000), book=BOOK, symbol="ON", disposition="deferred_missing_evidence")
    assert alarm and alarm["kind"] == "systemic_admission_failure"
    assert alarm["cause"] == "venue_time_in_future" and alarm["count"] == 2
    assert alarm["distinctSymbols"] == ["IREN", "ON"] and alarm["noSubmissionInBook"] is True
    assert alarm["offsetsMs"]["representative"] == 9600.0
    assert alarm["isGate"] is False, "an alarm must never be able to become a gate"
    assert "host clock" in alarm["text"] and "gate is correct to refuse" in alarm["text"]


def test_the_same_symbol_deferring_twice_is_not_yet_systemic():
    w, t0 = ah.AdmissionWatch(), 1_700_000_000_000
    assert w.observe(_rec(host_ms=t0), book=BOOK, symbol="IREN", disposition="deferred_missing_evidence") is None
    assert w.observe(_rec(host_ms=t0 + 500), book=BOOK, symbol="IREN", disposition="deferred_missing_evidence") is None


def test_a_slow_failure_still_alarms_on_the_third_silent_attempt():
    w, t0 = ah.AdmissionWatch(), 1_700_000_000_000
    hour = 3_600_000
    assert w.observe(_rec(host_ms=t0), book=BOOK, symbol="A", disposition="deferred_missing_evidence") is None
    assert w.observe(_rec(host_ms=t0 + hour), book=BOOK, symbol="A", disposition="deferred_missing_evidence") is None
    alarm = w.observe(_rec(host_ms=t0 + 2 * hour), book=BOOK, symbol="A", disposition="deferred_missing_evidence")
    assert alarm and alarm["count"] == 3 and alarm["noSubmissionInBook"] is True


def test_an_ordinary_refusal_never_pages_anyone():
    w, t0 = ah.AdmissionWatch(), 1_700_000_000_000
    for sym in ("A", "B", "C", "D"):
        assert w.observe({"ts": t0}, book=BOOK, symbol=sym, disposition="refused") is None, \
            "the method declining a trade is the policy working, not an incident"


def test_a_book_that_is_trading_does_not_alarm_on_scattered_deferrals():
    w, t0 = ah.AdmissionWatch(), 1_700_000_000_000
    w.observe({"ts": t0}, book=BOOK, symbol="X", disposition="passed")          # the book is alive
    hour = 3_600_000
    assert w.observe(_rec(host_ms=t0 + hour), book=BOOK, symbol="A", disposition="deferred_missing_evidence") is None
    assert w.observe(_rec(host_ms=t0 + 2 * hour), book=BOOK, symbol="B", disposition="deferred_missing_evidence") is not None, \
        "two symbols inside the window is still systemic even when the book has traded"


def test_the_alarm_does_not_repeat_inside_its_cooldown_but_keeps_counting():
    w, t0 = ah.AdmissionWatch(), 1_700_000_000_000
    w.observe(_rec(host_ms=t0), book=BOOK, symbol="A", disposition="deferred_missing_evidence")
    assert w.observe(_rec(host_ms=t0 + 1000), book=BOOK, symbol="B", disposition="deferred_missing_evidence")
    for i, sym in enumerate(("C", "D", "E")):
        assert w.observe(_rec(host_ms=t0 + 2000 + i), book=BOOK, symbol=sym, disposition="deferred_missing_evidence") is None
    assert w._alarmed[f"{BOOK}:venue_time_in_future"]["count"] == 5


def test_recovery_is_reported_once_when_an_entry_finally_passes():
    w, t0 = ah.AdmissionWatch(), 1_700_000_000_000
    w.observe(_rec(host_ms=t0), book=BOOK, symbol="A", disposition="deferred_missing_evidence")
    w.observe(_rec(host_ms=t0 + 1000), book=BOOK, symbol="B", disposition="deferred_missing_evidence")
    ok = w.observe({"ts": t0 + 2000}, book=BOOK, symbol="C", disposition="passed")
    assert ok and ok["kind"] == "systemic_admission_recovered" and ok["isGate"] is False
    assert w.observe({"ts": t0 + 3000}, book=BOOK, symbol="D", disposition="passed") is None, "recovery is announced once"


def test_a_second_books_failures_do_not_alarm_the_first():
    w, t0 = ah.AdmissionWatch(), 1_700_000_000_000
    assert w.observe(_rec(host_ms=t0), book=BOOK, symbol="A", disposition="deferred_missing_evidence") is None
    assert w.observe(_rec(host_ms=t0 + 10), book="other-book", symbol="B", disposition="deferred_missing_evidence") is None


def test_the_nine_records_of_2026_09_21_would_have_alarmed_within_two_seconds():
    """The real session, replayed from its own shape: IREN 13:31:02, ON 13:31:03."""
    w = ah.AdmissionWatch()
    t = 1_789_997_462_067
    assert w.observe(_rec(host_ms=t, ahead_ms=9516), book=BOOK, symbol="IREN",
                     disposition="deferred_missing_evidence", now_ms=t) is None
    alarm = w.observe(_rec(host_ms=t + 1502, ahead_ms=4030), book=BOOK, symbol="ON",
                      disposition="deferred_missing_evidence", now_ms=t + 1502)
    assert alarm is not None and alarm["lastAt"] - alarm["firstAt"] == 1502, \
        "the desk should have known 1.5 s after the second deferral, not hours later"


# --------------------------------------------------------------------------------------------
# deferral lifecycle: what the frozen policy really does, and the bounded proposal
# --------------------------------------------------------------------------------------------

def _trade(**kw):
    d = {"trigger_id": "b1", "status": "skipped", "filled_qty": 0.0, "entry_order_id": None,
         "fire_bar_index": 5, "timing": {"firstSale": {"disposition": "deferred_missing_evidence"}}}
    d.update(kw)
    return SimpleNamespace(**d)


def test_the_frozen_default_is_off_and_an_unreadable_value_is_off_not_bounded():
    assert dr.normalize_mode(None) == "off" and dr.normalize_mode("") == "off"
    assert dr.normalize_mode("bounded") == "bounded" and dr.normalize_mode("BOUNDED") == "bounded"
    assert dr.normalize_mode("yes") == "off" and dr.normalize_mode("retry") == "off"


def test_valid_evidence_inside_the_original_window_is_the_one_case_that_retries():
    ok, why = dr.eligible(_trade(), SimpleNamespace(status="fired"), bar_index=7, window_bars=3)
    assert ok and "inside the original" in why


def test_after_the_original_window_there_is_no_retry_and_no_chase():
    ok, why = dr.eligible(_trade(), SimpleNamespace(status="fired"), bar_index=12, window_bars=3)
    assert not ok and "elapsed" in why and "T4.1" in why


def test_a_setup_invalidated_while_waiting_is_never_revived():
    for status in ("invalidated", "expired", "stopped", "void"):
        ok, why = dr.eligible(_trade(), SimpleNamespace(status=status), bar_index=6, window_bars=3)
        assert not ok and status in why


def test_a_restart_during_the_deferral_refuses_rather_than_trusting_a_wall_clock():
    ok, why = dr.eligible(_trade(fire_bar_index=None), SimpleNamespace(status="fired"), bar_index=6, window_bars=3)
    assert not ok and "cannot bound the window without a clock" in why


def test_an_order_that_already_exists_can_never_be_doubled():
    for kw in ({"entry_order_id": "o-1"}, {"filled_qty": 2.0}):
        ok, why = dr.eligible(_trade(**kw), SimpleNamespace(status="fired"), bar_index=6, window_bars=3)
        assert not ok and "double" in why
    for st in ("working", "open", "submitting", "closed"):
        ok, why = dr.eligible(_trade(status=st), SimpleNamespace(status="fired"), bar_index=6, window_bars=3)
        assert not ok and "already sent or resolved" in why


def test_the_retry_is_used_once_and_only_once():
    ok, why = dr.eligible(_trade(), SimpleNamespace(status="fired"), bar_index=6, window_bars=3, retried={"b1"})
    assert not ok and "already used its one retry" in why


def test_a_method_refusal_is_a_decision_and_is_never_retried():
    t = _trade(timing={"firstSale": {"disposition": "refused"}})
    ok, why = dr.eligible(t, SimpleNamespace(status="fired"), bar_index=6, window_bars=3)
    assert not ok and "is a decision" in why


def test_a_halted_book_and_a_disarmed_plan_both_refuse():
    assert dr.eligible(_trade(), SimpleNamespace(status="fired"), bar_index=6, window_bars=3, halted=True)[0] is False
    ok, why = dr.eligible(_trade(), SimpleNamespace(status="fired"), bar_index=6, window_bars=3, plan_status="disarmed")
    assert not ok and "not armed" in why


# --------------------------------------------------------------------------------------------
# through the ACTUAL runner: the gate is unchanged, and the retry uses the production path
# --------------------------------------------------------------------------------------------

def _underlier(rig, *, venue_offset_ms: int, price: float = 100.0, symbol: str = "HOOD") -> None:
    """Publish a real-feed-shaped equity quote: two-sided, sourced, with its own venue time.
    `venue_offset_ms` is how far that venue time sits from this host's clock."""
    now = now_ms()
    q = Quote(symbol, bid=price - 0.01, ask=price + 0.01, last=price, ts=now, source="sip")
    q.quote_ts = now + venue_offset_ms
    q.last_ts = now + venue_offset_ms
    rig.engine.quotes.on_quote(q)


async def _enforce(rig):
    await rig.engine.settings.set("techniques.enhanced_market.first_sale_rr_gate", "enforce")
    # the gate target is pinned from the run's FROZEN config; the rig's run carries none, so pin it
    # here exactly as the reviewers' own first-sale tests do - an unresolved pin is its own refusal
    rig.runner._fs_pins = {rig.ap.run_id: {"pin": "tp2", "source": "run_config", "planRrGateTarget": 1}}
    rig.ap.plan = {"triggers": [{"id": "b1", "entry": {"price": 100.0}, "riskReward": 6.0}]}
    rig.trade.targets = [101.0, 106.0, 112.0]          # comfortably past the 3R floor at the gate target


async def test_a_fresh_real_feed_quote_admits_the_entry_and_it_reaches_the_executor(dispatch_rig):
    await _enforce(dispatch_rig)
    _underlier(dispatch_rig, venue_offset_ms=-250)     # a quarter second old: what a healthy host sees
    await dispatch_rig.runner._enter(dispatch_rig.ap, dispatch_rig.trade, SimpleNamespace(status="fired"), journal=False)
    assert dispatch_rig.submit.await_count == 1, "an eligible entry on valid evidence must reach the simulator"
    assert dispatch_rig.trade.status in ("submitting", "working", "open")


@pytest.mark.parametrize("offset,problem", [
    (10_500, "venue_time_in_future"),                  # the 2026-09-21 shape, to the millisecond
    (-3_600_000, "stale_underlier"),                   # an hour old
])
async def test_bad_venue_time_still_refuses_after_the_fix(dispatch_rig, offset, problem):
    await _enforce(dispatch_rig)
    _underlier(dispatch_rig, venue_offset_ms=offset)
    await dispatch_rig.runner._enter(dispatch_rig.ap, dispatch_rig.trade, SimpleNamespace(status="fired"), journal=False)
    assert dispatch_rig.submit.await_count == 0, "nothing may be sent on evidence the gate cannot trust"
    fs = dispatch_rig.trade.timing.get("firstSale") or {}
    assert fs.get("disposition") == "deferred_missing_evidence"


async def test_an_untimed_quote_is_refused_as_unknown_not_accepted_as_fresh(dispatch_rig):
    await _enforce(dispatch_rig)
    now = now_ms()
    q = Quote("HOOD", bid=99.99, ask=100.01, last=100.0, ts=now, source="sip")   # quote_ts / last_ts left at 0
    dispatch_rig.engine.quotes.on_quote(q)
    await dispatch_rig.runner._enter(dispatch_rig.ap, dispatch_rig.trade, SimpleNamespace(status="fired"), journal=False)
    assert dispatch_rig.submit.await_count == 0
    assert (dispatch_rig.trade.timing.get("firstSale") or {}).get("disposition") == "deferred_missing_evidence"


async def test_the_deferral_alarm_fires_from_the_real_runner_and_refuses_nothing(dispatch_rig, monkeypatch):
    await _enforce(dispatch_rig)
    raised = []
    monkeypatch.setattr(dispatch_rig.runner, "_admission_raise",
                        AsyncMock(side_effect=lambda ap, alarm: raised.append(alarm)))
    _underlier(dispatch_rig, venue_offset_ms=10_500)
    await dispatch_rig.runner._enter(dispatch_rig.ap, dispatch_rig.trade, SimpleNamespace(status="fired"), journal=False)
    _underlier(dispatch_rig, venue_offset_ms=10_500, symbol="AAPL")  # a second symbol, the SAME fault
    dispatch_rig.ap.symbol = "AAPL"
    dispatch_rig.trade.status = "fired"
    await dispatch_rig.runner._enter(dispatch_rig.ap, dispatch_rig.trade, SimpleNamespace(status="fired"), journal=False)
    await _settle()
    assert raised and raised[0]["kind"] == "systemic_admission_failure"
    assert raised[0]["count"] >= 2 and raised[0]["isGate"] is False
    assert dispatch_rig.submit.await_count == 0, "the alarm changes no decision"


async def _settle():
    import asyncio
    for _ in range(20):
        await asyncio.sleep(0.01)


async def test_the_bounded_retry_runs_the_whole_production_path_and_only_once(dispatch_rig, monkeypatch):
    """Deferred on a bad clock, then the clock is right: one more attempt, through every gate."""
    await _enforce(dispatch_rig)
    await dispatch_rig.engine.settings.set("techniques.enhanced_market.deferred_retry", "bounded")
    ap, trade, runner = dispatch_rig.ap, dispatch_rig.trade, dispatch_rig.runner
    _underlier(dispatch_rig, venue_offset_ms=10_500)
    await runner._enter(ap, trade, SimpleNamespace(status="fired"), journal=False)
    assert trade.status == "skipped" and dispatch_rig.submit.await_count == 0

    trade.fire_bar_index, ap.bar_index = 5, 7
    ap.trackers = {"b1": SimpleNamespace(status="fired")}
    monkeypatch.setattr(runner, "rules", lambda: SimpleNamespace(plan_entry_window_bars=3))
    _underlier(dispatch_rig, venue_offset_ms=-250)                   # the clock is repaired
    await runner._deferred_retry_pass(ap, None, journal=False)
    assert dispatch_rig.submit.await_count == 1, "the retry goes through _enter, so every gate ran again"

    trade.status, ap.bar_index = "skipped", 8                        # a second pass must find nothing left
    await runner._deferred_retry_pass(ap, None, journal=False)
    assert dispatch_rig.submit.await_count == 1, "one retry per trigger, ever"


async def test_with_the_policy_off_a_deferral_stays_terminal(dispatch_rig, monkeypatch):
    """The frozen behaviour of 2026-09-21, pinned so it cannot change by accident."""
    await _enforce(dispatch_rig)
    ap, trade, runner = dispatch_rig.ap, dispatch_rig.trade, dispatch_rig.runner
    _underlier(dispatch_rig, venue_offset_ms=10_500)
    await runner._enter(ap, trade, SimpleNamespace(status="fired"), journal=False)
    trade.fire_bar_index, ap.bar_index = 5, 6
    ap.trackers = {"b1": SimpleNamespace(status="fired")}
    monkeypatch.setattr(runner, "rules", lambda: SimpleNamespace(plan_entry_window_bars=3))
    _underlier(dispatch_rig, venue_offset_ms=-250)
    await runner._deferred_retry_pass(ap, None, journal=False)
    assert dispatch_rig.submit.await_count == 0, "default off: the attempt is consumed, as it was on 2026-09-21"
