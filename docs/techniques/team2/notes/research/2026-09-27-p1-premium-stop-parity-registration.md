# P1.1 — premium-stop parity: registration (committed before any number is computed)

Plan of record: `2026-09-24-sharp-pencil-plan.md` §5 P1.1. Order-free research on stored data. Changes no setting.

## Question
The replay (2026-09-19 harness, v2 real prints) decides the premium stop on the mark at each **2-minute close**. The
live desk decides it on the contract's **mid, about every 2 seconds** (`premium_stop_pct` 25, 3-tick floor). Live,
the premium stop decided 12 of 30 exits and −$4,167 (2026-09-08..09-24). Does applying the stop the way it actually
runs make the method materially worse than the replay says?

This fixes a **measurement**. It is not a new variant search. H6 (stop width) is not reopened.

## Inputs (frozen)
- **Baseline trades:** the existing training-window replay `train_base_s0.json` (282 trades, 2026-05-07..08-14,
  harness v2, `codeCommit fed75988`, slippage 0, touch mode `proxy`). No replay is re-run.
- **Prints:** the cached Alpaca 1m option trade bars for each trade's contract (`prof/data/opt/<OCC>.json`, the same
  files the replay used).

## Overlay rule (frozen)
- **Stop line:** `line = min(0.75 × entryPremium, entryPremium − 0.03)`. That is the live rule, 25% with a 3-tick
  floor, on the entry fill.
- **Walk:** the option minutes strictly after the entry minute, up to and including the minute of the baseline's
  final exit.
- **Two print proxies for the unobservable 2-second mid,** reported together as a bracket:
  - **P-close:** the first minute whose CLOSE ≤ line. Fewer triggers than the live mid.
  - **P-low:** the first minute whose LOW ≤ line. More triggers than the live mid, because a low print is at or below
    the bid.
- **Trigger timing:**
  - If the trigger minute ends before a baseline exit event, the remaining position at that moment exits at the OPEN
    of the next option minute that has a print within 5 minutes. With no such print, the baseline outcome is kept
    and the trade is counted as "censored".
  - Baseline exits before the trigger are kept.
  - If the baseline's own exit comes first, nothing changes.
- **Scope:** trades with X5 adds (19) are excluded from both arms, because their averaged basis is not reconstructable
  per unit. P&L is gross % per unit of the initial position. Fees are identical in both arms (same contracts bought
  and sold), so the difference is pure price.

## Statistics and decision (frozen)
- **Statistic:** the paired difference `variant − baseline` in pnl-% per trade, as a mean, with a **date-clustered
  bootstrap 95% interval** (10,000 resamples of sessions, seed 20260927).
- **Decision:**
  - **Leak:** if P-close is worse than baseline by **≥ 3 points per trade** and its interval excludes 0, the live stop
    is a measured leak. A registered prospective change is then proposed: confirmation on the 2m close, the replay's
    rule. Not activated without the user.
  - **Not the leak:** if P-low is within 3 points, the stop's sampling is not the leak.
  - **Unresolved:** anything between is unresolved, and prospective live counts (`team2_exit_review`) decide.
- **Reporting:** both proxies, the trigger counts, the censored count and the per-session spread, whatever the answer.
