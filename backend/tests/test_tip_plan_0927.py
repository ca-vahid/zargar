"""Sharp-pencil review #3 (2026-09-27): stale exit + slot cap (Q1), instrument-matched mirror (Q2), the author's close
disarms a waiting plan (Q3), share targets on the live bid (Q5), rule-proposal queue guard (Q7), 1-hour rulebook
cache (Q9), dry gate audit (Q12)."""
from types import SimpleNamespace as NS

from zargar.domain import Bar
from zargar.execution.policies import PolicyState, PositionView, evaluate, quote_target_decision
from zargar.signals.service import mirror_instrument_matches
from zargar.techniques.tip.lifecycle import policy_from_exit_plan
from zargar.techniques.tip.review_context import stable_first_blocks
from zargar.tools.tip_llm_cost import price


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def _bar(close):
    return Bar(symbol="X", tf="15m", ts=1_790_000_000_000, open=close, high=close, low=close, close=close, volume=1)


def test_stale_share_positions_free_the_slot_on_a_closed_bar():
    pol = {"stop": {"kind": "fixed", "price": 90.0}, "stale": {"sessions": 5, "min_r": 0.5}}
    st = PolicyState()
    view = lambda held, close: PositionView(direction="long", entry=100.0, risk=10.0, bar=_bar(close),  # noqa: E731
                                            sessions_held=held)
    d, _ = evaluate(pol, st, view(5, 104.0))                       # +0.4R after 5 sessions: stale
    assert [x.kind for x in d] == ["time"] and "stale" in d[0].reason
    assert evaluate(pol, st, view(5, 106.0))[0] == []              # +0.6R: earned its slot
    assert evaluate(pol, st, view(4, 100.0))[0] == []              # too early


def test_share_ladder_on_the_live_quote_uses_the_same_arithmetic():
    pol = {"ladder": {"targets": [110.0, 120.0], "fractions": [0.5, 0.5]}}
    assert quote_target_decision(pol, PolicyState(), "long", 109.99) is None
    d = quote_target_decision(pol, PolicyState(), "long", 110.0)
    assert d.kind == "trim" and abs(d.fraction - 0.5) < 1e-9
    d2 = quote_target_decision(pol, PolicyState(trims_done=1), "long", 121.0)
    assert abs(d2.fraction - 1.0) < 1e-9                            # the last rung sells the rest
    assert quote_target_decision(pol, PolicyState(trims_done=2), "long", 500.0) is None
    assert quote_target_decision({"ladder": {"targets": [90.0]}}, PolicyState(), "short", 89.0).kind == "trim"
    assert quote_target_decision(pol, PolicyState(), "long", None) is None


def test_adoption_policy_carries_stale_and_target_watch_for_shares_only():
    s = _S({"techniques.tip.stale_after_sessions": 5, "techniques.tip.stale_min_r": 0.5,
            "techniques.tip.share_target_watch": True})
    plan = {"underlyingStop": 90.0, "targets": [110.0], "fractions": [1.0], "maxHoldSessions": 15}
    shares = policy_from_exit_plan(plan, is_option=False, settings=s)
    assert shares["stale"] == {"sessions": 5, "min_r": 0.5} and shares["target_watch"] is True
    opt = policy_from_exit_plan(plan, is_option=True, settings=s)
    assert "stale" not in opt and "target_watch" not in opt
    off = policy_from_exit_plan(plan, is_option=False, settings=_S({}))
    assert "stale" not in off and "target_watch" not in off


def test_the_mirror_matches_only_the_leg_our_position_came_from():
    coin = {"instrument": "call", "strike": 220.0, "expiry": "2026-10-16"}
    assert mirror_instrument_matches(coin, {"instrument": "call", "strike": 197.5, "expiry": None})[0] is False
    assert mirror_instrument_matches(coin, {"instrument": "call", "strike": 220, "expiry": "2026-10-16"})[0] is True
    assert mirror_instrument_matches(coin, {"instrument": "call", "strike": None, "expiry": "2026-10-16"})[0] is True
    assert mirror_instrument_matches(coin, {"instrument": "put", "strike": 220, "expiry": None})[0] is False
    assert mirror_instrument_matches(coin, {"instrument": "call", "strike": None, "expiry": None})[0] is True
    shares = {"instrument": "shares", "strike": None, "expiry": None}
    assert mirror_instrument_matches(shares, {"instrument": "call", "strike": 45, "expiry": None})[0] is False
    assert mirror_instrument_matches(None, {"instrument": "call", "strike": 45, "expiry": None})[0] is True


