# Proposal (revision 4): Lane A — long daily-base breakout, one setup, one entry mode

Status: revised 2026-09-18 after the reviewer's findings on revision 1 (d7c226b). Verdict on
revision 1: proceed with evidence and diagnostic corrections; revise the strategy proposal
before activation. Nothing here is implemented as strategy; no setting, arm or runtime changed.
Evidence: BOTTLENECKS.md (with the D1 probe results); gates: FUNNEL.md; provenance of every rule:
RULE-MATRIX.md; reproduction: README.md.

Reviewer decisions incorporated:

- **1.5R planning rule**: measured against trigger-to-reviewed-invalidation; an *engineering
  interpretation* of the S14 checklist, built as an **inactive experimental filter** whose effect
  is reported before any activation. Executable entry R and option dollar risk are identified
  separately on every record.
- **Spread**: the 20% mid-basis limit stays. Diagnostics add absolute spread and quantity-adjusted
  dollar cost (QS: $0.53 = $106 for the two preflight contracts, before fees). Any alternative
  limit needs its own frozen comparison.
- **PWR chronology**: confirmed — contract refusal first (01:39:51Z, lowest otherwise-eligible
  ask $24.40 vs $5.00), missing-minute readiness 15:45:04Z, unverified provenance 15:46:05Z.

## 1. Why one lane

Four sessions of records show the pipeline works mechanically (APA filled; QS signalled and was
refused for a real, measured reason) and that most non-trading is explained by things that are
not entry thresholds: no contract passing all configured limits for high-priced names, a
baseline rule interacting with the provider's minute semantics, planning that admits setups with
almost no structural room, and bearish sessions on which the less-documented short side was the
only side. A narrow long lane tests the source-supported core on days it applies, on one
denominator, without touching the bearish path, the Moderate experiment or the research panels.

## 2. Lane A definition

**Direction and market.** Long only. Strict bullish alignment (S02): SPY and QQQ both closed
above their 8/21/50 EMAs on the latest completed session. On other sessions Lane A plans nothing.

**Setup `base_breakout` (one family).** A 10-session daily base (engineering window, unchanged)
whose ceiling was tested at least twice within 0.5% (S02 "repeatedly rejected resistance"; the
touch count exists today only for `ascending_triangle`), with the existing context gates
unchanged (8-week context, within 15% of the weekly high, relative strength vs SPY, base volume
≤ 0.8× prior, base range ≤ 15%, price above 21/50 EMA, screen profile `september_2026`). Trigger
= base ceiling; reviewed invalidation = base low. Other families are not planned by Lane A.

**Targets and room.** First target = nearest confirmed daily pivot above the trigger; Fibonacci
fallback off in Lane A (a candidate with no confirmed pivot is recorded `no_confirmed_target`,
not planned). `lane_a_min_planning_r` (default **null = inactive**): when set, first-target room
must be ≥ that multiple of (trigger − reviewed invalidation) at planning. The record always
carries `structuralR` (this basis), the later `executableR` (confirmation close vs actual stop)
and `optionRiskUsd` (full debit × quantity) as three separate fields. The current 0.5% distance
floor stays active until the experimental filter has been measured (§4).

**Contract feasibility (provisional, retryable; D2).** Before ranking, each context-passing
candidate gets a `contractFeasibility` record computed from the newest available chain
observation, using the *effective* limits: saved `contract_policy`, account-currency premium
budget, equity × risk% cap, contract multiplier and FX — never hardcoded dollars. States:
`affordable` (a contract passes every configured limit), `over_budget` (a contract passes every
limit except premium), `spread_blocked` (passes except spread), `unknown_stale` (no chain
observation newer than the configured horizon). Each state carries the observation time, the
lowest otherwise-eligible ask and the contract inspected. Ranking prefers `affordable`, then the
rest in the existing order; **nothing is excluded**: `over_budget`/`spread_blocked`/`unknown`
candidates remain `awaiting_contract` and are re-checked by the pending watcher within the
existing refresh budget, exactly as today. Correction to revision 1: pending contracts do not
consume focus slots (capacity counts occupied arms and positions); they consume the
25-candidate checking budget and watcher work, which is the bottleneck this addresses.

**Entry.** Unchanged: 15-minute closed bucket, crossing from below, volume ≥ 1.5× the same-slot
baseline, close location ≥ 0.70, never-chase ≤ 0.5R, executable R ≥ 0.25, closing bucket excluded,
trusted minutes required.

