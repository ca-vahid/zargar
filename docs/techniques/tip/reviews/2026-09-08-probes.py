"""Offline audit probes: real functions, fake I/O; no database, network or LLM calls.

Run from repository root: backend/.venv/Scripts/python.exe docs/techniques/tip/reviews/2026-09-08-probes.py
These assertions reproduce existing shortcomings; they are not acceptance tests.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))
from zargar.signals.extraction import Extractor
from zargar.signals.service import SignalService
from zargar.signals.schemas import TradeSignal
from zargar.signals.verification import verify_signal
from zargar.techniques.tip import analyst, retro
from zargar.tools.discord_gateway import Gateway, OP_DISPATCH


async def main():
    findings = []
    logging.disable(logging.CRITICAL)
    malformed = NS(content=[NS(type="text", text="not JSON")], stop_reason="end_turn")
    extractor = Extractor("offline-placeholder", "offline-model")
    extractor._client = NS(messages=NS(create=AsyncMock(return_value=malformed)))
    result = await extractor.extract("Buy EXAMPLE shares")
    assert extractor._client.messages.create.await_count == 2 and result.signals == []
    findings.append("Two malformed extraction responses return an ordinary empty signal result.")

    tool_request = NS(content=[NS(type="tool_use", name="get_quote", id="call", input={"symbol": "EXAMPLE"})])
    client = NS(messages=NS(create=AsyncMock(return_value=tool_request)))
    recorder = NS(step=lambda *a, **kw: None)
    with patch.object(analyst, "_persist_run", AsyncMock()), patch.object(analyst, "_run_tool", AsyncMock()) as tool:
        result = await analyst.run_agent_loop(
            NS(), client, model="offline", system="system", header="original header",
            rec=recorder, run_id="probe", max_tools=2, tool_ctx={},
            tools_used=[{"tool": "get_quote"}] * 4)
        assert result == "" and tool.await_count == 0
        assert len(client.messages.create.call_args.kwargs["messages"]) == 1
    findings.append("Repair-loop shape with four prior tools and max_tools=2 drops a requested tool and returns empty text; prior evidence is absent.")

    service = object.__new__(SignalService)
    service.tip_notes = AsyncMock(return_value=[])
    await service.notes_for_tip("EXAMPLE", "source-a", "signal-a")
    scopes = service.tip_notes.call_args.args[0]
    assert not any(s.startswith("daily:") for s in scopes)
    findings.append("Default note retrieval includes general/ticker/source/signal scopes but no daily digest.")

    chain = {"spot": 100, "rows": [{"strike": k} for k in range(80, 201, 5)]}
    compact = analyst._compact_chain(chain)
    assert 200 not in [r["strike"] for r in compact["strikes"]]
    findings.append("Default compact chain omits a named 200 strike when spot is 100; tool uses default centering.")

    signal = TradeSignal.model_construct(ticker="CRWV", direction="long", action="open",
        is_actionable=True, confidence="explicit_call", instrument="call",
        premium=1.40, target_price=1.75, stop_price=0.90)
    quote = NS(last=98.87, bid=98.79, ask=98.86, halted=False, spread_pct=0.071)
    verified = await verify_signal(signal, NS(get=lambda symbol: quote), {})
    target_check = next(c for c in verified["checks"] if c["name"] == "not_past_target")
    assert verified["park"] and not target_check["passed"]
    assert "98.87" in target_check["detail"] and "1.75" in target_check["detail"]
    findings.append("Option-premium target 1.75 is compared with underlying 98.87, incorrectly producing past-target parking.")

    gateway = object.__new__(Gateway)
    gateway._on_message = AsyncMock()
    await gateway._on_frame({"op": OP_DISPATCH, "t": "MESSAGE_UPDATE", "s": 1,
                             "d": {"id": "message-a", "content": "corrected stop"}}, None, {})
    assert gateway._on_message.await_count == 0
    findings.append("Discord MESSAGE_UPDATE is ignored.")

    http = NS(post=AsyncMock(return_value=NS(status_code=200, json=lambda: {"signals": []})))
    gateway.api = "http://offline.invalid"
    await gateway._ingest_message(http, {}, {"id": "message-a", "channel_id": "channel-a",
                                            "timestamp": "2026-09-08T14:00:00Z",
                                            "content": "Buy EXAMPLE", "author": {"username": "sample"}}, "source-a")
    payload = http.post.call_args.kwargs["json"]
    assert not any(k in payload for k in ("messageId", "discordMessageId", "statedAt", "stated_at"))
    findings.append("Gateway manual-intake payload omits Discord message identity and original timestamp.")

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def execute(self, query):
            # Respect the actual SQL LIMIT against 51 closed positions.
            assert "retro-done" not in str(query)
            rows = [NS(id=str(i), symbol="EXAMPLE", tags=["retro-done"] if i < 50 else [],
                       config={}, state={}, legs=[]) for i in range(51)]
            limited = rows[:query._limit_clause.value]
            return NS(scalars=lambda: NS(all=lambda: limited))
    eng = NS(settings={}, sf=Session)
    with patch.object(retro, "retro_position", AsyncMock()) as review:
        result = await retro.run_tip_retros(eng)
        assert review.await_count == 0 and result["pending"] == 0
    findings.append("With 50 oldest positions already reviewed, position 51 is never selected and pending reports zero.")
    print(json.dumps({"reproduced": len(findings), "findings": findings}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
