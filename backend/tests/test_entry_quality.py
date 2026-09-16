"""FC-01 / FC-02: the pure final entry-quality predicate over the current quote (no DB, no engine)."""
from zargar.domain import Quote
from zargar.execution.entry_quality import judge_entry_quote

NOW = 1_800_000_000_000
C = {"symbol": "HOOD270618C00101000", "ask": 3.0, "bid": 2.95, "priced": "opra", "warnings": []}


def _q(bid, ask, *, source="opra", ts=NOW, source_ts=None):
    return Quote(C["symbol"], bid=bid, ask=ask, last=(bid + ask) / 2, ts=ts, source=source,
                 source_ts=(ts if source_ts is None else source_ts))


def judge(q, contract=C, **kw):
    args = dict(max_spread_pct=10.0, max_age_s=10, refuse_wide=True, now_ms=NOW, require_current=True)
    args.update(kw)
    return judge_entry_quote(contract, q, **args)


def test_narrow_current_book_is_allowed():
    assert judge(_q(2.95, 3.0)) is None


def test_widened_current_book_is_refused_even_when_the_captured_contract_had_no_warning():
    why = judge(_q(2.5, 3.0))
    assert why and "T5.4 wide spread" in why and "18.2%" in why


def test_wide_book_is_only_a_warning_when_the_arm_does_not_skip_wide_spreads():
    assert judge(_q(2.5, 3.0), refuse_wide=False) is None


def test_one_sided_or_crossed_book_is_not_executable_evidence():
    assert "not two-sided" in judge(_q(0.0, 3.0))
    assert "not two-sided" in judge(_q(3.1, 3.0))


def test_missing_current_quote_is_refused_whatever_the_captured_warnings_said():
    assert "no current quote" in judge(None)
    assert "no current quote" in judge(None, require_current=False)


def test_delayed_chain_row_is_refused_when_a_real_time_source_is_expected():
    why = judge(_q(2.95, 3.0, source="chain", source_ts=NOW - 900_000))
    assert why and "delayed chain" in why and "900s" in why
    # with no real-time source configured the chain IS the book: judged by receipt age and spread, as RiskGate does
    assert judge(_q(2.95, 3.0, source="chain", source_ts=NOW - 900_000), require_current=False) is None
    assert "T5.4 wide spread" in judge(_q(2.5, 3.0, source="chain", source_ts=NOW - 900_000), require_current=False)


def test_entry_freshness_is_the_entry_policy_by_source_timestamp():
    assert judge(_q(2.95, 3.0, ts=NOW, source_ts=NOW - 12_000)) and "12s old (entry limit 10s)" in judge(_q(2.95, 3.0, ts=NOW, source_ts=NOW - 12_000))
    assert judge(_q(2.95, 3.0, ts=NOW - 12_000, source_ts=NOW - 12_000), max_age_s=0) is None
    assert "no timestamp" in judge(_q(2.95, 3.0, ts=0, source_ts=0))


def test_shares_entries_carry_no_contract_and_are_not_judged():
    assert judge(_q(2.5, 3.0), contract=None) is None
    assert judge(None, contract=None) is None
