"""The phone's Now payload: GET /api/technique/armed/summary shape + slim list."""
import httpx
import pytest

from zargar.api.app import create_app
from zargar.engine import Engine
from zargar.technique.service import attach_technique_layer

from .conftest import make_test_config


@pytest.fixture
async def app_client(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    await attach_technique_layer(eng)
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, eng
    if eng.technique is not None:
        await eng.technique.stop()
    await eng.stop()


async def test_summary_shape_when_nothing_armed(app_client):
    client, eng = app_client
    r = await client.get("/api/technique/armed/summary")
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("asOf", "window", "windowOpenNow", "haltEngaged", "workspace", "counts",
                "attention", "inTrade", "timeline", "watching", "stoppedToday", "pnl"):
        assert key in d, key
    assert d["counts"]["armed"] == 0 and d["counts"]["stoppedToday"] == 0
    assert d["pnl"] == {"realized": 0.0, "unrealized": 0.0, "lossLimit": 0.0, "lossLimitUsedPct": None}
    assert d["workspace"] == "practice" and d["haltEngaged"] is False


async def test_slim_list_drops_events(app_client):
    client, eng = app_client
    r = await client.get("/api/technique/armed?slim=1")
    assert r.status_code == 200 and r.json() == []
