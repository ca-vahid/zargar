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

### 1.4 Fire-time critic — net saver or net cost? → DEMOTED 2026-09-09, then RETIRED from the entry path 2026-09-15 (§5 `deterministic-entry-v1`)
**Status (2026-09-16):** CLOSED as a live question. Since v0.7.95 the fire-time critic is neither the decision
authority nor on the latency path: the app's encoded rules decide (`fire_decision_mode=deterministic`), the
momentum-family veto is retired, and the critic runs only under the explicit `legacy` rollback. The "advisory-no vs
yes fills" re-tally can no longer accumulate; the comparison that replaces it is **outcomes by policy version**
(`legacy-critic:*` rows vs `deterministic-entry-v1` rows in the profitability report) and, if a person enables
`fire_evidence_mode=after_close`, the model's after-the-fact opinion over the frozen decision as evidence only.
The history below is kept as the evidence that led to the demotion.
- *Status on day 10 (2026-09-09):* the decision threshold below was applied: 25 scored kills, net +0.5R, five of the nine
wrong ones the same at-level-reject shape (1.4b). `critic_mode=momentum_only`: bounces/rejects proceeded with
the verdict recorded (`criticAdvisory`), breakouts/breakdowns were still vetoed.
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

### 1.4b Critic vs T4.2: a systematic bias against at-level rejects? → moot since 2026-09-15 (critic off the entry path; kept as evidence)
- **2026-08-31 (day 5): the critic's first two WRONG kills since the fixes, both the
  same shape.** MUU r3 (killed ×2 → TP2, **+1.77R foregone**) and SOLS r1 (killed →
  TP3, **+2.44R foregone**, MFE 6.7R): in both, the critic argued "price already
  traded through the level on real volume = true breakout; shorting it is a
  knife-catch" (T2.5/T3.3 cited). Tape-based, coherent — and wrong both times:
  the pokes failed and the rejections paid. The structural problem: T4.2 rejects
  enter AT the level with NO confirmation; at fire time a reject will almost
  always look like momentum through the level, so demanding rejection evidence at
  that instant is a bias against the archetype — the same frame that was right
  about QCOM (a genuine thrust that ran) and INTU/T. Same-day saves for balance:
  PANW r1 (−1.25R avoided), UBER b2 ×2 (−1.05R avoided).
- **Candidate fix (prompt, not threshold):** teach the fire critic that for
  at-level kinds a trade *through* the level within tolerance is not by itself
  breakout confirmation (that requires close-through + T3.3a-c), and that its job
  is judging whether the break would CONFIRM — not whether price touched beyond.
  Hold until ≥5 reject kills are scored: running reject-kill counterfactual is
  the decision input (today −4.21R foregone vs +2.30R saved overall).
- **Day 6 (2026-09-02) scorecard:** 8 critic kills. WRONG: CRCL b1 bounce (+2.35R, all three
  targets inside 10 min) and HOOD b1 bounce (+2.60R) - both killed as "bounce into an active
  liquidation / falling knife / single-touch level". RIGHT: NOW b1 (-1.02R), VST r2 (~0).
  MOOT (never filled inside the entry window): IONQ, LITE, TXN, ARM. Running tally of scored
  wrong kills: MUU +1.77, SOLS +2.44 (day 5), CRCL +2.35, HOOD +2.60 = **4 kills, +9.2R foregone**
  vs 2 right kills avoiding -2.3R. The pattern is the same on both sides: the critic reads
  1-minute momentum INTO the level as a reason not to trade AT the level, which is the method's
  entry by definition. Prompt-fix candidate (mirror of the 08-28 direction clause): "a bounce
  fires into a decline and a reject fires into a rally - momentum into the level is the setup,
  not a kill reason; kill only when the level is already lost on a CLOSED bar or the volume
  read contradicts the plan". Decision threshold was >= 5 scored kills - at 4 now; one more
  scored day decides.
- **Day 7 (2026-09-03) scorecard - the blunt fix is withdrawn.** 3 scored kills: SOXS r1
  (-5.58R avoided, RIGHT), SOXS r2 (-2.61R avoided, RIGHT), SLB r2 (+2.50R forgone, WRONG).
  Nine scored kills over three days: wrong kills forfeited **+11.7R**, right kills avoided
  **-10.5R** - the critic is break-even, and "momentum into the level" cut both ways (right on
  SOXS where the level was gone within two closed bars, wrong on SLB/CRCL/HOOD where it held).
  REVISED candidate: the critic may kill on structure ("the level is already lost on a closed
  bar", "the stop is inside the bar range") and on volume contradiction, never on momentum
  alone; and it must state which of the two it used. Threshold reset: >= 10 scored kills under
  the current prompt with a net R of the kills below -3R before the prompt changes. Tally: 9,
  net -1.2R.
- **Day 8 (2026-09-04):** KORU r2 (-1.65R avoided, RIGHT), NOW b2 (-1.59R avoided, RIGHT).
  Tally: 11 scored kills, right 6 (-13.7R avoided) vs wrong 5 (+11.7R forgone), net of the
  kills **-2.0R** in the critic's favour. The prompt stays; threshold unchanged.
- **Day 9 (2026-09-08):** 9 kills - 8 right (-8.3R avoided, 3 of them moot/unfilled), 1 wrong
  (RDDT b2 +1.28R; RDDT b3 +0.75R on the replay but never filled live). **Tally: 20 scored
  kills, right 14 (-22.0R avoided) vs wrong 6 (+13.0R forgone), net +9.0R in the critic's
  favour.** The critic is now clearly earning its keep; the "momentum into the level" kills
  were right on 5 of 6 today. Prompt stays. Question 1.4b is closed unless the tally flips.
- **Day 10 (2026-09-09): the tally flipped back.** 5 scored kills: right 2 (MU r1 -1.08R, WDC r1
  -1.25R), **wrong 3 (APLD r1 +2.88R, OKLO r1 +3.34R, SNDK r2 +4.58R, all rejects killed as
  "momentum through the level")**, 3 moot (LITE, RDDT invalidated on the plan; IREN unscorable).
  **Tally: 25 scored kills, right 16 (-24.3R avoided) vs wrong 9 (+23.8R forgone), net +0.5R.**
  Of the 9 wrong kills, 5 are the same shape (MUU, SOLS on day 5; APLD, OKLO, SNDK today): a
  T4.2 reject at the level, killed because the fire bar looked like a thrust. The threshold in
  the REVISED candidate above (net of kills below -3R) is not crossed, so the prompt stays
  tonight - but 1.4b is REOPENED, and the next step is cheap and offline: re-judge the 25
  recorded kills under the candidate rule (kill on structure or volume contradiction only,
  never on momentum alone) and count how many of the 9 wrong ones it would have let through
  versus how many of the 16 right ones it would have released. If that reads better than
  +0.5R, propose the prompt change in §5 with the 25-kill evidence.

### 1.5 Blue-sky ladder R:R (T4.4 2/4/6%) — optimistic by construction
- A breakout with no resistance overhead gets targets at +2/4/6% and often a huge R:R;
  the grade caps at B for this reason. Open question: should TP1 for blue-sky breakouts
  be ATR-derived instead of 2%? Needs fired-breakout outcome data (none yet).

### 1.6 Wide-spread skips vs shares fallback → DECIDED 2026-09-12 (C1/C2, §5): shares are EM's Practice vehicle
**Status:** 8 of 9 fires in the week of 09-08 died on option spreads and only 1 of 37 baseline fires sat on an
option-liquid name. The nightly liquidity screen routes untradeable names to the shares fallback, the pick retries
the next strike / next expiry, and `techniques.enhanced_market.entry_fallback=shares`. The open question is now
the mirror one: over ten sessions of shares fills, does the option leg on the 24 liquid names beat the shares leg
in R and in $? Shorts still need a tradeable put.
- **Evidence caveat (2026-09-02):** until 13:42 ET on 2026-09-02 every option quote in the
  app was the CBOE chain, ~15 min DELAYED and re-stamped as fresh (PLATFORM-RULES 2026-09-02,
  invariant 14). T5.4/T5.3 skips before that judged a stale spread/IV; count "wide-spread
  skip" events from 2026-09-03 on only. Picks are now re-priced on the Alpaca OPRA NBBO
  before sizing and the entry limit; the spread gate is re-judged on that NBBO (see §5).
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
- **2026-09-16:** the "critic as chop filter" branch of this question is moot - the critic no longer decides
  entries (§5 2026-09-15). If mid-day is ever re-tested, the filter is the encoded rule set (volume floor, R3.2
  false-break cap, decisive-candle checks) and the finding must be read against `deterministic-entry-v1`. The
  toggle stays OFF.

### 1.8 Is the R2 bar (3.0) leaving a 2.0-3.0 band on the table? ⏳ open - R2 stays by user decision (2026-09-09); the weekly gate audit keeps the number
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
- **2026-09-01 · Weekly include-invalid audit #2 (sweep `0894b5d7`, plans built 08-31,
  traded 09-01):** 54 gate-rejected fires, +5.51R total but **mean +0.10R** — the
  micro-scalp profile again (41 "winners" hitting sub-1R ladders that spreads erase).
  By planned R:R band: **2.0–3.0: n=2, −0.23R, 0 wins**; 1–2: n=8, −1.19R; <1: n=44,
  +6.95R (targets a few ticks away). The band that would justify lowering R2 was
  empty-to-negative today. Running band tally since 08-26: still below the +0.3R bar.
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

### 1.11 Gap-day wait (R6.6) — does it hold out of sample? ⏳ new (2026-09-12)
- Adopted on sweep `evo-C3-gap0.5` (+5.1R vs baseline over 08-24..09-11, six fewer fires, non-gap days
  untouched). It is the first rule taken from the author's practice that survived its sweep.
- **Decision threshold:** after ten sessions with fills, compare gap-day fires held vs the same
  sessions' counterfactual without the wait (the tracker journals `gap_day` and `break_outside_window`,
  so the replay can score both). Revert if the held fires would have made > +2R net.

### 1.12 Pre-open re-plan: carry the evening triggers (C3b) ⏳ new (2026-09-12)
- IBIT r2 (+4.8R, 09-11) was discarded by the 09:25 re-plan. Evening triggers now ride along as
  `e_<id>` and are journaled `preopen_carried`; the open judges each on its own gap rules.
- **Decision threshold:** ten sessions; tally carried-trigger fires vs re-plan-trigger fires in R.
  If the carried set is net negative, the re-plan goes back to replacing.

### 1.9 An entry that fills AFTER a bar already closed through the stop (NOW 2026-09-02) - new

NOW r1 (reject 141.69, stop 142.40) fired on the 09:30 close; the put's BUY LMT 2.03 did not
print until 09:34 (1.93), but the 09:33 bar had already CLOSED at 142.57 - through the stop.
The runner has no rule for this: a working entry keeps working through a stop-close bar, and
the position opens with its thesis already "wrong" by our own stop definition. Today it paid
(+4.20R to TP2 on the counterfactual) because the level held on the next bar. Question:
should a stop-close bar CANCEL the working entry (the reject failed) or is the fill window
the only test? Decision threshold: 10 such cases scored by the counterfactual/outcome path;
cancel if the mean R after a pre-fill stop-close is < 0. Counts so far: 1 (NOW: +4.20R on the
put's late fill, but **-1.24R on the plan itself** - a shares-style fill at the level was stopped on
the 09:33 close; the option's 09:34 print turned a stopped plan into a winner by luck).
Day 7 adds the mirror case: MSTR r2 fired 09:43, the put's ask moved 2.80 -> 3.30 within
minutes and the resting order never filled - a right call missed on tempo, not chased (T4.1).
Fire-to-order latency (critic ~60 s + pick + sizing) is now a measured cost: 2 of 6 fires this
day were priced a beat late (PLTR stale limit - bug, fixed; MSTR ran away - rule). Candidate
for T-6/exit-tempo work: submit the entry BEFORE the critic on A-grade plans and let the critic
cancel it (a resting order costs nothing) - to be sized against the critic's save rate above.

### 1.10 Live plan vs replay parity - RESOLVED 2026-09-05 (phantom close bar)
DELL 2026-09-04: the armed plan (built 09-03 20:54) had r1 INVALID (R3.2, stop 3.23 < 2x ATR
1.84); the replay of the same close had it VALID (stop 4.28) and it fired 09:39 for +2.55R.
`replay-facts` on the run's saved bars: detectors unchanged (no code drift). The saved 1h bars
carried a 16:00-stamped one-print bucket that a next-day fetch lacks; it shrank the stop buffer.
Platform fix: `clip_to_rth` at the fetch source (PLATFORM-RULES 2026-09-05). Watch: every
evening-batch plan before 2026-09-05 was built with that phantom bar - stops were slightly
tighter than the replay's, so some R3.2 rejections in the 09-01..09-04 batches were false.
DELL is ledgered as a bug-missed trade (counterfactual 05a21c46): **NOT FILLED** - the 530 put
printed 5.15 on the fire bar and 10.95 one minute later (DELL fell hard); a resting limit at the
fire-bar ask never filled inside the entry window. The +2.55R is the underlying's number; under our
never-chase execution the trade was unreachable anyway. The defect is real, its cost on Friday was 0.

## 2. Findings (settled, with evidence)

- **2026-09-14 · External review (reviewer packet `reviews/DEV-TEAM-HANDOFF-2026-09-14.md`), Delivery A
  landed.** Six correctness defects confirmed and fixed (response: `reviews/DELIVERY-A-RESPONSE-2026-09-14.md`):
  the shares fallback kept the option's x100 (HPQ -$7.19 booked as -$719.30 and a false loss halt; five
  records in the dry-run manifest, one real), a two-contract exit waited a bar when TP1 and TP2 printed
  together, contracts were sized on the pick's stale ask, the 09:25 pre-open called twelve shorts
  `gapped_past` with the pre-market print still between entry and stop (SPY, IBIT, NKE, UNH, DIA, XLF, XLU,
  TLT, IWM, CVNA + USO/BSX rejects that gap_void would have voided anyway) and replaced them, the critic's
  opinion/advisory flag/errors were dropped on restart (INTC, HOOD), and short contracts were scored as longs
  by the adapters (no historical row affected). Policy decisions recorded there: risk budget is a BOUND
  (zero contracts allowed), quote confirmation counts distinct observations. The reviewer's larger point
  stands and is not fixed by these: the morning source supplies tickers, not the author's scenario (Delivery
  B design: `reviews/DELIVERY-B-DESIGN-2026-09-14.md`).
