"""Event journal: the append-only audit trail and source of truth.

Every decision the system makes lands here (order intents, risk verdicts,
fills, halts, approvals, config changes). Quotes are NOT journaled — they're
transient market state, not decisions.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from . import bus as topics
from .bus import Bus
from .models import Event


# --- event type constants ------------------------------------------------
ORDER_INTENT_CREATED = "OrderIntentCreated"
RISK_CHECK_PASSED = "RiskCheckPassed"
RISK_CHECK_FAILED = "RiskCheckFailed"
ORDER_SUBMITTED = "OrderSubmitted"
ORDER_ACCEPTED = "OrderAccepted"
ORDER_FILL = "OrderFill"
ORDER_FILLED = "OrderFilled"
ORDER_CANCELLED = "OrderCancelled"
ORDER_REJECTED = "OrderRejected"
ORDER_EXPIRED = "OrderExpired"
ORDER_DRY_RUN = "OrderDryRun"
POSITION_UPDATED = "PositionUpdated"
KILL_SWITCH_ENGAGED = "KillSwitchEngaged"
KILL_SWITCH_RELEASED = "KillSwitchReleased"
DAILY_LOSS_HALT = "DailyLossHalt"
DAILY_DRIFT_WARNING = "DailyDriftWarning"
SETTING_CHANGED = "SettingChanged"
CONTENT_RECEIVED = "ContentReceived"
SIGNAL_EXTRACTED = "SignalExtracted"
SIGNAL_VERIFIED = "SignalVerified"
SIGNAL_VERIFICATION_FAILED = "SignalVerificationFailed"
PROPOSAL_CREATED = "ProposalCreated"
PROPOSAL_APPROVED = "ProposalApproved"
PROPOSAL_REJECTED = "ProposalRejected"
PROPOSAL_EXPIRED = "ProposalExpired"
BROKER_CONNECTED = "BrokerConnected"
BROKER_DISCONNECTED = "BrokerDisconnected"
BROKER_SYNC = "BrokerSync"
BROKER_SYNC_MISMATCH = "BrokerSyncMismatch"
POSITION_RECONCILED = "PositionReconciled"
BROKER_ORDER_LINKED = "BrokerOrderLinked"
BROKER_SUBMIT_UNKNOWN = "BrokerSubmitUnknown"
BROKERAGE_ACCOUNT_LINKED = "BrokerageAccountLinked"
BROKER_CAPABILITY_CHECKED = "BrokerCapabilityChecked"
OPTION_EXPIRED = "OptionExpired"
TECHNIQUE_RUN_STARTED = "TechniqueRunStarted"
TECHNIQUE_RUN_COMPLETED = "TechniqueRunCompleted"
TECHNIQUE_RUN_FAILED = "TechniqueRunFailed"
TECHNIQUE_SETUP_EMITTED = "TechniqueSetupEmitted"
TECHNIQUE_GROUNDING_FAILED = "TechniqueGroundingFailed"
TECHNIQUE_SCAN = "TechniqueScan"
TECHNIQUE_OUTCOME_SCORED = "TechniqueOutcomeScored"
TECHNIQUE_REVIEW_ADDED = "TechniqueReviewAdded"
TECHNIQUE_RUN_REPLAYED = "TechniqueRunReplayed"
TECHNIQUE_SWEEP_STARTED = "TechniqueSweepStarted"
TECHNIQUE_SWEEP_COMPLETED = "TechniqueSweepCompleted"
TECHNIQUE_PLAN_ARMED = "TechniquePlanArmed"
TECHNIQUE_PLAN_DISARMED = "TechniquePlanDisarmed"
TECHNIQUE_PLAN_TRIGGER_FIRED = "TechniquePlanTriggerFired"
TECHNIQUE_PLAN_TRIGGER_SKIPPED = "TechniquePlanTriggerSkipped"
TECHNIQUE_PLAN_PAUSED = "TechniquePlanPaused"
TECHNIQUE_PLAN_RESUMED = "TechniquePlanResumed"
TECHNIQUE_PLAN_ORDER_INTENT = "TechniquePlanOrderIntent"
TECHNIQUE_PLAN_ORDER_RESULT = "TechniquePlanOrderResult"
TECHNIQUE_PLAN_POSITION_OPENED = "TechniquePlanPositionOpened"
TECHNIQUE_PLAN_EXIT = "TechniquePlanExit"
TECHNIQUE_PLAN_POSITION_CLOSED = "TechniquePlanPositionClosed"
TECHNIQUE_PLAN_ERROR = "TechniquePlanError"
CHAT_THREAD_CREATED = "ChatThreadCreated"
CHAT_TOOL_CALLED = "ChatToolCalled"


class Journal:
    def __init__(self, session_factory: async_sessionmaker, bus: Bus) -> None:
        self._sf = session_factory
        self._bus = bus

    async def append(
        self,
        type_: str,
        payload: dict[str, Any] | None = None,
        *,
        aggregate_type: str | None = None,
        aggregate_id: str | None = None,
        portfolio_id: str | None = None,
    ) -> dict:
        payload = payload or {}
        async with self._sf() as session:
            evt = Event(
                type=type_,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                portfolio_id=portfolio_id,
                payload=payload,
                ts=dt.datetime.now(dt.timezone.utc),
            )
            session.add(evt)
            await session.commit()
            record = {
                "id": evt.id,
                "ts": evt.ts.isoformat(),
                "type": type_,
                "aggregateType": aggregate_type,
                "aggregateId": aggregate_id,
                "portfolioId": portfolio_id,
                "payload": payload,
            }
        self._bus.publish(topics.EVENTS, record)
        return record
