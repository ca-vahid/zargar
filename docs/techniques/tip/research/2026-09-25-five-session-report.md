# Tips five-session prospective report - delivered 2026-09-25 (state INVALID)

Procedure: `FIVE-SESSION-CHECKPOINT.md`. Source files: `C:\ProgramData\Zargar\tips-five-session\` (generated
2026-09-25 16:47 ET by `tips-five-session.ps1`), plus the weekly appendix `2026-09-25-five-session-appendix.md`.

## Status: INVALID - four observe sessions, not five

`STATUS.json` = **INVALID** (`gateMode: enforce`). The fifth session, 2026-09-25, ran with the relevance gate on
**enforce** by the user's decision that morning (sharp-pencil plan P5), so it is not an observe session. The four
completed accounting days 09-21..09-24 are clean: 427 decisions, all observe, no gap, no mixed-mode day, every report
produced, `eligible: true` on those four days.

**What this report can and cannot claim.** The preregistered bar was five observe sessions. We have four. Everything
below about the gate is **four-session evidence**, and it is labelled that way. No further observe sessions can accrue
while the gate stays on enforce, and changing that is the user's decision, not this desk's. 09-25 is shown separately
as the first enforce session. It is not a prospective observe result.

## 1. Missed actions

- **Management false negatives:** **0**. That is 0 of 75 observe skip-decisions whose complete review managed
  something (427 of 427 decisions joined to a complete review; 0 running, failed, unmatched or unevaluable).
- **Unresolved decisions:** **0**.
- **Human-review candidates:** **75**, all exported in full in `review-gate-prospective.md`, "Human-review candidates".
  - By source: muggzone-options 45, common-stock 8, ab 7, eva 6, neal 3, MK-alpha-trades 2, giul-heatseeker 2,
    jon-and-kian 1, tt 1.
  - Almost all are position commentary on legs the desk does not hold, or ticker-less chatter (muggzone's fragmented
    mornings, SPX lines the desk cannot price).
  - Two carry a **missed-tip flag** and need a human read first:
    1. **09-22 15:26 muggzone QCOM** (run `fba7e31b`). The review points back to the 11:18 **AAPL 9/23 345C**: the
       author's limit filled at 1.29 and the live ask (1.13/1.14) was inside the fill band. That signal was demoted to
       `shadow`, so no proposal was made. This is a possible missed entry, decided by verification, not by the gate.
    2. **09-23 15:41 jon-and-kian HOOD** (run `fe059ff6`). The review flags the 11:18 **HOOD 10/16 140C** proposal:
       analyst TAKE, never confirmed, and it later **expired**. The dispositions report classes it as risk-infeasible,
       not avoidable. A human should confirm that classing.
  - No management proposal was recorded on any candidate (`proposedManagement=None` on all 75).

## 2. Opportunity delays

- **Dispositions** (`opportunity-dispositions.md`, ideas since 09-21):
  - 83 actionable ideas, 25 analyst takes, **13 filled**.
  - The rest: 57 declined, 11 risk-infeasible (muggzone 7), 1 order unfilled (a level that never came), 1 pending.
  - The scorecard's own join counts 98 ideas, 28 takes and 16 fills over the same period. The two reports join
    differently, and neither found an avoidable miss.
- **Avoidable misses (the desk's own processing):** **0**.
- **Intake coverage:** 525 messages were received and classified:
  - 222 produced signals;
  - 302 were extracted with no signal;
  - **1 failed** (MK-alpha-trades 09-21 12:32, content `85eb3bb1`, replayable). It is an unclassified message, not a
    missed winner.
- **Cold-park rechecks (`SignalColdParkRecheck`):** 6.
  - ARM 09-21 waited 7 s and stayed parked.
  - NEM 09-22, AMAT 09-23, BNTX and U 09-24 and SYM 09-25 each resolved with no wait and went on to a proposal.
  - None of these waits delayed an entry.

## 3. Operating costs (list-price estimates, separate from trading P&L)

**Four observe sessions, 09-21..09-24** (scorecard, accounting days):
- **Priced $306.10**, by day: $122.50 / $101.26 / $60.39 / $21.95.
- By stage: intake review $229.07, appraise $57.90, extraction $11.19, retro $7.04, digest $0.84, transcription $0.06.
- **Unpriced:** 0 runs.
- **Partial:** the extraction and transcription figures come from nightly roll-ups (2 extraction and 1 transcription
  roll-ups). They lose in-memory counts across restarts, so they are a **lower bound**.

**Review spend the filter WOULD have removed:** **$43.33** across 75 observe skip-decisions. This is a would-have,
not a saving: those reviews ran. Another 10 skips were applied for real under the approved non-actionable rule ($0).

**09-25 (enforce, first day, calendar basis):** priced $6.79, with 29 unpriced intake runs. Those 29 are gate skips
that made no model call. Partial: 0. Tonight's retro, digest and audit are not included.

## 4. Performance after costs, Tips Practice book (net of `executions.commission`)

| | marked change | realized net (fees inside) | model cost | **marked after cost (primary)** | realized after cost |
|---|---:|---:|---:|---:|---:|
| 09-21 | +2.15 | +2.79 | 122.50 | **-120.35** | -119.71 |
| 09-22 | +213.43 | +248.45 | 101.26 | **+112.17** | +147.19 |
| 09-23 | -47.15 | +46.57 | 60.39 | **-107.53** | -13.82 |
| 09-24 | +15.65 | -78.51 | 21.95 | **-6.30** | -100.46 |
| **4 sessions** | **+184.08** | **+219.30** (fees 16.64) | **306.10** | **-122.02** | **-86.80** |

- **Baseline:** 8,964.46 at the 09-21 03:59 mark. Final mark: 9,148.55 at 09-25 03:59. Open lots at the last mark were
  -456.52 against cost.
- **09-25 (enforce, not yet marked).** Its accounting day closes at 09-26 04:00 ET.
  - Realized **-98.15** net (fees 0; JELD carry -88.93).
  - Excluding the questioned XLU 4-share double trim, which 0.8.52 fixed: -98.76.
  - Model cost $6.79.
  - The appendix's provisional mark at 16:48 ET: marked **-112.69**, **-118.14** after model cost, and
    -240.16 cumulative over five days. The day's final mark comes after 04:00 ET.
- **Questioned fills:** none inside 09-21..09-24. MRNA 09-17 and APLD 09-14 are graded apart and sit outside this
  window.
- **Where the money came from:** one source. common-stock realized +295.80 on 2 completed ideas (+274.16 after model
  cost). Every other source is negative after model cost:
  - muggzone -140.43, of which $128.35 is model cost;
  - ab -88.75;
  - jon-and-kian -49.35;
  - tt -28.48;
  - eva -25.38;
  - neal -11.85.
  - No cohort has enough completed ideas to claim an edge.
- **Shadow books (never summed with Practice):**
  - The armed books of ab, common-stock and eva, and both muggzone books, are **quarantined**. They are excluded from
    judgement; this matches the phantom-short share rows found on 09-25.
  - **eva's immediate book shows +156,134.03 realized and is NOT quarantined.** That figure is not credible and should
    be audited before any source comparison uses it.
  - tt immediate (+1,979.52) is quarantined.

## 5. Evaluation-case readiness for P2 (cheaper intake-review model)

Captured cases against the quota: management **20 of 20** (32 captured), missed-entry flag **10 of 10** (12),
**correction 3 of 8**, mixed multi-ticker **6 of 6** (7), note-only **16 of 16** (363). That is **55 of 60** usable
against the quota. **Corrections are 5 short**: at about 0.6 a day they set the calendar, roughly 8 more sessions.
Replayable today: 454 captured reviews. The **$35** is an estimate-based spending guard, not a guaranteed maximum
(Sonnet 5 $22.03 + Haiku 4.5 $11.02, one pass each). **No paid run without the user's approval.**

## Boundaries (unchanged by this report)

- No settings, policy or model changes were made for this report.
- The gate's enforce state came from the user's 09-25 decision; this report does not move it either way.
- P3 approval expiry is unchanged, P4 is research only, P5 is pending, and P6 exit/overnight policies are unchanged.
- Decisions this report hands to the user:
  - P1: whether enforce stays, or observe returns so a fifth observe session can be collected;
  - the 5 missing correction cases before any P2 paid run;
  - the eva immediate-book audit;
  - the two flagged candidates above.
