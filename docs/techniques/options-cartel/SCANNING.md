# Research scans and scheduled work

Reviewed 2026-09-13. Selected-symbol research scans and [automatic daily preparation](DAILY-PREPARATION.md) are separate workflows. Only the latter discovers the broader market and can arm plans automatically.

## Selected-symbol scans

Validation accepts up to 20 unique US equity symbols with one profile, direction and fixed cutoff. Collections run with bounded concurrency; successful analyses and per-symbol errors are saved under a parent scan. Requests may select owned evidence snapshots. A source version, historical ranking or membership is not fabricated when unavailable.

Submission returns a background job. Poll its saved progress; completed children survive interruption. Retry unresolved symbols preserves successful analyses and targets pending/failed names. Shutdown owns/cancels its workers; three concurrent research jobs are the service limit. A cancelled scan does not retroactively erase saved research.

These tools do not select the entire-market universe, arm positions or create orders. Opening a successful analysis is not execution approval. Universe-wide, unbiased walk-forward evaluation remains separate work.

## Schedules and held-position recovery

`jobs.py` registers Cartel's research scan, position-data recovery and daily-preparation callbacks. The scan/recovery settings are separate from the preparation enable switch. Check the current Settings schedule panel for actual saved enable flags and dispatch times; the default preparation dispatches are 08:45/20:20 ET on trading days.

Research scanning is non-executing. Recovery for existing Cartel managed positions is different: validated missed-close catch-up may lead the position manager to execute exits at current eligible prices. It must preserve actual fills, existing protection, cancellation state and ownership. Historical prices are not executable fills. Stopping a research scan is not a request to close a held position.

Schedule dispatch success, a completed research run, a saved plan and a filled order are separate evidence. Persisted job outcomes can contain partial failures. Restart behavior for automatic preparation is documented in DAILY-PREPARATION.md; do not apply its lease/auto-resume rules indiscriminately to selected-symbol research jobs.

Implementation: `scans.py`, `scan_tasks.py`, `jobs.py`, `preparation.py`, `position_adapter.py`, `catchup.py`. Verification examples live in the scan/recovery/API and position tests. Historical UI and preview observations are not current runtime health checks.

Validation also contains the [prospective profitability panel](PROFITABILITY-RESEARCH.md). It reads a pool frozen by daily preparation; it is not a selected-symbol scan or an executable arming route.
