# C2 — multi-day key levels as entry levels: frozen definitions and measurement protocol (v2)

v1 written 2026-09-13; **v2 revised the same day after the other team's review**
(`C:/Cursor/zargar-codex/docs/techniques/team2/notes/research/2026-09-13-c2-spec-reviewer-response.md`): validation
moved to genuinely unseen dates, one causal flip/expiry state machine, D1 simplified, D2/D3 made deterministic, what C2
changes stated honestly, acceptance criteria predeclared. **Nothing is measured, nothing is built.** Sweeps run only on
the canonical inputs after C6; C1, the room rule and C3 stay off and unchanged throughout. There is no fourth
definition.

Source basis (METHOD §0c): the author anchors on multi-day levels ("3 days of support at our 293.43 zone", a level "7
candles wick'd off today", a two-sessions-old high reclaimed by a gap) and treats a broken level that holds on the
retest as flipped (L1.4). Our engine has the previous session's high/low as entry zones (L1) and prior pivots as
targets only (L3). C2 asks whether a small set of multi-day levels, added as entry levels AND as target candidates
(§5 says why both), improves the baseline convincingly. Everything below the author did not state is labelled **our
research convention**, not his rule.

## 0. Common frame (identical for all three definitions)

### 0.1 Inputs and timestamps

- **Bars:** RTH 15-minute bars of the last `L = 10` completed sessions before the plan date, from the canonical tape
  (post-C6, hash recorded), validated by F75. The plan date's own bars never build the day's level set.
- **Build time:** the nightly 17:00 ET mint (`build_skeleton`). The candidate set is frozen then; the 09:25/09:30
  completion only MASKS (§0.5), never adds or moves levels.
- **ATR for building and ranking (`atr_build`):** the 14-period ATR of 2-minute RTH bars of the previous completed
  session, read at that session's 16:00 close (one number per symbol per plan; no intraday value of the plan date is
  used). All widths in §0.3–§0.4 and in D1–D3 use `atr_build`.
- **ATR for live touch tests (`atr_live`):** unchanged from today — the read's contemporaneous 2m ATR on closed bars
  (`r.atr`), used with the existing `pm_tol_atr` tolerance. The two roles are different and both are recorded on the
  plan (`keyLevels.atrBuild`, and the read's `regime.atr` as now).

### 0.2 Level object (research fields; persisted on the plan)

```
levelId        stable: "<symbol>:<definition>:<originDate>:<originKind>:<price4dp>"
definition     D1 | D2 | D3
originKind     high | low | pivot_high | pivot_low
originDate     the session that created it (D1: newest member; D2: newest episode; D3: the pivot's own session)
availableAt    ms — the first instant the level could be known causally (D1/D2: that session's 16:00 close;
               D3: the close of the second confirming bar after the pivot)
price          the representative price (definition-specific)
role           support | resistance — decided at build time from the previous close: price below close → support,
               above → resistance (a level AT the close within 0.25 x atr_build is dropped)
score          initial score (definition-specific); FIXED between nightly rebuilds (research convention)
reactions      D1: cluster member count; D2: episode count; D3: 1 + retest count
lastReactionAt ms of the newest member / episode / retest
flips          confirmed flips so far (0, 1; retired at 2)
breakAt / flipPending / flipConfirmedAt   the flip state machine (§0.4)
maskedBy       none | pdh | pdl | pmh | pml | <levelId>   (§0.5)
```

### 0.3 Selection, cap and clustering

- **Cap:** after ranking, at most `K = 3` levels above the previous close and 3 below.
- **Ranking:** score, then recency (newer `lastReactionAt` wins), then proximity to the previous close (nearer wins),
  then price (above: higher wins; below: lower wins). Deterministic.
- **Clustering (all definitions, one procedure):** sort candidates by price; walk upward; a candidate joins the current
  cluster if it is within `0.5 x atr_build` of the cluster's CURRENT representative price (the median of members so
  far), else it starts a new cluster. This single-linkage-to-the-median rule cannot chain across several ATRs: the
  test is against the median, not the last member. Members are the candidates' own prices; episode/retest IDs are
  carried with them and de-duplicated on merge (a reaction that appears at two neighbouring candidates counts once).
- **Refill:** the cap is applied AFTER clustering and after the 17:00 dedupe against the PDH/PDL zones (§0.5), so
  the 3 per side are the best 3 survivors; a level masked at 09:25 by the PM range is NOT refilled (the day trades
  with fewer key levels — refilling at 09:25 would let the pre-market pick the levels).

### 0.4 Flip and expiry state machine (research convention, not an author rule)

- **Break:** a 15m body close through the level against its role (support: close below; resistance: close above) at
  time `breakAt` → `flipPending = true`. While pending the level is NOT an entry level and NOT a target candidate
  (its role is unknown); a pullback into it is ignored (journaled `key_level_pending`).
