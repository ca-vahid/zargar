# EM response to the September 17 profitability and LLM review (packages A-D)

Review answered: `C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-17-EOD-PROFITABILITY-AND-LLM-REVIEW.md`
(reviewer direction: reduce blanket LLM spending, measure executable profit giveback, test selective profit protection while
preserving large winners; no trading rules or runtime settings changed by the reviewer). Everything below is order-free
research or evidence validation; nothing arms, trades or changes a Practice rule. Built 2026-09-17 evening on the EM
branch `claude/technique-review-trade-plan-fbb9ba` on top of main 0.8.11.

## Headline numbers (one session, 2026-09-17; nothing here is a verdict)

| Item | Result |
|---|---|
| Actual EM Practice day | +$222.65 net of fees, six fills, 3 winners / 3 losers, largest ORCL +$250.92 (the report's realized column: +$239.29 before the book's marking basis) |
| ORCL fill validity (A) | NOT robust live evidence: limit 2.29 accepted at 13:32:01Z against 2.10/2.29; filled at 1.12 at 13:32:09Z on an OPRA snapshot 0.76/1.12 (38% of mid, sizes 202/66); the contract's own 09:32 ET 1m bar traded 2.48-2.88 (Yahoo) while the underlying ran 147.29 -> 148.97. Sensitivity: a 2.29 fill would have made about +$134 instead of +$250.92 -> the day about +$106. The ledger row is unchanged and flagged; no replacement fill is fabricated. Likely mechanism (Tips desk pointer, E17-01 / PR #201 in main 0.8.11): the quote cache recentred a fresh OPRA band on a stale chart-feed `last` (the contract's stale 09:31 print) while keeping `source=opra`; since 0.8.11 such a transformed quote is `derived:` and the simulator refuses it - the 09-17 fill predates that fix. EM grading labels the +$250.92 apart, as Tips did for MRNA. |
| Prep ablation (C, zero paid calls) | pre-open mirror matched the live re-plan decision on 62 of 63 plans judged live. A (model-selected, 58 plans): 11 replay fills, 4 W / 7 L, +2.87 R. B (any deterministic valid trigger, 110): 16 fills, 5 W / 11 L, +2.10 R. The model's 53 vetoes removed 5 fills worth -0.77 R in total, at 4.25 M input / 1.66 M output / 2.09 M cache-read tokens for the 111 reads. |
| What the model's vetoes were | 22 "R:R to TP3 below 3.0" (our gate measures R2 at TP2), 17 level provenance (one-touch / not in the merged levels), 7 manufactured pct-ladder targets, 4 level too far from the close, 3 volume floor. 43 of 53 are reproduced by a simple deterministic feature of the trigger the model NAMED. In 36 of 50 named vetoes the named trigger is one the plan builder had ALREADY marked invalid: the model argued about a declined idea while a different valid trigger was the arming candidate. |
| Cohort C as frozen | Worse than A (30 plans, 5 fills, -4.76 R): the anchored-target and touches features exclude the day's winners (ORCL, SCHW, ARM). Reported, not adopted. The exception features are not a proxy for the model's selection. |
| P-06 runner protection (B) | Frozen definition in `research/PROFITABILITY-COHORTS-2026-09-15.md` (addendum 2026-09-18). First rows: SCHW `compared` -$1.17 on 33 shares vs the close flatten; BMNR `underlying_proxy_only` +2.01 R on the underlying vs the later stop, premium unknown. |
| BMNR target trim (A) | Entry 0.86 / TP1 sale 0.80 on one contract = -$8.08 with fees; first-order payoff to TP1 $11.82 per contract (delta -0.5011 x 0.2358 x 100). Now visible per intent as `edgeAtTp1` (P-03 marker, never a gate). |
| Source coverage (D) | The 09:21 ET watchlist was EvaPanda's, not the EM author's; rows re-attributed, five conditional branches added with receipt time 13:23:03Z. AMZN / GOOGL `never_confirmed` (not misses); MRNA / MU `unknown` (no author target - R2 cannot be evaluated); TSLA `gated` (opened above the level; entry on the wrong side of the stop); SPX `unknown` (no index bars). The EM author's 09:06 livestream content is unavailable (no transcript). |

