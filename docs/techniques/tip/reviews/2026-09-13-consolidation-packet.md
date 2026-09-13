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

**Old → new mapping:** the 32 ids above → `superseded_by = <new family id>`;
the 14 evidence notes are NEW rows citing the old ids in text. **Rollback:**
clear `superseded_by` on the 32 (all pointers, no deletes) and supersede the
new family note with `expired:rollback`.

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
entity on every path). The 22 rows at the old 2,000-character boundary are
truncated evidence; they keep their text and get a `[truncated at 2000 —
legacy]` marker only if/when edited (no reconstruction is possible).
`16f86a3a` (source:ab) and `0600aecb` (rule) link to experiment-batch
signals: their promotion provenance is a review item, not a deletion.

## 5. Sequence

1. Safeguards first (this release): scheduling, conflict-locked transactional
   apply, immutable revisions, scope validation, complete traversal.
2. Human decisions: §3 kill-switch conflict; which numeric branches are
   policy.
3. Then apply §1 via the audit batch path (one reviewed batch, rollback
   pointers), then §2 source profiles, then §4 confirmed reassignments.
4. KB-08 measurement gates any change to what the analyst is SUPPLIED.
