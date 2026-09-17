# EM response to the September 17 profitability and LLM review (packages A-D)

Review answered: `C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-17-EOD-PROFITABILITY-AND-LLM-REVIEW.md`
(reviewer direction: reduce blanket LLM spending, measure executable profit giveback, test selective profit protection while
preserving large winners; no trading rules or runtime settings changed by the reviewer). Everything below is order-free
research or evidence validation; nothing arms, trades or changes a Practice rule. Built 2026-09-17 evening on the EM
branch `claude/technique-review-trade-plan-fbb9ba` on top of main 0.8.11.

## Headline numbers (one session, 2026-09-17; nothing here is a verdict)

| Item | Result |
|---|---|
| Actual EM Practice day | +$222.65 net after $16.64 commissions (+$239.29 gross before commissions), six fills, 3 winners / 3 losers, largest ORCL +$250.92 |
| ORCL fill validity (A) | NOT robust live evidence: limit 2.29 accepted at 13:32:01Z against 2.10/2.29; filled at 1.12 at 13:32:09Z on an OPRA snapshot 0.76/1.12 (38% of mid, sizes 202/66); the contract's own 09:32 ET 1m bar traded 2.48-2.88 (Yahoo) while the underlying ran 147.29 -> 148.97 - inconsistent with that minute's prints (a one-minute OHLC bar alone cannot prove a quote impossible). Sensitivity arithmetic, not a corrected fill or a new official P&L: a hypothetical 2.29 entry gives +$133.92 on the trade and +$105.65 on the day with the other fills unchanged. The ledger row is unchanged and flagged; no replacement fill is fabricated. Likely mechanism (Tips desk pointer, E17-01 / PR #201 in main 0.8.11): the quote cache recentred a fresh OPRA band on a stale chart-feed `last` (the contract's stale 09:31 print) while keeping `source=opra`; since 0.8.11 such a transformed quote is `derived:` and the simulator refuses it - the 09-17 fill predates that fix. EM grading labels the +$250.92 apart, as Tips did for MRNA. |
| Prep ablation (C, zero paid calls; ED-03 wording) | A descriptive UNDERLYING independent-replay comparison, not a measured economic value of the model: no option selection, executable fills, fees, shared capital or slot competition (unmodeled, unscorable as economics). Pre-open mirror matched the live replan-or-keep decision on 62 of 63 plans judged live (not full trigger/entry/exit parity - see the baseline funnel reconciliation in the report: live fired 12 / refused 5 / orders 15 / opened 6 vs replay fired 11 / filled 11, because the replay fills every fired trigger on the underlying). A (58 plans): 11 replay fills, 4 W / 7 L, +2.87 R. B (110): 16 fills, 5 W / 11 L, +2.10 R. Underlying independent-replay cohort difference A - B = +0.77 R under these assumptions, beside 4.25 M input / 1.66 M output / 2.09 M cache-read tokens for the 111 reads (never converted into a dollar return). |
| What the model's vetoes were | 22 "R:R to TP3 below 3.0" (our gate measures R2 at TP2), 17 level provenance (one-touch / not in the merged levels), 7 manufactured pct-ladder targets, 4 level too far from the close, 3 volume floor. 43 of 53 stated veto REASONS are reproduced by a simple deterministic feature of the trigger the model NAMED (that reproduces the reason, not the model's whole-plan eligibility decision). In 36 of 50 named vetoes (72%) the named trigger is one the plan builder had ALREADY marked invalid: the model argued about a declined idea while a different valid trigger was the arming candidate. |
| Cohort C as frozen | Worse than A (30 plans, 5 fills, -4.76 R): the anchored-target and touches features exclude the day's winners (ORCL, SCHW, ARM). Reported, not adopted. The exception features are not a proxy for the model's selection. |
| P-06 runner protection (B, ED-02 corrected) | Frozen definition in `research/PROFITABILITY-COHORTS-2026-09-15.md` (addendum 2026-09-18, ED-02 accounting). Bound to the trade instance's exit orders and their CONFIRMED executions; shares AND options are underlying proxies unless a covered `tp1-reclaim` observation exists (runtime observer added, order-free). The earlier SCHW dollar comparison is WITHDRAWN. First rows: SCHW `underlying_proxy_only`, BMNR `underlying_proxy_only` - no dollars. |
| BMNR target trim (A) | Entry 0.86 / TP1 sale 0.80 on one contract = -$8.08 with fees; first-order payoff to TP1 $11.82 per contract (delta -0.5011 x 0.2358 x 100). Now visible per intent as `edgeAtTp1` (P-03 marker, never a gate). |
| Source coverage (D) | The 09:21 ET watchlist was EvaPanda's, not the EM author's; rows re-attributed, five conditional branches added with receipt time 13:23:03Z. AMZN / GOOGL `never_confirmed` (not misses); MRNA / MU `unknown` (no author target - R2 cannot be evaluated); TSLA `gated` (opened above the level; entry on the wrong side of the stop); SPX `unknown` (no index bars). The EM author's 09:06 livestream content is unavailable (no transcript). |

