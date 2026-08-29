# Discord alert auto-intake + the Tips Analyst — research & build plan

*2026-08-28. POC scope: the user's laptop, experimental, not production. The
user is in the OWLS Capital Discord; the server's "Reaction Roles" blue
section DMs alert copies to members (confirmed: "@jon and kian DM" role
added 2026-08-28). Alerts are bot embeds ("OWLS Capital Clanker") with a
strict grammar and their own timestamps.*

## 0. The boundary, restated (supersedes the blanket "no Discord" line)

| | verdict | why |
|---|---|---|
| User-token automation ("self-bot", reading DMs via the gateway as you) | **POC-only, opted-in** | Violates Discord ToS; risk is to THIS account (ban if detected). User knowingly opted in 2026-08-28 for the laptop POC because desktop toasts proved unreliable. **Kept read-only** (listen, never write); auto-execution stays gated. `zargar/tools/discord_gateway.py`. Not for any shared/production build. |
| Bot-token automation in a server we don't own | **N/A** | We can't add a bot to OWLS Capital, and bots can't read your DMs anyway. |
| **Reading the OS notifications Discord already delivered to you** | **OK** | No Discord API touched, nothing automated inside Discord — the programmatic equivalent of the already-allowed "screenshot of your own client". Local, read-only. |
| Screenshot/OCR of your own Discord window | OK (fallback) | Same principle; we already have vision transcription. |
| A service's own API/webhook/email delivery | OK (best, when offered) | This is the "service's own bot/API" the research always allowed. Worth asking OWLS if they offer one. |
| Auto-EXECUTION of an alert | **still gated** | Intake ≠ execution. Everything lands in the existing pipeline: verification, shadow books, proposals; auto mode stays per-source-earned + RiskGate. |

## 1. Alert anatomy (from the user's screenshots, 2026-08-28)

