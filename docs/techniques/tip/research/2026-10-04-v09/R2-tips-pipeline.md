# R2 - Tips pipeline review (0.8.61, runtime checkout C:/Cursor/zargar @ claude/deploy-0859 e333aa89) - 2026-10-04

Scope: intake -> deferred stage -> analyst (alternatives / re-ask / prefetch / events) -> proposals (fan-out, band,
TTL, earnings, spreads) -> runner (arms, entry_gate) -> exits (policies / positions) -> market_events store.
Read-only: code read + read-only SQL + one pure-function evaluation (no tests run against a DB, no runtime writes).

**Context that matters for tomorrow:** no `TipBookFanOut`, `TipAppraisalDeferred`, `TipAlternativesOffered` or
`TipDeferredStageRecovered` row exists in the journal. The 0.8.59-0.8.61 code (deferred appraisal, multi-book fan-out,
watch->arm, find_alternatives, earnings-by-timing) has **never run in a market session**. Monday 10-05 is its first
session, and the first session with the IBKR paper book bound (`Tips IBKR Paper` 29bca4..., role live, mode auto,
allowLiveAuto, armAtLevel, capitalCap 3000, `trading.mode=live`, `live_parity` on).

No BLOCKER was proven. H5 could become one on IBKR. It needs a check in the first paper minutes.

---

## HIGH

### H1. The earnings window refuses every entry for the whole BMO report day (the code does not match its docstring)
`execution/policies.py:553-569` `earnings_exit_due`: `end = midnight after the report date` for **every** timing. The
docstring says "BMO at that day's open". I evaluated the pure function directly:
- BMO 10-22 at 10-22 10:30 -> *due* ("flat by 10-21 15:45").
- BMO 10-22 at 10-22 15:00 -> *due*.
- Unknown timing is treated as BMO, so it behaves the same way.

`proposals._earnings_context` (`approvals/proposals.py:1137-1140`) and `runner.entry_gate` (`techniques/tip/runner.py:527`)
refuse on `due`. So a post-earnings tip (for example "DAL beat, buying" on 10-09, DAL BMO in the store) is refused on
the record all day: `TipLaneDecided lane=refused reason=earnings window`. That is a systematic profit leak on the
day-after-the-print setups that tipsters post most. It does not protect anything, because the report is already out.
**Fix:** for BMO/unknown, `end = combine(d, 09:30 ET)`; keep the AMC end at midnight of the report day. Add a test for
BMO report day 10:00 -> None.

### H2. Entry and exit read DIFFERENT earnings sources, and the store keeps stale dates
- Entry (`proposals.py:1118-1123`) reads `market_events.earnings_for()` first and falls back to Yahoo
  `calendar.next_earnings`.
- Exit (`execution/positions.py:1409-1420`) reads only `calendar.next_earnings` (Yahoo, with its own timing parse).
- The store keys earnings rows `source:earnings:SYM:DATE` (`research/market_events.py:59`) and writes them with
  `tombstone_missing=False` (`refresh_earnings`). When a source moves a date (estimate -> confirmed), the old row stays
  current. `earnings_for` then takes the EARLIEST future row.

Failure scenario: the store says AMC (or an old earlier date) while Yahoo says unknown timing (or the new date). The
entry is admitted, then the first decision bar after adoption fires the `event` exit. This is the exact D7/W1.7
buy-then-force-sell that 0.8.59 meant to remove. The reverse also happens: a stale early date refuses entries for days.
Today no symbol has two rows from one source (36 Yahoo + 5 Nasdaq rows), so the drift starts with the first moved date.
**Fix:** one resolver shared by both paths (for example `ProposalService._earnings_context` logic moved into a shared
function that `PositionManager._decide` calls). In `refresh_earnings`, tombstone that source's other future rows for
every symbol refreshed.

### H3. The W3.1 1.10x option band is measured against the STATED contract even when the analyst reshaped to another contract
`approvals/proposals.py:814-827`: `ref_price = analyst.limit_price ...`, then
`if ref_price > sig.premium * 1.10: ref_price = sig.premium * 1.10`. Here `sig.premium` is the tip's stated contract
premium. After `find_alternatives`, the take's `contract` can be a **later expiry, same strike** (alternative kind 2).
That contract is normally more expensive than the stated one, so the limit is pinned below the market and the order
rests unfilled. Option 2 of W2.1 can therefore never fill on the tip-time path.

Related: `alternatives.apply_choice` (`techniques/tip/alternatives.py:578-580`) keeps the analyst's own `limit_price`
whenever it is lower than the alternative's ask. If the model echoes its limit for the stated contract, the reshaped
contract inherits that lower price.

