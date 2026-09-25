# Tips — sharp-pencil review #2 and plan (2026-09-24, after four observed sessions)

Written from the desk's own tools on the full Practice record 2026-09-08 → 09-24 (scorecard v6, dispositions,
knowledge ledger, overnight and gap studies, `tip_llm_cost`) and the shadow books. Samples are small and stated;
nothing here claims an edge. The first review (`2026-09-23-adversarial-review-and-plan.md`) fixed measurement and
model cost; this one asks where the money is actually lost and made.

## 1. The scoreboard

| window | marked | realized | model cost (list) | marked after cost |
|---|---:|---:|---:|---:|
| 09-08 → 09-11 (first week) | -$1,166 | -$950 | $174 | -$1,340 |
| 09-14 → 09-18 | +$131 | +$115 | $315 | -$184 |
| 09-21 → 09-24 (this week) | **+$184** | **+$219** | **$306** | **-$122** |
| **whole record** | **-$851** | **-$791** | **$822** | **-$1,673** |

Model cost has already fallen from ~$100-120 a weekday to **$21.45 on 09-24** (caching, Opus 5.5 at medium, the
non-actionable skip; extraction is now included). At that rate the desk costs ~$105/week to run, so **break-even needs
~$105/week of trading profit**. Trading has improved week on week; it is not yet there.

## 2. Where the money went (whole record)

**By vehicle.** Shares cohorts **+$243** realized (11 completed; common-stock +$275). Option cohorts **-$1,033**
(20 completed): every losing cohort in the table is an option cohort (florida-man 30+DTE -$505, ab 0-4DTE -$206,
muggzone 0-4DTE -$193, eva -$172, common-stock options -$159). The only positive option cohort is ab 30+DTE
(+$227, one +$248 trade).

**By how positions ended.**

| exit | n | net |
|---|---:|---:|
| **source's own exit mirrored by the analyst** | 8 | **+$417** (6 winners) |
| target / premium target | 2 | +$218 |
| underlying stop | 4 | -$124 |
| premium stop or bleed, in session | 3 | -$270 |
| **premium/stop exit in the first seconds of a session** | 6 | **-$830** (all options, all held overnight) |

The overnight study says holding options overnight was NOT the loser (0-7 DTE carry +$427 bid-to-bid, n=7). The
first-seconds exits are: option stops and premium stops evaluated on the **opening quote**, when spreads are widest.

**By source, net of model cost** (realized, open positions at cost not credited):

| source | fills | realized | model $ | **net** |
|---|---:|---:|---:|---:|
| muggzone-options | 8 | -$226 (all options, 0 realized winners) | **$334 (41% of all spend)** | **-$561** |
| florida-man | 1 | -$505 | $2 | -$507 |
| eva | 1 | -$172 | $82 | -$254 |
| ab | 11 | -$5 | $123 | -$128 |
| tt | 1 | -$27 | $86 | -$113 |
| jon-and-kian, neal, giul, MK | 7 | +$29 | $125 | -$96 |
| **common-stock** | 6 | **+$116** | $34 | **+$82** |

**The funnel.** 272 actionable ideas → 59 analyst takes → 35 fills. **17 of 59 takes (29%) were risk-infeasible**:
the option could not be sized inside the ~$92 risk budget. 7 avoidable misses, all 09-08 → 09-17 (analysis failures
since fixed).

**Research books.** eva's immediate book shows +$128k, but it is ONE ticket: META +$153k of cash; without META, MSTR
and MRVL nearly every eva name lost (AMZN -$36k, MU -$31k, TSLA -$22k, AVGO -$20k …) and 74 lots are still open. The
analyst declining 106 of 108 eva ideas is right; there is no eva edge to chase at our size.

## 3. Findings (adversarial)

