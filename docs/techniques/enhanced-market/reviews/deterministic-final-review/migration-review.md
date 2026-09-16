# Deterministic entry: settings, migration, UI and reporting review

Reviewed code: `758ccfb8e0a456d1df534f9e91a35e16f47cb352` in `C:/Cursor/zargar-codex/.cache/em-deterministic-final`.
This was an independent bounded review. No runtime settings, processes, orders, database rows or production code were changed. Tests below substitute in-memory persistence boundaries and execute the actual preview/report functions.

## Findings

### P2: the migration preview can write settings

`backend/zargar/tools/em_fire_policy_migration.py:25` constructs `SettingsService` and awaits `settings.load()`. The latter is not read-only: `backend/zargar/settings_service.py:619-647` adds canonical `execution.*` settings for legacy aliases, commits them, and journals changes; it can also rewrite old trading-mode values. Thus a command explicitly documented as read-only can change runtime settings whenever a legacy key has not yet been migrated.

The reproduction supplies a stored `technique.arm.use_critic=true` without its canonical counterpart. The actual preview adds `execution.use_critic` and calls `commit`, violating its contract. This is conditional; it does not prove the team's completed runtime preview changed an already-migrated database.

Correction: load and resolve settings into an in-memory projection that has no persistence/journal capability, and enforce read-only transactions on the preview connection. Use the same canonical policy normalizer as the runner. The preview currently also calls `critic` / `legacy_blocking` invalid even though the runner accepts them as legacy, and omits the runner's whitespace/case normalization.

Acceptance: preview with legacy aliases, old trading-mode aliases, canonical overrides, supported legacy mode aliases, active/paused plans and existing cooldowns must write zero rows/events and leave every original value unchanged. The effective policy must match the runner.

### P2: policy comparison attributes a later fill to an earlier fire

`backend/zargar/tools/em_profitability.py:301-305` selects the first intent and first fire by trigger ID from all historical events, but the report iterates only the latest trade stored under that trigger. The new policy-version report can therefore credit a deterministic trade to the earlier legacy critic policy after a veto/re-fire. It also counts one latest projection row as one attempt, dropping the earlier refusal. The same trigger can fire again after the established legacy cooldown or a controlled policy switch; the implementation plan explicitly requires comparisons by attempt/decision identity.

The reproduction has a legacy veto and a later deterministic fill, both on `b1`. The actual closed trade reconciles to +$97.92, but the report labels it `legacy-critic:momentum_only` with no decision ID instead of deterministic attempt `attempt-2`.

Correction: construct an attempt census from immutable decision/fire records; bind intent/results/executions by decision/attempt/order identity. Keep older records with explicit unknown identity rather than attaching the first same-trigger event. Preserve previous refusals, and keep the fill attached to its decision ID. Do not change trading behavior as part of this report correction.

Acceptance: a legacy veto followed by a deterministic fill yields two attempts, one refusal in the legacy cohort and one correctly attributed deterministic fill. Two deterministic attempts and historical ambiguous records also remain distinct/unknown as appropriate.

### P3: armed cards still say "critic on" in deterministic mode

`frontend/src/components/technique/ArmedTab.tsx:217-224` adds the correct effective-policy badge, but leaves the old right-hand summary using `config.useCritic` to show `critic on`. All restored arms with the legacy true flag and a configured model would show both deterministic entry and critic on. An invalid policy is also mislabeled as "legacy, no critic" in the new badge; the arm dialog presents the legacy checkbox for every non-deterministic value.

Correction: use the authoritative effective mode/criticEffective fields throughout. Show an explicit policy error for invalid mode; preserve legacy rendering only for legacy/older servers. Add one rendering assertion for an EM arm with `useCritic=true`, deterministic mode and an available model.

## Accepted within this subreview

- EM's fire policy defaults to deterministic from its own namespaced setting; the base runner remains legacy and evidence-off for other desks.
- Existing `useCritic=true` remains a stored compatibility field and does not select the live EM policy.
- Evidence defaults to off. Premarket LLM availability is separate from live mode metadata.
- Arm options, preflight wrapper and armed snapshots expose the effective policy. Restore copies persisted decision, disposition and timing fields.
- No new live-account authorization is introduced by these settings.
- Current same-attempt trades carry the deterministic decision into order intent and the ordinary persisted projection.

## Reproductions

File: `test_policy_migration_reporting.py` beside this report.

Command, from the reviewed worktree's backend:

```powershell
$env:PYTHONPATH=(Get-Location).Path
& .venv/Scripts/python.exe C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/deterministic-final-review/test_policy_migration_reporting.py
```

Result: **2 failed, 0.785 seconds**, each at the intended contract assertion (no fixture/import failures). No Postgres connection, provider, engine, paid model or runtime mutation was involved.

These findings concern migration safety and truthful presentation/measurement. They do not themselves show the live deterministic branch still awaits a model; the runner/rule reviewers cover that independently.
