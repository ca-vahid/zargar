# Recent bottlenecks reconstructed from runtime records (2026-09-14 → 2026-09-17), revision 2

Read-only reconstruction from the runtime database (`zargar` on 127.0.0.1:5433) with
`python -m zargar.tools.cartel_evidence` (README.md has the exact commands). Revision 2
(2026-09-18) incorporates the reviewer's corrections: attribution by identity, production's
crossing-state rule, exchange-calendar sessions, explicit partial evidence on data refusals, the
supported wording on contract feasibility, and the D1 trade-tape probe (§8b). Timestamps are UTC
unless marked ET. Practice book `0b48ed48de2f4030b49942b52858356d` ("Options Cartel Practice",
started $10,000, now $9,938.87, flat).

Reading rules:

- **First blocking gate** = the earliest gate in FUNNEL.md that stopped the candidate.
  **Independent blockers** = later gates that would still have stopped it, judged on records
  available at that time.
- Structural R = (first target − trigger) / (trigger − reviewed invalidation), from the plan
  snapshot (planning basis). Executable R = (first target − confirmation close) / (confirmation
  close − actual stop), from the signal record. Option dollar risk = full debit × quantity. The
  three are never substituted for one another.
- "What price did afterwards" is context only; nothing here is a profitability claim.
- **Journaled decisions are authoritative** for what happened. Two tapes exist beside them: the
  **final arm tape** (`technique_armed.state.minutes` as last saved, with the arm's final
  `observeAfter`) and the **stored tape** (`bars` as it stands now, revised after the fact, no
  receipt times). `replay` runs `read_entry` over each as a consistency check; neither is a
  decision-time reconstruction, because per-decision input values, availability times and
  cutoffs were not persisted. Bucket tables from the stored tape are descriptive.

## 1. Session funnels

| Session (prep run) | Direction | Discovered | Evaluated | Qualifying | Checked (of 25) | Armed | Awaiting contract | Coverage-blocked | Data errors | Not reached |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-16 (`ed6d9da2`, 02:26–02:42Z) | short (strict) | 3,066 | 3,062 | 29 | 18 | 5 | 3 | 10 | 4 | 11 |
| 2026-09-17 (`cee03dd7`, 01:11–01:39Z) | short (strict) | 3,059 | 3,056 | 13 | 13 | 1 | 2 | 10 | 3 | 0 |
| 2026-09-17 pre-open resume (`bc78bc51`, 13:23Z, attempt 3 of 3) | short | 3,059 | 3,058 | 13 | 10 | 0 | 0 | 10 | 1 | — |

Both were **bearish sessions**: SPY and QQQ closed below their 8/21/50 EMAs on 09-15 and 09-16,
so strict alignment chose `short` and every candidate was a put candidate. This is the primary
preparation pool, not the additional structural-short research proxy (zero candidates). Market
direction was not a blocker on either day.

Capacity semantics (corrected): the worker checks candidates in ranked order up to 25 and stops
when *occupied* arms and held positions reach `focus_count` (5). Pending `awaiting_contract`
items do not occupy slots; they consume the 25-candidate checking budget and pending-watcher
work. The 11 "not reached" on 09-16 were ranked below the 18 checked when five arms existed.

09-16 armed: APTV, QS, QUBT, HIMS, AAP. QS signalled and was refused on spread (§3); APTV never
met volume (§6); HIMS one `watch_only` (volume 1.14× at 15:15 ET); QUBT no crossing; AAP twelve
`untrusted_confirmation` decisions (26 sampled minutes in its tape) and no crossing recorded.
09-17 armed: APTV only (§7).

## 2. APA — the only filled trade (plan `e30a2db9…`, 2026-09-14)

