# 2026-09-21 EM fix: closure matrix

One integrated delivery against `EM-2026-09-21-COMPREHENSIVE-FIX-GOAL.md`. Both Practice books stayed
active throughout, the frozen bundle and the baseline are unchanged, and 2026-09-21's results are
untouched: baseline **+$201.70**, experiment **$0.00**, every original fill preserved.

Nothing in this delivery loosens a freshness check, a risk check, a volume, spread or stop rule. The
admission gate that refused every experimental entry was **correct** and is pinned by test, not relaxed.

## The finding that explains the session

The experimental book fired 13 times, was deferred 9 times on `venue_time_in_future`, and submitted
nothing. The venue timestamps were right. **This host's clock is 10.5 seconds behind true time**, so
every fresh quote read as future-dated and a gate built to refuse future-dated evidence did exactly that.

Measured, not inferred: five independent NTP servers (four stratum 1) agree within 38 ms, worst
round-trip uncertainty 62 ms. The Windows time service is **Stopped**, start type **Manual**, so the
drift returns after every reboot. The database in WSL is itself ~1.4 s behind true time, which is why
comparing the two machines understated the fault all day.

| | measured | note |
|---|---:|---|
| host vs NTP quorum | **+10,517 ms** | host behind; 5 servers, spread 38 ms |
| host vs database | +8,339 ms | corroboration only - the database is another computer's opinion |
| venue stamp vs host record, 9 deferrals | +4,030 to +10,073 ms | the same offset, less each quote's own age |
| admission tolerance | 1,000 ms | every fresh quote exceeded it |

## Closure matrix

| # | Verified finding | Cause | Correction | Test / evidence | Remaining uncertainty |
|---|---|---|---|---|---|
| 1 | Nine experimental entries deferred, zero orders all session | Host clock 10.5 s behind; time service stopped. The producer path is clean: `venue_ms` parses ISO with its offset, `quote_ts`/`last_ts` carry venue time, `q.ts` stays the receipt | `tools/clock_health.py`: NTP quorum with stated uncertainty, database as corroboration, platform sync state, and what the offset does to the gate. **The host repair itself is an administrator action and is NOT done here** | 8 tests incl. thresholds, quorum disagreement, unreachable servers; live probe reproduces the fault and exits non-zero | None about the cause. The host is still wrong until an administrator runs the command in §"What is left" |
| 2 | The desk was armed and silent for a whole session and nothing said so | No systemic detector existed; no push destination is configured on this host; the exception checker had two blind spots | `technique/admission_health.py` watches the shape of first-sale outcomes and raises one alarm with counts, times, offsets, book and build, then reports recovery. Checker blind spots fixed earlier the same day (commit `3745500f`) | 10 detector tests + one through the real runner; the live clock check raised `EM-ATTENTION.md` against the real fault at 13:51 | The file-level *clear* is proved by unit test and code path; it will be seen live when the clock is fixed |
| 3 | "Deferred" was terminal: all nine deferred triggers fired once and never again | `_refuse_entry` marks the trade `skipped`; the tracker has already left `fired`, so nothing re-offers it | Named honestly, and `deferral-retry-v1` offers **one** bounded re-evaluation as a separate **default-off** policy: same setup, same production path, window counted in bars so a wrong clock cannot stretch it | 9 eligibility tests covering every case the goal listed, plus two through the real runner: bounded retries exactly once, `off` stays terminal | Whether a retry would have filled on 2026-09-21 is unknowable and is not claimed |
| 4 | Refusal rows were being read as opportunities | `max_open_trades` re-journals every bar while a position is open | The report separates entry **attempts** from refusal **rows** | Report output matches an independent audit exactly: baseline 6 attempts, 116 rows, 69 pairs, 48 AVGO rows = **1** real; experiment 13 attempts, 23 skip rows = 11 real | An F33 budget block rescued by the shares fallback writes no journal row (see §"Open items") |
| 5 | The session was being compared as if it were evaluable | No impairment concept existed | `sessionQuality` marks the session **operationally impaired**, retained in every chronological report, excluded from strategy evaluation | Report prints it for 2026-09-21: "experiment: 13 attempts, 0 fills, 9 undecided" | None |
| 6 | The MRNA row was held as an AMD conflict | The transcriber wrote "maderna"; no alias matched, so topic carry-forward kept AMD's label | One alias added to a table that already carries transcription variants. The span logic is untouched because the span was already right | 7 tests on the real transcript, including that a ticker the evidence never names is still refused | Even resolved, the row had no valid app geometry: the day's MRNA plan had zero valid triggers |
| 7 | The persistent checks would not have run again | They were registered by hand for a single date | Script versioned in the repository, installed by `scripts/em-install-session-checks.ps1`, re-registered **weekly Mon-Fri**, and a **clock phase now runs before the open** | All seven tasks show a next run of 2026-09-22; the clock phase ran for real and raised attention | None |
| 8 | The IREN TP2 exit filled 5 cents below the bid seen at the signal | Measured: decision to order **21 ms**; order to fill **1,584 ms** for the option, against 224-395 ms for shares | `exit-latency-v1` records the durable stages and answers the money question **only** from contemporaneous evidence | 12 tests, including that the best price in the window is never the answer and that missing depth stays unknown | The $10 is **not** attributable: quotes are never journalled, so all six exits report `unknown` for the reachable price |
| 9 | NBIS ~$400 vs $394, and the AVGO sizing refusal | Both correct, and NBIS twice over. A ~$9.85k book with a 2% per-trade budget and a 50% premium stop cannot buy any contract priced above **$3.94** | **No code change.** The intended bound was not violated | Arithmetic reconciled to the exact contract, quantity and settings | The F33 message quotes a per-plan allowance while reading like a book-level one |
| 10 | Two failing tests unrelated to trading | The arming lifecycle helper published an anonymous option quote; the preparation test depended on synthetic geometry that drifts with the calendar | Both fixed, test-only | `test_em_experiment.py` 9/9; `test_technique_arming.py` lifecycle passes | None |

## What is NOT changed, deliberately

- The admission gate, its 1,000 ms tolerance and its refusal codes. It was right.
- Risk, volume, spread and stop rules; the 3R floor; the 3% stop cap; P-02 and P-06 as frozen.
- The baseline book, the frozen bundle, and every 2026-09-21 result.
- No order, fill or snapshot was fabricated, and no preparation was re-run.

## Open items, stated rather than quietly carried

1. **The host clock is still wrong.** Until it is fixed, the next session will refuse every experimental
   entry exactly as this one did. The pre-open clock check will now say so at 09:05 ET and raise
   `C:\ProgramData\Zargar\EM-ATTENTION.md`.
2. **F33 blocks rescued by the shares fallback leave no journal row** (`_entry_blocked` in the shared
   `planrunner.py`). MRVL was blocked in both books that morning and neither produced an event. The
   durable ledger under-counts budget blocks. Not fixed here: it is a shared-engine change and belongs in
   a reviewed diff of its own.
3. **Why the candidate builder saw no same-day plan for GOOGL, NFLX and SPY** is not visible in the data.
4. **Recovery of the attention file** is proved by test and by construction, not yet observed live.
