# EM model-veto study (2026-09-23)

Read-only study. No database writes, no model calls, no settings or code changes.
Script: `C:/Users/vispe/AppData/Local/Temp/claude/C--Cursor-zargar--claude-worktrees-technique-review-trade-plan-fbb9ba/66ca0c88-13db-45d3-9295-8dee73d70245/scratchpad/veto_study.py`
(run it with the backend venv python; it caches the query in `veto_cache.pkl` next to itself, `--refresh` re-reads the database).

**Question.** Before 2026-09-23 a paid model review (`technique_runs.trigger='promote'`) rejected or approved each
prepared plan. Since 2026-09-23 preparation is rules-only (`preparation_policy.decide`, grade floor B). Live evidence
from 2026-09-22/23 (7 rules-only-admitted trades, all losers, mean -0.98R vs -0.17R) suggested the veto had value.
Does it, on more data, and which kinds of veto reason predict losers?

**Short answer.** On 18 scored sessions (2026-08-25 .. 2026-09-18) the simulator shows **no measurable value in the
model's symbol-level veto**: approved and vetoed eligible triggers have overlapping, zero-straddling confidence
intervals, and in the gap-rules-off counterfactual the vetoed set did slightly better. One reason family (targets /
unanchored 2/4/6% ladder, which in practice means the break triggers) looked predictive of losers in the first 60% of
sessions but did not replicate in the last 40%. No deterministic rule is recommended for activation on this evidence.

## 1. Population and definitions

- Runs: 2,016 `promote` runs with status `done` and `result.analysis.verdict` set (2026-08-22 .. 2026-09-23 created);
  de-duplicated to the latest run per (symbol, planFor) (32 pairs had more than one run).
- Eligible trigger: in `decide(..., analysis=None, policy=effective(deterministic, floor B))['eligibleTriggers']`
  (valid geometry, stop present, targets present, grade A or B).
- Outcome: `technique_outcomes` row `plan_source='trigger:<id>'` for that run, status `scored`. **Filled** = `r_multiple`
  is not null (stopped, tp1, tp2, tp3, horizon). Every other scored outcome (gap_void, invalidated, not_triggered,
  gapped_past, gapped_through, observed, exhausted) = not filled, 0R, excluded from R statistics, counted in fill rate.
- 2,112 eligible triggers had a scored outcome; 365 eligible triggers had **no outcome row** (all plans for
  2026-09-21, 09-22, 09-23 and a few others) - see caveats. Scored sessions: 18.
- APPROVED = run verdict `setup` (the model approved the symbol; the baseline armed its valid triggers).
  VETOED = run verdict `no_setup` (the model rejected the symbol; only rules-only preparation admits these triggers).
  This is the distinction the live 09-22/23 evidence used.
- The literal per-trigger reading of `review_semantics` is not usable as "approval" on `setup` runs: 993 of 1,028
  eligible triggers on `setup` runs carry a "substantive" kept reason (plan-level CRITIC-WARN notes and accepted-with-caveat
  reasons reach every trigger). Only 35 triggers would count as approved, none filled. On `no_setup` runs every eligible
  trigger's veto was `substantive` (0 would-be rescues).
- "Model's chosen trigger" = on a `setup` run, the trigger with the same kind + direction as `analysis.setupType/direction`
  and entry within 1% of `analysis.entry.price` (651 runs matched, ~1 trigger per run).
- Two R sources: the **scored sim** (`r_multiple`, method windows + gap rules as scored) and the **noGapRules
  counterfactual** stored in the same outcome row (`plan.counterfactual.noGapRules.sim`, gap rules off). The gap rules
  void 37% of eligible triggers in the scored sim, so fills there are scarce (81); the counterfactual has 261.
- CI = session-clustered bootstrap of mean R over filled trades (resample planFor sessions with replacement, seed
  20260923, 5,000 draws, 2.5/97.5 percentiles). "-" = fewer than 3 fills or 1 session.

