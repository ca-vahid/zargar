"""Questions for the user (2026-11-18): asked through the API, answered once, never an action by themselves."""
import datetime as dt

import httpx
import pytest

from zargar.api.app import create_app
from zargar.engine import Engine
from zargar.models import DeskQuestion

from .conftest import make_test_config


@pytest.fixture
async def app_client(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    app = create_app(config, eng)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, eng
    await eng.stop()


async def test_a_question_is_asked_listed_and_answered_once(app_client):
    client, eng = app_client
    r = await client.post("/api/questions", json={"text": "No USD at Webull. Convert CAD or skip the buy?",
                                                  "options": ["Convert", "Skip"], "detail": "AAPL buy, about $358"})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["status"] == "open" and q["options"] == ["Convert", "Skip"] and q["askedBy"] == "claude"
    assert [x["id"] for x in (await client.get("/api/questions?open_only=true")).json()] == [q["id"]]

    a = await client.post(f"/api/questions/{q['id']}/answer", json={"answer": "Skip"}, headers={"X-Zargar-Client": "phone"})
    assert a.status_code == 200 and a.json()["status"] == "answered"
    assert a.json()["answer"] == "Skip" and a.json()["answeredVia"] == "phone"
    assert (await client.get("/api/questions?open_only=true")).json() == []
    again = await client.post(f"/api/questions/{q['id']}/answer", json={"answer": "Convert"})
    assert again.status_code == 400                                   # the first answer stands
    assert (await client.get(f"/api/questions/{q['id']}")).json()["answer"] == "Skip"


async def test_bad_questions_are_refused_and_a_cancelled_one_cannot_be_answered(app_client):
    client, eng = app_client
    assert (await client.post("/api/questions", json={"text": "  "})).status_code == 400
    assert (await client.post("/api/questions", json={"text": "x", "options": ["a", "A"]})).status_code == 400
    assert (await client.post("/api/questions", json={"text": "x", "options": list("abcde")})).status_code == 400
    assert (await client.post("/api/questions", json={"text": "x", "expiresAt": "2020-01-01T00:00:00+00:00"})).status_code == 400
    q = (await client.post("/api/questions", json={"text": "Free text is fine?"})).json()
    assert (await client.post(f"/api/questions/{q['id']}/cancel")).json()["status"] == "cancelled"
    assert (await client.post(f"/api/questions/{q['id']}/answer", json={"answer": "yes"})).status_code == 400
    assert (await client.get("/api/questions/nope")).status_code == 404


async def test_an_expired_question_reads_expired_and_refuses_an_answer(app_client):
    client, eng = app_client
    q = (await client.post("/api/questions", json={"text": "Still relevant?"})).json()
    async with eng.sf() as s:
        row = await s.get(DeskQuestion, q["id"])
        row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        await s.commit()
    assert (await client.get(f"/api/questions/{q['id']}")).json()["status"] == "expired"
    assert (await client.post(f"/api/questions/{q['id']}/answer", json={"answer": "yes"})).status_code == 400
