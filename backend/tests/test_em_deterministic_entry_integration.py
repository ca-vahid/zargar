"""deterministic-entry-v1 (2026-09-15): the shared runner's fire branch. A never-resolving model sentinel, an occupied
model semaphore, a restored `useCritic=true` arm and an absent LLM key must not touch the deterministic entry; a
deterministic refusal is never `critic_killed` and no advisory policy can downgrade it; `legacy` keeps the old veto;
other desks keep the legacy default. No DB, no engine start, no orders (the entry is a seam)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from zargar.domain import Bar
from zargar.execution.planrunner import ArmConfig, ArmedPlan, FireJudgement, PlanRunner
from zargar.marketstructure.tracker import TriggerTracker
from zargar.technique.arming import PlanArmer
from zargar.technique.rulebook import Thresholds

DAY = 1_789_479_000_000


class _Settings(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


class NeverResolves:
    """A model client that hangs forever; touching it at all is the failure."""
    def __init__(self):
        self.touched = 0

    async def create(self, **kw):
        self.touched += 1
        await asyncio.Event().wait()


class FakeTechnique:
    def __init__(self, settings, *, llm_available=True):
        self._settings = settings; self.llm_available = llm_available
        self.client = NeverResolves(); self.chat = None; self.persisted = []

    def thresholds(self):
        return Thresholds()

    def llm_config(self):
        return SimpleNamespace(available=self.llm_available, effort="low", api_key="k" if self.llm_available else None)

    def _get_client(self):
        return self.client

    async def _persist_setup(self, run_id, symbol, a, contract, options, grounded=True):
        self.persisted.append((run_id, a.verdict))

    async def get_run(self, run_id):
        return {"setups": [{"id": "setup-1"}]}


def fired_tracker(kind="bounce", direction="long"):
    trig = {"id": "b1", "kind": kind, "direction": direction, "entry": {"price": 100.0, "basis": "at_level"}, "stop": {"price": 99.0 if direction == "long" else 101.0},
            "targets": [{"price": 101.0 if direction == "long" else 99.0, "basis": "next_resistance"}, {"price": 102.0 if direction == "long" else 98.0, "basis": "next_resistance"}],
            "levelPrice": 100.0, "level": {"price": 100.0, "kind": "support", "effectiveKind": "support", "touches": 4, "sources": ["T1.2"]},
            "setupType": "support_bounce", "label": "b1", "riskReward": 3.0, "confidence": 0.6, "valid": True}
    tr = TriggerTracker(trigger=trig, thresholds=Thresholds(), gap_rules=False)
    closes = [101.0] * 24 + [100.05] if direction == "long" else [99.0] * 24 + [99.95]
    for i, c in enumerate(closes):
        tr.on_bar(Bar(symbol="X", tf="1m", ts=DAY + i * 60_000, open=c, high=c + 0.3, low=c - 0.3, close=c, volume=1000), i)
    assert tr.status == "fired"
    return tr, Bar(symbol="X", tf="1m", ts=DAY + 24 * 60_000, open=closes[-1], high=closes[-1] + 0.3, low=closes[-1] - 0.3, close=closes[-1], volume=1000)


def rig(settings, *, use_critic=True, llm_available=True, mode="auto"):
    st = _Settings(settings)
    engine = SimpleNamespace(settings=st, journal=SimpleNamespace(append=AsyncMock()), quotes=SimpleNamespace(get=lambda s: None),
                             quiesce_until_ms=0, sf=None, bars=SimpleNamespace(bars=lambda *a, **k: []),
                             positions=SimpleNamespace(equity=AsyncMock(return_value=10_000.0), portfolio=lambda pid: {"id": pid, "kind": "sim"}))
    tech = FakeTechnique(st, llm_available=llm_available)
    r = PlanArmer(engine, tech)
    r._log, r._publish, r._persist, r._alert = Mock(), Mock(), AsyncMock(), AsyncMock()
    r._enter = AsyncMock()                       # the existing entry chain is the seam under test
    r.pick_contract = AsyncMock(return_value=None)
    r._entry_gated = AsyncMock(return_value=None)
    r.after_fire = AsyncMock()
    tr, bar = fired_tracker()
    ap = ArmedPlan(run_id="run", symbol="X", plan={"planFor": "2026-09-15", "builtFromSession": "2026-09-14", "triggers": [tr.trigger]},
                   plan_for="2026-09-15", config=ArmConfig(portfolio_id="p", mode=mode, instrument="shares", use_critic=use_critic), trackers={"b1": tr}, armed_at=0)
    ap.status = "armed"; r._armed[ap.run_id] = ap
    return r, ap, tr, bar, tech


def run_fire(r, ap, tr, bar, *, timeout=5.0):
    async def go():
        await asyncio.wait_for(r._fire(ap, "b1", tr, bar, 24, journal=True), timeout)
    asyncio.run(go())


def test_deterministic_fire_never_touches_the_model_and_reaches_the_entry_chain():
    r, ap, tr, bar, tech = rig({"techniques.enhanced_market.fire_decision_mode": "deterministic"}, use_critic=True, llm_available=True)
    r.review_fire = AsyncMock(side_effect=AssertionError("the reviewer must not be called on the deterministic path"))
    run_fire(r, ap, tr, bar)
    trade = ap.trades["b1"]
    assert tech.client.touched == 0 and r.review_fire.await_count == 0
    assert trade.decision["verdict"] == "allow" and trade.decision["decisionVersion"] == "deterministic-entry-v1"
    assert trade.decision_disposition == "allowed" and trade.critic_disposition == "deterministic" and trade.critic is None
    assert r._enter.await_count == 1
    kinds = [c.args[0] for c in r.engine.journal.append.await_args_list]
    assert "TechniqueEntryDecision" in kinds and "TechniquePlanTriggerFired" in kinds
    fired = next(c.args[1] for c in r.engine.journal.append.await_args_list if c.args[0] == "TechniquePlanTriggerFired")
    assert fired["fireDecisionMode"] == "deterministic" and fired["criticDisposition"] == "deterministic" and fired["decision"]["decisionId"]
    assert trade.timing["decidedTs"] >= trade.timing["receivedTs"] and trade.timing["decisionMs"] < 1000


def test_restored_legacy_use_critic_arm_and_missing_llm_key_still_decide_deterministically():
    r, ap, tr, bar, tech = rig({"techniques.enhanced_market.fire_decision_mode": "deterministic"}, use_critic=True, llm_available=False)
    run_fire(r, ap, tr, bar)
    assert ap.trades["b1"].decision["verdict"] == "allow" and r._enter.await_count == 1 and tech.client.touched == 0
    view = r.fire_policy_view(ap)
    assert view["effectiveFireDecisionMode"] == "deterministic" and view["criticEffective"] is False and view["legacyUseCritic"] is True


def test_deterministic_refusal_is_not_critic_killed_and_advisory_policy_cannot_downgrade_it():
    r, ap, tr, bar, tech = rig({"techniques.enhanced_market.fire_decision_mode": "deterministic",
                                "techniques.enhanced_market.critic_mode": "advisory"})
    tr.failed_breaks = 3                         # R3.2 exhausted (the tracker would already be terminal; the rule refuses regardless)
    run_fire(r, ap, tr, bar)
    trade = ap.trades["b1"]
    assert trade.status == "refused" and trade.decision_disposition == "refused" and "level_exhausted" in trade.decision["reasonCodes"]
    assert trade.status != "critic_killed" and not trade.critic_advisory and r._enter.await_count == 0
    assert ap.critic_kills == {} and ap.refire_at == {} and ap.critic_failures == 0
    assert tr.status == "fired"                  # a consumed trigger is never re-fired by a deterministic refusal


def test_invalid_policy_refuses_with_a_policy_error_and_never_falls_back_to_the_model():
    r, ap, tr, bar, tech = rig({"techniques.enhanced_market.fire_decision_mode": "auto_magic"})
    run_fire(r, ap, tr, bar)
    trade = ap.trades["b1"]
    assert trade.status == "refused" and trade.decision_disposition == "policy_error" and tech.client.touched == 0 and r._enter.await_count == 0


def test_legacy_mode_keeps_the_old_reviewer_branch_with_its_veto():
    r, ap, tr, bar, tech = rig({"techniques.enhanced_market.fire_decision_mode": "legacy", "techniques.enhanced_market.critic_mode": "veto",
                                "execution.critic_timeout_seconds": 5})
    r.review_fire = AsyncMock(return_value=("no_setup", 0.2, {"kill": True, "summary": "model veto", "violations": []}))
    run_fire(r, ap, tr, bar)
    trade = ap.trades["b1"]
    assert r.review_fire.await_count == 1 and trade.status == "critic_killed" and trade.critic_disposition == "vetoed"
    assert trade.decision is None and r._enter.await_count == 0


def test_generic_desks_default_to_legacy_and_a_late_model_opinion_cannot_mutate_the_decision():
    generic = PlanRunner(SimpleNamespace(settings=_Settings({}), journal=SimpleNamespace(append=AsyncMock())))
    assert generic.fire_review_policy(None) == "legacy" and generic.fire_evidence_mode(None) == "off"
    assert asyncio.run(generic.fire_decision(None, "b1", None, None, attempt_id="x")) is None
    # a later opinion over a COPY of the frozen decision leaves the executed record untouched
    r, ap, tr, bar, tech = rig({"techniques.enhanced_market.fire_decision_mode": "deterministic"})
    run_fire(r, ap, tr, bar)
    before = dict(ap.trades["b1"].decision)
    from zargar.technique.entry_evidence import frozen_input, isolated_analysis
    fi = frozen_input({"runId": "run", "symbol": "X", "trigger": "b1", **ap.trades["b1"].decision}, tr.trigger)
    a = isolated_analysis(fi)
    a.verdict, a.confidence = "no_setup", 0.0          # the evidence copy may be mutated freely
    assert ap.trades["b1"].decision == before and ap.trades["b1"].status != "critic_killed" and ap.trades["b1"].decision_disposition == "allowed"
