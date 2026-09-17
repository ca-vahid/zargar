# Recent bottlenecks reconstructed from runtime records (2026-09-14 → 2026-09-17)

Read-only reconstruction, 2026-09-17 evening, from the runtime database (`zargar` on
127.0.0.1:5433) with `python -m zargar.tools.cartel_evidence` (see README.md for the exact
commands). Timestamps are UTC unless marked ET (EDT = UTC−4). Practice book
`0b48ed48de2f4030b49942b52858356d` ("Options Cartel Practice", started $10,000, now $9,938.87,
flat). No document in the repository recorded the 09-16/09-17 findings before this one.

Reading rules used throughout:

- **First blocking gate** = the earliest gate in the executable funnel (FUNNEL.md) that stopped
  the candidate. **Independent blockers** = later gates that would still have stopped it had
  the first one passed, judged on records available at that time.
- Structural R = (first target − trigger) / (trigger − reviewed invalidation), from the plan
  snapshot. Executable R = (first target − confirmation close) / (confirmation close − actual
  stop), from the signal record. They are reported separately and never substituted.
- "What price did afterwards" is context only; nothing here is a profitability claim.
- Bucket tables come from the stored 1m tape *as it exists now*. A minute that is `exchange`
  now may have been `sampled` or absent at decision time; where that matters it is stated.

## 1. Session funnels

| Session (prep run) | Direction | Discovered | Evaluated | Qualifying | Checked | Armed | Awaiting contract | Coverage-blocked | Data errors | Not reached |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-16 (`ed6d9da2`, 02:26–02:42Z) | short (strict) | 3,066 | 3,062 | 29 | 18 of 25 cap | 5 | 3 | 10 | 4 | 11 |
| 2026-09-17 (`cee03dd7`, 01:11–01:39Z) | short (strict) | 3,059 | 3,056 | 13 | 13 | 1 | 2 | 10 | 3 | 0 |
| 2026-09-17 pre-open resume (`bc78bc51`, 13:23Z, attempt 3 of 3) | short | 3,059 | 3,058 | 13 | 10 | 0 | 0 | 10 | 1 | — |

Both sessions were **bearish sessions**: SPY and QQQ closed below their 8/21/50 EMAs on 09-15
and 09-16, so strict alignment chose `short` and every candidate was a put candidate. This is
the primary preparation pool, not the additional structural-short research proxy (which
counted zero candidates). Market direction was not a blocker on either day.

09-16 armed: APTV, QS, QUBT, HIMS, AAP. Outcomes: QS signalled and was refused on spread
(§3); APTV never met volume (§6); HIMS one `watch_only` (volume 1.14x at 15:15 ET); QUBT no
crossing; AAP twelve `untrusted_confirmation` decisions (26 sampled minutes in its tape) and no
crossing recorded. 09-17 armed: APTV only (§7).

The 11 "not reached" candidates on 09-16 (TOST, DNUT, CSTM, ACHC, STLD, SSYS, ORKA, SKY, RERE,
XENE, ATHM) were ranked below the 18 checked and never had a baseline or contract looked at:
the worker stops when `focus_count` (5) arms are filled. On 09-17 all 13 were checked.

## 2. APA — the only filled trade (plan `e30a2db9…`, 2026-09-14)

| When (UTC) | Record | What it says |
|---|---|---|
| 09-13 02:28:25 | plan run | `inside_day` long, trigger 46.10, invalidation 43.94, targets 50.00 / 54.96 / 60.43 (Fibonacci anchors, engineering). Structural risk 2.16, first-target room 3.90 (8.46%), **structural R 1.80**. |
| 09-13 02:28:26 | armed | auto, contract APA261016C00045000 (Oct-16 $45 call), budget $500, risk 10%. |
| 09-14 00:52:17 | `execution_settings_reviewed` | legacy-arm limit review (Sept 13 correction) applied; contract/targets retained. |
| 09-14 13:45:00 (09:45 ET) | `entry_decision` triggered | 09:30–09:45 bucket: open 45.74, low **45.56**, close 46.235, volume 527,434 = **1.97x** slot baseline, close location 0.92. Stop = session extreme 45.56 → risk 0.675 (1.46%). **Executable R to first target 5.6.** |
| 13:45:00.604 | preflight | passed; qty 1 at ask 3.30 (bid 3.15, delta 0.62); budget bound (500/330 → 1) before the 10% risk bound (3). |
| 13:45:00.777 → :02.750 | order a152c05e | BUY 1 LMT 3.30, filled 3.30, fee 1.04. Adopted as managed position `cartel-3c3d11e5…`, `app_managed` overnight, one contract → legacy allocation → **no trim rung, no breakeven move possible** (exits.py: one unit exits only on stop / EMA50 daily close / DTE floor). |
| 09-14 16:50:03 → :24 (12:50 ET) | exit | 12:45–13:00 bucket low 45.43 crossed the 45.56 stop; MKT sell filled 2.7095, fee 1.04. **Net −$61.13.** |

