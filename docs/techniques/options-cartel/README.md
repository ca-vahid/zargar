# The Options Cartel — independent technique desk

Owner: Codex new-technique team. Working id: `options_cartel`.
Source author: Sean Trades (`@SRxTrades`), founder of `@TheOptionCartel`.
Started 2026-09-06. **Research and implementation in progress; not a shipped technique.**

Research preview: `http://127.0.0.1:8421/techniques/options-cartel` (isolated
`zargar_dev_codex`, sim broker/quotes, no integration credentials). Desk, Plans,
History and Method are connected to the persisted research APIs. Browser plan
and review workflows and phone/tablet audit passed in earlier verification.
The running desk supports alert, proposal and auto arming with reviewed execution
settings, live updates, approval, pause/resume, disarm and position closure.
Recovery restores available session bars and requires a fresh post-resume entry;
recorded invalidations remain effective. Feed recovery failures persist a visible
pause with a retry reason. Observation and signal consumption commit together.
Browser verification covered future-session synthetic auto/proposal arms and
retired them without placing preview orders. Complete replay/sweep UI, source
validation, broker normalization and rollout evidence remain unfinished.

Execution work now includes provisional management of confirmed partial fills,
same-position cumulative fill reconciliation, and serialized entry/exit updates.
Profit-taking waits for terminal entry settlement while stops remain active.
Residual fills after closure are separately reconciled and flattened. The entry
controller now submits through OrderManager/RiskGate and hands real sim fills
to management, including options, through the public runtime. Primary campaign cancellation has verified-order
reconciliation and restart tests. Persisted execution-readiness checks now block
new exposure when earlier orders, fills or restored positions are unresolved,
without disabling protective exits. Daily price/fee P&L and an optional persisted
day-loss latch now have a Desk card and authenticated report API. FX translation
is excluded and missing marks remain unknown. The card can recover compatible
missing prior closes through shared history without overwriting existing rows.
Scheduled scan/recovery integration, daily-history catch-up and broker time/fee
normalization remain rollout work (PLAN.md).

Independent screening primitives now exist in
`backend/zargar/techniques/options_cartel/` (rules, completed-session data,
market/universe screening, measured setup candidates, reviewed plan preparation
and causal entry/exit reading). An authenticated research API persists analyses,
reviewed plans, entry replays and reviews. The collection endpoint fetches daily
and intraday history through the shared provider and reports missing fundamental/
industry metadata. An earlier Cartel suite passed 131 cases (including 6 PostgreSQL
API tests); a live read-only history probe also succeeded. Full source research,
setup/entry/exit logic, runtime integration and the app page remain in progress.

The requested end state is a complete independent technique with its own
navigation page, method details, scanning/focus list, plans, arming controls,
execution/position management, history, review, and verification. Research alone
or a static page does not complete this task.

## Documents

The in-app Method library bundles the method, rules, source reviews, examples,
ledger, industry, replay and scanning chapters directly from these files.
Rebuild the frontend after documentation updates to refresh the shipped library.

- [DELIVERY-STATUS.md](DELIVERY-STATUS.md): current implementation, evidence and remaining work.

- [METHOD.md](METHOD.md): source-backed rules, version differences, unresolved details.
- [SOURCES.md](SOURCES.md): sources actually inspected and the remaining research queue.
- [PLAN.md](PLAN.md): complete implementation and acceptance worklist.
- [TRADING-RULES.md](TRADING-RULES.md): this method's own decisions and evidence.
- [REPLAY.md](REPLAY.md): campaign simulation, input provenance and outcome limits.
- [INDUSTRY-DATA.md](INDUSTRY-DATA.md): ranking workflow and historical evidence requirements.
- [SCANNING.md](SCANNING.md): multi-symbol focus-list scans and remaining automation work.
- [EXAMPLES.md](EXAMPLES.md): inspected trade examples, actor attribution and calibration limits.
- [LEDGER-REVIEW.md](LEDGER-REVIEW.md): full retrieved Sean-tab structural audit and return limitations.
- [RELATED-SOURCES.md](RELATED-SOURCES.md): related-account discovery and author ownership boundaries.

Do not edit EM, Tips, Flow, or Team2 method documents or rules for this technique.
Reuse technique-agnostic engine capabilities; any required shared additions must
preserve other techniques' behavior and be logged in PLATFORM-RULES.
Use only the Codex worktree and `zargar_test_codex`; never attach an additional
engine to the existing runtime database. See root AGENTS.md.

## Current findings

This is a momentum swing method, not Team2's intraday 0DTE method. It selects
leaders in strong markets/themes, waits for consolidation and volume-supported
breakouts, and manages partial exits over days or weeks. The September thread
and June thread agree on the central process but differ in some timeframe and
exit details. Those differences remain explicit in METHOD.md.

No claim is made that every public post has been captured. SOURCES.md records
coverage; media inspection, related-account posts, historical examples, and
the linked videos remain part of the research requirement.
