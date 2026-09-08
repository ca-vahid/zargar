# Team2 independent review scratchpad

Opened 2026-09-08 for the user's dedicated Team2 review task.

## Charter

Review the reviewer team's end-of-day conclusions and proposed changes BEFORE implementation. Produce feedback the user can relay to the team: what is supported, what needs correction, what needs testing, and what evidence is missing. Daily review does not require daily parameter changes. Improved accuracy and profitability are objectives to test, not assumed outcomes.

This task covers independent review and documentation. Implementation, runtime changes, and delivery to a particular team channel require the corresponding user instruction. Keep Team2 findings separate from other techniques.

## Baseline inspected

- Folder: `C:/Cursor/zargar-codex`; branch: `codex/zargar-development`.
- Local HEAD: `96b67a1` on 2026-09-08; working tree clean before creating this file. This is a local code baseline, not proof of the review team's deployed version.
- Read the Team2 README, method specification, plan decisions/review checklist, judgement-log findings, rules/settings, and replay/sweep entry points. Some long documents were inspected in excerpts; this is initial familiarization, not a complete code audit.
- No runtime, database, broker, or effective runtime settings inspected. No trading code changed or tests run for this documentation-only setup.

## Method orientation

Casey / @Team2Trading method, implemented in its own `team2` namespace:

- SPY, QQQ, IWM; 0DTE calls/puts.
- Previous-day high/low zones and pre-market high/low lines establish location and scenarios.
- Extended-hours 2-minute EMA 13/48/200 structure; 15-minute close confirmation; pullback/retest and base entry variants.
- Location-based full/small/no-trade sizing, controlled re-entries and trim-and-add behavior.
- Premium trims, EMA/level exits, target exits, premium loss protection and same-day flattening.

Selected LOCAL CODE DEFAULTS, not confirmed settings for any trading session:

| Field | Default |
|---|---|
| Entry / last entry / flatten (ET) | 09:45 / 15:30 / 15:45 |
| Entry types | `both`, EMA48 and EMA200-flush enabled |
| Pullback touch limit | 2 |
| Premium target / floor / pick | 0.60 / 0.20 / `closest` |
| Chase cap multiplier | 1.5 |
| Premium stop | 25%; live settings specify mid basis and 3-tick minimum |
| Trims | +50% and +100%, approximately one third each |
| Max adds / concurrent positions | 1 / 1 |
| Loss limit | 2, desk-wide |
| Shrink after win | enabled |
| Default mode | alert; deployed mode unknown |

## Source map

- `METHOD.md`: author-derived rules and historical versions; source references in `SOURCES.md` and `notes/`.
- `PLAN.md`: design decisions, assumptions and unfinished work.
- `TRADING-RULES.md`: reviewer findings and change history. Historical entries may have later fixes; read the complete finding and subsequent change log before treating it as open.
- `backend/zargar/techniques/team2/rules.py`: rule values and settings mapping.
- `backend/zargar/settings_service.py`: application defaults; these do not establish persisted settings.
- `backend/zargar/techniques/team2/session.py`: pure session read/simulation.
- `backend/zargar/techniques/team2/runner.py`: live execution integration.
- `backend/zargar/techniques/team2/service.py`: run snapshots, replay and sweep.
- `backend/zargar/tools/team2_sweep.py`: CLI using the running API. Do not invoke mutation-capable commands simply to familiarize with the method.
- `backend/tests/test_team2_*.py`: implementation checks, to inspect as proposals require.

## Known review hazards

