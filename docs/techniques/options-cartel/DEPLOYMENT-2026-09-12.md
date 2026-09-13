# Cartel deployment handoff — 2026-09-12

Final deployed version: **0.7.52**. Runtime: C:/Cursor/zargar, same existing API on 8420. Development/review branch: codex/cartel-ignition-reliability in C:/Cursor/zargar-codex/.cache/cartel-ignition-reliability. Deployment integration: codex/cartel-deploy-check, retaining the desk's committed EM C1-C5 work and unrelated dirty ingestion files.

- PR66: https://github.com/ca-vahid/zargar/pull/66 — ignition workflow, source-aware preparation, caches, ownership, readiness and reporting.
- PR67: https://github.com/ca-vahid/zargar/pull/67 — active watchlist filtering, accurate retired-state explanations and bounded/collapsed display.
- Both PRs verified merged. Integrated main was included in the deployed desk history. The only first integration conflict was appended platform documentation; both teams' sections were preserved. No other desk's rules, settings or in-progress files were discarded.

## Verification

Production builds and four desktop/phone Practice/Live UI cases passed. Backend evidence: initial full Cartel run 473 passed / 7 failed; all seven failures were resolved and checked in a 92-test affected run. Subsequent 54-test, 30-test and 27-test integration groups passed. The presentation follow-up's 16-test reliability module passed. Groups overlap; these are not additive totals or a full-platform sign-off. Source/replay assertions were updated to require retained provenance; the explicit contract-refresh budget assertion was preserved. All database tests ran sequentially on zargar_test_codex only.

Two managed ZargarRestart task invocations completed with result 0. Backend health and the served frontend both report 0.7.52. The existing ops inventory's 14 other-desk armed records, four managed positions and 24 resting orders matched before/after. Cartel's three new arms were separately verified in persisted state after the second restart; health reports 17 total arms. This separate Cartel verification must not be inferred solely from the ops inventory list.

## Fresh Practice preparation

Target session: Monday 2026-09-14. Used the existing general September profile and existing risk/account settings, not automatic pilot promotion.

- 3,076 discovered; 3,075 histories evaluated; one data error; 11 qualifying candidates.
- 11 candidates checked for history/contracts; three armed: **APA, NOV, CGNX**.
- All three have 26/26 historical baseline periods and require_exchange_bars=true.
- All three persisted automatic validUntil timestamps equal 2026-09-14 16:00 America/New_York, proving weekend evidence did not expire after 24 wall-clock hours.
- OKTA remains awaiting a suitable contract; seven other plans failed readiness checks. The partial label is therefore expected, not evidence that the three arms failed.
- Cold verification run: 14m12s, 52 cache hits. This seeds the durable cache but does not establish the warm/resume timing targets or a cold-run speed improvement.
- The active ignition research list contained 30 theses after the run. Developing/ready research is separate from executed or armed plans.

## Remaining validation

Native multi-symbol daily collection remains off by default because its provider-day dataset differs from the existing daily source. Enable only with source/entitlement comparison. The Practice ignition pilot is selectable but was not silently substituted for the user's current profile. Real option-fill performance, statistical expectancy and prospective graduation require future evidence; nothing in this release guarantees trades or profits.

No second engine was launched. No runtime/test databases were copied, no Live permissions were enabled, and existing positions retained their protective management.
