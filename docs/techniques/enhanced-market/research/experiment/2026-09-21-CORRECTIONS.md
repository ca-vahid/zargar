# 2026-09-21: five corrections to the close report, and the clock repair

The operationally-impaired classification and the booked totals stand: baseline **+201.70** net after fees,
experiment **0.00**, every original fill preserved. Five statements around them were wrong or imprecise and
are corrected here against the data.

## 1. IREN's net was overstated by its fees

I reported IREN at +176.00. That is the **gross**. The option round trip carried 4.16 in commission, which
the share trades did not.

| Symbol | Vehicle | Gross | Fees | **Net** |
|---|---|---:|---:|---:|
| IREN | option, 2 contracts | +176.00 | 4.16 | **+171.84** |
| AVGO | shares | +68.41 | 0.00 | **+68.41** |
| MRVL | shares | −38.55 | 0.00 | **−38.55** |
| **Total** | | **+205.86** | **4.16** | **+201.70** |

The book total was always right. Only the per-symbol IREN figure was stated gross while being labelled net.

## 2. AVGO did reclaim its first target; P-06 had no book to act in

I wrote that no runner reclaimed its first target. Wrong. The baseline recorded a **`tp1-reclaim`
observation on AVGO shares at 09:48 ET**, which is precisely the P-06 signal.

What did not happen is the exit, and for a reason that has nothing to do with the signal: P-06 executes
**only** in the experimental book, and that book held no AVGO position, because its entry was deferred at
the admission gate. The baseline, which did hold the position, records P-06 as an observation by design and
never acts on it. So the correct statement is that the signal fired, in the one book that cannot act on it.

That observation was also **unscorable**, with the reason "no source provenance / timestamp" - the share
evidence defect fixed in this delivery. Under the corrected recorder the same observation would carry the
feed label with `sourceBasis: engine_feed` and a real venue time.

Session P-06 exits: still **zero**. Session P-06 signals: **one**, on AVGO, unscorable as recorded.

## 3. The recorder was effectively ON for the experimental book

I said the book-snapshot recorder is off by default and produced no captures. That is right for the baseline
and **wrong for the experiment**:

| Book | Effective `book_snapshot_observe` | Why |
|---|---|---|
| EM Practice (baseline) | **off** | no technique-wide row, so the `False` default applies |
| EM Experimental | **on** | the experiment is enabled and its override sets it true, resolved per book |

Zero snapshots in the experimental book is therefore **not** evidence that the recorder was disabled. It is
consistent with the documented behaviour: a periodic tick on a flat book produces no record, and that book
was flat every minute of the session because it never filled. Event-caused snapshots need a fill, a target,
a stop or a flatten, and none occurred. The recorder has still never been exercised on a live experimental
position, so its path remains unproven by a real trade.

## 4. Marked peak is known; executable peak is not

Both were printed as unknown. Only one of them deserved that. The marked peak comes straight from the equity
samples and was computable all along; the executable peak needs capture coverage, which does not exist.

| | Baseline | Experiment |
|---|---:|---:|
| Equity samples | 959 | 959 |
| Marked peak | **10,063.69** | 9,849.60 |
| Marked trough | **9,815.05** | 9,849.60 |
| Marked peak gain over the open | **+214.09** | 0.00 |
| Max drawdown (marked) | −114.06 | 0.00 |
| **Executable peak** | **unknown** | **unknown** |
| Giveback against the executable peak | unknown | unknown |

The report now prints the marked pair and keeps the executable pair unknown, so the two are no longer
conflated. "We did not record it" and "we cannot compute it" are different statements.

## 5. Event rows are not unique attempts

The refusal counts I quoted mixed both. Separated:

| | Baseline | Experiment |
|---|---:|---:|
| **Unique entry attempts** (a trigger that reached the entry path) | **6** | **13** |
| Refusal / skip event rows | 116 | 150 |
| Distinct (plan, trigger) pairs behind those rows | 69 | 136 |
| Rows that are a guard re-stating itself | 47 | 12 |

The largest single distortion: **48 `max_open_trades` rows on AVGO are one suppressed setup**, re-journalled
every bar for 51 minutes while that plan's own long was open. In the experiment, 23 confirmation skips are 11
real ones. Anywhere a count of "refusals" is compared between books, it has to be the attempt count or the
distinct-pair count, never the row count.

## The clock repair

Performed after the close with every EM book flat and no order working anywhere on the host.

| | Value |
|---|---|
| Before, host vs NTP | **+10,659.7 ms** behind true time (5 servers, spread 21.7 ms, uncertainty 54.1 ms) |
| Before, time service | Stopped, start type Manual |
| Repair performed | `Set-Service w32time -StartupType Automatic`, `Start-Service w32time`, `w32tm /resync /force` |
| Repair timestamp | **2026-09-21 16:19:12 PT** (23:19:12 UTC), last successful sync reported by the service |
| After, host vs NTP | **+2.3 ms**, then +0.3 ms on the next reading |
| After, time service | Running, start type **Automatic**, stratum 5, leap indicator 0, source `time.windows.com` |
| After, admission | a fresh venue quote reads 0-5 ms ahead against a 1,000 ms tolerance: **within tolerance** |

The timestamp tolerance was **not** widened. The gate is unchanged; the clock it judges against is now right.

A second defect surfaced while proving the recovery path: the attention notice did not clear even though the
clock was healthy. `Say` wrote through `Tee-Object`, which emits into the pipeline, so the clock function
returned every logged line **plus** its exit code and the `-eq 0` test compared against an array. The notice
could have been raised and never cleared. Fixed, and the raise-then-clear cycle is now demonstrated live
rather than by construction.