## 2. Headline: approved vs vetoed

Scored sim:

| group | eligible | filled | fill rate | mean R | median R | win | sum R | 95% CI mean R | sessions w/ fills |
|---|---|---|---|---|---|---|---|---|---|
| APPROVED: verdict setup | 1028 | 44 | 4.3% | +0.26 | -0.43 | 43% | +11.36 | [-0.15, +0.81] | 13 |
| - the model's own chosen trigger | 652 | 29 | 4.4% | +0.51 | +0.06 | 52% | +14.68 | [-0.10, +1.16] | 13 |
| - other eligible triggers of a setup plan | 376 | 15 | 4.0% | -0.22 | -1.05 | 27% | -3.33 | [-0.93, +0.60] | 9 |
| VETOED: verdict no_setup | 1084 | 37 | 3.4% | +0.12 | -0.01 | 49% | +4.57 | [-0.24, +0.44] | 15 |
| ALL eligible (rules-only) | 2112 | 81 | 3.8% | +0.20 | -0.09 | 46% | +15.92 | [-0.14, +0.55] | 18 |

noGapRules counterfactual:

| group | eligible | filled | fill rate | mean R | median R | win | sum R | 95% CI mean R | sessions w/ fills |
|---|---|---|---|---|---|---|---|---|---|
| APPROVED: verdict setup | 1028 | 160 | 15.6% | +0.31 | -0.46 | 38% | +50.31 | [+0.02, +0.61] | 18 |
| - the model's own chosen trigger | 652 | 113 | 17.3% | +0.28 | -1.01 | 37% | +31.85 | [-0.04, +0.60] | 18 |
| - other eligible triggers of a setup plan | 376 | 47 | 12.5% | +0.39 | -0.09 | 40% | +18.46 | [-0.08, +0.83] | 15 |
| VETOED: verdict no_setup | 1084 | 101 | 9.3% | +0.41 | -0.11 | 44% | +41.20 | [+0.08, +0.72] | 17 |
| ALL eligible (rules-only) | 2112 | 261 | 12.4% | +0.35 | -0.29 | 40% | +91.52 | [+0.08, +0.60] | 18 |

Reading: the difference approved minus vetoed is +0.14R (scored) and -0.10R (counterfactual); both are well inside
the noise. The vetoed set adds positive sum R in both sims (+4.6R and +41.2R). The "chosen trigger beats the rest of a
setup plan" pattern in the scored sim (+0.51 vs -0.22) reverses in the counterfactual (+0.28 vs +0.39), so it is not
a stable finding.

### By direction, grade, kind (scored sim; counterfactual in brackets as mean R / fills)

| slice | APPROVED fills | APPROVED mean R [CI] | VETOED fills | VETOED mean R [CI] | counterfactual A / V |
|---|---|---|---|---|---|
| long | 24 | +0.30 [-0.20, +0.82] | 14 | -0.06 [-0.62, +0.52] | +0.33/86 vs +0.30/50 |
| short | 20 | +0.21 [-0.42, +1.07] | 23 | +0.23 [-0.16, +0.57] | +0.29/74 vs +0.51/51 |
| grade A | 15 | +0.46 [-0.53, +1.73] | 6 | -0.23 [-1.04, +0.94] | +0.10/71 vs +0.13/12 |
| grade B | 29 | +0.15 [-0.20, +0.42] | 31 | +0.19 [-0.18, +0.49] | +0.49/89 vs +0.45/89 |
| bounce | 23 | +0.33 | 8 | +0.27 | +0.35/83 vs +0.54/38 |
| reject | 15 | +0.41 | 12 | +0.51 | +0.38/66 vs +0.73/35 |
| breakdown | 5 | -0.40 | 11 | -0.06 | -0.40/8 vs +0.03/16 |
| breakout | 1 | -0.28 | 6 | -0.50 [-0.77, -0.24] | -0.01/3 vs -0.46/12 |

