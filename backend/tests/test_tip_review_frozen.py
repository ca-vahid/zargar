"""Frozen evaluation of intake reviews (2026-09-19, safeguards rev 2): a captured review replays on another model with
NO side effect; the INSTRUCTION is compared (levels and quantities, not only tool + target); evidence the case does not
hold stays missing; ONE ceiling covers every model, case, turn, retry and invocation."""
import json
from types import SimpleNamespace as NS

import pytest

from zargar.techniques.tip import review_frozen as rf

RATES = {"claude-sonnet-5": {"in": 2.0, "out": 10.0, "cacheRead": 0.2, "cacheWrite": 2.5},
         "claude-haiku-4-5": {"in": 1.0, "out": 5.0, "cacheRead": 0.1, "cacheWrite": 1.25}}
STOP = {"position_id": "pos-sblk", "underlying_stop": 30.58, "reason": "source moved the stop"}


def _run(*, captured=True, mgmt=STOP, reads=None):
    trace = [{"kind": "start", "text": "x"}]
    if captured:
        trace.append({"kind": "context", "reviewManifest": rf.review_manifest(
            header="MESSAGE: trimmed SBLK, stop to 30.58", system="SYS", model="claude-opus-5", max_tools=4, source="src")})
    for tool, args, result in (reads or [("get_positions", {}, {"positions": [{"symbol": "SBLK", "qty": 62}]})]):
        trace += [{"kind": "tool_call", "tool": tool, "args": args}, {"kind": "tool_result", "tool": tool, "result": result}]
    used = [{"tool": "get_positions", "args": {}}] + ([{"tool": "update_exit_plan", "args": mgmt}] if mgmt else [])
    return {"id": "run-1", "source": "src", "model": "claude-opus-5", "created_at": None, "trace": trace,
            "opinion": {"toolsUsed": used, "missedTip": None, "watch": ["SBLK"], "model": "claude-opus-5"}}


def _tool(name, args, i=1):
    return NS(type="tool_use", name=name, input=args, id=f"t{i}")


class _Client:
    """Scripted provider: each entry is a list of content blocks, or an Exception to raise."""
    def __init__(self, script, *, tokens=(1000, 100)):
        self.script, self.sent, self.tokens = list(script), [], tokens
        self.messages = NS(create=self._create)

    async def _create(self, **kw):
        self.sent.append({**kw, "messages": list(kw["messages"])})          # the list keeps growing - snapshot it
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return NS(content=step, usage=NS(input_tokens=self.tokens[0], output_tokens=self.tokens[1],
                                         cache_read_input_tokens=0, cache_creation_input_tokens=0), stop_reason="end_turn")


def _final(missed=None):
    return [NS(type="text", text=json.dumps({"headline": "SBLK trimmed", "details": "", "watch": ["SBLK"],
                                              "missed_tip": missed, "confidence": 0.6}))]


def _budget(cap=5.0, path=None):
    return rf.SuiteBudget(cap, RATES, ledger_path=path)


def test_an_uncaptured_review_is_not_replayable_and_says_why():
    case = rf.build_case(_run(captured=False))
    assert case["replayable"] is False and "not captured" in case["gaps"][0]
    assert case["baseline"]["instructions"] == [{"tool": "update_exit_plan", "target": "POS-SBLK", "params": {"underlying_stop": 30.58}}]


async def test_replay_serves_the_exact_read_and_never_executes_management():
    case = rf.build_case(_run())
    client = _Client([[_tool("get_positions", {})], [_tool("update_exit_plan", {**STOP, "reason": "other words"}, 2)], _final()])
    rep = await rf.replay_review(case, client=client, model="claude-sonnet-5", budget=_budget())
    assert client.sent[0]["system"] == "SYS" and client.sent[0]["messages"][0]["content"] == case["manifest"]["header"]
    assert json.loads(client.sent[1]["messages"][-1]["content"][0]["content"]) == {"positions": [{"symbol": "SBLK", "qty": 62}]}
    assert json.loads(client.sent[2]["messages"][-1]["content"][0]["content"])["frozen"] is True      # nothing was changed
    assert rep["compare"]["outcome"] == "agree"                     # the reason's wording is not part of the instruction
    assert rep["budget"]["attempts"] == 3 and rep["budget"]["withinGuard"] is True


async def test_a_changed_stop_level_is_a_disagreement_not_agreement():
    """Reviewer case: SBLK stop 30.58 -> 25.00 used to score as agreement (tool + target only)."""
    case = rf.build_case(_run())
    client = _Client([[_tool("update_exit_plan", {**STOP, "underlying_stop": 25.0})], _final()])
    c = (await rf.replay_review(case, client=client, model="claude-haiku-4-5", budget=_budget()))["compare"]
    assert c["outcome"] == "disagree" and c["agree"] is False and c["missed"] == [] and c["extra"] == []
    assert c["changed"] == [{"tool": "update_exit_plan", "target": "POS-SBLK",
                             "fields": {"underlying_stop": {"baseline": 30.58, "candidate": 25.0}}}]


