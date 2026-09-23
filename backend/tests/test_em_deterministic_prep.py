"""em-deterministic-prep-v1 (2026-09-23, user decision "EM fully deterministic"): the BASELINE book prepares from the graded
sheet with rules only - zero model calls - once `preparation_policy` is deterministic; off, it does nothing."""
import asyncio

from sqlalchemy import select

from zargar.models import Event, TechniqueArmed, TechniqueRun
from zargar.technique import em_deterministic_prep as dp

from .conftest import wait_for
from .test_em_experiment import _pin_sheet_geometry
from .test_technique_arming import rig  # noqa: F401  (rig is a fixture)


async def _sheet(rig, monkeypatch):
    from zargar.technique import service as svc_mod
    from zargar.marketstructure import sessions as wf
    monkeypatch.setattr(svc_mod, "last_completed_session", lambda now_ms=None: rig.days[3].isoformat())
    await rig.eng.settings.set("technique.walkforward.workers", 1, journal=False)
    await rig.eng.settings.set("techniques.enhanced_market.default_portfolio", rig.sim["id"], journal=False)
    for k, v in (("instrument", "shares"), ("risk_pct", 1.0), ("max_qty", 50), ("slippage_pct", 1.0)):
        await rig.eng.settings.set(f"execution.{k}", v, journal=False)
    sheet = await rig.svc.start_plan_sheet(["TEST"], label="sheet", wait=True)
    await _pin_sheet_geometry(rig, sheet["id"])
    plan_for = sheet["params"]["planFor"]
    monkeypatch.setattr(wf, "next_session_date", lambda now_ms: plan_for)
    dp._PREPARED.clear(); dp._PREPARING.clear()
    return sheet, plan_for


async def test_off_by_default_it_prepares_nothing(rig, monkeypatch):
    _sheet_, plan_for = await _sheet(rig, monkeypatch)
    assert await dp.auto_prepare(rig.svc, 0) is None
    out = await dp.prepare(rig.svc, plan_for)
    assert out["armed"] == 0 and "not deterministic" in out["errors"][0]


async def test_deterministic_baseline_arms_the_sheet_with_zero_model_calls_once(rig, monkeypatch):
    _sheet_, plan_for = await _sheet(rig, monkeypatch)
    await rig.eng.settings.set("techniques.enhanced_market.preparation_policy", "deterministic", journal=False)
    assert await dp.auto_prepare(rig.svc, 0) == plan_for and await dp.auto_prepare(rig.svc, 0) is None, "single flight"
    await wait_for(lambda: plan_for in dp._PREPARED, timeout=20)
    async with rig.eng.sf() as s:
        ev_ = (await s.execute(select(Event).where(Event.type == "TechniquePrepared"))).scalars().one().payload
        armed = (await s.execute(select(TechniqueArmed).where(TechniqueArmed.status == "armed"))).scalars().all()
        runs = (await s.execute(select(TechniqueRun).where(TechniqueRun.trigger == dp.TRIGGER))).scalars().all()
    assert ev_["errors"] == [] and (ev_["eligible"], ev_["minted"], ev_["armed"], ev_["modelCalls"]) == (1, 1, 1, 0), ev_
    assert [a.portfolio_id for a in armed] == [rig.sim["id"]], "armed into the BASELINE book"
    assert len(runs) == 1 and not (runs[0].result or {}).get("passes"), "zero model passes"
    assert not any(str(t).startswith("experiment:") for t in (runs[0].tags or [])), "a baseline run carries no experiment tag"
    dp._PREPARED.clear()
    assert await dp.auto_prepare(rig.svc, 0) is None and plan_for in dp._PREPARED, "after a restart the DATABASE says it is prepared"
    a, b = await asyncio.gather(dp.prepare(rig.svc, plan_for), dp.prepare(rig.svc, plan_for))
    for r in (a, b):
        assert (r["minted"], r["armed"], r["alreadyArmed"]) == (0, 0, 1), "a second / concurrent preparation mints and arms nothing new"
    via_api = (await rig.client.post("/api/technique/em/prepare", params={"planFor": plan_for})).json()
    assert (via_api["minted"], via_api["armed"], via_api["alreadyArmed"], via_api["modelCalls"]) == (0, 0, 1, 0)
