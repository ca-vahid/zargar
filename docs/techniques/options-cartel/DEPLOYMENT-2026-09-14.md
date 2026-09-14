# Cartel v0.7.74 deployment — September 14, 2026

- PR #107 merged: `60cda02ec324a9c10c24e88c609c2650eac5d055`.
- Team2 PR #106 took v0.7.73 during development. Its changes and release notes were
  preserved; the Cartel release moved to **v0.7.74** and deployment ownership was unified.
- Runtime integration: `3ea64d932d3af6eddbc32053dd371e5464b01c31`, preserving the desk's
  private work and the subsequent PR #109 coordination notes. The final late merge changed
  only PLATFORM-RULES; backend/frontend/scripts were identical to the tested integration.
- Runtime remains `C:/Cursor/zargar`, branch `claude/zargar-stock-app-research-8mnqfh`.
  No Claude worktrees, environments, private dirty files or trading settings were changed.

## Verified restart

The owner checked a quiet runtime, acknowledged and read back the entry pause, fast-forwarded
only the reviewed source, installed the built UI and handed a commit/version/hash manifest
to `ZargarRestart`. A prior handoff attempt correctly refused when another desk advanced
HEAD. A PowerShell File.Replace null-backup binding error was corrected with an explicit
backup path; the engine was not stopped on either failed handoff.

The scheduled task ran **16:37:15 PT**, finished its transcript at **16:39:12 PT**, and
returned **0**. API health reports **ok=true, started=true, version=0.7.74**.
Before/after identity comparison verified:

| Inventory | Preserved |
|---|---:|
| Armed plans | 11 / 11 |
| Resting orders | 23 / 23 |
| Managed positions | 3 / 3 |
| In-flight orders / working entries | 0 / 0 |

Preserved managed positions are RKT `7b7020cf32f244fdab16e1cd1f8338ea`, HIMS
`882b1644fcec48f1a738dd04188f7f25` and T `dcd7274dabd447e18c66e9a356ae53e1`.
No force override or second engine was used.

The first handoff's start script rebuilt the frontend because checkout timestamps changed.
The resulting artifact was independently verified; actual index SHA-256 is
`8ED9DC054F03BCFE364CA917BB07D06A5E69D9E21B9355F8E54B92C9320724F0`.
A maintenance follow-up forwards NoBuild for a verified handoff and checks the artifact hash
again before writing the receipt. The current receipt retains the original handoff hash as
well as the verified actual hash, rather than claiming the rebuild never occurred.

## Verified on the running app

Authenticated GET /api/options-cartel/session-review for September 14 / Practice returned:

- Options Cartel Practice: **-$59.05 gross, $2.08 fees, -$61.13 net**.
- **One closed campaign, zero open instruments**.
- APA **closed**, reason: underlying crossed the active protective stop.
- CGNX and NOV **invalidated**.
- Nine preparation exclusions/pending records; three archived quote-coverage groups.
- Two legacy fills lack exact source receipts, correctly reported as unknown.
- No accounting/mark issues in the report.

The shared live restore-check returned `ok=true` with an empty missing-identity set.

## Verification limits and remaining data issue

The integrated build and four desktop/phone light/dark UI checks passed. An additional
30-check integration run was invalidated while another job was visibly dropping/updating
tables in zargar_test_codex. That was not treated as an application verdict. After a quiet
database window, both affected checks passed; all tests remained confined to the disposable
Codex database. Earlier focused groups and regression corrections are recorded in
IMPLEMENTATION-2026-09-14.md; overlapping counts are not added together.

FISV's Yahoo historical gap is still excluded. Alpaca returns the missing November 12, 2025
bar, but the release does not splice unlike datasets or silently change the selected provider.
Existing risk settings and campaign snapshots remain unchanged. No historical unknown fill
is relabeled with invented source evidence, and no profitability improvement is claimed yet.

## User action

Refresh the app. Open **Options Cartel → Plans → Daily review**, select September 14 and
load the review. Expand exclusions, attempts and recorded quote coverage as needed.
Normal preparation schedules remain enabled; use Prepare now for the next session if you
want to prepare before the scheduled run. Do not manually duplicate already armed plans.
