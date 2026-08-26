# Zargar — Mobile-first plan (2026-08-26, refreshed against HEAD `b1a96a8`)

**Goal:** Zargar works as a first-class phone app — installable, thumb-driven,
safe to trade from — with the **Armed "Now" screen** as its home. One codebase,
responsive; no separate mobile build.

**Status legend:** `[ ]` todo · `[~]` in progress · `[x]` done. Phases are
independent enough to run in parallel worktrees **except Phase 1, which
everything else builds on** (shell, breakpoints, `Sheet`, touch tokens).
Do Phase 1 first, alone, then fan out.

---

## 0. Where we are (evidence, 2026-08-26)

Measured with Playwright device emulation (iPhone SE / 14 / Pixel 7 / iPad Mini)
against HEAD `b1a96a8` (re-run after the 2026-08-26 merges: Techniques family
nav, Validation-first technique tabs, universe settings). Baseline: **42/42
device×route combos fail**. Regenerate any time: `cd frontend && npm run
mobile-audit` (see Phase 9; one-time `npx playwright install chromium` in
`frontend/`).

**What changed since the first draft (50f2664 → b1a96a8) and what it means here:**
- Sidebar: items are now 15px / 11px padding (**≈ 44px — already touch-sized**)
  and "Techniques" is a family with an **EM Options** sub-item (more techniques
  will nest under it). The phone `More` sheet and any drawer must show the same
  family grouping, not a flat list.
- Technique page: tabs are now **Validation · Analyse · Chat · History · Backtest**,
  Validation is the default, and the Armed tab is gone (Armed is its own page).
  On phones the default tab must flip to Analyse/History (Phase 6) because
  Validation is desktop-only.
- Settings: new universe controls (core universe · extras · today's most
  active) with an **Extra symbols** modal + 13px textarea — Phase 4 covers it
  (sheet + 16px).
- Backend: `technique/universe.py`, sweeps-failed-on-restart, short-side plans
  (REJECT/BREAKDOWN badges in scan/plan views) — no layout impact beyond more
  badge variants in the Armed/Technique cards.

