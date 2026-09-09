# Gateway envelope — design + build plan (Codex audit finding 2)

**Date:** 2026-09-09 (overnight build, staged for Codex review — NOT deployed).
**Problem (audit, confirmed in code):** the receive loop awaits every message's
full downstream processing (mirror POST + a 200s-timeout ingest), sharing the
path with heartbeat ACKs — a slow message can zombie the connection. Reconnects
re-identify with no gap recovery (messages during a disconnect are silently
lost). The ingest body carries no Discord message id or posting time, so
dedupe happens only after a paid extraction. MESSAGE_UPDATE is ignored and the
mirror never revises. Mirror failures are suppressed, non-2xx unchecked.

## Design

**Envelope.** Every matched MESSAGE_CREATE / MESSAGE_UPDATE becomes
`{kind, messageId, channelId, postedAt, editedAt, sourceName, entry, em}` +
the raw message. Identity travels the whole path: the mirror row, the ingest
body (`messageId`, `postedAt`, `editedAt`), and `RawContent.meta`.

**Receive path stays hot.** `_on_frame` only matches (dict lookups) and
enqueues (`put_nowait` on a bounded queue, 500). Heartbeat ACKs are handled
before dispatch as today. On a full queue the envelope goes to the disk spool
instead of blocking — receive never waits on downstream.

**Workers + per-channel ordering.** Two workers drain the queue; a per-channel
`asyncio.Lock` serializes processing within a channel (FIFO queue + lock =
in-order per channel, parallel across channels). All downstream I/O (JSONL
log, mirror, EM forward, ingest) happens in workers.

**Durable delivery.** Mirror and ingest responses are STATUS-CHECKED. A failed
delivery appends the envelope to `gateway_spool.jsonl` with an attempt count;
a retry loop replays the spool every 60s (max 5 attempts, then it stays in the
file as evidence with `dead: true`). The spool is loaded at startup — a crash
mid-delivery replays after restart. Downstream is idempotent: the mirror
upserts by message id; ingest dedupes by `messageId` BEFORE extraction.

**Forward cursors + gap recovery.** `gateway_cursors.json` records the last
processed message id per channel. On READY (fresh connect or reconnect) the
gateway REST-fetches `?after=<cursor>` per watched channel (≤3 pages) and
enqueues what it missed, oldest first. Cursor advances only after successful
processing.

**Edits are revisions, with an explicit re-review policy.** MESSAGE_UPDATE on
a watched channel: (1) mirror upsert — the row's text/images/edited_at update
when the revision is newer; (2) `POST /api/tip/discord/message-edited` — the
app finds the ingested content by `meta.messageId`, journals
`TipMessageRevised`, and stamps the content's meta. **Policy: no automatic
re-extraction and no automatic trading action from an edit.** The analyst sees
the revised text through the mirror it already searches; a human (or a future
explicit rule) decides whether a corrected strike/stop warrants action. Do not
blindly replay old entries into execution (audit's own constraint).

**App-side ingest identity.** `/api/ingest/manual` accepts `messageId`,
`postedAt`, `editedAt`. `messageId` dedupes BEFORE extraction (repeat delivery
costs zero LLM calls); `postedAt` feeds `stated_at` (the mirror's clock beats
model inference); all three land in `RawContent.meta`.

## Out of scope (documented, deliberate)

- Discord session-resume (op 6): reconnect+gap-recovery covers the loss window
  with far less protocol surface; revisit if reconnect frequency grows.
- EM-side identity/dedupe changes: EM forwarding moves off the receive path
  (worker) but its payload is unchanged — EM's desk owns that contract.
- Automatic re-review of edits (see policy above).

## Validation (the audit's cases)

slow-processing (receive stays hot — worker test), disconnect (cursor gap
fetch), duplicate delivery (pre-extraction dedupe), edit (revision upsert +
journal, no re-extraction), app-unavailable (spool + replay). Tests in
`tests/test_gateway_envelope.py`; gateway helpers are pure/instantiable
without a websocket.
