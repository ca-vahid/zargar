# Independent review of PR246 — changes requested

Reviewed exact commit **ff67f695826908be728e8beb0bde357c7ad1b3fc**, branch
claude/cartel-brief-0921, against base **7eb89303c1a377d3615fd763d5d9ef36eaf98bfb**.
Review checkout: C:/Cursor/zargar-codex/.cache/cartel-pr246. Reviewer branch:
codex/review-cartel-pr246. No production source was edited during review; this
branch adds only the acceptance probes and this report. Do not merge this reviewer
branch as a release: the probes intentionally fail until the implementation is fixed.

## Verdict

**Code: changes requested. Deployment: hold. Activation: hold.** The implementation
is substantive and the nominal tests reproduce important September21 facts, but
the combined release has compatibility, lifecycle and evidence defects. Keeping
new flags off does not neutralize the existing-policy validation and always-on
reporting regressions. Fix the consolidated items below, or split a corrected
F1-F3 release from the unfinished cadence package and reassess that exact head.

## Independently run verification

- PR focused packet: **66 passed** — contracts45, cadence13, attribution8.
- Production frontend build/release metadata: **passed**, v0.8.29.
- Independent boundary probes: **7 failed**, all reproducible assertions (not
  timeout flakes or test-environment failures).
- Exact base accepts the saved Live5m preparation dictionary and prints5;
  the PR rejects the same dictionary.
- The reported reduce-only exit test also fails on the exact base, asserting
  position quantity1 but observing0. This is not evidence of a PR regression.
  Its underlying fixture/time-of-day diagnosis remains separate from these findings.
- All database tests ran sequentially via scripts/test-codex.ps1 on
  zargar_test_codex. No shared runtime, settings, arms or deployment changed.
- This was focused verification, not an independent rerun of the entire reported
 142-test packet. Supplied green totals are not substituted for the probes below.

## Consolidated blockers

### R1 — P1: matched controls stop when the executing cadence acts

**Location:** observer.py:390 and425; cadence.py:read_control.

The new control read lives behind the existing armed/waiting entry-observation
guard. Once the5m plan signals, its phase is signalled (later submitting/held),
and subsequent bars are skipped before the15m control can read them. A synthetic
same-tape reproduction signals the executing5m plan at09:40; the valid15m control
would signal at09:45. The pure reader produces one control signal, but the actual
observer persists zero. This biases the comparison in favor of whichever cadence
acts first. Executing invalidation/retirement can censor the other cadence too.

**Required correction:** give matched controls their own session lifetime,
subscription, observation watermark and restart state. Executing signal/fill/
position state must not terminate the control's observation. Keep it non-ordering
and retain incomplete windows. Explicitly handle pause, disable, execution close,
restart and corrections without replaying old signals or reviving entry authority.
Test through the real listener/repository path, not only read_control().

Probe: test_matched_control_keeps_observing_after_executing_signal.

### R2 — P1: saved Live5m settings no longer validate

**Location:** automatic_plans.py:79-98.

The before-validator converts every unlabeled5m policy to breakout_5m_v1, then
the after-validator rejects that label outside Practice. The existing dictionary
`{'workspace':'live','entry':{'timeframe_minutes':5}}` is accepted by the exact
base and rejected by this PR. Missing new keys therefore does not universally
mean legacy behavior. Preparation status/scheduled code that reads such a saved
policy can now fail before an operator can edit it.

**Required correction:** distinguish an existing unlabeled timeframe from an
explicit opt-in to the new experiment. Preserve saved-policy compatibility for
both snake_case/camelCase forms, including Live. The explicitly selected new
Practice-only experiment must remain rejected for Live. Do not change old arms
or retrofit experimental control policies onto them as a migration shortcut.

Probe: test_existing_live_5m_policy_is_not_reinterpreted_as_new_experiment.

### R3 — P1: long-only pilot silently affects executable short plans

**Location:** automatic_plans.py:199-202; preparation.py:regime/direction selection.

The handback says bearish plans are research-only and never arm. That is not what
the current preparation path does: a short market regime is an actionable direction
and automatic_review copies the5m policy directly to its executable short plan.
The independent short-candidate probe returns an ordinary PlanInput carrying5m
and breakout_5m_v1. There is no long-side pilot gate. The brief explicitly kept
bearish behavior separate.

**Required correction:** scope the new cadence to long Practice plans. Preserve
the existing bearish behavior/version, or explicitly refuse unsupported pilot
activation without changing old behavior. Do not relabel legitimate primary-short
sessions as research proxies. Exercise a real short-regime preparation through
arming in the acceptance packet, including both policy states.

Probe: test_long_only_cadence_pilot_does_not_change_short_execution.

### R4 — P2: expiry and chain requests escape the signal deadline

**Location:** contracts.py:400-406 and final selection return.

Only reprice requests use remaining-time wait_for. provider.expirations() and
provider.chain() are unbounded and are called before the deadline checks. In the
probe, expiry discovery advances beyond the signal deadline, yet another chain
request is issued. With an empty chain the routine can also label the search
complete instead of reporting expired/incomplete work. Outer timeout protection
in some callers does not satisfy the selector's per-request/deadline contract;
this is not a claim that the final order guard permits a late trade.

