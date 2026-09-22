# Developer handoff: September 21 Cartel execution and profitability fixes

**Prepared September 21, 2026. Specification for implementation; no changes are activated by this document.**

## 1. Objective and cooperation

Options Cartel is Zargar's deterministic interpretation of Sean Trades' swing-trading method. It discovers stocks, analyzes completed daily/weekly inputs, prepares a shortlist and option expression, confirms entries intraday, and manages partial exits. The user wants practical improvements in executed, after-cost outcomes. Extra reports, more signals and larger dollar gains from larger sizing are not sufficient outcomes.

Implement the bounded packages below. The coding team owns code, focused tests, documentation and a precise handback. The reviewer checks the complete source-to-fill path and returns one consolidated blocker list, separating **code accepted**, **deployed**, and **Practice activated**. Preserve other teams' changes. Read AGENTS.md, CLAUDE.md, ARCHITECTURE.md and PLATFORM-RULES.md before shared/runtime work. Refresh current main/runtime state; the observed review build was v0.8.28, not an instruction to downgrade a later release.

The user explicitly removed future-session evidence as a prerequisite for completing development. Deliver historical/fixture evidence and an actionable Practice implementation without waiting for 20 future sessions. The existing frozen forward trial remains an independent observational record: do not rewrite its protocol or falsely mark it passed. Development completion is not a profitability claim.

## 2. Current operating boundary

- Dedicated simulated book: `e7b246c9e30d4dde93f4d91844cbc982`, **Options Cartel Practice - Capital Experiment**.
- $1m starting virtual capital; $25k purchase budget per plan; max option ask $250; focus capacity 20; risk setting 10%; maximum contracts 10. Revalidate effective settings before implementation/activation. Do not reintroduce the old $500 affordability restriction or silently enlarge the experiment again.
- Old $10k book `0b48ed48de2f4030b49942b52858356d` is archived with its history intact. Never merge its returns with this experiment without accounting for the capital change.
- Live behavior, other techniques, account routing, positions, resting orders and protective exits are outside this change. No direct/manual broker orders or second engine.
- Valid data, instrument identity, fresh executable quotes, permissions, duplicate prevention and protective management stay enforced. Virtual money does not make a stale quote or invented fill valid.
- Behavioral experiments are explicit, versioned and Practice-only. Existing positions retain the policy under which they entered. Preserve the existing rollback switch and protective exits.

## 3. Authoritative evidence

Start with [the EOD review](reviews/2026-09-21-eod/README.md), [session review](reviews/2026-09-21-eod/session-review.json) and [shadow evidence](reviews/2026-09-21-eod/shadow-evidence.json). Evidence cutoff: September 21, 16:00 ET. Actual orders/executions were independently reconciled: **zero orders, fills, fees, open instruments and realized P&L**.

| Case | Established fact | What it does not prove |
|---|---|---|
| BBY/CNH/NVT | Session highs below planned triggers | That lowering the triggers would help |
| NOW | 09:31 high crossed; minute closed below trigger; no qualifying 15m crossing recorded | A wick is not an eligible missed entry |
| NTNX production | 15m confirmations rejected at 0.929x and 1.162x volume versus 1.5x required | Capital or order execution caused the refusal |
| NTNX lab | 5m confirmation at 10:30, volume 2.511x; captured at 10:30:35.885 | A shadow signal is an actual order or a profitable trade |
| NTNX selection | Two expiries/47 structural candidates; three attempts refreshed six November contracts each; no eligible refreshed contract | That every contract in the chain was ineligible |
| NTNX October | Reviewed `NTNX261016C00060000` had fresh OPRA bid9.80/ask11.30 near the signal; spread14.22%, sizes401/74 | Historical Greek/OI/risk checks all passed or a fill occurred |
| ULTA stock | 5m09:55 close548.76 failed volume0.962x; 15m10:00 close550.39 failed volume0.420x and target room0.064R | A rise to561.47 high/557.99 close implies option profit |
| ULTA option | Selected call bid10.00/ask14.80 near09:55; roughly38.71% spread; closing bid13.30 | Buying despite the spread would have been a good trade |
| HPE/NTAP screen | HPE failed range20.70% versus15% and volume1.104 versus0.8; NTAP failed only volume0.916 versus0.8 | Author-watchlist inclusion proves an entry or winner today |
| Data | SAIC/ASC lacked usable historical entry windows; FISV missing2025-11-12; armed tapes had zero unresolved minutes at final cutoff | Data was complete at every historical decision time |

