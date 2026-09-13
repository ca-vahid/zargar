"""Compare real pre/post C2 precedence with the research knob disabled."""
import subprocess
import sys
import types
from zargar.marketstructure import aggregate
from zargar.marketstructure.aggregate import bar_session
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.session import simulate_session
from .test_team2_integrity import PREV, TOP
from .test_team2_session import DAY, make_rules, path_1m


def test_key_levels_off_preserves_legacy_zone_pm_tie_precedence():
    old_source = subprocess.check_output([
        "git", "show", "ca26bf3:backend/zargar/techniques/team2/session.py"], text=True, encoding="utf-8")
    name = "zargar.techniques.team2._codex_legacy_c2_session"
    old = types.ModuleType(name)
    old.__package__ = "zargar.techniques.team2"
    sys.modules[name] = old
    exec(compile(old_source, name, "exec"), old.__dict__)
    rules = make_rules(key_levels="off")
    zone_top = build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules, prev_bars_1m=PREV)["zones"]["pdh"]["top"]
    def price(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return zone_top - 0.5
        x = m - (9 * 60 + 30)
        if x < 15:
            return zone_top + 0.2 + x * 0.06
        if x < 30:
            return zone_top + 0.8
        return zone_top + 0.8 + 0.01 * (x % 7)
    today = path_1m(DAY, (4, 0), (20, 0), price)
    # The path helper carries each previous close into the next open; specify the actual opening gap.
    next(b for b in today if bar_session(b.ts) == "rth").open = zone_top + 0.2
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules, prev_bars_1m=PREV), today)
    assert plan["dayType"] == "gap_up"
    assert plan["pmh"] < plan["zones"]["pdh"]["top"]
    before = old.simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV).to_dict()
    after = simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV).to_dict()
    before_fires = [(e["ts"], e.get("setup"), e.get("spot")) for e in before["events"] if e["event"] == "fire"]
    after_fires = [(e["ts"], e.get("setup"), e.get("spot")) for e in after["events"] if e["event"] == "fire"]
    assert before_fires == after_fires, {"before": before_fires, "after": after_fires}
