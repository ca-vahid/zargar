# Team2 retired — 2026-10-05 (user decision: "retire for now, revisit later")

Team2 automation, its experiments and its selection study are switched off. Nothing was deleted. This is the closing
record: what was switched, the final numbers, what was learned, and how to bring it back. All money figures are
**simulated** Practice books; Team2 never traded real money.

## 1. What was switched (2026-10-05, about 20:30 PT, journaled endpoints, no restart)

| item | before | now |
|---|---|---|
| `techniques.team2.enabled` | true | **false**: the nightly mint returns `skipped: disabled`, and the runner is not built on the next boot |
| `techniques.team2.selection_study` | collect | **off** |
| `techniques.team2.experiments` | enabled (sizing 363f1934, c1 bf259522, control 53139dc3) | `{"enabled": false, "books": []}` |
| armed plans for 2026-10-06 | 9 | 0 (disarmed, no positions) |
| books `Team2 Control 09-28` 53139dc3, `Team2 Sizing 0.5 09-28` 363f1934, `Team2 C1 Conjunction 09-28` bf259522 | active (two paused) | **archived**; flat, no open orders |

Left as they were:
- `techniques.team2.mode` stays `auto`, and `default_portfolio` still names the archived Control.
- The observation state and the two book pauses are untouched.
- The code default of `techniques.team2.enabled` is still `True`. The persisted setting is what keeps Team2 off, so
  **a settings reset would bring it back**.

## 2. Final numbers (every Team2 book, 2026-09-08 .. 2026-10-05)

| book | entries | before fees | fees | net | days traded | green days |
|---|---|---|---|---|---|---|
| Team2 Practice (09-08..09-17) | 5 | −$412 | $166 | −$579 | 3 | 0 |
| Control (09-18..09-25) | 11 | −$1,521 | $578 | −$2,099 | 5 | 0 |
| Sizing 0.5 (09-18..09-24) | 11 | +$40 | $456 | −$416 | 4 | 1 |
| C1 Conjunction (09-18..09-22) | 5 | −$962 | $360 | −$1,322 | 3 | 0 |
| Control 09-28 (09-28..10-05) | 13 | −$1,279 | $730 | −$2,009 | 5 | 0 |
| **all** | **45** | **−$4,135** | **$2,290** | **−$6,425** | 20 book-days | **1** |

Selection study s1-r4: **10 of 60 sessions counted** (09-21..10-02), 26 opportunities, 17 with a valid outcome.
2026-10-05 was excluded for an in-session restart. It was stopped before its endpoint, so it has **no result**. Its
coverage data stays in the journal.

## 3. What we learned (in order of how sure we are)

1. **The live method loses on price before any fee** (measured).
   - Before fees: −$4,135 over 45 entries.
   - The replay on real option prints agrees in direction: −3.7% per trade at the books' fee, about zero with no fee.
   - A cheaper venue (IBKR ~$0.65 against $1.04) or dearer contracts only narrow the loss.
2. **Fees then add about half again** (measured).
   - Fees were $2,290 = 55% of the before-fee loss.
   - Round-trip fees are 7.4% of premium under $0.35, and the picker's first-OTM-under-$0.60 rule buys the most
     fee-heavy contracts.
3. **Eleven single-factor changes failed on real prints.** Nine preregistered variants ran on 2026-09-19, among them
   a two-candle stop, a 1.5 ATR target-room rule, a new-extreme trim, collision re-plan, no target exit and a dearer
   contract. H6 (premium stop −40% vs −25%) and the P1.1 parity test followed. None cleared its criterion.
4. **The premium stop is not the leak** (measured twice).
   - Its width does not matter (H6).
   - Applying it every ~2 s instead of on 2m closes changes the replay by −0.13 to −0.61 points per trade (P1.1).
5. **Execution defects were real and are fixed.** They did not change the picture.
   - F129: a model's proxy premium could sell a held contract.
   - F130/F131: stale resting entries, about −$690.
   - F132: the same decision priced from different spots across books.
6. **The experiment books taught little.**
   - Sizing 0.5's lead over Control came mostly from two defects.
   - C1 (conjunction no-trade zone) took more trades at the same negative expectancy.
   - Both hit their drawdown thresholds within days.
7. **We do not capture all of the author's method.**
   - On 2026-09-28 his +300% QQQ trade used an intraday swing low flipping to resistance, and a "3 bar play". Neither
     is in `METHOD.md`, which has flips for the daily levels only (`notes/x/2026-09-28-...md`).
   - His late-day 0DTE trades run past our 15:30 cutoff and 15:45 flatten.
   - His recaps are self-selected, so the gap is either discretion we do not model or selection in what he posts.
     Which one is unknown.
8. **Operations.** Host memory pressure caused multi-minute decision lag on held 0DTE positions (09-24: 197–322 s)
   and in-session restarts. A 0DTE technique needs a healthier host than this one was.

## 4. If Team2 is revisited — what to do first, and what not to repeat

- **Do not re-run the same single-factor variants** on the same training window. They are measured.
- **Start from selection, not execution.** The open question is which setups have a gross edge at all. The S1
  design (`profitability-2026-09-19/07-selection-study-spec.md`) is still the right instrument. It needs about 60
  sessions and does not need orders. It needs an armed plan in **alert** mode (verify with a test that an alert plan
  opens observations; a paused auto book does not, because `halt_skip` returns before the observation).
- **Capture the author's material first.** Run a weekly X capture through the signed-in browser. Then define the
  intraday-flip level causally and measure it order-free, like C2. C2's sealed validation window (09-14..10-09) was
  never opened and can still be used once.
- **Any practice book should buy fewer, dearer contracts** (H5 arithmetic) and report P&L at the intended venue's fee
  (`zargar.tools.team2_cost_lines`).
- **No real money** without a preregistered arm passing on held-out data.

## 5. How to bring it back (all reversible)

1. Unarchive the book(s): `POST /api/portfolios/{pid}/archive?archived=false`. A fresh book is cleaner.
2. `PATCH /api/settings`: `techniques.team2.enabled=true`, `techniques.team2.default_portfolio=<book>`, and
   `techniques.team2.mode` (`alert` to observe, `auto` to trade Practice).
3. Experiments: restore the `techniques.team2.experiments` map, **and seed
   `techniques.team2.experiment_observation.books`** for every experiment book. The drawdown watch skips books
   missing from it.
4. Selection study: `techniques.team2.selection_study=collect` continues registration s1-r4. Label a new collection
   cohort for the gap, as for the 2026-09-21 clock incident.
5. Restart through the deploy door so the runner is built, then `POST /api/team2/plan-now`.

Code, tests (`tests/test_team2_*.py`, 475 passing at v0.8.55), tools (`team2_cost_lines`, `team2_opportunity_audit`,
`team2_selection_study`, `team2_receipt`) and the replay harness all remain in the repo. Draft PR #255 was closed
unmerged at retirement. It held the H6 write-up, the `team2_exit_review` tool and the OPRA vendor-timestamp
recording, and its branch `claude/team2-h6-premium-backstop` is kept.
