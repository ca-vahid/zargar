# Tips desk - experiment register (TMR-05, opened 2026-09-16)

The human-readable mirror of `backend/zargar/techniques/tip/experiments_register.py` (`experiments-v1`;
`tests/test_tip_scenarios_register.py` keeps the two id lists equal). Every research report the desk
produces carries `experiment` = the identity block of one entry below (hypothesis, variants, unit,
episode identity, primary metric, costs, regime incl. the build when known, evaluation window, status)
plus the standing caveat: repeated alerts or quotes are not independent observations; partial
realisations and fees count once; event sessions and incomplete evidence stay visible; no sample count
is called proof. Documentation and reporting only - nothing here allocates, promotes or trades.

## `entry-timing-cohort`

- **Hypothesis:** entering a tip at the alert-time qualified quote versus the same idea a fixed delay
  later (or only when the ask stays within a cap of the source-stated premium) changes net outcomes by setup.
- **Variants:** immediate (decision-time qualified quote); delayed (`entry_cohort_delay_minutes` 3.0);
  capped (ask <= `entry_cohort_premium_cap` 1.05 x source premium).
- **Eligible setup:** every eligible open/add idea on watched sources - skips, declines, blocked cards,
  shadows, parks and failures included. **Unit:** one idea at one decision. **Episode identity:**
  `tip_entry_cohort.id`.
- **Primary metric:** net $ and R per variant book on qualified quotes; insufficient counted, never filled.
- **Costs:** options fee per contract per side (+ regulatory), shares per order; fills at the ask, exits at the bid.
- **Regime:** `techniques/tip/cohort.py`, qualification `qualify_quote` (KF83-04), legacy rows re-judged at
  `sampledAt`; knobs `entry_cohort_enabled` (True since 2026-09-15), delay, cap, quote max age, delay tolerance.
- **Alternatives tried:** none promoted; the delayed-NBBO diagnostic (`TipEntryStudy`) preceded it.
- **Evaluation window:** opened 2026-09-15; closes after >= 30 adequate pairs per setup or 2026-10-15, whichever
  first. **Decision rule:** no entry-rule change without a cost-aware validated cohort; the reviewer decides.
- **Status:** collecting.

## `overnight-hold`

- **Hypothesis:** carrying a Tips position overnight versus a predeclared pre-close liquidation of the
  sampled size differs in net outcome by setup (shares / option DTE bucket).
- **Variants:** carry (overnight quote drift to the next session's first qualified bid inside 09:30-09:45 ET;
  the managed outcome shown apart when the position's own exit closed it first); intraday_exit (sell the
  sampled size at the pre-close qualified bid in the last 15 min before the exchange close).
- **Eligible setup:** open Tips positions at the pre-close window + positions that exited intraday that
  session. **Unit:** one position-session observation. **Episode identity:**
  `tip_hold_snapshots.observation_key` = study version | session | position | leg | arm.
- **Primary metric:** paired net $ and R (risk rebased to the sampled size) PER BOOK KIND x setup (Practice = sim,
  shadow, live, unknown - never pooled as performance; HOLD-SCOPE-01); `managedCarry` apart from
  `carryToNextOpen`; eligible / fresh / missing / late / ineligible counted. Inventory on a quarantined book, a
  position in `attention` or an unknown scope is diagnostic only, never an adequate pair (HOLD-SCOPE-02; the book
  status is captured on every observation from 2026-09-16, older rows resolve from the durable book or stay unknown).
- **Costs:** allocated entry fee + exit cost (options per contract per side + regulatory; shares per order per side).
- **Regime:** `techniques/tip/holdstudy.py` `holdstudy-v2`; jobs calendar-relative (close - 10 min; 09:30 with
  in-window retries); knobs `hold_study_enabled`, `hold_snapshot_before_close_minutes`,
  `hold_preclose_window_minutes`, `hold_next_open_window_minutes`, `hold_next_open_attempts`.
- **Alternatives tried:** v1 (2026-09-15) rejected - no windows, job-start clock, one fee side, first leg only;
  its three rows stay `outside_window` / insufficient.
- **Evaluation window:** opened 2026-09-16 (first protocol-correct capture 15:50 ET); closes after >= 20 adequate
  pairs per setup or 2026-10-16, whichever first. **Decision rule:** no holding-policy change from this study
  alone; the reviewer decides.
- **Status:** collecting.

## `frozen-context`

- **Hypothesis:** a compact analyst context (core rules + relevant notes + newest history lines) reaches the same
  decisions as the full context on identical frozen evidence at lower cost.
