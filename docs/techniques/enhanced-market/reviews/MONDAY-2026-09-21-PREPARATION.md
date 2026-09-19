# Monday 2026-09-21 - both EM books prepared (baseline + experiment)

Run once on 2026-09-19 (Saturday, market closed). No setting was changed, no book was paused, the experiment stays frozen at
`em-experiment-v1` with the bundle of `reviews/EXPERIMENT-LAUNCH-RECEIPT-2026-09-19.md`. Nothing here is live money.

## 1. Baseline (EM Practice `045d8c35...`) - the normal ritual, unchanged

Auto sheet `8e47c46d` (built Friday 16:15 ET) -> model review of every setup row -> arm the reviewed setups. One batch, run once.

| Sheet rows | Setup rows reviewed | Verdict setup | Verdict no_setup | Failed / unfinished | Armed | Arm failures |
|---:|---:|---:|---:|---:|---:|---:|
| 144 | **96** | **38** | 58 | 0 | **38** | 0 |

Model cost of this preparation: **423 requests, about 49.89 USD estimated** at the current `llm.rates` card (an estimate, not an
invoice; never subtracted from trading results). 3.30M input, 1.29M output, 1.75M cache-read tokens. No request without a completion.

One change to the batch script, and the reason: its "already held" guard skipped any symbol an EM plan held in ANY book. With the
experimental book holding 79 symbols, that would have suppressed 37 baseline arms and destroyed the comparison. The guard is now
scoped to the baseline book, so each book arms its own candidates independently.

## 2. Experiment (EM Experimental `07ef1e86...`) - unchanged since launch

79 plans armed for 2026-09-21 by the deterministic owner (144 rows, 79 eligible, 65 refused by the rules, **zero model calls**).
A second preparation on the live system minted and armed nothing: idempotent.

## 3. Both books before the open

| Item | Baseline | Experiment |
|---|---|---|
| Kind / cash / last equity point | sim / 9,849.60 / 9,849.60 | sim / 9,849.6032 / 9,849.6032 |
| Armed for the session | 38, all `armed`, mode `auto` | 79, all `armed`, mode `auto` |
| Plan origin | `promote` (model-reviewed sheet) | `experiment` (deterministic) |
| Experiment-tagged arms | 0 | 79 |
| Open positions / working orders | 0 / 0 | 0 / 0 |
| **Daily loss limit per plan** | **393.98** | **393.98** |
| riskPct / maxContracts / maxQty / maxOpenTrades | 2.0 / 10 / 100 / 1 | identical |
| singleContractExit / entryFallback / skipWideSpread / skipElevatedIv / slippagePct / flattenMinutesBeforeClose / allowLive | tp2 / shares / true / false / 0.1 / 5 / false | identical |

The loss allowance is the declared rule, not a difference between the books: `2 x riskPct x the book's equity at arm time`
(`PlanRunner._ensure_loss_halt`). Both books were at 9,849.60 when armed, so both carry 393.98. The 405.96 in the launch receipt
came from Friday's baseline arms, made when that book still held 10,149 before Friday's loss.

Routing: no experiment-tagged run armed outside the experimental book (0); no untagged arm inside it (0); both books are `sim`.
Technique-wide EM settings unchanged (first-sale gate off, preparation policy baseline, observers off, P-02 / P-06 observation on).
Shared and not per book: the order-rate window (30 per minute, all desks), the kill switch and `techniques.enhanced_market.paused`.

Symbol overlap: **37 symbols in both books**, 1 baseline only (DIS), 42 experiment only - the rules-only policy admits more names
than the model review does. Operating owner: the EM desk.

## 4. Monday checks - persistent, not session-bound

Three Windows scheduled tasks run the read-only checks even if every Claude session is gone. Script:
`C:/ProgramData/Zargar/em-monday-checks.ps1` (reads the database read-only, writes files, changes nothing). Log:
`C:/ProgramData/Zargar/logs/em-checks-2026-09-21.log`.

| Task | Fires (PT) | Phase | Writes |
|---|---|---|---|
| `ZargarEmChecksPreopen` | 06:07 (09:07 ET, before the 09:25 re-plan) | `preopen` | `research/experiment/2026-09-21-preopen.md` + `.json` |
| `ZargarEmChecksPostReplan` | 06:32 (09:32 ET, after the re-plan and the open) | `postreplan` | `...-postreplan.md` + `.json` |
| `ZargarEmChecksClose` | 13:37 (16:37 ET) | `close` | `research/experiment/2026-09-21.md` + `.json` (the daily comparison) |

Verified by running each phase once: task result 0, files written. To run any phase by hand:

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\Zargar\em-monday-checks.ps1 -Phase preopen -Date 2026-09-21
cd C:/Cursor/zargar/.claude/worktrees/technique-review-trade-plan-fbb9ba/backend   # ZARGAR_DATABASE_URL from C:/Cursor/zargar/backend/.env
python -m zargar.tools.em_experiment_check  --date 2026-09-21      # two-book state, limits, routing
python -m zargar.tools.em_experiment_report report --date 2026-09-21   # side-by-side session comparison
```

Rollback, unchanged: `POST /api/portfolios/07ef1e867cad4150bc81e072a8fd600a/pause`. Do not retune the bundle from one session.
