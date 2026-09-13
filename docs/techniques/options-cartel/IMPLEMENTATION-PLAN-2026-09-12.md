# Cartel implementation plan: data integrity and post-ignition continuation

> Execution update, 2026-09-12: the user subsequently authorized implementation, commit, push and deployment while the other team was busy. The proposal text below is the original review baseline, not a continuing approval block. See RELIABILITY-RELEASE-2026-09-12.md for shipped scope and remaining validation.

**Revision 1 — 2026-09-12 — PROPOSED; independent team review required before implementation.**

This is the implementation companion to [the weekend evidence review](WEEKEND-REVIEW-2026-09-12.md). No code, settings, risk limits, arms or runtime processes were changed. Earlier auto-merge permission does not bypass the user's current review-before-implementation request. The baseline for the audit is origin/main c0eb5c3; rebase and re-audit any intervening shared changes before starting work. Do not reserve a release number until integration.

## 1. Outcome and scope

Build an observable, source-informed Cartel workflow that discovers ignition events, maintains developing setups across sessions, qualifies their data and contract expression, and only then arms a fresh execution plan. Repair existing data/recovery defects independently of strategy experiments. Do not optimize for five arms or daily purchases.

The existing engine remains responsible for closed-bar decisions, shared order/risk gates, write-ahead submission, position adoption, partial fills and protective exits. Keep those mechanics; revise inputs and strategy policies deliberately. Live stays separate and is not enabled or migrated by this plan.

## 2. Transcript recovered: new source findings