| # | Finding | Evidence | Severity |
|---|---|---|---|
| F1 | **Options are where the desk loses.** The desk expresses most tips as options by default; the option cohorts carry the whole loss while shares are positive. | cohorts above | High |
| F2 | **Opening-quote exits are the single worst class** (-$830, 6/6 losers). Stops/premium stops fire on the 09:30 quote, when option spreads are widest, not on a considered price. | exit table; overnight study | High |
| F3 | **Mirroring the source's exit is the best exit** (+$417; +$378 this week) - but it depends on the analyst noticing (NEM 09-23 was missed until the author-flat rule, 09-24). | exit table | High (opportunity) |
| F4 | **One source consumes 41% of model spend and returns nothing.** muggzone: 73 ideas, 19 takes, 8 fills, all option losers, $334 of model. | source table | High |
| F5 | **29% of takes cannot be sized** as options at the risk budget - lost opportunities, and a sign the vehicle is wrong for our book size. | funnel | Medium |
| F6 | **The knowledge base is bloated and unmeasured.** 1,068 live source notes (1.56M chars), 603 never relied on; 347 ticker notes (200 never relied on); 37 operative rules (41.7k chars on every call), 18 bound to fewer than 3 cases; rule reliance is still not recorded. An intake run's trace is ~58k chars. | knowledge ledger | Medium |
| F7 | **Model cost is now small; what remains is cache writes** (~$12 of $21/day): each review writes its message-specific context. | `tip_llm_cost` 09-24 | Low |
| F8 | **Every test/evaluation run is fragile on this host.** Six+ background runs were killed for low memory this week (evals, broad suites). | session log | Medium (ops) |
| F9 | **Card alerts only reach push.** Telegram is not configured; a missed push means an expired card. | `TipCardAlert.sent.telegram=false` | Low |
| F10 | **Sample size.** 17 sessions, 35 fills, 22 completed ideas - no cohort can claim an edge; the direction (shares > options, mirror exits > stops) is consistent across all three weeks. | scorecard | - |

## 4. The plan (ranked by expected value)

### Tier 1 — trade what has worked (profit levers)

| # | Change | How | Expected value | Risk / check |
|---|---|---|---|---|
| **P1** | **Shares-first expression in Practice.** A tip is expressed in SHARES at the same underlying stop unless the source has an option record that earns options (≥10 completed option ideas net positive after fees) or the analyst states why only the option works (event, defined-risk spread). Lotto lane unchanged but capped (see P6). | per-source `expression` policy default -> shares; the existing equal-risk share sizing (P-E) becomes the default path, not the fallback | Removes the vehicle behind -$1,033 of losses; also removes most of the 29% risk-infeasible takes (F5). Shares cohorts +$243 on 11. | Practice only; journaled per card (`vehicle` + reason); review after 10 sessions against the options cohort's shadow. |
| **P2** | **Mirror the source's exit deterministically.** When extraction reads a trim/close/stop-out by the author on a position we mirror (source tag match), act on it without waiting for the analyst's judgement: close (or trim the same fraction) at the next quote; the analyst can only veto with a stated reason. | follow-up path: `action in (trim, close)` + source match -> `close_position` (reduce-only, RiskGate safety list) | Best exit class (+$417, 6/8 winners); removes misses like NEM 09-23. | Practice only; journaled `TipSourceExitMirrored`; exits only, never opens. |
| **P3** | **No stop decisions on the opening quote.** Between 09:30:00 and 09:34:59 ET an OPTION position's premium stop / quote-based stop waits for (a) the underlying stop to breach, or (b) the 09:35 first closed bar, unless the loss exceeds a hard catastrophe floor (e.g. -60% premium). Venue GTC stops on shares are unchanged. | position manager premium-stop gate by clock; setting `techniques.tip.open_stop_grace_s=300` | Targets the -$830 class directly. | Research check first on the 6 cases + hold-study opening samples (replay each with a 5-minute grace); ship only if it does not turn a stop into a bigger loss in those cases. |

### Tier 2 — spend where it pays

| # | Change | How | Expected value |
|---|---|---|---|
| **P4** | **Source allocation by net-after-model-cost.** muggzone -> `observe` (reviews still manage anything held; no new Practice entries), florida-man -> proposal-only (a human confirms), common-stock budget +50%. Revisit monthly from the source table. | per-source policy `mode` / `budget_per_tip` (journaled) | Cuts ~40% of review spend (~$4-8/day) and the source with 0 winners; puts budget where the only positive record is. |
| **P5** | **Enforce the relevance gate** (not only the non-actionable slice) if tomorrow's five-session report shows 0 management false negatives. | `techniques.tip.review_gate=enforce` (P1 decision from the S21 package) | -15-20% of reviews. |
| **P6** | **Lotto lane cap.** 0-3 DTE contracts: one per source per day, fixed $50 premium, never averaged down. | lotto budget knobs | Keeps the fat-tail optionality (eva-style) at a size that cannot hurt. |

### Tier 3 — knowledge that earns its place (quality + cost)

