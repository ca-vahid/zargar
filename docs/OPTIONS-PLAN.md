# Options trading — research findings & build plan

Status: **research done 2026-08-21; phases 0-5 built the same day (see §3).** This document is the
single source of truth for the options feature: what SnapTrade actually
supports for our Canadian brokers (verified against the real connections, not
just the docs), the design decisions that follow, and the phased build order.

Companion docs: `ARCHITECTURE.md` (engine), `techniques/enhanced-market/METHOD.md` §6
(module T5 — the option *selection* rules the technique pipeline already
implements), `techniques/enhanced-market/PIPELINE-PLAN.md` §4 (CBOE chain provider).

---

## 1. Research findings (verified 2026-08-21)

### 1.1 Can we trade options through SnapTrade from Canada? — **Yes, on Webull Canada. Not on Wealthsimple.**

Evidence comes from a **read-only probe against your real connections**
(`python -m zargar.tools.snaptrade_options_check`), which calls SnapTrade's
option-order *impact* endpoint — a broker-side simulation that places nothing:

| Account | `POST /accounts/{id}/trading/options/impact` (1× `F 260828C00014500` BUY_TO_OPEN, LIMIT 0.20) | Verdict |
|---|---|---|
| Webull Canada · **CASH** | `200` → `{estimated_cash_change: "21.04", cash_change_direction: "DEBIT", estimated_fee_total: "1.04"}` | ✅ **options trading works** |
| Webull Canada · **MARGIN** | `200` → same | ✅ works |
| Wealthsimple · PERSONAL (CAD, open) | `400` code **1156** `"Option Trade impact is not supported for this brokerage."` | ❌ not supported |
| Wealthsimple · PERSONAL (USD, closed) / CORPORATE (closed) | same 1156 | ❌ |

So the two-broker split is: **Webull CA = options venue**, **Wealthsimple =
equities only** (option *positions* there would still sync read-only, see
§1.4). The fee the broker returned ($1.04 on a $20 premium) matches Webull
Canada's published **$0.99 USD/contract** + regulatory fees; options on Webull
CA are **US-listed only** and require the options application to be approved in
the Webull app (it evidently is — the impact call succeeded on both accounts).

We could not load SnapTrade's Notion-hosted brokerage support matrix
(`support.snaptrade.com/brokerages` returns "page couldn't be found" to a
headless browser); the empirical probe above is more authoritative anyway.

### 1.2 The SnapTrade options API surface

| Purpose | Endpoint | Notes |
|---|---|---|
| **Place** single- or multi-leg option order | `POST /api/v1/accounts/{accountId}/trading/options` (`Trading_placeMlegOrder`) | Single-leg = one leg. Body: `order_type` ∈ `MARKET\|LIMIT\|STOP_LOSS_MARKET\|STOP_LOSS_LIMIT`, `time_in_force` ∈ `Day\|GTC\|FOK\|IOC`, `limit_price`/`stop_price` as **decimal strings**, `price_effect` ∈ `CREDIT\|DEBIT\|EVEN`, `legs[]` = `{instrument: {symbol: <OCC>, instrument_type: "OPTION"}, action: BUY_TO_OPEN\|BUY_TO_CLOSE\|SELL_TO_OPEN\|SELL_TO_CLOSE, units: <contracts>}`. Response `{brokerage_order_id, orders: [AccountOrderRecord…]}`. |
| **Preview** (fees, cash effect) | `POST /api/v1/accounts/{accountId}/trading/options/impact` (BETA) | Same body; response `{estimated_cash_change, cash_change_direction, estimated_fee_total}` (strings). Verified live — this is our capability probe *and* the ticket's "verify with broker" for options. |
| Cancel | `POST /api/v1/accounts/{accountId}/trading/cancel` `{brokerage_order_id}` | Same as equities (assumed — verify on the first supervised order). |
| Order status / fills | `GET /api/v1/accounts/{accountId}/recentOrders` | Option rows carry `option_symbol: {ticker: "<OCC padded>", option_type: CALL\|PUT, strike_price, expiration_date, underlying_symbol}` and `universal_symbol: null`; `action` ∈ `BUY_OPEN\|BUY_CLOSE\|SELL_OPEN\|SELL_CLOSE`; `execution_price` is **per share**, `filled_quantity` in **contracts**. ⚠ docs say `only_executed` defaults to `true` — the existing equity poller passes nothing; verify whether working/cancelled orders are visible and pass `only_executed=false` if not (pre-existing gap, affects equities too). |
| Positions | `GET /api/v1/accounts/{accountId}/positions/all` | Options appear as `instrument.kind == "option"` with `option_type`, `strike_price`, `expiration_date`, `underlying`. `extract_unified_position` already maps this to `secType: "OPT"`; the OCC symbol needs normalising (§2.1). The legacy `/optionsHoldings` endpoint returns **404** on these accounts — don't use it. |
| Chain / option quotes via SnapTrade | `GET /accounts/{id}/optionsChain`, `GET /accounts/{id}/quotes/options` | **Unavailable to personal keys** (`401 Please provide clientId, userId and userSecret`), and the quotes one is deprecated (sunset 2026-10-01). Chains and option quotes therefore come from outside SnapTrade (§1.3). |

