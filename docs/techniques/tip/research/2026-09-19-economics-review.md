# Tips economics review - does Tips Practice have a viable edge after execution and model costs? (2026-09-19)

Scope: Tips Practice book `4611946d…` since its 2026-09-08 reset, through the 2026-09-18 session (9 trading
sessions). Shadow research books are reported apart and never summed. Every trading figure reconciles to
executions and persisted equity; every model dollar is a list-price ESTIMATE from `llm.rates`, not an invoice.
Generated outputs beside this file: `economics/scorecard-2026-09-08_2026-09-18.md` (tips-scorecard-v1),
`economics/review-gate-retrospective-2026-09-09_2026-09-18.md` (review-gate-v1),
`economics/entry-horizons-2026-09-11_2026-09-18.md` (entry-horizons-v1).

**Short answer: unattractive as it stands.** Trading lost money before operating cost, and the model spend is
about half the trading loss again. There is no evidence of selection skill. The analyst's takes did not beat its
skips on the same fixed horizons. The one strong, repeated signal is a LOSS signal: short-dated tip options held
overnight lose heavily, and the desk's losses are concentrated there.

## 1. Reconciled scorecard (2026-09-08 .. 09-18)

| Line | Amount | Basis |
|---|---:|---|
| Method realized, after allocated fees | **-$939.11** | FIFO lots (census engine); fees inside it $112.32 |
| Questioned fills (graded apart) | -$97.41 | MRNA 165C +$112.92 (quote provenance), APLD 30C -$210.33 (option filled at 04:01 ET, before sim_option_sessions) |
| Bookkeeping repair | -$9.16 | RKT 59-share oversell by a venue stop, repaired by a tagged manual buy |
| Open positions, mark minus cost | +$15.34 | ACHR 7C x3, AAL 14C x2, SBLK 62 sh at the 09-18 close |
| Entry fees on open lots | -$5.20 | paid, not yet in realized |
| **Marked equity change** | **-$1,035.54** | $10,000.00 to $8,964.46; the identity closes with a $0.00 residual |
| Model operating cost, priced | **-$494.59** | list-price estimate; lower bound (see coverage) |
| **Net after model cost** | **about -$1,530** | trading marked change plus priced model cost |

Reconciliation: cash rebuilt from executions equals persisted cash at every session close (largest difference
$0.00). Start + all realized + open mark - open-lot entry fees = persisted equity exactly.

Model cost coverage (cumulative):

| Stage | Priced $ | Coverage |
|---|---:|---|
| Intake reviews | 377.35 | 90 stamped + 463 from the review run's own model field; 3 runs unpriced |
| Appraisals | 90.32 | 11 stamped + 120 run-record; 3 unpriced |
| Retros | 12.18 | all priced |
| Extraction | 12.17 | nightly stage rollup only - a LOWER bound (restarts lose counters) |
| Rule audits | 2.24 | 7 of 8 runs unpriced (1.38M input tokens), 39 unknown calls, 7 partial runs |
| Digest, transcription | 0.33 | 9 digest runs unpriced |

Unpriced input tokens, about 2.3M in all, would add roughly $12-15 at the Opus 5 list rate (illustrative, not a
priced figure). No journaled change of the analyst model exists, so "run-record" attribution is the model the
loop itself recorded, not an inference from today's settings.

Where the money went, by how each closed position ended (19 positions, net of fees; RKT corrected to its method
result -$30.15, its repair apart):

| Exit | Positions | Net |
|---|---:|---:|
| Premium stop, bleed or stop in the first seconds of a session (all held overnight) | 6 | **-$999.09** (incl. questioned APLD -$210.33) |
| Premium stop or bleed during the session | 3 | -$269.71 |
| Underlying stop | 4 | -$123.79 |
| Analyst mirrored the source's exit | 3 | +$25.38 |
| Target reached (GOOGL) / venue stop after TP1 (RKT) | 2 | +$217.85 |
| Questioned MRNA 165C | 1 | +$112.92 |

Positions held overnight: 12, net -$783.67. Closed the same session: 7, net -$252.69.

## 2. Ranked findings

1. **Short-dated options held overnight are the loss centre** (economic importance: high; confidence: moderate).
   Three independent views agree. Practice: overnight-held positions -$783.67 against -$252.69 same-session;
   six first-seconds exits -$999.09. Fixed horizons on every entry-study contract (takes and skips, n=41 paired):
   session close to next close median -22%, only 12 of 41 up; 5-14 DTE contracts median +2% at the session
   close, then -32% by the next close (8 of 29 up). Hold study: Practice short options carry -$97.16 on 2 adequate
   pairs; shares carry +$183.23 on 3. Limits: print evidence, not NBBO; 9 sessions; one market regime.
