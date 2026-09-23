# Tips — adversarial review of the approach, and a profit-and-opportunity plan (2026-09-23)

Written against the running system (0.8.32, build `63613751`) and the Tips Practice record 2026-09-08 → 09-22
(scorecard v4, `tip_outcomes --dispositions`, `tip_review_context_cost`, live DB). The brief was to attack our own
plan: what we trade, how we take tips, how we spend on the model, how the knowledge base works, and whether our
measurements can be trusted. Every number is from those tools; sample sizes are small and stated. Nothing here is
activated by this document — the decisions are in §4.

## 1. The honest scoreboard

| 2026-09-08 → 09-22 (10 sessions) | $ |
|---|---:|
| Marked change (primary trading result) | **−819.96** |
| Realized net of fees (method) | −674.04 |
| Priced model cost (list-price estimate, lower bound) | **735.92** |
| **Marked after model cost** | **−1,555.88** |

Two facts dominate everything else:

1. **Model spend is as large as the trading loss.** Intake reviews alone are $553.52 (75% of spend); appraisals
   $134.49; everything else ~$48.
2. **Options lost, shares made money.** Realized by vehicle: options cohorts **−$1,034**; share cohorts **+$360**
   (3 completed ideas) with five more share positions open and marked above cost. Small n, but every exit class below
   points the same way.

| how closed positions ended | n | net | winners |
|---|---:|---:|---:|
| premium/stop exit in the first seconds of a session (all held overnight) | 6 | −829.85 | 0 |
| premium stop / bleed in session | 3 | −269.71 | 0 |
| underlying stop | 4 | −123.79 | 1 |
| questioned fills | 2 | −97.41 | 1 |
| target / premium target | 2 | +217.77 | 1 |
| **analyst mirrored the source's exit** | 7 | **+331.55** | 5 |

The desk's losses are almost entirely **option premium decay and overnight gaps on long options**; its gains come
from **following the source's own management** (VKTX +$296 this week on lifted stops and mirrored exits).

## 2. Adversarial findings

Severity: **H** = changes the P&L or the evidence materially; **M** = meaningful cost or risk; **L** = hygiene.

### A. What we trade

| # | Finding | Evidence | Sev |
|---|---|---|---|
| A1 | **Long options are the loss engine.** Buying the tip's contract verbatim buys theta, spread and fees; nine premium-stop exits lost $1,099.56 with zero winners. | exit table above; ACHR 5.5c all-in friction 22% of debit, ACHR 6c 13% | H |
| A2 | **Holding short-dated long options overnight is the single worst habit.** All six first-seconds exits were overnight holds (−$829.85). The earlier D2 review rejected an "opening exit guard" because DTE ranged 3–70 — but that rejected one *remedy*, not the finding. The question to test is whether to *enter* or *hold* those contracts overnight at all. | exit table; `2026-09-19-economics-review.md` D2 | H |
| A3 | **The risk budget kills most option takes after we have already paid to appraise them.** 12 of 48 takes (25%) were risk-infeasible: one contract risked $113–$505 against a ~$92 budget. We pay Opus to appraise, then the geometry gate refuses. | dispositions; 09-22 HIMS/COIN/BABA | M |
| A4 | **Shares at equal risk are feasible where options are not**, and the only positive cohorts are shares. The account-fit study found a shares alternative for 4 of 6 infeasible takes; the live share entries (SBLK, VKTX, PL, IONQ, CRWV, NEM) are the book's best positions. | `tip_feasibility replay`; source × setup table | H |
| A5 | **Exposure is concentrated and unmanaged as a portfolio.** ~71% of equity is held overnight, mostly five share names; there is no book-level cap on aggregate open risk or on correlated names. | friction/exposure table 09-22 | M |

### B. How we take tips (intake)

