# Proposal: Lane A — long daily-base breakout, one setup, one entry mode

Status: proposal for review, 2026-09-17. Nothing here is implemented, no setting, arm or
runtime was changed. Evidence: BOTTLENECKS.md; gate map: FUNNEL.md; provenance of every rule:
RULE-MATRIX.md; reproduction: README.md.

## 1. Why one lane

Four sessions of records show the pipeline works mechanically (APA filled, QS signalled and was
refused for a real reason) and that most of the non-trading is explained by four things that are
not strategy rules: contract affordability for high-priced stocks, a baseline rule that
interacts badly with the provider's minute omissions, a planning stage that admits setups with
almost no room (structural R 0.07–0.28), and bearish sessions that put every candidate on the
less-documented short side. Tuning entry thresholds cannot fix any of those. A narrow long
lane lets us test the source-supported core on days it applies, measure it on one denominator,
and leave every other behaviour (including the bearish path) untouched.

## 2. Lane A definition

**Direction and market.** Long only. Strict bullish alignment: SPY and QQQ both close above
their 8/21/50 EMAs on the latest completed session (S02). On any other session Lane A prepares
nothing; the existing short path and the Moderate experiment continue as configured.

**Setup: `base_breakout` (one family).** A daily base of 10 completed sessions (engineering
window, unchanged) whose ceiling has been **tested at least twice** within 0.5% (S02:
"repeatedly rejected resistance"; today this touch count exists only for `ascending_triangle`),
with the existing context gates unchanged: 8-week context, within 15% of the weekly high,
relative strength vs SPY, base volume ≤ 0.8× prior, base range ≤ 15%, price above 21/50 EMA,
screen profile `september_2026`. Trigger = base ceiling; reviewed invalidation = base low
(current `base` geometry). Families other than `base` are not planned by Lane A.

