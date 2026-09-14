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


async def test_remove_shadow_book_only(app_client):
    """Demo/test shadow books are deletable (user 2026-08-30); sim/paper/live
    portfolios are NOT — the guard refuses them."""
    client, eng = app_client
    from zargar.models import Portfolio as PortfolioRow
    shadow = await eng.signals_service.shadow_portfolio("DemoSrc", "immediate")
    pid = shadow["id"]
    r = await client.delete(f"/api/portfolios/{pid}")
    assert r.status_code == 200 and r.json()["ok"]
    assert eng.positions.portfolio(pid) is None
    async with eng.sf() as session:
        assert await session.get(PortfolioRow, pid) is None

    sim = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")
    r2 = await client.delete(f"/api/portfolios/{sim['id']}")
    assert r2.status_code == 400
    assert eng.positions.portfolio(sim["id"]) is not None


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


async def test_evidence_scope_is_never_injected(app_client):
    """`evidence:<family>` notes are reachable on demand (search) but never
    supplied to a run — not by notes_for_tip and not by the rulebook."""
    client, eng = app_client
    svc = eng.signals_service
    n = await svc.add_tip_note("evidence:adoption-geometry", "AMZN 9/07 case: the handed stop was 0.2% wide (cites dbfd8177).")
    assert n["scope"] == "evidence:adoption-geometry"
    supplied = await svc.notes_for_tip("AMZN", "MuggZone", limit=50)
    assert all(x["id"] != n["id"] for x in supplied)
    from zargar.techniques.tip.analyst import _rules_text
    text, count, snap = await _rules_text(eng)
    assert n["id"] not in (snap or {}).get("revisionNos", {}) and "AMZN 9/07 case" not in text
    found = await svc.search_tip_notes("AMZN 9/07", None, offset=0, limit=10)
    assert any(x["id"] == n["id"] for x in found["items"])


async def test_reviewed_consolidation_applies_through_audited_paths(app_client):
    """The reviewed batches: disputes resolved deliberately, family + kill-switch
    merges via apply_knowledge_batch(mode=apply) with receipts and revision
    checks, evidence records in the never-injected scope; a replay is idempotent
    and a stale revision refuses."""
    from zargar.models import TipKnowledgeBatch, TipNote
    from zargar.techniques.tip.consolidation import apply_consolidation
    client, eng = app_client
    svc = eng.signals_service
    await eng.settings.set("techniques.tip.knowledge_apply_enabled", False, journal=False)   # routine stays propose-only
    base = await svc.add_tip_note("rule", "RULE (adoption geometry — base): five checks; one fast stop pauses the session.")
    ref1 = await svc.add_tip_note("rule", "RULE (adoption geometry — case 5): pre-adoption arithmetic gate.", family_dedupe=False)
    ks = await svc.add_tip_note("rule", "RULE (session kill-switch — geometry, not the clock): only a stop below the floor pauses.", family_dedupe=False)
    other = await svc.add_tip_note("rule", "RULE (lotto tape filter): unrelated family.")
    await svc.flag_tip_notes([base["id"], ks["id"]], needs_human=True)
    async with eng.sf() as session:
        revs = {r.id: r.revision_no for r in (await session.execute(select(TipNote))).scalars().all()}
    family = {"batchId": "consolidation-geometry-test", "scope": "rule",
              "merge": {"supersedes": [base["id"], ref1["id"]], "new_rule": "RULE (adoption geometry — canonical family): the five checks, consolidated."},
              "expected_revisions": {base["id"]: revs[base["id"]], ref1["id"]: revs[ref1["id"]]}, "author": "consolidation:test"}
    kill = {"batchId": "consolidation-killswitch-test", "scope": "rule",
            "merge": {"supersedes": [ks["id"]], "new_rule": "RULE (session kill-switch — execution-integrity pause): incidents, not clocks."},
            "expected_revisions": {ks["id"]: revs[ks["id"]]}, "author": "consolidation:test"}
    evidence = [{"scope": "evidence:adoption-geometry", "sourceId": ref1["id"], "sourceRevision": revs[ref1["id"]],
                 "text": f"[EVIDENCE — cites rule {ref1['id']}] the case-5 arithmetic gate record."}]
    out = await apply_consolidation(eng, manifest_hash="abc123", resolve=[base["id"], ks["id"]],
                                    family=family, kill_switch=kill, evidence=evidence)
    assert set(out["resolved"]) == {base["id"], ks["id"]}
    assert out["batches"]["family"]["merged"] == 2 and out["batches"]["killSwitch"]["merged"] == 1
    assert len(out["evidence"]) == 1 and out["evidence"][0].get("id")
    async with eng.sf() as session:
        b = await session.get(TipNote, base["id"]); r1 = await session.get(TipNote, ref1["id"])
        k = await session.get(TipNote, ks["id"]); o = await session.get(TipNote, other["id"])
        fam_id = out["batches"]["family"]["newRules"][0]
        fam = await session.get(TipNote, fam_id)
        rec = await session.get(TipKnowledgeBatch, "consolidation-geometry-test")
    assert b.superseded_by == fam_id and r1.superseded_by == fam_id and not b.needs_human
    assert k.superseded_by == out["batches"]["killSwitch"]["newRules"][0] and o.superseded_by is None
    assert fam.scope == "rule" and fam.superseded_by is None and rec.status == "applied"
    live_rules = await svc.tip_notes(["rule"], limit=50)
    assert {n["id"] for n in live_rules} == {fam_id, out["batches"]["killSwitch"]["newRules"][0], other["id"]}
    supplied = await svc.notes_for_tip("AAPL", "Src", limit=50)
    assert all(not n["scope"].startswith("evidence:") for n in supplied)
    # replay: idempotent (receipts), nothing merged twice, evidence not duplicated
    again = await apply_consolidation(eng, manifest_hash="abc123", resolve=[], family=family, kill_switch=kill, evidence=evidence)
    assert again["batches"]["family"].get("alreadyApplied") and again["evidence"][0].get("existing")
    # a stale manifest revision on a fresh batch id refuses (whole batch)
    stale = {**family, "batchId": "consolidation-geometry-stale", "merge": {"supersedes": [other["id"]], "new_rule": "x"},
             "expected_revisions": {other["id"]: 99}}
    with pytest.raises(ValueError, match="revision"):
        await apply_consolidation(eng, manifest_hash="stale", resolve=[], family=stale, kill_switch={}, evidence=[])
    # the API route exists and refuses the same way
    r = await client.post("/api/tip/knowledge/consolidate", json={"manifestHash": "stale", "family": stale})
    assert r.status_code == 409
