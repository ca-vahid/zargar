# D. Event calendar and event analysis for the Tips desk

Prepared 2026-10-02 from read-only queries against the runtime DB (`zargar-db`) and the code in `C:/Cursor/zargar/backend`. Window: Practice books `4611946d…` (from 2026-09-08) and `88aa8a26…` (from 2026-09-28). All times below are ET.

**Verdict:** yes, the desk needs a real event calendar. The reason is not the P&L so far: 47 trades is too few to show an event effect either way. The reasons are these:
- The data the app has today is hand-maintained, overwritten in place, and unranked.
- It only ever looks at today's session.
- Nothing on the entry side consults it. Armed plans fire straight through events.
- The earnings guard works only on the exit side, which leads to wasteful round trips (ORCL, below).

---

## 1. What event data exists today, and who reads it

| Data | Where it lives | Coverage / quality | Who reads it | Enforced? |
|---|---|---|---|---|
| **Tips verified macro events** | setting `techniques.tip.verified_events`. If unset, it falls back to `DEFAULT_VERIFIED_EVENTS` in `techniques/tip/events.py` (FOMC 09-16 only). | Updated by hand 3 times (journal `SettingChanged` 2026-09-17, 09-18, 09-24). Each update **replaces** the whole list. The current value starts at 2026-09-24, runs through 2026-10-09 (`coverageThrough`) and holds 15 entries. These mix Tier-1 items (NFP 10-02, PCE/GDP 09-30, JOLTS 09-29) with Treasury bill auctions, Fed G.19/G.20 statistical releases and BLS "Employee Benefits". There is no importance tier. **CPI was never on any version** (the 09-11 CPI is known only from a source post that the analyst called "eva's daily post-CPI level map"). The October CPI falls after 10-09, so it is not covered. | `events.context_for()` is called from: the analyst run header (`analyst.py:2183/2557`), `opinion.eventContext` (`analyst.py:2322`), proposal cards `context.eventContext` (`approvals/proposals.py:93,492,921`), cohort rows (`cohort.py:284,374`), and the hold study (`holdstudy.py:108`). | **No.** The module docstring says: "Nothing here places, blocks, sizes or times an order. It labels." The header line says "no automatic no-trade rule." |
| **Shared macro calendar** | `research.macro_events` (`research/macro_calendar.py`, engine `eng.macro`) | **Empty.** There is no row in `settings`, so the default `[]` applies. The code says "no remote source wired". | Team2's route `routes_team2.py:23` (`describe()`), and the Tips label (reported separately as "shared-manual"). | No. |
| **Earnings / ex-dividend** | `calendar_service.EventCalendar` (`engine.calendar`): Yahoo quoteSummary `calendarEvents`, held in an **in-memory 12 h cache only**, never persisted. `confirmed=False` always, from a single source. | Next date only. There is no history, so a past hold cannot be checked against it afterwards. | (a) **Exit:** `flatten_before {event: earnings, days: 1}`. Every tip position gets it by default (`lifecycle.py:296`, `avoidEarnings` defaults to True); `positions.py:1409` and `policies.py:410` close at `days_to_earnings <= 1`. (b) Signal verification adds `verification.calendarContext` when earnings fall inside horizon+4 days (`signals/service.py:2590`). This was set on 61 of 1,105 signals since 09-08. (c) The analyst tool `get_earnings` (`analyst.py:1300`). | **Exit side only.** No entry, sizing or arming path calls `days_to_earnings`. |

### Defects in the current implementation (with evidence)

