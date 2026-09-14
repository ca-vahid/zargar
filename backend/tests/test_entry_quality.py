"""FC-01: the pure final entry-quality predicate over the current quote (no DB, no engine)."""
from zargar.domain import Quote
from zargar.execution.entry_quality import judge_entry_quote

NOW = 1_800_000_000_000
C = {"symbol": "HOOD270618C00101000", "ask": 3.0, "bid": 2.95, "priced": "opra", "warnings": []}


def _q(bid, ask, *, source="opra", ts=NOW):
    return Quote(C["symbol"], bid=bid, ask=ask, last=(bid + ask) / 2, ts=ts, source=source, source_ts=ts)


def judge(q, contract=C, **kw):
    args = dict(max_spread_pct=10.0, max_age_s=90, refuse_wide=True, now_ms=NOW)
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


def test_stale_observation_is_refused_by_its_source_timestamp():
    why = judge(_q(2.95, 3.0, ts=NOW - 120_000))
    assert why and "120s old" in why
    assert judge(_q(2.95, 3.0, ts=NOW - 120_000), max_age_s=0) is None


def test_without_a_current_observation_the_captured_verdict_is_the_only_evidence():
    assert judge(None) is None
    flagged = {**C, "warnings": ["T5.4 wide spread 14.0% on the NBBO (bid 2.6 / ask 3.0)"]}
    assert "T5.4 wide spread" in judge(None, contract=flagged)
    assert judge(None, contract=flagged, refuse_wide=False) is None
    # a delayed chain row is the same evidence the pick was judged on, not a current book
    assert "T5.4 wide spread" in judge(_q(2.6, 3.0, source="chain"), contract=flagged)
    assert judge(_q(2.6, 3.0, source="chain")) is None


def test_shares_entries_carry_no_contract_and_are_not_judged():
    assert judge(_q(2.5, 3.0), contract=None) is None