Chain: entry gate passed → filled → protective stop (the first 15 minutes' low) hit 3 h later.
Context, not a claim: APA closed 09-14 at 45.03 (below the trigger, so the daily breakout
failed on the day), 47.41 on 09-15, 44.79 on 09-16. Under the reviewed invalidation (43.94)
the position would have survived 09-14 and 09-15 and been well under water on 09-16; under
the source's daily-candle-low rule the stop would have been 44.82 (the day's final low, only
knowable at the close). Neither alternative is shown to be better by this one case.

What the case establishes: (1) the entire entry chain works end to end; (2) with a $500
budget the trade was one contract, which the exit policy cannot trim; (3) the
`session_extreme` stop taken at the first bucket is a ~1.5% stop on a stock screened for
ADR > 3%, i.e. inside one day's normal range. That is TRADING-RULES Q2 (intraday breakout-bar
stop vs the daily candle low), still open.

## 3. QS — stock confirmed, no entry (plan `e2e12438…`, 2026-09-16)

| When (UTC) | Record | What it says |
|---|---|---|
| 09-16 02:42:13 | plan + armed | `ma_pullback` short, trigger 4.98, invalidation 5.26, targets 4.81 / 4.77 / 4.38. Structural risk 0.28, room 0.17 (3.41%), **structural R 0.61**. Contract QS261120P00007000 chosen from chain evidence at 1.98/2.40 (spread 19.2%, OI 3,790, delta −0.77); the two other eligible contracts were the Nov-20 $8 put (2.93/3.15, 7.2%) and $9 put (3.75/4.25, 12.5%). |
| 18:15:00 (14:15 ET) | `watch_only` | 14:00–14:15 bucket crossed (close 4.955), volume **3.06x**, first-target R 0.73, but close location **0.61 < 0.70** → refused. |
| 19:00:01 (15:00 ET) | **triggered** | 14:45–15:00 bucket: close 4.94, volume 702,616 = 3.06x, close location 0.88. Stop = session high 5.155, risk 0.215, **executable R 0.60**. Signal consumed, `_fire` scheduled. |
| 19:00:02.6 / 19:00:30.8 / 19:01:30.8 | preflight ×3 | every check passed except **`entry_contract_spread`**: bid 1.86 / ask 2.39 → 24.9% on the mid basis vs the saved 20% limit. Sizing would have been 2 contracts ($478). RiskGate's own spread check reported "24.9% exceeds 20% (limit order, warning only)". |
| 19:02:30 | `signal_expired` | 120 s signal age exceeded → phase back to `waiting`, `observeAfter` = now. |
| 19:15 → 19:45 ET buckets | no new crossing | closes 4.92 / 4.92 / 4.955 stayed below the trigger (no new cross) and the 15:45 bucket cannot start an entry. |
| 20:00:01 | expired | preparation `validUntil` = 09-16 close. |

Recorded quotes for the contract (8,078 observations on the plan): the spread was **5.7%** from
10:15 ET to about 13:45 ET, widened to 24.9% at ~13:47 ET and stayed there to the close with
*changing* sizes (bid size 55–3,745), so it was a live two-sided market, not a frozen feed.
Between 14:56 ET and the close **0 of 463** observations were within 20%.

First blocker: the saved 20% spread limit at final submission. Independent blockers: none in
the preflight record (all other checks passed). Two facts limit what "recovery" would mean:

1. The bounded spread-only reselection (`contract_reselection.py`) **was not running**: it
   merged in PR #189 at 2026-09-17 01:18Z, six hours after the refusal, and no
   `contract_reselection` action exists on the plan. Whether an alternative within the same
   limits existed at 15:00 ET is unknown — the two other contracts eligible at preparation
   time were not quoted at signal time.
2. Outcome context: QS closed 09-16 at 5.015, above the trigger; the 15:00 ET short would
   have ended the day against the position with the 24.9% spread paid on entry. Not a claim
   either way.

## 4. TTWO — never armed (plan `341d9773…`, 2026-09-17)

