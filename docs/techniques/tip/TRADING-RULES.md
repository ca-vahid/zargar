# Tip technique — judgement log

*The METHOD's findings, open questions and rule changes — not the code's.
Date every claim; cite the signal/replay/scorecard it came from. Sibling of
`docs/techniques/enhanced-market/TRADING-RULES.md`; engine-level invariants
live in `docs/PLATFORM-RULES.md`.*

## Rules under observation

- **Source-exit disarms on WAITING plans may be premature** (2026-09-04, n=3):
  MRVL ×2 (disarmed 11:17/11:19 on eva's/MuggZone's own exits) and CRWV
  (disarmed 12:34 on ab's "small trim") — all three names closed **+6%** the
  same day, and the shadow books show the mirrored contracts at 3–4× (MuggZone
  MRVL 230C 1.19→4.35, eva 240C 1.41→4.60). The disarm logic ("a source exit
  kills the thesis") is designed behavior — but a waiting plan has a defined
  stop; letting it live costs bounded risk. Candidate: on a source exit,
  distinguish *thesis-dead* ("not going to swing this") from *profit-taking*
  ("take a small trim" while still holding 60%) — disarm the first, keep the
  second armed with a tightened horizon. Decision threshold: ~10 disarm
  counterfactuals from the nightly lane grading.
- **Ratchet floors vs opening volatility** (2026-09-04, n=1): MU's monetize
  ratchet banked +16% (peak +56%) into the 09:30 dip, and MU then rallied
  +5.8% all day. Candidate: floors judged on 15m closes, or a 09:30–09:35
  grace. Wait for more occurrences before touching.
- **Earned-auto on the immediate lane** (2026-09-04, user decision): trust now
  grades the immediate shadow book's aged marks alongside closed practice
  positions (see change log). Watch: marked hits are softer evidence than
  realized ones — if a source graduates on marks and its first auto trades
  disappoint, add a realized-only floor (e.g. ≥2 closed winners).

- **Ladder vs trail on catalyst-backed tips** (2026-08-28, PeloSwing CRM
  replay): the armed-book replay filled at $149.80 and laddered out at TP2 for
  **+3.6R**, but the move's MFE was **10.7R** (CRM 153→252 into earnings). One
  data point, but the shape is typical of buyback/earnings theses: the ladder
  banks a third of a monster. Candidate rule: when the tip names a catalyst,
  trail after TP1 instead of exiting at TP2. Decision threshold: revisit once
  ~10 armed-book outcomes with catalysts exist; compare ladder P&L vs a
  trail-after-TP1 re-sim.
- **Default horizon 15 sessions** (raised from 10, 2026-08-28, user: "be
  generous"): the CRM tip needed ~13 sessions to clear TP2 on 1h bars. Watch
  the expired-unfilled rate; if it stays near zero the horizon can stretch
  further for share tips (options stay expiry-bounded).
- **Flag-day thresholds untouched**: verification price gates (deviation 3%,
  spread 1.5%) have not yet been tested against a real tip flow.

- **Breakout stops are built from the trigger-tf ATR** (2026-08-28, PeloSwing
  BOIL replay): a daily-chart wedge tip got a 1h-ATR stop 1.4% under the $22
  level (2x leveraged ETF!) with matching tight R targets. Candidate rule:
  scale the ATR (or the stop reference) to the tip's own timeframe — a
  "daily chart" thesis wants a daily-ATR stop. Decision threshold: first few
  filled breakout tips; check whether the tight stop gets wicked out.
- **Leveraged ETFs carry decay** (2026-08-28, BOIL = 2x natgas): a 15-session
  hold in a 2x commodity ETF pays decay the tip never mentions. Candidate:
  advisory context line ("2x leveraged — decay over weeks") the way
  `calendarContext` works. No gate — information only.

## Change log

- 2026-09-09 (pre-dawn) — **Audit finding 4 shipped: the analyst's failures are
  honest now.** Same-transcript JSON repair (tool evidence retained — the ORCL/
  CRWV/APLD no-verdict class), over-budget tool requests get a forced final
  answer, stop reasons + token usage ride every run, CancelledError and boot
  reconciliation kill zombie "running" runs, and mutating tools leave RECEIPTS
  (a failed run that acted says so in the UI instead of "nothing was asked or
  ordered"). Next in the audit order: the gateway envelope (Codex reviews).

- 2026-09-08 (night) — **Codex audit fixes 1/3/5 shipped** (v0.7.17; full
  triage + verification in `reviews/2026-09-08-system-audit-response.md`).
  Units: `price_domain` on option tips + `underlying_price_checks_ok` gate —
  premium targets are never judged against (or planned as) underlying prices;
  ambiguous units skip on the record. Extraction: typed outcomes — a garbled
  reply is status=error (sweep retries once), a refusal is status=refused;
  neither masquerades as commentary. Retros: keyset cursor + true backlog +
  oldest-unreviewed age (the oldest-50 window starved at ~50 lifetime retros).
  Open, in order: repair/reconciliation, gateway envelope, analyst evidence
  tools, knowledge governance + as-of experiments, measurement split.

- 2026-09-08 (evening) — **"Skip must never sit armed" is CODE** (v0.7.15, user
  yes after 8 manual analyst disarms in one day, one near-fire: eva's skipped
  MU 850P waiting AT live spot). `arm_shadow` refuses skip/watch verdicts, the
  morning sweep skips them silently, and `analyze_fire` re-reads the CURRENT
  verdict at fire time — a late verdict vetoes the fire and disarms the plan.
  Unappraised tips (verdict None) still arm: the armed book keeps measuring
  the source raw; what it stops measuring is ideas the desk already declined.
  RESEARCH NOTE: armed-lane counterfactuals are takes + unappraised from today
  — the scorecard comparison window resets accordingly.

- 2026-09-08 — **Promoted cards decide themselves; the session brake actually works**
  (v0.7.11). FRVO: an analyst TAKE promoted off a prevClose-artifact park sat
  pending under the old "promotions never self-approve" invariant — under
  unattended practice a promoted take now self-approves (skip/watch declines,
  NO verdict stays pending fail-closed per the TSLA lesson, live always human).
  APLD the same hour showed the fail-closed gate correctly holding a card the
  analyst never appraised. Also: the <5-min-stop-out session brake read
  `state.closeReason`, which was NEVER persisted (dormant since 09-04) — now
  written by `_mark_closed`; and shadow-book deaths no longer count against
  the real book (GME research noise would have paused autos all day).

- 2026-09-08 — **The geometry gate covers the ARMED lane** (v0.7.10). The
  nine-strike failures were armed-handoff adoptions, but the 09-04 gate only
  covered proposal fills. Day-1 evidence on the new books: AVGO armed-book
  fill 370.39 into a ladder of 359.51/361.57 (both below entry) self-flattened
  at −$17 in 6 min ("TP2 reached"); GME armed a 0.09%-wide stop and died the
  same minute. `runner._gate` now runs `check_exit_geometry` against the
  ACTUAL fill for both the analyst plan and the default ladder; repairs
  journal `TipGeometryRepaired` v2 (armed repairs carry runId/trigger,
  proposalId null) and land on the run log. Shadow books included — bad
  geometry poisons the armed-lane counterfactual sources are judged by.
  DEBT: the wiring has no end-to-end degenerate-fill test (forcing a fill
  past the planned ladder through the arm machinery is expensive); the pure
  gate is fully tested and the first live `TipGeometryRepaired` from the
  armed lane is the acceptance check — verify one appears within days.

- 2026-09-07 — **Glide sizing** (user decision: "ambitious but never lose a late
  tip to a full book" — the per-technique $10k cash-checked book made this real):
  per-tip budget = min(`budget_per_tip`, free cash / `reserve_slots` 3), floored
  at `min_budget` $500 while any cash lasts; only an empty book refuses, journaled
  `TipLaneDecided lane=refused`. On the $10k book: tips 1–5 full $2k, ~#6–8 glide
  $1.5k→$900, #9+ minimum expression. Cards carry the glide note. Also made the
  two DEAD per-source knobs real (`max_open_tips` count gate, `budget_open_max`
  shrinks to remaining allowance) — they were parsed and enforced nowhere.
  Shadow books never gated (counterfactuals stay full-size comparable).

- 2026-09-04 (evening) — **The adoption-geometry gate is CODE now** (the analyst's
  nine-strike rule made deterministic; `lifecycle.check_exit_geometry` +
  `adoption_killswitch`). Eight adoptions in three days (HOOD 9/02, MU 9/03–04 ×4,
  MRVL 9/03 ×2, RKLB 9/04) died in seconds on wrong-side targets, penny TP1s, or
  stops inside noise while the analyst kept escalating a PROMPT rule. At adoption
  the plan is now sanitised against the ACTUAL fill: wrong-side/penny targets
  dropped, an invalid stop re-placed at the structural level (>= max(~1x 15m ATR,
  0.75% of entry; 1.0% on 3%+ daily-range names), below the recent swing low −
  buffer for a long). Repairs journal `TipGeometryRepaired` + land on the analyst
  run. Session clause: one adoption stopped out < 5 min after arming pauses tip
  auto-approvals for the day (`TipAutoPaused`; cards wait for the human/triage).
  Sim feed skips the bars fetch (sign + % width only) — tests stay offline.
- 2026-09-04 (evening) — **Per-tip premium cap** `techniques.tip.max_premium_per_tip`
  ($750, 0 = off): BBAI's 25 × $0.51 = $1,275 concentration made one loser the whole
  day. Applies at every option sizing site, stated analyst/tip counts included;
  one contract always fits.
- 2026-09-04 (evening) — **Earned auto judges BOTH lanes** (user decision):
  `source_trust` adds the immediate shadow book's aged marks (first fill >= ~20h,
  marked above cost = hit) to closed practice positions. The armed lane barely
  trades on momentum tips (shadow audit: immediate +$52k/+$48k/+$18k vs armed
  ~flat), so armed-only trust could never graduate a good source.
- 2026-09-04 (evening) — **Knowledge hygiene**: nightly context digests ON
  (`techniques.tip.digest_enabled`), and a new `rule` note whose `RULE (<family>`
  prefix matches a live rule now auto-supersedes it (journaled `TipRuleAudited`
  via family-dedupe) — nine live versions of the geometry rule were being
  injected into every run; consolidated to one (note dbfd8177).

- 2026-09-04 — **The bleed exit: an option collapsing while the stock stands still is the
  OPTION failing, not the thesis** (BBAI Mar-27 4C: bought at the ask of a 26% spread at 0.51,
  stock never moved more than ~6% off entry, contract bled to the −55% premium stop over four
  sessions — −$780 where −$450 was available). New `premium_bleed` policy
  (`techniques.tip.bleed_exit_pct` 35 / `bleed_band_pct` 3): premium down ≥35% with the
  underlying inside ±3% of entry → exit now. When the stock IS moving, the normal stops own
  the decision. Note the entry half was fixed separately (spread-gated market orders +
  limit-at-mid). Watch: band 3% vs BBAI's slow drift — a 5-session drift can walk outside the
  band before the bleed threshold; revisit with ≥10 bleed-exit samples.


- 2026-09-04 — **Swing options run the monetize campaign; deep-ITM winners roll up** (user
  decision after the 09-03 review + literature research; ambitious defaults). Half off at
  +100% premium (the debit is recouped — the trade can no longer lose), ratchet floors
  15/50/120 under the rest, theta/IV tightening, and the McMillan roll-up (credit ≥ debit,
  max 2) for winners that go mostly intrinsic. Knobs: `techniques.tip.monetize_*`,
  `techniques.tip.rollup_*`. The analyst's underlying ladder still runs — whichever prints
  first. Watch: whether the +100% arm ever fires on our tip flow (shadow MFE data will say);
  revisit thresholds at 50 closed option positions, coarse grid only.


- 2026-09-02 — **Lotto exits are judged on the CONTRACT, every quote tick.** GOOGL
  340C 0DTE (ab, auto-filled 12:02 ET): the contract tripled and gave it all back inside
  one 15m bar while the analyst's underlying ladder (341.5 / 343.5 / 346) never printed
  (GOOGL peaked 339.18). Lotto policies now carry `premium_ladder`
  (`techniques.tip.lotto_premium_targets` "100,200" × `lotto_premium_fractions` "0.5,0.5"),
  `premium_floor_after_trim` (after the first rung the rest can't close below the
  entry premium) and `premium_watch` (premium ladder + premium stop on the ~2 s quote
  loop). The analyst's underlying ladder stays — whichever prints first. Rungs are a
  first guess (one observation); revisit after ≥10 lotto fills.
- 2026-09-02 — **That GOOGL fill was not real.** The practice book bought at 0.13 (the
  15-min-delayed chain ask) when the tape was ~0.55 — the "+230 %" the position showed
  was fantasy and the premium stop was blind to a real −60 %. Platform fix in
  PLATFORM-RULES (delayed band re-centres on the live print). Treat every practice
  option P&L before this fix as suspect where the contract moved fast; the lotto
  scorecard starts counting from here.

- 2026-08-28 — **Breakout tips honoured as breakouts**: a stated level on the
  far side of price ("watch $22 for a breakout", price 20.4) now mints a
  breakout/breakdown trigger at the tip's own level (`entry_basis=on_break`,
  tracker close-through + 1.5x volume + follow-through discipline). Before,
  the plan builder silently substituted a dip-buy at the nearest support —
  the opposite trade wearing the tip's name. The replay lane emulates the
  close-through fill for scoring.

- 2026-08-28 — **Shadow-implied lane**: `is_actionable=false` demotes to the
  shadow books instead of killing the tip (status `shadow`; proposals still
  require an explicit call). Reason: the PeloSwing CRM case — implied chart
  tips are the commonest real tip shape and the books were blind to them.
- 2026-08-28 — **Freshness rule**: content whose own visible date is older
  than `techniques.tip.max_tip_age_hours` (72) is **replayed on history**
  (`techniques/tip/replay.py`; both books' counterfactuals stored on
  `extraction.replay`) and never traded. Reason: a two-month-old screenshot
  verified clean because a price-less tip skips every price check.
- 2026-08-28 — **Immediate book fixes**: shares sized by `budget_per_tip`
  (was 5% of equity — dwarfed option tips, distorted the book comparison), and
  every bracket-less share buy books a `closeAfter` time exit (the morning
  sweep sells it; before this they were held forever).
- 2026-08-28 — **Generous defaults** (user): budget_per_tip 500→1000,
  budget_open_max 2000→5000, horizon_sessions 10→15, max_open_tips 3→5.
- 2026-08-28 — **Proposals trade the tip's vehicle** (found live: the SPY 750P
  hedge alert proposed SELL 1 SPY @ 769 — short shares at the underlying ask —
  while both books correctly bought the put). `create_from_signal` now proposes
  the analyst's "take" contract (else the book's expression contract) BUY-to-open,
  sized by `budget_per_tip`; a bearish tip with no usable put proposes NOTHING
  (shorts are puts only, same as the books). Run: analyst #1968b277 / proposal
  #71796b9b.
- 2026-08-28 — **Auto mode defined**: `mode: auto` self-approves the proposal via
  the normal `approve()` path (RiskGate inside, journaled `decided_via=auto`) only
  when the analyst said `take` (or is disabled); anything else waits for the
  human. Live portfolios additionally need `techniques.tip.allow_live_auto`
  (default off). Auto remains scorecard-earned per source — the platform default
  stays `proposal`.
- 2026-08-28 — **Shared tips knowledge** (`tip_notes`): the analyst reads the
  notes matching its tip (ticker/source/general/signal scopes) before every run
  and saves durable context via `save_note` (e.g. "SPY put = downside protection
  for the source's Oct-Dec calls" — the reason we'd exit differently weeks
  later). Journaled `TipNoteAdded`; user-editable in Tips > Analyst > Knowledge.
- 2026-08-28 — **The analyst is an independent trader** (user decision; charter
  in ANALYST.md). EM's method book NEVER applies to tips — "our book" in the
  analyst's tools means the desk's own positions. The analyst authors the EXIT
  PLAN for every take (scale-out ladder on the underlying, stop or declared
  premium-stop guard, premium bleed stop, hold cap); filled tip proposals are
  adopted into the durable position manager under that plan; closed positions
  get a retro run whose lessons update the shared notes and the analyst's OWN
  rules (knowledge scope `rule`, injected into every run). Safety floor stays
  platform-enforced: RiskGate on every order, never 0DTE / naked writing /
  share shorting, budget caps, auto only on "take" + allow_live_auto for live.

## Change log 2026-09-08 → 09-13 (first Practice week on the per-technique book + the audit cycle)

**Book reality (reconciled from executions+fees, Tips Practice `4611946d`):**
Sep-8 −$214.24, Sep-9 −$797.86, Sep-10 −$192.69, Sep-11 **+$254.24** —
cumulative closed net ≈ **−$950.55** since the reset. One green day inside a
drawdown; nothing is claimed proven. Open into the new week: T Jan-27 29C
(10 of 14), APLD Oct 30C, RKT 148 sh.

- 2026-09-11 — **First ladder win, correctly worded** (GOOGL Nov 370C, ab
  campaign): 8.45 → 10.95 ×1, +$247.92 net at TP1; the stock later faded
  below TP1. Supports that execution; ladder superiority and missed-upside
  remain unproven (reviewer's wording adopted).
- 2026-09-11 — **Partial source exits mirror proportionally** (T): source
  "CLOSE: sold 6/10" → desk sold 4 of 14 (+$27.68 net), kept the rest; the
  WAITING T plan was flagged for review, not disarmed. Matches the
  thesis-dead-vs-profit-taking distinction under observation above.
- 2026-09-10/11 — **Entry pricing at alert time is the working hypothesis for
  the loss shape** (CCXI bled 65% from 0.60; SPCX −4.3% real but killed by a
  stale mark; META filled 0.78 vs the source's 1.00→0.65 round trip) — but
  the entry study's first 13 pairs (proposal-time, proposal-path-only, NO
  lotto cohort) showed median ask drift 0.0%: no free lunch from waiting on
  that cohort. Collection continues; a week is a checkpoint, not a promotion
  deadline. NO entry-rule change.
- 2026-09-11 — **A fresh quote is not necessarily a sane quote** (DAL): the
  premium stop fired on `opra 1s old bid=0.82` while the exit filled at
  1.5274 one second later — an anomalous flash print. → tick premium stops
  (bleed AND ratchet floor) now need TWO DISTINCT fresh observations within
  45s (v0.7.54, `execution.premium_stop_confirm_window_seconds`); re-polled
  cached quotes never confirm; recovery resets. Bar path unchanged.
- 2026-09-11 — **Meet Kevin onboarded** (MK-alpha-trades tips-mode + 3
  context channels; long-horizon own-book style, source-profile note saved).
  Day-1: his "$200k basket add" extracted (NVDA/SPCX shares) then died in
  verification — root cause was NOT policy ("I added" IS recognized as
  actionable) but the grounding corpus: the image transcript REPLACED the
  caption (fixed v0.7.50, union + coverage manifest). Own-book mirroring
  stays OFF pending the shadow-first build with PREDEFINED promotion
  criteria (reviewer condition — no "trust accrued" hand-waving).
- 2026-09-10 — **The retro can no longer learn from trades that didn't
  happen**: CCXI's −$505 practice loss had been retro'd as "expired
  unfilled" and taught a wrong entry rule (run 1f692543). Unfilled retros now
  disqualify any signal with a real fill in any lane (v0.7.44).
- 2026-09-09/13 — Reliability line (details in reviews/): crash-proof gateway
  ledger; premium exits demand fresh marks and name their evidence;
  stale-quote entries get ONE bounded retry (auto+Practice only); analyst
  truncation repair gets doubled output room; per-turn input tokens recorded
  (the 136k "context" was cumulative across calls — measure before
  consolidating the 50-rule book).

- 2026-09-14 — **Geometry before entry + the execution-integrity pause are LIVE in
  Practice** (v0.7.67; record in `reviews/2026-09-13-pr91-pr93-response.md`).
  `techniques.tip.geometry_gate=enforce`: the stop is finalized and the size derived
  from it against the approved budget (`risk_pct` 1% of equity; `risk_budget_per_tip`
  0 = off) BEFORE the order, recomputed at submission; a card without evidence
  (delta older than 900 s, no fresh non-delayed underlying reference, unknown
  contract multiplier, bars down) is review-gated, never guessed. Post-fill a stop
  may only tighten immediately; a widen is trim-first with a durable attempt.
  `techniques.tip.entry_pause_mode=integrity`: the 2026-09-04 "<5-min stop-out
  pauses the session" clock brake is RETIRED — a fast loss on a trade whose
  geometry, sizing, quote evidence and fills were valid is a clean loss
  (`TipFastStopDiagnostic`, the daily-loss limits own that decision); automated
  entries pause on a persisted `TipExecutionIncident` (filled outside plan,
  unconfirmed/delayed exit evidence, duplicate/unreconciled fills, repeated
  pre-entry failure) and release only on evidence bound to it. The rulebook was
  consolidated the same night (61 → 32 live rules: the 28-rule adoption-geometry
  family into one canonical rule `85fb55e8`, the two disputed kill-switch rules
  released and replaced by the incident policy `035b22fc`; 14 case records in
  `evidence:adoption-geometry`, never injected). Numeric thresholds in the family
  text are HYPOTHESES, not operative policy. ACCEPTANCE: the first
  `TipGeometryRepaired phase: pre-entry, enforced: true` and the first
  review-gated card in the 2026-09-14 session; the first incident, if any, must
  show every automated path refusing while exits ran.

- 2026-09-14 (evening) — **Day 1 under enforce + integrity: the gate did its job, the
  budget decides everything.** Sixteen pre-entry geometry records on Tips Practice, all
  `enforced: true`. Twelve cards were review-gated: eleven on "no quantity satisfies the
  ~$89 risk budget" (1% of an $8.9k book; one option contract with no stop risks its whole
  debit, $96–$400) and one shares card with no stop. Ten of those were analyst SKIPs anyway
  (maps, wishes, hedges — rejected on the analyst's verdict, as before). Two were analyst
  TAKEs (MSFT 9/14 505C ×7, TSLA 9/25 340P ×3) that expired unapproved. The two take cards
  that PASSED (HIMS 9/18 30C resized 15→1, AAL 11/20 14C resized 11→2) were refused
  automatic approval by the integrity pause, approved by the user in the app at 10:09, and
  re-validated at submission: HIMS filled at 0.46 (adopted, stop 26.67, later 28.40); AAL
  rested unfilled all day at 0.67. Method verdict: under a 1% budget with no stop on the
  card, options tips are a REVIEW product, not an auto product — the analyst must supply a
  stop (underlying or premium) or the budget policy must change. Both are user decisions;
  nothing in the code is wrong. Exits were untouched by the pause: T mirrored a source
  trim at 09:32 (+$16), RKT TP1 at 13:00 (+$16), T TP1 at 14:15 (+$20); the pre-market
  APLD 30C stop (−$210) was a clean stop, no diagnostic fired. Zero
  `TipFastStopDiagnostic` today. Tips Practice realized −$158.
- 2026-09-14 — **The integrity counter's first false positive** (fixed the same morning,
  v0.7.69 in the 11:50 deploy): `repeated_pre_entry_failure` counted every review-gate
  as a path failure, opened six incidents (two duplicates) from budget-fit gates on
  skipped cards and paused Practice proposals from 09:22. Two were released on bound
  evidence (the HIMS/AAL validations, 10:16); four opened before the fix deployed are
  still open at the close (`760309ca`, `df02e34a`, `2e87b5bf`, `4e93b293`) — their
  basis is void, releasing them is a labeled override (user) or the next take card that
  validates on the book. Rule since 0.7.69: only SYSTEMIC failures (bars/quote/greeks/
  provider unavailable, delayed, stale, exceptions) count; one incident per path, book
  and session.

- 2026-09-14 — **MK own-book classification is built, shadow-first, off by default**
  (KFIN-08; PLATFORM-RULES invariant 19). An enrolled source's first-person text is
  classified deterministically (own_open / own_exit / recap / hypothetical /
  third_party; the extraction's new `actor`/`activity` fields only fill silence, text
  wins and a disagreement is recorded) and in `techniques.tip.mk_ownbook_mode=shadow`
  routed to the source's own-book shadow book (`book=ownbook`) — never the immediate
  book, the analyst, a proposal or an armed plan; the Practice/live gates are never
  reached. Evidence rules kept whole: shares need a grounded entry price, options a
  grounded strike + expiry, both a qualified two-sided quote ≤ 120 s old at the
  decision and content inside `max_tip_age_hours` — otherwise `ownbook_unresolved`
  with the reasons journaled (stale content is NOT back-filled from history). "Sold
  half" reduces the own-book position by half (reduce-only); an exit with nothing
  held, a recap, a hypothetical or another person's screenshot is `ownbook_context`
  and opens nothing. Own-book context/unresolved rows never dedupe a later message
  (a recap must not swallow "just added" an hour later). Grading is on the quote at
  the decision + our fill inside the DECLARED cohort (`mk_ownbook_cohort`; "" = nothing
  grades); the criteria (`mk_ownbook_min_graded` 20, `min_hit` 0.55,
  `min_avg_return_pct` 0, `max_unresolved_pct` 25, `min_age_sessions` 5) are REPORTED
  by `GET /api/tip/ownbook/{source}` with `verdict: human` — nothing acts on them, no
  calendar deadline. 18 labeled cases + 12 pipeline tests in `tests/test_tip_ownbook.py`.
  To enroll MK: `mk_ownbook_sources=["MK-alpha-trades"]`, `mk_ownbook_cohort=<label>`,
  `mk_ownbook_mode=observe` first (classification journaled, pipeline unchanged), then
  `shadow`. Known limits: "we bought" on an enrolled source reads as the author's fund;
  "sold puts" (a premium-selling OPEN) reads as an exit; a third-party screenshot with
  no textual cue relies on the extractor's `actor`; sessions are weekday-counted.
- 2026-09-14 (EOD review, `reviews/2026-09-14-eod-response.md`) — **Correction to the
  budget narrative:** the MSFT 9/14 505C and TSLA 9/25 340P takes DID carry stops (MSFT
  501.2 → 485.49 after structure repair, TSLA 368 → 369.81, 45% premium stops); their
  delta-linear unit risk ($96, $100) exceeded the ~$89 budget. "Require a stop on every
  take" does not fit them; the budget did what it was asked. No automatic budget increase.
  Research queued: show budget feasibility to the analyst before tool work; separate
  `take-but-cannot-fit` from skips in the scorecard; record why structure moved a stop.
  The APLD Oct 30C exit at 04:01 ET is an execution-realism defect (Practice options now
  fill only in an eligible session); its −$210 stays in the ledger, flagged. Three retro
  rules written after the close promoted reviewed HYPOTHESES to policy without a batch —
  quarantined; model-written rules are proposals from now on.

**Built 2026-09-14 (KFIN-08, shadow-first, INERT until enrolled):** MK
self-disclosed-trade classification with labeled fixtures + predefined promotion
criteria (`techniques/tip/ownbook.py`, `tests/fixtures/mk_ownbook_cases.json`,
`GET /api/tip/ownbook/{source}`). **Queued (agreed, not built):** multi-image
evidence processing.
**Built 2026-09-14:** geometry validated BEFORE entry with bounded journaled
post-fill exceptions (user decision 2026-09-11); rule-book consolidation.

## Change log 2026-09-15 → 09-16 (first FOMC day under enforce + integrity; the profitability build)

- 2026-09-15 — **The budget is the product's bottleneck, measured.** 32 `TipGeometryRepaired` records on
  the day: 15 review-gated "no quantity satisfies the ~$89 budget" (one-lot option risk above 1 % of
  equity), 6 stop re-placements at submission/revalidation, 2 wrong-side target drops. Two analyst takes
  expired unapproved. The feasibility annotation (PROF-01) now tells the analyst BEFORE the verdict; no
  automatic budget change - `risk_pct` / `risk_budget_per_tip` remain a user decision.
- 2026-09-15 — **Two over-sell classes, both platform, both fixed** (`PLATFORM-RULES`): the venue GTC stop
  kept its pre-trim size (RKT sold 148 vs 89 held → −59, reconciled on the user's go); the proposal's
  bracket children coexisted with the manager's venue stop (MRNA 14 resting against 7 held; released by
  hand 15:22 ET). Method consequence: the "one exit authority" the ARM-PLAN promised is now enforced at
  adoption. The shadow armed books carry phantom shorts from these classes (README gap 1) - their
  scorecards are not trust evidence for those names.
- 2026-09-15 — **Hold study protocol (holdstudy-v2, research only).** Observations count only inside
  exchange-calendar windows on the quote's own sample time; the three v1 rows (captured 16:42 ET by an
  after-close catch-up) are insufficient. The question stays open: is carrying overnight worse than a
  predeclared pre-close liquidation, by setup? No pair exists yet (first valid capture 2026-09-16 15:50 ET).
