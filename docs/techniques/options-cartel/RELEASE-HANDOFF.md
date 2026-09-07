# Options Cartel release handoff

## Release candidate

Version 0.7.2, prepared in `C:\Cursor\zargar-codex` on
`codex/zargar-development`. The user requested wrapping up the current feature;
no additional feature expansion is included in this release checkpoint.

The feature has an independent sidebar desk, method/source library, screening
profiles, source-dated evidence, focus-list scans/retries, reviewed plans,
share/option controls, alert/proposal/auto arming, durable management/recovery,
risk reporting, replay/comparison and recorded-option valuation. Other methods'
rulebooks were not changed. Shared plumbing changes and their boundaries are
recorded in [PLATFORM-RULES.md](../../PLATFORM-RULES.md).

## Validation

- Full backend: 1,096 passed, four auth-fixture key-length warnings, exit 0.
  `.cache/cartel-full-backend-quotes.log`; no database intervention.
- Final descriptive industry-rank change: 25 industry/API tests passed. It
  exposes ranks of captured values without changing freshness or trading gates.
- Production frontend build and focused mobile acceptance passed; final packaging
  verification is recorded in REGRESSION-NOTES.md.
- Joined simulated option campaign covers API arm, entry fill, target trim,
  manager/runner restore, duplicate suppression, final stop and P&L.
- Tests used only zargar_test_codex. Preview uses zargar_dev_codex, API 8421,
  simulation mode and blank integration credentials. No preview orders/positions
  were created during browser research. Recording and scheduled jobs remain off.

Reproduce backend checks from the worktree root:

```powershell
.\scripts\test-codex.ps1 -q
```

Run frontend verification from `C:\Cursor\zargar-codex\frontend`:

```powershell
npm run build
```

Do not run simultaneous backend test processes: fixtures recreate tables.

## Known limits and follow-up work

- Complete industry-performance collection and market-wide discovery are not
  automated. Current scans use selected symbols and supplied/captured evidence.
- Current industry freshness requirements can leave imported ranks unqualified;
  descriptive ranks remain reviewable. No provider timestamp is invented.
- Replay comparisons use selected cases. Recorded-premium valuation is conditional
  on the underlying schedule and does not simulate order depth, resting fills,
  expiry settlement or premium-driven exits.
- The indexed archive texts/images and September video were reviewed. Additional
  X posts/replies, unavailable linked videos and source-example calibration remain
  follow-ups. Author performance claims are not independently verified.
- Browser testing of filled runtime campaigns, broader broker normalization and
  operational soak remain follow-ups. Automated simulated integration tests are
  not real-broker acceptance.

## Deployment boundary

This handoff does not deploy, merge into main, or restart the existing app.
Before rollout, review the shared execution changes and arrange one controlled
restart of the existing runtime through its owner. The additive
`options_cartel_quotes` table is created through the existing metadata setup;
verify it in the intended database before enabling recording.

Keep `C:\Cursor\zargar` and Claude worktrees/environments/processes intact.
Do not run generic start/stop/setup scripts from the Codex checkout: they can
manage the shared app. The Codex preview is already running on 8421; never launch
another engine against that database. See [AGENTS.md](../../../AGENTS.md) and
[COLLABORATION.md](../../COLLABORATION.md) for isolation rules.
