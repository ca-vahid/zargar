# Historical method-lab review - September 19, 2026

## Decision and revised goal

The user removed future-market evidence as a completion dependency. This report closes the historical evaluation step; the existing forward collector remains optional and its frozen rules are unchanged. Historical results do not establish profitability.

**Keep the current execution policy and quality ranking. Do not activate reclaim/pivot or lower volume/coverage gates from this sample.** The adjustments delivered here are historical-data recovery, six-model comparison, preservation of old context flags, and source/evidence reporting. No production trading change is justified by the measured outcomes.

## Scope and reproducibility

Read-only repeatable-read snapshot, September 8-18, Options Cartel Practice. Latest preparation completed before each open; cited reused analyses included. Original short sessions remain short and are not synthesized into long winners. Earlier industry-prefiltered listings are unavailable. Research candidate selection uses the saved daily analyses and saved preparation policy through the current deterministic reviewer, so it is a retrospective reconstruction, not the original armed list.

55 native SIP history requests completed pagination. Request bounds and response hashes are in evidence.json. Retained-cache-only results were too incomplete; the final report uses freshly retrieved retrospective native bars for all 69 candidate-days. Twelve have every regular-session minute bar; absence of a bar is not proof that no trades occurred. No absent-minute prices/volume or historical availability were invented.

The six entry variants share each candidate tape. Volume baselines use only sessions completed before its daily source cutoff. 5m and 15m use separate same-time baselines. The model definitions and comparisons were chosen after these dates: exploratory, not held-out validation.

| Model | Candidate-days | Confirmations |
|---|---:|---:|
| breakout_5m_v1 | 69 | 4 |
| breakout_15m_v1 | 69 | 3 |
| undercut_reclaim_5m_v1 | 69 | 0 |
| pivot_30m_5m_v1 | 69 | 1 |
| undercut_reclaim_15m_v1 | 69 | 0 |
| pivot_30m_15m_v1 | 69 | 0 |

Breakout trace counters and shadow trace counters use different event definitions; they must not be compared as rates. Zero reclaim confirmations does not prove the model has no edge: missing buckets, session-stop coverage and volume refusals constrain interpretation. Confirmations are not proof of an eligible option or an actual order. BOX on September 15 was under a mixed-market preparation and remains research only.

## Selection comparison

Use the same historical long denominator and breakout_5m_v1 confirmation; select up to five per session. There are 26 selected candidate-days per ranking.

| Ranking | Confirmations in selected list |
|---|---:|
| quality | 3/26 |
| nearest | 2/26 |
| liquidity | 2/26 |
| compression | 2/26 |
| leadership | 2/26 |

This does not support replacing quality with proximity. The earlier 6/15 versus 4/15 result counted price touches in a different mixed long/short sample; it was not a confirmation or profitability comparison. Theme/leadership is an industry proxy, not a verified catalyst.

## Economics: same-day share scenarios, not option returns

Assumptions: $500 cash per independent scenario; whole shares; 2 basis points slippage per fill; zero per-order share commission. These are explicit modeling assumptions, not verified historical cash or venue liquidity. Overnight outcomes, queue effects and option expiration are outside this study. Native candles are evaluated sequentially; no future daily low supplies the entry stop.

| Session | Symbol / model | Saved-exit share outcome at session end |
|---|---|---|
| 2026-09-09 | SPCX / pivot_30m_5m_v1 | closed: $-3.34 |
| 2026-09-09 | VG / breakout_5m_v1 | open: $4.40 (includes unrealized mark) |
| 2026-09-14 | APA / breakout_5m_v1 | closed: $-7.53 |
| 2026-09-14 | APA / breakout_15m_v1 | closed: $-7.53 |
| 2026-09-14 | OKTA / breakout_5m_v1 | open: $11.46 (includes unrealized mark) |
| 2026-09-14 | OKTA / breakout_15m_v1 | open: $8.06 (includes unrealized mark) |
| 2026-09-15 | BOX / breakout_5m_v1 | incomplete: unknown |
| 2026-09-15 | BOX / breakout_15m_v1 | incomplete: unknown |

Do not sum correlated variants as separate trades. The only closed saved-exit scenarios are losses; positive VG/OKTA values include open positions. BOX saved-exit outcomes are incomplete. Alternate 60-minute and failed-break exits are included in evidence.json, but this small, selected sample cannot justify choosing an exit after seeing its winners.

Options remain unknown: matching historical contract, entry/exit bid/ask, size and fee evidence was not supplied. No stock-return-to-option-return conversion is used. Pass remains zero cost/zero capital. Actual Practice accounting is separate from every value above.

## Gaps and keep/change/reject verdict

- **Keep:** quality selection and current entry/risk permissions; no demonstrated after-cost challenger advantage.
- **Change delivered:** historical evaluator now uses verified provider identity, complete pagination, exclusive request boundaries, latest pre-open lineage, legacy context compatibility, independent timeframe baselines and explicit modeled economics.
- **Reject:** treating more price touches as profit, treating missing bars as zero-volume minutes, or declaring open marks realized profits.
- **Optional further historical work:** validate non-emission evidence where available; obtain archived option quotes for the exact candidate contracts; extend swing outcomes beyond the entry session. These are named limits, not a wait for future market sessions.

## Reproduction

Run from the owned backend directory with CARTEL_AUDIT_DATABASE_URL set locally to the runtime read-only connection target. The tool enforces read-only transactions. Read credentials in place; never copy the runtime .env.

```powershell
./.venv/Scripts/python.exe -m zargar.tools.cartel_historical_lab --start 2026-09-08 --end 2026-09-18 --portfolio 0b48ed48de2f4030b49942b52858356d --env-file C:/Cursor/zargar/backend/.env --output <local-output.json>
```

Validation: five focused tests, Ruff F and diff check. Tests cover pre-open selection, conflicting minutes, legacy refusal preservation, independent baselines and modeled costs, pagination completeness and request-end exclusion. No engine start, order, setting, arm or runtime table write was performed.
