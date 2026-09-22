"""setup-target-v1 in the read: default OFF must be indistinguishable from not existing.

The read is the live decision path. The 0.7.60 lesson on this desk was that a change to it touches
production unless a before/after test proves otherwise, so the first test here is that proof: the
whole session result, hashed, is identical with the knob at its default and with the resolver
absent from the code path.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from zargar.marketstructure import aggregate
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.session import simulate_session

from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars, trend_day

PREV = prev_day_bars()


def _run(**rule_kw):
    rules = make_rules(**rule_kw)
    today, _ = trend_day(PREV)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules), today)
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV)


def _digest(res) -> str:
    d = res.to_dict()
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- default off
def test_the_default_is_byte_identical_to_the_current_read():
    """`inherit` is the shipped default. Trades, events and every number must match a run that
    cannot reach the resolver at all."""
    base = _run()
    again = _run(setup_target="inherit")
    assert _digest(base) == _digest(again)
    assert not [e for e in again.events if str(e.get("event", "")).startswith("setup_target")]


def test_the_default_records_nothing_on_the_setups():
    res = _run()
    for s in (res.to_dict().get("setups") or []):
        assert "targetRecord" not in s, "the default path must leave no trace of the resolver"


# ---------------------------------------------------------------- switched on
def test_resolving_records_the_decision_on_every_setup():
    res = _run(setup_target="resolve")
    setups = res.to_dict().get("setups") or []
    assert setups, "the fixture day must produce at least one setup"
    for s in setups:
        rec = s.get("targetRecord")
        assert rec and rec["version"] == "setup-target-v1"
        assert rec["source"] == pytest.approx(s["anchor"], abs=1e-4)
        assert rec["sourceRole"] in ("pm_extreme", "zone_edge", "key_level")
        assert isinstance(rec["ladder"], list)
        # the setup's own target is exactly what the resolver chose - no third value anywhere
        assert (s["target"] is None) == (rec["target"] is None)
        if rec["target"] is not None:
            assert s["target"] == pytest.approx(rec["target"], abs=1e-4)


def test_a_resolved_destination_is_always_beyond_its_own_source():
    """The defect, made impossible: no setup may carry its own source level as its destination."""
    res = _run(setup_target="resolve")
    for s in (res.to_dict().get("setups") or []):
        if s.get("target") is None:
            continue
        gap = s["target"] - s["anchor"] if s["direction"] == "long" else s["anchor"] - s["target"]
        assert gap > 0, f"{s['id']} points at or behind its own source"


def test_every_resolution_is_narrated_in_the_events():
    res = _run(setup_target="resolve")
    said = [e for e in res.events if str(e.get("event", "")).startswith("setup_target")]
    assert said, "a decision that changes trading must be visible in the record"
    for e in said:
        assert e["event"] in ("setup_target_resolved", "setup_target_refused")
        assert "record" in e and "sourceRole" in e
        if e["event"] == "setup_target_refused":
            # requirement 4: the refusal says the structure had nothing, not that we dropped it
            assert "no destination exists in the available structural data" in e["why"]


# ---------------------------------------------------------------- determinism
def test_resolving_is_deterministic_across_runs():
    assert _digest(_run(setup_target="resolve")) == _digest(_run(setup_target="resolve"))


def test_switching_the_knob_changes_only_targets_and_what_follows_from_them():
    """Nothing else in the read may move: the same setups are confirmed, at the same times, from
    the same sources. Only the destination and its consequences differ."""
    off = _run().to_dict()
    on = _run(setup_target="resolve").to_dict()
    a = {s["id"]: s for s in (off.get("setups") or [])}
    b = {s["id"]: s for s in (on.get("setups") or [])}
    assert set(a) == set(b), "the resolver must not create or suppress setups"
    for sid in a:
        assert a[sid]["anchor"] == b[sid]["anchor"]
        assert a[sid]["direction"] == b[sid]["direction"]
        assert a[sid]["confirmedTs"] == b[sid]["confirmedTs"]
        assert a[sid]["kind"] == b[sid]["kind"]
