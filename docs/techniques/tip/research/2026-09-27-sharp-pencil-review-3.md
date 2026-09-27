# Tips - sharp-pencil review #3 and plan (2026-09-27, after the first week of shares-first)

Follows [review #2](2026-09-24-sharp-pencil-review-and-plan.md) (P1-P13) and the
[five-session report](2026-09-25-five-session-report.md). This review uses the whole Practice record since the book
opened (2026-09-08, $10,000, 14 accounting days), the hold study, the knowledge tables and the model ledger. Nothing
here changes a setting; every item is a proposal with its evidence, its rollback and the decision it needs.

## 1. The scoreboard (Practice book, net of fees, 09-08 .. 09-25)

| | amount |
|---|---:|
| Equity | 10,000.00 -> **9,031.76** |
| Marked change | **-968.24** |
| Realized (fees 133.12 inside; questioned -97.41, repairs -9.16) | -995.39 |
| Model cost (list-price estimate, priced; 22 unpriced + 9 partial runs = lower bound) | 828.41 |
| **Marked after model cost** | **-1,796.65** |

Model cost by stage, whole record: intake reviews $623 (75%), appraisals $150, extraction $24, retros $20, rule audit
$10, digest $1. By weekday last week: $115.65, $100.46, $61.16, $21.71, **$7.40** (Friday, after caching, Opus 5.5
medium, the gate on enforce). **The model bill is no longer the problem; trading is.** At Friday's rate the desk
spends ~$37 a week on models - the break-even bar for trading.

## 2. Where the money went

**By vehicle (completed ideas, net of fees):**

| vehicle | net | note |
|---|---:|---|
| Options, all cohorts | **about -1,030** | 0-4 DTE -399 (1 winner in 8); 30+ DTE mixed (ab +227 but -210 questioned; florida-man -505 on one idea) |
| Shares, all cohorts | **about +145** | common-stock +186 on 5; neal +7; ab -52 (2 of 3 still open); jon-and-kian +3 |

**By how a position ended (whole record):**

| exit | positions | net | winners |
|---|---:|---:|---:|
| Author's exit mirrored (analyst, then P2 from 09-25) | 8 | **+417.40** | 6 |
| Target / premium target | 2 | +217.77 | 1 |
| Stop in the first seconds of a session | 6 | **-829.85** | 0 |
| Premium stop or bleed, in session | 3 | -269.71 | 0 |
| Underlying stop | 5 | -212.72 | 1 |

**By source, realized minus model cost (whole record):** common-stock -7 (shares +186, one option -159); jon-and-kian
-22; neal -24; giul-heatseeker -40 (0 fills); ab -144; tt -113; eva -255 (1 fill in 14 sessions, $83 of model cost);
florida-man -507 (one option); muggzone -561 ($335 of model cost). No source has earned anything yet (P12 bar: 10
completed ideas, net positive after model cost, per vehicle).

**Overnight (hold study, 86 fresh preclose -> next-open pairs):** Practice shares +1.05% average (12/24 up, +$286),
Practice options +12.2% on the mid (14/23 up, +$543), shadow shares +0.42%. Holding overnight did not hurt on the mid;
**exiting on the opening quote did** (6 of 6 losers, -$830). P3 now covers option quote stops; it has not yet met an
open with an option position.

## 3. Findings (adversarial)

- **F1 - The book is about to be capital-bound, not risk-bound.** Shares-first works (3 of 3 entries on 09-25 were
  shares, fills at or inside the ask), but shares tie up cash: open cost is ~$5.3k of $9.0k after three days; free cash
  $3.7k. The glide sizes the next idea at free cash / 3 slots (~$1,236), then the $500 floor, then refuses. Hold caps
  run 3-20 sessions. Within about a week the desk stops taking new ideas while flat positions sit.
- **F2 - The mirror matches by source + symbol, not by instrument.** ab's two COIN messages (197.5C "leaving 1" and
  10/16 220C "second scale") both trimmed our COIN shares; only the first was the leg our position mirrored. The
  analyst's double trim (XLU) is fixed in 0.8.52.
