# Failure taxonomy (validated vocabularies — use these exact strings)

Source of truth: `backend/zargar/technique/review.py` (`REVIEW_VERDICTS`, `ROOT_CAUSE_STAGES`);
`python -m zargar.tools.technique_review taxonomy` prints them.

## review_verdict — was the run right?

| value | meaning | typical evidence |
|---|---|---|
| `correct` | verdict and plan were right for the chart and what followed | setup → outcome tp/positive R (or stopped on a genuinely valid plan); no_setup → candidate not_filled / stopped, or nothing tradeable on the chart |
| `wrong_verdict` | said setup when none / no_setup when a valid one existed | no_setup + candidate outcome tp2/tp3; setup + immediate stop with fakeout tells visible in FACTS |
| `wrong_levels` | right idea, wrong levels | model's levels differ from the chart's obvious ones; detectors merged/missed a level |
| `wrong_plan` | setup real, plan mis-placed | entry chased (T4.1), stop far/too tight (T4.3a), targets unreachable (R2), wrong basis (bounce vs break) |
| `late` | right call after the move | entry already 1%+ above the level; outcome not_filled while price ran |
| `data_issue` | bars / volume / time-of-day data wrong or missing | missing timeframe, forming-bar volume 0, as_of outside session, Yahoo gap |
| `unclear` | can't say yet | outcome pending/partial or ambiguous chart |

## root_cause_stage — where did the first wrong turn happen?

| value | owner (file) | ask |
|---|---|---|
| `data` | `history.py`, `analysis.gather_bars` | were the right bars there? right as_of? all timeframes? |
| `detectors` | `levels.py`, `volume.py`, `structure.py`, `candles.py`, `setups.py`, `analysis.compute_facts` | do `keyLevels` / `volume` / `trend` / `candidateSetups` match the chart? |
| `facts_prompt` | `analysis.facts_for_prompt` | did FACTS omit or obscure what mattered (level outside list, bars window)? |
| `pass_context` | `vision.py` PASS 1, `schemas.PassNotes` | higher-tf read wrong? |
| `pass_pattern` | `vision.py` PASS 2 | pattern / break test wrong? |
| `pass_entry` | `vision.py` PASS 3, `schemas.TechniqueAnalysis`, `schemas.SYSTEM_PROMPT` | verdict/plan wrong given correct FACTS? |
| `critic` | `vision.py` PASS 4, `schemas.CriticVerdict` | kill/keep unjustified? confidence nudge wrong? |
| `grounding` | `grounding.py` | accepted an ungrounded number, or rejected a grounded one / forced a bad retry? |
| `options` | `options.py` | contract pick wrong (strike/expiry/IV/spread)? |
| `thresholds` | `rulebook.Thresholds` via `technique.*` settings | a number (tolerance, touches, R:R floor, volume mults) produced the miss — fix is a setting, prove with `replay --set` |
| `rulebook` | `rulebook.RULES`, `docs/techniques/enhanced-market/METHOD.md` | the codified rule disagrees with the book |
| `other` | — | say what in notes |

## Choosing

1. Walk the trace top-down; the **first** stage whose output is wrong is the root cause.
   A bad entry caused by a missing level is `detectors`, not `pass_entry`.
2. If FACTS were right and the model still chose wrong → a `pass_*` stage (prompt/schema).
3. If the model was right and grounding flipped it → `grounding`.
4. If changing one setting would have fixed it (prove with `replay-facts --set` or
   `replay --set`) → `thresholds`.
5. If the run followed the rulebook faithfully and the book would still disagree → `rulebook`.

## Actions — be specific

Each `--action` is one change with a location, e.g.
- `levels.detect_levels: treat prior-day LOD as a level even with 1 touch (T1.3a)`
- `SYSTEM_PROMPT: bounce entries never require confirmation (T4.2) — currently says "confirm"`
- `grounding: reject stop > 1.5× ATR below entry for bounce setups`
- `settings technique.level_tolerance_pct 0.15 → 0.25 (replay <id> --set level_tolerance_pct=0.0025 flips to setup)`
- `tests/test_technique_setups.py: pin candidate validity for <scenario>`
