"""Sweep detection on option prints (FLOW-CONFIRMATION-PLAN phase 0). Pure tests:
the tick-test classifier and the rolling-window rule, calibrated on the author's
TSLA $360C 2026-08-31 (18k-contract window on 6.7k open interest) and GPRO."""
import datetime as dt

from zargar.research.optiontrades import (SweepRules, classify_nbbo, classify_tick, detect_sweeps,
                                          MinuteFlow)

MIN = 60_000
T0 = int(dt.datetime(2026, 8, 31, 13, 30, tzinfo=dt.timezone.utc).timestamp() * 1000)   # 09:30 ET


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def test_tick_test_counts_upticks_as_buys_and_buckets_minutes():
    prints = [{"t": _iso(T0 + 5_000), "p": 2.30, "s": 10}, {"t": _iso(T0 + 6_000), "p": 2.33, "s": 100},
              {"t": _iso(T0 + 7_000), "p": 2.33, "s": 20}, {"t": _iso(T0 + 8_000), "p": 2.31, "s": 50},
              {"t": _iso(T0 + 61_000), "p": 2.35, "s": 200}]
    m = classify_tick(prints)
    assert [x.ts for x in m] == [T0, T0 + MIN]
    a, b = m
    assert a.contracts == 180 and a.buys == 100 + 10 and a.prints == 4 and a.big_prints == 1
    assert b.contracts == 200 and b.buys == 200 and round(b.notional) == 200 * 2.35 * 100


def test_nbbo_classifier_marks_ask_side_prints():
    prints = [(T0, 2.33, 100, 2.30, 2.33), (T0 + 1000, 2.30, 50, 2.30, 2.33), (T0 + 2000, 2.315, 40, 2.30, 2.33)]
    m = classify_nbbo(prints)
    assert m[0].method == "nbbo" and m[0].buys == 100 + 20 and m[0].contracts == 190


def _burst(oi: int, quiet: int, burst: int, minutes_of_burst: int = 5) -> list[MinuteFlow]:
    out = []
    for i in range(20):
        c = burst if 10 <= i < 10 + minutes_of_burst else quiet
        out.append(MinuteFlow(ts=T0 + i * MIN, contracts=c, buys=int(c * 0.5), prints=c // 10))
    return out


def test_sweep_fires_on_the_tsla_shape_and_not_on_a_quiet_tape():
    # TSLA-like: OI 6,742, quiet 1,500/min then a 3,600/min burst -> cumulative crosses 3x OI
    # during the burst and the 5-minute window carries ~9k buys
    sweeps = detect_sweeps("TSLA260831C00360000", _burst(6742, 1500, 3600), 6742)
    assert len(sweeps) == 1
    sw = sweeps[0]
    assert T0 + 10 * MIN <= sw.ts <= T0 + 14 * MIN and sw.window_buys >= 0.25 * 6742 and sw.cumulative >= 3 * 6742
    # quiet tape on the same open interest: nothing
    assert detect_sweeps("X", _burst(6742, 200, 200), 6742) == []
    # a thin name below the absolute floors never qualifies however big the ratio
    assert detect_sweeps("Y", _burst(50, 20, 60), 50) == []


def test_one_continuous_burst_is_one_sweep_and_two_bursts_are_two():
    # one continuous 5x burst with the default cooldown = one sweep
    long_burst = _burst(2733, 300, 1500, minutes_of_burst=9)
    assert len(detect_sweeps("GPRO260918C00001000", long_burst, 2733)) == 1
    # two 10x bursts an hour apart on a quiet tape = two sweeps, one each
    two = [MinuteFlow(ts=T0 + i * MIN, contracts=300, buys=150, prints=30) for i in range(120)]
    for i in list(range(20, 25)) + list(range(80, 85)):
        two[i].contracts, two[i].buys = 3000, 1500
    sweeps = detect_sweeps("GPRO260918C00001000", two, 2733)
    mins = [(sw.ts - T0) // MIN for sw in sweeps]
    assert len(sweeps) == 2 and 20 <= mins[0] <= 24 and 80 <= mins[1] <= 84, mins



def test_a_steadily_heavy_tape_is_busy_not_swept():
    # a liquid 0DTE contract printing 3,000/min all day on 8k OI: cumulative passes every
    # ratio by 09:35, but nothing is a BURST against its own pace -> at most the opening
    # minutes qualify, never a sweep every cooldown
    steady = [MinuteFlow(ts=T0 + i * MIN, contracts=3000, buys=1500, prints=300) for i in range(120)]
    sweeps = detect_sweeps("NVDA260904P00230000", steady, 8000)
    assert len(sweeps) <= 1 and all(sw.ts < T0 + 15 * MIN for sw in sweeps)
    # a genuine 4x burst at 11:00 on that tape does qualify
    for i in range(90, 95):
        steady[i].contracts, steady[i].buys = 12000, 6000
    sweeps = detect_sweeps("NVDA260904P00230000", steady, 8000)
    assert any(T0 + 90 * MIN <= sw.ts <= T0 + 94 * MIN for sw in sweeps)