| Fact | Evidence |
|---|---|
| **The app has no phone layout at all.** Layout floor ≈ **760px** (232px sidebar + 528px content); a phone either clips the right half or zooms out to unreadable. | audit: `innerWidth 760` on every route; screenshots show Armed KPIs/table, trade toolbar and dashboard cards cut at the right edge |
| **Zero breakpoints below 1100px.** `styles.css` has 7 `@media` rules: 1100px ×3, 1400px, 1500px, reduced-motion ×2. | `styles.css:820, :983, :1717, :1398, :1345` |
| **Sidebar is 232px on phones even where a rule says 190px** — `.sidebar{width:232px}` at `:1501` is declared after the ≤1100 rule at `:823` with equal specificity, so the media rule loses. | cascade bug |
| **Top bar is a non-wrapping 48px flex row of ~10 controls incl. a fixed 240px search** → document scrolls sideways; **HALT is the first thing pushed off-screen**. | `styles.css:148-151, :615`; `TopBar.tsx:122-199` |
| **Load-bearing meaning lives in `title=` tooltips** (touch can't open them): ~50 settings hints, LIVE-vs-practice contract, Δ broker mismatch, failed risk-check reasons, order reject reasons, void reasons, fee notes, disabled-timeframe reasons. | Settings `:90/:111/:125`; TopBar `:130/:160/:186`; ConfirmOrderDialog `:123-126`; Blotter `:142`; ArmedPage `:313` |
| **Every input is 12–14px** → iOS zooms on focus and never zooms back — including the order ticket and the halt-reason prompt. | `styles.css:494-498, :473-477, :617-622` |
| **Sub-40px targets are the norm** (sidebar items are the exception since b1a96a8): `.link-btn` ~17px, `.icon-btn` ~22px, `.switch` 19px (the **dry-run** toggle!), `.status-pill` 20px, `.danger-btn` 25px (**Sell now**, **Cancel order**), table rows 24–28px. Audit on iPhone 14: Armed 15/25 targets < 40px, Trade 44/55, Signals 9/20, Settings 75/85, Journal 308/318. | `styles.css:584, :600, :521, :577, :586, :539` |
| **Tables everywhere, `nowrap`, 6–15 columns**, some inside `overflow:hidden` panels (Armed fleet: clipped, not even scrollable). | Blotter 8/10/7 cols; OptionChain 15; Inbox 8; Armed fleet 7–8 (`.panel{overflow:hidden}` `:372`); Technique history 11 |
| **`100vh` shell** (`:136`) + `calc(100vh-210px)` regions → bottom of app under iOS chrome; modals `80vh`; toasts fixed bottom-right, `max-width:380px` → clipped at 360px. | `styles.css:136, :919, :1714, :682, :765-768` |
| **No touch code at all**: no `pointer:coarse`, `hover:hover`, `touch-action`, `dvh`, safe-area insets, `:active` states, `visibilitychange`. | grep |
| **WS drops on every mobile network transition and never resubscribes** (`watchSymbol` no-ops on a closed socket); no client-side quote conflation; per-tick Highcharts redraw + `TickArrow` DOM remount per tick. | `ws.ts:15-19, :39-88`; `StockChart.tsx:301-327`; `quotekit.tsx:160` |
| **Data diet is desktop-sized**: 600 one-minute bars per watchlist symbol for an 84×22 sparkline; `/api/technique/armed` ships every trigger/trade + up to 200 events per plan every 30s. | `useDaySeries.ts:62`; `arming.py:302`; `ArmedPage.tsx:84` |
| **Nothing reaches a closed phone**: no manifest / service worker / Notification API; alerts are 6-second toasts; Telegram alerts are plain text with no deep link or buttons. | `store.ts:508-513`; `arming.py:1101-1106`; `telegram.py:92-100` |
| **A phone can't reach the app today**: backend binds `127.0.0.1`, no auth token by default, no TLS (PWA install, service workers and push all require HTTPS or localhost). | `config.py:18-21` |

What already helps: real URLs (`routing.ts`, OS back works, deep links exist),
`Collapse`/`useDisclosure`, click-based `InfoTip`, `Modal` sized with `min()`,
`.settings-grid{columns:400px}` degrades to one column, `.opt-expiries` chip
strip, sidebar badge for armed/attention counts.

---

## 1. Principles (decided — apply everywhere)

1. **Phone-first layout, desktop keeps everything.** Base styles are the phone
   styles; `@media (min-width: 640px)` and `(min-width: 1024px)` add columns
   back. Where that's too invasive for an existing rule, a `(max-width: 639px)`
   override is acceptable in Phase 1–4, but new CSS is written mobile-up.
   Breakpoints: **phone < 640**, **tablet 640–1023**, **desktop ≥ 1024**. Touch
   sizing is keyed on **`(pointer: coarse)`**, not width (iPad, touch laptops).
2. **Thumb zone rules.** Primary actions live at the bottom (tab bar, sticky
   BUY/SELL, sheet footers). Destructive/money actions are **larger and more
   separated** on phones, never smaller. Confirm buttons are full-width, never
   side-by-side with Cancel.
3. **Nothing load-bearing in hover.** Every `title=` that explains a number, a
   disabled state, a warning or a verdict becomes visible text, an `InfoTip`
   (tap), or a line inside the sheet. `title=` may remain only as a duplicate.
4. **Sheets, not popovers.** On phones: modals, account picker, symbol search,
   chart settings, plan detail, confirm dialogs are **bottom/full-screen
   sheets** (`Sheet` primitive, Phase 1). Absolutely-positioned dropdowns are
   desktop-only.
5. **Touch tokens:** inputs ≥ **16px** (kills iOS zoom); tap targets ≥ **44px**
   (40 minimum for dense lists); `:active` feedback everywhere `:hover` exists;
   `-webkit-tap-highlight-color: transparent`; `touch-action: manipulation` on
   controls; `100dvh`; `env(safe-area-inset-*)` on fixed bars.
6. **Cards, not tables, below 640px** — unless the table has ≤ 3 columns. A
   table that must stay a table gets a sticky first column and a real
   `overflow-x` wrapper with a visible scroll hint.
7. **Data diet on phones.** No sparkline history fetches; slim list endpoints;
   quote conflation ≤ 4 Hz; pause the socket when the tab is hidden; resubscribe
   on reconnect. Budget: opening Armed on cellular < 150 KB.
8. **Progressive, not broken.** Desktop-only features (Validation sweeps,
   Backtest, bulk review, Chat) are hidden behind an honest "open on desktop"
   note on phones — never rendered broken.
9. **Safety policy for phones (new setting, default ON):**
   `mobile.exit_only = true` — a phone session may HALT, flatten, disarm,
   pause, approve/reject proposals and **exit** positions, but **cannot open a
   new LIVE position** unless the user turns it off in Settings (desktop or
   phone, with a confirm). Detected via `pointer:coarse` + viewport < 640 and
   sent as `X-Zargar-Client: phone`; enforced client-side (ticket) **and**
   server-side in `RiskGate` as a safety check (`phone_entry_blocked`).
10. **Verification is automated.** Phase 9's device audit must pass before a
    phase is marked done: no horizontal overflow, no element wider than the
    viewport, no input < 16px, no interactive target < 40px on phone routes.

---

## 2. The phone's jobs (ranked — this is the build order inside each page)

1. **What's happening right now** — armed plans, fired, in trade, attention,
   P&L today, is the kill switch on. → Armed "Now" (Phase 2), the app's
   mobile home.
2. **Stop something** — HALT, flatten, disarm, sell now. Always ≤ 2 taps away.
3. **Approve / reject a proposal** before its TTL expires (Signals).
4. **See positions and P&L** (Blotter / Dashboard / Portfolios).
5. **Read a chart and a quote** for a symbol (Trade).
6. **Place an order** — exits first; entries only when `mobile.exit_only` is off.
7. **Glance at watchlists**, add a symbol.
8. **Read why** — journal / plan log / critic verdict.
9. **Flip a few settings** (arm mode, evening automation, theme).
10. Everything else is desktop.

---

## 3. Phases

### Phase 0 — Reach the phone at all (access, auth, TLS) `[ ]`

- [ ] **Bind + auth.** `ZARGAR_HOST=0.0.0.0` (or the Tailscale IP) and a
      required `ZARGAR_AUTH_TOKEN` when the host isn't loopback (refuse to start
      exposed without a token). Token entry screen on the phone (currently only
      `?token=` / localStorage): a small **"Sign in"** sheet that stores the
      token, plus a **QR code in desktop Settings** encoding
      `https://host/#token=…` so the phone never types it.
