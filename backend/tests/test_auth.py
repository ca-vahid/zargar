"""Sign-in: Google ID token -> allow list -> session cookie; static token still works."""
import httpx
import pytest

from zargar.api.app import create_app
from zargar.auth import COOKIE, AuthError, AuthService
from zargar.engine import Engine

from .conftest import make_test_config


class Cfg:
    auth_token = ""
    google_client_id = "client-123.apps.googleusercontent.com"
    google_allowed_emails = "visper@gmail.com, Other@Example.com"
    session_secret = "unit-test-secret"
    session_days = 30


def claims(email="visper@gmail.com", verified=True):
    return {"email": email, "email_verified": verified, "name": "Vahid", "picture": "https://p/x.png",
            "aud": Cfg.google_client_id, "iss": "https://accounts.google.com"}


def svc(cfg=None, verifier=None):
    return AuthService(cfg or Cfg(), None, google_verifier=verifier or (lambda cred: claims()))


def test_allow_list_gates_google_sign_in():
    a = svc()
    user = a.sign_in_google("token")
    assert user["email"] == "visper@gmail.com" and user["provider"] == "google"
    assert a.allowed_emails() == {"visper@gmail.com", "other@example.com"}
    with pytest.raises(AuthError) as ei:
        svc(verifier=lambda c: claims(email="stranger@gmail.com")).sign_in_google("t")
    assert ei.value.status == 403
    with pytest.raises(AuthError):
        svc(verifier=lambda c: claims(verified=False)).sign_in_google("t")


def test_session_round_trip_and_live_allow_list():
    a = svc()
    tok = a.issue_session({"email": "visper@gmail.com", "name": "V", "provider": "google"})
    assert a.verify_session(tok)["email"] == "visper@gmail.com"
    assert a.verify_session(tok + "x") is None
    assert a.authenticate(cookie=tok)["email"] == "visper@gmail.com"
    assert a.authenticate(bearer=tok)["email"] == "visper@gmail.com"
    assert a.authenticate() is None

    class Narrow(Cfg):
        google_allowed_emails = "someone-else@gmail.com"
    assert AuthService(Narrow(), None, google_verifier=lambda c: claims()).verify_session(tok) is None


def test_static_token_still_works_and_open_mode():
    class Tok(Cfg):
        google_client_id = ""
        auth_token = "s3cret"
    a = AuthService(Tok(), None)
    assert a.required and not a.google_enabled
    assert a.authenticate(bearer="s3cret")["provider"] == "token"
    assert a.authenticate(query_token="s3cret")["provider"] == "token"
    assert a.authenticate(bearer="nope") is None

    class Open(Cfg):
        google_client_id = ""
    o = AuthService(Open(), None)
    assert not o.required and o.authenticate()["provider"] == "open"
    ids = [p["id"] for p in a.providers()]
    assert ids == ["google", "microsoft", "office365"]
    assert all(not p["enabled"] for p in a.providers() if p["id"] != "google")


@pytest.fixture
async def sso_client(fresh_db):
    config = make_test_config(google_client_id=Cfg.google_client_id,
                              google_allowed_emails="visper@gmail.com", session_secret="api-test-secret")
    eng = Engine(config)
    await eng.start()
    eng.auth = AuthService(config, eng.settings, google_verifier=lambda cred: claims(
        email="stranger@gmail.com" if cred == "stranger" else "visper@gmail.com"))
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await eng.stop()


async def test_api_requires_sign_in_then_cookie_session(sso_client):
    client = sso_client
    cfg = (await client.get("/api/auth/config")).json()
    assert cfg["required"] is True and cfg["googleClientId"] == Cfg.google_client_id
    assert [p["enabled"] for p in cfg["providers"]] == [True, False, False]
    assert (await client.get("/api/state")).status_code == 401
    me = (await client.get("/api/auth/me")).json()
    assert me["required"] is True and me["user"] is None

    r = await client.post("/api/auth/google", json={"credential": "stranger"})
    assert r.status_code == 403 and "not allowed" in r.json()["detail"]

    r = await client.post("/api/auth/google", json={"credential": "good"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "visper@gmail.com" and body["token"]
    assert COOKIE in r.cookies
    # the cookie now opens the API; the token works as a bearer too
    assert (await client.get("/api/state")).status_code == 200
    assert (await client.get("/api/auth/me")).json()["user"]["email"] == "visper@gmail.com"
    client.cookies.clear()
    assert (await client.get("/api/state")).status_code == 401
    assert (await client.get("/api/state", headers={"Authorization": f"Bearer {body['token']}"})).status_code == 200
    assert (await client.get("/api/state", params={"token": body["token"]})).status_code == 200


async def test_sign_in_is_rate_limited(sso_client):
    client = sso_client
    codes = []
    for _ in range(12):
        codes.append((await client.post("/api/auth/google", json={"credential": "stranger"})).status_code)
    assert codes[:10] == [403] * 10 and codes[10:] == [429, 429]


async def test_generated_session_secret_survives_restart(engine):
    """No ZARGAR_SESSION_SECRET: the generated secret is persisted (hidden) so a restart
    keeps every device signed in; it must never appear in the settings the API lists."""
    from zargar.auth import SECRET_KEY
    from .conftest import wait_for

    class NoSecret(Cfg):
        session_secret = ""
    first = AuthService(NoSecret(), engine.settings)
    tok = first.issue_session({"email": "visper@gmail.com", "name": "V", "provider": "google"})
    await wait_for(lambda: engine.settings.get(SECRET_KEY) == first.secret())
    assert SECRET_KEY not in engine.settings.all()
    # "restart": a fresh service over the same settings verifies the old cookie
    second = AuthService(NoSecret(), engine.settings)
    assert second.secret() == first.secret()
    assert second.verify_session(tok)["email"] == "visper@gmail.com"
