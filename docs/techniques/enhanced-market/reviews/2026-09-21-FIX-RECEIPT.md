# 2026-09-21 EM fix: delivery receipt

One tested candidate. **Not deployed**, because deployment is a separate decision from implementation and
the market-closed protocol has not been invoked. Both Practice books are active, the frozen bundle is
unchanged, and no setting was written.

## The candidate and its ancestry

| | |
|---|---|
| Branch | `claude/technique-review-trade-plan-fbb9ba` |
| Candidate SHA | **`d251d3a7`** (the receipt commit; the merge of `origin/main` is `c2ad4686`) |
| main at merge time | `7eb89303` (Tips EOD 2026-09-21, PR #245) |
| Behind main | **0 commits** |
| Runtime now | v0.8.28 build `7ee5ad2a` on `claude/zargar-stock-app-research-8mnqfh` |
| Version after merge | **0.8.28**, taken from main; no new number claimed, because no release is being called |

Merge conflicts and how each was resolved, stated because two of them destroy work if resolved carelessly:

- `backend/tests/conftest.py` - EM's controlled-clock fixture and Team2's study-database fixture collided only
  because they share the decorator above and the `yield` below. **Both kept, as two separate functions.**
- `frontend/src/changelog.ts` - main never received this desk's 0.8.26 block, so taking either side alone would
  have deleted a released desk's notes. **Union:** main's 0.8.28 and 0.8.27 blocks, then 0.8.26, one `APP_VERSION`.
- `backend/pyproject.toml`, `backend/zargar/__init__.py`, `frontend/package.json`, `package-lock.json` -
  main's version string in all four; `build_sha()` kept on the runtime side.
- `docs/PLATFORM-RULES.md` - both desks appended to the shared log. **Both entries kept.**

Verified after the merge: no conflict marker anywhere in the tree, `zargar.api.app` imports, and all four
version values read 0.8.28.

## What is live right now, with no deploy

These run from the worktree as read-only tools and scripts, so they took effect today:

| Live now | Evidence |
|---|---|
| `clock_health` probe | Reproduces the fault and exits non-zero |
| Weekday scheduled checks, incl. a **clock phase at 09:05 ET before the open** | All seven tasks show a next run of 2026-09-22 |
| `EM-ATTENTION.md` persistent notice | Raised for real at 13:51 against the live clock fault |
| Corrected exception checker | The 12:41 ET scheduled run used it |
| Report: impairment marking and attempts-versus-rows | 2026-09-21 report regenerated |
| `em_exit_latency` ledger | Ran for the session |

These need a deploy before they do anything, and none of them changes trading defaults:

| Needs a deploy | Default |
|---|---|
| Systemic admission alarm inside the runner | on (`admission_alarm`), alarm only - refuses nothing |
| Bounded deferral retry | **off** (`deferred_retry`) |
| Share-observation provenance in the shadow recorder | research recorder only |
| The MRNA alias | extraction path |

## Test evidence

| Suite | Result |
|---|---|
| New: admission health, exit latency, source topic switch, shadow provenance | **62 passed** |
| Post-merge re-run of the EM suites on the merged tree | **101 passed** |
| Reviewers' suites: first sale, final dispatch budget, measurement boundaries, capture follow-up, DA execution, review execution | pass unchanged |
| EM experiment, preparation policy, source scenarios, source wiring | pass |
| `test_technique_arming.py` | **31/31 alone.** In a 200-test combined run one case fails, a different one each time, and every one passes in isolation: the file is timing-sensitive under long combined runs. Recorded, not hidden |

Databases: `zargar_test_emfix` and `zargar_test_emfix2` on :5433, isolated from other sessions and from the
runtime database. One earlier failure was caused by my own concurrent run against the same test database,
not by the code, and the suite was re-run clean.

## Next-session readiness

| Check | State |
|---|---|
| EM Experimental armed for 2026-09-22 | **91 plans**, deterministic, zero model calls |
| EM Practice armed for 2026-09-22 | not yet - the evening ritual runs tonight, as usual |
| Both books | active, `sim`, neither paused |
| Experiment config | unchanged: same overrides, same owner, same starting equity |
| New settings written to the database | **none** - both new keys exist only as code defaults |
| Pre-open coverage | clock 09:05 ET, two-book verification 09:07, post-replan 09:32, exceptions 10:22 / 12:41 / 14:52, close 16:37 |

## The one thing this delivery cannot do

**The host clock is still 10.5 seconds behind, and the time service is still stopped.** Until that is
repaired, tomorrow's experimental session will refuse every entry exactly as today's did. It is an
administrator action on this machine, outside what a desk should do to a shared host, and it is reported
here rather than performed:

```
Set-Service w32time -StartupType Automatic
Start-Service w32time
w32tm /resync /force
```

Afterwards, `python -m zargar.tools.clock_health` should read within a few hundred milliseconds and exit 0,
and the 09:05 ET check will clear `EM-ATTENTION.md` on its next run. Two other desks have asked to be told
the moment it lands, so they can mark which of their observation sessions were collected under the skew.

**Do not widen the admission tolerance instead.** The gate is refusing evidence that genuinely looks
future-dated; loosening it would admit real stale quotes to paper over a host fault.

## Rollback

Nothing needs rolling back today, because nothing was deployed and no setting was changed. If the candidate
is later deployed and the alarm proves noisy, `techniques.enhanced_market.admission_alarm = false` silences
it and changes no trading behaviour. The experiment's own rollback is unchanged:
`POST /api/portfolios/07ef1e867cad4150bc81e072a8fd600a/pause`.
