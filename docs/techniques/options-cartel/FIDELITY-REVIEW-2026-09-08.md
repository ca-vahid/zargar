# Method fidelity review — September 8, 2026

## Evidence and interpretation

- Sean's [September 8 system explanation](https://x.com/SRxTrades/status/2097459972884058424)
  emphasizes sector/theme leadership, bases, lower-timeframe entries, and scaling/trailing.
- His [September 7 weekly list](https://x.com/SRxTrades/status/2097097587828707793)
  includes memory, storage, semiconductors and biotech. The September 8 preparation
  excluded 13 inspected names on the strict industry gate before analyzing their charts.
  This demonstrates a coverage mismatch, not proof those stocks all had eligible entries.
- Cartel's [September 8 DRAM post](https://x.com/TheOptionCartel/status/2097414673662718231)
  reports over 200% on a swing. That is a group trade highlight, not verified Sean
  daily account P&L, weighted realized returns, or a trade opened that day.
- The provider classifies US DRAM as CBOE:DRAM, fund/ETF, USD, without stock market
  capitalization. The old stock-only NASDAQ/NYSE/AMEX query could not discover it.
- SPCX's recorded crossing was rejected by our 0.70 close-location threshold;
  ZIM was armed late with missing opening minutes and sparse volume baselines.
  These are implementation findings, not author-prescribed trading decisions.

## Changes in 0.7.12

New preparation uses industry ranks as context by default; explicit `strict`
retains the top-list gate. This is a versioned engineering interpretation motivated
by the current theme/leader guidance. Context mode does not claim to automate a
discretionary catalyst thesis. Market alignment, daily/weekly structure, liquidity,
relative strength, targets, and all execution risk checks remain required.

The reviewed ETF list defaults to DRAM and is configurable per preparation workspace.
Only explicitly listed provider-classified ETFs are eligible. ETF facts are dated;
stock market-cap and stock-industry requirements are inapplicable, while the other
price/volume/ADR/trend/setup checks remain. This is not blanket approval of inverse,
leveraged, or exotic funds. Any additional ETF requires a review of its structure.

A dated, editable historical comparison list explains coverage and exclusions. It
does not insert trades or override gates. The initial reference is Sean's September 7
list, not a continuously updated feed. Update its symbols and source together.

The existing 15m breakout, 1.5 volume multiple, and 0.70 close location remain the
default execution baseline. Settings expose timeframe, breakout/retest and threshold
choices. Sean's public 5m/15m and retest guidance supports researching those variants;
it does not establish our exact numeric thresholds. No variant is auto-promoted.

Timeframe research comparisons rebuild baselines from historical minutes saved in
new replay records. Older replays without that context must be recreated. Outcome
comparisons model underlying prices, not option P&L or audited broker execution.

New automatic plans require usable volume baselines for every session confirmation
period. Missing periods block arming with counts. Pending-contract activation reads
stored session minutes and makes a bounded historical recovery when needed; it
blocks incomplete or stale tape, crossed invalidation and a reached first target.
Recovery seeds the plan's observation only and cannot replay an earlier crossing.
Existing submitted orders and managed positions continue under their saved policies.

Entry decisions retain up to 500 distinct timestamped records through recovery,
including numeric rejection measurements. Decision changes are journaled. The record
page shows retained reasons and the Armed summary exposes the latest entry check.
Old preparation snapshots must be freshly prepared rather than resumed under the
new coverage interpretation; existing plans and research remain readable.

## Tomorrow's review

1. Confirm the deployed version and prepare a new session. Review the effective
   industry policy, reviewed ETFs, and dated comparison source in Settings.
2. Check discovery includes CBOE:DRAM and explains the comparison list's outcomes.
3. Inspect blocked-plan counts and missing-baseline periods before trusting “armed.”
4. At each review compare current conditions with retained entry decisions; verify
   recovery does not erase earlier reasons or trigger historical entries.
5. Build a set of complete replays over multiple sessions, including losing and
   non-entry cases. Compare all four timeframe/mode variants. A single day's better
   result does not justify changing the execution baseline.

Deployment requires updating/restarting the normal app outside a protected window.
Codex does not restart the shared runtime or alter its saved risk percentages.
