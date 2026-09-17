# Automatic daily preparation

Armed plans prepared ahead of their first session show **Armed for YYYY-MM-DD —
waiting for market open**. They owe no observation minutes from the preparation
day. Once their session starts, missing-minute warnings refer to that active
session; genuine gaps and the normal delivery grace period remain visible.

Current behavior, reviewed 2026-09-16. This is the operating guide; dated release notes are historical evidence.

The [September 13 corrections](READINESS-2026-09-13.md) preserve contract limits through final submission, recheck pending invalidation after selection and retain nearer confirmed targets. Older unused automatic Practice arms need the explicit **Review entry contract limits** action before entry. It preserves their selected contract, chart targets and exit policy.

Settings → Plan policy and exit allocations has a Practice-only whole-contract alternative for new plans: two contracts use first target/EMA50, three use first target/EMA8/EMA50. One contract retains its final EMA/protective exit. Old campaigns retain their saved policy. Enable Option quote recording to collect contemporaneous evidence. Leadership and prospective evidence on Plans is advisory; it does not replace the configured executable ranking.

## Using the desk

1. Select Practice or Live in the app workspace selector.
2. Open Options Cartel → Settings. Enable preparation, verify the account, method profile, coverage and risk settings, then save.
3. Outside regular trading hours, use Plans → Prepare now for a fresh market snapshot. Scheduled dispatches run at 08:45 and 20:20 ET on trading days, in the active workspace only.
4. Read the preparation result and actual Armed list. Research candidates, eligible setups, contract-pending reserves and active arms are different states.
5. Leave the engine running to monitor arms. Preparation does not submit an entry order. The controller enters only after fresh closed-bar, quote, risk and execution checks succeed.

Practice routes to `techniques.options_cartel.default_portfolio` when configured; a conflicting account is rejected. The archived shared Practice book is not a fallback. Live requires an explicit appropriate account, saved Live/overnight acknowledgements, the separate Cartel live-auto permission, the active Live workspace and a connected broker. Phone exit-only policy remains applicable. Saving settings never implicitly enables Live permissions.

Practice settings use `techniques.options_cartel.preparation`; Live uses `techniques.options_cartel.preparation_live`. Existing saved values are retained where supplied. The optional ignition pilot is Practice-only. See [IGNITION.md](IGNITION.md).

## What a run does

Discovery retrieves the supported TradingView primary US stock/DR universe and reviewed ETFs, then captures industry context and validates SPY/QQQ completed-session history. If benchmark freshness is inadequate, the executable scan stops early in `waiting_for_benchmark`; it does not spend a full market scan pretending stale data is a market opinion.

With fresh data but blocked/mixed market alignment, the configured research direction can still be evaluated. Resulting research records cannot become executable merely because alignment later changes: fresh preparation is required. Strict alignment requires both indices on the selected side of all selected EMAs. Moderate Practice permits bullish alignment when one index is above 8/21/50 and both are above 50; bearish alignment remains strict. Missing data never passes either mode.

All eligible listings are evaluated by default. `scanAll=false` explicitly applies `historyLimit`; the old stored value 200 is irrelevant while scanAll is true. Strict industry mode can reject definite rank failures before downloading history; context mode records ranks without using them as that gate.

Qualifying candidates default to ranking by structural first-target R, directional relative strength, daily volume, then symbol. Volume-only order remains selectable. Ranking is an engineering preference, not predicted option return. The worker checks up to five times `focusCount` candidates for baseline/contract readiness, stopping when capacity is filled. Pending contracts do not use active slots. Existing arms, paused/working campaigns and held positions reserve capacity and are preserved; a refresh does not disarm them first.

## Defaults for new/omitted settings

These are implementation defaults, not a report of the user's currently saved configuration.

| Setting | Practice default | Live default / boundary |
|---|---|---|
| Preparation enabled | false | false; explicit acknowledgements needed |
| Method profile | `september_2026` | established profiles; ignition pilot prohibited |
| Market alignment | strict | strict; Moderate is Practice-only |
| Industry handling | context | context unless explicitly changed |
| Ranking / focus count | quality / 5 | same |
| Entry | 15m breakout, gap-retest option, session-extreme stop, 1.5x volume, 0.70 close location | same unless explicitly saved differently |
| Minimum first-target distance / entry R | 0.5% / 0.25R | same |
| Entry-window readiness | first hour plus at least 80% of pre-close slots | full-session coverage |
| Baseline policy | covered periods | full session |
| Verified exchange history | true | mandatory for new Live preparation |
| Automatic interrupted-run recovery | true | still requires valid scope/permissions |
| Ignition research watchlist | true | research remains non-executing |
| Native daily batch source | false | false; explicit alternate provider-day dataset |
| Premium budget / equity risk / max contracts | 500 / 10% / 10 | 500 / 1% / 10 |
| Draft option preferences | 21–90 DTE, target 45; absolute delta target 0.5/minimum 0.25; ask <=5; spread <=20%; OI >=100 | same |
| September exit allocation | 25/25/20/20/10% | same; whole-unit rounding applies |

