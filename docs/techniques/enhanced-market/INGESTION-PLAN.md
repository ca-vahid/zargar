# EM Ingestion Pipeline — TradeProElite → method evolution (EM-ONLY)

*2026-09-01. User decision: reverse the 2026-08-29 "session-workflow only"
call — the app should auto-capture the author's daily material (morning
video ~09:00 ET, watch-list posts) and feed EM's evolution loop. This
pipeline is EM's alone: it never touches Tip's intake, watch lists, or any
other technique. The Tip separation-guard tests stay authoritative.*

## What the connector sees (catalog review, 2026-09-01)

Guild **TradeProElite** (`836435995854897193`, 197 channels visible). The
EM-relevant channels:

| Channel | id | Value | Role (user-reviewed 2026-09-01) |
|---|---|---|---|
| VIP Members / ⚡em-alerts | `1126325195301462117` | **the pre-trading setups video link lands here** + his alerts | **watch (primary)** |
| VIP Members / 🎯watchlists | `1126364741779062974` | morning board posts | **watch** |
| EMS Mentorship / 🔗recordings | `1293670143062710916` | stream recordings | optional backfill only |
| education / 🤑ems-guide | — | slightly newer than the book, barely active | one-time backfill, low priority |
| education / ☁ems-clouds | — | **STALE — last message 2024** (user checked) | skip |
| VIP live trading / 📅stream-schedule, 🚀live-trading | — | the 9:30+ live session — not the pre-open material | skip |
| VIP Members / 🏦stats | `1257419079237632091` | his performance claims | backfill (calibration), low priority |
| Trade Alerts / 🚨evapanda, princeton, marko, oobie | various | analyst alert feeds | **stay TIP-owned** — EM does not ingest them |

User's ground-truth pass (2026-09-01): the education channels looked like a
living corpus from the catalog but are mostly stale — the method's current
form is carried by the **daily pre-trading video linked in em-alerts**, not
by any doc channel. The pipeline optimizes for that: two watched channels,
video capture keyed on em-alerts.

## Architecture (platform-rules compliant)

```
discord_gateway (existing tool process, read-only, shared transport)
   └─ EM channel set (techniques.enhanced_market.discord.channels)
        └─ POST /api/technique/ingest/message        (EM-scoped inbox)
             ├─ text/chart posts → method-note record
             └─ video links (x.com/broadcasts, mp4) → em_ingest worker:
                  yt-dlp → ffmpeg → faster-whisper → transcript
                  → POST /api/technique/ingest/transcript
                       → method-note record
                       → LLM extraction (flat schema, 1 call):
                            • today's board (symbols, levels, direction, vetoes)
                            • method-evolution claims (candidate §3 theories)
```

- **Gateway stays shared + read-only** (the ToS caveat and read-only boundary
  are unchanged); EM adds its own channel list and its own mirror namespace —
  no change to `techniques.tip.discord.watch`.
- **`zargar.tools.em_ingest`** is a separate tool process (same pattern as the
  gateway): it owns the heavy media deps (yt-dlp, ffmpeg, faster-whisper) so
  the app process never imports them. Transcription of a 5–15 min video ≈
  2–4 min CPU with the small model.
- **Storage**: `technique_method_notes` table (EM-scoped, `technique` column):
  date, channel, kind (video/post/chart), raw text/transcript, media path,
  extraction JSON, status (new/reviewed/actioned). This is the "memory of the
  method's evolution" — queryable later by the LLM tool belt (phase 3 of
  EVOLUTION-PLAN: `get_method_notes`).
- **Settings** (all new, EM-namespaced): `techniques.enhanced_market.discord.channels`,
  `.ingest.auto_transcribe` (default on), `.ingest.auto_extract` (default on),
  `.ingest.auto_plan_board` (default on: run deterministic plan runs on the
  extracted board and show an arm list — arming stays HUMAN unless
  `.ingest.auto_arm`, default OFF).

## The morning flow (target behavior)

1. ~08:45–09:15 ET: gateway sees the broadcast link in stream-schedule /
   watchlists → em_ingest downloads + transcribes (ready ~09:20).
2. Extraction produces the day's board → deterministic plan runs on the named
   symbols (no LLM per symbol) → the Validation tab shows "Author's board:
   N covered by armed plans, M new candidates, K rejected (reasons)" with
   one-click arm — the exact workflow done by hand on 08-31/09-01, automated.
3. Method-evolution claims (anything that contradicts or extends our rules)
   land as **candidate theories** with source + date — reviewed by a human or
   a Claude session before entering TRADING-RULES §3. **Nothing auto-changes
   live parameters — the EVOLUTION-PLAN governance is unchanged.**
4. Every note is kept; TRADING-RULES stays the judgement log; the notes table
   is the raw archive.

## Status: BUILT 2026-09-01 (phases 1-3), first end-to-end run same evening

What exists (all EM-namespaced, nothing else touched):

- **Gateway** (`zargar/tools/discord_gateway.py`): a second channel set loaded from
  `GET /api/technique/ingest/channels` (settings `techniques.enhanced_market.discord.channels`,
  default em-alerts + watchlists) and forwarded to EM's inbox BEFORE the tip match runs.
  The tip allowlist/mirror/intake are untouched (tests: a channel in both sets feeds both;
  an EM-only channel never mirrors or tips).
- **Inbox + notes** (`zargar/technique/ingest.py`, table `technique_method_notes`):
  dedupe on message id; video link -> `pending_transcript`; text posts -> extraction.
