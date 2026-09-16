# EM forward measurement review at 4902b30

**The SP prose corrections are substantially addressed. Do not deploy the new measurement code enabled as-is.** The existing v0.7.83/b7d8a57 baseline and its worker-release acceptance remain intact. Baseline preparation should continue; no second batch or restart is requested.

Reviewed commit: `4902b30033c53db88d277605694b6f5f2ae39141`. Isolated checkout: `C:/Cursor/zargar-codex/.cache/em-measurement-review`, detached. Primary folder/branch remain `C:/Cursor/zargar-codex`, `codex/zargar-development`.

Independent checks: the seven supplied tests pass (0.35s). Eight new focused regressions fail at intended assertions (0.15s): five observer cases plus three source-timing cases. All are pure local tests, with no database use, engine startup, network or orders, run sequentially through `scripts/test-codex.ps1`. The reported wider 55-case group was not independently rerun.

## FM-01 — P1 release boundary: research logging can delay a protective exit

`backend/zargar/execution/planrunner.py:607-611` awaits `_shadow_target_pass` before evaluating protective exits; the observer awaits the journal write at line577. An exception is suppressed, but a slow or stalled write still blocks the quote-watch coroutine.

**Reproduction:** the underlying is at its target while the actual option bid breaches the premium stop. Hold the research journal write pending. The actual production `on_quote_watch()` cannot call `_exit` until that research write is released. Test: `test_research_journal_wait_cannot_delay_a_premium_stop`.

**Correction:** the experiment must not add awaited research I/O ahead of protective decisions or hold up later quote passes. Capture an immutable observation and hand it to bounded independent recording; record dropped/deferred evidence visibly without allowing the recorder to block production protection. Scope the opt-in to EM Practice. Current `execution.shadow_exit_observe=True` is global in the shared runner, so it also reaches other desks contrary to the declared EM-only cohort.

**Acceptance:** the supplied stalled-recorder case passes; recorder saturation/failure does not delay protection; other desks and non-EM-Practice books produce no experiment records unless separately opted in. Keep the experiment disabled or omit its runtime hook from a combined release until this boundary is corrected. No rollback of the already deployed baseline is needed.

## FM-02 — P1 measurement integrity: quantity and policy differ from production

`_full_exit_rung` uses current remaining quantity to decide whether an option was a one/two-contract position. Production `plan_exit` uses the originally filled quantity. A four-contract ladder with one contract left at TP3 is therefore mislabeled as small-position TP2. The observer also models all remaining quantity at a partial target: 100 HPQ-like shares at TP1 are modeled as 100 shares, although the production trim is 30.

**Reproductions:** `test_partial_ladder_does_not_become_small_original_position_policy` and `test_shadow_share_trim_matches_production_quantity_not_full_remaining`.

**Correction:** derive the proposed rung and its exit quantity from the actual production policy and original filled quantity, capped by current uncommitted remainder. Preserve separate original quantity, remaining quantity, proposed exit quantity and pending quantity. Shares/options and one/two/three-plus behavior must agree with production. This is an unchanged-exit-policy experiment, not a new whole-position liquidation rule.

Related diagnostic labeling: `_target_distance` calls a next ladder rung `fullExitRung` for larger positions, and labels stage=fill as `entryBasis=filled` while still using `tr.entry`, the underlying plan entry. `fillBasis` is an option premium for option trades. Record intended underlying geometry, observed underlying entry (if available), option premium, next trim and full-exit/runner policy separately; never mix their units or imply a filled underlying price that was not captured.

## FM-03 — P1 measurement integrity: unknown executable size becomes complete coverage

The observer treats a missing bid size as sufficient to cover the whole position. Test `test_unknown_bid_size_does_not_cover_the_whole_position` produces coveredQty=2 where depth is unknown. Missing size must remain unresolved; it must not turn into a demonstrated liquidation opportunity.

