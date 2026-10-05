# R1 - Money-path review before real money (IBKR cash, Tips only) - 2026-10-04

Scope: runtime checkout `C:/Cursor/zargar`, branch `claude/deploy-0859` (e333aa89, v0.8.61). Read-only: code reading,
read-only SQL on the runtime DB, one in-process Python check (no DB, no orders). Paths below are relative to
`C:/Cursor/zargar/backend/zargar/`.

## State found in the runtime DB (2026-10-04 ~23:00 UTC)

- `trading.mode = live` (real-order routing is already ON).
- `.env`: `ZARGAR_BROKER=ibkr`, port **4002 (paper)**, client id 17. Gateway account `DUR232647` (paper).
- The bound book is **`Tips IBKR Paper` (29bca492..., kind `paper`)**. No kind=live Tips book exists yet. A second
  IBKR-routed book `Live (IBKR)` (2d173f44..., kind `live`, venue defaults to ibkr) also exists.
- The paper book has **never routed an order to IBKR**: 1 order total (manual AAPL, REJECTED_RISK by the gate). No
  fill, stop, cancel or commission has been seen from the adapter. The runbook's paper pass criteria are unmet.
- Every `IbkrAccountSynced` row has **`settledCash: null`**. The account holds CAD 10,000 / USD 0; the book's cash is
  7,017.54 = CAD converted to USD (0.8.61 behaviour).
- `techniques.tip.allow_live_auto` is unset, so it takes the default `False`.
- `risk.daily_loss_halt_pct = 15` (the runbook says 3%).

---

## Findings (ranked)

### BLOCKER 1 - At-level (armed) auto fires on the live book skip the capital cap, cash glide, slot cap and risk sizing
- `techniques/tip/runner.py:361-365`: `arm_signal` sizes shares as
  `qty = max(1, size_by_budget(policy.budget_per_tip, entry_px))`. That is the **source** budget (global $2,000;
  `common-stock` $3,000). The binding's `capitalCap`, `reserveSlots`/`minBudget` glide, `budgetPerTip` and
  `maxOpenPositions` are never consulted. `_tip_budget` runs only on the proposal paths.
- `execution/planrunner.py:3031-3034` (`_size`): a fixed `cfg.qty` wins. The `risk_pct` sizing and the geometry gate
  (`_pre_entry_geometry` / `_admit_geometry`, proposals only) never run on an auto fire. `TipRunner.entry_gate`
  (runner.py:527) checks earnings and nothing else. `dailyLossLimit` is the source budget ($2,000) per plan.
- RiskGate does not save us: `cash_available` runs for `kind == "sim"` only (`risk.py:321`). The only other caps are
  `max_position_pct` 50% and `max_position_notional` $25k.
- The live binding has `armAtLevel: true` and `allowLiveAuto: true`, so `live_ack` is set (runner.py:478). Once the
  master `techniques.tip.allow_live_auto` is switched on for live, every analyst at-level take (and every W2.3
  "watch with a level") arms on the real account.
- Scenario: three at-level plans fire within an hour, each about $2,000-2,339 of stock. That is $6-7k deployed against
  a $3,000 cap, which is the whole account. Per-trade risk is whatever the stop distance gives, not 1%.
- Also: an option-shaped tip arms `instrument=options` on the live book (runner.py:352). Every fire then ends in an
  adapter rejection (no harm, but noise and a wasted fire).
- **Minimal fix for tomorrow:** set `armAtLevel: false` on the live binding. Code fix: size live/paper fires through
  `_tip_budget(binding)` + `_pre_entry_geometry`, or force `mode=proposal` on live bindings so a fire mints a card
  that `_decide_auto` approves through the same gates. Force `instrument=shares` for live books.

### BLOCKER 2 - Real-money routing is chosen by the gateway port, not by the book
- `engine.py:592-600` (`executor_for`): **every** `paper` or `live` portfolio whose venue is not snaptrade routes to
  the single IBKR gateway. Nothing checks that the connected account matches the book's kind (paper accounts are
  `DU...`). `ibkr.portfolio_id` only decides which book is SYNCED, not which books may route.