- **2026-09-08 · Does the nightly LLM plan review earn its time? First measurement.** Join of the
  replay's VALID fires to the evening batch's verdict, three sessions (09-03, 09-04, 09-08):
  plans the review ACCEPTED: 6 fires, **+3.10R (+0.52R/fire)**; plans it REJECTED: 4 fires,
  **-2.59R (-0.65R/fire)**. Ten fires is not proof, but the direction is the right one and the
  cost fell to ~5 minutes at 16-wide. Decision: keep it, re-measure at ten sessions (~09-19);
  cut it only if the accepted/rejected gap closes. The FIRE-time critic is a different question
  and is proven (+9.0R over 20 kills, 1.4b). *Update 2026-09-09: day 10 pulled the critic back
  to +0.5R over 25 kills (1.4b reopened); the review's own tally after four sessions: accepted
  12 fires -1.07R (-0.09R/fire), rejected 7 fires -3.34R (-0.48R/fire) - still the right
  direction, still not proof; decision at ten sessions stands.*
- **2026-09-08 · Option trade prints are available to us.** Alpaca's options data on our
  subscription returns historical option TRADES: the author's TSLA $360C (08-31) shows 10,000+
  prints and 37,874 contracts in the first 40 minutes. T-12 can be tested on history, not only
  live. Plan: `FLOW-CONFIRMATION-PLAN.md`.
- **2026-09-11 · Day 12 (Fri, CPI gap-up) and the two-week review.** 3 fires (AVAV, MUU, BSX -
  the critic timed out on two, said no to one), ALL three blocked by the spread gate (67 / 36 /
  80% NBBO spreads); MUU and BSX went on to TP1, AVAV stopped. Book unchanged at $9,929.64.
  Thu+Fri together: 9 fires, 8 spread-gated (4 later TP1, 4 stopped - the gate was net zero), 1
  fill (HOOD -$66). The author sat Friday out ("everything gapping up, moves exhausted, no
  risk/reward"). Deterministic replay (plans at the 09-10 close): 5 valid fires **+7.41R** -
  IBIT r2 +4.83R (TP2), CRWD b2 +2.28R, BSX b1 +1.30R, AAPL k1 +0.01R, INTU r2 -1.02R; the
  three review-rejected ones net +1.27R. **IBIT was armed and is one of the 16 option-liquid
  names, and it never fired live: the 09:25 pre-open re-plan on a +0.68% pre-market print
  "killed every trigger" and re-armed a plan whose only trigger was invalidated at 09:31.** The
  static plan's reject at the original level paid +4.8R. Pre-open re-plans now have two
  documented losses (this, and the HOOD/KLAC far-TP1 geometry) against no documented save -
  they go into the change plan as C3b. The chain snapshots say only 16 of 135 universe names have a median
  near-money option spread <= 10% and 83 are above 20%: EM plans setups on names it cannot
  trade in options. The twelve-session review and the proposed changes (tradeable-vehicle
  universe, shares fallback in Practice, gap-day policy, targeted scratch, consolidation-break
  trigger) are in `METHOD-CHANGE-PLAN-2026-09-12.md` for the other desks' review before any
  build.
- **2026-09-10 · Day 11 (Thu, PPI gap-down; first session with the critic advisory): the first
  EM fill in eleven sessions, and it lost -$66 on a stop that a +2.5R move had already paid for.**
  42 plans from the evening batch + board auto-arms. 6 fires, the critic said no to all 6 (advisory
  now), 5 of the 6 were then skipped by the T5.4 spread gate (11-64% NBBO spreads on $0.9-$2.5
  contracts at the open: TQQQ 13.9%, IREN 11%, SHOP 35%, HPE 42%, KLAC 64%). HOOD r1 passed:
  2 x HOOD 09/11 $114P at $1.73 (09:47, `criticAdvisory: true`), HOOD dropped 115.09 -> 113.64 by
  09:51 (**+2.5R on the underlying in four minutes**, the put ~+40%), then rallied; the 10:01 bar
  closed 116.18 through the 115.67 stop and the quote brake sold at $1.399: **-$66.20**. HOOD then
  fell to +8R by the close. Under the stop-on-close rule every fire but IREN stopped first: TQQQ
  (10:24, MFE 0.7R), SHOP (09:38), HOOD (10:01, MFE 2.8R), HPE (10:41), KLAC (11:33, MFE 2.0R);
  IREN b1 - the one the spread gate blocked - hit TP1 at 09:33 (MFE 3.2R). So the critic's "no" was
  right 5 of 6 on outcome, the spread gate saved four stops and cost the one winner (net ~+1R for
  the gate, 1.6), and the lesson is not the filter, it is the EXIT: three of six fires reached
  +2R and gave it all back to the stop because TP1 sat 3-7R away. Replay (sweep `<see api_sweep
  09-10>`, plans at the 09-09 close): 2 valid fires, both review-rejected close breakdowns, -0.02R -
  nothing missed on the deterministic book; gate audit 69 sub-R2 fires **+6.07R** (+0.09R/fire, the
  second positive day in a row, 1.8 - R2 stays by user decision, noted). Platform: two restarts,
  both overnight, none in the session. Books: EM $9,929.64. The author posted no trade today
  (Alertsify marketing and a leaderboard only).
- **2026-09-09 · Day 10 (Wed, gap-down open, SPX under 7700): zero fills, 18 fires, 17 critic
  kills, and the one survivor was skipped on the option spread.** 50 plans armed from the
  evening batch (run by the desk through the API after the run-cap incident, see PLATFORM-RULES
  2026-09-09) + 7 auto-armed from the author's 09:02 video / 09:23 gap-down post (GS, META,
  MSTR, NVDA, NBIS, GOOGL, CVNA - none fired). Gap rules voided 27 triggers and 33 more were
  invalidated at the open: correct behaviour on a gap day. Fires (unique setups, app-scored on
  the live plan geometry): MU r1 stopped -1.08R (RIGHT kill), WDC r1 stopped -1.25R (RIGHT),
  **APLD r1 -> TP3 +2.88R (WRONG), OKLO r1 -> TP1 +3.34R (WRONG), SNDK r2 -> TP2 +4.58R
  (WRONG)**; LITE r2 and RDDT b2 invalidated on the plan (moot), IREN b1 unscorable (moot). All
  three wrong kills are the 1.4b shape again: a REJECT short killed as "a short into a live,
  volume-confirmed thrust" that then reversed and paid. OKLO fired five times; the fifth (09:57)
  survived only because the critic timed out (fail-open, 1/3 budget) and was then skipped by
  T5.4 (13.2% NBBO spread on a $1.2 contract) - 1.6 evidence: the underlying made +3.3R.
  Deterministic replay (sweep `ea7001abaa`, plans at the 09-08 close): 9 valid fires, **net
  -4.92R** (RDDT b2 +0.73 the only winner; MU/LITE/VRT stopped), 6 of 9 on armed names
  (coverage 67%; the three uncovered were review-rejected AXP/SOXX/EEM, all small losers). The
  replay does not contain APLD/OKLO/SNDK as valid fires: those were pre-open RE-PLANS on the
  gap (the static sweep cannot see re-plans, 2026-09-05 finding), so the day reads two ways -
  on the deterministic book the method lost -4.9R and the critic saved it all; on the plans we
  actually held the critic forgave +10.8R and saved -2.3R. Gate audit: 99 invalid fires (R2 <
  3) net +3.72R = +0.04R/fire before costs - R2 stays (1.8). Books: EM flat at $10,000.
  Platform: TWELVE engine restarts during the session (10:14-16:09 ET, other desks' PR merges
  #33-#47, versions 0.7.22 -> 0.7.33), each re-arming 54 plans, and a bar-delivery stall at
  15:07 ET that idled 49 plans through the close window (PLATFORM-RULES 2026-09-09) - the
  prime_close window was effectively not traded today.
- **2026-09-08 · Day 9 (Tue, first day on the per-technique books): zero fills, nine fires, the
  critic right eight times.** 64 EM plans in EM Practice (45 armed: 42 from the evening batch +
  3 auto-armed from his 09:23 watchlist post - MU, GOOGL, META - the first morning the board
  armed by itself). 9 fires, 9 critic kills, 0 trades. On the real bars: ASTS -2.75R, SMCI
  -1.03R, CRCL -1.16R, MU -1.54R, MUU -1.86R (all RIGHT kills, -8.3R avoided); CRCL b2, RDDT
  b3, MU b2 never filled (moot); **RDDT b2 +1.28R (WRONG kill)**. Net if all taken: -7.1R.
  Replay of the day (sweep --start 09-04): 4 valid fires, ALL on armed names (coverage 100%):
  RDDT b2 +1.28R and b3 +0.75R (both critic-killed live), SMCI r1 -1.03R (killed, right), META
  k1 -1.03R (the live runner skipped it four times and invalidated it at 15:11 - a skip that
  saved a loss). Auto-armed board names: MU fired twice and was killed correctly both times;
  GOOGL/META never fired. Books: EM flat at $10,000; the Tips and Team2 books traded on their
  own (-$224 / -$66). The author's feed was read the same evening - see
  `notes/2026-09-08-author-x-feed.md` and T-12 below: his wins are FLOW-timed (sweeps on the
  ask vs open interest), an input we do not have intraday.
- **2026-09-04 · Day 8 (Fri, 0DTE): zero fills, three right calls, and the author's best trade
  was invisible to our level detector.** 27 armed (LLM-verified, the bulk-arm bug from the
  evening before repaired), 3 fires, 0 trades: HOOD r1 skipped on a 15.4% NBBO spread (the
  level then failed, -1.08R - the skip was right twice over), KORU r2 and NOW b2 killed
  (-1.65R / -1.59R if taken). -4.3R avoided. The author's MU call: "968 double-top break,
  target 989" - MU opened 971, ran to 1017 (+2.2R to his target, +5.2R to the high on a
  968/958 geometry). Our MU plan had NO level above the 958 close: his 968 was the 09-01
  session high (969.44), three sessions back and touched once, so the detector (prior-day
  HOD/LOD only + 2-touch pivots) never drew it, and the board check rejected MU on a 959
  reject with R:R 1.4. Even with the level, the 971 open would have "gapped through" it and
  the gap rule voids that. Two method questions, not a bug: T-11 (window extremes as levels,
  sweepable knob `seed_window_extremes`, off) and the gap-through continuation (T-6/T-7).
  Did-we-miss for FRIDAY itself (sweep `--start 09-03`: plans built at Thursday's close, scored on
  Friday's bars - the sweep semantics, see below): 117 sessions, 2 valid fires - DELL r1 +2.55R
  (DELL WAS armed on Friday and the live runner never fired it: live-vs-replay parity question,
  §1.10), VST r1 -0.70R (not armed, correctly). Practice
  -0.11% on the day is tips/Team2 activity in the shared book, not EM.
- **2026-09-03 · Day 7: zero fills, and flat was the right outcome (-7.0R avoided).** 36 plans,
  6 fires, 0 trades. On the real bars: SOXS r1/r2 shorts into a vertical breakout would have lost
  -5.58R and -2.61R (critic killed both - RIGHT); PLTR r2 was missed by the stale-limit bug
  (fixed same day, PLATFORM-RULES 2026-09-03) and would have lost -1.33R / -$53.08 (ledgered as a
  counterfactual anyway); MSTR r2's put ran 2.80 -> 3.30 before the resting order could fill and
  the underlying never re-touched the entry (T4.1, not a bug - tempo); SLB r2 was killed and made
  **+2.50R** (all three targets by 11:03 - WRONG kill); CVX b1 fired at 15:59, moot. Author
  board day 3: his valid levels ~0 (AAPL breakout -0.04R, AMZN never touched, his four armed
  names never fired); R2-rejected on his names net -0.9R (TSLA k1 +0.84R quick, NVDA r1 -1.13R).
  Practice +0.51% on the day is the two tip positions parked in the book, not EM.
- **2026-09-02 · Day 6: a bug cost the day's only fill, and the desk now keeps a counterfactual
  ledger.** NOW r1 fired 09:31 (reject 141.69, put 140P Sep-4 BUY LMT 2.03). The 10:04 restart
  stranded the working entry (three shared-runtime gaps, fixed the same day, PLATFORM-RULES
  2026-09-02). Replayed after the fix through the runner's own exit rules on the real bars:
  fill 1.93 at 09:34, TP2 138.71 at 10:17 with the put at 3.44 -> **+$148.92 net, +4.20R**
  (`technique_counterfactuals` 99ea88e4; Armed > History "Missed by a bug"). User decision:
  bug-missed trades are always replayed and ledgered AFTER the fix, NEVER booked into Practice
  - the real book stays what actually happened. Same morning: critic killed CRCL, HOOD, IONQ,
  LITE, TXN fires (outcomes pending); the author's 09:01 video ingested unattended (7 symbols,
  board 2 armed / 5 new) plus a 09:19 post (4 more) - see INGESTION-PLAN 2026-09-02 ops note.
  Method question raised: §1.9 (entry filled after a stop-close bar).
- **2026-09-02 · Author-levels A/B, day 2: strictness won again.** His seven video names built
  plans (AAPL/AMZN/MRNA/META/WMT/MSTR/GOOGL, arming left to the human, none armed). On the
  real bars, the VALID triggers on his levels that were touched: MRNA k1 breakout 154.7
  (-1.97R, stopped in 9 min), WMT k1 breakout 106.64 (-0.43R), GOOGL d1 breakdown 333.05
  (-1.03R) = **-3.4R over 3, 0 wins**; his AMZN/META/MSTR/GOOGL-upside levels were never
  reached. The R2-REJECTED triggers on the same names were mostly small quick winners (GOOGL
  b1 +0.65R in 3 min, AMZN b1 +0.24R, WMT r1 +0.27R, MRNA b1 +1.15R) - exactly the "he banks
  25% in five minutes" tempo his own transcript describes. Two days in: our gate is right to
  refuse his levels under OUR exits; the open question is exit tempo, not level quality (T-6
  / exit-tempo parameterisation, §3). Day 1 + day 2 tally on his levels: 0 wins under R2.
