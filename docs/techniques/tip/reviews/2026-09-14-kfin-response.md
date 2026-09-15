# Known-work completion packet (KFIN-01..10) — development response

Packet: `C:/Cursor/zargar-codex/docs/techniques/tip/reviews/2026-09-14-known-work-completion-packet.md`
(baseline main `561a859`, live v0.7.77). Work split across branches; each merged only after its
own suites and the integrated checks; deployed under the existing gates. Practice scope, the
approved risk budgets (`risk_pct` 1%, `risk_budget_per_tip` 0) and propose-only maintenance are
unchanged.

## KFIN-05 — manifest / rollback safeguards (this desk, branch `claude/kfin-05-10`)

`techniques/tip/consolidation.py` rewritten around ONE canonical payload hash
(`payload_hash`) shared by the client tool (`tools/tip_consolidation.py`) and the server:
every release carries the reviewed revision, every batch (merge or expire) its id, scope,
sorted sources, expected revisions and the sha256 of its exact output text, every evidence
record its scope, source id + revision and content sha. The server recomputes the hash from
the payload it receives — a changed text under the same claimed hash is refused before any
write. All reviewed revisions (including the dispute releases) are validated before ANY
mutation; a durable wrapper receipt (`tip_knowledge_batches` id `consolidation:<hash>`) records
progress step by step and answers an identical replay idempotently even after the sources
were superseded; a different payload under an already-applied batch id is refused (the batch
receipt carries the wrapper identity; pre-KFIN receipts are matched on their recorded
sources + output text). Evidence identity = source id + revision + content hash in the note
marker. Rollback guards come from the ACTUAL receipt transitions (`rollback_plan`: revision at
supersede, new rule id, release from→to, evidence ids), never "+1 per source". The wrapper
also applies reviewed REJECTIONS (expire batches) — used for the three quarantined promotions
(`--reject-proposals`, manifest in `2026-09-14-policy-proposal-rejection/`).

Tests: `tests/test_tip_knowledge.py::test_consolidation_payload_integrity_kfin05` (changed text
under the same hash, stale revision during resolution, changed evidence revision, different
payload under an applied batch id → refused with nothing written; identical replay idempotent;
receipt + rollback plan; expire batch) and the updated
`test_reviewed_consolidation_applies_through_audited_paths`.

## KFIN-10 — historical research with an honest disposition (this desk)

`tools/tip_late_evidence.py` reproduces the reviewer's cohort (33 late messages → 9 candidate
messages → 10 option branches + 1 share branch) from the live DB and attempts retrieval through
the already-authorized provider (Alpaca market data, the keys `research/optiontrades.py` uses):

| Evidence | Result |
|---|---|
| Option trade prints (±5 / +60 min around the post) | retrieved for all 10 contracts: 10,768 prints with exchange and condition codes |
| Option 1-minute bars (13:30–20:00 UTC) | retrieved for all 10: 2,429 bars |
| Contemporaneous NBBO (bid/ask/sizes) | **UNAVAILABLE** — `/v1beta1/options/quotes` answers HTTP 404 under this entitlement; recorded per case |
| MRNA shares | descriptive underlying path from local exchange bars only (the stated "risk at the 8D" names no indicator/trigger/fill policy) |

Every retrieval is persisted in the runtime table `historical_evidence` (provider, kind, symbol,
signal/message id, window, status, reason, record count, first/last timestamp, HTTP status,
request URL without credentials, raw records) and summarised in
`2026-09-14-late-evidence/disposition.md` + `evidence.json`. Disposition per option case:
prints and bars exist with provenance; because no executable quote exists at the alert, no
fill, spread, slippage or missed-profit figure is derived. Prospective sampling of the full
eligible cohort (skips and blocked candidates included) is built under KFIN-09.

**Three unproven truncated notes** (`aac9ee3e…`, `b3d7a110…` in `experiment:b1`, `1d7d118a…` in
`experiment:b2`, all 2,000-char cuts by the batch-review writer): no run trace holds the full
text and no authoritative original exists in the mirror; disposition = retain the original
truncated text at revision 1 with the provenance recorded as unresolved (no restoration, no
tombstone). They are experiment-scope records and are never injected.

**Three quarantined promotions** (`e02fbae2…`, `e7a30cb4…`, `2c8ed73d…`): closed through an
explicit reviewed rejection, not by clearing `needs_human` — released at their reviewed revision,
expired in one batch with the stated reason, and preserved verbatim as
`evidence:policy-proposals` records with the reviewer's rationale. Applied after the deploy
through the hardened wrapper; manifest hash and receipt recorded below.

## Other tags

| Tag | Branch | Status |
|---|---|---|
| KFIN-01/02 | `claude/kfin-01-02` | see the merged PR's report |
| KFIN-03/04 | `claude/kfin-03-04` | see the merged PR's report |
| KFIN-06 | `claude/kfin-06-suite-failures` | see the merged PR's report |
| KFIN-07 | `claude/kfin-07-multi-image` | see the merged PR's report |
| KFIN-08 | `claude/kfin-08-mk-shadow` | see the merged PR's report |
| KFIN-09 | `claude/kfin-09-experiments` | see the merged PR's report |
