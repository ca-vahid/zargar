# Knowledge consolidation packet — KB-05 / KB-06 (2026-09-13)

**Status: PROPOSAL for review. Nothing here is applied.** Live store at
review time: 860 notes, 850 active, 59 active rules. Every proposal below
maps old ids → a proposed new revision, lists retained evidence and wording
changes, names the unresolved policy choices, and carries a rollback mapping
(supersession is a pointer; the archive is never deleted). Bulk apply waits
for the KB-01/02 safeguards (shipped alongside this packet) AND a human
decision on the policy conflicts in §3.

## 1. Geometry family — 32 live rules → 1 canonical family + evidence records

The 2026-09-04 consolidated VETO (`dbfd8177`) is the base. Since then the
analyst appended 27 "refinement / confirming case" rules that each restate
the base and add one increment. They are one family wearing thirty faces —
and each of them is re-injected into every run (68,592 characters of rules
before a single note or tool).

**Proposed canonical rule family `RULE (adoption geometry)`, one note with
five sections** (wording drafted from the originals; NO new thresholds
introduced — every number below already exists in a live rule):

1. **SIGN** — long ⇒ stop < entry and every target > entry (mirror for
   shorts). A wrong-side ladder is usually a DIRECTION-LABEL error: the level
   set is consistent with the opposite direction (`f120c2b9`) — refuse, do
   not "let the engine sort it out".
2. **STOP WIDTH** — `stopWidthPct = (entry−stop)/spot ≥ 0.75%` AND `≥ 1× ATR`
   of the plan timeframe (`dbfd8177`, `17ec9915`, `eff8c28b`, `e306ebce`);
   momentum-chase entries: stop below the impulse ORIGIN (`3d08ab90`);
   15m-timeframe plans: 1× ATR alone is not enough (`2de9051d`);
   high-priced names: dollars can look wide and still be token in percent
   (`827e4527`). *Branches marked HYPOTHESIS, kept as-is:* high-beta sub-$25
   names ≥ 1.5% or 1× daily ATR when the 5-session range > 10% of spot
   (`c4d3b50c`, `26c38231`, `595642da`).
3. **TARGET WIDTH** — TP1 ≥ max(0.5× ATR, ~1.0R) (`557e30da`); the time box
   must be long enough for the ladder (`d45362c1`); a premium-% stop must be
   translated to an underlying move and sit outside the stated invalidation
   (`6f6e925b`); never a premium ratchet on a debit spread (`f39cf0b6`).
4. **STALENESS** — compare plan entry to LIVE spot; refuse when consumed
   risk `(entry−spot)/(entry−stop) ≥ 0.5` (`779fbcf3`, `cac7bd77`).
5. **DUPLICATE-TICKET / STOP-KIND** — the same defective geometry re-handed
   with a cosmetically re-cut ladder is one defect (`779afa13`); a source's
   daily-close invalidation is never translated into an intraday GTC
   (`6083fce5`).

**Evidence records (NOT rules) — 14 dated cases become `general` evidence
notes referencing the family:** HOOD 9/02, MU 9/03×2, MRVL 9/03×2, RKLB 9/04,
MU 9/04×3 (in the base), then AMZN 8/31, META 8/31, MSFT 9/03 (pass), GOOGL
9/02 (pass), INTC 9/04, AMZN 9/03 (pass-then-lose), AMZN 9/07 (`e6794b52`),
RDDT 9/07, SOFI 9/08, ZURA 9/08, MU 9/07 ×2, AVGO 9/07 (paid), NVDA 9/08.
Repeated processing of one trade must not create independent support: the
AMZN and MU "ticker memo → absolute auto-refuse" lines (`e6794b52`,
`827e4527`) are **engine-defect evidence** (the pipeline hands token stops on
those names), not source/ticker policy — they move to evidence with a link
to geometry revision 2, which validates BEFORE entry and makes the ticker
memos moot once built.

