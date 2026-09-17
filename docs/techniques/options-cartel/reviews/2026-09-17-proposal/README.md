# 2026-09-17 proposal package — Lane A (long base breakout)

Implementation desk handback for review. Read in this order: BOTTLENECKS.md (what actually
happened, from records), FUNNEL.md (every gate and its outcome class), RULE-MATRIX.md (where
each requirement comes from), PROPOSAL.md (the lane, acceptance criteria, incremental plan).

## Branch, commit, revisions examined

- Worktree `C:\Cursor\zargar\.claude\worktrees\session-2026-09-17`, branch
  `claude/cartel-lane-a-proposal` (renamed from `claude/session-2026-09-17`), based on
  origin/main `731edbd` (v0.8.11, PR #203 merge, 2026-09-17). The commit that carries this
  package is the branch head; its SHA is in the handback message and `git log`.
- Running app at the time of writing: `/api/health` v0.8.09, build `dd525de` (2026-09-16
  22:00 PT), 12 commits behind main, containing every Cartel commit through `c99501b`
  (PR #189, merged 2026-09-17 01:18Z). The QS refusal on 2026-09-16 19:00Z therefore ran
  without the spread reselection.
- Cartel source reviewed at `731edbd`: `backend/zargar/techniques/options_cartel/` (60 modules),
  `api/routes_options_cartel.py`, the Cartel documents listed in the assignment, and
  `docs/PLATFORM-RULES.md`. Line numbers in FUNNEL.md refer to that revision.
- Runtime database read: `zargar` on 127.0.0.1:5433 (read-only transactions only). Persisted
  Practice policy `techniques.options_cartel.preparation` last saved 2026-09-14 00:52Z; no
  other Cartel settings are persisted (defaults apply, including `reselect_wide_contract=true`).

Nothing in production behaviour, settings, arms or the runtime was modified. The only code
added is a read-only tool and a pure test.

## What is in this change

| Path | Purpose |
|---|---|
| `backend/zargar/tools/cartel_evidence.py` | read-only reconstruction (plan trail, preparation funnel, bucket table from stored minutes, cache coverage/provenance, recorded option quotes) |
| `backend/tests/test_cartel_evidence_tool.py` | pure tests for the tool's bucket aggregation (no database) |
| `docs/techniques/options-cartel/reviews/2026-09-17-proposal/*` | this package |
| `docs/techniques/options-cartel/README.md`, `DOCUMENTATION-CHANGES.md` | one pointer line each |

## Reproduction

From `backend/` with the main checkout's interpreter (a worktree has no `.env`, so pass the
database URL explicitly; the tool forces `default_transaction_read_only = on`):

```
set U=postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar
python -m zargar.tools.cartel_evidence --database-url %U% plan e30a2db9c9aa72602410dfbce37a0d16     # APA
python -m zargar.tools.cartel_evidence --database-url %U% plan e2e12438418bc82ff34c3b2c5a7f365b     # QS
python -m zargar.tools.cartel_evidence --database-url %U% plan 341d97737adc3ca0d85ecfc2b576e02f     # TTWO
python -m zargar.tools.cartel_evidence --database-url %U% plan 9be071fc7c2f039534d6a74d666ed863     # PWR 09-17
python -m zargar.tools.cartel_evidence --database-url %U% plan d4ba82cd110834013b45510c2a86a3b5     # APTV 09-16
python -m zargar.tools.cartel_evidence --database-url %U% plan 8ba793383b07796921c7c1bf11574559     # APTV 09-17
python -m zargar.tools.cartel_evidence --database-url %U% preparation ed6d9da2da1d4f06981ad43b6d0edfe5   # 09-16
python -m zargar.tools.cartel_evidence --database-url %U% preparation cee03dd791ce404ab322378626339849   # 09-17 nightly
python -m zargar.tools.cartel_evidence --database-url %U% preparation bc78bc51f42a46568b255568ff052428   # 09-17 last resume
python -m zargar.tools.cartel_evidence --database-url %U% buckets QS 2026-09-16 --plan e2e12438418bc82ff34c3b2c5a7f365b
python -m zargar.tools.cartel_evidence --database-url %U% buckets TTWO 2026-09-17 --plan 341d97737adc3ca0d85ecfc2b576e02f
python -m zargar.tools.cartel_evidence --database-url %U% buckets APTV 2026-09-16 --plan d4ba82cd110834013b45510c2a86a3b5
python -m zargar.tools.cartel_evidence --database-url %U% buckets APA 2026-09-14 --plan e30a2db9c9aa72602410dfbce37a0d16
python -m zargar.tools.cartel_evidence --database-url %U% coverage PLAB
python -m zargar.tools.cartel_evidence --database-url %U% quotes e2e12438418bc82ff34c3b2c5a7f365b
python -m pytest tests/test_cartel_evidence_tool.py -q
```

Key values the commands must reproduce (all in BOTTLENECKS.md): APA triggered 09-14 13:45:00Z
at 1.97× / 0.92, stop 45.56, filled 3.30, stop exit 2.7095, net −61.13; QS triggered 09-16
19:00:01Z, three preflights failing only `entry_contract_spread` at bid 1.86 / ask 2.39
(24.9%), signal expired 19:02:30Z; TTWO never armed, lowest otherwise-eligible ask 7.8–8.2 vs
cap 5.0, `target_passed` 13:56:07Z; PWR lowest ask 24.4–46.0, provenance reasons from
15:46:05Z; 09-17 funnel 3,059 → 13 → 3 shortlist + 10 coverage-blocked; PLAB baseline 19/26
slots with Alpaca provenance `noTradeIntervalsVerified: false`.

Results on this desk: all commands ran against the runtime database on 2026-09-17 between
22:30Z and 23:30Z and produced the values above; the pure test passes (2 tests). No other test
suite was run for this package because no production code changed.

## Confirmed defects (code behaves other than intended or documented)

1. **Planning admits setups with negligible room.** The only planning-time room check is a 0.5%
   first-target distance; structural R is computed, shown and never gated. PWR was planned at
   R 0.075 and TTWO at 0.28 (`automatic_plans.py:155`). The source checklist says ≥ 1.5:1 (S14).
2. **Data refusals record no measurements.** `untrusted_confirmation` and `missing_bucket`
   decisions carry no crossing/volume/location, so whether a provenance refusal cost a valid
   entry cannot be judged from the record (`entry.py:75-87`).
3. **Contract feasibility is checked after ranking and only for the top 25**, so unaffordable
   high-priced names take focus slots and pending-watcher time all day (TTWO, PWR ×2, NVT;
   `preparation.py:478-482, 557-558`).
4. **Registry tabs differ from the page** (`techniques/base.py:75` vs `OptionsCartelPage.tsx`),
   and `techniques.options_cartel.min_one_contract` is defined but never read by Cartel's sizing.
   Cosmetic; listed for completeness.

## Hypotheses (supported by records, not yet proven)

1. **Baseline coverage × provider minute omission** explains the 10/13 coverage blocks on 09-17:
   the all-15-minutes sample rule at 20 sessions cannot reach 5 samples when ~20% of minutes
   are absent; the minute-volume/daily-volume ratio (~75–80%) is the same for liquid and thin
   names, so absent minutes are not volume truncation. Whether they are genuine no-trade
   intervals is **unverified** (`noTradeIntervalsVerified: false`; Yahoo-sampled live minutes
   without a venue bar carry non-zero volume for PWR/PLAB). D1 in PROPOSAL.md tests this.
2. **The session-extreme stop at the first bucket is inside one day's normal range** for an
   ADR>3% screen (APA: 1.46%). One case; the paired daily-candle-low observation (S3) measures it.
3. **A single-contract fill cannot follow the exit policy** (no trim, no breakeven); with a $500
   budget most fills will be single contracts. Lane A reports the fraction.
4. **Bearish sessions dominated the sample** (09-15, 09-16, 09-17 all strict short). The long
   method has not been exercised since APA. Lane A only prepares on strict-bullish sessions,
   so its first evaluation may wait for the market.

## Unresolved questions for the reviewer

1. The QS put's spread widened from 5.7% to 24.9% at ~13:47 ET with live, changing sizes
   and stayed wide to the close. Is a 20% mid-basis limit the right final gate for a $2 option
   on a $5 stock, or should the limit be expressed in cents for low-premium contracts? (No
   change proposed; question only.)
2. Should Lane A's 1.5R planning rule use the reviewed invalidation (base low) as its risk
   basis, or the expected session-extreme stop? The source does not say; the proposal uses the
   invalidation and records the basis.
3. Is the minute-volume/daily-volume ratio of ~75–80% (Alpaca SIP 1m vs Yahoo daily) known and
   explained on the platform? It does not affect the 1.5× rule (same basis on both sides) but it
   affects any absolute-volume screen built on the minute feed.
4. Your record of a "current-session provenance block" for PWR on 09-17: the attempts show it
   from 15:46:05Z (1 → 17 minutes), after the contract audit had already refused every expiry.
   I read the affordability refusal as first and the provenance block as independent; please
   confirm or correct from your session notes.
