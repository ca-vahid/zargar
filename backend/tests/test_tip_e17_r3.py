"""E17 round 3 companions: scan-limit refusal keeps single objects working; model stamps on rule-audit
attempts; the budgeted cache on/off replay accounts every attempt and stops at the ceiling. Scripted only."""
import json

import pytest

from zargar.signals.extraction import _parse_result_json
from zargar.techniques.tip import frozen, rule_audit
from zargar.techniques.tip.analyst import AnalystOpinion, parse_single_object
from zargar.techniques.tip.frozen import ReplayBudget, ReplayBudgetExceeded
from zargar.tools.tip_llm_cost import normalize_usage

from .test_tip_analyst_loop import _Block, _Resp, _json_opinion


RATE = {"in": 5.0, "out": 25.0, "cacheRead": 0.5, "cacheWrite": 6.25}


def test_scan_limit_refusal_leaves_single_objects_and_bounded_junk_working():
    op = _json_opinion()
    assert parse_single_object(op + ' {"unrelated": 1}' * 5, AnalystOpinion).verdict == "skip"
    with pytest.raises(ValueError, match="scan limit"):
        parse_single_object(op + ' {"unrelated": 1}' * 25, AnalystOpinion)
    ex = '{"signals": [], "source_type": "other"}'
    assert _parse_result_json(ex + ' {"x": 1}' * 19).source_type == "other"
    with pytest.raises(ValueError, match="scan limit"):
        _parse_result_json(ex + ' {"x": 1}' * 21)


async def test_rule_audit_attempts_carry_the_model_on_success_and_failure():
    class Client:
        def __init__(self, fail): self.messages = self; self.fail = fail
        async def create(self, **kw):
            if self.fail:
                raise RuntimeError("boom")
            return _Resp([_Block(type="text", text=json.dumps({"keep": [], "supersede": [], "merge": [], "flag": [],
                                                                "summary": "ok", "new_rules": [], "expire": []}))])
    ok, calls = await rule_audit._judge(Client(False), model="audit-model", system="s", header="h", cap=500, max_tokens_ceiling=1000)
    assert calls and all(c.get("model") == "audit-model" for c in calls)
    assert normalize_usage(calls)["model"] == "audit-model"
    with pytest.raises(rule_audit.JudgeError) as ei:
        await rule_audit._judge(Client(True), model="audit-model", system="s", header="h", cap=500, max_tokens_ceiling=1000)
    failed_calls = ei.value.args[1] if len(ei.value.args) > 1 else getattr(ei.value, "calls", None)
    assert failed_calls and all(c.get("model") == "audit-model" and c.get("error") for c in failed_calls)


def test_replay_budget_checks_before_and_charges_after_including_unknown_billed():
    b = ReplayBudget(1.0, RATE, model="m")
    est = b.estimate_usd(system="s" * 4000, messages=[{"role": "user", "content": "h" * 4000}], tools=[], max_tokens=1000)
    floor = 2000 / 1e6 * 5.0 + 1000 / 1e6 * 25.0          # prompt chars / 4 at in-rate + full max_tokens at out-rate
    assert floor <= est <= floor * 1.05                      # the JSON envelope adds a few tokens - never less than the floor
    b.allow(est, label="a1")
    b.charge({"attempt": 1, "inputTokens": 100_000, "outputTokens": 1_000, "cacheReadTokens": 0, "cacheWriteTokens": 0})
    assert b.spent_usd == pytest.approx(0.5 + 0.025)
    # unknown-billed attempt: charged at its estimate, counted
    b.charge({"attempt": 2, "error": "timeout", "estimateUsd": 0.3})
    assert b.spent_usd == pytest.approx(0.825) and b.summary()["unknownBilled"] == 1
    with pytest.raises(ReplayBudgetExceeded):
        b.allow(0.2, label="a3")
    assert b.summary()["refused"][0]["label"] == "a3"
    with pytest.raises(ValueError, match="rate card"):
        ReplayBudget(8.0, {"in": 5.0}, model="m")


