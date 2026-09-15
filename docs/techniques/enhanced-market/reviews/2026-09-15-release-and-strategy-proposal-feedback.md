# EM deployed release and strategy proposal feedback

**Release verified; strategy proposal accepted as a research direction, with the corrections below before drawing comparative conclusions.** These are research-definition and reporting corrections, not reopened worker-release blockers. No strategy change, order, restart, repair or backfill was performed by the reviewer.

## Release and next-session readiness

Live health independently reports `ok`, version `0.7.83`, build `b7d8a574635aa0d6d2d6a4be0538dc06462c43e6`. Git ancestry includes reviewed `72607e9`. The on-disk deployment receipt records phase `verified`, completed `2026-09-15T04:29:04.5269596Z`, matching target/health build, restoration `ok`, and manifest `6A304C8F94AF5C33C98D416898960F920142D23067834BFD92F495EDDA83179C` for 21 files. Receipt metadata was inspected; the reviewer did not independently regenerate all artifact hashes.

The restart log records restoration by ID: armed 11/11, resting orders 23/23, managed positions 3/3, open trades and in-flight orders zero. The before-inventory file exists at `C:/Cursor/zargar/logs/restart-inventory-20260914-212757.json`. Health and current database agree on eleven armed plans. They remain **three Team2 and eight Tips, zero EM**, all active arm rows dated September 15. This confirms restoration, not completion of EM's next-session preparation.

The completed EM sheet `69cbf3b2d01c49249a19f813c38a6c6a` is for September 15 and was built from September 14. The user can now run the normal baseline review-and-arm process for EM Practice using that sheet. A successful release does not itself create those EM arms. The new continuation/exit research candidates must not be activated by that action. Previous AMD sheet-build error remains a separate row issue.

The team's 78/38 suite figures and known fixture failure are their reported checks on the final tree; no additional broad suite was rerun for this release-evidence/proposal review.

## SP-01: remove future information from the MSFT alternatives

Source reviewed: `STRATEGY-PROPOSAL-2026-09-14.md` at deployed commit `b7d8a57`, under `docs/techniques/enhanced-market/reviews`.

The main 09:49 completed-close candidate can use the low of the first five completed minutes. Its approximately 1.09R geometry supports the stated result: this chosen candidate fails the existing 3R gate, despite subsequently reaching the price target. It does not establish that every possible source-faithful interpretation fails.

However, the table's **09:31 first-touch alternative cannot use a stop derived from all five opening minutes**. That range is not complete until 09:35. Withdraw its +2.46R as an actionable as-of comparison; mark the stop unavailable or define a separately frozen stop known by 09:31. Remove the resulting claim that every entry definition reaches the target with that structural stop. Also distinguish a next-minute-open proxy from a genuine immediate first-touch entry.

Before the new cohort, specify:

- Earliest eligible observation only after all required opening-range data are available; define how earlier crosses are handled without hindsight.
- No-chase at the executable entry price, not merely the confirming close. Explicitly define the retest state, cancellation/expiry, and which risk/entry limits remain applicable.
- Correct the claim “15:45 like every EM plan.” The inspected actual EM configurations use `flattenMinutesBeforeClose=5`, i.e. a 15:55 trigger with the observed bar/submission delay (MSFT filled at 15:56). Keep that baseline clock or label 15:45 as a separate chosen candidate change.
- Call the September 14 table a retrospective case study. The definition can be frozen prospectively for new sessions; it was not frozen before this session's outcome was inspected. Do not generalize “never use the level itself” from these three retrospective paths.

## SP-02: HPQ motivates a timing experiment, not a proven +$3 outcome

The arithmetic is correct under an explicit hypothetical: 30 shares filled at exactly 35.1462, plus the original remaining 70-share exit, would net approximately +$3.10. The minute high does not establish an executable bid, posted size, queue fill, or fill at that price. Apply the venue's price increment in an actual order model.

A resting limit at the target and a fresh-observation exit are different mechanisms. A roughly two-second watcher can miss a brief touch, or observe it after the executable bid has moved. Separate the hypothetical resting-order illustration from the proposed quote-observation candidate. Replace “one observed beneficiary/no observed loser” with “one observed target-to-fill delay; alternative execution result unverified.” HOOD/INTC's hypothetical option outcomes remain unknown, including their sign. The team summary's “changes nothing on the other four” is too strong.

First forward measurement should be **shadow only** alongside unchanged baseline execution. Record source and receipt timestamps for the triggering underlying observation, same-contract NBBO timestamp/bid/ask/size, remaining position and pending exits, modeled decision/submission delay, proposed tick-valid order and quantity, eventual baseline fill, and why a shadow fill is or is not supportable. A displayed bid alone does not prove an executable fill of arbitrary size. State the stale/missing quote and same-observation stop/target precedence rules before collection. No second order owner or duplicate exits.

## SP-03: make policy P consistent before judging it

As written, P replaces TP1 with the first opposing saved level at least 1R away. The table then silently retains HPQ's closer old TP1 when the replacement is farther away. Those are different policies. Either explicitly define P as **earlier-only**, retaining the baseline when no eligible nearer level exists, or recalculate its stated effects. Do the same for INTC. Specify feasible one-, two-, and three-plus-contract quantities and subsequent target/stop behavior.

HOOD September 14's structural level is touched in the same minute as the 09:35:21 entry. Minute OHLC does not establish that touch occurred after the position existed. A next-minute option print also cannot establish the executable result. Mark this ambiguous/unscorable unless finer evidence resolves it; “roughly neutral” is not a measured finding.

The absence of an intermediate saved level on September 10 establishes a limitation of this saved-level-only candidate. It does not show that every structural exit is impossible or that only fixed-R/premium-percentage exits could work. Preserve unknowns instead of treating them as zero effect. There is no need to activate P now, but the supplied comparison does not justify rejecting the entire structural-exit question.

## Target-distance work: diagnostic first

Record full-exit target distance for the actual quantity/exit policy as a diagnostic flag first. Do not introduce another live arm rejection while investigating sparse entries. Before choosing N from sweeps, specify metric, chronological calibration/held-out split, baseline/variant configuration and immutable data versions. Include all eligible setups, refusals, losses and missed winners. Underlying-only sweeps measure geometry; they do not prove option profitability or executable exit improvement. A chosen threshold needs untouched forward validation before activation.

## What to send back

Revise the proposal and its dated TRADING-RULES entry for SP-01 through SP-03. Return one explicit source-candidate definition and one shadow exit-observation definition, with unknown outcomes retained as unknown. No new worker PR is requested. Baseline EM review-and-arm can proceed now; any new strategy activation remains a separate decision after measurement.

Companion detail: `2026-09-14-exit-proposal-feedback.md`. Prior evidence: `2026-09-14-trading-results-and-missed-setups.md`, `2026-09-14-source-opportunity-reassessment.md`, and `2026-09-14-trade-exit-reassessment.md` in this folder. All reviewer files remain in `C:/Cursor/zargar-codex`, branch `codex/zargar-development`.
