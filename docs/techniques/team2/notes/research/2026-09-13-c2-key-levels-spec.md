# C2 — multi-day key levels as entry levels: frozen definitions and measurement protocol

Written 2026-09-13 by the Team2 desk, per the other team's instruction: "a small family, 2–3 definitions, specified
before running the sweeps." **Nothing is measured yet, nothing is built.** The sweeps run only after C6 (one tape)
lands and on the canonical inputs; C1, the room rule and C3 stay exactly as they are (all off) throughout.

Source basis (METHOD §0c, week-37 charts): the author anchors on "3 days of support at our 293.43 zone", a level "7
candles wick'd off today" (287.83), and a two-days-old session high (764.47) reclaimed by a gap. He treats a broken
level that holds on the retest as flipped (L1.4). Our engine today has only the previous session's high/low as entry
zones (L1) and the prior pivots as targets (L3, `levels.level_ladder`, `find_pivots(window=2)`). The question C2
asks: does adding a small set of multi-day levels as ENTRY levels, and nothing else, improve the baseline convincingly.

## 0. Common frame (identical for all three definitions)

- **Inputs:** RTH 15-minute bars of the last `L = 10` completed sessions before the plan date (the same window
  `target_lookback_sessions` uses), validated by F75; the plan date's own bars are never used to build the day's
  level set (levels are frozen at 17:00 like the rest of the plan; the 09:25 completion does not add levels).
- **Level object:** `{price, kind: high|low, source: D1|D2|D3, score, born (session date), touches, flipped: bool}`.
  A level is a LINE with the standard touch tolerance `pm_tol_atr` (0.25 × 2m ATR), not a wick→body zone (the author
  draws these as lines; PDH/PDL keep their L1.2 zones).
- **Cap:** at most `K = 3` levels above and 3 below the previous close after ranking (one plan sheet cannot carry
  more without the read becoming a level soup; the author's plans name 2–3 per side).
- **Exclusion:** a candidate within `0.5 × 2m ATR` of the PDH/PDL zone, the PMH/PML (known only at 09:25 — applied
  at completion), or another already-selected level is merged into the higher-ranked one (dedupe), never listed twice.
- **How a key level acts (the ONLY method change):** a key level is a fifth/sixth "level" in the read with the same
  three plays as any level (L4): (a) a 15-minute body close THROUGH a key level that lies beyond the PDH/PDL zone on
  the day's side confirms the scenario exactly as a PDH/PDL close would (`scenario_1/4` on a key-level break above
  PDH / below PDL); (b) the entry is unchanged — the first/second 2m EMA13 pullback (T1) or the retest of the level
  itself (T2, `entry_at=level`); (c) a key level ahead of the entry is a target candidate ranked with the ladder
  (L3), nearest first. Bias precedence when levels compete: PDH/PDL zones outrank key levels (the scenario is still
  read on the zone first); a key-level break only ADDS a confirmation on a day where the zone is already behind
  price (gap days) or where price is beyond the zone and the next structure is a key level. Entry precedence: the
  nearest level on the trade's side wins; a pullback that touches two levels within tolerance is one touch.
- **Support/resistance flip (all definitions):** a level whose side price is on at the plan date (price above → it is
  support) flips when a 15m body closes through it and the next 15m bar does not re-close back; after the flip the
  level keeps its price and its score and changes kind. Intraday flips are read live; the plan carries the 17:00 side.
- **Expiry / invalidation (all definitions):** a level leaves the set when (i) it ages past `L` sessions, (ii) price
  closes a SESSION beyond it by more than `1.0 × 2m ATR` on two consecutive sessions without a reaction (a level that
  is simply "in the way" is not a level), or (iii) it has been broken and flipped twice (each flip halves the score;
  below `0.25` it is dropped).
- **Tie-breaking (all definitions):** score, then recency (newer wins), then proximity to the previous close (nearer
  wins), then the price itself (deterministic; higher wins above, lower wins below).

## D1 — Historical session levels (the simplest source-consistent reading)

- **Candidates:** each prior session's RTH high and RTH low over the last `L` sessions (up to 20 candidates), plus
  the previous session's close. This is literally "3 days of support": the same reading the author's L1 uses, extended
  backwards.
- **Clustering:** candidates within `0.5 × 2m ATR` (measured on the plan date's previous session) of each other form
  one cluster; the cluster's price is the volume-weighted mean of its members (volume = the 15m bar's volume at the
  extreme), its `touches` = member count.
- **Score:** `touches × recency`, recency = `0.85^(sessions_ago − 1)` of the newest member. Single-member clusters
  older than 3 sessions are dropped (a lone old extreme is not a key level).
- **Recency rule:** newest member decides `born`; a cluster is refreshed whenever a new session extreme joins it.
- **Nothing else.** No intraday pivots, no reaction counting. If this beats the baseline the method gains one simple
  sentence; if it does not, the more elaborate definitions must beat THIS, not the baseline, to justify themselves.

## D2 — Repeated-reaction levels (the author's "7 candles wick'd off this level")

- **Episode:** a 15-minute bar whose wick touches a price band but whose body closes on one side of it is a
  *reaction*; consecutive reacting bars at the same band count as ONE episode (they are one lingering visit); a new
  episode begins only after at least 4 × 15m bars (one hour) away from the band, or after a session boundary.
- **Band search:** a sliding price grid of `0.25 × 2m ATR` over the last `L` sessions' RTH range; for each grid price
  count episodes (bounces from below = support reactions, rejections from above = resistance reactions).