**Stop.** Unchanged for execution: `session_extreme` at confirmation (D7). Two observation
variants are recorded per Lane A signal, both labelled and neither executing: (a)
`hindsight_daily_low` — the completed breakout day's final low, explicitly a hindsight-only
diagnostic that protected nothing from entry; (b) `close_switch` — session-extreme stop from
entry until the close, then the completed daily candle's low from the close onward. Outcomes are
compared only from the close onward for (b); (a) is never compared as protection.

**Sizing, contract, exits.** Unchanged (budget $500, risk 10% of the book, full debit as risk,
DTE 21–90 target 45, delta target 0.5 floor 0.25, spread ≤ 20% at selection and submission,
reselection within limits, `september_2026` exits with `whole_contracts_v2`). Known consequence
kept visible: a one-contract fill has no trim rung and no breakeven move; Lane A reports the
share of single-contract fills.

**Refresh and expiry.** Unchanged: executable in the first session only; an unfilled plan
expires at the close and the next preparation rebuilds any still-valid setup from fresh daily
bars. Each expired Lane A plan records `expiredWithoutSetup` (trigger never reached) or
`expiredAfterRefusal` (a bucket crossed and was refused, with the refusal reasons), so expiry
is never read as the cause of a miss.

## 3. Coexistence and capacity (contract)

Lane A **supplements** the existing long planner inside the same preparation run; it does not
replace it and it changes nothing on sessions where strict bullish alignment is absent (the
existing planner, the Moderate experiment and the bearish path run exactly as today).

- **Disabled path.** `lane_a_focus` defaults to **0**. At 0 the Lane A reviewer is not invoked,
  no Lane A candidate is produced, ranking is the existing ranking unchanged, and no Lane A
  chain fetch or feasibility computation happens. The only observable difference is the
  setting's presence.
- **Same pass.** Discovery, screen and context are shared. With `lane_a_focus > 0` the Lane A
  reviewer runs over the context-passing pool beside the existing `automatic_review`.
- **One plan per symbol per session.** If both reviewers qualify a symbol and Lane A has a free
  slot, the Lane A plan is taken and records `alsoQualified: general`. If Lane A has **no free
  slot or the Lane A plan is not executable** (no confirmed target, feasibility not `affordable`
  at arming time, readiness refused), the symbol **falls back to the general plan** exactly as
  today, recording `laneA: {qualified: true, taken: false, reason}`. A symbol already armed,
  pending or held is `already_managed` for both reviewers (existing rule).
- **Slots.** Lane A plans are ranked first up to `lane_a_focus` (proposed 2 of the shared 5),
  then the existing ranking fills the remainder. Only **armed** Lane A plans and held positions
  count toward `lane_a_focus` and toward the shared capacity — the same occupancy rule as today.
- **Pending stays pending.** An `awaiting_contract` Lane A item remains pending and retryable by
  the pending watcher within the existing budget; it is never classified held/managed and never
  reserves a slot implicitly. When a pending Lane A item becomes armed, the general plan for
  another symbol is not disarmed to make room; capacity is checked at that moment as today.
- **Feasibility states** (extended so every fresh-chain outcome is named): `affordable` (a
  contract passes every configured limit), `over_budget` (fails premium only), `spread_blocked`
  (fails spread only), `filtered_other` (every inspected contract fails delta, DTE, OI or two or
  more filters; the first-failing-filter counts are recorded), `no_chain` (provider returned no
  expiries in range or an error) and `unknown_stale` (no chain observation newer than the
  configured horizon). Each carries the observation time and the lowest otherwise-eligible ask.
- **Lane identity** is snapshotted on the analysis run (`config.lane`), the plan snapshot, the
  arm config, the order tags (`cartel_lane:A`) and the managed position's `config.extras`, so
  fills and held positions can be attributed to the lane after the fact.

## 4. Evaluation and acceptance

**Causal snapshot per input.** Every Lane A decision cites, per input: source time (the bar's
session or the quote's `source_ts`), availability time (when the process observed it:
`historyObservedAt`, chain observation time, quote `available_at`) and the decision cutoff it
was judged against. A preparation run's `created_at` is not an availability time for data
fetched later in the run. Historical comparisons name missing point-in-time evidence as
`unknown` (planning-time chain quotes were not stored before 2026-09-16, so feasibility for
earlier sessions is `unknown` — accepted by the reviewer); such candidates stay in the
denominator, evidence coverage is reported per stage, and conclusions stop at the last
supported stage. No armed, filled or profitable outcome is ever inferred for them. The
evidence tool's replay comparison shows why this matters: the stored tape's minute values
differ from the arm's last saved minutes in most minutes (revised bars), so a stored-tape
replay is a consistency check, not a reconstruction.

