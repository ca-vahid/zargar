"""CR-01 / CR-02 (2026-09-15, corrected-review follow-ups): the after-close evidence command verifies the declared
decision identity against the captured material before rendering or buying an opinion, and the profitability report
counts refusal dispositions from the immutable attempt census once per full attempt identity (run + trigger + decision)."""
import asyncio
import copy
import datetime as dt
from dataclasses import asdict
from unittest.mock import AsyncMock, patch

from tests.test_em_deterministic_entry import POLICY, base_snapshot
from tests.test_policy_migration_reporting import _ReportConnection
from zargar.technique.entry_decision import evaluate_entry, frozen_bars_hash, recompute_input_hash
from zargar.technique.entry_evidence import frozen_thresholds, verify_identity
from zargar.tools import em_profitability as report


def _record():
    snap = base_snapshot()
    dec = evaluate_entry(snap, POLICY)
    bars = [{"ts": snap.fired_ts - (5 - i) * 60_000, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.1, "volume": 1000} for i in range(5)]
    return {"decisionId": "d1", "inputHash": dec.input_hash, "snapshot": asdict(snap),
            "policy": {"mode": POLICY.mode, "ruleVersion": POLICY.rule_version, "thresholds": dict(POLICY.thresholds), "enforceWindows": POLICY.enforce_windows},
            "frozenBars": bars, "frozenBarsHash": frozen_bars_hash(bars), "frozenBarsCount": len(bars), "signalBarClose": snap.fired_ts + 60_000}


def test_identity_verifies_from_the_captured_material_and_every_tamper_is_named():
    rec = _record()
    assert recompute_input_hash(rec["snapshot"], rec["policy"]) == rec["inputHash"]
    assert verify_identity(rec) is None
    t = copy.deepcopy(rec); t["frozenBars"][-1]["close"] += 50.0
    assert "frozenBarsHash" in verify_identity(t)
    t = copy.deepcopy(rec); t["policy"]["thresholds"]["volume_floor_mult"] = 0.9
    assert "inputHash" in verify_identity(t)
    t = copy.deepcopy(rec); t["snapshot"]["stop"] = 90.0
    assert "inputHash" in verify_identity(t)
    t = copy.deepcopy(rec); t["frozenBarsCount"] = 4
    assert "frozenBarsCount" in verify_identity(t)
    t = copy.deepcopy(rec)
    t["frozenBars"].append({"ts": rec["signalBarClose"], "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})
    t["frozenBarsHash"] = frozen_bars_hash(t["frozenBars"]); t["frozenBarsCount"] = 6
    assert "after the signal bar close" in verify_identity(t)
    t = copy.deepcopy(rec); del t["snapshot"]
    assert verify_identity(t) == "no frozen snapshot/policy"


def test_derived_facts_use_the_frozen_policy_values_and_disclose_it():
    th, label = frozen_thresholds({"thresholds": {"volume_spike_mult": 9.5, "not_a_threshold": 1}})
    assert th.volume_spike_mult == 9.5 and label == "frozen_policy_subset_over_defaults"
    th2, label2 = frozen_thresholds(None)
    assert label2.startswith("defaults_only") and th2.volume_spike_mult != 9.5


def test_refusals_are_counted_once_per_full_attempt_identity_across_runs():
    conn = _ReportConnection()
    base_events = list(conn.events)

    async def fetch(query, *args):
        if "from technique_armed" in query:
            rows = await _ReportConnection.fetch(conn, query, *args)
            second = copy.deepcopy(rows[0]); second["run_id"] = "run-2"; second["state"] = {"trades": []}
            return rows + [second]                      # a second run with the same trigger id = DISTINCT attempts
        if "from events" in query:
            run_id = args[0]                             # the report reads each run's own aggregate
            rows = [{"ts": dt.datetime.fromtimestamp(e["ts"] / 1000, dt.timezone.utc), "type": e["type"], "payload": {**e["payload"], "runId": run_id}}
                    for e in base_events]
            if run_id == "run-2":
                rows.append(copy.deepcopy(rows[0]))      # a duplicate delivery of run-2's veto (same run, trigger, bar) is ONE attempt
                rows.append({"ts": rows[0]["ts"] + dt.timedelta(minutes=1), "type": "TechniquePlanTriggerFired",   # unknown disposition: counted, never classified
                             "payload": {"trigger": "b1", "runId": "run-2", "fireDecisionMode": "legacy", "criticMode": "momentum_only", "criticDisposition": "weird"}})
            return rows
        return []

    conn.fetch = fetch
    with patch("asyncpg.connect", new=AsyncMock(return_value=conn)), patch.object(report, "LEDGER", "__deliberately_absent_ledger__"):
        data = asyncio.run(report.build("2026-09-16"))
    by = report.summarize(data)["byPolicy"]
    legacy = by["legacy-critic:momentum_only"]
    assert legacy["refused"] == 2, legacy                       # one veto per run - never per delivered event, never per row join
    assert legacy["attempts"] == 3, legacy                      # + the unknown-disposition attempt: counted but unclassified
    det = by["deterministic-entry-v1"]
    assert det["attempts"] == 2 and det["fills"] == 1 and det["refused"] == 0, det
