# Preparation workspace correction — 0.7.4

The user reported that the Practice account dropdown appeared in Live mode and
requested support for both workspaces with separate settings. This corrects the
Practice-only UI and backend boundary introduced with daily preparation.

- Practice retains `techniques.options_cartel.preparation`, its settings and
  existing records. Live uses `techniques.options_cartel.preparation_live` and
  starts disabled, with no selected account or live acknowledgements.
- The shared workspace hooks filter accounts. The old ambiguous automatic-account
  option is removed from the UI; a sole Practice account is displayed directly.
  Live accounts must be selected explicitly; broker-paper accounts belong to Live.
- Configuration/status requests carry an explicit workspace. The backend validates
  account kind and policy identity. Settings changes cancel only their own worker.
  Concurrent requests cannot join the other workspace's preparation run.
- Scheduled dispatch and pending-contract activation follow the active workspace.
  Mode changes during collection prevent arming in the former workspace. Prepared
  entry submission checks workspace, account kind and existing permissions again.
- Live requires both preparation acknowledgements, the independent shared Cartel
  live-auto permission and connected broker, plus the existing entry/risk checks.
  Saving a preparation policy does not grant that shared permission implicitly.
  Phone exit-only policy blocks Live preparation enable/run requests.
- Latest preparation, quote-refresh issues and automatic saved plans are scoped.
  Legacy automatic records remain Practice-owned; account-neutral research is shared.
  Changing mode clears unsaved UI drafts and prevents stale responses crossing views.
- Working orders and held-position protection retain their existing lifecycle.

Verification: 413 Cartel/platform-separation tests passed. The new fixture drives
actual Practice and Live arming with a stub connected executor and confirms zero
orders during preparation. It covers independent result lists, legacy records,
wrong-account rejection, missing permissions and workspace changes. API tests cover
scope mismatch, default isolation, acknowledgements and phone restrictions.

The production build and release consistency check passed. Browser checks confirmed
mode-specific dropdowns, fresh defaults and unsaved-draft separation. Plans and
Settings passed on five mobile devices in both Practice and Live. UI mode switching
was exercised only on the blank-key isolated sim preview, with preparation disabled,
and its original mode was restored. No normal-runtime settings were changed.

Operation and schedule details: [DAILY-PREPARATION.md](DAILY-PREPARATION.md).
