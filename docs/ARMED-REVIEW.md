# Flagged-plan review

The top-bar indicator counts **plans**, not setup messages, across both workspaces.
It opens `/armed/attention`, also available through Armed → Needs review. The URL
survives refresh and browser navigation. Ordinary Live and History views remain available.

Every flagged plan has a named stock, registered technique, account and workspace.
One plan can contain several setup messages. Setup labels and entry prices explain
the condition; original references such as b1/b2 remain in expandable technical details.
Explicit Unicode dash escapes are rendered as punctuation, not shown as source text.

Known risk-refused attempts with zero fills, no remaining exposure and no pending
entry are presented as notices. Held positions, uncertain submissions, missing
details and other problems remain actionable review items. This is presentation
classification only: engine flags, order status, risk caps and execution behavior
are unchanged. No acknowledgement suppresses a live problem.

The review list is read-only across workspaces. Trading controls appear only for
the selected workspace and known account kind, through explicit plan expansion.
Opening the indicator never changes trading mode or issues an order.

Verification: `cd frontend; node scripts/armed-attention-audit.mjs` after building.
The harness uses a static build and synthetic API/WebSocket data, never an engine
or database. It covers multiple messages in one plan, multiple stocks, live-account
visibility from Practice, uncertain/held outcomes, URL reload, empty/error states,
light/dark desktop/phone layouts and absence of mutation requests.

The mobile gate also covers `/armed/attention`. The Armed, review and History routes
passed 15 device/route combinations using a loopback frontend preview and read-only
access to the existing API. The smallest-phone header fits the device width and
technical-detail disclosures have touch-sized targets. Uncertain submissions and
pending proposals cannot be downgraded to no-action notices.

Deployment handoff, 2026-09-14: the running checkout has overlapping uncommitted
frontend work and its served assets differ from the committed-baseline build.
Production assets and source files were left untouched to preserve that work.
Integrate the merged review changes into the next coordinated frontend deployment.

For a frontend-only update during market hours, backend health continues reporting
the running process's previous version until the next normal safe restart. Do not
restart the trading engine solely to update that label; verify served UI and backend
provenance separately.
