"""Knowledge pagination (2026-09-16): category filters apply on the SERVER before
pagination, `total` is the filtered total, and the per-category / Needs-you counts
are GLOBAL - so an older rule or a flagged note beyond the first 200 rows is still
reachable and still counted. The analyst's own context limits are untouched."""
import datetime as dt

import httpx
import pytest
from sqlalchemy import select, update

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


async def _seed(eng, *, newer: int = 230):
    """OLD rules (5, two of them flagged) and OLD flagged ticker notes (3) dated
    weeks ago, buried under `newer` fresh ticker/source notes - all beyond page 200
    in newest-first order."""
    svc = eng.signals_service
    old_ids = {"rule": [], "flagged": []}
    for i in range(5):
        r = await svc.add_tip_note("rule", f"RULE (old family {i}): an older rule that still rides on every run.", family_dedupe=False)
        old_ids["rule"].append(r["id"])
    for i in range(3):
        n = await svc.add_tip_note(f"ticker:OLD{i}", f"OLD{i}: an old ticker note the audit flagged.")
        old_ids["flagged"].append(n["id"])
    await svc.flag_tip_notes(old_ids["flagged"] + old_ids["rule"][:2], needs_human=True)
    old_ids["flagged"] += old_ids["rule"][:2]
    for i in range(newer):
        scope = f"ticker:N{i % 40}" if i % 3 else f"source:src{i % 7}"
        await svc.add_tip_note(scope, f"fresh note {i}")
    # push the old rows weeks back and pin them (no TTL expiry) so ORDER, not expiry, hides them
    async with eng.sf() as session:
        await session.execute(update(TipNote).where(TipNote.id.in_(old_ids["rule"] + old_ids["flagged"]))
                              .values(created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40), valid_until=None))
        await session.commit()
    return old_ids


async def test_category_filters_before_pagination_and_counts_are_global(app_client):
    client, eng = app_client
    old = await _seed(eng)
    svc = eng.signals_service
    page = await svc.search_tip_notes("", None, offset=0, limit=200, category="all")
    assert page["limit"] == 200 and len(page["items"]) == 200 and page["total"] == 238   # 230 + 5 rules + 3 old ticker notes
    ids_page1 = {n["id"] for n in page["items"]}
    assert not (ids_page1 & set(old["rule"]))                                          # the old rules are beyond page 1 of "all"
    # the category button counts are GLOBAL - not the 200 loaded rows
    assert page["counts"]["rule"] == 5 and page["counts"]["flagged"] == 5
    assert page["counts"]["ticker"] == 3 + sum(1 for i in range(230) if i % 3) and page["counts"]["all"] == 238
    # the rule category is filtered on the server BEFORE pagination: page 1 holds every rule
    rules = await svc.search_tip_notes("", None, offset=0, limit=200, category="rule")
    assert rules["total"] == 5 and {n["id"] for n in rules["items"]} == set(old["rule"])
    assert all(n["scope"] == "rule" for n in rules["items"])
    # flagged notes beyond row 200 are reachable through their category, total = filtered total
    flagged = await svc.search_tip_notes("", None, offset=0, limit=200, category="flagged")
    assert flagged["total"] == 5 and {n["id"] for n in flagged["items"]} == set(old["flagged"])
    assert all(n["needsHuman"] for n in flagged["items"])
    # pagination inside a category: offset walks the FILTERED set
    t1 = await svc.search_tip_notes("", None, offset=0, limit=100, category="ticker")
    t2 = await svc.search_tip_notes("", None, offset=100, limit=100, category="ticker")
    assert t1["total"] == t2["total"] == page["counts"]["ticker"]
    assert len(t1["items"]) == 100 and 1 <= len(t2["items"]) <= 100
    assert not ({n["id"] for n in t1["items"]} & {n["id"] for n in t2["items"]})
    # search narrows the base filter for BOTH the total and the counts
    s = await svc.search_tip_notes("old family", None, offset=0, limit=50, category="all")
    assert s["total"] == 5 and s["counts"]["rule"] == 5 and s["counts"]["ticker"] == 0
    with pytest.raises(ValueError):
        await svc.search_tip_notes("", None, category="bogus")


async def test_api_returns_filtered_total_loaded_page_and_global_counts(app_client):
    client, eng = app_client
    old = await _seed(eng, newer=210)
    r = await client.get("/api/tip/notes/search?q=&offset=0&limit=200&category=all")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 218 and len(body["items"]) == 200 and body["category"] == "all"
    assert body["counts"]["flagged"] == 5 and body["counts"]["rule"] == 5
    assert "global" in body["countsScope"]
    r2 = await client.get("/api/tip/notes/search?category=rule&offset=0&limit=200")
    assert r2.status_code == 200 and r2.json()["total"] == 5
    assert {n["id"] for n in r2.json()["items"]} == set(old["rule"])
    r3 = await client.get("/api/tip/notes/search?category=flagged&offset=0&limit=200")
    assert r3.json()["total"] == 5 and all(n["needsHuman"] for n in r3.json()["items"])
    bad = await client.get("/api/tip/notes/search?category=nope")
    assert bad.status_code == 400


async def test_all_hides_experiments_unless_history_or_search_and_totals_agree(app_client):
    client, eng = app_client
    svc = eng.signals_service
    await svc.add_tip_note("general", "a durable general note")
    await svc.add_tip_note("experiment:b1", "batch review artifact - never injected")
    a = await svc.search_tip_notes("", None, category="all")
    assert a["total"] == 1 and a["counts"]["all"] == 1 and a["counts"]["experiment"] == 1
    assert all(not n["scope"].startswith("experiment:") for n in a["items"])
    h = await svc.search_tip_notes("", None, category="all", include_history=True)
    assert h["total"] == 2 and h["counts"]["all"] == 2
    q = await svc.search_tip_notes("batch review", None, category="all")
    assert q["total"] == 1 and q["items"][0]["scope"] == "experiment:b1"
    e = await svc.search_tip_notes("", None, category="experiment")
    assert e["total"] == 1


async def test_analyst_context_limits_are_not_widened(app_client):
    """The fix is presentation + server-side filtering; the analyst's own supply
    limits (notes_for_tip / rulebook) are not a pagination workaround."""
    client, eng = app_client
    svc = eng.signals_service
    for i in range(60):
        await svc.add_tip_note("ticker:AMZN", f"AMZN note {i}")
    supplied = await svc.notes_for_tip("AMZN", "src", limit=50)
    assert len(supplied) <= 50