- [ ] **HTTPS.** Recommended: **Tailscale** on desktop + phone,
      `tailscale serve https / http://127.0.0.1:8420` (real cert, no port
      forwarding, works on cellular). Alternatives documented: LAN + mkcert;
      Cloudflare Tunnel (public — token mandatory). Document in
      `docs/MOBILE-ACCESS.md`; add `scripts/mobile-access.ps1` that prints the
      QR + URL.
- [ ] **CORS/WS origin** allow the served origin; WS `?token=` stays.
- [ ] **Session hardening for a phone that's out in the world:** token in
      `localStorage` is acceptable for a single user, but add a Settings
      "Sign out this device" + "Rotate token" (rotating invalidates every
      device).

### Phase 1 — Shell & primitives (everything depends on this) `[ ]`

**Viewport / tokens**
- [ ] `index.html`: `viewport-fit=cover`, `theme-color` (light+dark),
      `apple-mobile-web-app-*` metas, `color-scheme`.
- [ ] `.app { height: 100dvh }` (fallback `100vh`); all `calc(100vh - …)`
      → `dvh`; `overscroll-behavior: none` on `.app`; `-webkit-text-size-adjust:100%`.
- [ ] Global touch tokens: `@media (pointer: coarse)` → `--control-y`
      bumps, `input/select/textarea { font-size: 16px }`, min-height 44px on
      `button`, `.link-btn` becomes a padded button, `.switch` 44×26,
      `.icon-btn` 40×40 hit area (visual can stay small), `:active` states,
      `-webkit-tap-highlight-color: transparent`, `touch-action: manipulation`.
- [ ] **Fix the sidebar cascade bug** (`:1501` vs `:823`) regardless of the
      rest — one-line, ship first.
- [ ] `useViewport()` store slice: `isPhone` (<640), `isTablet`, `coarse`
      (`matchMedia('(pointer: coarse)')`), `orientation`; **derived, never
      persisted**. Sidebar collapse state stops mattering on phones.

**Navigation**
- [ ] **Bottom tab bar** on phones (`.tabbar`, fixed, safe-area padded,
      56px + inset): **Now (Armed) · Trade · Signals · Portfolio · More**.
      Badges: armed/attention on Now, pending count on Signals. `More` opens a
      sheet with Dashboard, Options, Watchlists, **Techniques (grouped: EM
      Options, and any technique added later — same family model as the
      sidebar)**, Journal, Settings, theme toggle, connection state, sign out.