| # | Finding | Evidence | Sev |
|---|---|---|---|
| B1 | **Most intake is not a trade, yet each message gets an Opus extraction and, if discarded, a full Opus review.** Since 09-15: 240 of 391 signals `verification_failed` (top reasons `opens_position` 179, `actionable` 142) — recaps, commentary, exits. | signal statuses | H |
| B2 | **The review is a 3-turn agent loop re-sending ~127k input tokens per message** (3.2 calls, 3.3 tools on average). Note-only reviews are ~80% of review spend. | 09-21/22 intake runs; `review-gate-retrospective` | H |
| B3 | **The relevance gate works but is only observed.** It would skip 22–27% of reviews with zero management false negatives so far; every skipped message still costs full price during observation. | `tip_review_gate_eval --prospective` 09-21/22 | M |
| B4 | **Follow-up handling is the best thing the desk does** (mirrored exits +$331, stop lifts). It runs inside the expensive review path, so cheapening intake must not weaken it. | exit table; VKTX | H (protect) |
| B5 | **The cold-ticker fast path and dispositions closed the processing misses**: 0 avoidable misses since 09-17. Remaining "misses" are policy (risk budget, spreads) not bugs. | dispositions | L (done) |

### C. How we manage the LLM

| # | Finding | Evidence | Sev |
|---|---|---|---|
| C1 | **The prompt-cache pilot was scoped to the wrong prefix.** The 09-17 estimate cached only system + tool definitions (~5.3k tokens, ~11% of a call) and concluded the benefit was small. The big repeated content is the per-run header (rulebook + notes ≈ 19.5k tokens) and the conversation, re-sent on every turn of a 3-turn review. Caching through the header and the last message could remove an estimated **50–70% of intake input cost** (cache read = 0.1× input). This is arithmetic, not a measurement. | `2026-09-17-prompt-cache-pilot-plan.md` §prefix; `analyst.cacheable_request` marks system + last tool only | H |
| C2 | **One model for every job.** Opus 5 extracts, appraises, reviews recaps, writes digests and audits rules. The cheaper-review evaluation is prepared but has no captured cases faithful enough until this week. | cost by stage | H |
| C3 | **The rulebook is injected into every review although reviews mostly manage positions.** 37 live rules, 41.7k chars — 68% of every review header; the notes block is another 28%. | `review-context-cost-2026-09-21.md` | H |
| C4 | **Cost is not attributed to value per source.** MuggZone consumed $301.61 of model spend and produced −$226 realized (+$113 questioned); giul-heatseeker $37.84 with no fill; tt $80.35 for one losing fill; common-stock $25.69 for +$200. | cost by source; source × setup | H |

### D. Knowledge base

| # | Finding | Evidence | Sev |
|---|---|---|---|
| D1 | **The note store grows without a value test.** 986 live `source:` notes (avg 1.5k chars), 321 `ticker:`, 152 `general:`. There is no measure of whether a supplied note changed a decision for the better. | tip_notes by scope | M |
| D2 | **The model writes its own rules from few cases.** 37 live rules, 23 pending, 47 superseded in three weeks — churn that looks like overfitting to single trades. Rules are never back-tested against the trades they claim to explain. | tip_notes `rule` | M |
| D3 | **Knowledge is expensive to carry and cheap to create.** Every new rule adds cost to every future review forever (C3); nothing retires a rule that never mattered. | C3 × D2 | M |

### E. Can we trust our measurements?

| # | Finding | Evidence | Sev |
|---|---|---|---|
| E1 | **Shadow research books are broken, so we cannot judge the analyst's declines.** eva immediate shows **+$145,506** (21 unallocated sells); two armed books are quarantined; ab immediate −$6,257. Any "the analyst skipped a winner" claim is unsupported. | shadow section of scorecard | H |
| E2 | **Scorecard v4 target-to-fill is wrong for options (our defect).** For an option rung it compares the *underlying* target with the *premium* fill (T: "shortfall" $5,172; GOOGL $33,105). Shares rows are correct. | scorecard v4 target table | H (fix now) |
| E3 | **Premium-stop confirmations cannot be verified (P11).** Two OPRA poll stamps can be one print; CORZ's 09-22 exit is an instance. Owner Team2 (accepted). | PLATFORM-RULES 2026-09-22 | H |
| E4 | **n is tiny.** 31 filled ideas, 21 completed; no cohort has enough to claim an edge. Plans must be designed to learn fast, not to be right. | all tables | — |