- **F3 - The author's exit does not reach a waiting plan.** INTC (09-25 09:24, "close") and COIN (10:36, 11:02,
  "trim") were only FLAGGED on waiting armed plans ("review or disarm it"); nothing acted.
- **F4 - Armed at-level plans almost never trade.** 109 Tips plans armed since 09-08; **1** fired on the Practice book
  (tt, -$27). They roll daily for up to 15 sessions, restore on every boot and produce most of the gap/stale warnings.
- **F5 - The lotto lane has not paid.** 0-4 DTE: -$399 on 8 ideas, 1 winner (+$8.60). The $50 cap (P6) limits the
  damage; it does not create an edge.
- **F6 - The rulebook is 21k tokens that are almost never used.** 66 live rules (~86k characters) supplied 24,936
  times, cited 63 times (0.25%); 36 rules supplied more than 20 times were never cited; **29 rules sit PENDING human
  review** (propose-only). The rulebook is the biggest block of every review (~21k of ~36k input tokens per call on
  09-25). Retros keep adding proposals (48 retro runs, $20) that nobody reviews.
- **F7 - Notes are growing faster than they are used.** 1,102 live source notes, 365 ticker, 246 general (81 supplied
  more than 20 times, never cited); 36-159 new notes a day last week.
- **F8 - Cache writes are now 70% of the model bill.** Friday: 3.07M cached reads ($0.61) vs 1.04M cache writes
  ($5.21). The 5-minute cache expires between most reviews, so the rulebook is written again for almost every run.
- **F9 - Research books carry bad data.** 13 phantom SHORT share rows in armed shadow books (duplicate exit fills
  09-04..09-15; e.g. ab APLD -40,600); those books are quarantined. **eva's immediate shadow book shows +$156,134
  realized and is NOT quarantined** - any source comparison that reads it is wrong.
- **F10 - Two accounting gaps.** The rule audit's batch path left 59 calls with unknown usage and 9 partial runs; the
  scorecard's realized column excludes lots opened before its window (Friday printed +$7.27 instead of -$98.15 when run
  for one day).

## 4. The plan (ranked by expected value)

### Tier 1 - profit levers

| # | Change | How | Evidence / expected value | Rollback |
|---|---|---|---|---|
| **Q1** | **Capital recycling for shares.** A share position that has not reached +0.5R after 5 sessions, and whose source has not added or restated it, exits at the next session's first closed bar (not the opening quote). Max 7 open Tips positions; a new idea that would need the last slot must beat the weakest open one (analyst compares, journaled). | exit policy `stale_after_sessions` + `stale_min_r` (policies-as-data); slot rule in `_tip_budget` | Keeps the desk able to take new ideas (F1). The mirrored-exit and target classes are the only positive ones; a stale position is neither. | knobs to 0 |
| **Q2** | **Instrument-matched mirroring.** P2 acts deterministically only when the author's exit names the leg our position came from (same contract, or the tip had none, or a share position from a share tip); any other leg of the same ticker goes to the analyst as today. | `_mirror_source_exit`: compare against the position's originating tip contract | Keeps the +$417 class, removes false trims (F2). | code flag |
| **Q3** | **The author's close disarms our waiting plan.** A grounded author `close` on a ticker disarms that source's waiting armed plans for the ticker (journaled, reversible by re-arm); a `trim` keeps the plan flagged as today. | `runner.note_followup` -> disarm on close | Stops entries into trades the author has left (F3). | knob |
| **Q4** | **Lotto lane off** until a source earns it (P12 on the lotto cohort). | `lotto_budget=0` | -$399 on 8; removes the lowest-EV lane (F5). | budget back to 50 |
| **Q5** | **Resting target limit for shares.** When a share position adopts a ladder, rest a reduce-only LIMIT for TP1's quantity at the venue (the GTC stop quantity follows the rest); the bar-close MKT decision stays as the fallback. | position manager + OCO bookkeeping (sim first) | Captures touched targets at the target (VKTX left $11.83 on one rung); the closed-bar lag is up to 4 minutes. | knob |

### Tier 2 - knowledge that earns its place (quality first, cost second)

