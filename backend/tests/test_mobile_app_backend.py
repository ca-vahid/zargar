"""Backend for the native Android (Expo) app: Expo push transport, the alerts feed, and the
client class bound to the session. No test here reaches the network - the Expo POST is stubbed."""
import datetime as dt

import httpx
import pytest

from zargar import events as ev
from zargar import push as push_mod
from zargar.alerts_feed import ALERT_EVENT_TYPES, alert_item
from zargar.api.app import create_app
from zargar.auth import AuthService, client_class
from zargar.engine import Engine
from zargar.models import Portfolio
from zargar.push import channel_for, valid_expo_token

from .conftest import make_test_config, wait_for

TOKEN_A = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaaaa]"
TOKEN_B = "ExpoPushToken[bbbbbbbbbbbbbbbbbbbbbb]"
EMAIL = "visper@gmail.com"


@pytest.fixture
async def app_client(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    app = create_app(config, eng)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, eng
    await eng.stop()


class ExpoStub:
    """Stands in for PushService._post_expo: records every batch, answers with tickets."""

    def __init__(self, svc, *, errors: dict[str, str] | None = None, fail: Exception | None = None):
        self.batches: list[list[dict]] = []
        self.errors = errors or {}
        self.fail = fail
        svc._post_expo = self          # instance attribute shadows the method

    async def __call__(self, messages: list[dict]) -> list[dict]:
        self.batches.append(messages)
        if self.fail is not None:
            raise self.fail
        return [{"status": "error", "message": "refused", "details": {"error": self.errors[m["to"]]}}
                if m["to"] in self.errors else {"status": "ok", "id": "t"} for m in messages]

    @property
    def messages(self) -> list[dict]:
        return [m for b in self.batches for m in b]


# ------------------------------------------------------------------ A: Expo push
def test_token_shape_and_channel_mapping():
    assert valid_expo_token(TOKEN_A) and valid_expo_token(TOKEN_B)
    for bad in ("", "abc", "ExponentPushToken[]", "ExponentPushToken[a b]", "FcmToken[abc]",
                "ExponentPushToken[abc", "xExponentPushToken[abc]"):
        assert not valid_expo_token(bad), bad
    assert channel_for("proposal-123") == "approvals"
    assert channel_for("card-9") == "approvals"
    assert channel_for("armed-r1") == "trades"
    assert channel_for("armed-r1", "critical") == "trades"          # a failed exit stays a trade event
    assert channel_for("halt", "critical") == "critical"
    assert channel_for("host-memory") == "critical"                 # sent at the default level
    assert channel_for("alert-r1", "critical") == "critical"
    assert channel_for("alert-r1", "warning") == "alerts"
    assert channel_for("ibkr-link", "info") == "alerts"
    assert channel_for("desk-morning") == "alerts"
    assert channel_for(None) == "alerts"


async def test_expo_register_dedupe_delete_and_validation(app_client):
    client, eng = app_client
    r = await client.post("/api/push/expo", json={"token": "not-a-token", "label": "x"})
    assert r.status_code == 400 and "Expo push token" in r.json()["detail"]
    assert (await client.post("/api/push/expo", json={"label": "x"})).status_code == 422

    r = await client.post("/api/push/expo", json={"token": TOKEN_A, "label": "Pixel"})
    assert r.status_code == 200 and r.json() == {"ok": True, "subscriptions": 1}
    r = await client.post("/api/push/expo", json={"token": TOKEN_B})          # label is optional
    assert r.json() == {"ok": True, "subscriptions": 2}
    # re-registering the same token updates the label, never duplicates
    r = await client.post("/api/push/expo", json={"token": TOKEN_A, "label": "Pixel 9"})
    assert r.json() == {"ok": True, "subscriptions": 2}
    stored = {x["token"]: x for x in eng.push.expo_subscriptions()}
    assert stored[TOKEN_A] == {"kind": "expo", "token": TOKEN_A, "endpoint": TOKEN_A, "label": "Pixel 9"}
    assert stored[TOKEN_B]["label"] == ""

    # the two transports share one list and never disturb each other
    r = await client.post("/api/push/subscribe", json={"endpoint": "https://push.example/abc",
                                                       "keys": {"p256dh": "x", "auth": "y"}, "label": "web"})
    assert r.json()["subscriptions"] == 1
    vapid = (await client.get("/api/push/vapid")).json()
    assert vapid["subscriptions"] == 1 and vapid["expo"] == 2 and vapid["publicKey"]
    r = await client.delete("/api/push/subscribe", params={"endpoint": "https://push.example/abc"})
    assert r.json()["subscriptions"] == 0 and len(eng.push.expo_subscriptions()) == 2

    r = await client.delete("/api/push/expo", params={"token": TOKEN_A})
    assert r.status_code == 200 and r.json() == {"ok": True, "subscriptions": 1}
    assert [x["token"] for x in eng.push.expo_subscriptions()] == [TOKEN_B]
    assert (await client.get("/api/push/vapid")).json()["expo"] == 1


async def test_send_reaches_expo_without_web_push(engine, monkeypatch):
    """Zero web subscriptions AND no pywebpush: the Expo token is still sent."""
    monkeypatch.setattr(push_mod, "HAVE_PUSH", False)
    svc = engine.push
    await svc.subscribe_expo(TOKEN_A, "Pixel")
    assert svc.subscriptions() == []
    stub = ExpoStub(svc)
    sent = await svc.send("Kill switch engaged", "x" * 500, url="/armed", tag="halt", level="critical")
    assert sent == 1 and len(stub.batches) == 1
    assert stub.messages == [{
        "to": TOKEN_A, "title": "Kill switch engaged", "body": "x" * 400, "priority": "high",
        "sound": "default", "channelId": "critical",
        "data": {"url": "/armed", "tag": "halt", "level": "critical"}}]
    assert push_mod.EXPO_PUSH_URL == "https://exp.host/--/api/v2/push/send"

    # channel per call site; an explicit channel wins, an unknown one falls back to the mapping
    await svc.send("? Proposal: BUY 1 AAPL", "waiting for your approval", url="/inbox", tag="proposal-p1")
    await svc.send("Zargar alert", "stale bars", tag="alert-r1", level="warning")
    await svc.send("AAPL exit FAILED", "x", tag="armed-r1", level="critical")
    await svc.send("Morning", "report", tag="desk-morning", channel="critical")
    await svc.send("Morning", "report", tag="desk-morning", channel="nope")
    assert [m["channelId"] for m in stub.messages[1:]] == ["approvals", "alerts", "trades", "critical", "alerts"]


async def test_bus_taps_push_to_expo_with_the_right_channel(engine):
    """The engine's own triggers (proposal waiting, halt, technique alert) fan out to Expo."""
    svc = engine.push
    await svc.subscribe_expo(TOKEN_A)
    stub = ExpoStub(svc)
    from zargar import bus as topics
    await wait_for(lambda: len(svc._tasks) == 3)
    engine.bus.publish(topics.PROPOSALS, {"id": "p1", "status": "pending", "side": "BUY", "qty": 1, "symbol": "AAPL"})
    engine.bus.publish(topics.TECHNIQUE, {"kind": "alert", "level": "warning", "text": "AAPL: bars stale", "runId": "r1"})
    await engine.engage_halt("test halt", source="test")
    await wait_for(lambda: len(stub.messages) >= 3)
    by_tag = {m["data"]["tag"]: m for m in stub.messages}
    assert by_tag["proposal-p1"]["channelId"] == "approvals" and by_tag["proposal-p1"]["data"]["url"] == "/inbox"
    assert by_tag["alert-r1"]["channelId"] == "alerts" and by_tag["alert-r1"]["data"]["url"] == "/armed/r1"
    assert by_tag["halt"]["channelId"] == "critical" and by_tag["halt"]["body"] == "test halt"


async def test_device_not_registered_prunes_and_other_errors_do_not(engine):
    svc = engine.push
    await svc.subscribe_expo(TOKEN_A)
    await svc.subscribe_expo(TOKEN_B)
    await svc.subscribe({"endpoint": "https://push.example/web", "keys": {}}, "web")
    stub = ExpoStub(svc, errors={TOKEN_A: "DeviceNotRegistered"})
    svc._send_web = _no_web                       # the web transport is not under test here
    assert await svc.send("t", "b", tag="test") == 1
    assert [x["token"] for x in svc.expo_subscriptions()] == [TOKEN_B]
    assert len(svc.subscriptions()) == 1          # pruning one transport leaves the other alone
    stub.errors = {TOKEN_B: "MessageRateExceeded"}
    assert await svc.send("t", "b", tag="test") == 0
    assert [x["token"] for x in svc.expo_subscriptions()] == [TOKEN_B]


async def _no_web(*a, **k) -> int:
    return 0


async def test_network_error_is_swallowed_and_batches_cap_at_100(engine):
    svc = engine.push
    await svc.subscribe_expo(TOKEN_A)
    stub = ExpoStub(svc, fail=httpx.ConnectError("no route to exp.host"))
    assert await svc.send("t", "b", tag="test") == 0          # logged, never raised
    assert len(stub.batches) == 1 and len(svc.expo_subscriptions()) == 1

    entries = [{"kind": "expo", "token": f"ExponentPushToken[{i:04d}]", "endpoint": f"ExponentPushToken[{i:04d}]",
                "label": ""} for i in range(230)]
    await engine.settings.set("mobile.push_subscriptions", entries, journal=False)
    stub = ExpoStub(svc)
    assert await svc.send("t", "b", tag="test") == 230
    assert [len(b) for b in stub.batches] == [100, 100, 30]


# ------------------------------------------------------------------ B: alerts feed
async def test_alerts_feed_newest_first_mapped_and_limited(app_client):
    client, eng = app_client
    assert (await client.get("/api/alerts")).json() == []
    j = eng.journal
    await j.append(ev.TECHNIQUE_PLAN_ERROR, {"runId": "r1", "symbol": "AAPL", "stage": "exit",
                                             "error": "exit order FAILED " + "y" * 600, "level": "critical"},
                   aggregate_type="technique_run", aggregate_id="r1")
    await j.append(ev.SETTING_CHANGED, {"key": "risk.x", "value": 1})                   # not an alert
    await j.append("TipCardAlert", {"proposalId": "p1", "symbol": "NVDA", "text": "NVDA card waits", "sent": {}})
    await j.append(ev.TIP_EXECUTION_INCIDENT, {"id": "i1", "action": "opened", "cause": "stale mark",
                                               "why": "exit fired on a stale mark", "scope": {"symbol": "TSLA"}})
    await j.append(ev.TIP_EXECUTION_INCIDENT, {"id": "i1", "action": "evidence"})       # bookkeeping: skipped
    await j.append("HostMemoryLow", {"freeGb": 0.8, "thresholdGb": 1.0})
    await j.append("ManagedPositionAttention", {"positionId": "mp1", "symbol": "MRNA", "error": "stop not working",
                                                "level": "warning", "stage": "alert"})
    await j.append(ev.BOOK_HALT_ENGAGED, {"portfolioId": "b1", "name": "Tips Practice", "reason": "daily loss 5%",
                                          "source": "auto"})
    await j.append(ev.KILL_SWITCH_ENGAGED, {"reason": "manual stop", "source": "app"})

    r = await client.get("/api/alerts")
    assert r.status_code == 200, r.text
    items = r.json()
    assert [i["kind"] for i in items] == [
        "KillSwitchEngaged", "BookHaltEngaged", "ManagedPositionAttention", "HostMemoryLow",
        "TipExecutionIncident", "TipCardAlert", "TechniquePlanError"]
    for i in items:
        assert set(i) == {"id", "ts", "kind", "level", "title", "body", "symbol", "url"}
        assert isinstance(i["id"], str) and i["level"] in ("info", "warning", "error")
        assert len(i["body"]) <= 300 and len(i["title"]) <= 120
        ts = dt.datetime.fromisoformat(i["ts"])
        assert ts.utcoffset() == dt.timedelta(0)
    assert [int(i["id"]) for i in items] == sorted((int(i["id"]) for i in items), reverse=True)
    by = {i["kind"]: i for i in items}
    assert by["KillSwitchEngaged"] | {"id": "", "ts": ""} == {
        "id": "", "ts": "", "kind": "KillSwitchEngaged", "level": "error", "title": "Kill switch engaged",
        "body": "manual stop (by app)", "symbol": None, "url": "/armed"}
    assert by["TechniquePlanError"]["symbol"] == "AAPL" and by["TechniquePlanError"]["url"] == "/armed/r1"
    assert by["TechniquePlanError"]["level"] == "error" and by["TechniquePlanError"]["body"].endswith("…")
    assert by["ManagedPositionAttention"]["level"] == "warning" and by["ManagedPositionAttention"]["symbol"] == "MRNA"
    assert by["TipCardAlert"]["level"] == "warning" and by["TipCardAlert"]["body"] == "NVDA card waits"
    assert by["TipExecutionIncident"]["symbol"] == "TSLA" and "stale mark" in by["TipExecutionIncident"]["body"]
    assert by["BookHaltEngaged"]["title"] == "Book halted: Tips Practice"
    assert "0.8 GB free" in by["HostMemoryLow"]["body"]

    two = (await client.get("/api/alerts", params={"limit": 2})).json()
    assert [i["kind"] for i in two] == ["KillSwitchEngaged", "BookHaltEngaged"]
    assert len((await client.get("/api/alerts", params={"limit": 100000})).json()) == 7     # capped, not an error


async def test_alerts_feed_fills_the_limit_past_filtered_rows_and_names_rejected_orders(app_client):
    client, eng = app_client
    pid = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    await eng.ensure_symbol("AAPL")
    await wait_for(lambda: eng.quotes.get("AAPL") is not None)
    await eng.engage_halt("halt for the test", source="test")
    r = await client.post("/api/orders", json={"portfolio_id": pid, "symbol": "AAPL", "side": "BUY", "qty": 3,
                                               "order_type": "MKT"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED_RISK", r.text
    for n in range(250):                              # a wall of non-alert incident bookkeeping on top
        await eng.journal.append(ev.TIP_EXECUTION_INCIDENT, {"id": "i1", "action": "evidence", "n": n})
    items = (await client.get("/api/alerts", params={"limit": 2})).json()
    assert [i["kind"] for i in items] == ["OrderRejected", "KillSwitchEngaged"]
    assert items[0]["symbol"] == "AAPL" and items[0]["title"] == "Order rejected: BUY 3 AAPL"
    assert items[0]["level"] == "warning" and items[0]["body"]


def test_every_feed_type_maps_to_an_item():
    now = dt.datetime(2026, 10, 12, 14, 30)                       # naive -> treated as UTC
    for t in ALERT_EVENT_TYPES:
        payload = {"action": "opened"} if t == ev.TIP_EXECUTION_INCIDENT else {}
        item = alert_item(7, now, t, payload)
        assert item is not None and item["kind"] == t and item["title"], t
        assert item["id"] == "7" and item["ts"] == "2026-10-12T14:30:00+00:00"
    assert alert_item(1, now, ev.TIP_EXECUTION_INCIDENT, {"action": "resolved"}) is None
    assert alert_item(1, now, ev.TIP_INTAKE_PAGED, {"phase": "recovered", "maxIdleSeconds": 600})["level"] == "info"
    assert alert_item(1, now, ev.TIP_INTAKE_PAGED, {"phase": "stalled", "idleSeconds": 900})["level"] == "error"


# ------------------------------------------------------------------ C: client class bound to the session
class _Req:
    def __init__(self, user=None, header=None):
        self.state = type("S", (), {})()
        if user is not None:
            self.state.user = user
        self.headers = {"x-zargar-client": header} if header else {}


def test_session_claim_round_trip_and_precedence():
    class Cfg:
        auth_token = ""
        google_client_id = "client-123.apps.googleusercontent.com"
        google_allowed_emails = EMAIL
        session_secret = "unit-test-secret"
        session_days = 30
    a = AuthService(Cfg(), None)
    user = {"email": EMAIL, "name": "V", "provider": "google"}
    assert "client" not in a.verify_session(a.issue_session(user))                  # the web flow: no claim
    assert a.verify_session(a.issue_session(user, client="phone"))["client"] == "phone"
    assert a.verify_session(a.issue_session(user, client=" Tablet "))["client"] == "tablet"
    assert "client" not in a.verify_session(a.issue_session(user, client="watch"))  # anything else is ignored

    assert client_class(_Req()) is None
    assert client_class(_Req(header="Phone")) == "phone"
    assert client_class(_Req(header="toaster")) is None
    assert client_class(_Req(user={"email": EMAIL}, header="tablet")) == "tablet"
    assert client_class(_Req(user={"email": EMAIL, "client": "phone"}, header="desktop")) == "phone"
    assert client_class(_Req(user={"email": EMAIL, "client": "desktop"}, header="phone")) == "desktop"


@pytest.fixture
async def sso(fresh_db):
    config = make_test_config(google_client_id="client-123.apps.googleusercontent.com",
                              google_allowed_emails=EMAIL, session_secret="api-test-secret")
    eng = Engine(config)
    await eng.start()
    eng.auth = AuthService(config, eng.settings, google_verifier=lambda cred: {
        "email": EMAIL, "email_verified": True, "name": "V"})
    async with eng.sf() as session:
        row = Portfolio(id="real1", name="Webull CASH", kind="live", starting_cash=10_000.0, cash=10_000.0)
        session.add(row)
        await session.commit()
    eng.positions.register_portfolio(row, venue="snaptrade")
    await eng.ensure_symbol("AAPL")
    await wait_for(lambda: eng.quotes.get("AAPL") is not None)
    app = create_app(config, eng)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, eng
    await eng.stop()


def _phone_check(body: dict):
    return next((c for c in body["risk"]["checks"] if c["name"] == "phone_entry_blocked"), None)


async def test_session_bound_phone_cannot_open_on_a_real_book_whatever_the_header_says(sso):
    client, eng = sso
    user = {"email": EMAIL, "name": "V", "provider": "google"}
    entry = {"portfolio_id": "real1", "symbol": "AAPL", "side": "BUY", "qty": 1, "order_type": "MKT"}

    def hdr(token, declared=None):
        return {"Authorization": f"Bearer {token}", **({"X-Zargar-Client": declared} if declared else {})}

    phone = eng.auth.issue_session(user, client="phone")
    plain = eng.auth.issue_session(user)
    desk = eng.auth.issue_session(user, client="desktop")

    # bound phone session: the header cannot talk its way out, with or without a value
    for declared in ("desktop", None):
        r = await client.post("/api/orders", json={**entry, "dry_run": True}, headers=hdr(phone, declared))
        assert r.status_code == 200, r.text
        assert _phone_check(r.json()) is not None and not _phone_check(r.json())["passed"]
    r = await client.post("/api/orders", json=entry, headers=hdr(phone, "desktop"))           # the real thing
    assert r.status_code == 200 and r.json()["status"] == "REJECTED_RISK", r.text
    assert "phones are exit-only on real accounts" in r.json()["rejectReason"]
    assert not _phone_check(r.json())["passed"]
    # ...and the body cannot either
    r = await client.post("/api/orders", json={**entry, "dry_run": True, "client": "desktop"}, headers=hdr(phone))
    assert not _phone_check(r.json())["passed"]

    # no claim: the header decides exactly as before
    r = await client.post("/api/orders", json={**entry, "dry_run": True}, headers=hdr(plain, "desktop"))
    assert r.status_code == 200 and _phone_check(r.json()) is None
    r = await client.post("/api/orders", json={**entry, "dry_run": True}, headers=hdr(plain))
    assert _phone_check(r.json()) is None
    r = await client.post("/api/orders", json={**entry, "dry_run": True}, headers=hdr(plain, "phone"))
    assert not _phone_check(r.json())["passed"]

    # a session bound to desktop is not downgraded by a header either (the claim always wins)
    r = await client.post("/api/orders", json={**entry, "dry_run": True}, headers=hdr(desk, "phone"))
    assert _phone_check(r.json()) is None


async def test_google_sign_in_binds_the_client_class_only_when_asked(sso):
    client, eng = sso
    r = await client.post("/api/auth/google", json={"credential": "good"})                    # the web flow
    assert r.status_code == 200 and "client" not in r.json()["user"]
    assert "client" not in eng.auth.verify_session(r.json()["token"])
    r = await client.post("/api/auth/google", json={"credential": "good", "client": "smart-fridge"})
    assert r.status_code == 200 and "client" not in eng.auth.verify_session(r.json()["token"])

    r = await client.post("/api/auth/google", json={"credential": "good", "client": "phone"})
    assert r.status_code == 200 and r.json()["user"]["client"] == "phone"
    token = r.json()["token"]
    assert eng.auth.verify_session(token)["client"] == "phone"
    client.cookies.clear()
    me = (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).json()
    assert me["user"]["client"] == "phone"
    r = await client.post("/api/orders", headers={"Authorization": f"Bearer {token}", "X-Zargar-Client": "desktop"},
                          json={"portfolio_id": "real1", "symbol": "AAPL", "side": "BUY", "qty": 1,
                                "order_type": "MKT", "dry_run": True})
    assert not _phone_check(r.json())["passed"]
