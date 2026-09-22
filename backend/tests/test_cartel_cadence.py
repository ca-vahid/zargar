"""F4 (2026-09-21 brief): versioned Practice entry cadence with a non-ordering matched 15m control.

Recorded NTNX facts reproduced here: 5m 10:25-10:30 confirmation volume 42,293 at 2.511x its 5m
baseline; 15m 10:15-10:30 volume 72,691 at 0.929x its 15m baseline (78,231.5); close 70.575 above the
70.48 trigger, close location 1.0, session low 69.555. The minute tape is SYNTHETIC: it reproduces
those bucket sums and closes, not the actual prints.
"""
import datetime as dt

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.models import Order
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.cadence import (
    VolumeExperiment,
    control_config,
    control_plan,
    control_signal_id,
    control_summary,
    read_control,
    volume_grid_variants,
)
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.plans import CartelPlan, EntryPolicy
from zargar.techniques.options_cartel.prepare import build_volume_baseline

from . import test_options_cartel_state as state_tests

DAY = "2026-09-21"
OPEN, CLOSE = session_bounds(DAY)
MIN = 60_000
ET = dt.timezone(dt.timedelta(hours=-4))
NTNX_5M_BASELINE = 42293/2.5113116798289887
NTNX_15M_BASELINE = 78231.5


def at(hh, mm):
    return int(dt.datetime(2026, 9, 21, hh, mm, tzinfo=ET).timestamp()*1000)


def ntnx_plan(tf=5, baseline=None, **changes):
    slots = 390//tf
    values = {"id": "ntnx", "symbol": "NTNX", "direction": "long", "setup": "base", "created_at": OPEN-MIN,
              "first_session": dt.date(2026, 9, 21), "last_session": dt.date(2026, 9, 21), "trigger": 70.48,
              "invalidation": 69.555, "targets": (71., 71.61, 72.42), "source_refs": ("2026-09-21-eod",),
              "rationale": "Recorded 2026-09-21 NTNX geometry", "entry": EntryPolicy(timeframe_minutes=tf, baseline_policy="covered_periods"),
              "baseline_as_of": OPEN-MIN, "volume_baseline": baseline if baseline is not None else {i: (NTNX_5M_BASELINE if tf == 5 else NTNX_15M_BASELINE) for i in range(slots)},
              "cadence_version": f"breakout_{tf}m_v1"}
    values.update(changes)
    return CartelPlan(**values)


def ntnx_tape(until=at(10, 30)):
    """Flat 70.40 tape; 10:15-10:25 carries 30,398 shares, 10:25-10:30 carries 42,293 and closes 70.575."""
    bars = []
    for ts in range(OPEN, until, MIN):
        minute = (ts-OPEN)//MIN
        if 45 <= minute < 55:        # 10:15-10:25: two 5m buckets totalling 30,398
            bars.append(Bar("NTNX", "1m", ts, 70.40, 70.45, 70.30, 70.40, 3039.8, source="exchange"))
        elif 55 <= minute < 60:      # 10:25-10:30: 42,293 shares, last minute closes at its high 70.575
            close = 70.575 if minute == 59 else 70.45
            bars.append(Bar("NTNX", "1m", ts, 70.40, close, 70.30, close, 8458.6, source="exchange"))
        else:
            low = 69.555 if minute == 5 else 70.30
            bars.append(Bar("NTNX", "1m", ts, 70.40, 70.45, low, 70.40, 1000, source="exchange"))
    return bars


# ---- policy versioning -------------------------------------------------------------------------

def test_saved_policy_without_label_derives_its_cadence_and_explicit_labels_must_agree():
    saved = PreparationPolicy.model_validate({"entry": {"timeframe_minutes": 15}})
    assert saved.entry_cadence == "breakout_15m_v1" and saved.volume_experiment.version == "off"
    five = PreparationPolicy(entry=EntryPolicy(timeframe_minutes=5), entry_cadence="breakout_5m_v1")
    assert five.entry_cadence == "breakout_5m_v1"
    with pytest.raises(ValidationError, match="requires entry.timeframe_minutes=5"):
        PreparationPolicy(entry=EntryPolicy(timeframe_minutes=15), entry_cadence="breakout_5m_v1")
    with pytest.raises(ValidationError, match="Practice-only"):
        PreparationPolicy(workspace="live", allow_live=True, overnight_ack=True, entry=EntryPolicy(timeframe_minutes=5), entry_cadence="breakout_5m_v1")
    with pytest.raises(ValidationError, match="Practice-only"):
        PreparationPolicy(workspace="live", allow_live=True, overnight_ack=True, volume_experiment=VolumeExperiment(version="grid_v1"))
    thirty = PreparationPolicy(entry=EntryPolicy(timeframe_minutes=30))
    assert thirty.entry_cadence == "legacy_timeframe"


