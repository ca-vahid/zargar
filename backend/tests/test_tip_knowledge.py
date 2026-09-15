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
    from zargar.techniques.tip.consolidation import payload_hash
    resolve = [{"id": base["id"], "revision": revs[base["id"]]}, {"id": ks["id"], "revision": revs[ks["id"]]}]
    h = payload_hash(resolve=resolve, batches=[family, kill], evidence=evidence)
    out = await apply_consolidation(eng, manifest_hash=h, resolve=resolve,
                                    family=family, kill_switch=kill, evidence=evidence)
    assert {t["id"] for t in out["resolved"]} == {base["id"], ks["id"]}
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
    again = await apply_consolidation(eng, manifest_hash=h, resolve=resolve, family=family, kill_switch=kill, evidence=evidence)
    assert again.get("replay") is True and again["batches"]["family"]["merged"] == 2
    # a stale manifest revision on a fresh batch id refuses (whole batch)
    stale = {**family, "batchId": "consolidation-geometry-stale", "merge": {"supersedes": [other["id"]], "new_rule": "x"},
             "expected_revisions": {other["id"]: 99}}
    hs = payload_hash(resolve=[], batches=[stale], evidence=[])
    with pytest.raises(ValueError, match="revision"):
        await apply_consolidation(eng, manifest_hash=hs, resolve=[], family=stale, kill_switch={}, evidence=[])
    # the API route exists and refuses the same way
    r = await client.post("/api/tip/knowledge/consolidate", json={"manifestHash": hs, "family": stale})
    assert r.status_code == 409

