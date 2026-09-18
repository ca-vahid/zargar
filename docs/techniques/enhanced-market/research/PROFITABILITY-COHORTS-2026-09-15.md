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


## Addendum 2026-09-17 (`p04-p05-2026-09-17`, supersedes the 2026-09-16 draft after the PFU-02/03 review)

Order-free report cohorts. They change no entry or exit rule, no risk limit, no chase limit, and the 8% friction marker
stays a ranking marker. Every EM attempt is counted: fills, rejected opportunities (refused rows: budget bounds, not
chased, contract failures) and `underlyingTp1FirstRefused` (refused rows whose underlying-only proxy reached TP1 before
a stop close - an underlying fact, NOT a net winner and NOT a "sacrificed" trade; only a paired policy comparison can
attribute a sacrifice, and option outcomes without a quote stay unknown).

**P-04a - entry strata (DESCRIPTIVE).** P-01 attempts split by the FIRING bar's close: `anticipated` = touch entry (the
bar closed on the wrong side of the level), `observed_reclaim` = the firing bar closed on the trade's side, `unknown` =
no firing bar. The 2026-09-16 draft claimed this answers whether waiting for confirmation saves stops at the cost of
winners; it does not - it never constructs the delayed entry. That claim is WITHDRAWN. The strata stay as a description.

**P-04b - PAIRED confirmation comparison, a GEOMETRY-ONLY UNDERLYING PROXY (frozen 2026-09-17, corrected after the
re-review).** On the SAME eligible setups (every P-01 attempt, fills and refusals), baseline = the actual touch attempt;
variant = wait for the first COMPLETED 1m close beyond the level within 10 bars AFTER the touch bar (the touch bar itself
never qualifies as the confirming close - a firing bar that closed beyond the level is the `observed_reclaim` stratum and
the variant still waits for the next completed close), enter at the OPEN of the following bar (no same-close hindsight
fill), re-run the GEOMETRY gates only from the new entry (stop side, room to TP1, R2 >= 3.0 at the exit rung TP2 - a
frozen copy of the bar, never read live), then follow the underlying FROM THE ENTRY BAR inclusive: TP1 touch vs stop
close, first come. NOT evaluated, and therefore unknown for every variant row: quote quality / freshness, premium sizing
and the quantity-dependent exit rung, the never-chase cap, timing windows, admission and daily-loss budgets. A variant
row is never an admitted entry. Distinct outcomes:
`no_confirmation` (a full 10-bar window observed, or the session ended), `pending (horizon incomplete: n of 10 bars
observed)` (fewer bars available and the session not over - never counted as a non-confirmation), `refused_stop_side`,
`refused_no_room`, `refused_r2`, `unknown (...)` (bar gap, no executable bar, same-bar target and stop - the entry minute
included), `tp1_first` (+room/risk R, full-size underlying proxy), `stop_first` (-1R), `unresolved`. A budget refusal of the baseline and a missed confirmation of the variant are different outcomes
and are reported as such. Dollars at the delayed entry are UNKNOWN for options (no quote captured at that time); for
shares the underlying R applies. Both baseline winners and losers stay in the paired sample. Descriptive until >= 30
paired rows; nothing is activated by it. First corrected results (2026-09-15/16, 14 attempts): `refused_r2` 11, `no_confirmation` 1, `stop_first` 2 (-1R each on
the underlying proxy); baseline winners/losers kept 2/7; option dollars at the delayed entry unknown for 10 of 14. The
earlier sentence "waiting for the close costs room faster than it saves stops" is WITHDRAWN: two retrospective sessions
of a geometry-only proxy are exploratory and support no statement about the policy.

**P-05 - session-window / event-phase cohort (frozen 2026-09-17).** Every EM attempt keyed by (window, event phase):
the window comes from the shared clock `marketstructure.sessions.session_window` on the timezone-aware fire time
(`sessions-v1`: prime_open 09:30-10:30, midday 10:30-14:45, prime_close 14:45-16:00 ET; 10:45 ET is midday, never
"afternoon"); the runner's own window label at fire is kept beside it as a diagnostic. Event phase comes from a
hand-kept calendar in the tool (`EVENT_CALENDAR`: date -> label, ET clock time, source, retrospective flag; the app's
macro calendar is empty) and is `pre_event:<label>` / `post_event:<label>` around that time, or `unknown_calendar` when
the date has no entry - never silently "ordinary". Entries added after a session are marked retrospective; prospective
definitions are frozen before new sessions are collected. These labels never activate a trading-window change.

Tests: `tests/test_em_profitability_p04_p05.py` (strata rename, paired comparison semantics, refusals distinct, no
same-close fill, baseline block intact, 10:45 = midday, pre/post split, unknown calendar).

## Addendum 2026-09-18 (`p06-2026-09-18`, the 2026-09-17 EOD review's package B)

