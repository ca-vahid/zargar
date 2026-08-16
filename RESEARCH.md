# Zargar — Comprehensive Research

*Research date: August 2026. Compiled from three parallel research tracks: (1) the IBKR API landscape, (2) app architecture / charting / mock-mode patterns, (3) signal ingestion and automation safety.*

---

## 0. Executive summary — the recommended blueprint

| Decision | Recommendation |
|---|---|
| **Broker connectivity** | TWS API via **IB Gateway** in the maintained [gnzsnz/ib-gateway-docker](https://github.com/gnzsnz/ib-gateway-docker) container (IBC auto-login, one 2FA per week), driven by **[ib_async](https://github.com/ib-api-reloaded/ib_async)** (the maintained successor to ib_insync). Prototype the headless **OAuth 1.0a Web API via [IBind](https://github.com/Voyz/ibind)** in parallel as a no-2FA fallback path. |
| **Stack** | Python asyncio **trading engine daemon** (ib_async + FastAPI WebSocket) running 24/7 next to the gateway; **Vite + React + TypeScript** SPA frontend with Zustand; localhost/Tailscale + static bearer token for single-user auth. No Next.js, no Electron (Tauri wrapper optional later). |
| **Charting** | **Highcharts Stock** with the new official **`@highcharts/react`** wrapper; imperative updates via chart ref (bars, not raw ticks). ⚠️ Verify the purchased license is **Stock or Suite**, not Core-only — candlesticks/indicators/Stock Tools live in the Stock SKU. |
| **Mock mode** | Four-tier ladder sharing one order interface: dry-run → **local fill simulator against live quotes** → always-on **shadow portfolios** ("what would have happened") → IBKR paper account for end-to-end API rehearsal. |
| **Signal ingestion** | **Email is the universal bus** — re-subscribe newsletters to a dedicated address on a custom domain via **Cloudflare Email Routing + Workers** (free, webhook-native). Do **not** ingest from the corporate Microsoft 365 mailbox. |
| **Extraction** | Claude API structured outputs (`messages.parse()` + Pydantic schema) with **quote-grounding** (verbatim evidence snippets verified in code), explicit no-signal path, and confidence tiers. The LLM proposes; deterministic code disposes. |
| **Verification** | IBKR itself (contract lookup, live snapshot, spread/halt) + **Finnhub free tier** (earnings calendar, news corroboration). Price-deviation, liquidity/ADV, and halt checks before any proposal. |
| **Approval** | Pending-order queue with TTL + push notification with approve/reject action buttons (**ntfy.sh** or **Telegram bot**). Graduate per-source to rules-gated auto-execution with hard caps; kill switch at every layer. |
| **Persistence** | **SQLite (WAL)** with an **event-sourced append-only journal** as source of truth; projections for positions/P&L; Litestream for offsite backup. |

---

## 1. IBKR API landscape

IBKR exposes three programmatic surfaces as of 2025–2026: the **TWS API** (socket protocol into TWS or IB Gateway), the **Web API** (evolution of the Client Portal Web API — REST + WebSocket, with OAuth for gateway-less access), and **FIX CTCI** (institutional; minimum monthly commissions; orders only — skip it). IBKR is consolidating its web products into one Web API accessible via OAuth 2.0 ([Web API docs](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/)).

### 1a. TWS API (via TWS or IB Gateway) — the primary path

- **Capabilities:** the most complete API — full order-type catalog, streaming L1/L2 market data, historical data, account/portfolio updates, scanners, executions ([TWS API docs](https://www.interactivebrokers.com/docs/tws-api/doc/)).
- **Auth model:** no tokens. The app opens a plain TCP socket to a locally running TWS/IB Gateway that was logged in with username/password + 2FA. The socket is unauthenticated and **unencrypted** — keep it on localhost/private network.
- **Session constraints:**
  - One active login per username across all IBKR platforms — logging in elsewhere kicks the session. Standard fix: create a **second username** on the same account dedicated to the API ([multiple sessions](https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions)).
  - Gateway must restart daily. With **auto-restart** enabled, full 2FA is needed only **once per week** (session credentials expire ~01:00 ET Sunday) ([auto-restart considerations](https://www.ibkrguides.com/traderworkstation/auto-restart-considerations.htm), [IBC user guide](https://github.com/IbcAlpha/IBC/blob/master/userguide.md)).
- **Headless/always-on:** yes in practice — IB Gateway + IBC under Xvfb, packaged by [gnzsnz/ib-gateway-docker](https://github.com/gnzsnz/ib-gateway-docker) (env-var config, 2FA-timeout retry actions, VNC/SSH debug, live+paper in one container, ARM support). Schedule the restart inside IBKR's maintenance window (**23:45–00:45 ET**).
- **Rate limits:** max **50 messages/sec** client→TWS by default (= market data lines ÷ 2); historical data has its own pacing rules (≤60 requests/10 min, no identical request within 15 s, BID_ASK counts double) ([pacing limitations](https://www.interactivebrokers.com/docs/tws-api/doc/pacing-limitations/introduction), [historical limitations](https://interactivebrokers.github.io/tws-api/historical_limitations.html)).
- **Quirks:** nightly restart gap, weekly 2FA, occasional GUI dialogs (IBC handles most), competing-login kicks.

### 1b. Client Portal Web API / IBKR Web API

- REST + WebSocket: orders (incl. brackets/OCA), positions, PnL, top-of-book data. Narrower than TWS API; order placement has a server-side confirmation question/`/reply` dance.
- **Auth flavors:**
  1. **Client Portal Gateway** (retail-documented): local Java program, interactive browser login + 2FA, session needs `/tickle` every ≤5 min and a fresh interactive login roughly daily — the pain [IBeam](https://github.com/Voyz/ibeam) automates with headless-Chrome credential entry (works, but fragile by nature).
  2. **OAuth 1.0a first-party ("Web API 1.0")**: self-service key registration → call the Web API **with no local gateway and no 2FA at all**. Officially aimed at institutions but demonstrably works for individual accounts (live and paper); keys activate after a weekend restart ([IBind wiki](https://github.com/Voyz/ibind/wiki/OAuth-1.0a)). The only truly headless official-ish path today.
  3. **OAuth 2.0**: institutional only; for individuals "being considered, no ETA" — the fastest-moving piece; re-check periodically.
- **Rate limits:** 10 req/s via CP Gateway; 50 req/s per username via OAuth. Streaming concurrency is low (community reports ~5 simultaneous tickers) — fine for order entry, weak for a quote wall.

### 1c. Recommendation

**Primary:** IB Gateway (paper first) in gnzsnz/ib-gateway-docker + **ib_async**, with a dedicated second API username. **Parallel prototype:** OAuth 1.0a via IBind for a zero-2FA fallback and as a hedge on the Web API becoming the long-term winner. **Skip FIX.**

### 1d. Client libraries

| Library | Layer | Status (Aug 2026) | Verdict |
|---|---|---|---|
| Official `ibapi` | TWS | Maintained by IBKR but **PyPI package is stale (2020)** — real releases ship from IBKR's site; community mirrors exist | Low-level; beware `pip install ibapi` |
| **ib_async** | TWS | Active successor to ib_insync (ib-api-reloaded org); IBKR's own docs point migrants here; ships a connection `Watchdog` | **Recommended (Python)** |
| @stoqey/ib | TWS (Node/TS) | Active-ish port of the Java client | The Node option; smaller community |
| **IBind** | Web API | Active; supports headless OAuth 1.0a and gateway mode; automates the order question/reply dance | Best CP-API client |
| IBeam | CP Gateway auth | Active; headless-Chrome login automation | Works; prefer OAuth 1.0a if obtainable |
| IBC | Gateway automation | Canonical auto-login/restart controller (inside the docker image) | Essential |

### 1e. Account settings checklist (gotchas)

- TWS/Gateway Global Configuration → API → Settings: **Enable ActiveX and Socket Clients**, uncheck **Read-Only API**, set **Trusted IPs** (headless can't answer the connection prompt), check **Download open orders on connection**; raise the "precautionary settings" (order size/price sanity limits) that otherwise silently reject bot orders.
- TWS API order IDs must be monotonically increasing per clientId, seeded from `nextValidId` (ib_async manages this); persist and reconcile on reconnect.
- A dropped socket after submit does **not** mean the order didn't reach the broker — "unknown outcome" must default to *check, don't resend* (`reqAllOpenOrders`, executions carry `orderRef` back).
- Market data subscriptions are **per-username** — the API username needs its own (or the paper-sharing toggle).

---

## 2. Paper trading & mock mode

### 2a. IBKR paper account

- Every IBKR Pro account can request one paper account (its own username). Works with both APIs; conventional ports 7497 (TWS paper) / 4002 (Gateway paper).
- Delayed data by default; a Client Portal toggle shares real-time subscriptions with paper — but then live and paper usernames **can't consume data simultaneously**.
- **Fill simulation is simplistic:** top-of-book only, no market impact, some order types unsupported, community reports of better-than-limit fills. Use paper for **plumbing correctness** (order lifecycle, callbacks, reconnects), never for strategy P&L realism.

### 2b. The four-tier mock ladder (all sharing one order interface)

1. **Dry-run** — orders validated, risk-checked, logged, displayed; never sent.
2. **Local fill simulator against live quotes** — a `SimExecutionClient` implementing the same interface as the live client. Fill semantics borrowed from [Nautilus Trader](https://nautilustrader.io/docs/nightly/concepts/execution/) (configurable fill models, liquidity consumption, queue-position tracking) and [QuantConnect Lean](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/key-concepts) (whose *default* zero-slippage instant fills are a warning about naive paper engines). Practical minimum: market orders fill at the **opposite touch** + configurable slippage, capped by displayed size; limit orders fill only when the far side trades through (or touches, with a probability haircut); 50–200 ms simulated latency. ~300–500 lines for a credible simulator.
3. **Shadow portfolios** — run every strategy/signal source in signal-only mode continuously; simulate each signal via tier 2 into a virtual portfolio charted next to the real one. This is the "what would have happened if I bought" feature, and the tool for deciding what gets promoted to automation.
4. **IBKR paper account** — occasional end-to-end API rehearsal.

Don't adopt Nautilus/Lean wholesale — they're heavy frameworks that would own the architecture; steal their fill-model semantics instead.

---

## 3. Market data (US stocks, retail)

- **Free tier:** real-time streaming **Cboe One + IEX** (non-consolidated, no NBBO) + ~100 free snapshots/month — fine for a casual dashboard, not for tight limit placement ([pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)).
- **Consolidated NBBO:** the non-pro **US Securities Snapshot and Futures Value Bundle** — **USD 10/mo, waived with ≥ USD 30 commissions/mo**.
- **Snapshots:** USD 0.01/request beyond the free allotment (regulatory snapshots).
- **Delayed fallback:** `reqMarketDataType(3)` on every connect → unsubscribed instruments deliver 15–20 min delayed ticks.
- **Concurrency:** TWS API streams **100 simultaneous tickers** by default (Quote Booster packs for more); the CP WebSocket handles only a handful. For watching dozens of symbols, TWS API is clearly the stronger pipe.

---

## 4. Architecture & stack

### 4a. Why Python-engine + web SPA wins

The broker side settles the stack: the socket API requires a running gateway process, and the best client ecosystem is Python. Comparing Next.js+Node, desktop (Tauri/Electron), and Python-first:

- **Desktop app**: automation dies when the laptop closes — you'd build a separate daemon anyway.
- **Next.js**: SSR machinery a single-user dashboard doesn't need; complicates WebSockets and Highcharts.
- **Python engine + Vite React SPA** *(winner)*: engine and ib_async share one asyncio loop (quotes go broker→UI with no cross-language hop); the UI is a disposable client — it can crash/close with zero effect on automation; one language for all trading logic.

### 4b. Topology

```
IB Gateway (Docker, IBC auto-login)
   │  TCP socket
Engine daemon (Python asyncio, ib_async)
   ├─ internal async pub/sub bus (quotes, orders, fills, positions, signals, logs)
   ├─ strategy/automation tasks (subscribe to bus)
   ├─ signal-ingestion consumers (email webhook → extraction → verification)
   ├─ persistence writer (bus → SQLite event journal)
   └─ FastAPI: REST (commands/history) + WebSocket (state streaming)
        │  one WS per browser tab, JSON frames
   React SPA (Vite + TS + Zustand + @highcharts/react)
```

Real-time rules that matter:

- **One WebSocket to the UI**, multiplexing message types — not one socket per symbol.
- **Snapshot + delta**: on connect send full state (positions, open orders, last quotes), then deltas — reconnects never race REST backfills.
- **Conflate for humans**: coalesce ticks to ~4–10 Hz per symbol for the UI; the automation loop consumes the unconflated bus.
- The engine is the **only** consumer of IBKR — N browser tabs cost the market-data lines nothing.
- Frontend state: **Zustand** with selectors (not Context/Redux); buffer WS messages in a ref and flush once per animation frame.

### 4c. Hosting & auth

- Engine + gateway colocated 24/7 under systemd/Docker on a small home server or VPS.
- Bind to localhost; remote access via **Tailscale**; single static bearer token. No OAuth stack for a one-user app.
- Optional later: wrap the same SPA in **Tauri v2** for a desktop feel (not Electron — far smaller/lighter).

---

## 5. Charting — Highcharts Stock

- **Capabilities:** first-class `candlestick`/`ohlc`/`hollowcandlestick`/`heikinashi` series, navigator, range selector, **data grouping** (auto-downsampling on zoom), **40+ built-in indicators** (SMA/EMA, RSI, MACD, Bollinger, VWAP, Ichimoku…), **Stock Tools** GUI (TradingView-style drawing toolbar), annotations that serialize to JSON (persist per-symbol in the DB). Real-time updates are idiomatic: `series.addPoint()`, `point.update()` for the forming candle, batched `chart.redraw()` ([product page](https://www.highcharts.com/products/stock/), [Stock Tools](https://www.highcharts.com/docs/stock/stock-tools)).
- **React integration (2025/26 change):** use the **new official `@highcharts/react`** package (JSX-native, actively released; requires React ≥18.3, Highcharts ≥12.2) rather than the maintenance-mode `highcharts-react-official` ([announcement](https://www.highcharts.com/blog/news/improved-highcharts-for-react/)).
- **Performance pattern:** never route ticks through React props. Grab the chart instance via ref; the component renders once. Chart **bars, not raw ticks** (aggregate in the engine); `animation: false` on live series; one redraw per animation frame; pause redraws when the tab is hidden; Boost/WebGL module only if plotting >100k points.
- **Licensing ⚠️:** Highcharts Core and **Highcharts Stock are separate SKUs** — Stock (or the Suite bundle) is required for candlesticks/indicators/Stock Tools. Verify which license was purchased. Perpetual + optional Advantage renewal is usually the better economics for a personal app ([shop](https://shop.highcharts.com/)).

---

## 6. Signal ingestion

### 6a. Don't use the corporate mailbox

The owner's email is on a corporate Microsoft 365 tenant. Everything about that path is hostile to a personal integration: app registrations and Mail.Read consent are typically admin-locked, IMAP basic auth is dead (OAuth-only since 2026), and **external auto-forwarding is disabled by default** in M365 ([forwarding policy](https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-policies-external-email-forwarding)) — plus mixing personal trading automation into an employer tenant is an IT-policy risk regardless.

**Recommendation:** re-subscribe every newsletter/alert to a dedicated personal address.

### 6b. Email is the universal ingestion bus

Almost every paid source has an email delivery mode — and for paid Substacks, **the subscriber email effectively *is* the API** (RSS feeds truncate paid posts). Options for receiving programmatically:

| Option | Cost | Notes |
|---|---|---|
| **Cloudflare Email Routing + Email Workers** ✅ | Free | Custom domain; each inbound email invokes a Worker (parse MIME with `postal-mime`, store raw, call the pipeline, optionally forward a copy to the real inbox). Code-first, push-native, no OAuth ([blog](https://blog.cloudflare.com/email-service/)) |
| Postmark Inbound / SendGrid Inbound Parse | cheap/free tier | Same webhook pattern, cleanest JSON (Postmark) |
| Gmail API polling | Free | If a Gmail collector is preferred: `gmail.readonly` app in perpetual Testing mode; **poll every 30–60 s** (Pub/Sub push works but adds a GCP project + watch-renewal cron for latency newsletters don't need) |
| IMAP IDLE | Free | Pragmatic hack vs a personal Gmail (app password); fragile, full-mailbox credential on the server |

Recommended: `signals@<personal-domain>` on Cloudflare → store raw MIME → queue → extraction. Validate **DKIM/SPF at ingestion** — alert emails can be spoofed, and a forged "sell everything" alert must not reach the pipeline.

### 6c. Non-email sources (2026 reality)

- **Substack:** RSS for free posts / publish-triggers; paid content via email.
- **Discord alert rooms:** official bots require server-admin installation (paid rooms won't); reading via a user token (self-bot) violates Discord ToS and risks a ban — if used at all, use a throwaway account knowingly, or prefer the service's email/SMS mirror.
- **Stocktwits:** API program frozen (no new registrations); old JSON endpoints unofficial. Sentiment garnish at best.
- **X/Twitter:** economically dead for hobbyists (pay-per-use $0.005/post read; legacy tiers retired).
- **Seeking Alpha:** no public API; ToS prohibits scraping; use its email alerts.
- **Scraping generally:** public-data scraping is generally not a CFAA issue post-hiQ, but paywalled/logged-in scraping is a ToS breach — the realistic downside is losing the paid account. Never redistribute content.

### 6d. LLM extraction (Claude API)

Use `client.messages.parse()` with a Pydantic schema (structured outputs). Core schema fields: `ticker`, `direction`, `action` (open/add/trim/close/update_stop), `entry_price`/`entry_type`, `target_price`, `stop_price`, `timeframe`, `thesis_summary`, **`evidence_quotes`** (verbatim snippets), `confidence` (`explicit_call` / `implied` / `commentary_only`), `is_actionable`; plus a top-level `signals: []` (empty = no signal) and `source_type` classification.

Hallucination guards, in order of importance:

1. **Quote-grounding verified in code** — every extracted price/ticker must be backed by an `evidence_quotes` entry that actually appears (exact/fuzzy) in the source text; discard fields that fail.
2. **Explicit no-signal path** — most newsletter volume is not actionable; the prompt must say so (prevents manufacturing trades from marketing emails and performance recaps).
3. **Confidence tiers** — only `explicit_call` is ever eligible for automation.
4. **Temporal grounding** — pass the received timestamp; flag recaps ("we bought NVDA at $95 in 2024") vs fresh calls.
5. **Ambiguity rule** — "if ticker or direction is ambiguous, set `is_actionable=false` rather than guessing."

Cost is irrelevant at newsletter volume (cents per email even on the top model) — don't cheap out on the step where errors are most expensive. **Never let extraction output flow to an order without the deterministic verification layer. The LLM proposes; code disposes.**

### 6e. Verification layer (deterministic, before any proposal)

| Check | How |
|---|---|
| Ticker resolves | IBKR contract lookup (`reqContractDetails` / `/iserver/secdef/search`); disambiguate exchange — a Canadian newsletter's "GOLD" is not the NYSE ticker context-free |
| Price vs claimed entry | IBKR snapshot; reject/flag if live price >2–5% beyond claimed entry or past target (stale alert / chasing) |
| Halt status | Quotes updating? Nasdaq [current-halts feed](https://www.nasdaqtrader.com/trader.aspx?id=tradehalts); IBKR halted flag |
| Liquidity/spread | Min ADV ($), max bid-ask %; size ≤ ~1–5% of ADV — **this is the pump-and-dump filter** |
| Earnings proximity | Finnhub free earnings calendar (60 calls/min free tier) |
| Corroboration | ≥2 independent sources raise confidence — but a *surge* of identical hype on an illiquid ticker is a pump red flag, not confirmation |
| Sanity | stop < entry < target (long); position/exposure caps; dedupe vs signals already acted on |

Data sources: **IBKR primary** (already paid for, same API that places the order), **Finnhub free** secondary; Polygon ($199/mo) only as a later upgrade; Alpha Vantage free tier too thin.

### 6f. Approval UX → graduated automation

1. Verified signal → **proposed order** record: ticker, side, computed qty, limit price, bracket (stop/target), source, evidence, verification results, **TTL** (e.g., 15 min intraday, EOD for swing). Expired = auto-cancelled, logged.
2. **Push with action buttons**: [ntfy.sh](https://ntfy.sh) (free, self-hostable, lock-screen Approve/Reject buttons hitting a signed one-time URL) or a **Telegram bot** with inline keyboards (richer: thesis, chart snapshot, "approve half size"). Approval endpoints: single-use signed tokens, short expiry, proposal-hash binding (a stale tap can't approve a mutated order), daily approved-notional cap.
3. On approve: **limit order with bracket** at IBKR — never market orders from automation.
4. **Graduation ladder, per source:** manual → scored trust (N≥20 signals; approval rate, slippage vs alert price, P&L from the shadow portfolio) → rules-gated auto-execute (`source == X AND confidence == explicit_call AND size ≤ $Y AND spread ≤ 0.5% AND not near_earnings AND market_hours AND daily_auto_budget > 0`), where auto-executed trades still push a notification ("Executed — tap to cancel/flatten"). Rules live in a deterministic policy file, never LLM-decided.

---

## 7. Safety & guardrails

Scaled down from the [FIA automated-trading risk controls](https://www.fia.org/sites/default/files/2024-07/FIA_WP_AUTOMATED%20TRADING%20RISK%20CONTROLS_FINAL_0.pdf):

1. **Layered kill switch:** soft halt (cancel open orders, block new ones, persisted across restarts, one big red button + chat command) → hard stop (kill the gateway container) → broker-level backstop. Test it regularly.
2. **RiskGate pipeline on every order** — manual and automated, live and mock: max position per symbol (shares + notional), max gross exposure, price collar vs last quote (fat-finger), order-rate limit (breach ⇒ auto-halt), **stale-data block** (no orders if quotes older than X s), market-hours/instrument whitelist. Every verdict is a journal event.
3. **Daily loss limit:** breach ⇒ soft halt for the session, re-armable only by explicit human action next day; rolling max-drawdown demotion for automations.
4. **Idempotent submission:** client order ID assigned and persisted (`OrderIntentCreated`) *before* submit; reconcile on reconnect; never resubmit an intent without a definitive rejection.
5. **Watchdogs:** engine↔gateway heartbeat (auto-halt on data loss), dead-man's-switch notification if the engine misses check-ins, daily position reconciliation vs IBKR with auto-halt on mismatch.

---

## 8. Persistence

- **SQLite (WAL mode)** — single writer (the engine's persistence task), in-process, no network hop on the order path; **Litestream** streams the WAL to S3/B2 for point-in-time offsite backup (~$1/mo). Postgres only if the topology ever becomes multi-writer.
- **Event-sourced schema:** append-only `events` table (`SignalGenerated`, `OrderIntentCreated`, `RiskCheckPassed/Failed`, `OrderSubmitted`, `OrderAcked`, `Fill`, `OrderCancelled`, kill-switch activations, config changes) = the audit trail and source of truth; `orders`/`positions`/`daily_pnl` are rebuildable projections. Live, paper, and shadow portfolios share one schema differing only by portfolio ID.
- **Market data:** persist charted bars (1m+) in SQLite; raw tick history (if ever wanted) goes to Parquet + DuckDB, not the trading DB.

---

## 9. Regulatory & practical notes

- **Pump-and-dump exposure is the #1 real risk** of trading newsletter signals, and automation amplifies it. Defenses: the liquidity/ADV filter, no auto-trading micro-caps, skepticism when "independent" sources hype the same illiquid ticker simultaneously.
- **PDT rule:** reportedly **eliminated in April 2026** (SEC-approved FINRA overhaul replacing the $25k/3-day-trade rule with a risk-based framework — [NerdWallet](https://www.nerdwallet.com/article/investing/pattern-day-trading-rule-change), [Schwab](https://www.schwab.com/learn/story/sec-approves-scrapping-25000-day-trader-minimum)) — but broker adoption varies; have the app count round-trips and warn until IBKR's current policy is confirmed for this account's domicile.
- **Wash sales / CRA superficial-loss** (if a Canadian taxpayer): automated re-entry on repeated signals is exactly how wash sales accumulate. The verification layer should flag any loss-realizing sale + re-entry within 31 days on the same ticker; the Canadian rule also counts affiliated accounts (spouse, RRSP/TFSA).
- Trading your own money on your own account raises no registration issues — IBKR's API exists for exactly this. Respect market-data non-professional attestations; never redistribute newsletter or exchange data.
- By the time a popular alert lands in the inbox, the market has often moved — the price-deviation check doubles as protection against systematically buying every pop.

---

## 10. Suggested build order

1. **Foundation:** repo scaffolding; dockerized IB Gateway (paper) + engine skeleton (ib_async connect, quote streaming, event journal in SQLite); Vite/React SPA shell with WebSocket state and one Highcharts Stock chart.
2. **Manual trading MVP:** order ticket (limit/market/bracket), positions/orders/P&L views, RiskGate, kill switch — against the paper account.
3. **Mock ladder:** dry-run mode + local fill simulator + shadow portfolio projections.
4. **Signal ingestion:** Cloudflare email worker → raw store → Claude extraction with quote-grounding → verification layer → pending-proposal queue in the UI.
5. **Approval loop:** push notifications with approve/reject; audit trail end-to-end.
6. **Live money, small:** flip the engine to the live gateway with tight RiskGate caps.
7. **Graduated automation:** per-source trust stats from shadow portfolios → rules-gated auto-execution with hard caps and post-trade veto notifications.

---

## 11. Open questions for the owner

1. **Where does the 24/7 backend run?** Home server / mini-PC, cloud VPS, or desktop-only (no always-on automation)?
2. **Instrument scope:** US stocks only, or also Canadian listings (TSX/TSXV)? Options now or later? (Affects market-data subscriptions, contract disambiguation, and the fill simulator.)
3. **Signal sources:** which newsletters/boards, and in what delivery form (email, Discord, web)? Willing to re-subscribe them to a dedicated personal address?
4. **Approval channel:** phone push (ntfy/Telegram) vs in-app only? Which messenger is preferred?
5. **Highcharts license:** is it the Stock/Suite SKU (needed for candlesticks/indicators) or Core?
6. **Account details:** IBKR account domicile (US vs Canada — affects PDT/tax logic), Pro vs Lite, approximate funding size (drives sane default risk caps).