- Failure modes when the gateway moves to 4001:
  1. **Book left as kind `paper`.** If only the port changes, real money trades as "paper":
     - `_decide_auto` lets the binding's `allowLiveAuto` stand in for the master switch
       (`signals/service.py:3977-3978`: `kind != "live" or master`).
     - The armed-plan gate does the same (`runner.py:548-555` returns True for paper).
     - The morning triage auto-approves paper-kind cards with no binding check (`signals/service.py:3701`).
     - The real-money confirm dialog never fires.
  2. **Paper binding left in `techniques.tip.books` next to a new live binding.** Both books fan out and both route
     to the same live account: double orders. The unsynced paper book keeps sizing from its stale $7,017.
  3. **`Live (IBKR)` (2d173f44).** Any manual or other-desk order on it goes to the real account.
- Plus: the adapter has never completed a real order (see State).
- **Fix before go-live:**
  - Create a kind=`live` book.
  - Remove (not just disable) the paper binding, and archive `Tips IBKR Paper` and `Live (IBKR)`.
  - Do one supervised 1-share round trip: buy, check the venue GTC stop appears at IBKR with the held quantity, sell,
    check the commission.
  - Code: on connect, compare `managedAccounts()` (DU = paper) with the kind of `ibkr.portfolio_id`. Refuse to route
    any IBKR order whose `portfolio_id != ibkr.portfolio_id`, or whose kind disagrees with the account.

### HIGH 1 - The capital cap does not reserve in-flight entries (and RiskGate has no cash check on live books)
- `approvals/proposals.py:377-389` (`_book_open_cost`) and `:391-397` (`_book_open_count`) count only
  ManagedPositionRows. A tip entry gets a managed row only after it fills (`techniques/tip/lifecycle.py:730+`, which
  waits up to `FILL_WAIT_S` = 4 h).
- So a resting or unfilled LMT, or two tips appraised at the same moment (async appraisal, 6 gateway workers), each see
  the full $3,000 room and the full cash. Two $2,000 entries means $4,000 against a $3,000 cap.
- Nothing re-checks the cap at approval: `approve()` re-runs geometry and integrity only (proposals.py:2296-2333).
- **Fix:**
  - Add the notional of OPEN BUY orders (and pending approved proposals) on the book to `_book_open_cost` and to the
    slot count.
  - Re-run `_tip_budget` inside `approve()` for live/paper books.
  - Optionally extend `cash_available` (risk.py:321) to `paper`/`live` books for non-reduce BUYs.

### HIGH 2 - The settled-cash guard (W7.1) is not in effect
- `brokers/ibkr.py:373` reads `SettledCash` only when the row's currency equals `ibkr.cash_currency`.
  `engine.py:529-531` clamps only that currency.
- Evidence: every sync row carries `settledCash: null`, so no clamp ever applied. For the live account,
  `cash_currency=USD` and IBKR reports summary tags in the BASE currency (likely CAD), so it will stay null.
- What remains is `_unsettled_since_sync` (proposals.py:354-375). It only removes sells filled **since the last sync**,
  a window of 60 s or less. After the next sync the sale proceeds sit in `CashBalance` and count as spendable.
- Combined with MEDIUM 2 (summary cash refreshes every few minutes), a same-day sell-then-buy can use unsettled
  proceeds. On a cash account that is a good-faith violation, or IBKR rejects the buy (confirm which with IBKR).
- **Fix:** keep a T+1 ledger of SELL proceeds by trade date (subtract proceeds of sells from the current and previous
  session until they settle) instead of "since last sync". Or read `SettledCash` from `accountValues()` and handle the
  BASE vs per-currency rows explicitly. Journal a warning while `settledCash` is null on a live cash account.

### HIGH 3 - CAD is counted as spendable USD (0.8.61) on a cash account
- `engine.py:522-539` converts **every** currency balance into the book currency and adds it to spendable.
- A cash account may not auto-convert CAD to buy US stock. IBKR then rejects with insufficient funds, or (if
  auto-conversion is enabled on the account) converts at the FX spread. Either way the app sizes against money it
  cannot spend as USD.