The only slice where approved is consistently better than vetoed in both sims is **long** in the scored sim and
**grade A** in the scored sim - with 6 to 15 fills each, and neither survives in the counterfactual. Breakouts lose
whichever side of the veto they are on.

## 3. Veto reasons by family (no_setup triggers)

Taxonomy (keyword/regex, multi-label, applied to each vetoed trigger's KEPT clauses from `review_semantics`; a
trigger can carry several families; every no_setup trigger carried at least 2 families, so "sole family" slices are
empty). Families: `rr` (R2 / reward:risk), `level_quality` (T1.2 single touch, not a key level), `reach_distance`
(far away / never reach / chasing), `chop_range` (R3.2 / sideways / noise), `volume` (T3.3d / R3.1 / surge), `trend_htf`
(higher timeframe / counter-trend / T4.6 / T3.3g), `failed_break` (fakeout / failed / T3.3e-f), `gap_premarket`,
`stop_risk` (stop placement / T4.3 / R1 risk cap), `targets` (T4.4 ladder / unanchored / measured move),
`critic_bookkeeping` (CRITIC / FACTS accuracy / draft), `other`.

Trigger-scoped clauses only (reasons that name the trigger; plan-level reasons excluded):

| family | vetoed triggers | filled (scored) | mean R [CI] (scored) | win | filled (cf) | mean R [CI] (cf) |
|---|---|---|---|---|---|---|
| rr | 879 | 28 | +0.08 [-0.25, +0.38] | 50% | 66 | +0.11 [-0.14, +0.39] |
| level_quality | 556 | 24 | +0.27 [-0.19, +0.66] | 50% | 68 | +0.53 [+0.11, +0.87] |
| reach_distance | 369 | 7 | +0.26 [-0.89, +0.93] | 71% | 27 | +0.36 [-0.52, +1.29] |
| chop_range | 377 | 10 | -0.01 [-0.62, +0.79] | 40% | 28 | -0.00 [-0.47, +0.47] |
| volume | 649 | 22 | -0.22 [-0.62, +0.28] | 36% | 57 | +0.21 [-0.27, +0.74] |
| trend_htf | 579 | 15 | -0.03 [-0.60, +0.61] | 40% | 57 | +0.64 [+0.25, +1.07] |
| failed_break | 384 | 10 | +0.01 [-0.37, +0.59] | 40% | 19 | -0.23 [-0.54, +0.19] |
| gap_premarket | 133 | 6 | +0.17 [-0.93, +1.49] | 33% | 17 | +0.76 [-0.48, +1.83] |
| stop_risk | 474 | 24 | +0.43 [-0.06, +0.82] | 62% | 52 | +0.23 [-0.25, +0.78] |
| targets | 785 | 25 | **-0.22 [-0.46, -0.01]** | 44% | 52 | +0.00 [-0.35, +0.35] |
| critic_bookkeeping | 74 | 1 | -1.17 | 0% | 5 | -0.67 [-1.10, -0.03] |
| other | 810 | 26 | +0.14 [-0.28, +0.53] | 50% | 71 | +0.40 [-0.00, +0.83] |
| (reference: APPROVED setup) | 1028 | 44 | +0.26 [-0.15, +0.81] | 43% | 160 | +0.31 [+0.02, +0.61] |

(The table including plan-level clauses is in the script output; it tells the same story.)

Vetoes that avoided losers (negative mean in at least one sim, nothing positive in the other):
- **targets** (T4.4 unanchored 2/4/6% ladder): -0.22R in the scored sim, the only family with a CI below zero; 0.00R in
  the counterfactual.
- **failed_break** (fakeout / failed prior break): +0.01 / -0.23R, small n.
- **critic_bookkeeping**: -1.17 / -0.67R but only 1 / 5 fills (these are critic flags about the draft, not the setup).
- **volume** (-0.22 scored) flips to +0.21 in the counterfactual - not consistent.