Risk percentage uses that account's equity and full option premium debit, not all Practice books combined or expected stop loss. The lower budget/affordability bound wins: 10% of a 10,000 book does not override a 500 premium budget. Cash, FX, contract multiplier, quantity, exposure, loss and fresh quote gates remain mandatory. No risk escalation is automatic.

Confirmed price pivots supply targets first. Optional Fibonacci fallback anchors and the precise geometry/exit allocations are explicitly engineering choices. The 3x daily ignition-volume example is not the 1.5x intraday confirmation rule.

## History, provenance and coverage

The existing daily provider uses the shared historical path. Cartel's separate `cartel_history_cache` stores provider-keyed research histories, not a copy of the runtime bars table. Daily reads reuse matching completed sessions and incrementally request missing/revisable ranges. Legacy analysis-cache fallback preserves original observation time and checks actual last session; it can look back five calendar days, never past the requested as-of cutoff.

Minute baselines request 20 trading sessions, subject to source availability. Each usable slot needs at least five complete historical samples and a positive median. No missing minute is filled with invented volume. Partial baseline caches can be retried after five minutes. The first-hour/80% gate concerns pre-close entry windows; the closing slot cannot start an automatic entry. Explicit legacy coverage can still be selected for comparisons.

Timestamp coverage is not source quality. New automatically prepared plans default to requiring exchange-class bars for confirmation and session-extreme stops, with an independent controller check. Legacy six-number minute records remain provenance-unknown. Recovery can replace an inferior source with exchange data and advances the observation cutoff so old crossings do not fire retroactively. Same-quality corrections are not automatically preferred without stronger revision identity.

The app retains source classification, tape hashes and decision measurements. This is **not** a full immutable per-candle/per-decision provider-revision ledger; a hash cannot reconstruct overwritten input. Distinguish recorded decision measurements, current recovered tape and later provider revisions in reviews.

Native daily batching is off by default. With configured access it uses a separate Alpaca provider-day/raw-price dataset, fully paginates bounded requests and requires provider-day completion. It is not silently equivalent to RTH-only daily data. Access-denied fallback separates cache keys; other errors remain explicit. The ordinary batch window (25) and concurrency (6) are local controls, not 25 simultaneous requests. Default start spacing is 0.25 seconds. Cold-run speed gains have not been established; repeated warm work should be measured independently.

## Restart, cancellation and expiry

Preparation owns a renewable 120-second database lease, renewed during progress checkpoints and checked before arming. A stale owner cannot publish arms. A crashed lease may need to expire before a replacement worker proceeds; do not start another engine to get around it.

Resume saved scan reuses the original snapshot and successful analyses in a linked run. Eligibility requires current coverage schema (7), matching workspace/policy/target session, the same expected completed market session and age under four calendar days. Old-schema, changed-policy or expired snapshots need Prepare now. Progress may reconstruct saved analyses; the visible saved checkpoint is not a promise that no work remains.

Automatic recovery checks at five-minute intervals outside regular hours when enabled. It resumes eligible interrupted failed runs and retries fresh preparation after `waiting_for_benchmark`. Compatible partial results with unresolved history or plan errors now receive at most three automatic recovery attempts per evening/pre-open window, with exponential backoff outside regular hours. The morning job resumes this saved work instead of treating a partial scan as complete. Filtered analyses and waiting-contract plans are reused; failed baselines are retried. A changed baseline produces a new immutable plan revision at the original cutoff. Missing data still cannot authorize a historical entry. Stop preparation records cancellation and will not auto-resume that job; disabling preparation also stops future work. Neither action closes positions or discards existing arms.

New automatic evidence expires at the close of its **first intended entry session**, not 24 wall-clock hours after creation. This permits weekend preparation for Monday. A multi-session thesis or held position is separate from that automatic evidence window. Existing saved arms retain their original expiry/configuration unless explicitly rebuilt.

## Pending contracts and result interpretation

Pending activation checks at most once per minute from 08:45 ET through regular-session close, in the active workspace. It requires the latest compatible preparation, remaining capacity, usable history, valid price levels and an eligible contract. It pauses while a new preparation runs. A verified closed-bar invalidation is terminal for that pending plan; a rebound cannot revive it. Expired or target-passed cases remain distinct.

Planning chain quotes select a draft expression, not an executable price. Diagnostics retain first-failing-filter counts plus up to 30 ranked rejected examples with all measured failures. Search completeness and selection completeness are different; a truncated or unavailable search does not prove that no suitable contract exists. Fresh quote/Greek validation is repeated at entry, and the configured refresh budget is authoritative.

