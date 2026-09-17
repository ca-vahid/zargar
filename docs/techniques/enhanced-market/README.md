# EM Options (EnhancedMarket) — state of play, doc map, known gaps

*Start here. Dated; the newest entry wins over any older document in this folder. Update this file
whenever a release, an activation or a review changes what is true. Last full refresh: 2026-09-16
09:40 PT (first session on deterministic live entry, mid-session).*

## Doc map

| File | What it is | Currency |
|---|---|---|
| `README.md` | this file: state, what changed, known gaps | current |
| `METHOD.md` | the codified rulebook (numbered rules T1..T5, R1..R6 from the author's book; our extrapolations marked) | current; rule changes are dated in `TRADING-RULES.md` §5 |
| `TRADING-RULES.md` | EM's judgement log: rules under observation (§1), findings (§2), theories (§3), backlog (§4), change log (§5) | current; every claim dated with its evidence |
| `PIPELINE-PLAN.md` | build plan of the analysis pipeline (deterministic facts + vision passes + grounding) and what was learned | as-built history 2026-08-21; build order table kept current |
| `WALKFORWARD-PLAN.md` | session plans, walk-forward validation, live arming (phase 2), Validation tab, decisions | as-built 2026-08-22 with dated corrections; §9 item 3 describes the live fire path |
| `REVIEW-PLAN.md` | the review loop: trace, provenance, outcomes, reviews, replay, `/technique-review` skill | current (applies to premarket plan runs; live fire decisions are journaled events, not runs) |
| `EVOLUTION-PLAN.md` | method evolution loop: variant harness, ingestion, shadow instances; experiment log | current; "Where this stands" dated |
| `INGESTION-PLAN.md` | the author's Discord/video ingestion, board check, auto-arm boundary | current |
| `METHOD-CHANGE-PLAN-2026-09-12.md` | C1..C6 method change plan and verdicts (shares fallback, gap-day wait, liquidity screen) | as-built; verdicts in `TRADING-RULES.md` §5 2026-09-12 |
| `FLOW-CONFIRMATION-PLAN.md` | T-12 flow confirmation: measured and rejected on history | closed 2026-09-09 |
| `METHOD-REVIEW-2026-08-26.md` | the first book-vs-app audit | historical |
| `research/` | frozen profitability cohorts, per-session profitability reports, the order-free source-candidate ledger | current, dated files |
| `reviews/` | external review rounds, delivery responses, release verdicts, adopted regression packets | dated records; latest: `deterministic-final-review/DE-RESPONSE-2026-09-15.md` |
| `notes/` | author video transcripts and feed notes | dated |

## State of play (2026-09-16 evening)

- **PFU-01..04 closed on the branch at `47275c3f8ff02c857b46b431e71b3300ec0eea67` (0.8.02, not deployed):** watchdog classification module (owner: Tips desk, waits for the user), P-04 paired confirmation comparison + P-05 clock/event labels (descriptive), CBOE cooldown setting wired. Closure: `reviews/2026-09-17-PFU-CLOSURE.md`.
- **Sep 17 inventory:** 58 EM arms in EM Practice (86 triggers: 34 long / 52 short), all effective `deterministic`,
  evidence off, from sheet `fc9efd65418e` (111 reviewed, 58 setup, 53 no-setup, 0 arming failures). Live runtime
  v0.7.100 build `172ce1f` (Team2's deploy 18:50 PT); EM follow-ups on the branch at `c74df44`, NOT deployed.
  Six unplanned restarts today (TRADING-RULES §5 "2026-09-16 evening").

## State of play (2026-09-16, daytime)

- **Runtime:** v0.7.96 build `4c84697` since 10:52 ET 2026-09-16, after three unplanned watchdog restarts
  (10:40 to 10:53 ET; a converged checkout had lost the health route's build helper, PLATFORM-RULES 2026-09-16).
  The deterministic-entry release itself was v0.7.95 build `414a86c`, deployed 22:04 PT 2026-09-15 through the
  protocol (readiness safe, `deploy.ps1`, `ZargarRestart` task, restoration 56/56 by id). EM branch:
  `claude/technique-review-trade-plan-fbb9ba`; PR #174 puts it on `main`.
- **Live entry authority is DETERMINISTIC** (`techniques.enhanced_market.fire_decision_mode=deterministic`,
  `deterministic-entry-v1`, user decision 2026-09-15): when a trigger fires, `technique/entry_decision.py`
  judges the tracker's actual transition (saved geometry, the tracker's own window gate, volume and the confirmation
  branch that fired, R3.2, stop intact) in well under a millisecond; no model, no chart render, no timeout on the
  entry path. Every attempt is journaled as `TechniqueEntryDecision` with its frozen snapshot, policy and the last
  240 one-minute bars up to the signal close. Refusals persist as `no_setup` with reason codes. `legacy` is the
  journaled rollback to the awaited critic (`critic_mode` then applies again). The premarket LLM plan builder,
  analyst review and sheet promotion are unchanged.
- **After-close LLM evidence is OFF** (`fire_evidence_mode=off`). When a person turns it on,
  `tools/em_entry_evidence.py run --date` reviews the frozen decisions of a CLOSED session, verifies each record's
  declared identity (input hash, frozen-bar hash and count, cutoff) before rendering or calling a model, and appends
  `TechniqueEntryEvidence` (`authority=evidence_only`). It has no path back to trading.
- **Vehicle:** shares are EM's Practice vehicle when the option is untradeable (`entry_fallback=shares`, C2), sized by
  risk and capped by the book's position caps; the nightly liquidity screen marks the option-tradeable names (C1).
- **Entry chain after an `allow`:** contract pick with next-strike/next-expiry retry, one bounded provider quote
  refresh (`entry_quote_refresh_timeout_s` 2.5 s, EM only), re-price, T5.3/T5.4 re-judgement, risk-based sizing,
  option admission, never-chase cap, R2, final entry guard on the CURRENT quote, RiskGate. Budget bounds refuse before
  any order (F33 daily-loss bound, FIX-03 2% trade budget) and are journaled as `TriggerSkipped`.
- **Exits:** unchanged (stop on bar close, 0.25R quote-breach crash brake, premium stop, ladder trims). Both
  order-free observation knobs are ON for EM Practice by user decision 2026-09-15 14:06 PT
  (`shadow_exit_observe`, `shadow_p02_candidate`): they record `TechniqueExitShadow` candidates and never trade.
- **Rules live:** R6 windows, C3 gap-day wait (R6.6), gap-void, shares fallback, quote refresh. Not adopted after
  sweeps: T-11, T-12, T-13, T-14, C4, C5 (verdicts in `TRADING-RULES.md` §3/§5).
- **First deterministic session, FINAL (2026-09-16, FOMC day; full entry in `TRADING-RULES.md` §5 "2026-09-16 close"):** 11 fires / 11 allow (median 0.4 ms), 4 fills, net -$147.55 (1 winner, 3 quote-breach stops within minutes), 7 refusals (5 budget bounds, 1 not chased, 1 CBOE 429), 0 live model calls; bar close -> order submit median 1.6 s.
- *Interim at 09:40 PT the same day:* 7 fires, 7 `allow` decisions in
  0.25 to 0.92 ms with 240 frozen bars each, bar close to received 44 ms to 3.3 s, bar close to order submit 1.6 to
  2.2 s (legacy was 18 to 23 s); 3 orders, 2 fills (both stopped on the quote breach within minutes), 1 unfilled and
  cancelled (T4.1 not chased), 4 refused by budget bounds before any order; zero EM model calls since the open. The
  full-day read (timing percentiles, fills, profitability by policy) is the after-close measurement:
  `research/profitability/<date>.md` plus the decision timing chain from the journal.

## Measurement and reporting

- `tools/em_profitability.py` (order-free): per-session report beside the frozen cohorts
  (`research/PROFITABILITY-COHORTS-2026-09-15.md`); rows carry policy version, decision id, timing and quote-refresh
  facts; the attempt census comes from every run's immutable fire events, so refused attempts without a trade row are
  counted once per (run, trigger, decision).
- `tools/em_fire_policy_migration.py preview`: read-only effective policy over the stored arms (never writes).
- `tools/em_source_candidates.py`: the author's morning levels as an order-free ledger, evaluated after the close;
  rows never arm.
- The morning tick (session-local cron) reports health, the EM funnel, deterministic decisions and model calls every
  half hour from 06:20 PT.

## Known gaps, risks and what could be wrong

- **One session of deterministic data.** Faster entry is a latency fact, not a profit claim; the qualitative
  judgments the critic used to make (higher-timeframe fakeouts, opposing shelves, divergence, live chop) are recorded
  `not_evaluated` and are NOT encoded. Any such filter is a separate versioned rule with its own sweep.
- **Budget bounds refuse most fires on volatile names:** 4 of 7 fires today were refused by the F33 daily-loss bound or
  the FIX-03 2% trade budget because one contract risks more than the budget. The bounds are correct; the question is
  whether a shares fallback should be tried when the option is affordable but over budget (not built; needs a decision).
- **Quote-breach stops within minutes of entry** (CRCL, CVNA today; several on 09-14/15): the 0.25R crash brake fires
  on the underlying's live quote. Under measurement in the profitability report; no change without a cohort.
- **Watchdog single-probe kills:** a 4 s health timeout during a load stall killed a live engine on 2026-09-16 and
  the loop that followed was a start-path defect. The health route now tolerates a missing helper (PR #174); the probe
  policy belongs to the start-path owner.
- **Timing field for non-1m plans:** `barCloseTs` uses the plan's trigger timeframe, so Tips fires on 5-minute plans
  show a close in the future. Diagnostic only; EM's 1-minute timing is correct. Fix pending on the EM branch.
- **Yahoo 1m depth (~20 sessions)** bounds how late a run can be scored; frozen bars on each decision make the
  after-close evidence replayable regardless.
- **FIX-01 v4 money repair** (`tools/em_reconcile_fallback.py --apply`) remains a human step under its scoped GO.
