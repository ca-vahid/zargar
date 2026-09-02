"""The lotto lane + the knowledge-hygiene guards (daily review 2026-09-01)."""
import datetime as dt

import pytest

from zargar.domain import Bar
from zargar.execution.policies import PolicyState, PositionView, evaluate
from zargar.marketstructure.sessions import ET, session_bounds
from zargar.techniques.tip.lifecycle import policy_from_exit_plan
from zargar.techniques.tip.lotto import is_lotto, lotto_budget, past_flatten_time


class _S:
    def __init__(self, **kv):
        self.kv = {"techniques.tip.lotto_enabled": True, "techniques.tip.lotto_max_dte": 3,
                   "techniques.tip.lotto_budget": 1500.0, "techniques.tip.lotto_flatten_et": "15:45",
                   "execution.min_dte": 1, "techniques.tip.trailing_after_r": 1.0}
        self.kv.update(kv)

    def get(self, k, d=None):
        return self.kv.get(k, d)


class _Sig:
    def __init__(self, instrument, expiry, created=None):
        self.instrument = instrument
        self.expiry = expiry
        self.dte_hint_days = None
        self.created_at = created or dt.datetime.now(dt.timezone.utc)


def test_is_lotto_from_the_stated_contract():
    today = dt.date(2026, 9, 1)
    assert is_lotto(_Sig("call", "2026-09-04"), _S(), today)          # 3 DTE
    assert is_lotto(_Sig("put", "2026-09-01"), _S(), today)           # 0 DTE
    assert not is_lotto(_Sig("call", "2026-09-11"), _S(), today)      # 10 DTE
    assert not is_lotto(_Sig("shares", "2026-09-02"), _S(), today)    # not an option
    assert not is_lotto(_Sig("call", None), _S(), today)              # no stated expiry: never inferred
    assert not is_lotto(_Sig("call", "2026-09-02"), _S(**{"techniques.tip.lotto_enabled": False}), today)


def test_lotto_budget_and_flatten_time():
    assert lotto_budget(_S(), 5000.0) == 1500.0
    assert lotto_budget(_S(), 300.0) == 900.0            # never more than 3x the tip budget
    late = dt.datetime(2026, 9, 1, 15, 50, tzinfo=ET)
    early = dt.datetime(2026, 9, 1, 10, 0, tzinfo=ET)
    assert past_flatten_time(_S(), late) and not past_flatten_time(_S(), early)


def test_lotto_policy_holds_into_expiry_day_and_flattens():
    s = _S()
    plan = {"targets": [2.0], "fractions": [1.0], "maxHoldSessions": 2, "lotto": True}
    pol = policy_from_exit_plan(plan, is_option=True, settings=s)
    assert pol["dte_close"] == 0 and pol["expiry_day_flatten_et"] == "15:45"
    # a NON-lotto keeps the platform floor
    pol2 = policy_from_exit_plan({**plan, "lotto": False}, is_option=True, settings=s)
    assert pol2["dte_close"] == 1 and "expiry_day_flatten_et" not in pol2

    def view(minute: int, dte: int) -> PositionView:
        open_ms, _ = session_bounds("2026-09-01")
        ts = open_ms + minute * 60_000
        bar = Bar(symbol="X", tf="15m", ts=ts, open=1, high=1, low=1, close=1, volume=1)
        return PositionView(direction="long", entry=100.0, risk=1.0, bar=bar, bars=[bar],
                            net_mark=1.5, entry_mark=1.0, dte_min=dte, min_dte_floor=1)

    st = PolicyState()
    # 1 DTE lotto at 10:00 — held (the floor would have dumped it)
    d, _ = evaluate(pol, st, view(30, 1))
    assert not any(x.kind == "dte" for x in d)
    # expiry day 14:00 — still held
    d, _ = evaluate(pol, st, view(270, 0))
    assert not any(x.kind == "dte" for x in d)
    # expiry day, the bar closing 15:45 — flattened
    d, _ = evaluate(pol, st, view(374, 0))
    assert any(x.kind == "dte" and "expiry day" in x.reason for x in d)
    # the platform default still closes a 1-DTE contract at once
    d, _ = evaluate(pol2, PolicyState(), view(30, 1))
    assert any(x.kind == "dte" for x in d)


async def test_save_note_hygiene():
    from zargar.techniques.tip.analyst import _TAXONOMY_RE, _run_tool

    class _Svc:
        async def add_tip_note(self, scope, text, **kw):
            return {"scope": scope, "id": "n1"}

    class _Eng:
        signals_service = _Svc()

    ctx = {"ticker": "", "source": "src", "signal_id": "s", "run_id": "r"}
    r = await _run_tool(_Eng(), "save_note", {"scope": "ticker", "text": "x"}, ctx)
    assert not r["saved"] and "needs a ticker" in r["error"]
    ctx["ticker"] = "MU"
    r = await _run_tool(_Eng(), "save_note",
                        {"scope": "source", "text": "SEVENTEENTH message family: the pure exclamation"}, ctx)
    assert not r["saved"] and "not knowledge" in r["error"]
    assert _TAXONOMY_RE.search("tt message type #9 (12:29 ET)")
    assert not _TAXONOMY_RE.search("tt posts BTO as 'TICKER exp strike @ price'; trims say 'BANG'")
    ok1 = await _run_tool(_Eng(), "save_note", {"scope": "ticker", "text": "MU respects 950"}, ctx)
    ok2 = await _run_tool(_Eng(), "save_note", {"scope": "source", "text": "tt opens are structured"}, ctx)
    r3 = await _run_tool(_Eng(), "save_note", {"scope": "general", "text": "a third"}, ctx)
    assert ok1["saved"] and ok2["saved"] and not r3["saved"] and "budget" in r3["error"]
