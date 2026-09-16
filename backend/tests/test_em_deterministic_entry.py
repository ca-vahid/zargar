"""deterministic-entry-v1 (2026-09-15): the pure EM entry decision. Every family has a valid case and a failed /
unknown-required case; a kind label never manufactures confirmation; replay is deterministic; not-encoded judgments
stay diagnostic. No I/O, no model, no clock, no settings."""
import statistics
import time

from zargar.domain import Bar
from zargar.marketstructure.tracker import TriggerTracker
from zargar.technique.entry_decision import (DECISION_VERSION, EntryPolicy, EntrySnapshot, evaluate_entry, policy_from_thresholds,
                                             snapshot_from_tracker)
from zargar.technique.rulebook import Thresholds

DAY = 1_789_479_000_000            # 2026-09-15 09:30 ET


def bars(closes, *, vol=1_000, start=DAY, hl=0.3):
    return [Bar(symbol="X", tf="1m", ts=start + i * 60_000, open=c, high=c + hl, low=c - hl, close=c, volume=vol) for i, c in enumerate(closes)]


def base_snapshot(**kw) -> EntrySnapshot:
    d = dict(attempt_id="a1", run_id="run", plan_id="run", plan_version="v", session="2026-09-15", plan_status="armed",
             trigger_id="b1", family="bounce", direction="long", entry=100.0, stop=99.0, targets=(101.0, 102.0, 103.0),
             tracker_status="fired", fired_ts=DAY + 5 * 60_000, fired_window="prime_open",
             signal_bar={"ts": DAY + 5 * 60_000, "open": 100.2, "high": 100.4, "low": 99.9, "close": 100.1, "volume": 1000},
             fired_event={"ts": DAY + 5 * 60_000, "event": "fired", "window": "prime_open", "rel": 0.9, "fill": 100.0},
             tracker_events=(), gap_unchecked=False, gap_day=False, failed_breaks=0, continuation=False, received_ts=DAY + 6 * 60_000)
    d.update(kw)
    return EntrySnapshot(**d)


POLICY = EntryPolicy(thresholds={"volume_floor_mult": 0.5, "volume_spike_mult": 1.5, "max_false_breaks": 2, "followthrough_bars": 2,
                                 "followthrough_required": 1})


def test_bounce_at_the_level_allows_without_a_reclaim_candle_and_a_stop_close_refuses():
    d = evaluate_entry(base_snapshot(), POLICY)
    assert d.verdict == "allow" and d.confirmation_variant == "touch" and d.decision_version == DECISION_VERSION
    assert {c.name: c.outcome for c in d.checks if c.authority == "entry_required"} == {
        "plan_current": "pass", "trigger_family": "pass", "geometry": "pass", "tracker_fired": "pass", "stop_intact": "pass",
        "window": "pass", "volume": "pass", "confirmation": "pass", "exhausted": "pass"}
    # a firing bar closed through the stop is refused with the T4.3d code
    bad = base_snapshot(signal_bar={"ts": DAY + 5 * 60_000, "open": 100.2, "high": 100.4, "low": 98.5, "close": 98.9, "volume": 1000})
    r = evaluate_entry(bad, POLICY)
    assert r.verdict == "refuse" and "stop_invalidated" in r.reason_codes


def test_reject_short_mirrors_direction_and_volume_below_floor_refuses():
    ok = base_snapshot(family="reject", direction="short", entry=100.0, stop=101.0, targets=(99.0, 98.0, 97.0),
                       signal_bar={"ts": DAY + 5 * 60_000, "open": 100.1, "high": 100.5, "low": 99.8, "close": 99.9, "volume": 1000})
    assert evaluate_entry(ok, POLICY).verdict == "allow"
    low = base_snapshot(family="reject", direction="short", entry=100.0, stop=101.0, targets=(99.0, 98.0, 97.0),
                        signal_bar={"ts": DAY + 5 * 60_000, "open": 100.1, "high": 100.5, "low": 99.8, "close": 99.9, "volume": 1000},
                        fired_event={"ts": DAY + 5 * 60_000, "event": "fired", "rel": 0.2})
    r = evaluate_entry(low, POLICY)
    assert r.verdict == "refuse" and "volume_below_floor" in r.reason_codes
    unknown = base_snapshot(fired_event={"ts": DAY + 5 * 60_000, "event": "fired", "rel": None})
    u = evaluate_entry(unknown, POLICY)
    assert u.verdict == "defer" and "volume_unknown" in u.reason_codes and "unknown_required" in u.reason_codes


