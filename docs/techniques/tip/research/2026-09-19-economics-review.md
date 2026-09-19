# Tips economics review - revision 2 (2026-09-19, after the review team's verdict)

Scope: Tips Practice book `4611946d…` from its 2026-09-08 reset through the 2026-09-18 accounting day (9 trading
sessions). Generated outputs beside this file, all regenerated for this revision:
`economics/scorecard-2026-09-08_2026-09-18.md` (tips-scorecard-v2),
`economics/entry-horizons-2026-09-11_2026-09-18.md` (entry-horizons-v2),
`economics/review-gate-retrospective-2026-09-09_2026-09-18.md`,
`economics/d5-ladder-trailing-consolidation-manifest.md` (+ `.json`).

**What revision 2 changes.** The review verdict (`reviews/2026-09-19-economics-verdict.md`, ECON-01..04) found the
scorecard printing the wrong primary metric, two defects in the horizon study, an enforce-mode hole in the review gate,
and several over-stated conclusions in revision 1. All four are corrected below. Revision 1's "-32% next close" figure,
its takes-versus-skips comparison and its D2/D3 framing are WITHDRAWN and replaced by the corrected numbers.

**Short answer, unchanged in direction, narrower in claim:** the desk lost money before operating expense and the
intake bill is large. That much is supported. What caused the losses, and whether any proposed exit change would
help, is NOT established by this evidence.

## 1. Reconciled scorecard (2026-09-08 .. 09-18)

| Line | Amount | Basis |
|---|---:|---|
| Method realized, after allocated fees | -$939.11 | FIFO lots (census engine); fees inside it $112.32, counted once |
| Questioned fills (graded apart) | -$97.41 | MRNA 165C +$112.92 (quote provenance); APLD 30C -$210.33 (filled 04:01 ET, before `sim_option_sessions`) |
| Bookkeeping repair | -$9.16 | RKT 59-share oversell by a venue stop, repaired by a tagged manual buy |
| Realized total | -$1,045.68 | the three lines above |
| Open positions, mark minus cost | +$15.34 | ACHR 7C x3, AAL 14C x2, SBLK 62 sh |
| **MARKED equity change** | **-$1,035.54** | $10,000.00 to $8,964.46; identity residual $0.00 |
| Model operating cost, priced | -$494.59 | list-price estimate, a lower bound (coverage below) |
| **MARKED change after model cost (PRIMARY metric)** | **-$1,530.13** | -1,035.54 - 494.59 |
| Realized after model cost (secondary) | -$1,540.27 | -1,045.68 - 494.59 |

The two after-cost figures differ whenever open positions are marked, so the scorecard now prints both, per session and
cumulative, with the primary one labelled. For 2026-09-18: marked +$39.04 - $81.61 = **-$42.57**; realized -$11.18 -
$81.61 = -$92.79.

**The "close" is an accounting-day cutoff, not the 16:00 ET market close.** A session runs 04:00 ET to 04:00 ET and its
mark is the last persisted equity point in that window - 03:59 ET the next morning on every row here, so each mark
includes after-hours quote drift. The scorecard prints the actual mark timestamp. A report that starts after the book's
inception now takes its baseline from the prior accounting-day mark, and says so.

**Reconciling $84.59 and $81.61 for 2026-09-18.** They are different windows, not different prices. `tip_llm_cost` uses the
calendar ET day: that window prices $84.61 (within $0.02 of the reviewed $84.59). The scorecard uses the accounting
session: 4 runs between 00:00 and 04:00 ET on 09-18 (1 appraisal $0.80 + 3 intake reviews $2.22 = $3.02) belong to the
09-17 session, and no run fell between 00:00 and 04:00 ET on 09-19. $84.61 - $3.02 = $81.59, the scorecard's $81.61
after rounding. Totals from the two tools must not be mixed.

Model cost coverage (cumulative): intake reviews $377.35 (90 stamped + 463 from the review run's own model field; 3
unpriced); appraisals $90.32 (3 unpriced); retros $12.18; extraction $12.17 from the nightly stage rollup only - a lower
bound; rule audits $2.24 with 7 of 8 runs unpriced (1.38M input tokens, 39 unknown calls); digest and transcription
$0.33. About 2.3M input tokens remain unpriced.

Where closed positions ended (19 positions, net of fees; RKT at its method result -$30.15, its repair apart):

| Exit | Positions | Net |
|---|---:|---:|
| Premium stop, bleed or stop in the first seconds of a session (all had been held overnight) | 6 | -$999.09 (incl. questioned APLD -$210.33) |
| Premium stop or bleed during the session | 3 | -$269.71 |
| Underlying stop | 4 | -$123.79 |
| Analyst mirrored the source's exit | 3 | +$25.38 |
| Target reached (GOOGL) / venue stop after TP1 (RKT) | 2 | +$217.85 |
| Questioned MRNA 165C | 1 | +$112.92 |

