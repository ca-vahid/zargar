"""2026-09-23 cost levers: model/effort policy, Opus 5.5-safe repairs (replies replayed as received), durable
extraction usage (`tip_llm_calls`), and the non-actionable review skip."""
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import TipAnalystRun, TipLlmCall
from zargar.signals.extraction import Extractor
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip import llm_ledger, model_policy, review_gate
from zargar.techniques.tip.analyst import _Recorder, run_agent_loop

from .conftest import make_test_config


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_effort_is_sent_only_when_set_and_only_to_models_with_an_effort_ladder():
    s = _S({"techniques.tip.analyst_effort": "high"})
    assert model_policy.effort_kw(s, "techniques.tip.analyst_effort", "claude-opus-5-5") == {"output_config": {"effort": "high"}}
    assert model_policy.effort_kw(s, "techniques.tip.analyst_effort", "claude-haiku-4-5-20251001") == {}
    assert model_policy.effort_kw(_S({"techniques.tip.analyst_effort": ""}), "techniques.tip.analyst_effort", "claude-opus-5-5") == {}
    assert model_policy.effort_kw(_S({"techniques.tip.analyst_effort": "turbo"}), "techniques.tip.analyst_effort", "claude-opus-5-5") == {}
    assert model_policy.extraction_model(_S({"techniques.tip.extraction_model": "claude-sonnet-5"}), "claude-opus-5") == "claude-sonnet-5"
    assert model_policy.extraction_model(_S({}), "claude-opus-5") == "claude-opus-5"
    assert model_policy.analyst_model(_S({}), NS(extraction_model="claude-opus-5")) == "claude-opus-5"


def test_the_extractor_reads_its_model_per_call_and_an_explicit_override_wins():
    s = _S({"techniques.tip.extraction_model": "claude-sonnet-5"})
    ex = Extractor("k", "claude-opus-5", settings=s)
    assert ex.model == "claude-sonnet-5"
    s["techniques.tip.extraction_model"] = ""
    assert ex.model == "claude-opus-5"
    ex.model = "offline"
    assert ex.model == "offline"


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content, stop="end_turn", usage=(100, 50, 30, 20)):
        self.content = content
        self.stop_reason = stop
        self.usage = _Block(input_tokens=usage[0], output_tokens=usage[1],
                            cache_read_input_tokens=usage[2], cache_creation_input_tokens=usage[3])


class _Scripted:
    def __init__(self, responses):
        self._r = list(responses)
        self.calls: list[dict] = []
        self.messages = self

    async def create(self, **kw):
        self.calls.append(kw)
        return self._r.pop(0)


async def test_extraction_repair_replays_the_reply_as_received_and_every_attempt_is_ledgered():
    """Opus 5.5 rejects a transcript whose thinking blocks were dropped: the JSON repair must replay the whole reply."""
    thinking = _Block(type="thinking", thinking="", signature="sig")
    bad = _Resp([thinking, _Block(type="text", text="not json")])
    good = _Resp([_Block(type="text", text='{"signals": [], "source_type": "other"}')])
    client = _Scripted([bad, good])
    rows: list[dict] = []

    async def ledger(**kw):
        rows.append(kw)
    ex = Extractor("k", "claude-opus-5-5", settings=_S({"techniques.tip.extraction_effort": "high"}), ledger=ledger)
    ex._client = client
    tok = llm_ledger.bind_ref("content-1")
    try:
        out = await ex.extract("hello", source_name="s")
    finally:
        llm_ledger.reset_ref(tok)
    assert out.outcome == "ok"
    second = client.calls[1]["messages"]
    assert second[1]["role"] == "assistant" and second[1]["content"] is bad.content      # unmodified, thinking kept
    assert all(c["output_config"] == {"effort": "high"} for c in client.calls)
    assert [r["stage"] for r in rows] == ["extraction", "extraction"] and rows[1]["retried"] is True


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def test_the_ledger_writes_one_durable_row_per_call_with_its_content_ref(rig):
    eng = rig
    tok = llm_ledger.bind_ref("raw-42")
    try:
        await llm_ledger.record(eng, stage="extraction", model="claude-sonnet-5", resp=_Resp([]), latency_ms=12.0)
        await llm_ledger.record(eng, stage="transcribe", model="claude-sonnet-5", error="Overloaded")
    finally:
        llm_ledger.reset_ref(tok)
    async with eng.sf() as s:
        got = (await s.execute(select(TipLlmCall).order_by(TipLlmCall.id))).scalars().all()
    assert [(r.stage, r.ref, r.input_tokens, r.cache_read_tokens) for r in got] == [
        ("extraction", "raw-42", 100, 30), ("transcribe", "raw-42", 0, 0)]
    assert got[1].error == "Overloaded"
    # the live extractor is wired to the ledger and to the settings
    ex = eng.signals_service.extractor
    assert ex.ledger is not None and ex.settings is eng.settings