| When (UTC) | Record | What it says |
|---|---|---|
| 09-13 02:28:25 | plan run | `inside_day` long, trigger 46.10, invalidation 43.94, targets 50.00 / 54.96 / 60.43 (Fibonacci anchors, engineering). Structural risk 2.16, room 3.90 (8.46%), **structural R 1.80**. |
| 09-13 02:28:26 | armed | auto, APA261016C00045000 (Oct-16 $45 call), budget $500, risk 10%. |
| 09-14 00:52:17 | `execution_settings_reviewed` | legacy-arm limit review applied; contract/targets retained. |
| 09-14 13:45:00.43 | `entry_decision` triggered (bucket end 13:45:00, journaled +0.4 s) | 09:30–09:45 bucket: open 45.74, low **45.56**, close 46.235, volume 527,434 = **1.97×** slot baseline, close location 0.92. Stop = session extreme 45.56 → risk 0.675 (1.46%). **Executable R 5.6.** |
| 13:45:00.604 | preflight | passed; qty 1 at ask 3.30 (bid 3.15, spread $0.15 = $15 for one contract, 4.7%), delta 0.62; budget bound (500/330 → 1) before the risk bound (3). Option dollar risk $330. |
| 13:45:00.777 → :02.750 | order a152c05e (tag `cartel_run:e30a2db9…`) | BUY 1 LMT 3.30, filled 3.30, fee 1.04. Adopted as `cartel-3c3d11e5…` (`ManagedPositionAdopted` 13:45:02.88), `app_managed`; one contract → legacy allocation → **no trim rung, no breakeven move**. |
| 09-14 16:50:03 → :25 | exit (order 29b89a2c, from the position's exit record) | 12:45–13:00 ET bucket low 45.43 crossed the 45.56 stop; MKT sell filled 2.7095, fee 1.04. **Net −$61.13.** |

Attribution in revision 2 is by identity: the entry order carries the plan tag, the position id
comes from the arm's adoption record, the exit order id from the position's exit record, and all
events are read by those aggregate ids (39 events; the prior symbol-prefix match is gone).

Chain: entry gate passed → filled → protective stop (the first 15 minutes' low) hit 3 h later.
Context, not a claim: APA closed 09-14 at 45.03, 47.41 on 09-15, 44.79 on 09-16. The reviewed
invalidation (43.94) would have survived 09-14/15 and been deep under water on 09-16; the
source's daily-candle-low stop would have been 44.82, knowable only at the close. No alternative
is shown better by this case. What the case establishes: the chain works end to end; a $500
budget produced one contract, which the exit policy cannot trim; the session-extreme stop taken
at the first bucket is ~1.5% on an ADR > 3% stock (TRADING-RULES Q2, open). APA is an
`inside_day` plan with Fibonacci targets: a **legacy execution control**, not a Lane A example.

## 3. QS — stock confirmed, no entry (plan `e2e12438…`, 2026-09-16)

| When (UTC) | Record | What it says |
|---|---|---|
| 09-16 02:42:13 | plan + armed | `ma_pullback` short, trigger 4.98, invalidation 5.26, targets 4.81 / 4.77 / 4.38. Structural risk 0.28, room 0.17 (3.41%), **structural R 0.61**. Contract QS261120P00007000 from chain evidence at 1.98/2.40 (19.2%, OI 3,790, delta −0.77); also eligible then: Nov-20 $8 put (2.93/3.15, 7.2%) and $9 put (3.75/4.25, 12.5%). |
| 18:15:00.20 (bucket end 18:15) | `watch_only` | 14:00–14:15 ET bucket crossed (close 4.955), volume **3.06×**, first-target R 0.73, close location **0.61 < 0.70** → refused. |
| 19:00:01.42 (bucket end 19:00) | **triggered** | 14:45–15:00 ET bucket: close 4.94, volume 702,616 = 3.06×, close location 0.88. Stop = session high 5.155, risk 0.215, **executable R 0.60**. Signal consumed. |
| 19:00:02.6 / 19:00:30.8 / 19:01:30.8 | preflight ×3 | every check passed except **`entry_contract_spread`**: bid 1.86 / ask 2.39 = **$0.53 = $53 per contract, $106 for the 2-contract sizing** (24.9% of mid) vs the saved 20%. RiskGate's own check: "24.9% exceeds 20% (limit order, warning only)". Option dollar risk would have been $478. |
| 19:02:30 | `signal_expired` | 120 s signal age → `waiting`, `observeAfter` = now. |
| 15:15 → 15:45 ET buckets | no new crossing | closes 4.92 / 4.92 / 4.955 (already below the trigger); the closing bucket cannot start an entry. |
| 20:00:01 | expired | preparation `validUntil` = 09-16 close. |

What `replay` shows (revision 3): the journaled decisions above are authoritative. The
**final-arm-tape replay** (the arm's last saved minutes with its final `observeAfter` = 19:42Z,
set when the signal expired) returns only `entry_window_closed` — it suppresses the 18:15 and
19:00 decisions and is therefore not a reconstruction of what the observer saw. The
**stored-tape replay** reproduces the three decision kinds at the same bucket ends, but with
different values: signal 3.08× / 0.99 against the live 3.06× / 0.88, because the stored bars were
revised after the decision — 379 of 390 minutes differ in price or volume from the arm's saved
minutes (366 in volume; e.g. 09:30 ET live volume 116,007 vs stored 172,764) while every source
label is identical. Zero label differences does not mean identical inputs. Exact reconstruction
needs per-decision input values, availability times and cutoffs, which this plan did not persist.

Recorded quotes (8,078 observations): spread **5.7%** ($0.12) from 10:15 ET to ~13:45 ET,
then 24.9% ($0.53) from ~13:47 ET to the close with changing sizes (bid 55–3,745), so a live
two-sided market. Between 14:56 ET and the close **0 of 463** observations were within 20%.

First blocker: the saved 20% spread limit at final submission. Independent blockers: none in the
preflight record. Bounds on "recovery": the spread-only reselection merged at 2026-09-17 01:18Z
(PR #189), after the refusal; no `contract_reselection` action exists on the plan; whether an
alternative within the saved limits existed at 15:00 ET is unknown (the two other eligible
contracts were not quoted at signal time). Context: QS closed 09-16 at 5.015, above the trigger.

## 4. TTWO — never armed (plan `341d9773…`, 2026-09-17)

| When (UTC) | Record | What it says |
|---|---|---|
| 09-17 01:39:41 | plan (nightly prep `cee03dd7`; inputs as of 01:11:55Z) | `ma_pullback` short, trigger 210.72, invalidation 215.00, targets 209.51 / 207.91 / 206.45. Structural risk 4.28, room 1.21 (**0.57%**), **structural R 0.28**. Ranked second of three. |
| 01:39:41 | `awaiting_contract` | **No contract in the inspected snapshot passed all configured limits** (5 expiries): lowest otherwise-eligible ask $8.20 vs effective cap $5.00; the cheaper Oct-16 $200 put (ask 4.20) was rejected for **spread**, not premium or delta (floor 0.25). |
| 12:46 – 13:53Z | pending watcher (retryable) | re-checked every ~60 s; still 0 eligible (lowest 7.80). |
| 13:30–13:45Z (09:30–09:45 ET) | stored tape | opened 212.50, bucket low 210.205, close 210.34: crossed, close location 0.96, volume 159,086 = **1.01×** slot-0 baseline (157,896). `replay` (stored tape, no decision-time tape exists): `watch_only`, "Breakout volume is below the snapshotted confirmation threshold", R 0.27. |
| 13:56:07Z (09:56 ET) | `target_passed` (terminal), readiness checked at 13:56:07Z | latest completed minute closed below the first target 209.51 (the 10:00 ET bucket low was 208.77). Pending item retired. |
| 20:00 | — | plan expired with the session; expiry is not the cause of the miss. |

First blocker: contract feasibility — no contract passing all saved limits in the inspected
snapshots (premium and spread limits between them). Independent blockers, had a contract
existed: the only crossing bucket failed the 1.5× volume rule (1.01×, from the stored tape,
which for TTWO has 384 exchange and 6 sampled-only minutes); the first target was 0.57% away and
passed 26 minutes into the session. Removing the premium cap alone recovers nothing here.

## 5. PWR — never armed (plans `cd492b15…` 09-16 flag, `9be071fc…` 09-17 wedge)

| When (UTC) | Record | What it says |
|---|---|---|
| 09-16 02:42:30 | plan `cd492b15` | `flag` short; no contract passing all limits: lowest otherwise-eligible ask **$43.10** vs cap $5.00; sub-$5 candidates failed delta/spread/OI. Expired with 09-16. |
| 09-17 01:39:51 | plan `9be071fc` | `wedge` short, trigger 597.88, invalidation **653.87**, targets 593.70 / 580.13 / 558.91. Structural risk 55.99 (9.4%), room 4.18 (0.70%), **structural R 0.075**. Passed review: the only planning floor is 0.5% first-target distance. |
| 01:39:51 → 15:44Z | `awaiting_contract` | 0 eligible; lowest otherwise-eligible ask 24.4 → 46.0 → 38.9 through the day. |
| 15:45:04Z (11:45 ET) | readiness | "Missing 1 completed session minutes since the open" — first live-tape gap. |
| 15:46:05Z → 19:43Z | readiness | "N session minutes lack verified provenance" rising 1 → 17: Yahoo-sampled minutes where no Alpaca bar arrived. **D1 probe (§8b): all 17 had SIP trades, all odd-lot-only** — they were not no-trade minutes. |
| 19:30:37Z | readiness | "No supported confirmation period remains for a newly armed plan today." |
| 20:00:42Z | expired | — |
| stored tape | — | open 637.61, low 607.45: never within 9 points of the 597.88 trigger. |

Chronology confirmed by the reviewer: contract refusal first (01:39:51Z), missing-minute
readiness 15:45:04Z, unverified provenance 15:46:05Z. Independent blockers: price never reached
the trigger; from 11:46 ET the provenance rule would have refused arming; structural R 0.075.

## 6. APTV 2026-09-16 — armed, crossed, refused on volume and data (plan `d4ba82cd…`)

`base` short, trigger 43.55, invalidation 48.24, Fibonacci targets 35.54 / 25.34 / 14.09
(room 18.4%, structural R 1.71). Contract APTV261016P00045000 (2.5/2.9 = $0.40, 14.8%, OI 118).

The journaled decisions are authoritative. The final-arm-tape replay (386 exchange + 4 sampled
minutes) reproduces the three `untrusted_confirmation` kinds and the close, but not the 19:00
`watch_only` (its final `observeAfter` postdates it); the stored-tape replay reproduces the
`watch_only` with the same 1.32× / 1.00 while 386 of 390 minutes differ in price or volume from
the arm's saved minutes (labels identical). Known partial evidence for the data refusals, from
the tape:

| Bucket end (ET) | Decision | Known partial evidence (from the tape; crossing/volume ratio/close location/session extreme not computed) |
|---|---|---|
| 12:15 | `untrusted_confirmation` | untrusted minute 12:06; partial high 44.05 / low 43.92 / last close 44.04; partial volume 47,052 vs slot baseline 68,451 |
| 13:30 | `untrusted_confirmation` | untrusted 13:15; high 43.865 / low 43.81 / last 43.845; 49,539 vs 66,337 |
| 14:00 | `untrusted_confirmation` | untrusted 13:48, 13:57; high 43.86 / low 43.76 / last 43.77; 66,734 vs 72,260 |
| 15:00 | `watch_only` | crossed (close 43.28, location 1.00), volume 105,190 = **1.32×** < 1.5×; "cannot determine the session extreme with missing minutes" |
| 15:30 | `missing_bucket` then `untrusted_confirmation` | last close 43.20; no new crossing possible (already below the trigger) |

The partial lows of the three untrusted buckets (43.92, 43.81, 43.76) sit above the 43.55
trigger, so those refusals did not hide a crossing; this is a statement about the known minutes,
not a judged crossing. First blocker on the one real crossing: the 1.5× volume rule (1.32×).
Independent: the session-extreme stop was undeterminable because 4 minutes were sampled.
Context: APTV closed 43.35 and opened 09-17 at 44.23. Journal latency for this plan's decisions
ran 0.4 s to **60.1 s** after the bucket end (the 19:30Z bucket), within the 120 s acceptance.

## 7. APTV 2026-09-17 — armed, no setup occurred (plan `8ba79338…`)

`breakout_retest` short, trigger 42.99, invalidation 44.19, structural R 5.16 (Fibonacci). Armed
01:39Z; as an existing arm it was **retained** by every later preparation attempt and counted as
one occupied slot of five (capacity counts arms and positions). Stored tape: open 44.23, low
**43.32**, close 43.625 — the trigger was never touched. One decision: `entry_window_closed`.
No gate was involved; the setup did not happen.

## 8. The coverage gate: mechanism and numbers

Ten of thirteen 09-17 candidates (and ten of 29 on 09-16) were `plan_blocked` by "Opening and
broad coverage requires the first hour and 80% of pre-close windows". Mechanism
(`prepare.py:build_volume_baseline`, `preparation_readiness.py:baseline_coverage`,
`preparation.py:551-556`):

1. The 20-session 1m history is a live fetch from Alpaca (`feed=sip`, `adjustment=raw`);
   provenance is recorded per cache row with `noTradeIntervalsVerified: false`.
2. A 15-minute slot contributes a sample for a session **only if all 15 constituent minutes are
   present**; a slot is usable only with ≥5 samples and a positive median.
3. `opening_and_broad` requires slots 0–3 usable and ≥20 of the 25 pre-close slots usable.

Measured on the blocked names (09-17 rows; samples per opening slot 0–3; sessions per the
exchange calendar):

| Symbol | Usable slots | Opening-slot samples | Alpaca minutes returned per session (20 sessions) | Minute-volume ÷ Yahoo daily volume (descriptive) |
|---|---|---|---|---|
| PLAB | 18/25 | 9, 6, 9, 8 | 286–390 (median ≈ 335) | 41–91%, median ≈ 76% |
| LZB | 3/25 | 3, 2, 3, 3 | 268–383 (≈ 305) | 64–91%, ≈ 75% |
| SSYS | 0/25 | 1, 1, –, – | 187–340 (≈ 240) | 65–92%, ≈ 82% |
| GNRC | 3/25 | 5, 4, 3, 3 | 247–378 (≈ 305) | 34–92%, ≈ 79% |
| TTWO (not blocked) | 25/25 | 20, 19, 18, 16 | 354–390 (≈ 386) | 68–92%, ≈ 79% |

What follows, and what is only a hypothesis:

- The all-15-minutes rule turns any absent minute into a discarded sample. Illustratively, if
  absences were independent with per-minute probability p, a slot would be complete with
  probability (1−p)^15 — 3.5% at p ≈ 20% — so 20 sessions would rarely yield 5 samples. Real
  absences cluster (midday, thin names), so this is an illustration, not a model. All 20
  sessions were returned in every case; this is a requirement × provider-semantics interaction,
  not a shortage of history.
- **Hypothesis, not established:** the minute-volume/daily-volume ratio is similar (~75–80%) for
  liquid TTWO and for the thin names, which is consistent with the shortfall being systematic to
  the provider pair rather than to absent minutes. That comparison mixes two providers' volume
  bases and unmatched sessions; it does not prove truncation absent, and it does not show the
  relative-volume ratio is unaffected. Matched-provider, matched-session analysis is required.

### 8b. D1 probe: what the absent minutes actually contained (revision 3, boundary-enforced)

Read-only SIP trade-tape probe (`alpaca-minutes`, tool version 2, feed `sip`, bar pagination
complete on every run, trades filtered locally to `start <= t < end` because the provider's
`end` parameter is inclusive, per-interval verification times, credential-free artifacts in
`evidence/`). Every absent minute of each session was probed, so none is `unknown`.

| Symbol, session | SIP 1Min bars | Absent | Probed | `verified_no_trades` | `trades_without_bar` | Odd-lot condition on every trade | All sizes < 100 | Shares inside probed minutes | Trades dropped at the boundary | Run (UTC) |
|---|---|---|---|---|---|---|---|---|---|---|
| PLAB 2026-09-16 | 346/390 | 44 | 44 | 0 | **44** | 32 of 44 | 32 of 44 | 9,334 | 0 | 2026-09-18 01:35:46–51 |
| LZB 2026-09-16 | 335/390 | 55 | 55 | 0 | **55** | 51 of 55 | 51 of 55 | 11,264 | 0 | 01:35:53–59 |
| PWR 2026-09-17 | 373/390 | 17 | 17 | 0 | **17** | 15 of 17 | 17 of 17 | 5,428 | 0 | 01:36:00–02 |

Condition counts across the probed trades: PLAB `@` 829, `I` 816, `4` 181, `F` 41, `W` 13; LZB
` ` 840, `I` 836, `4` 144, `F` 62, `B` 4; PWR ` ` 717, `I` 715, `F` 62, `4` 52, `B` 2. The
revision-2 counts (40/30/17 probed) stand after boundary enforcement: zero trades fell on the
[start, end) boundary in any probed minute, and the classification is now by the reported
odd-lot condition (`I`) rather than by size, with size statistics kept separately (the two
measures agree except for 2 PWR minutes with a sub-100 trade lacking the `I` flag and 12 PLAB
minutes where a round-lot trade carried another condition).

Every probed absent minute had trades. The provider's minute bar was absent because no trade in
the minute was eligible for its bar aggregation, as its documentation describes — not because
nothing traded. Consequences, recorded in PROPOSAL.md D1: an absent minute is
`trades_without_bar` until a trade query says otherwise; it is never relabelled an ordinary
exchange bar; volume and price eligibility differ (odd-lot trades can carry volume without
setting OHLC), so any alternative aggregation is a separate versioned calculation evaluated
offline first, with no double counting and no change to execution behaviour or stop coverage.
The "count absent minutes as zero volume" idea from revision 1 is withdrawn.

The live tape shows the same thing from the other side: PWR's 17 "unverified provenance" minutes
on 09-17 are exactly the 17 minutes with odd-lot-only trades and no SIP bar; Yahoo's sampled
volume deltas for them (307, 214, 898 shares …) are consistent in magnitude with the probe.

### 8c. Stored bars are revised after decisions (finding from the replay comparison)

For every armed plan compared, the arm's last saved minutes and the current `bars` rows differ in
price or volume in most minutes with identical source labels: QS 379/390 (366 volume), APTV
09-16 386/390 (375 volume), APA 15/15. The live observer judged streaming exchange bars; the
stored rows were later refreshed (exchange-over-exchange merge, PLATFORM-RULES F75) with
different, mostly higher, volumes (QS 09:30 ET: 116,007 live vs 172,764 stored). So the
stored tape can only ever be a consistency check for a decision, and the same-slot baseline
(built from the provider's historical bars) and the live confirmation (streaming bars) are not
on one volume basis. This is a measurement, not yet a defect classification; the offline
`volume_eligibility_v1` comparison in PROPOSAL D1 is where it gets quantified.

## 9. Journal latency of entry decisions (bounded diagnostic)

`latency --since 2026-09-08`: 84 Cartel entry decisions journaled; delay from bucket end to
journal p50 1.4 s, p90 6.8 s, max **60.1 s** (APTV 09-16 19:30Z), none over the 120 s
acceptance window. Bars dropped by the observer for age produce no decision and are therefore
invisible here; D4 proposes counting them.

## 10. The four days in one table

| Case | Role | First blocking gate | Independent blockers | Would removing the first gate alone have produced an entry? |
|---|---|---|---|---|
| APA 09-14 | legacy control | none — filled | — | n/a; loss on the first-bucket session-extreme stop |
| QS 09-16 | diagnostics | saved 20% spread ($0.53, $106 for 2) at final submission | none recorded | possibly, at that spread; reselection not deployed; context negative |
| TTWO 09-17 | diagnostics | no contract passing all saved limits (premium and spread) | volume 1.01× on the only crossing; target 0.57% away, passed by 09:56 ET | no |
| PWR 09-16/17 | diagnostics | no contract passing all saved limits | trigger never reached; provenance from 11:46 ET (odd-lot minutes); structural R 0.075 | no |
| APTV 09-16 | diagnostics | volume 1.32× on the only crossing | session-extreme stop undeterminable (sampled minutes) | no |
| APTV 09-17 | diagnostics | no setup (trigger never reached) | — | n/a |
| 10 × coverage-blocked (09-17) | diagnostics | baseline sample rule × provider minute semantics (odd-lot minutes have no bar) | unknown — never planned; thin names would also hit live provenance | unknown until D1 defines the classes' effects |
