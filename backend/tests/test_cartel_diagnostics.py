"""D3/D4/D5 diagnostics (2026-09-18): pure, no database, no orders, no decision changes."""
import datetime as dt
from dataclasses import replace

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.entry import bucket_diagnostics, read_entry
from zargar.techniques.options_cartel.execution import spread_cost
from zargar.techniques.options_cartel.observer import CONFIRMATION_MAX_AGE_MS, DropRegistry

from .test_options_cartel_entry import DAY, MIN, OPEN, plan, tape


def test_data_refusals_record_known_measurements_without_deriving_a_crossing():
    bars = tape()
    missing = read_entry(plan(), bars[1:], OPEN + 10 * MIN)          # first minute absent -> missing_bucket
    refusal = next(t for t in missing["trace"] if t["decision"] == "missing_bucket")
    known = refusal["known"]
    assert known["minutesPresent"] == 4 and known["minutesMissing"] == [OPEN] and known["minutesUntrusted"] == []
    assert known["partialHigh"] == 48.75 and known["partialLow"] == 48.4 and known["partialVolume"] == 2000
    assert known["slotBaseline"] == 1000.0 and "crossing" in known["notComputed"] and len(known["bucketInputHash"]) == 64
    assert missing["signal"] is None or missing["signal"]["at"] != OPEN + 5 * MIN  # the decision itself is unchanged

    sampled = [replace(b, source="sampled" if i == 2 else "exchange") for i, b in enumerate(bars)]
    untrusted = read_entry(plan(entry=plan().entry.model_copy(update={"require_exchange_bars": True})), sampled, OPEN + 10 * MIN)
    refusal = next(t for t in untrusted["trace"] if t["decision"] == "untrusted_confirmation")
    assert refusal["known"]["minutesUntrusted"] == [OPEN + 2 * MIN] and refusal["known"]["minutesPresent"] == 5


def test_bucket_input_hash_changes_with_inputs_and_is_stable_otherwise():
    bars = tape()
    day = {b.ts: b for b in bars}
    p = plan()
    once = bucket_diagnostics(day, OPEN, OPEN + 5 * MIN, OPEN, p)["bucketInputHash"]
    again = bucket_diagnostics(day, OPEN, OPEN + 5 * MIN, OPEN, p)["bucketInputHash"]
    revised = {**day, OPEN: replace(bars[0], volume=bars[0].volume + 1)}
    other = bucket_diagnostics(revised, OPEN, OPEN + 5 * MIN, OPEN, p)["bucketInputHash"]
    assert once == again and once != other
    triggered = read_entry(p, bars, OPEN + 10 * MIN)
    assert triggered["status"] == "triggered"
    final = triggered["trace"][-1]
    assert final["decision"] == "triggered" and len(final["bucketInputHash"]) == 64


def test_spread_cost_reports_cents_percent_and_quantity_dollars():
    cost = spread_cost(1.86, 2.39, 2)
    assert cost == {"cents": 53.0, "pctOfMid": 24.94, "usdPerUnit": 53.0, "usdForQuantity": 106.0, "quantity": 2}
    assert spread_cost(2.39, 1.86, 2) is None          # crossed quote: nothing to report
    assert spread_cost(None, 2.39, 2) is None
    assert spread_cost(1.0, 1.1, 0)["usdForQuantity"] == 0.0


# ------------------------------------------------------------------- D4 registry

NEXT_DAY = DAY + dt.timedelta(days=1)          # 2026-05-06, a trading day
NEXT_OPEN, NEXT_CLOSE = session_bounds(NEXT_DAY.isoformat())


def _row(status="armed", phase="waiting", opens=OPEN, expires=NEXT_CLOSE):
    return {"status": status, "state": {"phase": phase, "opensAt": opens, "expiresAt": expires}}