**Denominator.** All discovered listings of a session. Before/after = Lane A's planning re-run
over the frozen rows and analysis inputs of the existing preparation runs, order-free, per session:
discovered → context-passed → Lane A setup → (experimental 1.5R) → feasibility state → armed →
crossed → confirmed → filled → outcome, with the first blocker for every drop.

**Examples, separated by role.**

| Role | Cases | What they establish |
|---|---|---|
| Lane A acceptance (must be complete, dated, long base) | App history: CPRT 2026-09-09 `base` (arm disarmed), DRAM 2026-09-09 `base` (expired), CVNA 2026-09-10 `base` (disarmed), NOV 2026-09-14 `base` (disarmed) — frozen inputs exist. Source-dated: S01 OSCR flat-top base and MU/SNDK (Sept 2026 images); S06 HOOD (entry 2025-05-07, trigger 48.80, stop 48.32) | whether the Lane A definition (≥2 ceiling tests, confirmed pivot) qualifies them is an **outcome**, not a requirement; no retrospective tuning to make an author example pass |
| Failures and ordinary controls (long) | bases in the frozen 09-08/09-09/09-10/09-14 long sessions that qualified and then broke or never triggered (e.g. CMG 09-09 flag, SPCX, ZIM) | invalid or non-triggering cases stay rejected or unfilled for explicit reasons |
| Legacy execution control | APA 2026-09-14 (`inside_day`, Fibonacci targets) | unchanged execution path still confirms at 09:45 ET with 1.97× / 0.92 and the same stop; **not** a Lane A qualifier |
| Diagnostics-only (bearish, not lane acceptance) | QS 09-16 (spread refusal, $106 for 2 contracts), TTWO 09-17 (no contract passing all limits; volume 1.01×; target passed), PWR 09-17 (contract first, then minutes), APTV 09-16 (volume 1.32×), APTV 09-17 (no setup) | exercise the diagnostics, the feasibility states and individual filters; say nothing about a long-only lane |

**Acceptance criteria.**

1. Qualifying Lane A examples reach entry with suitable data and contracts in the frozen replay,
   or the record names the exact gate and evidence time that stopped them.
2. Invalid examples remain rejected for explicit reasons; the diagnostics-only cases reproduce
   their recorded refusals through `zargar.tools.cartel_evidence replay` (decision-time tape).
3. Gaps, restarts and late observations cannot manufacture historical entries: focused tests
   `test_options_cartel_entry.py`, `test_options_cartel_pending_integrity.py`,
   `test_options_cartel_state.py`, `test_options_cartel_recovery.py` stay green on this desk's
   database (`zargar_test_cartel`), plus one new case per D1 class (§5).
4. Funded quantities, quotes, costs and exits are coherent: each fill records quantity, fill vs
   quote at signal time, absolute and dollar spread cost, fees, the reachable exit ladder for
   that quantity and the stop rule in force.
5. Before/after on the same denominator and a later holdout: the frozen replay is the "before"
   (current rules) and "after" (Lane A rules); the holdout is the first 20 Lane A Practice
   sessions after activation with no parameter changes. Twenty sessions is a checkpoint.

No daily trade quota. No profitability statement from underlying movement.

### 4b. Frozen replay result (revision 4, 2026-09-18, order-free, `zargar.tools.cartel_lane_a_eval`)

Population corrected per review: for each session the **original** preparation run of the Options
Cartel Practice book (earliest run with a known market read that evaluated the universe) and
**every frozen analysis it evaluated or reused** (analyses parented by that run plus the analyses
its rows cite — a resumed run reuses analyses an earlier run created). Lane A's own gates are
applied to every analysis; the old planner's row/shortlist status is reported beside the verdict,
never used as the denominator. Later runs of the same session are lineage ("later recovery") and
never change original-time eligibility. Files: `lane-a/frozen-replay-strict.md` (Lane A's
definition), `lane-a/frozen-replay-moderate.md` (information-only variant), both with JSON.

