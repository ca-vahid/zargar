# C1 conjunction and the sizing map — controlled comparisons on the canonical tape (2026-09-15)

**Recommendation in one line: run C1 conjunction as the next labelled Practice experiment (settings and risk budget in
§5); measure the sizing cap (`size_full` 0.5) as the follow-on — it improves both return and drawdown without touching
a single entry or exit, but it must be judged on its own sessions, not folded into C1.**

Other team's GO of 2026-09-15: reproduce their sweep on canonical data, compare C1 against baseline and the sizing map
against baseline separately, report after-cost $ P&L, drawdown, exposure, by date/symbol, sensitivity to worse fills,
the same eligible sample, and whether each improvement survives removing its best day. No Practice activation here;
C2's validation window (2026-09-14 → 10-09) untouched.

## 1. Sample, tape and method

- Dates 2026-08-20 → 09-11 (16 sessions), SPY/QQQ/IWM: **48 symbol-sessions eligible in every arm, none dropped**
  (`Team2Service.paired_rows`). Tape = the banked 1m bars, validated sessions, dataset content hash
  **`27516b6136abad09…`** — identical to the other team's sweep hash, so their table is reproduced exactly (baseline
  36 book trades +$471 / DD $320; C1 50 / +$1,514 / DD $565). C6's per-provider canonical tape is still pending; this
  is the same pre-C6 exchange-provenance tape as theirs, with the synthetic $1 strike grid and flat-IV model prices.
- Every arm is a full in-process rerun of the read (`Team2Service.sweep` with a knob overlay), never a filter on the
  baseline table. Costs: $1.04 per contract per side and one slippage tick in every arm; the "worse fills" arms rerun
  the whole method with **two** slippage ticks (entries, exits and the loss cap all move, unlike a fixed-trade
  deduction). $ figures = the existing chronological book at **$600 per full unit** (one open position desk-wide, two
  losses end the day; closed-trade equity, so drawdown is not intratrade). Script and JSON:
  `profitability-20260915-canonical/`.

## 2. Results on the same 48 cells

| Arm | Model trades | Book trades | Book P&L | PF | Max DD | Worst day | Minutes | Units deployed | Full-unit trades |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 54 | 36 | **+$471** | 1.36 | $320 | −$271 | 220 | 20.0 | 7 (−$367) |
| **C1 conjunction** | 82 | 50 | **+$1,514** | 1.96 | $565 | −$271 | 234 | 23.5 | 3 (−$410) |
| **Sizing: `size_full` 0.5** | 54 | 36 | **+$763** | 1.86 | **$187** | **−$141** | 220 | 15.75 | 0 |
| Baseline, 2-tick fills | 54 | 36 | −$121 | 0.93 | $459 | −$314 | 220 | 20.5 | 7 |
| C1, 2-tick fills | 82 | 50 | +$820 | 1.43 | $772 | −$314 | 234 | 24.25 | 3 |
| Sizing 0.5, 2-tick fills | 54 | 36 | +$293 | 1.26 | $340 | −$182 | 220 | 16.25 | 0 |
| C1 + sizing 0.5 (context only, not a candidate) | 82 | 50 | +$1,780 | 2.36 | $521 | −$194 | 234 | 21.5 | 0 |

By symbol ($): baseline IWM +610 / QQQ +296 / SPY −434; C1 IWM +874 / QQQ +619 / SPY +21; sizing IWM +622 / QQQ +296 /
SPY −155. Earlier dates (08-20..09-04) vs week 37: baseline +$281 / +$190; C1 +$655 / +$858; sizing +$593 / +$168.
By date for every arm is in `comparisons.json` (`arms.<name>.book.byDate`).

### 2a. C1 conjunction vs baseline (+$1,043; DD +$245, +77 %)

- Matched trades: 44 unchanged, 0 changed exits, 4 displaced (−63.8 %-pts), **34 new (+198.3 %-pts)**, 7 lost
  (−105.4 %-pts). The gain is new small-size entries reaching the book, not changed exits.
- Every new entry is bucket `small` by construction (the truth table never grants `full` inside the PM range): C1's
  three full-unit trades lose $410, its 35 half-size trades make $1,867.
- Remove the best day: both arms' best absolute day is 09-02 (+$401) — without it baseline +$70, C1 +$1,113. Remove
  C1's best *incremental* date (08-20, +$389 of the advantage): **+$654 remains**.