## 3. The plan

Principles: protect what works (source-following management, the risk gate, write-ahead exits); cut spend that buys
nothing; move exposure from the vehicle that loses to the vehicle that pays; fix measurement before judging.

### Phase 0 — correctness (this week, no policy change)

1. **Fix E2**: for option rungs, target-to-fill uses the underlying price at the fill instant (or is labelled
   "premium target — not comparable"), never premium vs underlying. Regression test with the T/GOOGL rows.
2. **Repair or exclude broken shadow books (E1)**: FIFO rebuild for eva/ab/tt immediate books from executions; any
   book with unallocated sells is quarantined automatically and excluded from every comparison.
3. **P11 with Team2**: vendor stamp on `Quote`, observation identity, then Tips' `_confirm_premium_stop` switch in its
   own reviewed diff. Record-only until then.

### Phase 1 — cut model spend 50–70% without losing follow-ups (biggest $ lever)

Target: intake + appraisal spend from ~$65–90/session to ~$20–30/session.

| Step | What | Expected effect | Guard |
|---|---|---|---|
| 1a | **Measured cache pilot, correctly scoped (C1)**: cache marker at the end of the header, and on the last message of each turn. Replay 10 captured reviews off vs on (captured manifests exist since 09-19). Budget ≤ $10, estimate-based. | −50–70% of intake input cost if the arithmetic holds | frozen replay; identical decisions required |
| 1b | **Review context diet (C3)**: reviews receive only management-relevant rules (exit, stop, follow-up families) and ticker-scoped notes for the tickers in the message and the book; appraisals keep the full rulebook. | header ~78k → ~15–25k chars | compare on captured cases: no lost management action |
| 1c | **Enforce the relevance gate after the five-session report (B3)** if false negatives stay 0 and the human list is clean. | −22–27% of reviews | P1 decision; observe until then |
| 1d | **Tiered models (C2)**: run the prepared evaluation (Sonnet 5 / Haiku 4.5) on the captured cases; route note-only reviews and digests to the cheaper model only if management instructions match. | note-only reviews ~5–10× cheaper | P2 decision; production model unchanged until approved |
| 1e | **Per-source spend caps (C4)**: a daily review budget per source proportional to its realized contribution; sources with no fill in 10 sessions drop to digest-only (context mode) with management follow-ups still reviewed for positions we hold. | MuggZone/giul/tt spend halved | never skips a message about a held position |

### Phase 2 — move exposure to what pays (profit lever)

| Step | What | Evidence | Guard |
|---|---|---|---|
| 2a | **Shares-first when the option is infeasible or high-friction (A3, A4)**: when no option quantity fits the risk budget, or all-in friction > X% of debit, propose the equal-risk share position as a *labelled alternative card* (human-approved in the first stage). | 4/6 feasible alternatives; share cohorts positive | never automatic substitution until measured; Practice only |
| 2b | **Overnight long-option rule (A2), tested before adopted**: compare "close ≤7-DTE long options at 15:50 unless the source explicitly holds" against current holding, on history (hold study `holdstudy-v2` already samples 15:50 and next open). | 6/6 overnight first-seconds exits lost $830 | research → decision; no live change without the comparison |
| 2c | **Premium floor for option tips**: skip contracts whose round-trip fees + spread exceed a threshold share of debit (candidate 10%). | ACHR 22%/13% | research first; P5 |
| 2d | **Make source-following the core (B4)**: extend mirror-exit and stop-lift follow-ups to every source we hold; alert when a held position's source posts and no review acted within N minutes. | +$331 mirrored, VKTX | no new entries from follow-ups |
| 2e | **Book-level risk (A5)**: cap aggregate planned risk and single-name exposure (e.g. ≤ 20% of equity per name, ≤ 60% total held overnight in Practice) — refuse new entries beyond it. | 71% held on 09-22 | risk limits unchanged until approved |
| 2f | **Source allocation by evidence**: budget per source from closed Practice outcomes net of model cost (common-stock and ab 30+DTE lead; MuggZone 0–4 DTE options trail); review monthly. | source × setup + cost by source | never from shadow books until E1 is fixed |

