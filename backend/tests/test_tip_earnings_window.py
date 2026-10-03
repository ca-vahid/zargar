"""W4.4 + W1.7 (2026-10-03): the earnings exit by report time, and no entry the exit would immediately undo."""
import datetime as dt
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from zargar.execution.policies import earnings_exit_at, earnings_exit_due

ET = ZoneInfo("America/New_York")


def t(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


def test_bmo_flattens_the_session_before_and_amc_the_report_day():
    # Monday 2026-10-05 BMO -> Friday 10-02 15:45 (the old whole-day rule held Friday longs through it)
    assert earnings_exit_at("2026-10-05", "BMO") == t(2026, 10, 2, 15, 45)
    assert earnings_exit_at("2026-10-05", "unknown") == t(2026, 10, 2, 15, 45), "unknown timing = before the open"
    assert earnings_exit_at("2026-10-08", "AMC") == t(2026, 10, 8, 15, 45)
    # the day after Thanksgiving closes at 13:00 - the cutoff moves inside the early close
    assert earnings_exit_at("2026-11-30", "BMO") == t(2026, 11, 27, 12, 45)


def test_due_window():
    assert earnings_exit_due(t(2026, 10, 2, 15, 44), "2026-10-05", "BMO") is None
    assert "flat by 10-02 15:45" in earnings_exit_due(t(2026, 10, 2, 15, 45), "2026-10-05", "BMO")
    assert earnings_exit_due(t(2026, 10, 5, 9, 31), "2026-10-05", "BMO"), "still holding on report morning: flatten now"
    assert earnings_exit_due(t(2026, 10, 8, 10, 0), "2026-10-08", "AMC") is None, "an AMC name trades the report day"
    assert earnings_exit_due(t(2026, 10, 8, 15, 50), "2026-10-08", "AMC")
    assert earnings_exit_due(t(2026, 10, 9, 10, 0), "2026-10-08", "AMC") is None, "after the report: nothing"
    assert earnings_exit_due(t(2026, 10, 8, 10, 0), None, "AMC") is None
    assert earnings_exit_due(t(2026, 10, 8, 10, 0), "garbage", "AMC") is None


def test_policy_uses_the_session_rule_and_keeps_the_legacy_days_rule():
    from zargar.domain import Bar
    from zargar.execution.policies import PolicyState as PositionState, PositionView, evaluate
    bar = Bar(symbol="X", tf="1m", ts=0, open=10, high=10, low=10, close=10, volume=1)
    st = PositionState()
    session = {"flatten_before": {"event": "earnings", "days": 1, "timing": "session"}}
    v = PositionView(direction="long", entry=10, risk=1, bar=bar, bars=[bar], days_to_event=0, event_due=None)
    assert not [d for d in evaluate(session, st, v)[0] if d.kind == "event"], "session rule ignores the day count"
    v.event_due = "earnings 2026-10-05 (BMO) - flat by 10-02 15:45 ET"
    assert [d.kind for d in evaluate(session, st, v)[0]] == ["event"]
    legacy = {"flatten_before": {"event": "earnings", "days": 1}}
    v2 = PositionView(direction="long", entry=10, risk=1, bar=bar, bars=[bar], days_to_event=1)
    assert [d.kind for d in evaluate(legacy, st, v2)[0]] == ["event"]


async def test_entry_inside_the_window_is_refused(monkeypatch):
    from zargar.approvals.proposals import ProposalService

    class Cal:
        def __init__(self, nxt): self.nxt = nxt
        async def next_earnings(self, sym): return self.nxt

    class S(dict):
        def get(self, k, d=None): return super().get(k, d)

    now = t(2026, 10, 2, 15, 50)

    class FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now
    import zargar.approvals.proposals as P
    monkeypatch.setattr(P.dt, "datetime", FakeDT)
    svc = ProposalService(NS(calendar=Cal(("2026-10-05", "BMO")), settings=S()))
    ctx, why = await svc._earnings_context("ORCL")
    assert ctx["timing"] == "BMO" and "earnings window" in why
    svc2 = ProposalService(NS(calendar=Cal(("2026-10-20", "AMC")), settings=S()))
    ctx2, why2 = await svc2._earnings_context("ORCL")
    assert why2 is None and ctx2["date"] == "2026-10-20", "a report weeks away only labels the card"
    svc3 = ProposalService(NS(calendar=Cal(("2026-10-05", "BMO")),
                              settings=S({"techniques.tip.earnings_entry_block": False})))
    assert (await svc3._earnings_context("ORCL"))[1] is None