- **Variants:** current (the CAPTURED request verbatim - the full-route CONTROL only when the run was on the
  full route; on a compact-route capture it is the compact treatment and is flagged `isFullControl=False`);
  core_only; no_knowledge; compact (the generic PROF-05 trim, not the production candidate); recap_candidate
  (the production recap route, `recap-candidate-v1`, assembled by the same builder production uses - exact
  parity by request hash on a compact capture, treatment-only on a full capture).
- **Eligible setup:** analyst runs captured with `frozen_capture_context` on (exact manifest) and, for the recap
  question, a captured classifier read (`recapRead`) - bundles without it are non-parity / coverage-limited;
  replayed on the identical bundle. **Unit:** one bundle x one variant replay; a pair is complete only when every
  requested tool input was served (`coverageLimited` false) AND both treatments were assembled from the same
  frozen inputs (`frozen.assemble_treatments`, offline, before any paid call). **Episode identity:** bundle id +
  variant + report hash.
- **Primary metric:** verdict / contract / protections equality; input, output and cached tokens; calls;
  latency; coverage.
- **Costs:** paid model calls per replay (recorded in the report usage).
- **Regime:** `techniques/tip/frozen.py`, bundle version 1; knobs `frozen_capture_context` (True), `frozen_variants`.
- **Alternatives tried:** one NVDA pair (`fb-16d3146639a86744`) - coverage-limited, mixed reading, not adopted;
  the 2026-09-16 SPX-map / APLD-digest bundles are HELD - unpaid assembly shows no captured classifier read, so
  their recap_candidate inputs are unavailable (non-parity); no paid pair was run.
- **Evaluation window:** opened 2026-09-15; closes after >= 10 complete-evidence pairs. **Decision rule:** compact
  is never adopted from coverage-limited pairs; the reviewer decides on complete pairs.
- **Status:** collecting.

## `mk-ownbook-observe`

- **Hypothesis:** mirroring a source's own-book trades (MK-alpha-trades) would add a positive net edge; first,
  observe only.
- **Variants:** observe (record, no book) - live; shadow and mirror - not enabled.
- **Eligible setup:** own-book narration from `mk_ownbook_sources`. **Unit:** one narrated trade.
  **Episode identity:** signal id.
- **Primary metric:** n/a until shadow - observation counts and narration quality only. **Costs:** n/a.
- **Regime:** KFIN-08 own-book path; knobs `mk_ownbook_mode` (observe), `mk_ownbook_sources`.
- **Alternatives tried:** none.
- **Evaluation window:** opened 2026-09-15; closes on the user's decision, and only with predefined promotion
  criteria before shadow. **Decision rule:** narration is research, never permission (PLATFORM-RULES 19).
- **Status:** observing.

## `prompt-cache` (opened 2026-09-17, NOT enabled; paid pilot SKIPPED by user decision 2026-09-17 late - expected benefit small at the measured ~5.3k-token prefix, ceiling caveats: estimate-based pre-check, per-invocation ledger)

- **Hypothesis:** caching the identical stable prefix (system prompt + schema + tool definitions) reduces repeated-input cost and latency without changing any judgment (the dynamic header with quotes/positions stays uncached).
- **Variants:** off (live); on (`techniques.tip.prompt_cache` True) - not enabled.
- **Eligible setup:** every analyst-family loop call. **Unit:** one provider call. **Episode identity:** run id + call index.
- **Primary metric:** `usage.cacheRead` / `cacheWrite` tokens per call, billable cost from `llm.rates`, latency; judgments must be unchanged (the header is outside the cache).
- **Costs:** the calls themselves; a cache write is billed above the input rate - measured, never assumed.
- **Regime:** `analyst.cacheable_request`, `tools/tip_llm_cost.py`; knobs `techniques.tip.prompt_cache`, `llm.rates`.
- **Evaluation window:** step 1 = the bounded side-effect-free PILOT in `research/2026-09-17-prompt-cache-pilot-plan.md` (harness EXECUTABLE since 2026-09-17 late: `tip_frozen replay --cache on|off --budget-usd 8`, enforced ceiling incl. retries, per-attempt accounting, prefix ~5.3k vs header ~20.4k tokens measured on the bundle; dry run demonstrated at $0; warm-up counted, prefix hashes checked, judgments compared) - runs only on the user's approval; step 2 (a measured session) only if the pilot is favourable and approved. **Decision rule:** the user decides on measured hits, priced cost incl. warm-up, and latency; recap routing stays OFF and is a separate experiment.
- **Status:** built, off; pilot plan awaiting approval (2026-09-17).

## `review-gate` (opened 2026-09-19, OBSERVE)