async def test_the_final_reply_is_kept_as_received_for_a_same_transcript_repair(rig):
    eng = rig
    run_id = new_id()
    async with eng.sf() as s:
        s.add(TipAnalystRun(id=run_id, ticker="TEST", status="running"))
        await s.commit()
    reply = [_Block(type="thinking", thinking="", signature="x"), _Block(type="text", text="no json")]
    client = _Scripted([_Resp(reply)])
    state: dict = {}
    text = await run_agent_loop(eng, client, model="claude-opus-5-5", system="s", header="h",
                                rec=_Recorder(eng, run_id), run_id=run_id, max_tools=4,
                                tool_ctx={}, tools_used=[], state=state)
    assert text == "no json" and state["lastAssistantContent"] is reply
    assert client.calls[0]["output_config"] == {"effort": "high"}          # pinned depth (Opus 5.5 defaults to medium)


def test_the_nonactionable_skip_needs_every_signal_marked_non_actionable():
    assert review_gate.nonactionable([]) is True
    assert review_gate.nonactionable([{"signal": {"isActionable": False}}, {"signal": {"isActionable": False}}]) is True
    assert review_gate.nonactionable([{"signal": {"isActionable": False}}, {"signal": {"isActionable": True}}]) is False
    assert review_gate.nonactionable([{"signal": {"ticker": "X"}}]) is False                 # missing flag keeps the review
    assert review_gate.skip_nonactionable_enabled(_S({})) is False


# ---- batching (nightly digests + knowledge audit) -----------------------------------------------------------------
from zargar.techniques.tip import batching  # noqa: E402


class _Batches:
    def __init__(self, result_type="succeeded", end_after=1):
        self.created, self.cancelled, self._polls, self._end = [], [], 0, end_after
        self.result_type = result_type

    async def create(self, *, requests):
        self.created.append(requests)
        return NS(id="b1", processing_status="in_progress")

    async def retrieve(self, bid):
        self._polls += 1
        return NS(id=bid, processing_status="ended" if self._polls >= self._end else "in_progress")

    async def cancel(self, bid):
        self.cancelled.append(bid)

    async def results(self, bid):
        rt = self.result_type

        async def gen():
            if rt == "succeeded":
                yield NS(result=NS(type="succeeded", message=_Resp([_Block(type="text", text="{}")])))
            else:
                yield NS(result=NS(type="errored", error=NS(message="overloaded")))
        return gen()


class _BatchClient:
    def __init__(self, batches):
        self.messages = NS(batches=batches, create=self._direct)
        self.direct = 0

    async def _direct(self, **kw):
        self.direct += 1
        return _Resp([_Block(type="text", text="{}")])


async def test_batching_off_is_the_direct_call_and_on_submits_one_json_request():
    b = _Batches()
    cl = _BatchClient(b)
    await batching.create(cl, _S({}), model="m", max_tokens=5, messages=[{"role": "user", "content": "h"}])
    assert cl.direct == 1 and not b.created
    on = _S({"techniques.tip.batch_jobs": True, "techniques.tip.batch_timeout_s": 60})
    reply = [_Block(type="thinking", thinking="", signature="s")]
    msg = await batching.create(cl, on, poll_s=0, custom_id="digest", model="m", max_tokens=5,
                                messages=[{"role": "user", "content": "h"}, {"role": "assistant", "content": reply}])
    assert msg.content[0].text == "{}" and cl.direct == 1
    req = b.created[0][0]
    assert req["custom_id"] == "digest" and req["params"]["model"] == "m"
    assert batching.timeout_s(on, 180) == 180 or batching.timeout_s(on, 180) >= 60


async def test_a_batch_that_does_not_end_is_cancelled_and_an_errored_result_raises():
    b = _Batches(end_after=10 ** 6)
    with pytest.raises(TimeoutError):
        await batching.create(_BatchClient(b), _S({"techniques.tip.batch_jobs": True, "techniques.tip.batch_timeout_s": 0.0001}),
                              poll_s=0.001, model="m", max_tokens=5, messages=[])
    assert b.cancelled == ["b1"]
    with pytest.raises(RuntimeError, match="errored"):
        await batching.create(_BatchClient(_Batches(result_type="errored")), _S({"techniques.tip.batch_jobs": True}),
                              poll_s=0, model="m", max_tokens=5, messages=[])


