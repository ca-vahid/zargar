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