- **2026-09-02 (corrected 09-05) · Sweep semantics: `--start D --end D` builds plans at D's CLOSE and
  scores them on D+1's bars.** That is why a same-day sweep returns sessions=0 (D+1 has no bars
  yet) and why it "worked the next day". To review session S, sweep the PREVIOUS session S-1.
  The 09-01 sweep on 09-01 evening scored 09-02; the 09-02 sweep on 09-03 scored 09-03; the 09-03
  sweep on 09-04 evening scored 09-04. Earlier entries labelled by sweep date are off by one session.
  **Run 2026-09-03 09:50:** confirmed - the next-day replay of 09-02 works (universe, include-
  invalid): 4 valid fires, 1 win, **-1.30R**; nothing our arming missed. Without the gap rules the
  same day would have fired 14 times for **-8.13R** - the gap rules saved ~6.8R on a gap day.
  Claim check flagged T1.3a (prior-day HOD/LOD strongest) as FAIL on this session (respect 27.9%
  vs 30.5% other, n=86/243) - one session, noted for the weekly audit, not acted on.
- **2026-09-01 · Day 5 "did we miss anything": nothing — and the pre-open re-planner
  earned its keep, measurably.** Whole-universe replay of the 08-31-close plans on the
  09-01 tape (sweep `0894b5d7`): only **3 valid fires, net −1.44R** (ANET b2 +0.12,
  VZ k1 −0.31, CRWD b2 −1.25) — and all three symbols WERE in the 43-symbol armed
  fleet (coverage 3/3; the reject-coverage leak of 08-27 is closed by arming wider).
  Yet none of the three fired live: the tanker-strike gap-down made the 09:25
  pre-open check **re-plan** ANET, CRWD and VZ (their stale close-built levels never
  became live triggers), and it re-planned GLD onto the 400.83 resistance that
  produced the day's only trade, **+$175 / +2.0R**. Separation attributable to the
  re-planner today ≈ **+3.4R** (−1.44R of stale fires avoided, +2.0R enabled). Caveat
  the static sweep cannot see re-plans by construction — a "sweep vs live" gap on a
  gap day is the re-planner working, not a bug. Capture-rate join: identified valid
  R −1.44 vs captured +2.0R — the first day live beat the replay.

- **2026-09-02 · Practice option FILLS before 2026-09-02 13:42 ET are suspect (delayed chain).**
  The tips desk found every option quote was the ~15-min-delayed CBOE chain re-stamped as
  fresh; practice fills (incl. GLD 2026-09-01) were booked at the delayed ask. What stands:
  the plan-level R (underlying bars), bar-based sweeps (`simulate_plan`) and the counterfactual
  ledger (contract 1m prints). What does not: $ P&L of practice option fills 08-22 → 09-02 13:42.
  Any evolution sweep or graduation stat that scores on practice fills must start 2026-09-03.
- **2026-09-01 · EM's FIRST LIVE TRADE — a winner, and the whole pipeline held.**
  GLD r1 reject (short gold at 400.83 after the tanker-strike rally spiked into a
  planned resistance): the critic killed the first five fires as "still momentum,"
  approved the sixth at 10:30 on real rejection evidence, bought the Sep-4 400P at
  3.80, managed it all day (max adverse 0.21R), flattened before close at 5.55 —
  **+$175 (+46% on premium); the underlying short scored +2.0R**. The five kills
  produced a near-perfect entry (§1.4b counter-evidence: at-level patience
  PERFECTED this one, vs costing MUU/SOLS yesterday — tally continues). Same day:
  RDDT r1 approved by the critic but refused by T5.4 (22% option spread) — the
  author's "contracts are terrible" veto, automated. The trade also survived a
  mid-morning server restart (state re-attached). Fires 16, kills 14, approvals 2,
  trades 1, P&L **+$175**.
- **2026-09-01 · Author-levels A/B, day 1: strictness won.** His NVDA "puts below
  216.21": the break reached only 215.10 and reversed to close 217.54 — the
  deterministic replay scores his trade `not_triggered`/scratch and a held put
  lost; our NVDA plan (b2 212.60 / r3 229.40) correctly never engaged. His NFLX
  wedge levels (80.65/81.73) whipsawed both directions (79.60 → 82.13 → 80.80);
  the one sim-fire near his upper line made +0.23R — noise. Meanwhile our one
  approved trade (GLD) made +2R. One day proves little (sweep `0894b5d7`,
  include-invalid), but day 1 of the live A/B goes to the R2 gate.

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
  **2026-09-09 exit-tempo half measured (FLOW-CONFIRMATION-PLAN phase 1b, `flow_variant --tempo`):**
  our 19 replay fires exited on premium percent (his tempo) lose in every grid cell (best
  -14.8% mean); the underlying ladder is better on the same fires. The continuation ENTRY
  archetype (backlog 9) is still unmeasured on a parameterised ladder; the exit half is closed.
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

### T-11 · Multi-session swing extremes are levels (the author's "double top")
The detector seeds only yesterday's HOD/LOD (T1.3a) plus 2-touch pivots. The author's MU 968
(09-04) was the 09-01 session high, three sessions back, one touch - the strongest level on his
chart and absent from ours. Knob `seed_window_extremes` (MarketRules + Thresholds, default off)
seeds the lookback window's highest high / lowest low as `T1.3a-window` levels. Test: variant
sweep `--set seed_window_extremes=true` vs baseline over 2026-08-24..09-03 (launched 09-04
evening, label evo-T11-*); adopt if net R/fire improves by >= +0.3R and the fire count does not
double. Related: the gap-through case (MU opened above the level) is T-6/T-7's territory.
**Result (2026-09-04 evening):** baseline 1,053 sessions / 26 fires / **+0.79R**; variant 26 fires /
**-0.12R** (bounce +0.84, reject +2.01, breakout -0.28, breakdown -2.69 - the extra window-LOW seeds
produced losing breakdown shorts). -0.035R/fire: **NOT adopted**, knob stays off. What the MU case
actually needed: the morning board build's 3-session window (09-02..09-04) no longer contained the
09-01 high; the evening build's window did, and the detector found 969.44 there only with the knob.
Next test: `lookback_sessions=5` as its own variant, and the gap-through continuation (T-6/T-7).

### T-14 · Scratch rule: stop to breakeven after +0.75R (exit tempo as management, not as a target)
Day 11's HOOD (+2.5R MFE in four minutes, stopped -1R) and KLAC (+2R, stopped), day 10's LITE and
WDC, are one shape: the book's ladder puts TP1 at the next zone (3-7R away on re-planned levels),
so a fast +2R move has nowhere to bank and the full risk stays on until the stop. Measured on the
12-session baseline (`evo-T13-baseline`, 36 valid fires, net -1.82R): 19 of 36 reached +0.5R, 12
reached +1R, 8 reached +2R; of the 16 stops, 8 had first been +0.5R. A crude hybrid (half off at
+0.75R, stop to breakeven on the rest) turns -1.82R into **+5.3R**; the same at +1.0R gives -2.7R
and at +1.5R -0.4R - the result is fragile (seven fires sit between +0.75R and +1R), which is
exactly why it needs the real simulator, not this arithmetic. Test: `breakeven_after_r` and
`first_trim_r` knobs in `simulate_plan` + the live exit policy, swept over 08-24..09-10 against
baseline; adopt bar D7. This is T-6's exit-tempo question asked the right way: as management of
the fire we already took, not as a replacement for the ladder.
**Verdict 2026-09-10 22:20 ET: NOT adopted - the real simulator says the opposite of the arithmetic.**
Sweeps over 08-24..09-10 (1,400 sessions, 37 valid fires each; baseline `b48db0763a`): baseline
**+3.98R**; scratch at 0.5R `de5cf24a45` **-0.09R**; at 0.75R `2e1b5600ac` **+1.21R**; at 1.0R
`80711f4d88` **-4.07R**. The rule does what it says - bounce win rate 57% -> 79%, reject 42% -> 83% -
but it pays for it by halving the position on every winner before the ladder, and this method's
whole edge is the few runners (5 TP3 exits carry the book). Losers avoided are small; winners
capped are large. The crude MFE arithmetic in the theory counted the trimmed half as if it still
rode the ladder; it does not. Both knobs stay in the code at 0. What the evidence does say: the
ladder's first rung is the problem only on RE-PLANNED gap-day levels (HOOD, KLAC, LITE, WDC), not on
the book's normal geometry - a targeted version (scratch only when TP1 > 3R away) is the next
variant, cheap to sweep, not built tonight.

### T-13 · Gap-through continuation (the author's SPY trade of 2026-09-09) - sweeping
His one posted trade on day 10: SPY puts on "the breakdown of PLOD" - SPY closed 09-08 with a
low of 765.14, opened 09-09 at 764.08 (through it) and drifted to 760.94 by 11:25; $0.70 ->
$1.58, +126%. Our SPY trigger was voided at 09:31 as `gapped_through`, Tips said "not chasing",
Team2 read "scenario 4, focus on puts" and did not enter. Theory: a bounce/reject level the open
gaps THROUGH is not dead - it is a continuation setup in the gap direction. Built 2026-09-09
evening as a sweepable knob (`gap_through_continuation`, default off, MarketRules + Thresholds):
the trigger is re-aimed as a break the other way - stop at the gapped level (a reclaim
invalidates), entry on a confirmed break of the opening bar's extreme through the EXISTING break
machinery (volume surge, decisive candle, follow-through, R6 windows), targets 1R/2R/3R on the
30/40/15 ladder. Nothing changes live. Test: `sweep --set gap_through_continuation=true` vs
baseline over 2026-08-24..09-09 (`evo-T13-*`), adopt bar D7 (+0.3R/fire over baseline, fires
<= 2x). Related: T-6/T-7 (gap-through was already named as their territory on day 8).
**Verdict 2026-09-09 21:30 ET (sweeps `2b86fd5b7d` baseline, `3188f2fc69` confirmed, `b4faf2700d`
loose; 1,287 sessions, 08-24..09-09): NOT adopted.** 37 gapped levels converted per sweep. With
OUR break confirmation (surge + decisive candle + follow-through) only 2 continuations fired,
both losers, net **-1.28R** vs baseline. With his tempo (`gap_continuation_confirm=false`: first
close through the opening extreme, volume floor only) 16 fired: breakdowns (gap down through
support, short) 11 fires, 6 wins, **+0.95R**; breakouts (gap up through resistance, long) 5
fires, 2 wins, -0.23R; net **+0.72R = +0.05R/fire**, all in prime_open, before option costs.
Below the D7 bar (+0.3R/fire). The gap-down/short half is the only slice with a pulse (55% win,
+0.09R/fire); twelve sessions is thin. Both knobs stay in the code, off; re-sweep at 25 sessions.
His SPY trade is reproducible by the loose rule, but on the universe the rule does not pay.

### T-12 · Flow-confirmed entries (the author's actual trigger, read 2026-09-08) - REJECTED on history 2026-09-09
**Status: both forms (confirm gate, sweeps as trigger) measured and rejected; no rule change; the detector stays as research tooling. The paragraphs below are the dated record in the order it happened.**
Every win he posted (TSLA +240% Aug 31, GPRO Aug 31, NVDA +115% Sep 4, Sep 8 OTM prints) names
a SWEEP: contracts bought at the ask, many times the open interest, in a near-the-money 0DTE or
weekly strike, minutes after the open; exit the same day on premium percent. Our level says
where, his sweep says when. Theory: a fire counts only if such a sweep prints in the contract we
would buy within N minutes of the touch (variant on history with chain snapshots first, then a
shadow instance). Needs the engine piece: an intraday option-print sweep detector on the Alpaca
stream (Flow is nightly today; its reads did flag NVDA 11 / MU 11 / TSLA 9 on his days). Adopt
bar +0.3R/fire; measure exits in premium percent to compare with him (T-6). Evidence:
`notes/2026-09-08-author-x-feed.md`, flow_reads 09-01..09-08.
**Phase 0 built 2026-09-08 evening:** the detector finds his TSLA sweep at 09:40 (he entered 09:49),
GPRO at 14:22, NVDA's put flow at 09:42, and nothing on NVDA's liquid calls - see
FLOW-CONFIRMATION-PLAN phase 0 for the calibrated definition. Next: backfill the universe's
near-the-money contracts for the last 20 sessions and run the `flow_confirm` variant.
**Phase 1a verdict, 2026-09-08 late (the confirm-gate is REJECTED on history):** of the 30 valid
replay fires over ten sessions (08-27..09-08), 19 had a chain snapshot to rebuild the contract;
sweeps printed inside [-15, +10] minutes of the touch on **1 of 19** (META k1 09-08, a -1.03R
loser). All 19 unfilled by the gate would have made +2.61R. A gate that keeps 1 fire in 19 and
picks a loser is not a gate; the finding is that the author's sweeps do not sit on OUR levels
(GPRO had no level at all). D4 ("confirm, never create") is the wrong premise for his edge.
Next test (phase 1b): sweeps as the TRIGGER - every sweep in the universe's near-the-money
contracts, entered at the sweep minute and exited on his tempo (+100% / -50% / 15:45), scored
in premium percent from the contract's own 1-minute bars. `tools/flow_sweep_universe.py`.
**Phase 1b verdict, 2026-09-09 00:30 ET (sweeps as the trigger: REJECTED on our data).** 923 sweeps
across the core universe's near-the-money contracts over 8 sessions (08-27..09-08; the detector
that finds his TSLA/GPRO/NVDA trades). Every sweep taken as a trade on his tempo (+100% / -50% /
flat 15:45), net of $1.04 fees and a 5% slippage haircut: **847 trades, 30% win rate, mean -13.0%
of premium, median -55%** (439 stops, 188 takes, 218 flats). No slice survives: first sweep per
name -12.1%; first 90 minutes -5.0%; the best exit in a 5-point grid (take 30% / stop 30%, first
90 minutes, first per name) reaches a 56% win rate and still averages **-2.4%** per trade. AAPL is
the only name positive (+2.3% on 50). Conclusion: the mechanism he names, as observable from
public prints, has no standalone edge on our data. What we cannot observe from history is his
ask-side classification (our history uses the tick test) and his selection; what we cannot
verify is survivorship in what he posts. T-12 stays as a LOGGED signal only: phase 2 collects
NBBO-classified sweeps live at zero cost and the question reopens after 10 sessions of live
data, not before. No rule changes.
**T-6 measured the same night (our fires on HIS tempo): also negative.** The 19 replay fires with a
chain, entered in the contract our pick would buy at the fire minute and exited on premium
(grid of take 30-100% / stop 30-50% / flat 15:45), net of fees and slippage: best cell take 30% /
stop 30% = 32% win rate, **mean -14.8%**; the default +100/-50 = 21% win, -18%. The three
winners are the plan winners (HOOD +94%, DELL +95%, CVNA +38%); the losers include every
illiquid contract (HYG $0.05, LQD $0.11: the round trip eats them). The plan-level ladder on the
underlying (+0.08R/fire on the same 19) beats his tempo on our fires. T-6 is not adopted; exit
tempo is not where our edge is hiding either.

