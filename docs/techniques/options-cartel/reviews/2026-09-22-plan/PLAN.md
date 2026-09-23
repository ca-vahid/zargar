# Options Cartel: improvement plan after 2026-09-22

Prepared 2026-09-22 evening ET by the Cartel implementation desk. Evidence is read-only from the
runtime database; nothing here claims a profitable strategy.

## 1. Where we stand

**Actual results.** Capital-experiment book `e7b246c9…`: zero orders, fills and P&L on 2026-09-21 and
2026-09-22 ($1,000,000 cash unchanged). Since 2026-09-14 across both Practice books the desk has one
executed trade (APA, -$61.13).

**Funnel across every observed automatic plan-day, 2026-09-14 to 2026-09-22:**

| Stage | Count |
|---|---:|
| Plan-days observed (one per symbol per session) | 24 |
| Trigger touched | 11 |
| Opened already beyond the trigger (gap) | 4 |
| Confirmation signals | 0 surviving (QS 09-16 confirmed, refused on spread) |
| Orders | 0 |
| First target under 0.25R at the trigger (planned stop) | 8 |
| First target under 1% from the trigger | 10 |
| Untrusted-data confirmation refusals (events) | 64 |

**What this says.** The desk is not losing money; it is not trading. The binding constraints, in order:
(a) too few candidates per day (six from a full-market scan); (b) plans whose first target sits almost
on top of the trigger, so the 0.25R entry rule refuses them; (c) confirmation windows refused because a
minute in them is a sampled bar; (d) gap opens that breakout mode can never enter.

**Source author (Sean Trades) today.** Not obtainable: x.com returns HTTP 402 to automated readers,
xcancel/nitter mirrors are blocked or down, Thread Reader's newest thread is 2025-12-07 and the YouTube
feed was not readable. No September 21/22 trades or P&L were verified; nothing is inferred.

## 2. Done tonight

1. **Contract ranking reverted in Practice** (`contractPolicy.rankingVersion` `executable_cost_v1` ->
   `legacy`, via the app's journaled preparation endpoint, 22:15 ET). The diverse search stays on.
   Reason: v1 ranks friction as a percent of the debit, which always prefers deep in-the-money contracts;
   the 2026-09-22 arms held NOW 60C (stock ~$140), NVT 110C (~$160), NTNX 60C (~$70). Existing arms and
   positions are unaffected (none are held).
2. **`executable_cost_v2` built** (branch `claude/cartel-cost-v2`): the same cost tuple, applied only
   inside a delta window around the reviewed target (`costDeltaBand`, default 0.15 = |delta| 0.35-0.65);
   contracts outside the window rank after every in-window contract in legacy order. Selection and
   planning paths. Tests reproduce the deep-ITM preference under v1 and its absence under v2.
   Activation after review: set `rankingVersion=executable_cost_v2` in Practice.

## 3. Practice books

Inventory of every sim/shadow book (orders, open positions, live arms, settings references):

- **EM Practice** is referenced by `execution.default_portfolio` and the EM experiment and traded on
  2026-09-22; **EM Experimental** holds 101 live arms. Neither is useless; both stay. They belong to the EM
  desk.
- The two retired books (`Practice (archived 2026-09-07)`, the old $10k `Options Cartel Practice`) are
  already archived with history intact.
- Candidates for the Tips desk to retire (not archived here, because their sources' shadow booking
  writes to them): `Shadow: flow-scan (armed)` (0 orders ever), `Shadow: flow-scan` (last order
  2026-09-01), `Shadow: florida-man` pair (last 2026-09-08/09), `Shadow: tt (armed)` (last 2026-09-11).

## 4. Improvement plan (Cartel), ordered by expected effect on executed trades

Each item is a separately versioned Practice policy with a rollback switch. Live stays unchanged.

| # | Change | Evidence | Measure of success | Status |
|---|---|---|---|---|
| P1 | Cost ranking v2 (delta-bounded) | Deep-ITM arms 2026-09-22 | Arms stay within |delta| 0.35-0.65; friction recorded vs legacy | Built, PR open |
| P2 | Candidate supply: setup-family calibration (brief F5) - compare the legacy 0.8 dry-up rule with a declared non-increasing-volume rule and setup-specific windows on equal snapshots | 6 candidates/day; NTAP excluded only by 0.916 vs 0.8 | More qualified plans per day at unchanged screen gates, every changed rule named | Next |
| P3 | Arm-quality gate: do not arm a plan whose first target is under 0.5R or 1% from the trigger at the planned stop (never skip the nearest resistance to manufacture room) | 8/24 plans under 0.25R, 10/24 under 1% | Share of armed plans that can pass the entry target rule | Next, Practice knob |
| P4 | Data trust: extend verified-interval repair and native-aggregate baselines (brief F7) | 64 untrusted-confirmation refusals | Untrusted refusals per plan-day, without admitting sampled bars as evidence | Next |
| P5 | Gap-open handling: Practice retest variant when the session opens beyond the trigger (S12: never chase a gap; require a completed retest) | 4/24 gap opens (BBY held above trigger all morning on 09-22) | Retest confirmations on gap days, against the matched breakout control | Needs design |
| P6 | 5-minute cadence activation (built, PR #246) | NTNX 09-21 5m 2.51x vs 15m 0.93x | Executed 5m entries vs the 15m control | Blocked on lifting the research-panel 15m-only exclusion |
| P7 | Lab underlying-quote timestamp mismatch (SIP quote time after observation time) | 09-21 shadow evidence | Lab observations become usable | Investigate with receipt-time evidence |

Not recommended: lowering the 1.5x volume multiple or the 20% spread limit on one day's evidence;
widening stops or skipping resistance to raise R; using bigger size to make results look better.

## 5. Activation order and rollback

1. Tonight: legacy ranking in Practice (done). 2. After review of `claude/cartel-cost-v2`: deploy through
the guarded procedure, then `rankingVersion=executable_cost_v2`. 3. P3 and P2 as Practice knobs, each with
a before/after count on the same preparation. 4. P6 after the research panels accept 5m plans.
Rollback of any step is a settings change back to the prior version; records and policy ids stay.

## 6. What the next EOD must answer

Did more plans reach a confirmation, did any confirmation reach an order, and what did the executed
trades earn after fees? A healthy app with zero trades is not progress.
