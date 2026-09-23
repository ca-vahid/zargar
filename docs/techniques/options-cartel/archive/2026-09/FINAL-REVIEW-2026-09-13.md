# Options Cartel final method and profitability review

Reviewed Sunday, September 13, 2026, approximately 16:35 PT. This is a review and correction plan, not a release or an instruction to place orders.

## Verdict

The project has a useful foundation for a systematic Practice experiment, but it is **not yet ready for an unconditional unattended-execution sign-off or a profitability claim**. Three reproducible correctness problems deserve priority over looser filters: missing contract-policy enforcement at entry, omitted nearby targets, and invalidation during pending activation. Small-contract exits and incomplete option evidence then limit what we can learn from trading it.

The right ambition is to capture repeatable, executable opportunities with controlled costs and explainable decisions. More arms, larger budgets, passing tests and resemblance to an author's charts do not independently establish an edge.

## Baseline and Monday state

Source reviewed: fetched `origin/main` **95b8d66cde53d76d2d194e48801e551e1be75bc6**, global version **0.7.61**, in detached audit checkout `C:/Cursor/zargar-codex/.cache/cartel-final-review`. Runtime health separately returned `ok=true`, `started=true`, version `0.7.61`. The desk checkout was `3a1c356` on `claude/zargar-stock-app-research-8mnqfh`; it contains the reviewed main commit, with no committed Cartel backend/page differences in the checked paths. A checkout comparison does not prove every loaded module's provenance.

Read-only runtime checks:

| Item | Observed state |
|---|---|
| Cartel book | Options Cartel Practice, USD 10,000 cash |
| Cartel orders | Zero records across statuses |
| Active arms | APA, NOV, CGNX; automatic Practice; waiting; no stored observation error |
| Entry horizon | Monday September 14, ending at 16:00 ET |
| Baselines | 26 of 26 periods in each saved plan |
| Policy | General September profile; Moderate alignment; industry context; scan all |
| Budget/risk | USD 500 premium budget; 10% full-premium risk ceiling; maximum 10 contracts |
| Contract selection | 21–90 DTE; 45-day preference; delta floor .25; ask ceiling $5; spread ceiling 20%; OI minimum 100 |
| Pending | OKTA was awaiting a suitable contract in the completed preparation |
| Halt | Persisted global halt disengaged; no persisted book halt in that record |
| Quote evidence | Recording setting absent, default false; **zero rows in `options_cartel_quotes`** |

The three arms require exchange-quality confirmation bars. Weekend health and saved baselines cannot verify Monday's live bar delivery, fresh option spreads or eventual signal/risk approval. Authenticated `/api/state` was not accessible to the unauthenticated loopback request; no live-memory halt/feed claim is inferred from the persisted snapshot.

At current equity the $500 budget is more restrictive than the $1,000 implied by 10% risk. A fully funded setup uses at most 5% in premium before additional constraints; three fully funded entries could commit up to 15%. Arms are not fills. No increased risk is recommended from these observations.

## What the latest author material changes