def test_cadence_change_is_a_policy_change_so_a_running_preparation_cannot_arm_under_it():
    before = PreparationPolicy(enabled=True)
    after = PreparationPolicy(enabled=True, entry=EntryPolicy(timeframe_minutes=5), entry_cadence="breakout_5m_v1")
    assert before != after   # preparation.py refuses to arm when read_policy(...) != policy


def test_volume_experiment_is_replay_only_and_inactive_by_default():
    off = PreparationPolicy()
    assert volume_grid_variants(off.volume_experiment, off.entry_cadence) == []
    grid = VolumeExperiment(version="grid_v1", multiples=(0.9, 1.2, 1.5))
    variants = volume_grid_variants(grid, "breakout_5m_v1")
    assert [v["volume_multiple"] for v in variants] == [0.9, 1.2, 1.5] and all(v["timeframe_minutes"] == 5 for v in variants)
    assert "volume_experiment" not in EntryPolicy.model_fields   # the live read never sees the grid
    with pytest.raises(ValidationError):
        VolumeExperiment(version="grid_v1", multiples=(1.0, 1.0))


# ---- NTNX 5m versus 15m with independent baselines --------------------------------------------

def test_ntnx_5m_confirms_at_2_511x_while_15m_refuses_at_0_929x_on_the_same_tape():
    tape = ntnx_tape()
    five = read_entry(ntnx_plan(5), tape, at(10, 30))
    assert five["signal"] and five["signal"]["at"] == at(10, 30)
    assert five["signal"]["volumeRatio"] == pytest.approx(2.5113, abs=1e-3) and five["signal"]["volume"] == pytest.approx(42293)
    assert five["signal"]["closeLocation"] == 1.0 and five["signal"]["referencePrice"] == 70.575 and five["signal"]["stop"] == 69.555
    fifteen = read_entry(ntnx_plan(15), tape, at(10, 30))
    assert fifteen["signal"] is None
    refusal = [d for d in fifteen["trace"] if d["decision"] == "watch_only"][-1]
    assert refusal["at"] == at(10, 30) and refusal["measurements"]["volumeRatio"] == pytest.approx(0.9292, abs=1e-3)
    assert refusal["measurements"]["volume"] == pytest.approx(72691) and refusal["measurements"]["closeLocation"] == 1.0


def test_independent_baselines_are_built_per_timeframe_from_the_same_minutes():
    sessions = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
    minutes = []
    for day in sessions:
        opens, closes = session_bounds(day)
        for ts in range(opens, closes, MIN):
            minute = (ts-opens)//MIN
            volume = 8458.6 if 55 <= minute < 60 else 3039.8 if 45 <= minute < 55 else 1000
            minutes.append(Bar("NTNX", "1m", ts, 70, 70.5, 69.5, 70, volume, source="exchange"))
    five = build_volume_baseline(minutes, "NTNX", 5, OPEN-MIN, sessions=20, min_samples=5)
    fifteen = build_volume_baseline(minutes, "NTNX", 15, OPEN-MIN, sessions=20, min_samples=5)
    assert five["timeframeMinutes"] == 5 and len(five["baselines"]) == 78 and five["baselines"][11] == pytest.approx(42293)
    assert fifteen["timeframeMinutes"] == 15 and len(fifteen["baselines"]) == 26 and fifteen["baselines"][3] == pytest.approx(72691)
    assert five["baselines"][11] != fifteen["baselines"][3]/3   # no 15m number is reused as a 5m baseline


