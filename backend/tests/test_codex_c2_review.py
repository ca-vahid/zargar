"""Independent C2 boundary cases at ca26bf3; pure fixture data, no market measurement."""
import statistics
from zargar.techniques.team2.levels import _cluster
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.session import simulate_session
from zargar.marketstructure import aggregate
from .test_team2_key_levels import _gap_day_through
from .test_team2_integrity import PREV, TOP
from .test_team2_session import DAY, make_rules, path_1m


def test_running_median_clustering_does_not_chain_across_multiple_atrs():
    width = 0.5  # atr_build = 1
    prices = [100.0]
    for _ in range(31):
        prices.append(statistics.median(prices) + width)
    cands = [{"price": p, "kind": "high", "origin_date": "2026-09-10", "available_at": 0,
              "last_reaction_at": 0, "episode_ids": []} for p in prices]
    clusters = _cluster(cands, width)
    spans = [max(c["members"]) - min(c["members"]) for c in clusters]
    # Even this more permissive 1 ATR diameter is exceeded; intended maximum must be explicit.
    assert max(spans) <= 2 * width, {"clusters": len(clusters), "span_atr": max(spans)}


def test_same_candle_breaks_keep_distinct_key_level_setup_ids():
    rules = make_rules(key_levels="D1")
    today = path_1m(DAY, (4, 0), (20, 0), _gap_day_through(TOP + 1, confirm=True))
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules, prev_bars_1m=PREV), today)
    levels = [{"levelId": f"level-{i}", "definition": "D1", "originKind": "high", "originDate": "2026-09-02",
               "availableAt": 0, "price": price, "role": "resistance", "score": 2.55, "reactions": 3,
               "lastReactionAt": 0, "members": [price], "episodes": [], "maskedBy": "none", "flips": 0,
               "flipPending": False, "breakAt": None, "flipConfirmedAt": None, "retired": False}
              for i, price in enumerate((TOP + 1, TOP + 1.5))]
    plan["keyLevels"] = {"definition": "D1", "atrBuild": 0.5, "candidates": levels, "above": levels, "below": []}
    result = simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV)
    setups = [e for e in result.events if e["event"] == "key_level_setup"]
    assert len(setups) == 2, setups
    assert len({e["setup"] for e in setups}) == 2, setups
    assert len([s for s in result.setups if s["kind"] == "key_break_up"]) == 2
