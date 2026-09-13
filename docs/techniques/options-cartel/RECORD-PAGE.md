# Dedicated Cartel records — current behavior (reviewed 2026-09-13)

Historical v0.7.6 defect: eight opens produced fifteen
chart sections. The detail fragment used the same run ID as the React key for
several sibling components. Each component now has a distinct key, and chart
cleanup owns only its dedicated host element. Repeated refreshes and range
changes retain one chart.

Records open at `/techniques/options-cartel/run/<runId>` as a dedicated view,
with a Back button and direct-load/refresh support. Standard links permit
modified-click/new-tab navigation. The shared URL sync waits for initial route
application instead of pushing the default page over the incoming URL.

Plan details lead with the selected setup, trigger, reviewed invalidation,
entry window and authoritative exit campaign. The preparation decision is
labeled as a snapshot; an active arm and its execution mode take precedence.
The page explains that passed checks establish eligibility, not an immediate
entry instruction. Structural target/risk distance is distinguished from the
actual entry stop and option-premium risk. Chart targets remain references;
the campaign's rungs determine exits.

The chart defaults to 30 saved sessions, with 60/all controls. Its indicators
still receive the full saved history for warm-up. Reference labels are listed
outside the plot to avoid overlapping target text. It remains a historical
snapshot, not a live price chart.

Evidence/alternative candidates and manual execution controls are separate
disclosures. Automatically prepared plans do not require clicking Arm alert
only. Saved rationale, campaign replay and record reviews remain available.
Automatic records viewed from the other workspace are read-only for execution
controls. Trading rules, budgets and execution machinery are unchanged.

Verification uses `frontend/scripts/cartel-record-audit.mjs` for direct URLs,
reload, Back/Forward, new tabs, missing records, and repeated refresh/range
changes. Existing desk/progress audits and the mobile device matrix also cover
the new navigation and expanded controls. Browser checks may use a synthetic static server; any backend tests use only zargar_test_codex. No running app is needed for documentation checks.


Current details include source-quality counts, persisted entry decisions and a whole-contract exit preview. The preview uses cumulative-floor allocation; a zero-sized first trim cannot move the stop to entry. Only actual fills advance live exits. Source counts/tape hashes do not constitute a complete historical provider-revision ledger. The preparation decision remains a snapshot; current arm state is authoritative for whether monitoring is active.