**P-06 - `tp1-reclaim-runner-exit-v1`, PROSPECTIVE runner protection (frozen 2026-09-18 before any result was read).**
On the SAME entry, instrument and quantity: after a COMPLETED production TP1 trim, the runner is retained unless a
completed 1m bar CLOSES back through the saved TP1 (long: close < TP1; short: close > TP1); the candidate then exits the
remaining quantity at the NEXT bar's OPEN. Compared with production's final exit on the same remaining quantity, referenced
to the close of the bar containing the production exit. Shares are compared in dollars; options in underlying-R only
(the premium at the modeled exit is UNKNOWN without a covered observation - never substituted). The original stop before
the trim is untouched; one-contract positions that cannot trim are a separate cohort (`not_eligible`), never doubled to
manufacture a runner. TP1 is the plan's saved first target at arm time - no threshold is chosen from an observed path.
Outcomes: `compared` (shares), `underlying_proxy_only` (options), `not_triggered`, `not_eligible`, `partial` (runner open at
the cutoff), `unknown (...)`. Descriptive until >= 30 eligible rows. The offline evaluator is
`em_profitability.runner_protection`; a runtime observer is NOT built - the bar-close rule needs no quote observation.

**Never-TP1 diagnostic (descriptive).** Every closed position WITHOUT a TP1 trim (single-contract full exits included,
winners and losers alike): best underlying excursion in R during the completed holding minutes versus the exit. No
trailing percentage or giveback threshold is derived from it, and the day's marked equity peak is never used as a
liquidatable high-water mark.

**TP1 edge after friction (P-03 marker).** `edgeAtTp1 = payoffToTp1 - hurdle` per intent: the first-order premium move
at the plan's TP1 (signed delta x signed move x qty x 100) minus the concession-plus-round-trip-fee hurdle. BMNR 09-17: one
contract's TP1 sale lost $8.08 with an $11.82 first-order payoff - a thin cushion, not a payoff prediction. A marker,
never a gate.

First rows (2026-09-17, exploratory): P-06 SCHW (shares) `compared` -$1.17 on 33 shares versus the close flatten;
BMNR (puts) `underlying_proxy_only` +2.01 R on the underlying versus the later stop, premium unknown. Two rows say nothing.

**P-06 accounting after ED-02 (2026-09-17 evening; supersedes the paragraph above where they differ).** Eligible only
after a CONFIRMED TP1 fill (executions of the trade instance's tp1 exit order; a cancelled or pending trim is not a trim).
The remainder = original fill minus every execution at or before the signal (partial and intermediate trims reduce it).
Signal = the first 1m bar completed after the TP1 fill (the fill minute's own bar included) whose close is back through the
saved TP1, over consecutive minutes (a gap = unknown), inspecting only bars completed before production's next runner
fill (a stop or trim that filled first wins: `not_triggered`). Candidate = the remainder sold at the first fresh COVERED
executable quote after the signal when a runtime `tp1-reclaim` observation exists (options; dollars = k x (bid - fill) x m
- actual entry fee - modeled exit fee); otherwise the next bar's open is an UNDERLYING PROXY for shares and options alike
and no dollars are stated. Production = the remainder's actual fills after the signal (VWAP, allocated fees) to its
terminal event; options compare underlying to underlying (the close of the bar containing production's first runner fill).
A remainder still open at the cutoff is `partial`. Runtime observer: `PlanRunner._reclaim_capture` (behind
`shadow_exit_observe`, same evidence rules as shadow-exit-v1, enqueued, never awaited ahead of protection). The 2026-09-17
SCHW dollar comparison stated earlier is WITHDRAWN; both 09-17 rows are `underlying_proxy_only`.

**P-06 after the ED closure re-review (2026-09-17 late; supersedes the two paragraphs above where they differ).**
(1) Observer: the reclaim SIGNAL is persisted on the trade once (bar, close, TP1, remaining; survives a restart) and the
quote watch then seeks the FIRST fresh, adequately covered contract quote on subsequent observations; an unscorable
sample (stale, absent, thin depth, stop-first, pending exit) is recorded once as raw evidence under its own key and never
consumes eligibility; a signal is never set while an ordinary exit is working. (2) Reducer: a chronological walk over the
trade instance's confirmed executions and completed bars up to the cutoff - eligibility opens at the FIRST TP1 fill (a
later partial fill never moves it), the remainder is updated as later trims fill (an intermediate TP2 trim does not end
the evaluation), a fill that empties the runner ends it (`not_triggered`), a working ordinary exit at the cutoff is
`partial` (a later sale is never assumed), executions after the cutoff are ignored. (3) Validator
(`validate_observation`, strict, shared-capable): trade instance, contract, the observation's own signal identity,
chronological quote/observation times, disposition `observed`, coverage >= remainder, lifetime 15 min after the signal,
cutoff and position close - a missing field fails; the EARLIEST valid observation wins, rejections are listed with
reasons. Dollars are OPTION-ONLY (shares are proxy-only even with an observation - disclosed); until an observation
passes in production every P-06 row is `underlying_proxy_only` or unavailable. P-02 collection and reducer unchanged.

**P-06 partial-depth rule (2026-09-17 late, reviewer follow-up).** The candidate sells the WHOLE remainder, so an observation
whose covered quantity is positive but below the remainder is RAW evidence (key `tp1-reclaim-raw`, recorded once) and the
covered key `tp1-reclaim` stays open for a later fully covered quote - both while the raw write is still queued and after it
is acknowledged. The reducer already rejected partial coverage; the observer now agrees with it. P-02's `tp1-candidate`
keeps its own quantity semantics (its reducer applies k; a depth >= k sample is covered on the first scorable sample).