### Phase 3 — knowledge that earns its place

1. **Rule budget and evidence binding (D2)**: a rule becomes operative only if it cites ≥ 3 dated cases and survives a
   replay of those cases; cap operative rules (e.g. 15, pinned first); everything else stays a proposal.
2. **Note value test (D1)**: record supply and reliance (already stamped) and retire notes never relied on in 30 days
   (tombstone, reversible); scope notes to tickers at supply time.
3. **Weekly knowledge ledger**: rules added / retired / relied on, and the context characters they cost.

### Phase 4 — measurement that can decide

1. **Per-source ROI line** in the scorecard: realized + marked − model cost, per source and per vehicle.
2. **Weekly decision review**: one page, from the scorecard, dispositions and the gate report; decisions logged in
   TRADING-RULES with the evidence cited.
3. **Stop running expensive research by default**: MK own-book observe, frozen capture variants and the entry-timing
   cohort cost little each; confirm each still has a question it will answer, or switch it off.

## 4. Decisions (one table)

| # | Decision | Recommendation | Evidence to wait for | Expected value |
|---|---|---|---|---|
| D-1 | Fix scorecard option target-to-fill (E2) | do now (bug) | none | correct evidence |
| D-2 | Repair/exclude broken shadow books (E1) | do now | none | trustworthy controls |
| D-3 | Correctly scoped cache pilot, ≤ $10 | approve | none (captured cases exist) | −$25–45/session if confirmed |
| D-4 | Review context diet | approve after 1a replay | no lost management action on captured cases | −$15–25/session |
| D-5 | Enforce relevance gate | after five-session report | 0 false negatives, clean human list | −$15–20/session |
| D-6 | Cheaper model for note-only reviews | after evaluation | instructions match on management/correction cases | −$20–30/session |
| D-7 | Per-source spend caps | approve design | 10-session source ledger | −$10–20/session |
| D-8 | Shares-first alternative cards | approve as human-approved cards | n ≥ 20 before auto | recovers infeasible takes |
| D-9 | Overnight short-DTE long options | research comparison | hold-study rows over ≥ 20 cases | avoids the −$830 class |
| D-10 | Premium/friction floor | research | friction table over the window | avoids high-friction losers |
| D-11 | Book-level risk caps | approve values | — | limits concentration |
| D-12 | Rule budget + evidence binding | approve | — | smaller, better rulebook; lower cost |
| D-13 | P11 premium-stop observation identity | Team2 first, then Tips | vendor stamp on Quote | trustworthy stops |

**Combined target if Phase 1 lands:** model cost from ~$74/session (window average) to ~$20–30/session — on this
window's trading that turns −$1,556 after cost into roughly −$1,100; the rest has to come from Phase 2 (vehicle and
overnight). Break-even needs both.

## 5. What we should stop doing

- Treating every Discord message as worth an Opus agent loop.
- Growing the rulebook by default; every rule is a permanent tax on every review.
- Quoting shadow-book P&L as support for a decision until E1 is fixed.
- Adding studies without a decision they will change.

## 6. What stays as is

The risk gate and geometry sizing, write-ahead exits and venue stops, source-following management, the five-session
observation, observe mode for the gate until the report, and the production model until an evaluation says otherwise.