**Days to expiry of those six first-seconds exits (correction).** Only three were short-dated: GS 9 DTE -$172.14, HIMS 3
DTE -$27.08, SMCI 7 DTE -$63.10 = **-$262.32**. The other three were long-dated: CCXI 37 DTE **-$505.08** (the largest
single loss in the book), APLD 32 DTE -$210.33 (questioned), DAL 70 DTE -$21.36 = -$736.77. A rule limited to contracts
of 14 DTE or less would not have touched CCXI.

"Held overnight" totals (12 positions, -$783.67) are whole-trade results of positions that happened to cross a night;
they are NOT overnight-only P&L and do not separate exposure, duration or the pre-close-to-open move.

## 2. Ranked findings (as corrected)

1. **Model spend is mostly intake reviews that change nothing** (importance high; confidence high for the count,
   estimate for the dollars). 556 reviews cost about $379 (09-09..18); 498 only saved a note; 51 called a management
   tool. A per-ticker relevance check would have skipped 186 reviews (about $122, 32%) with zero management actions
   lost - on a desk state REBUILT from the durable record, which is approximate. Of those 186, 3 carried a possible
   missed-entry flag and 182 a watch list (the review writes a watch list almost every time, so that field does not
   discriminate). A tool count alone does not prove a skipped review had no value; the checkpoint below is a human read.
2. **The first seconds after the open are where the largest realized losses were booked** (importance high; cause NOT
   established). Six exits, -$999.09, all after an overnight hold, across 3 to 70 DTE. Later trade prints were higher
   for DAL, HIMS and CCXI and lower for SMCI; a later print does not prove the quote at the time of sale was a stub, a
   midpoint is not a liquidation value, and a wide spread makes it less informative. No contemporaneous two-sided quote
   with size was analysed here.
3. **Short-dated contracts: the median loses by the next close, the mean does not** (provisional). Corrected horizon
   study, 38 eligible observations on 36 contracts (36 of 74 rows excluded: the decision quote was taken outside the
   option venue session). Paired close-window to next-close-window drift: n=28, median -18%, mean +3%, 10 up. By DTE:
   0-4 n=9 median -52% / mean +45% (a lottery tail); 5-14 n=10 median -37% / mean -28% (2 up); 15-45 n=3; 46+ n=6
   median +1%. Trade prints, not quotes; unmatched groups; one regime.
4. **No demonstrated selection edge** (not a finding that the analyst lacks skill). From the decision's own ask: takes
   (n=12) session close median -4%, next close median -53% (n=9, 1 up); skips (n=18/15) +2% and -32%. Takes and skips
   differ in setup and DTE, so the comparison is unmatched and small.
5. **Account size shapes the trades** (medium). Since geometry enforcement (09-14), 51 cards were stopped because one
   contract risked more than the ~$90 budget, against 7 executed entries; six were analyst takes. At one or two
   contracts a scale-out ladder cannot be executed: HOOD was closed in full on the source's first trim at 2.15. The
   contract later printed higher; that is a diagnostic, not evidence the exit was wrong or that a profit was realizable.
6. **Entry execution is not the main leak** (low; moderate). Source post to fill median ~80 s; fills at the ask, 0-2
   cents over mid; three minutes later the ask was higher in 5 of 8 studied entries.
7. **Knowledge supply was mis-budgeted and partly unmeasured** (medium; high) - FIXED as D4 below. 20 of 57 live rules
   are pending proposals; filled newest-first into the 50-rule budget they displaced the 7 oldest operative rules on
   every run. Rule supply was never stamped. Six pending proposals restate one clause.

## 3. Implemented in revision 2

| Change | Where | Behaviour |
|---|---|---|
| ECON-01 scorecard v2 | `tools/tip_scorecard.py` | Prints MARKED after model cost (primary) and realized after model cost separately; prints the mark's actual timestamp and names the 04:00 ET accounting convention; interval baseline when the report starts after inception; identity only from inception. |
| ECON-02 horizons v2 | `tools/tip_entry_horizons.py` | Forward-only prints; exchange-calendar windows (final 30 minutes of the decision session and of the NEXT TRADING session; holidays and early closes); starting quote accepted only by the existing `cohort.qualify_quote` rule and at most 15 s old; denominators, exclusions, observation times and repeat observations reported; missing stays missing. |
| ECON-03 gate | `techniques/tip/review_gate.py`, `techniques/tip/runner.py` | An ABSENT position manager or tip runner, or a runner whose restore has not completed, is an INCOMPLETE desk read: the message is reviewed, under enforce too. `None` never means empty. |
| Gate evaluation | `tools/tip_review_gate_eval.py` | Labels the retrospective reconstruction approximate; lists skipped reviews that carried a possible new entry, a deferred action or a mixed message for a human read; prospective report prints coverage in observed sessions. |
| D4 rulebook | `techniques/tip/analyst.py::_rules_text`, knob `techniques.tip.analyst_max_pending_rules` (6) | The 50-rule budget belongs to OPERATIVE rules (core first, then newest). Pending proposals ride in a separate, capped, clearly non-operative channel and consume no operative capacity. Snapshot keeps ids, revisions and hash in one chronological order and adds operative/pending counts, omitted ids and pending omitted ids. Supply is stamped for live runs (supplied, never relied-upon); historical reads never stamp. The rule budget is NOT expanded. |
| D5 manifest | `economics/d5-ladder-trailing-consolidation-manifest.{md,json}` | One reviewed CANDIDATE for the six duplicate pending ladder/trailing-coherence proposals, with every original id, revision, text hash and cited case, a reversible supersession map and the rollback. NOT applied; nothing superseded, deleted or promoted. |