- The runbook still says "CAD is not converted" (it was, before 0.8.61).
- **Fix:** for kind=`live` set `ibkr.cash_currency=USD` and count ONLY that currency as spendable (show other
  currencies as information). Convert CAD to USD inside IBKR before the open, as the runbook asks.

### HIGH 4 - A venue GTC stop that IBKR rejects or cancels is silently forgotten; restore never re-checks it
- `execution/positions.py:776-818` (`_ensure_venue_stop`) does not add an exit record and ignores the returned
  `status`.
- `on_order_update` (positions.py:1210-1218 and 1279) handles the venue stop only on FILLED/PARTIALLY_FILLED. With
  `rec` None, a REJECTED/CANCELLED report returns early: no alert, and `venue_stop_order_id` keeps pointing at the dead
  order.
- The next `_ensure_venue_stop` call sees the same price and quantity (positions.py:797-799) and returns without
  re-placing.
- On restart `restore()` only re-registers the id (positions.py:422-423). `IBKRBroker.catch_up` (ibkr.py:159-181)
  re-binds orders it finds but never flags app orders that are missing at IBKR (cancelled while the app was down,
  never reached the gateway, or cancelled by the user in TWS). Those stay ACCEPTED forever.
- Result: an overnight share position the app believes is protected has no stop at IBKR. With the app down or frozen
  (this host froze twice last week) the position is naked through the open.
- **Fix:**
  - On a REJECTED/CANCELLED report for `venue_stop_order_id`: alert, clear the id, and re-place on the next pass.
  - Check `res["status"]` in `_ensure_venue_stop`.
  - After every catch-up, compare each managed position's venue stop with `openTrades()` and re-place any that are
    missing.

### MEDIUM 1 - Reconnect runs the account sync BEFORE the execution catch-up (fills during an outage are counted twice)
- `brokers/ibkr.py:117-119`: `_notify("connected")`, which awaits `sync_ibkr_account()` (engine.py:503-505), runs
  before `catch_up()`.
- Scenario: a fill happens while disconnected (gateway restart, network blip, or app restart).
  - The sync level-sets the position and cash to IBKR's numbers.
  - Then catch-up replays the same execution through `apply_fill`.
  - For a stop that filled: the book shows **-N shares (phantom short)** and the proceeds counted twice.
  - For an entry that filled: 2N shares and the cost counted twice.
  - This lasts until the next sync (60 s).
- During that window RiskGate and the sizing logic read wrong position and cash, and `_close_leg` reads
  `_venue_qty` = -N.
- **Fix:** run `catch_up()` first, then the sync (or sync again right after catch-up).

### MEDIUM 2 - Account-summary cash is stale while positions are real-time
- `account_state` uses `accountSummaryAsync()` (cached subscription; IBKR documents roughly 3-minute updates) for cash,
  and `ib.positions()` (real-time) for positions.
- A sync shortly after a BUY therefore restores the pre-buy cash next to the new position. Cash is overstated by the
  cost for minutes (the day anchor is shifted to hide it), and the next tip's glide sizing uses that cash.
- **Fix:** after any fill, skip the cash level-set until the summary's cash has changed. Or use `reqAccountUpdates` /
  `accountValues`, or compute cash from fills and use the IBKR number only as a drift check.

### MEDIUM 3 - IBKR cancels are asynchronous, but replace and close assume they are instant (brief double sell orders)
- `_ensure_venue_stop` cancels then places immediately (positions.py:801-808): trailing moves, trims, adoption.
- `close()` cancels the venue stop and immediately sends a MKT sell (positions.py:996-1000). On IBKR the cancel only
  takes effect when IBKR confirms it.
- If the stop is triggering while the MKT goes out (likely: a stop exit fires exactly when price is at the stop), both
  can execute. That is a 2N sale against N held.
- `_evaluate_reduce_only` (risk.py:516-545) has no oversell or short check for non-shadow books. A cash account should
  reject the short, but this has not been tested.
- **Fix:** for IBKR, modify the resting stop in place (`placeOrder` with the same `orderId`) instead of cancel/replace.
  On a full close, wait for the cancel to be confirmed (or check the venue position) before the MKT. Add a reduce-only
  guard: qty must not exceed the held quantity minus resting sells, on live/paper books.