- **Hypothesis:** an intake review can only manage an item the desk holds, arms or proposes; skipping reviews of messages that reach none (and are not entry-shaped) removes about a third of review spend without losing a management action.
- **Variants:** observe (live: `TipReviewGate` journaled, the review still runs); enforce (skip) - not enabled.
- **Eligible setup:** every intake message on the review path (a discarded signal, or a no-ticker follow-up). **Unit:** one intake message. **Episode identity:** intake run id.
- **Primary metric:** false negatives = skip-decisions whose review called `update_exit_plan` / `close_position` / `disarm_plan` (must be 0); secondary: skipped share and priced review cost (`llm.rates`, an estimate).
- **Costs:** none in observe; enforce removes the skipped reviews' cost.
- **Regime:** `techniques/tip/review_gate.py`, `signals/service._review_gate`, `tools/tip_review_gate_eval.py`; knob `techniques.tip.review_gate`.
- **Alternatives tried:** the existing source-level open-items check (shadow signals never expire, so nearly every active source always passed it).
- **Evaluation window:** retrospective 2026-09-09..18 on the same evidence: 186 of 556 reviews skipped, $121.83 of $379.21 (32%), 0 false negatives; prospective = 5 observe sessions (2026-09-21..25, `tip_review_gate_eval --prospective`). **Decision rule:** a REVIEW checkpoint, never an automatic switch - 0 management false negatives (prospective AND retrospective) are necessary, and a human reads the skipped corrections / new entries / mixed messages / deferred actions; sessions are counted after the actual deployment (0.8.23, 2026-09-19 12:47 ET; first observed session 2026-09-21); the user approves any switch. ECON-03 (2026-09-19): absent or unrestored desk components always review.
- **Status:** built, observe (2026-09-19).

## `target-execution` (opened 2026-09-22, DESIGN ONLY - not activated)

- **Hypothesis:** exiting a ladder rung at an executable quote touch or with a resting reduce-only limit captures more of a touched target than the current closed-bar decision + marketable limit at the bid.
- **Variants:** current (bar-touch on the 15m close, limit at the seen bid) = live; quote-touch; resting limit - both hypothetical, described in `research/2026-09-21-target-execution-design.md`.
- **Eligible setup:** every target rung of a managed tip position. **Unit:** one rung. **Episode identity:** position id + rung.
- **Primary metric:** target-to-fill shortfall per rung (scorecard v4 trail: first touch, decision, order, fill) and the reversal rate (touch then close below target).
- **Costs:** none; observation from the scorecard trail. **Regime:** `friction.target_to_fill`, scorecard v4 `target_exits`.
- **Decision rule:** a Practice-only, per-technique policy decision on the measured distribution, with rollback; never a bug fix. One case (VKTX $11.83) decides nothing.
- **Status:** collecting the trail.

## `friction-exposure` (opened 2026-09-22, DIAGNOSTIC)

- **What:** all-in friction (entry fees + exit fees at the same basis + quoted spread) and same-underlying exposure on every open position (scorecard v4); fill records carry decision / submission / fill-time quotes apart.
- **Boundary:** no friction threshold; no size change; lower-friction expressions at equal risk stay research (`tip_feasibility replay`).
- **Status:** collecting.

## `review-model-eval` (opened 2026-09-19, PREPARED - no paid run)

