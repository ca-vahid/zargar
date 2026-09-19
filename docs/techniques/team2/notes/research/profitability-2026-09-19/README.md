# Team2 profitability study: acceptance package (correction and validation pass, 2026-09-19)

**Read `00-decision-sheet.md` first.** DEPLOYED and ACTIVATED on 2026-09-19: build `fea5bb49`, registration `s1-r4`, collector
`collect`, first counted session 2026-09-21 (`10-deployment-and-activation-receipt.md`). The selection-study package (pages 7 to 9) is ACCEPTED (2026-09-19) and waiting for a
separate merge, deployment and activation approval; the collector is OFF. It holds the decision, the accepted findings with their evidence class, every correction to
the first package, the limitations, the blockers, the reproduction commands and the acceptance checklist.

| # | Deliverable | File |
|---|---|---|
| 8 | Decision sheet | `00-decision-sheet.md` |
| 1 | Corrected baseline and actual-fill reconciliation; proxy validation; drawdown-monitor interpretation | `01-baseline-and-fill-reconciliation.md` |
| 2 | Versioned input and coverage manifest | `02-input-and-coverage-manifest.md`, `results/manifest_all_base_s0_proxy.json` |
| 3 | Corrected pricing harness and boundary regressions; what changed; what had been examined before each registration | `03-pricing-harness-corrections.md`, `harness/realmodel.py`, `harness/test_pricing_boundaries.py` |
| 4 | Chronological opportunity and book attribution; the C1-versus-Control trace | `04-book-and-opportunity-attribution.md` |
| 5 | Revised statistics and the nine variant verdicts | `05-statistics-and-variant-verdicts.md` |
| 6 | Source-grounded author comparison | `06-author-comparison.md` |
| 7 | Frozen prospective selection-study specification (registration `s1-r4`, final before activation) | `07-selection-study-spec.md` |
| 10 | **Release handoff: registration `s1-r4`, lifecycle, endpoint, frozen final sample, tests, deployment / activation / rollback, monitoring, verdict** | `09-release-handoff.md`, `backend/zargar/techniques/team2/selection_study_lifecycle.py`, `backend/tests/test_team2_selection_lifecycle.py`, `backend/tests/test_team2_selection_e2e.py` |
| 9 | The default-off, order-free, passive collector, the frozen analysis, the regression packet and the suite results | `08-collector-package.md`, `backend/zargar/techniques/team2/selection_study.py`, `selection_study_analysis.py`, `backend/zargar/tools/team2_selection_study.py`, `backend/tests/test_team2_selection_study.py`, `test_codex_team2_collector_boundaries.py`, `test_team2_selection_analysis.py` |
| A | Method-fidelity matrix from the first pass (built from the capture index; page 6 supersedes it where they differ) | `appendix-A-method-fidelity-matrix.md` |

Kept for the record and NOT current: `history-v1/` (the first package's documents), `harness/v1/` and `results/v1/` (its harness and
numbers). The registrations are in `../2026-09-19-profitability-preregistration.md` and were not edited in this pass.

Four kinds of number are kept apart everywhere: actual Practice fills; real trade prints; simulated execution on real prints;
historical quotes (none exist for options, none is used).