| # | Change | How | Expected value |
|---|---|---|---|
| **P7** | **Rules get ids and reliance is recorded.** Each operative rule rendered as `R12 …`; the analyst's reply lists the rule ids it used; `tip_notes.cited_count` counts them. | prompt + reply schema (additive field) | Makes the 37-rule tax measurable; after 10 sessions, rules never relied on become proposals, not operative. |
| **P8** | **Weekly note compaction per source.** One canonical `source:<name>` note (current book, habits, reliability, exits) rebuilt weekly from the notes; the rest tombstoned through the audited batch path (reversible). Retire never-relied-on ticker/source notes after 14 days (was 30). | knowledge maintenance job, propose-only rules stay human | Smaller, sharper context; less noise for the analyst; ~-20-30% of per-review input. |
| **P9** | **Second cache block per source.** Order the header rulebook → source notes → message, with a cache marker after the source block, so a source's consecutive reviews share it. | review_context stable-first extension | ~-$3-5/day of cache writes (F7). |

### Tier 4 — operations and measurement

| # | Change | How |
|---|---|---|
| **P10** | **A nightly Tips verify task** like EM's `ZargarVerify274`: own test DB, runs the Tips suites only when ≥ 2 GB is free, posts the result; evaluations use the same gate. | scheduled task + script (F8) |
| **P11** | **Telegram for card alerts** as the second channel (your bot token; one-time setup by you). | settings (F9) |
| **P12** | **Promotion rule written down.** A source's Practice mode and vehicle are earned: ≥ 10 completed ideas, net positive after model cost, per vehicle. Until then: observe or proposal-only. | per-source policy; weekly review table (`tip_weekly_review`) |

## 5. What to stop

- Buying options by default for sources with no option record (F1).
- Letting the opening quote decide stops (F2).
- Paying for reviews of a source that has not earned them (F4).
- Growing notes and rules without measuring use (F6).
- Launching broad test/eval runs on a host at < 2 GB free (F8).

## 6. Order of work

1. **Tonight/tomorrow (no trading change):** P7 (rule ids + reliance), P9 (source cache block), P10 (verify task).
2. **After tomorrow's five-session report (09-25):** P5 decision; P3 replay study, then ship if it passes.
3. **P1, P2, P4, P6** as Practice policy (journaled settings, per-source), measured over the next 10 sessions against
   the option-cohort shadow and the pre-change record.
4. P8 compaction once P7 has recorded two weeks of reliance.
5. P11 when you set up the Telegram bot; P12 applied at each weekly review.

**Target:** trading ≥ +$105/week (break-even after model cost) within two weeks of P1-P4; the model bill stays ≤ $25
per weekday.

## 7. Found the same night, and the EM desk's cross-desk review (2026-09-24 late)

**Defects fixed tonight (0.8.48):**

| # | Defect | Fix |
|---|---|---|
| D1 | **JELD after-hours stop-out.** An after-hours 1.60 print under a 1.6708 stop fired the underlying crash brake every ~4 s from 16:57 to 18:01 ET (305 exits), released the venue GTC stop and left a MKT DAY sell for the open. | Crash brake acts only in the regular session (`sessions.in_regular_session`) and never while an exit order is working; chaos test added. |
| D2 | **save_note full scopes filed as `general`** (EM P2.1: 135 of 701 saves). | `note_scope_from_args` honours `source:<name>` / `ticker:<SYM>` as written. The mis-filed notes are NOT re-scoped (propose-only knowledge; a reviewed batch can do it from the run traces). |
| D3 | **A new HTTP client per Discord image** plus a synchronous file write, both on the event loop (EM P0.4, a top stall stack). | One shared media client; the write moves off the loop. |
| D4 | **The extraction system prompt was not cached** (EM P2.5). | Cached block when Tips prompt caching is on. |

**Reported, not changed:** the position manager's roll-up gate compares `session_window(now) == "regular"`, but
`session_window` returns prime_open / midday / prime_close / extended, so **roll-ups have never run since v0.6.2**.
Fixing the comparison would switch on option rolls for the first time: a trading decision, listed as P13.

**EM's cross-desk items that agree with this plan:** P1.1 (hold vs next-open exit; the 10 positions sold within
10 minutes of the next open lost -$880) = F2/P3 here; P1.3 (judge sources excluding each source's top 3 trades; eva
is +$122k with them, -$69k without) = the eva finding and P4/P12; P2.2 relevance-based note retrieval and P2.3 settle
the 29 pending rules = P7/P8; P2.4 enforce the gate and per-source budgets = P4/P5. EM's estimate for its P2 set:
about $13-15 per weekday, down from $21.

| # | Added decision | Note |
|---|---|---|
| P13 | Switch on option roll-ups (fix the gate) | never live; needs a replay on held winners first |

