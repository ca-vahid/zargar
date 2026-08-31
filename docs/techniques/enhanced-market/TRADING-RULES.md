# Trading rules — EnhancedMarket (EM Options): findings, observations, theories, optimizations

> **Scope (2026-08-27):** this is EM's own judgement log. Lessons that hold for *every* technique —
> data feeds, restart recovery, the fire/exit runtime, risk — live in [`docs/PLATFORM-RULES.md`](../../PLATFORM-RULES.md)
> and are only cross-referenced here. Section numbers (1.1 … 1.8, A1 … A10, D1 … D5) are stable: code comments,
> UI tooltips and journal entries cite them.


**What this file is.** The living memory of how the EnhancedMarket method is actually
performing in this app: what we observed, what we suspect, what we changed and why, and
what evidence would change our minds. The codified rulebook lives in
[`METHOD.md`](METHOD.md); the build history in
[`PIPELINE-PLAN.md`](PIPELINE-PLAN.md). This file is for the layer
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
- **2026-08-26 · QUARANTINE today's samples.** The app was down until ~09:50 ET (machine
  reboot). 22 of the 23 "voided at the open" decisions for 08-26 were evaluated on the
  **09:50 bar** (journal `gap_void`/`gapped_past` payload `ts` = 13:50 UTC), because
  `TriggerTracker` ran its one-time gap test on the first bar it saw and the post-restart
  seed had no 09:30 bar. After 20 minutes of trading most names are > 1R from the previous
  close, so those voids say nothing about the rule. **Exclude every 08-26 void from the
  §1.1 counterfactual** (only CRWD b1, decided on the 09:30 bar, is a valid sample). The
  08-25 voids (8) were all decided on the 09:30 bar and stay valid. Root cause and fix in
  the change log (A1). The outage itself is an anomaly; the fix makes a late start harmless.

### 1.2 Grade calibration — do A > B > C outcomes actually hold? ⏳ accumulating
- Grades (plans.assess_trigger) are rule-cited but the weights are hand-set (2026-08-23).
- **Decision threshold:** ≥100 scored fires split by grade. If B outperforms A, the
  weights are wrong — re-derive from the outcome data, don't hand-tune.
- Early signal (1 day, anecdotal): the only two movers on 2026-08-25 (SNOW +1.89R replay,
  ZS ~+0.8R) were both armed A's. Encouraging, meaningless at n=2.
- **C-cohort experiment (armed 2026-08-25 evening for 08-26):** all 14 grade-C rows
  analyst-checked and armed on Practice **regardless of verdict** — deliberately
  including analyst-✗ plans as the control group, so grade-vs-outcome is measured
  without our own selection bias. The analyst rejected **0/14 C's**, making the
  cohort-level agreement monotonic: analyst confirmation rate A 6/12 (50%) >
  B 16/60 (27%) > C 0/14 (0%). The two measures rank cohorts the same way even
  though they disagree constantly on individual A's — outcomes will arbitrate.
  Fleet for 08-26: 37 plans (6A + 17B + 14C incl. ZS-B, CHPT-A).

### 1.3 Analyst-check hit rate — does the $0.20 read earn its keep? ⏳ accumulating
- The informed analyst (post-2026-08-24 prompt fix) confirmed 10/13 A's. Track
  analyst-✓ vs analyst-✗ outcome spread. If ✗ setups perform no worse, the check is
  costume; if they underperform, raise its weight (maybe gate bulk-arm on it harder).
- **2026-08-25 evening cohort (first large sample, 72 checks for the 08-26 session):**
  analyst confirmed **22/72** — A: **6/12**, B: **16/60**. Notable: half the A's were
  rejected while a quarter of the B's were endorsed — grade and analyst clearly measure
  different things. Scorecards for 08-26 are the first real test of which read is right
  (feeds 1.2 as well).

### 1.4 Fire-time critic — net saver or net cost? ⚠ watching closely
- 2 kills on day one, **both wrong** (ZS: data artifact + missing plan provenance;
  SNOW: "fabricated targets" prompt gap). Both causes fixed (plan provenance + data-quality
  + ladder clauses in the prompt; veto now re-arms the trigger, cap 3/day).