- Channel `#🔔|jon-and-kian` ("Mainly swing trades based on unusual options
  activity, heatseeker and technical…"); the DM copy mirrors the channel embed.
- Bot embeds quote the analyst (e.g. "RegardedTrader (Jon)") with:
  - `OPEN: NTR 82.5C 03/19/2027 Exp. At 4.60` → open, call, strike 82.5,
    expiry 2027-03-19, **premium 4.60** (the contract's own price).
  - `Update: SPCX in small profits, if you got that 3.70 dip and want to trim
    go for it!` → references an EARLIER position; action trim.
  - `OPEN: SPY 750P 09/18 Exp. At 3.38!!` → put + hedging context in prose.
  - Boilerplate every time: "Owls Investments LLC. Informational purposes
    only.", "Bot Version 6.7 …", a timestamp line `08/28/26 · 09:53:49 AM`.
- Eleven analyst channels (jon-and-kian, muggzone-options, shabs-sky-alerts,
  giul-heatseeker, tt, florida-man, eva, eli-alerts, common-stock, ab,
  bobby-spx-coms) → each is its own SOURCE with its own scorecard/policy.

## 2. Intake options, ranked for the laptop POC

0. **[BUILT 2026-08-28, EXPERIMENTAL — ToS-unsanctioned] Discord gateway
   listener** — `zargar/tools/discord_gateway.py`. A bare websocket to
   `wss://gateway.discord.gg/?v=10` with the user token: HELLO → heartbeat →
   IDENTIFY (user-shaped, no intents) → listen for `MESSAGE_CREATE` DMs, flatten
   embeds (the trade lives in the embed, not `content`), post to
   `/api/ingest/manual`. **Read-only** — never sends/reacts/types. Minimal
   footprint on purpose (no REST polling → less detectable than discord.py-self
   / discum). This is the *reliable* feed (works headless, survives a closed
   lid, no truncation) but carries account-ban risk; chosen for the POC after
   toasts proved flaky. Token in `ZARGAR_DISCORD_TOKEN` (never committed; the
   `discord_dms.jsonl` capture is gitignored — it holds DM contents). Modes:
   `--dump` (log only), `--ingest`, `--from-bots-only`, `--author-id`,
   `--channel-id`. **Token auto-grab** (`zargar/tools/discord_token.py`): the
   desktop app stores your token in leveldb, AES-GCM-encrypted under a DPAPI
   key bound to your Windows user; the tool decrypts it the way Discord does
   (ctypes `CryptUnprotectData` + `cryptography` AESGCM — no new deps), so the
   gateway auto-grabs it and you never touch DevTools. Works only as the same
   Windows user (DPAPI feature). Output is account-access-equivalent — never
   shared/committed.

1. **[BUILT 2026-08-28] Windows notification listener** —
   `zargar/tools/discord_watch.py`. WinRT `UserNotificationListener` (pywinrt
   `winrt-Windows.UI.Notifications[.Management]` packages) polls delivered
   toasts, filters Discord's app id (`com.squirrel.Discord.Discord`), posts
   new ones to `POST /api/ingest/manual` (`source_name="auto"` — the toast
   title carries the sender for source detection). Proven on this laptop:
   access ALLOWED, full title+body text readable, stable ids, timestamps.
   *Caveats:* Discord must be running with DM notifications on; focus
   assist/DND suppresses delivery; toasts may truncate long embeds; **the
   exact toast shape of an OWLS embed DM is still unobserved** — the watcher
   logs every toast to JSONL precisely to learn it. First real alert decides
   whether this path suffices alone.
2. **Window-capture OCR fallback** — if embed DMs arrive as unusable toast
   text ("sent you a message"), periodically capture the Discord window and
   push the image through the existing screenshot-transcription intake. More
   moving parts; only if (1) under-delivers.
3. **Phone relay** — Android (Tasker/Notification Listener) or iOS Shortcuts
   forwarding Discord push text to `POST /api/ingest/manual` over Tailscale.
   Good redundancy when the laptop sleeps; not built.
4. **Ask OWLS for programmatic delivery** (their own bot/API/email) — the
   cleanest possible path if they offer it; zero code on our side beyond the
   existing email webhook.

## 3. Build phases

- [x] **P1 — probe + watcher** (2026-08-28): listener POC proven; `discord_watch.py`
  with `--dry/--once`, JSONL capture of every toast, app-id filter, ingest POST.
- [x] **P2 — extraction understands alert grammar** (2026-08-28): `premium`
  field (contract price ≠ stock entry), OPEN/CLOSE/TRIM/Update grammar +
  boilerplate-ignore in the prompt, `Signal.premium` column + wire field.
- [x] **P3 — Tips Analyst v1** (2026-08-28): `techniques/tip/analyst.py` —
  tool-use agent (quote/bars/expiries/chain/flow/source-scorecard/earnings),
  advisory opinion (`take|watch|skip`, contract, limit premium, qty within
  budget, invalidation, rationale) stored on `extraction.analyst`, journaled
  `SignalAnalyzed`, rendered on the tip card. Fail-open, tool budget
  `techniques.tip.analyst_max_tools`, off-switch `techniques.tip.analyst_enabled`.
- [ ] **P4 — first live alert** (needs a real DM): run
  `discord_watch.py --dry` through a trading day; inspect the JSONL for the
  OWLS toast shape; fix the filter/parse; then drop `--dry`. Decide toast vs
  OCR-fallback here.
- [x] **P4b — source selection (allowlist)** (2026-08-28, user: "I don't want
  EVERY notification"): the gateway is now an ALLOWLIST, not a firehose.
  - The gateway reports its **catalog** (every DM + readable text channel, from
    the READY payload — names, grouped by server) to `POST /api/tip/discord/catalog`.
  - The user picks sources in the app (**Tips > Sources > Discord**): a toggle per
    DM/channel, each mapped to its own source name (so jon-and-kian and muggzone
    build separate scorecards); `botsOnly` per entry. Stored in
    `techniques.tip.discord.watch`; `GET/PUT /api/tip/discord/watch`.
  - The gateway polls the watchlist every 30s and ingests ONLY enabled channels
    (empty watchlist ⇒ nothing — personal DMs never become tips). Manual flags
    (`--all-dms`, `--from-bots-only`, `--channel-id`, `--author-id`,
    `--include-self`) remain for testing. **Channels work the same as DMs** — no
    Discord notification settings needed; if the account can read the channel,
    the gateway sees it.
  - VERIFY on a busy guild channel: message events for large servers may need a
    channel-subscribe frame (op 14); DMs and small guilds deliver without one.

- [x] **P4c — analyst run history + live view + process-on-demand** (2026-08-28):
  the Tips analyst now persists a full **TipAnalystRun** per appraisal —
  tools available, every LLM turn, every tool call + args + result, the final
  verdict — streamed live on the `tip_analyst` bus topic (WS type `tipAnalyst`).
  UI: **Tips > Analyst** tab (`/inbox/analyst`, run deep-link
  `/inbox/analyst/<runId>`) = a run list + timeline play-by-play with a
  copyable run id; it follows a running appraisal live (WS) and polls as a
  fallback. `GET /api/tip/analyst/runs[/{id}]`. A **"▶ tip"** action on each
  Discord source fetches its last message and runs it through the pipeline on
  demand (`POST /api/tip/discord/process-last`, served by the gateway peek
  loop) — pressing it jumps to the Analyst tab, which polls every 4 s so the
  run appears without a refresh. Rebuilt 2026-08-28 after first live use:
  timeline nodes + cards (SVG icons), analyst prose rendered as rich text,
  tool results folded behind a one-line summary, auto-scroll that follows the
  tail only while the user is at it, verdict card; tip rows and proposal cards
  link to their run ("analysis" / "view the analysis"). **Process outcomes are
  reported** (2nd live find: a non-tip message looked like silence): the
  gateway posts every "▶ tip" result to `POST /api/tip/discord/process-result`
  (fetch error / nothing to ingest / "did not extract as a trade tip" / the
  signals + analyst run ids) and the Analyst tab shows a progress bar that
  polls it — auto-opens the run on success, states the reason otherwise, and
  calls out a dead intake after 90 s.

- [x] **P4d — shared tips knowledge (notes)** (2026-08-28): `tip_notes` table —
  durable notes scoped `general` / `source:<name>` / `ticker:<SYM>` /
  `signal:<id>`. Every analyst run is handed the notes matching its tip
  (`techniques.tip.analyst_notes_max`) in the prompt and can write its own via
  the **save_note tool** (journaled `TipNoteAdded`). Born from the SPY 750P
  alert ("downside protection for my Oct-Dec calls" — context that matters at
  exit time, weeks later). UI: the **Knowledge** panel on Tips > Analyst
  (list/add/delete; a note links back to the run that saved it).
  API `GET/POST /api/tip/notes`, `DELETE /api/tip/notes/{id}`.
- [ ] **P5 — alert lifecycle → book management**: an `Update/TRIM/CLOSE` from
  the same source+ticker should attach to the OPEN signal (dedupe-style key)
  and drive the immediate book's exit — giving a *source-managed* exit
  counterfactual next to our policy exits on the scorecard. Design first; the
  shadow books must never double-count. (save_note is the stopgap: the analyst
  records lifecycle context so a later run knows.)
- [x] **P6 — analyst → proposal handshake + real vehicles** (2026-08-28): the
  proposal now trades the SAME vehicle the books do. Bug found live: the SPY
  750P hedge tip proposed **SELL 1 SPY @ 769** (short shares at the underlying
  ask) while the books correctly bought the put. `create_from_signal` rebuilt:
  an analyst `take` naming a contract proposes THAT contract (BUY to open, its
  limit/qty); else the book's expression contract; a bearish tip with no usable
  put proposes NOTHING (shorts are puts only); shares keep the bracket. Sized
  by the source's per-tip budget (was 5% of equity). Context now carries
  `vehicle`, `explain` (plain-language "what Approve does"), `analystRunId` +
  the analyst verdict — the card links straight to the run. **Full auto**:
  `mode: auto` sources self-approve the proposal via the same `approve()` path
  a human click takes (RiskGate inside, `decided_via="auto"`) — but only when
  the analyst said `take` (or is off), and a LIVE portfolio additionally needs
  `techniques.tip.allow_live_auto` (default off).
- [x] **P7 — launched by start.ps1** (2026-08-28): `scripts\start.ps1` opens
  the gateway listener in ITS OWN window via `scripts\discord-intake.ps1`
  (waits for the API, mints a 30-day local session so ingest passes auth,
  auto-grabs the token, runs the gateway `--from-bots-only --ingest`). A
  restart stops the prior intake first (matched by command line) so windows
  never stack. Opt out with `-NoDiscord`; run standalone with
  `scripts\discord-intake.ps1` (`-All`, `-DumpOnly`, `-NoWait`). Still TODO:
  a health line on the Tips page ("intake: watching / stalled / off").
  NOTE: like the app, it needs `backend\.venv` — runs from the main checkout,
  not a worktree.

- [x] **P8 — intake runs: the whole message streamed live + update review**
  (2026-08-28, after the EvaPanda positions-recap dead end: 6× "verification
  failed", no analyst run, "refreshed page showed me nothing new"). Every
  processed message now creates ONE **intake run** (`TipAnalystRun.kind=
  "intake"`) the moment processing starts — extraction progress, per-signal
  verification verdict WITH the failed checks spelled out, and appraisal
  hand-offs (linked) all stream live on the same `tip_analyst` topic, so the
  Analyst tab always has a run to watch (auto-focused on start). When any
  extracted signal is discarded by verification, the SAME run continues into
  **review mode** (`IntakeRun.review`, off-switch `techniques.tip.
  review_enabled`): the analyst reconciles the update against the desk —
  new tools **`get_positions`** (OUR portfolios' share/option positions +
  managed 2b positions; shadow books excluded) and **`get_open_tips`**
  (open tips by source/ticker with status + analyst verdict), both also
  available to every appraisal — saves durable notes (exits, adds, the
  source's open book) and reports `missed_tip` when a line verification
  discarded was actually a fresh call. Fixes ridden along: `ticker_resolves`
  is now a PARKING check ("no market data yet" is a feed state, not a bad
  tip — the AMZN "Added Today" case), and a cold symbol forces one
  `feed.poll_once()` sweep instead of losing the race against Yahoo's ~20 s
  backoff. Gateway reports + `ProcessResultBody` carry `intakeRunId`; the
  process banner focuses it.

## 4. Open questions

- Does the OWLS DM toast carry the embed text or a stub? (P4 decides.)
- Multiple channels: DM role currently only jon-and-kian — subscribe more
  blue-section roles as trust builds; each maps to its own source name.
- Toast truncation length (~2 lines visible; listener may expose more).
- The laptop lid: intake dies when the machine sleeps — phone relay (option
  3) is the eventual answer, or the eventual VPS.