def test_breakout_needs_its_actual_followthrough_branch_and_a_kind_label_cannot_confirm():
    events = ({"ts": DAY + 3 * 60_000, "event": "break_candidate", "rel": 2.1, "window": "prime_open"},
              {"ts": DAY + 5 * 60_000, "event": "fired", "window": "prime_open", "fill": 100.6, "confirmedAfter": 2})
    ok = base_snapshot(family="breakout", entry=100.5, stop=99.5, targets=(102.0, 103.0, 104.0), fired_event=events[1], tracker_events=events,
                       signal_bar={"ts": DAY + 5 * 60_000, "open": 100.5, "high": 100.9, "low": 100.4, "close": 100.7, "volume": 3000})
    d = evaluate_entry(ok, POLICY)
    assert d.verdict == "allow" and d.confirmation_variant == "normal_followthrough"
    # the same trigger named "breakout" with a tracker that only reached observed: NOT confirmed
    label_only = base_snapshot(family="breakout", entry=100.5, stop=99.5, targets=(102.0, 103.0, 104.0), tracker_status="observed",
                               fired_ts=None, fired_event=None, tracker_events=())
    r = evaluate_entry(label_only, POLICY)
    assert r.verdict == "refuse" and "trigger_not_fired" in r.reason_codes and "break_not_confirmed" in r.reason_codes
    # a fired note without its candidate evidence is an unknown-required, never a pass
    partial = base_snapshot(family="breakout", entry=100.5, stop=99.5, targets=(102.0, 103.0, 104.0),
                            fired_event={"ts": DAY + 5 * 60_000, "event": "fired"}, tracker_events=(),
                            signal_bar={"ts": DAY + 5 * 60_000, "open": 100.5, "high": 100.9, "low": 100.4, "close": 100.7, "volume": 3000})
    p = evaluate_entry(partial, POLICY)
    assert p.verdict == "defer" and p.checks[[c.name for c in p.checks].index("confirmation")].outcome == "unknown"


def test_breakdown_short_mirror_and_wedge_break_reuse_the_break_path():
    events = ({"ts": DAY + 3 * 60_000, "event": "break_candidate", "rel": 1.8}, {"ts": DAY + 5 * 60_000, "event": "fired", "confirmedAfter": 2})
    bd = base_snapshot(family="breakdown", direction="short", entry=99.5, stop=100.5, targets=(98.0, 97.0, 96.0), fired_event=events[1],
                       tracker_events=events, signal_bar={"ts": DAY + 5 * 60_000, "open": 99.5, "high": 99.6, "low": 99.0, "close": 99.2, "volume": 3000})
    assert evaluate_entry(bd, POLICY).verdict == "allow"
    wedge = base_snapshot(family="wedge_break", entry=100.5, stop=99.5, targets=(102.0, 103.0, 104.0), fired_event=events[1], tracker_events=events,
                          signal_bar={"ts": DAY + 5 * 60_000, "open": 100.5, "high": 100.9, "low": 100.4, "close": 100.7, "volume": 3000})
    assert evaluate_entry(wedge, POLICY).confirmation_variant == "normal_followthrough"
    weak = base_snapshot(family="breakdown", direction="short", entry=99.5, stop=100.5, targets=(98.0, 97.0, 96.0), fired_event=events[1],
                         tracker_events=({"ts": DAY + 3 * 60_000, "event": "break_candidate", "rel": 1.0}, events[1]),
                         signal_bar={"ts": DAY + 5 * 60_000, "open": 99.5, "high": 99.6, "low": 99.0, "close": 99.2, "volume": 3000})
    r = evaluate_entry(weak, POLICY)
    assert r.verdict == "refuse" and "volume_below_floor" in r.reason_codes


def test_range_break_and_loose_continuation_record_bypassed_checks_honestly():
    rb = base_snapshot(family="breakout", entry=100.5, stop=99.5, targets=(102.0, 103.0, 104.0),
                       fired_event={"ts": DAY + 5 * 60_000, "event": "fired", "rel": 0.8, "rangeBreak": True},
                       signal_bar={"ts": DAY + 5 * 60_000, "open": 100.5, "high": 100.9, "low": 100.4, "close": 100.7, "volume": 3000})
    d = evaluate_entry(rb, POLICY)
    conf = next(c for c in d.checks if c.name == "confirmation")
    assert d.verdict == "allow" and d.confirmation_variant == "range_break" and "follow_through" in conf.facts["bypassed"]
    lc = base_snapshot(family="breakout", continuation=True, entry=100.5, stop=99.5, targets=(102.0, 103.0, 104.0),
                       fired_event={"ts": DAY + 5 * 60_000, "event": "fired", "rel": 0.6, "loose": True},
                       signal_bar={"ts": DAY + 5 * 60_000, "open": 100.5, "high": 100.9, "low": 100.4, "close": 100.7, "volume": 3000})
    assert evaluate_entry(lc, POLICY).confirmation_variant == "loose_continuation"