- [ ] Sidebar hidden below 640px; on tablets it's the 52px rail by default.
- [ ] **Top bar on phones** = brand mark · **workspace chip (PRACTICE/LIVE)** ·
      **HALT** (44px, always visible, right-thumb) · search icon (opens the
      symbol-search sheet). Everything else (equity chip, attention pill, conn
      dot, theme, mode select) moves to `More`/Dashboard. Mode switch on phone
      lives in `More` behind the same confirm.
- [ ] Banners (`.halt-banner`, `.drift-banner`): `min-height` instead of
      `height:30px`, wrap, stack buttons; halt banner text ≥ 14px.
- [ ] Toasts: top-anchored on phones, full-width minus 8px, explicit ✕,
      auto-dismiss stays; never overlap the tab bar.
- [ ] Splash: skip below 640px or serve ≤ 800px art; `MAX_SHOW_MS` 1.2s.

**Primitives**
- [ ] **`Sheet`** component (bottom sheet + `full` variant): portal, drag
      handle, `max-height: 92dvh`, safe-area footer slot, scroll lock on body
      (fix the missing lock in `Modal` too), Escape/back-gesture closes
      (pushState entry so Android back closes the sheet, not the page),
      focus trap. `Modal` renders as `Sheet` when `isPhone`.
- [ ] **`Confirm`** upgrade: replace every `window.confirm` (Armed stop-all,
      pause/disarm/flatten, cancel order) with `ConfirmDialog`/`Sheet`; add a
      **typed-word confirm** variant ("type FLATTEN") for flatten-all and
      live flatten.
- [ ] **`InfoTip` sweep policy**: a lint-ish grep gate (`frontend/scripts/mobile-audit.mjs`
      reports `title=` on interactive/meaningful elements) — the sweep itself is
      done per page in Phases 2–6.
- [ ] **`CardList`** primitive for the tables→cards conversions: row = 2 lines
      (primary left/right, secondary muted), optional trailing action ≥ 44px,
      swipe-to-reveal optional (not required).
- [ ] **`ScrollX`** wrapper with edge fade + sticky first column for tables that
      must stay tables.
- [ ] Highcharts base theme: phone variant (no navigator, no legend, larger
      plot-line labels, `tooltip.followTouchMove`, `chart.zooming.pinchType:'x'`,
      `panning`), `chart.reflow()` on orientation change.

**WS / data foundation (used by every page)**
- [ ] `ws.ts`: keep a `watched` set, **resubscribe all topics on `onopen`**;
      `visibilitychange` → close socket after 30s hidden, reconnect + resnapshot
      on visible; reconnect backoff unchanged.
- [ ] Quote conflation on the client: coalesce `quotes` frames per animation
      frame / ≥ 250ms; `applyQuotes` batches. `TickArrow` stops remounting DOM
      per tick (CSS animation restart via class toggle).
- [ ] `useDaySeries`: on phones fetch `tf=5m&limit=80` (or skip when the
      sparkline is hidden); evict cache on symbol change; unsubscribe listeners.
- [ ] Client hint header `X-Zargar-Client: phone|tablet|desktop` on API + WS
      (for `mobile.exit_only` and slim payloads).

**Exit-only safety (Principle 9)**
- [ ] `settings_service.DEFAULTS["mobile.exit_only"] = True`; RiskGate safety
      check `phone_entry_blocked` (entry intents from a `phone` client while the
      setting is on → `REJECTED_RISK`, journaled); ticket shows the reason and
      hides BUY-to-open on phones. Settings toggle with a confirm.

**Done when:** every route renders inside 390px with no horizontal overflow
(audit passes for overflow + input size), tab bar navigates all pages, HALT is
reachable on every screen, sheets replace modals on phone.

### Phase 2 — Armed "Now": the mobile home `[ ]`

The phone opens on **Now**. It answers, top to bottom, in this order: *is
anything wrong → am I in a trade → what fired today → what's still waiting →
what died and why → how did today go*. One column, cards, no tables, 30s poll
+ WS patches.

