"""The C2 paired report's pure parts (spec §3–§5): matched-trade classes, the book simulation, the gates, the seal."""
from __future__ import annotations

import pytest

from zargar.tools.team2_c2_report import VALIDATION_END, VALIDATION_START, book_sim, classify, gates, seal_check


def t(setup, entry, exit_ts, pnl, kind="ema", size=1.0):
    return {"setup": setup, "entryTs": entry, "exitTs": exit_ts, "entryKind": kind, "pnlPct": pnl, "win": pnl > 0, "sizeMult": size}


def test_matched_trades_split_into_unchanged_changed_exit_displaced_new_and_lost():
    base = [{"symbol": "SPY", "date": "2026-09-01", "status": "ok", "trades": [t("scenario_1@09:30", 100, 200, 10.0), t("scenario_1@09:30", 300, 400, 5.0), t("pm_break_up@09:45", 500, 600, -8.0)]}]
    var = [{"symbol": "SPY", "date": "2026-09-01", "status": "ok", "trades": [t("scenario_1@09:30", 100, 250, 20.0), t("scenario_1@09:30", 300, 400, 5.0),
                                                                             t("pm_break_up@10:00", 520, 600, 3.0), t("key_break_up@10:15:101.00", 700, 800, 12.0)]}]
    c = classify(base, var)
    assert c["unchanged"] == 1
    assert [x["setup"] for x in c["changedExit"]] == ["scenario_1@09:30"] and c["changedExit"][0]["pnlPctBefore"] == 10.0
    assert [x["setup"] for x in c["displaced"]] == ["pm_break_up@10:00"]          # same family, different entry
    assert [x["setup"] for x in c["new"]] == ["key_break_up@10:15:101.00"]
    assert c["lost"] == []                                                        # the displaced one's original is not "lost"
    assert [x["setup"] for x in c["displacedFrom"]] == ["pm_break_up@09:45"]      # …but it IS accounted for (reviewer, 2026-09-15)
    assert c["sums"] == {"changedExit": 10.0, "displaced": 3.0, "displacedFrom": -8.0, "new": 12.0, "lost": 0.0, "netVsBase": 33.0}
    # the components reconcile to the model difference: (20+5+3+12) − (10+5−8) = 33
    assert c["sums"]["netVsBase"] == round(sum(x["pnlPct"] for x in var[0]["trades"]) - sum(x["pnlPct"] for x in base[0]["trades"]), 1)


def test_book_sim_is_chronological_one_position_and_two_losses_end_the_day():
    rows = [{"symbol": "SPY", "date": "2026-09-01", "trades": [t("a", 100, 300, -10.0), t("b", 400, 500, -10.0), t("c", 600, 700, 50.0)]},
            {"symbol": "QQQ", "date": "2026-09-01", "trades": [t("d", 200, 250, 30.0)]}]               # overlaps SPY's first trade
    b = book_sim(rows, unit=100.0)
    assert b["taken"] == 2 and b["skippedConcurrent"] == 1 and b["skippedLossCap"] == 1
    assert b["total"] == -20.0 and b["maxDrawdown"] == -20.0 and b["worstDay"] == -20.0


def test_gates_are_the_predeclared_ones():
    base = {"model": {"pnlPctSum": 100.0}, "book": {"total": 500.0, "maxDrawdown": -300.0, "worstDay": -200.0}}
    good = {"model": {"pnlPctSum": 150.0}, "book": {"total": 900.0, "maxDrawdown": -350.0, "worstDay": -240.0}}
    assert gates(base, good, changed_entries=6, changed_cells_positive=3, changed_cells=6)["qualifies"]
    thin = gates(base, good, changed_entries=5, changed_cells_positive=3, changed_cells=5)
    assert not thin["qualifies"] and thin["insufficientExposure"]
    deep = {"model": {"pnlPctSum": 150.0}, "book": {"total": 900.0, "maxDrawdown": -400.0, "worstDay": -240.0}}
    assert not gates(base, deep, 6, 3, 6)["g2_drawdown"]
    narrow = gates(base, good, changed_entries=6, changed_cells_positive=2, changed_cells=6)
    assert not narrow["g4_breadth"]


def test_the_validation_window_is_sealed():
    seal_check("2026-08-20", "2026-09-11", False, None)                          # development: fine
    with pytest.raises(SystemExit):
        seal_check("2026-08-20", VALIDATION_START, False, None)                   # touches the window
    with pytest.raises(SystemExit):
        seal_check(VALIDATION_START, VALIDATION_END, True, None)                  # the read needs the explicit --after date