**Required correction:** bound discovery, every chain request and refresh by the
same remaining deadline and per-call ceiling, check before each request, propagate
cancellation, and recheck the deadline before returning a selected result. Never
extend it. Retain a truthful incomplete/deadline status. Test stalled expiry and
chain calls, an already-expired request, and a result arriving after its deadline.

Probe: test_expiration_discovery_consuming_deadline_prevents_further_requests.

### R5 — P2: incomplete candles are reported as completed closes

**Location:** review_attribution.py:62-74.

price_touch() takes the last *available* minute in a bucket and calls it a completed
5m/15m close merely because wall-clock time has passed the bucket boundary. The
probe contains one minute of a5m bucket; four minutes are missing. The report still
adds the boundary to closedBucketsBeyond. Conversely a missing actual close can
produce an unjustified wick-only/no-confirmation conclusion. This affects the
new explanation even when another field retains an incomplete-window warning.

**Required correction:** require complete trusted price/non-emission evidence for
the relevant bucket and its publication/availability cutoff. Unknown close means
unknown, not wick-only or completed. Reuse the canonical aggregation semantics
and eligible interval proofs; do not manufacture a price for a non-emitted bucket.
Cover missing last/middle minutes, sampled bars, verified intervals, early closes
and repaired evidence arriving after the decision.

Probe: test_incomplete_bucket_cannot_be_reported_as_completed_close.

### R6 — P2: partial-fill reporting uses a schema the caller never supplies

**Location:** review_attribution.py:120-130; session_review.py/review_ledger.py boundary.

actual_outcome() expects assets[].filledQty, but summarize_fills() does not return
that field. The normal arm/entry signal also does not supply requestedQty in the
shape used by the new unit test. Using a real summarize_fills result for a2-of-3
fill reports held rather than partially_filled even when requestedQty is provided.
The supplied attribution test invents the missing field, so it does not test the
production boundary.

**Required correction:** derive submitted/requested quantity, cumulative entry
fills and current order disposition from actual order/execution records at cutoff.
Do not use remaining holdings as cumulative filled quantity: partial exits change
holdings. Test actual ledger/report integration for partial entry, partial exit,
cancellation of remainder, carried lots and restart, without synthetic fields
that the production producer omits.

Probe: test_partial_fill_classification_consumes_the_real_ledger_shape.

### R7 — P2: later decisions are asserted to be independent counterfactual vetoes

**Location:** review_attribution.py:165-172.

Every later blocker receives remainsIfFirstRemoved=true. A later entry-invalidated
observation is not proof it would still block a trade if an earlier volume veto
were removed: the plan could already have entered, changing the lifecycle. The
probe reproduces this false causal claim. Chronological later observations are
facts, but independence from an earlier changed decision is not established.

**Required correction:** assert independent blockers only when justified by the
same decision/window and unchanged inputs. Label later-window/stage independence
unknown unless an explicit causal replay establishes it; keep later observations
visible without counterfactual certainty. Preserve ULTA's two genuinely independent
same-window volume/target blockers.

Probe: test_later_refusal_is_not_proved_independent_of_first_entry_refusal.

## Scope still open, separate from newly found defects

- The single required end-to-end fixture is still missing. Add the real
  preparation -> confirmation -> diverse search -> preflight -> sim order ->
  partial fills/exits -> restart -> session report path. R1 and R6 demonstrate why
  separate pure tests do not cover this contract.
- Before F4 activation, resolve the acknowledged non-15m research-panel exclusion
  or explicitly replace those measures with complete equivalent evidence. Merely
  executing5m while losing the comparison is not acceptance.
- Investigate the acknowledged underlying-quote timestamp/observation mismatch
  with receipt-time evidence. Do not solve it by allowing genuinely future quotes.
  No claim was made here that this PR caused that pre-existing issue.
- The volume grid and historical cross-session comparisons were not run. Keep
  the grid off; do not imply a calibrated volume change. Run the brief's finite
  comparisons with fixed inputs, costs and disclosed missing evidence.
- The proposed mandatory one-session wait before cadence activation was not in
  the revised completion requirement. Staging can be sensible, but future-session
  evidence must not become a new hard prerequisite for delivering reviewed code.
- F5-F8 and shares integration remain outside this first package; do not label the
  entire comprehensive brief finished when only F1-F4 are delivered.

## Reproduction and next handback

Acceptance probes are in backend/tests/test_pr246_review_boundaries.py. They are
review artifacts to retain/adapt into regressions, not production code patches.

```powershell
./scripts/test-codex.ps1 tests/test_options_cartel_contracts.py tests/test_cartel_cadence.py tests/test_cartel_review_attribution.py -q
./scripts/test-codex.ps1 tests/test_pr246_review_boundaries.py -q --tb=short
```

Return one corrected commit with each R1-R7 mapped to the fix and retained test,
the end-to-end fixture, exact focused results, and separate code/deployment/
activation verdicts. Preserve the current runtime/book/arms/settings. No deployment,
activation or request to relax data/risk rules follows from this review.