Practice is shares-first for long ideas, so today this hits puts, lotto tips and any `expression: as_tip` source.
**Fix:**
- Apply the band only when `occ == canonical(stated contract)`. For a reshaped contract, cap at its own decision ask
  (or ask x band).
- In `apply_choice`, always take the chosen alternative's `limit_price` when `contract != stated`.

### H4. Verticals have two sizing authorities, and the analyst is told verticals are never auto-approved
- `find_alternatives` sizes a debit vertical with `fit_expression` (delta-linear loss at the stop on the net debit;
  `alternatives.py:251-257`). It can report "fits, qty 2".
- The proposal gate sizes the same spread by FULL max loss (`_spread_risk_plan`, `proposals.py:1342-1363`;
  `_admit_geometry` spread branch `:1657-1669`). With a ~$100 budget, any debit above $1.00 is `reviewRequired`.
  Under unattended Practice that card waits for a human and expires.
- The tool also hard-codes `autoEligible: False` and the note "a spread card waits for a person (never auto-approved)"
  (`alternatives.py:412-418`). That contradicts the 2026-10-03 decision that a fitting defined-risk spread
  self-approves, and it steers the analyst away from verticals.

Evidence from the last 3 days: 4 of the ~10 skips were "one lot risks > budget": MU 1200/1215 spread $170 vs $99.87,
MSTR $170 vs $99.77, a 44C $164, tt $138. These are exactly the W2.1 cases, and the vertical branch will mostly
promise what the gate refuses.
**Fix:**
- Size verticals in `find_alternatives` with `unitLoss = net * multiplier` (defined risk), the same arithmetic as
  `_spread_risk_plan`.
- Set `autoEligible` from `_geometry_scope == "enforce"` and fit >= 1, and drop the stale note.

### H5. (verify on IBKR paper) A failed TRIM is retried as a FULL market close; partial sells rest beside a full-size GTC stop
`execution/positions.py:1767-1778`: the failed-exit watchdog retries ANY last exit in ERROR/REJECTED/REJECTED_RISK with
`close(fraction=1.0, kind="stop", force_market=True)`. A rejected 50% trim (from the ladder, the quote-watch target or
a source-exit mirror) becomes a full flatten at market, which kills the runner.

`close()` cancels the venue GTC stop only when `fraction >= 1` (`:995-1000`). A partial sell is therefore sent while a
GTC stop for the full held quantity rests. On an IBKR cash account, check whether that sell is accepted (a cash
account cannot go short; total working sells would exceed the position).

If IBKR rejects it, every trim on the paper book becomes "rejected -> watchdog -> flatten everything". Today's open
Practice positions all carry full-size GTC stops (IBM 8, CVX 2, VSH 18, ENOV 83, PL 59). Watch the first trim on paper.
**Fix:**
- The watchdog re-sends the failed exit's own fraction and kind (only a stop or close escalates to full).
- For IBKR, shrink the venue stop to `held - trim` before sending a partial sell.

---

## MEDIUM

### M1. Fan-in siblings inherit a watch's `entry_level` / `underlying_stop`, so W2.3 arms every branch at branch 1's level
`signals/service.py:3018-3028`: the sibling copy pops entry fields only when the shared verdict is `take`. A shared
`watch` keeps `entry_level` and `underlying_stop`. Then `watch_arm` (`:3101-3105`) arms EACH sibling (a different
ticker) at the first ticker's level. `build_tip_plan_for` uses it as `tip_entry` (`:3576`).

On a ≥3-branch map, that is an at-level plan on ticker B with ticker A's price. Depending on side and distance, it is
either invalid or fires at once (auto mode, live book included, because the binding has `armAtLevel`). Historically
all 152 fan-in rows were skips, but the 0.8.59 prompt now asks for levels on watches.
**Fix:** for a fan-in inheritance, pop the entry/exit fields for `watch` as well, or require `not opinion.get("fanIn")`
in `watch_arm`.

### M2. The deferred-stage follow-up block is too broad (rolls, update_stop, other contracts)
`signals/service.py:2128-2135`: ANY later `trim|close|update_stop` signal from the same source on the same ticker
refuses the card or arm. Three cases are caught wrongly:
- **Same-message rolls:** a sibling signal in the SAME message ("trimmed 10/10, opening 10/17") is a later row.
- **`update_stop`:** the source managing the position it just opened.
- **Different contract:** a trim of an older contract on the same ticker.

