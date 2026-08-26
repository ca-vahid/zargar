# Trading rules — findings, observations, theories, optimizations

**What this file is.** The living memory of how the EnhancedMarket method is actually
performing in this app: what we observed, what we suspect, what we changed and why, and
what evidence would change our minds. The codified rulebook lives in
[`TECHNIQUE-ENHANCEDMARKET.md`](TECHNIQUE-ENHANCEDMARKET.md); the build history in
[`TECHNIQUE-PIPELINE-PLAN.md`](TECHNIQUE-PIPELINE-PLAN.md). This file is for the layer
above: **judgement**. Update it whenever a session teaches something; every claim gets a
date and a pointer to its evidence (run id, scorecard, sweep). Never delete an entry —
strike it through and say why.

**How to use it.** Each open question has a *decision threshold*: the evidence that would
settle it. When the evidence arrives, move the item to Findings, apply the change, and log
it in the Change log. The book's own bar applies throughout: **≥100 fires before trusting
a number** (p. 72).

---

## 1. Rules under observation (open questions)

### 1.1 Gap-void rule — is `gap_void_r = 1.0` too strict? ⚠ watching
- **The rule (ours, not the book's — spec Q11–Q13):** a trigger is void when
  |open − prev close| > 1.0 × its planned risk. The book is silent on overnight gaps.
- **Evidence so far:** 2026-08-25 (first live day): **8 of 23 armed triggers voided at the
  open** (NCLH, GOLD, SBUX fully; CHPT ×3; TSLA k1, COST k1, ZS k2). With chart-based
  stops risk is 0.5–3%, so an ordinary overnight gap trips the rule easily.
- **Why it might be wrong:** the rule was written when stops were the fixed 0.5% — risk
  denominators have since tripled, but the multiplier never moved.
- **Decision threshold:** the armed scorecards + walk-forward counterfactual (`noGapRules`)
  over **≥20 voided-trigger samples**. If voided triggers' counterfactual ΣR is clearly
  positive, raise `technique.plan.gap_void_r` toward 1.5–2.0 (settings-tunable, prove with
  `replay --set`). If negative, the rule earns its keep — leave it.
- **Do not touch until the samples exist.**

### 1.2 Grade calibration — do A > B > C outcomes actually hold? ⏳ accumulating
- Grades (plans.assess_trigger) are rule-cited but the weights are hand-set (2026-08-23).
- **Decision threshold:** ≥100 scored fires split by grade. If B outperforms A, the
  weights are wrong — re-derive from the outcome data, don't hand-tune.
- Early signal (1 day, anecdotal): the only two movers on 2026-08-25 (SNOW +1.89R replay,
  ZS ~+0.8R) were both armed A's. Encouraging, meaningless at n=2.

### 1.3 Analyst-check hit rate — does the $0.20 read earn its keep? ⏳ accumulating
- The informed analyst (post-2026-08-24 prompt fix) confirmed 10/13 A's. Track
  analyst-✓ vs analyst-✗ outcome spread. If ✗ setups perform no worse, the check is
  costume; if they underperform, raise its weight (maybe gate bulk-arm on it harder).

### 1.4 Fire-time critic — net saver or net cost? ⚠ watching closely
- 2 kills on day one, **both wrong** (ZS: data artifact + missing plan provenance;
  SNOW: "fabricated targets" prompt gap). Both causes fixed (plan provenance + data-quality
  + ladder clauses in the prompt; veto now re-arms the trigger, cap 3/day).
- **Decision threshold:** after the fixes, tally kill-vs-counterfactual over ≥10 kills.
  If informed kills still cost R on balance, demote the critic from veto to
  confidence-note on auto mode (it already never gates proposal mode).

### 1.5 Blue-sky ladder R:R (T4.4 2/4/6%) — optimistic by construction
- A breakout with no resistance overhead gets targets at +2/4/6% and often a huge R:R;
  the grade caps at B for this reason. Open question: should TP1 for blue-sky breakouts
  be ATR-derived instead of 2%? Needs fired-breakout outcome data (none yet).

### 1.6 Wide-spread skips vs shares fallback ⏳ new
- SNOW 2026-08-25: T5.4 spread guard (16.5%) blocked a +1.89R (stock) trade. Fallback
  `entry_fallback=shares` now exists (per-arm, changeable after arming).
- **Decision threshold:** compare shares-fallback trades vs option trades on R and $ over
  ≥20 fallback events. Also revisit next-strike/next-expiry retry if fallback data shows
  many skips happen with tradeable neighbours.

---

## 2. Findings (settled, with evidence)

- **2026-08-23 · Stops must be chart-based in fact, not in name** (MARA run `f055c5c6`).
  `level − max(2·tol, 0.5%, 0.25·ATR_1m)` was a fixed-percent stop in costume: identical
  $0.056 risk at three ladder rungs inside Friday's chop band. Fixed: stops anchor below
  the invalidating structure (zone floor / recent low), buffered by structure-tf ATR,
  capped by `max_stop_pct` (wider = no-trade, never silently tightened).
- **2026-08-23 · Clustered levels are one zone, not a ladder** (same run). b2's entry sat
  $0.004 above b1's stop — stop out, re-enter, churn. Levels within `zone_merge_pct`
  merge; **entry is always the zone's top member** (WDAY `a9fd6891` later proved
  strongest-member entries put you 5 broken supports deep — T3.4d).
