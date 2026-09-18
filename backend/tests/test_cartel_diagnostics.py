"""D3/D4/D5 diagnostics (2026-09-18): pure, no database, no orders, no decision changes."""
from dataclasses import replace

from zargar.domain import Bar
from zargar.techniques.options_cartel.entry import bucket_diagnostics, read_entry
from zargar.techniques.options_cartel.execution import spread_cost
from zargar.techniques.options_cartel.observer import CONFIRMATION_MAX_AGE_MS, DropRegistry

from .test_options_cartel_entry import MIN, OPEN, plan, tape


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


def test_drop_registry_counts_per_symbol_session_and_journals_at_most_once_per_interval():
    registry = DropRegistry(interval_ms=300_000, keep=3)
    now = OPEN + 30 * MIN
    late = OPEN + 5 * MIN                               # bar closed 24 minutes ago: beyond the 120 s acceptance
    assert now - (late + MIN) > CONFIRMATION_MAX_AGE_MS
    for i in range(5):
        entry = registry.note("HOOD", late + i * MIN, now)
    assert entry["count"] == 5 and len(entry["recent"]) == 3 and entry["maxAgeMs"] == now - (late + MIN)
    assert registry.due("r1", "HOOD", now) is True
    registry.mark_journaled("r1", "HOOD", now)
    assert registry.due("r1", "HOOD", now + 1_000) is False          # nothing new
    registry.note("HOOD", late + 6 * MIN, now + 2_000)
    assert registry.due("r1", "HOOD", now + 2_000) is False          # new drop but inside the interval
    assert registry.due("r1", "HOOD", now + 300_000) is True         # interval elapsed and count grew
    assert registry.due("r1", "OTHER", now) is False                 # no drops for that symbol
    next_day = registry.note("HOOD", OPEN + 24 * 60 * MIN, OPEN + 24 * 60 * MIN + 30 * MIN)
    assert next_day["count"] == 1                                    # a new session resets the tally