## Package A - make profit capture measurable first (ED-01 / ED-04 corrected)

Delivered now (evidence): the ORCL fill discontinuity analysis above (`tests/test_em_sim_option_spread.py` reproduces the
shape) and the BMNR friction analysis (`edgeAtTp1` in `tools/em_profitability.py`, report `research/profitability/2026-09-17.md`).

Built, OFF, proposed for activation (a simulator EVIDENCE guard, not a cancel/reprice policy): `brokers/sim.py`
`max_option_spread_pct` / config `sim_max_option_spread_pct` (default 0.0 = off). ED-01 correction: the cap applies ONLY to
OPENING option orders, keyed on the order manager's position-derived `option_action` (BUY_TO_OPEN / SELL_TO_OPEN - derived
from the book's position, never from the side alone); a protective stop, flatten, reducing exit (…_TO_CLOSE) or an order of
unknown intent (None) is never capped and keeps every existing quote-quality check (finite uncrossed book, freshness,
delayed-chain and unknown-source refusal). The first predicate (any OPT order) is withdrawn. The knob is executor-wide -
every Practice book - so it is a platform knob, logged in PLATFORM-RULES. Tests: 6 (default off = 09-17 behaviour; entry
rests then fills at the limit; stop / flatten / reducing trim / short cover all fill on the aberrant book with the cap on;
unknown intent never capped while the delayed-chain refusal still applies; a non-EM opening order is capped the same way;
shares keep F-HOLD-01's own cap). Activation and the cap value are the user's decision; not activated.

NOT built: the synchronized executable-profit basket (ED-04). OWNER ASSIGNED: the EM desk (this session) owns the EM-book
measurement and its journal record; the Tips desk owns the shared quote-cache / portfolio-mark layer it reads (E17-01 is
theirs) and reviews the shared-code diff. Acceptance contract retained verbatim from the review: realized net, midpoint
mark, executable covered liquidation net (bid for longs, ask for shorts, size-limited), contemporaneous source identity /
timestamps / sizes, pending and remaining quantities, exit fees, explicit unknowns for uncovered or stale portions; captured
asynchronously (queue + bounded recorder, the shadow-exit pattern) so no protective exit waits on it; recorded before and
after target / stop / protection decisions; reconciled to fills without subtracting spread twice; stale or unknown-depth
quotes can never make a liquidatable high-water mark. Delivery: design + record shape first (next dev session, 2026-09-18
evening), then the recorder behind a knob OFF, then the offline reducer in the profitability report. Until it exists the
09-17 giveback ($161.63 from a marked peak) remains a marked number, not recoverable dollars, and no further trailing /
giveback policy is proposed ahead of it.

## Package B - profit protection without sacrificing every big winner

P-02 retained unchanged. P-06 added as ONE prospective frozen alternative (definition above). ED-02 correction: bars determine
the signal, quotes determine the modeled sale - so a runtime `tp1-reclaim` observation (order-free, behind the existing
`shadow_exit_observe` knob, same evidence rules as shadow-exit-v1, enqueued and never awaited ahead of protection) now
captures the remaining quantity's contract NBBO on the closed bar that signals; the offline evaluator binds to the trade
instance's exit orders and CONFIRMED executions, activates only after an actual TP1 fill, reduces the remainder by partial
and intermediate trims, inspects only bars completed before production's next fill (stop-first wins), treats a missing
minute as unknown, and compares against production's actual fills with allocated fees to the terminal event. Shares and
options are underlying proxies without a covered observation - the SCHW dollar figure is withdrawn. Cases tested: cancelled
trim, delayed / partial fill, refire (foreign executions ignored), intermediate trim, gap, stop-first, quote-unavailable,
covered observation, runner open at the cutoff. The never-TP1 diagnostic and `edgeAtTp1` are descriptive. ORCL stays the mandatory regression against one-sided "earlier is
better" claims: on 09-17 the P-02 candidate at the TP1 bid (2.56) would have made +$141.92 against the actual +$250.92
(and both numbers inherit the doubtful 1.12 entry). Tests: `tests/test_em_runner_protection.py` (4).

## Package C - replace blanket model reviews with measured exception handling

Delivered: `tools/em_prep_ablation.py` (order-free; report `research/prep-ablation/2026-09-17.md` + `.json`;
tests `tests/test_em_prep_ablation.py`). Method: every saved promote read of the sheet -> the offline mirror of the live
pre-open judgement (journaled pre-market print for the 63 plans the runner judged live, Yahoo pre-market close for the rest;
rebuild from the saved bars snapshot when every trigger is dead) -> walk-forward replay with the plan's own thresholds and
volume profile. Veto reasons classified and checked against the deterministic feature of the trigger the model named.

Findings the reviewer asked for, in ED-03 terms: the underlying independent-replay cohort difference A - B was +0.77 R
under the replay's assumptions (not measured selection value); the stated veto reasons are mostly re-implementable as
deterministic features of the named trigger, and 36 of 50 named vetoes (72%) argue about triggers the builder had already
declined. A deterministic-by-default preparation with the model reserved for source interpretation is therefore
technically supportable, but the exception set must be learned from more sessions than one - cohort C shows how easily a
guessed feature set removes the winners. Lazy rendering delivered for the one path that renders for nobody: a pre-open
re-plan (`trigger == "preopen_replan"`, deterministic, no model pass) renders no charts (45 re-plans x 4 charts on the single
render thread at 09:25 ET on 09-17); every other run keeps its charts and annotated map (test in `test_technique_walkforward.py`).
NOT built: a versioned preparation policy / audit-sample knob, cost accounting per read in dollars (usage categories are
recorded; the price table is not), caching by causal-input hash. Proposed order: two more sessions of the ablation first.

## Package D - source coverage without hindsight

`tools/em_source_candidates.py` gained `--author` (default `enhancedmarket`); the two 09-17 SPX rows were re-attributed to
EvaPanda (`authorCorrectedAt`), five EvaPanda branches added with conditions and the 13:23:03Z receipt time, the day
evaluated (`research/source-candidates-2026-09-17.result.json`). Strikes are not targets: the 7720C / 7580P mentions were
recorded as conditions, never as levels. The source-continuation / wedge cohort with its own confirmation, stop and window
conventions is NOT frozen yet (needs the author's own examples with numbers; two threads read by the reviewer are
historical). MRNA / MU / TSLA stay unresolved candidates; AMZN / GOOGL are non-triggered.

## Tests and checks on this tree

`tests/test_em_prep_ablation.py` 4, `tests/test_em_sim_option_spread.py` 6, `tests/test_em_runner_protection.py` 8,
`tests/test_sim_share_session_and_spread.py` (Tips' F-HOLD-01, regression) 4, `test_technique_walkforward.py` lazy-render +
eager-render plan tests 2 - all passing on the private test database; import smoke green. Frontend build / check-release run
at the release bump (see the deployment record when it exists).

## Kept unchanged

Production Practice rules, thresholds, the 58-arm preparation flow, `shadow_exit_observe` / `shadow_p02_candidate` (ON, user
decision), the 8% friction marker as a marker, live gates. No batch rerun, no strategy activation, no trading-hours deploy.
