# Cartel deployment and Monday readiness — September 13, 2026

This is a dated operational checkpoint, not a live account report or a profitability claim.

## Release and provenance

- **v0.7.64 deployed** to the existing `C:/Cursor/zargar` app, API port 8420. Backend health and served frontend both report the release.
- [PR #86](https://github.com/ca-vahid/zargar/pull/86) verified merged; merge commit `0fae7609a219e27fd45c5a78eaa5c28dbcd90f74`. The other desk's released v0.7.63 was preserved; Cartel was renumbered to v0.7.64.
- Development: `C:/Cursor/zargar-codex/.cache/cartel-monday-integrity`, branch `codex/cartel-monday-integrity`. Deployment integration: `C:/Cursor/zargar-codex/.cache/cartel-monday-deploy`, branch `codex/cartel-monday-deploy`.
- Runtime integration `ac7354f` preserved the desk's committed parallel work. The runtime kept branch `claude/zargar-stock-app-research-8mnqfh`; unrelated dirty ingestion files and every other worktree were preserved.
- The authorized `ZargarRestart` task ran at **17:47:34 PT**, returned **0**, and reached healthy v0.7.64. No force override or second engine was used.

Before/after checks found no missing other-desk armed IDs, no missing Cartel arms, and preserved all **four managed positions** and **24 resting orders** by identity. Global/book halts were clear and the existing Hybrid/Alpaca feed reported connected. Cartel arms were checked separately because the shared ops inventory does not enumerate them.

## Verified changes and checks

The [correctness release](READINESS-2026-09-13.md) covers final-dispatch contract limits, pending invalidation, target causality, explicit unused-arm review, held-capacity accounting, provider identity, quantity-specific Practice exits/replay, quote evidence and advisory leadership cohorts.

- Full Cartel run: **574 passed, one failed**. The failure was a fixture lacking its newly required execution snapshot. The fixture was completed without changing its original unsupported-volume rejection assertion.
- **79 affected checks passed**, including the repaired fixture and final runtime pause/disarm/dispatch cases.
- **37 API/engine/preparation checks passed** after integrating the newer main branch.
- Shared risk/engine/position checks: **77 passed**, with one existing Team2 event missing its schema registration. Its actual v1 producer schema was registered and the invariant passed subsequently.
- Modified Python lint checks and production builds passed, including the final desk integration. Eight static desktop/phone Practice/Live UI audits passed.
- The actual app mobile audit had one navigation timeout on iPhone SE's Cartel Plans route. Its focused rerun loaded in **2.815 seconds**, with no page errors, horizontal overflow or zoom-sized inputs; light/dark screenshots were captured. Other live route/device cases passed.

Test groups overlap. This is not a claim that the final entire platform suite was rerun. Database tests used only `zargar_test_codex`, sequentially.

## Practice configuration and existing arms

Enabled continuous option-quote recording. A read-only check found **437 recorded observations**, with OPRA provenance observed in the source check; recording remains evidence collection, not trading authority.

Selected **`whole_contracts_v2` for new Practice preparation**. The premium budget remains **USD 500** and full-premium equity-risk ceiling **10%** in the dedicated **USD 10,000 Options Cartel Practice** book. Live settings/permissions were not enabled or relaxed.

Explicitly reviewed the unused NOV, CGNX and APA arms. All now persist the original contract limits: ask ceiling $5, spread ceiling 20%, delta floor .25, 21–90 DTE, 45-day preference and selection-time OI minimum 100. The action preserved their selected contracts, chart targets and original exit campaigns. **Those retained campaigns remain legacy exits; the new whole-contract setting affects newly prepared plans.**

All three were verified `armed`, automatic Practice, phase `waiting`, no observation error, and require exchange-quality entry bars. Their automatic entry windows end **Monday September 14 at 16:00 ET**. Cartel still had **zero orders** and **USD 10,000 cash** at verification.

## Fresh Monday preparation

Run **`ccaa6c2cf40f47f8bfeb4939df08fdd3`**, session **2026-09-14**:

| Measure | Result |
|---|---:|
| Discovered / processed | 3,068 / 3,068 |
| Histories evaluated | 3,067 |
| History cache hits | 3,021 |
| Qualifying setups | 11 |
| Active arms, preserved | 3 |
| New arms | 0 |
| Pending contract | 1 |
| Readiness-blocked plans | 7 |
| Data errors | 1 |
| Actual run duration | 12 minutes |

- **APA, NOV, CGNX:** armed and preserved.
- **OKTA:** new saved plan `27a9da9e75a674121d5b5087d4b5a98b`, awaiting a suitable contract. Pending activation still requires fresh eligible data, capacity, an intact setup and the saved entry checks; it is not a promised entry.
- **SXC, VERA, OII, NTRA, PPC, URBN, HOG:** insufficient historical baseline coverage for the required first hour plus 80% of pre-close windows. These were not force-armed.
- **FISV:** missing regular-session history for **2025-11-12**. No invented bar or unverified ticker substitution was used.

The `partial` status accurately reflects these exclusions; it does not mean the three existing arms failed. The run captured advisory leadership evidence for 3,067 evaluated listings across 126 groups, preparation-policy cohort `0.7.64:30c933cd8990de4b`. Retained-arm outcomes belong to their originating policies rather than being relabelled as this cohort.

## Monday operation and remaining limits

Leave the existing app running. Preparation is enabled; weekday jobs are registered at **08:45 ET / 05:45 PT** and **20:20 ET / 17:20 PT**. The pending-contract watcher and armed-plan engine retain their normal gates. There is no need to approve green research checks or arm alert-only duplicates.

At the open, actual exchange-bar delivery, current option quotes, trigger confirmation and risk checks still determine entries. Missing historical coverage and FISV's data gap remain explicit limitations. No guaranteed trade, profit, complete author replication or automatic Live graduation follows from this release. Use exact funded quantities and executable quote/fill evidence for the next review.