### MEDIUM 4 - A mirrored trim on a small share lot raises, and the exception skips the remaining books
- `execution/exits.py:193` truncates to `int(qty)`, so a 0.5-share trim becomes `OrderIntent(qty=0)` and pydantic
  raises. Verified in-process: `ValidationError ... Input should be greater than 0`.
- `_mirror_source_exit` (signals/service.py:2388-2417) loops over every book's position inside a single
  `contextlib.suppress` (service.py:2775). The first raise (for example the 1-share position, live or Practice) aborts
  the mirror for **every later book's** position, silently.
- With a $7k book and $1,000+ names, 1-2 share positions are normal. The same raise hits ladder trims on 1-share lots
  (positions.py:1470 has no whole-unit guard; the option path has one at 1836).
- **Fix:** in `_close_leg`, return None (journaled skip) when the integer quantity is 0. Wrap each position in the
  mirror loop in its own try.

### MEDIUM 5 - The one-share minimum overshoots the budget and the capital room
- `approvals/proposals.py:863` (`qty = max(1, floor(budget/limit))`) and runner.py:364 (`max(1, ...)`).
- When the room is $51-$999 and the share costs more, one share is still bought. Example: $200 room left, a $1,400
  share, 1 share bought, so the cap is exceeded by $1,200.
- The only bound is `max_position_pct` 50% of equity (about $3.5k). Geometry only shrinks the size on risk, never on
  notional.
- **Fix:** refuse when `limit > budget` on live/paper books (or always), journaled `TipLaneDecided lane=refused`.

### MEDIUM 6 - A partially filled entry has no protection until the order completes
- `techniques/tip/lifecycle.py:757-790`: adoption waits for FILLED, a terminal status, or the 4 h deadline.
- Bracket children spawn only on a FULL fill (`orders.py:714`). A partial DAY fill whose remainder rests (the price
  moved up) is unmanaged and has no stop until the remainder fills or the order is cancelled at 16:00.
- Practical exposure is mostly while the position is in profit (a drop back through the limit fills the rest and
  triggers adoption), but halts and gaps are not covered.
- **Fix:** after a partial fill rests longer than about 30-60 s, cancel the remainder and adopt the partial (or adopt
  the partial at once and let scale-in add the rest).

### MEDIUM 7 - `approve()` does not handle `SubmitUncertain`
- `approvals/proposals.py:2333`: `orders.place` raises `SubmitUncertain`. Examples: `placeOrder` raises
  `ConnectionError("Not connected")` after the `connected` check passed (ib_async `client.py:251`), or
  `qualifyContractsAsync` raises mid-await.