| Session | Original run (UTC) | Market strict / Moderate | Population | Strict: Lane A qualified | Moderate variant: qualified (exp. 1.5R passes) | Old planner: candidates / rejected after context passed / armed |
|---|---|---|---|---|---|---|
| 09-08 | `4f312571` 04:40 | long / long | 58 analyses (+3,032 `prefiltered` by the then-strict industry gate, no history fetched) | 0 (SPCX, ZIM: ceiling tested once) | 0 | 2 / 0 / 1 |
| 09-09 | `02b8a8bb` 03:37 | mixed / mixed | 3,080 | 0 (direction) | 0 (the 04:42 rerun read Moderate `long`; that is later recovery, not original-time) | 31 research-only |
| 09-10 | `33e2a508` 04:27 | mixed / long | 3,081 | 0 (direction) | **5** (ABUS 0.46R, BGC 0.14R, CVNA 0.06R, FUTU 1.09R, GROY 0.07R) — 0 pass 1.5R | 14 / 3 / 4 |
| 09-11 | `a973b3a4` 04:49 | short / short | 3,077 (2,554 reused from earlier runs) | 0 (direction) | 0 | 34 / 9 / 5 |
| 09-14 | `98bd007f` 09-13 02:14 | mixed / long | 3,075 | 0 (direction) | **1** (OII 0.27R) — 0 pass | 11 / 3 / 3 |
| 09-15 | `072d5e98` | mixed / mixed | 3,070 (2,013 reused) | 0 (direction) | 0 | 9 research-only |
| 09-16 | `ed6d9da2` 02:26 | short / short | 3,062 | 0 (direction) | 0 | 29 / 13 / 5 |
| 09-17 | `cee03dd7` 01:11 | short / short | 3,056 | 0 (direction) | 0 | 13 / 2 / 1 |

Stage breakdown where the market read allowed long planning (Moderate variant, 09-10 / 09-14):
screen 2,755 / 2,778; context 309 / 283; `base` ceiling tested once 10 / 10; distance floor 2 / 1;
no confirmed pivot 0 / 2 (NOV, SXC); qualified 5 / 1. Every qualified base had a **confirmed pivot
0.5–2.2% above the ceiling** (FUTU 10.0% apart), so the inactive 1.5R experiment would have
excluded all six. Hypothetical feasibility of the six under the saved limits and the effective cap
($5.00, bound by the policy; equity $10,000 at the run): CVNA `affordable` from the 09-09 snapshot
(failure sets recorded for every inspected contract), the other five `unknown_stale` (no nightly
snapshot for the previous session).

What this establishes and what it does not:

- Under **strict** alignment Lane A would have planned nothing in these eight sessions. The only
  strict-bullish read was 09-08; every long arm the current rules made (APA, CGNX, NOV, CPRT,
  CVNA, COIN, EL, SPCX, …) came from the Practice Moderate read on sessions strict called `mixed`.
- The old planner also **rejected after context passed** 3–13 names per session (`old_planner_rejected`);
  those are now in the population and judged by Lane A's gates, which is what the review asked.
- Among long context-passing bases, the single added source-backed requirement (a ceiling tested
  twice) removes about two thirds; the rest carry a confirmed pivot very close above. This is a
  measurement about the target algorithm meeting this sample — first resistance versus a
  meaningful campaign target — not a verdict on the author's method and not grounds for skipping
  the nearest pivot (reviewer's answer: keep nearby resistance visible; any farther-target study
  distinguishes first resistance / first trim / campaign target under a frozen definition of
  significant resistance and reports the obstacles crossed).
- Nothing here is an entry, fill or outcome; feasibility is hypothetical under the stated
  assumptions (date-only nightly snapshots, saved limits, effective cap); `unknown_stale` rows stay
  in the denominator and no later stage is inferred. Neither a farther-target rule nor the 1.5R
  filter is justified by these results.

## 5. Incremental plan

Status 2026-09-18 (revision 4): **D3, D4 and D5 are built as diagnostics** and corrected per review
(D4 registry keyed by plan and session, eligibility-aware, pruned and bounded, duplicate delivery
counted apart, persistence failures isolated; the collector's studies run on one bounded worker,
which limits concurrency but cannot cancel a running study). **The pure Lane A reviewer,
feasibility classifier and frozen replay are built and corrected** (complete population and
lineage, all failure sets preserved, single-cause states reserved for single failures, saved
limits and effective cap, hypothetical labelling). Nothing on the preparation, arming or entry
path imports them. D1 remains at "classification recorded"; D2, S1–S3, R1 and any production
change wait for review.

Reviewer answers folded in (2026-09-18):

- **Volume eligibility (D1):** a versioned **field-specific eligibility matrix**, not one exclusion
  list: per tape and condition combination, which fields (open/high/low/close/volume) a trade may
  update for minute and for daily aggregation, strictest applicable rule for multiple conditions,
  validated against the provider's own bar output before any use; historical and live buckets on
  the same basis, explicit late-correction handling, no double counting; offline first.
- **D3 decision bundle:** persist inputs **and** a hash. A bucket alone is insufficient — crossing
  depends on the previous bucket's state and the session-extreme stop on earlier minutes. The
  bundle per distinct decision: bucket input values with provenance; previous crossing/retest
  state and `observeAfter`; plan/policy and baseline versions; decision cutoff and available
  observation times; the session context used for the stop as an immutable reference (one
  session tape object per plan-session, referenced by hash, not copied per tick).