- **Level:** a grid price with `≥ 3` distinct episodes from `≥ 2` distinct sessions. Its price is the median of the
  episodes' extremes; `touches` = episode count.
- **Score:** `episodes × recency` with the same recency decay as D1 applied to the newest episode; a level whose
  episodes are all on one side (only bounces or only rejections) keeps its natural kind; mixed levels take the side
  price is on at the plan date.
- **Clustering:** grid prices within `0.5 × 2m ATR` merge into the one with the most episodes.

## D3 — Confirmed pivots with retests (the ladder the engine already has, promoted)

- **Candidates:** `find_pivots(window=2)` over the last `L` sessions' RTH 15m bars — a pivot exists only after the
  two bars on each side have CLOSED (the confirming bars; the same causality `level_ladder` already has, so no
  look-ahead is introduced).
- **Retests:** for each pivot, count later 15m bars whose wick enters the tolerance band and whose body closes back
  on the pivot's side (the same episode rule as D2 applies: consecutive bars are one retest).
- **Score:** `(1 + retests) × recency`; pivots with zero retests older than 3 sessions are dropped; the PDH/PDL of
  the previous session are excluded (they are zones already).
- **Clustering:** pivots within `0.5 × 2m ATR` merge; the merged level keeps the earliest `born` and the sum of
  retests.
- This is the most engine-native definition (it reuses `level_ladder`'s pivots) and the least like the author's
  words; it is included so "the ladder as entry levels" is measured rather than assumed.

## 1. Frozen parameters (no re-tuning during the study)

| parameter | value | shared by |
|---|---|---|
| L lookback sessions | 10 | all |
| K levels per side | 3 | all |
| touch tolerance | 0.25 × 2m ATR (`pm_tol_atr`) | all |
| cluster width | 0.5 × 2m ATR | all |
| recency decay | 0.85 per session | all |
| drop threshold (score) | 0.25 after flips; single old member > 3 sessions (D1/D3) | all |
| D2 episode gap | 4 × 15m bars or a session boundary | D2 |
| D2 minimum | 3 episodes from 2 sessions | D2 |
| D3 pivot window | 2 bars each side (existing) | D3 |
| flip confirmation | 15m body close through, next bar not re-closing | all |
| expiry | L sessions; 2 consecutive sessions ≥ 1.0 ATR beyond without reaction | all |

If any of these needs to change after the first sweep, the change is a NEW variant in the register (§4), not an
edit of the old one.

## 2. Measurement protocol (runs after C6, on the canonical tape)

- **Baseline:** the live rules exactly as deployed (v0.7.55 defaults; `no_trade_zone=pm_range`, `pm_room_atr=0`,
  `min_target_atr=0`, F81b as it stands). C2 is the ONLY change per variant (`techniques.team2.key_levels =
  off|D1|D2|D3`, default off, the read reads `plan.keyLevels`).
- **Inputs:** the canonical dataset after C6 (one venue precedence, hash recorded), identical for baseline and every
  variant; same sigma source, same sizing (`size_full/small/none`), same execution assumptions (model marks, grid
  ladder for history stated as a limitation), same fees.
- **Periods:** development = 2026-08-20 → 2026-09-05 (12 dates); **validation = 2026-09-08 onward, untouched until
  the definitions are frozen and the development sweep is written up.** Week 37's author charts are development
  examples; the validation verdict is read only once per definition.
- **Reported per variant:** matched trade lists (shared / added / lost, by date and symbol); the model's summed
  premium % AND the chronological book-level result (size multipliers, one open position desk-wide, two losses end
  the day, $600 per full unit as the labelled scale); max drawdown; exposure (trades, minutes in market, share of
  small-size entries); results by date and by symbol; the number of key levels per plan and how often a key-level
  confirmation or entry actually fired (a definition that changes nothing is reported as such).
- **Decision rule (theirs, adopted):** do not pick the highest return. Prefer the simplest source-consistent definition
  (D1 before D2 before D3) whose benefit survives validation with the drawdown not worse than the baseline's by more
  than the added exposure justifies; "none improves the baseline convincingly" is an acceptable result and ends C2.
- **Search discipline:** the three definitions above are the whole search. No fourth definition and no parameter
  change until one of them wins on development AND survives validation; every run is logged in the register with its
  dataset hash and the exact overrides.

## 3. Build plan (only after this document is accepted)

- `techniques/team2/levels.py`: `key_levels(bars15m, *, definition, atr, prev_close, L, K, …) -> list[Level]` for
  D1/D2/D3, pure, with unit tests on synthetic 15m tapes (a level that should cluster, an episode that should count
  once, a pivot that is not confirmed yet, a flip, an expiry).
- `plan.py::build_skeleton`: `plan["keyLevels"] = {"definition", "above": [...], "below": [...]}`; the level sheet
  lists them with their scores; `complete_plan` applies the PMH/PML dedupe.
- `session.py`: the key-level break as an additional scenario confirmation and the key-level retest as a `level`
  entry, gated by `rules.key_levels != "off"`; events `key_level_break`, `key_level_retest`, `key_level_flip` with
  the level's source and score in the payload so the trail says which definition acted.
- Sweep: `--set key_levels=D1|D2|D3`; the research script from the C1 study (`book_sim`) reused unchanged.

## 4. Variant register

| # | date | definition | overrides | dataset | dev result | validation | note |
|---|---|---|---|---|---|---|---|
| (none yet — the sweeps wait for C6) | | | | | | | |