## 4. Optimization backlog (ranked)

1. **Capture-rate telemetry** — a weekly roll-up: identified R (scorecard theoretical)
   vs captured R (realized), with the friction reason for every gap. This is THE metric;
   the daily scorecards already contain the raw material.
2. **Gap rule decision** (1.1) once ≥20 voided samples exist.
3. ~~**Critic scorecard** (1.4)~~ — superseded 2026-09-15: the profitability report groups attempts, fills and
   refusals by policy version (`byPolicy`), and the optional after-close evidence records the model's opinion over
   the frozen decision. The kill-counterfactual tally is historical evidence only.
4. **Grade/analyst calibration** (1.2/1.3) at the 100-fire mark.
5. **IBKR activation** — execution + second data source; retire the sim-only options fills
   with real paper fills.
6. ~~Next-strike/next-expiry contract retry~~ — BUILT 2026-09-12 (C1, `pick_for_setup(retry_wide=)`).
7. **Blue-sky TP1 from ATR** (1.5) — pending fired-breakout data.
8. **Full Settings redesign** (task chip exists); slow-DB-writes investigation (chip
   exists); ~~persist critic veto counts across restarts~~ (no veto counter exists on the deterministic path).
10. **Over-budget option, affordable shares** (2026-09-16): 4 of the first 7 deterministic fires were refused by
   the F33 daily-loss bound or the FIX-03 2% trade budget because ONE contract risked more than the budget. Decide
   whether a shares fallback should be tried in that case (it is not built; today the fallback covers only
   untradeable options). Needs the user's decision and a cohort, not a threshold tweak.
9. **T-6 continuation-breakout walk-forward** (2026-08-29): sweep the archetype over
   60 days on the universe + SPY/QQQ/IWM before any live arming — deterministic,
   free, and it directly answers "are we too strict or missing a lane". (Exit-tempo half
   closed 2026-09-09, negative; only the entry archetype remains.)

---

## 5. Change log (parameter/rule changes — date · change · why · evidence)

- 2026-09-12 · **Gap-day wait ON** (`technique.gap_day_pct = 0.5`, `gap_day_wait_minutes = 30`; C3 of
  METHOD-CHANGE-PLAN-2026-09-12, user decision to implement the plan). On a session the symbol
  itself opens >= 0.5% from its previous close, no entry fires in the first 30 minutes ("give the
  open time", the author's own rule on gap days). Sweep 08-24..09-11 (`evo-C-baseline 793512a5b5`
  vs `evo-C3-gap0.5 e032e96d98`, 1,500 sessions): baseline 39 fires **+6.28R**, gap-wait 33 fires
  **+11.38R** (+5.1R, +0.18R/fire - below the D7 +0.3R/fire bar in per-fire terms, but it works by
  REMOVING six losing gap-open fires and touches nothing on non-gap days). Adopted on that basis;
  the continuation add-on (`gap_day_continuation`) added only +0.3R more and stays off. Review after
  ten sessions with fills.
- 2026-09-12 · **Shares fallback ON in EM Practice** (`techniques.enhanced_market.entry_fallback =
  shares`; C2) and **option-liquidity routing** (C1: nightly screen `technique.universe.option_liquidity`,
  24 of 135 names tradeable at spread <= 12% / OI >= 500 on the 09-11 snapshot; an untradeable name
  arms with the shares fallback; the pick retries the next strike / next expiry on a wide spread).
  Why: 8 of 9 fires in the week of 09-08 died on option spreads, and on the 12-session baseline only
  **1 of 37 valid fires was on an option-liquid name** (-1.03R) - EM's edge, such as it is, lives on
  names whose options we cannot trade. Shares are the vehicle in Practice until that changes;
  shorts (puts only) still skip when the put is untradeable.
- 2026-09-12 · **Pre-open re-plan keeps the evening triggers** (`technique.arm.preopen_keep_triggers`;
  C3b). IBIT r2 +4.8R on 09-11 was discarded by the re-plan. Not sweepable; judged live at ten sessions.
- 2026-09-12 · NOT adopted after their sweeps (knobs stay off): **C4 targeted scratch** (scratch only
  when TP1 >= 3R away: -2.5R at 1.0R, -2.6R at 0.75R vs baseline), **C5 consolidation break**
  (`range_break`: 43 fires, -0.8R vs baseline). C3+C5 together +4.8R = C3 alone minus C5's drag.
- 2026-09-09 · **Critic veto -> advisory on at-level bounces and rejects**
  (`techniques.enhanced_market.critic_mode = momentum_only`; new runner knob
  `execution.critic_mode` = veto | momentum_only | advisory, default veto for every other technique;
  user decision 20:45 ET). The critic still runs on every fire, its verdict is journaled on the
  TriggerFired event and on the trade (`criticAdvisory: true` when it said no and the entry went
  ahead); it still VETOES breakouts, breakdowns and wedge breaks. Why: ten sessions, zero fills;
  25 scored kills net +0.5R in the critic's favour (16 right -24.3R, 9 wrong +23.8R), and 5 of the
  9 wrong kills were the same shape - a T4.2 reject at the level killed as "momentum through the
  level" (MUU, SOLS day 5; APLD, OKLO, SNDK day 10). A filter that is a coin flip on R and turns
  a breakeven method into no trades has no place in front of Practice money; the Practice books
  exist to accumulate fills. Review date: after 10 sessions of advisory fills, re-tally
  kills-vs-advisory-outcomes (1.4b). Evidence: 1.4b tallies days 5-10, §2 day-10 entry, tests
  `test_critic_mode_momentum_only_lets_an_at_level_bounce_proceed` / `_veto_still_kills`.
- 2026-09-04 · **Author-board auto-arm ON** (`techniques.enhanced_market.ingest.auto_arm=true`,
  user decision 10:55 ET). The morning board check now arms the "new" plans it builds for the
  author's names the moment they pass OUR gates (valid trigger, R:R >= 3, grade A/B via
  `ingest.auto_arm_min_grade`, critic at fire time, per-plan loss halt, Practice account).
  Rules/thresholds stay human; only the 09:15 click moved. Why: four mornings of a correct
  pipeline whose output needed a human at 06:15 Vancouver - today NVDA 230.4 / QCOM 170.6 sat
  unarmed. Evidence: INGESTION-PLAN status, board rows 09-01..09-04. Review after 5 mornings:
  fires/kills/R of auto-armed vs evening-batch plans (their runs carry the tag `ingest` and the board row `autoArmed`).
- 2026-09-02 · **T5.4 wide-spread gate judged on the real-time NBBO after the pick**
  (`technique/options.py::rejudge_spread`, called in `arming.py::_pick_contract` right after
  `OptionsService.reprice`). Why: until 13:42 ET every option quote was the ~15-min delayed
  CBOE chain (tips-desk audit, PLATFORM-RULES invariant 14) - the spread skip was judging a
  stale row. Threshold unchanged (10% of mid); only the price source changed. T5.3 (IV)
  Evidence: SNOW 08-25 skip (§1.6) and the 09-02 GOOGL 0.13-vs-0.60 fill; §1.6 evidence
  restarts 2026-09-03.
- 2026-09-02 (later) · **T5.3 elevated-IV gate judged on the live NBBO mid** - IV is the mid
  solved through Black-Scholes (`options.py::implied_vol`, flat 4% rate, expiry at 16:00 ET;
  `rejudge_iv` keeps the chain figure as `ivChain`). Why: the tips desk's open item - the
  chain's `mid_iv` was 15 min stale and no real-time chain provider exists. Threshold
  unchanged (0.60 absolute); the gate itself stays OFF by default
  (`technique.arm.skip_elevated_iv=false`), so this changes what the trace and the critic
  see, not what fires. Chain IV still picks the strike inside `select_contract`.
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

### 2026-09-14 evening - trading review (five completed Practice positions; +$364.49 net on the day, +$294.13 book)

Evidence and the two research comparisons: `reviews/STRATEGY-PROPOSAL-2026-09-14.md` (reviewers' packet:
`reviews/2026-09-14-trading-results-and-missed-setups.md` and companions). Findings, dated: (1) the author's MSFT
long over 498.97 -> 505 was covered by a SHORT plan - a representation mismatch, not a proven missed option trade;
with our frozen confirmation (completed 1m close) and stop (opening-range low) it is a 1.1R trade that fails the 3R
gate; a stop at the level is stopped out. (2) AAPL 336.22 and MRNA 149.73 never triggered - correct no-trades.
(3) HPQ's TP1 was touched intrabar at 09:36 and sold after the bar closed at +$0.99 on the trim: a fresh-observation
target execution (2a) is the first forward experiment. (4) HOOD Sep 10's giveback is a distant-target problem (TP1 at
6.5R, full exit at 12R) with no saved intermediate level - a structural exit policy is untestable there; proposal:
a target-distance gate at arm time, calibrated on sweeps, not on five trades. No rule changed.

### 2026-09-15 - strategy proposal revised for the reviewers' SP-01..03; order-free forward measurement started

`reviews/STRATEGY-PROPOSAL-2026-09-14.md` (revised). Corrections: (SP-01) the Sep 14 MSFT table is a RETROSPECTIVE case
study - the first-touch row has no as-of stop (the opening range is not complete until 09:35) and claims no R; the
definition `source-continuation-v1` is frozen for NEW sessions only: earliest eligible observation after the opening
range, completed-close confirmation with a next-open proxy entry, no-chase at the EXECUTABLE price (level + 0.5%, one
retest, expiry 11:30 unconfirmed / 15:55 = the baseline flatten clock, not 15:45), the opening-range-low stop, and every
existing gate (R2 3R, liquidity, budget, final dispatch) still applied - a gated candidate is recorded, never traded;
"never use the level as a stop" is withdrawn as a generalisation. (SP-02) HPQ's +$3.10 is an arithmetic illustration of
an ASSUMED resting-share fill, not the proposed mechanism; the fresh-observation result is unmeasured and HOOD/INTC
hypotheticals are unknown including their sign; the forward comparison is SHADOW ONLY (`shadow-exit-v1`, recorded as
`TechniqueExitShadow` from the quote watch: fresh observation <= 10 s by source timestamp, one record per trade per
production rung, same-contract NBBO with sizes, stop precedence on the same observation, covered vs unresolved
quantity, missing/stale quotes unscorable). (SP-03) policy P redefined as EARLIER-ONLY with one/two/three-plus
quantity rules and deferred; HOOD Sep 14's entry-minute touch is unscorable; Sep 10's missing saved level is a
limitation of the saved-level candidate, not evidence against structural exits. Target distance is recorded as a
diagnostic (`TechniqueTargetDistance` at fire and fill, `target-distance-v1`) - no gate, no N chosen.
Ledger + evaluator: `tools/em_source_candidates.py` -> `research/source-candidates.json` /
`source-candidates-<date>.result.json` (Sep 14 rows retrospective: MSFT gated 1.09R with a target path, AAPL and MRNA
never confirmed). Baseline trading and the Sep 15 review-and-arm ritual unchanged; nothing from this measurement arms.

### 2026-09-15 - measurement code corrected for the reviewers' FM-01..05 (observer stays disabled)

Reviewer cases adopted unchanged (`tests/test_codex_em_measurement_boundaries.py`, `tests/test_codex_source_evaluator_temporal_evidence.py`,
8 failed -> 8 pass; own 7 still pass). Research capture no longer awaits I/O ahead of protective exits (bounded
background recorder, visible drops); quantities and the next rung follow `plan_exit` (original filled quantity,
ladder trims, uncommitted remainder); coverage needs valid provenance/timestamp/uncrossed book/KNOWN size and
stop precedence includes the premium stop; recording is idempotent per trade instance and retryable; the
evaluator honours source availability, session identity and bar continuity and reports per-gate evaluation
(R2 only). Scope narrowed to raw observation capture - no shadow terminal tracker yet, P&L deferred to a reducer.
`techniques.enhanced_market.shadow_exit_observe` stays False pending activation; target distance remains a
diagnostic.

### 2026-09-15 - measurement follow-up MF-01..03 closed (observer still disabled)

Last-rung observation quantity now equals `plan_exit` (a 30/40/15 ladder keeps its runner at TP3; the diagnostic
labels that policy), recording distinguishes pending from acknowledged captures at the writer (no duplicate rung
records, failures retryable), and the source-candidate evaluator requires contiguous eligible minutes through the
confirmation/retest and to the 11:30 deadline (a missing interval = unknown, also for never-confirmed claims).
Sep 14 retrospective rows unchanged. No trading rule changed; `shadow_exit_observe` stays off.

