# Consolidation batches — manifest hash `973ee053a87254fa3ebccf0edf68f4d9e3b0193c16b6f0e1a6a063dd42d8f365`

Missing ids: none

## A — resolve disputes
- `dbfd8177afae45169c68035cd024d0c3`
- `7e72fd7f0b57402a992f9053cab757c1`

## B — geometry family `consolidation-geometry-2026-09-14` (28 sources)

| id | revision |
|---|---|
| `dbfd8177afae45169c68035cd024d0c3` | 2 |
| `f120c2b934d845e1a43ca476abfa042d` | 1 |
| `779fbcf381824b90a70486a0f2bd5156` | 1 |
| `cac7bd77fa584a7aa94ccea0bbe078bf` | 1 |
| `17ec9915c4544b1cac5ff0c0e24e612d` | 1 |
| `eff8c28bbb6e4f869d041ecb70d4e4cd` | 1 |
| `e306ebce7b8a449c8b002aedbe5d2f80` | 1 |
| `3d08ab9088e84d1ebb47430f73dd00c5` | 1 |
| `c4d3b50cc3aa4755bcb1b997bb8f1cc3` | 1 |
| `557e30dac27a4a8baf5871a888daf035` | 1 |
| `d45362c1211647ed937bba7d095d3b04` | 1 |
| `6f6e925b642445b4861421950ad8bd7f` | 1 |
| `f39cf0b677cd459b83629b17735586b9` | 1 |
| `6083fce516f643549c7c6b7cf157109b` | 1 |
| `4ccdf6ed82d746c2813ca8529ecca28b` | 1 |
| `2de9051d8016477db25666b1da5c63cc` | 1 |
| `827e452760e24ddd805724239e823f6e` | 1 |
| `26c382310fa040968da675279fe2c91f` | 1 |
| `595642da39ae4804946a4cb5fc53f3f4` | 1 |
| `779afa13c4b34773a1c6d9371ae963a4` | 1 |
| `bca1cac46d1d44b4b33d30da0718e272` | 1 |
| `0477b92b4a2e4e7a9516cf7fa3bd9ac8` | 1 |
| `1d30159726a3411bb4f6b6763769b08e` | 1 |
| `7101b39773524751b658c62555ecf089` | 1 |
| `395ce53ec92d44bd82a43c479da77391` | 1 |
| `e6794b52a9f14188a3a85931e2da8003` | 1 |
| `082d17b5abfa4548b347687b368d99ea` | 1 |
| `0db23ca65130402683546b83422dc0f6` | 1 |

### Exact family text

```
RULE (adoption geometry — canonical family, consolidated 2026-09-14 from 28 rules; the code gate `techniques.tip.geometry_gate=enforce` validates -> repairs -> resizes -> revalidates BEFORE entry, and this rule is the analyst's statement of the same policy):
1. SIGN — long: stop < entry and every target > entry; short/put: mirrored. A wrong-side ladder is usually a DIRECTION-LABEL error (the level set fits the opposite direction): treat it as a defective plan, never "let the engine sort it out".
2. STOP WIDTH — the stop sits OUTSIDE the underlying's noise on the plan timeframe. Formulas are direction-explicit and in UNDERLYING units: long stopWidthPct = (entry − stop) / spot; short stopWidthPct = (stop − entry) / spot; a non-positive width is a SIGN failure. Momentum-chase entries: the stop sits below (long) / above (short) the impulse ORIGIN. High-priced names: judge percent, not dollars. A token stop that happens to PAY is still a defect. Numeric floors (0.75%, 1x plan-timeframe ATR) are the code gate's engineering floors, not this rule's authority; the high-beta / sub-$25 (1.5% or 1x daily ATR when the 5-session range > 10% of spot) and 15m-timeframe extra floors are HYPOTHESES under observation, not operative policy.
3. TARGET WIDTH — the first target clears the noise floor and the time box is long enough for the ladder; a premium-% stop must be translated to an underlying move and sit outside the stated invalidation; never a premium ratchet on a debit spread. The TP1 >= max(0.5x ATR, ~1R) figure is a HYPOTHESIS, not operative policy.
4. STALENESS — compare the plan entry to LIVE spot before adopting; consumed risk = long (entry − spot)/(entry − stop), short (spot − entry)/(stop − entry). A missing or stale spot, a missing ATR or a zero denominator means CANNOT JUDGE (recorded as such) — neither a pass nor a refusal. The 0.5 consumed-risk threshold is a HYPOTHESIS.
5. DUPLICATE-TICKET / STOP-KIND — the same defective geometry re-handed with a cosmetically re-cut ladder is ONE defect; a source's daily-close invalidation is never translated into an intraday GTC.
Evidence for every clause lives in scope evidence:adoption-geometry (14 dated cases, never injected). Repeated processing of one trade is not independent support. The AMZN/MU "absolute auto-refuse" memos were engine-defect evidence; with the pre-entry gate they are moot.
```

## C — kill-switch `consolidation-killswitch-2026-09-14`

```
RULE (session kill-switch — execution-integrity pause; replaces the 2026-09-04 clock clause and the 2026-09-11 geometry refinement, approved 2026-09-14): a fast stop on a trade whose final geometry, sizing, quote evidence and fills were all valid is a CLEAN losing trade — it produces a diagnostic, never a session-wide refusal; the daily-loss limits own that decision independently. Automated tip entries pause on an execution-integrity INCIDENT: a filled trade outside its risk plan, an exit on unconfirmed or delayed evidence, duplicate or unreconciled fills, a repeatedly failing entry path, or an identified shared-component failure. An incident is a persisted record (it survives restarts and date rollovers), scoped to what its evidence implicates, honoured by every automated entry path — auto-approval, already-armed plans, retries — never by exits, and released only on evidence bound to it that proves the repair (or an explicit, labeled human override). Missing evidence is a HOLD, not proof of validity. Runtime: techniques.tip.entry_pause_mode = integrity.
```

## D — 14 evidence records (scope evidence:adoption-geometry)

- source `4ccdf6ed82d746c2813ca8529ecca28b` rev 1 (1832 chars)
- source `2de9051d8016477db25666b1da5c63cc` rev 1 (1854 chars)
- source `827e452760e24ddd805724239e823f6e` rev 1 (2012 chars)
- source `26c382310fa040968da675279fe2c91f` rev 1 (1698 chars)
- source `595642da39ae4804946a4cb5fc53f3f4` rev 1 (1647 chars)
- source `779afa13c4b34773a1c6d9371ae963a4` rev 1 (1800 chars)
- source `bca1cac46d1d44b4b33d30da0718e272` rev 1 (1487 chars)
- source `0477b92b4a2e4e7a9516cf7fa3bd9ac8` rev 1 (1880 chars)
- source `1d30159726a3411bb4f6b6763769b08e` rev 1 (1764 chars)
- source `7101b39773524751b658c62555ecf089` rev 1 (2067 chars)
- source `395ce53ec92d44bd82a43c479da77391` rev 1 (1808 chars)
- source `e6794b52a9f14188a3a85931e2da8003` rev 1 (1797 chars)
- source `082d17b5abfa4548b347687b368d99ea` rev 1 (1956 chars)
- source `0db23ca65130402683546b83422dc0f6` rev 1 (2192 chars)

## Rollback

supersede the family note and the kill-switch note with expired:rollback (snapshot), then restore superseded_by=NULL on each source ONLY where its revision_no still equals the value in expected_revisions (+1 for the supersede snapshot); evidence records stay; re-dispute the two rules if the policy question reopens
