# EM profitability cohorts - frozen definitions (`profitability-cohorts-v1`, 2026-09-15)

Answer to the reviewers' profitability sweep (`reviews/profitability-sweep-2026-09-15/`, priorities P-01..P-03).
Everything here is ORDER-FREE research: nothing arms, sizes, trades, gates or changes a setting. The already-active
gap-day wait stays. No blanket early-profit rule, no broadened entries, no family switched off. Candidates stay
order-free until separately approved for activation. New sessions evaluate these definitions; the sessions that
motivated them (Sep 14/15) are examples, never evidence that a rule works.

Tool: `python -m zargar.tools.em_profitability report --date YYYY-MM-DD [--cutoff HH:MM]` (read-only DB; writes
`research/profitability/<date>.md` + `.json`). Tests: `tests/test_em_profitability.py`.

## P-01 setup selection - cohort `long_bounce_next_resistance`

| Item | Definition |
|---|---|
| Member | EM trigger `kind=bounce`, `direction=long`, SAVED first target basis `next_resistance` (from the plan, never re-derived). |
| Baseline | Every EM fill of the session, reported beside the cohort in the same table. |
| Removed trades | Baseline fills outside the cohort, listed by name with their net. |
| Missed winners | Cohort-eligible fires that produced no position (refused / contract-skipped), with the refusal and an UNDERLYING-ONLY proxy (`tp1_first` / `stop_first` / `unresolved` / `unknown (bar gap)`) - chart events, never dollars. |
| Strata | `confirmation` = `observed_reclaim` when the firing bar CLOSED on the trade's side of the level, else `anticipated`; `room` at the ACTUAL entry = (TP1 - entry)/(entry - stop): `<1R`, `1-3R`, `>=3R`, `behind`; `qty`; `sourceAligned` = symbol+direction present in the day's source ledger. |
| Money | Net realized from the book's executions (fees included); open positions carry paid premium + entry fees as exposure, never a mark. |
| Decision rule | Research prioritisation only. No family is switched off, no size changes, whatever the cohort shows. |

## P-02 small-position exits - `small-position-exit-v1` (SPX-1)

| Item | Definition |
|---|---|
| Eligible | Option position, ORIGINAL filled quantity <= 2, first PRODUCTION sale >= 2.0R from the intended entry (planned underlying geometry; for < 3 contracts the first production sale is the single-contract-exit rung). |
| Alternative | Identical entry, contract and quantity. Two contracts: sell ONE at the first fresh, covered, executable bid observed at or after the underlying touches the plan's TP1; the other contract stays on the production policy. One contract: the whole position at that observation. |
| Evidence | `TechniqueExitShadow` records with rung `tp1-candidate`, disposition `covered` (valid provenance, fresh timestamp, uncrossed book, KNOWN displayed size). The observer captures them only when BOTH `shadow_exit_observe` and `shadow_p02_candidate` resolve true for EM - both are False today. No observation = UNKNOWN. A candle high, a print or an underlying MFE is never a fill. |
| Accounting | `alternative = k x (bid - fill) x 100 - fees(k) + production realized on the retained contracts`; `delta = alternative - production`; `forgoneOnWinner = max(0, production realized on the k sold contracts - alternative on them)` - profit sacrificed on big winners is counted, not only givebacks avoided. Open production position = `partial`. |
| Separate experiment | Faster execution at UNCHANGED targets = `shadow-exit-v1` at the production rungs. Never mixed with SPX-1. |
| Not chosen after the fact | The TP1 level is the plan's saved first target at arm time. No threshold is picked from an observed path. |

## P-03 contract economics

| Item | Definition |
|---|---|
| Per intent (filled OR refused) | `friction = (fill or ask - bid at the intent) x qty x multiplier + round-trip fees`, as a share of paid premium (`hurdlePct`); first-sale distance in R; affordable quantity under the UNCHANGED risk budget (`floor(budget / (premium x 100 x premium_stop_pct))`). |
| Attainable payoff | `delta x (TP1 - entry) x qty x 100` ONLY when the contract snapshot carries a positive delta; the stored `0.0` means unknown and is reported unknown. `hurdle / payoff` is shown when both exist. |
| Ranking marker | `hurdlePct >= 8%` is flagged `thin`. It is a ranking marker declared here, never a gate; risk limits, the spread rule and the budget are unchanged. |
| Purpose | Identify proposals whose costs consume too much of the expected move; the full accepted + refused set is retained with its outcomes. |

## Per-session report contents

Baseline vs cohort (fills, closed, net realized, winners/losers, open count and exposure, largest winner, fees);
removed trades; missed-winner candidates with the underlying proxy; strata; P-02 table (outcome / production /
alternative / delta / forgone / why); P-03 table; explicit unknown counts. Chronological blocks accumulate across
sessions in `research/profitability/`.

## PF-01..03 and the entry-label correction (same day, reviewer packet `reviews/profitability-cohort-regressions/`)

| Item | Correction |
|---|---|
| PF-01 observation contract | The reducer consumes the observer's ACTUAL payload (disposition `observed`, `modeled.scorable` / `coveredQty` / `bid`, `observedAt`) as well as the documented shape, and binds each observation to the trade instance (entry order), the same contract and the position's lifetime; coverage below the alternative's quantity, pending/stop-first and wrong-time evidence stay unknown with the reason. The producer keeps the FIRST covered opportunity: an unscorable touch is recorded once as raw evidence (own key `tp1-candidate-raw`) and leaves the candidate eligible for a later covered observation. The production rung's first-raw-observation semantics are unchanged. |
| PF-02 fee conservation | The alternative's sold contract keeps its ACTUAL entry fee (allocated by filled quantity) and pays the declared modeled exit fee only on the hypothetical sale; retained contracts keep their ACTUAL per-contract result (entry and exit fees allocated per fill); production components must sum to the execution-backed net or the pair is unknown. Same price and exit cost = zero delta. Forgone-on-winner uses the same basis. |
| PF-03 economics | Every intent stays in the P-03 table (friction unknown with the reason when no quote was captured - the oversized share fallbacks included); `riskBudgetQty` is wired (risk % x book equity at the fire from `equity_points`, premium stop % from settings, default 50) and labelled a budget bound only; the payoff proxy is SIGNED delta x SIGNED move (puts included), unknown when delta is missing/zero/invalid. |
| Entry label | `roomPlannedR` = TP1 room from the plan's intended underlying entry; `roomAtActualEntryR` is unknown for every fill (no underlying observation at dispatch is recorded; an option premium is never plugged into underlying geometry). `sourceSymbolDirectionMatch` replaces "aligned": symbol + direction in the ledger only. |
| Status | P-02 and P-03 sections are PROVISIONAL in every report until the reviewers accept these corrections; both knobs (`shadow_exit_observe`, `shadow_p02_candidate`) stay False. No strategy conclusion is drawn from the all-baseline P-01 cohort. |

## What could be wrong

- The cohort is small and confounded with direction and family (the reviewers' own caveat); the report separates
  strata but cannot de-confound them.
- P-02 is unknown for every trade until the observer and the candidate knob are activated; the accounting is tested
  on synthetic observations only.
- `feePerContractSide` is read from the day's executions (commission / quantity); a fee schedule change shows up as a
  different observed value, not a silent constant.
- The underlying proxy for refused fires uses stored 1m bars from the firing bar onward, close-based stop, same-bar
  target+stop = unknown. It is a chart diagnostic and is labelled so.