- **Worker** (`zargar/tools/em_ingest.py`, launcher `scripts/em-ingest.ps1`, its own
  venv `backend/.venv-ingest`): polls `/api/technique/ingest/pending`, yt-dlp -> mp3 ->
  faster-whisper (`small`) -> `POST /api/technique/ingest/transcript`; failures retry up
  to `ingest.transcribe_max_attempts` then mark the note `failed` (never silent).
- **Extraction**: one flat-schema read (`MethodExtraction`: summary, stance, symbols,
  board, claims, vetoes), effort low.
- **Board check**: deterministic plan runs (`analyze(plan=True, with_vision=False)`) on
  the named symbols -> armed / new (grade, run id) / rejected (closest trigger + reason).
  `ingest.auto_arm` default OFF - the Validation tab's **Author's board** card carries
  the Arm buttons.
- **API**: `/api/technique/ingest/{channels,message,pending,transcript,notes,board,notes/{id}[/extract|/board-check]}`.
- **Run it**: `scripts\start.ps1` launches the Discord intake AND the EM ingest worker
  windows (`-NoIngest` skips the worker); by hand: `scripts\em-ingest.ps1` (or `-Once`).

**First end-to-end run (2026-09-01 ~19:50 ET, verification instance on :8421 against
the test DB - the live server was elevated and could not be restarted from the
session):** the 09-01 broadcast link posted to the inbox -> worker transcribed
6.7 min in 93 s (4,799 chars) -> extraction (stance, board, 7 symbols, claims,
vetoes) in ~20 s -> board check 2 new / 5 rejected / 0 errors in ~15 s -> the
Author's board card rendered with Arm buttons. Fidelity note: speech-to-text
heard "SpaceX" and the model wrote SPCE - the prompt now carries a mis-hearing
hint (SPCX, CMG, NVDA, QCOM...).

**v2 end-to-end (2026-09-01 ~21:15 ET, :8421 test-DB instance, merged code):** fresh
note -> probe (`live=False`, title "TOP SETUPS") -> download -> transcript in 81 s ->
extraction `material=setups_brief`, stance cautious, symbols NVDA NFLX **SPCX** MU
AMZN GPRO V (the mis-hearing hint fixed SPCE -> SPCX) -> board check 2 new / 5
rejected in ~10 s; a re-post of the same link came back `duplicate`; the day view
kept the brief primary with the follow-up listed under "also today".

**LIVE on the production server since 2026-09-01 23:43 ET** (user's admin restart via
`start.ps1 -Detach`, which also opened the Discord intake and the EM ingest worker
windows). First live end-to-end at 23:50 ET: the 09-01 broadcast posted to the real
inbox -> the worker window transcribed it within ~2 min -> `setups_brief`, SPCX
correct -> board check 5 new / 2 rejected -> Arm buttons on the Validation tab.
Note for operators: the server is elevated again; restart it non-elevated when
convenient so future restarts work from any shell.

## The morning, unattended - as built (2026-09-01 evening, user Q&A)

1. **Recognition is deterministic, not AI.** Every message in the two EM channels
   becomes a note. A message carrying a media link (X broadcast / tweet / YouTube /
   mp4 - in the text, an embed card, or a video attachment: the forwarder surfaces
   all of them) is a *video* note; a text post >= 60 chars is extracted; an image-only
   post is kept as a *chart* note. The LLM only ever reads content - it never decides
   what to ingest.
2. **Live timing.** The link drops when he goes live. The worker first *probes* the
   link (`is_live`); while the broadcast runs it reports a DEFERRAL - no retry
   attempt spent, re-probe every `ingest.live_recheck_seconds` (60). When it ends,
   the full replay is downloaded and transcribed. After `ingest.live_max_wait_minutes`
   (45) the worker takes whatever replay exists and the note is marked *partial*.
   Typical: link 09:00, he ends 09:10-09:15, transcript + board by ~09:18.
3. **What is this item?** The extraction classifies `material`: setups_brief / alert /
   recap / other. Only setups_brief and alert earn plan runs; a recap or promo is
   stored (still searchable, still evidence) but never plan-checked.
4. **Supplementary messages.** Each later post is its own note and extraction; the
   day's view (`/api/technique/ingest/board`) keeps the video brief as the primary
   card and lists the rest under "also today" - a follow-up never replaces the brief.
   The same link re-posted within a day (pinned, echoed by a bot) is ONE video
   (`duplicate`, never transcribed twice).
5. **Nothing arms itself.** The card proposes; you click Arm; `ingest.auto_arm` stays off.

## Build phases

| # | What | Status |
|---|---|---|
| 1 | Gateway: EM channel set + `/api/technique/ingest/message` inbox + notes table | **built 2026-09-01** |
| 2 | `em_ingest` worker: video download → transcript → API (deps in its own venv) | **built 2026-09-01** (+ live-broadcast deferral) |
| 3 | Extraction pass + board coverage check + Validation-tab card | **built 2026-09-01** (+ material classification, today's view) |
| 4 | Education-channel backfill → method corpus; `get_method_notes` LLM tool | later (with EVOLUTION phase 3) — the education channels proved mostly stale, so this is low priority |

## Boundaries (write them once, keep them forever)

- EM-only: no tip channel, no tip table, no tip setting is read or written.
  Overlapping interest (e.g. evapanda) stays tip's; EM gets its knowledge of
  those calls the same way it does today — not through this pipeline.
- Read-only Discord, same self-bot risk caveat as the gateway header; the
  user accepted that risk knowingly for their own account.
- Auto-arm is OFF by default; the pipeline proposes, the human disposes.
- Method changes still flow: note → §3 theory → variant sweep → §5 change log.
