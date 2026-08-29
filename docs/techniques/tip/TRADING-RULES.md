# Tip technique — judgement log

*The METHOD's findings, open questions and rule changes — not the code's.
Date every claim; cite the signal/replay/scorecard it came from. Sibling of
`docs/techniques/enhanced-market/TRADING-RULES.md`; engine-level invariants
live in `docs/PLATFORM-RULES.md`.*

## Rules under observation

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
