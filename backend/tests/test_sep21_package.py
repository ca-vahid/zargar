"""2026-09-21 review package - the desk's own controls beside the reviewer's four regressions
(tests/test_sep21_economics_review.py): S21-01 put + missing-metadata controls, S21-07 digest bounded repair."""
import asyncio
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from zargar.approvals.proposals import ProposalService, _contract_metadata
from zargar.models import DiscordMessage
from zargar.techniques.tip import digest, execcost, geometry

from .conftest import wait_for
from .test_tip_analyst_loop import _Block, _Resp, _Scripted, rig  # noqa: F401 - fixture re-export
from .test_tip_retro_digest_accounting import _DIGEST_JSON, _Hanging, _notes_by_run, _only_run, _seed_channel


# ------------------------------------------------------------------ S21-01 controls
async def _card(monkeypatch, *, vehicle: dict, symbol: str, limit: float, targets: list[float]):
    from zargar.clock import now_ms
    now = now_ms()
    q = NS(last=5.0, bid=limit - .01, ask=limit, source="opra", source_ts=now, ts=now, delayed=False)
    eng = NS(settings={"options.fee_per_contract": .99, "sim.reg_fee_per_contract": .05},
             ensure_symbol=AsyncMock(), quotes=NS(get=lambda s: q),
             positions=NS(equity=AsyncMock(return_value=9000)), feed=type("SimQuoteFeed", (), {})(),
             options=NS(snapshot_cached=lambda s: {"greeks": {"delta": -.3}, "asOf": now, "greeksLive": True}))
    plan = {"targets": targets, "fractions": [1.0], "maxHoldSessions": 2}
    rp = NS(qty=3, unitLoss=20., reviewRequired=None, reviewClass=None)
    monkeypatch.setattr(geometry, "plan_risk", lambda **kw: (plan, rp))
    monkeypatch.setattr(execcost, "diagnose", lambda *a, **k: {"status": "known"})
    await ProposalService._compute_risk_plan(NS(engine=eng), mode="enforce", underlying="ACHR", direction="short", pid="p",
                                             exit_plan=plan, vehicle=vehicle, sec_type="OPT", symbol=symbol, limit=limit,
                                             qty=3, entry_hint=5.)
    return rp.payoff


async def test_a_put_card_prints_its_own_break_even_below_the_strike(monkeypatch):
    """The vehicle omits strike/expiry (today's live cards): the OCC symbol is DECODED, never guessed."""
    p = await _card(monkeypatch, vehicle={"multiplier": 100, "optionType": "put"}, symbol="ACHR260925P00005500",
                    limit=.20, targets=[4.5])
    assert p["feePerUnit"] == pytest.approx(1.04)
    assert p["breakEven"]["expiration"] == pytest.approx(5.30)                 # strike 5.5 - premium 0.20
    assert p["horizon"]["expiryDate"] == "2026-09-25" and p["horizon"]["maxHoldSessions"] == 2
    assert p["contractMetadata"] == {"source": "occ", "strike": 5.5, "expiry": "2026-09-25", "optionType": "put"}
    assert "AT the target price" in p["targetExecution"]                       # S21-03: the assumption is on the card


async def test_missing_contract_metadata_stays_missing(monkeypatch):
    """A symbol that is not an OCC contract and a vehicle without strike/expiry: no break-even is invented."""
    p = await _card(monkeypatch, vehicle={"multiplier": 100, "optionType": "call"}, symbol="NOT-AN-OCC", limit=.20, targets=[6.0])
    assert p["feePerUnit"] == pytest.approx(1.04)
    assert p["breakEven"].get("expiration") is None
    assert p["horizon"]["expiryDate"] is None
    assert p["contractMetadata"]["source"] is None and p["contractMetadata"]["strike"] is None