def test_ulta_5m_still_fails_unchanged_volume_and_now_wick_never_becomes_a_candle():
    ulta = ntnx_plan(5, symbol="ULTA", trigger=547.58, invalidation=544.43, targets=(548., 560.), id="ulta",
                     baseline={i: 10000. for i in range(78)})
    tape = []
    for ts in range(OPEN, at(9, 55), MIN):
        minute = (ts-OPEN)//MIN
        close = 548.76 if minute == 24 else 547.0
        tape.append(Bar("ULTA", "1m", ts, 547, max(close, 547.1), 546.5, close, 1924 if 20 <= minute < 25 else 1000, source="exchange"))
    result = read_entry(ulta, tape, at(9, 55))
    assert result["signal"] is None
    refusal = [d for d in result["trace"] if d["decision"] == "watch_only"][-1]
    assert refusal["measurements"]["volumeRatio"] == pytest.approx(0.962) and "volume" in refusal["reason"].lower()
    now = ntnx_plan(5, symbol="NOW", trigger=139.94, invalidation=135., targets=(145.,), id="now", baseline={i: 1000. for i in range(78)})
    tape = [Bar("NOW", "1m", OPEN+i*MIN, 138, 140.16 if i == 1 else 138.5, 137, 139.335 if i == 1 else 138.2, 5000, source="exchange") for i in range(10)]
    result = read_entry(now, tape, at(9, 40))
    assert result["signal"] is None and not any(d["decision"] in ("triggered", "watch_only") for d in result["trace"])


# ---- matched control ---------------------------------------------------------------------------

def control_block():
    baseline = {"timeframeMinutes": 15, "baselines": {i: NTNX_15M_BASELINE for i in range(26)}, "sampleCounts": {i: 20 for i in range(26)}}
    return control_config("breakout_5m_v1", baseline, OPEN-MIN)


def test_control_config_requires_its_own_timeframe_and_builds_a_15m_plan():
    block = control_block()
    assert block["control"] == "breakout_15m_v1" and block["controlTimeframeMinutes"] == 15 and block["placesOrders"] is False
    with pytest.raises(ValueError, match="timeframe"):
        control_config("breakout_5m_v1", {"timeframeMinutes": 5, "baselines": {}}, OPEN-MIN)
    assert control_config("breakout_15m_v1", {"timeframeMinutes": 15, "baselines": {}}, OPEN-MIN) is None
    shadow = control_plan(ntnx_plan(5), block)
    assert shadow.entry.timeframe_minutes == 15 and shadow.cadence_version == "breakout_15m_v1"
    assert shadow.volume_baseline[3] == NTNX_15M_BASELINE and shadow.trigger == 70.48 and shadow.id == "ntnx"


def test_control_read_records_the_15m_refusal_beside_the_executing_5m_signal_without_an_executable_id():
    plan, tape = ntnx_plan(5), ntnx_tape()
    executing = read_entry(plan, tape, at(10, 30))
    control = read_control(plan, control_block(), tape, at(10, 30), entry_after=OPEN-MIN)
    assert executing["signal"]["id"] == "ntnx:entry:"+str(at(10, 30))
    assert control["signals"] == [] and control["placesOrders"] is False and control["researchOnly"] is True
    refusal = [d for d in control["decisionHistory"] if d["decision"] == "watch_only"][-1]
    assert refusal["at"] == at(10, 30) and refusal["measurements"]["volumeRatio"] == pytest.approx(0.9292, abs=1e-3)
    summary = control_summary(control_block(), control, CLOSE)
    assert summary["controlSignals"] == 0 and summary["controlDecisionCounts"]["watch_only"] >= 1 and summary["executing"] == "breakout_5m_v1"


def test_control_signal_ids_are_never_consumable_and_the_watermark_survives_restart():
    plan = ntnx_plan(5)
    block = control_block()
    tape = []
    for ts in range(OPEN, at(10, 30), MIN):   # the 15m 10:15-10:30 bucket confirms when its volume is tripled
        minute = (ts-OPEN)//MIN
        volume = 25000 if 45 <= minute < 60 else 1000
        close = 70.575 if minute == 59 else 70.40
        tape.append(Bar("NTNX", "1m", ts, 70.40, close, 69.555 if minute == 5 else 70.30, close, volume, source="exchange"))
    control = read_control(plan, block, tape, at(10, 30), entry_after=OPEN-MIN)
    assert len(control["signals"]) == 1
    signal = control["signals"][0]
    assert signal["id"] == control_signal_id("ntnx", "breakout_15m_v1", at(10, 30)) and ":entry:" not in signal["id"]
    assert signal["placesOrders"] is False and signal["researchOnly"] is True
    # A restart re-reads the same tape: the watermark stops the candle from being re-emitted.
    again = read_control(plan, block, tape, at(10, 31), entry_after=OPEN-MIN, previous=control)
    assert len(again["signals"]) == 1 and again["observeAfter"] == at(10, 30)
    # Repaired late evidence cannot backdate a control signal either.
    late = read_control(plan, block, tape, at(10, 45), entry_after=at(10, 40))
    assert late["signals"] == []