1. **History is lost on every update.** Each `SettingChanged` replaces the list, and the current value's earliest entry is 09-24. Because the setting is non-null, it overrides `DEFAULT_VERIFIED_EVENTS`, so the 09-16 FOMC is no longer on the effective list. There is also no `coverageFrom`, and `event_context` treats any session `<= coverageThrough` as covered. So a replay, cohort re-label or hold-study read of **2026-09-16 run today is labeled `no-scheduled-event`**. That is false, and it is the exact failure TMR-01 was built to prevent ("unknown coverage is not 'no event'").
2. **No tiers means the label is noise.** The analyst header carried `event-day` on 221 of 236 labeled appraisals: every trading day from 09-17 to 10-02 except 10-01. The triggers include "Treasury 13-week and 26-week bill auctions" (09-21, 09-28) and "Fed G.20 Finance Companies". When everything is an event day, the label stops carrying information.
3. **It only looks at today.** `event_context` filters on `date == session`. A swing take on 10-01 with a 10-session hold cap and a 10/16 contract is told nothing about NFP on 10-02, which is the next morning.
4. **The earnings exit is not mirrored at entry, which causes round trips.** In the ORCL shadow book (`417efcf2…`, "MuggZone (armed)"):
   - Adopted 09-09 09:36, flattened 09:45 with "earnings in 1 day(s)".
   - Re-entered **09-10 09:32**, flattened **09:45** with "earnings in 0 day(s)".

   Both are two 12-share entries closed at the first 15m bar close. The entry path never asked the calendar the exit path asked nine minutes later.
5. **Armed plans fire through events.** On 2026-09-14 the analyst armed GOOGL at its 342.5/340.4 zone and wrote "+2.3% at session highs into the 9/16 FOMC". The plan carried no event condition. Trigger `tip-7794ebdca5d6-2` fired **09-16 15:17**, 77 minutes after the statement, during the post-decision slide (SPY 760.98 down to 749.6). It filled GOOGL 360C 10/16 at 5.40 and was stopped by an intra-bar quote breach at 15:30 for **−$25.10**. In the same afternoon the analyst *skipped* every fresh tip and cited the FOMC each time.
6. **Earnings dates are single-source and unpersisted.** Yahoo's date for ORCL moved from 09-10 to 12-10 the moment the report passed. Nothing records what the app believed at decision time, so earnings exposure cannot be audited after the fact.

---

## 2. Tip trades open across major scheduled events

There are 47 closed tip positions in the two Practice books; every one carried `flatten_before: earnings` and none was closed by it. Tier-1 instants used here:
- CPI 09-11 08:30. This date is **inferred** from a source post and is not on any app list.
- FOMC 09-16 14:00.
- PCE/GDP 09-30 08:30.
- NFP 10-02 08:30.

| Group | n | Realized $ | Mean $ | Winners |
|---|---|---|---|---|
| Open across ≥1 Tier-1 event | 11 | **+245.45** | +22.31 | 5/11 |
| Not across one | 36 | −1,016.85 | −28.25 | 15/36 |
| Options across / not | 6 / 18 | +75.76 / −1,161.63 | +12.63 / −64.54 | 2/6, 5/18 |
| Shares across / not | 5 / 18 | +169.69 / +144.78 | +33.94 / +8.04 | 3/5, 10/18 |

Trades that spanned a Tier-1 event:
- **CPI 09-11:** APLD opt −204.09, T opt +131.96, DAL opt −13.04, GOOGL opt +250.00 (TP1 on the CPI morning).
- **FOMC 09-16:** MRNA shares +94.10. SLV 11/20 65C −38.04, stopped on the bar close at 15:00, one hour after the statement.
- **PCE/GDP 09-30:** ACHR opt −51.03, NBIS shares +22.65, UBER shares −38.74.
- **PCE/GDP and NFP:** KWEB shares −67.58 (closed 10-02 09:40, venue GTC stop, after the NFP gap), ON shares +159.26 (10-02 09:45).
- Still open across NFP: CVX, IBM and PL (all shares).

Other trades near events:
- **Event-adjacent entry:** GOOGL post-FOMC armed fill, −25.10 (above).
- **NFP-morning entry:** VSH shares (open). The analyst flagged "entering into a 5.5% opening gap during the post-NFP first hour".

