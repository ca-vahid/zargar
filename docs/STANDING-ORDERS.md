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

Claude never arms an order, never flips `allow_live`, and never submits a real-money order itself.

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
- IBKR live is not connected (the gateway on 4002 is the paper account).
