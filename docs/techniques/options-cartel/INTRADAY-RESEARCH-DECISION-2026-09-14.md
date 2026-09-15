# Intraday market research decision — September 14, 2026

**Accepted:** monitor intraday market improvement and record hypothetical stock setups in
Practice. **Not accepted:** automatic intraday unlocking, weakened entry/risk gates, changing
Live permissions, or presenting the experiment as Sean's exact rule. User approved this
recommendation and requested that the decision be retained in the documentation.

## What Sean says and what we inferred

Sean describes market EMA context as a guide to participation and sizing: favorable SPY/QQQ
context supports greater long conviction; weakness calls for smaller size or abstention.
His lower-timeframe stock confirmations do not establish an automatic 15-minute reopening
rule for a blocked daily market assessment. His dated posts vary in EMA combinations;
our strict/Moderate binary permission rules are engineering interpretations, not verbatim
universal author rules.

Primary authored text, archived for access:
- [Strategy framework](https://threadreaderapp.com/thread/1971976644362674547.html):
  market context, reduced participation in weakness, leading themes and individual entry confirmation.
- [Market adaptation](https://threadreaderapp.com/thread/1902168481807704139.html):
  direction, limited exposure and abstention in sideways conditions.
- [September 13 system summary](https://x.com/SRxTrades/status/2099241717983486243):
  the previously reviewed market/theme/leader/setup/risk hierarchy. Live retrieval may require sign-in.

The assistant's earlier statement that the engine **should** reopen intraday was too strong.
No verified source establishes our proposed cadence, two-observation condition or automatic
permission transition. The approved response is evidence collection only.

## Version 1: daily_ema_intraday_research_v1

- Practice only; uses the matching completed, market-blocked, long-research preparation for
  the current session and its dedicated account. Maximum five saved shortlist names.
- Watches SPY, QQQ and those names for market data. Subscription/history collection is not an
  entry, proposal, alert arm or broker request. No option contracts are selected by this monitor.
- Keeps the prior completed session's daily EMA8/21/50 values **frozen**. Samples completed
  15-minute index candles against those levels. These are NOT 15-minute EMAs, and not a
  continuously recomputed provisional daily EMA. Missing/stale reference data stays unavailable.
- Mirrors the saved strict/Moderate comparison for research only. Two consecutive aligned
  quarter-hour observations establish `sustained_improvement`; a missing/late observation or
  a failed comparison breaks the streak. This count is an engineering choice.
- Allows 60–120 seconds after each quarter-hour close for normal bar persistence. A later
  observation cannot masquerade as an on-time one. It does not replay skipped quarters.
- Builds a frozen, exchange-source same-time volume baseline once per preparation, retaining
  the selected full-session/opening-and-broad coverage requirements. V1 supports 15-minute
  stock-entry policies; other selected timeframes are marked unsupported, never rewritten.
- After sustained improvement, applies the existing pure stock-entry reader to complete
  current-session context. Its prospective cutoff is the latest of the improvement observation,
  context availability and this monitor's startup. Pre-cutoff crossings cannot become new entries;
  prior invalidations remain binding. Restart never retroactively earns a hypothetical entry.
- Persists immutable `intraday_watch` and `watch_context` research records with preparation,
  account, session, code/policy version, timestamps and observed source evidence. Research records
  are not `plan` records, and the arm repository rejects them even if someone submits their IDs.
- A `hypothetical_stock_confirmation` means the saved **underlying** conditions matched the
  available evidence. Option eligibility, execution price, fees and profitability are not established.
  Recovered/stored bars do not prove they arrived at the original exchange close.

## Controls and visibility

Options Cartel → Plans contains **Intraday market research**. It explicitly states that
arming permission remains unchanged. Settings contains the non-executing research toggle,
`techniques.options_cartel.intraday_research` (enabled by default for this user-approved study).
Turning it off stops new collection; historical records remain. Existing trades, market gates,
risk budgets, automatic preparation and Live behavior are unaffected.

The worker runs bounded background work, once per minute at most, with one owned task and
one immutable snapshot per quarter-hour/preparation/version. It warms subscriptions/baselines
from 08:45 ET and observes 09:45–16:00 quarter-hour closes. Slow/provider-failed collection is
visible, backs off, and never blocks the order/exit loop. Stop cancels the owned research task.
No new engine, account or runtime database is created.

## Evaluation and promotion boundary

Collect consecutive sessions with both positive and negative observations. Keep missing-data
and missed-observation cases in the denominator; distinguish each preparation and experiment
version. Compare blocked-day candidates and fresh confirmations without retrospectively choosing
winning symbols or claiming stock movement as option profit. The existing twenty-session
collection checkpoint is not statistical proof or automatic graduation.

Any later trial that allows entries requires a separate explicit decision, source review,
predefined sizing/eligibility rules, forward validation and a new policy version. This release
contains no promotion switch, automatic execution override or Live activation.

## Implementation and validation

Delivered as the v0.7.84 research feature. Focused monitor/runtime checks: 19 passed;
monitor/preparation-safety checks: 9 passed (overlapping groups). The tests preserve the
market-blocked preparation, prove zero orders/arms/executable plans, reject attempts to arm
research record IDs, and exercise incomplete/stale/late evidence and broken streaks.
Production build and four built-UI cases passed (desktop/phone, Practice/Live), including
absence of execution controls and no trading writes. Research signal fixtures meet the existing
close-location/chase limits; those limits were not weakened for the test.