NTNX's October ask-to-closing-bid difference was -$150 per contract before fees; ULTA's illustration was also -$150. These are endpoint price comparisons, not executed P&L or complete campaign replays. Do not turn them into strategy-return labels.

## 4. Delivery order and decision gates

| Package | Priority | Deliverable | Activation boundary |
|---|---|---|---|
| F1 | P1 | Causal decision/quote fixtures and honest review attribution | Reporting only; no trading rule change |
| F2 | P1 | Reviewed-contract priority and diverse, bounded quote refresh | Practice selection policy after correctness checks |
| F3 | P1 | Executable-cost comparison and auditable selection ranking | Explicit Practice policy; no Live default change |
| F4 | P1 | Order-capable 5m Practice entry variant, 15m matched control | Fresh plans, one executing variant; preserve existing positions |
| F5 | P2 | Setup-specific dry-up/contraction comparison | Separate from F4; activate only an identified version |
| F6 | P2 | Long-share expression when options are unsuitable | Explicit Practice option, not a stock-entry bypass |
| F7 | P2 | Historical baseline/identity gaps and bounded lifecycle repair | Data correction with provenance; no invented bars |
| F8 | P2 | Source ingestion, operating checks and rollout documentation | No source post or online P&L claim gains order authority |

F1-F3 form the first release. F4 is the first trading-behavior experiment once quote selection and lifecycle work. F5/F6 are separate changes, not a bundle of loosened gates. Packages may share code, but keep their policy versions and effects attributable. Do not spend the whole iteration on reporting while postponing the entry/selection fix.

## 5. F1 — preserve causality and correct rejection summaries

**Code:** `session_review.py`, `opportunity_status.py`, decision bundles/contexts, quote records, `CartelSessionReview.tsx` and related status displays.

Current review precedence labels a plan data_limited when *any* prior data refusal exists. NTNX/ULTA consequently obscure their measured volume/target refusals. Do not fix this by merely swapping two branches: an earlier unknown window may still hide an opportunity.

Return separate fields for:
- actual outcome: no order / submitted / unfilled / partially filled / held / closed;
- first known blocking decision, timestamp, window, rule, input hash and measurements;
- other independent blockers, including which would remain if the first were removed;
- incomplete opportunity windows and whether their evidence was available at the time;
- current/final coverage, kept separate from decision-time coverage;
- selection coverage: not attempted / incomplete / exhausted / eligible expression found;
- actual fees/P&L versus modeled or unknown outcomes.

Show the primary *known* cause without asserting all other windows were valid. NOW needs a wick-versus-confirmation explanation; BBY/CNH/NVT need a no-level-touch explanation. Recovered data must not retroactively authorize an order. Price touch, confirmation, contract eligibility, submission and fill are distinct funnel stages.

**Acceptance:** NTNX shows the 10:30 volume refusal and later data warning separately; ULTA lists both independent 10:00 blockers; an unknown earlier window remains unknown; a repaired gap cannot become a timely fill; no-signal sessions with complete evidence are distinct from incomplete sessions.

## 6. F2 — fix contract refresh allocation

**Code:** `contracts.py::select_contract/rank_candidates`, `contract_reselection.py`, `research_quotes.py`, preparation/execution configuration. Inventory every caller, including manual/Live callers, before changing defaults.

The current selector sorts structural rows by expiry distance and delta distance, takes refresh_limit=6, and only then evaluates liquidity/freshness. One expiry can consume the entire refresh budget even when all its rows fail known OI requirements.