**Backend — `GET /api/technique/armed/summary`** (new; the live list stays)
- [ ] Returns (camelCase): `workspace`, `haltEngaged`, `attention[]`
      (`runId, symbol, reasons[], hasPosition`), `inTrade[]` (`runId, symbol,
      instrument, remaining, entry, stop, nextTarget, unrealizedPnl,
      unrealizedR, firedAt, window`), `timeline[]` (today, cross-plan, newest
      first, capped 100: `ts, runId, symbol, kind ∈ fired|exit|trim|critic_kill|
      entry_rejected|exit_failed|disarmed|loss_halt|paused|resumed|voided,
      text, pnl?`), `watching[]` (`runId, symbol, grade, mode, distancePct,
      windowState, stale, nextTriggerText`), `stoppedToday[]` (`runId, symbol,
      reason, at` — **includes plans disarmed by a loss halt, which the live
      list currently forgets**), `pnl` (`realized, unrealized, lossLimit,
      lossLimitUsedPct`), `counts`. Reuses `_attention_reasons()`,
      `_unrealized()`, plan `events`; terminated-today plans come from the
      armed history rows for `planFor == today`.
- [ ] `GET /api/technique/armed?slim=1`: no `events`, no per-trigger history —
      for the phone list; the detail sheet fetches the full plan on open.
- [ ] WS `armed` patches keep flowing; the page re-pulls `summary` on any
      `fired|exit_*|entry_*|disarmed|alert` kind (debounced 2s) instead of
      every 30s only.
- [ ] Tests: summary shape with fixtures for each timeline kind; loss-halted
      plan appears in `stoppedToday`; slim omits events.

**UI — `pages/ArmedPage.tsx` phone layout (`isPhone`), desktop unchanged**
- [ ] **Status strip** (sticky under the top bar): `PRACTICE/LIVE` · kill
      switch state · "3 armed · 1 in trade · 2 need attention" · last update
      age. Tap → quick actions sheet (Stop all / Flatten & stop all — typed
      confirm).
- [ ] **Needs attention** cards (red left rule): symbol, reason sentence,
      **Sell now** (44px, danger, sheet confirm) and **Open**.
- [ ] **In trade** cards: symbol + instrument line, `remaining × entry`,
      unrealized (money + R) as the big number, stop / next target as a
      two-segment meter (price now between stop and target), fired time +
      window. Tap → plan sheet. Long-press/`…` → Sell now / Pause / Disarm.
- [ ] **Fired today** timeline: one line per event (time · symbol · what ·
      P&L chip), critic kills and rejects included — "why nothing fired" is
      visible without opening anything.