2. **Opening-seconds premium exits sell at stub quotes** (high; moderate). Of the six first-seconds exits,
   three sold far below trades minutes later: DAL 1.53 vs 2.03 from 09:34; HIMS 0.21 vs 0.40-0.47 within six
   minutes; CCXI 0.20 (12 lots) vs 0.60 and 0.50 within 15 minutes. SMCI (0.98) beat that day's close of 0.68 and
   GS was mixed. The two-observation confirmation (since 09-12) does not help at the open: two distinct opening
   quotes arrive within seconds and the long mark is the bid.
3. **Model spend is mostly intake reviews that change nothing** (high; high). 556 reviews cost ~$379 (09-09..18).
   498 only saved a note; 51 called a management tool. A per-ticker relevance check would have skipped 186
   reviews ($121.83, 32%) with ZERO management actions lost (retrospective, same evidence). Built and live in
   observe mode (below).
4. **No measurable selection skill** (high for the economics; low confidence in either direction). On identical
   horizons from the decision's own ask: takes +30 min mean +8% / session close +3% / next close -35% (1 of 12
   up); skips +6% / +8% / +5% (median -25%). Takes did not outperform skips. n is small (12 vs 29-40).
5. **Account size shapes the trades** (medium; moderate). Since geometry enforcement (09-14), 51 cards were
   stopped because one contract risked more than the ~$90 budget (one unit $96-$2,475), against 7 executed
   entries. Six were analyst takes; one outcome is known (MU 950C expired worthless, the block saved ~$360). At
   one or two contracts the analyst cannot scale out: HOOD was fully closed on the source's first trim at 2.15
   and printed a 4.41 high and a 4.00 close.
6. **Entry execution is not the main leak** (low importance; moderate). Source post to fill median ~80 s (receipt
   2-6 s, extraction ~7 s, appraisal 40-100 s, order ~1 s). Fills are at the ask, 0-2 cents over mid. Against the
   source's stated premium the median gap is +1.8% (range -22% to +20%; "stated" is sometimes an average or a
   target). Three minutes after the decision the ask was higher in 5 of 8 studied entries (SMCI +12.6%, ORCL +7.3%,
   MRNA +7%, HOOD +5.5%), so waiting would have cost more, not less.
7. **Knowledge supply is noisy and partly mis-measured** (medium; high). 20 of 57 live rules are pending-review
   proposals. Because the rule budget (50) is filled newest-first, they displace the 7 OLDEST operative rules on
   every run, while being labelled "not operative". Rule supply is never stamped (all 57 rules show supplied 0);
   the per-run snapshot records supply but the Knowledge view reads the counter. Reviews wrote 493 source notes
   since 09-08 (813 live, 352 never supplied). Six pending proposals restate one clause (ladder/trailing coherence).
8. **Cost attribution gaps closed** (done). Intake extraction usage has no run record (the nightly rollup is a lower
   bound). Census crashed on legacy list usage and could not own armed-plan fills; both fixed below.

## 3. Implemented (tested, observe-only for anything that touches model review)

| Change | Where | Behaviour |
|---|---|---|
| Economic scorecard | `tools/tip_scorecard.py` | Daily + cumulative; method / questioned / repairs / open mark / model cost by stage, source and coverage class; cash and equity reconciliation printed. Reuses the census and cost tools. |
| Census as data | `tools/tip_outcomes.py::build_census` | Same output (table rows byte-identical); dated realizations; armed-plan fills resolved to their signal through `TechniquePlanOrderResult` (inside the window only); shadow books readable; legacy list usage no longer crashes. |
| Questioned-fill registry | `docs/techniques/tip/research/questioned-fills.json` | Reviewed entries only (MRNA 165C, APLD 30C), each with evidence. |
| Review relevance gate | `techniques/tip/review_gate.py`, `signals/service._review_gate`, knob `techniques.tip.review_gate` (default **observe**) | Journals `TipReviewGate` for every review-path message; `enforce` would skip a message that reaches no held/armed/proposed item and is not entry-shaped. An incomplete desk read or any gate error always reviews. |
| Gate evaluation | `tools/tip_review_gate_eval.py` | Retrospective (desk state rebuilt per review) and prospective (observe decisions joined to what each review did). |
| Fixed-horizon entry study | `tools/tip_entry_horizons.py` | Takes and skips scored from the same executable ask at the same horizons; missing stays missing. |
| Register | `EXPERIMENT-REGISTER.md` + `experiments_register.py` | `review-gate` entry with its decision rule. |

Tests: `tests/test_tip_review_gate.py` (frozen message categories: exit on a held position, trim on an unheld
ticker, no-ticker stop move with a live idea, chatter, another source's position, correction on an armed plan,
mixed message, option-root match, possible missed entry; enforce/observe/off; incomplete desk read reviews;
failing decision reviews), `tests/test_tip_scorecard.py` (session anchor, attribution classes, questioned and
repair separation, armed-plan owner resolution, horizon scoring), plus the existing census regressions and the
register mirror.