**Planning room (new, source-supported).** First target = the nearest **confirmed** daily pivot
above the trigger (no Fibonacci fallback in Lane A). Require first-target room ≥ 1.5 × (trigger
− invalidation) at planning (S14's ≥ 1.5:1 checklist; basis recorded as "first target vs
trigger-to-invalidation"). This replaces the 0.5% distance floor for Lane A and would have
excluded every 09-16/09-17 candidate below R 1.5 (QS 0.61, TTWO 0.28, PWR 0.075, AAP 0.20,
HIMS 0.31) while keeping APA (1.80) and APTV 09-16 (1.71). It is a planning rule; the
executable ≥ 0.25R check at confirmation stays as a safeguard.

**Contract feasibility before ranking (new ordering, no new limits).** Before ranking the pool,
read the nightly `option_chain_snapshots` (or the CBOE delayed chain) for each context-passing
candidate and compute `affordableContract`: an option with DTE 21–90, |delta| ≥ 0.25, OI ≥
100, spread ≤ 20% and ask ≤ min($5, budget/100) exists. Candidates without one are recorded
(`unaffordable`, with the lowest otherwise-eligible ask) and **excluded from Lane A ranking**.
Limits are unchanged; only the order changes. On 09-16/09-17 this would have removed NVT, REAL,
PWR ×2 and TTWO from the shortlist before they consumed slots or watcher time.

**Entry.** Unchanged: 15-minute closed bucket, crossing from below, volume ≥ 1.5× the
same-slot baseline, close location ≥ 0.70, never-chase ≤ 0.5R, executable R ≥ 0.25, closing
bucket excluded, trusted minutes required.

**Stop.** Unchanged for execution: `session_extreme` at confirmation (D7). The daily-candle-low
reading of S02 (stop known only at the close) is recorded as a **non-executing paired
observation** on every Lane A signal (existing `sweeps.py` / frozen-capture machinery), so the
two stop rules are compared on the same signals before any change is proposed.

**Sizing, contract, exits.** Unchanged: budget $500, risk 10% of the book, full debit as risk,
DTE 21–90 target 45, delta target 0.5 floor 0.25, spread ≤ 20% at selection and submission,
reselection within limits, `september_2026` exits with `whole_contracts_v2`. Known consequence
kept visible: a one-contract fill has no trim rung and no breakeven move; Lane A reports the
fraction of fills that are single contracts.

**Refresh and expiry.** Unchanged: the plan is executable in its first session only; an
unfilled plan expires at the close and the next preparation rebuilds any still-valid setup from
fresh daily bars. Lane A adds one report field per expired plan: `expiredWithoutSetup`
(trigger never reached), `expiredAfterRefusal` (a bucket crossed and was refused, with the
refusal reasons), so expiry is never read as the cause of a miss.

**Capacity.** Lane A shares the five focus slots; a Lane A plan is tagged `lane: A` on the run
and the arm so its funnel is countable on its own.

## 3. Which existing checks stay, change, or become lane-specific

| Check | Lane A | Why |
|---|---|---|
| Screen, market strict, industry context, relative strength, contraction | stay | source-backed or measured engineering; no evidence to change |
| Family selection | lane-specific: `base` + ≥2 ceiling touches | one definition to evaluate; S02 trigger definition |
| Fibonacci targets | off in Lane A | engineering anchors; the lane's room rule needs a real pivot |
| 0.5% distance floor | replaced by ≥ 1.5R at planning in Lane A | S14; the floor admitted R 0.07 |
| Contract selection order | affordability computed before ranking | reviewer finding "liquidity considered too late"; no limit changes |
| Baseline / coverage / provenance rules | stay, pending D1 evidence | changing them without verification biases the volume rule (BOTTLENECKS §8) |
| Entry quality, chase, executable R, stop mode | stay | untested variants are measured order-free first |
| Preflight, RiskGate, sizing, halts | stay | safeguards |
| Bearish path, Moderate alignment, research panels | untouched | out of lane; explicitly not disabled |

## 4. Evaluation and acceptance

**Frozen inputs.** Every Lane A decision cites the preparation run id, the daily-history input
hash, the baseline `asOfMs` and the chain snapshot date it read. Availability time is the run's
`created_at`; nothing observed after it may enter a planning decision (existing
`reviewed_execution_plan` rejects post-creation bars).

**Denominator.** All discovered listings of a session. Before/after comparisons re-run Lane A's
planning over the *frozen rows* of the existing preparation runs (2026-09-08 → 2026-09-17,
`technique_runs.mode = preparation`, `rows` and per-symbol analysis inputs), order-free, and
report per session: discovered → context-passed → Lane A setup → room ≥ 1.5R → affordable →
armed → crossed → confirmed → filled → outcome, with the first blocker for every drop.

**Cases (all reproduced with `zargar.tools.cartel_evidence` or the replay tools):**

1. *Intended qualifying examples reach entry with suitable data and contracts.* Source examples
   from `../../EXAMPLES.md` and the S01/S02 image sets (MU, SNDK, OSCR flat-top bases; the
   HOOD contract example) replayed on their own dates; plus APA 2026-09-14 as a live control that
   must still confirm at 09:45 ET with the same measurements (1.97×, 0.92).
2. *Invalid examples remain rejected for explicit reasons.* TTWO 09-17 and PWR 09-17 rejected at
   planning (`room < 1.5R`, `unaffordable`); QS 09-16 rejected at planning (R 0.61) and, if
   armed under the old rules, still refused at submission on spread; APTV 09-17 expires
   `expiredWithoutSetup`; APTV 09-16 refused on volume 1.32× with the reason recorded.
3. *Gaps, restarts and late observations cannot manufacture historical entries.* Existing
   suites stay green unchanged (`test_options_cartel_entry.py`, `pending_integrity`, `state`,
   `recovery`, `catchup*`); one new case: a minute that is absent, then verified empty by D1,
   completes its bucket only from the verification time forward, never retroactively.
4. *Funded quantities, quotes, costs and exits are coherent.* Every Lane A fill records quantity,
   fill vs quote at signal time, fees, the exit ladder actually reachable for that quantity
   (allocation preview) and the stop rule in force; single-contract fills are counted.
5. *Before/after on the same denominator and a later holdout.* The 09-08 → 09-17 frozen replay is
   the "before" (what current rules did) and "after" (what Lane A rules would have planned);
   the holdout is the first 20 Lane A Practice sessions after activation with **no parameter
   changes**. Twenty sessions is a checkpoint, not a promotion.

No daily trade quota. No profitability statement from underlying movement; option outcomes
are reported only from actual Practice fills and marks with provenance.

## 5. Incremental plan

Each step is its own PR, reviewable in isolation, with a rollback that is a setting or a
profile switch. Nothing activates in Practice before the reviewer's GO on the evidence listed.

**D — data corrections (no strategy change)**

- **D1 No-trade-interval verification.** For a minute absent from the Alpaca 1m response (baseline)
  or without a venue bar on the live tape, query Alpaca trades for that minute once; record the
  verdict on the cache provenance (`noTradeIntervalsVerified: true` with per-minute results)
  and on the tape minute (`source: exchange`, volume 0, `verifiedEmpty`). Only verified-empty
  minutes count as zero volume in baseline samples and confirmation buckets. Evidence before
  merge: on the 09-17 blocked set, the share of absent minutes that verify empty vs carry
  trades; expected effect on slot counts. Rollback: verification off = today's behaviour.
- **D2 Affordability before ranking** (as in §2): a computed field and an exclusion for Lane A
  only; other profiles keep today's order. Evidence: the 09-16/09-17 shortlists recomputed.
- **D3 Measurements on every refusal.** `untrusted_confirmation` and `missing_bucket` decisions
  record the bucket's crossing/volume/location so a data refusal can be judged afterwards
  (today they record nothing, BOTTLENECKS §6).
- **D4 Loop-stall exposure.** Count and journal bars dropped by the observer for age (>120 s)
  per plan/session; bound the profitability collector's per-tick work (it was attributed a
  stall cluster on 09-16, `docs/techniques/tip/reviews/2026-09-16-tmr-plan-record.md`).
  Evidence: dropped-bar counts before/after on a normal session. Not a platform rewrite.

