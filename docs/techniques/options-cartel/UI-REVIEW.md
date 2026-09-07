# Cartel desk consistency review — 0.7.3

Reviewed against CLAUDE.md (versioning, mobile rules, testing), ARCHITECTURE.md,
BUILDING-A-TECHNIQUE.md, MOBILE-PLAN.md, Team2 PLAN.md G-2, Team2Page.tsx,
the shared design tokens/components, routing and Cartel's existing controls.

| Finding | Change |
| --- | --- |
| A large promotional heading and pill navigation differed from the compact Team2 desk | Shared `tips-page`, `tips-head` and underline `tabs`; Plans is the default |
| The desk mixed routine execution with long research and settings forms | Plans, Armed, History and Validation separate daily tasks; Method and Settings have dedicated tabs |
| Configuration appeared before the daily shortlist | Plans shows schedule/account status, Prepare now and the shortlist; Settings contains the editable policy |
| Cards, buttons and inputs had independent sizing and rounded shapes | Shared panels, tables, status pills, symbol icons and primary/ghost/link buttons; spacing/type/radius tokens |
| Active plans appeared on unrelated tabs | Workspace-filtered Armed table, Monitor links to the shared Armed hub, and existing risk/management controls |
| Saved plans were crowded out by recent scan analyses | Dedicated `mode=plan` fetch, separate from the latest research history |
| Opening a record required scrolling past the entire desk | Details open below the current task and receive scroll/keyboard focus; an explicit Close details action |
| Tab and details navigation lacked a keyboard pattern | Selected tab, arrow/Home/End navigation, busy-state protection and visible shared focus styles |
| Loading, empty and error displays were inconsistent | Reuse shared Spinner, EmptyState and ErrorState; preparation errors support retry |
| Preparation success had no release entry; version locations could diverge | 0.7.3 in all version sources and lock metadata, curated user-facing changelog, build-time release consistency check |
| Mobile audit still assumed the old desk layout | Update its navigation/selectors and cover all six Cartel tabs; phone rules stay in mobile.css |

## Scope and preservation

Presentation and release metadata only. Trading rules, setup thresholds,
automatic Practice policy, risk gates and order execution remain unchanged.
Manual evidence capture, scanning, replay, contract selection, arming, reviews,
source library and recovery/recording controls remain accessible. Legacy
`/techniques/options-cartel/desk` opens Plans; all new tabs are deep-linkable.

The automatic preparation guide is now available in the Method chapter picker.
The page retains Cartel's own method language and source versions; unifying the
interface does not adopt Team2's trading rules.

## Verification

Build includes the version consistency gate. Browser checks cover desktop light
and dark themes, phone/tablet layout, keyboard tabs, saved-plan details, and
settings visibility. Backend API/health tests use only zargar_test_codex.
Exact results are recorded in the PR. Runtime preview uses zargar_dev_codex on
8421; the normal app and Claude worktrees are preserved.

Verified for this change: 73 backend/API tests passed; production build and
release consistency check passed; the isolated API reports 0.7.3. All six tabs
passed across five mobile device configurations (tablet font failures were
corrected and the affected routes rerun). The read-only desktop audit passed
light/dark views, keyboard navigation, settings separation, saved-plan details,
empty/error/retry states and the legacy desk URL. The expanded plan controls
also passed on all five mobile devices. Existing Vite chunk/import warnings remain.

Commands: `npm run build`, `node scripts/cartel-desk-audit.mjs` (frontend), and
`scripts/test-codex.ps1 tests/test_api_and_pipeline.py tests/test_options_cartel_api.py -q`
(repository root). The mobile audit accepts MOBILE_AUDIT_ROUTES for focused
checks; its default route list now includes all six Cartel tabs.