OCC symbology as SnapTrade wants it in order legs: **21 chars, root padded with
spaces to 6**, `yymmdd`, `C`/`P`, strike×1000 zero-padded to 8 — e.g.
`"F     260828C00014500"`, `"AAPL  251114C00240000"`.

Multi-leg (spreads) is supported by the endpoint itself; whether Webull CA
accepts it is untested (the impact endpoint can probe it with two legs before
we build the UI). Brokerages report each leg as a separate order record.

### 1.3 Market data for options (outside SnapTrade)

| Need | Source | Verified |
|---|---|---|
| Chain (all expiries, strikes, bid/ask/last, volume, OI, **greeks + IV**) | **CBOE delayed JSON** `cdn.cboe.com/api/global/delayed_quotes/options/{SYM}.json` — free, no auth, ~15-min delayed, US listings only. Already wrapped in `technique/options.py::CboeClient` with a 60 s cache. | ✅ live (F, SPY) |
| Live last price + 1m bars for one contract | **Yahoo v8 chart** `…/v8/finance/chart/F260828C00014500` — returns `instrumentType: OPTION`, `regularMarketPrice`, 390 live 1m bars, `chartPreviousClose`. Same endpoint `YahooQuoteFeed` already polls, so option symbols can flow through the existing feed. No bid/ask. | ✅ live |
| Yahoo v7 options chain | needs a crumb (`401 Invalid Crumb`) | ✗ skip |
| Real-time option bid/ask with greeks | IBKR (`reqSecDefOptParams` + market data) once the account activates; Tradier if a US-address token ever exists | later |

