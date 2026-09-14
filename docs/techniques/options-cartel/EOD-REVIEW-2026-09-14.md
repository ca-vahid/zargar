# Options Cartel — September 14, 2026 EOD review and development plan

Status: reviewed; development proposed, not implemented. All money below is USD in **Options Cartel Practice**, not the combined Practice dashboard. Times are Eastern unless stated otherwise.

## Outcome

**One completed option trade, net loss $61.13, book flat at $9,938.87.** That is a 0.6113% loss against its $10,000 starting balance. There is no remaining Cartel position requiring an EOD mark. Two filled orders represent one round trip, not two trades.

| Item | Verified result |
|---|---|
| Contract | APA October 16, 2026 $45 call (`APA261016C00045000`) |
| Entry | September 14, 09:45:02.717 — 1 contract at $3.30 |
| Entry debit / fee | $330.00 / $1.04 |
| Exit | 12:50:23.478 — 1 contract at $2.7095 |
| Exit credit / fee | $270.95 / $1.04 |
| Gross realized / total fees | −$59.05 / $2.08 |
| Net realized | **−$61.13** |
| Exit reason | Underlying protective stop at $45.56 |
| Final ownership state | Position quantity zero; managed position closed; arm disarmed/closed |

Identifiers: portfolio `0b48ed48de2f4030b49942b52858356d`; APA plan `e30a2db9c9aa72602410dfbce37a0d16`; managed position `cartel-3c3d11e51ef732751146ba2c50553ca9f599a4a2`.

The nominal 10% equity-risk ceiling did not mean 10% was invested. The $500 premium budget was tighter, and the executable quantity was one contract. Entry premium plus fee was $331.04, or 3.3104% of the original book. Do not raise either setting to compensate for this loss.

## What worked

- APA confirmed its planned level on a complete 15-minute exchange candle with the required relative volume. Preflight, risk checks, durable entry, adoption and protective exit all produced records. It did not buy from a quote tick or an old backfilled crossing.
- CGNX was invalidated at 09:45. Its first confirmation candle closed at $61.17, below the $62.54 reviewed invalidation; its high was below the $64.34 trigger. It correctly produced no order.
- NOV was invalidated at 11:15. Its 105 recorded/recovered exchange minutes had a maximum high of $21.065, below its $21.93 trigger. The final 15-minute close of $20.38 breached $20.48 invalidation. Two minute-history repairs did not hide an executable NOV crossing in this tape.
- APA remained managed across the morning deployment. No duplicate Cartel entry or exit was found. Its eventual stop closed the actual held quantity.
- Option observations were persisted. A recorder status showing zero after a later restart is not evidence that the day was unrecorded: APA has thousands of durable observations.
- The app was healthy on v0.7.72 at this review. Health is operational evidence, not a profitability verdict.

The SWKS/USO risk-refusal notices discussed earlier today belong to EM Practice. Their failures and the combined Practice header's P&L must not be counted as Cartel outcomes.

## What we missed, and what we cannot claim

### Preparation did not recover seven candidates

The 08:45 job returned `already_prepared` for Sunday's run `ccaa6c2cf40f47f8bfeb4939df08fdd3`. That snapshot had 3,068 discovered listings, 3,067 evaluated, 11 qualifying, three retained arms, OKTA pending, seven readiness failures and one daily-history error. There was no fresh Monday preparation run.

Reusing successful analysis is desirable. Treating a partial snapshot as finished without retrying its recoverable exclusions is the gap. The morning shortcut checks session, age, policy and benchmark errors, but not the unresolved candidate/history errors. Automatic recovery handles interrupted runs and benchmark waiting; pending activation handles `awaiting_contract`, not these seven baseline failures.

| Candidate | Supported entry windows out of 25 | Additional issue |
|---|---:|---|
| HOG | 17 | Below required broad coverage |
| NTRA | 12 | Below required broad coverage |
| OII | 2 | First four opening slots absent |
| PPC | 21 | First opening slot absent |
| SXC | 5 | First two opening slots absent |
| URBN | 16 | Below required broad coverage |
| VERA | 14 | Below required broad coverage |

The policy requires all four first-hour slots and at least 20 of 25 eligible pre-close entry windows. PPC has sufficient broad coverage but only four historical samples for the opening slot, below the required five. The complete baseline has 26 buckets; its final bucket is not a new-entry window. Their baseline cache records were not refreshed on Monday. This establishes missing recovery opportunity; it does **not** establish seven tradable or profitable missed entries. The coverage rule was correctly enforced on the available evidence.

