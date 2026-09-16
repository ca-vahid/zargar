"""Migration preview for the deterministic entry mode (2026-09-15). READ-ONLY: lists every active EM arm with its
stored legacy `useCritic`, the EFFECTIVE policy the next fire attempt will use, and any critic-only legacy state
(critic kills, critic failures, refire cooldowns, paused-by-critic) so a person can decide what to release. Nothing is
rewritten, unpaused, cleared or re-armed here.

    python -m zargar.tools.em_fire_policy_migration preview [--json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def preview() -> dict:
    from sqlalchemy import select
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..models import TechniqueArmed
    from ..settings_service import SettingsService
    from ..bus import Bus
    from ..events import Journal
    cfg = get_config(); eng = make_engine(cfg.database_url); sf = make_session_factory(eng)
    bus = Bus(); journal = Journal(sf, bus); settings = SettingsService(sf, bus, journal); await settings.load()
    try:
        mode = str(settings.get("techniques.enhanced_market.fire_decision_mode", "deterministic") or "deterministic")
        evidence = str(settings.get("techniques.enhanced_market.fire_evidence_mode", "off") or "off")
        critic_mode = str(settings.get("techniques.enhanced_market.critic_mode", settings.get("technique.arm.critic_mode", "veto")))
        async with sf() as session:
            rows = (await session.scalars(select(TechniqueArmed).where(TechniqueArmed.technique == "enhanced_market",
                                                                       TechniqueArmed.status.in_(("armed", "paused"))))).all()
        plans = []
        for r in rows:
            cfgd = r.config or {}; st = r.state or {}
            use_critic = bool(cfgd.get("useCritic", True))
            kills = st.get("criticKills") or {}; refire = st.get("refireAt") or {}; failures = int(st.get("criticFailures") or 0)
            paused_reason = str(st.get("stopReason") or "")
            critic_paused = r.status == "paused" and ("critic" in paused_reason.lower())
            unsupported = [t for t in ((r.state or {}).get("trackers") or {}).keys()
                           if str(((r.state or {}).get("trackers") or {}).get(t, {}).get("status")) in ("fired",)]   # consumed triggers never re-fire
            plans.append({"runId": r.run_id, "symbol": r.symbol, "planFor": r.plan_for, "status": r.status, "mode": cfgd.get("mode"),
                          "legacyUseCritic": use_critic, "legacyCriticMode": critic_mode,
                          "oldEffective": ("critic:" + critic_mode if use_critic else "no-critic"),
                          "newEffective": (mode if mode in ("deterministic", "legacy") else f"invalid:{mode}"),
                          "criticKills": kills, "criticFailures": failures, "refireAt": refire, "criticOnlyPaused": critic_paused,
                          "consumedTriggers": unsupported,
                          "note": ("critic-only cooldown/kill state present - left untouched; releasing it is a separate explicit step" if (kills or refire or failures) else "")})
        return {"effectiveFireDecisionMode": mode, "fireEvidenceMode": evidence, "decisionVersion": ("deterministic-entry-v1" if mode == "deterministic" else None),
                "plans": plans, "counts": {"total": len(plans), "legacyUseCriticTrue": sum(1 for p in plans if p["legacyUseCritic"]),
                                           "withCriticOnlyState": sum(1 for p in plans if p["criticKills"] or p["refireAt"] or p["criticFailures"]),
                                           "criticOnlyPaused": sum(1 for p in plans if p["criticOnlyPaused"])},
                "policy": "read-only preview: no arm rewritten, no plan unpaused, no cooldown cleared; the effective mode is resolved per fire attempt from the EM setting"}
    finally:
        await eng.dispose()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preview"); p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = asyncio.run(preview())
    if a.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        print(f"effective mode {out['effectiveFireDecisionMode']} ({out['decisionVersion']}), evidence {out['fireEvidenceMode']}; {out['counts']}")
        for p in out["plans"]:
            print(f"  {p['symbol']:6} {p['planFor']} {p['status']:6} useCritic={p['legacyUseCritic']!s:5} old={p['oldEffective']:22} new={p['newEffective']:14} "
                  f"kills={p['criticKills']} failures={p['criticFailures']} refire={list(p['refireAt'].keys())} {p['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
