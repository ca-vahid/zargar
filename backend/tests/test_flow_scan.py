"""Flow scan math — fixture chains through the pure functions.
CBOE-normalized row shapes (see zargar/options/chain.py)."""
from zargar.techniques.flow.scan import (
    FlowThresholds,
    aggregate_symbol,
    build_read,
    confirm_oi,
    context_line,
    flag_contracts,
    repeat_counts,
)

T = FlowThresholds()          # defaults: vol/oi 1.25, premium $100k, dte<=45, 0-12% OTM
DAY = "2026-08-27"
SPOT = 100.0


def row(*, sym="NVDA260918C00105000", opt="call", strike=105.0, expiry="2026-09-18",
        vol=5000, oi=1000, bid=2.0, ask=2.2, iv=0.45):
    return {"symbol": sym, "underlying": "NVDA", "expiry": expiry, "option_type": opt,
            "strike": strike, "bid": bid, "ask": ask, "last": (bid + ask) / 2,
            "volume": vol, "open_interest": oi,
            "greeks": {"delta": 0.3, "gamma": 0.01, "theta": -0.05, "vega": 0.1, "mid_iv": iv}}


# --- flag_contracts --------------------------------------------------------------

def test_flags_opening_style_volume():
    flags = flag_contracts([row()], spot=SPOT, day=DAY, t=T)
    assert len(flags) == 1
    f = flags[0]
    assert f["volOi"] == 5.0 and f["strong"]
    assert f["premium"] == 5000 * 2.1 * 100
    assert f["otmPct"] == 5.0
    assert f["dte"] == 22


def test_low_vol_oi_not_flagged():
    flags = flag_contracts([row(vol=1000, oi=1000)], spot=SPOT, day=DAY, t=T)  # 1.0 < 1.25
    assert flags == []


def test_small_premium_not_flagged():
    flags = flag_contracts([row(vol=600, oi=100, bid=0.5, ask=0.6)], spot=SPOT, day=DAY, t=T)
    assert flags == []          # 600 * 0.55 * 100 = $33k < $100k


def test_far_otm_and_long_dte_excluded():
    deep = row(strike=125.0)                       # 25% OTM
    leaps = row(expiry="2027-06-18")               # dte > 45
    itm = row(strike=90.0)                         # ITM call (negative OTM ok? -10 < otm_min 0)
    assert flag_contracts([deep, leaps, itm], spot=SPOT, day=DAY, t=T) == []


def test_flags_sorted_by_premium():
    small = row(sym="A", vol=1000, oi=200, bid=1.0, ask=1.2)     # $110k
    big = row(sym="B", vol=5000, oi=1000, bid=2.0, ask=2.2)      # $1.05M
    flags = flag_contracts([small, big], spot=SPOT, day=DAY, t=T)
    assert [f["contract"] for f in flags] == ["B", "A"]


# --- OI confirmation -------------------------------------------------------------

def test_oi_confirms_opening_volume():
    yesterday = flag_contracts([row(vol=5000, oi=1000)], spot=SPOT, day=DAY, t=T)
    confirmed = confirm_oi(yesterday, {"NVDA260918C00105000": 4500})  # +3500 >= 0.5*5000
    assert len(confirmed) == 1 and confirmed[0]["oiDelta"] == 3500


def test_oi_flat_means_closing_volume():
    yesterday = flag_contracts([row(vol=5000, oi=1000)], spot=SPOT, day=DAY, t=T)
    assert confirm_oi(yesterday, {"NVDA260918C00105000": 1200}) == []   # churn, not opening


# --- repeat hits -----------------------------------------------------------------

def test_repeat_counts_window():
    hist = {"C1": ["08-21", "08-24", "08-25", "08-26"], "C2": ["08-20"]}
    window = ["08-22", "08-24", "08-25", "08-26"]
    counts = repeat_counts(hist, window_days=window)
    assert counts["C1"] == 3
    assert "C2" not in counts


# --- aggregates + read -----------------------------------------------------------

def test_aggregate_and_os_ratio():
    rows = [row(opt="call", vol=3000), row(opt="put", sym="P1", strike=95.0, vol=1000)]
    agg = aggregate_symbol(rows, stock_volume=1_000_000)
    assert agg["callVolume"] == 3000 and agg["putVolume"] == 1000
    assert agg["osRatio"] == 0.4          # 4000 * 100 / 1_000_000
    assert agg["pcVolumeRatio"] == round(1000 / 3000, 3)


