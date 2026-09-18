# Preparation performance — 2026-09-18

Release 0.8.15 keeps the same universe, source data, setup rules, ranking, contract
checks and risk limits. No performance optimization authorizes a trade.

## Measured bottlenecks

Preparation `bc3d2967d7774a96a9fecdcad89638b6` evaluated 3,069 of 3,072 listings,
reported 2,724 history requests, and eventually armed five plans. It used 250 ms
spacing between history requests: the pacing ceiling alone contributes about
11.35 minutes before analysis and optional research. Existing history concurrency
was already six; raising concurrency alone cannot remove that pacing limit.

Read-only same-provider pilot, 100 symbols, the same four-day daily-history window,
six concurrent workers, fresh requests (no local-cache substitution):

| Request spacing | Elapsed | Successful symbols | Errors / rate-limit retries |
|---|---:|---:|---:|
| 250 ms | 25.825 s | 100 | 0 / 0 |
| 50 ms | 6.104 s | 100 | 0 / 0 |

Both outputs hashed to `b77ec5f1f49018b51bd9c99f00461dfd5c5ed07f7768f431c9f83f90ab5ffaba`.
This is a 4.23x download-stage improvement in this pilot, not a full-universe
end-to-end guarantee or a provider rate-limit agreement.

The primary-plus-bearish analysis CPU benchmark over the same 100 frozen analyses
fell from 3.285 s to 1.785 s with identical output hash
`d7b715f175121275a2743349fe267bc597f6ce6650905960231f4ee69bf06a10`.
It caches immutable date/timestamp arithmetic. The resolved early-close time remains
in the cache key, so calendar policy changes are not hidden by a stale cache.

## Operational behavior

- Settings exposes Fast (50 ms) and Conservative (250 ms) request spacing. Existing
  settings/defaults are preserved unless explicitly saved. This user authorized Fast
  for Cartel Practice; Live stays unchanged.
- The shared provider concurrency ceiling and 429 retry/backoff stay in force.
  A 429 also slows this preparation to at least 250 ms, doubles spacing on further
  throttling (capped at five seconds), and applies a cooldown. It does not change
  another technique's settings. Exhausted retries still fail visibly and retain
  resumable work.
- Executable shortlist checking and arming precede optional profitability research.
  Research still uses the same frozen analyses and separate cohort; it cannot change
  entry permission. Its failure does not remove existing arms. If interrupted, arms
  remain managed and research can be rebuilt from the saved analyses.
- Plans shows stage durations, provider pacing time and rate-limit slowdowns.
  `shortlistReadyAt` distinguishes completed executable checks from research completion;
  it does not mean every candidate was armed or that there were no data errors.

Keep performance results separate for cold/new-session fetches, warm repeats and
resumed runs. Never claim a fivefold complete scan improvement from only the HTTP
pilot. Assess the next full run with `phaseDurationsMs`, `historyPacingMs`,
`historyRateLimitRetries`, `cacheHits`, and actual shortlist readiness.

## First deployed full-universe validation

On v0.8.17 build `783be1a14d1071b74701d49328611f5301de59b2`, run
`0a3d8cebe39d4803b5f44286875c7213` processed all 3,072 listings for September 18:

- Shortlist checks completed at 284 seconds (4m44s); total 383 seconds (6m23s).
- Evaluation: 271.865 seconds; optional research: 98.911 seconds. Discovery and
  market/industry context accounted for roughly 12 seconds.
- Warm caches: 3,074 cache hits, two history calls, zero rate-limit retries.
- Five existing automatic arms were retained: BBY, DAR, NTNX, CNH and CLF.
- 3,071 analyses succeeded; FISV remained excluded for a missing 2025-11-12
  regular-session bar. This did not affect the five armed symbols.

This was a **warm-cache validation with existing arms**, not a cold-fetch or
fresh-arming benchmark. It does not prove a fivefold end-to-end speedup. The next
measured bottleneck is per-symbol evaluation/persistence, followed by optional
research; improving only network pacing cannot remove those costs. No further
late-night trading-policy changes were made.
