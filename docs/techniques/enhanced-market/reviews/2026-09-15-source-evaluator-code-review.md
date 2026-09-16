# Source evaluator review at 4902b30

Reviewed commit: `4902b30033c53db88d277605694b6f5f2ae39141`.

Scope: `backend/zargar/tools/em_source_candidates.py` against the revised `source-continuation-v1` definition. These are research-measurement defects, not evidence of orders being submitted or baseline trading changing. The retrospective September 14 rows remain explicitly retrospective. No database, engine, runtime setting, or application process was changed in this review.

## SE-01: source availability does not constrain eligibility (P1 for forward evidence)

Locations: `backend/zargar/tools/em_source_candidates.py:49`, `:77`, `:183`.

`evaluate_candidate` starts at the opening-range boundary regardless of the row's `availableAt`. The outer evaluator merely copies availability into the finished result. A source first available at 10:00 therefore receives a 09:36 proxy entry and a 09:40 target result. This gives the forward ledger knowledge before the source was available. Missing availability is likewise not treated as missing evidence.

Reproduction: `test_source_cannot_enter_before_its_available_at_time` supplies only 09:30–09:40 bars and a 10:00 source availability. Expected: no entry and unknown because there are no available-source observations. Actual: `target`, entry 09:36, target 09:40, +4.14 underlying R.

Correction: enforce a parsed, timezone-aware availability bound before a candidate can confirm or enter; retain the declared bar-close timing. Missing or ambiguous availability must remain unknown for a forward/as-of result. Retrospective rows may retain their separate descriptive analysis but must not become forward evidence. Preserve the source identity and availability used by the result.

Acceptance: retain the regression unchanged; add missing-availability and availability-between-confirmation-and-entry cases. A result cannot claim a confirmation before its governing source is available.

## SE-02: missing bars are silently replaced with later observations (P2)

Locations: `backend/zargar/tools/em_source_candidates.py:52`, `:58`, `:89`, `:128`.

The opening range uses the first five stored rows rather than verifying all five 09:30–09:34 bars. The next-open proxy uses the next stored row rather than verifying the immediately following minute. The terminal walk also skips unknown intervals. These substitutions can turn incomplete evidence into a definite target result.

Reproductions:

- `test_missing_opening_range_minute_is_unknown_not_replaced_by_a_later_bar`: remove 09:32. Expected: unknown opening-range stop and no certified entry. Actual: 09:35 is silently included in the opening range, then the row reports target and +4.14 underlying R.
- `test_next_stored_bar_after_a_gap_is_not_the_next_minute_open`: retain 09:35 confirmation but remove 09:36–09:39. Expected: unknown next-minute proxy, no certified entry. Actual: the 09:40 open is labeled `next-open-proxy` and reaches target on that same bar.

Correction: validate exact session date, unique ordered timestamps, and complete opening-range coverage; require the immediately following minute for a next-open proxy. Keep a gap that could contain entry/stop/target/flatten as an unresolved interval instead of silently certifying the later path. Gaps outside relevant intervals need not invalidate everything.

Acceptance: retain both reproductions unchanged and add a missing minute between entry and later target that could have contained a close-below-stop. That path must remain unknown absent finer-grained evidence.

## Verification and handoff

Three pure reproductions were executed directly through the reviewed module in the isolated reviewer checkout. All three failed at the intended assertions with the results above. No pytest process or database was used by this subreview.

Tests: `docs/techniques/enhanced-market/reviews/measurement-regressions/test_source_evaluator_temporal_evidence.py`. Copy into `backend/tests/` and run against the corrected commit together with `tests/test_em_forward_measurement.py`. The seven supplied cases are narrow positive paths; they do not cover these temporal-evidence cases.

Separately, the tool currently reports an underlying geometry/path result and implements only R2, not the option NBBO, daily-budget, or final-dispatch checks listed in the definition. Keep those unmeasured gates explicit rather than interpreting a `target` outcome as a fully admissible option trade. No request is made here to add order execution or activate any candidate.
