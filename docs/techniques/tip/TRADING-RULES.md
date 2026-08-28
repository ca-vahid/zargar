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

## Change log

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