| # | Change | How | Evidence / expected value |
|---|---|---|---|
| **Q6** | **Settle and shrink the rulebook.** One reviewed consolidation: 66 rules -> at most 15 operative rules (<= 5k tokens), using P7's citation record and the 29 pending proposals; everything else becomes `evidence:` records (never injected). A human confirms the manifest (`--confirm <hash>`, the path used on 09-14). | `tools/tip_consolidation.py` manifest | ~-40% of review input tokens; fewer conflicting rules in front of the analyst (F6). |
| **Q7** | **Retros stop minting rule proposals** until the pending queue is under 5; they keep writing ticker/source evidence. | retro prompt + a queue guard | Stops the backlog from growing (F6). |
| **Q8** | **Note caps per scope.** One canonical `source:<name>` note rebuilt weekly plus the 15 most relied-on; general notes never cited after 20 supplies retire (tombstone, reversible). Propose-only stays: a human applies the manifest. | knowledge maintenance cycle (P8, now with P7/P8 reliance data) | 1,102 -> ~150 source notes; smaller, sharper context (F7). |

### Tier 3 - spend where it pays

| # | Change | How | Evidence / expected value |
|---|---|---|---|
| **Q9** | **One-hour cache for the rulebook block** (after Q6). The 1-hour write costs 2x input instead of 1.25x, but one write then serves every review in the hour instead of one. | `cache_control: {type: ephemeral, ttl: "1h"}` on the rulebook block only | ~-$2-3 a weekday at today's volume (F8); measure for a week. |
| **Q10** | **Retros and the rule audit through the Batch API** (50%), with usage recorded per call. | `batching.py` (digest already there) | Small money; fixes F10's unknown-usage gap. |
| **Q11** | **Sources with no trades stop costing.** giul-heatseeker (0 fills, $40) and MK-alpha-trades -> `shadow`; eva -> `shadow` for entries (1 fill in 14 sessions, -$255 after cost) while her messages still manage anything we hold. | per-source `mode` (journaled) | Cuts spend with no trading loss; revisit at the monthly source review. |
| **Q12** | **Keep the gate on enforce, with a weekly audit.** 10 random skipped messages a week re-reviewed in batch (~$1/week); a management false negative flips the gate back to observe automatically. | small scheduled job + journaled switch | Keeps the 0-false-negative evidence alive now that skips are real. |

### Tier 4 - measurement and data hygiene

| # | Change | How |
|---|---|---|
| **Q13** | **Quarantine eva's immediate book and correct the 13 phantom shorts** through a reviewed data manifest (never a synthetic fill); rerun the source table. | tool + manifest, human confirm (F9) |
| **Q14** | **Scorecard realized by position, not by window**: a lot opened before `--since` is still matched against its entry (F10). | `tip_scorecard` census window |
| **Q15** | **A ten-session evaluation of P1-P3 with the bar written first**: shares-first cohort net after fees >= 0 and above the option cohort's shadow; mirrored exits keep >= 60% winners; zero opening-quote option stop-outs that the grace would have avoided. | weekly review table |
| **Q16** | **Book size is a user decision.** $9k with shares-first holds about 6 positions. If Practice should rehearse the real account, set its equity to the planned live capital so sizing, slots and capital limits behave the same. | user decision (settings) |

## 5. What to stop

- Letting 29 rule proposals and 1,100 source notes pile up without a human pass (F6, F7).
- Arming at-level plans that roll for 15 sessions and fill once in 109 (F4): shorten the horizon to 5 sessions.
- The lotto lane (F5).
- Trusting any source table that reads an unquarantined shadow book (F9).

## 6. Order of work

1. **Monday 09-28 before the open (settings only, journaled):** Q4 lotto off, Q11 source modes.
2. **Monday evening (code, Practice only, behind knobs off by default; tests, PR, deploy after the close):** Q2, Q3,
   Q1 (knob on after review), Q14, Q10.
3. **This week, one human session (~30 minutes):** Q6 manifest + Q7 guard, then Q8's first manifest; Q13 manifest.
4. **After Q6:** Q9 (measure one week), Q12 audit job.
5. **Later, if Q1 frees capital as expected:** Q5 (sim first; needs OCO bookkeeping on the venue).
6. **Q15 at the 10th session of P1 (about 10-09); Q16 whenever you decide.**