Design consequence: an option **Quote** in the `QuoteCache` is a merge —
`last`/bars live from Yahoo, `bid`/`ask`/greeks from CBOE (delayed, refreshed
each poll of the underlying's chain) — and is flagged so the UI says so.

### 1.4 What already exists in the codebase

- `SecType.OPT`, `Order.sec_type`, `Position.sec_type` (100× multiplier in
  `PositionKeeper`, P&L and cash math already contract-aware).
- `RiskGate`: `options_allowed`, `option_premium_cap` (% equity),
  `no_naked_short_option`; tests in `test_riskgate.py`.
- `technique/options.py`: CBOE + Tradier providers, `parse_occ`, T5 contract
  selection (`pick_for_setup`) and the `/api/technique/options/{symbol}` route;
  `TechniqueSetup.options` stores the pick.
- `SnapTradeSync` already classifies `kind == "option"` positions as `OPT`.
- Settings: `risk.allow_options`, `risk.max_option_premium_pct`,
  `technique.options.*`.

Nothing routes an OPT order to a broker yet, the UI has no chain/ticket, and
the SnapTrade executor only knows `/trade/place` (equities).

---

## 2. Design decisions

### 2.1 One canonical option symbol: **unpadded OCC**

Internal symbol for an option = OCC **without** root padding, e.g.
`F260828C00014500`, `AAPL251114C00240000`. Reasons: it is what CBOE and Yahoo
use natively (so the quote feed, chain and bars need no translation), it is a
valid Postgres/JSON key without embedded spaces, and it is already what
`technique/options.py` emits. A tiny `zargar/options/occ.py` owns:

- `parse(sym) -> Occ(underlying, expiry: date, right: "C"|"P", strike: float)`
  (accepts padded or unpadded, upper-cases, validates date/strike);
- `to_snaptrade(sym)` → padded 21-char form for `legs[].instrument.symbol`;
- `from_snaptrade(ticker)` → unpadded (used by the poller and position sync);
- `display(sym)` → `"F 28 Aug 26 14.5 C"`, plus `short()` for table cells;
- `dte(sym, today)`, `is_expired`, `multiplier` (100; mini options flagged by
  SnapTrade's `is_mini_option` are **rejected**, not mis-sized).

`currency_for_symbol` stays USD for OCC symbols (Webull CA options are US
only; `.TO` underlyings have no chain). `sec_type` = `"OPT"` travels alongside
as today; the symbol alone is never sniffed to decide sec_type.

### 2.2 Open/close is derived, never typed

The UI exposes BUY/SELL and contracts; the engine derives the SnapTrade
action from the current position in that portfolio:

| side | position before | action |
|---|---|---|
| BUY | ≥ 0 | `BUY_TO_OPEN` |
| BUY | < 0 | `BUY_TO_CLOSE` (qty ≤ |pos|, else split is rejected) |
| SELL | > 0 | `SELL_TO_CLOSE` (qty ≤ pos) |
| SELL | ≤ 0 | `SELL_TO_OPEN` → blocked by `no_naked_short_option` (covered calls are a later, explicit rule) |

`price_effect` follows: BUY → `DEBIT`, SELL → `CREDIT` (single-leg). The
derived action is journaled on `OrderIntentCreated` and shown in the confirm
dialog.

### 2.3 Venue capability is a gate, not an assumption

A per-brokerage allowlist `snaptrade.options_brokers` (default
`["Webull Canada"]`) plus a live probe: the Options ticket's "verify with
broker" calls the options impact endpoint and caches the verdict per account
(`supported` / `unsupported:1156` / `unknown`) for the session. Wealthsimple
accounts are shown as "options: not supported via SnapTrade" and the submit
button is disabled for OPT on them — we never discover unsupport by
submitting a real order.

### 2.4 Risk gate additions (all journaled, all settings-driven)

Existing: `options_allowed`, `option_premium_cap` (% equity), `no_naked_short_option`.
New checks for `sec_type == "OPT"`:

| check | default | behaviour |
|---|---|---|
| `option_not_expired` | — | DTE < 0 → reject; DTE == 0 → allowed only if `risk.allow_0dte` |
| `option_max_contracts` | `risk.max_option_contracts = 10` | per order |
| `option_premium_cap_abs` | `risk.max_option_premium_notional = 1000` | $ per order (qty × price × 100) |
| `option_spread` | `risk.max_option_spread_pct = 10` | (ask−bid)/mid from the CBOE-enriched quote; **MKT orders on wide spreads are rejected**, LMT only warned |
| `option_liquidity` | `risk.min_option_open_interest = 100` | warning-only check (`passed=true`, detail carries the warning) unless `risk.block_illiquid_options` |
| `market_hours` | — | options have no extended session: for OPT, `require_market_hours` is **forced on** for live portfolios (09:30–16:00 ET; index options excluded for now) |
| `quote_fresh` | — | the freshness clock uses the Yahoo last (live), not the CBOE timestamp |

Closing orders bypass the notional/contract caps exactly as reducing equity
orders do today.

### 2.5 Module layout

New package `backend/zargar/options/` (engine-level, not technique-level —
the technique pipeline becomes a consumer):

| Module | Responsibility |
|---|---|
| `occ.py` | symbology (§2.1) |
| `chain.py` | `ChainService`: CBOE (default) / Tradier / later IBKR providers moved here from `technique/options.py` (which keeps only T5 selection and imports from here); expiries, strike ladder rows, per-contract snapshot, spot; per-underlying cache (60 s); `enrich_quote()` that writes bid/ask/greeks onto the `QuoteCache` entry of an OCC symbol |
| `service.py` | `OptionsService`: chain API, contract quote subscription (`ensure_symbol` for OCC → Yahoo watch + chain enrichment loop), capability cache, impact passthrough, expiry housekeeping (mark expired positions, journal `OptionExpired`) |
| `api/routes_options.py` | REST (§2.7); ⚠ no `from __future__ import annotations` |

Executor changes live in `brokers/snaptrade.py` (`submit` branches on
`sec_type`), `brokers/sim.py` (per-contract commission, fills on the
enriched quote) and later `brokers/ibkr.py` (`Option(...)` contracts).

### 2.6 Data model

No new tables for single-leg. `Order`/`Position`/`Execution` already carry
`sec_type`; underlying/expiry/strike/right are derived from the symbol on
read (`order_dict` gains an `option: {underlying, expiry, strike, right, dte}`
block when `secType == "OPT"`, same for positions). Multi-leg (phase 6) adds
`Order.legs` JSON + `group_id`; schema changes wait for alembic (ROADMAP v0.2).

### 2.7 API (camelCase wire)

| Route | Returns |
|---|---|
| `GET /api/options/{underlying}/expiries` | `{underlying, spot, expiries: [{date, dte, is0dte}], provider, delayed}` |
| `GET /api/options/{underlying}/chain?expiry=YYYY-MM-DD` | strike ladder: `[{strike, call: {symbol, bid, ask, last, volume, openInterest, iv, delta, theta, gamma, vega, inTheMoney}, put: {…}}]` + `spot`, `asOf` |
| `GET /api/options/quote/{occ}` | one contract snapshot (merged Yahoo/CBOE) + `display` |
| `POST /api/options/impact` | `{portfolio_id, symbol, side, qty, order_type, limit_price}` → broker preview `{estimatedCashChange, direction, estimatedFees}` or `{error, code}`; also updates the capability cache |
| `GET /api/options/capabilities` | per brokerage account: `{supported: true\|false\|null, checkedAt, detail}` |
| `POST /api/orders` | unchanged route; `sec_type: "OPT"` + OCC symbol; response carries the derived `action` |
| WS | OCC symbols ride the existing `quotes` topic (conflated); `watch` works for them |

### 2.8 UI

- **New page `Options`** (sidebar + route `/options`, deep link
  `/options/SPY` and `/options/SPY/2026-08-28`): underlying search/quote
  header → expiry strip (DTE, weekly/monthly, 0DTE badge) → **strike ladder**
  (calls | strike | puts, centred on ATM, ITM shading, columns bid/ask/last/
  vol/OI/IV/Δ, delayed-data badge) → click a cell opens the **option ticket**.
- **Option ticket** (sibling of `OrderTicket`, shares `AccountSelect`,
  `ConfirmOrderDialog`): BUY/SELL, contracts, LMT default at mid (MKT allowed
  with the spread warning), TIF DAY/GTC, account (Webull CA accounts first;
  Wealthsimple disabled with the reason), derived open/close shown, cost =
  price × 100 × qty, fee estimate ($0.99/contract, editable `fees.webull_option_per_contract`),
  FX note reusing `lib/fees.ts`, greeks/IV/OI/DTE strip, **breakeven, max
  loss** (debit), T5 warnings when the pick came from the technique pipeline,
  "verify with broker" → `/api/options/impact`, dry run, and the real-money
  confirm dialog (pre-flight dry run, same as equities).
- **Blotter/positions**: OPT rows render `display()` (not the raw OCC), DTE,
  grouped under the underlying with a subtotal; row click → Options page with
  the ticket prefilled to close. Expired contracts grey out.
- **Dashboard**: options exposure tile (premium at risk, expiring ≤ 2 d).
- **Technique page**: the T5 contract card gets **"Trade this contract"** →
  Options page, ticket prefilled (practice by default).
- **Settings → Options**: every `risk.*option*` knob, `options.provider`,
  `snaptrade.options_brokers`, fee per contract, 0DTE toggle.
- Watchlists accept OCC symbols; `WatchRow` shows `short()`.

### 2.9 Practice rung

`SimExecutor` fills OPT orders against the enriched quote (opposite touch +
slippage as today; bid/ask from CBOE so practice fills are pessimistic by
construction) with a per-contract commission; shadow portfolios unaffected.
The whole Options page works in `practice` mode before any real order.

---

## 3. Build order

| Phase | Scope | Gate to move on |
|---|---|---|
| **0 — Probe** ✅ | `tools/snaptrade_options_check.py` (read-only: brokerage catalogue, option positions, impact per account) | done 2026-08-21 — Webull CA ✅ / Wealthsimple ❌ |
| **1 — Symbology & data** ✅ | `options/occ.py`, `options/chain.py` (providers moved out of `technique/options.py`, which re-exports), `QuoteCache.set_overlay`, Yahoo feed carries OCC symbols, `OptionsService` (chain/ladder/contract snapshot, quote enrichment, capability cache, expiry settlement) wired into `Engine`, `/api/options/*` routes | ✅ `tests/test_options_occ.py`, `tests/test_options_service.py` (20 tests) — live SPY chain verified in the running app |
| **2 — Practice trading + UI** ✅ | risk-gate option checks (`option_symbol`, `option_not_expired`/0DTE, `option_max_contracts`, `option_premium_notional`, `option_spread`, option price collar vs mid, market hours forced for OPT on live), derived open/close (`derive_option_action`, close-qty guard), sim fills + per-contract commission, **Options page** (`/options/SPY`, `/options/SPY/<expiry>`, `/options/c/<OCC>` deep links), strike ladder, option ticket (greeks strip, derived action, fees, max loss, breakeven, FX note, broker preview, dry run, confirm dialog), blotter/watchlist rendering of contracts, Settings → Options panel | ✅ verified in-app: buy 1× SPY 0DTE call in practice → filled → position row → click → SELL TO CLOSE prefilled. Dashboard tile not built (blotter DTE badges cover it) |
| **3 — SnapTrade live, single-leg (Webull CA)** ✅ code | `SnapTradeBroker.submit` OPT branch (`/trading/options`, padded OCC, action, `price_effect`, string prices), poll/reconcile on `option_symbol.ticker`, `option_impact`, capability gate (`OrderManager.option_gate` ← `OptionsService.allows_options`, allowlist `snaptrade.options_brokers` + live 1156 verdicts journaled as `BrokerCapabilityChecked`), option position parsing from `/positions/all`, `recentOrders?only_executed=false` (param accepted — verified live, read-only), client query-param signing | ✅ `tests/test_snaptrade_options.py` (9 tests incl. a two-broker engine test). **Still to do: the supervised first real trade** — LIVE mode, Webull CASH, 1× cheap liquid call, LMT, confirm dialog → `OrderSubmitted → BrokerOrderLinked → OrderAccepted → OrderFill(ed)` in the Journal; close it the same way |
| **4 — Lifecycle** ◐ | practice/shadow contracts cash-settle at intrinsic on expiry (`OptionExpired` journaled, 60 s loop); live contracts show DTE/expired badges and rely on the brokerage sync (`PositionReconciled`) — explicit assignment detection (stock appears as the contract vanishes) is **not** built; the real option position row shape from SnapTrade is unverified until a contract is actually held | hold one contract through expiry on Webull and check the sync |
| **5 — Technique hand-off** ◐ | T5 pick card → **"trade this contract →"** opens the ticket prefilled (practice by default) | OPT proposals via `technique.emit_proposals` + Telegram card: not built |
| **6 — Multi-leg** ☐ | **Probe passed 2026-08-21**: a 2-leg F debit call spread (`BUY_TO_OPEN 14.5C / SELL_TO_OPEN 15C`, LIMIT 0.10) previews on Webull CASH → `DEBIT 12.08, fees 2.08` — the venue accepts spreads. Build: `Order.legs` (alembic), vertical ticket, risk on net debit/credit + defined max loss, poller grouping of per-leg records | behind a feature flag |
| **7 — IBKR options** ☐ | `Option(...)` contracts, `reqSecDefOptParams` chain provider, real-time greeks | when the IBKR account activates |

Rough effort: phase 1 ≈ 1 day, phase 2 ≈ 2–3 days (UI-heavy), phase 3 ≈ 1 day
+ the supervised trade, phase 4 ≈ ½–1 day. Phases 5–7 are independent.

---

## 4. Hard rules carried over (non-negotiable)

- Every option order goes through `RiskGate.evaluate()`; the capability gate
  (§2.3) sits *after* it, before routing, like the bracket check today.
- Write-ahead intent + journal before `submit()`; unknown submit outcome →
  reconcile on `recentOrders` by `client_order_id` / `option_symbol.ticker`,
  never resubmit. Deterministic exec ids (`exec_id_for`) unchanged.
- Dry runs don't consume the rate/duplicate budget (confirm-dialog pre-flight).
- Real-money confirm dialog on `kind === "live"` only; options add the derived
  action, max loss and DTE to the headline.
- New knobs in `settings_service.DEFAULTS`; wire format camelCase.

---

## 5. Open questions / risks

1. **Wealthsimple**: SnapTrade code 1156 today. Re-run the probe monthly; if it
   flips, only the allowlist changes.
2. **Webull Canada integration is `release_stage: BETA`** at SnapTrade — expect
   occasional field-shape surprises; the executor must log and reject on
   unknown shapes rather than guess.
3. **`recentOrders` `only_executed`** — the poller now passes
   `only_executed=false` (accepted by the API, verified read-only on Webull
   CASH; the account had no recent orders so visibility of working rows is
   still to be confirmed on the first supervised order).
4. **Quote quality**: bid/ask are 15-min delayed (CBOE) while last is live
   (Yahoo). MKT orders are therefore discouraged by the risk gate; the broker
   preview is the user's real-time sanity check until IBKR.
5. **FX**: options settle in USD; a CAD Webull account auto-converts at ~1.5%
   unless the USD wallet covers it — the existing fee/FX note logic already
   handles this once `currency_for_symbol` says USD for OCC symbols.
6. **Expiry/assignment**: SnapTrade surfaces outcomes only through the next
   positions sync (overnight holdings sync); phase 4 makes this explicit rather
   than silently dropping a position.
7. **Multi-leg on Webull CA**: preview verified (see phase 6) — only the
   app-side build remains.
8. **Index/cash-settled options** (SPX, XSP) and mini options are out of scope;
   the symbology layer rejects `is_mini_option` rows.
