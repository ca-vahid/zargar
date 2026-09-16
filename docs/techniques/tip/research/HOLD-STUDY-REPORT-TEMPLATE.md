# Hold-study paired report - template (TMR-04, for the 2026-09-17 09:47 ET report and after)

Produce with `python -m zargar.tools.tip_hold_study report --since <session> --json <file>` on the
runtime DB (`ZARGAR_DATABASE_URL=...5433/zargar`), then fill this template. Research only: no order,
no knowledge write, no rule derived. The report carries the register identity (`overnight-hold`).

## Header

- Sessions paired: pre-close `<YYYY-MM-DD>` (event context: `<label from window.event>`) -> next open
  `<expected_next_session>`; study version `holdstudy-v2`; build that captured: `<health.build>`.
- Protocol: pre-close window `<start>-<end> ET` (close - 15 min, early closes included), job at close - 10 min;
  next-open window 09:30-09:45 ET, job from 09:30, `<attempts>` retries 20 s apart.

## Observation counts (per BOOK KIND, per arm, per setup; every row counted)

| book kind (sim = Tips Practice / shadow / live / unknown) | arm | setup | eligible rows | fresh both ends | pre-close missing / late / ineligible / outside_window | next-open missing / late / ineligible / missed | adequate pairs | distinct positions |
|---|---|---|---:|---:|---|---|---:|---:|

"Eligible" = every observation the protocol created; nothing is dropped or repaired. Legacy v1 rows
(2026-09-15) appear only in the outside_window column and never in a pair.

## Actual sample times (per observation)

| position / leg / arm | pre-close jobStartedAt | pre-close observedAt (actual) | pre-close sourceTs | next-open jobStartedAt | next-open observedAt (actual) | next-open sourceTs | attempts |
|---|---|---|---|---|---|---|---:|

observedAt is the quote's own `sampledAt` (never the job start); sourceTs is the venue print.

## Fees and risk basis (per observation)

| position / leg | qty sampled / entry qty | fee basis | entry fee allocated | exit fee | total costs | plannedRisk (for plannedRiskQty) | riskForSample |
|---|---|---|---:|---:|---:|---|---:|

## Results - quote drift versus the predeclared intraday close (per adequate pair)

| pair | setup | intradayExit price / net / R | carryToNextOpen (quote drift) price / net / R | carry - intraday $ | sacrificed winner? |
|---|---|---|---|---:|---|

## Results - what the strategy actually did (managed exits, SEPARATE from quote drift)

| pair | closedBeforeSample? | exits between endpoints (ts, qty, price, kind, reason) | managedCarry net / R | note |
|---|---|---|---|---|

`managedCarry.known = false` means the position was still open at the next-open sample: the strategy's
result is not yet known and the quote-drift number is NOT it.

## Inventory eligibility (HOLD-SCOPE-02; per observation)

| position / book | book kind | quarantined? (note) | position status | eligibility (eligible / quarantined / attention / unknown) | scope resolution (captured vs resolved from the durable book) |
|---|---|---|---|---|---|

A quarantined, attention or unknown-scope observation is DIAGNOSTIC: its arms are computed and shown, it is
never an adequate pair, and it never feeds a Practice or source/hold conclusion. Missing provenance stays
unknown - never assumed Practice.

## Aggregate (by BOOK KIND x setup - HOLD-SCOPE-01; never pooled as performance)

| book kind | setup | n pairs | insufficient | ineligible (diagnostic) | quote-drift carry net | intraday net | mean carry R | mean intraday R | paired diff R | managed known | managed net | sacrificed winners |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

The tool's "pooled across book kinds" block is a diagnostic only (`pooledDiagnostic.performance=false`); it is
never presented as Tips Practice expectancy. Denominators are per book kind.

## Reading

- State the sample honestly per book: e.g. "one prospective Practice carry pair (MRNA), zero validated shadow pairs" -
  not "two positions".
- One or two pairs decide nothing; the evaluation window closes after >= 20 adequate pairs per setup or
  2026-10-16 (register). No holding-policy change from this study alone.
- Event-day sessions (window.event status `event-day`) are listed, not blended into a claim.
- Next observation needed: `<what>`; reviewer decision needed: `<what, if any>`.