def test_contract_metadata_prefers_the_vehicle_and_decodes_otherwise():
    assert _contract_metadata({"strike": 14, "expiry": "2026-10-16", "optionType": "call"}, "AAL261016C00014000")["source"] == "vehicle"
    m = _contract_metadata({}, "AAL261016C00014000")
    assert (m["source"], m["strike"], m["expiry"], m["optionType"]) == ("occ", 14.0, "2026-10-16", "call")
    assert _contract_metadata(None, None)["strike"] is None


# ------------------------------------------------------------------ S21-07 digest bounded repair
class _Rec(_Scripted):
    """Scripted responses that also record each request's output cap."""

    async def create(self, **kw):
        self.__dict__.setdefault("max_tokens_seen", []).append(int(kw.get("max_tokens") or 0))
        return await super().create(**kw)


async def test_digest_truncation_then_repair_succeeds_with_both_attempts_on_record(rig):
    eng = rig
    await _seed_channel(eng)
    client = _Rec([_Resp([_Block(type="text", text='{"summary": "Room leaned bullish NV')], stop="max_tokens", usage=(400, 2000)),
                   _Resp([_Block(type="text", text=_DIGEST_JSON)], usage=(450, 90))])
    out = await digest.digest_channel(eng, "cf", client=client)
    assert out["verdict"] == "digest" and len(out["promoted"]) == 2
    usage = out["usage"]
    assert usage["calls"] == 2 and usage["stops"] == ["max_tokens", "end_turn"] and usage["in"] == 850
    repair_req = client.requests[1]
    assert repair_req[1]["role"] == "assistant" and repair_req[1]["content"].startswith('{"summary"')   # same transcript
    assert "ONLY the complete JSON" in repair_req[2]["content"]
    assert client_max_tokens(client) == [2000, 4000]                        # only the repair turn got more room
    assert len(await _notes_by_run(eng, out["runId"])) == 3                # written ONCE, after the repair
    row = await _only_run(eng, "digest")
    assert row.opinion["failure"]["kind"] == "truncation" and row.opinion["failure"]["repaired"] is True


async def test_digest_terminal_truncation_is_typed_and_writes_nothing(rig):
    eng = rig
    await _seed_channel(eng)
    client = _Scripted([_Resp([_Block(type="text", text="the room was busy")], stop="max_tokens", usage=(400, 2000)),
                        _Resp([_Block(type="text", text='{"summary": "still cut')], stop="max_tokens", usage=(420, 4000))])
    with pytest.raises(ValueError, match="repair attempt was also truncated"):
        await digest.digest_channel(eng, "cf", client=client)
    row = await _only_run(eng, "digest")
    assert row.status == "failed" and "max_tokens" in row.error
    assert row.opinion["usage"]["calls"] == 2 and row.opinion["usage"]["stops"] == ["max_tokens", "max_tokens"]
    assert row.opinion["failure"] == {**row.opinion["failure"], "kind": "truncation", "repairAttempted": True, "repair": "truncated again"}
    assert row.opinion["noteId"] is None and "receipts" not in row.opinion
    assert await _notes_by_run(eng, row.id) == []


async def test_digest_cancelled_during_the_repair_keeps_the_first_attempt(rig):
    eng = rig
    await _seed_channel(eng)
    client = _Hanging([_Resp([_Block(type="text", text="no json here")], stop="max_tokens", usage=(300, 2000))])
    task = asyncio.create_task(digest.digest_channel(eng, "cf", client=client))
    await wait_for(lambda: len(client.requests) == 2)          # the repair is in flight
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = await _only_run(eng, "digest")
    assert row.status == "failed" and row.error.startswith("cancelled")
    assert row.opinion["usage"]["calls"] == 1 and row.opinion["usage"]["perCall"][-1]["error"] == "cancelled"
    assert row.opinion["failure"]["repairAttempted"] is True and "repaired" not in row.opinion["failure"]
    assert await _notes_by_run(eng, row.id) == []


def client_max_tokens(client) -> list[int]:
    return list(getattr(client, "max_tokens_seen", []))