1. Documentation drift: older plan rows mention 16:05 flattening, while current local defaults specify 15:45. Old status notes also predate later implementation. Confirm the deployed commit and effective settings.
2. Session provenance: historical findings F12/F13 describe thresholds and completed-plan snapshots diverging from what ran. A replay must reconstruct the day's actual rules, plan, bars and intraday changes.
3. Premium provenance: modeled option returns, alert outcomes and executed portfolio P&L are different evidence. Check actual contract, bid/ask/mid basis, fees, fill timing, partials and adds. A sum of per-trade premium percentages is not an account return.
4. Operational confounders: missing bars, stale quotes, halts, refused orders, portfolio ownership and unsettled exits can explain results without a method defect. Historical findings include these issues; verify their status for the reviewed deployment.
5. Sweep comparability: replay loads saved thresholds; sweep builds its base from current settings. Pin an explicit baseline and compare identical data/date ranges. Confirm IV source and timestamp, warm-up bars, coverage and desk-wide constraints.
6. Outcome bias: keep the day's proposed changes separate from validation evidence. Evaluate losses introduced and winners removed, not only losing trades that a new filter would avoid.

## Intake for each day's review

Start with the team's report and exact proposed changes. Request missing details only where they affect the conclusion:

- Session date in ET, deployed commit/version, portfolio/mode, effective settings and any intraday changes.
- Per-proposal old value/behavior -> proposed value/behavior, rationale, affected rule/file and expected effect.
- Scorecard: signals, accepted/skipped/refused entries, fills, wins/losses, net P&L after costs, risk/exposure and open/unsettled positions. Separate actual fills, Practice fills, alerts and model results.
- Supporting run/trade IDs, timelines, traces, option quotes/fills and underlying bars for examples driving the proposal. Include missed opportunities and no-trade days where relevant.
- Baseline-versus-variant results with date range, data coverage, sample count, costs, IV assumptions, settings and any untouched validation sessions.

Screenshots may explain a setup; structured exports and exact setting changes make results reproducible. Do not request credentials or copies of another checkout's private database.

## Review method and feedback format

For each proposal:

1. State the claim and classify it: data/execution defect, deviation from documented method, or new strategy hypothesis.
2. Verify the causal chain from information available at the decision time through signal, gate, order, fill and exit. Check closed-bar timing and look-ahead.
3. Assess evidence and sample limitations. Compare net expectancy, drawdown/tail loss, exposure, trade count and opportunity cost alongside win rate.
4. Check method fidelity and execution/replay parity; identify shared-engine impact and required regression checks.
5. Recommend **support**, **revise**, **experiment only**, or **hold pending evidence**, with confidence and a precise reason.
6. Specify validation and rollback criteria before implementation; favor a small isolated variant and untouched sessions for strategy changes.

Return a concise team-ready note: overall assessment, prioritized findings, per-proposal verdicts, required evidence/tests, and unresolved questions. Record subsequent decisions here; do not silently rewrite the team's method or judgement log.

## Daily ledger

| Session | Review received | Proposals | Feedback | Decision / follow-up |
|---|---|---|---|---|
| Session date not explicit; received 2026-09-08 | First-clean-day report: Practice net about -66, two QQQ puts | F50, F47, F61, F62, F56, F51, F49; F63 and recurring outage | [Independent feedback](notes/research/2026-09-08-review-feedback.md) | Support scoped correctness work; revise target exit and touch semantics; hold target-skipping and broad PM-range bypass; no implementation authorized |

## Next step

User provides today's review outcome. Identify the deployed baseline and analyze the proposals against their evidence. Preserve other checkouts and runtimes; any needed tests use only the Codex-isolated test workflow.

## Author study completed 2026-09-08

The user asked for a comprehensive understanding of Casey's public method before discussing the review. See [AUTHOR-STUDY.md](AUTHOR-STUDY.md) and its [evidence ledger](notes/research/2026-09-08-author-study-evidence.md).

Read all 49 existing X source notes and both captured video transcripts; studied five older unrolls previously omitted, latest September public guidance, and 16 original chart images. Read the architecture document and platform invariants for targeted implementation comparison. Full historical-feed coverage and unverified contract/discretion details are explicitly not claimed.

Main review distinction: explicit author principles, behaviors demonstrated in recaps, and Zargar's mechanical choices must remain identifiable. Fixed touch limits, exact trim fractions, account-risk formulas and cutoff times are not automatically author rules. Judge proposals for both method fidelity and independently measured results. No trading code or runtime settings changed.