- Worse fills (two ticks): baseline falls to −$121, C1 keeps +$820 (advantage +$941) — but C1's drawdown at two ticks
  is $772, worst day −$314. The cost margin is the risk, not the direction.
- Where the advantage comes from by date: 08-20 (+$389), 09-11 (+$330, a date the baseline never trades), 09-10
  (+$357), 08-25 (+$198, another baseline-empty date); it gives back on 08-27 (−$140) and 08-31 (−$158).

### 2b. Sizing cap vs baseline (+$292; DD −$133, −42 %)

- **Entries and exits are identical**: 54 unchanged matched trades, 0 new/lost/displaced. The whole effect is the
  arithmetic of the 7 full-unit trades (−$367 at 1.0 → −$183 at 0.5) plus P7's shrink-after-win re-sizing later the
  same day (x0.25 trades 6 → 9), which is why it is +$292 rather than +$184.
- Worst day −$141 vs −$271; profit factor 1.86; units deployed 15.75 vs 20.0; maximum premium at risk $300 vs $600.
- Remove the best incremental date (09-03, the day the full-unit losers hit): **+$132 remains**. Worse fills: +$414
  advantage (+$293 vs −$121), drawdown $340 vs $459.
- Caveat: 7 full-unit trades is a thin sample, and "full" here is a location label (beyond the PDH/PDL zone) — the
  finding is that the method's biggest-conviction location has not paid on this tape, not that size causes losses.

## 3. What this does and does not establish

- The reproduction is exact (same hash, same numbers), so the other team's lead is confirmed on the banked tape; it is
  still one 16-date development sample, pre-C6, model prices, and the read's own book post-filter. The C1 advantage is
  concentrated (four dates carry it) and its two-tick drawdown ($772) exceeds any budget the desk has run under.
- The sizing cap is the more robust of the two per unit of evidence (identical trades, improves every risk figure,
  survives worse fills and best-day removal), but its dollar gain is small (+$292) and rests on 7 trades.
- Combining them (+$1,780, DD $521, PF 2.36) is shown for context only; the review asked for attribution first.

## 4. Decision the desk proposes

**C1 first**, as a labelled Practice experiment with the budget below; the sizing cap registered as the next isolated
experiment after C1's review (or measured by paired replay on C1's sessions, since it changes no entry or exit — the
same live trades re-priced at 0.5 are a valid measurement without a second live experiment). Nothing else changes.

## 5. Proposed C1 Practice experiment (for approval — not activated)

| Item | Setting |
|---|---|
| Label | `team2-c1-conjunction-2026-09` (journaled on the settings change; noted in TRADING-RULES) |
| Change | `techniques.team2.no_trade_zone` = `conjunction` — nothing else (`pm_room_atr` 0, `min_target_atr` 0, `key_levels` off, `size_*` unchanged, F81b as is) |
| Newly eligible entries | small by construction (bucket `small` = `size_small` 0.5); no full-unit entry is created by the change |
| Book | `Team2 Practice` ($10,000; the risk unit ≈ 6 % = $600 ≈ the research unit) |
| Risk budget | stop the experiment (knob back to `pm_range`, journaled) if the book's peak-to-trough drawdown since the start exceeds **$700** (≈ 1.25 × the modeled $565), or the desk-wide day-loss cap fires on newly eligible entries on **three consecutive sessions**; the existing 10 % technique pause and 15 % book breaker stay |
| Duration | **10 sessions or 20 newly eligible entries**, whichever first; then a review, never a promotion |
| Measurement | the same paired method on the live sessions: baseline vs conjunction replayed on identical bars (`Team2Service.replay` with the overlay), matched trades (new / lost / displaced), after-cost $ from the BOOK's fills, drawdown, exposure, by date/symbol, two-tick sensitivity, remove-best-day; the live-vs-replay gap reported per session |
| Not in this experiment | the sizing cap, C2, exits, premium target, adds, C6 |
| Abort conditions unrelated to P&L | any execution-integrity finding (the 09-14 batch's classes) reopens before activation |

## 6. Reproduction

```
cd backend && .venv/Scripts/python.exe ../docs/techniques/team2/notes/research/profitability-20260915-canonical/research_profit.py
```
(reads the runtime DB read-only through `backend/.env`; writes only the dataset-version record every sweep writes).
