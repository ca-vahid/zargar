# Tips — how 2026-09-23 went, and what to improve (observed session 3 of 5)

Written the evening of 2026-09-23 from the journal, the position records, 1-minute bars and today's analyst runs.
Numbers are Tips Practice, net of `executions.commission` (all fills today had $0 commission). Two defects found
today are fixed in this PR; everything else here is a proposal and changes nothing until decided.

## 1. The day in one table

| | |
|---|---|
| Realized | **-$38.13** (IONQ +85.85, NEM -39.28, SBLK -84.70); marked change -$40.07 |
| Model cost (list estimate) | $59.57 priced (99 intake reviews $51.81, 12 appraisals $7.76) — the smallest of the week (Mon $115.65, Tue $100.45) |
| Funnel | 16 ideas → 4 takes → 1 fill (JELD); 12 declined, 2 risk-infeasible, 0 avoidable misses |
| Cards that needed a human | 8; **3 expired unseen** (HOOD, GOOGL, AMAT) |
| Relevance filter | 98 decisions, 76 review / 22 skip, 0 read errors |
| Deploys | EM 0.8.38 (16:02) and Tips 0.8.39 (16:41), both verified; intake stalled only during the restart window |

## 2. What actually happened at the open (1-minute bars)

- **NEM (-$39.28):** gapped down 2.7% (127.26 close → 123.83 open) and drifted into its $122.60 stop within three
  minutes. **The source was already flat:** at 09:06 ab's "Mid Week Update" listed the NEM 130C under *Realized*.
  The review saw it ("the author … is now FLAT") and chose to tighten the stop and shorten the time box instead of
  closing. Closing at the open would have lost about -$27 instead of -$39. Small money, but it is the desk's own best
  exit class (mirrored source exits, +$332 over the window) not being applied.
- **SBLK (-$84.70):** an ordinary stop-out, drifting 30.94 → 30.58 over six minutes; held since 09-17.
- **IONQ (+$85.85):** gapped **up** 12% (40.75 → 45.83). Half was sold at the open mirroring neal (+$70.99, correct).
  The other half slid from about $45.80 into a stop still at the pre-gap $41.79 (+$14.86): roughly **$55 of open
  profit given back** because nothing moves a stop after a large favourable gap.

## 3. Defects found and fixed today (this PR)