## Package A - make profit capture measurable first

Delivered now (evidence): the ORCL fill discontinuity analysis above (`tests/test_em_sim_option_spread.py` reproduces the
shape) and the BMNR friction analysis (`edgeAtTp1` in `tools/em_profitability.py`, report `research/profitability/2026-09-17.md`).

Built, OFF, proposed for activation (a simulator EVIDENCE guard, not a cancel/reprice policy): `brokers/sim.py`
`max_option_spread_pct` / config `sim_max_option_spread_pct` (default 0.0 = off). When on, an OPTION quote wider than the
cap (spread / mid) cannot price a resting-order fill; the order RESTS with a journaled `fill_waiting` reason and fills on the
next plausible book. Share orders are untouched (F-HOLD-01 keeps its own 5% cap). Tests: 3 (default off = 09-17 behaviour;
cap rests then fills at the limit; shares unaffected). Activation and the cap value (EM's entry spread threshold is a
natural candidate) are the user's decision; PLATFORM-RULES logged.

NOT built yet: the synchronized liquidatable book snapshot (realized net, covered bid liquidation, exit fees, quote identity,
remaining / pending quantities) around target / stop / protection decisions. It needs the shared portfolio and quote
layers (platform owner) and asynchronous recording so protective exits never wait on research I/O. The requirement stands
as written in the review; the 09-17 giveback ($161.63 from a marked peak) remains a marked number, not liquidatable profit.

## Package B - profit protection without sacrificing every big winner

P-02 retained unchanged. P-06 added as ONE prospective frozen alternative (definition above); evaluated offline from stored
bars and the journaled exits (`runner_protection`), no runtime observer needed because the rule is a bar-close rule. The
never-TP1 diagnostic and `edgeAtTp1` are descriptive. ORCL stays the mandatory regression against one-sided "earlier is
better" claims: on 09-17 the P-02 candidate at the TP1 bid (2.56) would have made +$141.92 against the actual +$250.92
(and both numbers inherit the doubtful 1.12 entry). Tests: `tests/test_em_runner_protection.py` (4).

## Package C - replace blanket model reviews with measured exception handling

Delivered: `tools/em_prep_ablation.py` (order-free; report `research/prep-ablation/2026-09-17.md` + `.json`;
tests `tests/test_em_prep_ablation.py`). Method: every saved promote read of the sheet -> the offline mirror of the live
pre-open judgement (journaled pre-market print for the 63 plans the runner judged live, Yahoo pre-market close for the rest;
rebuild from the saved bars snapshot when every trigger is dead) -> walk-forward replay with the plan's own thresholds and
volume profile. Veto reasons classified and checked against the deterministic feature of the trigger the model named.

Findings the reviewer asked for: the model's selection value on this session was +0.77 R for the whole spend; the vetoes
are mostly re-implementable as deterministic features, and a third of them argue about triggers the builder had already
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

`tests/test_em_prep_ablation.py` 4, `tests/test_em_sim_option_spread.py` 3, `tests/test_em_runner_protection.py` 4,
`tests/test_sim_share_session_and_spread.py` (Tips' F-HOLD-01, regression) 4, `test_technique_walkforward.py` lazy-render +
eager-render plan tests 2 - all passing on the private test database; import smoke green. Frontend build / check-release run
at the release bump (see the deployment record when it exists).

## Kept unchanged

Production Practice rules, thresholds, the 58-arm preparation flow, `shadow_exit_observe` / `shadow_p02_candidate` (ON, user
decision), the 8% friction marker as a marker, live gates. No batch rerun, no strategy activation, no trading-hours deploy.