- [ ] **Watching** list (`CardList`): symbol, grade chip, distance-to-trigger
      meter (the existing `DistMeter`, 100% width), window state
      (open / closed / mid-day), STALE badge, one-line "waiting for …" text
      (from `ArmedDayPanel`'s now-sentence). Sort: attention → in trade →
      nearest trigger. Tap → plan sheet.
- [ ] **Stopped today**: symbol, reason (loss halt / gap-voided / gapped past /
      disarmed / exhausted), time; collapsed by default when empty.
- [ ] **Today** footer card: realized · unrealized · loss-limit progress bar;
      after the close, per-plan scorecard summary and a link to History.
- [ ] **Plan sheet** (`full` Sheet, replaces the split/strip detail on phones):
      `summary` sentence at 16px first; badges row; actions row (Pause/Resume ·
      Disarm · Flatten · mode select) as 44px buttons in a 2-column grid;
      triggers as cards; trades as cards (5 stat cells → 2×3 grid); day chart
      as an opt-in collapsed section (`ArmedDayPanel` at `height: 260`, no
      volume/R panes on phone); log/audit as a collapsed section. Deep link
      `/armed/<runId>` opens it directly (for Telegram links, Phase 7).
- [ ] **History** sub-tab: day cards (plans · fired · realized) → tap expands
      the plan rows as cards.
- [ ] Remove keyboard-only affordances from phone (←/→ hint); replace every
      `title=` void/status reason with visible text (`ArmedPage.tsx:313`).
- [ ] Dashboard's armed widget reuses the summary (counts + attention).

**Done when:** on a 390px phone the Now screen shows attention/in-trade/fired/
watching without any horizontal scroll, every action is ≥ 44px and confirmed
through a sheet, `summary` payload < 30 KB for 40 plans, audit passes.

### Phase 3 — Trade: chart, ticket, confirm, blotter `[ ]`

- [ ] **Trade layout on phones**: quote head (symbol · last · delta pill ·
      ext-hours chip; bid/ask on a second line) → full-bleed chart
      (`min-height: 46dvh`, landscape: 80dvh, toolbar hidden) → sticky
      **BUY / SELL** bar above the tab bar (SELL only, or "Exit" when
      `mobile.exit_only` and no position) → positions card list.
- [ ] **Chart toolbar → 2 controls**: range segmented control (1D · 5D · 1M ·
      1Y) and a `⋯` button opening a **chart settings sheet** (type, timeframe
      with *reasons* for disabled ones, indicators, views, ETH/RTH). Persist as
      today.
- [ ] `StockChart` phone options: navigator off, volume pane off, indicator
      count ≤ 1, `pinchType:'x'`, `panning` with a 2-finger hint, tooltip
      `followTouchMove` + `outside`, plot-line labels ≥ 11px or moved to a
      chip strip, no destroy/rebuild for toolbar toggles that can `update()`.
      Fix the **collapsed-rail bug** below 1100px (`.trade-grid--tc` cascade).
- [ ] **Order ticket → full-screen `Sheet`** on phones: single column,
      16px inputs, numeric keypads (`inputmode="decimal"`), qty stepper
      (±1/±10 and "max"), **Validate / Place** segmented control replaces the
      19px dry-run switch, account picker → `Sheet`, fees + FX note inline at
      13px+ (no tooltips), "verify with broker" as a 44px button; footer =
      the submit button (fixed, safe-area). Label overflow: `BUY 10 AAPL` on
      one line, cost on a second.
- [ ] **Confirm dialog → full-screen `Sheet`**: headline ≥ 20px, cost + account
      + connection status as rows, **risk checks expanded inline** (name +
      detail, pass/fail), pre-flight gating unchanged, **full-width Confirm**
      at the bottom with Cancel above it (never side by side), `dvh` +
      safe-area, scroll lock. LIVE confirm adds a 1.5s hold-to-confirm.
- [ ] `AccountSelect`, `SymbolSearch` → `Sheet` on phones (full-screen search
      with autofocus, 44px result rows, "+ watch" as a trailing 44px button;
      fix `mousedown`-only dismiss with `pointerdown`).
- [ ] **Blotter → `CardList`** on phones: positions (symbol · qty@avg / last ·
      P&L pill · value), orders (symbol · side qty · status / time · **Cancel**
      44px with confirm), fills; reject reason visible inline; tabs remain.
- [ ] `WatchRow`: remove the nested `<button>` (`DeltaPill` inside the row
      button) — pill becomes a `span` with a row-level toggle on phones.

### Phase 4 — Signals, Dashboard, Portfolios, Watchlists, Journal, Settings `[ ]`

- [ ] **Signals (Inbox)** — the most phone-native task: `.grid-2col` →
      single column below 900px; proposal card full-width with TTL countdown
      prominent, **Approve** full-width primary, Half/Reject as separate 44px
      buttons below; check chips → expandable list showing `detail`; Signals
      table → cards; Content table hidden behind a collapse (preview visible,
      not in `title`); manual-ingest textarea 16px.
- [ ] **Dashboard**: `.dash-providers` → `minmax(min(280px,100%),1fr)`;
      `HoldingsWidget` gets a `grid-area` so it lands first on mobile;
      orders/fills → cards; Δ mismatch as an inline dismissible note; equity
      chart 200px, legend off; watchlist strip not nested-scrolling.
- [ ] **Portfolios**: account header wraps into 2 lines; positions → cards;
      chart legend → chips; `.switch` → 44px; mismatch text inline.
- [ ] **Watchlists**: `minmax(min(340px,100%),1fr)`; edit mode with 44px
      trailing delete; add via the search sheet.
- [ ] **Journal**: tabs → scrollable chip strip; rows → 2-line entries
      (pill + relative time / summary; detail expands); load 50 + "more".
- [ ] **Settings**: every panel in `Collapse` (open by default: Evening
      automation, Trading mode, Appearance, **Mobile** (exit-only toggle, sign
      out, rotate token, install app)); `.setting-row` stacks below 640px with
      full-width controls; all `title` hints → `InfoTip` or `<small>` text
      (the ~50-item sweep); `.switch` 44px; in-page section jump list;
      the universe controls (core · extras · most-active) keep their line
      layout but the **Extra symbols** modal becomes a `Sheet` with a 16px
      textarea.

### Phase 5 — Options on phones `[ ]`

- [ ] Chain: **one side at a time** (Calls | Puts segmented), 3 columns
      (Strike sticky · Bid/Ask · Δ or IV via a toggle), ATM row centred,
      ITM shading stronger; tap row → contract sheet (greeks 2×4 grid,
      spread warning as text) → ticket sheet.
- [ ] Option ticket: same treatment as Phase 3; breakeven / max loss inline
      ≥ 13px; venue-unsupported message ≥ 14px with the reason; disabled-submit
      reasons listed above the button.
- [ ] Chain delay / IV30 explanations visible, not tooltips.

### Phase 6 — Technique on phones (read + arm one run) `[ ]`

- [ ] `.tq-head` wraps; tabs → scrollable chip strip; rail → a "Plans"
      sheet (remove the vertical-text handle on phones). **Phone default tab =
      Analyse** (desktop default is Validation since b1a96a8); the EM Options
      sub-item deep-links to `/technique/analyse`.
- [ ] Phone shows **Analyse** (symbol, as-of, TF, note; image via camera roll
      `<input type=file accept=image/*>`, no paste/drop copy) and **History**
      as cards (verdict · grade · symbol · when); run view (`PlanCard` /
      `RunResult`) reflowed: stat grids → 2 columns, facts table → key/value
      list, stand-aside reason visible; **Arm** → sheet.
- [ ] Validation, Backtest, Chat, bulk Check & arm: rendered as a compact
      "open on desktop" card with the current status (sweep running / N
      findings) — never the broken desktop layout.

### Phase 7 — Notifications & install (reach a closed phone) `[ ]`

- [ ] **PWA**: `manifest.webmanifest` (name, `display: standalone`, theme/bg
      colours, `start_url: /armed`, icons 192/512 + maskable + Apple touch
      icon from `logo-mark`), service worker that caches **the app shell
      only** (never `/api`, never WS; network-first for `index.html` so
      deploys aren't sticky); "Install app" row in Settings → Mobile.
- [ ] **Telegram deep links + buttons** (works today, zero infra): every
      `_alert()` and fired/exit/critic message gets an inline **Open** URL
      button to `/armed/<runId>` (and `/inbox` for proposals) on the served
      origin; token handoff via `#token=` fragment on first open (Phase 0).
- [ ] **Web Push** (VAPID, `pywebpush`): subscribe from Settings → Mobile;
      server sends `attention`, `fired`, `exit`, `loss_halt`, `kill_switch`,
      `proposal` pushes with a deep link; SW `notificationclick` focuses/opens
      the route. Per-kind toggles in Settings; quiet hours honour
      `technique.arm.*` windows.
- [ ] **App badge** (`navigator.setAppBadge`) = attention count + pending
      proposals; cleared when Now is viewed.
- [ ] In-app: alerts persist in a **Notifications sheet** (from the status
      strip) instead of vanishing after 6s; unread dot on the Now tab.

### Phase 8 — Performance & battery `[ ]`

- [ ] Code-split Technique, Options, Highcharts (dynamic import) — the phone
      shell should not download the Validation tab.
- [ ] Quote conflation + `visibilitychange` (Phase 1) measured: main-thread
      < 10% idle with 20 symbols on a mid-range Android.
- [ ] `/armed` slim + summary polling only while visible; 30s → 60s on
      cellular (`navigator.connection.saveData`/`effectiveType`).
- [ ] Images: splash ≤ 800px webp; broker logos lazy.
- [ ] No layout thrash: `contain: content` on card lists; virtualise Journal
      and long fleets (> 60 rows).

### Phase 9 — Verification gates `[ ]`

- [ ] **`frontend/scripts/mobile-audit.mjs`** (`npm run mobile-audit`; added with this plan; Playwright is a frontend devDependency, run `npx playwright install chromium` once): device
      matrix **iPhone SE (375), iPhone 14 (390), Pixel 7 (412), iPad Mini
      (768, portrait), iPhone 14 landscape**; every route + the Armed plan
      sheet + the order ticket + confirm sheet; writes screenshots to
      `frontend/.mobile-shots/` (gitignored) and `audit.json`; **fails** on:
      horizontal overflow, elements wider than the viewport, inputs < 16px,
      interactive targets < 40px (phone routes), `title=` on interactive
      elements without an accompanying visible label/InfoTip. Run it before
      marking any phase done.
- [ ] Real-device pass on the user's phone (iOS Safari quirks: `dvh`, keyboard
      + sheets, standalone mode back gesture, push permission) — a checklist in
      `docs/MOBILE-ACCESS.md`.
- [ ] Backend tests for: summary endpoint, `phone_entry_blocked`, Telegram
      link buttons, push subscription CRUD.
- [ ] A11y: focus order in sheets, `aria-modal`, tab bar `aria-current`,
      reduced-motion respected by sheet animations.

---

## 4. Rollout order and sizing

| Order | Phase | Size | Parallel? |
|---|---|---|---|
| 1 | 0 Access | S (½ day incl. Tailscale doc) | with Phase 1 |
| 2 | **1 Shell & primitives** | **L (2–3 days)** | **no — everything depends on it** |
| 3 | **2 Armed Now** | L (2 days: ½ backend summary, 1½ UI) | after 1 |
| 4 | 3 Trade/ticket/confirm/blotter | L (2 days) | parallel with 2 |
| 5 | 4 Signals/Dashboard/Portfolios/Watchlists/Journal/Settings | M (1½ days) | parallel with 2/3 |
| 6 | 7 Notifications & install | M (1 day; push needs Phase 0 HTTPS) | parallel |
| 7 | 5 Options · 6 Technique | M each | parallel |
| 8 | 8 Performance · 9 Verification | S–M | continuous; 9 gates every phase |

Suggested worktrees after Phase 1 lands: `mobile-armed-now` (2),
`mobile-trade` (3), `mobile-pages` (4), `mobile-notify` (7).

---

## 5. Decisions for the user (defaults chosen; say if you want different)

1. **Bottom tabs = Now · Trade · Signals · Portfolio · More.** (Alternative:
   swap Signals for Watchlists if proposals are rare.)
2. **Phones are exit-only for LIVE by default** (`mobile.exit_only`). You can
   flip it in Settings; the app will still ask for a hold-to-confirm on live
   entries from a phone.
3. **Access via Tailscale Serve** (HTTPS, private, no port forwarding). If you
   prefer LAN-only, PWA install still works via mkcert; push does not from
   outside the LAN.
4. **Telegram deep links first, Web Push second** — Telegram is one commit and
   already configured; push needs HTTPS + a subscription flow.
5. **Practice workspace is available on the phone** but the Now screen shows
   the *active* workspace only (same rule as desktop) with the cross-workspace
   pill.

---

## 6. Appendix — per-page findings (condensed from the 2026-08-26 review)

Full file:line detail lives in the review transcripts; the actionable items
are already folded into the phases above. Highest-severity per area:

- **Shell:** sidebar 232px cascade bug (items themselves are 44px now);
  top bar overflow pushes HALT off-screen; fixed-30px banners; toasts clipped;
  `100vh`; no drawer/tab bar; Techniques family grouping must survive the move
  to a tab bar / `More` sheet.
- **Trade:** 22-button toolbar (6–8 rows on a phone); `.trade-grid--tc` rail
  bug below 1100px; navigator + per-tick redraw; 14px symbol input.
- **Ticket/Confirm:** 13px inputs; 19px dry-run switch; 17px "verify fees";
  confirm is a 358px card with two ~34px right-aligned buttons; failed checks
  only in `title=`; no scroll lock.
- **Blotter:** 8/10/7-column nowrap tables; 25px Cancel with no confirm;
  reject reason in `title=`; rows tappable only by hover cue.
- **Armed:** fleet clipped (panel `overflow:hidden`); ≤1100 fallback is a
  300px nested scroller; detail card is a wall (chart 340–400px, 5-cell trade
  grids, 8 actions, log); Sell now 25px; `window.confirm`; 30s full payload;
  loss-halted plans vanish from the live list.
- **Technique:** `.tq-head` nowrap; 262px rail + vertical-text handle on phones;
  11-column history; `calc(100vh-210px)` chat; many fixed tracks (520px facts
  table, 280px findings, 260px rename…).
- **Options:** 15-column chain, 14 sub-40px targets per row each loading a
  contract into a real-money ticket; nested scroll trap; delay/IV30 in tooltips.
- **Signals:** `1fr 1fr` grid with no breakpoint; Approve/Reject ~20px
  adjacent; failed-check reasons and content previews in `title=`.
- **Dashboard/Portfolios/Watchlists/Journal/Settings:** `minmax(280/340px)`
  grids overflow; holdings widget auto-places last; 6–7-column tables;
  6-tab journal head + 180px input; ~50 tooltip-only settings hints; 60 inputs
  at 13px; 19px switches.
- **Data/WS:** no resubscribe on reconnect; no conflation; 600-bar sparkline
  fetches; `/armed` events payload; no `visibilitychange`.
- **Notifications:** none reach a closed phone; Telegram has no links/buttons.
