# Options Cartel: weekend review and proposed change programme

> Execution update, 2026-09-12: the user subsequently authorized implementation, commit, push and deployment while the other team was busy. The proposal text below is the original review baseline, not a continuing approval block. See RELIABILITY-RELEASE-2026-09-12.md for shipped scope and remaining validation.

**Date:** 2026-09-12. **Status: PROPOSAL — awaiting independent team review.**
No implementation, runtime configuration changes, new preparation, orders, or deployment are authorized by this document. The user requested a review before implementation. This supersedes any inference that earlier auto-merge permission applies to this programme.

## Transcript recovery update

The follow-up retry succeeded: the full auto-generated transcript was read and key chart frames checked. See [the implementation-ready plan](IMPLEMENTATION-PLAN-2026-09-12.md) for the post-ignition watchlist/detector, source timestamps and W0–W8 work packages. Earlier access-failure notes below describe the first pass; they are superseded by this update. No implementation has begun.

## Decision summary

Our dedicated Practice book has $10,000 cash and zero orders. Friday was a no-trade day, not a loss, but it does not validate profitability or full fidelity to Sean's method. Four of the five armed bearish names never reached their triggers in the stored tape; CENX crossed but failed its recorded volume test. There is no verified missed profitable option trade.

The first priority is **trustworthy data and causal decision evidence**, followed by **coverage-aware selection**, then **author-method calibration**. More trades is not the acceptance criterion. A source-consistent, observable system that can distinguish a valid abstention from a data failure is.

Important correction to the Friday EOD assessment: all five symbols had 390 stored minutes, but some were quote-sampled rather than exchange bars. Timestamp completeness alone was too strong a basis for saying the feeds were complete. That weakens the confidence of price-only counterfactuals and requires explicit provenance in future reviews.

## Review scope and baseline

- Code reviewed against fetched `origin/main` **c0eb5c3**; the local development branch contains unrelated unpublished desk work and was not used as an assumed integrated baseline.
- Read CLAUDE.md, architecture/platform guidance, METHOD, SOURCES, SOURCE-REVIEW, TRADING-RULES, prior fidelity and ledger notes, and current preparation, history, observer, entry, contract and ranking paths.
- Runtime inspection was SELECT-only, inside `BEGIN READ ONLY`, against the existing desk database. No raw runtime database was copied. Evidence below consists of aggregates and necessary run identifiers.
- Primary working folder remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. Existing Claude worktrees and app processes were preserved.
- These findings are a source/code/data review, not a newly executed full test suite, repaired-data replay or broker audit.

## 1. Updated author evidence: what we can and cannot compare

### Sources read on September 12