`partial` can coexist with valid arms: some histories or plans failed while others passed. Consult the individual reasons. `armed` means monitored; it does not mean purchased. For live operational state use Armed and account reports, not old deployment documents.

Implementation references are in [TRACEABILITY.md](TRACEABILITY.md); current limits are in [DELIVERY-STATUS.md](DELIVERY-STATUS.md).


## September 14 recovery and review corrections (v0.7.74)

Recovery shows its attempt count and next eligible retry. Each evening and pre-open window has a separate three-attempt allowance, so overnight exhaustion cannot suppress the morning recovery. After three automatic attempts in a window,
review the precise missing coverage or use Resume deliberately. Stop/disabled/session/policy
barriers remain authoritative. The lease also serializes pending activation with preparation;
expired ownership cannot arm after a slow provider call.

Each candidate selection/readiness attempt is saved separately with its time, account,
policy, plan identity and diagnostic result. An expired pending plan is marked expired;
its last selection result remains history. A held position without an active arm still
reserves capacity through its durable config.runId, or an explicit unlinked identity.

The daily review under Plans is read-only: choose a session and account (including a historical
archived book). It separates confirmed fills/closed campaigns, gross and net realized P&L,
allocated entry/exit fees, remaining holdings, preparation exclusions and option-recording
coverage. The native currency must match the account for combined monetary totals; missing
historical FX or marks are unavailable, not substituted from today's prices.

## Intraday research while the market gate is blocked

The Practice-only monitor observes the saved blocked shortlist against frozen completed-daily
EMA levels after closed 15-minute index candles. Two consecutive aligned observations can
produce research-only stock confirmations, subject to existing source, volume and entry
checks. It cannot unlock or arm these records. The daily market gate and execution policies
remain unchanged. Settings → Intraday market research controls collection only.

Protocol, source distinction and future promotion requirements are preserved in
[the September 14 decision](INTRADAY-RESEARCH-DECISION-2026-09-14.md).

For the broader prospective study, leave profitability research enabled in Settings
and run fresh preparation before the session. Validation's **Profitability research**
compares the bounded full candidate pool, ranking alternatives and separate bearish
and exit experiments. It does not increase executable shortlist capacity or grant
entry permission. See [the collection and review protocol](PROFITABILITY-RESEARCH.md).

## Common statuses and what to do

| Status | Meaning | Appropriate action |
|---|---|---|
| Waiting for completed benchmark session | SPY or QQQ is missing the required completed daily bar | Leave enabled recovery/schedules running; inspect provider errors if persistent. Do not bypass freshness. |
| Market blocked / research only | Fresh data does not satisfy the configured direction gate | Review evidence; these records do not auto-unlock. Fresh preparation is needed after alignment changes. |
| Awaiting contract | No inspected contract passed all configured checks | Expand contract details. Pending activation may retry within its valid window; this is not automatically a budget problem. |
| Armed for a future date | Entry session has not opened | No re-arming or prior-day gap repair is needed. |
| Auto: waiting | No qualifying fresh closed-bar entry is currently recorded | A price touch alone is insufficient. Inspect trigger, volume, candle quality and entry mode. |
| Overdue minute gaps during the active session | Expected observation minutes remain missing beyond delivery grace | Inspect source/recovery status. Recovery restores context, never a missed historical entry. |
| Untrusted confirmation | Some minutes exist but their source classification is sampled or unknown | Treat this separately from missing timestamps; zero overdue gaps does not prove trusted data. |
| Partial preparation with arms | Some candidates failed while others passed | Review individual exclusions; do not discard valid arms solely because the aggregate status is partial. |

A downside plan whose stock opens below the trigger is not automatically a fresh
breakdown. Gap/retest behavior depends on the saved entry mode; an enabled gap
option does not convert a breakout plan into a different method. Any alternative
belongs in a separately versioned research comparison before changing execution.

## Spread-only alternative selection in Practice

Settings includes **Search one alternative when only the selected option's spread
blocks an automatic Practice entry** (`techniques.options_cartel.reselect_wide_contract`,
default on). It applies only to automatically prepared Practice auto arms with saved
contract limits. A single search per fresh signal uses the existing expiry/refresh
bounds and at most 20 seconds, ending before the signal expires. It never widens
premium, spread, delta, DTE, budget or risk limits. No substitution is made for
Live, proposal/manual approval, other failed gates, working submissions or holdings.

A selected replacement is saved and journaled, then full preflight, reconciliation,
final quote checks and RiskGate run again. A pause, expired signal or changed saved
configuration during the search prevents entry. A failed/interrupted search is not
repeated for the same signal; ordinary quote retries can still observe the saved
contract. Daily review now names execution refusals and their dated bid/ask evidence,
separately from the earlier stock confirmation. No successful stock signal implies
an option was bought.