### 2026-09-15 - shares fallback sized to the book's caps (defect, not a rule change)

Session evidence: WDC b1 (89 sh x 416), INTU b1 (100 x 330), AMAT b2 (97 x 420) fired, fell back to shares because
the option was untradeable, and were sized from risk % alone (2% of a $10.2k book / stop distance, capped only by
maxQty 100) - $33-41k positions on a $10k Practice book, every one REJECTED_RISK by the position caps (notional
$25k, 50% of equity, gross 100%). Fix on the EM branch (`_shares_position_cap`, `tests/test_em_shares_position_cap.py`):
a share entry is sized DOWN to the tightest of the gate's own caps (shadow research books keep only the $ cap, as the
gate does); below one share it is a journaled `size_zero` skip. The RiskGate stays the authority; no threshold moved.
Not deployed during the session - rides the next verified combined release.

### 2026-09-15 - profitability cohorts frozen (reviewers' P-01..P-03; order-free, nothing activated)

Packet `reviews/profitability-sweep-2026-09-15/`. Definitions in `research/PROFITABILITY-COHORTS-2026-09-15.md`
(`profitability-cohorts-v1`): P-01 cohort `long_bounce_next_resistance` reported beside the full baseline with
removed trades, missed-winner candidates (underlying-only proxy) and strata (confirmation, room at the actual entry,
quantity, source alignment); P-02 `small-position-exit-v1` (<= 2 contracts, first production sale >= 2R: sell one of
two / the whole single contract at the first covered executable bid at the plan TP1; forgone profit on winners
counted; unknown without an observation) with faster-execution-at-unchanged-targets kept as the separate
shadow-exit-v1 experiment; P-03 friction (concession + fees as a share of premium, 8% = ranking marker, never a
gate), affordable quantity, delta-based payoff proxy or unknown. Per-session report:
`python -m zargar.tools.em_profitability report --date <session>` -> `research/profitability/<date>.md`.
First report (Sep 15, intraday cutoff) reproduces the reviewers' trade-book friction figures exactly (CVNA 10.12%,
IREN 6.22%, NFLX 4.64%, ORCL 4.08%, CRWV 3.75%); all five fills ARE the cohort (removed = none), four cohort-eligible
fires were refused (three by the position caps, one stale quote), P-02 is unknown for all four eligible positions.
Gap-day wait unchanged; no early-profit rule; no entry broadening; `shadow_exit_observe` and the new
`shadow_p02_candidate` knob both False.

### 2026-09-15 - profitability measurement corrected (PF-01..03), P-02/P-03 provisional, both experiments off

Reducer joins the observer's actual `tp1-candidate` payload bound to the trade instance/contract/lifetime; the
candidate keeps its first COVERED opportunity (raw touch recorded once); fees are conserved in the pair (actual entry
and retained fees, modeled exit fee only on the hypothetical sale, reconciliation required); every intent stays in the
economics table with explicit unknowns, `riskBudgetQty` is a budget bound only, the payoff proxy is signed (puts count);
planned room is labelled planned and the actual-entry room is unknown. No trading rule changed.

### 2026-09-15 14:10 PT - order-free observation collection ENABLED for EM Practice only (user decision after the reviewers' close verdict)

Journaled settings PATCH: `techniques.enhanced_market.shadow_exit_observe=true` (shadow-exit-v1: first fresh observation
at the production rungs, unchanged targets) and `techniques.enhanced_market.shadow_p02_candidate=true` (frozen
small-position-exit-v1 candidate observation at the plan TP1). `execution.*` defaults stay false, so no other desk
observes; the observer is additionally gated to EM's default (Practice) book. Actual entries, exits, sizing and risk
gates are UNCHANGED - the observer places no orders and never delays a protective exit (bounded background recorder).
Purpose: obtain new-session P-02 evidence; without it the comparison stays unknown by construction. The per-session
report (`tools/em_profitability.py`) consumes the records; conclusions only where covered evidence exists.
Rollback = PATCH both keys back to false. Sep 16 baseline batch launched 14:05 PT against sheet 7da239dc (110 rows).

### 2026-09-15 - entry quote refresh (entry-quote-refresh-v1), proposed, NOT deployed

Corrected finding: the three Sep 15 refusals (RKLB 10.9 s, SMCI 12.6 s, DVN 14.5 s) failed the RiskGate's
`risk.stale_quote_seconds` freshness check inside `OrderManager.place`, BEFORE the final dispatch guard, on quotes
10.9-14.5 s old; the fire-to-intent processing took 18-23 s and nothing re-fetched the quote in between (`reprice()`
returns the cached quote for an already-served contract). Change: one bounded PROVIDER refresh (`options.refresh_now`, timeout
`entry_quote_refresh_timeout_s`: execution 0 = off, EM 2.5 s) after the analysis and immediately before final
pricing/sizing; then the existing chain runs again unchanged on the refreshed price and quantity (re-price, T5.4/T5.3
re-judgement, sizing, admission, never-chase cap, R2, final guard, RiskGate). A timed-out / failed / delayed /
still-stale / crossed refresh leaves the contract as it was and those checks refuse exactly as before. Protective
exits do not pass through it. The intent journal carries `quoteRefresh` (attempted, ok, age before/after, bid/ask
before/after, elapsed) so admissions and later outcomes can be tracked - the three refused names are NOT three
recovered winners; the profitability report will show what refreshing changed.

### 2026-09-15 - deterministic live entry is EM's main mode (user decision; `deterministic-entry-v1`)

**Policy change, disclosed:** the live EM entry decision is made by application rules at fire time; the fire-time
vision critic is removed from the entry's decision authority AND its latency path (Sep 15: 15 critic traces waited
14.1-22.0 s, mean 17.6 s, all advisory). Under the old `momentum_only` policy the critic could still veto breakouts,
breakdowns and wedge breaks - **that discretionary momentum-family veto is retired**. No claim of equivalence with the
model's qualitative judgments is made: higher-timeframe fakeouts, an emerging opposing shelf, momentum divergence and
live chop are recorded `not_evaluated` (diagnostic) and are NOT encoded; any such filter is a separate versioned rule.

Rule map v1 (`backend/zargar/technique/entry_decision.py`, pure; the tracker's ACTUAL transition is the evidence, never
the trigger's kind label): plan current + saved geometry; tracker `fired` on the completed bar; stop intact (T4.3d);
eligible window (R6 / C3 gap-day wait) and gap state (or `gap_unchecked`, kept as today); volume from the branch that
fired (floor for touches / range break / loose continuation; surge at the break candidate for the normal
follow-through path); the confirmation branch recorded honestly (`touch` with T4.2 - no reclaim candle required;
`normal_followthrough`; `range_break` and `loose_continuation` record their bypassed checks); R3.2 false-break cap.
`allow` = eligible for the UNCHANGED order chain (contract pick, bounded quote refresh, sizing, admission, never-chase,
R2, final guard, RiskGate); `refuse` / `defer` (unknown required evidence) are their own dispositions - never
`critic_killed`, never downgraded by an advisory critic setting, never a kill counter, cooldown or pause.

Settings: `techniques.enhanced_market.fire_decision_mode = deterministic` (default) | `legacy` (explicit, journaled
rollback to the awaited critic with its old veto/momentum_only/advisory semantics); `fire_evidence_mode = off` |
`after_close` (optional LATER model opinion over the frozen decision snapshot, evidence only, never trades). A stored
arm's `useCritic` is a legacy compatibility field: the mode is resolved per fire attempt, so the 41 Sep 16 arms and
every restored arm obey the authoritative setting without a rewrite (migration preview:
`python -m zargar.tools.em_fire_policy_migration preview`). No exit, sizing, risk, threshold or other-desk change.
Premarket LLM planning (sheet promotion, analyst review) is unchanged and independent of a missing key at fire time.
Records: `TechniqueEntryDecision` (every attempt, allowed or refused, with timing boundaries) and optional
`TechniqueEntryEvidence` (`authority = evidence_only`). Reports group outcomes by policy version; faster entry is a
latency fact, not a profit claim.


### 2026-09-15 22:04 PT - deterministic live entry DEPLOYED (v0.7.95 build 414a86c); CR-01/CR-02 closed

The `deterministic-entry-v1` delivery above was accepted by the review team at 8e641e9 (DE-01..05 closed; record in
`reviews/deterministic-final-review/DE-RESPONSE-2026-09-15.md`) and deployed after the close through the protocol
(readiness safe, `deploy.ps1` under the lease, `ZargarRestart` task, restoration 56/56 by id: 41 EM arms, all
effective `deterministic`, `fire_evidence_mode=off`). Two bounded follow-ups shipped in the same release, neither a
trading-policy change: CR-01 - the after-close evidence command recomputes `inputHash`, `frozenBarsHash`, the bar
count and the cutoff from the captured material before rendering or buying an opinion (a mismatch is an `invalid`
outcome with no model request) and derives facts under the FROZEN policy thresholds; CR-02 - the profitability
report builds the attempt census from every run's immutable fire events, so refused attempts without a trade row are
counted once per (run, trigger, decision) and a row is never double-counted against its attempt.

### 2026-09-16 - first deterministic session (FOMC day), interim read at 09:40 PT; unplanned restarts 10:40-10:53 ET

- 7 fires, 7 `allow` decisions (0.25-0.92 ms each, 240 frozen bars each), bar close -> received 44 ms-3.3 s, bar
  close -> order submit 1.6-2.2 s (legacy path Sep 15: 18-23 s). 3 orders: NOW b1 shares unfilled and cancelled at
  T4.1 (not chased); CRCL b1 option filled 09:32:04 and stopped by the 0.25R quote breach at 09:35:40; CVNA b1 75
  shares filled 09:34:02 and stopped by the quote breach at 09:39:12. 4 fires refused BEFORE any order by budget
  bounds: DELL r2 and BE r1 (F33 daily-loss bound: one contract risked $708 / $415 against $403 left), NBIS r2 and r3
  (FIX-03: one contract at 5.90 / 5.70 risks more than the 2% trade budget). Zero EM model calls since the open (all
  EM technique runs were pre-market plan builds 09:17-09:27 ET). Realized -$123.60 at the interim. Faster entry is a
  latency fact; the day's profitability read is the after-close report by policy version.
- Skips at the open were dominated by `gap_void` (51) and `invalidated` (28) on the gap-up FOMC morning; the 09:25
  pre-open re-plan disarmed 17 plans whose pre-market print killed every trigger and 44 stayed armed.
- **Ops, not method:** at 10:40 ET the watchdog's single 4 s health probe timed out once while the engine was logging
  normally and it killed the live v0.7.95 process; the checkout it relaunched (converged to 0.7.96 by another desk)
  had lost the health route's build helper, so health returned 500 and the watchdog looped twice more. Healthy again
  at 10:52 ET on 0.7.96 build 4c84697 with all 44 EM arms restored, no EM fire in the dark window, four SPY 1m bars
  missing 10:40-10:44. Fix on the EM branch: `/api/health` answers `build=unknown` instead of a 500 when the helper is
  absent, and PR #174 puts the EM branch (helper included) on `main`. The probe policy belongs to the start-path owner
  (PLATFORM-RULES 2026-09-16). New backlog item 10 (over-budget option, affordable shares) opened from today's refusals.

### 2026-09-16 close - first deterministic session, final read (FOMC day; report `research/profitability/2026-09-16.md`)

- **Funnel:** 11 fires, 11 `allow` decisions (median 0.4 ms, max 0.92 ms; 240 frozen bars and a snapshot on every
  record), 6 orders, 4 fills, 7 refusals (5 budget bounds before any order, 1 unfilled-and-cancelled at T4.1, 1 failed
  on a CBOE 429), 0 order errors, 0 live model calls (75 technique runs today = premarket plan builds + Cartel).
- **Timing (ms, per attempt):** bar close -> received median 221 / p90 1373 / max 3281; received -> decided median 0.4;
  decided -> quote ready median 585 (the bounded provider refresh, 2 of 2 ok); bar close -> order submit median 1598 /
  max 2242 (legacy path on Sep 15: 18-23 s). Faster entry is a latency fact, not a profit claim.
- **Fills (all `long_bounce_next_resistance`):** CRCL b1 option -$94.11 (quote-breach stop 3.5 min after fill), CVNA b1
  75 shares -$29.49 (quote-breach stop 5 min), CRWV b2 option -$51.11 (quote-breach stop 20 min), SNDK b2 3 shares
  +$27.16 (30% at TP1 15:35, flattened 15:56 before the close). **Net -$147.55, 1 winner / 3 losers, fees $4.16.**
  Three of four fills ended on the 0.25R intra-minute quote breach within minutes - the same shape as Sep 14/15; the
  exit-tempo question (§3 T-6 lineage, P-02 candidate) is where the money is, not the entry latency.
- **Refusals:** DELL r2 / BE r1 (F33 daily-loss bound), NBIS r2 / r3 / b1 (FIX-03: one contract at 5.70-5.90 risks more
  than the 2% trade budget; three attempts on the same name), NOW b1 (T4.1 not chased), BAC d1 (CBOE 429 on the option
  pick, fix on the EM branch: retry, honest alert). Backlog item 10 (over-budget option, affordable shares) stands.
- **Skips:** 114 - `gap_void` 51, `invalidated` 28 on the gap-up FOMC open; 17 plans disarmed by the 09:25 re-plan.
- **Source ledger:** AMZN long 250 -> 255 `never_confirmed` (no completed close beyond the level by 11:30 ET).
- **Ops:** three unplanned watchdog restarts 10:40-10:53 ET (see the morning entry; PLATFORM-RULES 2026-09-16); a
  network blip at 15:29:33 ET (Alpaca keepalive drop, one DB connect failure, OPRA miss) journaled 30 "stale bars"
  errors and recovered in seconds - SNDK's TP1 scale-out and flatten ran normally afterwards.
- **Release state at the close:** live 0.7.96 build 4c84697; PR #174 merged to main (build helper + tolerant health on
  main); combined candidate 0.7.99 `53721b7` (main 0.7.98 + runtime 7a008d1 + CBOE 429 retry) ready, deploy awaits
  the user's go. Sep 17: auto sheet `fc9efd65418e` (111 setups) exists; the evening batch is the user's call.

