# Hold-study paired report - 2026-09-16 pre-close -> 2026-09-17 next open (first protocol-correct pair)

Produced 2026-09-17 09:47 ET from `python -m zargar.tools.tip_hold_study report --since 2026-09-16` on the runtime DB
(`scratchpad/hold-report-0917.json`). Research only: no order, no knowledge write, no rule derived. Register identity:
`overnight-hold` (`experiments-v1`; regime `holdstudy-v2`, evaluation window opened 2026-09-16, closes after >= 20
adequate pairs per setup or 2026-10-16; decision rule: no holding-policy change from this study alone, the reviewer decides).

**Honest sample: ONE prospective Tips Practice carry pair (MRNA), ZERO validated shadow pairs.** The AFRM row sits on the
quarantined ab ARMED shadow book and is DIAGNOSTIC ONLY. Yesterday's three Tips Practice intraday exits (T 13:15, SLV 15:00,
GOOGL Oct-16 360C 15:30 ET) have NO observations - the `intraday_exit` arm was blind on the 0.7.96 build (fixed in PR #184,
live since 0.8.03); they are counted MISSING, not backfilled. Both sessions carry event labels: the pre-close was the FOMC
session (`event-day`, statement 14:00 / presser 14:30 ET), the next open follows it.

## Header

- Sessions paired: pre-close `2026-09-16` (event: FOMC statement T+1h50m, press conference T+1h20m at capture; status
  `event-day`, coverage verified) -> next open `2026-09-17`; study version `holdstudy-v2`; build that captured the pre-close:
  0.7.96 `4c84697` (before `book_status` existed - scope resolved from the durable book, labeled); build that sampled the
  next open: 0.8.09 `dd525de`.
- Protocol: pre-close window 15:45-16:00 ET (close - 15 min), job at 15:50 (close - 10 min); next-open window 09:30-09:45
  ET, job from 09:30 with in-window retries. Both jobs ran: `tip_hold_snapshot` 15:50:10 ET result 2; `tip_hold_next_open`
  09:30:03 ET result 2, attempts 1.

## Observation counts (per BOOK KIND, per arm, per setup; every row counted)

| book kind | arm | setup | eligible rows | fresh both ends | pre-close missing / late / ineligible / outside_window | next-open missing / late / ineligible / missed | adequate pairs | distinct positions |
|---|---|---|---:|---:|---|---|---:|---:|
| sim (Tips Practice) | carry | shares | 1 | 1 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 1 | 1 |
| sim (Tips Practice) | intraday_exit | option:longer(>14d) x2, option:longer x1 (T, SLV, GOOGL) | 3 eligible | - | 3 MISSING (arm blind on 0.7.96) | - | 0 | 3 |
| shadow (ab armed, QUARANTINED) | carry | shares | 1 | 1 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 (ineligible - diagnostic) | 1 |

The 2026-09-15 v1 rows (MRNA, SLV, T) stay `outside_window` and never enter a pair.

## Actual sample times (per observation)

| position / leg / arm | pre-close jobStartedAt | pre-close observedAt (actual) | pre-close sourceTs | next-open jobStartedAt | next-open observedAt (actual) | next-open sourceTs | attempts |
|---|---|---|---|---|---|---|---:|
| MRNA / MRNA / carry (sim) | 2026-09-16 15:50:10.642 ET | 15:50:10.666 ET (quote sampledAt) | 0 (shares feed receipt basis) | 2026-09-17 09:30:03.445 ET | 09:30:03.672 ET (quote sampledAt) | 0 | 1 |
| AFRM / AFRM / carry (shadow) | 2026-09-16 15:50:10.642 ET | 15:50:10.642 ET | 0 | 2026-09-17 09:30:03.445 ET | 09:30:03.507 ET | 0 | 1 |

observedAt is the quote's own `sampledAt`, never the job start; sourceTs 0 = the shares feed carries no venue print time
(receipt basis; a known limitation, stated, not hidden).

## Inventory eligibility (HOLD-SCOPE-02; per observation)

| position / book | book kind | quarantined? (note) | position status | eligibility | scope resolution |
|---|---|---|---|---|---|
| MRNA / Tips Practice | sim | no | open | **eligible** | resolved from the durable book as it stands now (row captured before `book_status`) |
| AFRM / Shadow: ab (armed) | shadow | **yes** - EOD-09 2026-09-14 APLD same-symbol-leg runaway (3,282 exits, -40,600 sh) before v0.7.68; results invalid for lane comparison and source confidence until reconciled | closed 03:59:54 ET (see below) | **quarantined - diagnostic only** | resolved from the durable book |

## Fees and risk basis (per observation)

