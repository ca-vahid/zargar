"""2026-09-23 adversarial-review plan (ADV-01..12): the pure pieces behind every change, each with the failure it guards."""
import datetime as dt
import json
from types import SimpleNamespace as NS

import pytest

from zargar.approvals.proposals import ProposalService
from zargar.techniques.tip import friction, geometry, review_context, review_gate
from zargar.techniques.tip.analyst import cache_messages, prompt_cache_scope
from zargar.tools import tip_knowledge_ledger as kl
from zargar.tools import tip_overnight_study as ov
from zargar.tools import tip_shadow_audit as sa
from zargar.tools import tip_weekly_review as wr


# ADV-01 ------------------------------------------------------------------------------------------------------------
def test_an_option_rung_is_judged_on_the_underlying_never_on_the_premium():
    """The live table printed a $33,105 'shortfall' by comparing GOOGL's 342 target with a 10.95 premium."""
    o = friction.rung_shortfall(is_option=True, target=26.5, fill_price=0.64, underlying_at_fill=26.51, qty=2)
    assert o["shortfallPerUnit"] == pytest.approx(-0.01) and o["shortfallDollars"] is None and "underlying" in o["basis"]
    assert friction.rung_shortfall(is_option=True, target=342.0, fill_price=10.95, underlying_at_fill=None, qty=1)["shortfallPerUnit"] is None
    s = friction.rung_shortfall(is_option=False, target=30.60, fill_price=29.904, underlying_at_fill=None, qty=17)
    assert s["shortfallDollars"] == pytest.approx(11.83, abs=0.01)


# ADV-02 ------------------------------------------------------------------------------------------------------------
def test_a_book_with_unallocated_sells_or_negative_lots_is_never_evidence():
    assert sa.judge({"unallocated": 0, "negativeLots": 0})["reliable"] is True
    assert sa.judge({"unallocated": 2, "negativeLots": 0})["reliable"] is False
    bad = sa.judge({"unallocated": 0, "negativeLots": 1})
    assert bad["reliable"] is False and "short shares it never bought" in bad["reasons"][0]


# ADV-03 ------------------------------------------------------------------------------------------------------------
def test_cache_marks_only_the_last_block_and_never_mutates_the_transcript():
    msgs = [{"role": "user", "content": "HEADER"}, {"role": "assistant", "content": [NS(type="text", text="x")]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]}]
    out = cache_messages(msgs, enabled=True)
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in msgs[-1]["content"][-1]                       # the loop's own transcript is untouched
    assert out[0] is msgs[0]
    first = cache_messages([{"role": "user", "content": "HEADER"}], enabled=True)
    assert first[0]["content"] == [{"type": "text", "text": "HEADER", "cache_control": {"type": "ephemeral"}}]
    assert cache_messages(msgs, enabled=False) is msgs
    assert cache_messages([{"role": "assistant", "content": [NS(type="text")]}], enabled=True)[0]["content"][0].type == "text"


def test_cache_scope_defaults_to_the_old_prefix_and_rejects_junk():
    assert prompt_cache_scope(NS(settings={})) == "prefix"
    assert prompt_cache_scope(NS(settings={"techniques.tip.prompt_cache_scope": "conversation"})) == "conversation"
    assert prompt_cache_scope(NS(settings={"techniques.tip.prompt_cache_scope": "everything"})) == "prefix"


async def test_a_frozen_replay_can_cache_the_conversation_and_transform_the_header():
    from zargar.techniques.tip import review_frozen as rf
    case = rf.build_case({"id": "r", "source": "s", "created_at": None, "model": "m",
                          "trace": [{"kind": "context", "reviewManifest": rf.review_manifest(header="H", system="S", model="m", max_tools=2, source="s")}],
                          "opinion": {"toolsUsed": []}})
    sent = []

    async def create(**kw):
        sent.append(kw)
        return NS(content=[NS(type="text", text=json.dumps({"headline": "h", "details": "", "watch": [], "missed_tip": None, "confidence": .5}))],
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=7, cache_creation_input_tokens=3))
    budget = rf.SuiteBudget(5.0, {"m": {"in": 1.0, "out": 1.0, "cacheRead": .1, "cacheWrite": 1.25}})
    rep = await rf.replay_review(case, client=NS(messages=NS(create=create)), model="m", budget=budget,
                                 prompt_cache="conversation", header_transform=lambda h: h + "!")
    msg = sent[0]["messages"][0]["content"]
    assert msg[0]["text"] == "H!" and msg[0]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(sent[0]["system"], list) and rep["tokens"]["cacheRead"] == 7 and rep["tokens"]["cacheWrite"] == 3


# ADV-04 ------------------------------------------------------------------------------------------------------------
HEADER = """Today (ET): 2026-09-22 10:00
SOURCE: ab
MESSAGE:
$ACHR 5.5c im OUT

PER-SIGNAL OUTCOMES: []
YOUR TRADING RULES (self-maintained):
- RULE (trim alert is not an entry): a trim line is position commentary. """ + "x" * 900 + """
- RULE: short rule.
PENDING RULE PROPOSALS - NOT operative policy:
- RULE (pending thing): """ + "y" * 400 + """
SHARED NOTES (desk knowledge):
- [ticker:ACHR] ACHR note """ + "a" * 600 + """
- [ticker:NVDA] unrelated nvda note
- [source:ab] ab note
- [general] g1
- [general] g2
- [general] g3
- [general] g4
RECENT MESSAGES FROM THIS SOURCE (mirror, newest first):
- [10:00] ab: out
"""