Implement a deterministic, bounded policy, for example `diverse_liquidity_v1`:
1. Accept an optional reviewed/current contract from the caller. Give it first **refresh consideration**, not unconditional selection. Confirm symbol/right/expiry and account/plan identity.
2. Partition remaining structural candidates by expiry. Prioritize known acceptable static liquidity; record reliable known failures without wasting all refresh slots on them. Missing OI is unknown, not zero; do not invent its date or freshness. Record metadata provenance.
3. Allocate refresh opportunities across eligible expiries before additional depth within one expiry. Use stable tie breaks. With a six-contract budget and two expiries, both must be represented where candidates exist. Document the rule when expiries exceed the budget.
4. Bound total requests, per-provider concurrency, retries and elapsed time within the existing decision deadline. A second batch is allowed only under an explicit remaining request/time budget. Never extend an expired signal to complete a search.
5. Re-evaluate freshness, Greeks, spread and size after asynchronous requests complete. An initially fresh preferred quote may have aged; it receives no grandfathering.
6. Rank only fully eligible refreshed candidates. Return searched/refreshed/unrefreshed counts by expiry, per-contract reason sets, and unambiguous searchComplete. Partial failure means incomplete search, not no eligible option anywhere.
7. Preserve the old behavior for unaffected policy versions/Live. Snapshot the selected policy/version in new Practice plans and re-selection records.

**Acceptance:** reproduce the NTNX two-expiry/47-candidate structure. Six low-OI November rows cannot starve October. Include the reviewed October contract in the bounded refresh. Synthetic valid fresh Greek/OI inputs may prove selection mechanics; label those values synthetic rather than pretending the real case proved them. Also cover a now-invalid preferred contract, missing metadata, refresh timeout, stale-after-refresh result, deterministic ties, cancellation, restart/retry, no duplicate order and unchanged disabled/Live paths.

## 7. F3 — executable economics before instrument choice

**Code:** contract ranking, `execution.py`, `research_economics.py`, `receipt_economics.py`, `execution_review.py` and quote recording.

After hard eligibility, compare feasible quantities under the unchanged experiment budget and actual ask/depth. Record spread in quote units, per-unit dollars and total dollars, fees, debit, and spread as a percentage of premium. Favor a clearly documented cost/liquidity score over expiry proximity alone within allowed DTE/delta bounds. Do not silently replace the current 20% spread limit with another arbitrary number.

Use the actual whole-unit exit schedule to identify the first allocated sale. Preserve nearby resistance in the plan: do not skip it merely to manufacture attractive R. Separate stock target/stop R, option full-debit exposure, and estimated executable option economics.

If fresh Greeks support a delta-based target sensitivity, label its assumptions and uncertainty. It is not a forecast, executable future bid or a substitute for recorded prices. Missing Greeks/quotes produce unknown economics. Do not turn a weak linear estimate into a mandatory gate that creates another unexplained zero-trade system. Prefer measurable current cost/liquidity ranking first; introduce model-based hard thresholds only as a separately reviewed policy.

For the initial cost-ranking version, specify and persist a deterministic tuple:
entry displayed-size coverage first, then estimated crossing spread plus explicit
round-trip fees divided by entry debit, then DTE distance, delta distance and
contract symbol. Apply only after existing eligibility; this estimates current
friction, not expected return. Record every tuple component and compare against
the legacy ranking on the same snapshots. Do not silently add a new delta band.

Keep bid/ask asymmetry: modeled buys use ask, exits use bid; consume displayed size once, respect partial fills and actual fees. Do not use last prices/midpoints as executable fills. Preserve overnight risk, expiry and modeled-versus-actual limitations.

**Acceptance:** ULTA's 10.00/14.80 quote stays ineligible under the existing spread rule regardless of capital. NTNX's 9.80/11.30 book produces approximately14.22% spread and $150/contract crossing cost; no claim of positive outcome. Cover quantity/depth changes, one/two/three-unit allocations, fees, stale marks and unknown economics. Compare candidates at the same observation cutoff and same cash basis.

## 8. F4 — bounded active Practice entry-cadence experiment

**Code:** `EntryPolicy`, `entry.py`, preparation baseline construction, runtime signal identity, frozen policy/cohort metadata, UI settings and EOD comparison.

Both 5m and 15m are described in the archived method. The current automatic book uses 15m. Today's 5m NTNX signal is evidence that cadence changes eligibility, not evidence that 5m is profitable.

Deliver an explicit Practice entry policy that can execute 5m confirmations after F2/F3 pass. Keep 15m observations as a non-ordering matched control on the same pre-open candidates. Initially scope the new cadence to long Practice plans; keep the bearish path separately identified rather than silently extrapolating new models. One executing policy per plan/book: never submit two orders because both timeframes trigger. Existing positions retain original management. A new preparation must build the correct 5m historical baseline; do not reuse a 15m number or change the timeframe on an existing arm without a reviewed revision.