Require valid source provenance/timestamp, finite positive bid/ask, an uncrossed book, and explicit size semantics before marking a quantity covered. Validate option evidence independently of underlying evidence. Future-dated, stale, missing-time or invalid quotes stay unscorable. Stop precedence must include applicable production premium-stop decisions; checking only an underlying stop does not establish precedence when an option has simultaneously lost premium. Pending-exit and stop-first rows cannot be scored as additional free-to-sell quantity.

## FM-04 — P2 measurement completeness: first-hit logging is not a completed shadow trade

`_shadow_seen` is updated before durable append. A failed write then permanently consumes that rung in the process; `test_failed_shadow_write_does_not_permanently_consume_observation` reproduces this. The map is memory-only and keyed by run/trigger/rung rather than a specific actual trade instance, so it does not provide durable restart/refire identity.

The implementation records first target hits, with no implemented independent shadow remainder/terminal tracker found. It follows only open production positions and production rung state. If the alternative remainder differs, it cannot yet be followed to its own stop/target/flatten after the baseline changes or closes. This falls short of the proposal's explicit terminal-event claim.

**Correction:** use actual trade/entry identity plus experiment version and rung for idempotent persistence, retry failed writes without inventing later quote timing, and distinguish first unscorable observations from later resolvable evidence. Either complete the separate order-free shadow lifecycle or label this release as raw observation capture only, with P&L comparisons deferred to a separately defined reducer. Missing modeled quantity/terminal evidence remains unknown. The latency and slippage constants currently stored are metadata, not an applied fill simulation; describe them accordingly.

## FM-05 — P1 research validity: source time and missing bars are ignored

`backend/zargar/tools/em_source_candidates.py` stores `availableAt` but does not use it when determining eligibility. A source available at 10:00 can receive a 09:36 entry and 09:40 target. The opening range is the first five stored rows rather than verified 09:30–09:34 minutes; the next-open proxy uses the next stored row even across a four-minute hole.

Three supplied reproductions cover late source availability, a missing opening-range minute, and a missing next-entry minute. All fail. See the companion `2026-09-15-source-evaluator-code-review.md` for exact evidence.

**Correction:** combine source availability and opening-range completion before eligibility; validate exchange-session date/time, ordered unique minute identities, chosen provenance, and required continuity. Missing relevant observations are unknown, not replaced with later rows. Use a proper New York timezone for new sessions instead of a permanently fixed UTC-4 offset. Preserve data/version identity in the result.

The evaluator models underlying timing and R2, not the full option liquidity, budget and dispatch checks. Its `target` path is not a fully admitted option candidate. Publish separate path result and per-gate evaluated/passed/failed/unknown fields; do not describe every existing gate as evaluated merely because production gates remain unchanged.

## Preparation status and handoff

At the latest checked snapshot, 01:02 ET September 15, the runtime remained healthy v0.7.83/b7d8a57. Since the preparation start window, database records showed 31 completed and 15 running EM analyses, with zero EM arms yet; Team2/Tips retained eleven arms. Counts are a progress snapshot, not a completed batch receipt or proof that the claimed less-than-eight concurrency limit is effective. Do not start another review-and-arm batch. Let the team return the final count of reviewed/armed/refused/failed rows for September 15 in EM Practice.

Return a focused measurement-only correction for FM-01 through FM-05, retaining the attached reproductions and accurately narrowing any unfinished measurement scope. This is not another worker infrastructure review, and it does not hold up baseline preparation or the manually grounded source/trade review. Keep the next strategy comparison order-free and the new runtime observer disabled pending its protective-exit isolation fix.

Tests are in `reviews/measurement-regressions`. Copy the observer file into `backend/tests/test_codex_em_measurement_boundaries.py` and source file into `backend/tests/test_codex_source_evaluator_temporal_evidence.py` on the reviewed development tree. The observer cases import the team's `tests.test_em_forward_measurement` helpers. Run sequentially:

```powershell
./scripts/test-codex.ps1 tests/test_em_forward_measurement.py tests/test_codex_em_measurement_boundaries.py tests/test_codex_source_evaluator_temporal_evidence.py -q --tb=short
```

No production files or runtime data were modified by the reviewer. This document and the test packet are the only handoff; no message was sent to another team.
