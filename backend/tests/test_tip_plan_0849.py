"""2026-09-24 sharp-pencil plan, implemented for 09-25: shares-first (P1), deterministic mirror of the source's exit (P2),
opening-quote grace for option stops (P3), lotto daily cap (P6), rule labels + reliance (P7), relied-first notes (P8),
source cache block (P9)."""
import datetime as dt
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from zargar.approvals.proposals import shares_first_applies
from zargar.signals.sources import resolve_policy
from zargar.techniques.tip.analyst import rule_ids_from_labels
from zargar.techniques.tip.review_context import stable_first_blocks

ET = ZoneInfo("America/New_York")


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_shares_first_is_long_non_lotto_practice_only_and_per_source():
    assert shares_first_applies("shares", direction="long", lotto=False, portfolio_kind="sim") is True
    assert shares_first_applies("shares", direction="short", lotto=False, portfolio_kind="sim") is False   # puts only
    assert shares_first_applies("shares", direction="long", lotto=True, portfolio_kind="sim") is False     # lotto lane
    assert shares_first_applies("shares", direction="long", lotto=False, portfolio_kind="live") is False
    assert shares_first_applies("as_tip", direction="long", lotto=False, portfolio_kind="sim") is False
    s = _S({"techniques.tip.expression_default": "shares",
            "techniques.tip.sources": {"ab": {"expression": "as_tip"}, "cs": {}}})
    assert resolve_policy(s, "cs").expression == "shares" and resolve_policy(s, "ab").expression == "as_tip"
    assert resolve_policy(_S({}), "x").expression == "as_tip"


def test_rule_labels_map_to_the_runs_own_rule_ids():
    snap = {"ruleLabels": {"R1": "a", "R2": "b"}}
    assert rule_ids_from_labels(["R2", "r1", "N3", "R9", "R2"], snap) == ["b", "a"]
    assert rule_ids_from_labels(None, snap) == [] and rule_ids_from_labels(["R1"], None) == []


def test_the_source_notes_ride_their_own_cached_block():
    h = ("Today\nMESSAGE:\nhi\n\nYOUR TRADING RULES (self-maintained):\n- R1: a\nSHARED NOTES (desk knowledge):\n"
         "- [source:ab] s1\n- [ticker:X] t1\nRECENT MESSAGES FROM THIS SOURCE (mirror, newest first):\n- m\n")
    b = stable_first_blocks(h, source_block=True)
    assert len(b) == 3 and all("cache_control" in x for x in b[:2]) and "cache_control" not in b[2]
    assert "[source:ab] s1" in b[1]["text"] and "[source:ab]" not in b[2]["text"] and "[ticker:X] t1" in b[2]["text"]
    assert len(stable_first_blocks(h)) == 2                          # off: the P-D two-block layout


def _mgr(settings):
    from zargar.execution.positions import PositionManager
    pm = PositionManager.__new__(PositionManager)
    pm.engine = NS(settings=settings)
    pm._log = lambda *a, **k: None
    return pm


def test_option_quote_stops_wait_out_the_opening_minutes_unless_it_is_a_catastrophe():
    s = _S({"techniques.tip.open_stop_grace_s": 300, "techniques.tip.open_stop_catastrophe_pct": 60})
    pm = _mgr(s)
    opt = NS(id="p", technique="tip", has_options=True, entry_mark=1.0)
    ms = lambda h, m, sec=0: int(dt.datetime(2026, 9, 25, h, m, sec, tzinfo=ET).timestamp() * 1000)  # noqa: E731
    assert pm._open_grace(opt, ms(9, 31), mark=0.7) is True           # -30% in the first minutes: wait
    assert pm._open_grace(opt, ms(9, 31), mark=0.35) is False         # -65%: a catastrophe is never waited out
    assert pm._open_grace(opt, ms(9, 36), mark=0.7) is False          # after the grace
    assert pm._open_grace(NS(id="s", technique="tip", has_options=False, entry_mark=None), ms(9, 31)) is False
    assert _mgr(_S({}))._open_grace(opt, ms(9, 31), mark=0.7) is False   # 0 = off (EM/Team2 untouched)


async def test_the_authors_own_exit_closes_our_mirror_and_nothing_else():
    from zargar.signals.service import SignalService
    closed, journal = [], []

    class PM:
        def positions(self, status=None):
            return [{"id": "a", "technique": "tip", "tags": ["source:ab"], "symbol": "NEM", "portfolioId": "sim"},
                    {"id": "b", "technique": "tip", "tags": ["source:other"], "symbol": "NEM", "portfolioId": "sim"},
                    {"id": "c", "technique": "tip", "tags": ["source:ab"], "symbol": "IONQ", "portfolioId": "sim"},
                    {"id": "d", "technique": "tip", "tags": ["source:ab"], "symbol": "NEM", "portfolioId": "live"}]

        async def close(self, pid, fraction=1.0, reason=""):
            closed.append((pid, fraction))

    class J:
        async def append(self, *a, **k):
            journal.append(a[0])
    kinds = {"sim": {"kind": "sim"}, "live": {"kind": "live"}}
    eng = NS(settings=_S({"techniques.tip.mirror_source_exits": True, "techniques.tip.mirror_trim_fraction": 0.5}),
             position_manager=PM(), positions=NS(portfolio=lambda pid: kinds.get(pid)), journal=J())
    svc = SignalService.__new__(SignalService)
    svc.engine = eng
    row = NS(id="sig1", ticker="NEM")
    own = NS(action="close", actor="author", is_actionable=True)
    assert await svc._mirror_source_exit("ab", row, own, {"passed": True}) == ["a"]
    assert closed == [("a", 1.0)] and journal == ["TipSourceExitMirrored"]
    closed.clear()
    await svc._mirror_source_exit("ab", row, NS(action="trim", actor="author", is_actionable=True), {"passed": True})
    assert closed == [("a", 0.5)]
    closed.clear()
    await svc._mirror_source_exit("ab", row, NS(action="close", actor="third_party", is_actionable=True), {"passed": True})
    await svc._mirror_source_exit("ab", row, own, {"passed": False})                     # ungrounded
    await svc._mirror_source_exit("ab", row, NS(action="update_stop", actor="author", is_actionable=True), {"passed": True})
    eng.settings["techniques.tip.mirror_source_exits"] = False
    await svc._mirror_source_exit("ab", row, own, {"passed": True})
    assert closed == []