| position / leg | qty sampled / entry qty | fee basis | entry fee allocated | exit fee | total costs | plannedRisk (for plannedRiskQty) | riskForSample |
|---|---|---|---:|---:|---:|---|---:|
| MRNA (sim) | 7 / 7 | shares: per order per side; `sim.stock_commission` = 0.00 | $0.00 | $0.00 | $0.00 | $52.52 (for 7; stop 134.37 at capture) | $52.52 |
| AFRM (shadow) | 27 / 27 | same | $0.00 | $0.00 | $0.00 | $189.81 (for 27; stop 65.00) | $189.81 |

Fees charged to cash: MRNA entry 2026-09-15 09:34 ET commission $0.00 (executions table). Allocated = cash = $0.00 for
these share positions; sell-side regulatory charges are not modelled (stated on every row). For option rows the two views
differ and are reported apart (yesterday's EOD record).

## Results - quote drift versus the predeclared intraday close (per adequate pair)

| pair | book kind | setup | intradayExit price / net / R | carryToNextOpen (quote drift) price / net / R | carry - intraday $ | sacrificed winner? |
|---|---|---|---|---|---:|---|
| MRNA 7 sh (entry 141.96) | sim | shares | 145.21 bid @ 15:50:10 ET / **+$22.75** / 0.43R | 151.82 bid @ 09:30:03 ET / **+$69.02** / 1.31R | **+$46.27** | n/a (carry arm) |

DIAGNOSTIC ONLY (quarantined book; not a pair, not performance): AFRM 27 sh (entry 72.03): intradayExit 71.61 bid / -$11.34 /
-0.06R; carryToNextOpen 74.06 bid / +$54.81 / +0.29R; carry - intraday +$66.15.

## Results - what the strategy actually did (managed exits, SEPARATE from quote drift)

| pair | closedBeforeSample? | exits between endpoints (ts, qty, price, kind, reason) | managedCarry net / R | note |
|---|---|---|---|---|
| MRNA (sim) | no | none between 15:50:10 and 09:30:03 ET | **unknown** (still open at the sample) | AFTER the sample the strategy acted: 09:29:49-09:29:55 ET policy re-plan (stop 134.37 -> 145.50, ladder 155/162 x 0.5/0.5); 09:39:07 analyst follow-up close 2 sh @ 152.97 (source KianTrades "sold some MRNA here at 153.21"), stop -> 148.00; 09:45:00 TP1 155 trim 2 sh @ 154.37. 3 sh remain. None of this is in the pair; it is the managed path, reported when the position closes. |
| AFRM (shadow, diagnostic) | **yes** | 03:59:54 ET: 27 sh sold @ 44.991, kind venue_stop, "venue-side GTC stop" (stop was 65.00) | -$730.05 / -3.85R | A pre-market sim stop fill at 44.99 against a 71-74 market on a book already quarantined for a runaway - the row is evidence for the quarantine, not for the hold question; the book then re-bought 27 sh @ 73.06 at 09:35 ET (shadow arm). See "Findings". |

`managedCarry.known = false` for MRNA: the strategy's result is not yet known and the quote-drift number is NOT it.

## Aggregate (by BOOK KIND x setup - HOLD-SCOPE-01; never pooled as performance)

| book kind | setup | n pairs | insufficient | ineligible (diagnostic) | quote-drift carry net | intraday net | mean carry R | mean intraday R | paired diff R | managed known | managed net | sacrificed winners |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sim (Tips Practice) | shares | 1 | 0 | 0 | +69.02 | +22.75 | 1.31 | 0.43 | +0.88 | 0 | 0.00 | 0 |
| shadow (quarantined) | shares | 0 | 0 | 1 | - | - | - | - | - | - | - | - |

Pooled diagnostic (labeled `performance=false`, never Practice expectancy): shares obs 2 = sim 1 + shadow 1.

## Reading

- Sample: ONE Practice carry pair (MRNA) on an FOMC-day pre-close; zero validated shadow pairs; three intraday exits
  missing. One pair decides nothing; the window closes after >= 20 adequate pairs per setup or 2026-10-16. No holding-policy
  change from this study.
- The event-day label stays on this pair; it is listed, not blended into any claim.
- Next observation needed: today's 15:50 ET pre-close capture on 0.8.09 (the `intraday_exit` arm now reads the durable
  record - today's MRNA partial exits will be observed as exits IF the position closes today; otherwise MRNA's remaining 3 sh
  form tomorrow's carry row); the `book_status` column is now stamped at capture.
- Reviewer decision needed: none from this report.

## Findings (platform, owned separately; no change made here)

- **F-HOLD-01 (shadow sim stop fill at a nonsense price, 03:59:54 ET):** the quarantined ab armed shadow book's GTC stop
  (65.00) on AFRM filled 27 sh @ 44.991 pre-market while the stock traded 71-74 - a sim executor stop triggered on a bad
  off-hours quote. No money book was touched (MRNA's Practice stop at 134.37 did not fire). Evidence: `managed_positions`
  carry_outcome `exitsBetween`, the AFRM SELL execution 03:59 ET; details in the pre-open note. Handed to the platform /
  sim-executor owner for the quote-sanity check on off-hours stop triggers; the quarantine on that book stands.
