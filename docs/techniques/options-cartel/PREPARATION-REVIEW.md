# Preparation coverage and feedback review — 0.7.5

The reported run finished, but its presentation overstated coverage and hid the
reason no trade could be armed. Read-only inspection confirmed the plan existed:
refreshing Saved plans made it appear. The saved inside-day geometry agreed with
the candles and passed the implemented gates. This is a code/process assessment,
not a profitability claim or independent validation of every method threshold.

## Findings and corrections

- The old 200-symbol default silently bounded detailed evaluation. Full-universe
  checking is now the default; the optional cap and final shortlist size are
  independent controls. A definite required industry failure is recorded early,
  avoiding a history download that cannot change that listing's eligibility.
- Discovery/industry requests did not publish intermediate progress. Paginated
  counts, operation text, current symbol, a provider-wait heartbeat, elapsed time
  and distinct coverage counters are now exposed. Completed duration stops at
  completion. Failed provider reads and blocked plans are separate from completed
  analysis; incomplete work is not reported as full coverage.
- The old evaluated count included data errors. Later-stage pattern failures
  could also render “Checks passed” because only listing gates were shown.
  Both screen `label` and structure `name` fields now supply failure reasons.
- The separate saved-plan list did not reload on preparation completion. It now
  refreshes when published plans or completion state changes. Manual plan controls
  prefer the prepared account instead of defaulting to the first shadow book.
- Contract selection inspected only the nearest three expiry dates. It now
  continues through permitted dates as needed and records first-failing-filter
  counts, inspected expiries, effective ask/debit limit and the lowest ask that
  passed the other filters. A current public-provider check supported the reported
  contract blockage; the historical run did not preserve enough rejected-chain
  detail to reproduce its precise historical rejection breakdown.
- Provider requests are paced/bounded, exhausted rate limits halt the batch,
  and completed daily history can be reused with its original observation time.
  Resume creates a linked record with the same frozen evidence; original failed
  records remain intact. Recovery includes analyses saved before the next progress
  checkpoint and retains IDs rather than whole histories in the candidate queue.
- Preparation journal events now include the required symbol field.

## Verification

The isolated live-data exercise checked all 3,087 supported listings: 3,029 were
ruled out by the existing industry gate, 58 received history analysis, and zero
data errors remained. SPCX and ZIM qualified; ZIM was 905th in discovery order,
outside the old cutoff. Both remained awaiting contracts under unchanged limits.
No orders were placed. Resume recovered two committed analyses after an
interruption, including one absent from the last progress row; the original
failed run was preserved and Saved plans refreshed automatically.

Regression coverage includes >200-stock evaluation despite a cap value of two,
explicit limited coverage, early industry rejection, rate-limit interruption,
history cache provenance, recovery across the analysis/progress commit boundary,
provider task cancellation, named structure failures, partial plan-data failures
and searching beyond three expiry dates. Browser tests exercise discovery and
evaluation progress, automatic saved-list refresh and the optional cap on desktop
and phone. Build/version checks and the existing mobile audit also apply.

The normal runtime was inspected read-only. All execution/collection testing
used the isolated Codex preview or disposable Codex test database. Practice and
Live settings, risk limits, entry gates and held-position protection are preserved.

Checks: 420 Cartel/platform regression tests passed. The subsequent reporting,
recovery and plan-error fixes passed focused suites (31 tests, then 17 final
preparation/coverage/contract tests). The production build, release consistency
check and Ruff passed. Desktop/phone progress tests verified resume and automatic
saved-plan refresh; Plans, Settings and expanded plan controls passed the five-
device mobile matrix. Existing Vite chunk/import warnings remain.