async def test_a_different_sale_quantity_or_an_added_parameter_is_a_disagreement():
    sale = {"position_id": "pos-sblk", "fraction": 0.5, "reason": "trim"}
    run = _run(mgmt=None)
    run["opinion"]["toolsUsed"].append({"tool": "close_position", "args": sale})
    case = rf.build_case(run)
    c = (await rf.replay_review(case, client=_Client([[_tool("close_position", {**sale, "fraction": 1.0})], _final()]),
                                model="claude-sonnet-5", budget=_budget()))["compare"]
    assert c["outcome"] == "disagree" and c["changed"][0]["fields"] == {"fraction": {"baseline": 0.5, "candidate": 1.0}}
    case2 = rf.build_case(_run())
    c2 = (await rf.replay_review(case2, client=_Client([[_tool("update_exit_plan", {**STOP, "max_hold_sessions": 1})], _final()]),
                                 model="claude-sonnet-5", budget=_budget()))["compare"]
    assert c2["outcome"] == "disagree" and c2["changed"][0]["fields"] == {"max_hold_sessions": {"baseline": None, "candidate": 1.0}}


async def test_another_requests_evidence_is_never_substituted_and_missing_is_not_a_pass():
    """Reviewer case: a replay asking for MSFT's quote used to receive AAPL's captured quote."""
    aapl = ("get_quote", {"symbol": "AAPL"}, {"symbol": "AAPL", "last": 231.4})
    case = rf.build_case(_run(reads=[aapl]))
    client = _Client([[_tool("get_quote", {"symbol": "MSFT"})], [_tool("update_exit_plan", STOP, 2)], _final()])
    rep = await rf.replay_review(case, client=client, model="claude-sonnet-5", budget=_budget())
    answer = json.loads(client.sent[1]["messages"][-1]["content"][0]["content"])
    assert "error" in answer and "231.4" not in json.dumps(answer) and "AAPL" not in json.dumps(answer)
    assert rep["missingEvidence"] == [{"tool": "get_quote", "args": {"symbol": "MSFT"}}]
    c = rep["compare"]
    assert rep["instructions"] == case["baseline"]["instructions"]                  # identical instruction ...
    assert c["outcome"] == "inconclusive" and c["agree"] is False                   # ... yet NOT an equivalence pass
    s = rf.summarize([rep])
    assert s["agree"] == 0 and s["inconclusive"] == 1


async def test_a_missed_management_action_and_a_flag_difference_are_reported_apart():
    case = rf.build_case(_run())
    rep = await rf.replay_review(case, client=_Client([_final(missed="GS 900C")]), model="claude-haiku-4-5", budget=_budget())
    c = rep["compare"]
    assert c["outcome"] == "disagree" and c["missed"] == case["baseline"]["instructions"] and c["extra"] == []
    assert c["missedEntryFlag"] == {"baseline": False, "candidate": True, "same": False}
    s = rf.summarize([rep])
    assert s["missedManagement"] == 1 and s["missedEntryFlagDiffers"] == 1


async def test_one_ceiling_covers_both_models_all_cases_turns_retries_and_invocations(tmp_path):
    """The aggregate demonstration: 2 models x 6 cases x 2 turns with a failing attempt, across TWO processes."""
    ledger = str(tmp_path / "ledger.json")
    cap = 1.00
    sent = 0

    async def run_suite(models):
        nonlocal sent
        budget = _budget(cap, ledger)                                # a fresh object = a separate invocation
        reports = []
        for model in models:
            for n in range(6):
                case = rf.build_case({**_run(), "id": f"run-{n}"})
                script = [RuntimeError("overloaded")] if n == 1 else [[_tool("get_positions", {})], _final()]
                client = _Client(script)
                reports.append(await rf.replay_review(case, client=client, model=model, budget=budget))
                sent += len(client.sent)
        return budget, reports

    b1, r1 = await run_suite(["claude-sonnet-5"])
    b2, r2 = await run_suite(["claude-haiku-4-5"])                    # continues the SAME total from the ledger
    # a third invocation asks for more than what is left: refused BEFORE anything is sent, and never a pass
    b3 = _budget(cap, ledger)
    greedy = _Client([_final()])
    over = await rf.replay_review(rf.build_case(_run()), client=greedy, model="claude-sonnet-5", budget=b3, max_tokens=200_000)
    assert greedy.sent == [] and "budget" in over["error"] and over["compare"]["outcome"] == "invalid"
    s = b3.summary()
    assert s["withinGuard"] is True and s["spentUsd"] <= cap and s["refused"] == 1
    assert set(s["byModel"]) == {"claude-sonnet-5", "claude-haiku-4-5"} and s["attempts"] == sent == 22
    assert s["unknownBilled"] == 2                                   # each failed attempt stays charged at its reservation
    assert abs(s["spentUsd"] - sum(s["byModel"].values())) < 1e-4 and b3.spent_usd == b2.spent_usd
    assert rf.SuiteBudget(cap, RATES, ledger_path=ledger).spent_usd == b2.spent_usd  # durable
    with pytest.raises(ValueError):
        rf.SuiteBudget(cap * 2, RATES, ledger_path=ledger)            # a later run cannot raise the ceiling


async def test_the_reservation_is_conservative_and_a_budget_is_mandatory():
    b = _budget(5.0)
    res = b.reservation_usd("claude-sonnet-5", system="S" * 3000, messages=[], tools=[], max_tokens=1000)
    assert res >= (1000 / 1e6 * 2.0 + 1000 / 1e6 * 10.0) * 1.25 - 1e-12          # chars/3 input + FULL output, with headroom
    with pytest.raises(ValueError):
        await rf.replay_review(rf.build_case(_run()), client=_Client([]), model="claude-sonnet-5", budget=None)
    rep = await rf.replay_review(rf.build_case(_run()), client=_Client([_final()]), model="claude-opus-5", budget=b)
    assert rep["valid"] is False and "no rate card" in rep["error"]                # a model without a card cannot run
    with pytest.raises(ValueError):
        rf.SuiteBudget(5.0, {"m": {"in": 1.0, "out": 5.0}})