- **APA's 15-minute arm tape:** no trimming operation exists; the observer accepts decision bars
  only while the arm is `armed` and `waiting`, and APA signalled in the first bucket, so the tape
  stopped growing at the signal. Entry evidence should be preserved independently of mutable arm
  state (part of the D3 bundle).
- **Targets:** the nearest pivot is never skipped to manufacture a higher R; any farther-target
  study is offline, distinguishes first resistance / first trim / campaign target, and reports the
  obstacles crossed.

**D — data and diagnostics (no strategy change)**

- **D1 Missing-minute classification and a separate, versioned volume calculation.** Probe
  results (BOTTLENECKS §8b, boundary-enforced rerun): every probed absent minute had trades —
  none verified as no-trade. Classes: `verified_no_trades` (complete bar and trade pagination,
  zero trades inside [start, end)), `trades_without_bar` (trades inside the minute, no provider
  bar), `incomplete_evidence` (bar or trade pagination not exhausted, error, feed mismatch);
  unprobed minutes are `unknown`. Requirements: same feed (`sip`) for bars and trades, complete
  pagination, [start, end) boundaries enforced locally (the provider's `end` is inclusive),
  trade conditions recorded and interpreted only per the provider's documented aggregation
  rules, per-interval verification completion time, a credential-free artifact per run.
  Per the reviewer's answers: **execution behaviour is unchanged**; neither "exclude all odd
  lots" nor "add odd lots only in missing minutes" is implemented. Instead a **separate,
  versioned volume calculation** (`volume_eligibility_v1`) is evaluated **offline first**, applying
  the same documented eligibility rules to historical and current buckets, with double-counting
  prevented by construction (trade-tape volume is used only for minutes that have no emitted
  bar; minutes with a bar keep the bar's volume). Buckets containing `trades_without_bar` minutes
  stay **non-executable** under the present policy. The offline comparison specifies separately:
  eligible opening and closing prices, high/low, volume, empty boundary minutes, and
  session-extreme coverage — changing what the session extreme covers would change a trading
  protection and is not proposed. A constructed minute is never labelled `exchange`. Late
  corrections stay context-only and never create a retroactive entry (existing `observeAfter`
  boundary). Roll-out order: classification recorded (diagnostic) → offline comparison tables →
  review → only then any production change, each with its own rollback.
- **D2 Provisional feasibility** as in §2: compute, record, rank; never exclude.
- **D3 Measurements on every refusal** (`untrusted_confirmation`, `missing_bucket`): the known
  partial values and the fields not computed, as the evidence tool now shows.
- **D4 Confirmation latency and dropped bars**: the observer drops bars older than 120 s without
  a record; add a per-plan counter and journal it; bound the profitability collector's per-tick
  work. Current measured latency of journaled decisions is in BOTTLENECKS §9.
- **D5 Spread diagnostics**: absolute spread and quantity-adjusted dollar cost beside the percent
  on preflight records and the Armed page.

**S — strategy (Lane A), behind `lane_a_focus`**

- **S1** Lane A reviewer (`base_breakout`, ≥2 ceiling tests, confirmed pivots only, long-only,
  strict market), `lane_a_min_planning_r` inactive, lane snapshot on run/plan/arm/order/position.
- **S2** Expiry reason and single-contract share on Lane A records.
- **S3** The two labelled stop observations on Lane A signals (non-executing).

**R — reporting**: per-session Lane A funnel with first and independent blockers beside
`session_review`; the same numbers the frozen replay produces.

**O — order-free research**: O1 frozen replay 2026-09-08 → 2026-09-17 under Lane A rules; O2 the
5m confirmation variant's effect on first blockers (existing paired sweeps).

**Dependencies.** D1 diagnostic before any baseline change; D2 before S1; R before activation.
**Evidence before Practice activation:** D1 classification results on the blocked set; O1
tables with first blockers; the acceptance cases in §4 reproduced by the reviewer with the
evidence tool; the reviewer's written GO. Activation = `lane_a_focus > 0` on the Options Cartel
Practice book only.

## 6. What this proposal does not claim

That Lane A is profitable; that 1.5R or the touch count are the author's numbers (the ratio is
from a checklist whose basis the author does not state; the tolerance and window are ours);
that absent minutes can be treated as zero volume (the probe says most were odd-lot trades);
that any stop variant would have saved APA. Each is a measurement the plan produces.