async def test_an_exit_on_another_leg_is_left_to_the_analyst():
    from zargar.signals.service import SignalService
    closed, journal = [], []

    class PM:
        def positions(self, status=None):
            return [{"id": "a", "technique": "tip", "tags": ["source:ab"], "symbol": "COIN", "portfolioId": "sim",
                     "legs": [{"entryOrderId": "o1"}]}]

        async def close(self, pid, fraction=1.0, reason=""):
            closed.append((pid, fraction))

    class J:
        async def append(self, *a, **k):
            journal.append(a[0])
    eng = NS(settings=_S({"techniques.tip.mirror_source_exits": True, "techniques.tip.mirror_trim_fraction": 0.5}),
             position_manager=PM(), positions=NS(portfolio=lambda pid: {"kind": "sim"}), journal=J())
    svc = SignalService.__new__(SignalService)
    svc.engine = eng

    async def origin(p):
        return {"instrument": "call", "strike": 220.0, "expiry": "2026-10-16"}
    svc._position_origin = origin
    own = NS(action="trim", actor="author", is_actionable=True)
    other_leg = NS(id="s1", ticker="COIN", instrument="call", strike=197.5, expiry=None)
    assert await svc._mirror_source_exit("ab", other_leg, own, {"passed": True}) == []
    assert closed == [] and journal == ["TipSourceExitNotMirrored"]
    same_leg = NS(id="s2", ticker="COIN", instrument="call", strike=220.0, expiry="2026-10-16")
    assert await svc._mirror_source_exit("ab", same_leg, own, {"passed": True}) == ["a"]
    assert closed == [("a", 0.5)]


async def test_the_authors_close_disarms_a_waiting_plan_but_a_trim_only_flags():
    from zargar.techniques.tip.runner import TipRunner
    r = TipRunner.__new__(TipRunner)
    disarmed, alerts = [], []
    ap = NS(symbol="INTC", status="armed", run_id="run1", plan={"context": {"source": "ab"}}, trades={})
    r._armed = {"run1": ap}

    async def disarm(rid, reason=""):
        disarmed.append(rid)
        return True

    async def alert(*a, **k):
        alerts.append(a[1])

    async def noop(*a, **k):
        return None
    r.disarm, r._alert, r._persist = disarm, alert, noop
    r._log = lambda *a, **k: None
    r._publish = lambda *a, **k: None
    assert await r.note_followup(source="ab", ticker="INTC", action="trim", disarm=True) == ["run1"]
    assert disarmed == [] and len(alerts) == 1                     # a trim still only flags
    assert await r.note_followup(source="ab", ticker="INTC", action="close", disarm=True) == ["run1"]
    assert disarmed == ["run1"]
    ap.trades = {"t": NS(remaining=3)}
    disarmed.clear()
    await r.note_followup(source="ab", ticker="INTC", action="close", disarm=True)
    assert disarmed == []                                         # a plan holding shares is never disarmed here


async def test_rule_proposals_wait_while_the_review_queue_is_full(monkeypatch):
    from zargar.techniques.tip import analyst as an
    added = []

    async def pending(eng):
        return 29
    monkeypatch.setattr(an, "_pending_rule_count", pending)

    async def add(scope, text, **k):
        added.append(scope)
        return {"scope": scope, "id": "n1"}
    eng = NS(settings=_S({"techniques.tip.rule_proposal_queue_max": 5}), signals_service=NS(add_tip_note=add))
    out = await an._run_tool(eng, "save_note", {"scope": "rule", "text": "RULE (x): y"}, {})
    assert out["saved"] is False and "29 rule proposals" in out["error"] and added == []
    out = await an._run_tool(eng, "save_note", {"scope": "general", "text": "a durable habit"}, {})
    assert out["saved"] is True and added == ["general"]


async def test_a_gate_audit_review_is_dry():
    from zargar.techniques.tip import analyst as an
    out = await an._run_tool(NS(settings=_S({})), "close_position", {"position_id": "p", "reason": "x"}, {"dry": True})
    assert out["dryRun"] is True and out["wouldHave"] == "close_position"