def _minimal_bundle():
    return {"id": "fb-test", "manifest": {"exact": True, "system": "SYS-PROMPT", "header": "HEADER", "headerSha": None},
            "settings": {"techniques.tip.analyst_max_tools": 2, "techniques.tip.analyst_max_output_tokens": 500},
            "run": {"model": "m", "opinion": {"verdict": "skip"}}, "gaps": [], "toolOutputs": [], "knowledge": {"rules": [], "notes": []}}


class _Client:
    def __init__(self, responses):
        self.messages = self; self.kw = []; self._r = list(responses)

    async def create(self, **kw):
        self.kw.append(kw)
        r = self._r.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


def _resp_with_usage(text, *, inp=1000, out=50, cw=0, cr=0):
    r = _Resp([_Block(type="text", text=text)])
    r.usage = _Block(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=cw, cache_read_input_tokens=cr)
    return r


async def test_replay_cache_switch_shapes_the_request_and_accounts_every_attempt(monkeypatch):
    monkeypatch.setattr(frozen, "variant_knowledge", lambda b, v: {"available": True, "rulesText": "r", "notesText": "n"})
    monkeypatch.setattr(frozen, "_rebuild_header", lambda man, **kw: ("HEADER", []))
    off = _Client([_resp_with_usage(_json_opinion(), inp=2000)])
    rep_off = await frozen.replay(_minimal_bundle(), variant="current", client=off, prompt_cache=False)
    assert isinstance(off.kw[0]["system"], str) and rep_off["promptCache"] is False
    assert rep_off["tokens"]["attempts"][0]["inputTokens"] == 2000 and rep_off["prefixChars"] > 0 and rep_off["headerChars"] == len("HEADER")
    on = _Client([_resp_with_usage(_json_opinion(), inp=200, cw=1800)])
    b = ReplayBudget(8.0, RATE, model="m")
    rep_on = await frozen.replay(_minimal_bundle(), variant="current", client=on, prompt_cache=True, budget=b)
    assert on.kw[0]["system"][0]["cache_control"] == {"type": "ephemeral"} and on.kw[0]["tools"][-1].get("cache_control")
    assert rep_on["promptCache"] is True and rep_on["tokens"]["cacheCreation"] == 1800
    at = rep_on["tokens"]["attempts"][0]
    assert at["billing"] == "provider usage" and at["usd"] == pytest.approx(200 / 1e6 * 5.0 + 50 / 1e6 * 25.0 + 1800 / 1e6 * 6.25)
    assert rep_on["budget"]["spentUsd"] == pytest.approx(at["usd"]) and rep_on["verdict"] == "skip"


async def test_replay_stops_at_the_ceiling_and_charges_a_failed_attempt_at_estimate(monkeypatch):
    monkeypatch.setattr(frozen, "variant_knowledge", lambda b, v: {"available": True, "rulesText": "r", "notesText": "n"})
    monkeypatch.setattr(frozen, "_rebuild_header", lambda man, **kw: ("HEADER", []))
    # a tiny cap: the first attempt is refused before any call is sent
    tiny = ReplayBudget(0.0001, RATE, model="m")
    c = _Client([_resp_with_usage(_json_opinion())])
    rep = await frozen.replay(_minimal_bundle(), variant="current", client=c, prompt_cache=False, budget=tiny)
    assert rep["noVerdict"] is True and str(rep["error"]).startswith("budget:") and c.kw == [] and tiny.summary()["refused"]
    # a provider failure is charged at its estimate and counted as unknown-billed
    b = ReplayBudget(8.0, RATE, model="m")
    c2 = _Client([RuntimeError("provider down")])
    rep2 = await frozen.replay(_minimal_bundle(), variant="current", client=c2, prompt_cache=True, budget=b)
    assert rep2["noVerdict"] is True and rep2["tokens"]["unknownBilled"] == 1
    assert b.summary()["unknownBilled"] == 1 and b.spent_usd > 0 and b.attempts[0]["billing"].startswith("unknown")
