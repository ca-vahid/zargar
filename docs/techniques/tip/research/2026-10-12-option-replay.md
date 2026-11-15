# Tips option replay, 2026-10-12: are the analyst's takes better than its skips?

Follow-up to `2026-10-12-source-replay.md`, which scored tips on the underlying's move and found the analyst's
takes right less often than its skips. That replay could not see option prices. This one prices each option tip
on the contract's own trades.

Tool: `python -m zargar.tools.tip_option_replay` (read-only, no model). Run of 2026-10-12, archive since 2026-08-28.

## Method

- 481 opening signals, 434 distinct tips (one per source, name, side and day). 388 are option tips.
- 228 were priced. A tip needs a strike, a side and an expiry; 6 expiries were identified by matching the stated
  premium. Unpriced: 132 with no expiry and no premium, 50 with no contract, 16 with no print within 30 minutes,
  8 where no expiry matched the premium.
- Entry: the first 1-minute bar that starts after the alert (median 35 seconds later), at that minute's
  volume-weighted price. The median price paid was 2.7% above the premium the source stated.
- Three fixed exit rules, the same for every tip, so the take / skip split measures selection and not exits:
  - **scalp**: stop -30%, target +30%, flat at the day's close
  - **bracket**: stop -50%, target +100%, else sold at the horizon's close
  - **hold**: no stop, sold at the close of the tip's horizon (stated sessions, else 3), never past expiry
- Results are % of the premium paid, after $0.08 a share for both legs (slippage and fees).
- Intervals resample whole days (tips of one day move together).

## Result

| Group | Priced | Scalp | Bracket | Hold |
|---|---|---|---|---|
| All option tips | 228 | 44% winners, -6.3% | 30%, -13.9% | 26%, -21.2% |
| Analyst said take | 95 | 41%, -7.0% | 30%, -16.6% | 25%, -39.3% |
| Analyst said skip | 104 | 44%, -7.6% | 31%, -13.3% | 29%, -7.6% |

All three rules are negative for the whole pool with a 90% interval below zero (scalp -9.1% to -3.7%).

Before costs the scalp rule is flat (take -0.4%, skip -0.2%): bought a minute after the alert, these tips are a
coin flip, and costs make the coin flip a loss.

| Source | Priced | Scalp | Bracket | Hold | Verdict |
|---|---|---|---|---|---|
| muggzone-options | 94 | 42%, -6.0% | 27%, -16.8% | 23%, -32.6% | negative |
| ab | 42 | 50%, -6.5% | 24%, -13.8% | 15%, -42.0% | negative |
| eva | 33 of 171 | 48%, -8.4% | 39%, +0.4% | 39%, +52.3% | no edge shown |
| tt | 24 | 57%, +3.1% | 25%, -21.1% | 20%, -50.5% | no edge shown / negative on hold |
| jon-and-kian | 24 | 32%, -10.1% | 46%, -14.8% | 46%, -17.9% | negative on scalp and hold |

## Findings

1. **The analyst's take carries no information on option tips.** Takes beat skips under one of three rules, by
   0.6 points. Under hold they are 32 points worse. The earlier finding (takes worse than skips on the underlying)
   softens to "takes are no better than skips", which is still a failed selection test over 95 takes and 26 days.
2. **The pool has no edge after the alert.** No source and no exit rule shows a positive interval. The problem is
   upstream of the analyst: a better filter cannot find winners in a pool that is a coin flip before costs.
3. **Cheap contracts lose to costs alone.** Under $0.50 premium the scalp rule is -0.2% before costs and -38%
   after (14 tips). This is arithmetic, not a sample finding: $0.08 is 16% of a $0.50 premium.
4. Cuts by days to expiry, time of day and price paid versus the stated premium showed differences, all on 10 to
   100 tips each across many cuts. None is used: with this many cuts some will look good by chance.

## Limits

- Prints are not fills. The cost allowance stands in for the spread; the Team2 study measured the print proxy at
  about $0.03 a leg against that desk's fills.
- 132 skipped tips (mostly eva, who posts no expiry) could not be priced, so the skip row is not all skips.
- A stop and a target inside one minute are read stop-first.
- Alerts the source deleted are not in the archive.
- Six weeks of one market regime.

## What changed because of this

- The analyst now reads the measured record on every live run (`techniques/tip/record.py`, setting
  `techniques.tip.measured_record`): the all-source rates, the tip's own source, its own take-versus-skip record
  and the cost arithmetic, ahead of its rulebook and notes. A take must open its rationale with the specific fact
  that sets this tip apart from the losing record. The record is rebuilt nightly in a separate process.
- The check that this helps is in the same snapshot: `sinceSupply`, the take-versus-skip split for tips from
  2026-10-13 on. Read it when it holds 20 priced tips a side.
- Nothing gates an order. The analyst is not removed: it still reads the tip, names the contract and writes the
  exit plan.