def test_exhausted_level_plan_not_current_and_bad_geometry_refuse():
    r = evaluate_entry(base_snapshot(failed_breaks=2), POLICY)
    assert r.verdict == "refuse" and "level_exhausted" in r.reason_codes
    r = evaluate_entry(base_snapshot(plan_status="paused"), POLICY)
    assert r.verdict == "refuse" and "plan_not_current" in r.reason_codes
    r = evaluate_entry(base_snapshot(stop=101.0), POLICY)
    assert r.verdict == "refuse" and "geometry_invalid" in r.reason_codes
    r = evaluate_entry(base_snapshot(targets=()), POLICY)
    assert r.verdict == "defer" and "geometry_unknown_required" in r.reason_codes


def test_not_encoded_judgments_are_diagnostic_and_provenance_never_refuses():
    d = evaluate_entry(base_snapshot(level_provenance={"touches": 12, "sources": ["T1.3c"], "builtFromSession": "2026-09-14", "basis": ["next_resistance"]}), POLICY)
    diag = {c.name: c for c in d.checks if c.authority == "diagnostic"}
    assert d.verdict == "allow" and diag["higher_timeframe_fakeout"].outcome == "unknown" and diag["live_chop"].outcome == "unknown"
    assert diag["level_provenance"].outcome == "pass" and "gap" in diag
    assert "higher_timeframe_fakeout" in d.not_encoded


def test_replay_is_deterministic_and_the_input_hash_binds_policy():
    a = evaluate_entry(base_snapshot(), POLICY); b = evaluate_entry(base_snapshot(), POLICY)
    assert a.to_dict() == b.to_dict() and a.input_hash == b.input_hash and a.decision_id == b.decision_id
    other = evaluate_entry(base_snapshot(), EntryPolicy(thresholds={**POLICY.thresholds, "volume_floor_mult": 0.95}))
    assert other.input_hash != a.input_hash and other.verdict == "refuse"     # rel 0.9 < 0.95
    assert evaluate_entry(base_snapshot(attempt_id="a2"), POLICY).decision_id != a.decision_id


def test_snapshot_from_a_real_tracker_transition_and_policy_from_thresholds():
    t = Thresholds()
    trig = {"id": "b1", "kind": "bounce", "direction": "long", "entry": {"price": 100.0, "basis": "at_level"},
            "stop": {"price": 99.0}, "targets": [{"price": 101.0, "basis": "next_resistance"}, {"price": 102.0, "basis": "next_resistance"}],
            "level": {"price": 100.0, "touches": 4, "sources": ["T1.2"]}}
    tr = TriggerTracker(trigger=trig, thresholds=t, gap_rules=False)
    seq = bars([101.0] * 24 + [100.05], vol=1_000)
    for i, b in enumerate(seq):
        tr.on_bar(b, i)
    assert tr.status == "fired"
    snap = snapshot_from_tracker(attempt_id="a9", run_id="run", plan={"planFor": "2026-09-15", "builtFromSession": "2026-09-14"}, plan_status="armed",
                                 trigger_id="b1", tracker=tr, signal_bar={"ts": seq[-1].ts, "open": 100.05, "high": 100.35, "low": 99.75, "close": 100.05, "volume": 1000},
                                 received_ts=seq[-1].ts + 900, decided_ts=None)
    assert snap.fired_event["event"] == "fired" and snap.family == "bounce" and snap.targets == (101.0, 102.0)
    d = evaluate_entry(snap, policy_from_thresholds(t))
    assert d.verdict == "allow" and d.thresholds_hash and d.signal_bar_close == seq[-1].ts + 60_000 and d.received_time == seq[-1].ts + 900


def test_local_decision_latency_is_millisecond_scale():
    snaps = [base_snapshot(attempt_id=f"a{i}", fired_event={"ts": DAY + 5 * 60_000, "event": "fired", "rel": 0.6 + (i % 7) / 10}) for i in range(400)]
    samples = []
    for s in snaps:
        t0 = time.perf_counter(); evaluate_entry(s, POLICY); samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    p50, p95, p99 = samples[len(samples) // 2], samples[int(len(samples) * 0.95)], samples[int(len(samples) * 0.99)]
    assert p99 < 50.0, (p50, p95, p99)            # bounded local computation; the model wait it replaces was 14-22 s