FISV still had a missing November 12, 2025 regular-session daily bar. Nasdaq confirms FI changed listing/ticker to FISV on November 11 and instructs redistributors to retain its earlier history. The adjacent gap is an investigation lead, not a proven cause. Investigate symbol continuity and provider coverage; do not fabricate a candle, zero-fill a session or splice symbols without verified identity and adjustment conventions. [Nasdaq technical notice DTN2025-32](https://www.nasdaqtrader.com/TraderNews.aspx?id=DTN2025-32).

### OKTA confirmed on the underlying, but executable-contract evidence is missing

A bounded review of recovered exchange history found a 10:15 close above the saved trigger: previous close $178.865, confirmation close $182.32, volume about 3.79 times baseline, close location 0.933, target room about 1.39R and chase about 0.133R. These satisfy the saved numeric confirmation thresholds in that recovered tape.

This is retrospective signal evidence. We cannot prove the same complete inputs and an eligible option were available to the running engine at that moment. The pending watcher did run, but keeps the latest contract/readiness result rather than a durable per-attempt history. Its latest selection had no eligible contract and an otherwise eligible minimum ask of $9.55 against the $5 ceiling. That later observation cannot establish the quote at 10:15. No missed option profit is booked or estimated.

### APA did not have a demonstrated missed profit trim

During the actual holding interval, the highest recorded fresh OPRA bid was $3.35 — only $5 above entry in gross liquidation value for one contract, before fees. The highest observed underlying high was $46.59, below the saved first target near $50.00. This was a failed breakout followed by a stop, not evidence that the system ignored a reached first target.

APA retained its earlier plan and legacy exit allocation. New `whole_contracts_v2` settings did not rewrite it. Neither policy allows a literal 25% sale of one contract. Today therefore provides no outcome test of the new two-/three-contract ladder, and no evidence for changing EMA exits based on this one trade.

## Confirmed defects and planned corrections

Priorities: **P1** means correctness, availability or trustworthy measurement work before expanding the experiment; **P2** means reporting, efficiency or research quality. No confirmed current open-exposure emergency was found. Each item remains **planned**.

### C14-01 — P1: recover partial preparation without restarting the whole scan

Evidence: the 08:45 `already_prepared` result and the seven untouched baseline failures above. Code: `preparation.py`, scheduled shortcut around line 720, `automatic_recovery`, candidate error handling and pending activation.

Implement a durable recovery queue keyed by session, workspace, plan and policy/input identity. Keep successful research and immutable plans; distinguish retryable provider/coverage failures, deterministic exclusions, capacity waits and expired work. Retry the unresolved baseline/history subset on a bounded schedule with backoff. Show last attempt, next retry and the exact missing slots. A genuinely complete compatible snapshot may still be reused.

Acceptance:

- Sunday partial → Monday pre-open retries only failed candidates; already successful histories and arms are retained.
- A repaired baseline may proceed only with current contract/risk/capacity checks and causal current-session context. No historical crossing is executed, and earlier invalidation remains binding.
- Repeated failure is visible and bounded; cancellation/restart resumes the same queue without duplicate arms or concurrent workers.
- Workspace, changed policy, expired horizon and market-alignment changes invalidate inappropriate reuse. Missing opening data never passes merely because an arbitrary percentage is met.

### C14-02 — P1: repair the remaining managed-position identity path

Confirmed conditional code defect: `preparation.py:495` uses `held.run_id` when an open managed position exists without a matching active arm. `ManagedPositionRow` has no `run_id`; ownership is in `config.runId`. The separate capacity helper was corrected earlier, but this branch remained. It was not today's APA failure cause.

Use one validated ownership helper for capacity and the already-managed branch. Preserve an unlinked holding as capacity/exposure, with an explicit unresolved identity; never treat it as permission for another buy.

Acceptance: open managed holding with no active arm does not crash preparation, yields an accurate `already_managed` row, reserves capacity and cannot duplicate the symbol. Cover missing/malformed linkage and another technique/book. Retain the regression that directly exercises the real model shape.

### C14-03 — P1, shared execution: validate and record simulated fill evidence

Confirmed by an isolated pure reproduction: `SimExecutor.on_quote` fills a market sell on a 36.272-second-old OPRA quote and on a delayed 15-minute chain quote. The fresh control fills as expected. The shared quote consumer passes quotes into this executor without the missing quality checks.

This proves a simulator boundary defect. It does **not** prove APA used either bad quote. The $2.7095 fill matches a $2.71 bid less the configured 2bp slippage, but the actual fill quote identity is absent from the execution record. The later delayed chain bid was $2.95 and does not match the fill.

Define a versioned, feed-aware fill-evidence policy. Reject stale/delayed/future/crossed/untrusted market observations as sources of a claimed Practice fill; allow explicitly labelled synthetic-test feeds only under their own mode. Persist the exact quote source, source/receive timestamps, bid/ask/sizes, policy and slippage inputs with every simulated fill. Request fresh data and expose the pending state rather than silently fabricating completion.

This change governs **simulated fill claims**. It must not cancel protective orders, suppress risk-reducing dispatch to a real broker, or reuse entry liquidity thresholds to block exits.

Acceptance: preserve the currently failing stale/delayed regressions, add fresh/synthetic-mode/future/crossed/unknown cases, and verify pending stop/exit orders fill once a permissible fresh quote arrives. Partial fills, OCA, cancellation and restart stay idempotent. Run shared order/position checks sequentially against the isolated test DB before any rollout.

### C14-04 — P1, shared operations: serialize deployment ownership

The platform's dated session log records two desks attempting restarts around 11:45 and 11:50, with approximately two minutes of downtime. Its existing watchdog timestamp coordinates the watchdog, not two independent deployers. The guarded restart restored APA, but recovery after overlapping restarts should not be the normal coordination mechanism.

Add an atomic deployment lease/mutex with owner, intended commit/version, lifecycle and heartbeat. Claim it before mutating the runtime checkout, building/copying deployment assets, quiescing or restarting. Another desk queues or joins the release. Validate actual checkout and artifact identity again immediately before restart, then publish a receipt and release ownership after health and restoration checks.

Acceptance: two competing deployers yield exactly one runtime mutation/restart; crashed ownership expires safely; an unexpected target change fails visibly. Keep the existing in-flight/trade guards. Inventory must include Cartel arms and managed contracts, not only the shared PlanRunner inventory. No forced restart or generic process kill is introduced.

### C14-05 — P1/P2, shared data: measure delivery gaps and exit latency

NOV needed two one-minute repairs at 10:20:17 and 11:07:15. Both advanced the prospective observation cutoff; no NOV entry was lost in the recovered tape. The platform's independent EOD record also reports afternoon bar-delivery stalls despite complete stored SPY history. Persisted bars are not proof of timely delivery to a decision consumer.

Measure exchange timestamp → receive → aggregate → dispatch → consumer decision, with queue depth and event-loop lag. Distinguish source outage, sampling/recording gap and delivery delay. Record suppressed confirmation windows and recovery cutoffs in the EOD report. Measure stop breach, exit decision, submit, acceptance, usable quote and fill separately.

APA's exit intent was created around 12:50:03.541 and execution occurred at 12:50:23.478. This is about 20 seconds, not a measured 20-second broker defect: simulation waits on eligible quotes, and the decisive quote is not recorded. Instrumentation is needed to attribute it.

Acceptance: delayed dispatch with complete DB bars is reported as delivery lag; a real missing minute remains a data gap; recording gaps are not automatically called feed outages. Repairs remain prospective and cannot place delayed historical entries. Alert on a held position's stale monitoring/protection path without changing its exit policy.

### C14-06 — P2: make the EOD report reconcile the entire funnel and book

The current `/api/options-cartel/session-review` reports APA as `signalled` after it has closed, returns two filled orders without round-trip attribution, and lists only armed records. It omits the pending and readiness-blocked funnel and cannot answer the user's actual EOD question. APA's arm also retains `orderStatus=ACCEPTED`, `filledQty=0` and a null average fill beside its correct adoption/closed fields. Authoritative executions and holdings reconcile; the secondary projection is stale. OKTA still appears `awaiting_contract` after its entry session has ended.

Build an as-of session read model joining preparation candidates, readiness/selection attempts, arms, decisions, orders, executions and managed positions. Show separate counts for signals, entry orders, fills, trades, open positions, invalidations, risk refusals, data failures and pending contracts. Derive net realized P&L from executions and fees; label gross managed P&L separately. Use source-dated bid marks only for open long-option liquidation estimates, with missing/stale marks explicit.

Persist attempt history for pending/readiness decisions and the policy/code/contract cohort that actually executed. Distinguish inherited legacy arms from newly prepared v2 plans. Keep position accounting history readable after its book is archived or the technique default book changes.

Frontend acceptance: APA shows **closed, protective stop, −$61.13 net**, one trade/two fills and a consistent settled entry projection; NOV/CGNX show invalidation; OKTA shows expired entry permission plus the last pending-contract evidence with times; the seven baseline failures remain visible. Switching Practice/Live or the review date clears prior data and discards late responses for the old scope. Include carried positions from prior sessions and fees-only/partial-fill cases. Link each outcome to its full event/order/plan history.

### C14-07 — P2: honest quote coverage and performance statistics

The current recorder exposes last-process/last-batch counters. Restart can show zero or no last attempt even though historical samples exist. APA's holding interval has numerous gaps between fresh recorded observations; those are sampling/evidence gaps, not independently established feed outages.

Add durable per-session/per-contract coverage: unique source observations, fresh sample windows, gap duration, source distribution, restarts and last valid evidence. Keep plan/held-contract collection active through reconciliation and final fill. Capture order-decision/fill evidence directly rather than relying on a five-second sampler to happen to see it. Summaries should say when a counterfactual is unscorable.

Acceptance: reload/restart does not reset the historical daily coverage display; repeated cache reads are not new source observations; absent/delayed quotes create explicit gaps. A replay cannot substitute an earlier stale bid for a missing fill-time quote or quietly report a complete score.

### C14-08 — P2: source identity, docs and prospective method evaluation

Investigate FISV using dated exchange/provider identity evidence and adjustment-compatible history. Make the minimum missing baseline windows actionable, including verified no-trade semantics where the provider can establish them. The baseline cache identifies a shared fetch function, but that function can use more than one provider: retain the actual answering provider, feed, pagination/completion and adjustment identity rather than treating the wrapper name or `exchange` quality flag as sufficient provenance. Benchmark cold, warm and failed-subset recovery before raising concurrency; moving from six workers to fifty is not a substitute for repairing failed-subset scheduling.

Update `DELIVERY-STATUS`, `DAILY-PREPARATION`, `TRADING-RULES`, replay/quote documentation and release notes to match these boundaries. Correct the earlier implication that all held-position ownership paths and automatic recovery cases were covered. Keep author examples, observations, engineering choices and approved experiments distinct.

For method work, collect one frozen cohort prospectively. Report market/theme/leader evidence, actual ticket size, target room, bid/ask costs, max favorable/adverse excursion, rejection reasons and exact net outcomes. Retained legacy campaigns must not be counted as v2. Revisit the prior twenty-session collection checkpoint with this complete data, then compare one predefined challenger and a later untouched period. One losing trade does not identify a profitable parameter adjustment.

## Delivery sequence and completion gates

1. **Correctness PR:** C14-02 and C14-03, with failing regressions preserved, shared ownership review and documented simulator policy. Small independent commits; no risk-setting changes.
2. **Preparation PR:** C14-01 and its durable retry/attempt records. Prove partial-resume and restart behavior without touching the live runtime database in tests.
3. **Operations PR:** C14-04 and the C14-05 latency measurements, coordinated with the other desks. Do not duplicate parallel platform fixes; inspect current main before implementation.
4. **Review/UI PR:** C14-06 and C14-07, quantity/fee reconciliation and desktop/mobile Practice/Live verification.
5. **Research/docs follow-up:** C14-08; source-bound fixtures and prospective collection. No automated profitability or Live promotion claim.

For each release: rebase/integrate current main, choose a non-colliding version, update changelog/docs, run focused regressions and affected shared checks, build once for the final tree, then verify the artifact/health version and restored identity inventory. Database tests use `zargar_test_codex` sequentially. Do not deploy at the open or restart active work merely to fit a preferred time.

## Next session and limits of this review

- Current Cartel book is flat. The three Monday arms are terminal; they are not Tuesday trading instructions.
- Preparation remains enabled for 20:20 ET and 08:45 ET. A later run and its intended session, unresolved coverage, actual arms, contracts and cohort still need verification. Today's read-only review did not start preparation or arm orders.
- Leave Moderate alignment, the $500 budget, 10% ceiling and all execution protections unchanged while correcting measurement/recovery. Treat v2 as a fresh-plan experiment, not a reason to migrate historical results.
- No reliable new September 14 author result was verified from the dated search. Public posts or winning screenshots would not establish a comparable net account return. The preceding source review remains background, not today's benchmark.
- Checks here are live authenticated read-only API/SQL reconciliation, code-path review and an isolated pure simulator reproduction. No production mutation, engine launch, deployment, broad test-suite pass or profitability certification is claimed.

Audit checkout: `C:/Cursor/zargar-codex/.cache/cartel-eod-20260914`, detached `5188956a6ce253f0b4542dd3e45b252e398834f0`. Runtime checkout was `C:/Cursor/zargar`, branch `claude/zargar-stock-app-research-8mnqfh`, HEAD `b1da621fd326dcb69f04f1b0415fc1952e76370a`, healthy v0.7.72. The primary Codex checkout remains on `codex/zargar-development`; its unrelated work and all Claude worktrees were preserved.

Supporting audit artifacts in this checkout: `.cache/execution-findings.md`, `.cache/coverage-findings.md`, `.cache/economics-findings.md`, and `.cache/repro_sim_quote_evidence.py`. These contain bounded evidence and the intentionally failing pure simulator regression; they are not runtime database exports or broad passing-suite claims.
