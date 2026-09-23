# EM prospective definitions - frozen 2026-09-19 (supersedes the 2026-09-18 file)

> SUPERSEDED 2026-09-19 by `PROSPECTIVE-DEFINITIONS-2026-09-19-R2.md` before any validation data was collected. Kept unchanged below as the record of what was frozen first.

Why a new file: the candidate review (`reviews/2026-09-18-INTEGRATED-CANDIDATE-REVIEW.md`, IR-01..IR-05) found defects in three
frozen versions BEFORE any validation data was collected. No collector had been switched on, so no sample is affected. The
2026-09-18 file is kept unchanged as the record of what was frozen then; this file is what governs from now on. The evaluation
horizon, the fixed research strata and the "what is NOT claimed" section of the 2026-09-18 file carry over unchanged.

## Frozen versions (replacing the 2026-09-18 table)

| Version | What it fixes | Where |
|---|---|---|
| `first-sale-v2` (was v1) | admission R = R to the GATE TARGET of the final quantity from the WORSE of the runner's entry and the validated current executable underlying bound (long: ask, short: bid; a fresh print only when no fresh two-sided venue quote exists; shares also bounded by their own limit); evidence = named source + venue time within `risk.stale_quote_seconds` + symbol identity + not halted; UNROUNDED comparison; the policy-defining pin comes from the plan's frozen run config; observe is non-authoritative; enforce fails closed (refuse / defer) and is re-decided synchronously in the final entry guard; an invalid mode refuses. Gate target and first production sale are reported apart; the multi-contract rule (TP3) is unchanged | `technique/first_sale.py` |
| `book-snapshot-v2` / `profit-capture-reducer-v2` (were v1) | quote evidence needs identity, a known admissible source, the venue QUOTE time, a regular session, finite two-sided prices, a known size AND size unit; displayed depth is spent once per contract/side across the whole book, pending exits first, positions in deterministic order; realized totals and per-trade attribution come from the session's EXECUTIONS as of the capture time; a ledger that is pending, in error or inconsistent with the held quantity is unscorable; capture ids are stable across retries; every observer instance is a distinct identity | `technique/profit_capture.py`, `profit_capture_runtime.py` |
| `candidate-pricing-v1` (new) | contract, quote, spread (10%), sizing (risk budget as a bound, Friday multiplier), budget (RiskGate premium caps + cash) and executable-price no-chase (`first-sale-v2` admission) on evidence captured within 3 minutes of the trigger; decided once, never back-filled; missing evidence = unknown | `technique/source_candidate_policy.py` |
| `em-prep-policy-v1`, `conditional-review-v1`, `capacity-v1`, `source-scenarios-v1`, `source-plan-match-v1`, `source-continuation-v1`, `requalification-v1`, `model-costs-v1`, frozen exception features | unchanged from 2026-09-18. `model-costs-v1` now reads the platform's one price setting `llm.rates` (owner review) | as before |

Cache identity of a preparation decision (clarified, IR-05): bars, as-of, thresholds, dataset, policy version + conditional-review
version, grade floor, mode, ORIGIN, the analyst review's verdict and reasons, source revision ids, scenario / correction ids and
source holds. A decision is reused only when every one of these is identical.
