"""Focused delivery review. Runs without Postgres, providers, engine or paid calls.

From the reviewed backend:
  python <absolute path to this file>
The two tests execute actual preview/report code with in-memory persistence seams.
"""
import asyncio
import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from zargar.models import Setting
from zargar.tools import em_fire_policy_migration as migration
from zargar.tools import em_profitability as report


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _PreviewSession:
    def __init__(self):
        self.rows = [Setting(key="technique.arm.use_critic", value={"v": True})]
        self.writes = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt):
        return _Rows(self.rows)

    async def scalars(self, stmt):
        return _Rows([])

    def add(self, row):
        self.writes.append(("add", row.key))

    async def commit(self):
        self.writes.append(("commit",))


class _ReportConnection:
    def __init__(self):
        self.ts = report._ms(dt.date(2026, 9, 16), 10, 0)
        self.decision = {"decisionId": "attempt-2", "fireAttemptId": "attempt-2", "decisionVersion": "deterministic-entry-v1", "verdict": "allow"}
        self.trade = {"triggerId": "b1", "kind": "bounce", "direction": "long", "firedTs": self.ts,
                      "entry": 100.0, "stop": 99.0, "targets": [103.0], "status": "closed", "instrument": "options",
                      "filledQty": 1, "avgFill": 2.0, "multiplier": 100, "entryOrderId": "entry-2",
                      "openedTs": self.ts, "closedTs": self.ts + 60000,
                      "exits": [{"orderId": "exit-2", "kind": "tp1"}], "decision": self.decision}
        self.events = [
            {"ts": self.ts - 600000, "type": "TechniquePlanTriggerFired", "payload": {
                "trigger": "b1", "fireDecisionMode": "legacy", "criticMode": "momentum_only", "criticDisposition": "vetoed"}},
            {"ts": self.ts, "type": "TechniquePlanTriggerFired", "payload": {
                "trigger": "b1", "fireDecisionMode": "deterministic", "decision": self.decision}},
            {"ts": self.ts, "type": "TechniquePlanOrderIntent", "payload": {
                "trigger": "b1", "decision": self.decision, "secType": "OPT", "qty": 1,
                "contract": {"symbol": "X260918C00100000", "bid": 1.98, "ask": 2.0, "delta": 0.5}}},
        ]

    async def execute(self, *args):
        return None

    async def fetchrow(self, *args):
        return None

    async def fetch(self, query, *args):
        if "from technique_armed" in query:
            return [{"run_id": "run-1", "symbol": "X", "config": {}, "state": {"trades": [self.trade]},
                     "plan": {"triggers": [{"id": "b1", "kind": "bounce", "direction": "long", "levelPrice": 100.0,
                                             "targets": [{"price": 103.0, "basis": "next_resistance"}]}]}}]
        if "from events" in query:
            return self.events
        if "from executions where order_id" in query:
            return [{"order_id": "entry-2", "side": "BUY", "qty": 1, "price": 2.0, "commission": 1.04, "ts": self.ts},
                    {"order_id": "exit-2", "side": "SELL", "qty": 1, "price": 3.0, "commission": 1.04, "ts": self.ts + 60000}]
        return []

    async def close(self):
        pass


class MigrationReportingTests(unittest.TestCase):
    def test_preview_does_not_migrate_stored_settings(self):
        session = _PreviewSession()
        engine = SimpleNamespace(dispose=AsyncMock())
        journal = SimpleNamespace(append=AsyncMock())
        with patch("zargar.config.get_config", return_value=SimpleNamespace(database_url="unused")), \
             patch("zargar.db.make_engine", return_value=engine), \
             patch("zargar.db.make_session_factory", return_value=lambda: session), \
             patch("zargar.events.Journal", return_value=journal):
            asyncio.run(migration.preview())
        self.assertEqual(session.writes, [], "A read-only migration preview must not persist canonical settings")
        journal.append.assert_not_awaited()

    def test_fill_policy_belongs_to_its_attempt_after_legacy_refire(self):
        conn = _ReportConnection()
        with patch("asyncpg.connect", new=AsyncMock(return_value=conn)), \
             patch.object(report, "LEDGER", "__deliberately_absent_ledger__"):
            data = asyncio.run(report.build("2026-09-16"))
        self.assertEqual(len(data["trades"]), 1)
        trade = data["trades"][0]
        self.assertAlmostEqual(trade["netRealized"], 97.92)
        self.assertEqual(trade["policyVersion"], "deterministic-entry-v1",
                         "The second-attempt fill must not inherit the first legacy veto's policy")
        self.assertEqual(trade["decisionId"], "attempt-2")
        summary = report.summarize(data)
        self.assertEqual(sum(b["attempts"] for b in summary["byPolicy"].values()), 2,
                         "The first refused attempt must remain in the policy comparison")


if __name__ == "__main__":
    unittest.main(verbosity=2)