**Interpretation:** this data does **not** show that holding through events hurt. The event-spanning group did better, but that is mostly survivorship: a position has to survive several sessions to span an event, and the worst options losers (premium bleeds, 0DTE lottos) died within a day. With n=11 and n=36, both drawn from overlapping dates, no event effect can be distinguished from noise. What the data does show is that events are **where the variance sits**:
- The two largest single-trade swings tied to an event morning are GOOGL +250 (CPI morning) and APLD −204 (held through CPI to a weekend breach).
- The two FOMC-window option outcomes were both losses (SLV, GOOGL).

**Index moves.** SPY regular-session range (from the `bars` 1m data) was largest on the FOMC day: **1.59% on 09-16**, against a 21-session median of ~0.71%. The FOMC day closed −0.43%, the next session gapped **+1.20%** and closed +1.13%. Other large days:
- 09-21: +1.56%, range 1.16%. The only "event" listed that day was a T-bill auction, so this move was unscheduled.
- 09-11 (CPI): gap +0.91%.
- 10-02 (NFP): gap +0.86%, close +0.74%.

Scheduled Tier-1 days account for three of the four largest gaps or ranges in the window.

**Earnings of traded names.** The only earnings dates the app ever saw are the 33 `get_earnings` tool results in analyst traces, from 26 symbols. No closed Practice tip trade was open across a known earnings date. The nearest was MU: shares entered 09-28, Yahoo's earnings date 09-30, closed 09-29 at TP1 for +22.47, so `flatten_before` would have fired on 09-29 anyway. Every other traded name's next date was 20 or more days out (DAL 10-08, IBM 10-21, T 10-21, ON 11-02, VSH/U/HOOD 11-04 …). Earnings exposure has been avoided by luck of timing, not by design: no entry ever checked it.

---

## 3. How often the analyst considered events

Analyst runs since 09-08: 369 appraise, 1,832 intake, 108 retro, 48 digest. The search covered `opinion.rationale` and `exit_rationale`, matched case-sensitively for macro terms.

