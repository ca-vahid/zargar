# Cartel release and operational handoff

Reviewed September 16, 2026. Current source includes the prospective profitability
study, future-session warning correction and fair baseline queue. The current
[operating guide](DAILY-PREPARATION.md), [research protocol](PROFITABILITY-RESEARCH.md)
and [capability limits](DELIVERY-STATUS.md) describe behavior.

## Release versus running app

A merged PR, checkout version, built frontend and running Python process are four
separate facts. Check `/api/health` version/build, the actual served frontend, the
complete artifact manifest and the deployment receipt. A dirty or unknown process
build is not evidence that the reviewed commit is running. The launch-bound build
helper belongs on main; health may report unknown if it is unavailable, but that
does not certify a deployment.

## Safe deployment

1. Inspect the actual runtime checkout, latest main, open PRs and existing worktrees.
   Preserve other teams' dirty files and processes. If source review requires a
   clean checkout, wait for its owner; do not silently commit, stash or reset it.
2. Integrate committed changes in an owned checkout. Keep the build helper and all
   desks' changelog entries; bump above the highest applicable version and validate
   backend/UI/package metadata together.
3. Run relevant tests sequentially on `zargar_test_codex` and build the combined UI.
   Never start another engine on the shared runtime or test database.
4. At the authorized quiet window, acquire the common deployment lease and check
   `/api/ops/restart-check`. Respect active trade operations and paid analyst work.
   Confirm quiescence by acknowledgement and read-back; use the guarded scripts.
5. Preserve the prior artifact, install the tested full manifest and issue a current
   handoff. Never reuse a helper pinned to a different commit or artifact. Do not
   force a restart to obtain a window or bypass a Windows permission failure.
6. Verify process/build, served UI and restoration of armed, managed, resting and
   in-flight identities. Record deferred/failed/verified status accurately and
   release a pause if deployment did not complete.

Held positions and resting protective orders are not automatically reasons to
flatten; the common readiness/restoration contract decides what is interruptible.
A documentation-only file can still make the checkout unreviewed under the current
protocol. Keep that blocker distinct from busy trading or missing permissions.

## After the research update

Existing frozen contexts keep completed baselines, candidate ranking and signals.
The fair queue resumes without a new preparation. New sessions still need their
own fresh pre-session preparation. Check Validation for pending/ready/unavailable
counts and actual attempt progress. Quote and history gaps remain visible; no
execution setting or saved campaign is silently migrated.

Historical evidence remains in [the September 15 research release](PROFITABILITY-RELEASE-2026-09-15.md)
and [archived handoffs](archive/RELEASE-HANDOFF-PRE-2026-09-13.md). Historical armed
symbols, balances, PIDs and test totals do not describe today's runtime.