async def test_consolidation_payload_integrity_kfin05(app_client):
    """KFIN-05: one canonical payload hash; every reviewed revision validated
    before ANY mutation (including releases); changed text under the same hash,
    a stale revision during resolution, a changed payload under an applied batch
    id and a changed evidence revision are refused with nothing written; an
    identical replay is idempotent; the receipt carries the actual transitions."""
    from zargar.models import TipKnowledgeBatch, TipNote
    from zargar.techniques.tip.consolidation import apply_consolidation, payload_hash, rollback_plan
    client, eng = app_client
    svc = eng.signals_service
    await eng.settings.set("techniques.tip.knowledge_apply_enabled", False, journal=False)
    a = await svc.add_tip_note("rule", "RULE (widget family — base): one.")
    b = await svc.add_tip_note("rule", "RULE (widget family — case): two.", family_dedupe=False)
    c = await svc.add_tip_note("rule", "RULE (other): untouched.")
    await svc.flag_tip_notes([a["id"]], needs_human=True)
    async with eng.sf() as session:
        revs = {r.id: r.revision_no for r in (await session.execute(select(TipNote))).scalars().all()}
    resolve = [{"id": a["id"], "revision": revs[a["id"]]}]
    fam = {"batchId": "kfin05-family", "scope": "rule",
           "merge": {"supersedes": [a["id"], b["id"]], "new_rule": "RULE (widget family — canonical): one and two."},
           "expected_revisions": {a["id"]: revs[a["id"]], b["id"]: revs[b["id"]]}, "author": "consolidation:test"}
    evd = [{"scope": "evidence:widget", "sourceId": b["id"], "sourceRevision": revs[b["id"]], "text": "case two record"}]
    good = payload_hash(resolve=resolve, batches=[fam], evidence=evd)

    async def snapshot():
        async with eng.sf() as session:
            rows = {r.id: (r.revision_no, r.needs_human, r.superseded_by) for r in (await session.execute(select(TipNote))).scalars().all()}
            n_batches = len((await session.execute(select(TipKnowledgeBatch))).scalars().all())
        return rows, n_batches
    before = await snapshot()
    # (1) changed text under the same claimed hash -> refused, nothing written (not even the release)
    tampered = {**fam, "merge": {**fam["merge"], "new_rule": "RULE (widget family — canonical): one and TWO."}}
    with pytest.raises(ValueError, match="identity mismatch"):
        await apply_consolidation(eng, manifest_hash=good, resolve=resolve, family=tampered, evidence=evd)
    assert await snapshot() == before
    # (2) stale revision during dispute resolution -> refused before any mutation
    stale_resolve = [{"id": a["id"], "revision": revs[a["id"]] + 5}]
    h2 = payload_hash(resolve=stale_resolve, batches=[fam], evidence=evd)
    with pytest.raises(ValueError, match="refused before any mutation"):
        await apply_consolidation(eng, manifest_hash=h2, resolve=stale_resolve, family=fam, evidence=evd)
    assert await snapshot() == before, "a stale reviewed revision left the dispute and the sources untouched"
    # (3) changed evidence revision -> refused, nothing written
    evd_bad = [{**evd[0], "sourceRevision": revs[b["id"]] + 3}]
    h3 = payload_hash(resolve=resolve, batches=[fam], evidence=evd_bad)
    with pytest.raises(ValueError, match="evidence for"):
        await apply_consolidation(eng, manifest_hash=h3, resolve=resolve, family=fam, evidence=evd_bad)
    assert await snapshot() == before
    # (4) the good payload applies: release + merge + evidence, receipt with transitions
    out = await apply_consolidation(eng, manifest_hash=good, resolve=resolve, family=fam, evidence=evd)
    assert out["resolved"][0]["id"] == a["id"] and out["resolved"][0]["revisionTo"] == out["resolved"][0]["revisionFrom"] + 1
    fam_out = out["batches"]["family"]
    assert fam_out["merged"] == 2 and fam_out["newRuleId"] and {s["id"] for s in fam_out["superseded"]} == {a["id"], b["id"]}
    assert out["evidence"][0]["id"] and "cites rule" in out["evidence"][0]["marker"]
    plan = rollback_plan(out)
    assert {p["step"] for p in plan} >= {"re-dispute", "restore-superseded", "expire-new-rule", "keep"}
    async with eng.sf() as session:
        rec = await session.get(TipKnowledgeBatch, f"consolidation:{good}")
        brec = await session.get(TipKnowledgeBatch, "kfin05-family")
    assert rec.status == "applied" and rec.applied["rollbackPlan"] and brec.applied.get("consolidationIdentity")
    # (5) identical replay is idempotent — the recorded receipt comes back, nothing new written
    after = await snapshot()
    again = await apply_consolidation(eng, manifest_hash=good, resolve=resolve, family=fam, evidence=evd)
    assert again.get("replay") is True and again["batches"]["family"]["newRuleId"] == fam_out["newRuleId"]
    assert await snapshot() == after
    # (6) a DIFFERENT payload under the already-applied batch id -> refused, nothing written
    other = {**fam, "merge": {"supersedes": [c["id"]], "new_rule": "RULE (other): rewritten."},
             "expected_revisions": {c["id"]: revs[c["id"]]}}
    h6 = payload_hash(resolve=[], batches=[other], evidence=[])
    with pytest.raises(ValueError, match="DIFFERENT payload"):
        await apply_consolidation(eng, manifest_hash=h6, resolve=[], family=other, evidence=[])
    assert await snapshot() == after
    # the API refuses the same way (409) and still applies nothing
    r = await client.post("/api/tip/knowledge/consolidate", json={"manifestHash": good, "family": tampered, "resolve": resolve, "evidence": evd})
    assert r.status_code == 409 and await snapshot() == after
    # (7) an expire batch (reviewed rejection) works through the same wrapper with its own receipt
    d = await svc.add_tip_note("rule", "RULE (proposal to reject): hypothetical.", family_dedupe=False)
    async with eng.sf() as session:
        drev = await session.scalar(select(TipNote.revision_no).where(TipNote.id == d["id"]))
    rej = {"batchId": "kfin05-reject", "scope": "rule", "expire": {"ids": [d["id"]], "reason": "reviewed rejection: hypothesis, not policy"},
           "expected_revisions": {d["id"]: drev}, "author": "consolidation:test"}
    h7 = payload_hash(resolve=[], batches=[rej], evidence=[])
    out7 = await apply_consolidation(eng, manifest_hash=h7, batches=[rej])
    assert out7["batches"]["kfin05-reject"]["kind"] == "expire" and out7["batches"]["kfin05-reject"]["expired"][0]["id"] == d["id"]
    live = {n["id"] for n in await svc.tip_notes(["rule"], limit=100)}
    assert d["id"] not in live and c["id"] in live
