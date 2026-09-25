# Team2 review and plan update — 2026-09-23

Session 3 of the selection study (counted, cohort B-synced-clock). All Team2 books are simulated.
This updates `2026-09-22-improvement-plan.md` (on PR #255); nothing in that plan's decisions changes.

## 1. Result

| book | today | since start | notes |
|---|---|---|---|
| Team2 Sizing 0.5 | **+$381.46** | −$367 (−3.7%) | IWM 284P 0.62→1.00 target; SPY 767P 0.52→0.41 structural stop; IWM 283P 0.36→0.42 target |
| Team2 Control | **−$243.20** | −$1,581 (−15.8%) | one trade, a stale fill (F130 below) |
| Team2 C1 Conjunction | $0 | −$1,322 (−13.2%) | still paused on its 2026-09-22 threshold, as designed |
| Team2 total | **+$138.26** | | $195.52 of fees |
| EM Practice / EM Experimental | −$120 / −$106 | −2.4% / −3.8% vs its own start | the EM desk's live A/B; kept |

First green Team2 day of the cohort. One day is not evidence of an edge, in either direction.

## 2. How Casey did — from his own posts on X (read in the signed-in browser)

- **Morning:** bearish bias from a bear flag under the previous day's low on SPY/QQQ/IWM; puts "down to the next support
  zone", posted at +127%. **Our read took the same trade**: the IWM pm_break_down puts that made Sizing 0.5's money.
- **Afternoon:** IWM rejection 15:04, head-and-shoulders 15:18, "sell most" at 15:47 on the IWM 282.5 put (0DTE) at
  +172.5%, then a new low of day at 15:57. **We could not take this one by design**: our entries stop at 15:30 and the
  book is flat at 15:45 (D6/C3). It is a discretionary late-day 0DTE trade held past our flatten.
- His recaps are self-selected (he reviews trades he alerted), so this is evidence about his entries, not a P&L.

## 3. What went wrong, and what was fixed

**F130 — stale working entry (fixed on branch `claude/team2-stale-working-entry`, not deployed).** Control's IWM entry
rested unfilled from 10:18, the read closed the setup at its 10:27 target, and the order filled at 11:08 into a
move against it: −$243.20, the whole of Control's day. Cause: Team2 never cancelled a working entry except at the
15:45 flatten. Now the read's full exit of a setup cancels its working entries. Tests reproduce the case.

**Authority records.** Live target, intra-minute quote stop and clock-flatten exits now name their authority on
`TechniquePlanExit` like every F129 exit.

**Feed stall 15:11–15:16 ET (observed, not fixed; platform-wide).** Every armed plan on the platform reported
stale bars for about four minutes; the engine logged 44 event-loop stalls today, the longest 10.3 s. No restart. The
persisted SPY/QQQ/IWM minute bars are complete (recovered), so under the frozen s1-r4 outage rule the session counts
and is **not** reclassified. Team2 held nothing at the time. It is the platform's problem, not a Team2 decision.

## 4. Books

No book removed. EM Practice and EM Experimental are the EM desk's live A/B arms and both traded today. The idle
books (Options Cartel Practice – Capital, the two flow-scan shadows) belong to other desks and are left for them.
Noted for the Tips desk: the shadow book `🌟｜ab (armed)` shows equity **−$92,584** on a $10,000 start, which reads as a
valuation defect, not a result.

## 5. Plan changes

1. **Deploy F130 after review** (user decision). It is Team2-only except an additive journal field in the shared
   quote watch. Its value is concrete: it would have removed today's only loss.
2. **Unchanged:** keep the three books as registered (option A), keep collecting (3 of 60), no new replay arms, stop at
   25%, resolver off, #255 waits on its remaining suites.
3. **Not doing:** extending the entry cutoff or flatten to chase Casey's late-day trade. That changes the method's
   0DTE risk rule on the strength of one memorable trade; if wanted, it is a registered prospective test on a new
   book, like H5.