def test_eligibility_requires_an_armed_waiting_plan_and_a_minute_inside_its_horizon():
    two_day = plan(first_session=DAY, last_session=NEXT_DAY)
    assert DropRegistry.eligible(_row(), two_day, OPEN + 5 * MIN)
    assert DropRegistry.eligible(_row(), two_day, NEXT_OPEN + 5 * MIN)
    assert not DropRegistry.eligible(_row(status="paused"), two_day, OPEN + 5 * MIN)
    assert not DropRegistry.eligible(_row(phase="signalled"), two_day, OPEN + 5 * MIN)
    previous_session = OPEN - 24 * 60 * MIN                     # a bar from the day before the plan's first session
    assert not DropRegistry.eligible(_row(), two_day, previous_session)
    assert not DropRegistry.eligible(_row(), plan(), NEXT_OPEN + 5 * MIN)   # single-session plan: tomorrow is outside
    assert not DropRegistry.eligible(_row(expires=OPEN + 10 * MIN), two_day, OPEN + 20 * MIN)


def test_registry_counts_distinct_minutes_and_duplicates_per_plan_session_and_resets_on_rollover():
    registry = DropRegistry(interval_ms=300_000, keep=3)
    now = OPEN + 30 * MIN
    late = OPEN + 5 * MIN
    assert now - (late + MIN) > CONFIRMATION_MAX_AGE_MS
    for i in range(5):
        entry = registry.note("r1", late + i * MIN, now)
    registry.note("r1", late, now + 1_000)                          # the same minute delivered twice
    assert entry["count"] == 5 and entry["duplicates"] == 1 and len(entry["recent"]) == 3
    assert registry.due("r1", now) is not None
    registry.mark = None
    # journal, then the same count is not due again inside the interval
    entry["journaledCount"], entry["journaledAt"] = 5, now
    assert registry.due("r1", now + 1_000) is None
    registry.note("r1", late + 6 * MIN, now + 2_000)
    assert registry.due("r1", now + 2_000) is None                  # inside the interval
    assert registry.due("r1", now + 300_000) is not None            # interval elapsed and the count grew
    # rollover: the next session starts a fresh entry; yesterday's journaled count cannot suppress today's first drop
    fresh = registry.note("r1", NEXT_OPEN + 5 * MIN, NEXT_OPEN + 40 * MIN)
    assert fresh["count"] == 1 and fresh["journaledCount"] == 0 and fresh["journaledAt"] is None
    assert registry.due("r1", NEXT_OPEN + 40 * MIN) is not None
    assert [k for k in registry.entries if k[0] == "r1"] == [("r1", NEXT_DAY.isoformat())]   # only one live session per plan


def test_registry_prunes_retired_plans_and_stays_bounded():
    registry = DropRegistry(max_entries=3)
    now = OPEN + 30 * MIN
    for i in range(5):
        registry.note(f"r{i}", OPEN + 5 * MIN, now + i)
    assert len(registry.entries) == 3 and ("r0", DAY.isoformat()) not in registry.entries     # oldest evicted
    registry.retire("r4")
    assert registry.snapshot("r4") is None and len(registry.entries) == 2
    assert "minutes" not in registry.snapshot("r3")                                          # the set never leaves the registry


@pytest.mark.asyncio
async def test_flush_isolates_persistence_failures_and_only_marks_successes():
    registry = DropRegistry()
    now = OPEN + 30 * MIN
    registry.note("ok", OPEN + 5 * MIN, now)
    registry.note("broken", OPEN + 5 * MIN, now)
    calls = []

    async def persist(run_id, payload):
        calls.append((run_id, payload["count"], payload["session"]))
        if run_id == "broken":
            raise RuntimeError("journal unavailable")

    flushed = await registry.flush(["ok", "broken", "unknown"], now, persist)
    assert flushed == ["ok"] and [c[0] for c in calls] == ["ok", "broken"]
    assert registry.snapshot("broken")["journalFailures"] == 1 and registry.snapshot("broken")["journaledCount"] == 0
    assert registry.snapshot("ok")["journaledCount"] == 1
    # a restart starts from zero in memory; the last persisted summary lives on the arm row, not here
    assert DropRegistry().snapshot("ok") is None
