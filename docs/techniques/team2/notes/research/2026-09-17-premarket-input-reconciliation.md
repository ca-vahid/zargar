# Pre-market input reconciliation — 2026-09-17 (EOD review §5, GO for a source/derived-level audit)

*Read-only reconciliation of the frozen plan extremes against the bank and the plans' own journal, run 2026-09-17 evening with
`python -m zargar.tools.team2_pm_audit --date 2026-09-17` (built this session). The plans are NOT rewritten: the values the
desk traded on stay the record; this note says where they came from.*

## 1. Findings

| Symbol | Frozen (09:25:15 ET) | Bank now | Contributing minute | What produced the frozen value |
|---|---|---|---|---|
| SPY | PML **660.65** | 757.53 | 07:46 | an exchange **correction** delivered at 08:02:09.99 ET replaced the 07:46 bar 760.21/760.21/760.21/760.21/615 with 760.12/760.2369/**660.65**/760.2285/615 (same volume, low 100 points under the open — a dropped digit: 760.65). The bank kept the ORIGINAL bar. |
| SPY | PMH 764.00 | 763.99 | 09:01 | two corrections of the 09:01 bar (09:02:11 and 09:16:57), the second raising the high 763.99 → 764.00. The bank kept the original. |
| IWM | PML **283.92** | 285.35 | 04:00 | the 04:00 bar was corrected twice: 04:02:34 (285.97/286.41/285.97/286.07 → 286.03/286.41/286.03/286.07) and 04:16:06 (→ 285.97/286.41/**283.92**/286.08). The bank kept the first observation. |
| IWM | PMH 288.16 | 288.19 | 09:16 / 09:19 | the bank's 288.19 highs at 09:16 and 09:19 were never seen at that value by the private tape (its bars carry 288.16). |
| QQQ | PMH **716.76** | 716.78 | 08:34 | a correction at 08:35:17 lowered the 08:34 high 716.78 → 716.76. The bank kept 716.78. This 716.76 is the very level the day's pm_break_up setup anchored on and then targeted (§3 of the review). |
| QQQ | PML 704.192 | 704.192 | 08:01 | reconciled. |

Common mechanism, all three symbols: **the private tape (the runner's own bar list, `_bars[run_id]`) accepts every exchange
correction that arrives through the feed's exchange-bar channel (`Engine._ingest_exchange_bars` → `BarAggregator.ingest_exchange_bar`
→ published → `Team2Runner._merge_revision`, journaled as `bar_revised`), while the bank (`bars`, written by `persist_bars`) kept the
first observation of each of these minutes.** The plan's 09:25 completion reads the private tape (`_today_bars` → `complete_plan` →
`premarket_range`), so it froze the corrected values — including two corrupt lows and a 0.02 lower QQQ high.

Provenance of the corrections: every `bar_revised` row says `source exchange` on both sides. Yahoo seeding (F80) runs only at boot
(the engine was restarted 21:13 PT the previous evening, after hours), so the corrections that arrived 1–16 minutes after their
minute came through the live exchange-bar channel (Alpaca). The corrected values of the later QQQ revisions are float32-shaped
(716.760009765625, 716.5650024414062), which points at a specific decoding path in the correction source; the platform owners can
identify it from the `_ingest_exchange_bars` callers. Whether the correction bars were rejected by the persist path (calendar gate,
bucket alignment, precedence) or simply never sent to it is the open question for them — the outcome is the same: **two tapes**.

Did it cost a fill? SPY's one refusal (761.67) sits inside both the frozen and the banked PM range; IWM's refusals sit inside the
corrected ranges too. No evidence today's discrepancies changed a decision — the QQQ 716.76/716.78 difference did define the setup's
anchor and target to the cent, which is why the identity guard (item 1) judges identity rather than distance.

## 2. What changed in code (v0.8.12)

- `plan.complete_plan` records `pmExtrema`: for PMH and PML the source bar (ts, OHLCV, provenance) and for the inputs the count,
  first/last timestamp, provenance set and a SHA-1 of every pre-market bar. Journaled as `TechniquePlanRead/premarket_extrema` at the
  09:25 completion and again at the 09:30 finalization (the warm-up hash rides beside it).
- `zargar.tools.team2_pm_audit --date` reconciles frozen vs bank per plan and, for each discrepancy, lists the contributing minute,
  the bank's row, and every journaled revision of that minute with before/after and whether the bank kept the correction. Plans
  minted before v0.8.12 have no `pmExtrema`; the tool infers the contributing minute from the revisions (as above).

## 3. C6 consequence

Complete RTH coverage and `source=exchange` do not make one tape (review 2026-09-16); today shows a second reason: the live desk's
decision inputs include pre-market minutes the bank never held. C6 closure therefore needs (a) the pre-market input hash of each plan
(`pmExtrema.inputs.hash`) to equal the hash of the bank's pre-market rows for that date, or the differing minutes named and ruled on;
(b) the warm-up hash (`plan.warmup.hash`, F99) likewise; (c) the platform owners' answer on why exchange corrections reach the private
tape and not the bank (and whether corrupt corrections — a 100-point low on a flat bar — should be quarantined at intake rather than
merged). Added to `2026-09-16-c6-completion-plan.md` as step 1e.

## 4. Not done, on purpose

No frozen plan was edited, no bar was repaired, no decision was re-run. The corrupt lows are reported with their chain of
observations; how the bank and the private tape should reconcile is the platform owners' policy (PLATFORM-RULES entry added).