For the first cadence comparison retain volume1.5x, close quality, target/stop/risk and spread rules. This changes one component. Make the separate volume experiment configurable/versioned but inactive by default. Before selecting a volume change, replay a predeclared grid on all available prior sessions with the same population and costs; do not choose0.9 solely because ULTA was0.962 today. Finite historical/fixture acceptance permits a labeled Practice activation without waiting for20 future sessions, while profitability remains unproven.

**Acceptance:** reproduce the recorded NTNX 5m2.511x versus15m0.929x difference with independent baselines. ULTA still fails unchanged5m volume. NOW's wick cannot become a closed-candle signal. Cover early closes, first/last session bucket, restart watermark, repaired late evidence, existing held positions, duplicate 5m/15m confirmations and stale policy during preparation. Show actual fills and after-cost results separately from matched controls.

## 9. F5 — setup-family and source-fidelity corrections

**Code:** `setups.py`, `automatic_plans.py`, `quality.py`, leader/theme context, source matrix and preparation settings.

Today the same final10-session range and volume checks act as hard requirements across setup families. The default dry-up rule requires current-base/prior-base volume <=0.8, while the archived guidance is qualitative contraction. NTAP's0.916 is a measurable decline excluded solely by this engineering threshold; HPE has additional failures and must not be presented as a one-switch fix.

Implement separately versioned definitions for base/VCP, inside-day and pullback/reclaim context. For each define the consolidation window from completed data, how an impulse bar is excluded/included, minimum history, ADR-normalized range and contraction across subwindows. Preserve the legacy definition and report which exact check changed. Never select a window using later intraday performance or invent growth/theme evidence.

First compare the legacy0.8 rule against a declared non-increasing-volume interpretation and setup-specific windows. Report every evaluated name, unknown data and old/new classifications, not only public winners. A watchlist ticker is context, not an order. Do not promote a different stop, entry cadence and screening rule in the same result bucket.

**Acceptance:** preserve exact NTAP/HPE legacy measurements. A change that admits NTAP must name the changed rule; HPE's independent range/volume issues remain visible. Test past/future bars, mismatched source dates, ADR warm-up, no eligible base, and all families on equal source snapshots. Return a keep/change/reject recommendation without claiming a profitable edge from one session.

## 10. F6 — explicit long-share alternative

The runtime already supports long shares, but automatic preparation constructs options executions. Add a Practice-only instrument policy such as options_only versus options_or_shares; keep Live unchanged. Share eligibility requires the underlying setup to pass fully, including market, confirmation, data, target and risk rules.

A stock alternative may address option affordability or persistent option liquidity/cost failure. Specify permitted fallback reasons; distinguish a complete option rejection from an unavailable provider. For incomplete searches, say why shares were selected rather than claiming options were impossible. Obtain a fresh native stock bid/ask and displayed share size; modern SIP sizes are already shares. No extra x100 multiplier.

Recompute whole-share quantity, fees, cash and stop exposure under the same book budget. Reject zero quantity, stale/crossed quotes and bearish-share requests. Use the same managed-position lifecycle and integer exit allocation. A signal chooses one expression, with an atomic idempotency key; never buy both shares and options during retries or a late option refresh. Protect existing positions if the policy is disabled.

**Important:** this alone would not have entered ULTA under today's stock rules; its volume confirmation failed. Report independent blockers rather than claiming shares automatically fix every missed move.

**Acceptance:** valid stock signal plus unsuitable options can select shares under the enabled policy; failed stock confirmation never can. Exercise initial preparation, pending activation, re-selection, partial fills, duplicate retry, restart, zero units, fee/depth changes and exits. Compare net outcomes at equal deployed capital; the $1m funding injection is not profit.

## 11. F7 — fix data gaps without fabricating evidence

**Code:** `prepare.py::build_volume_baseline`, `preparation_io.py`, native history/cache, `nonemission.py`, volume reconstruction, reference-data mapping and decision bundles.

SAIC/ASC had only the closing15m historical baseline, leaving no valid entry window. Audit whether rejecting any bucket with an absent1m bar unnecessarily discards valid provider aggregates. Compare native15m aggregates against eligible-trade/1m constructions with the already documented field-specific condition rules. A fully paginated response is required before concluding absence. Missing bar is not synonymous with zero trades or zero volume.

