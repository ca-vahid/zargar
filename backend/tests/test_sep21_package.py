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


# ------------------------------------------------------------------ S21-02b checkpoint status (durable owner tooling)
from zargar.tools import tip_checkpoint_status as cps


def _dec(day: str, hour: int = 14, mode: str = "observe") -> dict:
    return {"ts": dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00"), "mode": mode}


def test_incomplete_fifth_day_is_not_ready_and_the_current_day_never_counts():
    days = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]
    decisions = [_dec(d) for d in days] + [_dec("2026-09-25", 15)]          # Friday has decisions but is not complete
    st = cps.compute_status(decisions=decisions, since=dt.date(2026, 9, 21),
                            now=dt.datetime.fromisoformat("2026-09-25T20:00:00+00:00"), need=5, gate_mode="observe")
    assert st["state"] == "NOT-YET" and st["observedSessions"] == 4 and st["until"] == "2026-09-24"
    assert st["partialDayExcluded"] == "2026-09-25" and st["gaps"] == []
    st2 = cps.compute_status(decisions=decisions, since=dt.date(2026, 9, 21),
                             now=dt.datetime.fromisoformat("2026-09-26T09:00:00+00:00"), need=5, gate_mode="observe")
    assert st2["state"] == "READY" and st2["observedSessions"] == 5             # after Friday's 04:00 ET close


def test_a_gap_day_and_a_non_observe_day_are_never_silently_counted(tmp_path):
    decisions = [_dec("2026-09-21"), _dec("2026-09-23"), _dec("2026-09-24"), _dec("2026-09-25"), _dec("2026-09-28")]
    st = cps.compute_status(decisions=decisions, since=dt.date(2026, 9, 21),
                            now=dt.datetime.fromisoformat("2026-09-29T09:00:00+00:00"), need=5, gate_mode="observe")
    assert st["observedSessions"] == 5 and st["gaps"] == ["2026-09-22"]
    final = cps.publish(st, {"scorecard.md": {"exit": 0}}, out_dir=str(tmp_path))
    assert final["state"] == "INCOMPLETE"                                     # five days, but a hole a human must explain
    bad = cps.compute_status(decisions=decisions + [_dec("2026-09-24", 16, mode="enforce")], since=dt.date(2026, 9, 21),
                             now=dt.datetime.fromisoformat("2026-09-29T09:00:00+00:00"), need=5, gate_mode="observe")
    assert bad["state"] == "INVALID" and bad["mixedModeDays"] == ["2026-09-24"]
    assert cps.compute_status(decisions=decisions, since=dt.date(2026, 9, 21), now=dt.datetime.fromisoformat("2026-09-29T09:00:00+00:00"),
                              need=5, gate_mode="enforce")["state"] == "INVALID"


def test_a_failed_report_command_can_never_publish_ready(tmp_path):
    class P:
        def __init__(self, code, out, err=""):
            self.returncode, self.stdout, self.stderr = code, out, err

    def runner(argv, **kw):
        return P(0, "# fine\n") if "tip_scorecard" in " ".join(argv) else P(1, "partial", "Traceback: boom")
    reports = cps.run_reports([("scorecard.md", ["py", "-m", "zargar.tools.tip_scorecard"]),
                               ("review-gate-prospective.md", ["py", "-m", "zargar.tools.tip_review_gate_eval"])],
                              out_dir=str(tmp_path), runner=runner)
    assert reports["scorecard.md"]["exit"] == 0 and reports["review-gate-prospective.md"]["exit"] == 1
    assert (tmp_path / "scorecard.md").exists() and not (tmp_path / "review-gate-prospective.md").exists()
    assert (tmp_path / "review-gate-prospective.md.failed").read_text(encoding="utf-8").startswith("partial")
    st = cps.compute_status(decisions=[_dec(f"2026-09-2{d}") for d in range(1, 6)], since=dt.date(2026, 9, 21),
                            now=dt.datetime.fromisoformat("2026-09-26T09:00:00+00:00"), need=5, gate_mode="observe")
    assert st["state"] == "READY"
    final = cps.publish(st, reports, out_dir=str(tmp_path))
    assert final["state"] == "FAILED" and final["failedReports"] == ["review-gate-prospective.md"]
    import json as _j
    assert _j.loads((tmp_path / "STATUS.json").read_text(encoding="utf-8"))["state"] == "FAILED"


# ------------------------------------------------------------------ S21-03/04 friction and target-to-fill arithmetic
from zargar.techniques.tip import friction as fr


def test_all_in_friction_reproduces_the_achr_case_and_keeps_unknowns_unknown():
    d = fr.all_in_friction(qty=5, fill_price=0.14, multiplier=100, entry_fees=5.20, fee_per_unit=1.04, bid=0.13, ask=0.14)
    assert (d["debit"], d["entryFees"], d["exitFeesEstimate"], d["spreadAtQuote"]) == (70.0, 5.2, 5.2, 5.0)
    assert d["allInDollars"] == 15.4 and d["allInPctOfDebit"] == 22.0 and d["complete"] is True
    u = fr.all_in_friction(qty=5, fill_price=0.14, multiplier=100, entry_fees=5.20, fee_per_unit=1.04, bid=None, ask=None)
    assert u["spreadAtQuote"] is None and u["allInDollars"] == 10.4 and u["complete"] is False and u["unknown"] == ["spread"]


def test_target_to_fill_reproduces_vktx_without_claiming_a_fill():
    t = fr.target_to_fill(target=30.60, fill_price=29.904, qty=17, multiplier=1)
    assert t["shortfallPerUnit"] == pytest.approx(0.696) and t["shortfallDollars"] == pytest.approx(11.83, abs=0.01)
    assert "not evidence" in t["claim"]
    assert fr.target_to_fill(target=None, fill_price=29.9, qty=17, multiplier=1)["unknown"] == ["target"]


def test_same_underlying_exposure_sees_options_and_shares_together():
    lots = [{"symbol": "ACHR270115C00007000", "cost": 144.0}, {"symbol": "ACHR260925C00005500", "cost": 70.0}, {"symbol": "ACHR", "cost": 500.0}]
    e = fr.same_underlying_exposure(lots, underlying="ACHR", exclude_symbol="ACHR260925C00005500")
    assert e["otherLots"] == 2 and e["otherCost"] == 644.0 and e["symbols"] == ["ACHR", "ACHR270115C00007000"]


# ------------------------------------------------------------------ S21-07b coverage classes and the replay event
from zargar.tools import tip_outcomes as to


def test_raw_message_coverage_classes_are_exhaustive_and_honest():
    assert to.classify_coverage({"status": "extracted", "meta": {}}, 2) == "extracted_with_signals"
    assert to.classify_coverage({"status": "extracted", "meta": {}}, 0) == "extracted_no_signal"
    assert to.classify_coverage({"status": "error", "meta": {"recoveryRetried": "x"}}, 0) == "failed"      # a retried failure is still failed
    assert to.classify_coverage({"status": "extracted", "meta": {"recoveryRetried": "x"}}, 1) == "recovered"
    assert to.classify_coverage({"status": "new", "meta": {}}, 0) == "pending"
    assert to.classify_coverage({"status": "ignored", "meta": {}}, 0) == "refused_or_ignored"


def test_replay_event_has_a_contract_and_the_budget_is_two():
    from zargar.research.events_contract import CONTRACTS, validate
    assert to.REPLAY_MAX == 2
    assert set(CONTRACTS["TipIntakeReplayed"]["required"]) == {"contentId", "attempt", "max", "reason"}
    validate("TipIntakeReplayed", {"contentId": "c", "attempt": 2, "max": 2, "reason": "manual"})