| Ref | Source and publication | What was verified | Limits |
|---|---|---|---|
| W1 | [Sean's September 9 environment framework](https://x.com/SRxTrades/status/2097792161466962380) | Full post: EMA trend quality, equal-weight participation, NYMO context, and the portfolio's own follow-through precede increased aggression. Deterioration calls for less exposure. | No numeric sizing algorithm or calibrated gate thresholds. |
| W2 | [ALAB, September 9](https://x.com/SRxTrades/status/2097827129438163014) | Planned long trigger over 311; contraction following an advance near the moving averages, with a longer-lived weekly thesis. | A watch idea, not a confirmed dated fill or Friday profit. |
| W3 | [AMD, September 9](https://x.com/SRxTrades/status/2097827535870414857) | Weekly wedge/relative-strength thesis; stated breakout level over 570. | Not proof of an executed trade. |
| W4 | [SMTC, September 9](https://x.com/SRxTrades/status/2097827348649214160) | Discusses an existing daily breakout and waiting for further structure near highs; quotes the September 7 theme/catalyst thesis. | Does not instruct buying immediately or establish Friday P&L. |
| W5 | [Friday continuation-setup announcement](https://x.com/SRxTrades/status/2098524484680716568), [YouTube video](https://www.youtube.com/watch?v=7xSMgmLoqM8) | September 11 publication, Sean Trades channel, 20:20 duration, title/description emphasizing one repeatable setup. | **Full video review remains open.** Transcript export timed out twice; the visible transcript panel remained loading. Description/intro are not a substitute for reviewing the examples. No new entry rule is inferred from them. |
| W6 | [Cartel's September 8 DRAM highlight](https://x.com/TheOptionCartel/status/2097414673662718231) | Latest non-pinned result highlight visible on the inspected profile reports a swing exceeding 200%. | Not a September 11 daily return; not an audited, weighted Sean account result. |
| W7 | [Public Sean ledger, gid 0](https://docs.google.com/spreadsheets/d/1yp96STZjdbA6JM06Rm-xlGiT9BzXoSO1w7ZCKnuifIs/htmlview/sheet?headers=true&gid=0) | Refreshed header, formula example and latest September rows through row 1253 inspected. | Rows lack exact entry dates, quantities and complete exits. Not all historical rows were re-audited this time. |
| W8 | [Sean, September 12](https://x.com/SRxTrades/status/2098849124951232628) | Emphasizes consistency before scaling. | Personal earnings assertions are not independently verified. |

X profiles initially failed, but the dated X search and subsequent direct post/profile reads succeeded. Search mirrors were discovery leads only; their previews were not accepted as current trade evidence. The [Thread Reader index](https://threadreaderapp.com/user/SRxTrades) still lists September 6 as its latest archived long thread; that index is not complete account coverage.

### Ledger update, with attribution limits

The refreshed September section contains DRAM 40C Oct 16 (entry 1.58, displayed 226.58%), losses on MUU/CRCG shares and CVNA/SMCI calls, an IWM day trade, and incomplete SPCX 160C Oct 16 and BMNR-share rows. These show a mix of outcomes and instruments. They do **not** identify which occurred Friday or establish realized daily earnings. The historical CCJ example still displays 27.62% from entry 2.10/highest trim 2.68 despite a final-exit cell of 1.80. Do not sum the percentage column as portfolio P&L.

SPCX's displayed entry premium of 5.05 illustrates a potential affordability difference from our $5 maximum ask, but timestamps, size and quote conditions are missing. It is not evidence that raising our cap would reproduce that trade. The September shares rows also reinforce the existing documented distinction between the author's equities-plus-options process and our automatic options-only expression.

**Answer to “what did they do that we didn't?”:** the verified difference is sustained thematic focus, discretionary chart context, instrument choice, and multi-session campaigns. There is no verified Friday trade-by-trade result list to label as our missed winners. Their publicly discussed long ideas and our Friday bearish scan were also evaluating different directions and dates.

## 2. Friday evidence and corrected interpretation

Friday preparation: `a973b3a438314f61b4975b3ec087650b` (session 2026-09-11). It evaluated 3,077 histories out of 3,078 listings, found 34 qualifying candidates, checked 14 candidates for readiness, and armed five. One daily error: FISV missing 2025-11-12. KN, ATRO, SSYS and FUL had only one baseline period and no usable pre-close window. Five other names remained contract-pending. Resume reused 2,554 analyses after the second restart; its final pass took 3m49s. These counts establish mechanics, not strategy performance.

| Symbol | Trigger / invalidation | Friday outcome | Stored exchange / sampled minutes | Historical baseline slots |
|---|---|---|---|---|
| AAP | 42.29 / 43.50 | Invalidated 06:45 PT; no recorded trigger crossing | 346 / 44 | 19/26 |
| LFTO | 17.47 / 18.44 | Invalidated 07:15 PT; no recorded trigger crossing | 284 / 106 | 2/26 |
| QUBT | 7.77 / 8.06 | Invalidated 09:00 PT; no recorded trigger crossing | 384 / 6 | 26/26 |
| YETI | 39.04 / 41.10 | No recorded trigger crossing; expired at close | 385 / 5 | 25/26 |
| CENX | 43.98 / 46.89 | Volume rejection, then expiry; 16 unsupported-period decisions | 353 / 37 | 10/26 |

Baseline counts include the closing slot, which cannot open a new entry; they must not be described as that many tradable opportunities. Current stored source tags are a database snapshot, not proof of the exact provenance seen at decision time.

CENX's saved 07:45 PT decision records volume 33,689 / baseline 34,773 = 0.9688, versus required 1.5. The same interval currently contains 15 exchange-tagged bars totaling 33,705, showing why as-observed evidence must be separated from subsequently corrected history. Both values are below the threshold; this difference does not overturn that rejection. Stored daily low 43.36 remained above the first target 43.29 and the close was 44.06. No option-price replay has established a profitable counterfactual.

Friday scan exclusions for author-reference names: ALAB failed weekly-base, near-extreme, dry-up and tightness checks; AMD/SMTC also failed directional/context checks. These are disagreements to label and study on date-matched charts, not permission to waive gates after seeing a public winner.

### Monday is not ready yet

Latest recorded preparation `f451f8270b3f4849bd12b378a4a83859`, targeting September 14, has 3,070 evaluated histories, five data errors and zero arms. Its SPY/QQQ inputs end September 10, not the expected September 11, so alignment is unknown and arming is blocked. A cache-bypassing retry does not manufacture a missing provider session. A fresh valid snapshot is required before any Monday arming. This review did not run preparation or modify those records.

## 3. Prioritized findings

| ID / priority | Evidence and issue | Proposed correction | Confidence |
|---|---|---|---|
| D1 / P0 | `Bar.source` exists, but `Bar.to_row()` and Cartel's persisted six-number minute rows discard it. `_seed_session` merges stored state over fetched data. `load_session_context` uses timestamps and `setdefault`, not source precedence. | Preserve provenance/revisions end-to-end; source-aware recovery and readiness. | Code-confirmed design gap, runtime mixed-source evidence. Exact impact on every old decision remains unproven. |
| D2 / P1 | `covered_periods` accepts any usable pre-close slot. LFTO entered the shortlist with 2/26 coverage; CENX with 10/26. `quality_key` ranks structural R, directional RS and daily volume, not coverage. | Recover baselines first, then gate and rank by usable windows before assigning executable slots. | Confirmed selection limitation. |
| D3 / P1 | The latest Monday scan still has stale benchmark sessions. Daily cache reuse requires matching expected session and observations within 12 hours; each new cutoff can redownload 550 calendar days. | Durable session-addressed cache, incremental updates, benchmark freshness barrier and bounded recovery state. | Confirmed behavior; provider root cause not yet established. |
| D4 / P1 | Local pacing .25s means about four request starts/second; 3,078 cold daily reads imply roughly 12.8 minutes of start spacing alone. Batches are concurrency windows, not multi-symbol API requests. Resume replays thousands of saved analyses. | Shared fetch deduplication, actual provider batching where supported, incremental features and checkpointed ranking. | Code-confirmed; performance targets require measurement. |
| M1 / P1 | Source process starts with themes/leaders and maintains specific chart theses. Our broad scalar ranking is not an equivalent discretionary review. | Versioned weekly thesis/watchlist layer, calibrated chart labels and explicit method profiles. | Source-supported mismatch; proposed numeric implementations remain hypotheses. |
| M2 / P1 | 15m, 1.5x same-time median volume, 70% close location, 0.25R, Moderate alignment and later exit fractions are engineering/user choices. | Separate author evidence from experiments; freeze a baseline and compare variants independently. | Confirmed provenance distinction, not proof those choices lose money. |
| E1 / P1 | Pending context recovery is ephemeral; missing minutes recur. Chain selection has finite expiry/refresh coverage and execution-time liquidity gates. | Durable readiness reasons, bounded gap repair, paginated contract coverage and retry classifications. | Code-confirmed limitation; do not infer every pending name is affordable. |
| E2 / P1 | Underlying R, full option premium at risk, per-plan budget and share/option expression are different quantities. Few contracts cannot reproduce smooth percentage trims. | Explicit risk/quantity/exit-feasibility card and deterministic small-quantity policy. | Review requirement; end-to-end exit defect not reproduced this weekend. |

P0 here means implementation-review priority for trustworthy entry evidence, not evidence of a live loss or permission to interrupt shared services.

## 4. Proposed implementation slices and acceptance tests

### PR A — provenance and decision reproducibility (first)

Target `domain.py`/shared bar DTO boundaries only as needed; Cartel `observer.py`, `observation_health.py`, `preparation_readiness.py`, `entry.py` and state serialization. Coordinate shared schema work with other desks.

Introduce a versioned candle envelope or sidecar keyed by symbol/timeframe/session/timestamp: provider, feed, source class, adjustment basis, received-at, revision and quality. Preserve original decision inputs; store later corrections separately. Legacy six-value rows become provenance-unknown, never retroactively exchange-certified.

For new automatic entries, require trustworthy data for the confirmation bucket and the selected stop calculation. A full-session stop needs verified session extrema coverage; a breakout-bar stop remains a separately reviewed source variant, not an automatic fallback. Quote sampling may support display/protection under existing policy, but must not masquerade as historical trade volume. Do not disable protective exits when entry evidence is inadequate.

Recovery replaces inferior sampled/unknown observations with verified data before the next prospective decision. It must not overwrite a superior/newer exchange revision, resurrect invalidated plans, refire an old crossing or rewrite a fill. Provider-confirmed no-trade intervals, outages, halts and unknown gaps need distinct states; do not infer zero trades from an absent bar.

**Accept:** sampled/unknown/legacy rows cannot pass an exchange-volume gate; a late correction updates context without an extra order; crash/restore preserves source and cutoff; held-position exits remain operable; Friday's recorded versus revised CENX decision can be reconstructed separately; all affected shared consumers have boundary regressions.

### PR B — durable history and baseline service

Store normalized daily/intraday history with versioned manifests keyed by symbol identity, provider/feed, interval, session, adjustment and revision. Reuse completed sessions; request only missing or explicitly refreshable ranges. Record complete pagination, requested/returned bounds, provider freshness and corporate-action/ticker mapping. Investigate FISV's missing session before splicing another symbol's history.

Request a trading-session lookback, not just 19 calendar days, when provider capability permits. Require at least five valid samples for each supported same-time bucket initially. A provider-native 15m aggregate may be an alternative only after its session boundaries, volume treatment and revisions are validated against the minute-derived definition; do not mix denominators silently. Retain all-baseline and partial-baseline policies as versioned variants.

**Accept:** holidays/half-days/DST, missing pages, repeated tokens, splits/renames, source disagreement, legitimate no-trade evidence and changed adjustment modes have tests; incomplete fetches cannot be labelled complete; repeated identical snapshots make no history calls; invalid OHLC is quarantined with a specific repair path.

### PR C — startup recovery, benchmark freshness and speed

Keep one owned preparation task/lease per scope, durable stage checkpoints and idempotent plan identities. On restart offer/configure automatic resume only for the same account, workspace, policy, data schema and valid session/cutoff. Cancellation or a user-disabled run must not restart itself. If the cutoff/session changes, create a new snapshot while reusing valid raw history, not old decisions. Recheck execution permissions immediately before any arm.

Prioritize SPY/QQQ readiness before an expensive executable scan. Persist bounded delayed retry/backoff; display “waiting for September 11 benchmark publication”, not “market bearish” or a generic coverage error. Research can continue separately and can never become an executable plan merely because a later poll changes alignment.

Alpaca's [multi-symbol bars endpoint](https://docs.alpaca.markets/us/reference/stockbars) supports a real batch request; results are symbol-sorted and pagination can span symbols. Implement capability/entitlement checks and exhaust `next_page_token` before declaring a batch complete. Current single-symbol wrappers need an adapter; this is not achieved by changing the batch-size setting. Keep global rate budgets/backoff and isolate research load from the execution loop.

**Targets for measurement, not promises:** same-snapshot warm run under 60s; recovery of 2,554 saved analyses under 30s; substantial cold-run improvement against an identical fixed universe. Record p50/p95, request/page counts, bytes, DB/CPU time, cache hits and event-loop lag. Provider throttling must win over a time target.

**Accept:** two concurrent resumes make one task; restart after plan commit does not duplicate an arm; stale benchmark success retries without reconstructing the universe; current workspace mismatch never arms; deterministic results match sequential evaluation; no starving quote/exit work under load.

### PR D — separate research, ready candidates and armed campaigns

Represent a full ranked candidate pool, a bounded executable shortlist, retained campaigns and pending reserves separately. Use independent statuses for data readiness, market permission, contract readiness and actual arm state. Persist every checked candidate and why candidates beyond the check budget were not inspected.

Proposed shadow-first policy: for a day-wide 15m plan, require all of the first four pre-close confirmation slots and at least 20 of 25 eligible slots; for a deliberately narrower entry schedule require complete coverage of that declared schedule. These are engineering proposals for reviewer approval, not author rules or an immediate production default. Replay alternative coverage thresholds before selecting one. Never move a plan to a convenient window retrospectively.

Order candidates by eligibility first, then source-aligned setup quality, then usable coverage/contract quality as explicit tie-breakers. Preserve existing campaign protection and account capacity. Do not evict a valid arm solely because a fresh score is higher. Do not treat “five armed” as the goal when only two have defensible entry windows.

**Accept:** LFTO-like 2/26 coverage cannot appear as an unrestricted ready plan; closing-only coverage is never executable; pending names consume no active slot; manual/paused/working/held campaigns cannot be displaced; capacity races, failed refreshes and retained plans passing expiry are covered.

### PR E — contract feasibility and reserve recovery

Persist per-attempt outcomes: unavailable provider, incomplete search, stale quotes, no eligible contract, unaffordable, invalidated, missed target and expired. Show nearest rejected contracts with every failed filter, not only the first failure. Preserve the distinction between planning chain prices and fresh executable quotes. Walk beyond the first refreshed candidates within a documented bounded budget; never call a truncated search exhaustive.

Keep a deduplicated pending-recovery queue and durable quality-qualified context cache. Stop retries for terminal invalidation/expiry; back off provider failures. Do not re-arm previously retired plans on a revised tape. Consider shares for source-supported long setups only in a separate opt-in Practice expression policy; no automatic leveraged ETF substitutions, naked options, margin shorts, or Live enablement.

**Accept:** seventh-candidate success fixture, pagination ending before a second symbol/expiry, missing delta/OI, stale NBBO, cheaper-but-ineligible contracts, 100x multiplier/FX/cash limits, midnight/DTE changes and retired-plan retry tests. Decisions still pass the shared order/risk/write-ahead path.

### PR F — source fidelity and multi-session setup lifecycle

Complete W5 video review with timestamped notes and chart examples first. Maintain rule-to-source evidence, date/version and confidence. Label numeric inventions explicitly. A weekly thesis should survive a daily plan's expiry, but each next-day executable plan must receive fresh market/data/risk checks. Preserve author lists with their publication/observation time and intended horizon, including names not yet in an entry-ready base.

Add measurable fields for prior advance, consolidation contraction, level touches, theme/catalyst evidence, relative strength and target provenance. Have reviewers label both positive and negative charts without future bars. ALAB/AMD/SMTC become date-matched disagreement examples, not permanent exceptions. Do not infer bearish Friday trades from long Wednesday watch ideas. NYMO must stay unavailable unless a defined, licensed dataset and formula are verified; equal-weight context is not a fabricated NYMO substitute.

**Accept:** two reviewers can trace each plan to inputs and rules; future posts cannot affect earlier snapshots; no unknown catalyst becomes a pass; research-only plans never acquire execution permission in place; daily refresh preserves thesis identity and held positions; method variants do not silently blend stop/exit rules from different years.

### PR G — controlled strategy and risk experiments

Freeze the present baseline after data repair. Pre-register a small matrix: 5m versus 15m; breakout versus retest; author-example stop versus causal session-extreme stop; current same-time volume comparison versus a separately evidenced volume definition. Change one family at a time, report all results and preserve failed variants. No unrestricted parameter search on five Friday names.

Use September 8–11 as diagnosis, not a holdout. Build an earlier, timestamp-valid labelled sample and reserve subsequent sessions for forward evaluation. Underlying replays measure geometry only. Option comparisons need contemporaneous bid/ask, Greeks, fees, fill assumptions, expiry and integer partial-exit quantities; otherwise label option P&L unavailable. Include no-trade days, invalidations, losers and opportunities excluded by data problems.

Current Practice 10% setting is a full-premium risk ceiling, not a mandatory stake or an author recommendation. Keep production settings unchanged for this review. Proposed experiments should use matched notional exposure and display portfolio-wide committed premium/cash, per-trade cap and realized/marked risk separately. A $500 budget on a $10,000 book can bind below the 10% ceiling. Do not infer that stop-at-entry makes an option campaign risk-free.

**Accept:** compare signal count, false positives, MFE/MAE, realized option expectancy where measurable, drawdown, data-blocked opportunities and concentration; promotion requires independent review and prospective evidence, not a target number of daily orders. No automatic risk escalation or Live graduation.

### PR H — product reporting and release coordination

Use existing Team2/shared table, badge, empty-state and status conventions. Plans should expose: benchmark through-date; trusted/live versus sampled/missing coverage; available entry windows; true contract/search status; reserved capacity; and next retry. An EOD report distinguishes no trigger, data-blocked, strategy-rejected, invalidated, broker-rejected, filled and expired.

Show cumulative logical-run progress across restarts instead of apparently restarting at zero. Keep stop/restart effects explicit. Add timestamped comparison notes for public author ideas, with links and attribution limits. Track version reservations against integrated main before assigning a release number; do not reserve numbers speculatively in this planning document. Build/version checks must validate merged changelog syntax as well as metadata agreement.

**Accept:** desktop/mobile and Practice/Live screenshots; no research-only/expired record presented as armed; corrected data cannot overwrite historical decision text; simulated and realized results remain separate; API/backend/built-frontend version provenance is displayed consistently.

## 5. Review gates, rollout and rollback

Recommended order: **A → B → C/D → E → F → G**, with H alongside each slice. A and B have shared-boundary review before merge. No large combined strategy-and-data PR.

1. Reviewer reproduces D1 source loss and D2 readiness classification; agrees schema/migration and source precedence.
2. Deliver a corrected-data diagnostic report before claiming missed signals or changing volume thresholds.
3. Run sequential tests only against `zargar_test_codex` on 127.0.0.1:5433 via `scripts/test-codex.ps1`. Build before tests serving frontend assets; no second engine on runtime/test DB.
4. Add synthetic boundary tests and isolated read-only provider smoke checks. Provider checks may establish availability, not profitability.
5. Ship additive schema/read paths first. Preserve old plan snapshots and events. Unknown legacy provenance fails closed for new entries; existing positions retain protective management.
6. Stage Practice shadow comparisons, then a separately reviewed Practice pilot. No Live migration, risk change or generic shared start/stop invocation by Codex.
7. Rollback disables new preparation/promotion, preserves exits and existing state, and returns to the prior compatible reader. Do not drop data, recreate runtime tables or resurrect retired plans.

### Questions for the other team

- Is source-quality gating scoped correctly for volume, confirmation and session-extreme stops? What protection remains available when data is degraded?
- Should provenance live in the shared Bar DTO or a Cartel sidecar, and how do other techniques remain backward-compatible?
- Which provider/feed/adjustment is authoritative, and can the account actually obtain the proposed daily and multi-symbol data?
- Is the proposed coverage threshold sensible, or should all declared windows be required? Which shadow comparison decides?
- Does the new video support a different setup/entry model? Require timestamps before changing rules.
- Are contract search budgets and integer exit quantities compatible with the book's affordable positions?
- Are tests checking causal decisions and restart/cancellation races, rather than just producing five green arms?

## 6. What is complete and what remains

- [x] Friday account and final plan states rechecked; no orders, $10,000 cash.
- [x] Mixed-source minute counts and source-loss code path identified; EOD wording corrected.
- [x] Latest author posts, market-framework text, Cartel profile and refreshed ledger tail inspected with attribution limits.
- [x] Current method/code differences and phased changes documented with acceptance criteria.
- [x] Follow-up: full September 11 transcript read and selected scanner/entry/setup frames checked; see IMPLEMENTATION-PLAN-2026-09-12.md.
- [ ] Exact Friday author fills/weighted P&L; public evidence does not supply them.
- [ ] Repaired exchange-data replay and statistically meaningful strategy validation.
- [ ] Independent team review and approval of selected slices.
- [ ] Implementation, tests, deployment and fresh Monday preparation after approval.

No code or settings changed. This is a review packet, not a deployment sign-off or promise of profits.