| When (UTC) | Record | What it says |
|---|---|---|
| 09-17 01:39:41 | plan (nightly prep `cee03dd7`) | `ma_pullback` short, trigger 210.72, invalidation 215.00, targets 209.51 / 207.91 / 206.45. Structural risk 4.28, room 1.21 (**0.57%**), **structural R 0.28**. Ranked second of three (quality ranking: structural R, relative strength, volume). |
| 01:39:41 | `awaiting_contract` | contract audit: 0 eligible in 5 expiries; **lowest otherwise-eligible ask $8.20 vs effective cap $5.00** (budget $500). The only sub-$5 put (Oct-16 $200 @ 4.20) failed the spread limit. |
| 12:46 – 13:53Z | pending watcher | retried every ~60 s: still 0 eligible (lowest 7.80). |
| 13:30–13:45Z (09:30–09:45 ET) | tape | opened 212.50, bucket low 210.205, close 210.34: **crossed** the trigger, close location 0.96, but volume 159,086 = **1.01x** the slot-0 baseline (157,896) — would have been `watch_only` had the plan been armed. |
| 13:56:07Z (09:56 ET) | `target_passed` (terminal) | latest completed minute closed below the first target 209.51 (the 10:00 bucket low was 208.77). Pending item retired. |
| 20:00 | — | plan expired with the session; expiry is not the cause of the miss. |

First blocker: **contract affordability** (a $210 stock's 0.5-delta put at 21–90 DTE cannot
cost ≤ $5; the $500 premium budget, not the spread, is binding). Independent blockers, had a
contract existed: the only crossing bucket failed the 1.5x volume rule (1.01x); the first
target was 0.57% away (structural R 0.28) and was passed 26 minutes into the session. Removing
the premium cap alone recovers nothing here.

## 5. PWR — never armed (plans `cd492b15…` 09-16 flag, `9be071fc…` 09-17 wedge)

| When (UTC) | Record | What it says |
|---|---|---|
| 09-16 02:42:30 | plan `cd492b15` | `flag` short; awaiting contract: lowest otherwise-eligible ask **$43.10** vs cap $5.00; sub-$5 candidates failed delta/spread/OI. Expired with 09-16. |
| 09-17 01:39:51 | plan `9be071fc` | `wedge` short, trigger 597.88, invalidation **653.87**, targets 593.70 / 580.13 / 558.91. Structural risk 55.99 (9.4%), room 4.18 (0.70%), **structural R 0.075**. Passed the review because the only planning floor is 0.5% first-target distance. |
| 01:39:51 → 15:44Z | `awaiting_contract` | 0 eligible; lowest otherwise-eligible ask 24.4 → 46.0 → 38.9 through the day. |
| 15:45:04Z (11:45 ET) | readiness | "Missing 1 completed session minutes since the open" — first live-tape gap. |
| 15:46:05Z → 19:43Z | readiness | "N session minutes lack verified provenance" rising 1 → 17 (Yahoo-sampled minutes where no Alpaca bar arrived; those sampled minutes carry non-zero Yahoo volume deltas, e.g. 11:44 ET 307 sh, 12:02 ET 898 sh — so they are not demonstrably no-trade minutes). |
| 19:30:37Z | readiness | "No supported confirmation period remains for a newly armed plan today." |
| 20:00:42Z | expired | — |
| tape | — | session open 637.61, low 607.45: **never within 9 points of the 597.88 trigger**. |

First blocker: contract affordability (a $620 stock). Independent blockers: price never reached
the trigger; from 11:45 ET the live-tape provenance rule would have refused arming; the
structural geometry (R 0.075) is not a trade anyone would take by the source's ≥1.5:1
checklist (S14). The provenance block is real but was never the binding constraint for PWR.

## 6. APTV 2026-09-16 — armed, crossed, refused on volume and data (plan `d4ba82cd…`)

`base` short, trigger 43.55, invalidation 48.24, Fibonacci targets 35.54 / 25.34 / 14.09
(room 18.4%, structural R 1.71). Contract APTV261016P00045000 (2.5/2.9, 14.8%, OI 118).

| ET bucket | Decision recorded | Tape now (exchange minutes) |
|---|---|---|
| 12:00–12:15, 13:15–13:30, 13:45–14:00 | `untrusted_confirmation` (sampled minutes in the bucket) | none of these buckets crossed the trigger (lows 43.92 / 43.81 / 43.76) — the provenance refusals cost nothing here. |
| 14:45–15:00 | `watch_only`: volume **1.32x** < 1.5x; "cannot determine the session extreme with missing minutes" | crossed (close 43.28, location 1.00), volume 105,190 vs baseline 79,924. |
| 15:00–15:15 | `missing_bucket` then `untrusted_confirmation` | close 43.20 — no new crossing anyway (already below the trigger). |
| 16:00 | expired | — |

First blocker on the one real crossing: the 1.5x volume rule (1.32x). Independent: the
session-extreme stop was undeterminable because 4 of the session's minutes were sampled. Context:
APTV closed 43.35 and opened 09-17 at 44.23 (above the session-extreme stop a 15:00 ET short
would have carried). No claim.