- **Confirm:** the NEXT 15m bar closes on the far side too → `flipConfirmedAt` = that bar's close; `role` swaps;
  `flips += 1`; the level becomes an entry level again in its new role from that instant. Never backdated in replay:
  the read learns the flip at the second close, live and in replay alike.
- **Reject:** the next 15m bar closes back on the original side → `flipPending = false`, nothing else changes (the
  break failed; the level held).
- **Retire:** on the second confirmed flip (`flips == 2`) the level leaves the set at that instant. No score decay, no
  halving, no 0.25 threshold (v1's contradictions removed).
- **Expiry (nightly, at rebuild):** a level older than `L` sessions (by `originDate`) is dropped; a level that two
  consecutive completed sessions closed beyond by more than `1.0 x atr_build` without any reaction (no wick into its
  tolerance band on either session) is dropped — knowable only at the second session's close, so it applies from the
  next plan, never intraday.
- **Interaction with entry confirmation:** a scenario confirmation is ONE 15m body close (C1, unchanged); a flip
  needs TWO. On a key-level break beyond the PDH/PDL zone, the scenario may therefore confirm at the first close
  (§0.6) while the broken level itself is `flipPending`; the entry that follows is the EMA13 pullback (T1) — a
  retest entry ON that level (T2) is available only once the flip is confirmed.

### 0.5 Dedupe against the existing references (two explicit transitions)

- **17:00, against PDH/PDL zones:** a candidate within `0.5 x atr_build` of the PDH zone (top or bottom) or the PDL
  zone is masked (`maskedBy = pdh|pdl`), never moved; the zone keeps its L1.2 semantics unchanged. The masked
  candidate stays in `keyLevels.candidates` with its reason.
- **09:25 (provisional) and 09:30 (completed), against PMH/PML:** a surviving level within `0.5 x atr_build` of the
  PMH or PML is masked (`maskedBy = pmh|pml`); the PM level keeps its L2 semantics. The 09:25 mask uses the
  provisional PM range; the 09:30 finalize re-applies it on the completed range (a level masked at 09:25 and freed at
  09:30 is free from 09:30; the plan records both states). No score comparison across systems ever happens: the
  existing references always win.
- Between key levels of different definitions there is no competition (one definition per sweep variant).

### 0.6 How a key level acts (the C2 package — see §5 for what it changes)

- **Bias:** the scenario is read on the PDH/PDL zones first, exactly as today. A key level adds a confirmation only in
  two situations: (a) price is beyond the zone on the day's side (gap or trend day) and a 15m body closes through a
  key level in that direction → `scenario_1` (above) / `scenario_4` (below) is confirmed on that close if it was not
  already; (b) inside the PDH–PDL range no key level exists by construction on a normal day (§0.5 masks them near the
  zones; between the zones the previous session's range rarely holds an older extreme — when it does, it acts only as
  a target, never as a confirmation, because B3's range-day rules govern there). When the zone read and a key-level
  close disagree (a zone flip against the key level's direction), the ZONE wins and the key level's confirmation is
  discarded (`key_level_overruled`).
- **Entry anchor (deterministic, preserved during a pullback):** for a confirmed setup the anchor is the LAST
  CONFIRMED BROKEN level in the trade's direction — the zone edge if the scenario came from the zone, the key level
  if from a key-level close. The anchor is fixed when the setup is minted and does not change while a pullback is in
  progress; a nearer key level that becomes available or flips later does not replace it (no silent switch). The T2
  retest entry tests the anchor; the T1 EMA13 entry is unchanged. Roles: "anchor" (behind the entry, the level whose
  break confirmed), "obstacle" (the nearest resistance/support AHEAD, used only for targets).
- **Targets:** key levels ahead of the entry join the L3 ladder as candidates and the existing rule picks the nearest
  structural level ahead (F81/F81b unchanged in behaviour; the ladder simply has more rungs). This CAN change the exit
  of a trade whose entry is unchanged — reported separately (§5).

## 1. The three definitions

### D1 — historical session levels (the simplest source-consistent reading)

- **Candidates:** each of the last `L` sessions' RTH high and RTH low (up to 20). Nothing else: no previous close, no
  volume (both removed in v2; they were unstated hypotheses).
- **Cluster representative:** the MEDIAN of member prices. `reactions` = member count.
- **Score:** `members x 0.85^(sessions_ago_of_newest_member - 1)`. A single-member cluster older than 3 sessions is
  dropped (a lone old extreme is not a key level).
- `originDate` = newest member's session; `availableAt` = that session's 16:00 close.

### D2 — repeated-reaction levels ("7 candles wick'd off this level")

- **Candle predicates (15m RTH bar `b`, band `[p - tol, p + tol]`, `tol = 0.25 x atr_build`):**
  - *support reaction at p*: `b.low <= p + tol` (the wick entered the band from above) AND `b.close > p + tol`
    (the body closed back ABOVE the band). In words: price came down into the level and closed back above it. The
    bar's colour and open are irrelevant.
  - *resistance reaction at p*: `b.high >= p - tol` AND `b.close < p - tol` — price came up into the level and
    closed back below it.
  - *body cross* (`b.close` on the far side) is not a reaction; it is a break candidate for §0.4 and ends any episode.
- **Episodes:** consecutive reacting bars (no intervening non-reacting bar) at the same grid price are ONE episode.
  A new episode at that price requires at least 4 consecutive CLOSED 15m bars whose entire range lies outside the
  band (`low > p + tol` or `high < p - tol`) since the previous reacting bar, or a session boundary (an overnight
  gap counts as away). Episode ID = `(sessionDate, index of first reacting bar)`.
- **Grid:** origin = the lowest RTH low of the `L` sessions, rounded DOWN to a multiple of `0.25 x atr_build`; step
  `0.25 x atr_build`; upper bound = the highest RTH high rounded up. Every grid price is tested; a reaction bar can
  satisfy several neighbouring grid prices — its episode ID is the same at each, so after clustering (§0.3) each
  episode is counted ONCE per cluster.
- **Level:** a cluster with `>= 3` distinct episodes from `>= 2` distinct sessions; representative price = the median
  of the episodes' extremes (wick lows for support episodes, wick highs for resistance episodes); `reactions` =
  distinct episode count; `role` per §0.2 from the previous close (a level with reactions of both kinds is allowed).
- **Score:** `episodes x 0.85^(sessions_ago_of_newest_episode - 1)`; `originDate` = the newest episode's session.

### D3 — confirmed pivots with retests (the engine's ladder, promoted)

- **Candidates:** `find_pivots(window=2)` over the `L` sessions' RTH 15m bars. `availableAt` = the close of the second
  confirming bar after the pivot bar (causal; identical to what `level_ladder` already knows at that time).
- **Retests:** 15m bars AFTER `availableAt` that satisfy the D2 reaction predicate at the pivot price in the pivot's
  natural role (a pivot high is resistance until flipped). Consecutive reacting bars are one retest episode (D2's
  episode rule). Episode IDs as in D2.
- **Score:** `(1 + retests) x 0.85^(sessions_ago_of_pivot - 1)` — recency is the PIVOT's age (`originDate` = its
  session); `lastReactionAt` is the newest retest and is used only for tie-breaking. A pivot with zero retests older
  than 3 sessions is dropped. The previous session's own high/low pivots are excluded (they are the PDH/PDL zones).
- **Clustering:** §0.3; the merged level's price = median of member pivot prices, `originDate` = the OLDEST member
  (a cluster of pivots is as old as its first pivot), retests = distinct episode IDs across members.

## 2. Frozen parameters (a change = a new register entry, never an edit)

| parameter | value | applies to |
|---|---|---|
| L lookback sessions | 10 | all |
| K levels per side | 3 | all |
| atr_build | ATR(14) of 2m RTH bars, previous completed session, at its close | all |
| touch tolerance (build) | 0.25 x atr_build | all |
| touch tolerance (live) | `pm_tol_atr` x atr_live (existing) | all |
| cluster width | 0.5 x atr_build to the running median | all |
| mask width vs PDH/PDL/PM | 0.5 x atr_build | all |
| recency decay | 0.85 per session | all |
| lone-old-member drop | single member/pivot older than 3 sessions | D1, D3 |
| D2 grid | origin = floor(lowest low, 0.25 atr_build), step 0.25 atr_build | D2 |
| D2 episode separation | 4 consecutive closed bars fully outside the band, or a session boundary | D2, D3 |
| D2 minimum | 3 episodes from 2 sessions | D2 |
| D3 pivot window | 2 bars each side (existing) | D3 |
| flip | break = 1 body close through; confirm = next bar closes through too; reject = next bar closes back | all |
| retire | second confirmed flip | all |
| expiry | originDate older than L sessions; or two consecutive completed sessions closing > 1.0 atr_build beyond without a reaction | all |

## 3. Measurement protocol (runs only on the canonical inputs after C6)

- **Baseline:** the live rules exactly as deployed (v0.7.55 defaults; `no_trade_zone=pm_range`, `pm_room_atr=0`,
  `min_target_atr=0`, F81b on). C2 is the only change per variant (`techniques.team2.key_levels = off|D1|D2|D3`,
  default off; the read reads `plan.keyLevels`).
- **Inputs:** one canonical dataset (post-C6, hash recorded) for the baseline and every variant; same sigma, sizing,
  execution assumptions (model marks; the synthetic strike grid for history, stated), same fees.
- **Development:** 2026-08-20 → 2026-09-11 inclusive (every date already inspected, including week 37). The last
  scored trading date before week 37 is 2026-09-04 (09-05 is a Saturday, 09-07 Labor Day).
- **Validation (fixed now, before any result):** prospective, **2026-09-14 → 2026-10-09** (20 trading dates, 60
  symbol-sessions), read ONCE per definition after 2026-10-09's close. Earlier bars supply warm-up/lookback to
  validation sessions; they are not validation observations. The window is not extended, shortened or re-read.
  If C6 lands after 09-14, validation still starts 09-14 (the canonical tape is rebuilt for those dates; no decision
  is read before the tape exists).
- **Reported per variant (development and, once, validation):** matched trade lists against the baseline split into
  (a) new entries, (b) displaced entries (same setup/time, different anchor or level), (c) unchanged entries with a
  changed target/exit, (d) lost entries — by date and by symbol; the model's summed premium %; the chronological
  book-level result (size multipliers, one open position desk-wide, two losses end the day, $600 per full unit as
  the labelled scale); max drawdown; exposure (trades, minutes in market, share of small-size entries); the level
  funnel: levels built / masked at 17:00 / masked at 09:25 / 09:30 / pending flips / confirmations added /
  key-level retest entries / entries blocked by the PM rule (C1 off) / overruled by the zone.
- **C1 stays off during C2.** Some C2 opportunities will be refused by the existing PM rule; the funnel records them.
  A definition that never reaches an executable decision is reported as "insufficient exposure under the baseline",
  not as "the levels have no value"; C1 is never enabled to rescue C2 and C2 is never activated on that argument.

## 4. Acceptance criteria (predeclared; every definition qualifies against the baseline on its own)

A definition QUALIFIES on a period only if all of the following hold on that period:

1. Book-level result >= baseline + $300 (one half-unit trade's typical win at the labelled scale) AND the model's
   summed premium % >= baseline (both signs agree).
2. Max drawdown <= 1.25 x baseline's max drawdown on the same period AND worst day >= baseline's worst day x 1.25.
3. At least 6 new or displaced entries on the period (otherwise: insufficient exposure, not a verdict).
4. Positive on at least half of the symbol-sessions where it changed anything (not carried by one date).

Verdict rule: a definition is a CANDIDATE if it qualifies on development; it is ACCEPTED only if it also qualifies on
the validation window read once. Among accepted definitions prefer the simplest (D1 < D2 < D3) unless a more complex
one beats the simpler accepted one by >= $600 at book level on validation. If none is accepted the result is "no
definition improves the baseline convincingly" and C2 ends; the register stays as it is and the search is not
expanded. Activation of an accepted definition is a separate, user-approved Practice experiment (as for C1).

## 5. What C2 changes (stated honestly)

C2 is a package: (i) new confirmations on key-level closes beyond the zones, (ii) key-level retest entries, (iii) more
rungs on the target ladder. (iii) can change the exit of a trade that C2 did not create. The matched-trade report
therefore separates new, displaced, changed-exit and lost trades, and the write-up states how much of the result comes
from exits alone. The entry anchor rule (§0.6) prevents a nearer, unconfirmed level from taking over a setup.

## 6. Build plan (only after this v2 is accepted; sweeps still gated on C6)

- `techniques/team2/levels.py`: `key_levels(bars15m, *, definition, atr_build, prev_close, L, K) -> list[KeyLevel]`
  (pure) with the state machine as a small pure `advance_flip(level, bar15m)`; causal regression fixtures on
  synthetic 15m tapes: a D1 cluster with the median, a D2 episode that lingers (counts once) and one that returns
  after four clean bars (counts twice), a reaction counted at two grid prices (once after clustering), a D3 pivot
  not yet available, a break → reject, a break → confirm → role swap, a second flip → retire, the two-session
  expiry, 17:00 zone masking and 09:25/09:30 PM masking with the candidate record kept.
- `plan.py::build_skeleton`: `plan["keyLevels"] = {definition, atrBuild, candidates: [...], above: [...], below: [...]}`;
  `complete_plan` applies the PM masks and records them.
- `session.py`: key-level confirmation (§0.6 a), pending-flip handling, the anchor rule, target rungs; events
  `key_level_break`, `key_level_flip`, `key_level_pending`, `key_level_retest`, `key_level_overruled`, each with
  `levelId`, `definition`, `score`, `role`.
- Sweep: `--set key_levels=D1|D2|D3`; the C1 study's `book_sim` reused unchanged; the funnel counters added to the
  sweep row.

## 7. Variant register (fixed; no entry until the canonical tape exists)

| # | date | definition | overrides | dataset | period | qualifies? | note |
|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | the sweeps wait for C6; validation window fixed at 2026-09-14 → 2026-10-09 |
