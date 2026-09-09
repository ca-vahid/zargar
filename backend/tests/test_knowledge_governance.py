"""Codex audit findings 7/9: supplied-vs-used knowledge, scope allocation,
disputed rules + run snapshots, and event-time isolation for experiments."""
import datetime as dt

import pytest

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import DiscordMessage, TipNote
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip.analyst import _rules_text, _run_tool

from .conftest import make_test_config


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def test_scope_allocation_reserves_slots(rig):
    svc = rig.signals_service
    for i in range(12):
        await svc.add_tip_note("general", f"general note {i}")
    await svc.add_tip_note("source:Src", "the source lies about fills")
    await svc.add_tip_note("ticker:NVDA", "NVDA gaps fade by 10:00")
    notes = await svc.notes_for_tip("NVDA", "Src", limit=12)
    scopes = [n["scope"] for n in notes]
    # the noisy general scope can no longer crowd the tip's own context out
    assert "source:Src" in scopes and "ticker:NVDA" in scopes
    assert scopes.count("general") <= 10   # reserved scopes hold their slots


async def test_supplied_is_not_used(rig):
    svc = rig.signals_service
    a = await svc.add_tip_note("ticker:T", "used note")
    b = await svc.add_tip_note("ticker:T", "merely shown note")
    async with rig.sf() as session:
        vu_b_before = (await session.get(TipNote, b["id"])).valid_until
    await svc.refresh_notes_cited([a["id"], b["id"]], used_ids=[a["id"]])
    async with rig.sf() as session:
        ra = await session.get(TipNote, a["id"])
        rb = await session.get(TipNote, b["id"])
    assert ra.cited_count == 1 and ra.supplied_count == 1
    assert rb.cited_count == 0 and rb.supplied_count == 1     # shown ≠ used
    assert rb.valid_until == vu_b_before                       # no TTL promotion
    assert ra.last_cited_at is not None and rb.last_cited_at is None
    # legacy callers (no used_ids) keep the old full promotion
    await svc.refresh_notes_cited([b["id"]])
    async with rig.sf() as session:
        rb2 = await session.get(TipNote, b["id"])
    assert rb2.cited_count == 1


async def test_disputed_rules_are_labeled_and_snapshotted(rig):
    svc = rig.signals_service
    r1 = await svc.add_tip_note("rule", "RULE (alpha family): do the thing.")
    await svc.add_tip_note("rule", "RULE (beta family): do the other thing.")
    await svc.flag_tip_notes([r1["id"]], needs_human=True)
    text, n, snap = await _rules_text(rig)
    assert n == 2 and "[DISPUTED" in text
    assert snap is _rules_text.last_snapshot        # explicit return, mirrored
    assert snap and len(snap["ruleIds"]) == 2 and len(snap["rulesHash"]) == 12
    # the snapshot carries the exact supplied content + flags (Codex K3):
    assert snap["rules"][0]["text"].startswith("RULE (alpha")
    assert snap["rules"][0]["disputed"] is True
    # editing a rule's TEXT in place changes the hash even with the same id
    from zargar.models import TipNote
    async with rig.sf() as session:
        row = await session.get(TipNote, r1["id"])
        row.text = "RULE (alpha family): do the OPPOSITE thing."
        await session.commit()
    _, _, snap2 = await _rules_text(rig)
    assert snap2["rulesHash"] != snap["rulesHash"]


async def test_historical_allowlist_blocks_every_management_tool(rig):
    """Codex K1: historical mode is an ALLOWLIST at dispatch — every tool that
    reads or mutates TODAY's state refuses, not just the six read tools."""
    ctx = {"experiment": "x", "asOfMs": 1750000000000}
    for tool in ("close_position", "update_exit_plan", "disarm_plan",
                 "get_positions", "get_open_tips", "get_quote", "get_chain",
                 "get_expiries", "get_flow", "get_earnings", "get_source_stats"):
        out = await _run_tool(rig, tool, {"symbol": "TEST", "position_id": "p",
                                          "run_id": "r"}, ctx=ctx)
        assert out.get("error") and "historical" in out["error"], (tool, out)


async def test_notes_respect_the_event_time_boundary(rig):
    """Codex K2: knowledge created after the tip's moment never reaches a
    historical run — notes_for_tip and tip_notes take as_of."""
    svc = rig.signals_service
    await svc.add_tip_note("general", "learned long after the event")
    as_of = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
    assert await svc.notes_for_tip("NVDA", "Src", as_of=as_of) == []
    assert await svc.tip_notes(["general"], as_of=as_of) == []
    assert len(await svc.notes_for_tip("NVDA", "Src")) == 1   # live view unchanged


async def test_experiment_search_filters_before_the_limit(rig):
    svc = rig.signals_service
    old_ts = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)
    new_ts = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.timezone.utc)
    async with rig.sf() as session:
        session.add(DiscordMessage(id="old-1", channel_id="c", source_name="S",
                                   text="TICK original open", posted_at=old_ts))
        for i in range(30):                       # newer noise fills any post-filter
            session.add(DiscordMessage(id=f"new-{i}", channel_id="c", source_name="S",
                                       text=f"TICK later chatter {i}", posted_at=new_ts))
        await session.commit()
    as_of = dt.datetime(2026, 6, 2, tzinfo=dt.timezone.utc)
    out = await _run_tool(rig, "search_messages",
                          {"source": "S", "contains": "TICK", "limit": 20},
                          ctx={"experiment": "x", "asOfMs": int(as_of.timestamp() * 1000)})
    msgs = out.get("messages") or []
    assert msgs, out                              # the OLD evidence is found...
    assert all("later chatter" not in m["text"] for m in msgs)   # ...and ONLY it


async def test_experiment_tool_matrix_withholds_current_state(rig):
    ctx = {"experiment": "x", "asOfMs": 1750000000000}
    for tool in ("get_chain", "get_expiries", "get_flow", "get_earnings",
                 "get_positions", "get_open_tips"):
        out = await _run_tool(rig, tool, {"symbol": "T", "expiry": "2026-10-16"}, ctx=ctx)
        assert "historical mode" in (out.get("error") or ""), (tool, out)