**Targets:** trading net after fees >= the model bill (~$37/week) by the 10-session review; model bill <= $10 a
weekday; rulebook <= 5k tokens; zero false trims from mirroring.

## 7. What this review does not claim

Three sessions of shares-first and one of the mirror are not evidence of an edge. The shares cohort (+$145) and the
mirrored-exit class (+$417 on 8) are the only positive lines in the record; both are small samples. Every Tier 1
change is framed to protect those lines and to stop paying for the lines that have lost.

## 8. Implemented (0.8.54, 2026-09-27; user: "go for all your recommendations")

| # | Built | Switch (journaled setting) | Rollback |
|---|---|---|---|
| Q1 | `policies.evaluate` stale exit (pure, closed bar) + adoption policy for SHARES; book slot cap in `_tip_budget` (refusal on the record) | `techniques.tip.stale_after_sessions` 5, `stale_min_r` 0.5, `max_open_positions` 7 | 0 / 0 |
| Q2 | `mirror_instrument_matches` + `_position_origin` (position -> proposal -> signal); a non-matching leg journals `TipSourceExitNotMirrored` and goes to the analyst | `techniques.tip.mirror_match_instrument` true | false |
| Q3 | `TipRunner.note_followup(disarm=)`: the author's own grounded CLOSE disarms a waiting plan that holds nothing; a trim still flags | `techniques.tip.followup_close_disarms` true | false |
| Q4 | settings only | `techniques.tip.lotto_enabled` false | true |
| Q5 | **Changed from the plan:** instead of a resting venue limit (a resting limit + the GTC stop could together sell more than held - the phantom-short class), share ladder rungs are judged on the live BID in the exit-only quote watch (`quote_target_decision`, rung marked taken before the order) | `techniques.tip.share_target_watch` true | false |
| Q6/Q8 | `zargar.tools.tip_knowledge_prune` (plan / `--apply --confirm <hash>` through the audited consolidation path). Draft: 66 rules -> 13 (18.7k chars), 29 pending proposals released inside the batch, 3 lotto rules expired; 983 notes expired (source scopes keep their 15 most relied-on; general never-cited after 20 supplies) | **human confirm** | receipt rollback plan |
| Q7 | save_note refuses a new rule proposal while the queue is at/over the max | `techniques.tip.rule_proposal_queue_max` 5 | 0 |
| Q9 | rulebook block `cache_control.ttl=1h`; `cacheWrite1h` recorded per run and priced at 1.6x the card's cacheWrite (2x input) in `tip_llm_cost.price` (scorecard included) | `techniques.tip.prompt_cache_rulebook_ttl` 1h | 5m |
| Q10 | **Changed:** retros are tool loops (not batchable). The real defect found: the rule audit's judge replies were truncated by `max_tokens` 3000 because Opus 5.x thinking counts inside it (09-14..09-26: most chunks `partial`/`failed`). Cap 8000, ceiling 16000 | `techniques.tip.audit_max_output_tokens` 8000 | 3000 |
| Q11 | settings only | giul-heatseeker, eva -> `shadow` | the sources map |
| Q12 | a sampled ENFORCED skip is reviewed DRY (mutating tools recorded, never executed; `TipReviewGateAudit`); a management proposal or missed-tip flag sets `review_gate=observe` | `techniques.tip.gate_audit_rate` 0.1 | 0 |
| Q13 | eva immediate shadow book quarantined (API); the phantom-short correction is folded into the reset decision | - | unquarantine |
| Q14 | scorecard census from the book's first execution, only the window summed (09-25 now -98.16, was +7.27) | code | - |
| Q15 | the bar, written before the data: at the 10th session of shares-first (about 10-09) - shares cohort net after fees >= 0 AND above the option cohort's shadow; mirrored exits >= 60% winners; zero option stop-outs in 09:30-09:35 that the grace would have avoided; model bill <= $10/weekday. A miss on any line is reported, not re-scoped. | - | - |
| Q16 | open: book size (with the reset) | - | - |
| stop | at-level plans wait at most 5 sessions | `techniques.tip.horizon_sessions` 5 | 15 |