The full English auto-generated transcript of [Sean's September 11 video](https://www.youtube.com/watch?v=7xSMgmLoqM8) was exported and read from 0:00 through 20:18 (video duration 20:20). Local research copy: `.cache/options-cartel/2026-09-11-ignition-transcript.txt`; SHA-256 `be7edff3041525d909b4436aaa279b63e799e1b970a7d87bb1c382b5d0d4f55d`. Keep it local; publish paraphrased notes and timestamp links, not the full transcript.

Auto-caption errors include variants of “8 EMA” and ticker spellings. Visual spot checks covered the scanner near 14:13, CRCL's five-minute entry illustration near 17:34, and SCCO's still-developing daily setup near 19:11. This is full transcript coverage plus selected chart verification, not frame-by-frame verification of every example or verification of his profits.

| Time | Source-supported point | Design consequence |
|---|---|---|
| [1:55–3:50](https://www.youtube.com/watch?v=7xSMgmLoqM8&t=115s) | EMA8/21/50 describe trend; flat averages and an unestablished trend can mean chop. | Trend quality is more than simply being on one side of an EMA. |
| [4:37–5:09](https://www.youtube.com/watch?v=7xSMgmLoqM8&t=277s) | This setup particularly uses EMA8 catching up with price. | Measure post-move consolidation near EMA8 rather than treating every MA pullback alike. |
| [7:40–10:26](https://www.youtube.com/watch?v=7xSMgmLoqM8&t=460s) | An unusually strong volume event precedes quieter consolidation and renewed expansion. He cites roughly 3–5 times average for the initial event. | Separate **daily ignition volume**, **consolidation volume**, and **intraday confirmation volume**. A 3x ignition threshold does not mean 3x entry volume. |
| [9:14–9:59](https://www.youtube.com/watch?v=7xSMgmLoqM8&t=554s) | Avoid buying the initial move or rushing the next day; wait for the flag/pennant/wedge and subsequent break. | Discovery is not arming. Store a developing setup across sessions. |
| [10:28–13:39](https://www.youtube.com/watch?v=7xSMgmLoqM8&t=628s) | Earnings can cause ignition, but other catalysts can too. A few consolidation days can suffice; a five-week base is not mandatory. | Add a dedicated detector; do not require the generic long-base geometry to pass unchanged. Do not invent an earnings event from price action. |
| [13:58–15:16](https://www.youtube.com/watch?v=7xSMgmLoqM8&t=838s) | Scanner: price >5, change >5%, average volume >500K, ADR >2%, EMA50 below price; a separate PG/ignition watchlist. The frame shows average volume 10D. | Apply the ignition discovery screen to the **event day**, not repeatedly to quiet consolidation days. |
| [15:18–17:49](https://www.youtube.com/watch?v=7xSMgmLoqM8&t=918s) | Daily range/previous-day highs define the level; 5m/15m provides entry detail; example stop is low of day. | Preserve level provenance; use a causal session-low-at-entry interpretation. Entry-at-break versus a completed-bar entry remains a documented difference. |
| [17:49–19:40](https://www.youtube.com/watch?v=7xSMgmLoqM8&t=1069s) | Hold a working trade; overnight continuation is considered with profit cushion. A developing setup may not trigger tomorrow. | Separate thesis lifetime, entry-plan expiry and held-position lifecycle. No automatic daily liquidation or perpetual plan extension is inferred. |

The video does not establish a universal option DTE/strike/spread policy, a precise daily volume-average lookback for ignition, a 70% candle-close rule, a 1.5x same-time intraday median rule, or new partial-exit allocations. Its “2.5% risk” illustration describes underlying entry-to-stop distance, not portfolio risk or maximum option loss. Discussion of institutional buying is the author's interpretation of price/volume, not identified buyer data we can certify.

## 3. Architectural decisions proposed for review

### 3.1 Preserve data quality without breaking shared consumers

Prefer an additive Cartel candle-envelope/sidecar first, retaining the shared six-value `Bar.to_row()` compatibility until a platform-wide DTO migration is separately reviewed. A sidecar must travel with every live, history, restore and replay conversion; merely adding a DB column is insufficient.

Required fields: symbol identity; timeframe; session; open timestamp; OHLCV; provider/feed; source class (`exchange`, `sampled`, `sim`, `unknown`); observed-at; revision identifier; adjustment policy; quality state; underlying raw-data reference. Separate “venue-reported aggregate” from “trusted as final”: exchange bars can also be revised.

Define the quality comparison centrally: compatible identity/feed/adjustment first; then trusted provider priority and revision/observation ordering. No universal last-write-wins. Never combine incompatible adjusted and unadjusted histories. Missing observations remain missing. A verified no-trade interval is distinct from an outage, halt or unrequested page and requires a documented provider definition.

For new automatic entries, sampled/unknown data must not satisfy a gate claiming exchange-volume confirmation. Tests and deliberately synthetic research retain explicit sim provenance. Existing positions keep their protective management; do not require the new entry standard to reduce risk. Unknown legacy minute rows are preserved, not relabelled exchange.

### 3.2 Persist raw history, derivations and decisions separately

Proposed logical records (reuse compatible platform storage where possible):

| Record | Key / principal fields | Invariant |
|---|---|---|
| History observation | instrument, provider/feed, adjustment, timeframe, timestamp, revision | Observed versions are traceable; no silent cross-provider splice. |
| Session manifest | dataset identity, session, request bounds, pagination, quality counts, latest revision, content hash | Timestamp coverage and trusted coverage are separate. |
| Baseline manifest | symbol, timeframe, slot, sample sessions, sample quality, estimator/version, as-of | Only prior completed sessions; missing samples never silently become zero. |
| Ignition event | symbol, event session, direction, event data revision, detector version | Stable idempotent identity; event is not an order signal. |
| Setup/thesis | event id, stage, geometry, evidence, validity, source profile/version | Survives ordinary daily-plan expiry. |
| Preparation job | workspace, portfolio, logical job id, snapshot id, stage, cursor, policy hash, lease | One owner; restart preserves committed work. |
| Decision evidence | plan id, decision time, snapshot hashes, gate measurements, decision, superseding correction reference | As-observed decision remains immutable. |

Do not create a second authoritative position or order ledger. `TechniqueRun`, `TechniqueArmed`, shared orders and managed positions retain ownership of those records.

### 3.3 Explicit setup lifecycle

`discovered → ignition_verified → consolidating → setup_ready → execution_ready → armed → triggered/invalidated/expired`.

The watchlist/thesis and its executable child plan have separate terminal states: an expired daily plan does not delete a still-valid thesis. Every new executable child rechecks current market permission, data, contract, cash/risk, and observed time. A source revision can invalidate or request review of an unfilled thesis; it cannot erase an executed trade or replay an entry missed during downtime.

Maintain a separate `research_only` lane. Later market alignment cannot mutate an old research record into an armed plan. Create a new evaluated snapshot instead. Held positions are managed independently from whether their original thesis is still on the watchlist.

## 4. Work packages, dependencies and concrete completion criteria

### W0 — evidence freeze and review fixtures

Before behavior changes, record code/version provenance, Friday run IDs, quality counts and as-observed decisions from the weekend review. Create sanitized synthetic fixtures reproducing the failures, with no credentials or copied runtime DB. Capture the video examples as timestamped annotations and label uncertain dates/tickers explicitly. Use a corrected-data offline comparison only when the data's source and availability are known.

Deliverable: baseline report and fixtures covering CENX's rejected bar, LFTO's low historical coverage, a stale Monday benchmark, a restart after 2,554 saved analyses, and a pending contract with a later eligible reserve. No profitability claims from these fixtures.

### W1 — candle provenance and source-aware recovery (P0)

Files: `observer.py`, `preparation_readiness.py`, `observation_health.py`, `entry.py`, `state.py`, shared data conversion boundaries as approved.

Implement source-aware merge, durable revisions and per-decision references. Recover both absent timestamps **and inferior sampled/unknown observations**. Preserve original decisions while applying corrections to future context. Persist source-specific coverage diagnostics and stale/missing reasons. On restore, old state cannot overwrite superior recovered evidence just because its timestamp is present.

Acceptance: round-trip envelope survival; sampled-to-exchange upgrade; exchange-to-sampled downgrade refusal; delayed correction after invalidation; duplicate/cancel/restart with consumed signal; held-position exits under degraded entry data. No synthetic or unknown bar is silently promoted to real data. Signal identifiers and order idempotency remain stable.

### W2 — incremental history, trustworthy baselines and benchmark barrier (P1; after W1)

Fetch only missing/revisable ranges after a validated seed. Persist daily sessions beyond a 12-hour analysis-cache window. Normalize source-specific daily timestamps at the provider boundary; enforce calendar close, corporate actions, identities and adjustment consistency. A current observation time cannot certify a stale final session.

Build baselines from a configurable **trading-session** window (initial proposal 20 sessions, at least five valid samples per slot). This is an engineering estimator, not a newly attributed author rule. If source retention cannot supply the window, report the actual sample set. Provider-native intraday aggregates need equivalence checks before substituting them.

Benchmark phase: resolve expected session → inspect manifest → incrementally fetch/refresh → validate → either publish a new market snapshot or enter bounded `waiting_for_benchmark` recovery. Repeated stale replies use backoff and never trigger an endless full-market scan. Monday requires Friday's completed session even when the job runs on Saturday/Sunday.

Acceptance: holidays/half-days/DST; partial pages/repeated tokens; stale/future daily timestamps; conflicting revisions; ticker-change gaps; missing/no-trade distinction; timeout and retry exhaustion. A same-snapshot warm run makes no history requests; a fresh day requests deltas and reuses older valid sessions.

### W3 — durable jobs and actual batch collection (P1; after W2)

Maintain separate snapshot identity and logical-job identity, with stage cursors and durable result references. A lease prevents duplicate workers. Reconstruct counters from committed children after a crash; do not replay all analyses just to rebuild progress if a valid aggregate/ranking checkpoint exists.

Resume only same-scope, same-policy, compatible-schema, unexpired work. Record explicit cancellation/disable separately from interruption. Automatic resume, if approved, cannot restart a deliberately cancelled job. If the expected session changes, keep raw cache but rebuild derived evidence. Process CPU-heavy analysis off the shared event loop where profiling justifies it; never fork an engine or inherit runtime integrations into workers.

Use provider-capability-aware multi-symbol requests, not just 25 parallel single-symbol calls. [Alpaca documents symbol-sorted results and cross-symbol pagination](https://docs.alpaca.markets/us/reference/stockbars); fully traverse pages before claiming a batch complete. Entitlements, rate budgets, per-feed limits and backoff remain mandatory. Fix the provider request model before raising concurrency.

Acceptance: identical sequential/batch outputs and hashes; no starvation of later symbols on pagination; partial batch recovery; one active job across simultaneous resume requests; no duplicated plans/arms after commit-before-checkpoint crash; measured event-loop lag and memory ceiling.

Performance targets to validate: repeated same-snapshot work <60s; saved-analysis recovery <30s; at least 50% lower cold-run elapsed time versus the same baseline universe when the provider permits. Publish cold/warm/resume p50/p95 and request/CPU/DB costs. Missing a speed target must not relax correctness or rate limits.

### W4 — post-ignition discovery and persistent watchlist (new method profile; after W2)

Add `post_ignition_2026_09_11` as a separate profile. Retain existing profiles and immutable plans. Initial release is long-side research only; the video's generic bearish discussion does not justify silently mirroring every numerical threshold into live puts.

Discovery uses event-session inputs: price >5; daily change >5%; 10-session average volume >500K; ADR >2%; price above EMA50. Review strict boundary handling and ADR formula/lookback. Initial daily volume anomaly proposal: volume >=3 times the prior 20-session mean, excluding the event bar. The 20-session denominator, equality boundary and anomaly lookback are explicit engineering choices for labelled calibration; the author gives illustrative 3–5x, not that exact formula. Gap size is recorded and scored, not treated as universally mandatory without further evidence.

Store event reason/catalyst with timestamped provenance when available. Unknown catalyst stays unknown; price/volume can identify an ignition-like event but cannot establish which institutions traded it. Avoid a mandatory earnings-only gate. Detect event-day newness and deduplicate successive scans by event identity/version. Keep quiet developing names even when they no longer satisfy daily +5% change.

Acceptance: a valid event becomes a watchlist item but cannot buy the event day; a later flat/quiet session remains tracked; an old event outside retention cannot reappear as new; earnings data published later cannot enter an earlier snapshot; ambiguous symbols/corporate actions quarantine instead of creating duplicate theses.

### W5 — post-ignition continuation detector (after W4)

Detect the **sequence**, not merely a pattern label: prior trend/impulse → verified ignition → contracting price/volume near a rising EMA8 (EMA21 context) → defined breakout level. Separate setup-specific checks from generic weekly context so a few-day flag is not rejected solely because it lacks a five-week base.

Candidate engineering search window: 2–15 completed post-event sessions. Require at least two completed consolidation sessions before the next-session executable plan, reflecting the instruction not to rush the event or next day. Retention, contraction ratios, EMA-distance bands and slope definitions require a small labelled calibration set, not optimization on Friday's five names. Measure high-volume adverse selling relative to the event and baseline; do not infer “institutions did not sell” as fact.

Store range-high/previous-day-high level alternatives with exact anchor bars. Select one deterministic rule per profile. Recompute a new plan when anchors materially change; no drift of a running plan's trigger. A setup that has not broken out remains a developing thesis; an invalidated setup does not automatically re-arm after a rebound.

Acceptance: young healthy flag passes its own geometry despite failing the old generic base duration; flat/choppy base without ignition does not; adverse high-volume distribution fails; all anchor bars predate the decision; equivalent repeated snapshots produce identical levels; no future-bar or hindsight selection of the nicest flag.

### W6 — executable readiness, contract search and capacity (after W1/W2; alongside W4/W5)

Expose independent `data`, `market`, `setup`, `contract`, `risk` and `arm` readiness. Keep the ranked pool, pending reserves and actual arms distinct. Complete first-window data recovery before comparing coverage quality. Proposed first shadow policy: first four 15m slots supported and >=20/25 pre-close slots, or complete coverage of an explicitly narrower schedule; reviewers may instead require every declared slot. No immediate default change to existing plans.

Improve chain diagnostics with all failed filters and nearest rejected candidates, provider/search completeness and fresh timestamps. Persist recoverable versus terminal failures. Extend search beyond a small refreshed sample within a bounded deadline; neither an incomplete search nor an unavailable provider means no eligible contract exists. Pending recoveries use a durable cache and backoff, stopping on invalidation/target-passed/expiry.

Serialize capacity reservations with account-scoped DB locking or an equivalent durable uniqueness mechanism, not only an in-process lock. Count paused, working and held campaigns once; include manual arms in the stated capacity policy. Never retire old arms before a replacement is fully validated, and default to preserving current valid campaigns. No capacity or duplicate-symbol race may submit extra exposure.

Acceptance: a lower-ranked ready candidate can fill a free slot; awaiting-contract candidates do not consume an arm; a seventh refreshed candidate can succeed; manual arm racing automatic activation cannot overfill declared capacity; cancelled/filled/ambiguous intents remain protected; all preparation and execution modes respect workspace routing and archived-book rules.

### W7 — entry/exit fidelity, position economics and shadow experiments (after W5/W6)

The video describes entry as the level breaks on 5m/15m. Platform rules require completed-bar entries. Keep the shared gate and label the distinction; do not quietly implement tick-triggered entries. Compare a 5m closed-bar candidate policy against the current 15m baseline in research first. Daily event volume and intraday entry volume remain separate fields and tests.

Retain a causal low/high-so-far stop with quality-qualified session data. A breakout-bar-stop profile is a separate sourced variant, not a fallback for missing session data. Do not use the eventual full day's extrema at entry. No new 3x intraday volume rule or new exit fractions are introduced from this video.

Audit integer options quantities against exit allocations: specify rounding, minimum tradable trim, protective-exit priority, residual units and single-contract behavior. Show premium-at-risk, underlying stop distance, maximum debit/fees, contract multiplier, cash and per-book exposure separately. The video does not supply exact expiry/Greek/overnight cushion rules; retain current controls until specifically reviewed. Shares/leveraged products require a separately approved expression policy and must not silently substitute for an unavailable option.

Pre-register a small one-family-at-a-time experiment matrix. Diagnose September 8–11 but do not use it as a holdout. Validate labelled historical setups without future information and then collect prospective shadow sessions. Option P&L needs actual historical quote/fill assumptions; underlying R alone is not option expectancy. Include no-trade days, false positives, opportunity costs, losers and all failed variants. No automated promotion or risk escalation.

### W8 — product, operations and release (alongside each package)

Use the shared app's existing visual components. Plans shows logical progress across restarts, benchmark date, data-quality coverage, developing ignition watchlist, execution-ready candidates, pending reserves and current arms. Every blocker includes a reason, last checked time, retry state and required next condition. Armed means active execution monitoring, not guaranteed entry; “complete” distinguishes scan completeness from tradability.

EOD exports: as-observed versus corrected tape, no-trigger/data-blocked/strategy-rejected/invalidated/broker-rejected/filled/expired counts, per-plan outcomes, option P&L confidence and links to decision evidence. Preserve signed-off historical reports; corrections append rather than overwrite.

Release gate: reserve a version against the integrated desk/main state; update version files/changelog/docs together; build integrated main before deploy; compare backend health and served frontend version. Do not perform generic start/stop from Codex or deploy intraday as routine. Tests run sequentially only on zargar_test_codex; no second runtime engine.

## 5. Migration and failure behavior

1. Add schemas/readers with feature disabled; verify old-state compatibility and protective exits.
2. Backfill only observable provenance. Unknown stays unknown. Build new cache manifests without rewriting old decision inputs.
3. Run research-only source-quality checks and report which existing unfilled plans would fail. Reviewer chooses explicit migration treatment; do not silently alter their strategy snapshot.
4. Enable the data-quality entry path in an approved Practice pilot; all consumers use the same decoder/source precedence.
5. Enable the ignition profile in shadow. Promote to automatic Practice only after a separate evidence review. Live remains unchanged.
6. Rollback disables new plan creation/activation, not position protection. Retain additive records and a compatible reader; no destructive database reversal or replayed entries.

Failure table: stale benchmark → wait/backoff; malformed bar → quarantine; unknown provenance → block new entry/recover; contract unavailable → bounded reserve retry; closed session/invalidated thesis → terminal for that executable child; process restart → recover eligible job; explicit cancel → remain cancelled; ambiguous order response → reconcile, never resubmit blindly.

## 6. Required reviewer decisions and definition of done

Before work starts, the other team should approve or amend: the additive envelope location and source precedence; authoritative provider/feed/adjustment; no-trade interval semantics; compatible legacy-state migration; capacity locking across manual and automatic paths; the ignition detector's engineering thresholds; covered-window policy; experimental entry/stop profile; and integer exit policy.

A package is done only when it has a small isolated PR, boundary tests, current-main integration evidence, documented failure/rollback behavior and reviewer approval. W1/W2 are not complete merely because the scanner becomes faster. W4/W5 are not complete merely because they find the video's winners. W7 is not complete merely because simulated trades are profitable.

For the overall programme: trusted input provenance survives restart; benchmark freshness is explicit; cold/warm/resume costs are measured; persistent ignition theses produce deterministic causal plans; executable candidates have valid data/contract/risk; capacity/position protection holds under races; every skipped or executed decision is explainable; and an independent reviewer accepts the evidence. No fixed date or trade count can guarantee profitable operation.

## 7. Handoff status

- [x] Full transcript recovered and read; scanner/entry/developing-setup chart spot checks complete.
- [x] Existing weekend findings mapped to W0–W8 with dependencies and acceptance tests.
- [x] Source facts separated from engineering proposals and unresolved interpretation.
- [ ] Reviewer approval, implementation, tests and rollout.
- [ ] Full statistical/option-fill validation and prospective profitability evidence.

No user assistance is currently needed for transcript access. No implementation has started.