1. **Recovery sweep raced the live appraisal (AMAT, 14:03).** A cold-parked call tip was re-verified by the recovery
   sweep 16 s before the analyst finished (with *skip*). The sweep minted a card with no opinion and the book's
   default vehicle (3 shares instead of the tip's 9/25 500C). It only waited for a human because it had no stop. Fix:
   the sweep leaves a park alone while its appraisal is in flight (`appraisal_pending`: analyst available, no verdict,
   younger than 15 minutes — the intake re-checks its own park when the appraisal ends); tests in `test_recovery.py`.
2. **`update_exit_plan` blanked fields it was not given (NEM, 09:07).** A stop-only edit wiped the profit ladder; the
   analyst paid a second call to restore it. Fix: an omitted field keeps its current value (`carried_exit_fields`);
   an explicit empty ladder is still honoured; the tool description says so.

## 4. Improvement proposals (need a decision; nothing is switched)

| # | Proposal | Evidence | Expected value | Cost / risk |
|---|---|---|---|---|
| P-A | **Close the mirror when the author is flat.** When a review finds the source's own position closed (realized/absent), close our mirrored position at the next opportunity instead of only tightening, unless the analyst states a separate thesis. Prompt rule first, measured over 10 sessions. | NEM today; mirrored exits are the best exit class (+$332) | a few $10s per occurrence; aligns with the desk's own record | a prompt/rule change — rulebook is propose-only, needs your approval |
| P-B | **Move a stop after a large favourable gap.** Research first: on the hold study's close→open samples, compare "stop to prior close (or breakeven) after a gap ≥ 1 R in our favour" against today's behaviour. | IONQ gave back ~$55 of a +12% gap | unknown until measured | D2/D3-class exit change → study only, no live change without the comparison |
| P-C | **Alert on a card that needs a human.** Review-required cards send nothing (no push, no Telegram); three expired unseen today. Send one push/Telegram line per review card (symbol, why, expiry). | HOOD, GOOGL, AMAT expired | recovers takes the budget could not size (the share alternative is on the card) | small build; no trading change |
| P-D | **Cache the rulebook across runs.** Caching works (uncached input fell to ~0), but each review still WRITES ~34k tokens of cache because the message sits before the rulebook in the prompt. Put the stable rulebook first with its own cache marker so consecutive runs share it. | 29 reviews 13:46–16:41: 2.06M read, 0.97M written | est. -$0.05 to -$0.07 per review (≈ -$5/day) on top of today's caching | prompt order change: must pass the frozen A/B (same instructions) before activation |
| P-E | **Equal-risk shares when the option cannot be sized (Practice).** Today the card shows the share alternative but waits for a human. Option: in Practice only, take the share alternative automatically when the analyst said take. | HOOD (15 sh), GOOGL (5 sh) takes were lost | recovers infeasible takes | a trading-policy change — your decision; P-C is the low-risk step first |
| P-G | **Deploy restore verifier compares too early** (EM desk finding, 0.8.40 at 20:45 ET): `deploy.ps1` exited 6 on "RESTORE MISMATCH armed 118/206" although all 206 plans restored moments later. `start.ps1` waits only for the armed count to hold 3 s (≤ 20 s), then `restore-check` for ≤ 60 s; EM now arms ~190 plans a night (was ~80). Wait on a restore-complete signal from the engine, with the stable-count poll as fallback, then compare ids. | 0.8.40 receipt, EM message | deploy failures stop being false alarms | platform deploy tooling; bundle with the after-hours MKT restore-rule fix (both need your go) |
| P-F | **Level maps create card noise.** eva's pre-bell map ("SPX 7760 on watch…") was sliced into 10 signals and 4 review cards, all declined by inheritance. Teach extraction that a two-sided level map is one non-actionable context signal. | 09:19 today, 4 cards | fewer cards, fewer appraisals | extraction prompt change → through the extraction A/B |

## 5. Cost package status (from `2026-09-23-cost-levers.md`)

Live since 16:41 ET: conversation caching, Opus 5.5 (effort pinned high), non-actionable review skip, batching for
digests + audits, per-call extraction cost records. The evening A/B **rejected** Sonnet 5 for extraction (it read two
real calls as non-actionable) and the notes-only review trim (4 missed management actions vs 2 for the reference);
both stay off. The next cost lever is P-D (rulebook-first caching).

## 6. Suggested order

1. Deploy the two fixes (tonight, after the A/B finishes; outside market hours).
2. P-C (card alerts) and P-D (rulebook-first caching, through the frozen A/B) — no trading change.
3. P-A as a proposed rule for your approval; P-B as a study on the hold-study data.
4. P-E and P-F only after P-C has run for a week.

## 7. What was done (2026-09-23 evening, user: "do everything right now"; 0.8.41 + 0.8.42)

| # | Outcome |
|---|---|
| fixes | 0.8.41 DEPLOYED 20:59 ET (recovery-sweep race, `update_exit_plan` field carry) |
| P-A | BUILT: review prompt rule "AUTHOR FLAT = CLOSE THE MIRROR" (live with the 0.8.42 deploy) |
| P-B | STUDIED, NOT BUILT: `tools/tip_gap_stop_study.py` over 21 share positions in non-quarantined books. With the stop journaled in force each morning, only ONE favourable gap >= 1 R qualified and the rule did not fire (today's IONQ stop was already above the prior close, so "stop to prior close" would not have saved the ~$55). Keeping part of a gap is a different rule with no evidence yet. |
| P-C | BUILT + ON: `TipCardAlert` push + Telegram for a card still pending after 20 s (`techniques.tip.card_alerts`) |
| P-D | BUILT: `techniques.tip.prompt_cache_stable_first` (rulebook first as its own cached block); switched on at deploy, cache reads/writes measured on the next session's runs |
| P-E | BUILT: `techniques.tip.shares_alternative_auto` (Practice only: take + long + option refused only for size -> equal-risk shares, journaled `TipSharesSubstituted`); switched on at deploy |
| P-F | NOT BUILT: the level-map cards are already auto-declined by the analyst in one inherited call and P-C only alerts cards still pending, so they cost little and page nobody; changing extraction risks losing real conditional level calls (the armed lane). |
| P-G | BUILT: `restart.ps1` / `start.ps1` restore check passes on OK and reports a mismatch only after the missing set has stopped shrinking for 60 s (max 5 min); companion fix `orders.market_order_age` - an after-hours market order ages from the next open, and `SimBookRestored` carries each cancellation's reason |