### 2026-09-16 evening - Sep 17 preparation done under a restart storm; execution follow-ups built (not deployed)

- **Sep 17 batch (sheet `fc9efd65418e`, 111 eligible rows):** reviewed 111, setup 58, no-setup 53, armed 58 into EM
  Practice (all effective `deterministic`, evidence off, auto), arming failures 0. Cost of the night: 21 paid reads
  killed by engine restarts and re-promoted (~$3-8), and four batch attempts before one could finish.
- **Six unplanned restarts today, none EM's:** 10:40-10:53 ET (helper missing, PLATFORM-RULES), 17:17 PT and 17:55 PT
  (single 4 s health-probe timeouts under load - the 17:55 one mid-batch), 18:31 (the engine's LISTENER died,
  `Accept failed on a socket`, WinError 64, while the process stayed alive), 18:34 (39 s after the previous start),
  and 18:48-18:50 the Team2 desk's own deploy of v0.7.100 (PR #190). Load facts: the Cartel research job ran 80-180
  technique runs per minute from ~17:30 to 18:40 (>1,200 runs) on the live engine, system CPU 100%, free RAM 1-3 GB of
  32 (machine-wide: a WSL VM 6.7 GB, twelve Claude sessions 3.5 GB, browsers); the harness killed three of my
  background jobs for memory. Live now: v0.7.100 build 172ce1f (not the EM candidate).
- **Morning review inputs (equity $9,926, 2% budget $198.53, premium stop 50% -> one contract affordable only up to a
  $3.97 ask; snapshot 2026-09-16):** 86 triggers on the 58 arms - 34 long (25 bounce, 9 breakout), 52 short (29
  breakdown, 23 reject). Only 6 arms are option-tradeable by the liquidity screen. Longs: 2 would take an option,
  32 fall back to shares (TP1 30% first sale). Shorts (puts only, no shares fallback): 29 have >= 1 affordable
  contract, 16 have 0 (over budget - the NBIS/DELL/BE pattern of today), 7 have no snapshot contract. 71 of the 72
  snapshot contracts expire 2026-09-18 = 1 DTE tomorrow (quarterly expiration Friday); 38 of them show a snapshot
  spread > 12%, which T5.3/T5.4 refuse at the pick. Costs: $1.04 per contract per side ($2.08 round trip per
  contract, $6.24 for 3), shares $0. First-sale rule: < 3 contracts exit in full at TP2; >= 3 contracts or shares
  scale 30% at TP1. Median planned room to TP1: 2.1R (longs) / 1.6R (shorts).
- **Event calendar (NOT from a feed - the app's macro calendar is empty; from the desk's calendar knowledge, verify
  before the open):** Thu 2026-09-17 08:30 ET weekly jobless claims + Philadelphia Fed; the day after FOMC (Powell's
  message digested overnight); Fri 2026-09-18 is the quarterly options/futures expiration - tomorrow's contracts are
  1 DTE, so premium decay and pin behaviour are unusually strong; the Friday size multiplier applies Friday, not
  tomorrow.
- **Source ledger 2026-09-16 completed:** AMZN long 250 -> 255 (conditions: "above 250 can see 255/257", intraday,
  available 09:23 ET, result `never_confirmed`); SPX 7677 -> 7750 long and 7580 -> 7500 short retained as index
  context with conditions verbatim - no tradeable vehicle in the ledger, evaluation stays UNKNOWN by design. The
  tool gained `--conditions`; missing information is stored as `null`, never invented.
