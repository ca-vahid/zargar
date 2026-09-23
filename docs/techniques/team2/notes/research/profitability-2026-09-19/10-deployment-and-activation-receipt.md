# 10. Deployment and activation receipt: selection study S1 (`s1-r4`)

Authorised by the user on 2026-09-19 (merge PR #223, deploy with the collector off, then activate outside market hours once the
build, registration, the nine Team2 plans and the trading settings were verified). Executed by the Team2 desk on 2026-09-19,
Saturday, market closed. Nothing else was changed.

## Merge

| | |
|---|---|
| PR #223 | MERGED into `main` as `6a8f46b8` (head `0b5886a5`) |
| PR #224 | already MERGED (not closed as superseded: it had been merged separately). Its fix is in `main`: the `TechniquePlanDiagnostic` entry is present in `research/events_contract.py` |
| Other desks' runtime-only code | preserved: `main` was merged INTO the running checkout's branch (`claude/zargar-stock-app-research-8mnqfh`), which is 159 commits ahead of main. One conflict, `backend/tests/conftest.py`, resolved by KEEPING BOTH desks' autouse fixtures (the EM dispatch clock pin and the Team2 study CLI test-database guard). Version files kept the runtime's higher 0.8.26 |

## Deployment

| | |
|---|---|
| Deployed commit / running build | `fea5bb49a3fc125f0b4c7818146e81b20db63633` (`/api/health` build matches the checkout HEAD) |
| Version | v0.8.26 (unchanged: nothing user-visible ships while the collector is off) |
| Gates | `python -c "import zargar.api.app"` ok; `node scripts/check-release.mjs` (frontend) "Release 0.8.26: UI, changelog, backend and package metadata agree" |
| Readiness | `/api/ops/restart-check` `safe: true`, `reasons: []`, `marketOpen: false` |
| Restart | scheduler task `ZargarRestart` (never `start.ps1` from an assistant shell); transcript `logs/restart-20260919-164312.log`, "transcript end" |
| Restoration | "Restore check OK: armed 142/142, openTrades 0/0, workingEntries 0/0, pendingExits 0/0, restingOrders 28/28, inflightOrders 0/0, managedPositions 6/6, managedOpen 6/6" |
| Team2 plans | all NINE identical before and after by run id, book, symbol, status and mode (Control / Sizing 0.5 / C1, each SPY+QQQ+IWM, `armed`, `auto`) |
| Team2 settings | byte-identical before and after (mode, default portfolio, experiments map, experiment observation, risk 6%, budget 2000, target replan, 0DTE caps). No book, sizing, risk, product pricing or C2 change |

## Activation (after the verification above)

| | |
|---|---|
| Registration | `s1-r4`, hash `13b2bcc18bbbf5fa`, analysis sha256 `4022fccf7e06d9102d0c3048e0951be35a7a34541fcb46574b04ff4ac9f1aa48`, read from the DEPLOYED code |
| Activation record | journaled once by `python -m zargar.tools.team2_selection_study activate --build fea5bb49… --confirm 13b2bcc18bbbf5fa`; `activatedAt` 1789861592709 (2026-09-19 16:46:32 PT), build recorded, exactly one activation row in the journal |
| Collector setting | `techniques.team2.selection_study`: `off` -> `collect` via `PATCH /api/settings`, journaled as `SettingChanged` |
| Lifecycle state | `collecting` |
| First eligible full session | **2026-09-21 (Monday)**, as recorded on the activation row. The top-level `firstEligibleSession` in `status` reads `null` until that session exists in the window (the activation happened on a Saturday); the authoritative value is the one on the activation record |
| Endpoint (frozen) | the close of the 60th counted session, or the close of the 2026-12-18 session, whichever comes first |
| Collector health at activation | all counters zero; 0 opportunities, coverage `null` |

## Monitoring

- Owner: the **Team2 desk** (this session's desk).
- Cadence: after each close, `cd backend && python -m zargar.tools.team2_selection_study status`.
- Watch ONLY: lifecycle state, counted sessions towards 60, non-counted sessions with their reasons, opportunity and valid-outcome
  counts, coverage percentage per feature bucket, and `collectorHealth` (every counter must stay zero).
- Never run `final` before the state is `ready_for_final_analysis`; it refuses anyway. No outcome by feature is looked at before the
  endpoint. Operational problems are reported apart from method performance.
- Rollback at any time: `PATCH techniques.team2.selection_study = off`. Open records close on the next quote-watch tick, later
  sessions count as `disabled`, nothing is deleted and trading is unaffected.