## 7. APTV 2026-09-17 — armed, no setup occurred (plan `8ba79338…`)

`breakout_retest` short, trigger 42.99, invalidation 44.19, structural R 5.16 (Fibonacci
targets). Armed at 01:39Z; retained by every later preparation attempt as `already_managed`
(so it also occupied one of the five focus slots all day). Tape: open 44.23, low **43.32**,
close 43.625 — the trigger was never touched. One decision: `entry_window_closed` at 16:00 ET.
No gate was involved; the setup did not happen.

## 8. The coverage gate: mechanism and numbers

Ten of thirteen 09-17 candidates (and ten of 29 on 09-16) were `plan_blocked` by
"Opening and broad coverage requires the first hour and 80% of pre-close windows". Mechanism
(`prepare.py:build_volume_baseline`, `preparation_readiness.py:baseline_coverage`,
`preparation.py:551-556`):

1. The 20-session 1m history is a live fetch from Alpaca (`feed=sip`, `adjustment=raw`);
   provenance is recorded per cache row with `noTradeIntervalsVerified: false`.
2. A 15-minute slot contributes a sample for a session **only if all 15 constituent minutes
   are present**; a slot is usable only with ≥5 samples and a positive median.
3. `opening_and_broad` requires slots 0–3 usable and ≥20 of the 25 pre-close slots usable.

Measured on the blocked names (09-17 rows; samples per opening slot 0–3):

| Symbol | Usable slots | Opening-slot samples | Alpaca minutes present per session (20 sessions) | Minute-volume ÷ Yahoo daily volume |
|---|---|---|---|---|
| PLAB | 18/25 | 9, 6, 9, 8 | 286–390 (median ≈ 335) | 41–91%, median ≈ 76% |
| LZB | 3/25 | 3, 2, 3, 3 | 268–383 (≈ 305) | 64–91%, ≈ 75% |
| SSYS | 0/25 | 1, 1, –, – | 187–340 (≈ 240) | 65–92%, ≈ 82% |
| GNRC | 3/25 | 5, 4, 3, 3 | 247–378 (≈ 305) | 34–92%, ≈ 79% |
| TTWO (not blocked) | 25/25 | 20, 19, 18, 16 | 354–390 (≈ 386) | 68–92%, ≈ 79% |

Two things follow and one does not:

- The all-15-minutes rule turns any absent minute into a discarded sample. With p absent
  minutes per session the chance a slot is complete is (1−p)^15; at p ≈ 20% (LZB) that is
  3.5%, so 20 sessions yield well under the 5 required samples. This is a **requirement ×
  provider-semantics** interaction, not a shortage of history: all 20 sessions were returned.
- Absent minutes are *not* volume truncation: the minute-volume/daily-volume ratio is the same
  ~75–80% for liquid TTWO (few gaps) as for the thin names (many gaps). The shortfall is
  systematic to the provider pair, not to gaps.
- It does **not** follow that absent minutes are no-trade minutes. The live tape shows Yahoo
  sampled volume in minutes where Alpaca delivered no bar (PWR, PLAB on 09-17). Counting
  absent minutes as zero volume without verification would bias baselines low and make the
  1.5x rule easier to pass. Verification (Alpaca trades for the interval, or a second
  provider) is required before any change here — see PROPOSAL.md D1.

The same mechanism hits the live tape: a minute with no venue bar stays `sampled` and makes
its bucket `untrusted_confirmation` (AAP: 26 sampled minutes, 12 untrusted decisions on 09-16).

## 9. What the four days say, in one table

| Case | First blocking gate | Independent blockers | Would removing the first gate alone have produced an entry? |
|---|---|---|---|
| APA 09-14 | none — filled | — | n/a; loss on the first-bucket session-extreme stop |
| QS 09-16 | saved 20% spread at final submission | none recorded | possibly, at a 24.9% spread; reselection not deployed; outcome context negative |
| TTWO 09-17 | contract affordability ($500 budget vs $210 stock) | volume 1.01x on the only crossing; target 0.57% away, passed by 09:56 ET | no |
| PWR 09-16/17 | contract affordability ($620 stock) | trigger never reached; provenance block from 11:45 ET; structural R 0.075 | no |
| APTV 09-16 | volume 1.32x on the only crossing | session-extreme stop undeterminable (sampled minutes) | no (data), and the crossing still failed volume |
| APTV 09-17 | no setup (price never reached the trigger) | — | n/a |
| 10 × coverage-blocked (09-17) | baseline coverage rule × provider minute gaps | unknown — never planned; several are thin names that would also hit live provenance | unknown until D1 verification |