Vetoes that removed winners:
- **level_quality** (single touch / not a key level): +0.27 / +0.53R [+0.11, +0.87]. Consistent with the feature scan
  below: triggers on levels with touches <= 1 did BETTER (+0.49R, 29 fills) than on >= 3-touch levels (+0.03R, 52).
- **trend_htf** (counter-trend / higher timeframe): -0.03 / +0.64R [+0.25, +1.07].
- **stop_risk** (stop placement): +0.43 / +0.23R.

## 4. Deterministic rules

Families already computable from the saved plan:
- targets -> `all(t.basis == 'pct_ladder' for t in trigger.targets)` (plan construction already knows this; the
  assessment caution "targets are the book's 2/4/6% ladder" is the same fact). **Caution: this is almost the same set
  as the break triggers**: 917 of 933 ladder triggers are breakdown (527) or breakout (390); bounce/reject triggers are
  almost always anchored to a level.
- level_quality -> `trigger.level.touches`, `level.timeframes`, `level.priorDayExtreme` (the data says do NOT veto on it).
- reach_distance -> `trigger.level.distancePct` (|dist| >= 1% did better, +0.41 vs -0.12 - do not veto on it).
- trend_htf -> `plan.context.trend[tf].direction` vs trigger direction (30m against: 3 fills, -1.06R; 1h against: 5 fills, +0.62R).
- failed_break -> assessment caution "the last session's break of this level FAILED" (2 fills).
- rr -> `trigger.riskReward` (already gated by `valid`; rr >= 5 vs < 5 showed no difference).

Rules simulated as a filter on the eligible (rules-only) set, chronological split: TRAIN = 11 sessions
2026-08-25 .. 09-09, TEST = 7 sessions 09-10 .. 09-18. The rules were chosen after looking at the full-sample feature
scan, so the TRAIN column is in-sample by construction; only TEST is a (weak) out-of-sample check.

Scored sim (filled / mean R / sum R):

| set | TRAIN | TEST |
|---|---|---|
| rules-only, unfiltered | 53 / +0.23 / +11.93 | 28 / +0.14 / +3.99 |
| model-approved (verdict setup) | 31 / +0.20 / +6.13 | 13 / +0.40 / +5.23 |
| R-targets kept (drop all-ladder triggers) | 36 / +0.49 / +17.74 | 19 / +0.20 / +3.78 |
| R-targets removed | 17 / -0.34 [-0.52, -0.14] | 9 / +0.02 [-0.50, +0.28] |
| R-breakout kept (drop kind=breakout) | 47 / +0.32 / +15.23 | 27 / +0.15 / +3.98 |
| R-breakout removed | 6 / -0.55 | 1 / +0.01 |
| R-30m-against kept | 50 / +0.30 / +15.11 | 28 / +0.14 / +3.99 |
| R-30m-against removed | 3 / -1.06 | 0 / - |
| R-failed-break kept | 51 / +0.25 / +12.89 | 28 / +0.14 / +3.99 |
| R-failed-break removed | 2 / -0.48 | 0 / - |
| R-combo (targets or breakout or 30m-against) kept | 32 / +0.65 / +20.93 | 19 / +0.20 / +3.78 |
| R-combo removed | 21 / -0.43 [-0.51, -0.30] | 9 / +0.02 |

noGapRules counterfactual:

| set | TRAIN | TEST |
|---|---|---|
| rules-only, unfiltered | 147 / +0.52 / +76.87 | 114 / +0.13 / +14.65 |
| model-approved (verdict setup) | 85 / +0.44 / +37.80 | 75 / +0.17 / +12.51 |
| R-targets kept | 122 / +0.69 / +84.62 | 98 / +0.13 / +12.79 |
| R-targets removed | 25 / -0.31 [-0.47, -0.08] | 16 / +0.12 [-0.28, +0.48] |
| R-breakout removed | 9 / -0.58 | 6 / -0.05 |
| R-30m-against removed | 12 / +0.27 | 9 / +0.22 |
| R-combo kept | 108 / +0.76 / +82.47 | 87 / +0.12 / +10.65 |
| R-combo removed | 39 / -0.14 | 27 / +0.15 |