- **Hypothesis:** a cheaper model can do the INTAKE REVIEW (not the appraisal) without missing a management action; note-only reviews are ~80% of review spend.
- **Variants:** production model (recorded baseline) vs `claude-sonnet-5` vs `claude-haiku-4-5`, each on the exact captured request; tools served from the case; a management tool is a recorded PROPOSAL, never executed.
- **Eligible setup:** an intake review captured with `techniques.tip.review_capture_context` on (exact header + system). Reviews before capture are NOT replayable (request not kept). **Unit:** one review. **Episode identity:** intake run id.
- **Primary metric:** missed OR changed management instructions (must be 0 - the instruction is compared: target, stop levels, targets, fractions, sale fraction, hold cap), invalid replies on management/correction cases (0), missed-entry flag agreement; extra actions reported apart, never netted; a replay that asked for evidence the case does not hold is INCONCLUSIVE, never a pass (rev 2, 2026-09-19: no substitution of another request's output).
- **Costs:** $35 estimate-based spending GUARD, not a guaranteed maximum (`review_frozen.SuiteBudget` - one durable write-ahead ledger across models, cases, turns, retries and invocations; reservations are estimates and actual billing can exceed one; the final bill can end above $35 by at most one attempt's overrun). Paid execution stays unapproved until the captured cases are ready AND the user decides whether to accept that limitation, 60 stratified cases (20 management / 10 missed-entry / 8 correction / 6 mixed / 16 note-only), one pass per model; plan `economics/review-model-evaluation-plan.md` (`tip_review_gate_eval --model-plan`). Candidate list prices live in the tool, not in `llm.rates`; re-verify on the approval day.
- **Regime:** `techniques/tip/review_frozen.py` (`case v2`).
- **Decision rule:** a paid run needs the user's approval; a result can only open a discussion - the production model changes on a user decision, never automatically. One pass does not measure run-to-run variance.
- **Status:** prepared; capture knob default OFF.

## `feasibility-annotate`

- **Hypothesis:** annotating every TAKE with the expression's feasibility and payoff (without downgrading)
  reduces unfittable option purchases over time; downgrade mode is not enabled.
- **Variants:** annotate (live); downgrade (not enabled).
- **Eligible setup:** every analyst TAKE on a live run. **Unit:** one analyst run. **Episode identity:** analyst run id.
- **Primary metric:** share of takes that fit >= 1 unit; unit risk vs budget; later, realised outcomes by
  feasibility verdict.
- **Costs:** as booked; the execution-cost diagnostic (`execcost-v1`) is on the record from 2026-09-16.
- **Regime:** `feasibility-v1`, `payoff-v1`, `execcost-v1`; knob `analyst_feasibility_gate` = annotate.
- **Alternatives tried:** none.
- **Evaluation window:** opened 2026-09-15; closes on the reviewer's decision. **Decision rule:** downgrade only
  on a reviewer verdict.
- **Status:** collecting.

## `prompt-cache-conversation` (opened + measured 2026-09-23, ADV-03)

- **Hypothesis:** caching through the last message of each turn (not only system + tools) removes most of the
  re-sent input on a multi-turn review without changing the reply.
- **Variants:** `prompt_cache_scope` = prefix (production) vs conversation. **Unit:** one captured review, replayed.
- **Result:** 4 captured 3-turn reviews, $2.39 off vs $1.20 on = **-49.8%** (`tools/tip_cache_pilot.py`; $3.58 of a $10
  estimate-based guard). Caching changes cost only; reply agreement was not the metric and is not claimed.
- **Decision rule:** activation is a user decision; proposed for after the 09-25 five-session report so the
  observation window is not disturbed. Rollback = the knob back to `prefix`.
- **Status:** measured; production stays `prefix`.

## `review-context-compact` (opened + REJECTED 2026-09-23, ADV-04)

- **Hypothesis:** a review needs only rule headlines, pending-rule titles and ticker/source-scoped notes.
- **Variants:** full header (73.6k chars) vs compact (16.4k chars), same model, same captured requests.
- **Result (8 captured reviews, $3.84, `tools/tip_context_compare.py`):** full arm agreed with the recorded
  review 4 times, compact 1; compact was inconclusive 6 times, turned a `close_position` into an `update_exit_plan`
  and missed a `disarm_plan`. **Unsafe - rejected.** A future attempt keeps the full rulebook and trims notes only,
  and must pass the same comparison with no lost management action.
- **Status:** closed; knob `review_context` stays `full`.

## `overnight-carry` (opened 2026-09-23, ADV-09, observation only)

- **Hypothesis (A2):** holding short-dated long options overnight loses money.
- **Measure:** bid-to-bid 15:50 -> next open from the hold study (`tools/tip_overnight_study.py`), by DTE bucket.
- **First pass (to 2026-09-22):** 0-7 DTE n=5 +$447 (median +15.4%), 8-30 n=4 +$17, 31+ n=6 -$23, shares n=10 +$322;
  11 pending. **The hypothesis is not supported** - the losing class is exits on the opening quote, not the carry.
- **Decision rule:** no rule from n < 20 per bucket; the follow-up study is the opening-exit comparison.
- **Status:** collecting.

## `source-review-budget` and `book-exposure-caps` (built 2026-09-23, ADV-05/06, OFF)

- Per-source daily review budget (`review_source_budgets`, `{}` = off; only gate-irrelevant messages are skipped,
  journaled `sourceBudget`) and book / single-name exposure caps (`max_book_exposure_pct`, `max_name_exposure_pct`,
  0 = off; refuse new entries only). Values are a user decision; no evidence window is claimed for either.

## `extraction-model-ab` and `review-model-ab` (2026-09-23, cost levers 2 + 4) - REJECTED

- **Extraction** (40 messages, $4.39, reference Opus 5): Opus 5.5 changed 1 actionable signal (dropped an expiry),
  Sonnet 5 changed 3 (two real calls read as non-actionable). Both fail; extraction stays Opus 5.
- **Reviews** (8 of 15 cases before a host low-memory stop, $4.75, reference Opus 5.5): missed-or-changed management
  2 (reference) vs 4 (notes-only trim) vs 5 (Sonnet 5). Both fail; review context stays full.
- Tools: `tools/tip_extraction_ab.py`, `tools/tip_review_ab.py` (`--rows` saves each case). Record:
  `2026-09-23-cost-levers.md`.

