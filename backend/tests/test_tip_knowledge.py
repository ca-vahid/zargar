"""Knowledge lifecycle (KNOWLEDGE plan Phase 3): per-scope TTLs, query-time
expiry, citation refresh, pin, and the widened knowledge audit."""
import datetime as dt

import httpx
import pytest
from sqlalchemy import select

from zargar.api.app import create_app
from zargar.engine import Engine
from zargar.models import TipNote
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config


@pytest.fixture
async def app_client(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    await attach_signal_layer(eng)
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, eng
    await eng.stop()


async def test_ttl_assignment_by_scope(app_client):
    client, eng = app_client
    svc = eng.signals_service
    daily = await svc.add_tip_note("daily:2026-08-30", "today's chatter digest")
    scoped = await svc.add_tip_note("ticker:NVDA", "NVDA gaps fill fast")
    rule = await svc.add_tip_note("rule", "RULE: never chase")
    general = await svc.add_tip_note("general", "desk timezone is ET")
    exp = await svc.add_tip_note("experiment:b1", "batch findings")
    assert daily["validUntil"] and scoped["validUntil"]
    assert rule["validUntil"] is None and general["validUntil"] is None
    assert exp["validUntil"] is None
    d_days = (dt.datetime.fromisoformat(daily["validUntil"])
              - dt.datetime.now(dt.timezone.utc)).days
    s_days = (dt.datetime.fromisoformat(scoped["validUntil"])
              - dt.datetime.now(dt.timezone.utc)).days
    assert 12 <= d_days <= 14 and 88 <= s_days <= 90


async def test_expiry_is_query_time_and_history_shows_it(app_client):
    client, eng = app_client
    svc = eng.signals_service
    note = await svc.add_tip_note("ticker:SPY", "old context")
    # force-expire it
    async with eng.sf() as session:
        row = await session.get(TipNote, note["id"])
        row.valid_until = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
        await session.commit()
    live = await svc.tip_notes(["ticker:SPY"])
    assert note["id"] not in {n["id"] for n in live}          # not injected/listed
    hist = await svc.tip_notes(["ticker:SPY"], include_expired=True)
    assert note["id"] in {n["id"] for n in hist}              # kept as history
    r = await client.get("/api/tip/notes", params={"superseded": "true"})
    assert note["id"] in {n["id"] for n in r.json()}


async def test_citation_refresh_extends_ttl(app_client):
    client, eng = app_client
    svc = eng.signals_service
    note = await svc.add_tip_note("ticker:AAPL", "AAPL respects round numbers")
    async with eng.sf() as session:                            # age it near expiry
        row = await session.get(TipNote, note["id"])
        row.valid_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)
        await session.commit()
    n = await svc.refresh_notes_cited([note["id"]])
    assert n == 1
    async with eng.sf() as session:
        row = await session.get(TipNote, note["id"])
        left = (row.valid_until - dt.datetime.now(dt.timezone.utc)).days
        assert 88 <= left <= 90                                # extended by scope TTL
        assert row.cited_count == 1 and row.last_cited_at is not None


async def test_pin_clears_expiry(app_client):
    client, eng = app_client
    svc = eng.signals_service
    note = await svc.add_tip_note("daily:2026-08-30", "worth keeping")
    r = await client.post(f"/api/tip/notes/{note['id']}/pin")
    assert r.status_code == 200 and r.json()["validUntil"] is None
    async with eng.sf() as session:
        row = await session.get(TipNote, note["id"])
        assert row.valid_until is None


class _FakeDigestClient:
    """Scripted digest judge: one summary + one durable promotion."""

    def __init__(self):
        async def create(**kw):
            return _FakeResp(
                '{"summary": "Room leaned bullish NVDA all day; several exits on SPY.",'
                ' "tickers": ["NVDA", "SPY"],'
                ' "promotions": [{"scope": "ticker:NVDA",'
                ' "text": "room treats 180 as a magnet"},'
                ' {"scope": "rule", "text": "must never land here"}]}')
        self.messages = type("M", (), {"create": staticmethod(create)})()


async def test_digest_channel_writes_daily_note_and_promotes(app_client):
    client, eng = app_client
    from zargar.models import DiscordMessage, TipAnalystRun
    from zargar.techniques.tip.digest import digest_channel

    await eng.signals_service.discord_set_watch([
        {"channelId": "cf", "kind": "channel", "sourceName": "trading-floor",
         "enabled": True, "botsOnly": False, "mode": "context"},
    ])
    now = dt.datetime.now(dt.timezone.utc)
    async with eng.sf() as session:
        for i in range(4):
            session.add(DiscordMessage(id=f"tf{i}", channel_id="cf",
                                       source_name="trading-floor", author=f"user{i}",
                                       text=f"NVDA looking strong {i}", posted_at=now))
        await session.commit()

    out = await digest_channel(eng, "cf", client=_FakeDigestClient())
    assert out is not None and out["verdict"] == "digest"
    svc = eng.signals_service
    daily = await svc.tip_notes([f"daily:{out['date']}"])
    assert len(daily) == 1 and daily[0]["text"].startswith("[trading-floor]")
    assert daily[0]["validUntil"] is not None            # 14d TTL applied
    nvda = await svc.tip_notes(["ticker:NVDA"])
    assert any("magnet" in n["text"] and "trading-floor" in n["text"] for n in nvda)
    # the "rule" promotion was refused — only ticker:/source: scopes allowed
    rules = await svc.tip_notes(["rule"])
    assert not any("must never land here" in n["text"] for n in rules)
    async with eng.sf() as session:
        run = await session.get(TipAnalystRun, out["runId"])
        assert run.kind == "digest" and run.status == "done"


class _FakeResp:
    def __init__(self, text):
        class B:  # noqa: N801 - tiny stub
            type = "text"
        b = B()
        b.text = text
        self.content = [b]


class _FakeAuditClient:
    """Scripted knowledge-audit judge: flags the first two notes of every group
    as a contradiction."""
    class messages:  # noqa: N801
        pass

    def __init__(self):
        self.calls = []

        async def create(**kw):
            self.calls.append(kw)
            import re
            ids = re.findall(r"\[([0-9a-f]{32})\]", kw["messages"][0]["content"])
            return _FakeResp(
                '{"merges": [], "expires": [], "contradictions": '
                f'[{{"ids": ["{ids[0]}", "{ids[1]}"], "why": "opposite"}}], '
                '"summary": "one contradiction"}')
        self.messages = type("M", (), {"create": staticmethod(create)})()


async def test_knowledge_audit_flags_scoped_contradictions(app_client):
    client, eng = app_client
    svc = eng.signals_service
    from zargar.techniques.tip.rule_audit import run_knowledge_audit
    await svc.add_tip_note("ticker:TSLA", "TSLA breakouts follow through")
    await svc.add_tip_note("ticker:TSLA", "TSLA breakouts always fail")
    await svc.add_tip_note("ticker:TSLA", "TSLA loves round numbers")
    await svc.add_tip_note("experiment:b1", "never audited")
    fake = _FakeAuditClient()
    out = await run_knowledge_audit(eng, client=fake)
    assert out is not None and out["groups"] == 1
    assert out["contradictions"] == 2
    import re
    served = re.findall(r"\[([0-9a-f]{32})\]", fake.calls[0]["messages"][0]["content"])
    notes = await svc.tip_notes(["ticker:TSLA"])
    flagged = {n["id"] for n in notes if n["needsHuman"]}
    assert flagged == set(served[:2])      # exactly what the judge flagged
    assert "experiment:b1" not in fake.calls[0]["messages"][0]["content"]
