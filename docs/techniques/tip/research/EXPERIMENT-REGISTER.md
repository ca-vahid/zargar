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
- **Primary metric:** paired net $ and R (risk rebased to the sampled size); `managedCarry` apart from
  `carryToNextOpen`; eligible / fresh / missing / late / ineligible counted.
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
- **Variants:** current (full, verbatim); core_only; no_knowledge; compact.
- **Eligible setup:** analyst runs captured with `frozen_capture_context` on (exact manifest), replayed on the
  identical bundle. **Unit:** one bundle x one variant replay; a pair is complete only when every requested tool
  input was served (`coverageLimited` false). **Episode identity:** bundle id + variant + report hash.
- **Primary metric:** verdict / contract / protections equality; input, output and cached tokens; calls;
  latency; coverage.
- **Costs:** paid model calls per replay (recorded in the report usage).
- **Regime:** `techniques/tip/frozen.py`, bundle version 1; knobs `frozen_capture_context` (True), `frozen_variants`.
- **Alternatives tried:** one NVDA pair (`fb-16d3146639a86744`) - coverage-limited, mixed reading, not adopted.
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