- **Decision threshold:** after the fixes, tally kill-vs-counterfactual over ≥10 kills.
  If informed kills still cost R on balance, demote the critic from veto to
  confidence-note on auto mode (it already never gates proposal mode).
- **2026-08-26 · first post-fix kills, 3/3 CORRECT** (PM k1, run `90f24dbc`): fired
  thrice into a 5-touch intraday resistance shelf (195.99, HOD 196.13) the evening
  plan couldn't see; critic killed all three citing chase (T4.1), overhead structure
  (T1.1) and a manufactured 5.0 R:R — and explicitly did NOT use the forbidden
  reasons ("killed on live-tape evidence, not on the data-outage or plan-provenance
  technicalities"). Price rejected off that exact shelf (196.66 → 194.99). Running
  tally since prompt fix: 3/3 saves. Also evidence for 1.5: the pct-ladder R:R was
  the artifact the critic had to shoot down.
- **2026-08-26 · T (AT&T), first mid-day-experiment fires: 4 more correct kills — tally 7/7.**
  k1 breakout fired 4× (13:37–13:58 ET, the 5-min cooldown pacing it, 4/10 vetoes used)
  inside a 3-cent hour-long chop box on 0.2× volume; critic killed all four citing
  T3.3d/c/f, R3.1, R3.2 and the unanchored 12:1 ladder — price stayed pinned in the box
  after. Two system validations inside the kills: the volume-baseline fix delivered
  ("rel=0.232x, measurable baseline of 4 sessions — R3.1 bites for real", vs yesterday's
  0.0x/unmeasurable), and `middayExperiment` context held — zero kills cited the window.
  Watch item: the tracker's fire-time volume gate passed bars the critic's FACTS graded
  0.2×— the two rel-volume computations (tracker profile vs live FACTS baseline) need
  reconciling before trusting R3.1 at the tracker.
- **2026-08-28 · Day 4: 17 fires, 17 kills — ALL correct on outcome (EOD-scored),
  but the 10 INTU kills cited an INVALID reason.** All fires were genuine in-band
  level touches (tape verified; the 08-27 zombie fix held — 13 dead triggers retired
  pre-entry by `invalidated`, 7 by gap_void, 11 would-be fires blocked by R3.1).
  EOD scorecard (simulate_plan, close job 16:00): NVDL b1 ×2 → sim `tp1` but net
  **−0.46R** (tagged TP1, runner gave it back — kill = save), OKLO b2/b3 ×2+1 →
  **−1.25R stopped** (saves), LRCX b2 ×2 → trigger `invalidated` in replay (fires
  were churn on a dying level), INTU r2 ×10 → **−1.09R stopped in prime_close**
  (INTU rallied through the 357.28 stop in the afternoon; the mid-day "+0.66R
  foregone" read was premature — the kills were saves, not costs). BUT the INTU
  kills cited *"the draft is a short — the method is long-only"* — a FALSE premise
  from a stale `SYSTEM_PROMPT` line (§5 fix, same root cause as the CVNA analyst
  miss); right outcome, invalid reasoning, so they count separately: outcome tally
  **44/44** kills correct through day 4; reasoned tally 34 valid + 10
  invalidated-reason. INTU r2 burned its full 10/10 veto cap by 12:51 (~7 min/fire
  on the 5-min cooldown) — second cap-burn after T; deterministic graduation
  (retire after N identical kills) is the top backlog candidate.
- **2026-08-28 · Day 4 EOD, whole-universe replay (sweep `e8f039e0`, 113 symbols,
  117 planned triggers): ONE valid fire all day** — a prime_close reject, stopped,
  −1.16R. Zero bounce/breakout/breakdown fires anywhere; 37 gap-voids (+samples for
  1.1); counterfactuals all lose (noGapRules: 6 fires −2.18R; noWindowGate: 4 fires
  −2.20R — every gate relaxation was negative today). Trading zero on Friday was
  the correct call end to end. Bonus: first **[pass]** on a book claim — prior-day
  HOD/LOD levels respected 27.1% vs 23.0% for other levels (tested n=554, T1.3a).

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

### 1.7 Mid-day no-trade rule (R6.3) — does the watch-only window earn its keep? ⏳ new
- **The rule (the book's):** trade only 09:30–10:30 and 14:45–16:00 ET; mid-day is
  chop, watch-only. Until now this was untestable — we never collected mid-day fires.
- **The experiment (2026-08-26):** `technique.arm.midday_trading` (Settings →
  Auto-trading → Experiments, default OFF) lets armed triggers fire mid-day, **live
  armer only** — plans, sweeps and the backtester stay R6-true, so the execution
  scorecard's live-vs-replay diff is the built-in counterfactual. Every fire carries
  `window="midday"` (+ `middayExperiment` on the journal event); the critic is told the
  suspension is deliberate so it never kills on the window itself. Practice only.
- **Decision threshold:** ≥30 scored mid-day fires. Compare R distribution vs
  prime-window fires from the same fleet. If mid-day ΣR is clearly negative → the
  book's rule is confirmed, turn the toggle off for good. If comparable or positive →
  R6.3 is costing us trades; consider widening the windows (with the critic as the
  chop filter). Watch T-1 (window asymmetry) alongside.
- ⚠ Keep OFF on any live account until this resolves.
- **First session data (toggle went live 2026-08-26 ~13:30 ET):** the first mid-day
  fires (T ×4) were exactly the chop-fakeouts R6.3 predicts — 3-cent box, 0.2× volume,
  stub-print breaks — and the critic vetoed all four. Early shape of the answer: mid-day
  DOES produce trigger conditions, and so far they're garbage the critic must filter.
  If that pattern holds, the finding may be "R6.3 is right about the tape but the
  critic can substitute for the clock" — n=4, keep counting.

### 1.8 Is the R2 bar (3.0) leaving a 2.0-3.0 band on the table? ⏳ new
- **First gate audit (2026-08-26 session, include-invalid sweep `57156a57`):** every
  trigger the validity gates rejected was simulated against the real session.
  Verdict: the gates dropped nothing worth having. Gate-rejected fires: 150 for
  +9.2R TOTAL — mean +0.06R, median +0.10R, 68% win rate: a micro-scalp profile
  that dies under option spreads/fees. Stop-cap (T4.3a/R1) rejects: 47 fires,
  net NEGATIVE. Meanwhile the plan-VALID set fired 6 for −3.1R — 08-26 offered
  the method nothing, and standing aside beat everything.
- **The tail worth watching:** the day's three best rejected trades (PLUG r1 +2.9R,
  CVNA r1 +2.4R, GS r1 +1.9R) all had planned R:R in the 2.2–2.6 band — just under
  the 3.0 bar. One gap day proves nothing, but it frames the question.
- **2026-08-31 · Live specimen: the author's TOP pick (SPCX, "break 143 → 149")
  produced ZERO valid triggers in our pipeline** (run `017e771dcf`): best trigger
  b2 bounce died at R2 with rr **2.50** — inside the 2.0–3.0 band — and his
  continuation shape is exactly T-6. Meanwhile our system independently AGREED
  with his SNDK breakdown / MRNA puts / CMG wedge-break / PATH break (all armed,
  MRNA grade A) and read META opposite (he leans long through resistance, ours
  plans d1 breakdown). Source: 08-31 setup video, transcript in notes/.
- **2026-08-29 · First variant pilot (12 sessions Aug 12–27, 113 symbols; baseline
  `26f752fa5a` vs rr2.0 `9edf5248fa`):** the 2.0–3.0 band added 36 fires for +6.39R —
  **marginal mean +0.18R/fire, below the +0.3R decision bar** (and pre-spread), n
  still small. But split by kind: the band's extra BOUNCES were +0.32R/fire (14
  fires) while extra rejects/breakouts were ~flat. Emerging shape: a per-kind rr
  gate (bounce 2.0, others 3.0) rather than one global bar. Keep accumulating
  weekly; also note baseline itself simulated +22.2R over the 12 sessions —
  identified R is there, the capture-rate gap is what live week 1 exposed.
- **2026-08-29 · Week-1 funnel autopsy (Aug 24–28, n=1,489 trigger-outcomes): R2 IS
  the funnel.** not_tradeable 988 (66%), 981 of them on R2; median failed R:R 0.57
  (structurally far, not near-misses), but +121 triggers pass at ≥2.0 and +206 at
  ≥1.5. Everything that survived all gates and fired: n=16, +5.47R, avg +0.34R,
  7/16 wins with big winners — the survivors are profitable, the funnel is just
  ~1%. The author's own practice (see notes/2026-08-28-author-video.md) trades
  continuation setups whose natural R:R to the NEXT zone is 1–2, exited fast —
  the R2=3.0-to-TP3 arithmetic may simply not describe his modern style.
- **Decision threshold:** repeat this audit weekly (free, deterministic). If the
  2.0–3.0 R:R band shows mean ≥ +0.3R over ≥100 simulated fires net of a spread
  estimate, consider a reduced-size tier for it; if it stays ≤ +0.1R, R2 is
  confirmed and this question closes.

---

## 2. Findings (settled, with evidence)

- **2026-08-29 · First capture-rate join (baseline sweep `26f752fa5a` × live arming
  events): the "identified +22R vs captured 0" headline was mostly regime, not leak.**
  +23.5R of the identified R sits on Aug 13–25, BEFORE live arming existed. On the
  three overlapping sessions (Aug 26–28) the whole universe identified only 6 fires,
  net −1.3R — and our pipeline covered the two losers (DELL r2, INTU r2 — both
  correctly critic-killed) while missing the two winners at the ARMING-COVERAGE
  layer (CVNA r2 +2.5R — the same CVNA reject missed twice now — and HYG b1 +0.2R).
  Revised diagnosis: no capture crisis; one specific leak = coverage/selection of
  REJECT setups on symbols that don't make the armed list. Fix is operational
  (arm wider, weight rejects — the strongest kind at +1.31R avg), not a threshold.
  Automate this join as the weekly capture report (backlog #1).

- **2026-08-27 · Day 3 (first clean day: fixed tracker, hooks, both directions): 0 live
  fires, and the replay says that was nearly right.** Whole-universe replay (sweep
  `830ecaa4`, 141 symbols): 3 valid fires, net +1.71R — CVNA r2 (a put) +2.5R to TP2,
  HYG b1 +0.21R, BSX b2 −1.0R. None of the three were in the armed 26: the day's only
  meaningful trade (CVNA) was dropped at the ANALYST/selection layer, not by the gates —
  a concrete case for 1.3. The armed set's own replay fired nothing: the afternoon's
  deterministic refusals (MSTR/LITE/SMTC on volume + candle) were all correct and cost
  ZERO critic calls (vs ~20 paid refusals the day before — the graduation principle,
  measured). +68 valid gap-void samples accumulated for 1.1. Clock-driven 16:00 close
  scored and expired all 26 plans on its first live run.

- **2026-08-27 · A trigger's level can die intraday — track it or fire zombies.** The
  pre-open re-planner (new) builds levels near pre-market price; when the open then
  walks THROUGH a bounce level and its stop, nothing killed the trigger: a long bounce
  "touched" whenever price was anywhere below the level (no far-side bound), fired at a
  fantasy fill equal to the level price, was critic-vetoed, re-armed, and refired every
  cooldown (LITE b1 fired 10x at 947.53 while the tape was at 923; MSTR r2 the short
  mirror). Fixes: touches must reach INTO the band; a pre-entry close through the stop
  is terminal (`invalidated`, T4.3d). The critic was the only line of defense and went
  20/20 — but 20 saves that a `bar.close < stop` comparison should have made for free
  is the graduation principle (1.4) restated by the machine itself.


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
- **2026-08-26 · No sub-minute entry bars — settled.** The method's confirmation IS the
  closed 1m bar (close vs level + volume through the bar, T3.3); firing intra-bar acts
  before confirmation exists and buys exactly the fakeouts the method avoids (PM's
  triple-veto would have FILLED on sub-minute bars). Sub-minute is also unvalidatable
  (no Yahoo history; Alpaca tick-rebuild = big cost, scalper's payoff for a 3R-levels
  method) and microstructure noise starves the volume gates. Sub-minute stays where it
  belongs: exits only (quote stop watch, premium stop) — protection may be fast and
  unvalidated because reduce-only can't hurt. Fire latency was the critic's thinking
  time, fixed with `technique.arm.critic_effort=low`, not bar size.
- **2026-08-26 · Full book-vs-app review** (`docs/techniques/enhanced-market/METHOD-REVIEW-2026-08-26.md`; the
  original developer independently verified the four headline claims). Method-level
  findings, each dated here so nothing is re-litigated:
  - **Touch counting was band-overlap, not a test of the level** (`levels._count_touches`):
    support and resistance used the identical expression and a bar blowing straight
    through a level counted as a "touch". Every touch count — `min_touches`, the "3+
    touches" confluence, the +12/+6 grade points — was inflated. Fixed (A3): a touch is a
    bar whose extreme reaches the band *and* whose close does not break it. Grades and
    sweep numbers produced before this fix are not comparable with those after
    (`sweepVersion` changes).
  - **Breakout stops were still a fixed percentage** — `level − 0.5 %` in `setups.py`, and
    the plan path collapsed to the same for single-level zones (T k1 08-26: 25.87 → 25.7407
    exactly). The 08-23 "chart-based stops" fix landed on bounces only. Combined with the
    unanchored +2/4/6 % ladder this made every plain breakout grade R:R ≈ 12, which is why
    the critic kept executing the same kill (PM, T). Fixed (A4): the stop anchors below the
    most recent swing low under the level (the base the break launches from), buffered
    like the bounce stop, refused when wider than `max_stop_pct`.
  - **R:R was gated at TP3 while a < 3-contract position exits at TP2** — a "3.0" plan is a
    2.25 trade as executed. Fixed (A5): R2 is evaluated at the exit the position will
    actually take (`technique.rr_gate_target`, default `tp2` while `technique.arm.contracts`
    < 3); the book's TP3 figure is still reported alongside.
  - **R3.1 lived in four places with two conventions** — FACTS blocked on unmeasurable
    volume, the tracker fired on it. Fixed (A6): one policy — an entry never fires on
    unknown volume (`volume_unknown` skip, journaled, trigger stays alive), and the floor
    is a setting (`technique.volume_floor_mult`).
  - **The book's universe is mega caps.** T ($26, 3-cent chop box, 13-cent stop), CHPT
    ($6), SOUN, CLF are outside what the method was written for; half the friction we
    fight (spread skips, stub-tick fakeouts, gap voids on tiny risk denominators) is the
    list. Decision pending (user): liquid A-list arms, wide list keeps grading for data.
  - **Silent no-halt**: 36/37 auto plans armed for 08-26 had no loss halt — equity was
    unavailable at the evening bulk-arm and the derivation skipped with a log line. Fixed
    (A2): a fixed fallback (`technique.arm.daily_loss_fallback`) plus a journaled alert
    and an attention badge; a restore also repairs it.
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
- **T-6 Continuation-breakout archetype (author's live style, 2026-08-28 video):**
  "sitting just below prior-day resistance → break at the open → long to the NEXT
  zone / gap edge, exit fast." Natural R:R 1–2, high intended win rate, 0DTE-friendly.
  Friday's ground truth: MSFT clean win (his 512–513 target hit), SPY/QQQ pop-then-fade
  (scalp wins, holds lose), IWM 7-cent fakeout. Test as a NEW trigger kind in the
  shared tracker with its own rr gate and a TP1-heavy or time-boxed exit — never by
  loosening R2 for the existing kinds. Entry archetype and exit tempo are a pair.
  **2026-08-29 first pilot (variant `5a916ced73` vs baseline `26f752fa5a`, 12
  sessions): NO edge under our exit model.** The relaxed-confirmation overlay fired
  280 vs 43; the 237 extra fires added only +5.8R (≈ +0.02R/fire, pre-spread —
  negative after costs). Relaxed breakouts: 108 fires −4.7R. IMPORTANT caveat: the
  sim held the standard all-day 30/40/15 ladder — his fast-exit tempo (bank the
  first pop) is exactly what the sim cannot yet express, and Friday's SPY/QQQ tape
  showed that's where his wins live. Verdict so far: do NOT loosen confirmation
  under our exits; the remaining open question is exit tempo, which needs a
  parameterized exit ladder in `outcome.simulate_plan` before T-6 can be fairly
  judged. Meanwhile the pilot confirmed: REJECTS are the strongest kind at baseline
  (+1.31R avg, 73% win, 11 fires) — the kind the long-only critic bug was killing —
  and breakouts are the weakest in BOTH configs (negative even fully confirmed);
  prime_open carries all the edge, prime_close was net negative in all three
  variants (more T-1 evidence).
- **T-7 Gap-fill targets:** an unfilled overnight gap in the trade's path is a target
  magnet in the author's practice (IWM/QQQ longs "into the gap", AMD short "gap to
  fill below"), not only a hazard. Experiment: add gap edges to the target-anchor set
  and re-sweep; keep gap_void for entry-side gaps (its samples say it saves R).
- **T-8 Index-ETF lane (SPY/QQQ/IWM):** his #1 setups; penny-wide 0DTE spreads kill
  the spread-cost argument from the 1.8 gate audit. Check why they never survive our
  funnel (likely R2 — index levels are close together) and sweep them under T-6 rules.
- **T-9 Liquidity-grab reclaim:** a false break through resistance that quickly
  reclaims reads as bullish fuel to the author (MU); our tracker counts it toward
  `exhausted`. Test: false-break-then-reclaim within N bars as a confirmation signal
  instead of a strike.
- **T-10 Earnings-gap veto:** his only gap rule is "earnings gap = untouchable"
  (AFRM +11%). We have no event calendar yet (B-gate list) — until then, a crude
  |gap| > 5% next-session veto in the sheet builder would mimic it.

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
9. **T-6 continuation-breakout walk-forward** (2026-08-29): sweep the archetype over
   60 days on the universe + SPY/QQQ/IWM before any live arming — deterministic,
   free, and it directly answers "are we too strict or missing a lane".

---

## 5. Change log (parameter/rule changes — date · change · why · evidence)

- 2026-08-28 · **SYSTEM_PROMPT taught the short mirrors; stale "Long-only." clause
  removed** (`schemas.py`), and `review_fire` adds a DIRECTION clause on
  reject/breakdown fires (`arming.py`). Why: the prompt still predated the
  2026-08-26 both-sides decision — the analyst dropped CVNA's +2.5R put on it
  (day-3 replay) and today the fire critic vetoed INTU r2 ×10 citing "the method
  is long-only". Evidence: day-4 event stream + INTU critic summaries. New
  promptVersion via provenance hash; deployed after the 08-28 close. the R6.3 mid-day experiment
  toggle (`technique.arm.midday_trading`) is **EM-scoped** — read only inside EM's
  `entry_windows_enforced()` hook, never by the generic runner, and never promoted
  to a platform key. Veto/critic budgets (`critic_kills_per_day`,
  `refire_cooldown_minutes`, `critic_fail_budget`, `critic_timeout_seconds`)
  **inherit platform defaults with per-technique override** — spec handed to the
  engine team for phase 3 settings scoping (`techniques.<id>.<key>` override, else
  `execution.<key>` platform default; old `technique.*` names as deprecated aliases).

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
- 2026-08-26 · `technique.arm.midday_trading` toggle added (default OFF) — the R6.3
  mid-day experiment, §1.7. Live armer only; fires tagged by window.
- 2026-08-26 · Fire-time critic hardening after the PM triple-veto: live FACTS get a
  prior-session volume baseline (was baselineSessions=0 → volume unmeasurable at every
  fire); veto cooldown `technique.arm.refire_cooldown_minutes=10` (one squeeze burned
  all vetoes in 3 min); cap now a setting `technique.arm.critic_kills_per_day` (3→6,
  user request); `technique.arm.critic_effort=low` (fire-time latency is cost — deep
  thinking stays for plan-mode reads). Kills/cooldowns persist across restarts.
- 2026-08-25 · **Risk caps raised for the practice experiment** (user-approved):
  `risk.max_option_premium_notional` 1000→2500, `risk.max_option_premium_pct` 5→25,
  `risk.max_position_notional` 1000→5000 — the old caps blocked 7/37 armed plans
  (BLK/GS/SPOT over the per-order cap; ADI/AMD/HD/WDC over 5% of the $10k sim
  account). The armer also pre-checks premium caps at fire time now and uses the
  shares fallback instead of dying at the RiskGate. ⚠ **These are GLOBAL settings:
  re-tighten before real-money trading** (a $2,500 premium is 25% of a $10k account
  — fine for data collection in sim, reckless with real capital).
- 2026-08-26 (evening) · **Review fixes A1–A10** (`docs/techniques/enhanced-market/METHOD-REVIEW-2026-08-26.md`; the
  original developer verified the headline findings and endorsed the order). Every item is
  a code change to how the METHOD is applied, so each is logged here:
  - **A1 gap rules only on the opening bar.** `TriggerTracker` judges gapped-past / gapped-
    through / gap-void on the 09:30 bar only; a later first bar records `gap_unchecked` and
    the trigger runs without the gap rules. A plan armed or restored after the open now
    fetches the missing opening bars from history (Alpaca-first) and replays them first
    (`opening_bars_seeded`). Evidence: 22/23 voids on 08-26 were decided on the 09:50 bar.
  - **A2 no silent no-halt.** Auto mode derives the loss halt from equity (2 × risk, with a
    retry); if equity is unreadable it uses `technique.arm.daily_loss_fallback` ($100) and
    raises a journaled warning + attention badge; fallback 0 = refuse to arm. Restores are
    repaired the same way. Evidence: 36/37 plans armed for 08-26 had no halt.
  - **A3 touch = test of the level.** `levels._count_touches`: the extreme reaches the band
    AND the close does not break it. Sweeps before/after are not comparable.
  - **A4 breakout stop under the break base.** `setups.breakout_anchor` / `plans._break_base`:
    the most recent trigger-tf swing low below the level (within `max_stop_pct`), buffered
    like a bounce stop (`stop_reference=below_break_base`); wedge stops get the same buffer.
    Never `level − 0.5 %` again. Evidence: T k1 25.87 → 25.7407 (= 0.995×).
  - **A5 R2 at the exit rung.** `technique.rr_gate_target = auto` → TP2 while the options
    instrument trades < 3 contracts (`single_contract_exit`), else the book's TP3; both
    figures are reported (`riskReward` / `riskRewardTp3`). Expect fewer valid triggers.
  - **A6 one R3.1 policy.** The tracker's relative volume is the trigger bar vs its
    time-of-day baseline; unknown volume never fires an entry (`volume unknown` skip, trigger
    stays alive). `technique.volume_floor_mult` is now a setting. Analysis-path breakouts are
    judged with the volume AT the break bar.
  - **A7 exchange bars reach the trading path.** `BarAggregator` holds a quote-sampled 1m bar
    `feed.exchange_bar_hold_seconds` (5 s) for Alpaca-streamed symbols so the exchange bar
    replaces it before consumers see either (`source: exchange`). Fires arrive ≤ 5 s later.
  - **A8 critic hygiene.** Contract is picked BEFORE the critic (it now sees the vehicle);
    hard timeout `technique.arm.critic_timeout_seconds` (25 s); failures fail OPEN with a loud
    alert and a per-day budget `technique.arm.critic_fail_budget` (3) whose last failure
    sends nothing and pauses the plan (the developer's call — an outage must not silently stop
    data collection); the fire → critic → order chain runs off the serial bar loop, so a slow
    model never delays another plan's stop; disarm waits for in-flight chains.
  - **A9 option quote freshness.** A refreshed chain bid/ask stamps the quote's `ts`; OCC
    symbols are no longer subscribed to the Alpaca equity stream; the "premium stop is blind"
    alert fires after ~1 min, not 5.
  - **A10 false-break counter (R3.2).** `technique.max_false_breaks` (2): a level whose break
    failed to hold twice in a session is `exhausted` (terminal). Evidence: T k1 fired 6× into
    the same 3-cent box; the paid critic was doing R3.2's job.
  - Still open (B, before real money): fleet-wide position/premium caps, R1 on premium,
    re-tightened `risk.*`, event calendar, RTH-only exits, real-time option quotes, fees.
- 2026-08-26 (night) · **User decisions on the review's D-questions**, all built the same
  night (see `docs/techniques/enhanced-market/METHOD-REVIEW-2026-08-26.md` §5-D):
  - **D1 Universe → large, liquid, refreshed.** `technique.walkforward.symbols` is now a
    curated **117-name core** (index/sector ETFs with daily or M/W/F expiries, mega caps,
    the most-active single-name options — ranked by one day of consolidated CBOE options
    volume, price ≥ $20; `technique/universe.py`). Plus `technique.universe.extra` (the
    user's own names, always in) and a daily **auto layer** (`technique.universe.auto_refresh`,
    Alpaca most-actives screener, Yahoo `most_actives` fallback, price floor
    `technique.universe.min_price` = $20, cap `auto_top` = 40). `technique.universe.exclude`
    wins over every layer. The evening sheet uses the resolved list when
    `technique.sheet.symbols` is empty; `GET /api/technique/universe` shows provenance.
    T, CHPT, SOUN, CLF are gone from the default set.
  - **D2 Sizing → risk-based in practice, Fridays smaller, 0DTE mornings only.**
    `technique.arm.contracts` 1→**0** (= size by risk), `risk_pct` 0.5→**2.0** (practice;
    the book's live range stays 0.5–1 %), `max_contracts` 5→10. Risk per contract = what
    the premium stop can lose (`premium_stop_pct` of the premium); contracts = equity ×
    risk% / that; **Fridays × `friday_size_mult` 0.5**, 0DTE × 0.5 (T5.2). `avoid_0dte_after`
    15:15→**10:30** — a fire after the morning window takes the next expiry. R2's `auto` gate
    therefore measures to TP3 again when the size is ≥ 3 contracts (fixed 1–2 → TP2).
    ⚠ Re-set `contracts`=1 / `risk_pct`≤1 before real money (R5, R1).
  - **D3 Stop → on the close, not the wick.** `technique.stop_on_close` = on: a 1m bar
    must CLOSE through the stop (the book's watch-the-reaction stop, T4.3/p. 73); the
    0.25 R quote breach remains the crash brake. Mirrored in `outcome.simulate_plan`
    (`stop_on`, brake fill at 0.25 R) and the backtester, so sweeps before/after are not
    comparable (`sweepVersion` changes). Counterfactual: the old rule is `stop_on_close`
    off.
  - **D4 Short side → on.** `technique.long_only` = **off** (spec Q10 lifted). Two mirror
    setups in every plan: **reject** (`r*`, short AT resistance from below — "sell at
    resistance", p. 74 — no confirmation, stop above the zone high) and **breakdown**
    (`d*`, a confirmed close through support: volume surge + decisive bearish candle +
    follow-through, stop above the most recent swing high, `above_break_top`). Expressed
    with **puts only** (just-OTM put, strike capped at TP2 from below); no share shorting.
    Tracker, replay scorer, exits, quote brake and the option pick are direction-aware.
    Book fidelity note: the author is long-biased and never spells out the short rules —
    these are OUR mirror, to be measured separately (`byKind` reject/breakdown in sweeps).
  - **D5 Gap rule → keep 1.0 R, and use the pre-market smartly.** Not traded on (R6.4),
    but at `technique.arm.preopen_at` (09:25 ET) every armed plan is judged against the
    pre-market print: which triggers the open would gap past/through/void is journaled
    (`TechniquePlanPreopen`) and shown; when EVERY valid trigger is already dead,
    `technique.arm.preopen_replan` rebuilds the plan from the same prior-session structure
    re-anchored to the pre-market price (`build_session_plan(reference_price=)`, levels
    flip roles around the new price) and arms it in the old plan's place
    (`TechniquePlanReplanned`, `trigger=preopen_replan`, parent linked). For a re-planned
    run the gap-void rule measures the 09:25→09:30 surprise (`referencePrice` is the
    tracker's prev_close). Evidence for §1.1 still accrues on the valid 08-25 samples.