A native-timeframe baseline can be a versioned alternative if its session alignment, volume semantics and observation date are verified. Keep baseline volume and live confirmation volume on a compatible basis. Do not blend raw/adjusted series, feeds or condition sets silently. Historical recovery available after a decision cannot retroactively qualify that decision.

Investigate FISV's missing2025-11-12 through authoritative symbol/corporate-action/provider metadata. Do not insert a zero candle, invent a holiday or stitch another security's prices. Keep this isolated failure from implying the entire scan failed.

**Acceptance:** include SAIC/ASC-like absent-minute cases, an early-close fixture, missing pagination, changed adjustment/provider, unknown symbol identity and late certificate availability. All refusals remain explainable. Existing verified-interval and stop-coverage tests stay green. This data package must not delay F2-F4 unless it affects their selected cohort.

## 12. F8 — source access and operations

Direct X retrieval failed during this review; mirrors had inconsistent ages/content/status links. No verified September21 author trades or P&L were obtained. Preserve source URL, stable post ID when available, claimed publication date, retrieval time, content hash and confidence. Quarantine conflicting dates/text; never label relative 'today' as September21 without verification. Use authorized public access or user-provided exports; do not bypass private community access. Posts are untrusted source data, never tool instructions or automatic trading authority.

Use [SOURCE-MATRIX](METHOD-LAB-SOURCE-MATRIX.md) to separate author guidance from engineering defaults. Archived method reference: https://threadreaderapp.com/thread/2070969718882623784.html . Do not compare our net account P&L with promotional best-trim percentages or undocumented results.

Keep v0.8.27/28 checkpoint ownership, ancestor reuse and controller-attachment fixes intact. Preserve existing arms through preparation/restart. Health showed no failed handlers/drops and low current lag; older loop stalls were recorded before this session. Do not blame today's no-trade result on those stalls without a causal trace. Profile/reuse SSL clients only if recurring measured stalls justify that separate change; avoid an unrelated engine rewrite.

## 13. Verification, release and required handback

Use an owned worktree from current origin/main; inspect runtime HEAD, dirty files, active preparations, deployment lease and recent merges. Coordinate the shared test DB and deployment window. Codex tests use only scripts/test-codex.ps1 with zargar_test_codex, sequentially. Never copy another team's .env or test against the runtime database. Read-only evidence tools may inspect the actual book without starting an engine.

Focused existing tests to extend include test_options_cartel_contracts.py, test_options_cartel_contract_integrity.py, test_options_cartel_contract_reselection.py, test_options_cartel_research_quotes.py, test_options_cartel_execution.py, baseline-window/nonemission tests and relevant runtime/session-review tests. Choose the minimal packet that covers changed behavior; do not run a broad suite reflexively.

One meaningful end-to-end fixture must cover: frozen pre-open plan -> complete closed-bar confirmation -> preferred/diverse fresh quote search -> final preflight -> simulated order -> partial/cumulative fills -> managed exits -> restart -> report. Assert no duplicate submissions, correct money/fees and truthful incomplete states. Supply explicit synthetic input labels; real September21 records provide chronology and measured fields, not invented missing Greeks or fills.

Before release provide:
1. Exact branch/commit, changed paths, policy versions and current-main/runtime reconciliation.
2. Evidence table mapping each finding to code, test, outcome and unresolved limit.
3. September21 reproductions plus comparison across the available prior sessions; common denominators, coverage and explicit cost assumptions.
4. Code-acceptance, deployment and Practice-activation verdicts separately. List exact settings before/after and which existing arms/positions are preserved.
5. Guarded deploy outside prime hours and active preparations; verify receipt/build, unquiesced state, restored arms/managed positions/orders and other-team fingerprints. Do not restart merely to install documentation.
6. User-visible explanations for instrument choice, search coverage, confirmation failures and actual net P&L. Update method/source/rules/review docs; mark replaced instructions superseded.
7. Rollback: stop new entries for the experiment while retaining protective exits; preserve old records and policy IDs; do not erase losses or convert unknown outcomes into zero.

Final acceptance is delivery of the tested fixes and an explicitly identified Practice experiment, with honest economic evidence and limits. It does not require future sessions, a minimum trade count, or a claim that profitability has already been achieved. The next EOD review must answer whether changed behavior produced better executable opportunities and after-cost outcomes, not merely whether the application stayed healthy.