**Old → new mapping:** the exact machine-readable list (every source id
with the `revision_no` it was judged at, its retained clause, and every
output record with its provenance) is §1a below; the apply batch MUST carry
those revision numbers as `expected_revisions` so a source edited after this
review aborts the whole batch (KB-02-B). **Rollback is itself a revision
transition, never a pointer edit:** (1) supersede the family note
(`superseded_by = expired:rollback`, snapshot reason `supersede`); (2) for
each source id, snapshot (reason `rollback`) and restore `superseded_by =
NULL` ONLY if its `revision_no` still equals the consolidation value — a row
edited after consolidation keeps its later revision and is listed for the
human instead of being overwritten; (3) evidence records stay (they cite,
they do not govern). The batch id and payload hash of the consolidation
receipt (`tip_knowledge_batches`) are the rollback's reference.

**Direction, units and missing inputs (corrects the long-only arithmetic
above):** long thesis `stopWidthPct = (entry − stop) / spot`, consumed risk
`(entry − spot) / (entry − stop)`; short / put thesis `stopWidthPct =
(stop − entry) / spot`, consumed risk `(spot − entry) / (stop − entry)`. A
non-positive width or a non-positive denominator is a SIGN failure (§1.1),
not a width or staleness failure. Entry, stop and spot are UNDERLYING prices
in the underlying's currency even when the vehicle is an option (premium
levels never enter these formulas); ATR is in the same units and the plan's
timeframe. A missing or stale spot (older than the desk's freshness bound),
a missing ATR or a zero denominator means **cannot judge** — the appraisal
records that reason; it is neither a pass nor a refusal of the trade.
**Authority:** 0.75 %, 1× ATR, 0.5 consumed risk and TP1 ≥ max(0.5× ATR,
~1R) exist only in LLM-authored notes; presence in a note is not approval —
each number is either approved by the human here or ships labeled
HYPOTHESIS. The family's unconditional "refuse" wording is replaced by:
"the geometry gate (revision 2) validates → repairs → resizes →
revalidates; the analyst refuses only what that sequence cannot repair".

**Evidence storage:** the 14 records do NOT go to `general` (automatically
retrieved with a reserved prompt allocation — that would put the case
histories back into every live context). They go to a scope that is never
auto-injected: `evidence:adoption-geometry` — a NEW prefix (allow-listed in
`normalize_scope`, excluded from `notes_for_tip`/rulebook selection,
reachable on demand through search and the analyst's notes tool, with a
guard test) — and that code change is a prerequisite of this batch.

### 1a. Machine-readable mapping (verified against the live store 2026-09-13)

Correction: the earlier "32 rules" was not reproducible from the store —
**29** live `rule` rows name the consolidated adoption-geometry VETO or are
the stop/exit-design rules the family folds in; the other three of the old
count could not be identified and are dropped. All 29 are `revision_no = 1`
at review time (the batch carries these as `expected_revisions`). Two of
the 29 are DISPUTED (`needs_human`, journaled 2026-09-13) and are EXCLUDED
from any batch until the kill-switch decision — and because one of them is
the family's base note, the family batch cannot apply before that decision.

```json
{
  "family": "RULE (adoption geometry)",
  "judgedAt": "2026-09-13",
  "expected_revisions": {"all 29 ids below": 1},
  "sources": [
    {"id": "dbfd8177", "role": "base: all five checks + CLOCK kill-switch clause", "status": "DISPUTED — excluded"},
    {"id": "7e72fd7f", "role": "kill-switch on GEOMETRY, not the clock", "status": "DISPUTED — excluded"},
    {"id": "f120c2b9", "clause": "1 SIGN — wrong-side ladder is a direction-label error"},
    {"id": "779fbcf3", "clause": "4 STALENESS gate"},
    {"id": "cac7bd77", "clause": "4 STALENESS — consumed risk ≥ 0.5 (threshold needs approval)"},
    {"id": "17ec9915", "clause": "2 STOP WIDTH — ≥ 1× ATR of the plan timeframe"},
    {"id": "eff8c28b", "clause": "2/5 enforcement of checks 2 + 5"},
    {"id": "e306ebce", "clause": "2 STOP WIDTH — token stop voids designed risk"},
    {"id": "3d08ab90", "clause": "2 STOP WIDTH — momentum-chase stop below the impulse origin"},
    {"id": "c4d3b50c", "clause": "2 high-beta / sub-$25 branch", "label": "HYPOTHESIS"},
    {"id": "557e30da", "clause": "3 TARGET WIDTH — TP1 ≥ max(0.5× ATR, ~1R); recycled-levels red flag (threshold needs approval)"},
    {"id": "d45362c1", "clause": "3 time box must match the ladder"},
    {"id": "6f6e925b", "clause": "3 premium-% stop translated to an underlying move"},
    {"id": "f39cf0b6", "clause": "3 never a premium ratchet on a debit spread"},
    {"id": "6083fce5", "clause": "5 stop KIND matches the source's stated invalidation"},
    {"id": "4ccdf6ed", "clause": "2 pre-adoption arithmetic gate", "case": "fifth confirming case"},
    {"id": "2de9051d", "clause": "2 15m-timeframe extra floor", "label": "HYPOTHESIS", "case": "seventh confirming case"},
    {"id": "827e4527", "clause": "2 high-priced names: percent, not dollars", "case": "tenth confirming case"},
    {"id": "26c38231", "clause": "2 high-beta branch", "label": "HYPOTHESIS", "case": "eighth confirming case"},
    {"id": "595642da", "clause": "2/3 (high-beta branch)", "label": "HYPOTHESIS", "case": "ninth confirming case"},
    {"id": "779afa13", "clause": "5 duplicate-ticket detector", "case": "eleventh confirming case"},
    {"id": "bca1cac4", "case": "1 SIGN — third confirming case + cost dimension"},
    {"id": "0477b92b", "case": "2 — a token stop that PAYS is still a defect"},
    {"id": "1d301597", "case": "affirmative counterpart — what a PASSING adoption looks like"},
    {"id": "7101b397", "case": "affirmative counterpart, extended"},
    {"id": "395ce53e", "case": "affirmative counterpart — third passing case"},
    {"id": "e6794b52", "case": "sixth confirming case — AMZN ticker memo (ENGINE-DEFECT evidence, links geometry rev 2)"},
    {"id": "082d17b5", "case": "twelfth confirming case"},
    {"id": "0db23ca6", "case": "thirteenth confirming case + duplicate reduce-order hygiene (also a PLATFORM-RULES finding)"}
  ],
  "outputs": [
    {"out": "F", "kind": "rule", "scope": "rule", "text": "the five-section family in §1 with the corrected formulas", "provenance": "the 27 non-disputed ids (superseded_by = F.id)"},
    {"out": "E01..E14", "kind": "evidence", "scope": "evidence:adoption-geometry", "one per case-bearing id": ["4ccdf6ed", "2de9051d", "827e4527", "26c38231", "595642da", "779afa13", "bca1cac4", "0477b92b", "1d301597", "7101b397", "395ce53e", "e6794b52", "082d17b5", "0db23ca6"], "provenance": "the id it is extracted from, cited in text; the id itself is superseded by F, not by E"}
  ],
  "rollback": "revision transitions per §1 (family → expired:rollback; each source restored only at its recorded revision)",
  "receipt": "tip_knowledge_batches row of the apply run (batch id + payload hash) — filled at apply time"
}
```

**Unresolved (needs the user, not the summarizer):**
- **Session kill-switch: clock vs geometry** — `dbfd8177` says one stop-out
  within ~10 minutes pauses all adoptions; `7e72fd7f` says only when the stop
  was BELOW the floor (good geometry that loses is not a pipeline defect).
  The code (`adoption_killswitch`, 5-minute rule) implements the CLOCK
  version. Geometry rev 2 changes the question again (validation moves
  pre-entry). **Decision required** before either rule is superseded; until
  then BOTH stay flagged `needs_human` and both are supplied (labeled
  DISPUTED) — the summarizer must not pick.
- Which of the numeric branches (high-beta 1.5%, 15m-timeframe extra floor)
  are approved policy vs hypothesis — currently all read as rules.

## 2. Source profiles — MuggZone (256 notes) and jon-and-kian

Zero exact duplicates, but repeated narration of single messages. The four
reviewer-named pairs, checked in full text:

| pair | verdict | what the merge must KEEP |
|---|---|---|
| `80032ab1` / `2d19c548` (12:00 "still in spx puts") | same event, twice | `2d19c548`'s addition: "still in X" is the counterpart of his "all out" line; `80032ab1`'s: the 11:38 addendum reference (TP1 2.50, "7700 major res") |
| `1fd75dc2` / `9a6f2466` (12:18 king-node dashboard) | same event, twice | BOTH decodings of the 3-panel dashboard (histogram + GEX ladder); the trim/mark timeline (2.40 @12:11, 2.85 @12:17) from `9a6f2466` |
| `a70e1be1` / `3877ef96` (14:23 NOW/ADBE "gap down") | same event, twice | the vocabulary rule + the full-format counter-example ("Took ORCL 9/25 $200 calls … starter size @everyone") from `3877ef96` |
| `1c074895` / `7e5f5259` (10:11 Kian stand-down) | same event, twice | "log-only; only the OWLS Clanker bot OPEN/CLOSE format is adoptable" from `7e5f5259`; the negative-filter use from `1c074895` |

**Proposed shape (KB-05):** one versioned **source interpretation profile**
per source (`source:<name>`, marked core-like for the analyst: format
vocabulary, adoptable shapes, lifecycle words, known trap patterns), plus
separate **dated evidence notes** keyed by the source message id
(`messageId` in text, and — once KB-05 lands in code — a `source_event`
field) so re-reading the same message is idempotent instead of a second
"independent" observation. The 256 MuggZone notes reduce to ≈1 profile +
≈40 evidence records (one per distinct message/day) — counts are
observations, not deletion quotas; every removed narration is superseded,
never deleted.

## 3. Policy vs fact (KB-06) — separation table

| class | examples | where it belongs |
|---|---|---|
| approved policy | the five geometry checks; "skip never arms" (`91fc550c`); "STO covered calls are never mirrorable" (`5777141f`) | `rule`, core |
| hypothesis | high-beta floors; 15m extra floor; "trail after TP1 on catalyst tips" (TRADING-RULES) | `rule` labeled HYPOTHESIS, or TRADING-RULES "under observation" |
| engine defect | AMZN/MU token-stop memos; duplicate reduce-order hygiene (`0db23ca6`) | evidence + PLATFORM-RULES finding, not a trading rule |
| source interpretation | MuggZone vocabulary; Kian free-text is log-only | source profile |
| dated market/position observation | "desk holds X" lines inside profiles | NOT knowledge — current holdings come from `get_positions`; such lines get a factual expiry that citation cannot extend |

## 4. Orphan scopes (KB-07) — reassignment list, evidence-backed, NOT applied

Eleven live rows with an empty entity. Each proposal below quotes the
row's own text; per the reviewer, none is assigned merely from a leading
word — where the text names the ticker as its subject it is a proposal
**requiring confirmation**; otherwise quarantine.

| id | scope | evidence in text | proposal |
|---|---|---|---|
| `9a367c9c` | ticker: | "HOOD — reconciliation from eva's 9/1 recap: her HOOD 120C 9/18 @3.10…" | `ticker:HOOD` (confirm) |
| `755709da` | ticker: | "CRWV / AbTrades campaign opened 2026-08-31…" | `ticker:CRWV` (confirm) |
| `24433a69` | ticker: | "CRWV — AbTrades' actual open (2026-08-31 12:45 ET…)" | `ticker:CRWV` (confirm) — likely duplicates `755709da` |
| `c3d6c596` | ticker: | "TSLA 2026-08-31 14:40 ET — MuggZone put a hard number on his live 9/2 355P" | `ticker:TSLA` (confirm) |
| `80090b73` | ticker: | "MRVL — 2026-09-01 15:57 MuggZone posted an UNNAMED-TICKER gamma/level map" | `ticker:MRVL` (confirm — the text itself says the map was unnamed) |
| `12bb5a3d` | ticker: | "MRVL 2026-09-01 16:00-16:12 — full two-sided package" | `ticker:MRVL` (confirm) |
| `336fff65` | ticker: | "CRDO — MuggZone 2026-09-01 20:57 image VIEWED" | `ticker:CRDO` (confirm) |
| `c87e5f4d` | ticker: | "MU — eva's 2026-09-01 sequence" | `ticker:MU` (confirm) |
| `5d1df867` | signal: | "META 9/2 590C (MuggZone 2026-08-31 19:09): 'no tp/sl'" | needs the signal id → `signal:<id>` if recoverable, else `ticker:META` evidence |
| `181c1677` | signal: | "[MuggZone / CRWV 9/11 105C] 11:25 'theres 2nd tp'" | needs the signal id; else `ticker:CRWV` evidence |
| `e2120ae0` | signal: | "[MuggZone / CRWV 9/11 105C] image VIEWED (msg 1546904697426681969)" | same as above |

New orphans can no longer be written (the service now refuses an empty
entity on every path).

**The 22 rows at the old 2,000-character boundary — checked against run
evidence (2026-09-13, read-only script `truncation_evidence.py`; corrects
the earlier "no reconstruction is possible" claim):**

- **19 are PROVEN truncated at storage**: their `run_id` resolves to a
  `tip_analyst_runs` row whose trace holds the `save_note` tool call with the
  full original text (2,006–2,335 chars), of which the stored 2,000 chars are
  a prefix. Ids (trace length): `9231fc1a` (2198), `0138e498` (2006),
  `f92d5ba9` (2335), `a186c7b8` (2128), `2c8de563` (2177), `1c2fb602` (2176),
  `1c86f3e3` (2124), `03583bcb` (2074), `b5eac6e0` (2224), `be144e3f` (2082),
  `8a7ed522` (2022), `869c257e` (2123), `e81e0a1a` (2093), `4929b203` (2158),
  `aead7ddb` (2062), `9ca7094d` (2156), `ef811150` (2041), `120fe04e` (2101),
  `ad1e485e` (2090). The `TipNoteAdded` journal payloads carry the already
  truncated text (2,000), so the trace is the only complete copy.
  **Proposed restoration (NOT applied):** one reviewed batch that, per row,
  snapshots the current text (revision 1, reason `edit`) and writes the
  trace text as revision 2, author `restore-from-trace:<run8>`, journaled —
  a revision transition, never an in-place overwrite; rows edited since
  (revision_no > 1 at apply time) are listed for the human instead.
- **3 have NO evidence** (`aac9ee3e`, `b3d7a110` experiment:b1; `1d7d118a`
  experiment:b2 — batch-review runs whose traces hold no `save_note` step):
  they stay labeled "possible truncation" in this packet only; nothing is
  written to them.

`16f86a3a` (source:ab) and `0600aecb` (rule) link to experiment-batch
signals: their promotion provenance is a review item, not a deletion.

## 5. Sequence

1. Safeguards first (v0.7.62 + v0.7.63): scheduling, conflict-locked
   transactional apply with receipts and revision checks, immutable
   revisions, scope validation, complete traversal, PROPOSE-ONLY default.
2. Prerequisite code: the `evidence:` scope (non-injected) and its guard
   test; restoration batch for the 19 trace-recoverable truncated notes
   (revision transitions, reviewed).
3. Human decisions: §3 kill-switch conflict (both rules are flagged
   DISPUTED through the journaled path since v0.7.63); which numeric
   branches are policy; approval of each threshold in §1.
4. Then apply §1 via the audit batch path with `expected_revisions` from
   §1a (one reviewed batch, rollback as a revision transition), then §2
   source profiles, then §4 confirmed reassignments. The trading-floor merge
   the automatic audit applied on 2026-09-13 (`31b0b7c7` + sibling →
   `571a93dc`) is reviewed in the same sitting: keep, or roll back the same
   way.
5. KB-08 measurement gates any change to what the analyst is SUPPLIED.
