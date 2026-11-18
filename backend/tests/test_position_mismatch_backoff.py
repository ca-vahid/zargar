"""2026-11-18: the quote brake stands down after an exit the order guard refused for an ACCOUNT TYPE MISMATCH (a paper
book while the gateway is logged into the live account) - and only for that reason."""
from types import SimpleNamespace

from zargar.execution.positions import PositionManager

NOW = 10_000_000_000


def _p(status, error, age_ms):
    return SimpleNamespace(exits=[{"status": status, "error": error, "ts": NOW - age_ms}])


def test_a_mismatch_refusal_stands_the_quote_brake_down_for_fifteen_minutes():
    msg = "account type mismatch: a 'paper' book cannot route to an IBKR live account"
    assert PositionManager._blocked_by_account_mismatch(_p("REJECTED", msg, 60_000), NOW)
    assert not PositionManager._blocked_by_account_mismatch(_p("REJECTED", msg, 16 * 60_000), NOW)


def test_any_other_refusal_or_no_exit_still_fires_the_brake():
    assert not PositionManager._blocked_by_account_mismatch(_p("REJECTED_RISK", "quote age 12s (max 10s)", 1000), NOW)
    assert not PositionManager._blocked_by_account_mismatch(_p("FILLED", None, 1000), NOW)
    assert not PositionManager._blocked_by_account_mismatch(SimpleNamespace(exits=[]), NOW)