Sean's September 13 system post emphasizes a hierarchy: market conditions, strong themes, leaders, setup, price/volume trigger and predefined risk. Group strength and leadership can matter more than a visually perfect pattern. He describes graded EMA context rather than one universal binary permission rule, repeated focus on a small set of leaders, and targets at previous highs, supply, weekly levels or extensions. Low of day is a frequent stop reference, with setup-dependent alternatives. This supports stronger theme/leader evidence and faithful target construction; it does not validate our exact numerical thresholds. [Sean's full September 13 breakdown](https://x.com/SRxTrades/status/2099241717983486243).

His new Sunday examples include FFIV's tight daily base with a stated 416 level and possible software rotation, and AMBQ's weekly flag near an IPO-base retest and 50-week EMA. These are useful prospective coverage examples, not proof of an executed trade or instructions to bypass our controls. Save publication time and later compare inclusion/exclusion reasons without tuning the scanner to these two charts. [FFIV](https://x.com/SRxTrades/status/2099254292779536704), [AMBQ](https://x.com/SRxTrades/status/2099260584189645197).

The September 11 video distinguishes the unusual-volume ignition event from the subsequent quiet consolidation and eventual breakout. Its examples discuss roughly 3–5 times normal **daily** volume, EMA catch-up, waiting rather than chasing, and 5/15-minute execution views. That is not evidence for a universal three-times intraday entry threshold. The exact transcript was available and reviewed, including the discovery screen and CRCL example; the prior transcript-access obstacle is resolved. [Video, September 11](https://www.youtube.com/watch?v=7xSMgmLoqM8).

Our 20-session ignition denominator, 2–15 consolidation days, 12% range, 3% EMA proximity, 50% event-volume ratio, 15-minute closed-bar rule, 1.5-times same-time median volume, 70% close location, contract preferences and allocation fractions remain engineering choices or explicit Practice experiments. S30 does not establish these as optimal. Moderate alignment is also an experiment; today's explanation does not retrospectively validate its precise formula.

The Cartel account's latest visible performance post remained the September 8 DRAM swing claim above 200%. That is a reported individual trade outcome, not independently verified account expectancy or a complete current-session return. The visible post contains no quantity-weighted fill ledger. [Cartel's September 8 post](https://x.com/TheOptionCartel/status/2097414673662718231).

## Findings requiring correction

Code references below are repository-relative at the audited commit. P1 means resolve before relying on the affected automatic behavior; P2 means material correctness, evidence or method-representation work.

### F1 — P1: preparation's contract limits do not all reach the final order

`backend/zargar/techniques/options_cartel/preparation.py:505` and `:629` construct `ExecutionInput` without the policy maximum premium or configured delta floor. There is no saved spread-cap field. Planning applies those filters in `automatic_plans.py:192`, but final preflight produces a limit order at the current ask (`execution.py:158`). `controller.py:135` checks current quote quality without preserving the reviewed spread policy. Shared `backend/zargar/risk.py:587` rejects an excessive spread only for market orders; a limit order receives a warning.

A contract can qualify at preparation, then quote $2.50 bid/$4.50 ask at its trigger. A $450 ask-priced limit can pass the remaining budget checks despite a 57.1% midpoint-relative spread and 44.4% immediate ask-to-bid liquidation difference. This is an illustrative code-path case, not an observed loss. Full-debit affordability remains enforced. Current arms actually store `max_premium=null`; their default $5 ceiling happens to be bounded by the $500 budget, but their spread restriction is not enforced at entry.

**Correction:** Persist a versioned execution-policy snapshot, including applicable premium, delta and spread limits. Recheck it against the final fresh quote before reservation/routing, including after slow work. Reject or defer entry with a specific reason. Entry-only constraints must not block protective exits. Do not broaden the shared platform's limit-order rule as an incidental Cartel fix.

**Acceptance:** Narrow-at-preparation/wide-at-trigger rejects; final-step widening rejects; custom ask/delta limits survive both initial and pending arming; good quotes still work; exits remain available. Define an explicit treatment for already-armed plans instead of silently mutating saved policy.

Why it matters economically: spreads can widen with liquidity and volatility changes, so yesterday's selection is insufficient evidence about today's entry cost. [Schwab's spread explanation](https://www.schwab.com/learn/story/large-bidask-options-spreads-volatile-markets).

### F2 — P1: target discovery can omit confirmed resistance and overstate quality

`setups.py:182` searches targets only before the generic base window, even when the selected inside-day, MA-pullback or retest uses more recent geometry. The pilot's `setups.py:90` also excludes the ignition candle. `automatic_plans.py:109` treats the resulting empty targets as permission for Fibonacci fallback, whose anchor window is likewise generic.

**Synthetic reproduction through the actual screen and analysis:** All current gates pass. Inside-day trigger 110, invalidation 108.5, confirmed recent high 110.2. Full completed-history pivot detection finds 110.2, but current selection invents a first target of 113.264, reporting 2.176 structural R. The nearer overhead offers only 0.133R and 0.182% room, below the configured 0.5% minimum. A separate ignition case excludes a confirmed 113.2 event high above a 113 trigger and instead accepts 116.944.

**Correction:** Search all relevant causally confirmed pivots for each candidate, including the ignition high and recent supply/support. Preserve genuine nearer barriers before deciding whether fallback is justified. Use candidate-specific anchor boundaries. Do not loosen the room gate.

**Acceptance:** Inside-day, pullback, retest and ignition cases retain nearby pivots; mirrored shorts behave consistently; insufficient room rejects; future bars never create targets.

**Current-plan check:** Recomputed pivots from each saved plan's 378 completed daily bars through September 11. CGNX's full-history targets equal its saved 64.80/65.23/66.44. APA and NOV have no directional pivots under this algorithm, matching their fallback usage. **This particular missing-pivot defect was not demonstrated in these three arms.** That does not validate Fibonacci anchors as profitable or constitute a complete chart review.

### F3 — P1: pending activation can overlook an intervening invalidation

`preparation.py:611` checks readiness before awaiting contract selection; it arms without a fresh context check afterward. `observer.py:248` moves effective plan creation to `armedAt`, while `entry.py:88` skips earlier buckets before evaluating invalidation.

**Pure reproduction:** Ready at 09:39:50; the 09:40 exchange bucket invalidates; selection finishes at 09:40:10; the original plan remains invalidated, but the observer-adjusted plan can trigger on a later rebound.

**Correction:** Preserve original creation time for invalidation. Use a separate entry cutoff only to prohibit historical entries. Refresh readiness/context immediately after selection and before publication.

**Acceptance:** Advance a fake clock across the invalidating close during slow selection; require terminal invalidation, no arm and no subsequent order, including after restore. Existing weekend arms are not exposed to this pre-arm race; pending OKTA and preparation crossing the opening bell are.

### F4 — P2: small positions follow a different exit strategy

Current cumulative-floor allocations and the `first_done` prerequisite in `exits.py:113`, `:180` and `:189` produce:

| Filled contracts | Target 1 | Extension allocation | EMA8 | EMA21 | EMA50 | Actual strength-exit limitation |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 0 | 0 | 0 | 0 | 1 | No first trim or stop-to-entry transition |
| 2 | 0 | 1 | 0 | 0 | 1 | Extension cannot trigger because first trim never happens |
| 3 | 0 | 1 | 1 | 0 | 1 | Extension cannot trigger; one EMA8 unit remains possible |
| 4 | 1 | 1 | 0 | 1 | 1 | EMA8 allocation is zero |
| 5 | 1 | 1 | 1 | 1 | 1 | Every exit leg has a whole contract |

Protective and expiry exits still apply. Unreachable extension units remain for final liquidation; they are not lost. The one-contract convention is intentional and documented. The misleading part is showing two/three-contract extension allocations without their unreachable prerequisite (`frontend/src/pages/CartelPlanOverview.tsx:73`).

**Correction:** Display reachable exits for actual funded/filled quantity. Specify and evaluate a separate small-lot campaign policy, preserving fill-confirmed transitions and whole-unit accounting. With $500, four contracts require ask no greater than $1.25 before fees, five no greater than $1.00. Do not force cheap low-delta options or increase risk merely to make percentages fit.

**Acceptance:** Quantities 1–5, partial fills, target touches without fills, and restored campaigns produce the declared reachable exits and never a false breakeven transition.

### F5 — P2: profitability replay and evidence are not aligned to the funded trade

`replay_service.py:27` and `CartelReplayControls.tsx:9` default to 100 units. `premium_replay.py:73` interprets replay units as contracts without account sizing. A 100-unit campaign has trims and breakeven that a one-contract campaign cannot have; dividing its result by 100 does not reproduce the small campaign.

The runtime quote recorder is currently off with zero recorded observations. There is therefore no stored Cartel premium dataset for valuing missed campaigns. When enabled, repeated cached quotes receive distinct sampling identities (`quote_observations.py:85`); stored valuation refuses over 40,000 observations (`premium_replay.py:143`). Continuous five-second sampling can reach that in roughly 56 hours, or 8.5 regular sessions, even with duplicate/stale source values.

**Correction:** Replay exact funded/filled quantities, then value exact contracts from eligible contemporaneous quotes. Record distinct source observations plus coverage gaps; support complete bounded campaign pagination. Enable recording as an explicit operational step with retention/coverage checks. Default-off recording is not itself a trading blocker, but it is a substantial research gap.

**Acceptance:** One-lot live/replay exits match; 100-unit results cannot be labelled account-sized; repeated unchanged source quotes do not imply fresh coverage; a long campaign remains valuatable; missing quotes remain unknown rather than fabricated fills.

Options depend on time, volatility and other inputs as well as the stock price. A favourable underlying path is not proof of positive option P&L. [OCC/OIC option-price behaviour](https://www.optionseducation.org/referencelibrary/faq/option-price-behavior).

### F6 — P2: disabling native batching can retain the other dataset

`preparation_io.py:161` checks provider identity on the legacy-analysis fallback only when native batching is enabled. A pure probe seeded an Alpaca provider-day analysis, selected non-native history and received the Alpaca analysis with zero calls to the selected provider.

**Correction:** Require compatible provider/feed/adjustment/session identity in both directions. **Acceptance:** Native-to-non-native and reverse switches, 401/403 fallback and same-provider cache reuse. This is conditional on another eligible dataset being present; no effect on today's three arms was demonstrated. Native batching remains off by default.

## Method improvements after correctness

1. **Theme and leader evidence:** Add dated group participation, leadership, liquidity and follow-through features to an advisory record first. Compare a prospective theme-first ranking against current quality ranking without changing eligibility and risk simultaneously. Static industry labels and structural R are incomplete proxies for this process. Keep held/armed campaigns protected from ranking churn.
2. **Persistent candidate lifecycle:** Retain discovery, developing, ready, triggered and invalidated evidence across sessions. The ignition list provides a start, but its fixed geometry and unverified catalyst field should remain visible. Keep the general and ignition cohorts separate.
3. **Cost-aware contract selection:** Diagnose candidates whose stock setup is attractive but whose executable option spread, premium or integer quantity makes the campaign unsuitable. Deferral is a legitimate result. A directionally correct stock thesis is not automatically a viable option trade.
4. **One frozen challenger:** After the correctness fixes, prioritize a quantity-correct exit comparison. Entry timeframe/volume, ranking and ignition thresholds should be later independent experiments, not daily simultaneous edits to fit yesterday's winners.

## Prospective evaluation and promotion

Use **20 consecutive market sessions as an operational collection checkpoint**, not proof of profitability or automatic Live graduation. This is a proposed research design, not an author rule.

- Freeze baseline version, policy, source identity and one challenger before collection. Keep a log of every attempted variant.
- Preserve all opportunities: discovery, exclusions, pending contracts, readiness failures, signals, refusals, no-fills, entries and exits. Evaluate the portfolio policy on the full opportunity set, not just trades closed under both variants.
- Record exact contract, whole quantity, bid/ask timing, order/fill outcomes, fees and capacity. Distinguish realized P&L, bid-marked open P&L and hypothetical quote-based valuations.
- Report expectancy after costs, drawdown, exposure/concentration, quote coverage, holding time and fill/no-fill rates. Treat repeated plans and correlated campaigns as dependent observations.
- Keep a subsequent untouched period. Promote only after out-of-sample improvement with acceptable risk and uncertainty sufficiently narrow for the claim; otherwise collect more evidence. Repeated searches across variants inflate false discoveries. [Original probability-of-backtest-overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

## Recommended order and Monday decision

| Order | Deliverable | Release condition |
|---|---|---|
| 1 | Enforce saved contract policy at final entry; close pending invalidation race | Initial/pending/final-refresh/restart boundary regressions pass |
| 2 | Correct candidate-specific targets | Causal nearby-target and mirrored-short regressions pass; regenerate affected unfilled plans explicitly |
| 3 | Quantity-correct exits/UI/replay and quote evidence | Declared small-lot behavior; no invented fills; usable recording coverage |
| 4 | Provider-identity fallback | Bidirectional dataset-switch regressions pass |
| 5 | Prospective theme/leader and exit experiments | Frozen cohorts, costs and promotion criteria recorded before observation |

For Monday, the existing arms are operationally present, but **F1 applies to their eventual entries**. F3 applies to pending activation. Resolve those before claiming unattended readiness. F2 should be fixed before relying on fresh ranked preparations; the saved three-plan pivot comparison above provides a narrower reassuring result, not a blanket sign-off. Preserve all positions and protective management during any correction.

No code, settings, arms or runtime processes were changed by this review. This document is a local review artifact; it is not a merged PR or deployed fix.

## Evidence boundaries

- Three independent ultra-effort audits covered execution, source fidelity and option economics; root separately checked runtime state and current-plan targets.
- Checks used source inspection and standalone deterministic probes, plus read-only selected runtime SQL. **No destructive database tests, full backend suite, production build or broker acceptance suite was run in this review.** Prior release test counts are not new evidence for these boundaries.
- No second engine was started. Other developers' worktrees and running app were preserved.
- Source access: September 13 public X posts and Cartel profile read in the browser; September 11 full saved transcript reviewed. No private-room completeness or independently verified author P&L is claimed.
- Main working folder remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`; audit source is detached at the commit recorded above.