async def test_a_missed_management_in_the_audit_sends_the_gate_back_to_observe():
    from zargar.signals.service import SignalService
    journal = []

    class Settings(_S):
        async def set(self, k, v):
            self[k] = v

    class J:
        async def append(self, *a, **k):
            journal.append((a[0], a[1]["verdict"]))
    eng = NS(settings=Settings({"techniques.tip.review_gate": "enforce"}), journal=J())
    svc = SignalService.__new__(SignalService)
    svc.engine = eng
    svc.__dict__["_gate_audits"] = {"r1": {"reason": "nothing held"}, "r2": {"reason": "nothing held"}}
    await svc._gate_audit_verdict(NS(id="r1"), {"receipts": [{"tool": "save_note"}], "missedTip": None})
    assert journal == [("TipReviewGateAudit", "clean")] and eng.settings["techniques.tip.review_gate"] == "enforce"
    await svc._gate_audit_verdict(NS(id="r2"), {"receipts": [{"tool": "close_position"}]})
    assert journal[-1] == ("TipReviewGateAudit", "false_negative")
    assert eng.settings["techniques.tip.review_gate"] == "observe"
    await svc._gate_audit_verdict(NS(id="not-sampled"), None)       # not an audit: nothing happens
    assert len(journal) == 2


def test_the_rulebook_can_ride_the_one_hour_cache_and_is_priced_for_it():
    h = ("Today\nMESSAGE:\nhi\n\nYOUR TRADING RULES (self-maintained):\n- R1: a\nSHARED NOTES (desk knowledge):\n"
         "- [ticker:X] t1\n")
    b = stable_first_blocks(h, rulebook_ttl="1h")
    assert b[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and "cache_control" not in b[-1]
    assert stable_first_blocks(h)[0]["cache_control"] == {"type": "ephemeral"}
    rate = {"in": 4.0, "out": 20.0, "cacheRead": 0.4, "cacheWrite": 5.0}
    five = price({"cacheWrite": 1_000_000}, rate)["usd"]
    one_h = price({"cacheWrite": 1_000_000, "cacheWrite1h": 1_000_000}, rate)["usd"]
    assert five == 5.0 and one_h == 8.0                               # 1h write = 2x input = 1.6x the 5-min rate


async def test_a_full_book_refuses_new_ideas_on_the_record():
    from zargar.approvals.proposals import ProposalService
    svc = ProposalService.__new__(ProposalService)
    eng = NS(settings=_S({"techniques.tip.max_open_positions": 7, "techniques.tip.reserve_slots": 3}),
             positions=NS(portfolio=lambda pid: {"cash": 5000.0, "name": "Tips Practice", "kind": "sim"}))
    svc.engine = eng

    async def seven(pid):
        return 7

    async def src(pid, name):
        return 0, 0.0
    svc._book_open_count = seven
    svc._source_open = src
    pol = NS(budget_per_tip=2000.0, name="ab", max_open_tips=0, budget_open_max=0)
    budget, _note, why = await svc._tip_budget(pol, "pf")
    assert budget == 0.0 and "book slots full" in why

    async def six(pid):
        return 6
    svc._book_open_count = six
    budget, _note, why = await svc._tip_budget(pol, "pf")
    assert budget > 0 and why is None


def test_the_knowledge_manifest_covers_every_rule_and_caps_notes():
    from zargar.tools.tip_knowledge_prune import plan_notes, plan_rules
    live = {"a": {"revision": 1, "needs_human": False}, "b": {"revision": 2, "needs_human": True},
            "c": {"revision": 1, "needs_human": False}}
    cons = {"rules": [{"text": "RULE (x): merged", "supersedes": ["a", "b"]}], "expire": [{"id": "c", "reason": "obsolete"}]}
    resolve, batches, problems = plan_rules(cons, live, tag="t")
    assert problems == [] and resolve == [{"id": "b", "revision": 2}]
    assert batches[0]["merge"]["supersedes"] == ["a", "b"] and batches[0]["expected_revisions"] == {"a": 1, "b": 2}
    assert batches[1]["expire"]["ids"] == ["c"]
    _, _, problems = plan_rules({"rules": [{"text": "RULE (x)", "supersedes": ["a"]}]}, live, tag="t")
    assert any("not covered" in p for p in problems)
    notes = [{"id": f"s{i}", "scope": "source:ab", "revision": 1, "needs_human": False, "core": False,
              "cited_count": i, "supplied_count": 5, "last_cited": 0, "created": i} for i in range(20)]
    notes += [{"id": "g1", "scope": "general", "revision": 1, "needs_human": False, "core": False,
               "cited_count": 0, "supplied_count": 30, "last_cited": 0, "created": 0},
              {"id": "g2", "scope": "general", "revision": 1, "needs_human": False, "core": True,
               "cited_count": 0, "supplied_count": 30, "last_cited": 0, "created": 0}]
    b = {x["scope"]: x for x in plan_notes(notes, keep=15, general_min_supplied=20, tag="t")}
    assert sorted(b["source:ab"]["expire"]["ids"]) == [f"s{i}" for i in range(5)]   # the 5 least relied-on
    assert b["general"]["expire"]["ids"] == ["g1"]                                   # a pinned note stays
