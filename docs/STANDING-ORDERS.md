# Standing orders (built 2026-11-14, v0.9.50)

The user's own order plans, executed by the app after **the user** arms them. First use: the ANT IPO week
(test sells/buys Mon 2026-11-16 on Webull + Wealthsimple; ANT buys Thu 2026-11-19, +10% take profit / -10% stop).

## Who does what
| Step | Who |
|---|---|
| Say the plan in plain words ("sell all SPCX on Webull, buy ANT with everything when it lists, TP +10 / SL -10") | user |
| Size and split it across accounts, draft every order as ONE plan (`POST /api/standing/plan`) | Claude |
| Review on **Standing orders** page, press **Arm plan** (one click + confirm) | user |
| Real-money books only: the switch **Allow armed standing orders to trade real accounts** (`execution.standing_orders.allow_live`) | user, once |
| Trigger, price, route, re-price, fill, exits | the app |
| Watch, diagnose, push the user, fix app bugs, draft corrected orders | Claude |

Claude never flips `allow_live` and never submits a real-money order outside a standing order. Claude arms orders only while the user's **delegation** is active (below); otherwise the user arms.

## Order fields
`portfolioId, symbol, side` (BUY/SELL), `qty` **or** `budget` (buys: whole shares that fit), `trigger`
(`now` | `at` + `notBefore` "HH:MM" ET | `listing` = a new issue's first regular-session prints), `expiresOn`
(ET date; unfilled after it = expired), `maxPrice` (buy cap) / `minPrice` (sell floor), `slippagePct`
(limit = ask x (1+s) / bid x (1-s), default 0.5), buys: `takeProfitPct`, `stopLossPct`.

## Execution (zargar/execution/standing.py)
- Every `execution.standing_orders.poll_seconds` (5 s) during 09:30-16:00 ET with a fresh two-sided quote.
- Always a DAY **limit** order through `OrderManager.place` (RiskGate inside; the kill switch blocks buys; sells
  are `reduce_only`). Source `standing`, tag `standing:<id>`.
- Write-ahead: the row is `placing` before the call; after a crash it is reconciled from the tagged order, never
  re-sent.
- Unfilled after `fill_wait_seconds` (60) -> cancelled -> re-priced next tick, up to `max_attempts` (5).
- Refusals keep the venue's reason in `lastError`, are journaled (`StandingOrder` stage `refused`) and pushed.
- A filled buy with exits is adopted by the position manager: fixed stop at avg x (1 - SL), one full-size
  target at avg x (1 + TP), judged on 5m bars; the stop also rests at the venue as a GTC order where the venue
  accepts one (`overnight=venue_stop`).

## Known limits / to verify on the first real orders
- SnapTrade stop orders on Webull CA / Wealthsimple are untested - if a venue refuses the GTC stop, the position
  is app-managed (needs the app running) and the manager raises an attention alert.
- A brand-new symbol may not resolve at SnapTrade for a while after it lists (ANT).
- RiskGate caps apply to real books too (`risk.max_position_pct` 50% of a book's equity, `risk.price_collar_pct`
  5%): a budget that breaches them is refused - use **preflight** on the page before arming.
- Cash by currency is not checked by the app before sending; the broker's refusal comes back as `lastError`.
- **IBKR refuses API orders on Canadian listings** (Error 201 "API/CTCI orders for Canadian products are not allowed",
  status Inactive; XIU.TO 2026-11-16). Use US listings at IBKR from Zargar. IBKR live U27762724 holds CAD only - a US
  buy needs USD there first.
- **Wealthsimple has two books named "Wealthsimple Trade (Personal)"**: c7134b99 (CAD, holds the TQQQ) and 2b821772
  (the USD sub-account - SnapTrade 400 "Account has been archived or closed"). Draft on c7134b99.
- **50% `risk.max_position_pct`** refuses a buy that takes one name past half the book (TQQQ buy-back on Wealthsimple,
  2026-11-16; an all-in ANT buy) - changing the cap is the user's decision.
- **App equity reads below the broker** (Webull -17%, Wealthsimple -32%, `BrokerSyncMismatch` 2026-11-16) - the % caps
  are judged on the lower number. Open fix.
- Fixed 2026-11-16: Yahoo 429s starved Yahoo-only symbols (0.9.53); a due order on a Yahoo-only quote fetches a fresh one
  (0.9.54); **a standing SELL is capped at the whole shares held and fails before any venue contact when there are none**
  (0.9.55 - before it a sell with no shares reached IBKR; on a US name it could have opened a short).
- First real fills 2026-11-16: Webull SELL 1 SPCX @ 139.03 (09:45), BUY 1 AAPL @ 353.99 (10:00) - each filled within
  seconds of the first limit; Zargar positions matched.

## Delegated arming (2026-11-16, user decision)
The user switches it on from **Standing orders -> Delegate arming** (accounts, window up to 31 days, max per buy, max
total buys, explicit confirm; phrase `I DELEGATE ARMING`). While it is active Claude may arm plans itself with the
confirm `DELEGATED <id[:8]>` - the user's chat plans, repairs of failed orders, and Scout ideas ("i can tell you to
listen to scout and you do the trading"). The APP enforces on every delegated arm: the delegation is active (not
revoked/expired), the account is covered, the order expires inside the window, a buy has a budget or a max price, the
buy's bound is within the per-order cap, and everything armed under the delegation stays within the total cap (open
orders count at their bound, finished ones at filled notional; a plan is checked as a whole, all or nothing). Each
delegated arm is stamped `armedBy=claude:delegation:<id>`, journaled and pushed to the user. Revoke stops new
delegated arms (working orders carry on). Never under delegation: `allow_live`, risk caps, kill switch, cash/FX,
account links. Rows: `standing_delegations`.
