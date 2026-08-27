"""TipRunner — the tip technique on the shared PlanRunner.

The runner owns everything that moves money (BUILDING-A-TECHNIQUE.md §2);
this class supplies the tip's opinions, which are deliberately few:

- rules(): touch-fire mechanics with NO volume requirement (volume_floor_mult=0
  — the tracker's opt-out, platform plan §2.1), no gap-magnitude void
  (gapped past/through the level still kills — those are real), all RTH
  windows (extended-hours suppression stays runner-core).
- no reviewer in v1 (the human/source policy is the judge); analyze_fire says
  "setup" with the trigger's own confidence.
- v1 arms **level-touch** tips only. A tip-time tip is an immediate proposal
  (the signals pipeline already does that); arming is for the waiting game.

Settings resolve `techniques.tip.<key>` → `execution.<key>` via `self.rt`
(instrument defaults to shares in v1 — option expression is Phase B).
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import select

from ... import events as ev
from ...domain import new_id
from ...execution.planrunner import ArmConfig, FireJudgement, PlanRunner
from ...marketstructure import SESSION_WINDOWS, MarketRules
from ...models import Signal, TechniqueRun

log = logging.getLogger("zargar.techniques.tip")

ARMABLE_STATUSES = ("verified", "parked", "proposed")


class TipRunner(PlanRunner):
    TECHNIQUE_ID = "tip"

    def __init__(self, engine) -> None:
        super().__init__(engine, name="tip-runner")

    # ------------------------------------------------------------- hooks
    def rules(self) -> MarketRules:
        s = self.engine.settings
        return MarketRules(
            level_tolerance_pct=float(s.get("techniques.tip.touch_tolerance_pct", 0.002)),
            volume_floor_mult=0.0,          # tips carry no volume rule (tracker opt-out)
            gap_void_r=1e9,                 # no gap-magnitude void; gapped past/through still applies
            windows=SESSION_WINDOWS,        # any RTH window may fire
            stop_on_close=True,
        )

    async def load_plan(self, run_id: str) -> dict | None:
        async with self.engine.sf() as session:
            row = await session.get(TechniqueRun, run_id)
        if row is None or row.technique != self.TECHNIQUE_ID:
            return None
        return {"id": row.id, "symbol": row.symbol, "mode": row.mode,
                "result": row.result or {}, "config": row.config or {}, "tags": row.tags or []}

    async def analyze_fire(self, ap, tid, tr, trade) -> FireJudgement:
        conf = float((tr.trigger.get("confidence") or 0.5))
        return FireJudgement(verdict="setup", confidence=conf)

    # ------------------------------------------------------------- tip-specific
    async def arm_signal(self, signal_id: str, config: ArmConfig | dict | None = None) -> dict:
        """Signal → today's tip plan → a minted `technique="tip"` run → armed.
        Level-touch tips only (a tip-time tip proposes immediately instead)."""
        svc = getattr(self.engine, "signals_service", None)
        if svc is None:
            raise RuntimeError("signals layer not attached")
        async with self.engine.sf() as session:
            sig = await session.get(Signal, signal_id)
        if sig is None:
            raise ValueError("unknown signal")
        if sig.status not in ARMABLE_STATUSES:
            raise ValueError(f"signal is {sig.status} — only verified/parked tips arm")
        from ...signals.sources import resolve_policy
        policy = resolve_policy(self.engine.settings, sig.source_name)
        if policy.entry != "level_touch":
            raise ValueError("this source's policy is tip_time — tip-time tips propose "
                             "immediately; arming is for level-touch tips")
        plan_dict = await svc.build_tip_plan_for(signal_id)
        if not any(t.get("valid") for t in plan_dict.get("triggers") or []):
            reasons = "; ".join((plan_dict.get("triggers") or [{}])[0].get("noTradeReasons") or [])
            raise ValueError(f"the tip plan has no valid trigger ({reasons or 'degenerate'})")
        source = sig.source_name or "unknown"
        run_id = new_id()
        row = TechniqueRun(
            id=run_id, technique=self.TECHNIQUE_ID, tags=[f"source:{source}"],
            symbol=sig.ticker, as_of=int(time.time() * 1000),
            primary_tf=str(plan_dict.get("triggerTf") or "5m"),
            mode="plan", trigger="tip", status="done", verdict="plan",
            result={"plan": plan_dict, "signalId": signal_id},
            config={"technique": self.TECHNIQUE_ID, "signalId": signal_id,
                    "source": source, "policy": policy.to_dict()},
        )
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        await self.engine.journal.append(
            ev.TECHNIQUE_RUN_COMPLETED,
            {"runId": run_id, "technique": self.TECHNIQUE_ID, "symbol": sig.ticker,
             "mode": "plan", "verdict": "plan", "signalId": signal_id, "source": source},
            aggregate_type="technique_run", aggregate_id=run_id)
        return await self.arm(run_id, config)

    async def runs_for_signal(self, signal_id: str) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TechniqueRun).where(TechniqueRun.technique == self.TECHNIQUE_ID)
                .order_by(TechniqueRun.created_at.desc()).limit(200))).scalars().all()
        return [{"id": r.id, "symbol": r.symbol, "status": r.status,
                 "createdAt": r.created_at.isoformat() if r.created_at else None}
                for r in rows if (r.result or {}).get("signalId") == signal_id]


async def attach_tip_runner(engine) -> None:
    """Called from the FastAPI lifespan after the engine + signals layer start."""
    if getattr(engine, "tip_runner", None) is not None:
        return
    engine.tip_runner = TipRunner(engine)
    try:
        restored = await engine.tip_runner.restore()
        if restored:
            log.info("tip runner restored %d armed plan(s)", restored)
    except Exception:  # pragma: no cover - restore must never block startup
        log.exception("tip runner restore failed")