- **2026-08-23 · R:R is only as honest as its target anchor** (MARA). Dropping a 27-touch
  resistance for sitting $0.002 below last close anchored the ladder on a rejected gap
  wick → "R:R 22.6". Anchors come from all resistances above the *entry*.
- **2026-08-24 · LLM disagreement is usually an information gap, not a verdict.** The
  blind analyst rejected 13/13 A's; given the plan, grades, and stop/zone rules it
  confirmed 10/13 and endorsed by trigger id (BKNG b2 before/after, runs
  `08bac1c1`/`2a9d2082`). Same for the plan-mode critic (R6 does not kill conditional
  plans; interpolated 40/75/100 trims are the method's own design). **Feed the judges
  everything the grader knows before you trust their dissent** — after that, dissent is
  real signal (1.3, 1.4).
- **2026-08-25 · Data quality reaches into every layer.** Yahoo 429 throttling caused:
  180 s bar stalls, a phantom touch (ZS fired at 172.39; official low 172.45), volume
  reading 0.0× at fire time (critic killed on it), and late fires. Fixed by Alpaca
  full-SIP streaming + Alpaca-first history (`1ffd1e9`); Yahoo is fallback with a
  visible "data: fallback" pill + journal alerts. **Volume gates require the
  consolidated tape — never run this method on an IEX-only feed.**
- **2026-08-25 · Restart recovery must never rewrite live history** (GOLD phantom fire).
  Replay of corrected bars is state-rebuilding, not truth; the persisted live record
  wins (`replay_divergence` / `phantom_dropped` events, pre-seed state snapshot).
- **2026-08-25 · The machine can be right and still capture nothing.** Day 1: ~2.7R
  identified, 0R captured — every dropped R traced to friction (critic prompt gap,
  spread guard with no fallback, data artifacts), not to the method. Discipline showed:
  refused three no-volume break attempts on WDAY that all faded (saved ~0.7R), refused
  gapped boards. **The edge appears to be real; the work is in the capture rate.**

---

## 3. Theories (unproven, worth testing)

- **T-1 Prime-window asymmetry:** the open window may produce more fakeouts (WDAY's three
  refused attempts) and the close window cleaner fires (SNOW). If scorecards agree over
  ~50 fires, weight close-window triggers up (or open-window confirmation stricter).
- **T-2 Mid-day touches predict prime-close fires:** SNOW touched its level 5× mid-day
  then fired at 14:46. `observedMidday` counts are already tracked — test whether
  touches-while-gated correlate with fill quality at 14:45+.
- **T-3 Gap-void beneficiaries:** gaps *toward* a breakout level (gap-past, T4.1
  don't-chase) differ from gaps that merely reprice risk (gap_void). The counterfactual
  should be split by gap direction before judging 1.1.
- **T-4 Volume floor at the trigger bar (R3.1 50%)** was tuned on Yahoo's
  quote-sampled volume. With true SIP volume it may be too lax or too strict —
  re-examine the floor after ~2 weeks of streamed data.
- **T-5 Analyst as position-sizer:** instead of gating, size by agreement
  (A+✓ full risk, A+✗ half risk). Needs 1.2/1.3 data first.

---

## 4. Optimization backlog (ranked)

1. **Capture-rate telemetry** — a weekly roll-up: identified R (scorecard theoretical)
   vs captured R (realized), with the friction reason for every gap. This is THE metric;
   the daily scorecards already contain the raw material.
2. **Gap rule decision** (1.1) once ≥20 voided samples exist.
3. **Critic scorecard** (1.4) — auto-tally kill counterfactuals.
4. **Grade/analyst calibration** (1.2/1.3) at the 100-fire mark.
5. **IBKR activation** — execution + second data source; retire the sim-only options fills
   with real paper fills.
6. **Next-strike/next-expiry contract retry** — pending 1.6 data.
7. **Blue-sky TP1 from ATR** (1.5) — pending fired-breakout data.
8. **Full Settings redesign** (task chip exists); slow-DB-writes investigation (chip
   exists); persist critic veto counts across restarts.

---

## 5. Change log (parameter/rule changes — date · change · why · evidence)

- 2026-08-23 · Stops → chart-based (zone floor + structure ATR, `max_stop_pct=3%` cap);
  zones (`zone_merge_pct=1%`); target anchors above entry · MARA review `f055c5c6`.
- 2026-08-23 · Trigger grades (A/B/C, rule-cited) + plan bottom line; pct-ladder R:R
  capped at grade B · MARA/COP/WDAY reviews.
- 2026-08-24 · Bounce entry = zone top (never a deep member) · WDAY `a9fd6891`.
- 2026-08-24 · Plan-mode analyst + critic get the full plan (provenance, grades, rules);
  R6/ladder declared never-violations · BKNG before/after.
- 2026-08-25 · Fire-time critic: plan provenance + data-quality guidance + ladder clause;
  veto re-arms the trigger (cap 3/day) · ZS `a59ac6f9`, SNOW 14:46 kill.
- 2026-08-25 · Alpaca full-SIP stream + Alpaca-first history; feed-down alerting ·
  Yahoo 429 incident.
- 2026-08-25 · `entry_fallback` off|shares per arm · SNOW spread skip (+1.89R untaken).
- 2026-08-25 · Evening automation (`technique.sheet.auto`): auto sheet after close,
  optional auto analyst-check of A's.
