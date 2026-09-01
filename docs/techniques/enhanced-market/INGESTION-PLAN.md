# EM Ingestion Pipeline — TradeProElite → method evolution (EM-ONLY)

*2026-09-01. User decision: reverse the 2026-08-29 "session-workflow only"
call — the app should auto-capture the author's daily material (morning
video ~09:00 ET, watch-list posts) and feed EM's evolution loop. This
pipeline is EM's alone: it never touches Tip's intake, watch lists, or any
other technique. The Tip separation-guard tests stay authoritative.*

## What the connector sees (catalog review, 2026-09-01)

Guild **TradeProElite** (`836435995854897193`, 197 channels visible). The
EM-relevant channels:

| Channel | id | Value | Proposed role |
|---|---|---|---|
| VIP Members / ⚡em-alerts | `1126325195301462117` | the author's own alert stream | **watch** (live) |
| VIP Members / 🎯watchlists | `1126364741779062974` | the morning board + video links | **watch** (live) |
| VIP live trading / 📅stream-schedule | `1271705986654273580` | the ~09:00 ET broadcast link | **watch** (live) |
| VIP live trading / 🚀live-trading | `1127779034835718228` | live-session chatter | watch (low priority) |
| EMS Mentorship / 🔗recordings | `1293670143020499016` | stream recordings | **backfill + watch** |
| education / ☁ems-clouds, 🤑ems-guide, ✏educational, 📚resources | various | the CURRENT method corpus (the "book v2") | **one-time backfill** |
| VIP Members / 🏦stats | `1257419079237632091` | his performance claims | backfill (calibration) |
| Trade Alerts / 🚨evapanda, princeton, marko, oobie | various | analyst alert feeds | **stay TIP-owned** — already tip lanes; EM does not ingest them |

Key insight from the education category: `ems-clouds` — the EMA-cloud overlay
on all his charts has its own doc channel. The method's current form is
documented in-server; the book is the stale version.

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

## Build phases

| # | What | Size |
|---|---|---|
| 1 | Gateway: EM channel set + `/api/technique/ingest/message` inbox + notes table | ~1 day |
| 2 | `em_ingest` worker: video download → transcript → API (deps in its own venv) | ~1 day |
| 3 | Extraction pass + board coverage check + Validation-tab card | ~1 day |
| 4 | Education-channel backfill → method corpus; `get_method_notes` LLM tool | later (with EVOLUTION phase 3) |

## Boundaries (write them once, keep them forever)

- EM-only: no tip channel, no tip table, no tip setting is read or written.
  Overlapping interest (e.g. evapanda) stays tip's; EM gets its knowledge of
  those calls the same way it does today — not through this pipeline.
- Read-only Discord, same self-bot risk caveat as the gateway header; the
  user accepted that risk knowingly for their own account.
- Auto-arm is OFF by default; the pipeline proposes, the human disposes.
- Method changes still flow: note → §3 theory → variant sweep → §5 change log.
