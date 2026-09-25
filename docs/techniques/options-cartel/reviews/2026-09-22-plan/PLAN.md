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

| # | Change | Setting (Practice) | Evidence | Status (0.8.33) |
|---|---|---|---|---|
| P1 | Cost ranking bounded to the reviewed delta window | `contractPolicy.rankingVersion=executable_cost_v2` (`costDeltaBand` 0.15) | Deep-ITM arms 2026-09-22 | Built and tested; off until chosen (Practice runs `legacy` since 22:15 ET) |
| P2 | Volume dry-up read as non-increasing base volume instead of 0.8x | `setups.dry_up_rule=non_increasing_v1` | NTAP excluded only by 0.916 vs 0.8 | Built; the check records the rule and threshold it used |
| P3 | Do not arm a plan whose first target is under N R from the trigger at the planned stop | `minArmTargetR` (0 = off; proposed 0.5) | 8/24 plans under 0.25R | Built; never skips resistance, the plan is simply not armed |
| P4 | Untrusted confirmations | none | Every untrusted window on 09-21/22 had its sampled minute within the bucket's last three minutes, before any non-emission proof can exist (proofs need minute+3 min). The kernel already drops sampled prints in proven minutes. | Not built: the only remedy is deciding after the candle closes, which the non-retroactivity rule forbids. Needs a design decision (a declared, fixed decision delay versus accepting the loss). |
| P5 | Enter a gap-and-hold session on a completed retest candle | `entry.gap_policy=retest_v1` | 4/24 gap opens (BBY 09-22) | Built; volume, close quality, chase, stop and target rules unchanged |
| P6 | Research panels keep scoring when the 5m pilot runs | automatic | Panels refused non-15m plans | Built: 5m candidates are scored on the labelled 15m research basis; the 5m execution is compared by the matched control |
| P7 | Lab stock-quote freshness judged on receipt time | automatic | Host clock ~9 s behind venue time made fresh SIP prints look future-dated | Built: receipt time decides freshness; venue time kept and bounded to 30 s ahead of receipt |
| P8 | 5-minute cadence activation | `entryCadence=breakout_5m_v1` + `entry.timeframe_minutes=5` | NTNX 09-21 5m 2.51x vs 15m 0.93x | Built (PR #246); unblocked by P6 |

Not recommended: lowering the 1.5x volume multiple or the 20% spread limit on one day's evidence;
widening stops or skipping resistance to raise R; using bigger size to make results look better.

## 5. Activation order and rollback

Every switch above defaults to the legacy behaviour; merging and deploying 0.8.33 changes nothing
until a setting is chosen. Recommended Practice activation after deployment, one preparation apart so
each effect is attributable:

1. `rankingVersion=executable_cost_v2` (contract quality; no effect on trade count).
2. `minArmTargetR=0.5` and `entry.gap_policy=retest_v1` (entry paths and arm quality).
3. `setups.dry_up_rule=non_increasing_v1` (more candidates; compare the shortlist before/after).
4. `entryCadence=breakout_5m_v1` with `entry.timeframe_minutes=5` (the 15m matched control records the comparison).

Rollback of any step is a settings change back to the prior value; records and policy ids stay, held
positions keep the policy they entered under.

## 6. What the next EOD must answer

Did more plans reach a confirmation, did any confirmation reach an order, and what did the executed
trades earn after fees? A healthy app with zero trades is not progress.

## 7. Activation record

| When (ET) | Change | Why |
|---|---|---|
| 2026-09-22 22:15 | `rankingVersion` v1 -> `legacy` | v1 picked deep in-the-money contracts |
| 2026-09-23 13:52 | `nativeDailyBatch=true` | Yahoo daily omitted 09-22; benchmark waited all day |
| 2026-09-23 20:26 | `nativeDailyBatch=false`; `rankingVersion=executable_cost_v2`; `entry.gap_policy=retest_v1`; `setups.dry_up_rule=non_increasing_v1` | Shared daily path is now Alpaca-first and complete by the evening; three switches act at separate funnel stages |
| pending | `minArmTargetR=0.5`; `entryCadence=breakout_5m_v1` | After the first sessions under the switches above |
