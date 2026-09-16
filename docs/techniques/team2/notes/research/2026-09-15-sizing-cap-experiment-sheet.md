# Experiment sheet — sizing cap first (`size_full` 0.5), C1 as the follow-on — 2026-09-15 (rev. 2)

> Rev. 2 after the other team's review of PR #143/#144 (`2026-09-15-sizing-sheet-pr144-review.md`): the calibration is
> labelled APPROXIMATE and says what it does and does not simulate; the loss stop is a SAMPLED REVIEW THRESHOLD with an
> executable breach action (pause all Team2 entries and adds, exits kept, no automatic return to size 1.0); the
> cross-check is by bucket identity; F127 is scoped to the selected contract's expiry and merged as v0.7.88.

**Status: for the other team's approval. Nothing activated.** Research settings unchanged (C1 / C2 / room rules /
near-ITM as they are; C2's validation window sealed). Data labels corrected: every number here is on the
**exploratory** pre-C6 banked tape (dataset `27516b61…`, 48 paired symbol-sessions, 08-20 → 09-11). C6 is pending; the
canonical-data activation gate agreed earlier is retained.

## 1. The sizing basis, recomputed with the intended Practice sizing (correction 2) — APPROXIMATE

The sweep's $600 per full unit is **premium invested**. The Practice book sizes by **loss risk**: `contracts =
int(equity × risk_pct / (premium × 100 × premium_stop_pct) × sizeMult)`, then `min(budget // premium)`, the contract cap,
floor 1 (`min_one_contract` on). Live settings on the `Team2 Practice` book today: equity **$9,934**, `risk_pct` **6 %**
($596 at risk per full trade), `premium_stop_pct` **25 %**, `budget_per_trade` **$2,000**, `risk.max_option_contracts`
**50**, `techniques.team2.zero_dte.max_contracts` **40**, `size_full` 1.0 / `size_small` 0.5.

At the tape's premiums ($0.21–$0.76, median ≈ $0.40) the risk formula asks for 40–110 contracts per full trade, so the
**$2,000 budget and the 40-contract cap bind, not the risk %**: a typical trade invests **$1,250 of premium** (median),
up to $1,976, with **$312 of modeled stop risk** (median, max $494). A research half-unit is $300 of premium; the
Practice book's "small" trade is four times that. The research drawdowns therefore do not transfer; the Practice-scale
figures below are the right SCALE (`profitability-20260915-exploratory/calibrate_practice.py`, output
`practice_calibration.json`) — an estimate, not a live replay and not a marked-to-market budget derivation. What it
simulates: integer initial quantities from the live formula, the $2,000 budget, the contract cap, one position
desk-wide, the two-loss day cap, the day-loss halt (2 × 6 %) and the 10 % technique pause on closed-trade day P&L, the
15 % breaker on closed-trade equity (never tripped on this tape), equity compounding trade by trade. What it does NOT:
intratrade marked-to-market equity, integer trim/add feasibility (trims and adds keep the model's fractions), exact fee
cash flows (the model's pnlPct nets $1.04/side inside its percentage; `pnlPct × premium invested` is not exact dollar
accounting — an explicit entry+exit fee column on the integer quantity is reported for scale), live quotes, the live
day's cutoff/flatten timing. Drawdown is closed-trade equity from the $9,934 start.

| Arm (0DTE cap 40, approximate) | Book trades | Modeled P&L | Max DD | Worst day | Without best day | Contracts min / med / max (at cap) | Premium invested med / max | Stop risk med / max |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| Baseline | 36 | **+$1,374** | **−$993 (10.0 %)** | −$839 | +$242 | 13 / 28 / 40 (8) | $1,250 / $1,976 | $312 / $494 |
| **Sizing cap 0.5** | 36 | **+$2,231** | **−$635 (6.4 %)** | −$503 | +$1,077 | 13 / 25 / 40 (6) | $1,250 / $1,510 | $312 / $378 |
| C1 conjunction (context) | 50 | +$6,415 | **−$2,619 (26.4 %)** | −$949 | +$4,489 | 12 / 28 / 40 (10) | $1,359 / $1,976 | $340 / $494 |

By symbol (sizing cap): SPY −$791, QQQ +$1,257, IWM +$1,765 (baseline SPY −$1,249, QQQ +$1,215, IWM +$1,407). With the
risk cap at 50 instead of 40 the picture is the same (baseline +$1,700 / DD −$1,013; cap +$2,655 / DD −$742).
Cross-check (corrected): the cap applied to the baseline's trades BY BUCKET IDENTITY — every full-location trade halved,
including the ones P7 had already reduced to 0.5 — gives exactly the sizing-cap arm's +$2,231 / −$635 (the earlier
multiplier-only cross-check, +$1,861 / −$832, missed those P7-reduced trades and was not the same transformation).

Two things this recalculation shows:

- **C1 at Practice scale draws down 26 % of the book.** The $700 budget proposed yesterday was not justified by the
  research scale, and C1 cannot be run under any budget the desk has operated with until its sizing is reconsidered
  — one more reason to put the sizing cap first.
- **A live defect found while calibrating (F127): today 11:14 ET the IWM `pm_break_down@10:30#2` entry (284P, ask
  $0.33, opra) was sized to 50 contracts and REFUSED by the RiskGate — "50 contracts exceeds the team2 0DTE cap 40".**
  The sizer capped at `risk.max_option_contracts` (50) while the 0DTE policy cap (40) is a rejection, not a clamp. The
  refusal depends on premium AND requested size together (at $0.33 a full-size request asks 60 → 50 → refused; the same
  premium at multiplier 0.5 asks 36 and clears). First occurrence in the journal. **Fixed as v0.7.88 (PR #144,
  conditional GO): the sizer clamps to the policy cap for a contract that expires TODAY, judged by the selected
  contract's OCC expiry on the RiskGate's own date basis; a longer-dated contract keeps its existing cap; the RiskGate
  is unchanged; the reviewer's expiry regression is in the suite.** Baseline and experiment evidence are stamped with
  the execution version from v0.7.88 on.

## 2. Frozen experiment rules (sizing cap first)

| Item | Setting |
|---|---|
| Label | `team2-sizing-cap-2026-09` — journaled on the settings change, recorded in TRADING-RULES |
| The one change | `techniques.team2.size_full` **1.0 → 0.5**. Nothing else: `size_small` 0.5, entries, exits, targets, adds, premium band, `no_trade_zone` pm_range, room rules, C2 off, F81b as is |
| Effect | the "full" location (beyond the PDH/PDL zone) trades at the same size as "small"; P7's after-win reduction then halves those exposures too (0.5 → 0.25) — 19 of 54 model trades on the tape (10 of the 36 the book selected: 7 at 1.0 → 0.5, 3 already P7-reduced at 0.5 → 0.25) |
| Prerequisites | v0.7.88 (F127) deployed (live since 09-15 17:12 PT); the C6 canonical-data gate retained (still outstanding); the per-book PAUSE route (v0.7.90: `POST /api/portfolios/{id}/pause` / `/unpause`) so the breach action below is executable by the desk and the watch job |
| Book | `Team2 Practice`, starting equity taken at activation (today $9,934), the existing 6 % risk, $2,000 budget, cap 40 |
| **Loss stop (sampled review threshold)** | **−$800 of marked-to-market peak-to-trough equity since activation (8 % of starting equity; a policy choice, ≈ 1.25 × the approximate modeled DD of $635), open positions and fees included** — evaluated at the watch job's 30-minute tick and at each close. It is a SAMPLED review trigger, not an enforced limit: the high-water mark is sampled, and price moves or fills can overshoot it. The ENFORCED limits stay the existing ones: F33's per-entry remaining-budget check, the day-loss halt (−$1,192), the 10 % technique pause and the 15 % book breaker. Recorded at activation and on every check: starting equity, high-water mark, marking basis (bid for held contracts), fees, and the pause state |
| **Breach action** | PAUSE the `Team2 Practice` book (v0.7.90: `POST /api/portfolios/<Team2 Practice id>/pause` with reason `experiment loss stop: <drawdown>` and label `team2-sizing-cap-2026-09`): every Team2 entry AND add on that book is refused (the runners via `trading_halted`, the RiskGate via `book_pause`), protective exits stay active (`halt_allows_exits`), other books are untouched; unlike the daily-loss halt the pause has no day — it survives restarts and the ET day roll and ends only with `/unpause` after an explicit review; the record snapshots `size_full` (stays 0.5 while paused — **no automatic return to 1.0**); releasing the pause never clears the kill switch or a daily-loss halt, and they never clear it; the breach, the equity path and the pause state are journaled (`BookPaused` / `BookPauseReleased`) |
| Observation window | **ten completed sessions**; twenty distinct filled opportunities (not retries, repeated signals or adds) trigger an **interim review only**; the count of independent dates is reported; insufficient exposure is stated, never extended or retuned; every session's evidence carries the execution version (v0.7.88+) |
| What is measured | **actual fills, separately**: after-cost $ P&L from the book's own fills, contracts, premium invested, stop risk, drawdown (marked-to-market), exposure (minutes, units), by date and symbol. **Simulated, labelled as such**: the baseline sizing replayed on the same frozen sessions with integer quantities, trim feasibility and costs (`Team2Service.replay` with `size_full=1.0`), which is a modeled counterfactual, never mixed with the fills |
| Not in this experiment | C1, C2, room rules, exits, premium target, adds, C6 |
| Review | after ten sessions: the same paired method (matched trades — identical by construction here — dollar P&L, drawdown, worst day, remove-best-day, two-tick sensitivity via replay); a review, never a promotion |

## 2b. Parallel design (review team's GO, 2026-09-15) — three books, one change each

| Book | Rules | Threshold (sampled review; breach → pause, no auto reset) |
|---|---|---|
| Team2 Control | shared baseline | the existing protections only |
| Team2 Sizing 0.5 | baseline + `size_full` 0.5 | −$800 of marked-to-market peak-to-trough since activation (§2) |
| Team2 C1 Conjunction | baseline + `no_trade_zone` conjunction (newly eligible setups small by construction) | **−$1,000** = 10 % of the $10,000 start — a policy figure equal to the desk's technique day-loss pause level applied cumulatively; not derived from the backtest (the approximate modeled Practice-scale C1 drawdown is $2,619, so the review fires at ≈ 0.4× of it) and not the rejected $700 justification |

Equal $10,000 starts, the same market data, session timing and execution assumptions; each book keeps its own cash,
positions, loss counters, concurrency cap and pause state (`tests/test_team2_experiments.py`); C1 and the sizing cap
are never combined in one book; C2, room rules, exits, adds and premium selection unchanged everywhere. Measurement
per book: ten completed sessions observed concurrently, twenty distinct fills = interim review only, actual after-fee
P&L, marked-to-market drawdown, exposure, fills and refusals, by date and symbol; modeled replay kept separate; the
sealed C2 validation preserved. Activation stays conditional on **C6** and verified isolation; the readiness receipt
(`zargar.tools.team2_receipt`) is sent before the open.

## 3. C1 as the follow-on (superseded by §2b: parallel, not sequential)

After the sizing review, C1 conjunction is the next **independent** comparison on its own frozen prospective period
(baseline vs C1, both complete paths), with its budget set from the Practice-scale recalculation — which at today's
sizing is a 26 % drawdown, so C1's sheet must address sizing before its budget (a cap-first result makes that natural).
Resizing C1's observed trades estimates sizing conditional on C1; it is not the standalone sizing test, and is not
claimed as one.

## 4. Reporting corrections applied (from the review of PR #140)

- Labels: "canonical" → **exploratory** in the note, folder and script; the hash equality is a reproduction, not C6.
- Sizing attribution: 19 model trades change size (14 at 1.0 → 0.5, 5 already P7-reduced at 0.5 → 0.25); of the 36
  book-selected, 10 (7 + 3). The gain beyond halving the first seven is those already-reduced full-location exposures
  being halved too — not a newly induced P7 response. Yesterday's note is corrected.
- C1 attribution: the classifier now reports **both sides of a displacement** (`displacedFrom`) and a `netVsBase`
  that reconciles to the model difference (44 shared, 4 displaced ← 3 displaced-from, 34 new, 7 lost: +198.3 + (−63.8)
  − (+90.9) − (−105.4) = +149.0 %-pts, the model difference being +149.1). `zargar.tools.team2_c2_report.classify` + its test.
- The reproduction script's side effects are stated: `SettingsService.load()` (a read) and the dataset-version record
  every sweep writes; no settings write, no orders.
- C1 + sizing combined stays disclosed as context only; it is not a candidate.