- 2026-09-16 (FOMC day: statement 14:00 ET, presser 14:30 ET) — **A quiet, selective morning is not four
  correct skips.** Tips Practice: 0 executions through 12:15 ET; four completed appraisals, all skip (eva
  SPX-led 12-branch map = a map, not an open; tt META lotto = counter-trend tape + reach; ab APLD holdings
  digest = old averages, not a buy; ab GOOGL Sep-18 350C = ceiling/reach + source lotto record). The review
  team's read: the tape / source / attainable-gain reasons stand on their own; two REASONING defects rode
  along and are corrected in the prompt and the tools (below). No counterfactual executable path was run
  to grade the skips - "flat" is the honest description.
- 2026-09-16 — **Reasoning correction 1: the expiration break-even is not a profit condition** (INTRA-01,
  I175-03). The GOOGL rationale said breakeven 352.19 above the 350 ceiling meant the trade only pays on a
  break. Wrong frame: a sale before expiry pays when the executable bid exceeds entry + costs. Synthetic
  acceptance: 2.19 → 2.50 bid with the underlying at 349 nets +$28.92 after $2.08 fees. A maximum hold
  cap is not an expiry exit; only a declared held-to-expiry scenario uses intrinsic value.
- 2026-09-16 — **Reasoning correction 2: one lot is an exit-plan question** (INTRA-02, I175-02). META and
  GOOGL called one contract "an unmanageable binary". The executable single-lot plan (first-target exit
  or a premium exit) is judged on its own net payoff; the label "can copy partials" is derived from the
  executed unit sequence (3 × 80/10/10 executes 2/1/0 - it cannot). Skip only when the thesis depends on
  scaling or one unit does not fit the budget.
- 2026-09-16 — **Appraisal cost baseline** (INTRA-03): the four appraisals used 482,420 input tokens over
  12 calls (37k–45k per call, cache reads 0) - the per-call header × the call count. A cheap message-shape
  read is journaled before every multi-signal appraisal; routing confirmed recaps to a compact context is
  built but OFF until evaluated on frozen bundles with a captured classifier read (parity proven unpaid).
- 2026-09-16 — **Event days have no rule.** The desk labels decisions with the verified event and the
  time to it (TMR-01); the shared calendar is empty and no desk enforces event days. Whether the label
  should ever become a sizing or timing input is an open question for the register, not a rule.

### Rules under observation (added 2026-09-16)

- **Recap route (OFF):** does the compact context reach the same verdict on confirmed maps/recaps at lower
  cost? Evidence set: compact-route captures replayed under `recap_candidate` vs `current`; negative
  controls (fresh entry, management, mixed) must stay on the full route by construction. Decision: reviewer.
- **Break-even framing:** do post-correction rationales still cite the expiration break-even as a
  profit condition? Read the next ten option skips.
- **One-lot plans:** how many one-lot takes/skips cite `singleLot`; how many one-lot fills reach their
  first-target exit vs the stop (payoff report + hold study managed outcome).