## 4. Decisions requiring approval

| # | Proposal | Evidence | Expected benefit | Downside | Sample limits | Rollback |
|---|---|---|---|---|---|---|
| D1 | Switch `techniques.tip.review_gate` to `enforce` after 5 observe sessions with 0 false negatives | Retro: 186/556 reviews skipped, 0 management actions lost | about -$13/session model cost (-32% of reviews) | a possible missed-entry note is not written for irrelevant messages (3 of 23 flags; no process consumes them) | 9 sessions retro | `PATCH` back to `observe` (journaled) |
| D2 | Opening-window guard for PREMIUM exits only: 09:30-09:35 ET judge premium stop/bleed on the mid with a spread cap (or defer to 09:35); underlying stops, DTE/expiry flatten unchanged | 6 first-seconds exits -$999; 3 sold 40-70% below prints minutes later | avoids stub-quote exits; biggest single identified leak | a real gap-down bleeds up to 5 more minutes (the underlying stop still protects) | 6 cases, print evidence | a setting, default off |
| D3 | Same-session exit for tip options of 14 DTE or less unless the analyst records an explicit overnight thesis | Practice overnight -$784 vs same-session -$253; fixed horizons 5-14 DTE next close median -32%; hold study short options -$97 | removes the largest loss cohort | forgoes overnight gap-ups (none in the short-option sample; shares and 46+ DTE unaffected) | 12 overnight positions; 29 paired contracts | a setting, default off |
| D4 | Rulebook: supply operative rules first, then pending proposals within the budget (or stop supplying pending proposals) | 20 pending proposals displace the 7 oldest operative rules on every run | correct rule set in force; ~6.5k tokens/call if pending are dropped (~$9/session) | the analyst no longer sees proposals it wrote (labelled non-operative today) | structural, not statistical | revert the selection order |
| D5 | Consolidate the six pending ladder/trailing-coherence proposals into one for human review | duplicates in the pending set | fewer tokens, one decision | none (propose-only) | - | - |
| D6 | Paid, budgeted frozen-replay comparison of a cheaper model for intake REVIEWS on the review-gate's kept set | reviews are 76% of priced spend | potentially large; unmeasured | judgment quality on management actions | needs a representative frozen set | not deployed without a verdict |

No change is proposed to risk budgets, source promotion, sizing, entry timing or position size. Larger positions
are not a remedy: there is no demonstrated edge to scale.

## 5. Practical economics at this account size

- Opportunity rate: 22 filled ideas in 9 sessions (about 2.4 per session) at ~$90 risk each.
- Operating cost: $494.59 priced in 9 sessions (~$55/session); the most recent sessions ran $75-82.
- To cover $55-80 per session from trading, each filled idea must earn about $23-33 net, roughly +0.25R to
  +0.37R per trade, before any profit. Observed: method -$939 over 22 ideas, about -0.47R per trade.
- Feasible reductions (D1, D4): about -$22/session, leaving ~$35-60/session. Still +0.16R to +0.28R per trade to
  break even, with no evidence yet of positive expectancy.
- Recurring session expense (intake reviews, appraisals, extraction) is ~95% of the ledger; nightly overhead
  (retro, rule audit, digest) is the rest. Development and research model use (reviews like this one, frozen
  replays) are not in this ledger.

**Verdict: unattractive now, unproven after fixes.** The first steps are the cost gate and D2/D3 on the loss
centre, measured prospectively. Scaling size or adding sources would enlarge the loss, not fix it.

## 6. Prospective evaluation plan (definitions frozen 2026-09-19; no rule change after seeing results)

- **Primary metric (per session and cumulative):** Tips Practice marked equity change minus priced model cost,
  from `tip_scorecard` (tips-scorecard-v1), with method / questioned / repairs and coverage columns unchanged.
- **Secondary:** method realized net per completed idea; opening-window exits (count, net, and shortfall vs the
  first print at or after +5 minutes); overnight-held option cohort vs same-session cohort; review cost per
  session and review-gate false negatives.
- **Checkpoints:** C1 after 5 sessions (2026-09-25): review-gate prospective report (D1 decision input only).
  C2 after 10 sessions (2026-10-02): scorecard + entry horizons + hold study, same windows, same tools.
  C3 after 20 sessions (2026-10-16): the viability call. A session with no fills still counts; questioned fills
  stay apart; open positions are never credited to a cohort.
- **If D2 or D3 are approved:** each runs with its own setting and start date recorded in the register; its
  comparison is the frozen pre-period above plus the shadow books' unchanged behaviour, never a re-cut of
  history chosen after the fact.
- **Stop rule:** if at C2 the primary metric is below -$50/session with D1-D3 in force, recommend pausing live
  intake reviews beyond management of held positions and reassess the desk.