async def test_control_signal_cannot_be_consumed_by_the_arm_repository(repo):
    from .test_options_cartel_entry import OPEN as HOOD_OPEN   # the shared r1 plan lives on 2026-05-05
    await repo.arm("r1", "pf", "auto", {"execution": {"portfolio_id": "pf", "budget": 500}}, now_ms=HOOD_OPEN)
    bad = {**state_tests.signal(), "id": control_signal_id("r1", "breakout_15m_v1", state_tests.signal()["at"])}
    with pytest.raises(ValueError):
        await repo.consume_signal("r1", bad, now_ms=bad["at"]+1000)
    row = await repo.load("r1")
    assert row["state"]["phase"] == "waiting" and row["state"].get("signal") is None


async def test_one_executing_cadence_places_at_most_one_order_while_the_control_also_confirms(repo, monkeypatch):
    from zargar.techniques.options_cartel.execution import ExecutionInput
    from .test_options_cartel_runtime import publish_tape, runtime
    from .test_options_cartel_entry import plan as hood_plan
    runner, spec = await runtime(repo, monkeypatch)
    base = hood_plan()
    block = control_config("breakout_5m_v1", {"timeframeMinutes": 15, "baselines": {i: 1. for i in range(26)}}, base.baseline_as_of)
    await runner.arm("r1", {"mode": "auto", "portfolioId": "pf", "execution": ExecutionInput(portfolio_id="pf", mode="auto", instrument="shares", budget=500, max_units=2).model_dump(), "cadence": block})
    await publish_tape(repo, runner)
    row = await repo.load("r1")
    assert row["state"]["signal"]["id"].startswith("r1:entry:")
    assert row["state"]["control"]["cadence"] == "breakout_15m_v1" and row["state"]["control"]["placesOrders"] is False
    async with repo.engine.sf() as session:
        buys = (await session.scalars(select(Order).where(Order.side == "BUY", Order.portfolio_id == "pf"))).all()
    assert len(buys) <= 1
    await runner.stop()


repo = state_tests.repo


# ---- session geometry --------------------------------------------------------------------------

def test_early_close_first_and_last_buckets():
    day = "2026-11-27"   # 13:00 ET close
    opens, closes = session_bounds(day)
    assert closes-opens == 210*MIN
    plan = ntnx_plan(5, first_session=dt.date(2026, 11, 27), last_session=dt.date(2026, 11, 27), created_at=opens-MIN, baseline_as_of=opens-MIN,
                     baseline={i: 1000. for i in range(42)})
    tape = [Bar("NTNX", "1m", opens+i*MIN, 70.40, 70.575 if i in (4, 209) else 70.45, 70.30, 70.575 if i in (4, 209) else 70.40, 5000, source="exchange") for i in range(210)]
    first = read_entry(plan, tape, opens+5*MIN)
    assert first["signal"] and first["signal"]["at"] == opens+5*MIN   # the first 5m candle can confirm
    last = read_entry(plan, tape, closes, entry_after=opens+6*MIN)
    assert last["signal"] is None and any(d["decision"] == "entry_window_closed" and d["at"] == closes for d in last["trace"])


def test_existing_arms_keep_their_prepared_cadence_when_the_policy_changes():
    armed = ntnx_plan(5)
    snapshot = CartelPlan.model_validate(armed.snapshot()["plan"])
    assert snapshot.cadence_version == "breakout_5m_v1" and snapshot.entry.timeframe_minutes == 5
    legacy = CartelPlan.model_validate({k: v for k, v in armed.snapshot()["plan"].items() if k != "cadence_version"})
    assert legacy.cadence_version is None and legacy.entry.timeframe_minutes == 5
