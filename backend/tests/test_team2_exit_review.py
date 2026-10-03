"""team2_exit_review: the pure judgement behind the after-close exit report."""
from __future__ import annotations

from zargar.tools import team2_exit_review as xr

OPEN = 1_000_000_000_000
M = 60_000


def bars(closes):
    """1-minute bars from a list of closes, starting at the open."""
    return [(OPEN + i * M, c, c, c, c) for i, c in enumerate(closes)]


def test_ema_is_rolled_from_the_journalled_seed_not_a_fresh_warm_up():
    path = xr.ema_path(bars([100, 100, 101, 101]), OPEN, 99.0, OPEN)
    assert path[0]["ema13"] == 99.0, "the seed bar keeps the fire's own journalled EMA"
    assert path[1]["ema13"] > 99.0


def test_a_stop_while_price_holds_above_ema_is_cut_ahead_of_structure():
    path = [{"closeTs": OPEN + 2 * M, "close": 101, "ema13": 100},
            {"closeTs": OPEN + 30 * M, "close": 99, "ema13": 100}]
    j = xr.judge(path, OPEN + 3 * M, "long")
    assert j["structureIntactAtExit"] is True and j["structuralBreakTs"] == OPEN + 30 * M


def test_a_stop_just_before_the_break_is_not_counted_as_cut_ahead():
    """2026-09-22 10:39:55: structure was intact at that instant and broke on the 10:40 close. The
    premium stop only got there first; counting it as an intact-structure cut would inflate the case."""
    path = [{"closeTs": OPEN + 2 * M, "close": 101, "ema13": 100},
            {"closeTs": OPEN + 4 * M, "close": 99, "ema13": 100}]
    exit_ms = OPEN + 4 * M - 5_000
    j = xr.judge(path, exit_ms, "long")
    gap = j["structuralBreakTs"] - exit_ms
    assert j["structureIntactAtExit"] is True and gap <= xr.TWO_MIN


def test_short_setups_are_mirrored():
    path = [{"closeTs": OPEN + 2 * M, "close": 99, "ema13": 100},
            {"closeTs": OPEN + 20 * M, "close": 101, "ema13": 100}]
    j = xr.judge(path, OPEN + 3 * M, "short")
    assert j["structureIntactAtExit"] is True and j["structuralBreakTs"] == OPEN + 20 * M


def test_the_contract_path_after_exit_uses_only_later_prints():
    opt = [(OPEN + i * M, 0.5, 0.5 + i / 100, 0.4, 0.5) for i in range(10)]
    a = xr.after_exit(opt, OPEN + 3 * M, OPEN + 8 * M)
    assert a["bars"] == 5 and a["maxHigh"] == 0.58, "only prints strictly after the exit and within the window"


def test_the_summary_counts_decisions_and_only_genuine_cuts():
    rows = [{"authority": "live premium stop", "cutAheadOfStructure": True},
            {"authority": "live premium stop", "cutAheadOfStructure": False},
            {"authority": "structural stop"}]
    s = xr.summarise(rows)
    assert s["livePremiumStops"] == 2 and s["livePremiumStopsCutAheadOfStructure"] == 1


def test_the_tool_writes_nothing():
    import pathlib
    src = pathlib.Path(xr.__file__).read_text(encoding="utf-8")
    for forbidden in ("journal.append", "OrderIntent", "place(", "settings.set", "INSERT", "UPDATE ", "commit("):
        assert forbidden not in src
