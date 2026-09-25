# Team2 sharp-pencil review and plan — 2026-09-24

Written at the user's request after session 4 of the selection study: re-read the whole approach (method, execution,
costs, how we use models, the knowledge base, how we take material in) and plan for the most opportunity and profit.
Everything here is simulated money. Supersedes the plan sections of `2026-09-22-improvement-plan.md` (PR #255) and
`2026-09-23-review-and-plan.md`; their measurements stand. Sources: three read-only reviews run tonight (results and
levers, execution cost and ops, models and knowledge), the cross-desk `docs/PLAN-2026-09-24-SHARP-PENCIL.md` (EM desk,
item P1.2), and the Team2 record.

---

## 1. Bottom line

1. **There is still no measured after-cost edge.** Live: 30 Team2 trades since 2026-09-08, **−$3,981 net**, 5 wins
   (17%). Average win +$368 and average loss −$233 need a 39% hit rate to break even. The EM desk's FIFO count
   (−$4,435 over 32 trades) differs in method, not in direction.
2. **Most of the loss is not the entry signal.** It splits into three buckets we can act on:
   - **Costs.** Fees are $1,506, 38% of the net loss, and 4–8% of premium per round trip. The spread adds about one tick.
   - **Execution defects.** Stale orders cost about −$690. That was fixed and deployed tonight.
   - **The premium stop.** It decided **12 of 30 exits and −$4,167**. The live stop is not the rule the replay measured,
     so its cost is unmeasured.
3. **The one lever with arithmetic on its side is buying fewer, dearer contracts** (fees are per contract). It is not
   an edge. It halves a certain drag. It needs a prospective test, and I recommend reusing C1's paused book for it.
4. **No real money** until a preregistered arm passes on held-out data (cross-desk P1.5).

## 2. Where we stand (2026-09-24 close)

| book | since start | state |
|---|---|---|
| Team2 Control | −$1,665 (−16.6%) | trading (the untouched reference) |
| Team2 Sizing 0.5 | −$416 (−4.2%) | **paused** 09-24 15:00 on its $800 sampled-drawdown threshold (−$1,096 from a $10,681 high water) |
| Team2 C1 Conjunction | −$1,322 (−13.2%) | paused 09-22 on its threshold |

The Sizing-vs-Control comparison is **contaminated by defects**. Most of Sizing's lead comes from the 09-23 stale fill
(Control only) and a strike tie that gave the two books different contracts (§4.4). At the 20-session review, report a
defect-excluded view next to the registered one. Do not replace the registered one.

## 3. Done tonight (v0.8.49, deployed and verified 20:27 PT)

- **F130.** The read's exit of a setup cancels that setup's resting entries (09-23: −$243).
- **F131.** An unfilled entry or add is cancelled after 240 s, which is two 2m decisions (09-24: −$444). The value was
  fixed from the method's cadence before measuring. 28 of 30 entries fill within 15 s, so the limit only touches the
  two stale ones.
- **Exit authority records.** The live target, the intra-minute quote stop and the clock flatten now record which rule
  sold.
- **Entry pick priority.** Team2's live entry pick reads the chain at CBOE entry priority, the longer retry schedule EM
  uses (PR #274).
- **No-model guard.** A test pins that no model can reach Team2's decision path.
- **Clean-up.** Two merged worktrees and four merged branches removed. Five finished Team2 test databases dropped
  (~115 MB). The idle `Team2 Practice` book was archived 09-22.

## 4. Findings

### 4.1 Costs (certain, measured)
- **Sim fee.** The sim charges $1.04 per contract per side, matching the Webull CA preview. It **omits** the ~1.5%
  CAD→USD conversion, so it may *understate* Webull. IBKR (~$0.65) would be ~$0.75 cheaper per round trip, but that is
  not verified.
- **Fee as a share of premium.** Round-trip fees are 7.4% of premium under $0.35, 4.2% at $0.35–0.55 and 3.4% above
  $0.55.
- **Spread.** About one tick: 2% at $0.50, 4% at $0.25.
- **Picker bias.** The picker's first-OTM-under-$0.60 rule systematically buys the most fee-heavy contracts.

### 4.2 Exits (the biggest loss bucket; not measured on the live rule)
- **Premium stop.** Across 12 exits it lost −$4,167, about −29% each. After 8 live premium stops the contract was back
  above the sale price 6 times at +30 min and 4 times at +60 min: a coin flip.
- **Why the replay can't judge it.** H6 found the stop width doesn't matter *in the replay*, but the replay applies
  the stop on 2m closes. The live desk applies it every ~2 s on the mid.
- **Slippage.** Stop exits fill 1–2 ticks below mid ($0.96/contract), and actual exits land 26–28% down against a 25%
  line.

### 4.3 Entries and selection (speculation only)
- `scenario_1` lost 9 of 9 (−$3,088, 3 dates) and the `pm_break` puts are gross-positive. These are subgroup cells
  looked at before any registration, not findings.
- The S1 selection study (4 of 60 sessions) is the only programme built to answer this.
- Widening capture (resolver, no-trade zone, the 15:30 cutoff) adds trades at negative expectancy. C1 measured it.

### 4.4 Defects still open
1. **Strike tie at a whole-dollar spot.** 284.000 vs 284.005 gave Control the 283P at $0.25 and Sizing the 284P at
   $0.61 on the same fire (`strike < spot`, `runner.py` ~645–655). Books firing the same decision must price the same
   spot snapshot.
2. **Exits without an authority record.** V2 trims (tp1/tp2) and the X2 runner trail are still missing one; F130
   covered the rest.
3. **Recorded Greeks are implausible.** One SPY call shows delta 0.82 at a $0.62 ask. No research may use these fields
   until the source is checked.
4. **Sim is optimistic on marketable target sells.** The 15 s freshness gate held them back, and they then filled
   above their limit: about +$365 of improvement a venue would not give. This is platform-owned. Evidence should not
   flatter us.

### 4.5 Models and knowledge
- **Team2's decision path uses no model.** It is now pinned by a test.
- **The market-watch job.** Team2's only paid model work was the Claude Code `team2-market-watch` job. Its log stops
  2026-09-14 (600 KB of mostly "alive, no fire"), and its timestamps ran 1h35m fast. Retire it formally. The
  deterministic end-of-day receipt and exit review replace it.
- **The knowledge base has not been updated since its first capture.** It is one manual capture from 2026-09-03 (49
  notes, 2 transcripts). Week-37 posts are indexed by id only, and nothing has been captured since 09-12.
- **Casey's material** is all on X, readable only through the user's signed-in Chrome. His Discord is a paid whop, and
  a self-bot there is a ban risk: do not build it.
- **No structured link from rule to evidence to outcome.** METHOD.md cites sources in prose, outcomes live as prose
  findings, and plans do not stamp a METHOD version.

### 4.6 Operations (threaten decisions, owned platform-wide)
- **09-24 11:33 ET.** Team2's bar queue backed up **197–322 s (1,484 bars)** while holding IWM, the DB pool ran dry
  (5+10) and a `decision_inputs` audit row was lost.
- **09-23 15:11–15:16 ET.** Platform-wide stale bars.
- **Tonight ~19:45 PT.** `/api/health` went unanswered for more than 90 s at 0.9 GB free RAM (a Cartel research tool
  plus a chaos test run). It recovered when they finished.
- These are cross-desk P0.1/P0.2 (EM owns the platform fixes).

## 5. The plan

### P0 — this week (Team2-owned, small, no method change)
| # | action | why | effort |
|---|---|---|---|
| 0.1 | Fix the strike tie: one spot snapshot per fire across books, with an explicit tie rule | removes a determinism defect that splits the experiment books | small |
| 0.2 | Authority record on V2 trims and the X2 trail | every sale names its rule; the exit review needs it | small |
| 0.3 | Alert when Team2's bar-queue lag exceeds 10 s while holding (journal + toast) | 322 s of lag on a held 0DTE position went unseen | small |
| 0.4 | Stamp a METHOD/rules version hash on every plan | per-session attribution of which method traded | small |
| 0.5 | Retire `team2-market-watch` formally; move `notes/market-watch.md` to `notes/archive/` | stops a stale paid job's footprint; history kept | trivial |
| 0.6 | Nightly: study status (coverage only), `team2_exit_review`, opportunity audit | the prospective evidence that answers §4.2 and §4.3 | running |

### P1 — measurement (order-free)
| # | action | decision rule |
|---|---|---|
| 1.1 | **Premium-stop parity:** re-run the 09-19 harness with the stop applied intrabar (1m print lows, mid-equivalent) against the 2m-close baseline. This fixes the measurement; it is not a new variant search. | if the intrabar stop is worse by ≥ 3 points/trade (date-clustered), the live stop is the leak, and a registered change (2m-close confirmation) is proposed |
| 1.2 | **Venue-cost lines:** report each book's P&L at gross, at Webull ($1.04 + FX) and at IBKR (~$0.65) | reporting only; the fee assumption decides every verdict at a ~6% headroom |
| 1.3 | Check the Greeks source (CBOE delayed Greeks vs live price) | no delta-bounded research until resolved |
| 1.4 | Ask the platform owner to fix the sim's marketable-sell improvement (§4.4-4) | evidence must not be flattering |

### P2 — prospective tests (**need your approval**)
| # | test | design |
|---|---|---|
| 2.1 | **H5-P: dearer contracts on the paused C1 book.** No new book is needed. C1's experiment has done its job (it paused on its threshold). | premium target ~$1.20 (floor $0.80) instead of first-OTM ≤ $0.60. Same signals as Control, 20 sessions. Criterion frozen before start: ≥ 3 points/trade better than Control's same-day trades, date-clustered, **and** a book above Control. A new $800 threshold, registered. |
| 2.2 | Sizing 0.5 stays paused as registered | resuming it would break its own rule; its lead is defect-driven anyway |

### P3 — knowledge and material intake
| # | action | effort |
|---|---|---|
| 3.1 | Weekly semi-manual X capture: a checklist run in your signed-in Chrome → `extract_threads.py` → a diff of candidate rules against METHOD, **propose-only** (a human changes rules) | ~30 min/week |
| 3.2 | A rule→source→outcome register (rule id, source note ids, date adopted, findings, measured result), generated from METHOD's citations like `build_sources_index.py` | ~1 day |
| 3.3 | A daily Casey-vs-desk ledger for days he posts trades: his entries and exits beside ours on the same setups. Self-selected, so descriptive only | ~15 min/day |
| 3.4 | No Discord forward; no model on the order path (pinned) | — |

### P4 — the 20-session review (~2026-10-15)
- Decide each experiment arm by its registered criterion, and show a defect-excluded view beside it.
- If no arm is positive after costs, retire Team2 *automation* to observation only and keep the studies running.
- S1 continues to 60 sessions. It is the only route to a setup-level edge.

## 6. What we are deliberately not doing
- Not tuning the premium stop width again (H6 measured it). P1.1 fixes *how* it is measured, not its value.
- Not extending the 15:30 cutoff / 15:45 flatten to chase Casey's late-day trade (09-23). It is a 0DTE risk rule; if
  wanted, it is a registered test like H5.
- Not widening opportunity capture before S1 finds a positive class.
- Not reading one green day, or a defect-driven book lead, as progress.

## 7. Decisions for you
1. **Approve H5-P on the paused C1 book** (P2.1). I recommend yes: it is the only test aimed at the certain drag, and
   it needs no new book.
2. **Sizing 0.5 stays paused** (P2.2). Recommended, and applied: nothing was changed.
3. **Target venue for cost reporting:** Webull CA (current), IBKR (pending), or both lines (recommended).