In sync mode the open would already have traded. This turns rolls and early stop moves into misses.
**Fix:**
- Exclude `Signal.raw_content_id == row.raw_content_id`.
- Require the same contract when both rows carry one.
- Drop `update_stop`, or turn it into an update of the new plan's stop.

### M3. A failure during the W2.2 re-ask throws away the first opinion
`techniques/tip/analyst.py:2450-2459`: only `_parse_opinion` is guarded. An `AnalystDeadline`, timeout or API error
inside the re-ask's `run_agent_loop` propagates to `analyze_tip`'s outer `except`. The run is persisted `failed` and
None is returned.

The original skip or watch (including a W2.3 watch with level and stop, which would have armed) is lost. Auto then fails
closed: "no verdict". The `< 15 s` precheck reduces this but does not remove it (the final call can still be cut).
**Fix:** wrap the re-ask in `try/except Exception: return op` and record `budgetReask.outcome="error"`.

### M4. Historical event context reports "no scheduled event" on real FOMC/CPI days
`research/market_events.py:330-341` `as_verified` stamps every store event `verifiedAt = valid_from` (first fetch
2026-10-03; BLS stamped `BLS_READ_AT`). Coverage (`coverageThrough` 2026-12-23) is NOT cut to the knowledge instant.

`events.event_context(as_of=...)` (`techniques/tip/events.py:108-131`) hides events verified after the cut but still
calls the session "covered". Any replay or experiment before 10-03 on 09-16 (FOMC) or 09-11 (CPI) is labelled
`no-scheduled-event` with coverage `verified`. That is the exact defect W4.1 set out to fix ("the 09-16 FOMC later
read as no event"). Only the manual list's FOMC entries rescue part of it. Live decisions are unaffected.
**Fix:** treat an as_of before the source's first coverage fetch as `unknown`; or backfill `valid_from` for historical
rows. Do both, and cut coverage to the latest coverage row with `fetched_at <= as_of`.

### M5. At-level option arms price their cap at the tip-time premium
- `runner.entry_limit_cap` (`techniques/tip/runner.py:124-141`) uses `analyst.limit_price or sig.premium` x 1.10.
- `_create_from_armed_fire` (`proposals.py:484-490`) uses the same reference as the limit, improved only downward.

For a breakout or reclaim level above the tip-time spot, the call costs more at the touch than at tip time, so the
entry rests at a stale cap and expires. A watch-armed plan (W2.3) usually has no `limit_price` at all, so it falls back
to the stated premium. Systematic non-fill on the best (momentum) fires.
**Fix:** reprice the cap at the touch from the decision-time delta (`ref + delta x (level - spot_at_appraisal)`), or
use a band on the fire-time ask, never on a tip-time print.

### M6. `approve()` does not re-check the earnings window
Earnings are judged only at card creation (`proposals.py:660`, `:472`) and at the armed `pre_order` gate. A human card
created at 15:40 before an AMC cutoff and approved at 15:50 enters, then the event exit sells it on the next bar. This is
low frequency now that books are unattended.
**Fix:** call `_earnings_context` in `assess()` / readiness.

### M7. W1.10 is still open and still observed
`tip_analyst_runs` rule_audit runs have `status=partial` with an EMPTY error on 09-29, 09-30, 10-02 and **10-04 17:25**.
The PLAN box is unchecked, so the review cannot tell a judge failure from a partial success.

---

## LOW
- **L1.** The Practice binding's `budgetPerTip: 3000` is ignored, because overrides may only LOWER the source budget
  (`proposals.py:287-291`). It is dead config. common-stock 3000 on paper uses the whole $3,000 `capitalCap` in one
  tip, so the next tips are cut to $300-661 or refused.
- **L2.** `shadow_arm_open_tips` (`runner.py:617-620`) skips every `watch`, including watch-armed ones. `arm_shadow`
  (`:579`) admits them, so the armed research book never re-arms armed watches on later days.
- **L3.** Fast lane observe (`observe_lanes.py:57-60`) compares `sig.entry_price` (underlying) with the underlying ask.
  An option tip has no entry price, so "no stated price" is recorded and the lane can never "would" on options. The
  research data is biased. Also, `asyncio.create_task` keeps no reference (`service.py:2999`), so the task can be
  garbage-collected.
- **L4.** A promoted (implied -> take) card is stamped `autoGate: "promoted from shadow - a human approves"`
  (`service.py:3195-3196`), but `_decide_auto` self-approves it on unattended books (`:3990`). The record contradicts
  itself.
- **L5.** `_earnings_context` returns (None, None) when `engine.calendar` is None, even if the store has the date
  (`proposals.py:1116`).
- **L6.** `earnings_for` takes `timing` from the first non-unknown row of ANY date or source
  (`market_events.py:366-367`), not from the chosen date.
- **L7.** Open positions adopted before 0.8.59 keep the whole-day rule (`flatten_before` without `timing`). For
  example, CVX (BMO 10-30) is sold at the first 15m bar of 10-29 instead of 15:45. This is known and harmless, but it
  is a leak.
- **L8.** The share-substitution and shares-first decisions use `policy_kind` (`sim` under live_parity), while
  `find_alternatives` uses the real kind for `why_shares`. The two agree today (paper = shares-only), but the logic is
  duplicated. Keep it in one helper.

---

## Runtime data (last 3 sessions 09-30, 10-01, 10-02; read-only SQL)
- **Lane decisions:**
  - 15 `TipLaneDecided`: 13 proposal, 2 arm (auto, at-level), 1 refused.
  - The refusal was 09-30 15:59: "book slots full: 7 open tip positions ... max_open_positions 7".
  - 1 `ProposalExpired` (ttl, 09-30 14:17).
  - No `TipAutoPaused`, no `TipBookFanOut`, no deferred-stage rows (new code not yet exercised).
- **Analyst skip reasons:** ~half of the skips/watches on BTOs were budget/one-lot-risk: MSTR 245C $170 vs $99.77, MU
  spread $170, a 44C $164, a tt lotto $138. The others were judgement: hedge (R4), escalation (R3), tape. W2.1 targets
  the budget half, and H3/H4 cut into it.
- **Analyst runs since 09-29:**
  - 80 appraise done + 1 failed: META 09-29 13:21, timeout.
  - 337 intake + 1 failed: timeout.
  - rule_audit: 4 partial with empty error (M7).
  - Verdicts: take 20 / skip 52 / watch 8 / none 1.
- **Positions and stops:**
  - Every open Practice tip position has a GTC venue stop sized to the held qty: IBM 8 @218.28, CVX 2 @204.2,
    VSH 18 @30.9, ENOV 83 @17.0, PL 59 @15.45 (old book, open since 09-21).
  - Shadow MU spread: `stop none`, guard defined-risk (valid).
  - No unprotected position found.
- **Exits:** no wrong-fire pattern in 09-29..10-02. The 99x "intra-bar quote breach" CANCELLED storms (ACHR, AVGO,
  JELD) are all 09-24 and predate the F-HOLD-01 fix. The 17:10 ET `updated_at` stamps on old-book positions are
  archival writes, not late fills: last-fill vs `closedMs` agree.
- **Intake:** `TipIntakeStalled` 2-5 per day, each followed by `TipIntakeRecovered`.

## Profit leaks (systematic)
1. **BMO report-day entry block (H1):** day-after-print setups refused all day.
2. **Unknown earnings timing is read as BMO:** an AMC name without timing is flattened a full session early, and
   entries are blocked from 15:45 the day before.
3. **Failed trim becomes a full market flatten (H5):** kills runners. On IBKR it may hit every trim.
4. **Reshaped later-expiry contracts are limited below market (H3)**, and verticals are promised but gate-refused (H4).
   The "find another way" lane is mostly a no-op where it matters.
5. **At-level option caps use tip-time premium (M5):** momentum fires do not fill.
6. **Deferred block on same-message rolls and update_stop (M2).**
7. **Capacity:** the 7/7 slot cap refused a late tip on 09-30. Shares positions hold up to 15-20 sessions
   (`time_stop_sessions` 15/20), and stale exits only at 5 sessions/<0.5R. Capital sits in flat names (PL 10 sessions,
   CVX/IBM/VSH). On paper, the $3k cap with a $2-3k per-tip budget allows about 1-2 concurrent ideas.
8. **Time stop exits winners regardless of trend:** `time_stop_sessions` fires even when the trail is working. Consider
   "time stop only if < X R" (as stale does) for shares.

## Suggested pre-open checks for 10-05
- The first deferred intake journals `TipAppraisalDeferred` -> `...Done` and a `TipBookFanOut` with both books.
- The first paper trim. If it is REJECTED, set the binding to `enabled=false` until H5 is fixed. The watchdog would
  otherwise flatten the position.
- Any `TipLaneDecided refused reason~"earnings window"` on a BMO report day is H1.
- `TipAlternativesOffered` rows where `chosenKind=expiry` and the proposal never fills are H3.