def test_the_compact_header_keeps_verbatim_prefixes_and_scopes_notes():
    out = review_context.compact_review_header(HEADER, tickers=["ACHR"], source="ab")
    assert len(out) < len(HEADER) * 0.6
    assert "- RULE (trim alert is not an entry): a trim line" in out and "x" * 400 not in out
    assert "- RULE: short rule." in out and "y" * 200 not in out
    assert "[ticker:ACHR]" in out and "[source:ab]" in out and "[ticker:NVDA]" not in out
    assert out.count("[general]") == review_context.MAX_GENERAL_NOTES
    assert "RECENT MESSAGES FROM THIS SOURCE" in out and "MESSAGE:\n$ACHR 5.5c im OUT" in out
    assert review_context.tickers_in("$ACHR 5.5c and $NEM", [{"ticker": "pl"}]) == ["ACHR", "NEM", "PL"]


# ADV-05 ------------------------------------------------------------------------------------------------------------
def test_source_budget_is_off_by_default_and_only_a_known_spend_trips_it():
    assert review_gate.source_budget({}, "ab") is None
    assert review_gate.source_budget({"techniques.tip.review_source_budgets": {"*": 5}}, "ab") == 5.0
    assert review_gate.source_budget({"techniques.tip.review_source_budgets": {"ab": 0, "*": 5}}, "ab") is None
    assert review_gate.over_budget(5.0, 5.0) and not review_gate.over_budget(None, 5.0) and not review_gate.over_budget(9.0, None)


# ADV-06 ------------------------------------------------------------------------------------------------------------
def test_exposure_caps_refuse_new_entries_only_when_set():
    r = ProposalService.exposure_refusal
    assert r(equity=9000, total_cost=6500, name_cost=0, book_pct=0, name_pct=0, underlying="X") is None
    assert "book exposure cap" in r(equity=9000, total_cost=6500, name_cost=0, book_pct=60, name_pct=0, underlying="X")
    assert "name exposure cap" in r(equity=9000, total_cost=1000, name_cost=2000, book_pct=60, name_pct=20, underlying="SBLK")
    assert r(equity=0, total_cost=6500, name_cost=0, book_pct=60, name_pct=0, underlying="X") is None


# ADV-07 ------------------------------------------------------------------------------------------------------------
def test_the_share_alternative_is_equal_risk_long_only_and_bounded():
    a = geometry.shares_alternative(direction="long", entry_ref=100.0, final_stop=96.0, budget=90.0, max_notional=2000.0)
    assert a["available"] and a["qty"] == 20 and a["plannedRisk"] == 80.0 and a["notional"] == 2000.0
    assert geometry.shares_alternative(direction="long", entry_ref=100.0, final_stop=96.0, budget=90.0, max_notional=1000.0)["qty"] == 10
    assert geometry.shares_alternative(direction="short", entry_ref=100, final_stop=104, budget=90)["available"] is False
    assert geometry.shares_alternative(direction="long", entry_ref=100, final_stop=None, budget=90)["available"] is False
    assert geometry.shares_alternative(direction="long", entry_ref=100, final_stop=0.5, budget=90)["available"] is False


# ADV-09 ------------------------------------------------------------------------------------------------------------
def test_overnight_carry_is_bid_to_bid_and_bucketed_by_dte():
    assert ov.dte_bucket("ACHR260925C00005500", "2026-09-22") == "0-7 DTE"
    assert ov.dte_bucket("ACHR270115C00007000", dt.date(2026, 9, 22)) == "31+ DTE" and ov.dte_bucket("PL", dt.date(2026, 9, 22)) == "shares"
    c = ov.carry({"symbol": "ACHR260925C00005500", "qty": 5, "preclose": {"bid": 0.14}, "nextOpen": {"bid": 0.18}})
    assert c["dollars"] == pytest.approx(20.0) and c["pct"] == pytest.approx(28.57, abs=0.01)
    assert ov.carry({"symbol": "PL", "qty": 1, "preclose": {"bid": 0}, "nextOpen": {"bid": 1}}) is None


# ADV-11 ------------------------------------------------------------------------------------------------------------
def test_a_rule_is_bound_only_by_three_dated_cases():
    assert kl.cases_cited("MSTR 9/04, ORCL 9/10, PURR 9/10 and 2026-09-14") == 3
    assert kl.judge_rule({"text": "a rule from one trade on 9/04"}) == ["unbound"]
    assert kl.judge_rule({"text": "9/04 9/10 9/11"}) == []


# ADV-12 ------------------------------------------------------------------------------------------------------------
def test_the_weekly_review_picks_sections_without_duplicating_the_headline():
    md = "# T\nline\n## Reconciliation\nr1\n## Other\no1\n## How closed positions ended\nh1"
    assert wr.headline(md, 30) == "# T\nline"
    assert wr.pick_sections(md, ["## Reconciliation", "## How closed"]) == "## Reconciliation\nr1\n## How closed positions ended\nh1"
