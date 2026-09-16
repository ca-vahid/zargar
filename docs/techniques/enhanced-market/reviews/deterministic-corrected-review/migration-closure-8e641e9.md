# DE-02/DE-03 and UI closure review at 8e641e9

Code inspected: `8e641e9e7fd86f5b29beef339ad25401cd4c1a86`, isolated review checkout `C:/Cursor/zargar-codex/.cache/em-deterministic-corrected`.
Scope: original migration, decision attribution and UI findings only. No database access, test process, settings change, engine or helper operation was performed in this subreview.

- **DE-03 closed by code inspection.** The preview uses `read_only_settings` over selected rows and opens a read-only transaction. `ReadOnlySettings` resolves defaults, recognized per-technique keys, legacy execution aliases with canonical-row precedence, and trading-mode aliases entirely in memory. It exposes no set/commit/journal method. `SettingsService.load()` and journal construction are removed. The preview and runner now share `normalize_fire_mode`, including case/whitespace and supported legacy aliases. This does not independently verify current runtime arm counts.
- **UI correction closed by code inspection.** The armed-card header now uses the effective deterministic mode and says the critic is not applicable; invalid modes display a policy error. The arm dialog offers the critic checkbox only for legacy/older servers and shows invalid mode separately. Existing-arm `useCritic=true` cannot create the earlier contradictory label.
- **DE-02 setup verdict and fill attribution corrected.** `PlanArmer.record_fire` converts deterministic refuse/defer to the persisted `no_setup` result with reason codes. Profitability rows select matching `decisionId` rather than taking the first same-trigger fire, and the actual trade's decision is a fallback. The original example's deterministic fill is no longer attributed to the legacy veto. The census preserves both attempts in the original fixture.

## Remaining DE-02 report correction (P2, does not affect execution)

`backend/zargar/tools/em_profitability.py:445-459`: census entries increment only `attempts`; their `disposition` is not used for refusal counts. Refusals are still counted solely from the latest stored trade projection. In the original fixture (legacy veto, later deterministic fill), the legacy cohort becomes **one attempt, zero fills, zero refusals**, although its event explicitly says `criticDisposition=vetoed`. The earlier refusal is still lost in the advertised refused total.

Add to the existing reproduction after `summary = report.summarize(data)`:

```python
self.assertEqual(summary["byPolicy"]["legacy-critic:momentum_only"]["refused"], 1)
self.assertEqual(summary["byPolicy"]["deterministic-entry-v1"]["fills"], 1)
self.assertAlmostEqual(summary["byPolicy"]["deterministic-entry-v1"]["net"], 97.92)
```

Count immutable refusal/deferral dispositions once by attempt identity, then join actual order outcomes; do not count an attempt again because its latest projection also appears. Unknown/no-result attempts should remain explicitly unclassified rather than forced to refusal. Include `runId` in census/deduplication keys: the new build-stage deduplication currently uses only trigger ID plus event timestamp, and summary identity uses only trigger ID plus decision ID.

This is a correction to the policy-comparison report, not a new trading rule or infrastructure request. It does not require delaying deterministic main-mode activation if the independent execution review passes; keep refusal-rate comparisons provisional until corrected.