- **Execution follow-ups built on the EM branch `c74df44` (evidence + tests, NOT deployed):** loop-stall watch
  (`zargar/loopwatch.py`), chart rendering off the loop (`render_chart_async`), CBOE priority + cooldown
  (`cboe_priority`), watchdog STALL-vs-DOWN classification (`scripts/watchdog.ps1`, start-path owner's call), P-04 /
  P-05 profitability cohorts (frozen addendum). Details: PLATFORM-RULES 2026-09-16 evening; README known gaps.
- **Release state:** the frozen 0.7.99 candidate `68dc42a` is superseded by Team2's 0.7.100 for every Tips PR it
  carried; what remains undeployed from EM is the CBOE 429 retry (`739e750`), the follow-ups above and the health
  tolerance (already on main via PR #174). A new combined candidate needs the runtime checkout `172ce1f` as an
  ancestor and the user's go.

### 2026-09-17 (night of 09-16) - PFU-01..04 closed on the EM branch (code `47275c3`, integrated `e048f5a` = 0.8.03 on runtime `ed88f25`), NOT deployed; runtime is 0.8.02 build ed88f254 since 19:57 PT (Team2's deploy)

- **PFU-01 watchdog:** held proposal reworked as a pure classification module with a refuse-and-escalate policy for a
  live-but-unhealthy engine (PLATFORM-RULES 2026-09-16 evening, PFU-01 paragraph). Owner coordination: the Tips desk
  agrees with the direction and puts it in the pre-open note; integration waits for the user. Evidence: seven watchdog
  kills of a live engine on 09-16 (07:40, 17:17, 17:55, 18:31, 18:34, 19:43) plus the listener death at 18:29.
- **PFU-02 P-04:** the "waiting for confirmation" claim is withdrawn from the strata (now `underlyingTp1FirstRefused`,
  descriptive); a PAIRED order-free comparison is built instead (research addendum 2026-09-17). First read, 13
  attempts over 09-15/16: 12 variants refused by the frozen R2 bar or never confirmed within 10 bars, 1 entered and
  stopped (-1R). Descriptive until >= 30 paired rows.
- **PFU-03 P-05:** labels now come from the shared session clock on tz-aware fire times (10:45 ET = midday) with
  pre/post event phase from a hand-kept, dated calendar and `unknown_calendar` for dates without an entry. 09-16 read:
  prime_open pre-FOMC 2 fills -$123.60 / 4 rejected; prime_close post-FOMC 2 fills -$23.95 / 1 rejected; midday 2
  rejected (one each side of 14:00). 09-15: unknown_calendar throughout (no entry) - by design.
- **PFU-04:** `options.cboe_cooldown_seconds` is wired (live-editable; non-default case tested); wording corrected to
  "background cooldown with bounded retry" - it reserves no provider capacity and preempts nothing; freshness / risk
  refusals decide when retries yield no usable evidence.
- **Earlier exits (the user's priority):** the frozen P-02 `small-position-exit-v1` comparison has ONE comparable row so
  far - CRWV b2 on 09-16: production -$51.11 vs alternative +$9.92 (+$61.03, forgone-on-winner $0.00); five other
  eligible fills are `unknown` because the observer had no covered executable-bid observation at the TP1 touch
  (09-15 predates the observer being ON; 09-16 CRCL b1 had none). The observation collection stays ON; the comparison
  stays provisional until the covered sample exists. No exit rule change.
- **Entry selection after costs:** P-03 friction on filled options 6.2-10.1% of premium (CVNA 09-15 10.1%, CRCL 09-16
  9.0%, CRWV 8.2%), all above the 8% marker except IREN; the marker stays a marker. The paired P-04b result above is the
  first entry-selection measurement and says "not this way" for two sessions.
- **Verification before the open (re-done against runtime 0.8.02 build ed88f254 at 20:08 PT after Team2's deploy):** 58 EM arms armed for 2026-09-17,
  book EM Practice, all `deterministic`, evidence off; `fire_decision_mode=deterministic`, `fire_evidence_mode=off`,
  `shadow_exit_observe=True`, `shadow_p02_candidate=True`, `preopen_at=09:25`, `trading.mode=practice`; one engine pair,
  Discord gateway and EM ingest worker alive, intake liveness live. The 06:20 PT attending owner is this session's
  session-local cron (job 64ad08c1); it dies with the session - the user must keep the session open or assign another.
- **DEPLOYED 20:25 PT (user: "do it all"):** v0.8.03 build d3091ae, restoration 72/72 by id (58 EM), 0 open trades, watchdog
  classification live via the checkout, stall watch reporting on health (`eventLoopLagMs` 15.4 at start). Host: `.wslconfig` written
  (12 GB cap on the WSL2 VM that hosts Docker/Postgres, 4 processors, 4 GB swap) - applies at the next WSL restart, deliberately
  NOT restarted tonight (a WSL shutdown stops Postgres under the engine). Recommend a quiet-time reboot, not a trading day.
- **Runtime note (superseded by the deploy above):** the running checkout was dirty only with EM research artifacts that are committed on the EM branch
  (they match after a fast-forward); its build string reads `-dirty` for that reason. The EM integrated candidate
  `47275c3f8ff02c857b46b431e71b3300ec0eea67` (0.8.02) contains runtime 3f5675d and origin/main as ancestors; no restart is requested for research labels.

### 2026-09-16 20:29-20:56 PT - host WSL restart, the stall watch names two causes, both fixed and DEPLOYED as v0.8.04

- **WSL / Postgres restart (user's go):** `docker compose stop` (clean Postgres shutdown) -> `wsl --shutdown` -> Docker brought the VM
  back in 8 s -> `docker compose up -d` healthy in 30 s. VM 4.5 GB -> 2.2 GB, free RAM 4 -> 6 GB, the new 12 GB cap is in force
  (`free -g` inside WSL: 11 GB total). The running engine kept its dead connection pool (DB-backed API calls hung, journal writes
  partly failed for ~60 s); it was replaced by the next deploy.
- **Stall watch, first evening on the live engine:** stalls #3 (4.0 s) and #5 (51.5 s) captured with the main thread's stack.
  #5: `logging.handlers.RotatingFileHandler.emit` called from uvicorn's response send - synchronous file logging on the loop; #3:
  `CboeClient._payload -> httpx.Response.json()` parsing a multi-megabyte chain on the loop. Fixed: root logging through a
  `QueueHandler` with the file/console handlers on a `QueueListener` thread (`main.configure_logging`), provider chain/snapshot JSON
  parsed with `asyncio.to_thread`. Tests `test_em_logging_offloop.py` + the CBOE suites.
- **DEPLOYED 20:56 PT: v0.8.04 build 66e85f6** (renumbered twice tonight: Team2 took 0.8.02 and 0.8.03 while EM blocks were open -
  re-read main AND the runtime branch right before committing a release block). Protocol: readiness safe after waiting out a
  Tips analyst run; `deploy.ps1` lease + `ZargarRestart`; receipt verified 0.8.04; restoration 72/72 by id (58 EM), resting 26 -> 26,
  open 0 -> 0; DB pool alive (portfolios 51 ms); helpers one pair each; intake live; stall watch 0 stalls after start; the CBOE
  background cooldown visibly working in the log; the watchdog classified the swap window as `absent` (processes=0) and deferred to
  the start lock - correct. Also in this build: a healthy first probe clears the stall marker.
- **Not working yet:** `ZARGAR_TELEGRAM_BOT_TOKEN` / `CHAT_ID` are EMPTY in `backend/.env`, so the watchdog's refusal escalation can
  only log (it did, at 20:25:34). The user must fill them for the Telegram path.
- **Pre-existing test flake, not from tonight's changes:** `test_technique_api.py::test_chart_png_endpoint_on_sim_symbol` fails only
  after other tests in the file (the shared Yahoo history httpx client reuses a closed loop); passes alone.

### 2026-09-16 21:04 PT - third stall cause fixed and DEPLOYED as v0.8.04 build 662a8e6

The stall watch's second catch on the 66e85f6 build (#2, 4.8 s at 20:58): `OptionsService.refresh_tracked` -> `occ.symbol`
formatting over thousands of chain rows (`CboeClient._normalize` for every option of every tracked underlying) on the loop.
Fixed: chain normalisation and the enrichment index run on a worker thread (`_normalize_all`), each tracked OCC is parsed once
per pass, and the pass yields between underlyings. Deployed 21:04 PT through the protocol (readiness safe, receipt verified,
restoration 72/72 by id, resting 26 -> 26, open 0 -> 0); loop lag 1.6 ms and 0 stalls at start. Tests
`test_em_chain_normalize_offloop.py` (6,000-row chain normalises while the loop keeps ticking). Live runtime: v0.8.04 build 662a8e6.

### 2026-09-16 21:35 PT - PFU closure RE-REVIEW answered (code `3d458d0`, 0.8.06); the confirmation claim is withdrawn

- **Watchdog (release blocker):** a live process with a quiet log was classified `absent` and `-Force` without `-Override`
  skipped classification and readiness. Corrected: live-unhealthy / uncertain / absent classes, `-Force` alone refuses,
  only `-Override` replaces a living engine, a healthy first probe clears marker + alert state, `-ProbeOnly` writes
  nothing; the caller decision is a pure function with 20 mocked cases (`scripts/tests/watchdog-classify.tests.ps1`).
  Deployment of this correction is recorded in `reviews/2026-09-17-PFU-CLOSURE.md`.
- **Paired confirmation (research):** the entry minute was skipped (a TP1 reached in the fill minute read as a later stop);
  fixed - the scan starts at the entry bar. Incomplete horizons are `pending`. The proxy is labelled geometry-only with
  the gates it does not evaluate. Reports regenerated 21:15 PT: 14 attempts over 09-15/16 -> `refused_r2` 11,
  `no_confirmation` 1, `stop_first` 2. **Withdrawn:** "waiting for the close costs room faster than it saves stops" - two
  retrospective sessions of a geometry-only proxy support no statement about the policy. Descriptive until >= 30 rows.
- **Record consistency:** the closure document was rewritten around one tested candidate with runtime collection and
  offline report generation stated separately (command, owner, location, tool version, output timestamps).
- Scope kept: no repeat batch, no activation, deterministic Practice trading and observation collection unchanged.

### 2026-09-16 22:05 PT - re-review follow-up: the report cutoff is not the session close (research tool only)

- `em_profitability.confirmation_pair` closed an incomplete horizon whenever the last observed bar sat right before the
  REPORT cutoff - so an intraday 10:02 ET report with one observed bar read `no_confirmation`. Fixed: only the session's
  actual last bar (16:00 ET on the firing day, `session_close_of`, or an explicit `session_close_ms`) closes a horizon;
  an early report leaves it `pending`. Focused case `test_intraday_report_cutoff_is_not_the_session_close` (own test
  file; reviewer files untouched). The 09-15/09-16 reports were generated after the close and do not change. Ships in
  the next normal release (0.8.09 block); nothing about preparation or trading moved.
- Watchdog refusals while Telegram is unconfigured: the EM desk session monitors them on every review tick (refusal lines
  and the stall marker are printed with an ATTENTION line); one refusal was recorded at 21:43:34 PT tonight - the engine
  was mid-restart under the 0.8.08 deploy and cleared at 21:46 (correct behaviour, no action).
- Research load: 379 `options_cartel` manual runs hit the live engine between 18:40 and 21:40 PT (after hours). The
  review tick now reports run volume by technique for the last 30 minutes and flags research-scale volume during RTH.

### 2026-09-17 evening - EOD profitability / LLM review answered (packages A-D; `reviews/2026-09-17-EOD-RESPONSE.md`)

- **The day's largest winner rests on a doubtful simulated fill.** ORCL 148C: limit 2.29 accepted against 2.10/2.29, filled
  7 s later at 1.12 on an OPRA snapshot 0.76/1.12 (38% of mid) that no print supports (the contract's own 09:32 bar traded
  2.48-2.88). Sensitivity: about +$134 instead of +$250.92; the day about +$106 instead of +$222.65. The ledger is unchanged
  and flagged; the likely mechanism is the quote-cache overlay recentring a fresh OPRA band on a stale chart `last` (E17-01, fixed in
  main 0.8.11 - such quotes are now `derived:` and refused by the simulator). Proposal built OFF as a second, independent evidence guard: `sim_max_option_spread_pct` (simulator evidence guard; activation = user decision).
- **What the setup model buys (one session, order-free ablation, `research/prep-ablation/2026-09-17.md`):** its 53 vetoes
  removed 5 replay fills worth -0.77 R in total (A 11 fills +2.87 R vs B 16 fills +2.10 R) for 4.25 M input tokens. 43 of 53
  vetoes are reproduced by a deterministic feature of the trigger the model named; 36 of 50 named vetoes argue about a
  trigger the builder had already marked INVALID. A guessed exception set (cohort C) excluded the winners (-4.76 R): the
  exception features must be learned across sessions, not declared from one. Direction supported, activation not proposed yet.
- **P-06 runner protection frozen** (`tp1-reclaim-runner-exit-v1`): exit the runner only if a completed 1m bar closes back
  through the saved TP1, at the next open. First two rows (SCHW -$1.17 on shares, BMNR +2.01 R underlying-proxy) say nothing.
- **BMNR:** a TP1 trim that lost $8.08 against an $11.82 first-order payoff - `edgeAtTp1` marker added (never a gate).
- **Sources:** the 09:21 watchlist was EvaPanda's; rows re-attributed, five branches added and evaluated (AMZN/GOOGL never
  confirmed, MRNA/MU no target, TSLA gated, SPX unknown). The author's livestream content is unavailable.
- **Runtime:** pre-open re-plan runs render no charts (45 x 4 charts on the render thread at 09:25 ET on 09-17).
- Kept: rules, thresholds, observation knobs, the preparation flow; no batch rerun; no trading-hours deploy.

### 2026-09-17 late - delivery review ED-01..04 answered (`reviews/2026-09-17-EOD-DELIVERY-CLOSURE.md`)

- ED-01: the OFF option spread cap applied to every option order, protective exits included - corrected to OPENING orders
  only (position-derived `option_action`); stops / flattens / reducing exits / unknown intent never capped. Still OFF.
- ED-02: P-06 bound to confirmed executions of the trade instance; shares and options are underlying proxies without a
  covered `tp1-reclaim` observation (runtime observer added, research only); the SCHW dollar comparison is withdrawn.
- ED-03: the ablation is a descriptive underlying replay; "+0.77 R" is a cohort difference under its assumptions, never
  measured model value or a token-dollar return; the live funnel (12 fired / 5 refused / 6 opened) vs the replay (11 fired
  / 11 filled) is reconciled per symbol; 36 of 50 (72%) named vetoes concern already-invalid triggers.
- ED-04: the executable-profit basket has an owner (EM desk; Tips desk for the shared quote/mark layer), the acceptance
  contract retained, delivery scheduled ahead of any further giveback policy.
- Reporting: $222.65 net after $16.64 commissions ($239.29 gross); the ORCL 2.29 sensitivity is arithmetic ($133.92 trade,
  $105.65 day), not a corrected fill.

### 2026-09-17 17:10 PT - v0.8.12 build `e6cb4b7` live; 39 arms for 2026-09-18

Preparation: 102 setup rows reviewed (setup 39 / no_setup 62 / 1 provider failure retried -> no_setup), 39 armed, 0 failed.
Deployment through the protocol after the batch, restoration 54/54 by id. Defaults unchanged (option spread cap OFF).

### 2026-09-17 late - P-06 re-review corrections (three bounded, `reviews/2026-09-17-EOD-DELIVERY-CLOSURE.md` addendum)

- Observer seeks the first covered quote after a persisted signal (raw samples never consume eligibility); reducer walks
  fills and bars chronologically (first TP1 fill = eligibility; intermediate trims reduce, not end; stop-first wins;
  pending exits explicit; cutoff-filtered executions); strict observation validator with identity, contract, signal,
  chronology, coverage, lifetime and cutoff - the reviewer's reproduction (foreign identity, wrong contract, after-cutoff)
  is rejected with reasons. Dollars option-only; both 09-17 rows stay `underlying_proxy_only`.
- Disclosure: once deployed, the observer is a NEW code path active under the already-on `shadow_exit_observe` knob -
  observation-only (journal rows), no order, no exit, no setting change. P-02 collection untouched.
- The executable-profit measurement (ED-04) remains the next priority; nothing here substitutes for it.

### 2026-09-17 18:51 PT - v0.8.13 build `46c50eb` live (P-06 corrections); 39 arms for 2026-09-18 unchanged

Tested code 330328c; deployed 46c50eb (adds the pyproject version line the first attempt lacked - the runtime's check-release
refused that attempt at the build step, no restart happened). Restoration 54/54 by id. From this restart the P-06 reclaim
observer runs as an observation-only path under the on `shadow_exit_observe` knob. Next priority: the executable-profit
measurement (ED-04, EM desk owner; Tips desk for the shared quote/mark layer).

### 2026-09-17 late - P-06 partial-depth rule (0.8.14 block, next coordinated release)

A first contract quote with some depth but less than the remainder is raw evidence for the reclaim observation; the covered
key stays open (verified while the raw write is queued and after it is acknowledged). P-02 semantics untouched. Research only.

### 2026-09-17 late - 0.8.14 candidate consolidated (`586ed13`), not deployed

Partial-depth rule accepted; main `edc5dd0` (Tips #206-#208) merged cleanly; 70 focused + shared-change tests, build and
release check green on the merged SHA; arming solo on the pre-merge tree 30 passed + the known baseline failure. Live stays
v0.8.13 build `46c50eb`. Strategy changes deferred; the executable-profit measurement (ED-04) is the next work item.

### 2026-09-18 evening - integrated delivery (A-E) built on one candidate; SBUX: R2 was never re-measured at the final quantity

Closure: `reviews/INTEGRATED-DELIVERY-RESPONSE-2026-09-18.md`. Nothing below changes baseline Practice preparation or trading;
every new policy / capture switch is OFF, and the one observation default is named.

**Finding (SBUX 2026-09-18, event 165135; run `8a79a643`, trigger d1 breakdown).** Saved plan: entry 96.0907, stop 97.681,
targets 94.1689 / 92.2471 / 90.3253, R:R 3.63 - measured to TP3, because `technique.rr_gate_target=auto` resolves to TP3
whenever `technique.arm.contracts=0` (risk-based sizing leaves the quantity unknown at plan time). At the fire the runner's entry
was the confirming close 95.335, the sizer bought ONE put, and a position of fewer than three contracts leaves whole at TP2:
(95.335 - 92.2471) / (97.681 - 95.335) = **1.316R** against `min_risk_reward` 3.0. The documented rule ("R2 is measured where the
position exits") was applied at plan time with the wrong quantity assumption and never re-applied after sizing. It is an
UNDERLYING rule and stays one: no premium metric was substituted, 3R was not weakened, and the underlying's live price at
admission - which the runner never captured - stays unknown in the record.

**Change (`first-sale-v1`).** One versioned record at the final quantity and price (`TechniqueFirstSale`), journaled on the entry
path after sizing and before the intent: the exit rung for that quantity (1-2 contracts -> `single_contract_exit`; 3+ contracts
and shares -> the book's TP3; a pinned `rr_gate_target` is honoured), R on the saved entry / the runner's entry / the observed
underlier (unknown when not observed), fees, spread cost, a labelled delta payoff proxy, the plan-time measurement beside it, and an
order-free vehicle comparison on the chain rows already in hand. Setting `techniques.enhanced_market.first_sale_rr_gate` =
`observe` (DEFAULT: records, never refuses) | `enforce` (refuses the ENTRY when R at the real exit rung is below the minimum;
unknown never refuses; exits never pass through it) | `off`. Retrospective on the order-intent journal
(`research/first-sale/2026-09-15_2026-09-18.md`): of 28 EM entries in four sessions, `enforce` would have refused exactly ONE -
SBUX (-84.10). Break families are the exposed case: their entry is the confirming close, which eats reward the plan-time number
assumed. `enforce` is a separate activation decision.

**Other verdicts recorded tonight (all order-free).**
- Conditional-plan review (`conditional-review-v1`): "the breakout has not happened yet" is classified and discarded clause by
  clause; every other objection is kept; a reason that opens with a trigger id reaches that trigger only. On the REAL 09-18
  overnight reviews (NVDA, META, MRNA, MU) the invalid clause was never the only objection - nothing is rescued. The mismatch was
  real but was not why those plans were vetoed. Report-only under baseline (`conditional_review_fix=report`).
- Preparation comparison (`research/prep-compare/2026-09-15_2026-09-18.md`, zero model calls, shared book `capacity-v1`):
  proxy R, four sessions - model-selected +7.68 / -0.93 / +0.85 / -3.52; deterministic +7.90 / -1.76 / -0.40 / -2.78. The
  deterministic selection roughly doubles the candidate count and meets the daily-loss halt more often. PROXY ONLY (underlying
  replay; no option evidence exists for unselected plans). Actual baseline dollars: -220.30 / -147.55 / +222.65 / -299.33 =
  -444.52. Neither selection is shown to be better; the model reads cost about 4.2M input + 1.6M output tokens per evening at
  an UNKNOWN price (no dated price row is configured - never invented).
- Source fidelity (`research/source-scenarios/2026-09-18.md`): MU was spoken, TSLA was extracted -> `conflict`, held; MBGO
  unresolved (AVGO is a hypothesis); the 700C in the EvaPanda note is an option mention, not a target; 1155 beside 160C/165C is a
  flagged conflict, never 155. The AMD 2.97R breakout and the SPCX long (k2, 2.56R) stay NAMED refusals; the armed SPCX trigger
  was the opposite short reject. The author gave NVDA no numeric level: no app geometry, held - never "aligned".
- Requalification (`requalification-v1`) on 09-18 bars: fresh NVDA structure after the 09:31 invalidation gave entry 219.76 /
  stop 218.27 with the author target 222 = 1.51R -> refused by R2, threshold untouched. MRNA / TSLA / META (EvaPanda): no
  author target beyond the fresh entry -> held. ARM: stop 3.04% > the 3% cap -> refused.
- DRAM stop (19:45:24 -> 19:45:59 UTC): the MKT exit was accepted in 0.4 s; the sim waited because the thin contract's NBBO
  source time was older than its freshness limit (`SimFillWaiting` 19:45:47) and filled at 0.24 when a fresh OPRA quote arrived -
  the same bid that triggered the stop. No EM-side defect and no demonstrated price loss; an on-demand refresh would return the
  same unchanged venue timestamp. Left as it is; how the shared simulator treats an unchanged standing quote is for its owners.
- SKHY (19:22:05 UTC): the provider 429 outlasted the client's ~1.8 s back-off; a fired put entry sent nothing. Built, OFF:
  ONE re-pick after `pick_retry_after_429_s` (cap 8 s) only if the underlying has not run 0.25R past the entry; never stale chain
  data, never a loop. The missed trade belongs in the counterfactual ledger after the fix is live (rollout checklist).
- ORCL 09-17: both fills carry `source: opra` raw evidence with no transform (buy 1.12 at the ask of 0.76/1.12, sell 3.65 at the
  bid of 3.65/3.90). The 0.36-wide entry book (38% of mid) is the questionable part, not a derived quote. Cash is not rewritten.

### 2026-09-19 - candidate review IR-01..IR-05 answered on one corrected candidate (`reviews/INTEGRATED-DELIVERY-RESPONSE-2026-09-18.md`, revision 2)

The reviewers reproduced real defects in the first candidate; all five are corrected, none was deployed, nothing was activated.
- **First sale (IR-01/IR-04).** v1 judged the SAVED entry and only reported the live underlier; it rounded before comparing; under
  `enforce` an unknown or an exception passed; it ran once, before the order waits; and it shipped `observe` by default with an awaited
  journal write on the entry path. `first-sale-v2`: the validated executable underlying bound owns admission (long ask / short bid),
  the comparison is unrounded, `enforce` fails closed and is re-decided inside the final entry guard after every wait and retry, an
  invalid setting refuses, the record goes to a bounded non-blocking recorder, and the default is **OFF**. Historical admission is
  UNKNOWN for all 28 entries of 09-15..09-18 (the executable underlier was never captured) - the earlier "enforce would have refused
  one of 28" read the saved geometry only and is withdrawn as a back-test.
- **Executable profit (IR-02/IR-03).** v1 scored a quote with no source, spent the same displayed depth once per trade, and took
  realized totals from in-memory trades. v2: unknown provenance is unknown; depth is spent once per contract/side across the book;
  realized totals and per-trade attribution come from the session's executions (restart / disarm / late start / prior session safe);
  capture ids are idempotent; the reducer reconciles net, fees, the sum of closed trades and cash against the ledger.
- **Candidates (IR-05).** The pricing stage is real (`candidate-pricing-v1`): with contemporaneous evidence it evaluates contract,
  quote, spread, sizing, budget and executable-price no-chase; without it every gate is unknown. Decided once at the trigger.
- **Dispatch tests.** The reviewers' EM dispatch cases failed because `size_multiplier` read the WALL clock: on a Friday the x0.5
  multiplier sized a $150-risk contract to zero against a $100 budget and the entry never reached the RiskGate. The weekday now comes
  from the test-pinnable `zargar.clock` (production = real time) and those modules run on a controlled Wednesday clock. Verified by
  running the unchanged cases under a pinned clock before and after the fix; not an after-hours effect.
- **Activation order changes:** measurement first (ED-04 recorder, then first-sale OBSERVE). Enforcement is not recommended on the
  strength of one avoided loser.

### 2026-09-19 (later) - revision-2 review R2-01 / R2-02 and the final-completion goal answered (`reviews/INTEGRATED-DELIVERY-RESPONSE-2026-09-18.md`, revision 3)

The reviewers reproduced two more real defects and listed integration boundaries to prove through the actual callers. Nothing was deployed or activated.
- **Two entries in one contract were one trade (R2-01).** The ledger grouped fills by symbol until flat and named the result after the first entry.
  Now the trade instance is the ENTRY ORDER, bound by the runner's journaled order results (exits carry `entryOrderId`; older events are bound by
  the run + trigger journal sequence). Unknown linkage is an error, never a guess. Aggregate cash can reconcile while attribution is wrong, so both
  are tested with different prices and fees.
- **Late fills.** The execution-time cursor could skip a fill that arrives late with an older time. Each capture now re-reads its bounded session;
  the capture keeps what was known then, and the reducer marks it REVISED when the final executions disagree.
- **"Feasible" was not feasible (R2-02).** A wrong-underlying, expired contract passed because only the quote symbol matched; the gate named
  no-chase was the R calculation. `candidate-pricing-v2` binds the contract by OCC identity, judges a chase bound apart from R, and takes the
  production RiskGate verdict, halt state, position slot and entry reservations as evidence. Anything missing = partial, never feasible.
- **Causality.** Only the source revision current AS OF the evaluation is actionable; an idea is judged with the plan that existed at its birth; a
  pivot is knowable at the close of its confirming bar (the old code used the bar's START time as the availability time - one minute early in the
  record, although the same bars were fed); the first persisted geometry of a candidate or child is immutable.
- **Method lesson:** "reconciles in aggregate" and "matches the quote symbol" are not proofs of identity. Identity has to be carried, not inferred.

### 2026-09-19 - EM Experimental launched as a second Practice book (`research/EXPERIMENT-DEFINITIONS-2026-09-19.md`)

On the user's direction the integrated bundle runs ACTIVELY in its own sim book while EM Practice stays the unchanged baseline: deterministic preparation
(conditional-review fix applied, grade floor B), first-sale enforcement, executable-profit capture, promotion of live source-continuation and requalified
candidates into real simulated plans, and P-06 runner protection as an executed exit. Same sizing and risk limits in both books. It is ONE bundle: the
difference between the books will not say which component caused it, and four sessions of history predict nothing about it. Questions it can answer after
the declared horizon: after-cost dollars and drawdown of the bundle against the baseline; how often enforcement defers for missing evidence and what those
entries did in the baseline; how much displayed profit was executable; whether source-conditioned plans add trades the preparation did not already arm.


### 2026-09-21 - the first active experimental session traded nothing, and the reason was the clock

The experimental book fired 13 times, deferred 9 at the first-sale gate on `venue_time_in_future` and submitted no
order; the baseline traded normally and finished +$201.70. **The method was not tested that day.** The host clock ran
10.5 s behind true time, so correct venue timestamps looked future-dated and a gate built to refuse them did. The
session is retained in every chronological report and marked **operationally impaired**: it measures the environment,
not the bundle, and must not be averaged into any judgement about selection or profit management.

What the session did teach, none of it about the rules:

- **A refusal row is not an opportunity.** One AVGO trigger produced 48 `max_open_trades` rows across 51 minutes
  while the plan's own long was open. Count attempts (`TechniquePlanTriggerFired`), not rows.
- **Sizing feasibility is a property of the book.** With a ~$9.85k book, a 2% per-trade budget and a 50% premium
  stop, no contract priced above **$3.94** can be bought at all. NBIS at $8.00 and AVGO at $4.80 were both refused
  correctly, and the refusal is arithmetic, not a defect.
- **The author's ideas mostly died for want of a chart, not for want of a rule.** Six of eighteen source rows were
  him pointing at a line on a screen the app never received. Of those that did have numbers, META and TSLA failed on
  a stop wider than the 3% cap, and AMZN, NVDA and MU on the 3R floor. META then ran to 753 - and TSLA, MU and SNDK
  did not reach their first stated targets, which is the half of the evidence a tuning exercise would forget.
- **`deferred` meant terminal.** Every deferred trigger fired once and never again. A bounded one-shot retry now
  exists as `deferral-retry-v1`, DEFAULT OFF, and is a proposal to be judged on a forward sample, not a change to
  the frozen bundle.


### 2026-09-22 - the midday experiment is ended; R6 stands (`technique.arm.midday_trading` true -> false)

Decided on the preregistered rule in the midday section above: at least 30 scored midday fires, then compare midday R
against the prime windows. There were 62 midday fires. The filled midday trades lost **−0.30R per trade** (total −2.40R,
22% winners) against −0.09R per trade in the prime windows, de-duplicated across the two books.

Recorded honestly: the prime windows are negative too, and midday is **not** statistically distinguishable from them
(one-sided permutation p = 0.36, eight midday trades against twenty-eight prime). So this does not show midday is the
cause of EM's losses. What it shows is that allowing midday adds nothing, which was the experiment's question, and the
null answer returns the method to its own documented rule: midday is chop, watch-only. The toggle's default was always
off. It applies to both books equally, so the A/B comparison stays fair. Rollback is the same key back to true.

Context for anyone revisiting it: across all 38 EM trades to date the method has not made money (−$219.40 net, profit
factor 0.84), and 18 of its 27 stop-outs kept moving against the position afterwards, so the losses are mostly entry
selection rather than stop placement. Full analysis in `reviews/2026-09-22-PROFITABILITY-PLAN.md`.

### 2026-09-22 (late) - the EM stop rule is adopted and the open questions are preregistered (`em-scorecard-v1`)

User decision 2026-09-22, on `reviews/2026-09-22-PROFITABILITY-PLAN.md`. Nothing here changes a trade; it fixes, BEFORE
the data exists, what will decide EM's future and each open method question.

**The stop rule (`em-stop-rule-v1`).** Counted forward from 2026-09-22 in the BASELINE book (the sessions that suggested
the rule do not get to decide it). After **20 evaluable sessions**: if cumulative R is **at or below zero** AND the
upper end of a 95% session-resampled bootstrap of the mean trade R is **below +0.1R**, stop the paid model review
(`techniques.enhanced_market.paid_review` → false) and keep the baseline watch-only: plans still built and scored, no
money spent. A losing but noisy record (upper bound ≥ +0.1R) does not trip it - the rule stops a method shown to have
no edge, not one that is merely unlucky. R = the method's own planned risk: shares |entry − stop| × qty; options the
premium stop (premium × 100 × qty × `premium_stop_pct`). Impaired book-sessions (the 2026-09-21 experimental clock
fault) are excluded from evaluation and kept in every report; the disputed ORCL fill is reported as booked and at the
ask, never silently replaced. The close check writes `research/experiment/<date>-scorecard.md` daily and raises a keyed
`stoprule` notice when it trips; setting the switch is a human step.

**Preregistered tests** (thresholds fixed now; `technique/em_scorecard.py::TESTS`; a reading before the sample is
complete is printed for transparency and is never a verdict; the copy of a baseline trade in the experimental book
counts once):

| Test | Question | Counted from | Sample | Metric |
|---|---|---|---:|---|
| `shares_fallback` | does the shares fallback do as well as the option leg? | 2026-09-12 | 20 trades | mean R, long shares vs long options |
| `short_puts_prime` | do short puts pay in the prime windows, now midday is off? | 2026-09-23 | 20 trades | mean R |
| `stop_vs_volatility` | are stops small against the stock's own range stopped by noise? | 2026-09-23 | 40 stops | share later reaching TP1, stop < 2 vs ≥ 2 average 1m ranges |
| `one_touch_levels` | do entries off a once-touched level lose disproportionately? | 2026-09-23 | 15 trades | mean R vs the rest |
| `rules_vs_model` | does free rules-only preparation do no worse than the paid review? | 2026-09-22 | 20 sessions | cumulative and per-session R, experimental vs baseline |

Readings at adoption (NOT verdicts): stop rule collecting 1/20; shares fallback n = 14, shares −0.54R vs options +0.52R
per trade. Until a test is ready, `stop_buffer`, the shares fallback, the put side and the level-touch floor stay as
they are.

**Measurement added the same evening:** `TechniqueExitQuote` (`exit-quote-v1`, `techniques.enhanced_market.exit_quote_capture`
on) - the exit side of the spread becomes measured instead of estimated from 2026-09-23. **Operational fix:** BRK.B now
streams from Alpaca (PLATFORM-RULES 2026-09-22); before it, BRK.B plans saw one bar every 3-5 minutes and could miss
their trigger bar, so BRK.B trades before 2026-09-23 are a feed artefact as much as a method result.

### 2026-09-23 - EM becomes fully deterministic (user decision); the paid nightly review is retired

User decision 2026-09-23, after the model-cost analysis: EM's model spend over 2026-08-21..09-23 was **$1,109 at list
price, of which $1,104 was the nightly paid review** of the next session's sheet (the rest: manual Analyse runs, scans,
chat). The pre-open re-plan, the experimental book's preparation, the author-source plan runs and the live entry decision
(`deterministic-entry-v1`, since 2026-09-15) already made zero model calls. EM had shown no edge (38 trades, −$219.40, PF
0.84), and the review's value was the open question of the `rules_vs_model` test.

**Change (`em-deterministic-prep-v1`):** the baseline book is prepared inside the engine from the graded sheet by the same
eligibility owner the experimental book uses (`preparation_policy.decide`, grade floor, no analysis), minting one
`trigger=prepare` plan run per eligible row with no model pass, armed through `prep_arm` (one arm per candidate, RiskGate on
every order). Switch: `techniques.enhanced_market.preparation_policy=deterministic` (technique-wide) with
`techniques.enhanced_market.paid_review=false`; the evening batch stands down on either. Rollback = both keys back
(`baseline`, `true`) - the batch then prepares the baseline as before.

**What it does to the tests.** `rules_vs_model` is **superseded by decision**, not answered: both books now prepare by
rules, so it can no longer compare them. The two books still differ by the experiment bundle (first-sale enforcement,
P-06 runner protection, promoted source candidates, conditional-review fix, grade floor); the comparison continues as a
bundle comparison. The stop rule (`em-stop-rule-v1`) keeps counting in the baseline book, but its action - stop the paid
review - has already been taken; if it trips, the remaining decision is whether EM keeps trading in Practice at all.
Author-note ingestion (`technique/ingest.py::_llm_extract`, ~2 notes a day at low effort, cents) still reads the author's
free text with a model; it is the only automatic EM model call left and can be stopped with the ingestion switch if wanted.

### 2026-09-23 (close) - day 2 of both books; the model veto measured; break triggers registered as a test

Full record: `reviews/2026-09-23-DAY-REVIEW-AND-PLAN.md`. Baseline -120.18, experiment -105.75. On matched trades the
experiment did better (+45.53 vs +7.96), P-06 turning LITE from -10.09 to +15.58.

**The 7-trade streak.** On 09-22 and 09-23 all 7 rules-only-only admissions lost (-276, about -0.98R each, against -0.17R
for model-approved trades the same days). Checked on 18 scored sessions (`research/2026-09-23-MODEL-VETO-STUDY.md`):
approved +0.26R [-0.15, +0.81] (44 fills) vs vetoed +0.12R [-0.24, +0.44] (37 fills). There is no measurable value in the
veto, and no reason family held out of sample. The deterministic decision stands; the streak is recorded as most likely
chance.

**Registered:** `break_vs_level` (em_scorecard): break triggers (ladder targets) against level-anchored bounce/reject,
30 break fills from 2026-09-24. In-sample -0.27R (22) vs +0.40R (54); the test split was neutral, so it is NOT a rule.
`rules_vs_model` is closed as superseded by the 2026-09-23 decision.

**Defect (0.8.40):** outcome scoring had stopped after 2026-09-18 (future-session plans starved the queue). Studies that
need outcomes for 09-21 onward waited for the backlog to drain.

### 2026-09-24 - the shares fallback is switched OFF (preregistered test `shares_fallback` decided)

The test registered 2026-09-12 (C2) reached its sample: 22 long-shares trades at **-0.52R** per trade against 15 long-option
trades at **+0.05R** (de-duplicated, method-own R). The decision written in advance (`reviews/2026-09-23-DAY-REVIEW-AND-PLAN.md`)
was applied through the journaled settings API: `techniques.enhanced_market.entry_fallback` shares -> **off**. When the option
is untradeable the trigger is now skipped instead of buying shares. `entry_fallback` is frozen on each arm, so the plans
armed for 2026-09-25 keep `shares`; the change applies from the 2026-09-25 evening arming (session 2026-09-28) onward.
Rollback = the same key back to `shares`.

Context the same day: 2026-09-24 was the worst EM session so far (baseline -439.42, experiment -660.92, 9 of 9 trades
stopped). Record to date 61 trades, -1,545.67, profit factor 0.50; the stop rule is at 3 of 20 sessions.