**S — strategy (Lane A), behind profile `lane_a_base_breakout_v1`**

- **S1** Setup: `base` with ≥2 ceiling touches; Fibonacci off; planning room ≥ 1.5R; long-only,
  strict market. Pure functions with unit tests on synthetic and real frozen rows.
- **S2** Lane tagging on runs/arms and the per-plan expiry reason.
- **S3** Non-executing paired stop observation (daily-candle-low) on Lane A signals.
  Rollback for S1–S3: select the previous profile; existing arms are untouched.

**R — reporting**

- **R1** Per-session Lane A funnel with first blocker and independent blockers, persisted
  beside `session_review` and shown on Plans; the same numbers the acceptance replay produces.

**O — optional research (order-free)**

- **O1** Frozen replay of 2026-09-08 → 2026-09-17 under Lane A rules (the "before/after").
- **O2** Whether the 5m confirmation variant changes the first-blocker distribution (existing
  paired sweeps) — observation only.

**Dependencies.** S1 does not depend on D1 (liquid leaders pass today's coverage rule), but
Lane A's universe is materially larger with D1. D2 before S1 so the first Lane A shortlist is
not spent on unaffordable names. R1 before activation so the holdout is countable from day one.

**Evidence required before Practice activation.** D1 verification numbers; O1 replay tables
with first blockers; all Cartel suites green on the reviewer's database; the acceptance cases
in §4 reproduced by the reviewer; a written GO. Activation is a profile switch on the Options
Cartel Practice book only; the short path, Moderate alignment and every research panel stay as
they are.

## 6. What this proposal does not claim

That Lane A is profitable; that the 1.5R rule or the touch count are the author's exact
numbers (the ratio is, the touch tolerance and window are ours); that verified-empty minutes
will unblock thin names (D1 may show they carry trades); that a wider stop would have saved
APA. Each of those is a measurement the plan produces, not an assumption it makes.
