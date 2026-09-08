"""Authenticated, independent Cartel research routes. Runtime controls follow separately."""
import time

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from .. import events as ev
from ..models import Event
from ..techniques.options_cartel.automatic_plans import PreparationPolicy
from ..techniques.options_cartel.collect import CollectInput
from ..techniques.options_cartel.contracts import ContractSelectionInput, select_contract
from ..techniques.options_cartel.execution import ExecutionInput, preflight
from ..techniques.options_cartel.fundamentals import capture_fundamentals
from ..techniques.options_cartel.industry import IndustrySnapshot, save_snapshot
from ..techniques.options_cartel.jobs import PREFIX, ScheduleInput, schedule_status
from ..techniques.options_cartel.loss import daily_loss_report
from ..techniques.options_cartel.marks import recover_prior_marks
from ..techniques.options_cartel.membership import capture_membership
from ..techniques.options_cartel.plans import CartelPlan
from ..techniques.options_cartel.premium_replay import (
    PremiumReplayInput,
    StoredPremiumReplayInput,
    save_premium_replay,
    value_stored_quotes,
)
from ..techniques.options_cartel.preparation import (
    preparation_portfolio,
    preparation_status,
    stop_preparation,
    submit_preparation,
)
from ..techniques.options_cartel.preparation_scope import Workspace, active_workspace, setting_key
from ..techniques.options_cartel.quote_observations import capture_cached_quote, quote_observations
from ..techniques.options_cartel.replay_service import CampaignReplayRequest, replay_from_history
from ..techniques.options_cartel.scan_tasks import submit_scan
from ..techniques.options_cartel.scans import ScanRequest
from ..techniques.options_cartel.service import (
    CartelService,
    PlanInput,
    ReplayInput,
    ResearchInput,
    ReviewInput,
)
from ..techniques.options_cartel.sweeps import SweepRequest, run_sweep