Regressions: the review team's `tests/test_economics_boundaries_review.py` (3) adopted verbatim and passing. Own tests:
gate (absent components, unfinished restore), scorecard render with open P&L, horizon calendar windows and start
eligibility, rulebook D4 (3). One stale Tips liveness expectation that was already red on main was corrected to the
2026-09-18 semantics (a claim in flight warns; a persistent pending count stalls).

## 4. Proposal status after the verdict

| # | Proposal | Status | Note |
|---|---|---|---|
| D1 | Review gate enforce | OBSERVE only | Enforcement needs ECON-03 (done) AND a human review of the prospective evidence: management, corrections, new entries, mixed messages and useful deferred actions. Five clean sessions are a checkpoint, not proof and not an automatic switch. |
| D2 | Opening-window premium-exit guard | **NO-GO** | Withdrawn as a live proposal. Research only, with contemporaneous two-sided quotes and size, adverse as well as favourable outcomes. "The underlying stop still protects" was wrong as a general claim: the reviewed SMCI position had NO underlying stop (premium guard only). |
| D3 | Same-session exit for short-dated options | RESEARCH comparison only | No blanket activation. It would not have addressed CCXI (-$505.08, 37 DTE). Needs overnight-only P&L, same-expression and same-risk paths, and predefined journaled exceptions. |
| D4 | Operative rules first | **DONE** | Governance fix, not a trading rule. |
| D5 | Consolidate duplicate pending proposals | MANIFEST PREPARED | Reversible, propose-only; approval of any rule stays a human decision. |
| D6 | Cheaper model for intake reviews | NOT STARTED | Verdict allows preparing an UNPAID representative frozen comparison; no paid run, no model activation. Not part of this packet. |

Savings are ESTIMATES until measured on identical inputs, and D1 and D4 OVERLAP: D4 shortens every call's prompt
(roughly 14 pending proposals fewer per run), D1 removes whole calls, so the two must not be added. Indicative only:
D1 alone about $13 per session; D4 alone a few dollars per session; together less than their sum.

## 5. Practical economics at this account size

- Opportunity rate: 22 filled ideas in 9 sessions (about 2.4 per session).
- Operating cost: $494.59 priced in 9 sessions (~$55 per session); the latest sessions ran $75-82.
- At today's ~$90 risk budget, covering $55-80 per session needs roughly +0.25R to +0.37R per filled idea before any
  profit. These R figures are ILLUSTRATIVE current-budget equivalents: historical entry-time risk was not
  reconstructed, and early trades (CCXI, 12 lots) were sized before the geometry budget existed, so "-0.47R per
  trade" from revision 1 is withdrawn as a measured statistic.
- Recurring session expense (intake reviews, appraisals, extraction) is about 95% of the ledger. Development and
  research model use is not in this ledger.

**Verdict: the current economics are unattractive; whether they can be made viable is unproven.** Larger positions,
looser stops or more sources are not remedies: there is no demonstrated edge to scale.

## 6. Prospective evaluation plan (definitions frozen 2026-09-19)

- **Primary metric:** Tips Practice MARKED equity change minus priced model cost, per accounting session and
  cumulative, from `tip_scorecard` (tips-scorecard-v2); realized-after-cost printed beside it; method / questioned /
  repairs and coverage columns unchanged.
- **Secondary:** method realized net per completed idea; first-seconds exits (count, net, DTE at exit); review cost per
  session; review-gate management false negatives plus the human-read list.
- **Controls:** none from the shadow books. Several nominally non-quarantined shadow books carry unallocated sells in
  the scorecard's own table, and two are quarantined; they are execution-inconsistent and are NOT a policy control.
- **Checkpoints count OBSERVED sessions after the actual deployment** (0.8.23 live 2026-09-19 12:47 ET; the corrected
  gate and D4 go live with the next deploy). C1 after 5 observed sessions: gate evidence review (D1 input only). C2
  after 10: scorecard + horizons + hold study, same tools and windows. C3 after 20: viability call. Each reports sample
  and coverage. A session with no fills counts; questioned fills stay apart; open positions are never credited to a
  cohort.
- **Pause criterion (C2):** judged on the corrected primary metric and the configuration actually in force (D2 and D3
  are not approved and are not assumed). Any pause recommendation covers NEW intake reviews and entries only: management
  and protection of held positions continue, and existing armed entries are handled explicitly (kept or disarmed by a
  recorded decision), never silently dropped.

## Observation status (2026-09-19)

`techniques.tip.review_gate` = observe on the live build (0.8.23). `tip_review_gate_eval --prospective --since
2026-09-19`: 0 decisions over 0 sessions - the deploy landed on a Saturday and no review-path message has arrived.
The first observed session will be Monday 2026-09-21.