Reading:
- **R-targets (equivalently "no break triggers with ladder-only targets")** is the strongest candidate: in TRAIN the
  removed triggers lose in both sims with CIs below zero; in TEST the removed triggers are flat (+0.02 / +0.12R) - the
  rule neither helped nor hurt out of sample, and it halves the eligible set. Full-sample by kind: bounce/reject
  (anchored) +0.40R on 54 fills, +0.46R on 215 counterfactual fills; breakdown/breakout ladder -0.27R on 22 fills,
  -0.22R on 34 counterfactual fills.
- **R-breakout**: removed breakouts lose in TRAIN (6 and 9 fills) and there was only 1 (scored) / 6 (cf) in TEST.
  Consistent direction, too little data.
- **R-30m-against** and **R-failed-break**: 0 to 3 filled trades removed; not testable here.
- **The model-approved set does not beat the unfiltered rules-only set** in either half in the counterfactual
  (+0.44 vs +0.52; +0.17 vs +0.13) and the scored-sim differences are within noise.

Proposal (for observation, not activation): record `targetsAnchored = not all(pct_ladder)` and the trigger kind on
every eligible trigger and track two cohorts prospectively - anchored (bounce/reject) vs ladder (break triggers). If
the ladder cohort's mean R stays below the anchored cohort over a preregistered sample (for example 30 filled ladder
trades), a deterministic rule `drop trigger if all targets are pct_ladder` (or `kind in {breakout, breakdown}`) would be
justified. This overlaps the existing EM stop-rule scorecard and preregistered tests (TRADING-RULES / `em_scorecard`);
it should be registered there rather than tuned now.

## 5. Caveats

- **Small samples.** 81 filled trades in the scored sim over 18 sessions (1 to 11 fills per session); every family row
  has 1 to 32 fills. Session-clustered CIs are wide and most straddle zero. Multiple families x two sims x several
  slices were examined: some "significant" cells are expected by chance.
- **The live evidence is not in this data.** No `technique_outcomes` rows exist for promote runs planned for
  2026-09-21, 09-22 or 09-23 (365 eligible triggers without an outcome row), so the 7 live rules-only losers
  (-0.98R mean) are neither confirmed nor contradicted here. Live fills also include execution (option pricing, fill
  quality, the 2026-09-12 C3 gap-day policy, the deterministic fire decision) that the sim does not model; whether the
  sim's gap rules match the live gap policy is unknown.
- **Sim limits.** R is the walk-forward `simulate_plan` on 1m bars in share terms, not option P&L. The scored sim
  voids 37% of eligible triggers on gap rules; the noGapRules counterfactual has 3x the fills but is a different trading
  rule. The two sims disagree on several families (volume, trend_htf, the chosen-trigger split); only findings with the
  same sign in both are treated as candidates.
- **Approval definition.** "Approved" is symbol-level (`verdict=setup`), matching what the baseline armed and how the
  live evidence was framed. The per-trigger `review_semantics` reading cannot express approval on setup runs (section 1).
  The "chosen trigger" match is a heuristic (kind + direction + entry within 1%).
- **Reason taxonomy** is keyword-based and multi-label; plan-level clauses reach every trigger; the mapping of a reason
  to "why the model vetoed" is approximate. Examples of each family are printed by the script.
- **Selection bias of the population.** Only triggers that the rules-only policy would admit are studied; triggers the
  model approved but the rules reject (grade C, invalid) are outside the question.
- De-duplication kept the latest run per (symbol, planFor); which run's plan was actually armed for those 32 pairs is
  unknown.
- The train/test cut is chronological but the candidate rules were picked after seeing the full sample.
