# Cartel reliability and ignition release — 2026-09-12

## Implemented

- Cartel minute snapshots retain source classification without changing the shared six-value Bar serialization. Unknown legacy snapshots stay unknown. New automatic preparation requires verified exchange bars for confirmation and session-extreme stops; the execution controller independently checks those inputs. Recovery upgrades sampled context, resets the observation cutoff, and never replays a missed entry. Same-quality revisions are not silently preferred without a stronger revision identity.
- New durable research caches store provider-keyed histories separately from shared runtime bars. Daily series update incrementally with an overlapping revision check; baselines request 20 trading sessions and disclose actual usable samples. Partial baseline caches are retried after a short TTL, not certified complete.
- Preparation now has a short-transaction, renewable database ownership lease; expired owners cannot publish arms. Stop preparation is explicit and is not auto-resumed. Interrupted compatible jobs retry outside trading hours, with checkpoint counts visible. Stale benchmarks stop the executable scan early and enter bounded recovery.
- Native multi-symbol daily collection handles all pages, unexpected symbols and repeated tokens. It is **opt-in and off by default** because Alpaca provider-day bars are a different dataset from the existing daily source. Provider-day completion is required, and caches do not mix these sources. Access-denied errors fall back to the existing source with a separate cache; rate limits do not cause an unbounded retry storm.
- The persistent ignition research watchlist tracks event-day discovery and subsequent consolidation separately. The selectable `post_ignition_2026_09_11` Practice pilot uses its own short-consolidation detector rather than requiring the generic weekly-base checks. It is prohibited in Live. Existing profiles and plans remain available and unchanged; watchlist records themselves never arm orders.
- New Practice preparation defaults to the first hour plus 80% of pre-close baseline slots; Live defaults to full-session coverage. Explicit legacy coverage remains selectable for comparisons. Existing plans retain their saved policy. The new coverage gate is an engineering choice, not attributed to Sean.
- Capacity checks count armed, paused, working and held campaigns, using a database account lock plus a local guard. Valid current arms are preserved. Pending contracts do not occupy armed slots.
- Contract diagnostics include sampled rejected contracts with all failed filters and search completeness. Existing explicit refresh budgets remain hard limits. Whole-contract exit previews disclose zero-sized trims and match the existing cumulative-floor allocation policy; no fee, risk or exit thresholds are loosened.
- Read-only session review exposes as-observed decisions and source counts. Replay snapshots preserve source classification, and paired sweeps can compare stop modes while rebuilding timeframe-specific baselines with the same source-quality policy.

## Source interpretation

S30 is the September 11 video, https://www.youtube.com/watch?v=7xSMgmLoqM8. Full auto-generated transcript read and scanner/CRCL/SCCO frames checked. Discovery criteria: event-day price >5, change >5%, prior ten-session average volume >500K, ADR >2%, above EMA50. Engineering detector version v1 adds ignition volume >=3x prior 20-session mean; 2–15 consolidation sessions; range <=12%; price within 3% of a rising EMA8; consolidation mean volume below half the event volume. These remain labelled experimental; no automatic tuning or performance-based promotion is implemented.

The source describes entry as the level breaks on 5m/15m charts. This release preserves the platform's completed-bar gate. A new strategy profile is selectable, not silently selected. Catalyst identity remains unverified rather than inferred from a price move.

## Verification and deployment

Tests use only zargar_test_codex. The initial full Cartel pass was 473 passed / 7 failed; after fixing the constructor and updating intentional serialization/cache assertions (while preserving the refresh-budget boundary), the affected 92-test group passed. A further 54-test entry/readiness/workspace/shared-history group passed; final new boundary checks and deployment provenance are recorded at handoff. No full-platform success is implied by these counts.

Production build and four synthetic desktop/phone Practice/Live UI checks pass, including the ignition watchlist, profile controls and source-state messages. Native provider calls are covered with mocked pagination, not a claim of real account entitlement or throughput.

## Limits that need forward evidence

- Cold/warm/resume latency targets need real-provider measurement. Native batching is not enabled by this release.
- A sampled-source count and an exchange-source label are not a full broker revision ledger. Equal-quality corrections need stronger provider revision metadata before being preferred automatically; original decisions stay preserved.
- Full causal option-fill replay, statistically meaningful expectancy, and prospective pilot graduation require market data and future sessions. No profitability claim or automatic risk escalation is made.
- The user authorized deployment, but the release must be integrated with the desk's current committed changes and verified through its managed restart workflow. No second engine or generic Codex start/stop invocation is permitted.

## Final boundary additions

Automatic evidence expires at the intended first entry-session close rather than 24 wall-clock hours after preparation, so weekend plans can reach Monday. Resume requires the same completed-market session and target entry session. Pending candidates retain a terminal status after a verified closed-bar invalidation; a later rebound cannot revive them. A sampled predecessor cannot manufacture a crossing into a trusted confirmation bucket.

## Operating steps

After deployment verify backend and frontend release versions, then use Practice → Options Cartel → Settings. Verified-source history and automatic recovery are on; native provider-day batching is off. Keep the existing method profile for continuity, or explicitly select the post-ignition Practice pilot. Save changes before a fresh preparation. Old-schema interrupted runs require Prepare now; new-schema interrupted runs can resume. Monday preparation must include Friday's completed benchmark session.

Keep Live permissions and risk limits unchanged. Existing held positions remain under protective management throughout.