def build_options_cartel_routes(app, eng, auth, config):
    service = CartelService(eng)
    eng.options_cartel = service

    @app.get('/api/options-cartel/preparation', dependencies=[auth])
    async def cartel_preparation_status(workspace: Workspace | None = None):
        return await preparation_status(eng, workspace)

    @app.post('/api/options-cartel/preparation/config', dependencies=[auth])
    async def cartel_preparation_config(body: PreparationPolicy, request: Request, workspace: Workspace | None = None):
        async def save():
            scope = workspace or active_workspace(eng)
            if body.workspace != scope:
                raise ValueError('Preparation settings belong to a different workspace')
            if scope == 'live' and body.enabled and request.headers.get('X-Zargar-Client') == 'phone' and eng.settings.get('mobile.exit_only', True):
                raise ValueError('Phones are exit-only on real accounts')
            if body.enabled or body.portfolio_id:
                await preparation_portfolio(eng, body.portfolio_id, scope)
            await eng.settings.set(setting_key(scope), body.model_dump(mode='json'))
            if not body.enabled:
                await stop_preparation(eng, scope)
            return await preparation_status(eng, scope)
        return await respond(save())

    @app.post('/api/options-cartel/preparation/run', dependencies=[auth], status_code=202)
    async def cartel_prepare_daily(request: Request, workspace: Workspace | None = None):
        scope = workspace or active_workspace(eng)
        if scope == 'live' and request.headers.get('X-Zargar-Client') == 'phone' and eng.settings.get('mobile.exit_only', True):
            raise HTTPException(status_code=400, detail='Phones are exit-only on real accounts')
        return await respond(submit_preparation(eng, workspace=scope))

    @app.post("/api/options-cartel/runs/{run_id}/premium-replay-stored", dependencies=[auth])
    async def cartel_stored_premium_replay(run_id: str, body: StoredPremiumReplayInput):
        return await respond(value_stored_quotes(service, run_id, body))

    class QuoteRecordingInput(BaseModel):
        model_config = {"extra": "forbid"}
        enabled: bool

    @app.get("/api/options-cartel/quote-recording", dependencies=[auth])
    async def cartel_quote_recording_status():
        recorder = getattr(getattr(eng, 'cartel_observer', None), 'quote_recorder', None)
        return recorder.status() if recorder is not None else {
            'enabled': bool(eng.settings.get('techniques.options_cartel.record_option_quotes', False)),
            'running': False, 'lastAttemptAt': None, 'captured': 0, 'errors': {}, 'sampleIntervalMs': 5000}

    @app.post("/api/options-cartel/quote-recording", dependencies=[auth])
    async def cartel_quote_recording_save(body: QuoteRecordingInput):
        await eng.settings.set('techniques.options_cartel.record_option_quotes', body.enabled)
        return await cartel_quote_recording_status()

    @app.post("/api/options-cartel/runs/{run_id}/option-quotes/{contract}", dependencies=[auth])
    async def cartel_capture_option_quote(run_id: str, contract: str):
        return await respond(capture_cached_quote(service, run_id, contract))

    @app.get("/api/options-cartel/runs/{run_id}/option-quotes/{contract}", dependencies=[auth])
    async def cartel_option_quote_observations(run_id: str, contract: str, limit: int = Query(1000, ge=1, le=40000)):
        return await respond(quote_observations(service, run_id, contract, limit=limit))

    @app.post("/api/options-cartel/runs/{run_id}/premium-replay", dependencies=[auth])
    async def cartel_premium_replay(run_id: str, body: PremiumReplayInput):
        return await respond(save_premium_replay(service, run_id, body))

    @app.post("/api/options-cartel/membership/{exchange}/{symbol}", dependencies=[auth])
    async def cartel_membership(exchange: str, symbol: str):
        return await respond(capture_membership(service, exchange, symbol))

    @app.post("/api/options-cartel/fundamentals/{symbol}", dependencies=[auth])
    async def cartel_fundamentals(symbol: str):
        return await respond(capture_fundamentals(service, symbol))

    @app.post("/api/options-cartel/industry-snapshots", dependencies=[auth])
    async def cartel_industry_snapshot(body: IndustrySnapshot):
        return await respond(save_snapshot(service, body))

    @app.get("/api/options-cartel/schedule", dependencies=[auth])
    async def cartel_schedule():
        return await schedule_status(eng)

    @app.post("/api/options-cartel/schedule", dependencies=[auth])
    async def cartel_schedule_save(body: ScheduleInput):
        await eng.settings.set_many({PREFIX+key: value for key, value in body.model_dump().items()})
        return await schedule_status(eng)

    @app.post("/api/options-cartel/scans", dependencies=[auth], status_code=202)
    async def cartel_scan(body: ScanRequest):
        return await respond(submit_scan(service, body))

    @app.post("/api/options-cartel/scans/{run_id}/retry", dependencies=[auth], status_code=202)
    async def cartel_retry_scan(run_id: str):
        return await respond(submit_scan(service, retry_id=run_id))

    @app.post("/api/options-cartel/sweeps", dependencies=[auth])
    async def cartel_sweep(body: SweepRequest):
        return await respond(run_sweep(service, body))

    def observer():
        value = getattr(eng, "cartel_observer", None)
        if value is None:
            raise HTTPException(503, "Cartel observer has not started")
        return value

    class AlertArmInput(BaseModel):
        model_config = {"extra": "forbid"}
        portfolioId: str

    class SignalApproval(BaseModel):
        model_config = {"extra": "forbid"}
        signalId: str

    @app.post("/api/options-cartel/runs/{run_id}/arm", dependencies=[auth])
    async def cartel_arm_execution(run_id: str, body: ExecutionInput, request: Request):
        return await respond(observer().arm(run_id, {"mode": body.mode, "portfolioId": body.portfolio_id,
            "execution": body.model_dump(), "clientKind": request.headers.get("X-Zargar-Client", "desktop")}))

    @app.get("/api/options-cartel/armed/{run_id}", dependencies=[auth])
    async def cartel_execution_detail(run_id: str):
        detail = observer().detail(run_id)
        if detail is None and hasattr(observer(), "load_detail"):
            detail = await respond(observer().load_detail(run_id))
        if detail is None:
            raise HTTPException(404, "Cartel armed plan not found")
        return detail

    @app.post("/api/options-cartel/armed/{run_id}/approve", dependencies=[auth])
    async def cartel_approve(run_id: str, body: SignalApproval):
        return await respond(observer().approve(run_id, body.signalId))

    @app.post("/api/options-cartel/armed/{run_id}/flatten", dependencies=[auth])
    async def cartel_flatten(run_id: str):
        return {"disarmed": await observer().disarm(run_id, reason="flatten requested", flatten=True)}

    @app.post("/api/options-cartel/runs/{run_id}/arm-alert", dependencies=[auth])
    async def cartel_arm_alert(run_id: str, body: AlertArmInput):
        return await respond(observer().arm(run_id, {"portfolioId": body.portfolioId, "mode": "alert"}))

    @app.get("/api/options-cartel/armed", dependencies=[auth])
    async def cartel_armed():
        return observer().armed()

    @app.post("/api/options-cartel/armed/{run_id}/pause", dependencies=[auth])
    async def cartel_pause(run_id: str):
        return await respond(observer().pause(run_id))

    @app.post("/api/options-cartel/armed/{run_id}/resume", dependencies=[auth])
    async def cartel_resume(run_id: str):
        return await respond(observer().resume(run_id))

    @app.post("/api/options-cartel/armed/{run_id}/disarm", dependencies=[auth])
    async def cartel_disarm(run_id: str):
        return {"disarmed": await observer().disarm(run_id)}

    async def respond(operation):
        try:
            return await operation
        except KeyError as exc:
            raise HTTPException(404, "Cartel run not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/options-cartel/analyze", dependencies=[auth])
    async def cartel_analyze(body: ResearchInput):
        return await respond(service.analyze(body))

    @app.get("/api/options-cartel/risk/{portfolio_id}", dependencies=[auth])
    async def cartel_risk_report(portfolio_id: str):
        async def read():
            report = await daily_loss_report(eng, portfolio_id, now_ms=int(time.time()*1000))
            report["limitPct"] = eng.settings.get("techniques.options_cartel.daily_loss_halt_pct", 0)
            async with eng.sf() as session:
                halt = await session.scalar(select(Event).where(Event.type == ev.OPTIONS_CARTEL_LOSS_HALT,
                    Event.portfolio_id == portfolio_id, Event.payload["day"].as_string() == report["day"]).limit(1))
            report["halted"] = halt is not None and bool(report["limitPct"])
            return report
        return await respond(read())

    @app.post("/api/options-cartel/risk/{portfolio_id}/recover-marks", dependencies=[auth])
    async def cartel_recover_marks(portfolio_id: str):
        return await respond(recover_prior_marks(eng, portfolio_id, now_ms=int(time.time()*1000)))

    @app.post("/api/options-cartel/collect", dependencies=[auth])
    async def cartel_collect(body: CollectInput):
        return await respond(service.collect_and_analyze(body))

    @app.get("/api/options-cartel/runs", dependencies=[auth])
    async def cartel_runs(limit: int = Query(50, ge=1, le=200), symbol: str | None = None,
                          mode: str | None = Query(None, max_length=24), workspace: Workspace | None = None):
        return await service.runs(limit, symbol, mode, workspace)

    @app.get("/api/options-cartel/runs/{run_id}", dependencies=[auth])
    async def cartel_run(run_id: str):
        return await respond(service.detail(run_id))

    @app.post("/api/options-cartel/runs/{run_id}/plan", dependencies=[auth])
    async def cartel_plan(run_id: str, body: PlanInput):
        return await respond(service.prepare(run_id, body))

    @app.post("/api/options-cartel/runs/{run_id}/replay", dependencies=[auth])
    async def cartel_replay(run_id: str, body: ReplayInput):
        return await respond(service.replay(run_id, body))

    @app.post("/api/options-cartel/runs/{run_id}/replay-campaign", dependencies=[auth])
    async def cartel_campaign_replay(run_id: str, body: CampaignReplayRequest):
        return await respond(replay_from_history(service, run_id, body))

    @app.post("/api/options-cartel/runs/{run_id}/reviews", dependencies=[auth])
    async def cartel_review(run_id: str, body: ReviewInput):
        return await respond(service.review(run_id, body))

    @app.post("/api/options-cartel/runs/{run_id}/preflight", dependencies=[auth])
    async def cartel_preflight(run_id: str, body: ExecutionInput, request: Request):
        async def evaluate():
            row = await service._load(run_id)
            if row.mode != "plan":
                raise ValueError("preflight requires a reviewed plan")
            plan = CartelPlan.model_validate(row.result["plan"]["plan"])
            client = request.headers.get("X-Zargar-Client", "desktop")
            if client not in ("phone", "tablet", "desktop"):
                client = "desktop"
            report = await preflight(eng, plan, body, client_kind=client)
            await eng.journal.append(ev.OPTIONS_CARTEL_PREFLIGHT,
                                     {"runId": run_id, "symbol": plan.symbol, "portfolioId": body.portfolio_id,
                                      "report": report}, aggregate_type="technique_run", aggregate_id=run_id,
                                     portfolio_id=body.portfolio_id)
            return report
        return await respond(evaluate())

    @app.post("/api/options-cartel/runs/{run_id}/contracts", dependencies=[auth])
    async def cartel_contracts(run_id: str, body: ContractSelectionInput):
        async def select():
            row = await service._load(run_id)
            if row.mode != "plan":
                raise ValueError("contract selection requires a reviewed plan")
            plan = CartelPlan.model_validate(row.result["plan"]["plan"])
            report = await select_contract(eng, plan, body)
            await eng.journal.append(ev.OPTIONS_CARTEL_CONTRACT_SELECTION,
                                     {"runId": run_id, "symbol": plan.symbol, "report": report},
                                     aggregate_type="technique_run", aggregate_id=run_id)
            return report
        return await respond(select())