| Mention (appraise runs, n=369) | Runs |
|---|---|
| earnings | 37 (10%) |
| FOMC / Fed / Powell | 26 (7%). 25 of these fall between 09-14 and 09-16; they concentrate entirely in FOMC week. |
| CPI | 1 (09-11, describing a source's "post-CPI" map) |
| jobs / NFP / JOLTS | 5 (09-29 JOLTS ×2, 10-01 and 10-02 NFP ×3) |
| PCE / GDP | 0. PCE/GDP was on the header on 09-30 and never mentioned. |
| `get_earnings` tool called | 19 of 369 appraisals (5%); 33 calls in total, including intake/review |
| Event label present on the opinion | 236 (from 09-16 on): 221 `event-day`, 15 `no-scheduled-event`, 0 `unknown` |

Qualitatively, where the analyst noticed an event it used it sensibly:
- On 09-15 it halved SLV size because "FOMC is tomorrow".
- It refused fresh long premium on 09-15 and 09-16 because of FOMC tail risk (NVDA, TSLA, MRNA ×2, META, AMD).
- It wrote **0 takes from 12 appraisals on 09-16**; the 09-14 to 10-02 trading days run 2 to 10 takes a day.
- It flagged JOLTS as a two-sided risk on BE and ORCL (09-29) and cited NFP (10-01 MU skip, 10-02 VSH and TSLA).

But its "86% hike odds" figure came from its own knowledge notes, not from a sourced calendar. It never considered PCE/GDP, and it checked earnings in only 5% of appraisals. Awareness is ad hoc and depends on the model happening to read the header. Nothing carries the analyst's awareness into the arm it leaves behind (the GOOGL case).

---

## 4. Feature proposal: "Tips event calendar v2" (observe first, then gate)

The design follows the desk's existing pattern: provenance-first data, journaled labels, shadow counterfactuals, and gates only after a preregistered measurement. Every gate is a `techniques.tip.*` knob in `settings_service.DEFAULTS`, defaulting to `observe`.

### 4.1 Data: one persisted, append-only event store (shared platform capability)

New table `market_events`, owned by the platform under `zargar/research/` so EM, Team2 and Cartel can read it:
- Columns: `id, kind, tier, name, scope (macro | symbol), symbol, instant_et, time_known, source, url, fetched_at, verified_at, revision, superseded_by, deleted_at`.
- Append-only revisions in the style of `tip_note_revisions`. An `as_of` read resolves the revision in force at that instant, so a moved date never back-dates.
- Coverage is recorded per source as an explicit `[coverage_from, coverage_through]` row. A date outside every coverage window is `unknown`, never "no event". This fixes defect 1.

Fetchers run as a nightly scheduler job plus a pre-open refresh at 08:00. Every fetch is journaled as `MarketEventsFetched` (counts, diffs, failures).

| Kind | Tier | Official source | Mechanism |
|---|---|---|---|
| FOMC statement, press conference, SEP; minutes | 1 (minutes: 2) | federalreserve.gov `monetarypolicy/fomccalendars.htm` | Yearly HTML parse; statement at 14:00, presser at 14:30 |
| CPI, Employment Situation (NFP), PPI, JOLTS, ECI | CPI/NFP 1, PPI/JOLTS 2 | BLS release calendar `bls.gov/schedule/` (iCal feed `bls.gov/schedule/news_release/bls.ics`) | iCal parse |
| GDP, Personal Income & Outlays (PCE) | 1 | BEA `bea.gov/news/schedule` (iCal available) | iCal or HTML parse |
| Weekly claims, retail sales (Census), ISM | 2 | DOL `dol.gov/ui/data.pdf` cadence (Thursday 08:30); Census economic indicator calendar | Rule plus calendar |
| Fed chair / governor speeches | 2 (chair), 3 (others) | federalreserve.gov newsevents calendar | HTML |
| Treasury auctions, G-series releases | 3 (label only, never shown in the header) | fiscaldata.treasury.gov auctions API | JSON |
| Earnings (BMO/AMC) | symbol-scoped, 1 for the held name | Primary: Yahoo (existing `EventCalendar`). Second source: Nasdaq earnings calendar JSON (`api.nasdaq.com/api/calendar/earnings?date=`) or Finnhub (key). | `confirmed=True` only when the two sources agree within 1 day; persisted daily for every held, armed or proposed symbol and the universe |
| Ex-dividend | symbol | Same sources | Already consumed by the short-call guard |

The manual `verified_events` path stays as an **override/annotation layer** written into the same store (`source=tips-desk`). The `research.macro_events` placeholder is retired.

### 4.2 Context: a horizon-aware exposure record

Replace "is today an event day" with "**which events fall inside this position's life**":
- Inputs: decision time; planned hold window `min(hold cap, contract expiry, horizon)`; instrument and DTE.
- Output, journaled as **`TipEventExposure`** on every proposal, arm, adoption and nightly hold:
  - events by tier;
  - minutes to the next Tier-1 event;
  - whether earnings fall before the option expiry or the hold cap;
  - the coverage status;
  - the knowledge cut.

The analyst header shows only Tier 1–2 events plus earnings for the ticker, so the noise from defect 2 goes away. The `get_earnings` result is supplied automatically in the header instead of relying on a 5%-used tool. `opinion` gains a required `event_ack` field: `none_in_window | acknowledged:<event ids> + one-line plan | event_play`. When exposure is non-empty and the analyst's `event_ack` does not cover it, the take is re-asked once, or under propose-only it is marked `needs_review`.

### 4.3 Policies (each one a knob: off | observe | enforce)

Policy **E0** fixes a bug and can be enforced right away. **E1–E5** start in `observe`: they compute and journal what they *would* have done (`TipEventPolicyShadow`), with counterfactual outcomes from the shadow books and quote history. They never touch an order until measured.

| ID | Rule | Rationale from this review |
|---|---|---|
| **E0** (enforce) | **Entry/exit consistency for earnings:** refuse a new entry when `days_to_earnings <= flatten_before.days`. The refusal is journaled as `TipLaneDecided lane=refused reason=earnings_window`. | ORCL round trips (defect 4): the exit rule already decided the answer. |
| E1 | **Tier-1 blackout for new entries:** no new option entry from T−60m to T+30m around FOMC statement/presser, CPI, NFP and PCE/GDP; shares from T−15m to T+15m. This covers `approve(via=auto)`, final submission and **armed-plan trigger fires**. Armed plans stay armed but are held: a level touch inside the window is recorded and re-judged on the first closed bar after T+30m. | GOOGL post-FOMC fill (defect 5); FOMC-day range 2.2× the median. |
| E2 | **Size-down across Tier-1:** an entry whose planned hold spans a Tier-1 event gets `risk_budget × 0.5`, or the analyst must label `event_play`. | Event days carry the window's largest gaps; the analyst already did this by hand for SLV. |
| E3 | **Short-dated options do not hold across Tier-1 or earnings:** an option with DTE ≤ 5 at the event is flattened before it (15:45 the prior session for 08:30 releases; T−15m for 14:00 FOMC) unless `event_ack=event_play`. | Theta plus IV-crush exposure; options are the desk's losing lane (−$1,161 on 18 non-spanning trades). |
| E4 | **Earnings timing-aware flatten:** derive the flatten instant from BMO/AMC rather than whole days: BMO means flatten 15:45 the prior session, AMC means 15:45 the same day. Applies to shares and options. Unconfirmed dates widen the window by one session. | The current `days<=1` flattens a full day early for AMC names and at 09:45 on report day. |
| E5 | **Arm conditions carry the event:** an arm created when exposure is non-empty stores `context.eventExposure`. On the event day the runner asks for a re-appraisal (`disarm_plan` or keep) before the window opens. | Carries the 09-14 analyst's own FOMC caveat forward to the 09-16 fire. |

Exits are never blocked (they remain reduce-only, per RiskGate). The integrity pause and the loss limits stay independent of these policies.

### 4.4 Measurement (preregistered; add to `research/EXPERIMENT-REGISTER.md`)

- **Cohort tag.** Each closed position is labeled `spans_tier1`, `entered_in_window(±60m)`, `spans_earnings`, or `none`, and the label is frozen at adoption from the `as_of` revision.
- **Outcome metrics:** realized R; MFE/MAE in R; premium change across the event (option leg); `TipFillVsQuote` slippage for entries inside versus outside the windows; and the stop-out rate within 30 minutes of entry.
- **Counterfactual.** For each `observe` policy, the counterfactual P&L of the blocked or resized trade (shadow book plus OPRA prints, priced on real prints and never on Black-Scholes), compared with the actual. Use date-clustered bootstrap intervals; event days cluster.
- **Decision rule, fixed in advance.** Promote a policy to `enforce` only if, over at least 25 affected trades **and** at least 6 distinct Tier-1 events (about 2–3 months at the current cadence), the counterfactual improves mean R with a date-clustered 90% interval excluding 0, or reduces the loss tail (worst-decile R) without lowering mean R by more than 0.05R. E0 needs no study; it is a consistency fix.
- **Data-quality metrics on the desk report:** coverage days ahead per source; any `unknown` coverage on a trading day; earnings confirmation rate; the count of date revisions (dates that moved after a decision).

### 4.5 Build order

1. **Store and fetchers** (Fed, BLS iCal, BEA iCal, Treasury JSON, two-source earnings), with the coverage rows and `as_of` reads. Also back-fill the three journaled `SettingChanged` versions and the 09-16 FOMC, so that history is labeled correctly.
2. `TipEventExposure` plus the tiered header, and **E0** enforced.
3. E1–E5 in `observe`, `event_ack` in the opinion schema, and the Settings "Tips technique" panel rows.
4. After the preregistered sample: review, then flip individual policies. These are user decisions, recorded in the Tips README and PLATFORM-RULES because the store is shared.