def test_read_scores_and_leans_bull():
    flags = flag_contracts([row()], spot=SPOT, day=DAY, t=T)
    read = build_read("NVDA", DAY, flags=flags, confirmed=[], repeats={},
                      agg=aggregate_symbol([row()], stock_volume=None), t=T)
    assert read["score"] > 0 and read["lean"] == "bull"
    assert read["reasons"]


def test_read_repeat_accumulation_scores_highest():
    flags = flag_contracts([row()], spot=SPOT, day=DAY, t=T)
    plain = build_read("NVDA", DAY, flags=flags, confirmed=[], repeats={},
                       agg={}, t=T)
    hot = build_read("NVDA", DAY, flags=flags, confirmed=flags,
                     repeats={"NVDA260918C00105000": 3}, agg={}, t=T)
    assert hot["score"] > plain["score"]
    assert hot["repeatHits"]


def test_bear_os_ratio_demotes_bull_lean():
    flags = flag_contracts([row()], spot=SPOT, day=DAY, t=T)
    read = build_read("NVDA", DAY, flags=flags, confirmed=[], repeats={},
                      agg={"osRatio": 0.9}, t=T)
    assert read["lean"] == "mixed"


def test_quiet_symbol_reads_none():
    read = build_read("KO", DAY, flags=[], confirmed=[], repeats={}, agg={}, t=T)
    assert read["score"] == 0 and read["lean"] == "none"
    assert context_line(read) is None


def test_context_line_mentions_top_contract():
    flags = flag_contracts([row()], spot=SPOT, day=DAY, t=T)
    read = build_read("NVDA", DAY, flags=flags, confirmed=[], repeats={}, agg={}, t=T)
    line = context_line(read)
    assert line and "call accumulation" in line and "NVDA260918C00105000" in line


# --- spot_from_chain / last_weekday (the 2026-08-28 degraded-scan fixes) ---------

def test_spot_from_chain_parity():
    from zargar.techniques.flow.scan import spot_from_chain
    rows = []
    for k in (95.0, 100.0, 105.0):
        # call mid ≈ max(spot-k,0)+2 · put mid ≈ max(k-spot,0)+2 around spot 101
        c = max(101 - k, 0) + 2.0
        p = max(k - 101, 0) + 2.0
        rows.append(row(sym=f"C{k}", opt="call", strike=k, bid=c - 0.1, ask=c + 0.1))
        rows.append(row(sym=f"P{k}", opt="put", strike=k, bid=p - 0.1, ask=p + 0.1))
    assert abs(spot_from_chain(rows) - 101.0) < 0.5


def test_spot_from_chain_needs_both_sides():
    from zargar.techniques.flow.scan import spot_from_chain
    calls_only = [row(strike=k) for k in (95.0, 100.0, 105.0)]
    assert spot_from_chain(calls_only) == 0.0


def test_spot_from_chain_prefers_nearest_expiry():
    from zargar.techniques.flow.scan import spot_from_chain
    near_c = row(sym="NC", strike=100.0, bid=2.9, ask=3.1, expiry="2026-09-04")
    near_p = row(sym="NP", opt="put", strike=100.0, bid=1.9, ask=2.1, expiry="2026-09-04")
    far_c = row(sym="FC", strike=100.0, bid=30.0, ask=32.0, expiry="2027-01-15")
    far_p = row(sym="FP", opt="put", strike=100.0, bid=2.0, ask=2.2, expiry="2027-01-15")
    # nearest expiry pair: spot ≈ 100 + 3.0 − 2.0 = 101 (far pair would say ~129)
    assert abs(spot_from_chain([far_c, far_p, near_c, near_p]) - 101.0) < 0.5


def test_last_weekday_rolls_weekends_only():
    import datetime as dt
    from zargar.techniques.flow.scan import last_weekday
    sat, sun = dt.date(2026, 8, 29), dt.date(2026, 8, 30)
    fri, wed = dt.date(2026, 8, 28), dt.date(2026, 8, 26)
    assert last_weekday(sat) == fri and last_weekday(sun) == fri
    assert last_weekday(wed) == wed