def test_the_cost_report_prices_batched_usage_at_half_the_list_rate():
    from zargar.tools.tip_llm_cost import rollup
    rate = {"m": {"in": 4.0, "out": 20.0, "cacheRead": 0.2, "cacheWrite": 5.0}}
    runs = [{"day": "2026-09-23", "kind": "digest", "model": "m", "usage": {"calls": 1, "in": 1_000_000, "out": 0}},
            {"day": "2026-09-23", "kind": "digest", "model": "m", "usage": {"calls": 1, "in": 1_000_000, "out": 0, "batch": True}}]
    g = {x["model"]: x["usd"] for x in rollup(runs, rate)["groups"]}
    assert g == {"m": 4.0, "m (batch)": 2.0}


def test_the_notes_only_trim_keeps_every_rule_and_proposal_verbatim():
    from zargar.techniques.tip.review_context import compact_review_header
    h = ("MESSAGE:\n$ACHR out\n\nYOUR TRADING RULES (self-maintained):\n- RULE (a): " + "x" * 900 +
         "\nPENDING RULE PROPOSALS - NOT operative policy:\n- RULE (p): " + "y" * 400 +
         "\nSHARED NOTES (desk knowledge):\n- [ticker:ACHR] keep " + "a" * 600 + "\n- [ticker:NVDA] drop\n"
         "RECENT MESSAGES FROM THIS SOURCE (mirror, newest first):\n- x\n")
    out = compact_review_header(h, tickers=["ACHR"], source="ab", notes_only=True)
    assert "x" * 900 in out and "y" * 400 in out
    assert "[ticker:ACHR]" in out and "[ticker:NVDA]" not in out and len(out) < len(h)


def test_an_exit_plan_edit_keeps_every_field_it_did_not_send():
    """2026-09-23 NEM: a stop-only edit blanked the ladder; the analyst paid a second call to restore it."""
    from zargar.techniques.tip.analyst import carried_exit_fields
    pol = {"stop": {"kind": "fixed", "price": 121.19}, "ladder": {"targets": [129.6, 131.0, 133.0], "fractions": [0.25, 0.4, 0.35]},
           "premium_stop_pct": 40.0}
    got = carried_exit_fields(pol, {"underlying_stop": 122.6, "max_hold_sessions": 4})
    assert got == {"targets": [129.6, 131.0, 133.0], "fractions": [0.25, 0.4, 0.35], "underlyingStop": 122.6, "premiumStopPct": 40.0}
    assert carried_exit_fields(pol, {"exit_targets": [], "exit_fractions": []})["targets"] == []      # an explicit clear is honoured
    assert carried_exit_fields({"stop": {"kind": "none"}}, {})["underlyingStop"] is None


def test_the_extraction_prompt_names_position_updates_for_opus_5_5():
    """2026-09-23: Opus 5.5 read "return an empty list" literally and dropped trims/stop-outs; the rule names them."""
    from zargar.signals.schemas import EXTRACTION_SYSTEM_PROMPT as P
    assert "POSITION UPDATES are not empty-list content" in P
    for cue in ('"TP hit"', "stopped out", '"friday calls"', "LEAPS", 'instrument="shares"'):
        assert cue in P



def test_a_full_note_scope_written_by_the_model_is_honoured():
    """EM cross-desk review P2.1: 135 of 701 saves with a full scope were stored as `general`."""
    from zargar.techniques.tip.analyst import note_scope_from_args
    ctx = {"ticker": "", "source": "ab", "signal_id": "s1"}
    assert note_scope_from_args("source:🌟｜common-stock", ctx) == "source:🌟｜common-stock"
    assert note_scope_from_args("ticker:$amzn", ctx) == "ticker:AMZN"
    assert note_scope_from_args("source", ctx) == "source:ab"
    assert note_scope_from_args("tip", ctx) == "signal:s1"
    assert note_scope_from_args("rule", ctx) == "rule"
    assert note_scope_from_args("whatever", ctx) == "general"
    assert note_scope_from_args("ticker:", ctx) == "ticker:"          # no entity -> refused downstream as before


def test_the_extraction_system_prompt_is_a_cached_block_only_when_caching_is_on():
    on = Extractor("k", "m", settings=_S({"techniques.tip.prompt_cache": True}))
    off = Extractor("k", "m", settings=_S({}))
    assert on._system_param("SYS") == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert off._system_param("SYS") == "SYS"
