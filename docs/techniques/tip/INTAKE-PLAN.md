# Discord alert auto-intake + the Tips Analyst — research & build plan

*2026-08-28. POC scope: the user's laptop, experimental, not production. The
user is in the OWLS Capital Discord; the server's "Reaction Roles" blue
section DMs alert copies to members (confirmed: "@jon and kian DM" role
added 2026-08-28). Alerts are bot embeds ("OWLS Capital Clanker") with a
strict grammar and their own timestamps.*

## 0. The boundary, restated (supersedes the blanket "no Discord" line)

| | verdict | why |
|---|---|---|
| User-token automation ("self-bot", discord.py-self, reading DMs via the API as you) | **NEVER** | Explicit Discord ToS violation; account termination risk. Stays on the never-list. |
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
- [ ] **P5 — alert lifecycle → book management**: an `Update/TRIM/CLOSE` from
  the same source+ticker should attach to the OPEN signal (dedupe-style key)
  and drive the immediate book's exit — giving a *source-managed* exit
  counterfactual next to our policy exits on the scorecard. Design first; the
  shadow books must never double-count.
- [ ] **P6 — analyst → proposal handshake**: a `take` opinion on a
  proposal-mode source pre-fills the proposal with the analyst's contract +
  limit; human still approves. Auto mode stays scorecard-earned.
- [ ] **P7 — watcher as a service**: run `discord_watch.py` under the
  engine's process (optional task) or a Scheduled Task at logon; health line
  on the Tips page ("intake: watching / stalled / off").

## 4. Open questions

- Does the OWLS DM toast carry the embed text or a stub? (P4 decides.)
- Multiple channels: DM role currently only jon-and-kian — subscribe more
  blue-section roles as trust builds; each maps to its own source name.
- Toast truncation length (~2 lines visible; listener may expose more).
- The laptop lid: intake dies when the machine sleeps — phone relay (option
  3) is the eventual answer, or the eventual VPS.
