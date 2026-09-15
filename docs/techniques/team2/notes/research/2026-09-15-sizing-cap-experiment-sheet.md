# Experiment sheet — sizing cap first (`size_full` 0.5), C1 as the follow-on — 2026-09-15

**Status: for the other team's approval. Nothing activated.** Research settings unchanged (C1 / C2 / room rules /
near-ITM as they are; C2's validation window sealed). Data labels corrected: every number here is on the
**exploratory** pre-C6 banked tape (dataset `27516b61…`, 48 paired symbol-sessions, 08-20 → 09-11). C6 is pending; the
canonical-data activation gate agreed earlier is retained.

## 1. The sizing basis, recomputed with the intended Practice sizing (correction 2)

The sweep's $600 per full unit is **premium invested**. The Practice book sizes by **loss risk**: `contracts =
int(equity × risk_pct / (premium × 100 × premium_stop_pct) × sizeMult)`, then `min(budget // premium)`, the contract cap,
floor 1 (`min_one_contract` on). Live settings on the `Team2 Practice` book today: equity **$9,934**, `risk_pct` **6 %**
($596 at risk per full trade), `premium_stop_pct` **25 %**, `budget_per_trade` **$2,000**, `risk.max_option_contracts`
**50**, `techniques.team2.zero_dte.max_contracts` **40**, `size_full` 1.0 / `size_small` 0.5.

At the tape's premiums ($0.21–$0.76, median ≈ $0.40) the risk formula asks for 40–110 contracts per full trade, so the
**$2,000 budget and the 40-contract cap bind, not the risk %**: a typical trade invests **$1,250 of premium** (median),
up to $1,976, with **$312 of modeled stop risk** (median, max $494). A research half-unit is $300 of premium; the
Practice book's "small" trade is four times that. The research drawdowns therefore do not transfer; the Practice-scale
figures below do (`profitability-20260915-exploratory/calibrate_practice.py`, output `practice_calibration.json`;
equity compounds trade by trade; the day-loss halt (2 × 6 %) and the 10 % technique pause are applied; drawdown is
closed-trade equity from the $9,934 start).

| Arm (0DTE cap 40) | Book trades | Modeled P&L | Max DD | Worst day | Without best day | Contracts min / med / max (at cap) | Premium invested med / max | Stop risk med / max |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| Baseline | 36 | **+$1,374** | **−$993 (10.0 %)** | −$839 | +$242 | 13 / 28 / 40 (8) | $1,250 / $1,976 | $312 / $494 |
| **Sizing cap 0.5** | 36 | **+$2,231** | **−$635 (6.4 %)** | −$503 | +$1,077 | 13 / 25 / 40 (6) | $1,250 / $1,510 | $312 / $378 |
| C1 conjunction (context) | 50 | +$6,415 | **−$2,619 (26.4 %)** | −$949 | +$4,489 | 12 / 28 / 40 (10) | $1,359 / $1,976 | $340 / $494 |

By symbol (sizing cap): SPY −$791, QQQ +$1,257, IWM +$1,765 (baseline SPY −$1,249, QQQ +$1,215, IWM +$1,407). With the
risk cap at 50 instead of 40 the picture is the same (baseline +$1,700 / DD −$1,013; cap +$2,655 / DD −$742).

Two things this recalculation shows:

- **C1 at Practice scale draws down 26 % of the book.** The $700 budget proposed yesterday was not justified by the
  research scale, and C1 cannot be run under any budget the desk has operated with until its sizing is reconsidered
  — one more reason to put the sizing cap first.
- **A live defect found while calibrating: today 11:14 ET the IWM `pm_break_down@10:30#2` entry (284P, ask $0.33,
  opra) was sized to 50 contracts and REFUSED by the RiskGate — "50 contracts exceeds the team2 0DTE cap 40".** The
  sizer caps at `risk.max_option_contracts` (50) and the 0DTE policy cap (40) is a rejection, not a clamp, so every
  contract cheaper than ≈ $0.50 (where the $2,000 budget would cap at 40) is refused outright. First occurrence in the
  journal (earlier fills were dearer). Fix prepared on its own branch (PR held open, not merged): the sizer clamps to
  the technique's 0DTE `max_contracts` before the order. It changes live sizing (refusal → 40 contracts), so it is
  presented for GO rather than deployed; the experiment cannot start before it, because the baseline itself does not
  fill cheap contracts today.

## 2. Frozen experiment rules (sizing cap first)

| Item | Setting |
|---|---|
| Label | `team2-sizing-cap-2026-09` — journaled on the settings change, recorded in TRADING-RULES |
| The one change | `techniques.team2.size_full` **1.0 → 0.5**. Nothing else: `size_small` 0.5, entries, exits, targets, adds, premium band, `no_trade_zone` pm_range, room rules, C2 off, F81b as is |
| Effect | the "full" location (beyond the PDH/PDL zone) trades at the same size as "small"; P7's after-win reduction then halves those exposures too (0.5 → 0.25) — 19 of 54 model trades on the tape (10 of the 36 the book selected: 7 at 1.0 → 0.5, 3 already P7-reduced at 0.5 → 0.25) |
| Prerequisite | the 0DTE cap clamp deployed (§1) so the baseline and the experiment both fill cheap contracts |
| Book | `Team2 Practice`, starting equity taken at activation (today $9,934), the existing 6 % risk, $2,000 budget, cap 40 |
| **Loss stop** | marked-to-market peak-to-trough equity of the book since activation, **open positions and fees included**, checked **every 30 minutes** by the watch job and at each close: **breach at −$800 (8 % of starting equity ≈ 1.25 × the modeled Practice-scale DD of $635)** → the knob goes back to 1.0 (journaled), **no new experiment entries**, protective exits (premium stop, target, quote stop, 15:45 flatten) stay in force; the existing day-loss halt (−$1,192), 10 % technique pause and 15 % breaker are unchanged and independent |
| Observation window | **ten completed sessions**; twenty distinct filled opportunities (not retries, repeated signals or adds) trigger an **interim review only**; the count of independent dates is reported; insufficient exposure is stated, never extended or retuned |
| What is measured | **actual fills, separately**: after-cost $ P&L from the book's own fills, contracts, premium invested, stop risk, drawdown (marked-to-market), exposure (minutes, units), by date and symbol. **Simulated, labelled as such**: the baseline sizing replayed on the same frozen sessions with integer quantities, trim feasibility and costs (`Team2Service.replay` with `size_full=1.0`), which is a modeled counterfactual, never mixed with the fills |
| Not in this experiment | C1, C2, room rules, exits, premium target, adds, C6 |
| Review | after ten sessions: the same paired method (matched trades — identical by construction here — dollar P&L, drawdown, worst day, remove-best-day, two-tick sensitivity via replay); a review, never a promotion |

## 3. C1 as the follow-on

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