- The proposal stays `pending`, with no `order_id` and no adoption task. The order row stays SUBMITTED.
- A later approval path (sweep, a person's click) can submit the same idea again. If the first order did reach IBKR
  and fills, the position is unmanaged: only its bracket children protect it, and the capital cap does not see it.
- **Fix:** catch `SubmitUncertain` in `approve()`. Mark the proposal `executed` (or `uncertain`) with that order id
  and start `adopt_when_filled` on it.

### LOW
- **L1.** Catch-up replays and late commission reports: a fill emitted with commission unknown is stored as 0 and
  never corrected (ibkr.py:329-353; the dedupe blocks a re-emit). P&L is slightly optimistic, about $1 per fill.
- **L2.** `account_state` sums cash and positions across every account the login manages (`reqAccountSummary("All")`,
  ibkr.py:360-385). This is correct only for a single-account login.
- **L3.** `_contract_for` sends `BRK.B`-style symbols unchanged; IBKR wants `BRK B`. Qualification fails and the order
  is rejected (no harm).
- **L4.** IBKR `Inactive` maps to rejected (ibkr.py:293). If IBKR later activates and fills the order, the fill is
  applied to a REJECTED order and adoption already gave up, so only the bracket protects it.
- **L5.** `execution.exit_inflight_ttl_seconds` (900 s): a resting unfilled LMT exit stops counting as in flight after
  15 min. A non-forced exit can then be sent beside it, a potential double sell.
- **L6.** Duplicate engine processes (seen 2026-09-16) would fight over client id 17. The second cannot route (fail
  closed), but it still runs its intake and approval logic against the shared DB.

### Verified OK (no action)
- **Fills are never applied twice in the DB.** `Execution.id` = `ibkr:<execId>` is the primary key; with evidence
  attached, the flush raises before `positions.apply_fill` (orders.py:669-693). The in-memory pre-check race in
  `_emit_fill` is backstopped by that.
- **Reduce-only exits** pass the mode gate, the kill switch (`risk.halt_allows_exits` on), book halts and pauses
  (orders.py:390, risk.py:516-536).
- **The kill switch, per-book halt and per-book pause** are checked on every non-reduce order (risk.py:272-286).
- **The venue stop follows the held quantity** after trims (positions.py:793-799, 1274-1277). The resting stop is
  re-registered on restore.
- **Live and paper books:** an option or spread vehicle is refused on the tip-time proposal path
  (proposals.py:711-715, 1015-1019). The IBKR adapter rejects anything that is not STK.
- **Morning triage skips kind=`live`.** The integrity admission runs on every `via=auto` approval.
- **Missing FX rate:** the sync is skipped and journaled (`IbkrSyncSkipped`), the previous cash stands, and the
  unsettled lookback widens to 2 days (conservative).

---

## Settings to change before go-live

| Setting | Now | Recommend | Why |
|---|---|---|---|
| `.env ZARGAR_IBKR_PORT` | 4002 | 4001 (live gateway) | Restart via ZargarRestart, market closed. |
| Tips live book | only `Tips IBKR Paper` (kind paper) | new book, kind **live**, base USD | B2: kind paper skips the master switch and the confirm dialog. |
| `ibkr.portfolio_id` | paper book | the new live book | Sync target. |
| `techniques.tip.books` | Practice + **paper** binding | Practice + **live** binding only; delete the paper binding | B2 (double routing). |
| live binding `armAtLevel` | true | **false** | B1: armed fires bypass capitalCap, glide, slots and risk sizing. |
| live binding `budgetPerTip` | unset (falls back to $2,000 global / $3,000 common-stock) | ~$750-1,000 | One tip currently takes 67-78% of the $3k cap; this also bounds the H1/M5 overshoot. |
| live binding `riskPct` (or `riskBudgetPerTip`) | unset (global 1% = ~$70) | 0.75-1% (~$50-70) | Explicit per book, not inherited from Practice. |
| live binding `maxOpenPositions` | 5 | 3 | With a ~$1k tip and a $3k cap, 3 is the real number. |
| live binding `capitalCap` | 3000 | 3000 (or the user's chosen limit for the ~$7k account) | Note H1 and M5: the cap is soft today. |
| `ibkr.cash_currency` | CAD | **USD** | H3; convert CAD to USD inside IBKR before the open. |
| `risk.daily_loss_halt_pct` | **15** (global) | 3-5 for the live book | 15% = ~$1,050/day on $7k (runbook promised 3%). It is global: lowering it also halts Practice and Team2/EM sim books sooner. A per-book override is the clean fix (small code change in `engine.check_daily_loss` + `risk.py:498-504`). |
| `risk.max_position_notional` | 25000 | ~3,500 | Global hard cap. Must stay at or above Practice's $3,000 budget. Bounds any single live order. |
| `risk.max_position_pct` | 50 | 35 | 50% of $7k = $3.5k in one name; 35% still fits Practice ($3k of ~$10k). |
| `risk.require_market_hours` | false | true (applies to live/paper books only) | No pre-market DAY LMTs queued at a pre-market ask into the open on day 1. Exits are exempt. |
| `techniques.tip.max_name_exposure_pct` | 0 | ~40 (optional) | Two sources tipping the same name stack on the live book. |
| `techniques.tip.allow_live_auto` | false (default) | true **only after** the items above | The master switch also enables live armed fires (B1). |
| `trading.mode` | live | live | Already on; it routes every paper/live non-SnapTrade book to IBKR (B2). |
| Book `Live (IBKR)` 2d173f44 | active, kind live | archive | Any order on it would go to the real account. |

Process: before switching to live, run the runbook's paper checks (at least one entry, one exit, a visible venue stop,
one reconnect). The adapter has zero real executions so far.
