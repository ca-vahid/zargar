# Cartel release and operational handoff

Current documentation: 2026-09-13. Latest Cartel-specific functional delivery: v0.7.51–0.7.52. Other techniques can advance the app-wide version independently.

The next correctness release is described in [September 13 readiness](READINESS-2026-09-13.md), with the [final audit](FINAL-REVIEW-2026-09-13.md) preserved as historical evidence. Its deployment checkpoint will supersede the September 12 operational snapshot below.

- [Current capabilities and limits](DELIVERY-STATUS.md)
- [Preparation/settings/recovery](DAILY-PREPARATION.md)
- [Ignition research and Practice pilot](IGNITION.md)
- [September 12 deployment evidence](DEPLOYMENT-2026-09-12.md)
- [Release scope and validation limits](RELIABILITY-RELEASE-2026-09-12.md)
- [Current backlog](PLAN.md)

The September 12 verification found APA, NOV and CGNX armed for September 14 with 26/26 baseline periods and first-entry-session-close expiry. This is historical evidence, not a current account recommendation or guarantee those arms remain active. Verify the UI and persisted state before an operational action.

Before deployment, compare current main with the actual desk checkout, preserve committed parallel work and dirty files, validate the integrated build/version metadata, inspect active work, and use only the authorized managed runtime procedure. Afterwards verify backend and served frontend versions, Cartel arms separately, managed positions and orders. The shared ops inventory observed on September 12 did not enumerate Cartel arms; it was supplemented with a separate check.

For Codex work: do not start a second engine or point tests at the runtime database. Use the isolated test wrapper, build before tests that serve dist, and follow root AGENTS.md rather than historical launcher/PID instructions.

The previous handoff is [archived](archive/RELEASE-HANDOFF-PRE-2026-09-13.md). Its preview-only deployment boundary and old suite counts do not describe current delivery.
